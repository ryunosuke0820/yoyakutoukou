"""
WordPressの下書きを一括公開するスクリプト
"""
import argparse
import logging
import sys

from config import get_config
from wp_client import WPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_drafts(wp_client: WPClient, per_page: int = 100) -> list[dict]:
    """下書き一覧を取得"""
    response = wp_client._request(
        "GET", 
        "posts", 
        params={"status": "draft", "per_page": per_page}
    )
    response.raise_for_status()
    return response.json()


def publish_post(wp_client: WPClient, post_id: int) -> dict:
    """投稿を公開"""
    response = wp_client._request(
        "POST",
        f"posts/{post_id}",
        json={"status": "publish"}
    )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="下書きを一括公開")
    parser.add_argument("--dry-run", action="store_true", help="公開せずに下書き一覧を表示")
    parser.add_argument("--limit", type=int, default=100, help="最大件数（デフォルト: 100）")
    args = parser.parse_args()
    
    config = get_config()
    wp_client = WPClient(
        base_url=config.wp_base_url,
        username=config.wp_username,
        app_password=config.wp_app_password,
    )
    
    logger.info("下書き一覧を取得中...")
    drafts = get_drafts(wp_client, per_page=args.limit)
    
    if not drafts:
        logger.info("下書きが見つかりませんでした")
        return
    
    logger.info(f"下書き件数: {len(drafts)}件")
    print("\n" + "=" * 60)
    for i, draft in enumerate(drafts, 1):
        title = draft.get("title", {}).get("rendered", "無題")
        print(f"  {i}. [ID:{draft['id']}] {title[:50]}")
    print("=" * 60 + "\n")
    
    if args.dry_run:
        logger.info("【ドライラン】公開処理をスキップ")
        return
    
    # 確認プロンプト
    confirm = input(f"上記 {len(drafts)} 件を公開しますか? (y/N): ")
    if not confirm.lower().startswith("y"):
        logger.info("キャンセルしました")
        return
    
    # 一括公開
    success = 0
    fail = 0
    for draft in drafts:
        try:
            result = publish_post(wp_client, draft["id"])
            logger.info(f"公開成功: ID={draft['id']}, URL={result.get('link', '')}")
            success += 1
        except Exception as e:
            logger.error(f"公開失敗: ID={draft['id']}, error={e}")
            fail += 1
    
    print("\n" + "=" * 60)
    print(f"✅ 公開完了! 成功: {success}件 / 失敗: {fail}件")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
