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

   - `TICKERS` – comma-separated symbols (default: `AAPL,MSFT,GOOGL,AMZN,TSLA`)  
   - `ALPACA_DATA_BASE_URL` – REST data API (default `https://data.alpaca.markets`)  
   - `STREAM` – set to `false` or `0` for one-shot REST only; default is streaming mode  
   - `REDIS_URL` – Redis address for Python brain (e.g. `redis://localhost:6379`); if unset, events are not published  
   - `REDIS_STREAM` – stream name (default `market:updates`)  
   - `APCA_API_BASE_URL` – Alpaca Trading API for positions/orders (default `https://paper-api.alpaca.markets`)

## How to run

### Run full stack with Docker (Go + Redis + Python brain)

One command runs everything. **Prerequisites:** [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) installed and **running** (open the app and wait until the whale icon appears in the menu bar).

1. **Create `.env`** in the project root with:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` (Alpaca)
   - `TICKERS=AAPL,MSFT,GOOGL,AMZN,TSLA` (optional)
   - Do **not** set `REDIS_URL` or `BRAIN_CMD` — the compose file sets them for the app container.

2. **From the project root:**
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   docker compose up --build
   ```

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
  - `BRAIN_CMD="python3 /app/python-brain/consumer.py"`
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
BRAIN_CMD="python3 /app/python-brain/consumer.py"
```

Then run the app container with that env; point it at Redis Cloud instead of a local Redis.

---

### Run without Docker (Go + Python brain on your machine)

From the **project root**:

1. In `.env`: set `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `BRAIN_CMD="python3 python-brain/consumer.py"`. Omit or comment out `REDIS_URL` unless you run Redis via Homebrew.
2. Run:
   ```bash
   set -a && source .env && set +a && go run ./go-engine
   ```

Make sure `.env` contains your real Alpaca keys. Use `TICKERS=AAPL,TSLA,NVDA,META` to change symbols.

## How to test

1. **From project root**, load env and run the Go engine (with optional brain):

   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   set -a && source .env && set +a && go run ./go-engine
   ```

2. **With the Python brain:** add to `.env`:
   ```bash
   BRAIN_CMD=python3 python-brain/consumer.py
   ```
   Then run the same command above. You should see:
   - Go: `Brain: piping to python3 python-brain/consumer.py`
   - Go: Alpaca stream lines (`[price]`, `[quote]`, `[news]`, volatility block)
   - Python: `[brain] TRADE ...`, `[brain] QUOTE ...`, `[brain] NEWS ...`, etc., as events are piped to the consumer

3. **Without the brain:** leave `BRAIN_CMD` unset or comment it out. Only the Go console output will appear.

4. **Test the Python consumer alone** (no Go): pipe a few JSON lines into it to confirm it parses and prints:
   ```bash
   cd /Users/sunnypatel/Projects/sentry-bridge
   echo '{"type":"trade","ts":"2026-02-22T12:00:00Z","payload":{"symbol":"AAPL","price":178.5}}' | python3 python-brain/consumer.py
   ```
   You should see one `[brain] TRADE AAPL ...` line.

5. **Stop:** press **Ctrl+C** in the terminal where `go run ./go-engine` is running.

**Note:** During US market hours (9:30am–4pm ET, weekdays) you’ll get live trades/quotes. Outside those hours you’ll mainly see news (if any), volatility on startup, and positions/orders every 30s.

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
BRAIN_CMD=python3 python-brain/consumer.py
```

Run from **project root** so the path resolves:

```bash
cd /path/to/sentry-bridge
set -a && source .env && set +a && go run ./go-engine
```

The Python script in `python-brain/consumer.py` reads stdin and prints each event (trade, quote, news, volatility, positions, orders). Replace that with your AI logic when ready.

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
