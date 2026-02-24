# Sentry Bridge

Sentry Bridge is an **automated trading system** that streams market data from **Alpaca**, runs a **Python strategy brain** (signals, rules, paper or live orders), and supports **pre-market discovery**, **backtesting**, and **one-command deployment** on **Google Cloud (GCP)**. It is built for **Alpaca paper trading** by default; you can switch to live keys when ready.

## Features

### Market data (Alpaca)

- **Real-time trades and quotes** – WebSocket to Alpaca; **SIP** (full US consolidated tape) by default for accurate volume and NBBO; set `ALPACA_DATA_FEED=iex` for the free tier.
- **News** – WebSocket stream of headlines and summaries (used for sentiment).
- **Volatility** – 30-day annualized volatility from daily bars (REST, refreshed every 5 minutes).
- Optional **one-shot REST mode** (no WebSockets) via `STREAM=false`.

### Discovery and opportunity engine

- **Pre-market discovery** (7:00–9:30 ET) – On full market days, a screener runs every 5 minutes and writes a **priority watchlist** to `ACTIVE_SYMBOLS_FILE`. At 9:30 ET the Go engine starts with that list. Enable with `DISCOVERY_ENABLED=true` and `ACTIVE_SYMBOLS_FILE`.
- **One-shot scanner** – Alternatively, a Z-score and volume-spike screener can run once at container start or on a schedule (no discovery window).

### Strategy brain (Python)

- **Composite score** – News sentiment (FinBERT/VADER), momentum (1m/5m returns), optional technicals (RSI, MACD, patterns). Consensus: require N-of-3 sources positive before buy.
- **Rules** – Daily cap (stop new buys when daily PnL ≥ 0.2%), drawdown guard, kill switch (bad news or sharp drop), stop loss, session (regular-hours-only by default; post-close holds).
- **Paper trading** – Market day orders on Alpaca paper account; positions/orders refreshed every 15s. Scale-out (sell 25% at 1%/2%/3%) and conviction-based sizing from recent outcomes.

### Learning and optimization

- **Experience buffer** – Saves a market snapshot on every entry and exit to `data/experience_buffer.jsonl` for later analysis.
- **Strategy optimizer** – RF/XGBoost on the buffer; suggests filter rules and thresholds.
- **Shadow strategy** – Three ghost models (tighter/wide/scalp) for A/B-style comparison; promotion logic to promote a shadow to primary.
- **Conviction** – Position size scales with recent win/loss by setup type.

### Deployment (GCP)

- **Single Docker stack** – Go engine + **Redis** + Python brain in one `docker compose` setup.
- **Redis** – Runs **locally in the same Docker Compose** on the GCP VM for **low latency** (no external Redis required for production).
- **GCP VM** – One-command startup: install Docker, clone repo, configure `.env`, run `docker compose up -d --build`. Containers use `restart: unless-stopped`.
- **Deploy on every merge to main** – GitHub Actions workflow SSHs to the VM and runs `git fetch` / `git reset --hard origin/main` and `docker compose up -d --build`.

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

   - **Tickers:** Come from the scanner. Set `ACTIVE_SYMBOLS_FILE`, `OPPORTUNITY_ENGINE_ENABLED=true`, and `SCREENER_UNIVERSE` (e.g. `lab_12`, `sp400`, `nasdaq100`). With discovery enabled, the scanner runs 7:00–9:30 ET on full market days; otherwise it runs once at container start.  
   - `ALPACA_DATA_BASE_URL` – REST data API (default `https://data.alpaca.markets`)  
   - `STREAM` – set to `false` or `0` for one-shot REST only; default is streaming mode  
   - `REDIS_URL` – Set by Docker Compose for the app container (e.g. `redis://redis:6379`). Do not set in `.env` when using compose; the stack runs Redis locally for low latency.  
   - `REDIS_STREAM` – stream name (default `market:updates`)  
   - `APCA_API_BASE_URL` – Alpaca Trading API for positions/orders (default `https://paper-api.alpaca.markets`)

## How to run

### Run locally with Docker (same as cloud)

One command runs the full stack (Go + Redis + Python brain) the same way locally and in production. **Prerequisites:** [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) installed and **running** (open the app and wait until the whale icon appears in the menu bar).

1. **Create `.env`** in the project root with:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` (Alpaca)
   - `ACTIVE_SYMBOLS_FILE`, `OPPORTUNITY_ENGINE_ENABLED=true`, `SCREENER_UNIVERSE=lab_12` (scanner runs at start and 7:00 ET with discovery on market days)
   - Do **not** set `REDIS_URL` or `BRAIN_CMD` — the compose file sets them for the app container.

2. **From the project root** (either command):
   ```bash
   cd /path/to/sentry-bridge
   docker compose up --build
   ```
   Or: `./run-docker.sh`

   This builds the app image (Go + Python brain), starts Redis, then runs the app. You’ll see Go logs, Redis stream connection, and `[brain]` lines from the Python consumer. Stop with **Ctrl+C**. Run in background with `docker compose up -d --build`.

3. **Stop and remove containers:**
   ```bash
   docker compose down
   ```

**What runs:** The `app` container runs the Go binary; Go connects to the `redis` service (in the same Compose stack) and pipes events to the Python brain. **Redis runs locally** in the stack for low latency; no external Redis is required.

### Deploy on a GCP VM (single-command startup)

The recommended production setup is a **GCP Compute Engine VM** running the full Docker stack. **Redis runs in the same Docker Compose** on the VM (no separate Redis Cloud or external Redis), so event flow stays on the same machine for **faster latency**. Compose uses `restart: unless-stopped`, so containers come back after a VM reboot as long as Docker is enabled.

1. **Create a VM** (e.g. **Ubuntu 22.04**, e2-medium or larger, in a region you prefer).

2. **SSH in and install Docker** (and Compose v2):
   ```bash
   sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
   sudo chmod a+r /etc/apt/keyrings/docker.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo usermod -aG docker "$USER"
   ```
   Log out and back in (or `newgrp docker`) so `docker` runs without `sudo`.

3. **Clone the repo and configure env:**
   ```bash
   git clone <your-repo-url> sentry-bridge && cd sentry-bridge
   cp .env.example .env
   # Edit .env: set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and scanner options (ACTIVE_SYMBOLS_FILE, OPPORTUNITY_ENGINE_ENABLED, SCREENER_UNIVERSE).
   # Do not set REDIS_URL or BRAIN_CMD — compose sets them for the app container.
   ```

4. **Start the full stack (single command):**
   ```bash
   docker compose up -d --build
   ```
   This builds the app image (Go + Python brain), starts Redis in the same stack, then the app. Redis runs locally on the VM for low latency. The entrypoint runs the scanner if `ACTIVE_SYMBOLS_FILE` is set, then starts the Go engine; Go starts the Python brain via `BRAIN_CMD`. Logs: `docker compose logs -f app`.

5. **Optional:** Ensure Docker starts on boot (Ubuntu often does this by default):
   ```bash
   sudo systemctl enable docker
   ```

To stop: `docker compose down`. To update: `git pull && docker compose up -d --build`.

#### Deploy on every merge to main

The workflow **builds the app image in GitHub Actions**, pushes it to **GitHub Container Registry (ghcr.io)**, then SSHs to the VM and runs **pull + up** (no build on the VM, so the VM needs less disk and never runs out of space during deploy). One-time setup:

1. **VM and app**  
   Complete the GCP VM steps above (create VM, install Docker, clone repo, configure `.env`). You can run `docker compose up -d --build` once locally on the VM to verify, or wait for the first automated deploy. Note the VM’s external IP.

2. **SSH key for GitHub Actions**  
   On your machine, create a key pair used only for deploys (no passphrase):
   ```bash
   ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key -N ""
   ```
   Add the **public** key (`deploy_key.pub`) to the VM’s `~/.ssh/authorized_keys` (as the user that runs Docker).

3. **GitHub repository secrets**  
   In the repo: **Settings → Secrets and variables → Actions**. Add:
   - `GCP_VM_HOST` – VM’s external IP (e.g. `34.123.45.67`).
   - `GCP_VM_USER` – SSH user (e.g. `ubuntu` or `sunnyakpatel`).
   - `GCP_SSH_PRIVATE_KEY` – Full contents of the **private** key file (`deploy_key`).
   - `GHCR_PAT` – A **Personal Access Token** with `read:packages` so the VM can pull the image from ghcr.io. Create under GitHub **Settings → Developer settings → Personal access tokens**; give it `read:packages` and no other scopes. Use a fine-grained token with read access to the repo’s packages, or a classic token with `read:packages`.
   - `GCP_REPO_PATH` (optional) – Path to the repo on the VM; default is `~/sentry-bridge`.

4. **Result**  
   Every push (or merge) to `main`: (1) workflow builds the Docker image and pushes to `ghcr.io/<owner>/<repo>/sentry-bridge-app:latest`, (2) SSHs to the VM, updates the repo to `origin/main`, logs in to ghcr.io with `GHCR_PAT`, runs `docker compose pull` and `docker compose up -d`. You can also run the workflow manually from **Actions** → **Deploy to GCP VM** → **Run workflow**.

---

### Run without Docker (Go + Python brain on your machine)

From the **project root**:

1. In `.env`: set `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `BRAIN_CMD="python3 python-brain/apps/consumer.py"`. Omit or comment out `REDIS_URL` unless you run Redis via Homebrew.
2. Run:
   ```bash
   set -a && source .env && set +a && cd go-engine && go run .
   ```

Make sure `.env` contains your real Alpaca keys and scanner config (`ACTIVE_SYMBOLS_FILE`, `OPPORTUNITY_ENGINE_ENABLED=true`, `SCREENER_UNIVERSE`) so the engine gets tickers from the scanner.

## How to test

1. **From project root**, load env and run the Go engine (with optional brain):

   ```bash
   cd /path/to/sentry-bridge
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
   cd /path/to/sentry-bridge
   echo '{"type":"trade","ts":"2026-02-22T12:00:00Z","payload":{"symbol":"AAPL","price":178.5}}' | python3 python-brain/apps/consumer.py
   ```
   You should see one `[brain] TRADE AAPL ...` line.

5. **Test end-to-end with synthetic data (no market hours):** When the market is closed (e.g. Sunday evening), use the replay script to run the full brain pipeline (composite → strategy → optional paper order):
   ```bash
   cd /path/to/sentry-bridge
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
   cd /path/to/sentry-bridge
   set -a && source .env && set +a && cd go-engine && go run .
   ```
   You should see `Redis stream: market:updates` and Go logs. News, trades, quotes, etc. are written to the stream.

4. **Terminal 2 — Python (reads from Redis):**
   ```bash
   cd /path/to/sentry-bridge/python-brain
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

- **Price** – WebSocket to Alpaca stock stream (`v2/sip` by default, or `v2/iex` if `ALPACA_DATA_FEED=iex`): real-time trades and quotes; each update is printed (throttled to 1 per symbol per second).
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

The Python brain (`python-brain/apps/consumer.py`) reads stdin, logs events, and runs an **AI-driven strategy** on each news item: sentiment (VADER, or optional FinBERT) + probability of gain from returns/volatility → **buy / sell / hold**. When paper trading is enabled, it **places market orders** on Alpaca (paper account) for the tickers from the scanner (ACTIVE_SYMBOLS_FILE).

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
   ACTIVE_SYMBOLS_FILE=data/active_symbols.txt
   OPPORTUNITY_ENGINE_ENABLED=true
   SCREENER_UNIVERSE=lab_12
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

## Redis

On **GCP** (and in the default Docker setup), **Redis runs in the same Compose stack** as the app for low latency. The app also pipes events to the brain via stdin. Redis is used for the stream so you can replay, run a second consumer, or inspect events. When running **without Docker** (e.g. locally with `go run`), Redis is optional: the brain can receive data via stdin only; use Redis for replay, dashboards, or a second consumer.

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

## Optional: external Redis (e.g. Redis Cloud)

**Recommended production setup:** Run the full stack (Go + **Redis** + Python brain) on a **GCP VM** with Redis in the same Docker Compose for **low latency**. No external Redis is required.

If you prefer **hosted Redis** (e.g. Redis Cloud) instead of the local container:

1. Create a Redis Cloud (or other) database and get the URL (e.g. `rediss://default:<password>@<host>:<port>`). Choose a region close to your app.
2. Run only the **app** service (no local `redis` in compose): set `REDIS_URL` to that URL and provide Alpaca keys, `ACTIVE_SYMBOLS_FILE`, and `BRAIN_CMD` as needed. Store secrets in your platform’s secret store (e.g. GCP Secret Manager).
3. **Summary** – **GCP VM (recommended):** `docker compose up -d --build` runs Redis + app on the same VM. **With external Redis:** Use a compose override or run the app container only and set `REDIS_URL` to your hosted Redis.

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
