"""
記事バリデーター - 品質チェック（検品ゲート）
"""
import re
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """バリデーション結果"""
    is_valid: bool
    errors: list[str]
    warnings: list[str]


class Validator:
    """生成された記事の品質チェック"""
    
    # 必須見出し（記事に含まれるべきもの）
    REQUIRED_HEADINGS = [
        "推しポイント",
        "注意点",
        "刺さる人",
        "刺さらん人",
    ]
    
    # 連続語尾パターン
    REPEATED_ENDINGS = [
        r"(です。){3,}",
        r"(ます。){3,}",
        r"(でしょう。){3,}",
        r"(ですね。){3,}",
        r"(ました。){3,}",
    ]
    
    def __init__(
        self,
        min_chars: int = 800,
        max_chars: int = 1500,
        banned_words_path: Path | None = None,
    ):
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.banned_words: set[str] = set()
        
        if banned_words_path and banned_words_path.exists():
            self._load_banned_words(banned_words_path)
    
    def _load_banned_words(self, path: Path) -> None:
        """禁止ワードを読み込む"""
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith("#"):
                    self.banned_words.add(word)
        logger.info(f"禁止ワード読み込み: {len(self.banned_words)}件")
    
    def validate(self, content: str) -> ValidationResult:
        """
        記事内容をバリデート
        
        Args:
            content: 記事本文
        
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        # HTMLタグを除去して純粋なテキスト長を計算
        plain_text = re.sub(r"<[^>]+>", "", content)
        char_count = len(plain_text)
        
        # 1. 文字数チェック
        if char_count < self.min_chars:
            errors.append(f"文字数不足: {char_count}文字（最低{self.min_chars}文字必要）")
        elif char_count > self.max_chars * 1.5:  # 上限は警告のみ
            warnings.append(f"文字数が多すぎ: {char_count}文字（推奨{self.max_chars}文字以下）")
        
        # 2. 禁止ワードチェック
        for word in self.banned_words:
            if word in content:
                errors.append(f"禁止ワード検出: {word}")
        
        # 3. 連続語尾チェック
        for pattern in self.REPEATED_ENDINGS:
            if re.search(pattern, plain_text):
                warnings.append(f"同じ語尾が連続しています: {pattern}")
        
        # 4. 必須見出しチェック
        missing_headings = []
        for heading in self.REQUIRED_HEADINGS:
            if heading not in content:
                missing_headings.append(heading)
        
        if missing_headings:
            errors.append(f"必須見出しが不足: {', '.join(missing_headings)}")
        
        # 5. 注意書きチェック
        if "18歳未満" not in content and "18禁" not in content:
            errors.append("18歳未満閲覧禁止の注意書きがありません")
        
        if "アフィリエイト" not in content and "広告" not in content and "PR" not in content:
            warnings.append("アフィリエイト表記がありません")
        
        # 6. 同じフレーズの繰り返しチェック（簡易）
        sentences = re.split(r"[。！？\n]", plain_text)
        seen_phrases = {}
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20:  # 短い文は無視
                if sentence in seen_phrases:
                    seen_phrases[sentence] += 1
                    if seen_phrases[sentence] >= 2:
                        warnings.append(f"同じ文が繰り返されています: {sentence[:30]}...")
                else:
                    seen_phrases[sentence] = 1
        
        is_valid = len(errors) == 0
        
        if errors:
            logger.warning(f"バリデーションエラー: {errors}")
        if warnings:
            logger.info(f"バリデーション警告: {warnings}")
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
        )
