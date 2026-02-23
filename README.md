# Sentry Bridge

Go engine that pulls **market news**, **price**, and **volatility** from Alpaca Markets for a configurable set of stock tickers. Currently set up for **Alpaca sandbox** (paper trading); production/live can be enabled later.

## Prerequisites

- [Go 1.21+](https://go.dev/dl/)
- [Alpaca](https://alpaca.markets) account (use **Paper Trading** for sandbox)

## Setup

1. **Get Alpaca API keys (sandbox)**  
   - Sign up at [alpaca.markets](https://alpaca.markets) and open the **Paper Trading** dashboard.  
   - Create an API key pair (Key ID + Secret). Use these for sandbox.

2. **Configure environment**  
   Copy the example env file and add your keys:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set:

   - `APCA_API_KEY_ID` – your Alpaca Key ID  
   - `APCA_API_SECRET_KEY` – your Alpaca Secret Key  

   Optional:

   - `TICKERS` – comma-separated symbols (fallback when not using the scanner)  
   - **Daily opportunity pool:** Set `SCREENER_UNIVERSE` (e.g. `lab_12`, `sp400`, `nasdaq100`), `ACTIVE_SYMBOLS_FILE=data/active_symbols.txt`, and `OPPORTUNITY_ENGINE_ENABLED=true`; the scanner runs automatically before the trading day (no static stock list needed).  
   - `ALPACA_DATA_BASE_URL` – REST data API (default `https://data.alpaca.markets`)  
   - `STREAM` – set to `false` or `0` for one-shot REST only; default is streaming mode  
   - `REDIS_URL` – Redis address for Python brain (e.g. `redis://localhost:6379`); if unset, events are not published  
   - `REDIS_STREAM` – stream name (default `market:updates`)  
   - `APCA_API_BASE_URL` – Alpaca Trading API for positions/orders (default `https://paper-api.alpaca.markets`)

## How to run

### Run locally with Docker (same as cloud)

One command runs the full stack (Go + Redis + Python brain) the same way locally and in production. **Prerequisites:** [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) installed and **running** (open the app and wait until the whale icon appears in the menu bar).

1. **Create `.env`** in the project root with:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` (Alpaca)
   - `TICKERS=AAPL,MSFT,GOOGL,AMZN,TSLA` (optional)
   - Do **not** set `REDIS_URL` or `BRAIN_CMD` — the compose file sets them for the app container.

2. **From the project root** (either command):
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   docker compose up --build
   ```
   Or: `./run-docker.sh`

   This builds the app image (Go + Python brain), starts Redis, then runs the app. You’ll see Go logs, Redis stream connection, and `[brain]` lines from the Python consumer. Stop with **Ctrl+C**. Run in background with `docker compose up -d --build`.

3. **Stop and remove containers:**
   ```bash
   docker compose down
   ```

**What runs:** The `app` container runs the Go binary; Go connects to the `redis` service and pipes events to the Python brain inside the same container. Redis is used for the stream (replay/other consumers).

### Deploy (e.g. AWS with Redis Cloud)

- **Same image:** Build and push your image (e.g. to ECR), then run it in ECS, App Runner, or EC2 in **us-east-1**.
- **Redis:** Use **Redis Cloud** in the same region. Create a database, get the URL (e.g. `rediss://default:PASSWORD@host:port`).
- **Environment:** Set at runtime (no `.env` in the container):
  - `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`
  - `REDIS_URL=<your-redis-cloud-url>`
  - `BRAIN_CMD="python3 /app/python-brain/apps/consumer.py"`
  - `TICKERS=...` (optional)
- **Secrets:** Store Alpaca keys and Redis password in AWS Secrets Manager or Parameter Store and inject into the task/instance.
- **Compose on a server:** You can run `docker compose` on an EC2 (or similar) and use an override for production:
  - No local `redis` service; set `REDIS_URL` to Redis Cloud.
  - Use `env_file` pointing to a prod env file or pass env from Secrets Manager.

Example override for “app only + Redis Cloud” (no local Redis container):

```bash
# .env.production (or inject via your orchestrator)
REDIS_URL=rediss://default:YOUR_PASSWORD@your-redis-cloud-host:port
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
BRAIN_CMD="python3 /app/python-brain/apps/consumer.py"
```

Then run the app container with that env; point it at Redis Cloud instead of a local Redis.

---

### Run without Docker (Go + Python brain on your machine)

From the **project root**:

1. In `.env`: set `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `BRAIN_CMD="python3 python-brain/apps/consumer.py"`. Omit or comment out `REDIS_URL` unless you run Redis via Homebrew.
2. Run:
   ```bash
   set -a && source .env && set +a && cd go-engine && go run .
   ```

Make sure `.env` contains your real Alpaca keys. Use `TICKERS=AAPL,TSLA,NVDA,META` to change symbols.

## How to test

1. **From project root**, load env and run the Go engine (with optional brain):

   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   set -a && source .env && set +a && cd go-engine && go run .
   ```

2. **With the Python brain:** add to `.env`:
   ```bash
   BRAIN_CMD=python3 python-brain/apps/consumer.py
   ```
   Then run the same command above. You should see:
   - Go: `Brain: piping to python3 python-brain/apps/consumer.py`
   - Go: Alpaca stream lines (`[price]`, `[quote]`, `[news]`, volatility block)
   - Python: `[brain] TRADE ...`, `[brain] QUOTE ...`, `[brain] NEWS ...`, etc., as events are piped to the consumer

3. **Without the brain:** leave `BRAIN_CMD` unset or comment it out. Only the Go console output will appear.

4. **Test the Python consumer alone** (no Go): pipe a few JSON lines into it to confirm it parses and prints:
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   echo '{"type":"trade","ts":"2026-02-22T12:00:00Z","payload":{"symbol":"AAPL","price":178.5}}' | python3 python-brain/apps/consumer.py
   ```
   You should see one `[brain] TRADE AAPL ...` line.

5. **Test end-to-end with synthetic data (no market hours):** When the market is closed (e.g. Sunday evening), use the replay script to run the full brain pipeline (composite → strategy → optional paper order):
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   set -a && source .env && set +a
   python3 python-brain/apps/replay_e2e.py | python3 python-brain/apps/consumer.py
   ```
   To test strategy only without placing orders: `TRADE_PAPER=false python3 python-brain/apps/replay_e2e.py | python3 python-brain/apps/consumer.py`.

6. **Stop:** press **Ctrl+C** in the terminal where `cd go-engine && go run .` is running.

**Note:** During US market hours (9:30am–4pm ET, weekdays) you’ll get live trades/quotes. Outside those hours you’ll mainly see news (if any), volatility on startup, and positions/orders every 30s.

### Test the Go → Redis → Python pipeline (news and all events)

To verify that events (including news) flow from Go to Redis to Python:

1. **Start Redis** (Docker or Homebrew):
   ```bash
   docker compose up -d redis
   # or: brew services start redis
   ```

2. **`.env`** must include:
   ```bash
   REDIS_URL=redis://localhost:6379
   ```
   Optionally comment out `BRAIN_CMD` so only Redis is used (no stdin pipe).

3. **Terminal 1 — Go (writes to Redis):**
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   set -a && source .env && set +a && cd go-engine && go run .
   ```
   You should see `Redis stream: market:updates` and Go logs. News, trades, quotes, etc. are written to the stream.

4. **Terminal 2 — Python (reads from Redis):**
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge/python-brain
   python3 -m pip install -r requirements.txt
   REDIS_URL=redis://localhost:6379 REDIS_STREAM=market:updates python3 apps/redis_consumer.py
   ```
   You should see `[redis] NEWS ...`, `[redis] TRADE ...`, `[redis] QUOTE ...`, etc. as events arrive. News headlines will appear when Alpaca sends them.

5. **Stop:** Ctrl+C in both terminals. Optionally `docker compose down` to stop Redis.

To test with Docker (Go + Redis in one stack), run `docker compose up --build` in one terminal and the Python Redis consumer in another (same `REDIS_URL=redis://localhost:6379`; Redis is exposed on the host).

## Logging

All components use structured logging with configurable levels.

**Go (slog):**
- **LOG_LEVEL:** `DEBUG` | `INFO` (default) | `WARN` | `ERROR`. Reduces noise (e.g. `DEBUG` for every trade/quote).
- **LOG_FORMAT:** `json` for one-JSON-object-per-line to stderr (for log aggregators); omit for human-readable text.
- Example: `LOG_LEVEL=INFO LOG_FORMAT=json` when deploying.

**Python (brain, executor, strategy, redis_consumer):**
- **LOG_LEVEL:** Same as Go (`DEBUG`, `INFO`, `WARN`, `ERROR`). Default `INFO`.
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s` to stderr. The brain calls `log_config.init()` so all loggers share this.
- Example: `LOG_LEVEL=DEBUG python3 apps/consumer.py` for verbose event logs (run from python-brain).

### Streaming mode (default — high-frequency)

By default the app runs in **streaming mode**:

- **Price** – WebSocket to Alpaca stock stream (`v2/iex`): real-time trades and quotes; each update is printed (throttled to 1 per symbol per second).
- **News** – WebSocket to Alpaca news stream (`v1beta1/news`): headlines printed as they arrive.
- **Volatility** – Refreshed every **5 minutes** via REST (30-day daily bars, annualized). Printed on startup and then every 5 min.

Press **Ctrl+C** to stop. Streams reconnect automatically if the connection drops.

### Brain (closest to data)

Set **`BRAIN_CMD`** to pipe events directly to your Python brain process via **stdin** (no Redis in the hot path). The Go engine starts the process and writes one NDJSON event per line. Example:

```bash
# .env
BRAIN_CMD=python3 python-brain/apps/consumer.py
```

Run from **project root** so the path resolves:

```bash
cd /path/to/sentry-bridge
set -a && source .env && set +a && cd go-engine && go run .
```

The Python brain (`python-brain/apps/consumer.py`) reads stdin, logs events, and runs an **AI-driven strategy** on each news item: sentiment (VADER, or optional FinBERT) + probability of gain from returns/volatility → **buy / sell / hold**. When paper trading is enabled, it **places market orders** on Alpaca (paper account) for the tickers in `TICKERS`.

### Paper trading (AI buy/sell)

The brain decides when to buy or sell using:

- **Sentiment:** [FinBERT](https://huggingface.co/ProsusAI/finbert) (finance-trained transformer) on news headline + summary; falls back to VADER if unavailable. Install deps with `python3 -m pip install -r python-brain/requirements.txt`.
- **Probability of gain:** Heuristic from `return_1m`, `return_5m`, and `annualized_vol_30d` (from the stream).
- **Rules:** Buy when sentiment and prob_gain are above thresholds and you have no position; sell when sentiment is bearish or prob_gain drops and you have a position. Trades only during **regular session** unless you set `STRATEGY_REGULAR_SESSION_ONLY=false`. One order per symbol per 60s (cooldown).

**Enable paper trading:**

1. **Install Python deps** (from repo root):
   ```bash
   python3 -m pip install -r python-brain/requirements.txt
   ```

2. **`.env`** (you already have Alpaca keys for data; same keys work for paper trading):
   ```bash
   APCA_API_KEY_ID=...
   APCA_API_SECRET_KEY=...
   BRAIN_CMD=python3 python-brain/apps/consumer.py
   TRADE_PAPER=true
   TICKERS=AAPL,TSLA,NVDA
   ```

3. **Optional tuning** (defaults shown):
   ```bash
   SENTIMENT_BUY_THRESHOLD=0.18    # buy when sentiment >= this
   SENTIMENT_SELL_THRESHOLD=-0.18 # sell when sentiment <= this (and you have position)
   PROB_GAIN_THRESHOLD=0.54       # buy only when prob_gain >= this
   STRATEGY_MAX_QTY=2             # max shares per order
   STRATEGY_REGULAR_SESSION_ONLY=true
   # Composite: require 2 of 3 sources (news, social, momentum) positive to buy; avoid single sensational headline
   USE_CONSENSUS=true
   CONSENSUS_MIN_SOURCES_POSITIVE=2
   CONSENSUS_POSITIVE_THRESHOLD=0.15
   # 0.2% daily shutdown: no new buys when daily PnL >= 0.2% (lock in gains)
   DAILY_CAP_ENABLED=true
   DAILY_CAP_PCT=0.2
   # Kill switch: blocks all new buys when triggered (sticky until restart)
   KILL_SWITCH=false              # set true to disable buys manually
   KILL_SWITCH_SENTIMENT_THRESHOLD=-0.50   # bad news: trigger if headline+summary sentiment <= this
   KILL_SWITCH_RETURN_THRESHOLD=-0.05      # market tanks: trigger if return_1m or return_5m <= -5%
   # 5% stop loss on positions (sell when unrealized P&amp;L <= -5%)
   STOP_LOSS_PCT=5.0
   ```

   **Kill switch:** When triggered (bad news, sharp negative return, or `KILL_SWITCH=true`), **no new buy** signals are issued; sells (including stop loss) still execute. Triggered automatically when news sentiment ≤ `KILL_SWITCH_SENTIMENT_THRESHOLD` or when 1m/5m return ≤ `KILL_SWITCH_RETURN_THRESHOLD`.

   **Stop loss:** Every positions update (every 30s from Alpaca), any position with unrealized PnL ≤ `-STOP_LOSS_PCT`% is sold (market order). Default 5%.

4. **Run** (from project root):
   ```bash
   set -a && source .env && set +a && cd go-engine && go run .
   ```

You should see strategy logs with `sources=... consensus_ok=... -> action=...` and `[executor] BUY 1 AAPL -> order id=...` when the strategy triggers. Orders are **market, day** on your Alpaca **paper** account. Set `TRADE_PAPER=false` to log decisions only and not place orders.

**Composite score (3 sources):** By default the bot uses **News** (FinBERT) + **Social** (placeholder) + **Momentum** (returns). It only buys when at least **2 of 3** sources are "positive" (`CONSENSUS_MIN_SOURCES_POSITIVE=2`), so a single sensational headline doesn’t drive trades. If News is positive but Social is "meh," the bot stays cash. Set `USE_CONSENSUS=false` to use a single news score as before.

**0.2% daily shutdown:** When daily PnL ≥ `DAILY_CAP_PCT` (default **0.2%**), the bot stops **new buys** for the day (sells still allowed). Set `DAILY_CAP_ENABLED=false` to disable.

### Python brain: modular design

The Python brain is split so you can add or change business rules without rewriting the core:

| Layer | Role |
|-------|------|
| **config.py** | All thresholds and flags from env (e.g. `CONSENSUS_MIN_SOURCES_POSITIVE`, `DAILY_CAP_PCT`). |
| **signals/** | **news_sentiment** = FinBERT/VADER on news. **composite** = News + Social (placeholder) + Momentum and consensus. |
| **rules/** | **consensus** = allow buy only when enough sources positive. **daily_cap** = block new buys when daily PnL ≥ 0.2%. |
| **strategy.py** | Orchestrates: applies rules (kill switch, daily cap, session, consensus, stop loss) and returns buy/sell/hold. |
| **apps/consumer.py** | Stdin entry: reads events, updates state, calls composite + strategy + executor. |
| **apps/redis_consumer.py** | Redis entry: reads stream `market:updates` (test pipeline or second consumer). |
| **apps/test_paper_order.py** | One-off: submit 1 paper BUY to verify Alpaca API. |
| **executor.py** | Places orders on Alpaca; exposes `get_account_equity()` for daily cap. |

**Adding a business rule:** Add a new module under `rules/` (e.g. `rules/max_drawdown.py`) that exports something like `is_rule_blocking_buy() -> bool`. In `strategy.decide()`, pass that into the existing “block buy” checks and add a new `Decision("hold", ..., "max_drawdown")` branch. No need to change signals or consumer.

**Go ↔ Python transport:** Today the Go engine streams NDJSON to the brain over **stdin** (pipe). For lower latency you can later switch to **Unix sockets** or **gRPC** from Go and a matching client in Python; the brain’s entry point remains “receive events, update state, run strategy, optionally place order.”

### Redis stream (optional)

If `REDIS_URL` is set, every event is also pushed to a **Redis Stream** (`REDIS_STREAM`, default `market:updates`) so a Python layer can read with `XREAD BLOCK` and make buy/sell decisions. Each entry has `type`, `ts`, and `payload` (JSON):

| type        | payload contents |
|------------|-------------------|
| `news`     | id, headline, author, created_at, summary, url, symbols, source |
| `trade`    | symbol, price, size, volume_1m, volume_5m, return_1m, return_5m, session, volatility |
| `quote`    | symbol, bid, ask, bid_size, ask_size, mid, volume_1m, volume_5m, return_1m, return_5m, session, volatility |
| `volatility` | symbol, annualized_vol_30d |
| `positions` | positions[] (symbol, qty, side, market_value, cost_basis, unrealized_pl, current_price) |
| `orders`   | orders[] (id, symbol, side, qty, filled_qty, type, status, created_at) |

`session` is `pre_open`, `regular`, or `post_close` (Eastern). Volatility is 30-day annualized. Positions and orders are refreshed every 30 seconds.

## Local Redis

Redis is optional: the app works without it (brain gets data via stdin). Use Redis for replay, dashboards, or a second consumer.

### Option A: Docker (easiest)

From the project root:

```bash
docker compose up -d redis
# or:  docker-compose up -d redis
# or:  docker run -d --name redis -p 6379:6379 redis:7-alpine
```

Redis listens on `localhost:6379`. In `.env`:

```bash
REDIS_URL=redis://localhost:6379
REDIS_STREAM=market:updates
```

Stop with `docker compose down`.

### Option B: Homebrew (macOS)

```bash
brew install redis
brew services start redis
```

Then set `REDIS_URL=redis://localhost:6379` in `.env`.

### Verify

```bash
redis-cli PING
# PONG
```

Run the Go engine; events will be written to the stream `market:updates`. Inspect with:

```bash
redis-cli XRANGE market:updates - + COUNT 5
```

## Deploying to AWS (us-east) with Redis Cloud

1. **Redis Cloud**
   - Sign up at [redis.com/try-free](https://redis.com/try-free/) and create a subscription.
   - Create a database; choose **region** (e.g. **AWS us-east-1** for low latency to your app).
   - Enable **TLS** if required; note the **public endpoint** and **default user password**.
   - Connection string format: `rediss://default:<password>@<host>:<port>` (use `rediss://` if TLS is on).

2. **App on AWS (us-east-1)**
   - Run the Go engine (and optional Python brain) on **EC2**, **ECS/Fargate**, or **App Runner** in **us-east-1** so it’s in the same region as Redis Cloud.
   - Set environment variables (no `.env` file in prod):  
     `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `REDIS_URL=<your-redis-cloud-url>`, `REDIS_STREAM=market:updates`, `TICKERS`, and optionally `BRAIN_CMD` if the brain runs in the same task/instance.
   - For **BRAIN_CMD** in ECS/Fargate: either build a single image that runs both Go and Python (e.g. a shell script that starts the brain then the engine), or run the brain as a sidecar and use a local socket/Redis instead of stdin (more involved). Easiest: one container that runs `go run .` with `BRAIN_CMD` pointing to a Python script in the image.

3. **REDIS_URL in production**
   - Use the Redis Cloud **full URL** (with password), e.g.  
     `REDIS_URL=rediss://default:YOUR_PASSWORD@redis-12345.redis.cloud.com:12345`  
   - Store the password in **AWS Secrets Manager** or **Parameter Store** and inject it when starting the app (e.g. task definition env from Secrets Manager).

4. **Networking**
   - Redis Cloud databases have a **public endpoint** by default; restrict access by **source IP** (your app’s outbound IP or VPC NAT) in Redis Cloud if possible.
   - Alternatively use **Redis Cloud private endpoint** (VPC peering) if you’re in a VPC; then `REDIS_URL` uses the private hostname.

5. **Summary**
   - **Local:** `REDIS_URL=redis://localhost:6379`, optionally `docker compose up -d redis`.
   - **AWS us-east + Redis Cloud:** Run app in us-east-1, set `REDIS_URL` to your Redis Cloud URL (us-east-1), keep secrets in Secrets Manager.

### One-shot mode (single REST fetch)

To run a single REST fetch and exit (no WebSockets), set in `.env`:

```bash
STREAM=false
```

Then run the same commands above. You’ll get one snapshot of news, price, and volatility per ticker.

## Why price or volatility can be null

- **US equity markets** are closed on **weekends** and outside **9:30am–4pm ET** on weekdays.
- When the market is closed, **latest trade** and **latest quote** are not updated, so the snapshot can have nulls. The app falls back to **previous close** (last daily bar) when available and prints `[previous close (market closed)]`.
- **Volatility** is computed from the last 30 **daily** bars. Those bars exist regardless of market hours, so volatility should usually be non-null; if it’s null, the API returned no bars for that symbol.

## What you’ll see

The program prints to the console, **per stock**:

- **News** – headlines and timestamps for that symbol  
- **Price** – latest trade/quote when market is open, or daily/previous close when closed (with a short label)  
- **Volatility** – 30-day annualized volatility (from daily bars)

Example:

```
═══════════════════════════════════════════════════════════
  AAPL
═══════════════════════════════════════════════════════════
  News: 2 article(s)
    • Apple Leader in Phone Sales...
      2021-12-31T11:08:42Z | benzinga

  Price: $178.25  [last trade (live)]

  Volatility (30d annualized): 22.45%
```

## High-frequency / low-latency setup (how often to call)

For a trading app that needs fresh data:

| Data      | Recommended approach | Polling fallback (if not streaming) |
|-----------|----------------------|-------------------------------------|
| **Price** | **WebSocket** (Alpaca `stream.data.alpaca.markets`) for real-time trades/quotes. | REST snapshot every **1–5 seconds**; respect rate limits. |
| **News**  | **WebSocket** (Alpaca news stream) for instant headlines. | REST every **15–60 seconds** to balance latency vs rate limits. |
| **Volatility** | Compute from bars when new bar arrives. | **1-min bars**: recompute every 1–5 min. **Daily bars**: once per day or when daily bar is final. |

- **True HFT** (sub-millisecond) needs co-location and direct feeds; this app is REST/streaming over the internet, so aim for **low-second** latency (streaming) or **few-second** (polling).
- Use **streaming** for price and news when you move to a production trading loop; keep **volatility** on a slower schedule (e.g. minute or daily bars).

## Switching to production (later)

When you’re ready for live data:

1. Create a **live** Alpaca account and get live API keys.  
2. In `.env`, set:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` to your **live** keys  
   - `ALPACA_DATA_BASE_URL=https://data.alpaca.markets`  
3. Run the same commands as above; the app will use live market data.
