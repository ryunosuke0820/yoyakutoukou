
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_download(url, referer=None):
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    if referer:
        headers["Referer"] = referer
    
    session.headers.update(headers)
    session.cookies.set("age_check_done", "1", domain=".dmm.co.jp")
    session.cookies.set("age_check_done", "1", domain=".fanza.co.jp")
    session.cookies.set("age_check_done", "1", domain=".dmm.com")

    logger.info(f"Testing URL: {url} with Referer: {referer}")
    try:
        response = session.get(url, timeout=10)
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Size: {len(response.content)} bytes")
        logger.info(f"Content-Type: {response.headers.get('Content-Type')}")
        
        # Save for inspection
        with open("test_image.jpg", "wb") as f:
            f.write(response.content)
            
        return len(response.content)
    except Exception as e:
        logger.error(f"Error: {e}")
        return 0

# Test 1: Original URL, Original Referer
test_download("https://pics.dmm.co.jp/digital/video/vrkm01759/vrkm01759pl.jpg", "https://www.dmm.co.jp/")

# Test 2: .com domain
test_download("https://pics.dmm.com/digital/video/vrkm01759/vrkm01759pl.jpg", "https://www.dmm.co.jp/")

# Test 3: No Referer, .com domain
test_download("https://pics.dmm.com/digital/video/vrkm01759/vrkm01759pl.jpg", None)

# Test 4: imgsrc domain (pattern for package)
test_download("https://imgsrc.dmm.com/pics/digital/video/vrkm01759/vrkm01759pl.jpg", None)
