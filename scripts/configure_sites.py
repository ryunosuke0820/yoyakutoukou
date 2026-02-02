import os
import sys
import logging
import requests
import base64
from dataclasses import dataclass

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SiteConfig:
    subdomain: str
    title: str
    tagline: str
    color: str
    keywords: list[str] # FANZA検索用キーワード
    affiliate_id: str = None # サイト固有のアフィリエイトID (Noneの場合はデフォルトを使用)

# サイトのリスト定義
# サイトのリスト定義
SITES = [
    SiteConfig(subdomain="sd01-chichi", title="乳ラブ", tagline="", color="ピンク", keywords=["巨乳", "爆乳", "着衣巨乳"], affiliate_id=None),
    SiteConfig(subdomain="sd02-shirouto", title="素人専門屋", tagline="", color="水色", keywords=["素人", "ナンパ", "投稿"], affiliate_id=None),
    SiteConfig(subdomain="sd03-gyaru", title="ギャルしか！", tagline="", color="黄色", keywords=["ギャル", "黒ギャル"], affiliate_id=None),
    SiteConfig(subdomain="sd04-chijo", title="痴女プリーズ", tagline="", color="赤", keywords=["痴女", "誘惑", "露出"], affiliate_id=None),
    SiteConfig(subdomain="sd05-seiso", title="清楚特集", tagline="", color="白", keywords=["清楚", "お嬢様", "美少女"], affiliate_id=None),
    SiteConfig(subdomain="sd06-hitozuma", title="人妻・愛", tagline="", color="ワインレッド", keywords=["人妻", "不倫"], affiliate_id=None),
    SiteConfig(subdomain="sd07-oneesan", title="??????", tagline="", color="紺", keywords=["??????", "????", "?"], affiliate_id=None),
    SiteConfig(subdomain="sd08-jukujo", title="熟女の家", tagline="", color="茶色", keywords=["熟女", "美魔女"], affiliate_id=None),
    SiteConfig(subdomain="sd09-iyashi", title="夜の癒し♡", tagline="", color="ラベンダー", keywords=["癒やし", "マッサージ", "エステ"], affiliate_id=None),
    SiteConfig(subdomain="sd10-otona", title="大人な時間", tagline="", color="ターコイズ", keywords=["コスプレ", "制服", "イベント"], affiliate_id=None),
]

# 共通ログイン情報（マスターと同じと想定）
WP_USERNAME = "moco"
WP_APP_PASSWORD = "LS3q H0qN 6PNB dTHN W07W iHh3" 

def get_site_config(subdomain: str) -> SiteConfig | None:
    """サブドメイン名からサイト設定を取得"""
    for site in SITES:
        if site.subdomain == subdomain:
            return site
    return None

def update_site_settings(site: SiteConfig):
    base_url = f"https://{site.subdomain}.av-kantei.com"
    api_url = f"{base_url}/wp-json/wp/v2/settings"
    
    # Basic認証ヘッダー
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
            
            # 再取得して検証
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
