"""
サイドバー用画像付きカテゴリウィジェットHTML生成スクリプト
"""
import logging
import sys
import io
from wp_client import WPClient
from config import get_config

# Windows環境での文字化け対策
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_footer_home_link_html(base_url: str):
    """
    フッターなどに設置するシンプルな「ホーム」リンクを生成
    """
    html = f'''<div class="site-footer-home-link" style="text-align:center; padding:20px 0; border-top:1px solid #eee;">
  <a href="{base_url}" style="color:#666; text-decoration:none; font-size:14px; border-bottom:1px solid #999; padding-bottom:2px;">
    ホームに戻る
  </a>
</div>\n'''
    return html

def generate_recent_posts_html(wp_client: WPClient, displayed_post_ids: set, count: int = 5):
    """
    全カテゴリの最新記事からサイドバー用HTMLを生成
    """
    params = {
        "per_page": count + 10, # 重複でスキップされる分を見越して多めに取得
        "status": "publish"
    }
    response = wp_client._request("GET", "posts", params=params)
    posts = response.json()

    if not posts:
        return ""

    html = f'<div class="widget-recent-posts">\n'
    html += f'  <h3 class="widget-title" style="font-size:16px;margin-bottom:15px;border-bottom:2px solid #333;padding-bottom:5px;">✨ 最新の記事</h3>\n'
    html += f'  <ul style="list-style:none;padding:0;margin:0;">\n'

    added_count = 0
    for post in posts:
        if added_count >= count:
            break
            
        post_id = post['id']
        if post_id in displayed_post_ids:
            continue
            
        displayed_post_ids.add(post_id)
        added_count += 1
        
        title = post['title']['rendered']
        link = post['link']
        thumb_url = ""
        
        featured_media = post.get('featured_media')
        if featured_media:
            try:
                media = wp_client.get_media(featured_media)
                thumb_url = media['media_details']['sizes'].get('medium', {}).get('source_url', media['source_url'])
            except: pass

        html += f'''    <li style="display:flex;gap:10px;margin-bottom:15px;align-items:flex-start;">
      <a href="{link}" style="flex:0 0 100px;display:block;">
        <img src="{thumb_url}" style="width:100px;height:70px;object-fit:cover;border-radius:6px;box-shadow:0 3px 6px rgba(0,0,0,0.15);">
      </a>
      <div style="flex:1;">
        <a href="{link}" style="font-size:14px;line-height:1.4;text-decoration:none;color:#333;font-weight:bold;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">
          {title}
        </a>
      </div>
    </li>\n'''

    html += f'  </ul>\n'
    html += f'</div>\n'
    return html

def generate_widget_html(wp_client: WPClient, category_name: str, displayed_post_ids: set, count: int = 3):
    """
    指定したカテゴリの最新記事からサイドバー用HTMLを生成
    """
    # カテゴリIDを取得
    cats = wp_client.get_categories()
    cat_id = None
    for c in cats:
        if c['name'] == category_name:
            cat_id = c['id']
            break
    
    if not cat_id:
        # 見つからない場合は作成せずにスキップ
        return ""

    # 特定カテゴリの記事を取得
    params = {
        "categories": cat_id,
        "per_page": count + 5, # 重複でスキップされる分を見越して多めに取得
        "status": "publish"
    }
    response = wp_client._request("GET", "posts", params=params)
    posts = response.json()

    if not posts:
        return ""

    html = f'<div class="widget-category-posts" style="margin-top:30px;">\n'
    html += f'  <h3 class="widget-title" style="font-size:16px;margin-bottom:12px;border-bottom:2px solid #e60000;padding-bottom:5px;">📂 {category_name}まとめ</h3>\n'
    html += f'  <ul style="list-style:none;padding:0;margin:0;">\n'

    added_count = 0
    for post in posts:
        if added_count >= count:
            break
            
        # フォルダ内での重複は避けるが、他フォルダとの重複は許容する（ユーザー要望：VRはここ、美少女はここ）
        # ただし同じフォルダ内に同じ記事が出ることはWPのクエリ的に無いはず
        
        added_count += 1

        title = post['title']['rendered']
        link = post['link']
        thumb_url = ""
        
        featured_media = post.get('featured_media')
        if featured_media:
            try:
                media = wp_client.get_media(featured_media)
                thumb_url = media['media_details']['sizes'].get('medium', {}).get('source_url', media['source_url'])
            except: pass

        html += f'''    <li style="display:flex;gap:10px;margin-bottom:12px;align-items:center;">
      <a href="{link}" style="flex:0 0 80px;display:block;">
        <img src="{thumb_url}" style="width:80px;height:60px;object-fit:cover;border-radius:4px;box-shadow:0 2px 5px rgba(0,0,0,0.1);">
      </a>
      <a href="{link}" style="font-size:13px;line-height:1.4;text-decoration:none;color:#333;font-weight:bold;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">
        {title}
      </a>
    </li>\n'''

    html += f'  </ul>\n'
    html += f'  <a href="{wp_client.base_url}/category/{category_name}/" style="display:block;text-align:right;font-size:12px;color:#666;text-decoration:none;margin-top:5px;">もっと見る →</a>\n'
    html += f'</div>\n'
    
    return html

def main():
    config = get_config()
    wp_client = WPClient(
        base_url=config.wp_base_url,
        username=config.wp_username,
        app_password=config.wp_app_password
    )

    print("\n" + "="*60)
    print("サイドバー用ビジュアルHTML生成")
    print("="*60 + "\n")

    full_html = ""
    displayed_post_ids = set()
    
    # 1. フッター用ホームリンク
    footer_html = generate_footer_home_link_html(config.wp_base_url)
    
    # 2. サイドバー用まとめ（フォルダ形式）
    sidebar_html = ""
    target_categories = ["VR作品", "素人・ナンパ", "熟女・人妻", "美少女・若手", "巨乳・爆乳"]
    for cat in target_categories:
        html = generate_widget_html(wp_client, cat, displayed_post_ids)
        if html:
            sidebar_html += html + "\n<hr style='border:0;border-top:1px dashed #eee;margin:25px 0;'>\n"
    
    print("\n--- 【A】フッター用ホームリンク（フッターエリアに設置） ---")
    print(footer_html)
    
    print("\n--- 【B】サイドバー用まとめ（サイドバーに設置） ---")
    print(sidebar_html)
    
    print("="*60)
    print("\n[設置方法]")
    print("【A】は WordPress管理画面 > 外観 > ウィジェット の「フッター左・中・右」のいずれかに。")
    print("【B】は 「サイドバー」エリアに、それぞれ「カスタムHTML」として貼り付けてください。")

if __name__ == "__main__":
    main()
