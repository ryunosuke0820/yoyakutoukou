from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path
import sys
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts import configure_sites as cs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
MAX_RETRIES = 5
RETRY_STATUSES = {429, 500, 502, 503, 504}

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IFRAME_TAG_RE = re.compile(r"<iframe\b[^>]*>", re.IGNORECASE)


def _request_with_retry(method: str, url: str, session: requests.Session, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    last_res: requests.Response | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if res.status_code in RETRY_STATUSES:
                last_res = res
                logger.warning(f"{method} {url} returned {res.status_code} (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(1.5 * attempt)
                continue
            return res
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(f"{method} {url} failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            time.sleep(1.0 * attempt)

    if last_res is not None:
        return last_res
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request failed")


def _iter_posts(session: requests.Session, base_url: str, statuses: list[str]) -> Iterable[dict]:
    page = 1
    while True:
        res = _request_with_retry(
            "GET",
            f"{base_url}/wp-json/wp/v2/posts",
            session,
            params={
                "per_page": 100,
                "page": page,
                "context": "edit",
                "status": ",".join(statuses),
            },
        )
        if res.status_code == 400 and "rest_post_invalid_page_number" in res.text:
            break
        res.raise_for_status()
        posts = res.json()
        if not posts:
            break
        for post in posts:
            yield post
        total_pages = int(res.headers.get("X-WP-TotalPages", page))
        if page >= total_pages:
            break
        page += 1


def _has_attr(tag: str, attr: str) -> bool:
    return re.search(rf"\b{re.escape(attr)}\s*=", tag, re.IGNORECASE) is not None


def _get_attr(tag: str, attr: str) -> str | None:
    m = re.search(rf"\b{re.escape(attr)}\s*=\s*([\"'])(.*?)\1", tag, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(2)


def _set_or_replace_attr(tag: str, attr: str, value: str) -> str:
    if _has_attr(tag, attr):
        pattern = re.compile(
            rf"(\b{re.escape(attr)}\s*=\s*)([\"']).*?\2",
            flags=re.IGNORECASE | re.DOTALL,
        )
        return pattern.sub(lambda m: f'{m.group(1)}"{value}"', tag, count=1)
    return tag[:-1] + f' {attr}="{value}">'


def _ensure_attr(tag: str, attr: str, value: str) -> str:
    if _has_attr(tag, attr):
        return tag
    return tag[:-1] + f' {attr}="{value}">'


def _optimize_iframe_tag(tag: str) -> str:
    new_tag = _ensure_attr(tag, "loading", "lazy")
    new_tag = _ensure_attr(new_tag, "referrerpolicy", "strict-origin-when-cross-origin")
    return new_tag


def _optimize_img_tag(tag: str) -> str:
    cls = (_get_attr(tag, "class") or "").lower()
    is_hero = "aa-img" in cls

    new_tag = _ensure_attr(tag, "decoding", "async")

    if is_hero:
        new_tag = _set_or_replace_attr(new_tag, "loading", "eager")
        new_tag = _set_or_replace_attr(new_tag, "fetchpriority", "high")
    else:
        new_tag = _set_or_replace_attr(new_tag, "loading", "lazy")
        if not _has_attr(new_tag, "fetchpriority"):
            new_tag = _ensure_attr(new_tag, "fetchpriority", "low")

    return new_tag


def optimize_content(content: str) -> tuple[str, bool]:
    changed = False

    def iframe_repl(match: re.Match) -> str:
        nonlocal changed
        old = match.group(0)
        new = _optimize_iframe_tag(old)
        if new != old:
            changed = True
        return new

    def img_repl(match: re.Match) -> str:
        nonlocal changed
        old = match.group(0)
        new = _optimize_img_tag(old)
        if new != old:
            changed = True
        return new

    new_content = IFRAME_TAG_RE.sub(iframe_repl, content)
    new_content = IMG_TAG_RE.sub(img_repl, new_content)

    return new_content, changed


def update_site(base_url: str, statuses: list[str], apply_changes: bool, limit: int | None = None) -> None:
    session = requests.Session()
    session.auth = (cs.WP_USERNAME, cs.WP_APP_PASSWORD)

    scanned = 0
    updated = 0

    for post in _iter_posts(session, base_url, statuses=statuses):
        scanned += 1
        post_id = post.get("id")
        content_obj = post.get("content", {}) or {}
        content = content_obj.get("raw") or content_obj.get("rendered") or ""

        new_content, changed = optimize_content(content)
        if changed:
            if apply_changes:
                res = _request_with_retry(
                    "POST",
                    f"{base_url}/wp-json/wp/v2/posts/{post_id}",
                    session,
                    json={"content": new_content},
                )
                res.raise_for_status()
            updated += 1

        if scanned % 100 == 0:
            logger.info(f"{base_url}: scanned={scanned}, changed={updated}, apply={apply_changes}")

        if limit is not None and scanned >= limit:
            break

    logger.info(f"{base_url}: done scanned={scanned}, changed={updated}, apply={apply_changes}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize iframe/img loading attributes in WordPress posts.")
    parser.add_argument("--site", default="", help="Subdomain only (e.g. sd07-oneesan). Empty means all SD sites.")
    parser.add_argument("--include-main", action="store_true", help="Include main site av-kantei.com")
    parser.add_argument(
        "--status",
        default="publish,draft",
        help="Comma-separated statuses to scan (default: publish,draft)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Scan limit per site (0 means no limit)")
    parser.add_argument("--apply", action="store_true", help="Actually update posts. Default is dry-run.")
    args = parser.parse_args()

    statuses = [s.strip() for s in args.status.split(",") if s.strip()]
    if not statuses:
        statuses = ["publish", "draft"]

    targets: list[str] = []
    if args.site:
        targets.append(f"https://{args.site}.av-kantei.com")
    else:
        targets.extend([f"https://{s.subdomain}.av-kantei.com" for s in cs.SITES if s.subdomain.startswith("sd")])

    if args.include_main:
        targets.append("https://av-kantei.com")

    limit = args.limit if args.limit > 0 else None

    for base_url in targets:
        try:
            update_site(base_url=base_url, statuses=statuses, apply_changes=args.apply, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{base_url}: failed: {exc}")


if __name__ == "__main__":
    main()
