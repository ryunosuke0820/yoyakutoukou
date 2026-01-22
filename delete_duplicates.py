"""
重複記事を検出して削除するスクリプト
"""
import logging
from collections import defaultdict

from config import get_config
from wp_client import WPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_posts(wp_client: WPClient, per_page: int = 100) -> list:
    """下書き記事と公開済み記事を全て取得"""
    all_posts = []
    
    for status in ["draft", "publish"]:
        page = 1
        while True:
            endpoint = f"posts?status={status}&per_page={per_page}&page={page}"
            try:
                response = wp_client._request("GET", endpoint)
                response.raise_for_status()
                posts = response.json()
                if not posts:
                    break
                all_posts.extend(posts)
                logger.info(f"{status}記事: {len(posts)}件取得 (page={page})")
                page += 1
            except Exception as e:
                logger.error(f"{status}記事取得失敗: {e}")
                break
    
    return all_posts


def delete_post(wp_client: WPClient, post_id: int, force: bool = True) -> bool:
    """投稿を削除"""
    endpoint = f"posts/{post_id}"
    if force:
        endpoint += "?force=true"
    
    try:
        response = wp_client._request("DELETE", endpoint)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"削除失敗: ID={post_id}, error={e}")
        return False


def main():
    config = get_config()
    wp_client = WPClient(
        base_url=config.wp_base_url,
        username=config.wp_username,
        app_password=config.wp_app_password,
    )
    
    # 記事を取得（下書き＋公開済み）
    logger.info("記事を取得中...")
    posts = get_posts(wp_client)
    logger.info(f"取得した記事: {len(posts)}件")
    
    if not posts:
        print("記事がありません")
        return
    
    # タイトルごとにグループ化
    title_groups = defaultdict(list)
    for post in posts:
        title = post["title"]["rendered"]
        title_groups[title].append(post)
    
    # 重複を検出
    duplicates_to_delete = []
    for title, posts in title_groups.items():
        if len(posts) > 1:
            logger.info(f"重複検出: 「{title[:40]}...」 ({len(posts)}件)")
            # 最新のもの（ID最大）を残し、それ以外を削除対象に
            posts_sorted = sorted(posts, key=lambda p: p["id"], reverse=True)
            keep = posts_sorted[0]
            for dup in posts_sorted[1:]:
                duplicates_to_delete.append({
                    "id": dup["id"],
                    "title": title[:50],
                })
    
    if not duplicates_to_delete:
        print("\n重複記事はありませんでした！✅")
        return
    
    print(f"\n{'='*60}")
    print(f"[DELETE] 削除対象の重複記事: {len(duplicates_to_delete)}件")
    print("="*60)
    for item in duplicates_to_delete:
        print(f"  ID={item['id']}: {item['title']}...")
    
    confirm = input(f"\nこれらの重複記事を削除しますか? (y/N): ")
    if not confirm.lower().startswith("y"):
        logger.info("キャンセルしました")
        return
    
    # 削除実行
    success = 0
    fail = 0
    for item in duplicates_to_delete:
        if delete_post(wp_client, item["id"]):
            logger.info(f"削除成功: ID={item['id']}")
            success += 1
        else:
            fail += 1
    
    print("\n" + "=" * 60)
    print(f"[OK] 重複削除完了! 成功: {success}件 / 失敗: {fail}件")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
