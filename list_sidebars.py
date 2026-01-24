import sys
import io
from wp_client import WPClient
from config import get_config

def list_sidebars():
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    config = get_config()
    wp = WPClient(config.wp_base_url, config.wp_username, config.wp_app_password)
    sidebars = wp._request('GET', 'sidebars').json()
    print("Available Widget Areas (Sidebars):")
    for s in sidebars:
        print(f"ID: {s['id']}, Name: {s['name']}")

if __name__ == "__main__":
    list_sidebars()
