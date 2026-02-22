package alpaca

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// PriceStream connects to Alpaca's stock WebSocket (trades + quotes) for real-time price.
type PriceStream struct {
	baseURL   string
	keyID     string
	secretKey string
	feed      string // "iex" or "sip"
	symbols   []string

	// Last price per symbol (mid from quote or last trade)
	mu     sync.RWMutex
	prices map[string]float64

	// Callbacks (optional). Quote includes bid/ask size for order-book context.
	OnTrade func(symbol string, price float64, size int, t time.Time)
	OnQuote func(symbol string, bid, ask float64, bidSize, askSize int, t time.Time)
}

// NewPriceStream creates a stream for v2/iex (or v2/sip). Use feed "iex" for free tier.
func NewPriceStream(streamBaseURL, keyID, secretKey, feed string, symbols []string) *PriceStream {
	if feed == "" {
		feed = "iex"
	}
	return &PriceStream{
		baseURL:   streamBaseURL,
		keyID:     keyID,
		secretKey: secretKey,
		feed:      feed,
		symbols:   symbols,
		prices:    make(map[string]float64),
	}
}

// LastPrice returns the latest price for the symbol (0 if unknown).
func (p *PriceStream) LastPrice(symbol string) float64 {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.prices[symbol]
}

// Run connects, authenticates, subscribes to trades and quotes, and processes messages until ctx is done or connection fails.
func (p *PriceStream) Run() error {
	url := p.baseURL + "/v2/" + p.feed
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("APCA-API-KEY-ID", p.keyID)
	req.Header.Set("APCA-API-SECRET-KEY", p.secretKey)
	conn, resp, err := websocket.DefaultDialer.Dial(url, req.Header)
	if err != nil {
		if resp != nil {
			return fmt.Errorf("dial %s: %w (status %d)", url, err, resp.StatusCode)
		}
		return fmt.Errorf("dial %s: %w", url, err)
	}
	defer conn.Close()

	// Auth by message (required within 10s)
	authMsg := map[string]string{
		"action": "auth",
		"key":    p.keyID,
		"secret": p.secretKey,
	}
	if err := conn.WriteJSON(authMsg); err != nil {
		return fmt.Errorf("auth write: %w", err)
	}

	// Read until we get success or error
	if err := p.readOneControl(conn); err != nil {
		return err
	}

	// Subscribe trades and quotes
	sub := map[string]interface{}{
		"action": "subscribe",
		"trades": p.symbols,
		"quotes": p.symbols,
	}
	if err := conn.WriteJSON(sub); err != nil {
		return fmt.Errorf("subscribe write: %w", err)
	}
	if err := p.readOneControl(conn); err != nil {
		return err
	}

	log.Printf("[stream] connected to %s, subscribed to %v", url, p.symbols)

	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}
		if err := p.handleMessage(data); err != nil {
			log.Printf("[stream] handle message: %v", err)
		}
	}
}

func (p *PriceStream) readOneControl(conn *websocket.Conn) error {
	_, data, err := conn.ReadMessage()
	if err != nil {
		return err
	}
	var arr []map[string]interface{}
	if err := json.Unmarshal(data, &arr); err != nil || len(arr) == 0 {
		return fmt.Errorf("unexpected control: %s", string(data))
	}
	first := arr[0]
	t, _ := first["T"].(string)
	if t == "error" {
		code, _ := first["code"].(float64)
		msg, _ := first["msg"].(string)
		return fmt.Errorf("alpaca stream error: code=%.0f msg=%s", code, msg)
	}
	if t != "success" && t != "subscription" {
		return nil
	}
	return nil
}

func (p *PriceStream) handleMessage(data []byte) error {
	var arr []map[string]interface{}
	if err := json.Unmarshal(data, &arr); err != nil {
		return err
	}
	for _, m := range arr {
		t, _ := m["T"].(string)
		sym, _ := m["S"].(string)
		switch t {
		case "t":
			price, _ := m["p"].(float64)
			size := 0
			if s, ok := m["s"].(float64); ok {
				size = int(s)
			}
			ts := parseTime(m["t"])
			p.setPrice(sym, price)
			if p.OnTrade != nil {
				p.OnTrade(sym, price, size, ts)
			}
		case "q":
			bp, _ := m["bp"].(float64)
			ap, _ := m["ap"].(float64)
			bs, _ := m["bs"].(float64)
			as, _ := m["as"].(float64)
			mid := (bp + ap) / 2
			if mid > 0 {
				p.setPrice(sym, mid)
			}
			ts := parseTime(m["t"])
			if p.OnQuote != nil {
				p.OnQuote(sym, bp, ap, int(bs), int(as), ts)
			}
		}
	}
	return nil
}

func (p *PriceStream) setPrice(symbol string, price float64) {
	if symbol == "" || price <= 0 {
		return
	}
	p.mu.Lock()
	p.prices[symbol] = price
	p.mu.Unlock()
}

func parseTime(v interface{}) time.Time {
	s, _ := v.(string)
	t, _ := time.Parse(time.RFC3339Nano, s)
	return t
}
