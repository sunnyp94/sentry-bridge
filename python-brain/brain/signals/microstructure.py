"""
Market microstructure and volatility indicators (pro-style).

Shifts from simple price action to how price is actually made—"retail guessing" → systematic
execution. The strategy stops asking only "where is price going?" and starts asking "is this
move valid and sustainable?"

1. VWAP — The institutional magnet
   Pros treat VWAP as "true" price for the day; large size targets execution at or better than VWAP.
   Logic: mean reversion. If price is extended above VWAP, assume the move is exhausted; wait for
   snap-back toward fair value before entering. (USE_VWAP_ANCHOR, VWAP_MEAN_REVERSION_PCT.)

2. ATR — Volatility filter (death of the fixed stop)
   A fixed 1–2% stop in a high-volatility name is a donation to the market.
   Logic: stop distance = ATR × multiplier. Stop widens when choppy, tightens when calm; keeps
   you in the trade through noise. (USE_ATR_STOP, ATR_PERIOD, ATR_STOP_MULTIPLE.)

3. Z-Score of returns — Quantifying "weirdness"
   Z = (x - μ) / σ standardizes how many standard deviations the current return is from the mean.
   Logic: Z ≤ -3 is a statistical outlier (~99.7% in a normal distribution)—treat as extreme
   oversold, mathematically likely to bounce, not "crash to fear." (USE_ZSCORE_MEAN_REVERSION,
   ZSCORE_MEAN_REVERSION_BUY.)

4. OFI (Order Flow Imbalance) — Leading signal [not implemented on daily bars]
   Price lags; order flow leads. Sideways price + heavily positive OFI = aggressive buyers
   hitting the ask, absorbed by a large limit seller; when exhausted, price often moves.
   Logic: avoids fake-outs (price up on low volume/weak conviction). Requires tape/tick data.
"""
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np


def _ensure_series(arr) -> np.ndarray:
    if hasattr(arr, "values"):
        return np.asarray(arr.values, dtype=float)
    return np.asarray(arr, dtype=float)


def vwap_from_ohlcv(
    high: List[float],
    low: List[float],
    close: List[float],
    volume: List[float],
    lookback: Optional[int] = None,
) -> Tuple[Optional[List[float]], Optional[float]]:
    """
    Rolling VWAP: typical_price = (H+L+C)/3, then VWAP = sum(typical*vol)/sum(vol) over window.
    Returns (series of VWAP per bar, latest VWAP value).
    lookback: window size; None = use all bars up to each index (expanding).
    """
    if not close or not volume or len(close) != len(volume):
        return None, None
    n = len(close)
    h = _ensure_series(high if high and len(high) == n else [0.0] * n)
    l_ = _ensure_series(low if low and len(low) == n else [0.0] * n)
    c = _ensure_series(close)
    v = _ensure_series(volume)
    typical = (h + l_ + c) / 3.0
    vwap_series = []
    for i in range(n):
        start = 0 if lookback is None else max(0, i - lookback + 1)
        tp = typical[start : i + 1]
        vol = v[start : i + 1]
        vol_sum = vol.sum()
        if vol_sum <= 0:
            vwap_series.append(float(c[i]))
            continue
        vwap_series.append(float((tp * vol).sum() / vol_sum))
    return vwap_series, vwap_series[-1] if vwap_series else None


def vwap_distance_pct(price: float, vwap: Optional[float]) -> Optional[float]:
    """Percentage distance of price from VWAP. Positive = above VWAP, negative = below."""
    if vwap is None or vwap <= 0:
        return None
    return (price - vwap) / vwap * 100.0


def vwap_band_std_series(
    close: List[float],
    vwap_series: Optional[List[float]],
    lookback: int = 20,
) -> Tuple[Optional[List[Optional[float]]], Optional[float]]:
    """
    Rolling std dev of (close - VWAP) for fair-value band. Band = VWAP ± std.
    Returns (series of std per bar, latest std). None where insufficient data.
    """
    if not close or not vwap_series or len(close) != len(vwap_series):
        return None, None
    n = len(close)
    c = _ensure_series(close)
    v = _ensure_series(vwap_series)
    dev = c - v
    std_list = []
    for i in range(n):
        start = max(0, i - lookback + 1)
        window = dev[start : i + 1]
        if len(window) < 2:
            std_list.append(None)
            continue
        std_list.append(float(window.std()))
    return std_list, std_list[-1] if std_list else None


def atr_percentile_series(
    atr_series_list: List[float],
    lookback: int = 60,
) -> Tuple[Optional[List[Optional[float]]], Optional[float]]:
    """
    Rolling percentile of current ATR within the last lookback bars (0-100).
    Tradable band: e.g. only trade when percentile in [10, 90].
    Returns (series of percentile per bar, latest). None where insufficient data.
    """
    if not atr_series_list or len(atr_series_list) < lookback:
        return None, None
    arr = _ensure_series(atr_series_list)
    n = len(arr)
    pct_list = []
    for i in range(n):
        if i < lookback - 1:
            pct_list.append(None)
            continue
        window = arr[i - lookback + 1 : i + 1]
        current = arr[i]
        if window.size == 0 or np.isnan(current):
            pct_list.append(None)
            continue
        pct = (window < current).sum() / len(window) * 100.0
        pct_list.append(float(pct))
    return pct_list, pct_list[-1] if pct_list else None


def atr_series(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int = 14,
) -> Tuple[Optional[List[float]], Optional[float]]:
    """
    Average True Range. TR = max(H-L, |H-prev_C|, |L-prev_C|); ATR = EMA(TR, period).
    Returns (series of ATR per bar, latest ATR value).
    """
    if not high or not low or not close or len(high) != len(close) or len(low) != len(close):
        return None, None
    n = len(close)
    h = _ensure_series(high)
    l_ = _ensure_series(low)
    c = _ensure_series(close)
    tr = np.zeros(n)
    tr[0] = h[0] - l_[0]
    for i in range(1, n):
        tr[i] = max(
            h[i] - l_[i],
            abs(h[i] - c[i - 1]),
            abs(l_[i] - c[i - 1]),
        )
    # EMA of TR
    k = 2.0 / (period + 1)
    atr_arr = np.zeros(n)
    atr_arr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr_arr[i] = k * tr[i] + (1 - k) * atr_arr[i - 1]
    atr_list = [float(atr_arr[i]) for i in range(n)]
    latest = atr_list[-1] if atr_list else None
    return atr_list, latest


def atr_stop_pct(price: float, atr: float, multiple: float) -> float:
    """Stop distance as % of price: (ATR * multiple) / price * 100."""
    if price <= 0 or atr <= 0:
        return 0.0
    return (atr * multiple) / price * 100.0


def returns_zscore_series(
    returns: List[float],
    period: int = 20,
) -> Tuple[Optional[List[Optional[float]]], Optional[float]]:
    """
    Z-Score of (most recent) return vs rolling mean and std of returns.
    Z = (current_return - rolling_mean) / rolling_std. Extreme negative → oversold (mean reversion buy).
    Returns (series of z-scores per bar, latest z-score). None where not enough data.
    """
    if not returns or len(returns) < period:
        return None, None
    arr = _ensure_series(returns)
    n = len(arr)
    z_list = []
    for i in range(n):
        if i < period:
            z_list.append(None)
            continue
        window = arr[i - period : i]
        mu = window.mean()
        std = window.std()
        if std is None or std <= 0 or np.isnan(std):
            z_list.append(None)
            continue
        z = (arr[i] - mu) / std
        z_list.append(float(z))
    latest = z_list[-1] if z_list else None
    return z_list, latest


def returns_zscore_from_prices(prices: List[float], period: int = 20) -> Tuple[Optional[List[Optional[float]]], Optional[float]]:
    """Compute 1-period returns from prices, then z-score series. Index i in result = z-score of return that just closed at bar i."""
    if not prices or len(prices) < 2:
        return None, None
    ret = [float((prices[i] - prices[i - 1]) / prices[i - 1]) if prices[i - 1] else 0.0 for i in range(1, len(prices))]
    z_series, last_z = returns_zscore_series(ret, period)
    if z_series is None:
        return None, None
    # Bar 0: no return; bar i (i>=1): z-score for ret[i-1]. So result[0]=None, result[1]=z_series[0], ...
    padded = [None] + z_series
    return padded[: len(prices)], last_z


def ofi_from_volumes(aggressive_buys: float, aggressive_sells: float) -> Optional[float]:
    """
    Order Flow Imbalance from precomputed aggressive buy/sell volume.
    OFI = (buys - sells) / (buys + sells). In [-1, 1]; positive = more buying pressure.
    """
    total = aggressive_buys + aggressive_sells
    if total <= 0:
        return None
    return max(-1.0, min(1.0, (aggressive_buys - aggressive_sells) / total))


class OFITracker:
    """
    Rolling Order Flow Imbalance from live trade/quote stream (e.g. Alpaca via Go).
    Infers aggressor from trade price vs last bid/ask: trade >= ask → aggressive buy,
    trade <= bid → aggressive sell; else use mid. Maintains last N trades per symbol.
    """

    def __init__(self, window_trades: int = 100):
        self.window_trades = max(1, window_trades)
        self._last_bid: Dict[str, float] = {}
        self._last_ask: Dict[str, float] = {}
        self._deque: Dict[str, deque] = {}  # symbol -> deque of (buy_vol, sell_vol)
        self._total_buy: Dict[str, float] = {}
        self._total_sell: Dict[str, float] = {}

    def update_quote(self, symbol: str, bid: Optional[float], ask: Optional[float]) -> None:
        if bid is not None and bid > 0:
            self._last_bid[symbol] = float(bid)
        if ask is not None and ask > 0:
            self._last_ask[symbol] = float(ask)

    def update_trade(
        self,
        symbol: str,
        price: float,
        size: int,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
    ) -> Optional[float]:
        """
        Classify trade as aggressive buy or sell using price vs bid/ask; update rolling window; return current OFI.
        bid/ask can be passed in or use last stored from update_quote.
        """
        if price <= 0 or size <= 0:
            return self.get_ofi(symbol)
        b = bid if bid is not None else self._last_bid.get(symbol)
        a = ask if ask is not None else self._last_ask.get(symbol)
        if b is None or a is None or a <= b:
            return self.get_ofi(symbol)
        mid = (b + a) / 2.0
        vol = float(size)
        if price >= a:
            buy_vol, sell_vol = vol, 0.0
        elif price <= b:
            buy_vol, sell_vol = 0.0, vol
        else:
            buy_vol = vol if price > mid else 0.0
            sell_vol = vol if price < mid else 0.0
            if price == mid:
                return self.get_ofi(symbol)

        if symbol not in self._deque:
            self._deque[symbol] = deque()
            self._total_buy[symbol] = 0.0
            self._total_sell[symbol] = 0.0
        d = self._deque[symbol]
        d.append((buy_vol, sell_vol))
        self._total_buy[symbol] += buy_vol
        self._total_sell[symbol] += sell_vol
        while len(d) > self.window_trades:
            old_b, old_s = d.popleft()
            self._total_buy[symbol] -= old_b
            self._total_sell[symbol] -= old_s
        return self.get_ofi(symbol)

    def get_ofi(self, symbol: str) -> Optional[float]:
        """Current OFI for symbol in [-1, 1] or None if no tape yet."""
        total_b = self._total_buy.get(symbol, 0.0)
        total_s = self._total_sell.get(symbol, 0.0)
        return ofi_from_volumes(total_b, total_s)
