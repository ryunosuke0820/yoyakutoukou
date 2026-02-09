"""
Fill missing product IDs ("品番") for SD sites.

- If spec table has a 品番 row with an empty value, fill it.
- If spec table has no 品番 row, append one into the spec table.
- Product ID source: WPClient.extract_fanza_id (meta/slug/content/title fallback).
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from scripts.configure_sites import SITES, WP_APP_PASSWORD, WP_USERNAME
from src.clients.wordpress import WPClient

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


PRODUCT_LABEL = "\u54c1\u756a"  # 品番
SPEC_MARKER = 'class="aa-card aa-spec"'
TABLE_MARKER = 'class="aa-table"'
NOTE_MARKER = 'class="aa-muted aa-spec-note"'
PRODUCT_ROW_RE = re.compile(
    r'(<div class="aa-th" role="cell">\s*' + PRODUCT_LABEL + r'\s*</div>\s*<div class="aa-td" role="cell">\s*)([^<]*)(\s*</div>)',
    re.S,
)
EMPTY_VALUES = {"", "N/A", "n/a", "\u672a\u8a2d\u5b9a", "-", "\u306a\u3057", "&nbsp;"}


def is_empty_value(value: str) -> bool:
    return value.strip() in EMPTY_VALUES


def make_product_row(product_id: str) -> str:
    return (
        '            <div class="aa-tr" role="row">\n'
        f'                <div class="aa-th" role="cell">{PRODUCT_LABEL}</div>\n'
        f'                <div class="aa-td" role="cell">{product_id}</div>\n'
        "            </div>\n"
    )


def _find_spec_section_bounds(html: str) -> tuple[int, int] | None:
    spec_start = html.find(SPEC_MARKER)
    if spec_start == -1:
        return None
    # Scope to this spec section for safer insertion.
    spec_end = html.find("</section>", spec_start)
    if spec_end == -1:
        spec_end = len(html)
    return spec_start, spec_end


def fill_or_insert_product_id(html: str, product_id: str) -> tuple[str, str]:
    """
    Returns: (new_html, action)
    action in {"unchanged", "filled", "inserted", "skip_no_spec", "skip_no_table"}
    """
    if not product_id:
        return html, "unchanged"

    # 1) If 品番 row exists, fill only when empty.
    m = PRODUCT_ROW_RE.search(html)
    if m:
        current = (m.group(2) or "").strip()
        if not is_empty_value(current):
            return html, "unchanged"
        new_html = PRODUCT_ROW_RE.sub(r"\1" + product_id + r"\3", html, count=1)
        return new_html, "filled"

    # 2) Insert 品番 row into spec table.
    bounds = _find_spec_section_bounds(html)
    if not bounds:
        return html, "skip_no_spec"
    spec_start, spec_end = bounds
    spec_html = html[spec_start:spec_end]

    table_idx = spec_html.find(TABLE_MARKER)
    if table_idx == -1:
        return html, "skip_no_table"

    note_idx = spec_html.find(NOTE_MARKER, table_idx)
    if note_idx == -1:
        # Fallback: insert before </details> (best effort).
        details_end = spec_html.find("</details>", table_idx)
        if details_end == -1:
            return html, "skip_no_table"
        insert_anchor = spec_html.rfind("</div>", table_idx, details_end)
    else:
        insert_anchor = spec_html.rfind("</div>", table_idx, note_idx)

    if insert_anchor == -1:
        return html, "skip_no_table"

    row = make_product_row(product_id)
    new_spec = spec_html[:insert_anchor] + row + spec_html[insert_anchor:]
    return html[:spec_start] + new_spec + html[spec_end:], "inserted"


def run_for_site(subdomain: str, max_pages: int, dry_run: bool) -> dict[str, int]:
    base_url = f"https://{subdomain}.av-kantei.com"
    wp = WPClient(base_url, WP_USERNAME, WP_APP_PASSWORD)
    stats = {
        "scanned": 0,
        "updated": 0,
        "filled": 0,
        "inserted": 0,
        "skip_no_id": 0,
        "skip_no_spec": 0,
        "skip_no_table": 0,
    }

    for post in wp.iter_posts(
        status="publish",
        per_page=100,
        max_pages=max_pages,
        fields="id,slug,title,excerpt,content,meta",
        context="edit",
    ):
        stats["scanned"] += 1
        post_id = int(post.get("id", 0))
        content_obj = post.get("content", {}) or {}
        content = content_obj.get("raw") or content_obj.get("rendered") or ""
        if not content:
            continue

        fanza_id = wp.extract_fanza_id(post)
        if not fanza_id:
            stats["skip_no_id"] += 1
            continue

        new_content, action = fill_or_insert_product_id(content, fanza_id)
        if action == "unchanged":
            continue
        if action == "skip_no_spec":
            stats["skip_no_spec"] += 1
            continue
        if action == "skip_no_table":
            stats["skip_no_table"] += 1
            continue

        if action == "filled":
            stats["filled"] += 1
        elif action == "inserted":
            stats["inserted"] += 1

        if dry_run:
            stats["updated"] += 1
            logger.info(f"[dry-run] update post id={post_id} action={action} pid={fanza_id}")
            continue

        wp.update_post(post_id, {"content": new_content})
        stats["updated"] += 1
        logger.info(f"updated post id={post_id} action={action} pid={fanza_id}")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill missing SD product IDs (品番) in existing posts")
    parser.add_argument("--subdomains", type=str, default="all", help="comma-separated list or 'all'")
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.subdomains == "all":
        subdomains = [s.subdomain for s in SITES if s.subdomain.startswith("sd")]
    else:
        subdomains = [s.strip() for s in args.subdomains.split(",") if s.strip()]

    if not subdomains:
        logger.error("No target subdomains.")
        return

    for subdomain in subdomains:
        logger.info(f"target: {subdomain}")
        stats = run_for_site(subdomain, max_pages=args.max_pages, dry_run=args.dry_run)
        logger.info(
            f"{subdomain}: scanned={stats['scanned']}, updated={stats['updated']}, "
            f"filled={stats['filled']}, inserted={stats['inserted']}, "
            f"skip_no_id={stats['skip_no_id']}, skip_no_spec={stats['skip_no_spec']}, "
            f"skip_no_table={stats['skip_no_table']}"
        )


if __name__ == "__main__":
    main()
