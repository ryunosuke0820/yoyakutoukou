from __future__ import annotations

import logging
import re
import time
from typing import Iterable
import urllib.parse

import requests

from pathlib import Path
import sys

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts import configure_sites as cs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
MAX_RETRIES = 5
RETRY_STATUSES = {429, 500, 502, 503, 504}

NEW_SUBLINE_1 = (
    "\u203b\u672c\u30da\u30fc\u30b8\u306f\u6210\u4eba\u5411\u3051\u5185\u5bb9\u3092\u542b\u307f\u307e\u3059\u3002"
    "18\u6b73\u672a\u6e80\u306e\u65b9\u306f\u95b2\u89a7\u3067\u304d\u307e\u305b\u3093\u3002"
)
NEW_SUBLINE_2 = "\u203b\u5f53\u30b5\u30a4\u30c8\u306f\u30a2\u30d5\u30a3\u30ea\u30a8\u30a4\u30c8\u5e83\u544a\u3092\u5229\u7528\u3057\u3066\u3044\u307e\u3059\u3002"

SUBCARD_RE = re.compile(r'(<div class="aa-cta-subcard"[^>]*>)(.*?)(</div>)', re.S)


def _replace_subcard(content: str) -> str | None:
    def _repl(match: re.Match) -> str:
        inner = (
            f"\n        <div class=\"aa-subline\">{NEW_SUBLINE_1}</div>"
            f"\n        <div class=\"aa-subline\">{NEW_SUBLINE_2}</div>\n      "
        )
        return match.group(1) + inner + match.group(3)

    new_content, n = SUBCARD_RE.subn(_repl, content, count=1)
    if n == 0:
        return None
    if new_content == content:
        return None
    return new_content


def _request_with_retry(method: str, url: str, session: requests.Session, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    last_res: requests.Response | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if res.status_code in RETRY_STATUSES:
                last_res = res
                logger.warning(
                    f"{method} {url} returned {res.status_code} (attempt {attempt}/{MAX_RETRIES})"
                )
                time.sleep(2.0 * attempt)
                continue
            return res
        except Exception as exc:
            last_exc = exc
            logger.warning(f"{method} {url} failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            time.sleep(1.0 * attempt)
    if last_res is not None:
        return last_res
    if last_exc:
        raise last_exc
    raise RuntimeError("request failed")


def _iter_posts(session: requests.Session, base_url: str, search: str | None = None) -> Iterable[dict]:
    page = 1
    while True:
        url = f"{base_url}/wp-json/wp/v2/posts"
        params = {"per_page": 100, "page": page, "context": "edit"}
        if search:
            params["search"] = search
        res = _request_with_retry("GET", url, session, params=params)
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


def update_site(subdomain: str, search: str | None = None) -> None:
    base_url = f"https://{subdomain}.av-kantei.com"
    session = requests.Session()
    session.auth = (cs.WP_USERNAME, cs.WP_APP_PASSWORD)

    updated = 0
    checked = 0
    for post in _iter_posts(session, base_url, search=search):
        checked += 1
        post_id = post.get("id")
        content_obj = post.get("content", {}) or {}
        content = content_obj.get("raw") or content_obj.get("rendered") or ""
        new_content = _replace_subcard(content)
        if not new_content:
            continue
        update_url = f"{base_url}/wp-json/wp/v2/posts/{post_id}"
        res = _request_with_retry("POST", update_url, session, json={"content": new_content})
        res.raise_for_status()
        updated += 1
        if updated % 20 == 0:
            logger.info(f"{subdomain}: updated {updated} posts so far")

    logger.info(f"{subdomain}: checked {checked}, updated {updated}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Update hero CTA sublines across posts.")
    parser.add_argument("--site", default="", help="Target single subdomain (e.g., sd07-oneesan)")
    default_search = "\u4f1a\u54e1\u767b\u9332\u306a\u3057"
    parser.add_argument(
        "--search",
        default=default_search,
        help="WordPress search query to limit posts (default: kaiin-touroku-nashi)",
    )
    args = parser.parse_args()

    if args.site:
        targets = [args.site]
    else:
        targets = [s.subdomain for s in cs.SITES if s.subdomain.startswith("sd")]
    for subdomain in targets:
        try:
            update_site(subdomain, search=args.search if args.search else None)
        except Exception as exc:
            logger.error(f"{subdomain}: failed {exc}")


if __name__ == "__main__":
    main()
