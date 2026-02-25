"""
Structural Map (Higher Timeframe Filter).
TrendAnalyzer: 15m/1h proxy using daily bars when that's what we have.
- Bullish bias: Price > 50 EMA → only Longs allowed.
- Pause longs: Double Top or Head & Shoulders (bearish) on HTF → no new Long entries.
"""
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from brain.core import config
from .technical import detect_double_top, detect_head_shoulders_bearish


@dataclass
class StructureResult:
    """Result of HTF structure check."""
    trend_bullish: bool   # price > EMA(50) → longs allowed
    pause_longs: bool     # double top or H&S bearish on HTF → no new longs
    structure_ok: bool    # True when trend aligned for longs (bullish and not pause_longs)


def _ema_series(closes: List[float], period: int) -> Optional[float]:
    """Last value of EMA(period)."""
    if not closes or len(closes) < period:
        return None
    arr = np.array(closes[-period - 10 :], dtype=float)  # a bit extra for warmup
    mult = 2.0 / (period + 1)
    ema = np.mean(arr[:period])
    for i in range(period, len(arr)):
        ema = (arr[i] - ema) * mult + ema
    return float(ema)


def trend_analyzer(
    htf_closes: List[float],
    ema_period: Optional[int] = None,
    pattern_lookback: int = 40,
) -> StructureResult:
    """
    Structural map: trend bias + pause-longs on bearish patterns.
    htf_closes: higher-timeframe closes (e.g. daily bars as 1h proxy).
    Returns structure_ok=True when longs are allowed (bullish and no double top/H&S).
    """
    ema_period = ema_period or getattr(config, "STRUCTURE_EMA_PERIOD", 50)
    if not htf_closes or len(htf_closes) < max(ema_period, pattern_lookback):
        return StructureResult(trend_bullish=False, pause_longs=False, structure_ok=False)

    price = htf_closes[-1]
    ema = _ema_series(htf_closes, ema_period)
    trend_bullish = (ema is not None and price > ema)

    dt = detect_double_top(htf_closes, lookback=pattern_lookback)
    hs = detect_head_shoulders_bearish(htf_closes, lookback=pattern_lookback)
    pause_longs = (dt < 0) or (hs < 0)

    structure_ok = trend_bullish and not pause_longs
    return StructureResult(trend_bullish=trend_bullish, pause_longs=pause_longs, structure_ok=structure_ok)
