import requests
import time

sites = [
    "sd06-hitozuma",
    "sd07-oneesan",
    "sd08-jukujo",
    "sd09-iyashi",
    "sd10-otona"
]

print("Checking sitemap status...")
for site in sites:
    url = f"https://{site}.av-kantei.com/wp-sitemap.xml"
    try:
        start = time.time()
        response = requests.get(url, timeout=10)
        end = time.time()
        elapsed = end - start
        
        status = response.status_code
        size = len(response.content)
        
        print(f"[{site}] Status: {status}, Time: {elapsed:.2f}s, Size: {size} bytes")
        if status != 200:
            print(f"  -> Error: {status}")
    except Exception as e:
        print(f"[{site}] Failed to connect: {e}")
