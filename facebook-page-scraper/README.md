# Facebook 粉絲專頁爬蟲

爬取 Facebook 粉絲專頁的所有貼文，支援兩種方式：

## 方式一：Graph API（推薦）

最穩定可靠的方式，需要 Facebook Developer Access Token。

### 取得 Access Token

1. 前往 [Facebook Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. 建立或選擇一個 Facebook App
3. 勾選 `pages_read_engagement`、`pages_read_user_content` 權限
4. 點擊「Generate Access Token」
5. 複製 `.env.example` 為 `.env`，貼上 token

```bash
cp .env.example .env
# 編輯 .env 填入你的 token
```

### 使用方式

```bash
pip install -r requirements.txt

# 基本用法 - 爬取所有貼文
python scraper_graph_api.py <粉專ID>

# 限制筆數
python scraper_graph_api.py NASA --limit 50

# 含留言 + 預覽
python scraper_graph_api.py NASA --comments --preview

# 指定輸出路徑
python scraper_graph_api.py NASA -o my_data.json
```

## 方式二：免 API 版本

不需要 Access Token，使用 `facebook-scraper` 套件直接爬取。

> ⚠️ Facebook 會封鎖爬蟲 IP，建議搭配 cookies 使用，且不適合大量爬取。

### 使用方式

```bash
pip install -r requirements.txt

# 基本用法
python scraper_no_api.py <粉專名稱>

# 限制頁數（每頁約 8-10 篇）
python scraper_no_api.py NASA --pages 5

# 搭配 cookies（減少被封鎖機率）
python scraper_no_api.py NASA --cookies cookies.txt

# 預覽結果
python scraper_no_api.py NASA --preview
```

### 取得 Cookies

1. 用瀏覽器登入 Facebook
2. 安裝 [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) 擴充功能
3. 在 Facebook 頁面匯出 cookies（Netscape 格式）
4. 儲存為 `cookies.txt`

## 輸出格式

結果儲存為 JSON，預設路徑 `output/posts.json`：

```json
[
  {
    "id": "123456789",
    "message": "貼文內容...",
    "created_time": "2024-01-15T08:30:00+0000",
    "permalink_url": "https://www.facebook.com/...",
    "reaction_count": 150,
    "shares": {"count": 30}
  }
]
```

## 兩種方式比較

| | Graph API | 免 API |
|---|---|---|
| 需要 Token | ✅ 需要 | ❌ 不需要 |
| 穩定性 | ⭐⭐⭐ 高 | ⭐ 低（易被封鎖） |
| 速度 | 快 | 慢 |
| 資料完整度 | 高 | 中 |
| 適合用途 | 大量爬取 | 小量測試 |
