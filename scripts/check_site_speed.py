
import requests
import time
import logging
from legacy_utils.site_router import get_site_router

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def check_speed():
    router = get_site_router()
    sites = router.get_all_sites()
    
    urls = [f"https://{site.subdomain}.av-kantei.com" for site in sites]
    urls.append("https://av-kantei.com") # Add main site
    
    print(f"{'URL':<40} | {'Status':<10} | {'Time (s)':<10}")
    print("-" * 65)
    
    results = []
    
    for url in urls:
        try:
            start_time = time.time()
            response = requests.get(url, timeout=10)
            end_time = time.time()
            duration = end_time - start_time
            
            status_code = response.status_code
            print(f"{url:<40} | {status_code:<10} | {duration:.4f}")
            results.append((url, status_code, duration))
        except requests.exceptions.RequestException as e:
            print(f"{url:<40} | {'ERROR':<10} | {str(e)}")
            results.append((url, 'ERROR', None))

if __name__ == "__main__":
    check_speed()
