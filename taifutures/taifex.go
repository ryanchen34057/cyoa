package main

import (
	"encoding/csv"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"golang.org/x/text/encoding/traditionalchinese"
	"golang.org/x/text/transform"
)

// taifexURL 是台灣期交所「期貨每日交易行情下載」端點，回傳 Big5 編碼的 CSV。
const taifexURL = "https://www.taifex.com.tw/cht/3/futDataDown"

// FetchTX 向期交所抓取 [start, end] 期間台指期(TX)的每日行情，
// 並回傳每個交易日「日盤(一般)」中成交量最大(主力近月)的合約紀錄。
func FetchTX(start, end time.Time) ([]Record, error) {
	form := url.Values{
		"down_type":      {"1"},
		"commodity_id":   {"TX"},
		"queryStartDate": {start.Format("2006/01/02")},
		"queryEndDate":   {end.Format("2006/01/02")},
	}
	req, err := http.NewRequest(http.MethodPost, taifexURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", "Mozilla/5.0 (taifutures)")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("連線期交所失敗: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("期交所回傳狀態碼 %d", resp.StatusCode)
	}

	// 期交所 CSV 為 Big5 編碼，需轉成 UTF-8 才能解析。
	utf8 := transform.NewReader(resp.Body, traditionalchinese.Big5.NewDecoder())
	return parseFutCSV(utf8)
}

// parseFutCSV 解析「已轉為 UTF-8」的期交所行情 CSV，
// 依交易日期分組後挑選日盤成交量最大的合約。輸出依日期由舊到新排序。
func parseFutCSV(r io.Reader) ([]Record, error) {
	cr := csv.NewReader(r)
	cr.FieldsPerRecord = -1 // 期交所部分列尾欄位數不一，放寬檢查
	cr.LazyQuotes = true

	header, err := cr.Read()
	if err != nil {
		return nil, fmt.Errorf("讀取 CSV 表頭失敗: %w", err)
	}
	col := indexColumns(header)
	need := []string{"date", "open", "high", "low", "close", "change", "volume", "session"}
	for _, k := range need {
		if _, ok := col[k]; !ok {
			return nil, fmt.Errorf("CSV 缺少必要欄位: %s", k)
		}
	}

	// 同一交易日可能有多個合約(近月、次月、週選等)，保留成交量最大者即主力近月。
	best := map[string]Record{}
	for {
		row, err := cr.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		get := func(k string) string {
			i := col[k]
			if i < 0 || i >= len(row) {
				return ""
			}
			return strings.TrimSpace(row[i])
		}

		// 只取日盤(一般)。盤後(夜盤)略過。
		if !strings.Contains(get("session"), "一般") {
			continue
		}
		date := normalizeDate(get("date"))
		if date == "" {
			continue
		}
		open, e1 := cleanNum(get("open"))
		high, e2 := cleanNum(get("high"))
		low, e3 := cleanNum(get("low"))
		clo, e4 := cleanNum(get("close"))
		vol, e5 := cleanInt(get("volume"))
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil || e5 != nil {
			continue // 當日該合約無有效成交(如以「-」表示)
		}
		change, _ := cleanNum(get("change")) // 漲跌價；缺值時視為 0
		rec := Record{
			Date:      date,
			Contract:  get("expiry"),
			Open:      open,
			High:      high,
			Low:       low,
			Close:     clo,
			PrevClose: round2(clo - change), // 昨收 = 收盤 - 漲跌價(同合約基準)
			Volume:    vol,
		}
		if cur, ok := best[date]; !ok || rec.Volume > cur.Volume {
			best[date] = rec
		}
	}

	out := make([]Record, 0, len(best))
	for _, r := range best {
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Date < out[j].Date })
	return out, nil
}

// indexColumns 將期交所表頭對應到內部欄位鍵，採關鍵字比對以容忍欄位順序/標題微調。
func indexColumns(header []string) map[string]int {
	col := map[string]int{}
	for i, h := range header {
		h = strings.TrimSpace(h)
		switch {
		case h == "交易日期":
			col["date"] = i
		case strings.HasPrefix(h, "到期月份"):
			col["expiry"] = i
		case h == "開盤價":
			col["open"] = i
		case h == "最高價":
			col["high"] = i
		case h == "最低價":
			col["low"] = i
		case h == "收盤價":
			col["close"] = i
		case h == "漲跌價":
			col["change"] = i
		case h == "成交量":
			col["volume"] = i
		case h == "交易時段":
			col["session"] = i
		}
	}
	return col
}

// normalizeDate 將期交所的 2006/01/02 轉為 2006-01-02。
func normalizeDate(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	t, err := time.Parse("2006/01/02", s)
	if err != nil {
		return ""
	}
	return t.Format("2006-01-02")
}

// cleanNum 清掉千分位逗號、引號、百分比與漲跌方向符號後轉成 float。
func cleanNum(s string) (float64, error) {
	s = strings.NewReplacer(",", "", "\"", "", "%", "", "+", "", " ", "",
		"▲", "", "▼", "", "△", "", "▽", "").Replace(strings.TrimSpace(s))
	if s == "" || s == "-" {
		return 0, fmt.Errorf("empty")
	}
	return strconv.ParseFloat(s, 64)
}

func cleanInt(s string) (int, error) {
	f, err := cleanNum(s)
	if err != nil {
		return 0, err
	}
	return int(f), nil
}
