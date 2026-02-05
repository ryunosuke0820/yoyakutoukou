from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import requests

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts import configure_sites as cs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

USER = cs.WP_USERNAME
APP = cs.WP_APP_PASSWORD

DISCLAIMER_HTML = (
    '<div class="adult-disclaimer" '
    'style="text-align:center; padding:16px 18px; background: rgba(0,0,0,0.02); '
    'border-radius: 8px; margin: 10px 0 20px; font-size: 14px; color: #e60000; '
    'border: 1px solid rgba(0,0,0,0.05); clear: both; font-weight: 700; line-height: 1.6; letter-spacing: .02em;">'
    "<div>※ 本ページは成人向け内容を含みます。</div>"
    "<div>18歳未満の方は閲覧できません。</div>"
    "</div>"
)


def _auth_headers() -> dict:
    import base64

    token = base64.b64encode(f"{USER}:{APP}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def _get_json(url: str) -> dict:
    res = requests.get(url, headers=_auth_headers(), timeout=20)
    res.raise_for_status()
    return res.json()


def _post_json(url: str, payload: dict) -> dict:
    res = requests.post(url, headers=_auth_headers(), json=payload, timeout=20)
    res.raise_for_status()
    return res.json()


def _normalize_html(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def update_site(subdomain: str) -> None:
    base_url = f"https://{subdomain}.av-kantei.com"
    sidebar_url = f"{base_url}/wp-json/wp/v2/sidebars/footer-center?context=edit"
    widgets_url = f"{base_url}/wp-json/wp/v2/widgets"

    sidebar = _get_json(sidebar_url)
    widget_ids = sidebar.get("widgets", [])

    disclaimer_id = None

    # Find existing disclaimer widget in footer-center
    for wid in widget_ids:
        w = _get_json(f"{widgets_url}/{wid}?context=edit")
        raw = (w.get("instance", {}) or {}).get("raw", {})
        content = raw.get("content", "")
        if "adult-disclaimer" in content or "成人向け内容" in content:
            disclaimer_id = wid
            if _normalize_html(content) != _normalize_html(DISCLAIMER_HTML):
                raw["content"] = DISCLAIMER_HTML
                _post_json(f"{widgets_url}/{wid}", {"instance": {"raw": raw}})
                logger.info(f"{subdomain}: updated disclaimer widget {wid}")
            else:
                logger.info(f"{subdomain}: disclaimer widget already up-to-date")
            break

    # Create new custom_html widget if not found
    if not disclaimer_id:
        created = _post_json(
            widgets_url,
            {
                "id_base": "custom_html",
                "sidebar": "footer-center",
                "instance": {"raw": {"content": DISCLAIMER_HTML}},
            },
        )
        disclaimer_id = created.get("id")
        logger.info(f"{subdomain}: created disclaimer widget {disclaimer_id}")

    # Ensure disclaimer widget is first
    if disclaimer_id:
        new_order = [disclaimer_id] + [wid for wid in widget_ids if wid != disclaimer_id]
        if new_order != widget_ids:
            _post_json(f"{base_url}/wp-json/wp/v2/sidebars/footer-center", {"widgets": new_order})
            logger.info(f"{subdomain}: reordered footer widgets")


def main() -> None:
    targets = [s.subdomain for s in cs.SITES if s.subdomain.startswith("sd")]
    for subdomain in targets:
        try:
            update_site(subdomain)
        except Exception as exc:
            logger.error(f"{subdomain}: failed {exc}")


if __name__ == "__main__":
    main()
