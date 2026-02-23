"""
Shared data fetching (Alpaca bars, assets). Used by backtest and screener.
"""
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

# SPY symbol for global 200-day MA regime
SPY_SYMBOL = "SPY"
SPY_200MA_LOOKBACK = 210


def get_tradeable_symbols_from_alpaca(limit: Optional[int] = None) -> List[str]:
    """
    Fetch active, tradeable US equity symbols from Alpaca Assets API.
    With Active Trader Pro (10k calls/min) this is a single request.
    Optional limit caps the list (e.g. 500 or 1000 for faster screener runs).
    """
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass
    except ImportError:
        return []
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return []
    client = TradingClient(key, secret)
    req = GetAssetsRequest(asset_class=AssetClass.US_EQUITY, status="active")
    assets = client.get_all_assets(req)
    symbols = [a.symbol for a in assets if getattr(a, "tradable", True)]
    if limit is not None and limit > 0:
        symbols = symbols[:limit]
    return symbols


def get_bars(symbols: List[str], days: int) -> Dict[str, pd.DataFrame]:
    """Fetch daily bars from Alpaca. Returns dict symbol -> DataFrame with columns open, high, low, close, volume (and c/h/l/v if raw)."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
    except ImportError:
        return {}
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return {}
    client = StockHistoricalDataClient(key, secret)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    feed = DataFeed.SIP if os.environ.get("ALPACA_DATA_FEED", "").lower() == "sip" else DataFeed.IEX
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=feed,
    )
    bars = client.get_stock_bars(req)
    if bars is None:
        return {}
    out: Dict[str, pd.DataFrame] = {}
    if hasattr(bars, "df") and bars.df is not None and not bars.df.empty:
        for sym in symbols:
            try:
                if hasattr(bars.df.index, "get_level_values") and sym in bars.df.index.get_level_values(0):
                    df = bars.df.loc[sym].copy()
                elif hasattr(bars.df.columns, "get_level_values") and sym in bars.df.columns.get_level_values(0):
                    df = bars.df[sym].copy()
                else:
                    continue
                if isinstance(df, pd.Series):
                    df = df.to_frame().T
                if "close" not in df.columns and "c" in df.columns:
                    df["close"] = df["c"]
                if "open" not in df.columns and "o" in df.columns:
                    df["open"] = df["o"]
                out[sym] = df
            except Exception:
                continue
    elif hasattr(bars, "data") and isinstance(bars.data, dict):
        for sym in symbols:
            if sym not in bars.data or not bars.data[sym]:
                continue
            rows = []
            for b in bars.data[sym]:
                rows.append({
                    "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                    "volume": getattr(b, "volume", 0),
                })
            out[sym] = pd.DataFrame(rows)
    return out


def get_bars_chunked(
    symbols: List[str],
    days: int,
    chunk_size: int = 100,
    delay_between_chunks_sec: float = 0.5,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch daily bars for a large symbol list in chunks to avoid rate limits.
    With 10k calls/min (Active Trader Pro), chunk_size=100 and ~0.5s delay
    keeps you well under the limit.
    """
    out: Dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        chunk_bars = get_bars(chunk, days)
        out.update(chunk_bars)
        if i + chunk_size < len(symbols) and delay_between_chunks_sec > 0:
            time.sleep(delay_between_chunks_sec)
    return out


def get_spy_200ma_regime(lookback_days: int = SPY_200MA_LOOKBACK) -> Dict[str, Any]:
    """
    Fetch SPY daily bars and compute whether current close is above or below 200-day SMA.
    Used for global filter: when SPY < 200 MA, bot is more cautious on longs and (when shorts exist) more aggressive on shorts.
    Returns dict: above_200ma (bool), close (float), sma200 (float). On error returns above_200ma=True (permissive).
    """
    bars = get_bars([SPY_SYMBOL], lookback_days)
    if not bars or SPY_SYMBOL not in bars:
        return {"above_200ma": True, "close": 0.0, "sma200": 0.0}
    df = bars[SPY_SYMBOL].sort_index()
    if "close" not in df.columns and "c" in df.columns:
        df["close"] = df["c"]
    if "close" not in df.columns or len(df) < 200:
        return {"above_200ma": True, "close": 0.0, "sma200": 0.0}
    closes = df["close"].astype(float)
    sma200 = closes.rolling(200, min_periods=200).mean()
    last_close = float(closes.iloc[-1])
    last_sma = float(sma200.iloc[-1])
    above = last_sma > 0 and last_close >= last_sma
    return {"above_200ma": above, "close": last_close, "sma200": last_sma}
