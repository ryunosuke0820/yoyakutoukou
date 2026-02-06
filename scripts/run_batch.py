"""
実行バッチ
"""
import argparse
import logging
import sys
import time
import io
import random
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from pathlib import Path

# srcルートをパスに追加
sys.path.append(str(Path(__file__).parent.parent))

from src.core.config import get_config
from src.clients.fanza import FanzaClient
from src.clients.wordpress import WPClient
from src.clients.openai import OpenAIClient
from src.processor.renderer import Renderer
from src.processor.images import ImageTools
from src.database.dedupe import DedupeStore
from src.services.poster import PosterService
from scripts.configure_sites import get_site_config

def setup_logging(level: str) -> None:
    # WindowsのコンソールでUnicodeEncodeErrorが発生するのを防ぐ
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(errors="replace")

    # ハンドラーの作成
    stream_handler = logging.StreamHandler(sys.stdout)

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            stream_handler,
            logging.FileHandler("fanza_bot.log", encoding="utf-8"),
        ],
    )

def _parse_iso_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

def sync_wp_cache(
    wp_client: WPClient,
    dedupe_store: DedupeStore,
    logger: logging.Logger,
    force_full: bool = False,
    overlap_hours: int = 6,
    max_pages: int | None = None,
) -> None:
    """WP投稿をローカルDBに同期（初回フル、以後は増分）"""
    last_sync_raw = dedupe_store.get_meta("wp_last_sync_at")
    after = None

    if force_full or not last_sync_raw:
        logger.info("WP同期: フル同期を実行します")
    else:
        last_sync = _parse_iso_dt(last_sync_raw)
        if last_sync:
            after_dt = last_sync - timedelta(hours=overlap_hours)
            after = after_dt.isoformat()
            logger.info(f"WP同期: 増分同期 after={after} (last_sync={last_sync_raw})")
        else:
            logger.warning("WP同期: last_syncが不正なためフル同期に切り替えます")

    posts_scanned = 0
    items: list[tuple[str, int | None]] = []
    seen_fanza: set[str] = set()

    for post in wp_client.iter_posts(
        status="any",
        per_page=100,
        max_pages=max_pages,
        after=after,
        fields="id,slug,meta,content",
        context="edit",
    ):
        posts_scanned += 1
        fanza_id = wp_client.extract_fanza_id(post)
        if fanza_id and fanza_id not in seen_fanza:
            items.append((fanza_id, post.get("id")))
            seen_fanza.add(fanza_id)

    inserted = dedupe_store.bulk_mark_posted(items, status="published")
    dedupe_store.set_meta("wp_last_sync_at", datetime.now(timezone.utc).isoformat())
    logger.info(f"WP同期完了: scanned={posts_scanned}, cached={len(items)}, inserted={inserted}")

def main():
    parser = argparse.ArgumentParser(description="FANZA → WordPress 自動記事投稿")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--sort", type=str, default="date")
    parser.add_argument("--since", type=str)
    parser.add_argument("--subdomain", type=str, help="対象のサブドメイン (例: sd01-chichi)")
    parser.add_argument("--dedupe-key", type=str, default="", help="投稿済みDBキーを明示指定 (例: main)")
    parser.add_argument("--sync-full", action="store_true", help="WP投稿キャッシュを全件同期")
    parser.add_argument("--sync-overlap-hours", type=int, default=6)
    parser.add_argument("--sync-max-pages", type=int, default=0, help="WP同期の最大ページ(0で無制限)")
    parser.add_argument("--fetch-max-pages", type=int, default=10, help="FANZA取得の最大ページ")
    args = parser.parse_args()
    
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    config = get_config()

    # サブドメイン指定がある場合、設定を上書き
    site_keywords = None
    keyword_list: list[str] | None = None
    site_info = None
    resolved_subdomain = args.subdomain
    if args.subdomain:
        subdomain_alias = {
            "sd1": "sd01-chichi",
        }
        resolved_subdomain = subdomain_alias.get(args.subdomain, args.subdomain)
        site_info = get_site_config(resolved_subdomain)
        if site_info:
            logger.info(f"サイト設定適用: {site_info.title} ({resolved_subdomain})")
            config.wp_base_url = f"https://{resolved_subdomain}.av-kantei.com"
            # Use multiple keywords by cycling, instead of AND search
            keyword_list = [kw for kw in site_info.keywords if kw]
            if keyword_list:
                logger.info(f"???????: {' '.join(keyword_list)}")
            else:
                site_keywords = None
        else:
            logger.error(f"サブドメイン {resolved_subdomain} の設定が見つかりません。")
            sys.exit(1)
    
    # アフィリエイトIDの決定
    affiliate_id = config.fanza_affiliate_id
    if site_info and site_info.affiliate_id:
        affiliate_id = site_info.affiliate_id
        logger.info(f"サイト固有のアフィリエイトIDを使用: {affiliate_id}")

    fanza_client = FanzaClient(config.fanza_api_key, affiliate_id)
    llm_client = OpenAIClient(config.openai_api_key, config.openai_model, config.prompts_dir, config.base_dir / "viewpoints.json")
    wp_client = WPClient(config.wp_base_url, config.wp_username, config.wp_app_password)
    renderer = Renderer(config.base_dir / "layout_premium")
    dedupe_key = args.dedupe_key.strip() or resolved_subdomain or "default"
    dedupe_store = DedupeStore(config.data_dir / f"posted_{dedupe_key}.sqlite3")
    image_tools = ImageTools()
    
    poster_service = PosterService(config, fanza_client, wp_client, llm_client, renderer, dedupe_store, image_tools)
    
    logger.info("=" * 60)
    logger.info(f"開始: limit={args.limit}, dry_run={args.dry_run}, site={dedupe_key}")
    
    sync_max_pages = None if args.sync_max_pages <= 0 else args.sync_max_pages
    sync_wp_cache(
        wp_client,
        dedupe_store,
        logger,
        force_full=args.sync_full,
        overlap_hours=args.sync_overlap_hours,
        max_pages=sync_max_pages,
    )

    # 候補取得
    target_count = args.limit
    candidate_pool_size = max(target_count * 5, 80)
    all_items = []
    
    seen_pids: set[str] = set()
    
    page = 0
    max_fetch_pages = max(args.fetch_max_pages, 1)
    if keyword_list:
        for kw in keyword_list:
            page = 0
            while len(all_items) < candidate_pool_size and page < max_fetch_pages:
                batch = fanza_client.fetch(
                    limit=100,
                    since=args.since,
                    sort=args.sort,
                    keyword=kw,
                    offset=page * 100,
                )
                if not batch:
                    break
                for item in batch:
                    pid = item['product_id']
                    pid_norm = str(pid).lower()
                    if pid_norm in seen_pids:
                        continue
                    seen_pids.add(pid_norm)
                    if not dedupe_store.is_posted(pid_norm):
                        all_items.append(item)
                    if len(all_items) >= candidate_pool_size:
                        break
                page += 1
            if len(all_items) >= candidate_pool_size:
                break
    else:
        while len(all_items) < candidate_pool_size and page < max_fetch_pages:
            batch = fanza_client.fetch(
                limit=100,
                since=args.since,
                sort=args.sort,
                keyword=site_keywords,
                offset=page * 100,
            )
            if not batch:
                break
            for item in batch:
                pid = item['product_id']
                pid_norm = str(pid).lower()
                if pid_norm in seen_pids:
                    continue
                seen_pids.add(pid_norm)
                if not dedupe_store.is_posted(pid_norm):
                    all_items.append(item)
                if len(all_items) >= candidate_pool_size:
                    break
            page += 1
    random.shuffle(all_items)
    items = all_items[:target_count]
    logger.info(f"処理対象: {len(items)}件 (候補プール: {len(all_items)}件からランダム選定)")
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    with tqdm(total=len(items), desc="全体進捗", unit="件") as pbar:
        for idx, item in enumerate(items, 1):
            pbar.set_postfix_str(f"処理中: {item['product_id']}")
            try:
                res = poster_service.process_item(idx, len(items), item, dry_run=args.dry_run, site_info=site_info if args.subdomain else None)
                if res == "success":
                    success_count += 1
                elif res == "skip":
                    skip_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"予期せぬエラー: {item['product_id']} - {e}")
                fail_count += 1
            pbar.update(1)
            
    logger.info(f"結果: 成功={success_count}, 失敗={fail_count}, スキップ={skip_count}")

if __name__ == "__main__":
    main()
