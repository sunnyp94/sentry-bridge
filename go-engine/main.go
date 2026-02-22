// Package main runs the Sentry Bridge engine: streams Alpaca market data (trades, quotes, news),
// computes volatility, and pushes events to a Python brain (stdin pipe) and optionally Redis.
// The Python brain decides buy/sell and places paper orders via Alpaca. Set STREAM=false for one-shot REST mode.
package main

import (
	"context"
	"encoding/json"
	"log/slog"
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

// initLogger configures slog from LOG_LEVEL (DEBUG/INFO/WARN/ERROR) and LOG_FORMAT (json or text).
func initLogger() {
	level := slog.LevelInfo
	if s := os.Getenv("LOG_LEVEL"); s != "" {
		switch strings.ToUpper(strings.TrimSpace(s)) {
		case "DEBUG":
			level = slog.LevelDebug
		case "INFO":
			level = slog.LevelInfo
		case "WARN":
			level = slog.LevelWarn
		case "ERROR":
			level = slog.LevelError
		}
	}
	opts := &slog.HandlerOptions{Level: level}
	var h slog.Handler
	if strings.ToLower(strings.TrimSpace(os.Getenv("LOG_FORMAT"))) == "json" {
		h = slog.NewJSONHandler(os.Stderr, opts)
	} else {
		h = slog.NewTextHandler(os.Stderr, opts)
	}
	slog.SetDefault(slog.New(h))
}

func main() {
	initLogger()
	cfg, err := config.Load()
	if err != nil {
		slog.Error("config load failed", "err", err)
		os.Exit(1)
	}
	if cfg.APIKeyID == "" || cfg.APISecretKey == "" {
		slog.Error("missing credentials", "msg", "set APCA_API_KEY_ID and APCA_API_SECRET_KEY (e.g. in .env)")
		os.Exit(1)
	}
	if len(cfg.Tickers) == 0 {
		slog.Error("missing tickers", "msg", "set TICKERS (comma-separated, e.g. AAPL,TSLA,GOOGL)")
		os.Exit(1)
	}

	if cfg.StreamingMode {
		runStreaming(cfg)
		return
	}
	runOneShot(cfg)
}

// runStreaming: WebSocket price + news, volatility refresh every 5 min; push all to Redis for Python brain.
func runStreaming(cfg *config.Config) {
	slog.Info("streaming mode", "data_url", cfg.DataBaseURL, "stream_url", cfg.StreamWSURL, "tickers", cfg.Tickers)

	client := alpaca.NewClient(cfg.DataBaseURL, cfg.APIKeyID, cfg.APISecretKey)
	tradingClient := alpaca.NewTradingClient(cfg.TradingBaseURL, cfg.APIKeyID, cfg.APISecretKey)

	// Brain closest to data: pipe events to Python subprocess via stdin (no Redis in hot path)
	var brainPipe *brain.Pipe
	if cfg.BrainCmd != "" {
		if p, err := brain.StartPipe(cfg.BrainCmd); err != nil {
			slog.Error("brain pipe start failed", "cmd", cfg.BrainCmd, "err", err)
		} else if p != nil {
			brainPipe = p
			defer brainPipe.Close()
			slog.Info("brain pipe started", "cmd", cfg.BrainCmd)
		}
	}

	// Redis (optional; for replay or other consumers)
	var pub redis.PublisherInterface = redis.NoopPublisher{}
	if cfg.RedisURL != "" {
		if p, err := redis.NewPublisher(cfg.RedisURL, cfg.RedisStream); err != nil {
			slog.Error("redis not connected", "err", err)
		} else {
			pub = p
			defer p.Close()
			slog.Info("redis stream", "stream", cfg.RedisStream)
		}
	}

	// Brain state: price/volume history for returns and volume_1m/5m
	state := brain.NewState()

	// Shared volatility (updated every 5 min)
	var volMu sync.RWMutex
	volatility := make(map[string]float64)

	// Initial volatility and push to Redis
	updateVolatility := func() {
		barsResp, err := client.GetBars(cfg.Tickers, "1Day", 30)
		if err != nil {
			slog.Error("volatility bars error", "err", err)
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
		volMu.RLock()
		for _, sym := range cfg.Tickers {
			if v := volatility[sym]; v > 0 {
				slog.Info("volatility", "symbol", sym, "annualized_30d_pct", v*100)
			}
		}
		volMu.RUnlock()
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
			slog.Debug("price", "symbol", symbol, "price", price, "size", size, "at", t.Format("15:04:05"))
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
			slog.Debug("quote", "symbol", symbol, "bid", bid, "ask", ask, "mid", mid, "at", t.Format("15:04:05"))
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
		slog.Info("news", "symbols", strings.Join(a.Symbols, ","), "headline", a.Headline, "created_at", a.CreatedAt, "source", a.Source)
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
				slog.Error("trading positions error", "err", err)
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
				slog.Error("trading orders error", "err", err)
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
				slog.Error("price stream ended", "err", err)
			}
			select {
			case <-ctx.Done():
				return
			default:
				slog.Info("reconnecting price stream in 5s")
				time.Sleep(5 * time.Second)
			}
		}
	}()

	// Run news stream in background
	go func() {
		for {
			if err := newsStream.Run(); err != nil {
				slog.Error("news stream ended", "err", err)
			}
			select {
			case <-ctx.Done():
				return
			default:
				slog.Info("reconnecting news stream in 5s")
				time.Sleep(5 * time.Second)
			}
		}
	}()

	<-ctx.Done()
	slog.Info("stopping")
}

// runOneShot: single REST fetch and print (original behavior).
func runOneShot(cfg *config.Config) {
	slog.Info("one-shot REST", "data_url", cfg.DataBaseURL, "tickers", cfg.Tickers)
	client := alpaca.NewClient(cfg.DataBaseURL, cfg.APIKeyID, cfg.APISecretKey)

	news, errNews := client.GetNews(cfg.Tickers, 50)
	snapshots, errSnap := client.GetSnapshots(cfg.Tickers)
	barsResp, errBars := client.GetBars(cfg.Tickers, "1Day", 30)

	if errNews != nil {
		slog.Error("news fetch error", "err", errNews)
	}
	if errSnap != nil {
		slog.Error("snapshots fetch error", "err", errSnap)
	}
	if errBars != nil {
		slog.Error("bars fetch error", "err", errBars)
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
		articles := newsBySymbol[sym]
		if len(articles) > 0 {
			for _, a := range articles {
				slog.Info("news", "symbol", sym, "headline", a.Headline, "created_at", a.CreatedAt, "source", a.Source)
			}
		} else {
			slog.Debug("news", "symbol", sym, "count", 0)
		}

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
			slog.Info("price", "symbol", sym, "price", price, "source", priceSource)
		} else {
			slog.Info("price", "symbol", sym, "msg", "no data (US market closed weekends 9:30am–4pm ET)")
		}

		bars, ok := barsResp.Bars[sym]
		if ok && len(bars) > 0 {
			vol := alpaca.AnnualizedVolatility(bars)
			slog.Info("volatility", "symbol", sym, "annualized_30d_pct", vol*100)
		} else {
			slog.Debug("volatility", "symbol", sym, "msg", "no bar data")
		}
	}

	slog.Info("one-shot done")
}
