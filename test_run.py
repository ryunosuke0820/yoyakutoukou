"""
シンプルなテストスクリプト
各ステップの実行時間を計測
"""
import time
import sys
from pathlib import Path
from dotenv import load_dotenv
import os

# 環境変数読み込み
load_dotenv()


def step(label: str):
    """開始ログを出して、終了時に秒数を出す関数を返す"""
    t0 = time.perf_counter()
    print(f"[STEP] {label} ...", flush=True)
    def end(ok: bool = True):
        dt = time.perf_counter() - t0
        status = "OK" if ok else "FAIL"
        print(f"[TIME] {label}: {dt:.2f}s ({status})", flush=True)
    return end


def main():
    # クライアント初期化
    from fanza_client import FanzaClient
    from openai_client import OpenAIClient
    from wp_client import WPClient
    from renderer import get_renderer
    
    fanza_client = FanzaClient(
        api_key=os.getenv("FANZA_API_KEY"),
        affiliate_id=os.getenv("FANZA_AFFILIATE_ID"),
    )
    
    llm_client = OpenAIClient(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        prompts_dir=Path("prompts"),
        viewpoints_path=Path("viewpoints.json"),
    )
    
    wp_client = WPClient(
        base_url=os.getenv("WP_BASE_URL"),
        username=os.getenv("WP_USERNAME"),
        app_password=os.getenv("WP_APP_PASSWORD"),
    )
    
    # Step 1: FANZA商品取得
    end = step("fanza_fetch")
    try:
        items = fanza_client.search(limit=1)
        end()
    except Exception as e:
        end(ok=False)
        print(f"[ERROR] {e}", flush=True)
        sys.exit(1)
    
    if not items:
        print("[ERROR] 商品が取得できませんでした", flush=True)
        sys.exit(1)
    
    item = items[0]
    print(f"  → 取得: {item.title[:50]}...", flush=True)
    
    # Step 2: LLM記事生成
    end = step("llm_generate")
    try:
        result = llm_client.generate_article(item.to_dict())
        ai_body_html = result["content"]
        end()
    except Exception as e:
        end(ok=False)
        print(f"[ERROR] {e}", flush=True)
        sys.exit(1)
    
    print(f"  → 生成: {len(ai_body_html)}文字", flush=True)
    
    # Step 3: コンテンツレンダリング
    end = step("render_content")
    try:
        renderer = get_renderer()
        item_dict = item.to_dict()
        content_html = renderer.render_post_content(
            aff_url=item_dict["affiliate_url"],
            package_image_url=item_dict.get("package_image_url", ""),
            title=item_dict["title"],
            ai_body_html=ai_body_html,
            sample_urls=item_dict.get("sample_image_urls", []),
        )
        end()
    except Exception as e:
        end(ok=False)
        print(f"[ERROR] {e}", flush=True)
        sys.exit(1)
    
    print(f"  → レンダリング: {len(content_html)}文字", flush=True)
    
    # Step 4: WordPress下書き投稿
    end = step("wp_post_draft")
    try:
        post_id = wp_client.create_post(
            title=result["title"],
            content=content_html,
            excerpt=result.get("excerpt", ""),
            status="draft",
        )
        end()
    except Exception as e:
        end(ok=False)
        print(f"[ERROR] {e}", flush=True)
        sys.exit(1)
    
    print(f"  → 投稿ID: {post_id}", flush=True)
    
    print("[DONE] all finished", flush=True)


if __name__ == "__main__":
    main()
