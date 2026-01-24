from wp_client import WPClient
from config import get_config

import sys
import io

def check_categories():
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    config = get_config()
    wp = WPClient(config.wp_base_url, config.wp_username, config.wp_app_password)
    cats = wp.get_categories()
    print("Found categories:")
    for c in cats:
        print(f"ID: {c['id']}, Name: {c['name']}")

if __name__ == "__main__":
    check_categories()
