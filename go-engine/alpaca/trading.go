package alpaca

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// TradingClient calls Alpaca Trading API (positions, orders).
type TradingClient struct {
	baseURL    string
	keyID      string
	secretKey  string
	httpClient *http.Client
}

func NewTradingClient(baseURL, keyID, secretKey string) *TradingClient {
	return &TradingClient{
		baseURL:   baseURL,
		keyID:     keyID,
		secretKey: secretKey,
		httpClient: &http.Client{
			Timeout: 15 * time.Second,
		},
	}
}

func (c *TradingClient) do(method, path string) ([]byte, error) {
	req, err := http.NewRequest(method, c.baseURL+path, nil)
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
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("trading API %s %s: %s (status %d)", method, path, string(body), resp.StatusCode)
	}
	return body, nil
}

// Position is a single position from GET /v2/positions.
type Position struct {
	Symbol         string  `json:"symbol"`
	Qty            string  `json:"qty"`
	Side           string  `json:"side"`
	MarketValue    string  `json:"market_value"`
	CostBasis      string  `json:"cost_basis"`
	UnrealizedPL   string  `json:"unrealized_pl"`
	UnrealizedPLPC string  `json:"unrealized_plpc"`
	CurrentPrice   float64 `json:"current_price"`
}

// GetPositions returns open positions.
func (c *TradingClient) GetPositions() ([]Position, error) {
	body, err := c.do("GET", "/v2/positions")
	if err != nil {
		return nil, err
	}
	var out []Position
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Order is a single order from GET /v2/orders.
type Order struct {
	ID        string  `json:"id"`
	Symbol    string  `json:"symbol"`
	Side      string  `json:"side"`
	Qty       string  `json:"qty"`
	FilledQty string  `json:"filled_qty"`
	Type      string  `json:"type"`
	Status    string  `json:"status"`
	LimitPrice *float64 `json:"limit_price,omitempty"`
	StopPrice  *float64 `json:"stop_price,omitempty"`
	CreatedAt string  `json:"created_at"`
}

// GetOpenOrders returns orders with status=open.
func (c *TradingClient) GetOpenOrders() ([]Order, error) {
	body, err := c.do("GET", "/v2/orders?status=open")
	if err != nil {
		return nil, err
	}
	var out []Order
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	return out, nil
}
