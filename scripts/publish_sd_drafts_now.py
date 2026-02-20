from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from dotenv import load_dotenv
from src.clients.wordpress import WPClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
load_dotenv(ROOT / ".env")

TARGET_SITES = [
    "sd01-chichi",
    "sd02-shirouto",
    "sd03-gyaru",
    "sd04-chijo",
    "sd05-seiso",
    "sd06-hitozuma",
    "sd07-oneesan",
    "sd08-jukujo",
    "sd09-iyashi",
    "sd10-otona",
]


@dataclass
class QueueItem:
    site: str
    post_id: int
    slug: str
    url_before: str
    status_before: str


def _site_env_key(subdomain: str, prefix: str) -> str:
    m = re.match(r"^(sd\d{2})-", str(subdomain or "").strip().lower())
    if not m:
        return ""
    return f"{prefix}_{m.group(1).upper()}"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_sites(raw_sites: str) -> list[str]:
    value = (raw_sites or "").strip().lower()
    if not value or value == "all":
        return list(TARGET_SITES)
    parsed = [s.strip() for s in value.split(",") if s.strip()]
    invalid = [s for s in parsed if s not in TARGET_SITES]
    if invalid:
        raise ValueError(f"Unknown site ids: {', '.join(invalid)}")
    return parsed


def _progress_path(output_dir: Path) -> Path:
    return output_dir / "progress.json"


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / "manifest.json"


def _default_progress() -> dict[str, Any]:
    return {
        "last_published_at": "",
        "total_published": 0,
        "per_site_published": {site: 0 for site in TARGET_SITES},
        "processed_post_ids": [],
    }


def _load_progress(output_dir: Path) -> dict[str, Any]:
    path = _progress_path(output_dir)
    if not path.exists():
        return _default_progress()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_progress()

    base = _default_progress()
    base["last_published_at"] = str(data.get("last_published_at", "") or "")
    base["total_published"] = int(data.get("total_published", 0) or 0)

    per_site = data.get("per_site_published", {})
    if isinstance(per_site, dict):
        for site in TARGET_SITES:
            base["per_site_published"][site] = int(per_site.get(site, 0) or 0)

    processed = data.get("processed_post_ids", [])
    if isinstance(processed, list):
        base["processed_post_ids"] = [int(v) for v in processed if str(v).isdigit()]
    return base


def _save_progress(output_dir: Path, progress: dict[str, Any]) -> None:
    payload = _default_progress()
    payload["last_published_at"] = str(progress.get("last_published_at", "") or "")
    payload["total_published"] = int(progress.get("total_published", 0) or 0)

    per_site = progress.get("per_site_published", {})
    if isinstance(per_site, dict):
        for site in TARGET_SITES:
            payload["per_site_published"][site] = int(per_site.get(site, 0) or 0)

    processed = progress.get("processed_post_ids", [])
    payload["processed_post_ids"] = sorted(set(int(v) for v in processed if str(v).isdigit()))
    _progress_path(output_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_manifest_entries(output_dir: Path) -> list[dict[str, Any]]:
    path = _manifest_path(output_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = data.get("entries", [])
    return entries if isinstance(entries, list) else []


def _save_manifest(
    output_dir: Path,
    *,
    selected_sites: list[str],
    status_filter: str,
    dry_run: bool,
    run_entries: list[dict[str, Any]],
    max_items: int,
) -> None:
    merged_entries = _load_manifest_entries(output_dir)
    merged_entries.extend(run_entries)
    payload = {
        "generated_at": _now_utc_iso(),
        "sites": selected_sites,
        "status_filter": status_filter,
        "dry_run": dry_run,
        "max_items": max_items,
        "entries": merged_entries,
    }
    _manifest_path(output_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _site_credentials(config, site_id: str) -> tuple[str, str]:
    user = config.wp_username
    pw = config.wp_app_password
    user_key = _site_env_key(site_id, "WP_USERNAME")
    pw_key = _site_env_key(site_id, "WP_APP_PASSWORD")
    site_user = (os.getenv(user_key) or "").strip() if user_key else ""
    site_pw = (os.getenv(pw_key) or "").strip() if pw_key else ""
    if site_user:
        user = site_user
        logger.info("[%s] credentials override: username key=%s", site_id, user_key)
    if site_pw:
        pw = site_pw
        logger.info("[%s] credentials override: password key=%s", site_id, pw_key)
    if not user or not pw:
        raise ValueError(
            f"missing credentials for {site_id} (expected WP_USERNAME/WP_APP_PASSWORD or {user_key}/{pw_key})"
        )
    return user, pw


@dataclass
class PublishConfig:
    base_dir: Path
    wp_username: str
    wp_app_password: str


def _load_publish_config() -> PublishConfig:
    wp_username = (os.getenv("WP_USERNAME") or "").strip()
    wp_app_password = (os.getenv("WP_APP_PASSWORD") or "").strip()
    return PublishConfig(
        base_dir=ROOT,
        wp_username=wp_username,
        wp_app_password=wp_app_password,
    )


def _post_sort_key(post: dict[str, Any]) -> tuple[datetime, int]:
    post_id = int(post.get("id", 0) or 0)
    raw = str(post.get("date", "") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except ValueError:
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return dt, post_id


def _build_site_queue(
    wp_client: WPClient,
    *,
    site_id: str,
    status_filter: str,
    max_pages: int,
    processed_ids: set[int],
) -> deque[QueueItem]:
    posts: list[dict[str, Any]] = []
    for post in wp_client.iter_posts(
        status=status_filter,
        per_page=100,
        max_pages=max_pages,
        fields="id,slug,link,status,date",
        context="edit",
    ):
        post_id = int(post.get("id", 0) or 0)
        if post_id in processed_ids:
            continue
        posts.append(post)

    posts.sort(key=_post_sort_key)
    q = deque()
    for post in posts:
        q.append(
            QueueItem(
                site=site_id,
                post_id=int(post.get("id", 0) or 0),
                slug=str(post.get("slug", "") or ""),
                url_before=str(post.get("link", "") or ""),
                status_before=str(post.get("status", "") or ""),
            )
        )
    return q


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish SD draft posts now (draft -> publish).")
    parser.add_argument("--sites", type=str, default="all")
    parser.add_argument("--max-items", type=int, default=0, help="0 means all available")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--status-filter", type=str, default="draft")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-progress", action="store_true")
    parser.add_argument("--output-dir", type=str, default="data/publish_sd_drafts")
    args = parser.parse_args()

    if args.max_pages <= 0:
        raise ValueError("--max-pages must be > 0")
    if args.status_filter.strip().lower() != "draft":
        raise ValueError("This publisher only supports --status-filter draft")

    selected_sites = _parse_sites(args.sites)
    status_filter = (args.status_filter or "draft").strip().lower()

    config = _load_publish_config()
    output_dir = (config.base_dir / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    progress = _load_progress(output_dir)
    if args.reset_progress:
        progress = _default_progress()
        _save_progress(output_dir, progress)
        logger.info("progress reset: %s", _progress_path(output_dir))

    processed_ids = set(int(v) for v in progress.get("processed_post_ids", []))
    site_clients: dict[str, WPClient] = {}
    site_queues: dict[str, deque[QueueItem]] = {}
    init_entries: list[dict[str, Any]] = []

    for site_id in selected_sites:
        try:
            user, pw = _site_credentials(config, site_id)
            wp_client = WPClient(f"https://{site_id}.av-kantei.com", user, pw)
            site_clients[site_id] = wp_client
            site_queues[site_id] = _build_site_queue(
                wp_client,
                site_id=site_id,
                status_filter=status_filter,
                max_pages=max(1, args.max_pages),
                processed_ids=processed_ids,
            )
            logger.info("[%s] queued drafts: %s", site_id, len(site_queues[site_id]))
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] queue init failed: %s", site_id, exc)
            init_entries.append(
                {
                    "site": site_id,
                    "post_id": 0,
                    "slug": "",
                    "url_before": "",
                    "status_before": "",
                    "action": "failed",
                    "reason": f"queue_init_failed:{exc}",
                    "updated_at": _now_utc_iso(),
                }
            )

    cycle_sites = deque([site for site in selected_sites if site_queues.get(site)])
    if not cycle_sites and not init_entries:
        logger.info("no target drafts found")
        return

    max_items = int(args.max_items or 0)
    run_entries: list[dict[str, Any]] = list(init_entries)
    assigned = 0

    while cycle_sites:
        if max_items > 0 and assigned >= max_items:
            break
        site_id = cycle_sites[0]
        queue = site_queues[site_id]
        if not queue:
            cycle_sites.popleft()
            continue

        item = queue.popleft()
        row = {
            "site": item.site,
            "post_id": item.post_id,
            "slug": item.slug,
            "url_before": item.url_before,
            "status_before": item.status_before,
            "action": "skipped",
            "reason": "",
            "updated_at": _now_utc_iso(),
        }

        if item.status_before != "draft":
            row["action"] = "skipped"
            row["reason"] = f"status_is_{item.status_before}"
        elif args.dry_run:
            row["action"] = "skipped"
            row["reason"] = "dry_run"
        else:
            wp = site_clients[site_id]
            try:
                latest = wp.get_post(item.post_id)
                latest_status = str(latest.get("status", "") or "")
                if latest_status != "draft":
                    row["action"] = "skipped"
                    row["reason"] = f"status_changed_to_{latest_status}"
                else:
                    wp.update_post(item.post_id, {"status": "publish"})
                    row["action"] = "updated"
                    row["reason"] = ""
            except Exception as exc:  # noqa: BLE001
                row["action"] = "failed"
                row["reason"] = str(exc)

        run_entries.append(row)
        progress["processed_post_ids"].append(item.post_id)
        if row["action"] == "updated":
            progress["last_published_at"] = _now_utc_iso()
            progress["total_published"] = int(progress.get("total_published", 0) or 0) + 1
            per_site = progress.get("per_site_published", {})
            per_site[site_id] = int(per_site.get(site_id, 0) or 0) + 1
            progress["per_site_published"] = per_site

        assigned += 1
        cycle_sites.rotate(-1)
        if not site_queues[site_id]:
            while cycle_sites and cycle_sites[0] == site_id:
                cycle_sites.popleft()
            if site_id in cycle_sites:
                cycle_sites.remove(site_id)

    _save_progress(output_dir, progress)
    _save_manifest(
        output_dir,
        selected_sites=selected_sites,
        status_filter=status_filter,
        dry_run=bool(args.dry_run),
        run_entries=run_entries,
        max_items=max_items,
    )

    updated = sum(1 for r in run_entries if r["action"] == "updated")
    skipped = sum(1 for r in run_entries if r["action"] == "skipped")
    failed = sum(1 for r in run_entries if r["action"] == "failed")
    logger.info("done: assigned=%s updated=%s skipped=%s failed=%s", len(run_entries), updated, skipped, failed)
    logger.info("progress: %s", _progress_path(output_dir))
    logger.info("manifest: %s", _manifest_path(output_dir))


if __name__ == "__main__":
    main()
