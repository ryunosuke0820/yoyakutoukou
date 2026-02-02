"""
SDサイトの既存投稿CTAを更新
- CTA文言を「動画の購入はこちらから」「購入はこちらから」に統一
- 固定CTAを挿入/更新（PCでも表示）
- CTA色の上書きCSSを追加
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


def _load_sticky_script() -> str:
    renderer_path = project_root / "src" / "processor" / "renderer.py"
    text = renderer_path.read_text(encoding="utf-8")
    # Robust extraction: find the first <script> block after _STICKY_SCRIPT
    idx = text.find("_STICKY_SCRIPT")
    if idx == -1:
        raise RuntimeError("Sticky script marker not found in renderer.py")
    script_start = text.find("<script>", idx)
    script_end = text.find("</script>", script_start)
    if script_start == -1 or script_end == -1:
        raise RuntimeError("Sticky script not found in renderer.py")
    return text[script_start : script_end + len("</script>")].strip()


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


def _rebuild_cta_section(
    html: str,
    section_class: str,
    aria_label: str,
    label: str,
    default_class: str,
) -> tuple[str, int]:
    pattern = re.compile(
        rf'(<section class="[^"]*{re.escape(section_class)}[^"]*">)([\s\S]*?)(</section>)',
        re.S,
    )
    match = pattern.search(html)
    if not match:
        return html, 0

    head, body, tail = match.group(1), match.group(2), match.group(3)
    href_match = re.search(r'href="([^"]+)"', body)
    href = href_match.group(1) if href_match else "#"

    anchor = (
        f'<a class="{default_class}" href="{href}" rel="nofollow noopener" target="_blank" '
        f'aria-label="{aria_label}">\n'
        f'  <span class="aa-btn-inner">{label}</span>\n'
        f'</a>'
    )

    a_start = body.find("<a")
    a_end = body.find("</a>", a_start)
    if a_start != -1 and a_end != -1:
        new_body = body[:a_start] + anchor + body[a_end + len("</a>") :]
    else:
        # fallback: prepend anchor if malformed
        new_body = anchor + "\n" + body

    new_html = html[: match.start(2)] + new_body + html[match.end(2) :]
    return new_html, 1


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
    if not href_match:
        # try to find href within a small window after scope
        window = html[scope_idx : min(len(html), scope_idx + 2000)]
        href_match = re.search(r'href="([^"]+)"', window)
    href = href_match.group(1) if href_match else "#"

    anchor = (
        f'<a class="{default_class}" href="{href}" rel="nofollow noopener" target="_blank" '
        f'aria-label="{aria_label}">\n'
        f'  <span class="aa-btn-inner">{label}</span>\n'
        f'</a>'
    )

    new_html = html[:a_start] + anchor + html[a_end + len("</a>") :]
    return new_html, 1


def update_content(
    html: str,
    site_id: str,
    primary_label: str,
    secondary_label: str,
    sticky_script: str,
) -> tuple[str, bool]:
    if "aa-wrap" not in html:
        return html, False

    updated = False

    # Top / Mid / Final labels
    html, n = _replace_label_by_aria(html, "cta top", primary_label)
    if n == 0:
        html, n = _replace_label_in_section(html, "aa-cta-top", primary_label)
    updated |= n > 0

    html, n = _replace_label_by_aria(html, "cta final", primary_label)
    if n == 0:
        html, n = _replace_label_in_section(html, "aa-cta-final", primary_label)
    updated |= n > 0

    # Repair malformed CTA anchors (e.g. literal \\1/\\3 inserted)
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

    # Move final CTA under sample video
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
    if final_match:
        final_block = final_match.group(0)
        html = html[: final_match.start()] + html[final_match.end() :]
        video_marker = "<!-- ▼サンプル動画セクション -->"
        video_start = html.find(video_marker)
        if video_start != -1:
            next_section = html.find("<!--", video_start + len(video_marker))
            insert_at = next_section if next_section != -1 else video_start + len(video_marker)
            html = html[:insert_at] + "\n\n" + final_block + "\n\n" + html[insert_at:]
            updated = True

    # Remove duration row from spec table
    html, n = re.subn(
        r'<div class="aa-tr" role="row">\s*<div class="aa-th" role="cell">収録時間</div>[\s\S]*?</div>\s*</div>\s*',
        "",
        html,
        flags=re.S,
    )
    updated |= n > 0

    # Sticky CTA
    sticky_div_exists = '<div class="aa-sticky-cta"' in html
    if sticky_div_exists:
        def _update_sticky_block(m: re.Match) -> str:
            block = m.group(0)
            block = re.sub(r'data-show-after="\\d+"', 'data-show-after="0"', block)
            block = re.sub(r'data-once="[^"]+"', 'data-once="true"', block)
            block = re.sub(r'data-dismissable="[^"]+"', 'data-dismissable="true"', block)
            block = re.sub(r'data-key="[^"]+"', f'data-key="aaStickyCtaDismissed-{site_id}"', block)
            block = re.sub(
                r'<span class="aa-btn-inner">[^<]*</span>',
                f'<span class="aa-btn-inner">{primary_label}</span>',
                block,
            )
            if "aa-sticky-cta-close" not in block:
                block = block.replace(
                    "</a>",
                    '</a>\n    <button class="aa-sticky-cta-close" type="button" aria-label="閉じる">×</button>',
                )
            return block

        html, n = re.subn(r'<div class="aa-sticky-cta"[\\s\\S]*?</div>\\s*', _update_sticky_block, html, count=1)
        updated |= n > 0
    else:
        # Build sticky CTA from top CTA link
        href_match = re.search(r'aria-label="cta top"[^>]*?href="([^"]+)"', html)
        if not href_match:
            href_match = re.search(r'<a class="aa-btn[^"]*"[^>]*?href="([^"]+)"', html)
        href = href_match.group(1) if href_match else "#"
        sticky_block = f'''  <div class="aa-sticky-cta" data-show-after="0" data-once="true" data-dismissable="true" data-key="aaStickyCtaDismissed-{site_id}">
    <a class="aa-btn aa-btn-primary" href="{href}" rel="nofollow noopener" target="_blank" aria-label="sticky cta">
      <span class="aa-btn-inner">{primary_label}</span>
    </a>
    <button class="aa-sticky-cta-close" type="button" aria-label="閉じる">×</button>
  </div>
'''
        badge_match = re.search(r'(<div class="aa-sticky-badge"[\\s\\S]*?</div>\\s*)', html)
        if badge_match:
            insert_at = badge_match.end()
            html = html[:insert_at] + "\n" + sticky_block + html[insert_at:]
            updated = True

    # Sticky script
    if "aaStickyCtaInit" not in html:
        html = html.rstrip() + "\n\n" + sticky_script + "\n"
        updated = True

    # CSS overrides for existing posts
    override_style = """<style>
/* SD CTA overrides */
body[data-site^="sd"] {
  --aa-cta-accent: #ff2d55;
  --aa-cta-accent2: #ff8a3d;
  --aa-cta-text: #fff;
}
body[data-site="sd07-oneesan"] {
  --aa-cta-accent: var(--aa-accent);
  --aa-cta-accent2: var(--aa-accent2);
}
body[data-site="sd07-oneesan"],
body[data-site="sd07-oneesan"] .site,
body[data-site="sd07-oneesan"] .site-content,
body[data-site="sd07-oneesan"] .content-area,
body[data-site="sd07-oneesan"] .entry-content {
  background: var(--aa-bg) !important;
}
body[data-site^="sd"] .aa-btn,
body[data-site^="sd"] .aa-btn-secondary {
  background: linear-gradient(135deg, var(--aa-cta-accent), var(--aa-cta-accent2));
  border-color: transparent;
  color: var(--aa-cta-text) !important;
  box-shadow: 0 14px 28px color-mix(in srgb, var(--aa-cta-accent) 35%, transparent), var(--aa-btn-glow);
}
body[data-site^="sd"] .aa-cta,
body[data-site^="sd"] .aa-cta-final {
  background: var(--aa-card) !important;
}
body[data-site^="sd"] .aa-cta-top .aa-btn {
  padding: 18px 14px;
  font-size: 16px;
  letter-spacing: .04em;
  transform: translateY(-1px);
  box-shadow:
    0 22px 50px color-mix(in srgb, var(--aa-cta-accent) 55%, transparent),
    0 0 0 2px color-mix(in srgb, var(--aa-cta-accent) 35%, transparent),
    var(--aa-btn-glow);
}
@media (min-width: 769px) {
  .aa-sticky-cta {
    display: flex !important;
  }
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
    parser = argparse.ArgumentParser(description="SDサイトの既存投稿CTAを更新")
    parser.add_argument("--subdomains", type=str, default="all", help="comma-separated, or 'all'")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--label-primary", type=str, default="動画の購入はこちらから")
    parser.add_argument("--label-secondary", type=str, default="購入はこちらから")
    args = parser.parse_args()

    subdomains = [s.strip() for s in args.subdomains.split(",") if s.strip()]
    if args.subdomains == "all":
        subdomains = [s.subdomain for s in SITES if s.subdomain.startswith("sd")]

    if not subdomains:
        logger.error("対象サブドメインがありません")
        return

    config = get_config()
    sticky_script = _load_sticky_script()

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
                sticky_script=sticky_script,
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
