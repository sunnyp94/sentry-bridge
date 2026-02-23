#!/usr/bin/env python3
"""
E2E replay: emit synthetic NDJSON events so you can test the full brain pipeline
without live market (e.g. Sunday 6pm ET when there are no trades/news).

Prints one event per line to stdout. Pipe into the stdin consumer:

  # From repo root (source .env first if you want Alpaca keys for paper order)
  python3 python-brain/apps/replay_e2e.py | python3 python-brain/apps/consumer.py

  # Strategy-only (no orders): ensure TRADE_PAPER=false or omit Alpaca keys
  TRADE_PAPER=false python3 python-brain/apps/replay_e2e.py | python3 python-brain/apps/consumer.py

Event sequence: volatility (AAPL) → trade (AAPL, with returns) → news (positive headline for AAPL).
The brain will run composite (news + momentum), consensus, and decide() on the news event.
"""
import json
import sys
from datetime import datetime, timezone

# Optional: use TICKERS from env so replay matches your config (default AAPL for minimal test)
def _tickers():
    import os
    t = os.environ.get("TICKERS", "AAPL")  # TICKERS optional for replay; default minimal
    return [s.strip() for s in t.split(",") if s.strip()]


def emit(ev: dict) -> None:
    print(json.dumps(ev), flush=True)


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tickers = _tickers()
    symbol = tickers[0] if tickers else "AAPL"

    # 1) Volatility so the symbol has market context
    emit({
        "type": "volatility",
        "ts": ts,
        "payload": {"symbol": symbol, "annualized_vol_30d": 0.22},
    })

    # 2) Trade with small positive returns (momentum will be slightly positive)
    emit({
        "type": "trade",
        "ts": ts,
        "payload": {
            "symbol": symbol,
            "price": 178.50,
            "size": 100,
            "volume_1m": 50000,
            "volume_5m": 200000,
            "return_1m": 0.002,
            "return_5m": 0.005,
            "session": "regular",
        },
    })

    # 3) News with positive headline/summary so sentiment triggers strategy
    emit({
        "type": "news",
        "ts": ts,
        "payload": {
            "id": "replay-e2e-1",
            "headline": "Strong earnings beat and raised guidance for " + symbol,
            "summary": "Company reported better than expected results and increased full year outlook. Analysts are bullish.",
            "symbols": tickers[:3],
            "source": "replay_e2e",
        },
    })

    # 4) Positions (optional) so daily cap and stop-loss path are exercised
    emit({
        "type": "positions",
        "ts": ts,
        "payload": {"positions": []},
    })

    # 5) Second news for another symbol (optional)
    if len(tickers) > 1:
        ts2 = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        emit({
            "type": "news",
            "ts": ts2,
            "payload": {
                "id": "replay-e2e-2",
                "headline": tickers[1] + " stock gains on sector rotation",
                "summary": "Positive momentum continues as investors favor tech.",
                "symbols": [tickers[1]],
                "source": "replay_e2e",
            },
        })


if __name__ == "__main__":
    main()
