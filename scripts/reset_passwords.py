import io
import logging
import os
import sys
from pathlib import Path

# Make local package importable when run as script.
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from scripts.configure_sites import SITES
from src.clients.wordpress import WPClient

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


def reset_password(site) -> None:
    base_url = f"https://{site.subdomain}.av-kantei.com"
    wp = WPClient(
        base_url=base_url,
        username=_required_env("WP_USERNAME"),
        app_password=_required_env("WP_APP_PASSWORD"),
    )
    wp.update_post  # keep import usage explicit for linters

    import base64
    import requests

    api_url = f"{base_url}/wp-json/wp/v2/users/1"
    credentials = f"{_required_env('WP_USERNAME')}:{_required_env('WP_APP_PASSWORD')}"
    encoded = base64.b64encode(credentials.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }
    data = {"password": _required_env("NEW_LOGIN_PASSWORD")}

    try:
        logger.info("Resetting login password for %s (%s)...", site.title, base_url)
        response = requests.post(api_url, json=data, headers=headers, timeout=10)
        if response.status_code == 200:
            logger.info("Successfully reset password for %s", site.subdomain)
        else:
            logger.error("Failed to reset %s: %s %s", site.subdomain, response.status_code, response.text)
    except Exception as exc:
        logger.error("Error resetting %s: %s", site.subdomain, exc)


def main() -> None:
    # Fail fast before looping.
    _required_env("WP_USERNAME")
    _required_env("WP_APP_PASSWORD")
    _required_env("NEW_LOGIN_PASSWORD")

    logger.info("Starting password resets for all 10 sites...")
    for site in SITES:
        reset_password(site)
    logger.info("Finished.")


if __name__ == "__main__":
    main()
