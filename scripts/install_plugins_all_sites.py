from __future__ import annotations

import argparse
import logging
import time
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts import configure_sites as cs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_PLUGINS = [
    "ewww-image-optimizer",
    "wp-fastest-cache",
    "wp-optimize",
]

SITE_ALIASES = {
    "sd1": "sd01-chichi",
    "sd01": "sd01-chichi",
    "sd2": "sd02-shirouto",
    "sd02": "sd02-shirouto",
    "sd3": "sd03-gyaru",
    "sd03": "sd03-gyaru",
    "sd4": "sd04-chijo",
    "sd04": "sd04-chijo",
    "sd5": "sd05-seiso",
    "sd05": "sd05-seiso",
    "sd6": "sd06-hitozuma",
    "sd06": "sd06-hitozuma",
    "sd7": "sd07-oneesan",
    "sd07": "sd07-oneesan",
    "sd8": "sd08-jukujo",
    "sd08": "sd08-jukujo",
    "sd9": "sd09-iyashi",
    "sd09": "sd09-iyashi",
    "sd10": "sd10-otona",
    "main": "av-kantei.com",
}

REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _request_with_retry(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    last_res: requests.Response | None = None
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if res.status_code in RETRY_STATUSES:
                last_res = res
                logger.warning("%s %s -> %s (attempt %s/%s)", method, url, res.status_code, attempt, MAX_RETRIES)
                time.sleep(1.5 * attempt)
                continue
            return res
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("%s %s failed (attempt %s/%s): %s", method, url, attempt, MAX_RETRIES, exc)
            time.sleep(1.5 * attempt)

    if last_res is not None:
        return last_res
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request failed")


def _wp_v2_urls(base_url: str, endpoint: str) -> list[str]:
    ep = endpoint.strip("/")
    return [
        f"{base_url}/wp-json/wp/v2/{ep}",
        f"{base_url}/?rest_route=/wp/v2/{ep}",
    ]


def _wp_v2_request(session: requests.Session, method: str, base_url: str, endpoint: str, **kwargs) -> requests.Response:
    last: requests.Response | None = None
    for url in _wp_v2_urls(base_url, endpoint):
        res = _request_with_retry(session, method, url, **kwargs)
        last = res
        # Try fallback route only when canonical wp-json route is unavailable.
        if res.status_code == 404:
            continue
        return res
    if last is None:
        raise RuntimeError("request failed")
    return last


def _plugin_map(session: requests.Session, base_url: str) -> dict[str, dict]:
    res = _wp_v2_request(session, "GET", base_url, "plugins")
    res.raise_for_status()
    rows = res.json() or []
    return {str(p.get("plugin", "")).split("/")[0]: p for p in rows}


def install_plugins(base_url: str, plugins: list[str], apply_changes: bool) -> tuple[int, int]:
    session = requests.Session()
    session.auth = (cs.WP_USERNAME, cs.WP_APP_PASSWORD)

    installed_or_active = 0
    failed = 0

    existing = _plugin_map(session, base_url)
    for slug in plugins:
        try:
            if slug in existing:
                plugin_file = existing[slug].get("plugin", f"{slug}/{slug}")
                status = existing[slug].get("status")
                if status == "active":
                    logger.info("%s %s already active", base_url, slug)
                    installed_or_active += 1
                    continue
                if not apply_changes:
                    logger.info("%s %s would activate", base_url, slug)
                    installed_or_active += 1
                    continue
                res = _wp_v2_request(
                    session,
                    "POST",
                    base_url,
                    f"plugins/{plugin_file}",
                    json={"status": "active"},
                )
                if res.status_code >= 300:
                    logger.error("%s %s activate failed: %s %s", base_url, slug, res.status_code, res.text[:240])
                    failed += 1
                    continue
                logger.info("%s %s activated", base_url, slug)
                installed_or_active += 1
                continue

            if not apply_changes:
                logger.info("%s %s would install+activate", base_url, slug)
                installed_or_active += 1
                continue

            res = _wp_v2_request(
                session,
                "POST",
                base_url,
                "plugins",
                json={"slug": slug, "status": "active"},
            )
            if res.status_code >= 300:
                logger.error("%s %s install failed: %s %s", base_url, slug, res.status_code, res.text[:240])
                failed += 1
                continue
            logger.info("%s %s installed+activated", base_url, slug)
            installed_or_active += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("%s %s failed: %s", base_url, slug, exc)
            failed += 1

    return installed_or_active, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Install and activate WordPress plugins across SD sites.")
    parser.add_argument("--site", default="", help="Single subdomain target (e.g. sd01-chichi)")
    parser.add_argument("--include-main", action="store_true", help="Also run for https://av-kantei.com")
    parser.add_argument(
        "--plugins",
        default=",".join(DEFAULT_PLUGINS),
        help=f"Comma-separated plugin slugs (default: {','.join(DEFAULT_PLUGINS)})",
    )
    parser.add_argument("--apply", action="store_true", help="Actually install/activate. Default is dry-run.")
    args = parser.parse_args()

    plugins = [p.strip() for p in args.plugins.split(",") if p.strip()]
    if not plugins:
        raise ValueError("plugins is empty")

    targets: list[str] = []
    if args.site:
        key = args.site.strip().lower()
        resolved = SITE_ALIASES.get(key, args.site.strip())
        if resolved == "av-kantei.com":
            targets.append("https://av-kantei.com")
        elif resolved.startswith("http://") or resolved.startswith("https://"):
            targets.append(resolved)
        elif "." in resolved:
            targets.append(f"https://{resolved}")
        else:
            targets.append(f"https://{resolved}.av-kantei.com")
    else:
        targets.extend([f"https://{s.subdomain}.av-kantei.com" for s in cs.SITES if s.subdomain.startswith("sd")])
    if args.include_main:
        targets.append("https://av-kantei.com")

    ok = 0
    ng = 0
    for base_url in targets:
        logger.info("=== target: %s (apply=%s) ===", base_url, args.apply)
        installed_or_active, failed = install_plugins(base_url, plugins, apply_changes=args.apply)
        logger.info(
            "%s result: requested=%s ok=%s failed=%s",
            base_url,
            len(plugins),
            installed_or_active,
            failed,
        )
        ok += installed_or_active
        ng += failed

    logger.info("ALL DONE: ok=%s failed=%s", ok, ng)


if __name__ == "__main__":
    main()
