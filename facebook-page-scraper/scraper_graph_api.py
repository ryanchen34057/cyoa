"""
Facebook 粉絲專頁爬蟲 - 使用 Graph API

使用方式:
    python scraper_graph_api.py <粉專ID或名稱> [--output output.json] [--limit 100]

需要先設定 FB_ACCESS_TOKEN 環境變數或在 .env 檔案中設定。

取得 Access Token:
    1. 前往 https://developers.facebook.com/tools/explorer/
    2. 選擇你的應用程式
    3. 勾選 pages_read_engagement 權限
    4. 點擊「Generate Access Token」
    5. 將 token 貼到 .env 檔案中
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


def get_access_token():
    token = os.getenv("FB_ACCESS_TOKEN")
    if not token:
        print("錯誤: 請設定 FB_ACCESS_TOKEN 環境變數或在 .env 檔案中設定")
        print("取得方式: https://developers.facebook.com/tools/explorer/")
        sys.exit(1)
    return token


def fetch_page_posts(page_id, access_token, limit=None):
    """透過 Graph API 取得粉專所有貼文"""
    url = f"{GRAPH_API_BASE}/{page_id}/posts"
    params = {
        "access_token": access_token,
        "fields": "id,message,created_time,full_picture,permalink_url,"
                  "shares,type,status_type,attachments{description,media,url,type}",
        "limit": 100,  # 每頁最多 100 筆
    }

    all_posts = []
    page_count = 0

    while url:
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_data = e.response.json() if e.response else {}
            error_msg = error_data.get("error", {}).get("message", str(e))
            print(f"\nAPI 錯誤: {error_msg}")
            if "OAuthException" in str(error_data):
                print("提示: Access Token 可能已過期，請重新取得")
            break
        except requests.exceptions.RequestException as e:
            print(f"\n網路錯誤: {e}")
            print("等待 5 秒後重試...")
            time.sleep(5)
            continue

        data = response.json()
        posts = data.get("data", [])
        all_posts.extend(posts)
        page_count += 1

        print(f"\r已取得 {len(all_posts)} 篇貼文 (第 {page_count} 頁)...", end="", flush=True)

        if limit and len(all_posts) >= limit:
            all_posts = all_posts[:limit]
            break

        # 取得下一頁
        paging = data.get("paging", {})
        url = paging.get("next")
        params = {}  # next URL 已包含所有參數

        # 避免請求過快
        time.sleep(0.5)

    print(f"\n共取得 {len(all_posts)} 篇貼文")
    return all_posts


def fetch_post_comments(post_id, access_token, max_comments=50):
    """取得單篇貼文的留言"""
    url = f"{GRAPH_API_BASE}/{post_id}/comments"
    params = {
        "access_token": access_token,
        "fields": "id,message,created_time,from,like_count",
        "limit": 100,
    }

    comments = []
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        comments = data.get("data", [])[:max_comments]
    except requests.exceptions.RequestException:
        pass

    return comments


def fetch_post_reactions(post_id, access_token):
    """取得單篇貼文的反應數"""
    url = f"{GRAPH_API_BASE}/{post_id}"
    params = {
        "access_token": access_token,
        "fields": "reactions.summary(true).limit(0)",
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("reactions", {}).get("summary", {}).get("total_count", 0)
    except requests.exceptions.RequestException:
        return 0


def enrich_posts(posts, access_token, with_comments=False):
    """為每篇貼文加上反應數與留言"""
    total = len(posts)
    for i, post in enumerate(posts):
        print(f"\r正在取得詳細資料: {i + 1}/{total}...", end="", flush=True)

        post["reaction_count"] = fetch_post_reactions(post["id"], access_token)

        if with_comments:
            post["comments"] = fetch_post_comments(post["id"], access_token)

        time.sleep(0.3)

    print()
    return posts


def format_post(post):
    """格式化單篇貼文供顯示"""
    created = post.get("created_time", "")
    if created:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        created = dt.strftime("%Y-%m-%d %H:%M:%S")

    message = post.get("message", "(無文字內容)")
    if len(message) > 200:
        message = message[:200] + "..."

    shares = post.get("shares", {}).get("count", 0)
    reactions = post.get("reaction_count", "N/A")
    url = post.get("permalink_url", "")

    return (
        f"[{created}]\n"
        f"{message}\n"
        f"反應: {reactions} | 分享: {shares}\n"
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
    parser = argparse.ArgumentParser(description="Facebook 粉絲專頁爬蟲 (Graph API)")
    parser.add_argument("page_id", help="粉專 ID 或名稱 (例: NASA)")
    parser.add_argument("--output", "-o", default="output/posts.json", help="輸出檔案路徑")
    parser.add_argument("--limit", "-l", type=int, default=None, help="最多取得幾篇貼文")
    parser.add_argument("--comments", action="store_true", help="同時取得留言")
    parser.add_argument("--no-enrich", action="store_true", help="不取得反應數等額外資料")
    parser.add_argument("--preview", action="store_true", help="在終端機預覽貼文")
    args = parser.parse_args()

    access_token = get_access_token()

    print(f"正在爬取粉專: {args.page_id}")
    print("=" * 60)

    posts = fetch_page_posts(args.page_id, access_token, limit=args.limit)

    if not posts:
        print("未取得任何貼文，請確認粉專 ID 是否正確以及 Access Token 權限")
        sys.exit(1)

    if not args.no_enrich:
        posts = enrich_posts(posts, access_token, with_comments=args.comments)

    if args.preview:
        print("\n" + "=" * 60)
        for post in posts[:10]:
            print(format_post(post))
        if len(posts) > 10:
            print(f"\n... 還有 {len(posts) - 10} 篇貼文（請查看輸出檔案）")

    save_to_json(posts, args.output)

    # 統計資訊
    dates = [p.get("created_time", "") for p in posts if p.get("created_time")]
    if dates:
        oldest = min(dates)[:10]
        newest = max(dates)[:10]
        print(f"\n貼文時間範圍: {oldest} ~ {newest}")
    print(f"總計: {len(posts)} 篇貼文")


if __name__ == "__main__":
    main()
