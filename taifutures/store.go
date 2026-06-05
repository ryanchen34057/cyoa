package main

import (
	"encoding/json"
	"os"
	"sort"
	"sync"
)

// Store 以單一 JSON 檔保存所有紀錄，並以交易日期(date)為唯一鍵做去重 / 更新。
type Store struct {
	mu   sync.Mutex
	path string
	recs map[string]Record
}

// NewStore 載入既有資料檔；檔案不存在則視為空集合。
func NewStore(path string) (*Store, error) {
	s := &Store{path: path, recs: map[string]Record{}}
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return s, nil
		}
		return nil, err
	}
	if len(b) == 0 {
		return s, nil
	}
	if err := json.Unmarshal(b, &s.recs); err != nil {
		return nil, err
	}
	return s, nil
}

// Upsert 新增或覆寫某日紀錄，並立即寫回磁碟。
func (s *Store) Upsert(recs ...Record) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, r := range recs {
		s.recs[r.Date] = r
	}
	return s.save()
}

// Delete 刪除某日紀錄。
func (s *Store) Delete(date string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.recs, date)
	return s.save()
}

// Get 取得某日紀錄。
func (s *Store) Get(date string) (Record, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.recs[date]
	return r, ok
}

// All 回傳所有紀錄，依日期由新到舊排序。
func (s *Store) All() []Record {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Record, 0, len(s.recs))
	for _, r := range s.recs {
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Date > out[j].Date })
	return out
}

func (s *Store) save() error {
	b, err := json.MarshalIndent(s.recs, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, s.path)
}
