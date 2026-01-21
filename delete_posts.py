"""
WordPressの特定の投稿を削除するスクリプト
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
    parser = argparse.ArgumentParser(description="特定の投稿を削除")
    parser.add_argument("post_ids", type=int, nargs="+", help="削除する投稿ID（スペース区切り）")
    parser.add_argument("--no-force", action="store_false", dest="force", help="ゴミ箱に移動（完全に削除しない）")
    args = parser.parse_args()
    
    config = get_config()
    wp_client = WPClient(
        base_url=config.wp_base_url,
        username=config.wp_username,
        app_password=config.wp_app_password,
    )
    
    confirm = input(f"投稿ID {args.post_ids} を削除しますか? (y/N): ")
    if not confirm.lower().startswith("y"):
        logger.info("キャンセルしました")
        return
    
    success = 0
    fail = 0
    for pid in args.post_ids:
        if delete_post(wp_client, pid, force=args.force):
            logger.info(f"削除成功: ID={pid}")
            success += 1
        else:
            fail += 1
    
    print("\n" + "=" * 60)
    print(f"✅ 削除完了! 成功: {success}件 / 失敗: {fail}件")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
