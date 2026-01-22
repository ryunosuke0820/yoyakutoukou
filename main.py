"""
FANZA → WordPress 自動記事投稿ボット

メインエントリポイント（シンプル版）
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from config import get_config
from fanza_client import FanzaClient
from openai_client import OpenAIClient
from wp_client import WPClient
from renderer import Renderer
from image_tools import ImageTools
from dedupe_store import DedupeStore


# ────────────────────────────────────────────────────────────────────────────
# 計測ヘルパー
# ────────────────────────────────────────────────────────────────────────────
def step(label: str):
    """工程の所要時間を計測するヘルパー"""
    t0 = time.perf_counter()
    logging.info(f"STEP {label} 開始")
    def end():
        dt = time.perf_counter() - t0
        logging.info(f"STEP {label} 完了: {dt:.2f}s")
    return end


def setup_logging(level: str) -> None:
    """ロギング設定"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("fanza_bot.log", encoding="utf-8"),
        ],
    )


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="FANZA商品から記事を生成しWordPressに投稿",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="取得件数（デフォルト: 1）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="WPに投稿せず、生成結果を保存して終わる",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル（デフォルト: INFO）",
    )
    parser.add_argument(
        "--sort",
        type=str,
        default="rank",
        help="ソート順 (rank: 人気順, date: 新着順, etc. デフォルト: rank)",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="この日付以降の商品を取得 (YYYY-MM-DD)",
    )
    
    args = parser.parse_args()
    
    # ロギング設定
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("FANZA → WordPress 自動記事投稿ボット 開始")
    logger.info(f"limit={args.limit}, dry_run={args.dry_run}, sort={args.sort}, since={args.since}")
    logger.info("=" * 60)
    
    try:
        # 設定読み込み
        config = get_config()
        logger.info("設定読み込み完了")
        
        # クライアント初期化
        fanza_client = FanzaClient(
            api_key=config.fanza_api_key,
            affiliate_id=config.fanza_affiliate_id,
        )
        llm_client = OpenAIClient(
            api_key=config.openai_api_key,
            model=config.openai_model,
            prompts_dir=config.prompts_dir,
            viewpoints_path=config.base_dir / "viewpoints.json",
        )
        wp_client = WPClient(
            base_url=config.wp_base_url,
            username=config.wp_username,
            app_password=config.wp_app_password,
        )
        renderer = Renderer(templates_dir=config.base_dir / "templates")
        
        # 重複防止ストア初期化
        dedupe_store = DedupeStore(db_path=config.data_dir / "posted.sqlite3")
        stats = dedupe_store.get_stats()
        logger.info(f"重複防止ストア: 合計={stats['total']}, 下書き={stats['drafted']}, ドライラン={stats['dry_run']}, 失敗={stats['failed']}件")
        
        # ────────────────────────────────────────────────────────────────
        # STEP fanza_fetch
        # ────────────────────────────────────────────────────────────────
        end = step("fanza_fetch")
        items = fanza_client.fetch(limit=args.limit, since=args.since, sort=args.sort)
        end()
        
        if not items:
            logger.warning("取得商品が0件のため終了")
            sys.exit(0)
        
        logger.info(f"取得完了: {len(items)}件")
        
        # ImageTools は1回だけ初期化
        image_tools = ImageTools()
        
        # 成功・失敗カウンタ
        success_count = 0
        fail_count = 0
        
        # 全件をループ処理
        # 投稿済み商品を除外
        skipped_count = 0
        for idx, item in enumerate(items, 1):
            product_id = item['product_id']
            
            # 重複チェック
            if dedupe_store.is_posted(product_id):
                logger.info(f"[{idx}/{len(items)}] スキップ（投稿済み）: {product_id}")
                skipped_count += 1
                continue
            
            logger.info(f"\n{'='*60}")
            logger.info(f"[{idx}/{len(items)}] 対象商品: {product_id} - {item['title'][:40]}...")
            logger.info("=" * 60)
            
            try:
                # ────────────────────────────────────────────────────────────────
                # STEP llm_generate
                # ────────────────────────────────────────────────────────────────
                end = step(f"llm_generate [{idx}/{len(items)}]")
                ai_response = llm_client.generate(item=item)
                end()
                
                logger.info(f"AI応答取得完了: title={ai_response.get('title', '')[:30]}...")
                
                # ────────────────────────────────────────────────────────────────
                # STEP upload_images (ドライランでなければ)
                # ────────────────────────────────────────────────────────────────
                if not args.dry_run:
                    end = step(f"upload_images [{idx}/{len(items)}]")
                    
                    # アイキャッチ画像用のメディアIDを保存
                    featured_media_id = None
                    
                    # パッケージ画像をアップロード
                    if item.get("package_image_url"):
                        try:
                            img_bytes, filename, mime_type = image_tools.download_to_bytes(item["package_image_url"])
                            result = wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                            item["package_image_url"] = result.get("source_url", item["package_image_url"])
                            logger.info(f"パッケージ画像アップロード完了: {item['package_image_url']}")
                        except Exception as e:
                            logger.warning(f"パッケージ画像アップロード失敗: {e}")
                    
                    # サンプル画像をアップロード（記事表示用は中盤、アイキャッチは最後尾の過激画像）
                    sample_pool = item.get("sample_image_urls", [])
                    # 記事表示用はインデックス 2, 5, 8 あたりを優先
                    targets = [2, 5, 8]
                    selected_urls = []
                    for t in targets:
                        if t < len(sample_pool):
                            selected_urls.append(sample_pool[t])
                    
                    # 足りない場合は前から詰める
                    if len(selected_urls) < 3:
                        for url in sample_pool:
                            if url not in selected_urls:
                                selected_urls.append(url)
                            if len(selected_urls) >= 3:
                                break
                    
                    # アイキャッチ用に後半の画像を選ぶ（肌の露出が多い）
                    eyecatch_url = None
                    if sample_pool:
                        # 後半のインデックスを狙う（肌露出多め）
                        # 画像枚数に応じて適切なインデックスを選択
                        if len(sample_pool) >= 9:
                            eyecatch_idx = 7  # 9枚以上なら7
                        elif len(sample_pool) >= 7:
                            eyecatch_idx = 6  # 7-8枚なら6
                        elif len(sample_pool) >= 5:
                            eyecatch_idx = 4  # 5-6枚なら4
                        elif len(sample_pool) >= 3:
                            eyecatch_idx = 2  # 3-4枚なら2
                        else:
                            eyecatch_idx = len(sample_pool) - 1  # 少ない場合は最後
                        eyecatch_url = sample_pool[eyecatch_idx]
                        logger.info(f"アイキャッチ画像候補: インデックス {eyecatch_idx} を選択（肌露出狙い）")
                    
                    new_sample_urls = []
                    for i, sample_url in enumerate(selected_urls[:3]):
                        try:
                            img_bytes, filename, mime_type = image_tools.download_to_bytes(sample_url)
                            result = wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                            new_sample_urls.append(result.get("source_url", sample_url))
                            media_id = result.get("id")
                            logger.info(f"サンプル画像{i+1}アップロード完了 (media_id={media_id})")
                        except Exception as e:
                            logger.warning(f"サンプル画像{i+1}アップロード失敗: {e}")
                            new_sample_urls.append(sample_url) # 失敗時は元URLを使用
                    
                    # アイキャッチ画像を別途アップロード（最後尾の過激シーン）
                    if eyecatch_url:
                        try:
                            img_bytes, filename, mime_type = image_tools.download_to_bytes(eyecatch_url)
                            result = wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                            featured_media_id = result.get("id")
                            logger.info(f"アイキャッチ画像アップロード完了: media_id={featured_media_id}")
                        except Exception as e:
                            logger.warning(f"アイキャッチ画像アップロード失敗: {e}")
                    
                    item["sample_image_urls"] = new_sample_urls
                    item["_featured_media_id"] = featured_media_id  # 内部用に保持
                    end()
                
                # ────────────────────────────────────────────────────────────────
                # STEP render_content
                # ────────────────────────────────────────────────────────────────
                end = step(f"render_content [{idx}/{len(items)}]")
                content_html = renderer.render_post_content(item, ai_response)
                end()
                
                logger.info(f"最終HTML長: {len(content_html)}文字")
                
                # ドライラン時はファイル保存のみ
                if args.dry_run:
                    logger.info("【ドライラン】WP投稿をスキップ")
                    dry_run_path = config.data_dir / f"dry_run_{item['product_id']}_content.html"
                    dry_run_path.parent.mkdir(parents=True, exist_ok=True)
                    dry_run_path.write_text(content_html, encoding="utf-8")
                    logger.info(f"ドライランHTML保存: {dry_run_path}")
                    # ドライラン時も記録して再実行時にスキップ
                    dedupe_store.record_success(product_id, wp_post_id=None, status="dry_run")
                    success_count += 1
                    continue
                
                # ────────────────────────────────────────────────────────────────
                # STEP wp_post_draft
                # ────────────────────────────────────────────────────────────────
                end = step(f"wp_post_draft [{idx}/{len(items)}]")
                featured_media_id = item.get("_featured_media_id")
                
                # 抜粋として AI が生成した short_description を使用
                excerpt_text = ai_response.get("short_description", "")
                
                post_id = wp_client.post_draft(
                    title=item["title"], 
                    content=content_html,
                    excerpt=excerpt_text,
                    featured_media=featured_media_id
                )
                end()
                
                logger.info(f"投稿成功: wp_post_id={post_id}")
                # 投稿成功を記録
                dedupe_store.record_success(product_id, wp_post_id=post_id, status="drafted")
                success_count += 1
                
            except Exception as e:
                logger.exception(f"[{idx}/{len(items)}] 処理失敗: {e}")
                # 失敗を記録（リトライ用に別ステータス）
                dedupe_store.record_failure(product_id, str(e))
                fail_count += 1
                continue  # 次の商品へ
        
        # 最終結果サマリー
        print("\n" + "=" * 60, flush=True)
        if args.dry_run:
            print("✅ ドライラン完了！", flush=True)
        else:
            print("✅ WordPress投稿完了！", flush=True)
        print(f"   成功: {success_count}件 / 失敗: {fail_count}件 / スキップ: {skipped_count}件 / 合計: {len(items)}件", flush=True)
        print("=" * 60 + "\n", flush=True)
        
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", flush=True)
        logger.exception(f"エラー発生: {e}")
        raise


if __name__ == "__main__":
    main()
