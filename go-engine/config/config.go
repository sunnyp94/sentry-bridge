package config

import (
	"os"
	"strings"
)

// Load reads configuration from the environment.
// Required: APCA_API_KEY_ID, APCA_API_SECRET_KEY.
// Optional: ALPACA_DATA_BASE_URL (default data.alpaca.markets; paper keys work here),
//           TICKERS (comma-separated, e.g. "AAPL,TSLA,GOOGL"),
//           STREAM (true = run WebSocket streaming mode; default true for high-frequency).
func Load() (*Config, error) {
	baseURL := os.Getenv("ALPACA_DATA_BASE_URL")
	if baseURL == "" {
		baseURL = "https://data.alpaca.markets"
	}
	streamWSURL := os.Getenv("ALPACA_STREAM_WS_URL")
	if streamWSURL == "" {
		streamWSURL = dataURLToStreamWS(baseURL)
	}
	tickersStr := os.Getenv("TICKERS")
	if tickersStr == "" {
		tickersStr = "AAPL,MSFT,GOOGL,AMZN,TSLA"
	}
	tickers := parseTickers(tickersStr)
	stream := strings.ToLower(os.Getenv("STREAM")) != "false" && strings.ToLower(os.Getenv("STREAM")) != "0"
	return &Config{
		APIKeyID:      os.Getenv("APCA_API_KEY_ID"),
		APISecretKey:  os.Getenv("APCA_API_SECRET_KEY"),
		DataBaseURL:   baseURL,
		StreamWSURL:   streamWSURL,
		Tickers:       tickers,
		StreamingMode: stream,
	}, nil
}

// dataURLToStreamWS converts https://data.alpaca.markets -> wss://stream.data.alpaca.markets
func dataURLToStreamWS(dataURL string) string {
	if strings.HasPrefix(dataURL, "https://data.sandbox.alpaca.markets") {
		return "wss://stream.data.sandbox.alpaca.markets"
	}
	return "wss://stream.data.alpaca.markets"
}

func parseTickers(s string) []string {
	var out []string
	for _, t := range strings.Split(s, ",") {
		t = strings.TrimSpace(t)
		if t != "" {
			out = append(out, strings.ToUpper(t))
		}
	}
	return out
}

type Config struct {
	APIKeyID      string
	APISecretKey  string
	DataBaseURL   string
	StreamWSURL   string
	Tickers       []string
	StreamingMode bool
}
