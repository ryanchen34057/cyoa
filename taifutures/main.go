package main

import (
	"embed"
	"flag"
	"fmt"
	"html/template"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

//go:embed templates/*.html
var tmplFS embed.FS

// taipei 為台北時區(UTC+8)，用固定偏移避免主機缺少 tzdata。
var taipei = time.FixedZone("CST", 8*3600)

type server struct {
	store *Store
	tmpl  *template.Template
}

func main() {
	addr := flag.String("addr", ":8080", "HTTP 服務監聽位址")
	data := flag.String("data", "records.json", "資料儲存檔路徑")
	flag.Parse()

	store, err := NewStore(*data)
	if err != nil {
		log.Fatalf("載入資料失敗: %v", err)
	}

	funcs := template.FuncMap{
		"f2":  func(f float64) string { return strconv.FormatFloat(f, 'f', 2, 64) },
		"sign": func(f float64) string {
			switch {
			case f > 0:
				return "up"
			case f < 0:
				return "down"
			default:
				return ""
			}
		},
	}
	tmpl, err := template.New("").Funcs(funcs).ParseFS(tmplFS, "templates/*.html")
	if err != nil {
		log.Fatalf("解析樣板失敗: %v", err)
	}

	s := &server{store: store, tmpl: tmpl}
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleIndex)
	mux.HandleFunc("/fetch", s.handleFetch)
	mux.HandleFunc("/add", s.handleAdd)
	mux.HandleFunc("/delete", s.handleDelete)
	mux.HandleFunc("/export.csv", s.handleExport)

	log.Printf("台指期日盤紀錄系統啟動於 http://localhost%s (資料檔: %s)", *addr, *data)
	log.Fatal(http.ListenAndServe(*addr, mux))
}

type pageData struct {
	Records []Record
	Today   string
	Msg     string
	Err     string
	Count   int
	AvgAmp  float64 // 平均振幅(%)
	AvgChg  float64 // 平均漲跌幅(%)
}

func (s *server) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	recs := s.store.All()
	data := pageData{
		Records: recs,
		Today:   time.Now().In(taipei).Format("2006-01-02"),
		Msg:     r.URL.Query().Get("msg"),
		Err:     r.URL.Query().Get("err"),
		Count:   len(recs),
	}
	for _, rec := range recs {
		data.AvgAmp += rec.AmplitudePct()
		data.AvgChg += rec.ChangePct()
	}
	if len(recs) > 0 {
		data.AvgAmp = round2(data.AvgAmp / float64(len(recs)))
		data.AvgChg = round2(data.AvgChg / float64(len(recs)))
	}
	if err := s.tmpl.ExecuteTemplate(w, "index.html", data); err != nil {
		log.Printf("render error: %v", err)
	}
}

func (s *server) handleFetch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Redirect(w, r, "/", http.StatusSeeOther)
		return
	}
	now := time.Now().In(taipei)
	start := parseDateOr(r.FormValue("start"), now)
	end := parseDateOr(r.FormValue("end"), now)
	if end.Before(start) {
		start, end = end, start
	}

	recs, err := FetchTX(start, end)
	if err != nil {
		redirectFlash(w, r, "", "抓取失敗: "+err.Error())
		return
	}
	if len(recs) == 0 {
		redirectFlash(w, r, "", "查無日盤資料(可能為假日或尚未收盤)")
		return
	}
	if err := s.store.Upsert(recs...); err != nil {
		redirectFlash(w, r, "", "儲存失敗: "+err.Error())
		return
	}
	redirectFlash(w, r, fmt.Sprintf("已更新 %d 筆紀錄", len(recs)), "")
}

func (s *server) handleAdd(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Redirect(w, r, "/", http.StatusSeeOther)
		return
	}
	date := normalizeDate(strings.ReplaceAll(r.FormValue("date"), "-", "/"))
	if date == "" {
		redirectFlash(w, r, "", "日期格式錯誤")
		return
	}
	open, e1 := strconv.ParseFloat(r.FormValue("open"), 64)
	high, e2 := strconv.ParseFloat(r.FormValue("high"), 64)
	low, e3 := strconv.ParseFloat(r.FormValue("low"), 64)
	clo, e4 := strconv.ParseFloat(r.FormValue("close"), 64)
	prev, e5 := strconv.ParseFloat(r.FormValue("prev_close"), 64)
	if e1 != nil || e2 != nil || e3 != nil || e4 != nil || e5 != nil {
		redirectFlash(w, r, "", "價格欄位需為數字")
		return
	}
	vol, _ := strconv.Atoi(r.FormValue("volume"))
	rec := Record{
		Date: date, Contract: r.FormValue("contract"),
		Open: open, High: high, Low: low, Close: clo, PrevClose: prev, Volume: vol,
	}
	if err := s.store.Upsert(rec); err != nil {
		redirectFlash(w, r, "", "儲存失敗: "+err.Error())
		return
	}
	redirectFlash(w, r, "已手動儲存 "+date, "")
}

func (s *server) handleDelete(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Redirect(w, r, "/", http.StatusSeeOther)
		return
	}
	date := r.FormValue("date")
	if err := s.store.Delete(date); err != nil {
		redirectFlash(w, r, "", "刪除失敗: "+err.Error())
		return
	}
	redirectFlash(w, r, "已刪除 "+date, "")
}

func (s *server) handleExport(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", "attachment; filename=tx_records.csv")
	w.Write([]byte("\xEF\xBB\xBF")) // UTF-8 BOM 讓 Excel 正確顯示中文
	fmt.Fprintln(w, "日期,合約,開盤,最高,最低,收盤,昨收,振幅點數,振幅%,跳空點數,跳空%,漲跌點數,漲跌%,成交量")
	for _, r := range s.store.All() {
		fmt.Fprintf(w, "%s,%s,%g,%g,%g,%g,%g,%g,%g,%g,%g,%g,%g,%d\n",
			r.Date, r.Contract, r.Open, r.High, r.Low, r.Close, r.PrevClose,
			r.AmplitudePt(), r.AmplitudePct(), r.GapPt(), r.GapPct(),
			r.ChangePt(), r.ChangePct(), r.Volume)
	}
}

func parseDateOr(s string, def time.Time) time.Time {
	if t, err := time.ParseInLocation("2006-01-02", strings.TrimSpace(s), taipei); err == nil {
		return t
	}
	return def
}

func redirectFlash(w http.ResponseWriter, r *http.Request, msg, errMsg string) {
	q := url.Values{}
	if msg != "" {
		q.Set("msg", msg)
	}
	if errMsg != "" {
		q.Set("err", errMsg)
	}
	http.Redirect(w, r, "/?"+q.Encode(), http.StatusSeeOther)
}
