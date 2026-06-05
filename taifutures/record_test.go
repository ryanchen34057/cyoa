package main

import "testing"

func TestRecordMetrics(t *testing.T) {
	r := Record{
		Date: "2026-05-02", Open: 18050, High: 18200, Low: 17900,
		Close: 18100, PrevClose: 18000, Volume: 90000,
	}
	cases := []struct {
		name string
		got  float64
		want float64
	}{
		{"振幅點數", r.AmplitudePt(), 300},
		{"振幅%", r.AmplitudePct(), 1.67},
		{"跳空點數", r.GapPt(), 50},
		{"跳空%", r.GapPct(), 0.28},
		{"漲跌點數", r.ChangePt(), 100},
		{"漲跌%", r.ChangePct(), 0.56},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s = %v, want %v", c.name, c.got, c.want)
		}
	}
}

func TestMetricsZeroPrevClose(t *testing.T) {
	r := Record{Open: 100, High: 110, Low: 90, Close: 105}
	if r.AmplitudePct() != 0 || r.GapPct() != 0 || r.ChangePct() != 0 {
		t.Errorf("昨收為 0 時百分比指標應回傳 0，避免除以零")
	}
}
