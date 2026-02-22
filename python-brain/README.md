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
│   └── test_paper_order.py # One-off test: submit 1 paper BUY to verify Alpaca API.
└── brain/              # Library package (do not run directly)
    ├── config.py       # All thresholds and flags from env.
    ├── log_config.py   # Logging init (LOG_LEVEL, stderr).
    ├── strategy.py     # Orchestrates signals + rules → buy/sell/hold.
    ├── executor.py     # Places orders on Alpaca; get_account_equity() for daily cap.
    ├── signals/        # Score inputs for strategy
    │   ├── news_sentiment.py  # FinBERT/VADER on news (headline + summary).
    │   └── composite.py       # News + Social (placeholder) + Momentum; consensus.
    └── rules/          # Business rules
        ├── consensus.py   # Require N sources positive to allow buy.
        └── daily_cap.py   # 0.2% daily shutdown (no new buys when daily PnL ≥ 0.2%).
```

## Running

- **From Go (Docker or local):** Set `BRAIN_CMD="python3 python-brain/apps/consumer.py"` (or `/app/python-brain/apps/consumer.py` inside Docker). Go pipes NDJSON to stdin.
- **Redis consumer (standalone):** From repo root or `python-brain`:  
  `REDIS_URL=redis://localhost:6379 python3 python-brain/apps/redis_consumer.py`  
  (or from inside `python-brain`: `python3 apps/redis_consumer.py`).
- **Test paper order:** From repo root with `.env` loaded:  
  `cd python-brain && python3 apps/test_paper_order.py`

Install deps first: `python3 -m pip install -r requirements.txt` (from repo root or python-brain).
