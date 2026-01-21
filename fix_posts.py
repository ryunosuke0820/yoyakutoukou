"""既存投稿からCSSと目次ショートコードを削除するスクリプト"""
import os
import re
from dotenv import load_dotenv
from wp_client import WPClient

load_dotenv()

def fix_post_content(content: str) -> str:
    """投稿内容からCSSブロックと[no_toc]を削除"""
    # <style>...</style>ブロックを削除
    content = re.sub(r'<style>[\s\S]*?</style>', '', content)
    # [no_toc]を削除
    content = content.replace('[no_toc]', '')
    # 連続する空行を整理
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()

def main():
    wp = WPClient(
        base_url=os.getenv("WP_BASE_URL"),
        username=os.getenv("WP_USERNAME"),
        app_password=os.getenv("WP_APP_PASSWORD"),
    )
    
    print("投稿を取得中...")
    posts = wp.get_posts(per_page=100, status="publish")
    print(f"{len(posts)}件の投稿を取得")
    
    fixed = 0
    for post in posts:
        raw_content = post.get("content", {}).get("raw", "")
        
        if not raw_content:
            continue
            
        if "<style>" in raw_content or "[no_toc]" in raw_content:
            new_content = fix_post_content(raw_content)
            wp.update_post(post["id"], {"content": new_content})
            title = post.get("title", {}).get("raw", "不明")
            print(f"[OK] 修正: {title[:40]}...")
            fixed += 1
    
    print(f"\n完了: {fixed}件を修正しました")

if __name__ == "__main__":
    main()
