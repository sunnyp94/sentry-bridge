// Package config loads all engine settings from environment variables (.env or shell).
// Required: APCA_API_KEY_ID, APCA_API_SECRET_KEY. Optional: TICKERS, ACTIVE_SYMBOLS_FILE, data URLs, Redis, BRAIN_CMD, STREAM.
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
// Optional: TICKERS (comma-separated fallback), ACTIVE_SYMBOLS_FILE (one symbol per line; used when set and file exists),
//           ALPACA_DATA_BASE_URL, STREAM (true = WebSocket streaming; default true).
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
	// Algo Trader Plus: set ALPACA_DATA_FEED=sip for full SIP (all US exchanges). Default iex for free tier.
	dataFeed := strings.ToLower(os.Getenv("ALPACA_DATA_FEED"))
	if dataFeed != "sip" && dataFeed != "iex" {
		dataFeed = "iex"
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

// loadTickers returns symbols to stream. If ACTIVE_SYMBOLS_FILE is set and the file exists,
// read one symbol per line from it (scanner output). Otherwise use TICKERS (comma-separated).
func loadTickers() []string {
	filePath := os.Getenv("ACTIVE_SYMBOLS_FILE")
	if filePath != "" {
		if !filepath.IsAbs(filePath) {
			if cwd, err := os.Getwd(); err == nil {
				filePath = filepath.Join(cwd, filePath)
			}
		}
		if f, err := os.Open(filePath); err == nil {
			defer f.Close()
			var syms []string
			sc := bufio.NewScanner(f)
			for sc.Scan() {
				t := strings.TrimSpace(sc.Text())
				if t != "" && !strings.HasPrefix(t, "#") {
					syms = append(syms, strings.ToUpper(t))
				}
			}
			if err := sc.Err(); err == nil && len(syms) > 0 {
				return syms
			}
		}
	}
	tickersStr := os.Getenv("TICKERS")
	if tickersStr == "" {
		tickersStr = "CRWD,SNOW,DDOG,NET,MDB,DECK,POOL,SOFI,XPO,HIMS,FIVE,ZS"
	}
	return parseTickers(tickersStr)
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
	APIKeyID             string   // Alpaca API key (data + paper trading)
	APISecretKey         string   // Alpaca secret
	DataBaseURL          string   // e.g. https://data.alpaca.markets
	StreamWSURL          string   // e.g. wss://stream.data.alpaca.markets
	TradingBaseURL       string   // e.g. https://paper-api.alpaca.markets (positions, orders)
	Tickers              []string // Symbols to stream and send to brain
	StreamingMode        bool     // true = WebSocket streaming; false = one-shot REST
	DataFeed             string   // "iex" or "sip" — sip = full US exchanges (Algo Trader Plus)
	RedisURL             string   // Optional Redis for replay/other consumers
	RedisStream          string   // Stream name, default market:updates
	BrainCmd             string   // Command to start Python brain, e.g. python3 python-brain/consumer.py
	PositionsIntervalSec int      // How often to fetch positions/orders (5–300s); default 15 (production-like)
}
