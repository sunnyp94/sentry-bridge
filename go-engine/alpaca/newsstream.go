package alpaca

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/gorilla/websocket"
)

// NewsStream connects to Alpaca's news WebSocket for real-time headlines.
type NewsStream struct {
	baseURL   string
	keyID     string
	secretKey string
	symbols   []string // empty or ["*"] = all news

	OnNews func(article NewsArticle)
}

// NewNewsStream creates a stream for v1beta1/news.
func NewNewsStream(streamBaseURL, keyID, secretKey string, symbols []string) *NewsStream {
	return &NewsStream{
		baseURL:   streamBaseURL,
		keyID:     keyID,
		secretKey: secretKey,
		symbols:   symbols,
	}
}

// Run connects, authenticates, subscribes to news, and processes messages until connection fails.
func (n *NewsStream) Run() error {
	url := n.baseURL + "/v1beta1/news"
	header := http.Header{}
	header.Set("APCA-API-KEY-ID", n.keyID)
	header.Set("APCA-API-SECRET-KEY", n.secretKey)
	conn, resp, err := websocket.DefaultDialer.Dial(url, header)
	if err != nil {
		if resp != nil {
			return fmt.Errorf("dial %s: %w (status %d)", url, err, resp.StatusCode)
		}
		return fmt.Errorf("dial %s: %w", url, err)
	}
	defer conn.Close()

	// Auth by message
	authMsg := map[string]string{
		"action": "auth",
		"key":    n.keyID,
		"secret": n.secretKey,
	}
	if err := conn.WriteJSON(authMsg); err != nil {
		return fmt.Errorf("auth write: %w", err)
	}

	if err := n.readOneControl(conn); err != nil {
		return err
	}

	// Subscribe: specific symbols or ["*"] for all
	subSymbols := n.symbols
	if len(subSymbols) == 0 {
		subSymbols = []string{"*"}
	}
	sub := map[string]interface{}{
		"action": "subscribe",
		"news":   subSymbols,
	}
	if err := conn.WriteJSON(sub); err != nil {
		return fmt.Errorf("subscribe write: %w", err)
	}
	if err := n.readOneControl(conn); err != nil {
		return err
	}

	slog.Info("news stream connected", "url", url)

	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}
		if err := n.handleMessage(data); err != nil {
			slog.Error("news stream handle", "err", err)
		}
	}
}

func (n *NewsStream) readOneControl(conn *websocket.Conn) error {
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
		return fmt.Errorf("alpaca news stream error: code=%.0f msg=%s", code, msg)
	}
	return nil
}

// stream news message type is "n"; fields match NewsArticle where applicable
func (n *NewsStream) handleMessage(data []byte) error {
	var arr []struct {
		T         string   `json:"T"`
		ID        int64    `json:"id"`
		Headline  string   `json:"headline"`
		Author    string   `json:"author"`
		CreatedAt string   `json:"created_at"`
		Summary   string   `json:"summary"`
		URL       string   `json:"url"`
		Symbols   []string `json:"symbols"`
		Source    string   `json:"source"`
	}
	if err := json.Unmarshal(data, &arr); err != nil {
		return err
	}
	for _, m := range arr {
		if m.T != "n" {
			continue
		}
		a := NewsArticle{
			ID:        m.ID,
			Headline:  m.Headline,
			Author:    m.Author,
			CreatedAt: m.CreatedAt,
			Summary:   m.Summary,
			URL:       m.URL,
			Symbols:   m.Symbols,
			Source:    m.Source,
		}
		if n.OnNews != nil {
			n.OnNews(a)
		}
	}
	return nil
}
