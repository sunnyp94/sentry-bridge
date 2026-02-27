# Python brain

Trading brain for Sentry Bridge: reads market events (from Go via stdin or from Redis), runs strategy and rules, and places paper orders on Alpaca.

## Layout

```
python-brain/
├── README.md           # This file
├── requirements.txt    # Dependencies (redis, vaderSentiment, alpaca-py, transformers, torch, …)
├── apps/               # Entry points (runnable scripts)
│   ├── consumer.py     # Stdin consumer — used by Go (BRAIN_CMD). Reads NDJSON, runs strategy, places orders.
│   ├── redis_consumer.py  # Redis consumer — reads stream market:updates (test pipeline or second consumer).
│   ├── replay_e2e.py  # E2E test: emits synthetic NDJSON (volatility, trade, news) so you can test without market hours.
│   ├── backtest.py    # Backtest strategy on Alpaca daily bars (same decide() + prob_gain; optional RSI).
│   ├── run_screener.py # Stock scanner: daily opportunity pool (Z/volume), output top N to file.
│   └── test_paper_order.py # One-off test: submit 1 paper BUY to verify Alpaca API.
└── brain/              # Library package (do not run directly)
    ├── config.py       # All thresholds and flags from env.
    ├── log_config.py   # Logging init (LOG_LEVEL, stderr).
    ├── strategy.py     # Orchestrates signals + rules → buy/sell/hold.
    ├── executor.py     # Places orders on Alpaca; get_account_equity() for daily cap.
    ├── learning/       # Learning from trades + generated filter rules (see brain/learning/README.md)
    │   ├── experience_buffer.py  # Records entry/exit to data/experience_buffer.jsonl for the optimizer.
    │   └── generated_rules.py    # Loads active rules; should_block_buy(context) before placing a buy.
    ├── signals/        # Score inputs for strategy
    │   ├── news_sentiment.py  # FinBERT/VADER on news (headline + summary).
    │   ├── composite.py       # News + Social (placeholder) + Momentum + optional Technical (RSI); consensus.
    │   ├── technical.py      # RSI (and optional indicators) from price series; score in [-1, 1].
    │   └── microstructure.py # VWAP, ATR, Z-Score (pro-style); OFI stub for tape data.
    └── rules/          # Business rules
        ├── consensus.py   # Require N sources positive to allow buy.
        └── daily_cap.py   # 0.25% daily shutdown (no new buys when daily PnL ≥ 0.25%).
```

## Running

- **From Go (Docker or local):** Set `BRAIN_CMD="python3 python-brain/apps/consumer.py"` (or `/app/python-brain/apps/consumer.py` inside Docker). Go pipes NDJSON to stdin.
- **Redis consumer (standalone):** From repo root or `python-brain`:  
  `REDIS_URL=redis://localhost:6379 python3 python-brain/apps/redis_consumer.py`  
  (or from inside `python-brain`: `python3 apps/redis_consumer.py`).
- **Test paper order:** From repo root with `.env` loaded:  
  `cd python-brain && python3 apps/test_paper_order.py`

- **E2E replay (no market data):** When the market is closed (e.g. Sunday), run a short replay that feeds the same NDJSON format Go uses:
  ```bash
  cd python-brain
  python3 apps/replay_e2e.py | python3 apps/consumer.py
  ```
  You should see event logs, composite/strategy output, and optionally a paper order if `TRADE_PAPER=true` and Alpaca keys are set. To only test the pipeline without placing orders, set `TRADE_PAPER=false` or omit Alpaca keys.

- **Backtest:** Run the strategy on historical daily bars (Alpaca). No news (sentiment=0); uses momentum + optional RSI when `USE_TECHNICAL_INDICATORS=true`.
  ```bash
  set -a && source .env && set +a
  python3 python-brain/apps/backtest.py --symbols AAPL,MSFT --days 90
  ```

- **Stock scanner (daily opportunity pool):** Don’t hard-code a static list—screen the universe each day and activate only the top 3–5 names. Run every morning (e.g. discovery 7:00–9:30 ET); writes active symbols to a file the consumer reads.
  - **Universe:** Start with `lab_12`, `sp400`, `nasdaq100`, or `file:path/to/symbols.txt`. Scanner runs at container start and 7:00 ET (discovery) on full market days.
  - **Criteria:** |Z-score| > 2.0 (extreme move), or 15% volume spike vs 20-day average; optional OFI skew when available.
  - **Deploy:** Bot only runs strategy for symbols in the active list when `OPPORTUNITY_ENGINE_ENABLED=true` and `ACTIVE_SYMBOLS_FILE` is set.
  ```bash
  python3 apps/run_screener.py --universe lab_12 --top 5 --out data/active_symbols.txt
  ```
  Then set `OPPORTUNITY_ENGINE_ENABLED=true` and `ACTIVE_SYMBOLS_FILE=data/active_symbols.txt` (or absolute path). Consumer runs strategy only for symbols in that pool.

- **Full-market / small–mid cap scan (Active Trader Pro):** With higher Alpaca rate limits (e.g. 10k calls/min), you can screen the whole tradeable universe or a custom list.
  - **Universe:** `alpaca_equity` = all active US equities from Alpaca; `alpaca_equity_500` = first 500 (faster). Alpaca does not expose market cap; for Russell 2000 or a custom small-cap list, use a symbols file: `file:path/to/symbols.txt` (one symbol per line; `#` = comment).
  - **Batching:** Bars are fetched in chunks (default 100 symbols, 0.5s delay). Use `SCREENER_CHUNK_SIZE` / `SCREENER_CHUNK_DELAY_SEC` or `--chunk-size` / `--chunk-delay` to tune.
  - **Russell 2000 / small-cap list:** Export a list from your broker or a data provider (e.g. Fidelity, or a CSV from the web), one symbol per line, save as e.g. `python-brain/data/r2000.txt`, then:
  ```bash
  python3 apps/run_screener.py --universe file:data/r2000.txt --top 10 --out data/active_symbols.txt
  ```

- **Trade universe (S&P MidCap 400 / Nasdaq 100):** For high liquidity without the most efficient mega-caps, use index lists. Add symbol files and use named universes:
  - **S&P MidCap 400:** Put symbols in `data/sp400.txt` (one per line; get list from S&P or your broker), then `--universe sp400`.
  - **Nasdaq 100:** Put symbols in `data/nasdaq100.txt`, then `--universe nasdaq100`.
  ```bash
  python3 apps/run_screener.py --universe sp400 --top 10 --out data/active_symbols.txt
  ```

- **Global filter (SPY 200-day MA):** When SPY is below its 200-day moving average, the bot is more cautious on longs (stricter Z-score for entry, smaller position size) and will be more aggressive on short Z-score signals when shorts are added. Enable with `SPY_200MA_REGIME_ENABLED=true`; tune `SPY_BELOW_200MA_Z_TIGHTEN` (e.g. -2.8) and `SPY_BELOW_200MA_LONG_SIZE_MULTIPLIER` (e.g. 0.5). Live consumer refreshes SPY regime every 15 minutes.

- **Technical (RSI + MACD + 3 patterns):** The technical layer is only RSI, MACD, and three chart patterns: **double top** (bearish), **inverted head and shoulders** (bullish), **bull/bear flag** (directional). No other indicators. Set `USE_TECHNICAL_INDICATORS=true`; optional `USE_MACD`, `USE_PATTERNS`, `MACD_FAST/SLOW/SIGNAL`, `PATTERN_LOOKBACK`. Price history from trade/quote or daily bars.

### Market microstructure (pro-style)

The strategy can use four professional layers so execution is driven by how price is made, not just lagging price action:

| Layer | Role | Config (all optional, off by default) |
|-------|------|--------------------------------------|
| **VWAP** | Institutional magnet / fair value. Extended above VWAP → wait for mean reversion before entering. | `USE_VWAP_ANCHOR`, `VWAP_MEAN_REVERSION_PCT`, `VWAP_LOOKBACK` |
| **ATR** | Volatility-adjusted stops (no fixed %). Stop widens when choppy, tightens when calm. | `USE_ATR_STOP`, `ATR_PERIOD`, `ATR_STOP_MULTIPLE` |
| **Z-Score** | Quantify “weirdness”: Z ≤ -2 or -3 = statistical oversold, bias toward mean-reversion buy. | `USE_ZSCORE_MEAN_REVERSION`, `ZSCORE_MEAN_REVERSION_BUY`, `ZSCORE_PERIOD` |
| **OFI** | Order flow imbalance (leading signal). Built from Alpaca trade/quote: aggressor inferred from trade price vs bid/ask; rolling window per symbol. | `USE_OFI`, `OFI_WINDOW_TRADES` (live only; backtest uses daily bars, no tape) |

See `brain/signals/microstructure.py` and `.env.example` for details.

### Recursive Strategy Optimizer

The brain includes an optional **experience buffer**, **attribution engine**, **shadow strategy**, and **conviction sizing** to reduce strategy decay:

| Component | Role | Config / Script |
|-----------|------|-----------------|
| **Experience Buffer** | In **brain/learning/**: saves a `MarketSnapshot` on every entry/exit to `data/experience_buffer.jsonl`. Trimmed by default to last 20,000 lines (older lines dropped when over limit). Conviction uses in-memory window; optimizer trains on the buffer. | `EXPERIENCE_BUFFER_ENABLED=true` (default). See **brain/learning/README.md**. |
| **Attribution Engine** | Runs Random Forest on the **experience buffer** (see **brain/learning/**). Suggests filter rules when a setup has &lt;40% success under a condition. Run daily after 4pm ET: `./scripts/run_optimizer_after_close.sh` or **docs/OPTIMIZER_DAILY.md**. Active rules are applied via **brain.learning.generated_rules** (`should_block_buy`). | `python3 python-brain/apps/strategy_optimizer.py [--write-proposed] [--rolling-days 7]`. Requires `scikit-learn`. |
| **Shadow Strategy** | Tracks 3 ghost models (tighter/wide/scalp stop–TP) in parallel with live. No real orders; logs when a shadow outperforms over 30 ghost trades. | `SHADOW_STRATEGY_ENABLED=true` (default). |
| **Conviction** | Reward +1 for profit, −2 for stop loss. Per-setup conviction scales position size (winning streak → up to 1.5×; losing → down to 0.5×). | `CONVICTION_SIZING_ENABLED=true` (default). |

Install deps first: `python3 -m pip install -r requirements.txt` (from repo root or python-brain).

### Long continuous runs (e.g. 2 weeks without restart)

- **Experience buffer:** The buffer file (`data/experience_buffer.jsonl`) is trimmed by default to the last 20,000 lines (when it exceeds that, the file is rewritten with only the last N lines — older lines are dropped). See **brain/learning/experience_buffer.py**.
- **Memory:** The consumer prunes symbol-keyed caches (payload, session, sentiment, price history, order cooldown) to the active symbol list + current positions when `OPPORTUNITY_ENGINE_ENABLED=true` and `ACTIVE_SYMBOLS_FILE` is set, so memory stays bounded as the watchlist changes. Shadow strategy keeps only the last 1000 ghost trades per shadow. Scale-out state is cleared when a position is closed.
- **Logging:** Use `LOG_LEVEL=INFO` (or `WARN`) in production so logs don’t grow too fast; rotate logs externally if needed.
- **Go state:** The Go engine keeps per-symbol price/volume history trimmed to a 6-minute lookback; the number of symbols is your configured ticker list, so memory is bounded if the watchlist is fixed.
