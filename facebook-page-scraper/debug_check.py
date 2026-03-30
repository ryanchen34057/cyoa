"""檢查 Facebook GraphQL 回應的資料結構"""
import json
import re
import time
from playwright.sync_api import sync_playwright
from scraper_browser import load_cookies_for_playwright

big_responses = []

def on_resp(resp):
    try:
        if "graphql" in resp.url:
            t = resp.text()
            if len(t) > 10000:
                big_responses.append(t)
    except:
        pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
        locale="zh-TW",
    )
    ctx.add_cookies(load_cookies_for_playwright("cookies.txt"))
    page = ctx.new_page()
    page.on("response", on_resp)
    page.goto("https://www.facebook.com/chihyunstock", timeout=30000)
    time.sleep(8)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(5)
    browser.close()

print(f"攔截到 {len(big_responses)} 個大型回應")

for i, resp_text in enumerate(big_responses):
    print(f"\n=== 回應 {i+1} ({len(resp_text)} 字元) ===")
    for kw in ["creation_time", "publish_time", "message", "post_id"]:
        print(f"  {kw}: {resp_text.count(kw)} 次")

    # 找 creation_time 附近內容
    for m in list(re.finditer(r"creation_time", resp_text))[:2]:
        s = max(0, m.start() - 100)
        e = min(len(resp_text), m.end() + 200)
        print("  ---")
        print("  " + resp_text[s:e])

    # 如果沒有 creation_time，印前 3000 字元看結構
    if "creation_time" not in resp_text:
        print("  前 3000 字元:")
        print("  " + resp_text[:3000])

    # 儲存最大的回應
    with open(f"output/debug_resp_{i+1}.json", "w", encoding="utf-8") as f:
        f.write(resp_text)

print("\n已儲存至 output/debug_resp_*.json")
