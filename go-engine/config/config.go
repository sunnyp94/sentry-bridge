// Package config loads all engine settings from environment variables (.env or shell).
// Required: APCA_API_KEY_ID, APCA_API_SECRET_KEY, ACTIVE_SYMBOLS_FILE (scanner runs at startup and 8am ET on market days).
// Optional: data URLs, Redis, BRAIN_CMD, STREAM.
package config

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Load reads configuration from the environment.
// Required: APCA_API_KEY_ID, APCA_API_SECRET_KEY.
// Optional: ALPACA_DATA_BASE_URL, STREAM (true = WebSocket streaming; default true).
func Load() (*Config, error) {
	baseURL := os.Getenv("ALPACA_DATA_BASE_URL")
	if baseURL == "" {
		baseURL = "https://data.alpaca.markets"
	}
	streamWSURL := os.Getenv("ALPACA_STREAM_WS_URL")
	if streamWSURL == "" {
		streamWSURL = dataURLToStreamWS(baseURL)
	}
	tickers := loadTickers()
	stream := strings.ToLower(os.Getenv("STREAM")) != "false" && strings.ToLower(os.Getenv("STREAM")) != "0"
	// Default SIP (full US consolidated). Set ALPACA_DATA_FEED=iex for IEX-only (free tier).
	// Alpaca Pro/Algo Trader Plus: SIP, higher rate limits, no 15-min delay. OFI computed locally from trades/quotes.
	dataFeed := strings.ToLower(strings.TrimSpace(os.Getenv("ALPACA_DATA_FEED")))
	if dataFeed != "iex" && dataFeed != "sip" {
		dataFeed = "sip"
	}
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
	positionsIntervalSec := envIntOrDefault("POSITIONS_INTERVAL_SEC", 15)
	if positionsIntervalSec < 5 {
		positionsIntervalSec = 5
	}
	if positionsIntervalSec > 300 {
		positionsIntervalSec = 300
	}
	return &Config{
		APIKeyID:             os.Getenv("APCA_API_KEY_ID"),
		APISecretKey:         os.Getenv("APCA_API_SECRET_KEY"),
		DataBaseURL:           baseURL,
		StreamWSURL:          streamWSURL,
		TradingBaseURL:        tradingBaseURL,
		Tickers:               tickers,
		StreamingMode:         stream,
		DataFeed:              dataFeed,
		RedisURL:              redisURL,
		RedisStream:           envOrDefault("REDIS_STREAM", "market:updates"),
		BrainCmd:              brainCmd,
		PositionsIntervalSec:  positionsIntervalSec,
	}, nil
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envIntOrDefault(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
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

// loadTickers returns symbols to stream. Only from ACTIVE_SYMBOLS_FILE (scanner output).
// Scanner runs at container start and at 8am ET on full market days.
func loadTickers() []string {
	filePath := os.Getenv("ACTIVE_SYMBOLS_FILE")
	if filePath == "" {
		return nil
	}
	if !filepath.IsAbs(filePath) {
		if cwd, err := os.Getwd(); err == nil {
			filePath = filepath.Join(cwd, filePath)
		}
	}
	f, err := os.Open(filePath)
	if err != nil {
		return nil
	}
	defer f.Close()
	var syms []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		t := strings.TrimSpace(sc.Text())
		if t != "" && !strings.HasPrefix(t, "#") {
			syms = append(syms, strings.ToUpper(t))
		}
	}
	if sc.Err() != nil || len(syms) == 0 {
		return nil
	}
	return syms
}

// Config holds loaded env: Alpaca keys, data/trading/stream URLs, tickers, Redis, and brain command.
type Config struct {
	APIKeyID             string   // Alpaca API key (data + paper trading)
	APISecretKey         string   // Alpaca secret
	DataBaseURL          string   // e.g. https://data.alpaca.markets
	StreamWSURL          string   // e.g. wss://stream.data.alpaca.markets
	TradingBaseURL       string   // e.g. https://paper-api.alpaca.markets (positions, orders)
	Tickers              []string // Symbols to stream and send to brain
	StreamingMode        bool     // true = WebSocket streaming; false = one-shot REST
	DataFeed             string   // "sip" (default) or "iex" — sip = full US consolidated tape
	RedisURL             string   // Optional Redis for replay/other consumers
	RedisStream          string   // Stream name, default market:updates
	BrainCmd             string   // Command to start Python brain, e.g. python3 python-brain/consumer.py
	PositionsIntervalSec int      // How often to fetch positions/orders (5–300s); default 15 (production-like)
}
