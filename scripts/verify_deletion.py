import io
import logging
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from scripts.configure_sites import SITES
from src.clients.wordpress import WPClient
from src.core.config import get_config

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def check_posts(base_url: str, label: str) -> None:
    wp_client = WPClient(
        base_url=base_url,
        username=_required_env("WP_USERNAME"),
        app_password=_required_env("WP_APP_PASSWORD"),
    )
    try:
        posts = wp_client.get_recent_posts(limit=1, status="any")
        if len(posts) == 0:
            logger.info("[%s] %s: 0 posts (Clean)", label, base_url)
        else:
            logger.info("[%s] %s: Found posts! Still has content.", label, base_url)
    except Exception as exc:
        logger.error("[%s] Error checking %s: %s", label, base_url, exc)


def main() -> None:
    _required_env("WP_USERNAME")
    _required_env("WP_APP_PASSWORD")

    config = get_config()
    logger.info("Verifying post counts...")

    check_posts(config.wp_base_url, "MAIN SITE")
    for site in SITES:
        check_posts(f"https://{site.subdomain}.av-kantei.com", f"SUBDOMAIN: {site.subdomain}")

    logger.info("Verification completed.")


if __name__ == "__main__":
    main()
