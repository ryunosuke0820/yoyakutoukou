"""
既存の投稿にアイキャッチ画像を追加するスクリプト
投稿のコンテンツから最初の画像を取得してアイキャッチに設定
"""
import argparse
import logging
import re
import sys

from config import get_config
from wp_client import WPClient
from image_tools import ImageTools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_posts(wp_client: WPClient, status: str = "publish", per_page: int = 100, only_without_featured: bool = False) -> list[dict]:
    """投稿を取得"""
    response = wp_client._request(
        "GET", 
        "posts", 
        params={"status": status, "per_page": per_page}
    )
    response.raise_for_status()
    posts = response.json()
    
    if only_without_featured:
        # アイキャッチが0（未設定）の投稿のみ返す
        return [p for p in posts if p.get("featured_media", 0) == 0]
    return posts


def extract_eyecatch_image_url(content: str) -> str | None:
    """コンテンツから後半の画像URLを抽出（肌の露出が多い画像）"""
    # imgタグからsrc属性を全て抽出
    matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
    if matches:
        # 後半の画像を選ぶ（肌露出多め）
        total = len(matches)
        if total >= 9:
            idx = 7  # 9枚以上なら7
        elif total >= 7:
            idx = 6  # 7-8枚なら6
        elif total >= 5:
            idx = 4  # 5-6枚なら4
        elif total >= 3:
            idx = 2  # 3-4枚なら2
        else:
            idx = total - 1  # 少ない場合は最後
        return matches[idx]
    return None


def update_featured_media(wp_client: WPClient, post_id: int, media_id: int) -> bool:
    """投稿のアイキャッチ画像を更新"""
    try:
        response = wp_client._request(
            "POST",
            f"posts/{post_id}",
            json={"featured_media": media_id}
        )
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"アイキャッチ更新失敗: post_id={post_id}, error={e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="既存投稿のアイキャッチを更新")
    parser.add_argument("--status", default="publish", help="対象の投稿ステータス（publish/draft）")
    parser.add_argument("--dry-run", action="store_true", help="実際には更新しない")
    parser.add_argument("--limit", type=int, default=100, help="最大件数")
    parser.add_argument("--all", action="store_true", help="アイキャッチ設定済みの投稿も含めて更新")
    args = parser.parse_args()
    
    config = get_config()
    wp_client = WPClient(
        base_url=config.wp_base_url,
        username=config.wp_username,
        app_password=config.wp_app_password,
    )
    image_tools = ImageTools()
    
    only_without = not args.all
    target_desc = "アイキャッチ未設定の投稿" if only_without else "全投稿（アイキャッチ更新）"
    logger.info(f"{target_desc}を取得中...")
    posts = get_posts(wp_client, status=args.status, per_page=args.limit, only_without_featured=only_without)
    
    if not posts:
        logger.info("対象の投稿はありませんでした")
        return
    
    logger.info(f"対象投稿: {len(posts)}件")
    print("\n" + "=" * 60)
    for i, post in enumerate(posts, 1):
        title = post.get("title", {}).get("rendered", "無題")
        print(f"  {i}. [ID:{post['id']}] {title[:50]}")
    print("=" * 60 + "\n")
    
    if args.dry_run:
        logger.info("【ドライラン】更新処理をスキップ")
        return
    
    confirm = input(f"上記 {len(posts)} 件にアイキャッチを設定しますか? (y/N): ")
    if not confirm.lower().startswith("y"):
        logger.info("キャンセルしました")
        return
    
    success = 0
    fail = 0
    
    for post in posts:
        post_id = post["id"]
        title = post.get("title", {}).get("rendered", "無題")[:40]
        content = post.get("content", {}).get("rendered", "")
        
        # コンテンツから中盤の画像URL（顔+エロ）を抽出
        img_url = extract_eyecatch_image_url(content)
        if not img_url:
            logger.warning(f"[{post_id}] 画像が見つかりません: {title}")
            fail += 1
            continue
        
        try:
            # 画像がすでにWP上にある場合はそのメディアIDを取得
            # 外部URLの場合はダウンロードしてアップロード
            if config.wp_base_url in img_url:
                # すでにWPにある画像 - メディアを検索
                logger.info(f"[{post_id}] WP画像検出、メディア検索中...")
                # ファイル名でメディアを検索
                filename = img_url.split("/")[-1]
                response = wp_client._request("GET", "media", params={"search": filename.split(".")[0]})
                media_list = response.json()
                
                if media_list:
                    media_id = media_list[0]["id"]
                    logger.info(f"[{post_id}] 既存メディア発見: media_id={media_id}")
                else:
                    # 見つからなければ新規アップロード
                    img_bytes, filename, mime_type = image_tools.download_to_bytes(img_url)
                    result = wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                    media_id = result["id"]
                    logger.info(f"[{post_id}] 新規アップロード: media_id={media_id}")
            else:
                # 外部URL - ダウンロードしてアップロード
                img_bytes, filename, mime_type = image_tools.download_to_bytes(img_url)
                result = wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                media_id = result["id"]
                logger.info(f"[{post_id}] 外部画像アップロード: media_id={media_id}")
            
            # アイキャッチを設定
            if update_featured_media(wp_client, post_id, media_id):
                logger.info(f"[{post_id}] ✅ アイキャッチ設定完了: {title}")
                success += 1
            else:
                fail += 1
                
        except Exception as e:
            logger.error(f"[{post_id}] エラー: {e}")
            fail += 1
    
    print("\n" + "=" * 60)
    print(f"✅ 処理完了! 成功: {success}件 / 失敗: {fail}件")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
