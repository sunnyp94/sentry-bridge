package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"sync"
	"time"

	"github.com/sunnyp94/sentry-bridge/go-engine/alpaca"
	"github.com/sunnyp94/sentry-bridge/go-engine/brain"
	"github.com/sunnyp94/sentry-bridge/go-engine/config"
	"github.com/sunnyp94/sentry-bridge/go-engine/redis"
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

	if cfg.StreamingMode {
		runStreaming(cfg)
		return
	}
	runOneShot(cfg)
}

// runStreaming: WebSocket price + news, volatility refresh every 5 min; push all to Redis for Python brain.
func runStreaming(cfg *config.Config) {
	fmt.Println("Alpaca Market Data — streaming mode (high-frequency)")
	fmt.Println("Data URL:", cfg.DataBaseURL)
	fmt.Println("Stream URL:", cfg.StreamWSURL)
	fmt.Println("Tickers:", strings.Join(cfg.Tickers, ", "))
	fmt.Println("Price + News: real-time WebSocket | Volatility: refreshed every 5 min")
	fmt.Println()

	client := alpaca.NewClient(cfg.DataBaseURL, cfg.APIKeyID, cfg.APISecretKey)
	tradingClient := alpaca.NewTradingClient(cfg.TradingBaseURL, cfg.APIKeyID, cfg.APISecretKey)

	// Brain closest to data: pipe events to Python subprocess via stdin (no Redis in hot path)
	var brainPipe *brain.Pipe
	if cfg.BrainCmd != "" {
		if p, err := brain.StartPipe(cfg.BrainCmd); err != nil {
			log.Printf("[brain] could not start %q: %v", cfg.BrainCmd, err)
		} else if p != nil {
			brainPipe = p
			defer brainPipe.Close()
			fmt.Println("Brain: piping to", cfg.BrainCmd)
		}
	}

	// Redis (optional; for replay or other consumers)
	var pub redis.PublisherInterface = redis.NoopPublisher{}
	if cfg.RedisURL != "" {
		if p, err := redis.NewPublisher(cfg.RedisURL, cfg.RedisStream); err != nil {
			log.Printf("[redis] not connected (%v)", err)
		} else {
			pub = p
			defer p.Close()
			fmt.Println("Redis stream:", cfg.RedisStream)
		}
	}
	fmt.Println()

	// Brain state: price/volume history for returns and volume_1m/5m
	state := brain.NewState()

	// Shared volatility (updated every 5 min)
	var volMu sync.RWMutex
	volatility := make(map[string]float64)

	// Initial volatility and push to Redis
	updateVolatility := func() {
		barsResp, err := client.GetBars(cfg.Tickers, "1Day", 30)
		if err != nil {
			log.Printf("[vol] bars error: %v", err)
			return
		}
		volMu.Lock()
		for _, sym := range cfg.Tickers {
			bars, ok := barsResp.Bars[sym]
			if !ok || len(bars) < 2 {
				continue
			}
			volatility[sym] = alpaca.AnnualizedVolatility(bars)
		}
		volMu.Unlock()
		state.SetVolatilityMap(volatility)
		// Push volatility snapshot to Redis (one event per symbol)
		for _, sym := range cfg.Tickers {
			volMu.RLock()
			v := volatility[sym]
			volMu.RUnlock()
			if v > 0 {
				payload := map[string]interface{}{"symbol": sym, "annualized_vol_30d": v}
				if brainPipe != nil {
					_ = brainPipe.Send("volatility", payload)
				}
				redis.LogErr(pub.PublishJSON(context.Background(), "volatility", payload), "volatility")
			}
		}
		// Print snapshot
		volMu.RLock()
		fmt.Println("--- Volatility (30d annualized) ---")
		for _, sym := range cfg.Tickers {
			v := volatility[sym]
			if v > 0 {
				fmt.Printf("  %s: %.2f%%\n", sym, v*100)
			}
		}
		volMu.RUnlock()
		fmt.Println()
	}
	updateVolatility()

	// Price stream (trades + quotes) — update state and push to Redis
	priceStream := alpaca.NewPriceStream(cfg.StreamWSURL, cfg.APIKeyID, cfg.APISecretKey, "iex", cfg.Tickers)
	lastPrint := make(map[string]time.Time)
	var printMu sync.Mutex
	priceStream.OnTrade = func(symbol string, price float64, size int, t time.Time) {
		state.RecordTrade(symbol, price, size, t)
		volMu.RLock()
		vol := volatility[symbol]
		volMu.RUnlock()
		payload := map[string]interface{}{
			"symbol":     symbol,
			"price":      price,
			"size":       size,
			"volume_1m":  state.Volume1m(symbol),
			"volume_5m":  state.Volume5m(symbol),
			"return_1m": state.Return1m(symbol, price),
			"return_5m": state.Return5m(symbol, price),
			"session":    brain.Session(time.Now()),
			"volatility": vol,
		}
		if brainPipe != nil {
			_ = brainPipe.Send("trade", payload)
		}
		redis.LogErr(pub.PublishJSON(context.Background(), "trade", payload), "trade")
		printMu.Lock()
		now := time.Now()
		if now.Sub(lastPrint[symbol]) >= time.Second {
			lastPrint[symbol] = now
			fmt.Printf("[price] %s $%.2f (size %d) %s\n", symbol, price, size, t.Format("15:04:05"))
		}
		printMu.Unlock()
	}
	priceStream.OnQuote = func(symbol string, bid, ask float64, bidSize, askSize int, t time.Time) {
		mid := (bid + ask) / 2
		volMu.RLock()
		vol := volatility[symbol]
		volMu.RUnlock()
		payload := map[string]interface{}{
			"symbol":     symbol,
			"bid":       bid,
			"ask":       ask,
			"bid_size":  bidSize,
			"ask_size":  askSize,
			"mid":       mid,
			"volume_1m": state.Volume1m(symbol),
			"volume_5m": state.Volume5m(symbol),
			"return_1m": state.Return1m(symbol, mid),
			"return_5m": state.Return5m(symbol, mid),
			"session":   brain.Session(time.Now()),
			"volatility": vol,
		}
		if brainPipe != nil {
			_ = brainPipe.Send("quote", payload)
		}
		redis.LogErr(pub.PublishJSON(context.Background(), "quote", payload), "quote")
		printMu.Lock()
		now := time.Now()
		if now.Sub(lastPrint[symbol]) >= time.Second {
			lastPrint[symbol] = now
			fmt.Printf("[quote] %s bid=%.2f ask=%.2f mid=%.2f %s\n", symbol, bid, ask, mid, t.Format("15:04:05"))
		}
		printMu.Unlock()
	}

	// News stream — push full article to Redis
	newsStream := alpaca.NewNewsStream(cfg.StreamWSURL, cfg.APIKeyID, cfg.APISecretKey, cfg.Tickers)
	newsStream.OnNews = func(a alpaca.NewsArticle) {
		payloadBytes, _ := json.Marshal(map[string]interface{}{
			"id":         a.ID,
			"headline":   a.Headline,
			"author":     a.Author,
			"created_at": a.CreatedAt,
			"updated_at": a.UpdatedAt,
			"summary":    a.Summary,
			"url":        a.URL,
			"symbols":    a.Symbols,
			"source":     a.Source,
		})
		var payload map[string]interface{}
		_ = json.Unmarshal(payloadBytes, &payload)
		if brainPipe != nil {
			_ = brainPipe.Send("news", payload)
		}
		redis.LogErr(pub.PublishJSON(context.Background(), "news", payload), "news")
		fmt.Printf("[news] %s | %s\n", strings.Join(a.Symbols, ","), a.Headline)
		fmt.Printf("       %s | %s\n", a.CreatedAt, a.Source)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	// Volatility refresh every 5 min
	go func() {
		ticker := time.NewTicker(5 * time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				updateVolatility()
			}
		}
	}()

	// Positions and open orders for the brain (every 30s)
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		pushPositionsAndOrders := func() {
			positions, err := tradingClient.GetPositions()
			if err != nil {
				log.Printf("[trading] positions: %v", err)
				return
			}
			posPayload := make([]map[string]interface{}, 0, len(positions))
			for _, p := range positions {
				posPayload = append(posPayload, map[string]interface{}{
					"symbol": p.Symbol, "qty": p.Qty, "side": p.Side,
					"market_value": p.MarketValue, "cost_basis": p.CostBasis,
					"unrealized_pl": p.UnrealizedPL, "unrealized_plpc": p.UnrealizedPLPC, "current_price": p.CurrentPrice,
				})
			}
			if brainPipe != nil {
				_ = brainPipe.Send("positions", map[string]interface{}{"positions": posPayload})
			}
			redis.LogErr(pub.Publish(context.Background(), redis.BrainEvent{Type: "positions", Payload: map[string]interface{}{"positions": posPayload}}), "positions")
			orders, err := tradingClient.GetOpenOrders()
			if err != nil {
				log.Printf("[trading] orders: %v", err)
				return
			}
			ordPayload := make([]map[string]interface{}, 0, len(orders))
			for _, o := range orders {
				ordPayload = append(ordPayload, map[string]interface{}{
					"id": o.ID, "symbol": o.Symbol, "side": o.Side, "qty": o.Qty,
					"filled_qty": o.FilledQty, "type": o.Type, "status": o.Status,
					"created_at": o.CreatedAt,
				})
			}
			if brainPipe != nil {
				_ = brainPipe.Send("orders", map[string]interface{}{"orders": ordPayload})
			}
			redis.LogErr(pub.Publish(context.Background(), redis.BrainEvent{Type: "orders", Payload: map[string]interface{}{"orders": ordPayload}}), "orders")
		}
		pushPositionsAndOrders()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				pushPositionsAndOrders()
			}
		}
	}()

	// Run price stream in background (reconnect on error for resilience)
	go func() {
		for {
			if err := priceStream.Run(); err != nil {
				log.Printf("[stream] price stream ended: %v", err)
			}
			select {
			case <-ctx.Done():
				return
			default:
				log.Printf("[stream] reconnecting price stream in 5s...")
				time.Sleep(5 * time.Second)
			}
		}
	}()

	// Run news stream in background
	go func() {
		for {
			if err := newsStream.Run(); err != nil {
				log.Printf("[stream] news stream ended: %v", err)
			}
			select {
			case <-ctx.Done():
				return
			default:
				log.Printf("[stream] reconnecting news stream in 5s...")
				time.Sleep(5 * time.Second)
			}
		}
	}()

	<-ctx.Done()
	fmt.Println("\nStopping...")
}

// runOneShot: single REST fetch and print (original behavior).
func runOneShot(cfg *config.Config) {
	fmt.Println("Alpaca Market Data (one-shot REST)")
	fmt.Println("Data URL:", cfg.DataBaseURL)
	fmt.Println("Tickers:", strings.Join(cfg.Tickers, ", "))
	keyPreview := "not set"
	if len(cfg.APIKeyID) >= 8 {
		keyPreview = cfg.APIKeyID[:4] + "..." + cfg.APIKeyID[len(cfg.APIKeyID)-4:]
	}
	fmt.Println("Key ID:", keyPreview)
	fmt.Println()

	client := alpaca.NewClient(cfg.DataBaseURL, cfg.APIKeyID, cfg.APISecretKey)

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

	newsBySymbol := make(map[string][]alpaca.NewsArticle)
	if errNews == nil && news != nil {
		for i := range news.News {
			a := &news.News[i]
			for _, sym := range a.Symbols {
				newsBySymbol[sym] = append(newsBySymbol[sym], *a)
			}
		}
	}

	for _, sym := range cfg.Tickers {
		fmt.Println("═══════════════════════════════════════════════════════════")
		fmt.Printf("  %s\n", sym)
		fmt.Println("═══════════════════════════════════════════════════════════")

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

		s, ok := snapshots[sym]
		price, priceSource := 0.0, ""
		if ok {
			if s.LatestTrade != nil && s.LatestTrade.Price > 0 {
				price, priceSource = s.LatestTrade.Price, "last trade (live)"
			} else if s.LatestQuote != nil && (s.LatestQuote.BidPrice+s.LatestQuote.AskPrice) > 0 {
				price = (s.LatestQuote.BidPrice + s.LatestQuote.AskPrice) / 2
				priceSource = "mid quote (live)"
			} else if s.DailyBar != nil && s.DailyBar.Close > 0 {
				price, priceSource = s.DailyBar.Close, "daily close"
			} else if s.PrevDailyBar != nil && s.PrevDailyBar.Close > 0 {
				price, priceSource = s.PrevDailyBar.Close, "previous close (market closed)"
			}
		}
		if price > 0 {
			fmt.Printf("  Price: $%.2f  [%s]\n", price, priceSource)
		} else {
			fmt.Println("  Price: — (no data; US market closed weekends 9:30am–4pm ET)")
		}
		fmt.Println()

		bars, ok := barsResp.Bars[sym]
		if !ok || len(bars) == 0 {
			fmt.Println("  Volatility (30d annualized): — (no bar data)")
		} else {
			vol := alpaca.AnnualizedVolatility(bars)
			fmt.Printf("  Volatility (30d annualized): %.2f%%\n", vol*100)
		}
		fmt.Println()
	}

	fmt.Println("═══════════════════════════════════════════════════════════")
	fmt.Println("Done.")
}
