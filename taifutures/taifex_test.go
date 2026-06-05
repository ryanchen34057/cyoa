package main

import (
	"strings"
	"testing"
)

// 模擬期交所(已轉 UTF-8)的下載 CSV：含日盤/盤後、多合約、千分位逗號等情境。
const sampleCSV = `交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,交易時段
2026/05/02,TX,202605,"18,050","18,200","17,900","18,100",100,0.56,"90,000","18,100","95,000",一般
2026/05/02,TX,202606,17950,18150,17850,18050,90,0.50,"12,000",18050,40000,一般
2026/05/02,TX,202605,18100,18300,18000,18250,150,0.82,"30,000",18250,95000,盤後
2026/05/05,TX,202605,18120,18400,18050,18380,280,1.55,"85,000",18380,93000,一般
2026/05/05,TX,202605,-,-,-,-,-,-,-,-,-,一般`

func TestParseFutCSV(t *testing.T) {
	recs, err := parseFutCSV(strings.NewReader(sampleCSV))
	if err != nil {
		t.Fatalf("parseFutCSV error: %v", err)
	}
	if len(recs) != 2 {
		t.Fatalf("應有 2 個交易日，得到 %d", len(recs))
	}

	// 第一筆(由舊到新)：2026-05-02，應選成交量最大的近月(90,000)而非次月或盤後。
	r0 := recs[0]
	if r0.Date != "2026-05-02" {
		t.Errorf("date = %s, want 2026-05-02", r0.Date)
	}
	if r0.Contract != "202605" {
		t.Errorf("contract = %s, want 202605", r0.Contract)
	}
	if r0.Volume != 90000 {
		t.Errorf("應挑選成交量最大者，volume = %d, want 90000", r0.Volume)
	}
	if r0.Open != 18050 || r0.Close != 18100 {
		t.Errorf("OHLC 解析錯誤: %+v", r0)
	}
	// 昨收 = 收盤 - 漲跌價 = 18100 - 100 = 18000
	if r0.PrevClose != 18000 {
		t.Errorf("prevClose = %v, want 18000", r0.PrevClose)
	}
	if r0.AmplitudePt() != 300 || r0.GapPt() != 50 || r0.ChangePt() != 100 {
		t.Errorf("指標計算錯誤: 振幅=%v 跳空=%v 漲跌=%v",
			r0.AmplitudePt(), r0.GapPt(), r0.ChangePt())
	}

	// 第二筆：2026-05-05，含一列無效(-)資料應被略過，保留有效列。
	r1 := recs[1]
	if r1.Date != "2026-05-05" || r1.Volume != 85000 {
		t.Errorf("second record wrong: %+v", r1)
	}
}

func TestCleanNum(t *testing.T) {
	cases := map[string]float64{
		`"18,200"`: 18200,
		"100":      100,
		"+50":      50,
		"1.55%":    1.55,
		"▲100":     100,
	}
	for in, want := range cases {
		got, err := cleanNum(in)
		if err != nil || got != want {
			t.Errorf("cleanNum(%q) = %v, %v; want %v", in, got, err, want)
		}
	}
	if _, err := cleanNum("-"); err == nil {
		t.Errorf(`cleanNum("-") 應回傳錯誤`)
	}
}

func TestNormalizeDate(t *testing.T) {
	if got := normalizeDate("2026/05/02"); got != "2026-05-02" {
		t.Errorf("normalizeDate = %q", got)
	}
	if got := normalizeDate("not a date"); got != "" {
		t.Errorf("無效日期應回傳空字串，得到 %q", got)
	}
}
