package brain

import (
	"sync"
	"time"
)

const (
	lookback = 6 * time.Minute
)

type pricePoint struct {
	t time.Time
	p float64
}

type volumePoint struct {
	t time.Time
	v int
}

// State holds per-symbol price/volume history for returns and volume metrics (1m, 5m).
// Session is computed from current time (ET). Volatility is set externally.
type State struct {
	mu sync.RWMutex

	priceHistory  map[string][]pricePoint
	volumeHistory map[string][]volumePoint
	volatility    map[string]float64
}

func NewState() *State {
	return &State{
		priceHistory:  make(map[string][]pricePoint),
		volumeHistory: make(map[string][]volumePoint),
		volatility:    make(map[string]float64),
	}
}

func (s *State) RecordTrade(symbol string, price float64, size int, t time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := t
	if now.IsZero() {
		now = time.Now()
	}
	cut := now.Add(-lookback)

	// Price history
	s.priceHistory[symbol] = append(s.priceHistory[symbol], pricePoint{t: now, p: price})
	ph := s.priceHistory[symbol]
	for len(ph) > 0 && ph[0].t.Before(cut) {
		ph = ph[1:]
	}
	s.priceHistory[symbol] = ph

	// Volume history
	if size > 0 {
		s.volumeHistory[symbol] = append(s.volumeHistory[symbol], volumePoint{t: now, v: size})
		vh := s.volumeHistory[symbol]
		for len(vh) > 0 && vh[0].t.Before(cut) {
			vh = vh[1:]
		}
		s.volumeHistory[symbol] = vh
	}
}

func (s *State) SetVolatility(symbol string, vol float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.volatility[symbol] = vol
}

func (s *State) SetVolatilityMap(vol map[string]float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for k, v := range vol {
		s.volatility[k] = v
	}
}

func (s *State) GetVolatility(symbol string) float64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.volatility[symbol]
}

// Volume1m returns total trade volume in the last 1 minute for symbol.
func (s *State) Volume1m(symbol string) int64 {
	return s.volumeSince(symbol, time.Minute)
}

// Volume5m returns total trade volume in the last 5 minutes for symbol.
func (s *State) Volume5m(symbol string) int64 {
	return s.volumeSince(symbol, 5*time.Minute)
}

func (s *State) volumeSince(symbol string, d time.Duration) int64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	cut := time.Now().Add(-d)
	var sum int64
	for _, p := range s.volumeHistory[symbol] {
		if p.t.After(cut) {
			sum += int64(p.v)
		}
	}
	return sum
}

// Return1m returns (current - price_1m_ago) / price_1m_ago. Returns 0 if insufficient data.
func (s *State) Return1m(symbol string, currentPrice float64) float64 {
	return s.returnSince(symbol, currentPrice, time.Minute)
}

// Return5m returns (current - price_5m_ago) / price_5m_ago.
func (s *State) Return5m(symbol string, currentPrice float64) float64 {
	return s.returnSince(symbol, currentPrice, 5*time.Minute)
}

func (s *State) returnSince(symbol string, current float64, d time.Duration) float64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	cut := time.Now().Add(-d)
	ph := s.priceHistory[symbol]
	if len(ph) == 0 || current <= 0 {
		return 0
	}
	var past float64
	for i := len(ph) - 1; i >= 0; i-- {
		if ph[i].t.Before(cut) || ph[i].t.Equal(cut) {
			past = ph[i].p
			break
		}
	}
	if past <= 0 {
		return 0
	}
	return (current - past) / past
}

// Session returns "pre_open", "regular", or "post_close" based on Eastern Time.
func Session(now time.Time) string {
	et := now.In(eastern)
	h := et.Hour()
	m := et.Minute()
	minutes := h*60 + m
	// 9:30 = 570, 16:00 = 960
	if minutes < 570 {
		return "pre_open"
	}
	if minutes >= 960 {
		return "post_close"
	}
	return "regular"
}

var eastern *time.Location

func init() {
	var err error
	eastern, err = time.LoadLocation("America/New_York")
	if err != nil {
		eastern = time.FixedZone("ET", -5*3600)
	}
}
