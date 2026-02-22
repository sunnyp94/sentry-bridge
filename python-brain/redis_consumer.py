#!/usr/bin/env python3
"""
Read events from the Redis stream (Go → Redis → this script).
Use this to test the pipeline: Go writes to Redis, this script reads and logs.

  REDIS_URL=redis://localhost:6379 REDIS_STREAM=market:updates python3 redis_consumer.py

Requires: pip install redis
"""
import json
import os
import sys
from datetime import datetime

try:
    import redis
except ImportError:
    print("Install redis: python3 -m pip install redis  (or: pip3 install redis)", file=sys.stderr)
    sys.exit(1)


def format_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return ts


def print_event(ev: dict) -> None:
    typ = ev.get("type", "?")
    ts = format_ts(ev.get("ts", ""))
    payload = ev.get("payload") or {}

    if typ == "news":
        symbols = ",".join(payload.get("symbols") or [])
        headline = (payload.get("headline") or "")[:80]
        print(f"[redis] NEWS   {symbols} | {headline} [{ts}]")
    elif typ == "trade":
        price = payload.get("price") or 0
        print(f"[redis] TRADE  {payload.get('symbol')} ${price:.2f} [{ts}]")
    elif typ == "quote":
        mid = payload.get("mid") or 0
        print(f"[redis] QUOTE  {payload.get('symbol')} mid={mid:.2f} [{ts}]")
    elif typ == "volatility":
        vol = payload.get("annualized_vol_30d") or 0
        print(f"[redis] VOL    {payload.get('symbol')} {vol*100:.2f}% [{ts}]")
    elif typ in ("positions", "orders"):
        print(f"[redis] {typ.upper()} count={len(payload.get(typ) or [])} [{ts}]")
    else:
        print(f"[redis] {typ} {json.dumps(payload)[:60]} [{ts}]")


def main() -> None:
    url = os.environ.get("REDIS_URL") or os.environ.get("REDIS_ADDR") or "redis://localhost:6379"
    stream = os.environ.get("REDIS_STREAM", "market:updates")

    print(f"[redis] Connecting to {url}, reading stream {stream} (BLOCK). Ctrl+C to stop.", file=sys.stderr)

    r = redis.from_url(url, decode_responses=True)
    last_id = "$"  # only new messages

    while True:
        try:
            streams = r.xread(streams={stream: last_id}, block=5000, count=10)
        except redis.ConnectionError as e:
            print(f"[redis] Connection error: {e}", file=sys.stderr)
            sys.exit(1)
        if not streams:
            continue
        for sname, messages in streams:
            for msg_id, fields in messages:
                last_id = msg_id
                ev = {
                    "type": fields.get("type", "?"),
                    "ts": fields.get("ts", ""),
                    "payload": {},
                }
                payload_str = fields.get("payload")
                if payload_str:
                    try:
                        ev["payload"] = json.loads(payload_str)
                    except json.JSONDecodeError:
                        pass
                print_event(ev)


if __name__ == "__main__":
    main()
