package config

import (
	"os"
	"strings"
)

// Load reads configuration from the environment.
// Required: APCA_API_KEY_ID, APCA_API_SECRET_KEY.
// Optional: ALPACA_DATA_BASE_URL (default data.alpaca.markets; paper keys work here),
//           TICKERS (comma-separated, e.g. "AAPL,TSLA,GOOGL").
func Load() (*Config, error) {
	baseURL := os.Getenv("ALPACA_DATA_BASE_URL")
	if baseURL == "" {
		baseURL = "https://data.alpaca.markets"
	}
	tickersStr := os.Getenv("TICKERS")
	if tickersStr == "" {
		tickersStr = "AAPL,MSFT,GOOGL,AMZN,TSLA"
	}
	tickers := parseTickers(tickersStr)
	return &Config{
		APIKeyID:     os.Getenv("APCA_API_KEY_ID"),
		APISecretKey: os.Getenv("APCA_API_SECRET_KEY"),
		DataBaseURL:  baseURL,
		Tickers:      tickers,
	}, nil
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
	APIKeyID     string
	APISecretKey string
	DataBaseURL  string
	Tickers      []string
}
