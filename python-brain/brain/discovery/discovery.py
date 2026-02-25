"""
Two-Stage Intelligence: Discovery Loop (pre-market 7:00–9:30 ET).

Runs every 5 minutes in the discovery window. Scores universe by:
- Relative Volume (RV): latest day volume vs 20-day average (institutional activity proxy).
- Z-Score: price move ±2σ from 20-day mean (statistical stretch).

Outputs a Priority Watchlist (top N) to ACTIVE_SYMBOLS_FILE for handoff to execution at 9:30.
"""
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from brain.core import config as brain_config
from brain.market.data import get_bars, get_bars_chunked, filter_tradeable_symbols
from brain.screener import get_universe, score_universe
from brain.market.market_calendar import is_full_trading_day

log = logging.getLogger("brain.discovery")

def _parse_et_time(s: str) -> Tuple[int, int]:
    """Parse 'HH:MM' -> (hour, minute). Default (8, 0) if invalid."""
    if not s or ":" not in s:
        return (8, 0)
    parts = s.strip().split(":")
    if len(parts) != 2:
        return (8, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except (TypeError, ValueError):
        return (8, 0)


def _now_et() -> Optional[datetime]:
    if ZoneInfo is None:
        return None
    return datetime.now(ZoneInfo("America/New_York"))


def _in_discovery_window(start_et: Tuple[int, int] = (8, 0), end_et: Tuple[int, int] = (9, 30), now: Optional[datetime] = None) -> bool:
    """True if current time (ET) is in [start_et, end_et) on a weekday."""
    if now is None:
        now = _now_et()
    if now is None:
        return False
    if now.weekday() >= 5:
        return False
    start_min = start_et[0] * 60 + start_et[1]
    end_min = end_et[0] * 60 + end_et[1]
    now_min = now.hour * 60 + now.minute
    return start_min <= now_min < end_min


def run_discovery(
    universe_name: Optional[str] = None,
    top_n: int = 10,
    lookback_days: int = 35,
    z_threshold: float = 2.0,
    volume_spike_pct: float = 15.0,
    out_path: Optional[str] = None,
) -> List[str]:
    """
    One discovery run: fetch bars, score by RV + Z, return top N symbols.
    Writes to out_path (or ACTIVE_SYMBOLS_FILE) when provided.
    """
    universe_name = universe_name or getattr(brain_config, "SCREENER_UNIVERSE", "r2000_sp500_nasdaq100")
    out_path = out_path or getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
    universe = get_universe(universe_name)
    if not universe:
        log.warning("discovery: empty universe %s", universe_name)
        return []

    chunk_size = getattr(brain_config, "SCREENER_CHUNK_SIZE", 100)
    log.info("discovery: universe %s has %d symbols (will fetch bars in chunks of %d)",
             universe_name, len(universe), chunk_size)

    if len(universe) > chunk_size:
        bars_by_sym = get_bars_chunked(
            universe,
            lookback_days,
            chunk_size=getattr(brain_config, "SCREENER_CHUNK_SIZE", 100),
            delay_between_chunks_sec=getattr(brain_config, "SCREENER_CHUNK_DELAY_SEC", 0.5),
            max_workers=getattr(brain_config, "SCREENER_PARALLEL_CHUNKS", 1),
        )
    else:
        bars_by_sym = get_bars(universe, lookback_days)

    if not bars_by_sym:
        log.warning("discovery: no bar data; cannot build watchlist")
        return []

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
        active = universe[:top_n]
        log.info("[DISCOVERY] USING BACKUP LIST (no Z/RV qualifiers): %s", active)
    else:
        log.info("[DISCOVERY] PRIORITY WATCHLIST (RV+Z scored): %s | %s",
                 active, [(s, info.get("reason")) for s, info in scored])

    # Exclude symbols that are not active/tradeable on Alpaca to avoid order rejections
    active = filter_tradeable_symbols(active)

    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            for s in active:
                f.write(s + "\n")
        log.info("discovery: wrote %d symbols to %s", len(active), out_path)
    return active


class DiscoveryEngine:
    """
    Pre-market discovery loop: every N min from start_et to end_et (on full trading days),
    score universe by RV + Z and write Priority Watchlist to ACTIVE_SYMBOLS_FILE.
    At 9:30 the watchlist is handed off to execution (same file used by Go/consumer).
    """

    def __init__(
        self,
        start_et: Tuple[int, int] = (8, 0),
        end_et: Tuple[int, int] = (9, 30),
        interval_sec: int = 5 * 60,
        top_n: int = 10,
    ):
        self.start_et = start_et
        self.end_et = end_et
        self.interval_sec = interval_sec
        self.top_n = top_n
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run_loop(self) -> None:
        if ZoneInfo is None:
            log.warning("discovery: zoneinfo not available; cannot run ET loop")
            return
        et = ZoneInfo("America/New_York")
        log.info("discovery: loop started (every %d min from %02d:%02d to %02d:%02d ET on full trading days)",
                 self.interval_sec // 60, self.start_et[0], self.start_et[1], self.end_et[0], self.end_et[1])
        while not self._stop:
            now = datetime.now(et)
            if not is_full_trading_day(now.date()):
                time.sleep(60)
                continue
            start_min = self.start_et[0] * 60 + self.start_et[1]
            end_min = self.end_et[0] * 60 + self.end_et[1]
            now_min = now.hour * 60 + now.minute
            if now_min < start_min:
                today_start = now.replace(hour=self.start_et[0], minute=self.start_et[1], second=0, microsecond=0)
                secs = (today_start - now).total_seconds()
                if secs > 0:
                    time.sleep(min(secs, 60))
                continue
            if now_min >= end_min:
                tomorrow = (now.date() + timedelta(days=1))
                next_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, self.start_et[0], self.start_et[1], 0, tzinfo=et)
                secs = (next_start - now).total_seconds()
                if secs > 0:
                    time.sleep(min(secs, 300))
                continue
            try:
                run_discovery(top_n=self.top_n)
            except Exception as e:
                log.exception("discovery run failed: %s", e)
            elapsed = (now_min - start_min) * 60 + now.second
            next_in = self.interval_sec - (elapsed % self.interval_sec)
            if next_in <= 0:
                next_in = self.interval_sec
            time.sleep(min(next_in, self.interval_sec))
