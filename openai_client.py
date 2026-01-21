"""
OpenAI APIクライアント
記事生成のためのプロンプト管理と呼び出し
"""
import json
import random
import logging
from pathlib import Path
from typing import Any
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI GPTによる記事生成"""
    
    def __init__(
        self,
        api_key: str,
        model: str,
        prompts_dir: Path,
        viewpoints_path: Path,
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.prompts_dir = prompts_dir
        
        # プロンプトテンプレート読み込み
        self.system_prompt = self._load_template("system.txt")
        self.user_template = self._load_template("user.txt")
        
        # 観点カード読み込み
        self.viewpoints = self._load_viewpoints(viewpoints_path)
        
        logger.info(f"OpenAIクライアント初期化: model={model}, 観点数={len(self.viewpoints)}")
    
    def _load_template(self, filename: str) -> str:
        """テンプレートファイルを読み込む"""
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"プロンプトテンプレートが見つかりません: {path}")
        return path.read_text(encoding="utf-8")
    
    def _load_viewpoints(self, path: Path) -> list[dict[str, str]]:
        """観点カードを読み込む"""
        if not path.exists():
            logger.warning(f"viewpoints.jsonが見つかりません: {path}")
            return []
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return data.get("viewpoints", [])
    
    def _select_viewpoints(self, count: int = 2) -> list[dict[str, str]]:
        """ランダムに観点を選択"""
        if len(self.viewpoints) < count:
            return self.viewpoints
        return random.sample(self.viewpoints, count)
    
    def generate_article(self, product: dict[str, Any]) -> dict[str, str]:
        """
        商品データから記事を生成
        
        Args:
            product: Product.to_dict()の結果
        
        Returns:
            {
                "title": 記事タイトル,
                "content": 本文HTML,
                "excerpt": 抜粋,
                "raw_response": 生のレスポンス
            }
        """
        # 観点を選択
        selected_viewpoints = self._select_viewpoints(2)
        viewpoint_text = "\n".join([
            f"- {v['name']}: {v['description']}"
            for v in selected_viewpoints
        ])
        
        logger.info(f"記事生成開始: {product['product_id']}")
        logger.debug(f"選択された観点: {[v['name'] for v in selected_viewpoints]}")
        
        # ユーザープロンプトを構築
        user_prompt = self.user_template.format(
            product_id=product["product_id"],
            title=product["title"],
            actress=", ".join(product["actress"]) if product["actress"] else "情報なし",
            maker=product["maker"] or "情報なし",
            genre=", ".join(product["genre"]) if product["genre"] else "情報なし",
            release_date=product["release_date"] or "情報なし",
            duration=product.get("duration") or "情報なし",
            summary=product["summary"] or "情報なし",
            affiliate_url=product["affiliate_url"],
            viewpoints=viewpoint_text,
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_completion_tokens=2000,  # GPT-5.x対応
                timeout=60,  # タイムアウト60秒
                response_format={ "type": "json_object" } if "gpt-4" in self.model or "gpt-3.5-turbo-0125" in self.model or "gpt-5" in self.model else None
            )
            
            raw_response = response.choices[0].message.content
            logger.debug(f"OpenAI応答長: {len(raw_response)}文字")
            
            # JSONとしてパース
            result = self._parse_response(raw_response)
            result["raw_response"] = raw_response
            
            return result
            
        except Exception as e:
            logger.error(f"OpenAI APIエラー: {e}")
            raise
    
    def generate(self, item: dict) -> dict:
        """
        商品データからAI応答を生成
        
        Args:
            item: 商品dict（product_id, title, actress等）
        
        Returns:
            AI応答dict（title, short_description, scenes, ratings, summary, cta_text, excerpt等）
        """
        return self.generate_article(item)
    
    def _parse_response(self, response: str) -> dict:
        """OpenAIの応答をパース（新形式対応）"""
        try:
            # chat completionのJSONモードなら直接パース可能
            data = json.loads(response)
            
            # 新形式: scenes, ratings, summary等を含む
            return {
                "title": data.get("title", ""),
                "short_description": data.get("short_description", ""),
                "scenes": data.get("scenes", []),
                "ratings": data.get("ratings", {}),
                "summary": data.get("summary", ""),
                "cta_text": data.get("cta_text", "今すぐ堪能する"),
                "excerpt": data.get("excerpt", ""),
            }
        except json.JSONDecodeError:
            # JSONモードでない、または失敗した場合のフォールバック
            if "```json" in response:
                try:
                    start = response.index("```json") + 7
                    end = response.index("```", start)
                    json_str = response[start:end].strip()
                    data = json.loads(json_str)
                    return {
                        "title": data.get("title", ""),
                        "short_description": data.get("short_description", ""),
                        "scenes": data.get("scenes", []),
                        "ratings": data.get("ratings", {}),
                        "summary": data.get("summary", ""),
                        "cta_text": data.get("cta_text", "今すぐ堪能する"),
                        "excerpt": data.get("excerpt", ""),
                    }
                except (ValueError, json.JSONDecodeError):
                    pass
        
        # フォールバック（最低限の構造）
        logger.warning("JSONパース失敗、フォールバック使用")
        return {
            "title": "レビュー",
            "short_description": "作品レビュー",
            "scenes": [
                {"title": "シーン1", "points": ["レビュー内容"]},
            ],
            "ratings": {
                "ease": {"stars": 3, "note": ""},
                "fetish": {"stars": 3, "note": ""},
                "volume": {"stars": 3, "note": ""},
                "repeat": {"stars": 3, "note": ""},
            },
            "summary": response[:200] if response else "",
            "cta_text": "今すぐ堪能する",
            "excerpt": response[:150] if response else "",
        }

