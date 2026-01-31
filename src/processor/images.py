"""
画像ツール
"""
import logging
import tempfile
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

class ImagePlaceholderError(Exception):
    """画像がプレースホルダーの場合のエラー"""
    pass

class ImageTools:
    """画像処理ユーティリティ"""
    
    def __init__(self, temp_dir: Path | None = None):
        self.temp_dir = temp_dir or Path(tempfile.gettempdir())
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.dmm.co.jp/"
        })
    
    def download(self, url: str, filename: str | None = None) -> Path:
        """画像をダウンロード"""
        if not filename:
            filename = url.split("/")[-1].split("?")[0]
            if not filename:
                filename = "image.jpg"
        save_path = self.temp_dir / filename
        logger.info(f"画像ダウンロード: {url}")
        try:
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"画像保存完了: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"画像ダウンロード失敗: {e}")
            raise
    
    def download_to_bytes(self, url: str) -> tuple[bytes, str, str]:
        """画像をバイト列としてダウンロード"""
        filename = url.split("/")[-1].split("?")[0]
        if not filename:
            filename = "image.jpg"
        logger.info(f"画像ダウンロード（メモリ）: {url}")
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            mime_type = response.headers.get("Content-Type", "image/jpeg")
            content_size = len(response.content)
            logger.info(f"ダウンロード成功: {filename} ({content_size} bytes, type={mime_type})")
            if content_size < 1000:
                logger.warning(f"画像サイズが非常に小さいです ({content_size} bytes)。プレースホルダーの可能性があります。")
                raise ImagePlaceholderError(f"画像がプレースホルダーです（サイズ: {content_size} bytes）。まだ準備されていない可能性があります。")
            return response.content, filename, mime_type
        except ImagePlaceholderError:
            # Placeholder is expected; caller handles skip/retry.
            raise
        except Exception as e:
            logger.error(f"画像ダウンロード失敗: {e}")
            raise
    
    def add_text_overlay(
        self,
        image_path: Path,
        text: str,
        output_path: Path | None = None,
    ) -> Path:
        """画像に文字を入れる"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Pillowがインストールされていません。文字入れをスキップします。")
            return image_path
        if not output_path:
            output_path = image_path.with_stem(f"{image_path.stem}_overlay")
        try:
            with Image.open(image_path) as img:
                draw = ImageDraw.Draw(img)
                font_size = max(20, img.width // 20)
                try:
                    font = ImageFont.truetype("msgothic.ttc", font_size)
                except OSError:
                    font = ImageFont.load_default()
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                x = (img.width - text_width) // 2
                y = img.height - text_height - 20
                padding = 10
                draw.rectangle([x - padding, y - padding, x + text_width + padding, y + text_height + padding], fill=(0, 0, 0, 180))
                draw.text((x, y), text, font=font, fill=(255, 255, 255))
                img.save(output_path)
                logger.info(f"文字入れ完了: {output_path}")
                return output_path
        except Exception as e:
            logger.error(f"文字入れ失敗: {e}")
            return image_path
