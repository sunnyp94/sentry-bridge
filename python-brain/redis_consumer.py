#!/usr/bin/env python3
"""
Read events from the Redis stream (Go → Redis → this script).
Use this to test the pipeline: Go writes to Redis, this script reads and logs.

  REDIS_URL=redis://localhost:6379 REDIS_STREAM=market:updates python3 redis_consumer.py

Requires: pip install redis. Logging: LOG_LEVEL (default INFO), same as brain (log_config).
"""
import json
import logging
import os
import sys
from datetime import datetime

log = logging.getLogger("redis_consumer")

try:
    import redis
except ImportError:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log.error("Install redis: python3 -m pip install redis  (or: pip3 install redis)")
    sys.exit(1)


def format_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return ts


def log_event(ev: dict) -> None:
    typ = ev.get("type", "?")
    ts = format_ts(ev.get("ts", ""))
    payload = ev.get("payload") or {}

    if typ == "news":
        symbols = ",".join(payload.get("symbols") or [])
        headline = (payload.get("headline") or "")[:80]
        log.info("NEWS symbols=%s headline=%s ts=%s", symbols, headline, ts)
    elif typ == "trade":
        price = payload.get("price") or 0
        log.info("TRADE symbol=%s price=%.2f ts=%s", payload.get("symbol"), price, ts)
    elif typ == "quote":
        mid = payload.get("mid") or 0
        log.info("QUOTE symbol=%s mid=%.2f ts=%s", payload.get("symbol"), mid, ts)
    elif typ == "volatility":
        vol = (payload.get("annualized_vol_30d") or 0) * 100
        log.info("VOL symbol=%s annualized_30d=%.2f%% ts=%s", payload.get("symbol"), vol, ts)
    elif typ in ("positions", "orders"):
        count = len(payload.get(typ) or [])
        log.info("%s count=%d ts=%s", typ.upper(), count, ts)
    else:
        log.info("event type=%s payload=%s ts=%s", typ, json.dumps(payload)[:60], ts)


def main() -> None:
    try:
        from log_config import init as init_logging
        init_logging()
    except ImportError:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    url = os.environ.get("REDIS_URL") or os.environ.get("REDIS_ADDR") or "redis://localhost:6379"
    stream = os.environ.get("REDIS_STREAM", "market:updates")
    log.info("Connecting to %s, stream=%s (BLOCK). Ctrl+C to stop.", url, stream)

    r = redis.from_url(url, decode_responses=True)
    last_id = "$"  # only new messages

    while True:
        try:
            streams = r.xread(streams={stream: last_id}, block=5000, count=10)
        except redis.ConnectionError as e:
            log.exception("Connection error: %s", e)
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
                log_event(ev)


if __name__ == "__main__":
    main()
