"""
Shared data fetching (Alpaca bars, assets). Used by screener and consumer.
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import pandas as pd

_log = logging.getLogger(__name__)


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


def filter_tradeable_symbols(symbols: List[str]) -> List[str]:
    """
    Return only symbols that are active and tradeable on Alpaca.
    Used by discovery to avoid writing symbols that would cause "asset is not active" on order.
    On API error or missing credentials, returns the original list (no change) so discovery is not broken.
    """
    if not symbols:
        return symbols
    try:
        from alpaca.trading.client import TradingClient
    except ImportError:
        return symbols
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return symbols
    out: List[str] = []
    try:
        client = TradingClient(key, secret)
        for sym in symbols:
            s = (sym or "").strip().upper()
            if not s:
                continue
            try:
                asset = client.get_asset(s)
                if asset is None:
                    continue
                if getattr(asset, "status", "") != "active":
                    continue
                if not getattr(asset, "tradable", True):
                    continue
                out.append(s)
            except Exception:
                _log.debug("filter_tradeable: skip %s (not active/tradeable)", s)
                continue
        if len(out) < len(symbols):
            _log.info("filter_tradeable: kept %d of %d symbols (dropped non-tradeable)", len(out), len(symbols))
    except Exception as e:
        _log.warning("filter_tradeable_symbols failed: %s; using unfiltered list", e)
        return symbols
    return out if out else symbols


def get_bars(symbols: List[str], days: int) -> Dict[str, pd.DataFrame]:
    """Fetch daily bars from Alpaca. Returns dict symbol -> DataFrame with columns open, high, low, close, volume (and c/h/l/v if raw)."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
    except ImportError as e:
        _log.warning("get_bars: alpaca.data import failed: %s", e)
        return {}
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        _log.warning("get_bars: missing APCA_API_KEY_ID or APCA_API_SECRET_KEY (or ALPACA_* env)")
        return {}
    # Optional: use same data URL as Go engine (e.g. https://data.alpaca.markets)
    url_override = os.environ.get("ALPACA_DATA_BASE_URL", "").strip() or None
    if url_override and not url_override.startswith("http"):
        url_override = "https://" + url_override
    client = StockHistoricalDataClient(key, secret, url_override=url_override) if url_override else StockHistoricalDataClient(key, secret)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    # Default SIP (full US). Set ALPACA_DATA_FEED=iex for IEX-only (free tier).
    feed = DataFeed.IEX if os.environ.get("ALPACA_DATA_FEED", "").strip().lower() == "iex" else DataFeed.SIP
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=feed,
    )
    _log.info("get_bars: request symbols=%s days=%d start=%s end=%s feed=%s", symbols[:5], days, start.isoformat(), end.isoformat(), feed)
    try:
        bars = client.get_stock_bars(req)
    except Exception as e:
        _log.warning("get_bars: Alpaca API error: %s", e)
        return {}
    if bars is None:
        _log.warning("get_bars: Alpaca returned None")
        return {}
    # Debug: what did we get?
    has_df = hasattr(bars, "df") and bars.df is not None
    df_shape = bars.df.shape if has_df else None
    has_data = hasattr(bars, "data") and isinstance(bars.data, dict)
    data_keys = list(bars.data.keys()) if has_data else []
    _log.info("get_bars: response has_df=%s df_shape=%s has_data=%s data_keys=%s", has_df, df_shape, has_data, data_keys[:10] if data_keys else [])
    out: Dict[str, pd.DataFrame] = {}
    if has_df and not bars.df.empty:
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
            except Exception as e:
                _log.debug("get_bars: parse %s: %s", sym, e)
                continue
    elif has_data:
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
    if not out:
        _log.warning("get_bars: parsed 0 DataFrames (df.empty=%s or no matching symbols)", bars.df.empty if has_df else "n/a")
    return out


def get_bars_chunked(
    symbols: List[str],
    days: int,
    chunk_size: int = 100,
    delay_between_chunks_sec: float = 0.5,
    max_workers: int = 1,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch daily bars for a large symbol list in chunks.
    When max_workers > 1, fetches that many chunks in parallel (faster; stay under Alpaca rate limits).
    When max_workers == 1, sequential with delay_between_chunks_sec between chunks.
    """
    n_chunks = (len(symbols) + chunk_size - 1) // chunk_size
    _log.info(
        "get_bars_chunked: %d symbols in %d chunks (chunk_size=%d, max_workers=%d)",
        len(symbols), n_chunks, chunk_size, max_workers,
    )
    out: Dict[str, pd.DataFrame] = {}

    if max_workers is None or max_workers < 1:
        max_workers = 1
    if max_workers == 1:
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i : i + chunk_size]
            chunk_bars = get_bars(chunk, days)
            out.update(chunk_bars)
            if i + chunk_size < len(symbols) and delay_between_chunks_sec > 0:
                time.sleep(delay_between_chunks_sec)
    else:
        chunks = [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]
        workers = min(max_workers, len(chunks))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(get_bars, chunk, days): chunk for chunk in chunks}
            for future in as_completed(futures):
                try:
                    chunk_bars = future.result()
                    out.update(chunk_bars)
                except Exception as e:
                    _log.warning("get_bars_chunked: chunk failed: %s", e)
    _log.info("get_bars_chunked: got bars for %d symbols", len(out))
    return out
