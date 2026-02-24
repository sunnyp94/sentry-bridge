#!/usr/bin/env python3
"""
Pre-market discovery: run from container start until market open (9:30 ET).
- From 7:00 ET: run discovery every 5 min, write Priority Watchlist to ACTIVE_SYMBOLS_FILE.
- At 9:30 ET: run discovery once (handoff), then exit so entrypoint can start the Go engine.
- If already at or after 9:30 when started: run discovery once and exit (Go will read the file).
All times Eastern. Run this once; at 9:30 the engine starts and watches the hand-picked list.
"""
import os
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Load .env if present (e.g. /app/.env in Docker)
_env_file = _root.parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from brain.discovery import run_discovery, _parse_et_time
from brain import config as brain_config
from brain.market_calendar import is_full_trading_day
from brain.log_config import init as init_logging


def _read_watchlist(out_path: str) -> list:
    """Return list of symbols from the handoff file (for logging)."""
    p = Path(out_path)
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _verify_handoff_file(out_path: str) -> None:
    """Ensure handoff file exists and has at least one symbol so Go doesn't start with no tickers."""
    lines = _read_watchlist(out_path)
    if not lines:
        raise SystemExit("[discovery_until_open] handoff file missing or empty: %s" % out_path)


def main() -> int:
    init_logging()
    if not ZoneInfo:
        print("run_discovery_until_open: zoneinfo required for ET schedule", file=sys.stderr, flush=True)
        return 1
    et = ZoneInfo("America/New_York")
    out_path = getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
    if not out_path:
        print("run_discovery_until_open: set ACTIVE_SYMBOLS_FILE", file=sys.stderr, flush=True)
        return 1
    start_et = _parse_et_time(getattr(brain_config, "DISCOVERY_START_ET", "07:00"))
    end_et = _parse_et_time(getattr(brain_config, "DISCOVERY_END_ET", "09:30"))
    interval_min = getattr(brain_config, "DISCOVERY_INTERVAL_MIN", 5)
    top_n = getattr(brain_config, "DISCOVERY_TOP_N", 10)

    def now_et():
        return __import__("datetime").datetime.now(et)

    def minutes_since_midnight(t):
        return t.hour * 60 + t.minute

    start_min = start_et[0] * 60 + start_et[1]
    end_min = end_et[0] * 60 + end_et[1]
    interval_sec = interval_min * 60

    def log(msg: str) -> None:
        print("[discovery_until_open] " + msg, file=sys.stderr, flush=True)

    log("Eastern time; discovery %02d:%02d–%02d:%02d ET every %d min -> %s" % (
        start_et[0], start_et[1], end_et[0], end_et[1], interval_min, out_path))

    while True:
        now = now_et()
        if now.weekday() >= 5:
            log("weekend; sleeping 1h")
            time.sleep(3600)
            continue
        if not is_full_trading_day(now.date()):
            log("not a full trading day; sleeping 1h")
            time.sleep(3600)
            continue
        now_min = minutes_since_midnight(now)
        if now_min >= end_min:
            log("at or past market open; running final discovery and exiting")
            run_discovery(top_n=top_n, out_path=out_path)
            _verify_handoff_file(out_path)
            log("Watching: %s" % _read_watchlist(out_path))
            return 0
        if now_min < start_min:
            # Sleep until discovery start (e.g. 7:00 ET)
            from datetime import datetime, timedelta
            today_start = now.replace(hour=start_et[0], minute=start_et[1], second=0, microsecond=0)
            secs = (today_start - now).total_seconds()
            if secs > 0:
                log("sleeping until %02d:%02d ET (%.0fs)" % (start_et[0], start_et[1], secs))
                time.sleep(min(secs, 3600))
            continue
        # In window [start_et, 9:30): run discovery every 5 min
        log("Running discovery (fetching bars, scoring)...")
        try:
            run_discovery(top_n=top_n, out_path=out_path)
            log("Watching: %s" % _read_watchlist(out_path))
        except Exception as e:
            log("run_discovery failed: %s" % e)
        elapsed = (now_min - start_min) * 60 + now.second
        next_in = interval_sec - (elapsed % interval_sec)
        if next_in <= 0:
            next_in = interval_sec
        # If next run would be at or after 9:30, sleep until 9:30 then run once and exit
        if next_in >= (end_min - now_min) * 60 - now.second:
            from datetime import datetime, timedelta
            today_end = now.replace(hour=end_et[0], minute=end_et[1], second=0, microsecond=0)
            if now < today_end:
                secs = (today_end - now).total_seconds()
                log("sleeping until market open %02d:%02d ET (%.0fs)" % (end_et[0], end_et[1], secs))
                time.sleep(secs)
            # Run final discovery and exit
            log("market open; final discovery handoff")
            run_discovery(top_n=top_n, out_path=out_path)
            _verify_handoff_file(out_path)
            log("Watching: %s" % _read_watchlist(out_path))
            return 0
        log("Discovery done; next run in %ds" % next_in)
        time.sleep(min(next_in, interval_sec))


if __name__ == "__main__":
    sys.exit(main())
