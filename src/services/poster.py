"""
投稿統合サービス
"""
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

from src.core.models import Product, AIResponse
from src.core.config import Config
from src.clients.fanza import FanzaClient
from src.clients.wordpress import WPClient
from src.clients.openai import OpenAIClient
from src.database.dedupe import DedupeStore
from src.processor.renderer import Renderer
from src.processor.images import ImageTools, ImagePlaceholderError


logger = logging.getLogger(__name__)

class PosterService:
    """記事投稿のワークフローを管理"""
    
    def __init__(
        self,
        config: Config,
        fanza_client: FanzaClient,
        wp_client: WPClient,
        llm_client: OpenAIClient,
        renderer: Renderer,
        dedupe_store: DedupeStore,
        image_tools: ImageTools,
    ):
        self.config = config
        self.fanza_client = fanza_client
        self.wp_client = wp_client
        self.llm_client = llm_client
        self.renderer = renderer
        self.dedupe_store = dedupe_store
        self.image_tools = image_tools

    def process_item(self, idx: int, total: int, item: dict, dry_run: bool = False, site_info: Any = None) -> str:
        """1件の商品を処理して投稿する"""
        product_id = str(item['product_id']).lower()
        item['product_id'] = product_id
        try:
            # 既に投稿済み/処理中なら開始しない（原子的に確保）
            if not self.dedupe_store.try_start(product_id):
                logger.info(f"duplicate/processing skip: {product_id}")
                return "skip"
            sys.stdout.flush()
            
            # 最終チェック: すでにWP側に記事がないか確認
            if not dry_run:
                if self.wp_client.check_post_exists_by_fanza_id(product_id):
                    logger.info(f"スキップ: すでに同じFANZA IDの記事が存在します (WP側): {product_id}")
                    # ローカルDB側も成功扱いとして記録（次回以降is_postedで弾けるようにする）
                    self.dedupe_store.record_success(product_id, status="drafted")
                    return "skip"
                    
                if self.wp_client.check_post_exists_by_slug(product_id):
                    logger.info(f"スキップ: すでにWordPress上に記事が存在します (slug match): {product_id}")
                    self.dedupe_store.record_success(product_id, status="drafted")
                    return "skip"

            # シーン用の画像URLを決定
            sample_pool = item.get("sample_image_urls", [])
            if not sample_pool:
                logger.warning(f"サンプル画像が1枚もないためスキップします: {product_id}")
                return "skip"
            
            targets = [2, 5, 8]
            scene_image_urls = []
            for t in targets:
                if t < len(sample_pool):
                    scene_image_urls.append(sample_pool[t])
            
            if len(scene_image_urls) < 3:
                for url in sample_pool:
                    if url not in scene_image_urls:
                        scene_image_urls.append(url)
                    if len(scene_image_urls) >= 3:
                        break
            
            logger.info(f"シーン用画像: {len(scene_image_urls)}枚を選択")
            
            # AI生成 (site_info を渡す)
            ai_response = self.llm_client.generate(item=item, sample_image_urls=scene_image_urls, site_info=site_info)
            sys.stdout.flush()
            
            logger.info(f"AI応答取得完了: title={ai_response.get('title', '')[:30]}...")
            
            # 画像アップロード
            featured_media_id = None
            package_media_id = None
            use_cdn_images = os.environ.get("USE_CDN_IMAGES", "").lower() == "true"
            require_featured_media = os.environ.get("REQUIRE_FEATURED_MEDIA", "true").lower() != "false"
            
            if use_cdn_images:
                logger.info("USE_CDN_IMAGES=true: 画像アップロードをスキップしてCDN URLを直接使用")
                # パッケージ画像はそのまま (FANZA CDN URL)
                # シーン画像もそのまま使用
                item["sample_image_urls"] = scene_image_urls[:3]
                # アイキャッチ欠損防止のため、最低1枚だけはWPメディアにアップロードしてfeatured_mediaを確保する。
                if not dry_run and item.get("package_image_url"):
                    try:
                        img_bytes, filename, mime_type = self.image_tools.download_to_bytes(item["package_image_url"])
                        result = self.wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                        featured_media_id = result.get("id")
                        logger.info(f"USE_CDN_IMAGES時のアイキャッチ確保アップロード完了: media_id={featured_media_id}")
                    except ImagePlaceholderError as e:
                        logger.warning(f"アイキャッチ用画像が未準備のためスキップ: {e}")
                        return "skip"
                    except Exception as e:
                        logger.error(f"USE_CDN_IMAGES時のアイキャッチ確保アップロード失敗: {e}")
                item["_featured_media_id"] = featured_media_id
            elif not dry_run:
                if item.get("package_image_url"):
                    try:
                        img_bytes, filename, mime_type = self.image_tools.download_to_bytes(item["package_image_url"])
                        result = self.wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                        item["package_image_url"] = result.get("source_url", item["package_image_url"])
                        package_media_id = result.get("id")
                        logger.info(f"パッケージ画像アップロード完了: {item['package_image_url']}")
                    except ImagePlaceholderError as e:
                        logger.warning(f"画像がまだ準備されていません。スキップ: {e}")
                        return "skip"
                
                # 画像アップロードの並列化
                new_sample_urls = [None] * len(scene_image_urls[:3])
                
                def upload_task(url, index, is_featured=False):
                    try:
                        img_bytes, filename, mime_type = self.image_tools.download_to_bytes(url)
                        result = self.wp_client.upload_media(file_bytes=img_bytes, filename=filename, mime_type=mime_type)
                        return {"index": index, "url": result.get("source_url", url), "id": result.get("id"), "is_featured": is_featured}
                    except ImagePlaceholderError as e:
                        logger.warning(f"画像プレースホルダーにつきスキップ: {url}")
                        return {"error": "placeholder", "index": index}
                    except Exception as e:
                        logger.error(f"画像アップロード失敗: {url} - {e}")
                        # アップロード失敗時はオリジナルのCDN URLをフォールバックとして使用
                        return {"index": index, "url": url, "id": None, "is_featured": is_featured, "fallback": True}

                upload_jobs = []
                # シーン画像
                for i, sample_url in enumerate(scene_image_urls[:3]):
                    upload_jobs.append((sample_url, i, False))
                # アイキャッチ
                eyecatch_url = None
                if sample_pool:
                    indices = [10, 8, 6, 4, 2]
                    eyecatch_idx = 0
                    for threshold in indices:
                        if len(sample_pool) >= threshold:
                            eyecatch_idx = threshold // 2
                            break
                    eyecatch_url = sample_pool[eyecatch_idx]
                    upload_jobs.append((eyecatch_url, -1, True)) # -1 is eyecatch

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(upload_task, job[0], job[1], job[2]) for job in upload_jobs]
                    for future in as_completed(futures):
                        res = future.result()
                        if "error" in res:
                            if res["error"] == "placeholder": return "skip"
                            continue
                        
                        if res["is_featured"]:
                            featured_media_id = res["id"]
                            logger.info(f"アイキャッチ画像アップロード完了: media_id={featured_media_id}")
                        else:
                            new_sample_urls[res["index"]] = res["url"]
                            logger.info(f"サンプル画像{res['index']+1}アップロード完了")

                # アイキャッチ専用画像のアップロードに失敗した場合は、
                # 既にアップロード済みのパッケージ画像をフォールバックで利用する。
                if not featured_media_id and package_media_id:
                    featured_media_id = package_media_id
                    logger.warning(
                        f"アイキャッチ画像IDが未取得のためパッケージ画像を代替利用: media_id={featured_media_id}"
                    )

                item["sample_image_urls"] = [u for u in new_sample_urls if u is not None]
                item["_featured_media_id"] = featured_media_id

            # コンテンツレンダリング
            site_id = "default"
            if site_info and hasattr(site_info, "subdomain"):
                site_id = site_info.subdomain

            category_ids: list[int] = []
            tag_ids: list[int] = []
            related_posts: list[dict] = []

            # タクソノミー準備 (dry_run時は作成しない)
            genres_raw = item.get("genre", [])
            genres_str = "".join(genres_raw)
            title_str = item.get("title", "")

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
            selected_big_cat = "動画"
            if "VR" in title_str.upper():
                selected_big_cat = "VR作品"
            else:
                for big_cat, keywords in mapping_order:
                    if any(kw in genres_str for kw in keywords):
                        selected_big_cat = big_cat
                        break

            if not dry_run:
                category_ids, tag_ids = self.wp_client.prepare_taxonomies(
                    genres=[selected_big_cat],
                    actresses=item.get("actress", [])
                )
            else:
                # dry_runでは作成せず既存タグのみ参照
                for actress in item.get("actress", []) or []:
                    tag_id = self.wp_client.get_tag_id(actress)
                    if tag_id:
                        tag_ids.append(tag_id)

            # related posts scoring
            try:
                site_decor = self.renderer._get_site_decor(site_id)
                priority = site_decor.get("related", {}).get("priority")
                related_posts = self.wp_client.find_related_posts(
                    priority=priority,
                    tag_ids=tag_ids,
                    category_ids=category_ids,
                    limit=6,
                    exclude_fanza_id=product_id,
                )
            except Exception as e:
                logger.warning(f"related posts fetch failed: {e}")
            
            content_html = self.renderer.render_post_content(
                item,
                ai_response,
                site_id=site_id,
                related_posts=related_posts,
            )

            if dry_run:
                logger.info("【ドライラン】WP投稿をスキップ")
                
                # プレビュー保存
                try:
                    preview_path = self.config.base_dir / f"preview_{site_id}.html"
                    # プレビュー用にメタタグを追加した完全なHTMLにする
                    full_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Preview {site_id}</title>
<style>
body {{ max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif; background: #eee; }}
.aa-wrap {{ background: #fff; margin: 0 auto; }}
</style>
</head>
<body>
{content_html}
</body>
</html>"""
                    preview_path.write_text(full_html, encoding="utf-8")
                    logger.info(f"【ドライラン】プレビューHTMLを保存しました: {preview_path}")
                except Exception as e:
                    logger.warning(f"プレビュー保存失敗: {e}")

                self.dedupe_store.record_success(product_id, wp_post_id=None, status="dry_run")
                return "success"

            # アイキャッチ無し投稿は避ける。取得できなかった場合は投稿を中断する。
            if require_featured_media and not item.get("_featured_media_id"):
                raise RuntimeError(f"featured_media未設定のため投稿中断: product_id={product_id}")
            
            # WordPress投稿
            actresses = item.get("actress", [])
            if actresses:
                custom_slug = f"{actresses[0].replace(' ', '').replace('/', '-')}-{product_id}"
            else:
                custom_slug = f"video-{product_id}"
                
            post_id = self.wp_client.post_draft(
                title=item["title"], 
                content=content_html,
                excerpt=ai_response.get("short_description", ""),
                slug=custom_slug,
                featured_media=item.get("_featured_media_id"),
                categories=category_ids,
                tags=tag_ids,
                fanza_product_id=product_id
            )
            
            self.dedupe_store.record_success(product_id, wp_post_id=post_id, status="drafted")
            return "success"
                
        except Exception as e:
            logger.exception(f"[{idx}/{total}] 処理失敗: {e}")
            self.dedupe_store.record_failure(product_id, str(e))
            return "failure"
