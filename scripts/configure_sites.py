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
        title="乳ラブ",
        tagline="巨乳・爆乳専門動画サイト",
        color="pink",
        keywords=[
            "巨乳", "爆乳", "着衣巨乳",
            "おっぱい", "パイズリ", "乳首", "バスト", "美乳",
            "Iカップ", "Jカップ", "Kカップ", "Lカップ",
            "Dカップ", "Eカップ", "Fカップ", "Gカップ", "Hカップ"
        ],
        affiliate_id=None,
    ),
    SiteConfig(subdomain="sd02-shirouto", title="素人図鑑", tagline="素人系AV動画まとめ", color="cyan", keywords=["素人", "マジックミラー", "ナンパ", "投稿", "ハメ撮り"], affiliate_id=None),
    SiteConfig(subdomain="sd03-gyaru", title="ギャルパラダイス", tagline="ギャル系動画まとめ", color="yellow", keywords=["ギャル", "コギャル", "金髪", "ガングロ"], affiliate_id=None),
    SiteConfig(subdomain="sd04-chijo", title="痴女マニア", tagline="痴女・露出系動画", color="red", keywords=["痴女", "露出", "野外", "羞恥"], affiliate_id=None),
    SiteConfig(subdomain="sd05-seiso", title="清楚コレクション", tagline="清楚・お嬢様系", color="green", keywords=["清楚", "お嬢様", "黒髪", "美少女"], affiliate_id=None),
    SiteConfig(subdomain="sd06-hitozuma", title="人妻の秘め事", tagline="人妻・不倫系", color="brown", keywords=["人妻", "不倫", "寝取られ", "未亡人"], affiliate_id=None),
    SiteConfig(subdomain="sd07-oneesan", title="お姉さん日和", tagline="お姉さん・女教師系", color="blue", keywords=["お姉さん", "女教師", "OL", "キャンギャル"], affiliate_id=None),
    SiteConfig(subdomain="sd08-jukujo", title="熟女の館", tagline="熟女・美魔女", color="orange", keywords=["熟女", "美魔女", "母", "義母"], affiliate_id=None),
    SiteConfig(subdomain="sd09-iyashi", title="癒しの泉", tagline="癒し・マッサージ系", color="purple", keywords=["癒し", "マッサージ", "エステ", "奉仕"], affiliate_id=None),
    SiteConfig(
        subdomain="sd10-otona",
        title="大人の嗜み",
        tagline="高画質・ハイエンドAV",
        color="teal",
        keywords=[
            "ハイレゾ", "4K", "高級", "セレブ", "VR",
            "合コン", "オフ会", "同窓会", "社員旅行", "温泉旅行",
            "学園祭", "企画", "パーティー", "撮影会"
        ],
        affiliate_id=None,
    ),
]

def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value

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
    wp_username = _required_env("WP_USERNAME")
    wp_app_password = _required_env("WP_APP_PASSWORD")
    credentials = f"{wp_username}:{wp_app_password}"
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
