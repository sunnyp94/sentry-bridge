// Package config loads all engine settings from environment variables (.env or shell).
// Required: APCA_API_KEY_ID, APCA_API_SECRET_KEY, TICKERS. Optional: data URLs, Redis, BRAIN_CMD, STREAM.
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
	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = os.Getenv("REDIS_ADDR")
	}
	tradingBaseURL := os.Getenv("APCA_API_BASE_URL")
	if tradingBaseURL == "" {
		tradingBaseURL = "https://paper-api.alpaca.markets"
	}
	// Brain closest to data: Go pipes events to this process via stdin (NDJSON).
	// e.g. "python3 python-brain/consumer.py" when run from project root.
	brainCmd := os.Getenv("BRAIN_CMD")
	return &Config{
		APIKeyID:       os.Getenv("APCA_API_KEY_ID"),
		APISecretKey:   os.Getenv("APCA_API_SECRET_KEY"),
		DataBaseURL:    baseURL,
		StreamWSURL:    streamWSURL,
		TradingBaseURL: tradingBaseURL,
		Tickers:        tickers,
		StreamingMode:  stream,
		RedisURL:       redisURL,
		RedisStream:    envOrDefault("REDIS_STREAM", "market:updates"),
		BrainCmd:       brainCmd,
	}, nil
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
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

// Config holds loaded env: Alpaca keys, data/trading/stream URLs, tickers, Redis, and brain command.
type Config struct {
	APIKeyID       string   // Alpaca API key (data + paper trading)
	APISecretKey   string   // Alpaca secret
	DataBaseURL    string   // e.g. https://data.alpaca.markets
	StreamWSURL    string   // e.g. wss://stream.data.alpaca.markets
	TradingBaseURL string   // e.g. https://paper-api.alpaca.markets (positions, orders)
	Tickers        []string // Symbols to stream and send to brain
	StreamingMode  bool     // true = WebSocket streaming; false = one-shot REST
	RedisURL       string   // Optional Redis for replay/other consumers
	RedisStream    string   // Stream name, default market:updates
	BrainCmd       string   // Command to start Python brain, e.g. python3 python-brain/consumer.py
}
