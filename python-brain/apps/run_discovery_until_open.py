#!/usr/bin/env python3
"""
Pre-market discovery: run from container start until market open (9:30 ET).
- From 7:00 ET: run discovery every 5 min, write Priority Watchlist to ACTIVE_SYMBOLS_FILE.
- If the next 5-min rerun would be at or after 9:30: sleep until 9:30, then use existing
  active_symbols file and exit (no final discovery run).
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


def _run_optimizer_after_close() -> None:
    """Run strategy optimizer once after market close (self-learning phase). Uses same data/ as app. Non-fatal on failure."""
    import subprocess
    def _log(msg: str) -> None:
        print("[discovery_until_open] " + msg, file=sys.stderr, flush=True)
    root = _root.parent  # repo root (sentry-bridge or /app in Docker)
    script = root / "python-brain" / "apps" / "strategy_optimizer.py"
    if not script.exists():
        script = root / "apps" / "strategy_optimizer.py"
    if not script.exists():
        _log("strategy_optimizer.py not found; skip self-learning run")
        return
    try:
        _log("running strategy optimizer (post-market self-learning)...")
        result = subprocess.run(
            [sys.executable, str(script), "--write-proposed", "--rolling-days", "7"],
            cwd=str(root),
            env=os.environ,
            timeout=600,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _log("strategy optimizer finished")
        else:
            _log("strategy optimizer exited %s: %s" % (result.returncode, (result.stderr or result.stdout or "")[:300]))
    except subprocess.TimeoutExpired:
        _log("strategy optimizer timed out after 600s")
    except Exception as e:
        _log("strategy optimizer failed: %s" % e)


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
    close_et = _parse_et_time(getattr(brain_config, "MARKET_CLOSE_ET", "16:00"))
    close_min = close_et[0] * 60 + close_et[1]

    def log(msg: str) -> None:
        print("[discovery_until_open] " + msg, file=sys.stderr, flush=True)

    log("Eastern time; discovery %02d:%02d–%02d:%02d ET every %d min; market close %02d:%02d ET -> %s" % (
        start_et[0], start_et[1], end_et[0], end_et[1], interval_min, close_et[0], close_et[1], out_path))

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
        # After market close: run self-learning (strategy optimizer) once, then sleep until 7am next day.
        if now_min >= close_min:
            _run_optimizer_after_close()
            from datetime import datetime, timedelta
            tomorrow = (now.date() + timedelta(days=1))
            next_7am = now.replace(year=tomorrow.year, month=tomorrow.month, day=tomorrow.day,
                                  hour=start_et[0], minute=start_et[1], second=0, microsecond=0)
            secs = (next_7am - now).total_seconds()
            if secs <= 0:
                continue  # already past 7am next day (e.g. long sleep or clock skew)
            log("market closed; sleeping until 7am ET (%.0fs)" % secs)
            time.sleep(min(secs, 3600 * 18))
            continue
        if now_min >= end_min:
            # Always run discovery when at or past market open so we get a fresh list for the day (do not skip just because file already has symbols).
            log("at or past market open; running discovery once and exiting")
            run_discovery(top_n=top_n, out_path=out_path)
            _verify_handoff_file(out_path)
            log("Watching: %s" % _read_watchlist(out_path))
            return 0
        if now_min < start_min:
            # Sleep until discovery start (e.g. 7:00 ET); cap 1h per iteration so we re-check weekend/close
            from datetime import datetime, timedelta
            today_start = now.replace(hour=start_et[0], minute=start_et[1], second=0, microsecond=0)
            secs = (today_start - now).total_seconds()
            if secs <= 0:
                continue  # already at or past 7am (e.g. clock skew)
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
        # Use current time after discovery (discovery can take 2+ min); avoid sleeping past 09:30
        now = now_et()
        now_min = minutes_since_midnight(now)
        if now_min >= end_min:
            # We just ran discovery above, so handoff file is fresh; exit (no second run).
            log("at or past market open after discovery; exiting")
            log("Watching: %s" % _read_watchlist(out_path))
            return 0
        elapsed = (now_min - start_min) * 60 + now.second
        next_in = interval_sec - (elapsed % interval_sec)
        if next_in <= 0:
            next_in = interval_sec
        # If next run would be at or after 9:30, don't run discovery again — use existing file and exit
        if next_in >= (end_min - now_min) * 60 - now.second:
            today_end = now.replace(hour=end_et[0], minute=end_et[1], second=0, microsecond=0)
            secs = max(0, (today_end - now).total_seconds())
            if secs > 0:
                log("sleeping until market open %02d:%02d ET (%.0fs); will use existing active_symbols" % (end_et[0], end_et[1], secs))
                time.sleep(secs)
            log("market open; using existing active_symbols (skipping final discovery run)")
            _verify_handoff_file(out_path)
            log("Watching: %s" % _read_watchlist(out_path))
            return 0
        log("Discovery done; next run in %ds" % next_in)
        time.sleep(min(next_in, interval_sec))


if __name__ == "__main__":
    sys.exit(main())
