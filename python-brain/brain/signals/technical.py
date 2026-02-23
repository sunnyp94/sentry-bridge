"""
Technical layer: RSI, MACD, and 3 chart patterns (double top, inverted H&S, bull/bear flag).
Single technical_score() combines these for the Green Light pattern check. No other indicators.
"""
from typing import List, Optional, Tuple

import numpy as np


# ---- RSI ----

def _rsi_from_series(prices: List[float], period: int) -> Optional[float]:
    """RSI from closes. Returns 0-100 or None."""
    if len(prices) < period + 1:
        return None
    arr = np.array(prices[-period - 1 :], dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _rsi_score(prices: List[float], period: int) -> Optional[float]:
    """Map RSI to [-1, 1]: oversold -> positive, overbought -> negative."""
    if not prices or len(prices) < period + 1:
        return None
    rsi = _rsi_from_series(prices, period)
    if rsi is None:
        return None
    if rsi <= 30:
        score = 0.5 + (30 - rsi) / 60.0
    elif rsi >= 70:
        score = -0.5 - (rsi - 70) / 60.0
    else:
        score = (50 - rsi) / 50.0
    return max(-1.0, min(1.0, float(score)))


# ---- MACD ----

def _ema(series: np.ndarray, period: int) -> np.ndarray:
    """EMA of series; first (period-1) values are NaN, then valid."""
    out = np.full_like(series, np.nan, dtype=float)
    if len(series) < period:
        return out
    mult = 2.0 / (period + 1)
    out[period - 1] = np.mean(series[:period])
    for i in range(period, len(series)):
        out[i] = (series[i] - out[i - 1]) * mult + out[i - 1]
    return out


def macd_components(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[Tuple[List[float], List[float], List[float]]]:
    """
    MACD line, signal line, histogram. Returns (macd_line, signal_line, histogram) or None.
    Needs at least slow + signal bars.
    """
    if len(prices) < slow + signal:
        return None
    arr = np.array(prices, dtype=float)
    ema_f = _ema(arr, fast)
    ema_s = _ema(arr, slow)
    macd_line = (ema_f - ema_s).tolist()
    # Signal = EMA of MACD
    macd_arr = np.array(macd_line, dtype=float)
    valid = ~np.isnan(macd_arr)
    if not np.any(valid):
        return None
    first_valid = int(np.argmax(valid))
    if first_valid + signal > len(macd_arr):
        return None
    signal_arr = _ema(macd_arr, signal)
    signal_line = np.where(np.isnan(signal_arr), 0.0, signal_arr).tolist()
    hist = []
    for i in range(len(macd_line)):
        m = macd_line[i]
        s = signal_line[i] if i < len(signal_line) else 0.0
        if (isinstance(m, float) and np.isnan(m)) or (isinstance(s, float) and np.isnan(s)):
            hist.append(0.0)
        else:
            hist.append(float(m - s))
    return (macd_line, signal_line, hist)


def _macd_score(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[float]:
    """
    Score in [-1, 1] from MACD: histogram sign and recent slope (bullish -> positive).
    """
    comp = macd_components(prices, fast=fast, slow=slow, signal=signal)
    if not comp or len(comp[2]) < 2:
        return None
    hist = comp[2]
    # Use last few histogram values
    recent = [h for h in hist[-5:] if h != 0]
    if not recent:
        return 0.0
    last = recent[-1]
    # Normalize by typical price scale so score is bounded
    avg_price = float(np.mean(prices[-30:])) if len(prices) >= 30 else prices[-1]
    if avg_price <= 0:
        return 0.0
    # Histogram in price terms: scale to roughly [-1,1] (e.g. 1% of price = 0.5)
    scale = avg_price * 0.02
    raw = last / scale if scale else 0
    score = max(-1.0, min(1.0, raw))
    return float(score)


# ---- Pattern detection (closes; optional highs/lows for better accuracy) ----

def _local_extrema(closes: List[float], window: int = 2) -> Tuple[List[int], List[int]]:
    """Indices of local maxima and minima (peak/trough). window = bars each side."""
    n = len(closes)
    peaks, troughs = [], []
    for i in range(window, n - window):
        left = closes[i - window : i]
        right = closes[i + 1 : i + 1 + window]
        if closes[i] >= max(left + [closes[i]]) and closes[i] >= max(right + [closes[i]]):
            peaks.append(i)
        if closes[i] <= min(left + [closes[i]]) and closes[i] <= min(right + [closes[i]]):
            troughs.append(i)
    return peaks, troughs


def detect_double_top(
    closes: List[float],
    lookback: int = 40,
    tolerance_pct: float = 2.0,
) -> Optional[float]:
    """
    Double top: two similar highs then break below trough. Returns bearish score 0..-1 (or 0 if not present).
    """
    if len(closes) < lookback:
        return 0.0
    use = closes[-lookback:]
    peaks, troughs = _local_extrema(use, window=2)
    if len(peaks) < 2 or len(troughs) < 1:
        return 0.0
    # Two most recent peaks
    p1_idx = peaks[-2]
    p2_idx = peaks[-1]
    if p2_idx <= p1_idx:
        return 0.0
    p1_val = use[p1_idx]
    p2_val = use[p2_idx]
    if p1_val <= 0:
        return 0.0
    diff_pct = abs(p2_val - p1_val) / p1_val * 100
    if diff_pct > tolerance_pct:
        return 0.0
    # Trough between the two peaks
    between = [t for t in troughs if p1_idx < t < p2_idx]
    if not between:
        return 0.0
    trough_val = min(use[t] for t in between)
    last_close = use[-1]
    if last_close < trough_val:
        # Break below trough: confirm double top bearish
        break_pct = (trough_val - last_close) / trough_val * 100
        return -max(0.0, min(1.0, break_pct / 5.0))  # cap at -1
    return 0.0


def detect_inverted_head_shoulders(
    closes: List[float],
    lookback: int = 40,
    tolerance_pct: float = 3.0,
) -> Optional[float]:
    """
    Inverted H&S: left shoulder low, head (lower), right shoulder low, break above neckline.
    Returns bullish score 0..1 (or 0 if not present).
    """
    if len(closes) < lookback:
        return 0.0
    use = closes[-lookback:]
    peaks, troughs = _local_extrema(use, window=2)
    if len(troughs) < 3 or len(peaks) < 2:
        return 0.0
    # Three troughs: left shoulder, head, right shoulder (head = lowest)
    t_indices = troughs[-3:] if len(troughs) >= 3 else troughs
    t_vals = [use[i] for i in t_indices]
    head_idx = t_indices[np.argmin(t_vals)]
    left_idx = min(t_indices)
    right_idx = max(t_indices)
    if head_idx == left_idx or head_idx == right_idx:
        return 0.0
    left_val = use[left_idx]
    right_val = use[right_idx]
    head_val = use[head_idx]
    if head_val >= left_val or head_val >= right_val:
        return 0.0
    # Shoulders roughly equal
    if left_val <= 0:
        return 0.0
    sh_diff_pct = abs(right_val - left_val) / left_val * 100
    if sh_diff_pct > tolerance_pct:
        return 0.0
    # Neckline: line through the two peaks between L-H and H-R
    peaks_between = [p for p in peaks if left_idx < p < right_idx]
    if len(peaks_between) < 2:
        return 0.0
    neck_high = max(use[p] for p in peaks_between)
    last_close = use[-1]
    if last_close > neck_high:
        break_pct = (last_close - neck_high) / neck_high * 100
        return max(0.0, min(1.0, break_pct / 5.0))
    return 0.0


def detect_head_shoulders_bearish(
    closes: List[float],
    lookback: int = 40,
    tolerance_pct: float = 3.0,
) -> float:
    """
    Classic (bearish) Head & Shoulders: left shoulder high, head (higher), right shoulder high, break below neckline.
    Returns bearish score 0..-1 (or 0 if not present). Used for HTF 'pause longs'.
    """
    if len(closes) < lookback:
        return 0.0
    use = closes[-lookback:]
    peaks, troughs = _local_extrema(use, window=2)
    if len(peaks) < 3 or len(troughs) < 2:
        return 0.0
    # Three peaks: left shoulder, head, right shoulder (head = highest)
    p_indices = peaks[-3:] if len(peaks) >= 3 else peaks
    p_vals = [use[i] for i in p_indices]
    head_idx = p_indices[np.argmax(p_vals)]
    left_idx = min(p_indices)
    right_idx = max(p_indices)
    if head_idx == left_idx or head_idx == right_idx:
        return 0.0
    left_val = use[left_idx]
    right_val = use[right_idx]
    head_val = use[head_idx]
    if head_val <= left_val or head_val <= right_val:
        return 0.0
    if left_val <= 0:
        return 0.0
    sh_diff_pct = abs(right_val - left_val) / left_val * 100
    if sh_diff_pct > tolerance_pct:
        return 0.0
    troughs_between = [t for t in troughs if left_idx < t < right_idx]
    if len(troughs_between) < 2:
        return 0.0
    neck_low = min(use[t] for t in troughs_between)
    last_close = use[-1]
    if last_close < neck_low:
        break_pct = (neck_low - last_close) / neck_low * 100
        return -max(0.0, min(1.0, break_pct / 5.0))
    return 0.0


def detect_flag(
    closes: List[float],
    lookback: int = 30,
    pole_bars: int = 5,
    pole_min_move_pct: float = 3.0,
    flag_bars_min: int = 3,
    flag_bars_max: int = 15,
) -> Optional[float]:
    """
    Bull flag: strong up move (pole) then consolidation then break above -> +1.
    Bear flag: strong down move then consolidation then break below -> -1.
    Returns score in [-1, 1] or 0.
    """
    if len(closes) < lookback or lookback < pole_bars + flag_bars_max + 2:
        return 0.0
    use = closes[-lookback:]
    # Pole: first pole_bars move
    start = use[0]
    pole_end = use[pole_bars]
    if start <= 0:
        return 0.0
    pole_move_pct = (pole_end - start) / start * 100
    if abs(pole_move_pct) < pole_min_move_pct:
        return 0.0
    # Flag: next flag_bars_min..flag_bars_max bars (consolidation)
    flag_start_idx = pole_bars
    best_score = 0.0
    for flen in range(flag_bars_min, min(flag_bars_max + 1, len(use) - pole_bars - 1)):
        flag_end_idx = flag_start_idx + flen
        if flag_end_idx >= len(use):
            break
        flag_high = max(use[flag_start_idx:flag_end_idx + 1])
        flag_low = min(use[flag_start_idx:flag_end_idx + 1])
        last_c = use[-1]
        if pole_move_pct > 0:  # bull flag
            if last_c > flag_high:
                break_pct = (last_c - flag_high) / flag_high * 100
                best_score = max(best_score, min(1.0, break_pct / 3.0))
        else:  # bear flag
            if last_c < flag_low:
                break_pct = (flag_low - last_c) / flag_low * 100
                best_score = min(best_score, -min(1.0, break_pct / 3.0))
    return best_score if best_score != 0 else 0.0


# ---- Unified technical score ----

def technical_score(
    prices: List[float],
    rsi_period: int = 14,
    use_macd: bool = True,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    use_patterns: bool = True,
    pattern_lookback: int = 40,
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
) -> Optional[float]:
    """
    Single technical score in [-1, 1] from RSI + MACD + 3 patterns (double top, inverted H&S, bull/bear flag).
    Combines with equal weight; patterns only add when detected.
    highs/lows optional (for future refinement); patterns use closes when not provided.
    """
    if not prices or len(prices) < rsi_period + 1:
        return None
    components = []

    # RSI
    r = _rsi_score(prices, rsi_period)
    if r is not None:
        components.append(("rsi", r))

    # MACD
    if use_macd and len(prices) >= macd_slow + macd_signal:
        m = _macd_score(prices, fast=macd_fast, slow=macd_slow, signal=macd_signal)
        if m is not None:
            components.append(("macd", m))

    # Patterns (3)
    if use_patterns and len(prices) >= pattern_lookback:
        dt = detect_double_top(prices, lookback=pattern_lookback)
        if dt != 0:
            components.append(("double_top", dt))
        ihs = detect_inverted_head_shoulders(prices, lookback=pattern_lookback)
        if ihs != 0:
            components.append(("inv_h_s", ihs))
        fl = detect_flag(prices, lookback=min(pattern_lookback, 30))
        if fl != 0:
            components.append(("flag", fl))

    if not components:
        return _rsi_score(prices, rsi_period) if r is not None else 0.0

    # Equal weight average
    total = sum(v for _, v in components)
    n = len(components)
    score = total / n
    return max(-1.0, min(1.0, float(score)))


# ---- Energy filters (RSI divergence, MACD zero-cross) ----

def rsi_bullish_divergence(prices: List[float], period: int = 14, lookback: int = 30) -> bool:
    """
    Bullish divergence: price makes Lower Low but RSI makes Higher Low.
    Requires at least 2 troughs in lookback; compares last two price troughs and their RSI values.
    """
    if len(prices) < lookback or lookback < period + 5:
        return False
    use = prices[-lookback:]
    _, troughs = _local_extrema(use, window=2)
    if len(troughs) < 2:
        return False
    t1, t2 = troughs[-2], troughs[-1]
    if t2 <= t1:
        return False
    p1, p2 = use[t1], use[t2]
    rsi_series = []
    for i in range(period + 1, len(use)):
        r = _rsi_from_series(use[: i + 1], period)
        if r is not None:
            rsi_series.append((i, r))
    if len(rsi_series) < 2:
        return False
    r1 = next((r for i, r in rsi_series if i >= t1), None)
    r2 = next((r for i, r in reversed(rsi_series) if i <= t2), None)
    if r1 is None or r2 is None:
        return False
    return p2 < p1 and r2 > r1  # price lower low, RSI higher low


def macd_histogram_above_zero(
    prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> bool:
    """True if MACD histogram has crossed above zero (last value > 0 and had a negative value recently)."""
    comp = macd_components(prices, fast=fast, slow=slow, signal=signal)
    if not comp or len(comp[2]) < 3:
        return False
    hist = comp[2]
    if hist[-1] <= 0:
        return False
    # Crossed above: was negative in last 5 bars
    recent = hist[-6:]
    return any(h < 0 for h in recent[:-1])


# Backward compatibility: expose RSI for callers that need it
def rsi_value(prices: List[float], period: int = 14) -> Optional[float]:
    """Return raw RSI 0-100."""
    return _rsi_from_series(prices, period)
