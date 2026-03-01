#!/usr/bin/env python3
"""
Stock scanner (Opportunity Engine): finds a pool of opportunities for the day.

Scores the universe by |Z-score| and volume spike, then writes the top N symbols to a file.
When OPPORTUNITY_ENGINE_ENABLED=true, the consumer uses this file as the daily opportunity pool:
it only runs strategy (and trades) for symbols in that list.

Run daily (e.g. cron at market open or 8am ET):
  python3 apps/run_screener.py [--universe r2000_sp500_nasdaq100] [--top 5] [--out data/active_symbols.txt]

With --wait (used by entrypoint): on non-trading days do not write a file or start the engine;
instead block and sleep until next full trading day 7am ET with clear logs. Engine only starts
after scanner runs on a full trading day.
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# So brain.data get_bars debug logs are visible (e.g. in Docker)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from brain import config as brain_config
from brain.data import get_bars, get_bars_chunked
from brain.screener import get_universe, score_universe
from brain.market_calendar import is_full_trading_day

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


def _next_full_trading_day_7am_et():
    """Return (datetime of next 7am ET on a full trading day, tz ET) or None if zoneinfo missing."""
    if ZoneInfo is None:
        return None
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    d = now.date()
    while not is_full_trading_day(d):
        d += timedelta(days=1)
    return now.replace(year=d.year, month=d.month, day=d.day, hour=7, minute=0, second=0, microsecond=0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Screen universe for Z/volume/OFI opportunities; output top N symbols")
    parser.add_argument("--universe", type=str, default=None, help="r2000_sp500_nasdaq100 | lab_12 | russell2000 | sp500 | sp400 | nasdaq100 | env | alpaca_equity_500 | file:path.txt | comma list")
    parser.add_argument("--top", type=int, default=None, help="Top N symbols (default: SCREENER_TOP_N or 5)")
    parser.add_argument("--out", type=str, default=None, help="Write symbols to file (one per line); default ACTIVE_SYMBOLS_FILE or stdout")
    parser.add_argument("--days", type=int, default=None, help="Lookback days for bars (default SCREENER_LOOKBACK_DAYS or 22)")
    parser.add_argument("--z", type=float, default=None, help="|Z| threshold (default SCREENER_Z_THRESHOLD or 2.0)")
    parser.add_argument("--vol-pct", type=float, default=None, help="Volume spike %% vs 20d avg (default 15)")
    parser.add_argument("--chunk-size", type=int, default=None, help="Bar fetch chunk size for large universes (default from config or 100)")
    parser.add_argument("--chunk-delay", type=float, default=None, help="Seconds between bar chunks (default from config or 0.5)")
    parser.add_argument("--wait", action="store_true", help="When not a full trading day, sleep until next 7am ET (do not write file or start engine)")
    args = parser.parse_args()

    universe_name = args.universe or getattr(brain_config, "SCREENER_UNIVERSE", "r2000_sp500_nasdaq100")
    universe = get_universe(universe_name)
    if not universe:
        print("Empty universe; set --universe or SCREENER_UNIVERSE", file=sys.stderr)
        return 1

    top_n = args.top if args.top is not None else getattr(brain_config, "SCREENER_TOP_N", 5)
    days = args.days or getattr(brain_config, "SCREENER_LOOKBACK_DAYS", 22)
    z_threshold = args.z if args.z is not None else getattr(brain_config, "SCREENER_Z_THRESHOLD", 2.0)
    volume_spike_pct = args.vol_pct if args.vol_pct is not None else getattr(brain_config, "SCREENER_VOLUME_SPIKE_PCT", 15.0)
    chunk_size = getattr(brain_config, "SCREENER_CHUNK_SIZE", 100)
    chunk_delay = getattr(brain_config, "SCREENER_CHUNK_DELAY_SEC", 0.5)
    parallel = getattr(brain_config, "SCREENER_PARALLEL_CHUNKS", 1)
    chunk_size = args.chunk_size if args.chunk_size is not None else chunk_size
    chunk_delay = args.chunk_delay if args.chunk_delay is not None else chunk_delay

    # On non-full trading days: --wait = block and sleep (no file, engine won't start); else write fallback for manual/cron use.
    while not is_full_trading_day():
        if args.wait:
            next_7am = _next_full_trading_day_7am_et()
            if next_7am is None:
                print("[SCANNER] App sleeping (not a full trading day) but zoneinfo missing; sleeping 1h", file=sys.stderr)
                time.sleep(3600)
                continue
            now = datetime.now(next_7am.tzinfo)
            secs = max(0, (next_7am - now).total_seconds())
            if secs > 0:
                print("[SCANNER] App sleeping — not a full trading day (weekend/holiday/half-day). Next run: %s 07:00 ET (in %.0fs)" % (next_7am.date().isoformat(), secs), file=sys.stderr)
                time.sleep(min(secs, 3600 * 18))
            continue
        # No --wait: write fallback and exit (e.g. manual/cron run on a Sunday).
        print("[SCANNER] Not a full trading day; skipping bar fetch, writing fallback list (no --wait)", file=sys.stderr)
        active = universe[:top_n]
        out_path = args.out or getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                for s in active:
                    f.write(s + "\n")
            print("Wrote %d symbols (fallback) to %s" % (len(active), out_path), file=sys.stderr)
        else:
            for s in active:
                print(s)
        return 0

    # Large universes: fetch bars in chunks to stay under Alpaca rate limits (e.g. 10k/min)
    if len(universe) > chunk_size:
        print("Fetching bars for %d symbols in chunks of %d (parallel=%d)..." % (len(universe), chunk_size, parallel), file=sys.stderr)
        bars_by_sym = get_bars_chunked(universe, days, chunk_size=chunk_size, delay_between_chunks_sec=chunk_delay, max_workers=parallel)
    else:
        bars_by_sym = get_bars(universe, days)

    if not bars_by_sym:
        # No bar data (e.g. weekend, market closed, or API issue): write fallback so the engine can start
        active = universe[:top_n]
        out_path = args.out or getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                for s in active:
                    f.write(s + "\n")
            print("[SCANNER] USING BACKUP LIST (no bar data — market closed or API issue): %s" % active, file=sys.stderr)
            print("Wrote %d symbols to %s" % (len(active), out_path), file=sys.stderr)
        else:
            for s in active:
                print(s)
        return 0

    min_vol = getattr(brain_config, "SCREENER_MIN_VOLUME", 2000000)
    scored = score_universe(
        bars_by_sym,
        z_threshold=z_threshold,
        volume_spike_pct=volume_spike_pct,
        volume_avg_days=20,
        top_n=top_n,
        min_volume=min_vol,
    )
    active = [s for s, _ in scored]

    if not active:
        # No candidates met Z/volume criteria; fallback to first N from universe so we don't leave bot with empty list
        active = universe[:top_n]
        print("[SCANNER] USING BACKUP LIST (no symbols met Z/volume criteria): %s" % active, file=sys.stderr)

    out_path = args.out or getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            for s in active:
                f.write(s + "\n")
        if scored:
            print("[SCANNER] OPPORTUNITY LIST (Z/vol scored): %s" % active, file=sys.stderr)
            print("Top opportunities: %s" % [(s, info.get("reason")) for s, info in scored], file=sys.stderr)
        print("Wrote %d active symbols to %s" % (len(active), out_path), file=sys.stderr)
    else:
        for s in active:
            print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
