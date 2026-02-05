import json
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class Renderer:
    _SUBCOLOR_MAP = {
        "cream_pink": "#ffe3ef",
        "dusty_blue": "#c9dff2",
        "neon_pink": "#ff4fd8",
        "wine_red": "#7a0e2d",
        "mint_beige": "#e7f2e8",
        "greige": "#c9c2b8",
        "navy": "#1e2a44",
        "brown": "#7a4b2a",
        "lavender": "#cbb9ff",
        "neon_yellow": "#facc15",
        "teal": "#14b8a6",
    }

    _IMG_SHADOW_MAP = {
        "soft": "0 10px 24px rgba(0, 0, 0, .16)",
        "thin": "0 2px 8px rgba(0, 0, 0, .18)",
        "elegant": "0 14px 30px rgba(0, 0, 0, .28)",
        "light": "0 6px 16px rgba(0, 0, 0, .12)",
        "medium": "0 10px 22px rgba(0, 0, 0, .20)",
        "none": "none",
    }

    _STICKY_SCRIPT = """<script>
(() => {
  if (window.__aaStickyCtaInit) return;
  window.__aaStickyCtaInit = true;
  const stickies = document.querySelectorAll('.aa-sticky-cta');
  if (!stickies.length) return;

  const updateVisibility = (el) => {
    const showAfter = parseInt(el.dataset.showAfter || '0', 10);
    const once = el.dataset.once === 'true';
    const key = el.dataset.key || 'aaStickyCtaDismissed';
    if (once) {
      try {
        if (window.localStorage && localStorage.getItem(key) === '1') {
          el.classList.remove('is-visible');
          return;
        }
      } catch (_) {
        // ignore storage errors
      }
    }
    const doc = document.documentElement;
    const max = Math.max(doc.scrollHeight - doc.clientHeight, 1);
    const scrollTop = window.pageYOffset || doc.scrollTop || 0;
    const pct = Math.round((scrollTop / max) * 100);
    if (pct >= showAfter) {
      el.classList.add('is-visible');
    } else {
      el.classList.remove('is-visible');
    }
  };

  const bind = (el) => {
    if (el.dataset.bound === '1') return;
    el.dataset.bound = '1';
    const dismissable = el.dataset.dismissable !== 'false';
    const key = el.dataset.key || 'aaStickyCtaDismissed';
    const once = el.dataset.once === 'true';

    const remember = () => {
      if (once) {
        try {
          if (window.localStorage) {
            localStorage.setItem(key, '1');
          }
        } catch (_) {
          // ignore storage errors
        }
      }
      el.classList.remove('is-visible');
    };

    const closeBtn = el.querySelector('.aa-sticky-cta-close');
    if (closeBtn) {
      if (dismissable) {
        closeBtn.addEventListener('click', remember);
      } else {
        closeBtn.remove();
      }
    }
    const link = el.querySelector('a');
    if (link) {
      link.addEventListener('click', remember);
    }
  };

  const onScroll = () => {
    stickies.forEach(updateVisibility);
  };

  stickies.forEach(bind);
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  onScroll();
})();
</script>"""
    _SITE_DATA_SCRIPT = """<script>
(() => {
  const wrap = document.querySelector('.aa-wrap[data-site]');
  if (!wrap) return;
  const site = wrap.getAttribute('data-site') || '';
  const root = document.documentElement;
  const body = document.body;
  if (body && !body.getAttribute('data-site')) {
    body.setAttribute('data-site', site);
  }
  if (root && !root.getAttribute('data-site')) {
    root.setAttribute('data-site', site);
  }
  const sub = wrap.style.getPropertyValue('--sub-color');
  if (sub) {
    if (body) body.style.setProperty('--sub-color', sub);
    if (root) root.style.setProperty('--sub-color', sub);
  }

  // Hide author/follow box (theme-level)
  const authorSelectors = [
    '.author-box',
    '.author-info',
    '.author-description',
    '.author-link',
    '.author-follow',
    '.sns-follow-buttons',
  ];
  authorSelectors.forEach((sel) => {
    document.querySelectorAll(sel).forEach((el) => el.remove());
  });
  document.querySelectorAll('[class*=\"author\"], [class*=\"profile\"], [class*=\"follow\"]').forEach((el) => {
    const text = (el.textContent || '').trim();
    if (text.includes('をフォローする') || text.toLowerCase().includes('follow') || text.includes('moco0426')) {
      el.remove();
    }
  });

  // Hide TOC blocks (theme/plugin)
  const tocSelectors = [
    '.toc',
    '#toc',
    '.toc-container',
    '.toc-title',
    '.ez-toc-container',
    '.ez-toc-title',
    '.cocoon-toc',
  ];
  tocSelectors.forEach((sel) => {
    document.querySelectorAll(sel).forEach((el) => el.remove());
  });
})();
</script>"""
    """記事HTMLレンダラー"""
    
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        
        # テンプレート読み込み
        self._hero_template = self._load_template("hero.html")
        self._hero_template_sd03 = self._load_template("hero_sd03.html")
        self._scene_template = self._load_template("scene.html")
        self._rating_template = self._load_template("rating.html")
        self._summary_template = self._load_template("summary.html")
        self._cta_bottom_template = self._load_template("cta_bottom.html")
        self._video_template = self._load_template("video.html")
        self._styles_template = self._load_template("styles.html")
        self._site_decor = self._load_site_decor()
        
        logger.info(f"Renderer初期化完了: templates_dir={templates_dir}")

    def _load_template(self, name: str) -> str:
        """テンプレートファイルを読み込む"""
        path = self.templates_dir / name
        if not path.exists():
            logger.error(f"テンプレートファイルが見つかりません: {path}")
            return ""
        return path.read_text(encoding="utf-8")

    def _load_site_decor(self) -> dict:
        """サイトテーマ設定を読み込み (site_theme_config.json を優先)"""
        # 新しい設定ファイルを優先
        new_path = self.templates_dir.parent.parent / "site_theme_config.json"
        if new_path.exists():
            try:
                data = json.loads(new_path.read_text(encoding="utf-8"))
                logger.info(f"site_theme_config.json を読み込みました ({len(data)} サイト)")
                return data
            except json.JSONDecodeError as exc:
                logger.warning(f"site_theme_config.json parse error: {exc}")
        
        # フォールバック: 旧形式
        path = self.templates_dir.parent.parent / "data" / "site_decor.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning(f"site_decor.json parse error: {exc}")
            return {}

    def _get_site_decor(self, site_id: str) -> dict:
        if not site_id:
            return self._site_decor.get("_default", {})
        return self._site_decor.get(site_id, self._site_decor.get("_default", {}))

    def _build_wrap_attrs(self, site_id: str) -> tuple[str, str]:
        decor = self._get_site_decor(site_id)
        theme = decor.get("theme", {})
        image_cfg = decor.get("image", {})
        hover_cfg = image_cfg.get("hover", {})

        classes = ["aa-wrap", f"aa-site-{site_id}"]
        style = {}

        # 新形式: テーマカラーをCSS変数として出力
        primary = theme.get("primary")
        if primary:
            style["--aa-primary"] = primary
        
        sub_color = theme.get("subColor")
        if sub_color:
            # ???????????HEX??
            if sub_color.startswith("#"):
                style["--sub-color"] = sub_color
            else:
                # ?????? ???????????
                classes.append(f"aa-subcolor-{sub_color}")
                sub_hex = self._SUBCOLOR_MAP.get(sub_color)
                if sub_hex:
                    style["--sub-color"] = sub_hex
            if "--sub-color" in style:
                style["--aa-subcolor"] = style["--sub-color"]

        accent = theme.get("accent")
        if accent:
            style["--aa-accent"] = accent

        background = theme.get("background")
        if background:
            style["--aa-background"] = background

        # 旧形式互換
        theme_style = theme.get("style")
        if theme_style:
            classes.append(f"aa-theme-{theme_style}")

        for token in theme.get("decor", []) or []:
            classes.append(f"aa-decor-{token}")

        thumb_shape = image_cfg.get("thumbShape")
        if thumb_shape == "rounded":
            style["--aa-thumb-radius"] = "12px"
        elif thumb_shape == "square":
            style["--aa-thumb-radius"] = "0px"

        shadow = image_cfg.get("shadow")
        if shadow in self._IMG_SHADOW_MAP:
            style["--aa-img-shadow"] = self._IMG_SHADOW_MAP[shadow]

        hover_type = hover_cfg.get("type")
        if hover_type in ("scale", "scale_glow"):
            scale = hover_cfg.get("scale", 1.04)
            style["--aa-img-hover-scale"] = str(scale)
            if hover_type == "scale_glow":
                glow_color = hover_cfg.get("glowColor", "rgba(255, 92, 168, .45)")
                style["--aa-img-shadow-hover"] = f"0 0 18px {glow_color}"
        elif hover_type == "fade":
            opacity = hover_cfg.get("opacity", 0.95)
            style["--aa-img-hover-opacity"] = str(opacity)

        class_attr = " ".join(classes)
        style_attr = "; ".join([f"{k}: {v}" for k, v in style.items()])
        return class_attr, style_attr

    def render_hero(
        self,
        package_image_url: str,
        title: str,
        short_description: str,
        highlights: list[str],
        meters: dict,
        product_id: str,
        aff_url: str,
        cta_label_primary: str | None = None,
        cta_subline_1: str | None = None,
        cta_subline_2: str | None = None,
        external_link_label: str = "DMMで詳細を見る",
        site_id: str = "default",
    ) -> str:
        """Heroセクションをレンダリング"""
        html = self._hero_template_sd03 if site_id.startswith("sd") and self._hero_template_sd03 else self._hero_template
        html = html.replace("{EYECATCH_URL}", package_image_url)
        html = html.replace("{TITLE}", title)
        html = html.replace("{SHORT_DESCRIPTION}", short_description)
        html = html.replace("{HIGHLIGHT_1}", highlights[0] if len(highlights) > 0 else "")
        html = html.replace("{HIGHLIGHT_2}", highlights[1] if len(highlights) > 1 else "")
        html = html.replace("{HIGHLIGHT_3}", highlights[2] if len(highlights) > 2 else "")

        # Meters
        html = html.replace("{METER_LABEL_TEMPO}", "テンポ")
        html = html.replace("{METER_TEMPO_LEVEL}", str(meters.get("tempo_level", 3)))
        html = html.replace("{METER_LABEL_VOLUME}", "ボリューム")
        html = html.replace("{METER_VOLUME_LEVEL}", str(meters.get("volume_level", 3)))

        # Labels/Notes
        html = html.replace("{EXTERNAL_LINK_LABEL}", external_link_label)
        html = html.replace("{NOTICE_18}", "")
        html = html.replace("{NOTICE_EXTERNAL}", "外部サイトへ移動します")
        default_cta = "今すぐ作品をチェックする"
        html = html.replace("{CTA_BUTTON_LABEL_TOP}", cta_label_primary or default_cta)
        html = html.replace("{CTA_URL_TOP}", aff_url)
        html = html.replace("{CTA_SUBLINE_1}", cta_subline_1 if cta_subline_1 is not None else "会員登録なしですぐにデモ視聴可能")
        html = html.replace("{CTA_SUBLINE_2}", cta_subline_2 if cta_subline_2 is not None else "安心の公式リンク（DMM.co.jp）")
        html = html.replace("{EXTERNAL_LINK_LINE}", f"※{external_link_label}へ移動します")

        # Placeholder for visual
        html = html.replace("{EYECATCH_PLACEHOLDER}", "")

        return html
    
    def render_spec(self, item: dict, site_id: str = "default") -> str:
        """作品スペックセクションをレンダリング"""
        html = self._load_template("spec.html")
        
        spec_title = "作品詳細スペック"
        if site_id == "sd02-shirouto":
            spec_title = "素人詳細スペック"
            
        html = html.replace("{SPEC_TITLE}", spec_title)
        html = html.replace("{SPEC_TOGGLE_HINT}", "クリックで詳細を表示")
        
        labels = ["配信開始日", "出演者", "メーカー", "品番"]
        values = [
            item.get("release_date", "N/A"),
            ", ".join(item.get("actress", [])) if item.get("actress") else "N/A",
            item.get("maker", "N/A"),
            item.get("product_id", "N/A"),
        ]
        
        for i in range(4):
            html = html.replace(f"{{SPEC_LABEL_{i+1}}}", labels[i])
            html = html.replace(f"{{SPEC_VALUE_{i+1}}}", values[i])
            
        html = html.replace("{SPEC_NOTE}", "※情報は配信当時のものです。最新の情報はリンク先でご確認ください。")
        return html

    def render_feature(self, index: int, scene: dict, image_url: str) -> str:
        """特徴（見どころ）カードを1枚レンダリング"""
        html = self._load_template("feature.html") # 新規作成
        html = html.replace("{FEATURE_INDEX}", str(index + 1))
        html = html.replace("{FEATURE_LABEL}", scene.get("feature_label", f"見どころ {index + 1}"))
        html = html.replace("{FEATURE_CHECK}", scene.get("feature_check", "ここが最高！"))
        html = html.replace("{FEATURE_DESCRIPTION}", scene.get("points", ""))
        html = html.replace("{FEATURE_METER_LABEL}", "興奮度")
        html = html.replace("{FEATURE_LEVEL}", str(scene.get("feature_level", 4)))
        
        # 画像スロット
        if image_url:
            img_tag = f'<img src="{image_url}" alt="scene {index+1}" class="aa-img" />'
            html = html.replace("{FEATURE_1_IMAGE_SLOT}", img_tag) # 汎用プレースホルダ
        else:
            html = html.replace("{FEATURE_1_IMAGE_SLOT}", "画像準備中")
            
        return html

    def render_checklist(self, checklist_data: dict, site_id: str = "default") -> str:
        """要素チェック表をレンダリング"""
        html = self._load_template("checklist.html")
        
        checklist_title = "要素別チェックリスト"
        if site_id == "sd02-shirouto":
            checklist_title = "素人鑑定チェックリスト"
            
        html = html.replace("{CHECKLIST_TITLE}", checklist_title)
        html = html.replace("{CHECKLIST_NOTE}", "ベテランレビュアーによる俺得評価")
        
        items = checklist_data.get("items", [])
        for i in range(10):
            label = items[i]["label"] if i < len(items) else "-"
            state = items[i]["state"] if i < len(items) else "off"
            html = html.replace(f"{{TAG_{i+1}_LABEL}}", label)
            html = html.replace(f"{{TAG_{i+1}_STATE}}", state)
            
        html = html.replace("{LEGEND_ON}", "アリ")
        html = html.replace("{LEGEND_OFF}", "ナシ")
        html = html.replace("{LEGEND_MAYBE}", "微妙")
        return html

    def render_safety(self) -> str:
        """安心・注意カードをレンダリング"""
        html = self._load_template("safety.html") # 新規作成
        html = html.replace("{SAFETY_TITLE}", "安心してご利用いただくために")
        html = html.replace("{CALLOUT_1_TITLE}", "18歳未満禁止")
        html = html.replace("{CALLOUT_1_BODY}", "本作品は成人向けです。18歳未満の方は閲覧・購入できません。")
        html = html.replace("{CALLOUT_2_TITLE}", "公式リンク")
        html = html.replace("{CALLOUT_2_BODY}", "当サイトはDMMアフィリエイトとして公式の正規配信サイトへのみ誘導します。")
        html = html.replace("{CALLOUT_3_TITLE}", "ネタバレ配慮")
        html = html.replace("{CALLOUT_3_BODY}", "レビューには一部内容が含まれますが、結末等の重大なネタバレは避けています。")
        return html

    def render_faq(self, faqs: list[dict]) -> str:
        """FAQセクションをレンダリング"""
        html = self._load_template("faq.html") # 新規作成
        html = html.replace("{FAQ_TITLE}", "よくある質問")
        for i in range(5):
            q = faqs[i]["q"] if i < len(faqs) else "視聴に会員登録は必要ですか？"
            a = faqs[i]["a"] if i < len(faqs) else "はい、DMMの無料会員登録が必要です。一部デモ動画は登録なしでも見られます。"
            html = html.replace(f"{{FAQ_Q{i+1}}}", q)
            html = html.replace(f"{{FAQ_A{i+1}}}", a)
        return html

    def render_post_content(
        self,
        item: dict,
        ai_response: dict,
        site_id: str = "default",
        related_posts: list[dict] | None = None,
    ) -> str:
        """投稿本文全体を生成"""
        parts = []
        
        # 全体をSITE_IDでラップ
        site_decor = self._get_site_decor(site_id)
        cta_cfg = site_decor.get("cta", {})
        cta_primary = cta_cfg.get("label_primary")
        cta_secondary = cta_cfg.get("label_secondary")
        sticky_cfg = site_decor.get("stickyCta", {})
        wrap_class, wrap_style = self._build_wrap_attrs(site_id)
        style_attr = f' style=\"{wrap_style}\"' if wrap_style else ''
        parts.append(f'<div class=\"{wrap_class}\" data-site=\"{site_id}\"{style_attr}>')
        
        # 1. Sticky Badge
        parts.append(f'''
  <div class="aa-sticky-badge" aria-label="notice">
    <span class="aa-badge aa-badge-18">18+</span>
    <span class="aa-badge aa-badge-ext">DMM公式</span>
  </div>
        ''')
        # Sticky CTA disabled (requested)
        # 2. Hero (A)
        hero_cta_label = cta_primary
        hero_subline_1 = None
        hero_subline_2 = None
        hero_external_label = None
        cta_note_3 = None
        cta_external_line = None
        if site_id.startswith("sd"):
            hero_cta_label = "今すぐ無料サンプルを見る"
            hero_subline_1 = "※会員登録なし / 安心の公式DMMリンク"
            hero_subline_2 = ""
            hero_external_label = "DMM.co.jp（公式）"
            cta_primary = "今すぐこの快楽を本編で堪能する"
            cta_note_3 = "※DMM.co.jp（公式）へ移動します"
            cta_external_line = ""

        hero_html = self.render_hero(
            package_image_url=item.get("package_image_url", ""),
            title=item.get("title", ""),
            short_description=ai_response.get("short_description", ""),
            highlights=ai_response.get("highlights", []),
            meters=ai_response.get("meters", {}),
            product_id=item.get("product_id", ""),
            aff_url=item.get("affiliate_url", ""),
            cta_label_primary=hero_cta_label,
            cta_subline_1=hero_subline_1,
            cta_subline_2=hero_subline_2,
            external_link_label=hero_external_label or "DMMで詳細を見る",
            site_id=site_id,
        )
        parts.append(hero_html)
        
        # 3. Features (C: Highlights x3)
        sample_urls = item.get("sample_image_urls", [])
        scenes = ai_response.get("scenes", [])
        parts.append('<section class="aa-stack" aria-label="feature cards">')
        for i in range(min(3, len(scenes))):
            parts.append(self.render_feature(i, scenes[i], sample_urls[i] if i < len(sample_urls) else ""))
        parts.append('</section>')
        
        # 4. Sample Video
        parts.append(self.render_video(item.get("sample_movie_url", "")))

        # 5. Final CTA (move under sample video)
        parts.append(self.render_cta_final(
            item.get("affiliate_url", ""),
            cta_label_primary=cta_primary,
            cta_note_3=cta_note_3,
            external_link_line=cta_external_line,
        ))
        # 6. Spec (B)
        parts.append(self.render_spec(item, site_id=site_id))

        related_posts = related_posts or []
        if related_posts:
            parts.append(self.render_related(related_posts))

        # 7. (removed: Final CTA moved under sample video)
        
        parts.append('</div>')
        
        # スタイルシートを追加
        parts.append(self._styles_template)
        # NOTE: JavaScript削除 - WordPress/Cocoonが<script>タグを除去し、
        # 中身のJSがプレーンテキストとして残り、White Screen of Deathを引き起こすため
        # Sticky CTAのJS機能は無効化（将来的にはテーマ側かプラグインで対応）
        
        body = "\n\n".join(parts)
        
        # サイト別ボタンクラスを置換
        site_button_class = f"aa-btn-{site_id}" if site_id != "default" else ""
        body = body.replace("{SITE_BUTTON_CLASS}", site_button_class)
        
        # ブロックエディタのHTMLブロックとして包み、wpautopの崩れを抑制
        return f"<!-- wp:html -->\n{body}\n<!-- /wp:html -->"

    def render_summary(self, summary_text: str) -> str:
        """総評セクションをレンダリング"""
        html = self._summary_template
        html = html.replace("{SUMMARY_TITLE}", "まとめ")
        return html.replace("{SUMMARY_TEXT}", summary_text)

    def render_cta_mid(self, aff_url: str, cta_label_secondary: str | None = None) -> str:
        """中間CTA (D) をレンダリング"""
        html = self._load_template("cta.html")
        html = html.replace("{CTA_URL_MID}", aff_url)
        default_cta = "まずは無料デモで興奮を確かめる"
        html = html.replace("{CTA_BUTTON_LABEL_MID}", cta_label_secondary or default_cta)
        html = html.replace("{CTA_MID_SUBLINE_1}", "会員登録なしで1分以上のサンプル視聴が可能")
        html = html.replace("{CTA_MID_SUBLINE_2}", "※リンク先で「動画サンプル」をクリック")
        html = html.replace("{EXTERNAL_LINK_LINE}", "※DMM.co.jp（公式）へ移動します")
        return html

    def render_cta_final(
        self,
        aff_url: str,
        cta_label_primary: str | None = None,
        cta_note_1: str | None = None,
        cta_note_2: str | None = None,
        cta_note_3: str | None = None,
        external_link_line: str | None = None,
    ) -> str:
        """最終CTA (I) をレンダリング"""
        html = self._load_template("cta_bottom.html")
        html = html.replace("{CTA_URL_FINAL}", aff_url)
        default_cta = "今すぐこの快楽を本編で堪能する"
        html = html.replace("{CTA_BUTTON_LABEL_FINAL}", cta_label_primary or default_cta)
        html = html.replace("{CTA_FINAL_NOTE_1}", cta_note_1 or "DMMなら最高画質ですぐに視聴開始")
        html = html.replace("{CTA_FINAL_NOTE_2}", cta_note_2 or "※18歳未満は閲覧できません")
        html = html.replace("{CTA_FINAL_NOTE_3}", cta_note_3 or "")
        if not cta_note_3:
            html = re.sub(r"\n\s*<div class=\"aa-note-line\">\s*</div>", "", html)
        html = html.replace(
            "{EXTERNAL_LINK_LINE}",
            external_link_line if external_link_line is not None else "※DMM.co.jp（公式）へ移動します",
        )
        if external_link_line == "":
            html = re.sub(r"\n\s*<div class=\"aa-extline\">\s*</div>", "", html)
        return html

    def render_meters_section(self, meters: dict) -> str:
        level = meters.get("tempo_level", 3)
        return f"""
<section class="aa-card aa-meters-card" aria-label="excitement meters">
  <div class="aa-section-head">
    <h2 class="aa-h2">興奮度ゲージ</h2>
    <span class="aa-muted">作品の勢い目安</span>
  </div>
  <div class="aa-meters">
    <div class="aa-meter">
      <div class="aa-meter-label">テンポ</div>
      <div class="aa-meter-dots" data-level="{level}" aria-label="テンポ {level}">
        <span class="aa-dot"></span><span class="aa-dot"></span><span class="aa-dot"></span><span class="aa-dot"></span><span class="aa-dot"></span>
      </div>
    </div>
    <div class="aa-meter">
      <span class="aa-badge aa-badge-18">18+</span>
    </div>
  </div>
</section>
        """

    def render_sticky_cta(self, aff_url: str, label: str, sticky_cfg: dict, site_id: str) -> str:
        show_after = sticky_cfg.get("showAfterScrollPct", 40)
        once = sticky_cfg.get("once", True)
        dismissable = sticky_cfg.get("dismissable", True)
        safe_label = label or "続きを見る"
        close_btn = ""
        if dismissable:
            close_btn = (
                '<button class="aa-sticky-cta-close" type="button" aria-label="閉じる">×</button>'
            )
        return f'''
  <div class="aa-sticky-cta" data-show-after="{show_after}" data-once="{str(once).lower()}" data-dismissable="{str(dismissable).lower()}" data-key="aaStickyCtaDismissed-{site_id}">
    <a class="aa-btn aa-btn-primary" href="{aff_url}" rel="nofollow noopener" target="_blank" aria-label="sticky cta">
      <span class="aa-btn-inner">{safe_label}</span>
    </a>
    {close_btn}
  </div>
        '''

    def render_related(self, related_posts: list[dict]) -> str:
        title = "次に選ばれてる作品"
        items = []
        for post in related_posts:
            link = post.get("link", "")
            label = post.get("title", "")
            if not link or not label:
                continue
            items.append(f'<a class="aa-related-item" href="{link}" rel="nofollow noopener" target="_blank">{label}</a>')
        if not items:
            return ""
        items_html = "\n".join(items)
        return f'''
<section class="aa-card aa-related">
  <h2 class="aa-related-title">{title}</h2>
  <div class="aa-related-list">
    {items_html}
  </div>
</section>
        '''

    def render_rating(self, ratings: dict) -> str:
        """評価セクションをレンダリング"""
        html = self._rating_template
        # テンプレートは {{...}} 形式を使用している
        mapping = {
            "{{RATING_EASE}}": ratings.get("ease", "★★★★☆"),
            "{{RATING_EASE_NOTE}}": ratings.get("ease_note", "初心者でも安心"),
            "{{RATING_FETISH}}": ratings.get("fetish", "★★★★★"),
            "{{RATING_FETISH_NOTE}}": ratings.get("fetish_note", "性癖に刺さる"),
            "{{RATING_VOLUME}}": ratings.get("volume", "★★★★☆"),
            "{{RATING_VOLUME_NOTE}}": ratings.get("volume_note", "大満足のボリューム"),
            "{{RATING_REPEAT}}": ratings.get("repeat", "★★★★☆"),
            "{{RATING_REPEAT_NOTE}}": ratings.get("repeat_note", "何度でも見たい"),
        }
        for k, v in mapping.items():
            html = html.replace(k, v)
        return html

    def render_video(self, sample_movie_url: str) -> str:
        """動画セクションをレンダリング"""
        if not sample_movie_url:
            return ""
        html = self._video_template
        return html.replace("{{SAMPLE_MOVIE_URL}}", sample_movie_url)
