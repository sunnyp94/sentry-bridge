"""
Pillar 2: Context Logic — Regime filter.
Only fire mean-reversion signals in choppy regime; trend signals in trending regime.
"""
from typing import List, Literal, Optional

import numpy as np

from . import config


RegimeType = Literal["mean_reversion", "trend", "neutral"]


def _ensure_arr(x) -> np.ndarray:
    if hasattr(x, "values"):
        return np.asarray(x.values, dtype=float)
    return np.asarray(x, dtype=float)


def get_regime(
    closes: List[float],
    atr_series: Optional[List[float]] = None,
    lookback: Optional[int] = None,
) -> RegimeType:
    """
    Simple regime: choppy (high vol, range-bound) → mean_reversion; sustained direction → trend.
    - If price > SMA and momentum positive → trend.
    - If volatility high (e.g. ATR percentile) and price oscillating → mean_reversion.
    - Else → neutral (allow both).
    """
    if not closes or len(closes) < 2:
        return "neutral"
    n = len(closes)
    lb = lookback or getattr(config, "REGIME_LOOKBACK", 20)
    if n < lb:
        return "neutral"
    c = _ensure_arr(closes)
    sma_period = getattr(config, "REGIME_TREND_SMA_PERIOD", 20)
    if n < sma_period:
        return "neutral"
    sma = np.mean(c[-sma_period:])
    momentum = (c[-1] - c[-min(5, n - 1)]) / c[-min(5, n - 1)] if c[-min(5, n - 1)] else 0
    # Trending: price above SMA and positive short-term momentum
    if c[-1] > sma and momentum > 0.005:
        return "trend"
    # Choppy: high volatility (ATR percentile) or range-bound (price near SMA, low momentum)
    if atr_series and len(atr_series) >= lb:
        arr_atr = _ensure_arr(atr_series[-lb:])
        current_atr = arr_atr[-1] if len(arr_atr) else 0
        if current_atr > 0:
            pct = (arr_atr < current_atr).sum() / len(arr_atr) * 100.0
            vol_pct_thresh = getattr(config, "REGIME_VOLATILITY_PCT", 70)
            if pct >= vol_pct_thresh:  # ATR in high percentile = volatile/choppy
                return "mean_reversion"
    # Price near SMA and small momentum → neutral/choppy
    if abs(c[-1] - sma) / sma < 0.02 and abs(momentum) < 0.01:
        return "mean_reversion"
    return "neutral"
