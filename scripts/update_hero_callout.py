import argparse
import os
import re
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _slug_from_url_or_slug(value: str) -> str:
    v = (value or "").strip()
    if v.startswith("http://") or v.startswith("https://"):
        path = urlparse(v).path.strip("/")
        return path.split("/")[-1] if path else ""
    return v.strip("/")


def _replace_first_callout(content: str, title: str, body: str) -> tuple[str, bool]:
    title_re = re.compile(r'(<div class="aa-callout-title">)(.*?)(</div>)', re.DOTALL)
    body_re = re.compile(r'(<div class="aa-callout-body">)(.*?)(</div>)', re.DOTALL)

    new_content, n1 = title_re.subn(rf"\1{title}\3", content, count=1)
    new_content, n2 = body_re.subn(rf"\1{body}\3", new_content, count=1)
    return new_content, (n1 > 0 and n2 > 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update first hero callout text of an existing WP post.")
    parser.add_argument("--target", required=True, help="Post URL or slug")
    parser.add_argument("--base-url", default="", help="WP base URL (fallbacks to WP_BASE_URL in .env)")
    parser.add_argument("--title", required=True, help="New callout title")
    parser.add_argument("--body", required=True, help="New callout body")
    parser.add_argument("--dry-run", action="store_true", help="Do not update WP")
    args = parser.parse_args()

    load_dotenv(".env")
    base_url = (args.base_url or os.getenv("WP_BASE_URL", "")).rstrip("/")
    username = _required_env("WP_USERNAME")
    app_password = _required_env("WP_APP_PASSWORD")
    slug = _slug_from_url_or_slug(args.target)
    if not base_url or not slug:
        raise RuntimeError("base_url or slug is empty")

    auth = (username, app_password)
    params = {"slug": slug, "context": "edit", "status": "any", "_fields": "id,slug,content"}
    res = requests.get(f"{base_url}/wp-json/wp/v2/posts", params=params, auth=auth, timeout=30)
    if res.status_code != 200:
        raise RuntimeError(f"Failed to fetch post: status={res.status_code} body={(res.text or '')[:300]}")
    items = res.json() or []
    if not items:
        raise RuntimeError(f"Post not found: slug={slug}")

    post = items[0]
    post_id = int(post["id"])
    content_obj = post.get("content", {})
    raw = content_obj.get("raw") if isinstance(content_obj, dict) else ""
    if not raw:
        raise RuntimeError("Post raw content is empty (need context=edit permission)")

    updated, ok = _replace_first_callout(raw, args.title, args.body)
    if not ok:
        raise RuntimeError("Callout block not found in content")

    if args.dry_run:
        print(f"[DRY RUN] would update post_id={post_id} slug={slug}")
        return 0

    u = requests.post(
        f"{base_url}/wp-json/wp/v2/posts/{post_id}",
        json={"content": updated},
        auth=auth,
        timeout=30,
    )
    if u.status_code not in (200, 201):
        raise RuntimeError(f"Failed to update post: status={u.status_code} body={(u.text or '')[:300]}")
    print(f"updated post_id={post_id} slug={slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
