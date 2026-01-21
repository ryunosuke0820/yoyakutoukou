"""
SQLite重複防止ストア
投稿済み商品のトラッキングと重複チェック
"""
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal
from contextlib import contextmanager

logger = logging.getLogger(__name__)

Status = Literal["drafted", "failed", "dry_run"]


class DedupeStore:
    """投稿済み商品の管理"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_db()
    
    def _ensure_db(self) -> None:
        """データベースとテーブルを初期化"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posted_items (
                    product_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    wp_post_id INTEGER,
                    created_at TEXT NOT NULL,
                    error_message TEXT
                )
            """)
            conn.commit()
            logger.debug(f"データベース初期化完了: {self.db_path}")
    
    @contextmanager
    def _connect(self):
        """データベース接続のコンテキストマネージャ"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def is_posted(self, product_id: str) -> bool:
        """
        既に投稿済み（または処理中）かどうかを確認
        
        重複投稿を100%防ぐため、statusに関係なく存在すればTrue
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM posted_items WHERE product_id = ?",
                (product_id,)
            )
            result = cursor.fetchone() is not None
            if result:
                logger.debug(f"重複検出: {product_id}")
            return result
    
    def record_success(
        self,
        product_id: str,
        wp_post_id: int | None = None,
        status: Status = "drafted",
    ) -> None:
        """投稿成功を記録"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO posted_items
                (product_id, status, wp_post_id, created_at, error_message)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (product_id, status, wp_post_id, datetime.now().isoformat())
            )
            conn.commit()
            logger.info(f"成功記録: {product_id}, status={status}, wp_post_id={wp_post_id}")
    
    def record_failure(
        self,
        product_id: str,
        error_message: str,
    ) -> None:
        """投稿失敗を記録"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO posted_items
                (product_id, status, wp_post_id, created_at, error_message)
                VALUES (?, 'failed', NULL, ?, ?)
                """,
                (product_id, datetime.now().isoformat(), error_message)
            )
            conn.commit()
            logger.warning(f"失敗記録: {product_id}, error={error_message}")
    
    def get_stats(self) -> dict[str, int]:
        """統計情報を取得"""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'drafted' THEN 1 ELSE 0 END) as drafted,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'dry_run' THEN 1 ELSE 0 END) as dry_run
                FROM posted_items
            """)
            row = cursor.fetchone()
            return {
                "total": row["total"] or 0,
                "drafted": row["drafted"] or 0,
                "failed": row["failed"] or 0,
                "dry_run": row["dry_run"] or 0,
            }
    
    def clear_failed(self) -> int:
        """失敗した項目をクリア（リトライ用）"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM posted_items WHERE status = 'failed'"
            )
            conn.commit()
            deleted = cursor.rowcount
            logger.info(f"失敗項目をクリア: {deleted}件")
            return deleted
