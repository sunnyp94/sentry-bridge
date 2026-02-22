#!/usr/bin/env python3
"""
One-off test: submit a single paper BUY (1 share AAPL) to verify Alpaca paper API.

Install deps first (from repo root or python-brain):
  python3 -m pip install -r requirements.txt
  # or:  python3 -m pip install alpaca-py

Then run with .env loaded (from repo root):
  set -a && source .env && set +a && cd python-brain && python3 test_paper_order.py

When market is closed (e.g. Sunday), Alpaca usually accepts the order and holds it for next open (e.g. Monday 9:30am ET).
"""
import os
import sys

if __name__ == "__main__":
    from strategy import Decision
    from executor import place_order

    if not os.environ.get("APCA_API_KEY_ID") and not os.environ.get("ALPACA_API_KEY_ID"):
        print("Missing APCA_API_KEY_ID (source .env)", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("APCA_API_SECRET_KEY") and not os.environ.get("ALPACA_API_SECRET_KEY"):
        print("Missing APCA_API_SECRET_KEY (source .env)", file=sys.stderr)
        sys.exit(1)

    print("Submitting paper BUY 1 AAPL (paper-api.alpaca.markets)...", file=sys.stderr)
    d = Decision("buy", "AAPL", 1, "test_paper_order")
    ok = place_order(d)
    print("Result: OK" if ok else "Result: FAILED", file=sys.stderr)
    sys.exit(0 if ok else 1)
