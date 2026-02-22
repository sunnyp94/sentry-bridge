package main

import (
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/sunnyp94/sentry-bridge/go-engine/alpaca"
	"github.com/sunnyp94/sentry-bridge/go-engine/config"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}
	if cfg.APIKeyID == "" || cfg.APISecretKey == "" {
		log.Fatal("set APCA_API_KEY_ID and APCA_API_SECRET_KEY (e.g. in .env)")
	}
	if len(cfg.Tickers) == 0 {
		log.Fatal("set TICKERS (comma-separated, e.g. AAPL,TSLA,GOOGL)")
	}

	fmt.Println("Alpaca Market Data")
	fmt.Println("Data URL:", cfg.DataBaseURL)
	fmt.Println("Tickers:", strings.Join(cfg.Tickers, ", "))
	// Confirm credentials are loaded (masked)
	keyPreview := "not set"
	if len(cfg.APIKeyID) >= 8 {
		keyPreview = cfg.APIKeyID[:4] + "..." + cfg.APIKeyID[len(cfg.APIKeyID)-4:]
	}
	fmt.Println("Key ID:", keyPreview)
	fmt.Println()

	client := alpaca.NewClient(cfg.DataBaseURL, cfg.APIKeyID, cfg.APISecretKey)

	// Fetch all data first
	news, errNews := client.GetNews(cfg.Tickers, 50)
	snapshots, errSnap := client.GetSnapshots(cfg.Tickers)
	barsResp, errBars := client.GetBars(cfg.Tickers, "1Day", 30)

	if errNews != nil {
		log.Printf("news error: %v", errNews)
	}
	if errSnap != nil {
		log.Printf("snapshots error: %v", errSnap)
	}
	if errBars != nil {
		log.Printf("bars error: %v", errBars)
		os.Exit(1)
	}

	// Build symbol -> news index
	newsBySymbol := make(map[string][]alpaca.NewsArticle)
	if errNews == nil && news != nil {
		for i := range news.News {
			a := &news.News[i]
			for _, sym := range a.Symbols {
				newsBySymbol[sym] = append(newsBySymbol[sym], *a)
			}
		}
	}

	// Print per stock: news, price, volatility
	for _, sym := range cfg.Tickers {
		fmt.Println("═══════════════════════════════════════════════════════════")
		fmt.Printf("  %s\n", sym)
		fmt.Println("═══════════════════════════════════════════════════════════")

		// News for this stock
		articles := newsBySymbol[sym]
		if len(articles) == 0 {
			fmt.Println("  News: (none for this symbol in this batch)")
		} else {
			fmt.Printf("  News: %d article(s)\n", len(articles))
			for _, a := range articles {
				fmt.Printf("    • %s\n", a.Headline)
				fmt.Printf("      %s | %s\n", a.CreatedAt, a.Source)
			}
		}
		fmt.Println()

		// Price
		s, ok := snapshots[sym]
		if !ok {
			fmt.Println("  Price: (no snapshot)")
		} else {
			price := 0.0
			if s.LatestTrade != nil {
				price = s.LatestTrade.Price
			} else if s.LatestQuote != nil {
				price = (s.LatestQuote.BidPrice + s.LatestQuote.AskPrice) / 2
			} else if s.DailyBar != nil {
				price = s.DailyBar.Close
			}
			fmt.Printf("  Price: $%.2f\n", price)
		}
		fmt.Println()

		// Volatility
		bars, ok := barsResp.Bars[sym]
		if !ok || len(bars) == 0 {
			fmt.Println("  Volatility (30d annualized): (no bar data)")
		} else {
			vol := alpaca.AnnualizedVolatility(bars)
			fmt.Printf("  Volatility (30d annualized): %.2f%%\n", vol*100)
		}

		fmt.Println()
	}

	fmt.Println("═══════════════════════════════════════════════════════════")
	fmt.Println("Done.")
}
