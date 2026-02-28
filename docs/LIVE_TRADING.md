# Enabling live trading

Follow these steps to switch from **paper** to **live** trading. The app will only place real orders when all conditions below are set.

---

## 1. Get live API keys

- In the [Alpaca dashboard](https://app.alpaca.markets), open your **Live** account (not Paper).
- Create an API key pair for **Live** (Key ID + Secret).  
- **Do not** use your paper keys for live trading.

---

## 2. Update `.env` on your machine or VM

Edit your `.env` and apply **all** of the following.

### Replace keys with live keys

```env
APCA_API_KEY_ID=<your_live_key_id>
APCA_API_SECRET_KEY=<your_live_secret_key>
```

### Switch to live trading

```env
TRADE_PAPER=false
LIVE_TRADING_ENABLED=true
```

Both must be set. If `TRADE_PAPER=false` and `LIVE_TRADING_ENABLED` is not set, the app will **not** place orders (log-only mode).

### Point the Go engine at the live trading API

```env
APCA_API_BASE_URL=https://api.alpaca.markets
```

The Go engine uses this URL for positions and orders. For paper it defaults to `https://paper-api.alpaca.markets`; for live you must set the URL above.

---

## 3. Leave everything else as-is (optional)

You do **not** need to change:

- `ALPACA_DATA_FEED` – Data/news API is the same for paper and live.
- `ALPACA_DATA_BASE_URL` – Omit or keep default; data endpoint is shared.
- `SCREENER_UNIVERSE`, `ACTIVE_SYMBOLS_FILE`, `DISCOVERY_TOP_N` – Same for paper and live.

---

## 4. Restart the app

So the new env is loaded:

**Local (Docker):**

```bash
docker compose down
docker compose up -d --build
```

**VM (after editing `.env` on the VM):**

```bash
cd ~/sentry-bridge   # or your repo path
docker compose down
docker compose up -d --force-recreate
```

---

## Checklist

| Step | What to set |
|------|-------------|
| 1 | Use **live** Alpaca API keys (not paper). |
| 2 | `TRADE_PAPER=false` |
| 3 | `LIVE_TRADING_ENABLED=true` |
| 4 | `APCA_API_BASE_URL=https://api.alpaca.markets` |
| 5 | Restart containers so `.env` is reloaded. |

---

## Example `.env` for live

Minimal live section (rest of your `.env` can stay the same):

```env
APCA_API_KEY_ID=<live_key_id>
APCA_API_SECRET_KEY=<live_secret_key>
ALPACA_DATA_FEED=sip
SCREENER_UNIVERSE=r2000_sp500_nasdaq100
ACTIVE_SYMBOLS_FILE=data/active_symbols.txt

TRADE_PAPER=false
LIVE_TRADING_ENABLED=true
APCA_API_BASE_URL=https://api.alpaca.markets

DISCOVERY_TOP_N=10
```

---

## PDT (Pattern Day Trader) notice

If your account is under $25k equity, US rules may limit day trades (e.g. 3 in 5 business days). The app can open and close positions the same day. See **python-brain/README.md** (Live trading) for details.
