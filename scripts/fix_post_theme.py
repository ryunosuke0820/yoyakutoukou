import argparse
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# Allow `python scripts/...` execution from repository root.
sys.path.append(str(Path(__file__).parent.parent))

from src.core.config import get_config
from src.clients.wordpress import WPClient

logger = logging.getLogger(__name__)


def extract_slug(url_or_slug: str) -> str:
    value = (url_or_slug or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        path = urlparse(value).path.strip("/")
        return path.split("/")[-1] if path else ""
    return value.strip("/")


def apply_site_theme(content: str, site_id: str) -> tuple[str, bool]:
    updated = content
    changed = False

    updated2 = re.sub(r'data-site="[^"]*"', f'data-site="{site_id}"', updated, count=1)
    if updated2 != updated:
        changed = True
        updated = updated2
    elif '<div class="aa-wrap' in updated:
        updated = updated.replace('<div class="aa-wrap', f'<div class="aa-wrap" data-site="{site_id}"', 1)
        changed = True

    updated2 = re.sub(r'aa-site-[a-z0-9-]+', f'aa-site-{site_id}', updated, count=1)
    if updated2 != updated:
        changed = True
        updated = updated2

    return updated, changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix a WordPress post to use a target site theme.")
    parser.add_argument("--url", required=True, help="Target post URL or slug.")
    parser.add_argument("--site-id", default="sd01-chichi", help="Theme site id (default: sd01-chichi).")
    parser.add_argument("--dry-run", action="store_true", help="Show detection only, do not update.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    slug = extract_slug(args.url)
    if not slug:
        logger.error("Could not extract slug from --url.")
        return 1

    config = get_config()
    wp = WPClient(config.wp_base_url, config.wp_username, config.wp_app_password)

    resp = wp._request("GET", "posts", params={"slug": slug, "status": "any", "context": "edit", "_fields": "id,slug,content"})
    resp.raise_for_status()
    posts = resp.json() or []
    if not posts:
        logger.error("Post not found: slug=%s", slug)
        return 1

    post = posts[0]
    post_id = int(post["id"])
    content_obj = post.get("content", {})
    raw_content = content_obj.get("raw") if isinstance(content_obj, dict) else ""
    if not raw_content:
        logger.error("Post content(raw) is empty. post_id=%s", post_id)
        return 1

    updated_content, changed = apply_site_theme(raw_content, args.site_id)
    if not changed:
        logger.info("No theme marker changed. post_id=%s slug=%s", post_id, slug)
        return 0

    if args.dry_run:
        logger.info("Dry run: would update post_id=%s slug=%s to site=%s", post_id, slug, args.site_id)
        return 0

    wp.update_post(post_id, {"content": updated_content})
    logger.info("Updated post_id=%s slug=%s to site=%s", post_id, slug, args.site_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
