"""
WordPress REST APIクライアント
下書き投稿、メディアアップロード、カテゴリ/タグ管理
"""
import base64
import logging
import time
from typing import Any
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class WPClient:
    """WordPress REST APIクライアント"""
    
    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: str,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/wp-json/wp/v2"
        
        # Basic認証ヘッダー
        credentials = f"{username}:{app_password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self.auth_header = f"Basic {encoded}"
        
        # リトライ設定付きセッション
        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,  # 最大2回リトライ
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        self.timeout = 20  # タイムアウト20秒
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # カテゴリ/タグのキャッシュ
        self._category_cache: dict[str, int] = {}
        self._tag_cache: dict[str, int] = {}
    
    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> requests.Response:
        """APIリクエストを実行"""
        url = f"{self.api_url}/{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = self.auth_header
        
        response = self.session.request(
            method,
            url,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        
        # 429エラー時はRetry-Afterを尊重
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning(f"WP APIレート制限。{retry_after}秒待機...")
            time.sleep(retry_after)
            return self._request(method, endpoint, headers=headers, **kwargs)
        
        return response
    
    def create_post(
        self,
        title: str,
        content: str,
        excerpt: str = "",
        slug: str = "",
        status: str = "draft",
        categories: list[int] | None = None,
        tags: list[int] | None = None,
        featured_media: int | None = None,
        fanza_product_id: str | None = None,
    ) -> dict[str, Any]:
        """
        投稿を作成
        
        Args:
            title: 記事タイトル
            content: 記事本文（HTML）
            excerpt: 抜粋
            slug: URLスラッグ
            status: 投稿ステータス（draft/publish/pending/private）
            categories: カテゴリIDのリスト
            tags: タグIDのリスト
            featured_media: アイキャッチ画像のメディアID
            fanza_product_id: FANZA商品ID（重複チェック用に永続化）
        
        Returns:
            作成された投稿データ
        """
        data = {
            "title": title,
            "content": content,
            "excerpt": excerpt,
            "status": status,
        }
        
        if slug:
            data["slug"] = slug
        
        if categories:
            data["categories"] = categories
        
        if tags:
            data["tags"] = tags
        
        if featured_media:
            data["featured_media"] = featured_media
        
        # FANZA商品IDをメタ情報として保存（重複チェック用）
        if fanza_product_id:
            data["meta"] = {"fanza_product_id": fanza_product_id}
        
        logger.info(f"WP投稿作成: {title[:30]}... status={status}")
        
        response = self._request("POST", "posts", json=data)
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"投稿作成成功: id={result['id']}, link={result.get('link', '')}")
        
        return result
    
    def get_posted_fanza_ids(self, per_page: int = 100, max_pages: int = 10) -> set[str]:
        """
        既存投稿からFANZA商品IDを取得（重複チェック用）
        
        WordPressに保存された全投稿のメタ情報から fanza_product_id を収集し、
        GitHub Actions等で実行時にDBがリセットされても永続的にチェック可能にする
        
        Args:
            per_page: 1ページあたりの取得件数
            max_pages: 最大ページ数
        
        Returns:
            投稿済みFANZA商品IDのセット
        """
        posted_ids = set()
        
        for page in range(1, max_pages + 1):
            try:
                response = self._request("GET", "posts", params={
                    "per_page": per_page,
                    "page": page,
                    "status": "any",  # draft, publish, pending 全て
                    "context": "edit",  # メタ情報を含める
                })
                
                if response.status_code == 400:
                    # ページが存在しない場合
                    break
                    
                response.raise_for_status()
                posts = response.json()
                
                if not posts:
                    break
                
                for post in posts:
                    meta = post.get("meta", {})
                    if isinstance(meta, dict):
                        fanza_id = meta.get("fanza_product_id")
                        if fanza_id:
                            posted_ids.add(fanza_id)
                    elif isinstance(meta, list):
                        # メタが配列の場合
                        for m in meta:
                            if isinstance(m, dict) and m.get("key") == "fanza_product_id":
                                posted_ids.add(m.get("value", ""))
                
                logger.debug(f"WP投稿取得 page={page}: {len(posts)}件, 累計ID={len(posted_ids)}")
                
                # 取得件数がper_page未満なら最終ページ
                if len(posts) < per_page:
                    break
                    
            except Exception as e:
                logger.warning(f"WP投稿取得エラー page={page}: {e}")
                break
        
        logger.info(f"WordPress投稿済みFANZA ID: 合計{len(posted_ids)}件")
        return posted_ids

    
    def get_posts(self, per_page: int = 100, status: str = "publish") -> list[dict]:
        """投稿一覧を取得"""
        response = self._request("GET", "posts", params={
            "per_page": per_page,
            "status": status,
            "context": "edit",  # raw contentを取得
        })
        response.raise_for_status()
        return response.json()
    
    def get_post(self, post_id: int) -> dict:
        """投稿を取得"""
        response = self._request("GET", f"posts/{post_id}", params={"context": "edit"})
        response.raise_for_status()
        return response.json()

    def get_media(self, media_id: int) -> dict:
        """メディア情報を取得"""
        response = self._request("GET", f"media/{media_id}")
        response.raise_for_status()
        return response.json()

    def get_categories(self, per_page: int = 100) -> list[dict]:
        """カテゴリ一覧を取得"""
        response = self._request("GET", "categories", params={"per_page": per_page})
        response.raise_for_status()
        return response.json()
    
    def update_post(self, post_id: int, data: dict) -> dict:
        """投稿を更新"""
        response = self._request("POST", f"posts/{post_id}", json=data)
        response.raise_for_status()
        return response.json()
    
    def post_draft(self, title: str, content: str, excerpt: str = "", featured_media: int | None = None, categories: list[int] | None = None, fanza_product_id: str | None = None) -> int:
        """
        投稿を作成（本番公開）
        
        Args:
            title: 記事タイトル
            content: 記事本文HTML
            excerpt: 抜粋
            featured_media: アイキャッチ画像のメディアID
            categories: カテゴリIDのリスト
            fanza_product_id: FANZA商品ID（重複チェック用）
        
        Returns:
            投稿ID
        """
        result = self.create_post(
            title=title, 
            content=content, 
            excerpt=excerpt, 
            status="publish",  # 本投稿に変更
            featured_media=featured_media,
            categories=categories,
            fanza_product_id=fanza_product_id
        )
        return result["id"]
    
    def upload_media(
        self,
        file_path: Path | None = None,
        file_bytes: bytes | None = None,
        filename: str = "image.jpg",
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        """
        メディアをアップロード
        
        Args:
            file_path: ファイルパス（file_bytesと排他）
            file_bytes: ファイルバイト（file_pathと排他）
            filename: ファイル名
            mime_type: MIMEタイプ
        
        Returns:
            アップロードされたメディアデータ
        """
        if file_path:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
        
        if not file_bytes:
            raise ValueError("file_pathまたはfile_bytesを指定してください")
        
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime_type,
        }
        
        logger.info(f"メディアアップロード: {filename}")
        
        response = self._request(
            "POST",
            "media",
            headers=headers,
            data=file_bytes,
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"メディアアップロード成功: id={result['id']}")
        
        return result
    
    def get_or_create_category(self, name: str) -> int:
        """カテゴリを取得または作成"""
        if name in self._category_cache:
            return self._category_cache[name]
        
        # 既存カテゴリを検索
        response = self._request("GET", "categories", params={"search": name})
        response.raise_for_status()
        categories = response.json()
        
        for cat in categories:
            if cat["name"].lower() == name.lower():
                self._category_cache[name] = cat["id"]
                return cat["id"]
        
        # 新規作成
        response = self._request("POST", "categories", json={"name": name})
        response.raise_for_status()
        cat = response.json()
        self._category_cache[name] = cat["id"]
        logger.info(f"カテゴリ作成: {name} -> id={cat['id']}")
        
        return cat["id"]
    
    def get_or_create_tag(self, name: str) -> int:
        """タグを取得または作成"""
        if name in self._tag_cache:
            return self._tag_cache[name]
        
        # 既存タグを検索
        response = self._request("GET", "tags", params={"search": name})
        response.raise_for_status()
        tags = response.json()
        
        for tag in tags:
            if tag["name"].lower() == name.lower():
                self._tag_cache[name] = tag["id"]
                return tag["id"]
        
        # 新規作成
        response = self._request("POST", "tags", json={"name": name})
        response.raise_for_status()
        tag = response.json()
        self._tag_cache[name] = tag["id"]
        logger.info(f"タグ作成: {name} -> id={tag['id']}")
        
        return tag["id"]
    
    def prepare_taxonomies(
        self,
        genres: list[str],
        actresses: list[str],
    ) -> tuple[list[int], list[int]]:
        """
        ジャンルと女優名からカテゴリ/タグIDを準備
        
        Args:
            genres: ジャンル名リスト（カテゴリに）
            actresses: 女優名リスト（タグに）
        
        Returns:
            (カテゴリIDリスト, タグIDリスト)
        """
        category_ids = []
        tag_ids = []
        
        for genre in genres[:5]:  # 最大5カテゴリ
            try:
                cat_id = self.get_or_create_category(genre)
                category_ids.append(cat_id)
            except Exception as e:
                logger.warning(f"カテゴリ作成失敗: {genre}, error={e}")
        
        for actress in actresses[:10]:  # 最大10タグ
            try:
                tag_id = self.get_or_create_tag(actress)
                tag_ids.append(tag_id)
            except Exception as e:
                logger.warning(f"タグ作成失敗: {actress}, error={e}")
        
        return category_ids, tag_ids
