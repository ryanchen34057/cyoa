"""
Facebook 粉絲專頁爬蟲 - 免 API 版本（使用 facebook-scraper 套件）

使用方式:
    python scraper_no_api.py <粉專名稱> [--output output.json] [--pages 10]

注意:
    - 此方法不需要 Access Token
    - 但 Facebook 會頻繁封鎖爬蟲，可能需要搭配 cookies 使用
    - 適合小規模爬取，大量爬取建議使用 Graph API 版本
"""

import argparse
import json
import os
import sys
from datetime import datetime

from facebook_scraper import get_posts, set_cookies


def scrape_page(page_name, pages=None, cookies_path=None):
    """爬取粉專貼文"""
    options = {
        "comments": False,
        "reactors": False,
        "allow_extra_requests": False,
    }

    if cookies_path:
        if not os.path.exists(cookies_path):
            print(f"錯誤: 找不到 cookies 檔案: {cookies_path}")
            sys.exit(1)
        set_cookies(cookies_path)
        print(f"已載入 cookies: {cookies_path}")

    all_posts = []
    try:
        for i, post in enumerate(get_posts(page_name, pages=pages, options=options)):
            processed = {
                "id": post.get("post_id"),
                "text": post.get("text") or post.get("post_text", ""),
                "created_time": post.get("time", "").isoformat() if post.get("time") else None,
                "url": post.get("post_url", ""),
                "image": post.get("image", ""),
                "video": post.get("video", ""),
                "likes": post.get("likes", 0),
                "comments_count": post.get("comments", 0),
                "shares": post.get("shares", 0),
                "reactions": post.get("reactions", {}),
                "type": post.get("post_type", ""),
            }
            all_posts.append(processed)
            print(f"\r已取得 {len(all_posts)} 篇貼文...", end="", flush=True)

    except Exception as e:
        error_msg = str(e)
        if "temporarily blocked" in error_msg.lower() or "login" in error_msg.lower():
            print(f"\n被 Facebook 封鎖了。建議:")
            print("  1. 等待一段時間後重試")
            print("  2. 使用 --cookies 參數提供登入 cookies")
            print("  3. 改用 Graph API 版本 (scraper_graph_api.py)")
        else:
            print(f"\n爬取錯誤: {e}")

        if all_posts:
            print(f"已取得 {len(all_posts)} 篇貼文（部分結果）")

    print()
    return all_posts


def format_post(post):
    """格式化單篇貼文供顯示"""
    created = post.get("created_time", "")
    if created:
        try:
            dt = datetime.fromisoformat(created)
            created = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass

    text = post.get("text", "(無文字內容)")
    if len(text) > 200:
        text = text[:200] + "..."

    likes = post.get("likes", 0)
    comments = post.get("comments_count", 0)
    shares = post.get("shares", 0)
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

    # datetime 物件轉字串
    def default_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2, default=default_serializer)
    print(f"已儲存至 {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Facebook 粉絲專頁爬蟲 (免 API)")
    parser.add_argument("page_name", help="粉專名稱 (網址中的名稱，例: NASA)")
    parser.add_argument("--output", "-o", default="output/posts.json", help="輸出檔案路徑")
    parser.add_argument("--pages", "-p", type=int, default=None,
                        help="要爬幾頁 (每頁約 8-10 篇，不指定則爬到底)")
    parser.add_argument("--cookies", "-c", default=None,
                        help="Facebook cookies 檔案路徑 (Netscape 格式)")
    parser.add_argument("--preview", action="store_true", help="在終端機預覽貼文")
    args = parser.parse_args()

    print(f"正在爬取粉專: {args.page_name}")
    print("=" * 60)

    posts = scrape_page(args.page_name, pages=args.pages, cookies_path=args.cookies)

    if not posts:
        print("未取得任何貼文")
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
        print(f"\n貼文時間範圍: {oldest} ~ {newest}")
    print(f"總計: {len(posts)} 篇貼文")


if __name__ == "__main__":
    main()
