"""
FANZA/DMM APIクライアント
"""
import time
import logging
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.core.models import Product

logger = logging.getLogger(__name__)

class FanzaClient:
    """FANZA/DMM Affiliate APIクライアント"""
    
    # DMM Affiliate API エンドポイント（差し替え可能）
    BASE_URL = "https://api.dmm.com/affiliate/v3/ItemList"
    
    def __init__(self, api_key: str, affiliate_id: str):
        self.api_key = api_key
        self.affiliate_id = affiliate_id
        
        # リトライ設定付きセッション
        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,  # 最大2回リトライ
            backoff_factor=1,  # 1s, 2s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        self.timeout = 20  # タイムアウト20秒
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    def search(
        self,
        limit: int = 10,
        site: str = "FANZA",
        service: str = "digital",
        floor: str = "videoa",
        sort: str = "date",
        keyword: str | None = None,
        since: str | None = None,
        offset: int = 0,
    ) -> list[Product]:
        """
        商品を検索して取得
        """
        params = {
            "api_id": self.api_key,
            "affiliate_id": self.affiliate_id,
            "site": site,
            "service": service,
            "floor": floor,
            "hits": min(limit, 100),
            "sort": sort,
            "offset": offset + 1,  # DMM APIは1始まり
            "output": "json",
        }
        
        if keyword:
            params["keyword"] = keyword
        
        if since:
            params["gte_date"] = since.replace("-", "")
        
        try:
            while True:
                logger.info(f"FANZA API呼び出し: limit={limit}, sort={sort}, offset={offset}")
                response = self.session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=(5.0, 30.0),  # (connect, read) タイムアウト
                )
                
                if response.status_code >= 400:
                    logger.error(f"FANZA API error body: {response.text}")

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"レート制限。{retry_after}秒待機して再試行...")
                    time.sleep(retry_after)
                    continue  # ループで再試行
                
                response.raise_for_status()
                data = response.json()
                
                return self._parse_response(data)
        except requests.exceptions.Timeout:
            logger.error("FANZA APIタイムアウト")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"FANZA APIエラー: {e}")
            raise
    
    def fetch(self, limit: int = 1, since: str | None = None, sort: str = "date", keyword: str | None = None, offset: int = 0) -> list[dict]:
        """商品を取得してdict形式で返す（シンプルAPI）"""
        products = self.search(limit=limit, since=since, sort=sort, keyword=keyword, offset=offset)
        return [p.to_dict() for p in products]
    
    def fetch_by_id(self, content_id: str) -> list[dict]:
        """商品IDで商品を取得"""
        params = {
            "api_id": self.api_key,
            "affiliate_id": self.affiliate_id,
            "site": "FANZA",
            "service": "digital",
            "floor": "videoa",
            "cid": content_id,
            "hits": 1,
            "output": "json",
        }
        
        try:
            logger.info(f"FANZA API呼び出し（ID指定）: cid={content_id}")
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            products = self._parse_response(data)
            return [p.to_dict() for p in products]
        except Exception as e:
            logger.error(f"FANZA API（ID指定）エラー: {e}")
            return []

    def _parse_response(self, data: dict[str, Any]) -> list[Product]:
        """APIレスポンスをProductリストにパース"""
        products = []
        result = data.get("result", {})
        items = result.get("items", [])
        
        for item in items:
            try:
                actress_list = []
                if "iteminfo" in item and "actress" in item["iteminfo"]:
                    actress_list = [a.get("name", "") for a in item["iteminfo"]["actress"]]
                
                genre_list = []
                if "iteminfo" in item and "genre" in item["iteminfo"]:
                    genre_list = [g.get("name", "") for g in item["iteminfo"]["genre"]]
                
                maker = ""
                if "iteminfo" in item and "maker" in item["iteminfo"]:
                    makers = item["iteminfo"]["maker"]
                    if makers:
                        maker = makers[0].get("name", "")
                
                image_url = ""
                if "imageURL" in item:
                    image_url = item["imageURL"].get("large", item["imageURL"].get("small", ""))
                
                sample_movie_url = ""
                if "sampleMovieURL" in item:
                    movie_data = item["sampleMovieURL"]
                    sample_movie_url = movie_data.get("size_720_480", movie_data.get("size_644_414", movie_data.get("size_476_306", "")))

                sample_urls = []
                if "sampleImageURL" in item:
                    sample_data = item["sampleImageURL"]
                    if "sample_l" in sample_data and "image" in sample_data["sample_l"]:
                        sample_urls = sample_data["sample_l"]["image"][:10]
                    elif "sample_s" in sample_data and "image" in sample_data["sample_s"]:
                        sample_urls = sample_data["sample_s"]["image"][:10]
                
                product = Product(
                    product_id=item.get("content_id", item.get("product_id", "")),
                    title=item.get("title", ""),
                    actress=actress_list,
                    maker=maker,
                    genre=genre_list,
                    release_date=item.get("date", ""),
                    summary=item.get("description", item.get("title", "")),
                    package_image_url=image_url,
                    affiliate_url=item.get("affiliateURL", item.get("URL", "")),
                    sample_image_urls=sample_urls,
                    sample_movie_url=sample_movie_url,
                )
                products.append(product)
            except Exception as e:
                logger.warning(f"商品パースエラー: {e}, item={item.get('content_id', 'unknown')}")
                continue
        return products
