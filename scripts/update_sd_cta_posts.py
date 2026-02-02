"""
SD????????????CTA/?????????????
- ??CTA??
- ??????????CTA???????????
- ????????????????????????
- ??????CTA??
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

from src.core.config import get_config
from src.clients.wordpress import WPClient
from scripts.configure_sites import SITES

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _replace_label_in_section(html: str, section_class: str, label: str) -> tuple[str, int]:
    pattern = re.compile(
        rf'(<section class="[^"]*{re.escape(section_class)}[^"]*"[\s\S]*?<span class="aa-btn-inner">)([^<]*)(</span>)',
        re.S,
    )
    def _repl(m: re.Match) -> str:
        return f"{m.group(1)}{label}{m.group(3)}"
    return pattern.subn(_repl, html, count=1)


def _replace_label_by_aria(html: str, aria_label: str, label: str) -> tuple[str, int]:
    pattern = re.compile(
        rf'(aria-label="{re.escape(aria_label)}"[\s\S]*?<span class="aa-btn-inner">)([^<]*)(</span>)',
        re.S,
    )
    def _repl(m: re.Match) -> str:
        return f"{m.group(1)}{label}{m.group(3)}"
    return pattern.subn(_repl, html, count=1)


def _repair_cta_anchor_by_scope(
    html: str,
    scope_token: str,
    aria_label: str,
    label: str,
    default_class: str,
) -> tuple[str, int]:
    scope_idx = html.find(scope_token)
    if scope_idx == -1:
        return html, 0
    a_start = html.find("<a", scope_idx)
    if a_start == -1:
        return html, 0
    a_end = html.find("</a>", a_start)
    if a_end == -1:
        return html, 0

    anchor_block = html[a_start : a_end + len("</a>")]
    if "\\1" not in anchor_block and "aa-btn-inner" in anchor_block:
        return html, 0

    href_match = re.search(r'href="([^"]+)"', anchor_block)
    href = href_match.group(1) if href_match else "#"

    anchor = (
        f'<a class="{default_class}" href="{href}" rel="nofollow noopener" target="_blank" '
        f'aria-label="{aria_label}">\\n'
        f'  <span class="aa-btn-inner">{label}</span>\\n'
        f'</a>'
    )

    new_html = html[:a_start] + anchor + html[a_end + len("</a>") :]
    return new_html, 1


def _move_final_cta_below_video(html: str) -> tuple[str, int]:
    # Find final CTA block
    final_match = re.search(
        r'<!-- I\. Final CTA -->\s*<section class="aa-card aa-cta aa-cta-final"[\s\S]*?</section>',
        html,
        re.S,
    )
    if not final_match:
        final_match = re.search(
            r'<section class="aa-card aa-cta aa-cta-final"[\s\S]*?</section>',
            html,
            re.S,
        )
    if not final_match:
        return html, 0

    final_block = final_match.group(0)
    html = html[: final_match.start()] + html[final_match.end() :]

    # Insert after video block if iframe exists
    iframe_idx = html.find("<iframe")
    if iframe_idx == -1:
        # put it back where it was removed (end of content)
        return html + "\n\n" + final_block + "\n", 1

    # try to find the closing outer div after iframe
    outer_end = html.find("</div>", iframe_idx)
    if outer_end == -1:
        return html + "\n\n" + final_block + "\n", 1

    # insert after the next closing div to close the video container
    outer_end = html.find("</div>", outer_end + 6)
    if outer_end == -1:
        return html + "\n\n" + final_block + "\n", 1

    insert_at = outer_end + len("</div>")
    html = html[:insert_at] + "\n\n" + final_block + "\n\n" + html[insert_at:]
    return html, 1


def update_content(html: str, site_id: str, primary_label: str, secondary_label: str) -> tuple[str, bool]:
    if "aa-wrap" not in html:
        return html, False

    updated = False

    # Top / Final labels
    html, n = _replace_label_by_aria(html, "cta top", primary_label)
    if n == 0:
        html, n = _replace_label_in_section(html, "aa-cta-top", primary_label)
    updated |= n > 0

    html, n = _replace_label_by_aria(html, "cta final", primary_label)
    if n == 0:
        html, n = _replace_label_in_section(html, "aa-cta-final", primary_label)
    updated |= n > 0

    # Repair malformed CTA anchors
    for section_class, aria_label, label, default_class in [
        ("aa-cta-top", "cta top", primary_label, "aa-btn"),
        ("aa-cta-final", "cta final", primary_label, "aa-btn aa-btn-primary"),
    ]:
        html, n = _repair_cta_anchor_by_scope(html, section_class, aria_label, label, default_class)
        updated |= n > 0

    # Remove mid CTA entirely
    html, n = re.subn(
        r'<!-- D\. Mid CTA -->\s*<section class="aa-card aa-cta aa-cta-mid"[\s\S]*?</section>\s*',
        "",
        html,
        flags=re.S,
    )
    if n == 0:
        html, n = re.subn(
            r'<section class="aa-card aa-cta aa-cta-mid"[\s\S]*?</section>\s*',
            "",
            html,
            flags=re.S,
        )
    updated |= n > 0

    # Move final CTA under sample video if present
    html, n = _move_final_cta_below_video(html)
    updated |= n > 0

    # Remove duration row from spec table (if present)
    html, n = re.subn(
        r'<div class="aa-tr" role="row">\s*<div class="aa-th" role="cell">収録時間</div>[\s\S]*?</div>\s*</div>\s*',
        "",
        html,
        flags=re.S,
    )
    updated |= n > 0

    # Update purchase label text (above button)
    html, n = re.subn(
        r'(<div class="aa-purchase-label">)(.*?)(</div>)',
        r"\1動画の購入はこちらから\3",
        html,
        count=0,
        flags=re.S,
    )
    updated |= n > 0

    # Remove sticky CTA and scripts
    html, n = re.subn(r'<div class="aa-sticky-cta"[\s\S]*?</div>\s*', '', html, flags=re.S)
    updated |= n > 0
    html, n = re.subn(r'<script>[\s\S]*?aaStickyCtaInit[\s\S]*?</script>\s*', '', html, flags=re.S)
    updated |= n > 0

    # CSS overrides for existing posts
    override_style = """<style>
/* SD CTA overrides */
body[data-site^="sd"],
.aa-wrap[data-site^="sd"] {
  --aa-cta-accent: #ff2d55;
  --aa-cta-accent2: #ff8a3d;
  --aa-cta-text: #fff;
}
body[data-site="sd07-oneesan"],
.aa-wrap[data-site="sd07-oneesan"] {
  --aa-bg: #fff7fb;
  --aa-card: #ffffff;
  --aa-text: #1f2330;
  --aa-muted: rgba(31, 35, 48, .66);
  --aa-line: rgba(31, 35, 48, .10);
  --aa-shadow: 0 10px 24px rgba(255, 164, 206, .18);
  --aa-accent: #ff6fb1;
  --aa-accent2: #ffd1e6;
  --aa-cta-accent: var(--aa-accent);
  --aa-cta-accent2: var(--aa-accent2);
}
body[data-site="sd01-chichi"],
.aa-wrap[data-site="sd01-chichi"] {
  --aa-bg: #fff7fb;
  --aa-card: #ffffff;
  --aa-text: #1f2330;
  --aa-muted: rgba(31, 35, 48, .66);
  --aa-line: rgba(31, 35, 48, .10);
  --aa-shadow: 0 10px 24px rgba(255, 164, 206, .18);
  --aa-accent: #ff6fb1;
  --aa-accent2: #ffd1e6;
}
body[data-site^="sd"] .aa-btn,
body[data-site^="sd"] .aa-btn-secondary,
.aa-wrap[data-site^="sd"] .aa-btn,
.aa-wrap[data-site^="sd"] .aa-btn-secondary {
  background: linear-gradient(135deg, var(--aa-cta-accent), var(--aa-cta-accent2));
  border-color: transparent;
  color: var(--aa-cta-text) !important;
  box-shadow: 0 14px 28px color-mix(in srgb, var(--aa-cta-accent) 35%, transparent), var(--aa-btn-glow);
}
body[data-site^="sd"] .aa-cta,
body[data-site^="sd"] .aa-cta-final,
.aa-wrap[data-site^="sd"] .aa-cta,
.aa-wrap[data-site^="sd"] .aa-cta-final {
  background: var(--aa-card) !important;
}
body[data-site^="sd"] .aa-cta-top .aa-btn,
.aa-wrap[data-site^="sd"] .aa-cta-top .aa-btn {
  padding: 18px 14px;
  font-size: 16px;
  letter-spacing: .04em;
  transform: translateY(-1px);
  box-shadow:
    0 22px 50px color-mix(in srgb, var(--aa-cta-accent) 55%, transparent),
    0 0 0 2px color-mix(in srgb, var(--aa-cta-accent) 35%, transparent),
    var(--aa-btn-glow);
}
</style>"""
    if "SD CTA overrides" in html:
        html, n = re.subn(r"<style>\s*/\* SD CTA overrides \*/[\s\S]*?</style>", override_style, html)
        updated |= n > 0
    else:
        html = html.rstrip() + "\n\n" + override_style + "\n"
        updated = True

    return html, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="SDサイトの既存記事CTA調整")
    parser.add_argument("--subdomains", type=str, default="all", help="comma-separated, or 'all'")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--label-primary", type=str, default="この迫力を確かめる")
    parser.add_argument("--label-secondary", type=str, default="")
    args = parser.parse_args()

    subdomains = [s.strip() for s in args.subdomains.split(",") if s.strip()]
    if args.subdomains == "all":
        subdomains = [s.subdomain for s in SITES if s.subdomain.startswith("sd")]

    if not subdomains:
        logger.error("対象サブドメインがありません")
        return

    config = get_config()

    for subdomain in subdomains:
        base_url = f"https://{subdomain}.av-kantei.com"
        wp_client = WPClient(base_url, config.wp_username, config.wp_app_password)

        logger.info(f"対象: {subdomain} ({base_url})")

        updated_count = 0
        scanned = 0
        for post in wp_client.iter_posts(
            status="publish",
            per_page=100,
            max_pages=args.max_pages,
            fields="id,content",
            context="edit",
        ):
            scanned += 1
            post_id = post.get("id")
            content_obj = post.get("content", {}) or {}
            content = content_obj.get("raw") or content_obj.get("rendered") or ""
            if not content:
                continue

            new_content, changed = update_content(
                content,
                site_id=subdomain,
                primary_label=args.label_primary,
                secondary_label=args.label_secondary,
            )
            if not changed:
                continue

            updated_count += 1
            if args.dry_run:
                logger.info(f"[dry-run] update post id={post_id}")
                continue

            try:
                wp_client.update_post(post_id, {"content": new_content})
                logger.info(f"updated post id={post_id}")
            except Exception as exc:
                logger.error(f"update failed id={post_id}: {exc}")

        logger.info(f"{subdomain}: scanned={scanned}, updated={updated_count}")


if __name__ == "__main__":
    main()
