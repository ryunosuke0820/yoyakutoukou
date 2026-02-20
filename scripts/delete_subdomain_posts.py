import os
import sys
import logging
import io
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.clients.wordpress import WPClient
from scripts.configure_sites import SITES, SiteConfig

# Windows環境での文字化け対策
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 共通ログイン情報
def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value

def delete_all_posts_from_site(site: SiteConfig):
    base_url = f"https://{site.subdomain}.av-kantei.com"
    logger.info(f"Starting deletion for {base_url}...")
    
    wp_client = WPClient(
        base_url=base_url,
        username=_required_env("WP_USERNAME"),
        app_password=_required_env("WP_APP_PASSWORD"),
    )
    
    deleted_count = 0
    while True:
        # 100件ずつ取得 (ゴミ箱も含めて全削除する場合 status='any')
        try:
            posts = wp_client.get_recent_posts(limit=100, status="any")
            if not posts:
                break
                
            logger.info(f"[{site.subdomain}] Found {len(posts)} posts. Deleting...")
            for post in posts:
                try:
                    post_id = post["id"]
                    # 永久削除 (force=True) する
                    wp_client.delete_post(post_id, force=True)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"[{site.subdomain}] Failed to delete post {post.get('id')}: {e}")
            
            logger.info(f"[{site.subdomain}] Deleted {deleted_count} posts so far...")
            
            if len(posts) < 100:
                break
        except Exception as e:
            logger.error(f"[{site.subdomain}] Error fetching posts: {e}")
            break
    
    logger.info(f"[{site.subdomain}] Finished. Total deleted: {deleted_count}")

def main():
    logger.info("Starting subdomain posts cleanup...")
    # SITES は configure_sites.py で定義されているサブドメインのリスト
    for site in SITES:
        try:
            delete_all_posts_from_site(site)
        except Exception as e:
            logger.error(f"Error processing {site.subdomain}: {e}")
    logger.info("Subdomain posts cleanup completed.")

if __name__ == "__main__":
    main()
