#!/usr/bin/env python3
"""
Brain consumer: reads NDJSON events from stdin (piped from Go engine).
Run by the Go engine when BRAIN_CMD is set, e.g.:
  BRAIN_CMD="python3 python-brain/consumer.py"
Run from project root so the path resolves.
"""
import json
import sys
from datetime import datetime


def format_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return ts


def print_event(ev: dict) -> None:
    typ = ev.get("type", "?")
    ts = format_ts(ev.get("ts", ""))
    payload = ev.get("payload") or {}

    if typ == "trade":
        print(f"[brain] TRADE  {payload.get('symbol')} ${payload.get('price', 0):.2f} "
              f"size={payload.get('size')} vol_1m={payload.get('volume_1m')} "
              f"ret_1m={payload.get('return_1m', 0):.4f} session={payload.get('session')} [{ts}]")
    elif typ == "quote":
        print(f"[brain] QUOTE  {payload.get('symbol')} bid={payload.get('bid'):.2f} ask={payload.get('ask'):.2f} "
              f"mid={payload.get('mid'):.2f} bid_sz={payload.get('bid_size')} ask_sz={payload.get('ask_size')} [{ts}]")
    elif typ == "news":
        symbols = ",".join(payload.get("symbols") or [])
        print(f"[brain] NEWS   {symbols} | {payload.get('headline', '')[:60]}... [{ts}]")
    elif typ == "volatility":
        print(f"[brain] VOL    {payload.get('symbol')} annualized_30d={payload.get('annualized_vol_30d', 0)*100:.2f}% [{ts}]")
    elif typ == "positions":
        positions = payload.get("positions") or []
        print(f"[brain] POSITIONS count={len(positions)} [{ts}]")
        for p in positions[:5]:
            print(f"         {p.get('symbol')} {p.get('side')} qty={p.get('qty')} mv={p.get('market_value')}")
    elif typ == "orders":
        orders = payload.get("orders") or []
        print(f"[brain] ORDERS count={len(orders)} [{ts}]")
        for o in orders[:5]:
            print(f"         {o.get('symbol')} {o.get('side')} qty={o.get('qty')} status={o.get('status')}")
    else:
        print(f"[brain] {typ} {json.dumps(payload)[:80]} [{ts}]")


def main() -> None:
    print("[brain] reading from stdin (NDJSON)...", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            print_event(ev)
        except json.JSONDecodeError as e:
            print(f"[brain] invalid JSON: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[brain] error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
