# Sentry Bridge

Sentry Bridge is an **automated trading system** that streams market data from **Alpaca**, runs a **Python strategy brain** (signals, rules, paper or live orders), and supports **pre-market discovery** and **one-command deployment** on **Google Cloud (GCP)**. It is built for **Alpaca paper trading** by default; you can switch to live keys when ready.

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

- **Green Light entry** – Buy only when a 4-point checklist passes: (1) structure/trend, (2) pattern at confluence (technical score, Z/VWAP), (3) momentum (or scalp skip), (4) OFI. Plus `prob_gain` above threshold. News sentiment is used only for the kill switch, not for entry.
- **Exits** – Stop loss (fixed % or ATR-based), take profit at VWAP, optional scale-out 50% at VWAP then trail the rest, breakeven at halfway to VWAP, trailing stop, max hold days, portfolio health check (e.g. close losers before close). Supports **longs and shorts** (shorts: cover = buy).
- **Rules** – Daily cap (stop new buys when daily PnL hits target/soft cap), drawdown halt, kill switch (bad news or sharp return drop), session (regular-hours-only by default).
- **Paper/live trading** – Market or limit day orders on Alpaca (paper by default; live with `TRADE_PAPER=false` and live keys). Positions/orders refreshed every 15s (`POSITIONS_INTERVAL_SEC`). Scale-out: 25% at 1%/2%/3% profit (consumer) and optional 50% at VWAP (strategy). Position size: 5% of equity per trade (`POSITION_SIZE_PCT`).

### Learning and optimization

- **Experience buffer** – Saves a market snapshot on every entry and exit to `data/experience_buffer.jsonl` for later analysis.
- **Strategy optimizer** – RF/XGBoost on the buffer; suggests filter rules and thresholds; proposed rules promoted to active after 24h out-of-sample.
- **Shadow strategy** – Three ghost models (tighter/wide/scalp) for A/B-style comparison; promotion logic to promote a shadow to primary.

### Deployment (GCP)

- **Single Docker stack** – Go engine + Python brain in one `docker compose` setup.
- **GCP VM** – One-command startup: install Docker, clone repo, configure `.env`, run `docker compose up -d --build`. Containers use `restart: unless-stopped`.
- **GitHub Actions** – **Merge/push to main:** builds the image and pushes to ghcr.io only (no deploy). **Manual trigger:** builds and deploys to the VM (Actions → Deploy to GCP VM → Run workflow).

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
   - Paper vs live: use **paper** keys and leave `TRADE_PAPER=true` for sandbox. For live, use **live** API keys and set `TRADE_PAPER=false` (the SDK uses the correct trading endpoint from the `paper` flag).

## How to run

### Run locally with Docker (same as cloud)

One command runs the full stack (Go engine + Python brain) the same way locally and in production. **Prerequisites:** [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) installed and **running** (open the app and wait until the whale icon appears in the menu bar).

1. **Create `.env`** in the project root with:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` (Alpaca)
   - `ACTIVE_SYMBOLS_FILE`, `OPPORTUNITY_ENGINE_ENABLED=true`, `SCREENER_UNIVERSE=lab_12` (scanner runs at start and 7:00 ET with discovery on market days)
   - Do **not** set `BRAIN_CMD` — the compose file sets it for the app container.

2. **From the project root** (either command):
   ```bash
   cd /path/to/sentry-bridge
   docker compose up --build
   ```
   Or: `./run-docker.sh`

   This builds the app image (Go + Python brain) and runs the app. You’ll see Go logs and `[brain]` lines from the Python consumer. Stop with **Ctrl+C**. Run in background with `docker compose up -d --build`.

3. **Stop and remove containers:**
   ```bash
   docker compose down
   ```

**What runs:** The `app` container runs the Go binary and pipes events directly to the Python brain via stdin.

### Deploy on a GCP VM (single-command startup)

The recommended production setup is a **GCP Compute Engine VM** running the Docker stack. Compose uses `restart: unless-stopped`, so containers come back after a VM reboot as long as Docker is enabled.

1. **Create a VM** (e.g. **Ubuntu 22.04** or **Debian**, e2-standard-2 or e2-standard-4 recommended, in a region you prefer).

2. **SSH in and install Docker** (and Compose v2). For **Ubuntu**:
   ```bash
   sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
   sudo chmod a+r /etc/apt/keyrings/docker.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo usermod -aG docker "$USER"
   ```
   For **Debian**, use the same pattern but with `https://download.docker.com/linux/debian` and `$(. /etc/os-release && echo "$VERSION_CODENAME")` in the `echo` line. Log out and back in (or `newgrp docker`) so `docker` runs without `sudo`.

3. **Clone the repo and configure env:**
   ```bash
   git clone <your-repo-url> sentry-bridge && cd sentry-bridge
   cp .env.example .env
   # Edit .env: set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and scanner options (ACTIVE_SYMBOLS_FILE, OPPORTUNITY_ENGINE_ENABLED, SCREENER_UNIVERSE).
   # Do not set BRAIN_CMD — compose sets it for the app container.
   ```

4. **Start the full stack**  
   Run the workflow **manually** once (Actions → Deploy to GCP VM → Run workflow) to pull the image and start the stack—or run `docker compose up -d --build` on the VM (ensure enough disk). Logs: `docker compose logs -f app`.

5. **Optional:** Ensure Docker starts on boot:
   ```bash
   sudo systemctl enable docker
   ```

To stop: `docker compose down`. To update: run the workflow **manually** to deploy, or on the VM run `git pull` then `docker compose pull && docker compose up -d` (with `DOCKER_IMAGE` set to your ghcr.io image).

#### GitHub Actions: build on push, deploy on manual trigger

- **Merge or push to main:** workflow **only builds** the image and pushes to **ghcr.io**. Deploy is **not** run (no SSH to VM).
- **Manual trigger (Actions → Deploy to GCP VM → Run workflow):** workflow **builds**, pushes to ghcr.io, **and deploys** to the VM (SSH, `docker compose pull`, `docker compose up -d`).

One-time setup (see also [docs/DEPLOY_GCP.md](docs/DEPLOY_GCP.md)):

1. **VM and app**  
   Complete the GCP VM steps above (create VM, install Docker, clone repo, configure `.env`). Run `docker compose up -d --build` once on the VM to verify, or wait for the first manual deploy (Run workflow). Note the VM’s external IP.

2. **SSH key for GitHub Actions**  
   On your machine, create a key pair used only for deploys (no passphrase):
   ```bash
   ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key -N ""
   ```
   Add the **public** key (`deploy_key.pub`) to the VM’s `~/.ssh/authorized_keys` (as the user that runs Docker).

3. **GitHub repository secrets**  
   In the repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Add each:
   - **`GCP_VM_HOST`** – VM’s **External IP** from GCP Console → Compute Engine → VM instances (e.g. `34.145.149.188`).
   - **`GCP_VM_USER`** – The Linux user you use to SSH (e.g. `ubuntu` on Ubuntu images, `sunnyakpatel` on Debian; see your SSH prompt).
   - **`GCP_SSH_PRIVATE_KEY`** – On your machine run `cat deploy_key` and paste the **entire** output (including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`).
   - **`GHCR_PAT`** – A Personal Access Token with `read:packages` so the VM can pull from ghcr.io. GitHub → **Settings** (your profile) → **Developer settings** → **Personal access tokens** → generate with `read:packages`.
   - **`GCP_REPO_PATH`** (optional) – Repo path on the VM if not `~/sentry-bridge` (e.g. `/home/sunnyakpatel/sentry-bridge`).

4. **Result**  
   **Push/merge to main** → build + push image only. **Manual Run workflow** → build + push + deploy to VM (SSH, `git reset --hard origin/main`, `docker compose pull`, `docker compose up -d`).

---

### Run without Docker (Go + Python brain on your machine)

From the **project root**:

1. In `.env`: set `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `BRAIN_CMD="python3 python-brain/apps/consumer.py"`.
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

### Test the Go → Python pipeline (news and all events)

To verify that events (including news) flow from Go to the Python brain:

1. **`.env`** must include `BRAIN_CMD=python3 python-brain/apps/consumer.py` (and Alpaca keys, `ACTIVE_SYMBOLS_FILE`, etc.).

2. **Run the stack** (from project root):
   ```bash
   set -a && source .env && set +a && cd go-engine && go run .
   ```
   Or with Docker: `docker compose up --build`. You should see Go logs and `[brain]` lines from the Python consumer. News, trades, quotes flow over stdin to the brain.

3. **Stop:** Ctrl+C (or `docker compose down` if using Docker).

## Logging

All components use structured logging with configurable levels. To stream **app.log** to Google Cloud Logs Explorer, install the Ops Agent on the VM and add a file receiver for `data/app.log`. The VM’s service account needs the **Logs Writer** role (IAM) and the VM must have **access scopes** that allow the Cloud Logging API; see [docs/OPS_AGENT_APP_LOG.md](docs/OPS_AGENT_APP_LOG.md) for steps and troubleshooting.

**Go (slog):**
- **LOG_LEVEL:** `DEBUG` | `INFO` (default) | `WARN` | `ERROR`. Reduces noise (e.g. `DEBUG` for every trade/quote).
- **LOG_FORMAT:** `json` for one-JSON-object-per-line to stderr (for log aggregators); omit for human-readable text.
- Example: `LOG_LEVEL=INFO LOG_FORMAT=json` when deploying.

**Python (brain, executor, strategy):**
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

Set **`BRAIN_CMD`** to pipe events directly to your Python brain process via **stdin**. The Go engine starts the process and writes one NDJSON event per line. Example:

```bash
# .env
BRAIN_CMD=python3 python-brain/apps/consumer.py
```

Run from **project root** so the path resolves:

```bash
cd /path/to/sentry-bridge
set -a && source .env && set +a && cd go-engine && go run .
```

The Python brain (`python-brain/apps/consumer.py`) reads stdin, logs events, and runs the **Green Light strategy** on tape data (trades/quotes) and optionally on news (kill switch only). **Entry:** 4-point checklist (structure, pattern, momentum, OFI) + `prob_gain`; **exits:** stop loss, take profit at VWAP, scale-out 50% at VWAP, trailing ATR, breakeven, trailing stop, max hold days, portfolio health check. Longs and shorts supported. When paper trading is enabled, it places **market or limit** orders on Alpaca (paper or live per `TRADE_PAPER` and API keys) for tickers from the scanner (ACTIVE_SYMBOLS_FILE).

### Paper trading (AI buy/sell)

The brain decides when to buy or sell using:

- **Entry (long only):** Green Light 4-point checklist (structure/trend, pattern at confluence, momentum, OFI) and `prob_gain >= PROB_GAIN_THRESHOLD`. [FinBERT](https://huggingface.co/ProsusAI/finbert) / VADER on news is used only for the **kill switch** (block new buys on bad news), not for entry. Install deps with `python3 -m pip install -r python-brain/requirements.txt`.
- **Exits:** Stop loss (fixed % or ATR), take profit at VWAP, scale-out 25% at 1%/2%/3% (consumer) and optional 50% at VWAP (strategy), trailing ATR above VWAP, breakeven at halfway to VWAP, breakeven/trailing stop, max hold days, portfolio health check (e.g. close losers before market close). **Shorts:** same logic with cover = buy.
- **Rules:** Daily cap (stop new buys when daily PnL hits target), drawdown halt, kill switch (bad news or sharp return), regular session only by default. One order per symbol per 30s (cooldown; `ORDER_COOLDOWN_SEC`).

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

3. **Optional tuning** (defaults from `brain/config.py`; override in `.env` as needed):
   ```bash
   PROB_GAIN_THRESHOLD=0.12        # buy when prob_gain >= this (Green Light)
   STRATEGY_MAX_QTY=12            # max shares per order (default)
   STRATEGY_REGULAR_SESSION_ONLY=true
   DAILY_CAP_ENABLED=true
   DAILY_CAP_PCT=0.5              # daily profit target / soft cap (default 0.5%)
   KILL_SWITCH=false              # set true to disable buys manually
   KILL_SWITCH_SENTIMENT_THRESHOLD=-0.50   # bad news: trigger if headline+summary sentiment <= this
   KILL_SWITCH_RETURN_THRESHOLD=-0.05      # market tanks: trigger if return_1m or return_5m <= -5%
   STOP_LOSS_PCT=1.0              # 1% stop loss (or use ATR-based with USE_ATR_STOP=true)
   USE_LIMIT_ORDERS=true           # limit orders when price available (default)
   ```

   **Kill switch:** When triggered (bad news, sharp negative return, or `KILL_SWITCH=true`), **no new buy** signals are issued; exits (stop loss, TP, etc.) still execute. Triggered when news sentiment ≤ `KILL_SWITCH_SENTIMENT_THRESHOLD` or when 1m/5m return ≤ `KILL_SWITCH_RETURN_THRESHOLD`.

   **Stop loss:** Every positions update (every 15s by default from Alpaca), any position with unrealized PnL ≤ `-STOP_LOSS_PCT`% is closed (market or limit order). Default 1%. ATR-based stops available with `USE_ATR_STOP=true`.

4. **Run** (from project root):
   ```bash
   set -a && source .env && set +a && cd go-engine && go run .
   ```

You should see strategy logs with `action=... qty=... reason=...` and `[executor] BUY/SELL ... -> order id=...` when the strategy triggers. Orders are **market or limit, day** on your Alpaca **paper** account (or live if `TRADE_PAPER=false` and live keys). Set `TRADE_PAPER=false` to log decisions only and not place orders.

**Daily cap:** When daily PnL reaches the target/soft cap (`DAILY_CAP_PCT`, default **0.5%**), the bot stops **new buys** for the day (exits still allowed). Set `DAILY_CAP_ENABLED=false` to disable.


### Python brain: modular design

The Python brain is split so you can add or change business rules without rewriting the core:

| Layer | Role |
|-------|------|
| **config.py** | All thresholds and flags from env (e.g. `PROB_GAIN_THRESHOLD`, `DAILY_CAP_PCT`, `STOP_LOSS_PCT`). |
| **signals/** | **news_sentiment** = FinBERT/VADER on news (kill switch). **technical** = RSI, MACD, patterns for Green Light. **microstructure** = VWAP, ATR, OFI. |
| **rules/** | **daily_cap** = block new buys when daily PnL hits target. **drawdown** = block new buys when drawdown from peak exceeds threshold. |
| **strategy.py** | Green Light 4-point entry + prob_gain; exits (stop, TP at VWAP, scale-out, trailing, breakeven, max hold, health check). Long and short. |
| **apps/consumer.py** | Stdin entry: reads events, updates state, runs strategy + executor; scale-out 25% at 1%/2%/3%. |
| **apps/test_paper_order.py** | One-off: submit 1 paper BUY to verify Alpaca API. |
| **execution/executor.py** | Places orders on Alpaca (market or limit); exposes `get_account_equity()` for daily cap. |

**Adding a business rule:** Add a new module under `brain/rules/` (e.g. `drawdown.py` already exists) that exports a check like `is_drawdown_halt() -> bool`. In `strategy.decide()`, call it in the block-buy section and return `Decision("hold", ..., "drawdown_halt")`. Register in `rules/__init__.py`. No need to change signals or consumer.

**Go ↔ Python transport:** The Go engine streams NDJSON to the brain over **stdin** (pipe). The brain’s entry point is “receive events, update state, run strategy, optionally place order.”

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

When you’re ready for live trading:

1. Create a **live** Alpaca account and get **live** API keys (separate from paper).
2. In `.env`, set:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` to your **live** keys
   - `TRADE_PAPER=false` (or `APCA_PAPER=false`) so the SDK uses the live trading endpoint (`https://api.alpaca.markets`).
   - Optionally `ALPACA_DATA_BASE_URL` for the data API if you override it.
3. Run the same commands as above; the app will place live orders. See **python-brain/README.md** (Live trading) for PDT notes if your account is under $25k.
