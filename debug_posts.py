import sys
import io
from wp_client import WPClient
from config import get_config

def debug_posts():
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    config = get_config()
    wp = WPClient(config.wp_base_url, config.wp_username, config.wp_app_password)
    
    target_categories = ["VR作品", "素人・ナンパ", "熟女・人妻", "美少女・若手", "巨乳・爆乳"]
    cats = wp.get_categories()
    cat_map = {c['name']: c['id'] for c in cats}
    
    for name in target_categories:
        cat_id = cat_map.get(name)
        if not cat_id:
            print(f"Category {name} not found")
            continue
            
        posts = wp._request('GET', 'posts', params={'categories': cat_id, 'status': 'publish', 'per_page': 10}).json()
        print(f"\n--- Category: {name} (ID: {cat_id}) ---")
        for p in posts:
            print(f"ID: {p['id']}, Categories: {p['categories']}, Title: {p['title']['rendered']}")

if __name__ == "__main__":
    debug_posts()
