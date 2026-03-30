"""
Facebook 粉絲專頁爬蟲 - 直接爬取版本

策略：
1. 先訪問粉專頁面取得頁面 ID 和必要 token
2. 使用 Facebook 內部的 GraphQL API 取得貼文
3. 自動分頁爬取所有歷史貼文

使用方式:
    python scraper_direct.py <粉專名稱> --cookies cookies.txt [--output output.json] [--limit 100]
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from http.cookiejar import MozillaCookieJar

import requests


def load_cookies(cookies_path):
    """從 Netscape 格式的 cookies 檔案載入 cookies"""
    jar = MozillaCookieJar(cookies_path)
    jar.load(ignore_discard=True, ignore_expires=True)
    session = requests.Session()
    session.cookies = jar
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "*/*",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
    })
    return session


def extract_tokens_from_page(session, page_name, debug=False):
    """從粉專頁面 HTML 中提取必要的 token 和 page ID"""
    url = f"https://www.facebook.com/{page_name}"
    resp = session.get(url, timeout=30)

    if debug:
        os.makedirs("output", exist_ok=True)
        with open("output/debug_page.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(f"[DEBUG] 已儲存 HTML ({len(resp.text)} 字元) -> output/debug_page.html")
        print(f"[DEBUG] 回應 URL: {resp.url}")

    html = resp.text

    # 提取 fb_dtsg token (CSRF token)
    dtsg_match = re.search(r'"DTSGInitialData".*?"token":"([^"]+)"', html)
    if not dtsg_match:
        dtsg_match = re.search(r'name="fb_dtsg" value="([^"]+)"', html)
    if not dtsg_match:
        dtsg_match = re.search(r'"dtsg":\{"token":"([^"]+)"', html)
    fb_dtsg = dtsg_match.group(1) if dtsg_match else None

    # 提取 page ID
    page_id = None
    # 方法1: pageID
    pid_match = re.search(r'"pageID":"(\d+)"', html)
    if pid_match:
        page_id = pid_match.group(1)
    # 方法2: page_id
    if not page_id:
        pid_match = re.search(r'"page_id":"(\d+)"', html)
        if pid_match:
            page_id = pid_match.group(1)
    # 方法3: content_owner_id_new
    if not page_id:
        pid_match = re.search(r'"content_owner_id_new":"(\d+)"', html)
        if pid_match:
            page_id = pid_match.group(1)
    # 方法4: userID 或 entity_id
    if not page_id:
        pid_match = re.search(r'"entity_id":"(\d+)"', html)
        if pid_match:
            page_id = pid_match.group(1)
    # 方法5: fb://page/ID
    if not page_id:
        pid_match = re.search(r'fb://page/(\d+)', html)
        if pid_match:
            page_id = pid_match.group(1)
    # 方法6: ownerID or profileID
    if not page_id:
        pid_match = re.search(r'"(?:ownerID|profileID|userID)":"(\d+)"', html)
        if pid_match:
            page_id = pid_match.group(1)

    # 提取 lsd token
    lsd_match = re.search(r'"LSD".*?\[.*?"(\w+)"\]', html)
    if not lsd_match:
        lsd_match = re.search(r'name="lsd" value="([^"]+)"', html)
    lsd = lsd_match.group(1) if lsd_match else None

    # 提取 jazoest
    jazoest_match = re.search(r'jazoest=(\d+)', html)
    jazoest = jazoest_match.group(1) if jazoest_match else None

    # 提取 __user (自己的 user ID)
    user_match = re.search(r'"USER_ID":"(\d+)"', html)
    if not user_match:
        user_match = re.search(r'"actorID":"(\d+)"', html)
    user_id = user_match.group(1) if user_match else None

    # 提取 __rev (revision)
    rev_match = re.search(r'"__spin_r":(\d+)', html)
    if not rev_match:
        rev_match = re.search(r'"server_revision":(\d+)', html)
    revision = rev_match.group(1) if rev_match else None

    # 提取 hsi
    hsi_match = re.search(r'"hsi":"(\d+)"', html)
    hsi = hsi_match.group(1) if hsi_match else None

    # 也嘗試直接從 HTML 提取貼文（首次載入頁面就有一些貼文）
    initial_posts = extract_posts_from_html(html, debug)

    if debug:
        print(f"[DEBUG] fb_dtsg: {'找到' if fb_dtsg else '未找到'}")
        print(f"[DEBUG] page_id: {page_id or '未找到'}")
        print(f"[DEBUG] lsd: {'找到' if lsd else '未找到'}")
        print(f"[DEBUG] user_id: {user_id or '未找到'}")
        print(f"[DEBUG] revision: {revision or '未找到'}")
        print(f"[DEBUG] 從首頁提取到 {len(initial_posts)} 篇貼文")

    return {
        "fb_dtsg": fb_dtsg,
        "page_id": page_id,
        "lsd": lsd,
        "jazoest": jazoest,
        "user_id": user_id,
        "revision": revision,
        "hsi": hsi,
        "initial_posts": initial_posts,
    }


def extract_posts_from_html(html, debug=False):
    """從 Facebook 頁面 HTML 中嵌入的 JSON 提取貼文"""
    posts = []
    seen_ids = set()

    # Facebook 在 HTML 中嵌入了大量 JSON 資料
    # 尋找包含貼文內容的 JSON 片段

    # 方法1: 找 "message" 欄位附近的 JSON 物件
    # Facebook 的貼文資料通常包含 "message":{"text":"..."} 結構
    message_pattern = re.compile(
        r'"message":\{"text":"((?:[^"\\]|\\.)*)"\}',
    )

    # 方法2: 找 creation_time 和 message 配對
    # 格式: "creation_time":1234567890,...,"message":{"text":"..."}
    post_block_pattern = re.compile(
        r'"post_id":"([^"]+)".*?"creation_time":(\d+).*?"message":\{"text":"((?:[^"\\]|\\.)*?)"\}',
        re.DOTALL
    )

    # 方法3: 更寬鬆的搜尋 - 找所有 story/post 相關的 JSON
    story_pattern = re.compile(
        r'"story":\{[^}]*"creation_time":(\d+)[^}]*"message":\{"text":"((?:[^"\\]|\\.)*?)"\}',
        re.DOTALL
    )

    # 嘗試方法: 找所有包含 creation_time 的 JSON 區塊
    # Facebook 會把貼文資料嵌入在 <script> 標籤中
    creation_time_pattern = re.compile(r'"creation_time":(\d{10})')
    message_text_pattern = re.compile(r'"message":\{"text":"((?:[^"\\]|\\.)*)"\}')

    # 找所有 JSON-like 的 script 標籤
    script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)

    for block in script_blocks:
        if '"creation_time"' not in block:
            continue

        # 在這個 script block 中找 post_id + creation_time + message 的組合
        for match in post_block_pattern.finditer(block):
            post_id = match.group(1)
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            timestamp = int(match.group(2))
            text = match.group(3)
            text = decode_unicode_escapes(text)

            posts.append({
                "id": post_id,
                "text": text,
                "created_time": datetime.fromtimestamp(timestamp).isoformat(),
                "timestamp": timestamp,
            })

    # 如果方法2沒找到，嘗試更通用的方式
    if not posts:
        # 找所有 creation_time 和就近的 message
        all_json_text = " ".join(script_blocks)

        # 嘗試找 node -> comet_sections -> content -> story -> message 結構
        # 這是 Facebook 現代版的資料結構
        node_pattern = re.compile(
            r'"node":\{[^{]*?"id":"(\d+)".*?"creation_time":(\d{10})',
            re.DOTALL
        )

        for match in node_pattern.finditer(all_json_text):
            post_id = match.group(1)
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            timestamp = int(match.group(2))

            # 試著在附近找到 message text
            start = max(0, match.start() - 500)
            end = min(len(all_json_text), match.end() + 2000)
            nearby = all_json_text[start:end]

            text = ""
            msg_match = message_text_pattern.search(nearby)
            if msg_match:
                text = decode_unicode_escapes(msg_match.group(1))

            posts.append({
                "id": post_id,
                "text": text,
                "created_time": datetime.fromtimestamp(timestamp).isoformat(),
                "timestamp": timestamp,
            })

    # 如果還是沒有，嘗試最寬鬆的搜尋
    if not posts:
        for block in script_blocks:
            for msg_match in message_text_pattern.finditer(block):
                text = decode_unicode_escapes(msg_match.group(1))
                if len(text) > 20:  # 過濾太短的
                    # 在附近找 creation_time
                    start = max(0, msg_match.start() - 1000)
                    nearby = block[start:msg_match.end()]
                    time_match = creation_time_pattern.search(nearby)

                    timestamp = int(time_match.group(1)) if time_match else 0
                    post_id = f"unknown_{len(posts)}"

                    # 找附近的 post_id
                    id_match = re.search(r'"post_id":"([^"]+)"', nearby)
                    if id_match:
                        post_id = id_match.group(1)

                    if post_id not in seen_ids:
                        seen_ids.add(post_id)
                        posts.append({
                            "id": post_id,
                            "text": text,
                            "created_time": datetime.fromtimestamp(timestamp).isoformat() if timestamp else "",
                            "timestamp": timestamp,
                        })

    # 依時間排序（新的在前）
    posts.sort(key=lambda p: p.get("timestamp", 0), reverse=True)

    return posts


def fetch_more_posts_graphql(session, tokens, cursor=None, debug=False):
    """透過 Facebook GraphQL API 取得更多貼文"""
    if not tokens.get("fb_dtsg") or not tokens.get("page_id"):
        return [], None

    url = "https://www.facebook.com/api/graphql/"

    # PageTimelineFeedQuery 的 doc_id（這個值可能會隨 Facebook 版本變動）
    # 常見的 doc_id
    doc_ids = [
        "9432605916771498",   # PageTimelineFeedQuery
        "7349867498405938",   # CometPageTimelineFeedQuery
        "6539270149468498",   # PageProfileTimelineFeedQuery
    ]

    variables = {
        "pageID": tokens["page_id"],
        "count": 3,
        "cursor": cursor or "",
        "privacySelectorRenderLocation": "COMET_STREAM",
        "renderLocation": "timeline",
        "scale": 1,
        "id": tokens["page_id"],
    }

    for doc_id in doc_ids:
        data = {
            "fb_dtsg": tokens["fb_dtsg"],
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "PageTimelineFeedQuery",
            "variables": json.dumps(variables),
            "doc_id": doc_id,
        }

        if tokens.get("lsd"):
            data["lsd"] = tokens["lsd"]

        try:
            resp = session.post(url, data=data, timeout=30)
            if resp.status_code == 200:
                return parse_graphql_response(resp.text, debug)
        except requests.exceptions.RequestException as e:
            if debug:
                print(f"[DEBUG] GraphQL 請求失敗 (doc_id={doc_id}): {e}")
            continue

    return [], None


def parse_graphql_response(response_text, debug=False):
    """解析 GraphQL API 回應"""
    posts = []
    next_cursor = None

    if debug:
        os.makedirs("output", exist_ok=True)
        with open("output/debug_graphql.json", "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"[DEBUG] 已儲存 GraphQL 回應 -> output/debug_graphql.json")

    # Facebook GraphQL 回應可能是多行 JSON
    for line in response_text.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # 遞迴搜尋 JSON 中的貼文
        found_posts, cursor = search_json_for_posts(data)
        posts.extend(found_posts)
        if cursor:
            next_cursor = cursor

    return posts, next_cursor


def search_json_for_posts(data, depth=0):
    """遞迴搜尋 JSON 結構中的貼文資料"""
    posts = []
    cursor = None

    if depth > 20 or data is None:
        return posts, cursor

    if isinstance(data, dict):
        # 找 cursor (分頁)
        if "end_cursor" in data and data.get("has_next_page"):
            cursor = data["end_cursor"]

        # 找貼文節點
        if "creation_time" in data and "message" in data:
            post = {
                "id": data.get("id", data.get("post_id", "")),
                "text": data.get("message", {}).get("text", "") if isinstance(data.get("message"), dict) else str(data.get("message", "")),
                "created_time": datetime.fromtimestamp(data["creation_time"]).isoformat(),
                "timestamp": data["creation_time"],
            }
            if data.get("feedback"):
                fb = data["feedback"]
                post["reaction_count"] = fb.get("reaction_count", {}).get("count", 0)
                post["comment_count"] = fb.get("comment_count", {}).get("total_count", 0)
                post["share_count"] = fb.get("share_count", {}).get("count", 0)
            posts.append(post)

        # 遞迴搜尋
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                found, c = search_json_for_posts(value, depth + 1)
                posts.extend(found)
                if c:
                    cursor = c

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                found, c = search_json_for_posts(item, depth + 1)
                posts.extend(found)
                if c:
                    cursor = c

    return posts, cursor


def decode_unicode_escapes(text):
    """解碼 JSON 中的 Unicode 跳脫字元"""
    try:
        # 處理 \uXXXX 跳脫
        text = text.encode('utf-8').decode('unicode_escape', errors='replace')
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    # 處理常見的跳脫
    text = text.replace("\\n", "\n")
    text = text.replace("\\t", "\t")
    text = text.replace('\\"', '"')
    text = text.replace("\\/", "/")
    return text


def scrape_all_posts(session, page_name, limit=None, debug=False):
    """爬取粉專所有貼文"""
    print("步驟 1: 載入粉專頁面，提取 token...")
    tokens = extract_tokens_from_page(session, page_name, debug)

    if not tokens["page_id"]:
        print("錯誤: 無法取得粉專 ID，請確認名稱是否正確")
        return []

    print(f"粉專 ID: {tokens['page_id']}")

    all_posts = list(tokens.get("initial_posts", []))
    seen_ids = {p["id"] for p in all_posts}

    if all_posts:
        print(f"從首頁取得 {len(all_posts)} 篇貼文")

    # 嘗試透過 GraphQL 取得更多貼文
    if tokens.get("fb_dtsg"):
        print("\n步驟 2: 透過 API 取得更多貼文...")
        cursor = None
        page_count = 0
        consecutive_empty = 0

        while True:
            if limit and len(all_posts) >= limit:
                all_posts = all_posts[:limit]
                break

            posts, next_cursor = fetch_more_posts_graphql(session, tokens, cursor, debug)
            page_count += 1

            new_posts = [p for p in posts if p.get("id") and p["id"] not in seen_ids]
            for p in new_posts:
                seen_ids.add(p["id"])
            all_posts.extend(new_posts)

            print(f"\r已取得 {len(all_posts)} 篇貼文 (API 第 {page_count} 頁)...", end="", flush=True)

            if not new_posts:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print("\n連續 3 頁沒有新貼文，停止")
                    break
            else:
                consecutive_empty = 0

            if not next_cursor:
                print("\n已到最後一頁")
                break

            cursor = next_cursor
            time.sleep(1.5)
    else:
        print("無法取得 API token，僅使用首頁的貼文")

    # 排序
    all_posts.sort(key=lambda p: p.get("timestamp", 0), reverse=True)

    print(f"\n共取得 {len(all_posts)} 篇貼文")
    return all_posts


def format_post(post):
    """格式化單篇貼文供顯示"""
    created = post.get("created_time", "未知時間")
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

    stats = f"反應: {reactions} | 留言: {comments} | 分享: {shares}"

    return (
        f"[{created}]\n"
        f"{text}\n"
        f"{stats}\n"
        f"{'-' * 60}"
    )


def save_to_json(posts, output_path):
    """儲存結果為 JSON"""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print(f"已儲存至 {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Facebook 粉絲專頁爬蟲")
    parser.add_argument("page_name", help="粉專名稱 (網址中 facebook.com/ 後面那段)")
    parser.add_argument("--cookies", "-c", default="cookies.txt", help="Cookies 檔案路徑")
    parser.add_argument("--output", "-o", default="output/posts.json", help="輸出檔案路徑")
    parser.add_argument("--limit", "-l", type=int, default=None, help="最多取得幾篇貼文")
    parser.add_argument("--preview", action="store_true", help="在終端機預覽貼文")
    parser.add_argument("--debug", action="store_true", help="儲存原始回應供除錯")
    args = parser.parse_args()

    if not os.path.exists(args.cookies):
        print(f"錯誤: 找不到 cookies 檔案: {args.cookies}")
        sys.exit(1)

    print(f"正在爬取粉專: {args.page_name}")
    print("=" * 60)

    session = load_cookies(args.cookies)
    posts = scrape_all_posts(session, args.page_name, limit=args.limit, debug=args.debug)

    if not posts:
        print("未取得任何貼文。可能原因：")
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
    dates = [p["created_time"] for p in posts if p.get("created_time")]
    if dates:
        oldest = min(dates)[:10]
        newest = max(dates)[:10]
        print(f"貼文時間範圍: {oldest} ~ {newest}")
    print(f"總計: {len(posts)} 篇貼文")


if __name__ == "__main__":
    main()
