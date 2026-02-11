import argparse
import html
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv


DEFAULT_SITE_ID = "sd01-chichi"
DEFAULT_RULES_FILE = "site_theme_config.json"
PRODUCT_LABEL = "品番"
CAST_LABEL_OLD = "出演者"
CAST_LABEL_NEW = "女優名"
MAKER_LABEL_DEFAULT = "メーカー"
MIDOKORO_DEFAULT = "見どころ3選"

SITE_ALIASES = {
    "sd1": "sd01-chichi",
    "sd01": "sd01-chichi",
    "sd2": "sd02-shirouto",
    "sd02": "sd02-shirouto",
    "sd3": "sd03-gyaru",
    "sd03": "sd03-gyaru",
    "sd4": "sd04-chijo",
    "sd04": "sd04-chijo",
    "sd5": "sd05-seiso",
    "sd05": "sd05-seiso",
    "sd6": "sd06-hitozuma",
    "sd06": "sd06-hitozuma",
    "sd7": "sd07-oneesan",
    "sd07": "sd07-oneesan",
    "sd8": "sd08-jukujo",
    "sd08": "sd08-jukujo",
    "sd9": "sd09-iyashi",
    "sd09": "sd09-iyashi",
    "sd10": "sd10-otona",
}

DEFAULT_NORMALIZE_RULES = {
    "hero_callout": {
        "title": "⚠ 作品の傾向が刺さる人向け",
        "body": "好みと違う場合はリンク先の詳細情報も確認してください。",
    },
    "spec_labels": {
        "cast": CAST_LABEL_NEW,
        "maker": MAKER_LABEL_DEFAULT,
    },
    "stack_chip_text": MIDOKORO_DEFAULT,
    "title_format": "[{pid}] {title}",
}

CTA_PRIMARY_FIX_MARKER = "SD CTA primary fix"
CTA_PRIMARY_FIX_STYLE = """<style>
/* SD CTA primary fix */
body[data-site^="sd"] .aa-cta,
body[data-site^="sd"] .aa-cta-final,
.aa-wrap[data-site^="sd"] .aa-cta,
.aa-wrap[data-site^="sd"] .aa-cta-final {
  background: var(--aa-card) !important;
}
body[data-site^="sd"] .aa-btn-primary,
.aa-wrap[data-site^="sd"] .aa-btn-primary {
  background: linear-gradient(135deg, var(--aa-cta-accent), var(--aa-cta-accent2)) !important;
  border-color: transparent !important;
  color: var(--aa-cta-text) !important;
  box-shadow: 0 14px 28px color-mix(in srgb, var(--aa-cta-accent) 35%, transparent), var(--aa-btn-glow) !important;
}
</style>"""


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value


def _normalize_site_id(site_id: str) -> str:
    normalized = str(site_id or "").strip().lower()
    if not normalized:
        return DEFAULT_SITE_ID
    if normalized in SITE_ALIASES:
        return SITE_ALIASES[normalized]
    if normalized.startswith("sd"):
        prefix = normalized.split("-", 1)[0]
        if prefix in SITE_ALIASES:
            return SITE_ALIASES[prefix]
    return normalized


def _request_with_retry(
    method: str,
    url: str,
    *,
    attempts: int = 4,
    sleep_sec: float = 1.5,
    **kwargs,
) -> requests.Response:
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504) and i < attempts:
                time.sleep(sleep_sec * i)
                continue
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if i < attempts:
                time.sleep(sleep_sec * i)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("request failed")


def _extract_pid(post: dict) -> str:
    meta = post.get("meta") or {}
    if isinstance(meta, dict):
        value = str(meta.get("fanza_product_id", "")).strip()
        if value:
            return value.lower()

    content = ((post.get("content") or {}).get("raw") or "")
    match = re.search(
        rf'<div class="aa-th" role="cell">\s*{PRODUCT_LABEL}\s*</div>\s*<div class="aa-td" role="cell">\s*([^<\s]+)\s*</div>',
        content,
        re.S,
    )
    if match:
        return match.group(1).strip().lower()

    slug = str(post.get("slug") or "").strip().lower()
    if slug.startswith("video-") and len(slug) > 6:
        return slug[6:]

    match = re.search(r"([a-z0-9_]+(?:-[a-z0-9_]+)*\d)$", slug)
    return match.group(1).lower() if match else ""


def _strip_existing_pid_tokens(title: str, pid: str) -> str:
    text = str(title or "").strip()
    if not pid:
        return text

    pid_esc = re.escape(pid)
    patterns = [
        rf"^\s*[\[\u3010]?\s*{pid_esc}\s*[\]\u3011]?\s*[\|｜\-:：]?\s*",
        rf"\s*[\|｜\-:：]?\s*[\[\u3010]?\s*{pid_esc}\s*[\]\u3011]?\s*$",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.I)
    return text.strip(" -|｜:\t\n\r")


def _normalize_title(title: str, pid: str, title_format: str) -> str:
    plain = re.sub(r"<[^>]+>", "", str(title or "")).strip()
    if not pid:
        return plain
    core = _strip_existing_pid_tokens(plain, pid)
    if not core:
        core = plain
    fmt = title_format if "{pid}" in title_format and "{title}" in title_format else "[{pid}] {title}"
    return fmt.format(pid=pid, title=core).strip()


def _build_search_link(text: str) -> str:
    keyword = str(text or "").strip()
    if not keyword:
        return "N/A"
    q = quote_plus(keyword)
    return f'<a class="aa-spec-link" href="/?s={q}">{html.escape(keyword)}</a>'


def _split_names(text: str) -> list[str]:
    cleaned = re.sub(r"<[^>]+>", "", str(text or "")).strip()
    if not cleaned or cleaned.upper() == "N/A":
        return []
    parts = re.split(r"\s*/\s*|\s*、\s*|\s*,\s*", cleaned)
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = part.strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _load_rules(site_id: str, rules_file: str) -> dict:
    path = Path(rules_file)
    if not path.exists():
        raise RuntimeError(f"Rules file not found: {rules_file}")
    data = json.loads(path.read_text(encoding="utf-8"))
    site_cfg = data.get(site_id, {}) if isinstance(data, dict) else {}
    site_rules = site_cfg.get("normalize", {}) if isinstance(site_cfg, dict) else {}

    rules = json.loads(json.dumps(DEFAULT_NORMALIZE_RULES))
    for key in ("hero_callout", "spec_labels"):
        extra = site_rules.get(key, {})
        if isinstance(extra, dict):
            rules[key].update(extra)
    for key in ("stack_chip_text", "title_format"):
        value = site_rules.get(key)
        if isinstance(value, str) and value.strip():
            rules[key] = value.strip()
    return rules


def _build_midokoro_block(text: str) -> str:
    label = html.escape(text or MIDOKORO_DEFAULT)
    return (
        '<div style="margin:0 0 14px;">'
        '<span class="aa-chip" style="font-size:22px;line-height:1.2;font-weight:800;padding:10px 16px;">'
        f"{label}"
        "</span></div>"
    )


def _normalize_spec_block(spec_block: str, cast_label: str, maker_label: str) -> str:
    cast_candidates = {cast_label.strip(), CAST_LABEL_OLD, CAST_LABEL_NEW}
    cast_candidates = {c for c in cast_candidates if c}
    maker_candidates = {maker_label.strip(), MAKER_LABEL_DEFAULT}
    maker_candidates = {c for c in maker_candidates if c}

    row_pattern = re.compile(
        r'(<div class="aa-tr" role="row">\s*<div class="aa-th" role="cell">)([\s\S]*?)(</div>\s*<div class="aa-td" role="cell">)([\s\S]*?)(</div>\s*</div>)',
        re.S,
    )
    row_idx = -1
    cast_done = False
    maker_done = False

    def _norm_label_text(text: str) -> str:
        return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", text or ""))

    def replace_row(match: re.Match) -> str:
        nonlocal row_idx, cast_done, maker_done
        row_idx += 1
        th_raw = match.group(2)
        td_raw = match.group(4)
        th_norm = _norm_label_text(th_raw)

        cast_hit = th_norm in cast_candidates or "出演" in th_norm or "女優" in th_norm
        maker_hit = th_norm in maker_candidates or "メーカー" in th_norm
        if not cast_done and not cast_hit and row_idx == 1:
            cast_hit = True
        if not maker_done and not maker_hit and row_idx == 2:
            maker_hit = True

        if not cast_done and cast_hit:
            names = _split_names(td_raw)
            linked = " / ".join(_build_search_link(n) for n in names) if names else "N/A"
            cast_done = True
            return f"{match.group(1)}{cast_label}{match.group(3)}{linked}{match.group(5)}"

        if not maker_done and maker_hit:
            maker_value = re.sub(r"<[^>]+>", "", td_raw).strip()
            linked = _build_search_link(maker_value) if maker_value else "N/A"
            maker_done = True
            return f"{match.group(1)}{maker_label}{match.group(3)}{linked}{match.group(5)}"

        return match.group(0)

    return row_pattern.sub(replace_row, spec_block)


def _normalize_content(raw: str, rules: dict) -> tuple[str, bool]:
    original = raw
    callout_title = rules["hero_callout"]["title"]
    callout_body = rules["hero_callout"]["body"]
    cast_label = rules["spec_labels"]["cast"]
    maker_label = rules["spec_labels"]["maker"]
    midokoro_block = _build_midokoro_block(rules["stack_chip_text"])

    raw = re.sub(
        r'(<div class="aa-callout-title">)[\s\S]*?(</div>)',
        rf"\1{callout_title}\2",
        raw,
        count=1,
    )
    raw = re.sub(
        r'(<div class="aa-callout-body">)[\s\S]*?(</div>)',
        rf"\1{callout_body}\2",
        raw,
        count=1,
    )
    raw = re.sub(r'\s*<h1 class="aa-title">[\s\S]*?</h1>\s*', "\n", raw, count=1)
    raw = re.sub(r'\s*<header class="aa-hero-head">[\s\S]*?</header>\s*', "\n", raw, count=1)

    spec_iter = list(re.finditer(r'<section class="aa-card aa-spec"[\s\S]*?</section>', raw, re.S))
    spec_block = ""
    if spec_iter:
        spec_block = _normalize_spec_block(spec_iter[0].group(0), cast_label=cast_label, maker_label=maker_label)
        raw = re.sub(r'\s*<section class="aa-card aa-spec"[\s\S]*?</section>\s*', "\n", raw, flags=re.S)

    if spec_block:
        hero_match = re.search(r'<section class="aa-card aa-hero"[\s\S]*?</section>', raw, re.S)
        if hero_match:
            hero = hero_match.group(0)
            if 'class="aa-card aa-spec"' not in hero:
                cta_match = re.search(
                    r'<div class="aa-cta aa-cta-top">[\s\S]*?</div>\s*<div class="aa-extline">[\s\S]*?</div>\s*</div>',
                    hero,
                    re.S,
                )
                if cta_match:
                    insert_at = cta_match.end()
                    hero = hero[:insert_at] + "\n\n" + spec_block + "\n\n" + hero[insert_at:]
                else:
                    hero = hero[:-10] + "\n\n" + spec_block + "\n\n</section>"
                raw = raw[:hero_match.start()] + hero + raw[hero_match.end():]

    stack_match = re.search(r'<section class="aa-stack"[^>]*>', raw)
    if stack_match:
        cleaned, n = re.subn(
            r'(<section class="aa-stack"[^>]*>)\s*(?:<div[^>]*>\s*<span class="aa-chip"[^>]*>[\s\S]*?</span>\s*</div>\s*)+',
            r"\1" + "\n  " + midokoro_block + "\n",
            raw,
            count=1,
            flags=re.S,
        )
        if n > 0:
            raw = cleaned
        else:
            raw = raw[:stack_match.end()] + "\n  " + midokoro_block + "\n" + raw[stack_match.end():]

    # Ensure CTA primary stays themed (fix for theme/plugin overrides).
    if CTA_PRIMARY_FIX_MARKER not in raw:
        raw = raw.rstrip() + "\n\n" + CTA_PRIMARY_FIX_STYLE + "\n"

    return raw, raw != original


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize SD posts to unified layout policy")
    parser.add_argument("--site-id", default=DEFAULT_SITE_ID, help="Target site id (e.g. sd01-chichi)")
    parser.add_argument("--base-url", default="", help="WordPress site URL. Defaults to https://{site-id}.av-kantei.com")
    parser.add_argument("--rules-file", default=DEFAULT_RULES_FILE, help="Path to normalize rules JSON")
    parser.add_argument("--status", default="publish")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    site_id = _normalize_site_id(args.site_id)
    base_url = args.base_url.strip().rstrip("/") or f"https://{site_id}.av-kantei.com"

    rules = _load_rules(site_id, args.rules_file)
    title_format = str(rules.get("title_format") or "[{pid}] {title}")

    load_dotenv(".env")
    user = _required_env("WP_USERNAME")
    app = _required_env("WP_APP_PASSWORD")
    auth = (user, app)

    scanned = 0
    updated = 0
    failed = 0
    page = 1

    while page <= max(1, args.max_pages):
        params = {
            "context": "edit",
            "status": args.status,
            "per_page": max(1, min(100, args.per_page)),
            "page": page,
            "_fields": "id,slug,title,meta,content",
        }
        res = _request_with_retry(
            "GET",
            f"{base_url}/wp-json/wp/v2/posts",
            params=params,
            auth=auth,
            timeout=30,
        )
        if res.status_code == 400:
            break
        res.raise_for_status()
        posts = res.json() or []
        if not posts:
            break

        for post in posts:
            scanned += 1
            pid = _extract_pid(post)
            raw = ((post.get("content") or {}).get("raw") or "")
            if not raw:
                continue

            new_raw, changed_content = _normalize_content(raw, rules)
            title_obj = post.get("title") or {}
            raw_title = title_obj.get("raw") if isinstance(title_obj, dict) else str(title_obj)
            new_title = _normalize_title(raw_title or "", pid, title_format=title_format)
            changed_title = new_title != (raw_title or "")

            if not changed_content and not changed_title:
                continue

            updated += 1
            if args.dry_run:
                print(
                    f"[dry-run] site={site_id} id={post.get('id')} slug={post.get('slug')} "
                    f"pid={pid} content={changed_content} title={changed_title}"
                )
                continue

            payload = {}
            if changed_content:
                payload["content"] = new_raw
            if changed_title:
                payload["title"] = new_title

            try:
                req = _request_with_retry(
                    "POST",
                    f"{base_url}/wp-json/wp/v2/posts/{post['id']}",
                    json=payload,
                    auth=auth,
                    timeout=30,
                )
                req.raise_for_status()
                print(
                    f"updated site={site_id} id={post.get('id')} slug={post.get('slug')} "
                    f"pid={pid} content={changed_content} title={changed_title}"
                )
            except requests.RequestException as exc:
                failed += 1
                print(
                    f"update_failed site={site_id} id={post.get('id')} slug={post.get('slug')} "
                    f"pid={pid} error={exc}"
                )

        page += 1

    print(f"done site={site_id} scanned={scanned} updated={updated} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
