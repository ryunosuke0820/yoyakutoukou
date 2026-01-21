"""
設定モジュール - 環境変数の読み込みとバリデーション
"""
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()


@dataclass
class Config:
    """アプリケーション設定"""
    
    # FANZA/DMM API
    fanza_api_key: str
    fanza_affiliate_id: str
    
    # WordPress
    wp_base_url: str
    wp_username: str
    wp_app_password: str
    
    # OpenAI
    openai_api_key: str
    openai_model: str
    
    # 記事生成設定
    min_chars: int
    max_chars: int
    post_status: str
    
    # パス設定
    base_dir: Path
    data_dir: Path
    prompts_dir: Path
    
    @classmethod
    def from_env(cls) -> "Config":
        """環境変数から設定を読み込む"""
        
        # 必須項目のチェック
        required_vars = [
            "FANZA_API_KEY",
            "FANZA_AFFILIATE_ID",
            "WP_BASE_URL",
            "WP_USERNAME",
            "WP_APP_PASSWORD",
            "OPENAI_API_KEY",
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise ValueError(f"必須の環境変数が設定されていません: {', '.join(missing)}")
        
        base_dir = Path(__file__).parent
        
        return cls(
            # FANZA/DMM API
            fanza_api_key=os.getenv("FANZA_API_KEY", ""),
            fanza_affiliate_id=os.getenv("FANZA_AFFILIATE_ID", ""),
            
            # WordPress
            wp_base_url=os.getenv("WP_BASE_URL", "").rstrip("/"),
            wp_username=os.getenv("WP_USERNAME", ""),
            wp_app_password=os.getenv("WP_APP_PASSWORD", ""),
            
            # OpenAI
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            
            # 記事生成設定
            min_chars=int(os.getenv("MIN_CHARS", "800")),
            max_chars=int(os.getenv("MAX_CHARS", "1500")),
            post_status=os.getenv("POST_STATUS", "draft"),
            
            # パス設定
            base_dir=base_dir,
            data_dir=base_dir / "data",
            prompts_dir=base_dir / "prompts",
        )
    
    def validate(self) -> None:
        """設定値のバリデーション"""
        if self.min_chars < 100:
            raise ValueError("MIN_CHARSは100以上に設定してください")
        
        if self.max_chars < self.min_chars:
            raise ValueError("MAX_CHARSはMIN_CHARS以上に設定してください")
        
        if self.post_status not in ("draft", "publish", "pending", "private"):
            raise ValueError(f"無効なPOST_STATUS: {self.post_status}")
        
        if not self.wp_base_url.startswith(("http://", "https://")):
            raise ValueError("WP_BASE_URLはhttp://またはhttps://で始まる必要があります")


# グローバル設定インスタンス（遅延初期化）
_config: Config | None = None


def get_config() -> Config:
    """設定を取得する（シングルトン）"""
    global _config
    if _config is None:
        _config = Config.from_env()
        _config.validate()
    return _config
