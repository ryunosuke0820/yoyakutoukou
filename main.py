"""
FANZA → WordPress 自動記事投稿ボット

メインエントリポイント（シンプル版）
"""
import argparse
import logging
import io
import sys
import time
from pathlib import Path

# Windows環境での文字化け対策
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from config import get_config
from fanza_client import FanzaClient
from openai_client import OpenAIClient
from wp_client import WPClient
from renderer import Renderer
from image_tools import ImageTools, ImagePlaceholderError
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
        default="date",
        help="ソート順 (date: 新着順[推奨], rank: 人気順. デフォルト: date)",
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
        # STEP fanza_fetch (ページング対応・100件初回取得)
        # ────────────────────────────────────────────────────────────────
        end = step("fanza_fetch")
        
        # 設定: 投稿目標件数とページング
        target_count = args.limit  # 投稿したい件数
        fetch_batch_size = 100     # 1回のAPI取得件数
        max_pages = 5              # 最大ページ数
        
        all_items = []        # 全取得アイテム
        posted_ids = set()    # 投稿済みID（サーバー側からも取得）
        
        # WordPress側から既存の投稿済みIDを取得（永続チェック）
        try:
            wp_posted_ids = wp_client.get_posted_fanza_ids()
            posted_ids.update(wp_posted_ids)
            logger.info(f"WordPress側の投稿済みID: {len(wp_posted_ids)}件")
        except Exception as e:
            logger.warning(f"WordPress側の投稿済みID取得失敗（続行）: {e}")
        
        # ローカルDBからも投稿済みIDを確認
        # ※dedupe_storeのis_postedは個別チェック用なので、ここでは使わない
        
        # ページングで候補を取得
        for page in range(max_pages):
            offset = page * fetch_batch_size
            logger.info(f"FANZA API取得: page={page+1}, offset={offset}")
            
            batch = fanza_client.fetch(
                limit=fetch_batch_size, 
                since=args.since, 
                sort=args.sort,
                offset=offset
            )
            
            if not batch:
                logger.info(f"page={page+1}で取得件数0のため終了")
                break
            
            # 投稿済みを除外して追加
            for item in batch:
                pid = item['product_id']
                if pid in posted_ids or dedupe_store.is_posted(pid):
                    continue
                all_items.append(item)
                posted_ids.add(pid)  # 重複追加防止
            
            logger.info(f"page={page+1}: 取得{len(batch)}件 → 未投稿候補{len(all_items)}件")
            
            # 目標件数に達したら終了
            if len(all_items) >= target_count:
                break
        
        end()
        
        if not all_items:
            logger.warning("未投稿の商品が0件のため終了")
            sys.exit(0)
        
        # 投稿対象を目標件数に絞る
        items = all_items[:target_count]
        logger.info(f"投稿対象: {len(items)}件 (候補総数: {len(all_items)}件)")
        
        # ImageTools は1回だけ初期化
        image_tools = ImageTools()
        
        # 成功・失敗カウンタ
        success_count = 0
        fail_count = 0
        posted_product_ids = []  # 今回投稿したIDのログ用
        
        # 全件をループ処理（既に投稿済み除外済み）
        for idx, item in enumerate(items, 1):
            product_id = item['product_id']
            
            logger.info(f"\n{'='*60}")
            logger.info(f"[{idx}/{len(items)}] 対象商品: {product_id} - {item['title'][:40]}...")
            logger.info("=" * 60)
            
            try:
                # ────────────────────────────────────────────────────────────────
                # まずシーン用の画像URLを決定（AI生成前に必要）
                # ────────────────────────────────────────────────────────────────
                sample_pool = item.get("sample_image_urls", [])
                # 記事表示用はインデックス 2, 5, 8 あたりを優先
                targets = [2, 5, 8]
                scene_image_urls = []
                for t in targets:
                    if t < len(sample_pool):
                        scene_image_urls.append(sample_pool[t])
                
                # 足りない場合は前から詰める
                if len(scene_image_urls) < 3:
                    for url in sample_pool:
                        if url not in scene_image_urls:
                            scene_image_urls.append(url)
                        if len(scene_image_urls) >= 3:
                            break
                
                logger.info(f"シーン用画像: {len(scene_image_urls)}枚を選択")
                
                # ────────────────────────────────────────────────────────────────
                # STEP llm_generate（画像付きでマルチモーダル呼び出し）
                # ────────────────────────────────────────────────────────────────
                end = step(f"llm_generate [{idx}/{len(items)}]")
                ai_response = llm_client.generate(item=item, sample_image_urls=scene_image_urls)
                end()
                
                logger.info(f"AI応答取得完了: title={ai_response.get('title', '')[:30]}...")
                
                # ────────────────────────────────────────────────────────────────
                # STEP upload_images (ドライランでなければ)
                # ────────────────────────────────────────────────────────────────
                if not args.dry_run:
                    end = step(f"upload_images [{idx}/{len(items)}]")
                    
                    # アイキャッチ画像用のメディアIDを保存
                    featured_media_id = None
                    
                    # パッケージ画像をアップロード（プレースホルダーならスキップ）
                    if item.get("package_image_url"):
                        try:
                            img_bytes, filename, mime_type = image_tools.download_to_bytes(item["package_image_url"])
                            result = wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                            item["package_image_url"] = result.get("source_url", item["package_image_url"])
                            logger.info(f"パッケージ画像アップロード完了: {item['package_image_url']}")
                        except ImagePlaceholderError as e:
                            logger.warning(f"画像がまだ準備されていません。この商品をスキップします: {e}")
                            end()  # step終了
                            fail_count += 1
                            continue  # 次の商品へ
                        except Exception as e:
                            logger.warning(f"パッケージ画像アップロード失敗: {e}")
                    
                    # シーン画像をアップロード（AI生成前に決定済みのscene_image_urlsを使用）
                    # アイキャッチ用: 顔がありつつエロいシーン（中盤〜後半を狙う）
                    eyecatch_url = None
                    if sample_pool:
                        # インデックス4-6あたりが「顔あり＋エロい」の確率が高い
                        # 画像枚数に応じて適切なインデックスを選択
                        if len(sample_pool) >= 10:
                            eyecatch_idx = 5  # 10枚以上なら5（中盤）
                        elif len(sample_pool) >= 8:
                            eyecatch_idx = 4  # 8-9枚なら4
                        elif len(sample_pool) >= 6:
                            eyecatch_idx = 3  # 6-7枚なら3
                        elif len(sample_pool) >= 4:
                            eyecatch_idx = 2  # 4-5枚なら2
                        else:
                            eyecatch_idx = 1 if len(sample_pool) >= 2 else 0  # 少ない場合
                        eyecatch_url = sample_pool[eyecatch_idx]
                        logger.info(f"アイキャッチ画像候補: インデックス {eyecatch_idx} を選択（顔あり＋エロ狙い）")
                    
                    new_sample_urls = []
                    for i, sample_url in enumerate(scene_image_urls[:3]):
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
                # STEP taxonomies (カテゴリ・タグ準備)
                # ────────────────────────────────────────────────────────────────
                end = step(f"taxonomies [{idx}/{len(items)}]")
                
                # ジャンルから大カテゴリを判定
                genres_raw = item.get("genre", [])
                genres_str = "".join(genres_raw)
                title_str = item.get("title", "")
                
                # 優先順位に基づいたマッピング
                mapping_order = [
                    ("VR作品", ["VR", "ハイクオリティVR"]),
                    ("アニメ・2D", ["アニメ", "二次元", "CG"]),
                    ("素人・ナンパ", ["素人", "ナンパ", "投稿", "地味"]),
                    ("熟女・人妻", ["熟女", "人妻", "お姉さん", "四十路", "美魔女", "お母さん"]),
                    ("美少女・若手", ["美少女", "若手", "新人", "10代", "女子大生"]),
                    ("巨乳・爆乳", ["巨乳", "爆乳", "爆にゅう"]),
                    ("単体女優", ["単体作品"]),
                    ("企画・バラエティ", ["企画", "バラエティー", "コスプレ"]),
                ]
                
                selected_big_cat = None
                
                # タイトルにVRが含まれていればVR作品を最優先
                if "VR" in title_str.upper():
                    selected_big_cat = "VR作品"
                else:
                    # 優先順位に従って判定
                    for big_cat, keywords in mapping_order:
                        if any(kw in genres_str for kw in keywords):
                            selected_big_cat = big_cat
                            break
                
                if not selected_big_cat:
                    selected_big_cat = "動画"  # 該当なしの場合のデフォルト
                
                # カテゴリIDとタグIDを取得
                category_ids, tag_ids = wp_client.prepare_taxonomies(
                    genres=[selected_big_cat],  # リスト形式で渡すが中身は1つ
                    actresses=item.get("actress", [])
                )
                end()

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
                    featured_media=featured_media_id,
                    categories=category_ids,
                    fanza_product_id=product_id
                )
                end()
                
                logger.info(f"投稿成功: wp_post_id={post_id}")
                # 投稿成功を記録
                dedupe_store.record_success(product_id, wp_post_id=post_id, status="drafted")
                success_count += 1
                posted_product_ids.append(product_id)
                
            except Exception as e:
                logger.exception(f"[{idx}/{len(items)}] 処理失敗: {e}")
                # 失敗を記録（リトライ用に別ステータス）
                dedupe_store.record_failure(product_id, str(e))
                fail_count += 1
                continue  # 次の商品へ
        
        # 最終結果サマリー
        logger.info("\n" + "=" * 60)
        if args.dry_run:
            logger.info("[SUCCESS] Dry-run completed!")
        else:
            logger.info("[SUCCESS] Post completed!")
        logger.info(f"   成功: {success_count} / 失敗: {fail_count} / 対象: {len(items)}")
        
        # 今回投稿したIDの一覧をログ出力
        if posted_product_ids:
            logger.info(f"今回投稿したID ({len(posted_product_ids)}件):")
            for pid in posted_product_ids:
                logger.info(f"   - {pid}")
        
        logger.info("=" * 60 + "\n")
        
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", flush=True)
        logger.exception(f"エラー発生: {e}")
        raise


if __name__ == "__main__":
    main()
