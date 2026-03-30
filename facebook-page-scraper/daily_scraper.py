"""
每日增量爬取 Facebook 粉專新貼文，並輸出為 Claude Projects 格式

功能：
    - 記住上次爬到的最新貼文，只抓新的
    - 輸出格式化的 Markdown 檔案，可直接上傳到 Claude Projects
    - 支援 Windows Task Scheduler 排程

使用方式：
    # 首次執行（會爬所有貼文）
    python daily_scraper.py chihyunstock --cookies cookies.txt --scroll 500

    # 之後每日執行（只抓新文）
    python daily_scraper.py chihyunstock --cookies cookies.txt

設定 Windows 排程：
    python daily_scraper.py --install-schedule chihyunstock --cookies cookies.txt
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# ============================================================
# 設定
# ============================================================

DATA_DIR = Path("output")
STATE_FILE = DATA_DIR / "last_state.json"
POSTS_FILE = DATA_DIR / "all_posts.json"
CLAUDE_FILE = DATA_DIR / "claude_knowledge.md"


# ============================================================
# Cookie 處理
# ============================================================

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


# ============================================================
# 狀態管理
# ============================================================

def load_state():
    """載入上次爬取狀態"""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_post_ids": [], "last_timestamp": 0, "total_posts": 0}


def save_state(state):
    """儲存爬取狀態"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_existing_posts():
    """載入已存的所有貼文"""
    if POSTS_FILE.exists():
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_all_posts(posts):
    """儲存所有貼文"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean_posts = []
    for post in posts:
        clean = {}
        for k, v in post.items():
            if isinstance(v, str):
                v = re.sub(r'[\ud800-\udfff]', '', v)
            clean[k] = v
        clean_posts.append(clean)
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_posts, f, ensure_ascii=False, indent=2)


# ============================================================
# 文字解碼
# ============================================================

def decode_fb_text(text):
    """安全解碼 Facebook JSON 中的 Unicode 跳脫字元"""
    try:
        text = json.loads('"' + text + '"')
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        text = text.replace("\\n", "\n")
        text = text.replace("\\t", "\t")
        text = text.replace('\\"', '"')
        text = text.replace("\\/", "/")
    text = re.sub(r'[\ud800-\udfff]', '', text)
    return text


# ============================================================
# 爬蟲核心
# ============================================================

def extract_posts_from_graphql(response_text):
    """從 GraphQL 回應中用 regex 提取貼文"""
    posts = []
    seen_ids = set()

    post_id_pattern = re.compile(r'"post_id":"(\d+)"')
    creation_time_pattern = re.compile(r'"creation_time":(\d{10})')
    message_text_pattern = re.compile(r'"message":\{(?:[^{}]*"text":"((?:[^"\\]|\\.)*?)")')
    url_pattern = re.compile(r'"url":"(https:\\/\\/www\.facebook\.com\\/[^"]*?\\/posts\\/[^"]*?)"')

    post_id_positions = {}
    for m in post_id_pattern.finditer(response_text):
        pid = m.group(1)
        if pid not in post_id_positions:
            post_id_positions[pid] = m.start()

    for pid, pos in post_id_positions.items():
        if pid in seen_ids:
            continue

        search_start = max(0, pos - 5000)
        search_end = min(len(response_text), pos + 5000)
        nearby = response_text[search_start:search_end]

        timestamp = 0
        ct_match = creation_time_pattern.search(nearby)
        if ct_match:
            timestamp = int(ct_match.group(1))

        text = ""
        for mt_match in message_text_pattern.finditer(nearby):
            candidate = mt_match.group(1)
            if len(candidate) > len(text):
                text = candidate

        url = ""
        url_match = url_pattern.search(nearby)
        if url_match:
            url = url_match.group(1).replace("\\/", "/")

        if text:
            text = decode_fb_text(text)

        if timestamp > 0 or text:
            seen_ids.add(pid)
            post = {
                "id": pid,
                "text": text,
                "timestamp": timestamp,
                "url": url,
            }
            if timestamp > 0:
                post["created_time"] = datetime.fromtimestamp(timestamp).isoformat()
            posts.append(post)

    return posts


def scrape_posts(page_name, cookies_path, max_scrolls=10, known_ids=None):
    """爬取貼文，如有 known_ids 則遇到已知貼文時提早停止"""
    if known_ids is None:
        known_ids = set()

    all_posts = {}
    found_known = 0

    def handle_response(response):
        nonlocal found_known
        try:
            if "graphql" in response.url:
                body = response.text()
                if len(body) > 5000:
                    posts = extract_posts_from_graphql(body)
                    for post in posts:
                        pid = post.get("id", "")
                        if pid and pid not in all_posts:
                            if pid in known_ids:
                                found_known += 1
                            else:
                                all_posts[pid] = post
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-TW",
        )
        context.add_cookies(load_cookies_for_playwright(cookies_path))

        page = context.new_page()
        page.on("response", handle_response)

        url = f"https://www.facebook.com/{page_name}"
        print(f"載入: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        time.sleep(5)

        if "login" in page.url:
            print("錯誤: 需要登入，cookies 可能已過期")
            browser.close()
            return []

        # 關閉彈出視窗
        try:
            for btn in page.query_selector_all('[aria-label="關閉"], [aria-label="Close"]'):
                btn.click()
                time.sleep(0.5)
        except Exception:
            pass

        no_new_count = 0
        for scroll_num in range(1, max_scrolls + 1):
            prev_count = len(all_posts)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

            current_count = len(all_posts)
            new_this_scroll = current_count - prev_count

            print(f"\r捲動 {scroll_num}/{max_scrolls} | 新貼文: {current_count} | 已知: {found_known}", end="", flush=True)

            # 增量模式：遇到夠多已知貼文就停止
            if known_ids and found_known >= 5:
                print(f"\n已遇到 {found_known} 篇舊貼文，停止爬取")
                break

            if new_this_scroll == 0:
                no_new_count += 1
                if no_new_count >= 5:
                    print(f"\n連續 {no_new_count} 次沒有新貼文，已到底部")
                    break
            else:
                no_new_count = 0

        browser.close()

    posts = list(all_posts.values())
    posts.sort(key=lambda p: p.get("timestamp", 0), reverse=True)
    print(f"\n取得 {len(posts)} 篇新貼文")
    return posts


# ============================================================
# Claude Projects 格式輸出
# ============================================================

def generate_claude_knowledge(posts, page_name):
    """產生適合上傳到 Claude Projects 的 Markdown 檔案"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 按時間排序（舊到新）
    sorted_posts = sorted(posts, key=lambda p: p.get("timestamp", 0))

    lines = []
    lines.append(f"# {page_name} - Facebook 貼文紀錄")
    lines.append(f"")
    lines.append(f"最後更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"總貼文數: {len(posts)}")
    lines.append(f"")
    lines.append("---")
    lines.append("")

    for post in sorted_posts:
        created = post.get("created_time", "")
        if created and "T" in created:
            try:
                dt = datetime.fromisoformat(created)
                created = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass

        text = post.get("text", "").strip()
        text = re.sub(r'[\ud800-\udfff]', '', text)
        url = post.get("url", "")

        if not text:
            continue

        lines.append(f"## [{created}]")
        lines.append("")
        lines.append(text)
        lines.append("")
        if url:
            lines.append(f"連結: {url}")
            lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)

    with open(CLAUDE_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    size_kb = len(content.encode("utf-8")) / 1024
    print(f"已產生 Claude Knowledge 檔案: {CLAUDE_FILE} ({size_kb:.1f} KB)")
    return CLAUDE_FILE


# ============================================================
# Windows 排程安裝
# ============================================================

def install_windows_schedule(page_name, cookies_path):
    """產生 Windows Task Scheduler 的 batch 檔和指示"""
    script_dir = Path(__file__).parent.resolve()
    bat_file = script_dir / "run_daily.bat"

    bat_content = f"""@echo off
cd /d "{script_dir}"
python daily_scraper.py {page_name} --cookies {cookies_path}
"""

    with open(bat_file, "w", encoding="utf-8") as f:
        f.write(bat_content)

    print(f"已建立 {bat_file}")
    print()
    print("請用以下步驟設定 Windows 排程:")
    print("=" * 50)
    print("1. 按 Win+R，輸入 taskschd.msc，按 Enter")
    print("2. 右側點擊「建立基本工作」")
    print(f'3. 名稱填: Facebook_{page_name}_爬蟲')
    print("4. 觸發程序選「每天」")
    print("5. 設定執行時間 (例: 08:00)")
    print(f'6. 動作選「啟動程式」，程式填:')
    print(f'   {bat_file}')
    print("7. 完成！")
    print()
    print("或用命令列直接建立:")
    print(f'schtasks /create /tn "Facebook_{page_name}" /tr "{bat_file}" /sc daily /st 08:00')


# ============================================================
# 主程式
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="每日 Facebook 粉專爬蟲 + Claude Knowledge 輸出")
    parser.add_argument("page_name", help="粉專名稱")
    parser.add_argument("--cookies", "-c", default="cookies.txt", help="Cookies 檔案路徑")
    parser.add_argument("--scroll", "-s", type=int, default=20,
                        help="最多捲動次數 (首次建議 500，之後預設 20 就夠)")
    parser.add_argument("--full", action="store_true", help="強制全量爬取（忽略已知貼文）")
    parser.add_argument("--install-schedule", action="store_true", help="安裝 Windows 每日排程")
    args = parser.parse_args()

    if not os.path.exists(args.cookies):
        print(f"錯誤: 找不到 cookies 檔案: {args.cookies}")
        sys.exit(1)

    if args.install_schedule:
        install_windows_schedule(args.page_name, args.cookies)
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Facebook 每日爬蟲: {args.page_name} ===")
    print(f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 載入既有資料
    state = load_state()
    existing_posts = load_existing_posts()
    known_ids = {p["id"] for p in existing_posts if p.get("id")}

    if args.full:
        known_ids = set()
        print(f"全量模式: 忽略 {len(existing_posts)} 篇已知貼文")
    else:
        print(f"增量模式: 已有 {len(existing_posts)} 篇貼文")

    # 爬取新貼文
    new_posts = scrape_posts(
        page_name=args.page_name,
        cookies_path=args.cookies,
        max_scrolls=args.scroll,
        known_ids=known_ids if not args.full else None,
    )

    if new_posts:
        # 合併新舊貼文（用 id 去重）
        posts_dict = {p["id"]: p for p in existing_posts if p.get("id")}
        for p in new_posts:
            if p.get("id"):
                posts_dict[p["id"]] = p

        all_posts = list(posts_dict.values())
        all_posts.sort(key=lambda p: p.get("timestamp", 0), reverse=True)

        # 儲存
        save_all_posts(all_posts)
        print(f"已儲存 {len(all_posts)} 篇貼文至 {POSTS_FILE}")

        # 更新狀態
        state["last_post_ids"] = [p["id"] for p in all_posts[:20]]
        state["last_timestamp"] = max(p.get("timestamp", 0) for p in all_posts)
        state["total_posts"] = len(all_posts)
        state["last_run"] = datetime.now().isoformat()
        save_state(state)

        # 產生 Claude Knowledge 檔案
        generate_claude_knowledge(all_posts, args.page_name)

        # 預覽新貼文
        print(f"\n=== 新增 {len(new_posts)} 篇貼文 ===")
        for post in new_posts[:5]:
            text = re.sub(r'[\ud800-\udfff]', '', post.get("text", ""))
            if len(text) > 100:
                text = text[:100] + "..."
            created = post.get("created_time", "?")
            print(f"  [{created}] {text}")
        if len(new_posts) > 5:
            print(f"  ... 還有 {len(new_posts) - 5} 篇")

        print(f"\n上傳 {CLAUDE_FILE} 到你的 Claude Project 即可！")
    else:
        print("沒有新貼文")


if __name__ == "__main__":
    main()
