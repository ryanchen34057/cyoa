"""
Facebook 粉絲專頁爬蟲 - 直接爬取版本（使用 requests + cookies）

使用方式:
    python scraper_direct.py <粉專名稱> [--cookies cookies.txt] [--output output.json] [--pages 10]
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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
    })
    return session


def extract_posts_from_html(html):
    """從 HTML 中提取貼文資料"""
    posts = []

    # 嘗試從 HTML 中解析貼文 - Facebook 的 HTML 結構會變動
    # 找尋貼文的 userContent 或 message 區塊
    # Facebook 使用 data-ft 屬性儲存貼文 metadata
    post_pattern = re.compile(
        r'data-ft=\'\{[^}]*"mf_story_key":"(\d+)"[^}]*\}\'',
        re.DOTALL
    )

    for match in post_pattern.finditer(html):
        post_id = match.group(1)
        posts.append({"id": post_id})

    return posts


def fetch_page_mbasic(session, page_name, max_pages=None, debug=False):
    """使用 mbasic.facebook.com 爬取（較簡單的 HTML 結構）"""
    base_url = f"https://mbasic.facebook.com/{page_name}"
    all_posts = []
    url = base_url
    page_count = 0

    while url:
        if max_pages and page_count >= max_pages:
            break

        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"\n請求錯誤: {e}")
            break

        html = resp.text
        page_count += 1

        # Debug: 儲存原始 HTML
        if debug:
            debug_path = f"output/debug_page_{page_count}.html"
            os.makedirs("output", exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\n[DEBUG] 已儲存原始 HTML: {debug_path}")
            print(f"[DEBUG] 回應 URL: {resp.url}")
            print(f"[DEBUG] HTML 長度: {len(html)} 字元")

        # 檢查是否需要登入
        if "login" in resp.url and page_count == 1:
            print("錯誤: 需要登入。請確認 cookies 是否有效。")
            break

        # 從 mbasic 頁面提取貼文
        posts = parse_mbasic_posts(html)
        if not posts:
            print(f"\n第 {page_count} 頁沒有找到貼文，停止爬取")
            break

        all_posts.extend(posts)
        print(f"\r已取得 {len(all_posts)} 篇貼文 (第 {page_count} 頁)...", end="", flush=True)

        # 找「顯示更多」連結
        next_link = find_next_page_link(html, page_name)
        if next_link:
            url = "https://mbasic.facebook.com" + next_link if next_link.startswith("/") else next_link
        else:
            url = None

        time.sleep(2)  # 避免太快被封鎖

    print(f"\n共取得 {len(all_posts)} 篇貼文")
    return all_posts


def parse_mbasic_posts(html):
    """解析 mbasic.facebook.com 的貼文"""
    posts = []

    # mbasic 版本的貼文被包在 article 標籤或特定 div 中
    # 用正則提取貼文區塊
    # 每篇貼文通常在 <article> 或 <div role="article"> 中

    # 方法1: 找 article 標籤
    article_pattern = re.compile(
        r'<article[^>]*>(.*?)</article>',
        re.DOTALL
    )

    # 方法2: 找 story_body_container
    story_pattern = re.compile(
        r'<div[^>]*data-ft=["\'][^"\']*story_fbid[^"\']*["\'][^>]*>(.*?)</div>\s*</div>\s*</div>',
        re.DOTALL
    )

    articles = article_pattern.findall(html)

    if not articles:
        # 備用：找包含 story_body 的區塊
        articles = story_pattern.findall(html)

    for article_html in articles:
        post = extract_post_data(article_html)
        if post and (post.get("text") or post.get("id")):
            posts.append(post)

    return posts


def extract_post_data(article_html):
    """從單篇貼文的 HTML 中提取資料"""
    post = {}

    # 提取貼文 ID
    story_id_match = re.search(r'story_fbid=(\d+)', article_html)
    if story_id_match:
        post["id"] = story_id_match.group(1)

    pfbid_match = re.search(r'pfbid\w+', article_html)
    if pfbid_match:
        post["id"] = pfbid_match.group(0)

    # 提取貼文連結
    permalink_match = re.search(r'href="(/[^"]*?/posts/[^"]*?)"', article_html)
    if not permalink_match:
        permalink_match = re.search(r'href="(/permalink\.php\?[^"]*?)"', article_html)
    if not permalink_match:
        permalink_match = re.search(r'href="(/story\.php\?[^"]*?)"', article_html)
    if permalink_match:
        post["url"] = "https://www.facebook.com" + permalink_match.group(1).replace("&amp;", "&")

    # 提取時間
    time_match = re.search(r'data-utime="(\d+)"', article_html)
    if time_match:
        timestamp = int(time_match.group(1))
        post["created_time"] = datetime.fromtimestamp(timestamp).isoformat()
    else:
        # mbasic 版本的時間格式
        time_match = re.search(r'<abbr[^>]*>(.*?)</abbr>', article_html)
        if time_match:
            post["created_time_text"] = clean_html(time_match.group(1))

    # 提取文字內容
    # 找 <p> 標籤中的文字
    text_parts = []
    p_pattern = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL)
    for p_match in p_pattern.finditer(article_html):
        text = clean_html(p_match.group(1))
        if text and len(text) > 1:
            text_parts.append(text)

    # 也找 span 中的文字（有些貼文用 span）
    if not text_parts:
        span_pattern = re.compile(r'<span[^>]*class="[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
        for s_match in span_pattern.finditer(article_html):
            text = clean_html(s_match.group(1))
            if text and len(text) > 10 and '<' not in text:
                text_parts.append(text)

    post["text"] = "\n".join(text_parts) if text_parts else ""

    # 提取互動數據
    like_match = re.search(r'(\d+)\s*人[都對]?.*?(?:讚|like)', article_html, re.IGNORECASE)
    if like_match:
        post["likes"] = int(like_match.group(1))

    comment_match = re.search(r'(\d+)\s*則?留言', article_html)
    if comment_match:
        post["comments_count"] = int(comment_match.group(1))

    share_match = re.search(r'(\d+)\s*次?分享', article_html)
    if share_match:
        post["shares"] = int(share_match.group(1))

    # 提取圖片
    img_match = re.search(r'<img[^>]*src="(https://[^"]*?(?:scontent|fbcdn)[^"]*?)"', article_html)
    if img_match:
        post["image"] = img_match.group(1).replace("&amp;", "&")

    return post


def find_next_page_link(html, page_name):
    """找到「查看更多貼文」或「顯示更多」的連結"""
    # mbasic 的「更多」連結
    patterns = [
        re.compile(r'href="(/[^"]*?' + re.escape(page_name) + r'[^"]*?\?[^"]*?)"[^>]*>[^<]*(?:顯示更多|查看更多|See More|Show more)', re.IGNORECASE),
        re.compile(r'href="(/page_content_list_view/more/\?[^"]*?)"', re.IGNORECASE),
        re.compile(r'href="(/pages/more/\?[^"]*?)"', re.IGNORECASE),
        # 通用的「更多」連結
        re.compile(r'<a[^>]*href="([^"]*)"[^>]*>\s*(?:顯示更多|查看更多|See More Stories|更多)\s*</a>', re.IGNORECASE),
        # Timeline cursor 分頁連結
        re.compile(r'href="(/[^"]*?timeline[^"]*?cursor[^"]*?)"', re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(html)
        if match:
            return match.group(1).replace("&amp;", "&")

    return None


def clean_html(text):
    """移除 HTML 標籤"""
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#x27;', "'", text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


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

    likes = post.get("likes", "-")
    comments = post.get("comments_count", "-")
    shares = post.get("shares", "-")
    url = post.get("url", "")

    return (
        f"[{created}]\n"
        f"{text}\n"
        f"讚: {likes} | 留言: {comments} | 分享: {shares}\n"
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
    parser = argparse.ArgumentParser(description="Facebook 粉絲專頁爬蟲 (直接爬取)")
    parser.add_argument("page_name", help="粉專名稱 (網址中 facebook.com/ 後面那段)")
    parser.add_argument("--cookies", "-c", default="cookies.txt", help="Cookies 檔案路徑 (預設: cookies.txt)")
    parser.add_argument("--output", "-o", default="output/posts.json", help="輸出檔案路徑")
    parser.add_argument("--pages", "-p", type=int, default=None, help="最多爬幾頁 (不指定則爬到底)")
    parser.add_argument("--preview", action="store_true", help="在終端機預覽貼文")
    parser.add_argument("--debug", action="store_true", help="儲存原始 HTML 供除錯")
    args = parser.parse_args()

    if not os.path.exists(args.cookies):
        print(f"錯誤: 找不到 cookies 檔案: {args.cookies}")
        print("請提供 Netscape 格式的 Facebook cookies 檔案")
        sys.exit(1)

    print(f"正在爬取粉專: {args.page_name}")
    print(f"使用 mbasic.facebook.com (行動簡易版)")
    print("=" * 60)

    session = load_cookies(args.cookies)
    posts = fetch_page_mbasic(session, args.page_name, max_pages=args.pages, debug=args.debug)

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
    print(f"總計: {len(posts)} 篇貼文")


if __name__ == "__main__":
    main()
