"""
FANZA/DMM APIクライアント
このファイルにAPI呼び出しを隔離することで、エンドポイント変更に対応しやすくする
"""
import time
import logging
from dataclasses import dataclass
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class Product:
    """FANZA商品データ"""
    product_id: str
    title: str
    actress: list[str]
    maker: str
    genre: list[str]
    release_date: str
    summary: str
    package_image_url: str
    affiliate_url: str
    sample_image_urls: list[str]  # サンプル画像URL（最大10枚）
    sample_movie_url: str = ""    # サンプル動画URL
    
    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換"""
        return {
            "product_id": self.product_id,
            "title": self.title,
            "actress": self.actress,
            "maker": self.maker,
            "genre": self.genre,
            "release_date": self.release_date,
            "summary": self.summary,
            "package_image_url": self.package_image_url,
            "affiliate_url": self.affiliate_url,
            "sample_image_urls": self.sample_image_urls,
            "sample_movie_url": self.sample_movie_url,
        }


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
        since: str | None = None,
        offset: int = 0,
    ) -> list[Product]:
        """
        商品を検索して取得
        
        Args:
            limit: 取得件数（最大100）
            site: サイト（FANZA/DMM）
            service: サービス（digital/mono等）
            floor: フロア（videoa/videoc等）
            sort: ソート順（date/rank等）
            since: この日付以降（YYYY-MM-DD形式）
            offset: 取得開始位置（ページング用）
        
        Returns:
            Productのリスト
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
        
        # 日付フィルタ（取れれば）
        if since:
            # DMM APIではgte_dateパラメータで対応
            params["gte_date"] = since.replace("-", "")
        
        try:
            logger.info(f"FANZA API呼び出し: limit={limit}, sort={sort}, offset={offset}")
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout,
            )
            
            # 429エラー時はRetry-Afterを尊重
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"レート制限。{retry_after}秒待機...")
                time.sleep(retry_after)
                return self.search(limit, site, service, floor, sort, since, offset)
            
            response.raise_for_status()
            data = response.json()
            
            return self._parse_response(data)
            
        except requests.exceptions.Timeout:
            logger.error("FANZA APIタイムアウト")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"FANZA APIエラー: {e}")
            raise
    
    def fetch(self, limit: int = 1, since: str | None = None, sort: str = "date", offset: int = 0) -> list[dict]:
        """
        商品を取得してdict形式で返す（シンプルAPI）
        
        Args:
            limit: 取得件数
            since: この日付以降（YYYY-MM-DD形式）
            sort: ソート順（date, rank等）
            offset: 取得開始位置（ページング用）
        
        Returns:
            商品dictのリスト
        """
        products = self.search(limit=limit, since=since, sort=sort, offset=offset)
        return [p.to_dict() for p in products]
    
    def _parse_response(self, data: dict[str, Any]) -> list[Product]:
        """
        APIレスポンスをProductリストにパース
        
        Note: DMM APIのレスポンス構造に依存
              エンドポイント変更時はここを修正
        """
        products = []
        
        result = data.get("result", {})
        items = result.get("items", [])
        
        logger.info(f"取得件数: {len(items)}")
        
        for item in items:
            try:
                # 女優情報
                actress_list = []
                if "iteminfo" in item and "actress" in item["iteminfo"]:
                    actress_list = [a.get("name", "") for a in item["iteminfo"]["actress"]]
                
                # ジャンル情報
                genre_list = []
                if "iteminfo" in item and "genre" in item["iteminfo"]:
                    genre_list = [g.get("name", "") for g in item["iteminfo"]["genre"]]
                
                # メーカー情報
                maker = ""
                if "iteminfo" in item and "maker" in item["iteminfo"]:
                    makers = item["iteminfo"]["maker"]
                    if makers:
                        maker = makers[0].get("name", "")
                
                # 画像URL（パッケージ画像）
                image_url = ""
                if "imageURL" in item:
                    # 大きいサイズを優先
                    image_url = item["imageURL"].get("large", item["imageURL"].get("small", ""))
                # サンプル動画URL
                sample_movie_url = ""
                if "sampleMovieURL" in item:
                    movie_data = item["sampleMovieURL"]
                    # PC用高画質を優先
                    sample_movie_url = movie_data.get("size_720_480", movie_data.get("size_644_414", movie_data.get("size_476_306", "")))

                # サンプル画像URL
                sample_urls = []
                if "sampleImageURL" in item:
                    sample_data = item["sampleImageURL"]
                    if "sample_l" in sample_data and "image" in sample_data["sample_l"]:
                        # 多めに取得しておき、後で「エロい」ものを選びやすくする
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
