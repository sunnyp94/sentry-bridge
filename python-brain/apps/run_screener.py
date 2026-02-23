#!/usr/bin/env python3
"""
Stock scanner (Opportunity Engine): finds a pool of opportunities for the day.

Scores the universe by |Z-score| and volume spike, then writes the top N symbols to a file.
When OPPORTUNITY_ENGINE_ENABLED=true, the consumer uses this file as the daily opportunity pool:
it only runs strategy (and trades) for symbols in that list.

Run daily (e.g. cron at market open or 8am ET):
  python3 apps/run_screener.py [--universe lab_12] [--top 5] [--out data/active_symbols.txt]

Without --out, prints symbols to stdout. With --out or ACTIVE_SYMBOLS_FILE, writes the pool file.
"""
import argparse
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from brain import config as brain_config
from brain.data import get_bars, get_bars_chunked
from brain.screener import get_universe, score_universe


def main() -> int:
    parser = argparse.ArgumentParser(description="Screen universe for Z/volume/OFI opportunities; output top N symbols")
    parser.add_argument("--universe", type=str, default=None, help="lab_12 | env | alpaca_equity | alpaca_equity_500 | sp400 | nasdaq100 | file:path.txt | comma list")
    parser.add_argument("--top", type=int, default=None, help="Top N symbols (default: SCREENER_TOP_N or 5)")
    parser.add_argument("--out", type=str, default=None, help="Write symbols to file (one per line); default ACTIVE_SYMBOLS_FILE or stdout")
    parser.add_argument("--days", type=int, default=None, help="Lookback days for bars (default SCREENER_LOOKBACK_DAYS or 22)")
    parser.add_argument("--z", type=float, default=None, help="|Z| threshold (default SCREENER_Z_THRESHOLD or 2.0)")
    parser.add_argument("--vol-pct", type=float, default=None, help="Volume spike %% vs 20d avg (default 15)")
    parser.add_argument("--chunk-size", type=int, default=None, help="Bar fetch chunk size for large universes (default from config or 100)")
    parser.add_argument("--chunk-delay", type=float, default=None, help="Seconds between bar chunks (default from config or 0.5)")
    args = parser.parse_args()

    universe_name = args.universe or getattr(brain_config, "SCREENER_UNIVERSE", "lab_12")
    universe = get_universe(universe_name)
    if not universe:
        print("Empty universe; set --universe or SCREENER_UNIVERSE / TICKERS", file=sys.stderr)
        return 1

    top_n = args.top if args.top is not None else getattr(brain_config, "SCREENER_TOP_N", 5)
    days = args.days or getattr(brain_config, "SCREENER_LOOKBACK_DAYS", 22)
    z_threshold = args.z if args.z is not None else getattr(brain_config, "SCREENER_Z_THRESHOLD", 2.0)
    volume_spike_pct = args.vol_pct if args.vol_pct is not None else getattr(brain_config, "SCREENER_VOLUME_SPIKE_PCT", 15.0)
    chunk_size = getattr(brain_config, "SCREENER_CHUNK_SIZE", 100)
    chunk_delay = getattr(brain_config, "SCREENER_CHUNK_DELAY_SEC", 0.5)
    chunk_size = args.chunk_size if args.chunk_size is not None else chunk_size
    chunk_delay = args.chunk_delay if args.chunk_delay is not None else chunk_delay

    # Large universes: fetch bars in chunks to stay under Alpaca rate limits (e.g. 10k/min)
    if len(universe) > chunk_size:
        print("Fetching bars for %d symbols in chunks of %d (delay %.1fs)..." % (len(universe), chunk_size, chunk_delay), file=sys.stderr)
        bars_by_sym = get_bars_chunked(universe, days, chunk_size=chunk_size, delay_between_chunks_sec=chunk_delay)
    else:
        bars_by_sym = get_bars(universe, days)
    if not bars_by_sym:
        print("No bar data; check Alpaca keys and universe symbols", file=sys.stderr)
        return 1

    scored = score_universe(
        bars_by_sym,
        z_threshold=z_threshold,
        volume_spike_pct=volume_spike_pct,
        volume_avg_days=20,
        top_n=top_n,
    )
    active = [s for s, _ in scored]

    if not active:
        # No candidates met Z/volume criteria; fallback to first N from universe so we don't leave bot with empty list
        active = universe[:top_n]
        print("No symbols met Z/volume criteria; using first %d from universe: %s" % (top_n, active), file=sys.stderr)

    out_path = args.out or getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            for s in active:
                f.write(s + "\n")
        print("Wrote %d active symbols to %s" % (len(active), out_path), file=sys.stderr)
    else:
        for s in active:
            print(s)
    if scored:
        print("Top opportunities:", [(s, info.get("reason")) for s, info in scored], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
