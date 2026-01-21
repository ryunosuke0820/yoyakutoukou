import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class Renderer:
    """記事HTMLレンダラー"""
    
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        
        # テンプレート読み込み
        self._hero_template = self._load_template("hero.html")
        self._scene_template = self._load_template("scene.html")
        self._rating_template = self._load_template("rating.html")
        self._summary_template = self._load_template("summary.html")
        self._cta_bottom_template = self._load_template("cta_bottom.html")
        self._video_template = self._load_template("video.html")
        self._styles_template = self._load_template("styles.html")
        
        logger.info(f"Renderer初期化完了: templates_dir={templates_dir}")

    def _load_template(self, name: str) -> str:
        """テンプレートファイルを読み込む"""
        path = self.templates_dir / name
        if not path.exists():
            logger.error(f"テンプレートファイルが見つかりません: {path}")
            return ""
        return path.read_text(encoding="utf-8")

    def render_hero(
        self,
        package_image_url: str,
        title: str,
        short_description: str,
        actress: str,
        maker: str,
        release_date: str,
        duration: str,
        product_id: str,
        aff_url: str,
    ) -> str:
        """Heroセクションをレンダリング"""
        html = self._hero_template
        html = html.replace("{{PACKAGE_IMAGE_URL}}", package_image_url)
        html = html.replace("{{TITLE}}", title)
        html = html.replace("{{SHORT_DESCRIPTION}}", short_description)
        html = html.replace("{{ACTRESS}}", actress)
        html = html.replace("{{MAKER}}", maker)
        html = html.replace("{{RELEASE_DATE}}", release_date)
        # 収録時間がない場合は行ごと削除
        if duration:
            html = html.replace("{{DURATION}}", duration)
        else:
            # 収録時間の行を丸ごと削除
            import re
            html = re.sub(r'<li[^>]*>.*?収録時間.*?</li>\s*', '', html, flags=re.DOTALL)
        html = html.replace("{{PRODUCT_ID}}", product_id)
        html = html.replace("{{AFF_URL}}", aff_url)
        return html
    
    def render_scene(self, scene_image_url: str, title: str, text: str) -> str:
        """シーンセクションをレンダリング"""
        html = self._scene_template
        html = html.replace("{{SCENE_IMAGE_URL}}", scene_image_url)
        html = html.replace("{{SCENE_TITLE}}", title)
        html = html.replace("{{SCENE_TEXT}}", text)
        return html

    def render_scenes(self, scenes: list[dict], sample_urls: list[str] | None = None) -> str:
        """全シーンセクションをレンダリング"""
        parts = []
        sample_urls = sample_urls or []
        
        for i, scene in enumerate(scenes):
            image_url = sample_urls[i] if i < len(sample_urls) else ""
            
            # pointsがリストで来る可能性に対応（互換性のため）
            text = scene.get("points", "")
            if isinstance(text, list):
                text = " ".join(text)
                
            scene_html = self.render_scene(
                scene_image_url=image_url,
                title=scene.get("title", f"シーン{i+1}"),
                text=text,
            )
            parts.append(scene_html)
            
            if i < len(scenes) - 1:
                parts.append('<hr style="margin:20px 0;border:0;border-top:1px dashed #ddd;">')
        
        return "\n\n".join(parts)
    
    def render_rating(self, ratings: dict) -> str:
        """総合評価セクションをレンダリング"""
        html = self._rating_template
        
        for key, label in [("ease", "EASE"), ("fetish", "FETISH"), ("volume", "VOLUME"), ("repeat", "REPEAT")]:
            # 新しいフラット形式と以前のネスト形式の両方に対応
            stars = 3
            note = ""
            
            if key in ratings:
                val = ratings[key]
                if isinstance(val, dict):
                    stars = val.get("stars", 3)
                else:
                    stars = val
            
            note_key = f"{key}_note"
            if note_key in ratings:
                note = ratings[note_key]
            elif isinstance(ratings.get(key), dict):
                note = ratings[key].get("note", "")
            
            stars_str = self._stars_to_string(stars)
            html = html.replace(f"{{{{RATING_{label}}}}}", stars_str)
            html = html.replace(f"{{{{RATING_{label}_NOTE}}}}", note)
        
        return html

    def render_video(self, sample_movie_url: str) -> str:
        """動画セクションをレンダリング"""
        if not sample_movie_url:
            return ""
        html = self._video_template
        html = html.replace("{{SAMPLE_MOVIE_URL}}", sample_movie_url)
        return html
    
    def render_summary(self, summary_text: str) -> str:
        """まとめセクションをレンダリング"""
        html = self._summary_template
        return html.replace("{{SUMMARY_TEXT}}", summary_text)
    
    def render_cta_bottom(self, aff_url: str, cta_text: str = "今すぐ堪能する") -> str:
        """下部CTAをレンダリング"""
        html = self._cta_bottom_template
        html = html.replace("{{AFF_URL}}", aff_url)
        html = html.replace("{{CTA_TEXT}}", cta_text)
        return html

    def _stars_to_string(self, count: int) -> str:
        """数値スコアを★文字列に変換"""
        try:
            c = int(count)
        except:
            c = 3
        c = max(0, min(5, c))
        return "★" * c + "☆" * (5 - c)

    def render_post_content(
        self,
        item: dict,
        ai_response: dict,
    ) -> str:
        """投稿本文全体を生成"""
        parts = []
        
        # 1. Hero
        actress_str = ", ".join(item.get("actress", [])) if item.get("actress") else "情報なし"
        hero_html = self.render_hero(
            package_image_url=item.get("package_image_url", ""),
            title=item.get("title", ""),
            short_description=ai_response.get("short_description", "作品レビュー"),
            actress=actress_str,
            maker=item.get("maker", "情報なし"),
            release_date=item.get("release_date", "情報なし"),
            duration=item.get("duration", "情報なし"),
            product_id=item.get("product_id", ""),
            aff_url=item.get("affiliate_url", ""),
        )
        parts.append(hero_html)
        
        # 2. シーン別
        scenes_html = self.render_scenes(
            ai_response.get("scenes", []),
            item.get("sample_image_urls", []),
        )
        parts.append(scenes_html)
        
        # 3. 評価
        rating_html = self.render_rating(ai_response.get("ratings", {}))
        parts.append(rating_html)
        
        # 4. まとめ
        summary_html = self.render_summary(ai_response.get("summary", ""))
        parts.append(summary_html)
        
        # 5. 下部CTA
        cta_html = self.render_cta_bottom(
            aff_url=item.get("affiliate_url", ""),
            cta_text=ai_response.get("cta_text", "今すぐ堪能する"),
        )
        parts.append(cta_html)
        
        # 6. サンプル動画
        video_html = self.render_video(item.get("sample_movie_url", ""))
        parts.append(video_html)
        
        return "\n\n".join(parts)
