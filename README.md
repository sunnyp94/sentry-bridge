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
   - `ALPACA_DATA_BASE_URL` – leave as `https://data.sandbox.alpaca.markets` for sandbox

## How to run

From the **project root**:

```bash
# Load .env and run the Go engine
set -a && source .env && set +a && cd go-engine && go run .
```

Or from the **go-engine** directory (after setting env vars):

```bash
cd go-engine
export APCA_API_KEY_ID=your_key_id
export APCA_API_SECRET_KEY=your_secret_key
go run .
```

To use a custom ticker list:

```bash
export TICKERS=AAPL,TSLA,NVDA,META
# then run as above
```

## What you’ll see

The program prints to the console, **per stock**:

- **News** – headlines and timestamps for that symbol  
- **Price** – latest trade/quote or daily close  
- **Volatility** – 30-day annualized volatility (from daily bars)

Example:

```
═══════════════════════════════════════════════════════════
  AAPL
═══════════════════════════════════════════════════════════
  News: 2 article(s)
    • Apple Leader in Phone Sales...
      2021-12-31T11:08:42Z | benzinga

  Price: $178.25

  Volatility (30d annualized): 22.45%
```

## Switching to production (later)

When you’re ready for live data:

1. Create a **live** Alpaca account and get live API keys.  
2. In `.env`, set:
   - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` to your **live** keys  
   - `ALPACA_DATA_BASE_URL=https://data.alpaca.markets`  
3. Run the same commands as above; the app will use live market data.
