import argparse
import os
import re
import time
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv


CALLOUT_TITLE = "\u26a0 \u5de8\u4e73\u304c\u5927\u597d\u304d\u306a\u4eba\u5411\u3051"
CALLOUT_BODY = "\u30dc\u30ea\u30e5\u30fc\u30e0\u611f\u306e\u3042\u308b\u80f8\u304c\u597d\u304d\u306a\u4eba\u307b\u3069\u30cf\u30de\u308a\u3084\u3059\u3044\u4e00\u672c\u3067\u3059\u3002"
MIDOKORO_TEXT = "\u898b\u3069\u3053\u308d3\u9078"
CAST_LABEL = "\u5973\u512a\u540d"
CAST_LABEL_OLD = "\u51fa\u6f14\u8005"
MAKER_LABEL = "\u30e1\u30fc\u30ab\u30fc"
PRODUCT_LABEL = "\u54c1\u756a"

MIDOKORO_BLOCK = (
    '<div style="margin:0 0 14px;">'
    '<span class="aa-chip" style="font-size:22px;line-height:1.2;font-weight:800;padding:10px 16px;">'
    f'{MIDOKORO_TEXT}'
    '</span></div>'
)


def _required_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def _request_with_retry(method: str, url: str, *, attempts: int = 4, sleep_sec: float = 1.5, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                if i < attempts:
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
        v = str(meta.get("fanza_product_id", "")).strip()
        if v:
            return v.lower()

    content = ((post.get("content") or {}).get("raw") or "")
    m = re.search(
        rf'<div class="aa-th" role="cell">\s*{PRODUCT_LABEL}\s*</div>\s*<div class="aa-td" role="cell">\s*([^<\s]+)\s*</div>',
        content,
        re.S,
    )
    if m:
        return m.group(1).strip().lower()

    slug = str(post.get("slug") or "").strip().lower()
    if slug.startswith("video-") and len(slug) > 6:
        return slug[6:]

    m = re.search(r'([a-z0-9_]+(?:-[a-z0-9_]+)*\d)$', slug)
    return m.group(1).lower() if m else ""


def _normalize_title(title: str, pid: str) -> str:
    t = re.sub(r"<[^>]+>", "", str(title or "")).strip()
    if not pid:
        return t
    t = re.sub(rf'\s*\[?{re.escape(pid)}\]?\s*$', '', t, flags=re.I)
    t = re.sub(rf'\s*[\|\-\?\uFF5C\uFF0D\uFF1F\u3010\[]\s*{re.escape(pid)}\s*[\]\u3011]?\s*$', '', t, flags=re.I)
    t = t.strip(" -|?\t\n\r")
    return f"{t} [{pid}]"


def _build_search_link(text: str) -> str:
    q = quote_plus(text.strip())
    return f'<a href="/?s={q}" style="color:#1d4ed8;text-decoration:underline;">{text}</a>'


def _split_names(text: str) -> list[str]:
    s = re.sub(r"<[^>]+>", "", text or "").strip()
    if not s or s.upper() == "N/A":
        return []
    parts = re.split(r"\s*/\s*|\s*\u3001\s*|\s*,\s*", s)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        v = p.strip()
        if not v:
            continue
        k = v.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


def _normalize_spec_block(spec_block: str) -> str:
    spec_block = re.sub(
        rf'(<div class="aa-th" role="cell">)\s*{CAST_LABEL_OLD}\s*(</div>)',
        rf'\1{CAST_LABEL}\2',
        spec_block,
        count=1,
    )

    def replace_actress_row(m: re.Match) -> str:
        value = m.group(4)
        names = _split_names(value)
        if names:
            linked = " / ".join(_build_search_link(n) for n in names)
        else:
            linked = '<span style="color:#1d4ed8;">N/A</span>'
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{linked}{m.group(5)}"

    row_pat = re.compile(
        rf'(<div class="aa-th" role="cell">\s*)({CAST_LABEL}|{CAST_LABEL_OLD})(\s*</div>\s*<div class="aa-td" role="cell">)([\s\S]*?)(</div>)',
        re.S,
    )
    spec_block = row_pat.sub(replace_actress_row, spec_block, count=1)

    def replace_maker_row(m: re.Match) -> str:
        value = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        linked = _build_search_link(value) if value else '<span style="color:#1d4ed8;">N/A</span>'
        return f"{m.group(1)}{linked}{m.group(3)}"

    maker_pat = re.compile(
        rf'(<div class="aa-th" role="cell">\s*{MAKER_LABEL}\s*</div>\s*<div class="aa-td" role="cell">)([\s\S]*?)(</div>)',
        re.S,
    )
    spec_block = maker_pat.sub(replace_maker_row, spec_block, count=1)

    return spec_block


def _normalize_content(raw: str) -> tuple[str, bool]:
    original = raw

    raw = re.sub(
        r'(<div class="aa-callout-title">)[\s\S]*?(</div>)',
        rf'\1{CALLOUT_TITLE}\2',
        raw,
        count=1,
    )
    raw = re.sub(
        r'(<div class="aa-callout-body">)[\s\S]*?(</div>)',
        rf'\1{CALLOUT_BODY}\2',
        raw,
        count=1,
    )

    raw = re.sub(r'\s*<h1 class="aa-title">[\s\S]*?</h1>\s*', '\n', raw, count=1)
    raw = re.sub(r'\s*<header class="aa-hero-head">[\s\S]*?</header>\s*', '\n', raw, count=1)

    spec_match = re.search(r'<section class="aa-card aa-spec"[\s\S]*?</section>', raw, re.S)
    spec_block = spec_match.group(0) if spec_match else ""
    if spec_block:
        spec_block = _normalize_spec_block(spec_block)
        raw = re.sub(r'\s*<section class="aa-card aa-spec"[\s\S]*?</section>\s*', '\n', raw, flags=re.S)

    if spec_block:
        hero_match = re.search(r'<section class="aa-card aa-hero"[\s\S]*?</section>', raw, re.S)
        if hero_match:
            hero = hero_match.group(0)
            if 'class="aa-card aa-spec"' not in hero:
                cta_match = re.search(r'<div class="aa-cta aa-cta-top">[\s\S]*?</div>\s*<div class="aa-extline">[\s\S]*?</div>\s*</div>', hero, re.S)
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
            r'\1' + "\n  " + MIDOKORO_BLOCK + "\n",
            raw,
            count=1,
            flags=re.S,
        )
        if n > 0:
            raw = cleaned
        else:
            raw = raw[:stack_match.end()] + "\n  " + MIDOKORO_BLOCK + "\n" + raw[stack_match.end():]

    return raw, raw != original


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize all SD01 posts to the latest layout policy")
    parser.add_argument("--base-url", default="https://sd01-chichi.av-kantei.com")
    parser.add_argument("--status", default="publish")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(".env")
    user = _required_env("WP_USERNAME")
    app = _required_env("WP_APP_PASSWORD")
    auth = (user, app)
    base = args.base_url.rstrip("/")

    page = 1
    scanned = 0
    updated = 0

    while page <= max(1, args.max_pages):
        params = {
            "context": "edit",
            "status": args.status,
            "per_page": max(1, min(100, args.per_page)),
            "page": page,
            "_fields": "id,slug,title,meta,content",
        }
        r = _request_with_retry("GET", f"{base}/wp-json/wp/v2/posts", params=params, auth=auth, timeout=30)
        if r.status_code == 400:
            break
        r.raise_for_status()
        posts = r.json() or []
        if not posts:
            break

        for p in posts:
            scanned += 1
            pid = _extract_pid(p)
            raw = ((p.get("content") or {}).get("raw") or "")
            if not raw:
                continue

            new_raw, changed_content = _normalize_content(raw)
            title_obj = p.get("title") or {}
            raw_title = title_obj.get("raw") if isinstance(title_obj, dict) else str(title_obj)
            new_title = _normalize_title(raw_title or "", pid)
            changed_title = new_title != (raw_title or "")

            if not changed_content and not changed_title:
                continue

            updated += 1
            if args.dry_run:
                print(f"[dry-run] id={p.get('id')} slug={p.get('slug')} pid={pid} content={changed_content} title={changed_title}")
                continue

            payload = {}
            if changed_content:
                payload["content"] = new_raw
            if changed_title:
                payload["title"] = new_title

            try:
                u = _request_with_retry("POST", f"{base}/wp-json/wp/v2/posts/{p['id']}", json=payload, auth=auth, timeout=30)
                u.raise_for_status()
                print(f"updated id={p.get('id')} slug={p.get('slug')} pid={pid} content={changed_content} title={changed_title}")
            except requests.RequestException as exc:
                print(f"update_failed id={p.get('id')} slug={p.get('slug')} pid={pid} error={exc}")

        page += 1

    print(f"done scanned={scanned} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
