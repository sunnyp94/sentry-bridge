package alpaca

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Client calls Alpaca Market Data API (news, snapshots, bars).
type Client struct {
	baseURL    string
	keyID      string
	secretKey  string
	httpClient *http.Client
}

// NewClient builds an Alpaca data API client.
func NewClient(baseURL, keyID, secretKey string) *Client {
	return &Client{
		baseURL:   baseURL,
		keyID:     keyID,
		secretKey: secretKey,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *Client) do(method, path string, params url.Values) ([]byte, error) {
	u := c.baseURL + path
	if len(params) > 0 {
		u += "?" + params.Encode()
	}
	req, err := http.NewRequest(method, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("APCA-API-KEY-ID", c.keyID)
	req.Header.Set("APCA-API-SECRET-KEY", c.secretKey)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("alpaca API %s %s: %s (status %d)", method, path, string(body), resp.StatusCode)
	}
	return body, nil
}

// NewsArticle is a single news item from Alpaca.
type NewsArticle struct {
	ID        int64    `json:"id"`
	Headline  string   `json:"headline"`
	Author    string   `json:"author"`
	CreatedAt string   `json:"created_at"`
	UpdatedAt string   `json:"updated_at"`
	Summary   string   `json:"summary"`
	URL       string   `json:"url"`
	Symbols   []string `json:"symbols"`
	Source    string   `json:"source"`
}

// NewsResponse is the response from GET /v1beta1/news.
type NewsResponse struct {
	News          []NewsArticle `json:"news"`
	NextPageToken string        `json:"next_page_token"`
}

// GetNews fetches latest news for the given symbols (comma-separated).
func (c *Client) GetNews(symbols []string, limit int) (*NewsResponse, error) {
	if limit <= 0 || limit > 50 {
		limit = 10
	}
	params := url.Values{}
	if len(symbols) > 0 {
		params.Set("symbols", strings.Join(symbols, ","))
	}
	params.Set("limit", fmt.Sprintf("%d", limit))
	body, err := c.do("GET", "/v1beta1/news", params)
	if err != nil {
		return nil, err
	}
	var out NewsResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Snapshot is the latest trade, quote, and daily bar for a symbol.
type Snapshot struct {
	Symbol struct {
		LatestTrade   *Trade `json:"latestTrade"`
		LatestQuote    *Quote `json:"latestQuote"`
		MinuteBar     *Bar   `json:"minuteBar"`
		DailyBar      *Bar   `json:"dailyBar"`
		PrevDailyBar  *Bar   `json:"prevDailyBar"`
	} `json:"-"`
	// Raw map keyed by symbol; each value has latestTrade, latestQuote, dailyBar, etc.
}

// Trade is a single trade.
type Trade struct {
	Price  float64 `json:"p"`
	Size   uint64  `json:"s"`
	Time   string  `json:"t"`
	Cond   []int   `json:"c"`
	Exchange string `json:"x"`
}

// Quote is bid/ask.
type Quote struct {
	BidPrice  float64 `json:"bp"`
	AskPrice  float64 `json:"ap"`
	BidSize   uint64  `json:"bs"`
	AskSize   uint64  `json:"as"`
	Timestamp string  `json:"t"`
}

// Bar is OHLCV bar.
type Bar struct {
	Open   float64 `json:"o"`
	High   float64 `json:"h"`
	Low    float64 `json:"l"`
	Close  float64 `json:"c"`
	Volume uint64  `json:"v"`
	Time   string  `json:"t"`
}

// GetSnapshots returns latest price (and daily bar) per symbol.
// Response is map[symbol] -> snapshot object (latestTrade, latestQuote, dailyBar).
func (c *Client) GetSnapshots(symbols []string) (map[string]SnapshotData, error) {
	if len(symbols) == 0 {
		return nil, nil
	}
	params := url.Values{}
	params.Set("symbols", strings.Join(symbols, ","))
	body, err := c.do("GET", "/v2/stocks/snapshots", params)
	if err != nil {
		return nil, err
	}
	var raw map[string]SnapshotData
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, err
	}
	return raw, nil
}

// SnapshotData holds latest trade, quote, and daily bar for one symbol.
type SnapshotData struct {
	LatestTrade  *Trade `json:"latestTrade"`
	LatestQuote  *Quote `json:"latestQuote"`
	DailyBar     *Bar   `json:"dailyBar"`
	PrevDailyBar *Bar   `json:"prevDailyBar"`
}

// BarsResponse is the response from GET /v2/stocks/bars.
type BarsResponse struct {
	Bars       map[string][]Bar `json:"bars"`
	NextPageToken string        `json:"next_page_token"`
}

// GetBars fetches historical bars (e.g. daily) for the given symbols.
func (c *Client) GetBars(symbols []string, timeframe string, limit int) (*BarsResponse, error) {
	if len(symbols) == 0 {
		return nil, nil
	}
	if timeframe == "" {
		timeframe = "1Day"
	}
	if limit <= 0 || limit > 10000 {
		limit = 30
	}
	params := url.Values{}
	params.Set("symbols", strings.Join(symbols, ","))
	params.Set("timeframe", timeframe)
	params.Set("limit", fmt.Sprintf("%d", limit))
	body, err := c.do("GET", "/v2/stocks/bars", params)
	if err != nil {
		return nil, err
	}
	var out BarsResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

