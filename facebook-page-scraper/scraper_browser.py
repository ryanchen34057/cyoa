"""
Facebook 粉絲專頁爬蟲 - 使用 Playwright 瀏覽器

策略：用無頭瀏覽器載入頁面，自動捲動載入更多貼文，
攔截 Facebook 的 GraphQL API 回應來提取貼文資料。

安裝：
    pip install playwright
    playwright install chromium

使用方式：
    python scraper_browser.py <粉專名稱> --cookies cookies.txt [--output output.json] [--scroll 50]
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright


def load_cookies_for_playwright(cookies_path):
    """從 Netscape 格式的 cookies 檔案轉換為 Playwright 格式"""
    cookies = []
    with open(cookies_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _, path, secure, expires, name, value = parts[:7]
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": secure.upper() == "TRUE",
                "expires": int(expires) if expires != "0" else -1,
            })
    return cookies


def scrape_with_browser(page_name, cookies_path, max_scrolls=50, output_path="output/posts.json",
                        preview=False, debug=False, headless=True):
    """使用 Playwright 爬取粉專貼文"""
    all_posts = {}  # post_id -> post_data (去重用)
    graphql_responses = []

    def handle_response(response):
        """攔截 GraphQL API 回應"""
        try:
            if "api/graphql" in response.url:
                body = response.text()
                posts = extract_posts_from_graphql(body)
                for post in posts:
                    pid = post.get("id", "")
                    if pid and pid not in all_posts:
                        all_posts[pid] = post
                if debug and posts:
                    graphql_responses.append(body[:2000])
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-TW",
        )

        # 載入 cookies
        cookies = load_cookies_for_playwright(cookies_path)
        context.add_cookies(cookies)

        page = context.new_page()

        # 攔截所有 GraphQL 回應
        page.on("response", handle_response)

        # 載入粉專頁面
        url = f"https://www.facebook.com/{page_name}"
        print(f"正在載入: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            # networkidle 可能 timeout，但頁面通常已載入
            pass

        time.sleep(3)

        # 檢查是否需要登入
        if "login" in page.url:
            print("錯誤: 需要登入，請確認 cookies 是否有效")
            browser.close()
            return []

        # 關閉可能的彈出視窗
        try:
            close_btns = page.query_selector_all('[aria-label="關閉"], [aria-label="Close"]')
            for btn in close_btns:
                btn.click()
                time.sleep(0.5)
        except Exception:
            pass

        print(f"頁面已載入，開始捲動載入貼文...")
        print(f"（最多捲動 {max_scrolls} 次）\n")

        initial_count = len(all_posts)
        if initial_count > 0:
            print(f"首次載入取得 {initial_count} 篇貼文")

        # 捲動頁面載入更多貼文
        no_new_count = 0
        for scroll_num in range(1, max_scrolls + 1):
            prev_count = len(all_posts)

            # 捲動到頁面底部
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # 等待新內容載入
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            current_count = len(all_posts)
            new_this_scroll = current_count - prev_count

            print(f"\r捲動 {scroll_num}/{max_scrolls} | 已取得 {current_count} 篇貼文 (+{new_this_scroll})", end="", flush=True)

            if new_this_scroll == 0:
                no_new_count += 1
                if no_new_count >= 5:
                    print(f"\n連續 {no_new_count} 次捲動沒有新貼文，可能已到底部")
                    break
                time.sleep(1)
            else:
                no_new_count = 0

        # 也嘗試從頁面 DOM 直接提取貼文
        print("\n\n正在從頁面 DOM 提取貼文...")
        dom_posts = extract_posts_from_dom(page)
        for post in dom_posts:
            pid = post.get("id", f"dom_{len(all_posts)}")
            if pid not in all_posts:
                all_posts[pid] = post

        if debug:
            os.makedirs("output", exist_ok=True)
            with open("output/debug_graphql_responses.json", "w", encoding="utf-8") as f:
                json.dump(graphql_responses[:10], f, ensure_ascii=False, indent=2)
            # 儲存頁面 HTML
            with open("output/debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"[DEBUG] 攔截到的 GraphQL 回應: {len(graphql_responses)} 個")

        browser.close()

    # 整理結果
    posts = list(all_posts.values())
    posts.sort(key=lambda p: p.get("timestamp", 0), reverse=True)

    return posts


def extract_posts_from_graphql(response_text):
    """從 GraphQL 回應中提取貼文"""
    posts = []

    for line in response_text.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        found = find_posts_in_json(data)
        posts.extend(found)

    return posts


def find_posts_in_json(data, depth=0):
    """遞迴搜尋 JSON 中的貼文"""
    posts = []

    if depth > 30 or data is None:
        return posts

    if isinstance(data, dict):
        # Facebook 貼文的典型結構:
        # node -> comet_sections -> content -> story -> message -> text
        # 或 node -> post_id, creation_time, message

        has_creation_time = "creation_time" in data
        has_message = "message" in data

        # 完整貼文節點
        if has_creation_time and has_message:
            text = ""
            msg = data.get("message")
            if isinstance(msg, dict):
                text = msg.get("text", "")
            elif isinstance(msg, str):
                text = msg

            post = {
                "id": str(data.get("id", data.get("post_id", ""))),
                "text": text,
                "created_time": datetime.fromtimestamp(data["creation_time"]).isoformat(),
                "timestamp": data["creation_time"],
            }

            # 互動數據
            feedback = data.get("feedback") or data.get("comet_feed_ufi_container") or {}
            if isinstance(feedback, dict):
                rc = feedback.get("reaction_count") or feedback.get("reactors")
                if isinstance(rc, dict):
                    post["reaction_count"] = rc.get("count", rc.get("total_count", 0))
                cc = feedback.get("comment_count") or feedback.get("total_comment_count")
                if isinstance(cc, dict):
                    post["comment_count"] = cc.get("total_count", cc.get("count", 0))
                sc = feedback.get("share_count")
                if isinstance(sc, dict):
                    post["share_count"] = sc.get("count", sc.get("total_count", 0))

            # URL
            if data.get("url"):
                post["url"] = data["url"]
            elif data.get("permalink_url"):
                post["url"] = data["permalink_url"]

            if post["id"]:
                posts.append(post)
                return posts  # 不再往下找

        # 另一種結構: story node
        if data.get("__typename") in ("Story", "Post") and has_creation_time:
            text = ""
            msg = data.get("message")
            if isinstance(msg, dict):
                text = msg.get("text", "")

            post = {
                "id": str(data.get("id", data.get("story_id", ""))),
                "text": text,
                "created_time": datetime.fromtimestamp(data["creation_time"]).isoformat(),
                "timestamp": data["creation_time"],
                "url": data.get("url", ""),
            }
            if post["id"]:
                posts.append(post)
                return posts

        # 遞迴搜尋子節點
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                found = find_posts_in_json(value, depth + 1)
                posts.extend(found)

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                found = find_posts_in_json(item, depth + 1)
                posts.extend(found)

    return posts


def extract_posts_from_dom(page):
    """從頁面 DOM 中提取貼文（備用方案）"""
    posts = []

    try:
        # Facebook 的貼文通常在 role="article" 的元素中
        articles = page.query_selector_all('[role="article"]')

        for i, article in enumerate(articles):
            try:
                text = ""
                # 找貼文文字（通常在 data-ad-preview="message" 或特定 div 中）
                msg_el = article.query_selector('[data-ad-preview="message"]')
                if msg_el:
                    text = msg_el.inner_text()

                if not text:
                    # 嘗試找最長的文字區塊
                    divs = article.query_selector_all('div[dir="auto"]')
                    texts = [d.inner_text() for d in divs if d.inner_text().strip()]
                    if texts:
                        text = max(texts, key=len)

                # 找時間
                time_el = article.query_selector('a[href*="/posts/"] span, a[href*="permalink"] span')
                time_text = time_el.inner_text() if time_el else ""

                # 找連結
                link_el = article.query_selector('a[href*="/posts/"], a[href*="permalink"]')
                url = ""
                if link_el:
                    href = link_el.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else f"https://www.facebook.com{href}"

                if text and len(text) > 5:
                    posts.append({
                        "id": f"dom_{i}",
                        "text": text.strip(),
                        "created_time_text": time_text,
                        "url": url,
                    })
            except Exception:
                continue

    except Exception as e:
        print(f"DOM 提取錯誤: {e}")

    return posts


def format_post(post):
    """格式化單篇貼文供顯示"""
    created = post.get("created_time") or post.get("created_time_text", "未知時間")
    if "T" in str(created):
        try:
            dt = datetime.fromisoformat(created)
            created = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass

    text = post.get("text", "(無文字內容)")
    if len(text) > 300:
        text = text[:300] + "..."

    reactions = post.get("reaction_count", "-")
    comments = post.get("comment_count", "-")
    shares = post.get("share_count", "-")
    url = post.get("url", "")

    return (
        f"[{created}]\n"
        f"{text}\n"
        f"反應: {reactions} | 留言: {comments} | 分享: {shares}\n"
        f"連結: {url}\n"
        f"{'-' * 60}"
    )


def save_to_json(posts, output_path):
    """儲存結果為 JSON"""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print(f"已儲存至 {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Facebook 粉絲專頁爬蟲 (Playwright 瀏覽器)")
    parser.add_argument("page_name", help="粉專名稱 (網址中 facebook.com/ 後面那段)")
    parser.add_argument("--cookies", "-c", default="cookies.txt", help="Cookies 檔案路徑")
    parser.add_argument("--output", "-o", default="output/posts.json", help="輸出檔案路徑")
    parser.add_argument("--scroll", "-s", type=int, default=50, help="最多捲動幾次 (預設 50，每次約載入 3-5 篇)")
    parser.add_argument("--preview", action="store_true", help="在終端機預覽貼文")
    parser.add_argument("--debug", action="store_true", help="儲存除錯資訊")
    parser.add_argument("--headed", action="store_true", help="顯示瀏覽器視窗 (方便除錯)")
    args = parser.parse_args()

    if not os.path.exists(args.cookies):
        print(f"錯誤: 找不到 cookies 檔案: {args.cookies}")
        sys.exit(1)

    print(f"正在爬取粉專: {args.page_name}")
    print("=" * 60)

    posts = scrape_with_browser(
        page_name=args.page_name,
        cookies_path=args.cookies,
        max_scrolls=args.scroll,
        output_path=args.output,
        preview=args.preview,
        debug=args.debug,
        headless=not args.headed,
    )

    if not posts:
        print("\n未取得任何貼文。可能原因：")
        print("  1. Cookies 已過期，請重新匯出")
        print("  2. 粉專名稱不正確")
        print("  3. 被 Facebook 封鎖")
        sys.exit(1)

    if args.preview:
        print("\n" + "=" * 60)
        for post in posts[:10]:
            print(format_post(post))
        if len(posts) > 10:
            print(f"\n... 還有 {len(posts) - 10} 篇貼文（請查看輸出檔案）")

    save_to_json(posts, args.output)

    # 統計
    dates = [p["created_time"] for p in posts if p.get("created_time") and "T" in p["created_time"]]
    if dates:
        oldest = min(dates)[:10]
        newest = max(dates)[:10]
        print(f"貼文時間範圍: {oldest} ~ {newest}")
    print(f"總計: {len(posts)} 篇貼文")


if __name__ == "__main__":
    main()
