import os
import sys
import logging
import requests
import base64
from dataclasses import dataclass

# ????
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SiteConfig:
    subdomain: str
    title: str
    tagline: str
    color: str
    keywords: list[str]  # FANZA????????
    affiliate_id: str = None  # ?????????????ID (None????????????)

# ??????
SITES = [
    SiteConfig(
        subdomain="sd01-chichi",
        title="???",
        tagline="",
        color="???",
        keywords=[
            "??",
            "??",
            "????",
            "????",
            "????",
            "??",
            "???",
            "??",
            "D???",
            "E???",
            "F???",
            "G???",
            "H???",
            "I???",
            "J???",
            "K???",
            "L???",
        ],
        affiliate_id=None,
    ),
    SiteConfig(subdomain="sd02-shirouto", title="?????", tagline="", color="??", keywords=["??", "???", "??"], affiliate_id=None),
    SiteConfig(subdomain="sd03-gyaru", title="??????", tagline="", color="??", keywords=["???", "????"], affiliate_id=None),
    SiteConfig(subdomain="sd04-chijo", title="??????", tagline="", color="?", keywords=["??", "??", "??"], affiliate_id=None),
    SiteConfig(subdomain="sd05-seiso", title="????", tagline="", color="?", keywords=["??", "???", "???"], affiliate_id=None),
    SiteConfig(subdomain="sd06-hitozuma", title="????", tagline="", color="??????", keywords=["??", "??"], affiliate_id=None),
    SiteConfig(subdomain="sd07-oneesan", title="??????", tagline="", color="?", keywords=["????", "??", "??"], affiliate_id=None),
    SiteConfig(subdomain="sd08-jukujo", title="????", tagline="", color="??", keywords=["??", "???"], affiliate_id=None),
    SiteConfig(subdomain="sd09-iyashi", title="?????", tagline="", color="?????", keywords=["???", "?????", "???"], affiliate_id=None),
    SiteConfig(subdomain="sd10-otona", title="?????", tagline="", color="?????", keywords=["????", "??", "????"], affiliate_id=None),
]

# WordPress???????.env???
WP_USERNAME = "moco"
WP_APP_PASSWORD = "LS3q H0qN 6PNB dTHN W07W iHh3"

def get_site_config(subdomain: str) -> SiteConfig | None:
    """????????????????"""
    for site in SITES:
        if site.subdomain == subdomain:
            return site
    return None

def update_site_settings(site: SiteConfig):
    base_url = f"https://{site.subdomain}.av-kantei.com"
    api_url = f"{base_url}/wp-json/wp/v2/settings"

    # Basic??????
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded = base64.b64encode(credentials.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json"
    }

    data = {
        "title": site.title,
        "description": site.tagline
    }

    try:
        logger.info(f"Updating settings for {base_url}...")
        response = requests.post(api_url, json=data, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"Successfully updated title/tagline for {site.subdomain}")

            # ????
            verify_res = requests.get(api_url, headers=headers, timeout=10)
            if verify_res.status_code == 200:
                current = verify_res.json()
                if current.get("title") == site.title:
                    logger.info(f"Verification Success: {site.subdomain} is now '{site.title}'")
                else:
                    logger.warning(f"Verification Mismatch: Expected '{site.title}', got '{current.get('title')}'")
        else:
            logger.error(f"Failed to update {site.subdomain}: {response.status_code} {response.text}")

    except Exception as e:
        logger.error(f"Error updating {site.subdomain}: {e}")

def main():
    logger.info("Starting site configuration updates...")
    for site in SITES:
        update_site_settings(site)
    logger.info("All site updates completed.")

if __name__ == "__main__":
    main()
