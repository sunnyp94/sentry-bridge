#!/usr/bin/env python3
"""
One-off test: submit a single paper BUY (1 share AAPL) to verify Alpaca paper API.
  From repo root: set -a && source .env && set +a && cd python-brain && python3 apps/test_paper_order.py
  Or from python-brain: python3 apps/test_paper_order.py (with .env loaded).
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import os

if __name__ == "__main__":
    from brain.strategy import Decision
    from brain.executor import place_order

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
