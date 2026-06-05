package main

import "math"

// Record 代表台指期(TX)某一交易日「日盤(一般)」近月主力合約的紀錄。
// 其餘的振幅 / 跳空 / 漲跌幅皆由欄位即時計算，不另外儲存，避免資料不一致。
type Record struct {
	Date      string  `json:"date"`       // 交易日期 YYYY-MM-DD
	Contract  string  `json:"contract"`   // 到期月份(週別)，例如 202606
	Open      float64 `json:"open"`       // 開盤價
	High      float64 `json:"high"`       // 最高價
	Low       float64 `json:"low"`        // 最低價
	Close     float64 `json:"close"`      // 收盤價
	PrevClose float64 `json:"prev_close"` // 前一交易日收盤價(同合約)
	Volume    int     `json:"volume"`     // 成交量
}

// AmplitudePt 振幅(點數) = 最高 - 最低
func (r Record) AmplitudePt() float64 { return round2(r.High - r.Low) }

// AmplitudePct 振幅(%) = (最高 - 最低) / 昨收 * 100
func (r Record) AmplitudePct() float64 {
	if r.PrevClose == 0 {
		return 0
	}
	return round2((r.High - r.Low) / r.PrevClose * 100)
}

// GapPt 跳空(點數) = 開盤 - 昨收。正值為跳空開高，負值為跳空開低。
func (r Record) GapPt() float64 { return round2(r.Open - r.PrevClose) }

// GapPct 跳空(%) = (開盤 - 昨收) / 昨收 * 100
func (r Record) GapPct() float64 {
	if r.PrevClose == 0 {
		return 0
	}
	return round2((r.Open - r.PrevClose) / r.PrevClose * 100)
}

// ChangePt 漲跌(點數) = 收盤 - 昨收
func (r Record) ChangePt() float64 { return round2(r.Close - r.PrevClose) }

// ChangePct 漲跌幅(%) = (收盤 - 昨收) / 昨收 * 100
func (r Record) ChangePct() float64 {
	if r.PrevClose == 0 {
		return 0
	}
	return round2((r.Close - r.PrevClose) / r.PrevClose * 100)
}

func round2(f float64) float64 { return math.Round(f*100) / 100 }
