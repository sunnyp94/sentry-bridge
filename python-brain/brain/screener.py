"""
Opportunity Engine: screen a universe for the "weirdest" moves (Z-score, volume spike, OFI skew).
Returns top N symbols to activate for the day instead of trading a static list.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from brain.signals.microstructure import returns_zscore_from_prices


# Default lab universe (12 names for testing); scale later to Russell 2000 or top 500 liquid.
LAB_12 = [
    "CRWD", "SNOW", "DDOG", "NET", "MDB", "DECK", "POOL", "SOFI",
    "XPO", "HIMS", "FIVE", "ZS",
]


def get_universe(name: str) -> List[str]:
    """
    Resolve universe name to list of symbols.
    - "lab_12": default 12-ticker testing lab.
    - "env": TICKERS from environment (comma-separated).
    - "alpaca_equity": all active tradeable US equities from Alpaca (large; use with chunked bars).
    - "alpaca_equity_500": first 500 symbols from Alpaca (faster full-market scan).
    - "sp400": S&P MidCap 400 (file data/sp400.txt — add symbols from S&P or broker).
    - "nasdaq100": Nasdaq 100 (file data/nasdaq100.txt — high liquidity, avoids mega-cap-only).
    - "file:path/to/symbols.txt": one symbol per line (e.g. Russell 2000 list).
    - Otherwise treated as comma-separated list (e.g. "AAPL,TSLA,GOOGL").
    """
    import os
    from pathlib import Path

    if name == "lab_12":
        return list(LAB_12)
    if name == "env":
        raw = os.environ.get("TICKERS", "").strip()
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    if name == "sp400":
        return get_universe("file:data/sp400.txt")
    if name == "nasdaq100":
        return get_universe("file:data/nasdaq100.txt")
    if name == "alpaca_equity":
        from brain.data import get_tradeable_symbols_from_alpaca
        return get_tradeable_symbols_from_alpaca(limit=None)
    if name == "alpaca_equity_500":
        from brain.data import get_tradeable_symbols_from_alpaca
        return get_tradeable_symbols_from_alpaca(limit=500)
    if name.startswith("file:"):
        path = Path(name[5:].strip()).expanduser().resolve()
        if not path.exists():
            return []
        symbols = []
        with open(path, "r") as f:
            for line in f:
                s = line.split("#")[0].strip().upper()
                if s:
                    symbols.append(s)
        return symbols
    return [s.strip().upper() for s in name.split(",") if s.strip()]


def _ensure_close_volume(df: pd.DataFrame) -> Tuple[Optional[List[float]], Optional[List[float]]]:
    """Extract close and volume lists from a bar DataFrame. Handles c/v column names."""
    if df is None or df.empty:
        return None, None
    close = df["close"] if "close" in df.columns else df.get("c")
    vol = df["volume"] if "volume" in df.columns else df.get("v")
    if close is None:
        return None, None
    closes = close.astype(float).tolist()
    if vol is None:
        vols = [1.0] * len(closes)
    else:
        vols = vol.astype(float).tolist()
    if len(vols) != len(closes):
        vols = vols[: len(closes)] if len(vols) > len(closes) else vols + [1.0] * (len(closes) - len(vols))
    return closes, vols


def score_universe(
    bars_by_sym: Dict[str, pd.DataFrame],
    z_threshold: float = 2.0,
    volume_spike_pct: float = 15.0,
    volume_avg_days: int = 20,
    top_n: int = 5,
    z_period: int = 20,
    ofi_by_sym: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Score each symbol by:
    1. |Z-score| > z_threshold (extreme move)
    2. Volume spike: latest volume >= (1 + volume_spike_pct/100) * 20-day avg volume
    3. Optional: OFI skew (when ofi_by_sym provided) — rank by |OFI|

    Returns list of (symbol, info_dict) sorted by composite score (best first), length <= top_n.
    info_dict has: z_score, vol_ratio, ofi (if provided), score, reason.
    """
    volume_mult = 1.0 + volume_spike_pct / 100.0  # e.g. 1.15 for 15% spike
    candidates: List[Tuple[str, Dict[str, Any]]] = []

    for symbol, df in bars_by_sym.items():
        if df is None or len(df) < max(z_period + 1, volume_avg_days + 1):
            continue
        df = df.sort_index() if hasattr(df.index, "sort_values") else df
        closes, vols = _ensure_close_volume(df)
        if not closes or not vols:
            continue

        # Z-score of returns (latest bar)
        z_series, last_z = returns_zscore_from_prices(closes, period=z_period)
        z_score = float(last_z) if last_z is not None else 0.0

        # Volume ratio: latest / avg(last volume_avg_days)
        use_vols = vols[-volume_avg_days:] if len(vols) >= volume_avg_days else vols
        avg_vol = float(np.mean(use_vols)) if use_vols else 1.0
        latest_vol = float(vols[-1]) if vols else 0.0
        vol_ratio = (latest_vol / avg_vol) if avg_vol > 0 else 0.0

        # Qualify: |Z| >= z_threshold OR volume spike
        qualifies_z = abs(z_score) >= z_threshold
        qualifies_vol = vol_ratio >= volume_mult
        if not qualifies_z and not qualifies_vol:
            continue

        # Composite score: higher = weirder / more opportunity
        # |Z| contributes directly; volume spike contributes (vol_ratio - 1) * 2 so 15% spike ≈ 0.3
        score = abs(z_score) + max(0, (vol_ratio - 1.0)) * 2.0
        ofi = ofi_by_sym.get(symbol) if ofi_by_sym else None
        if ofi is not None:
            score += abs(float(ofi))  # OFI skew adds to score
        reason_parts = []
        if qualifies_z:
            reason_parts.append(f"|Z|={abs(z_score):.2f}")
        if qualifies_vol:
            reason_parts.append(f"vol={vol_ratio:.2f}x")
        if ofi is not None:
            reason_parts.append(f"OFI={ofi:.2f}")

        candidates.append((symbol, {
            "z_score": z_score,
            "vol_ratio": vol_ratio,
            "ofi": ofi,
            "score": score,
            "reason": " ".join(reason_parts),
        }))

    # Sort by score descending, take top_n
    candidates.sort(key=lambda x: -x[1]["score"])
    return candidates[: top_n]


def run_screener(
    universe: List[str],
    bars_by_sym: Dict[str, pd.DataFrame],
    top_n: int = 5,
    z_threshold: float = 2.0,
    volume_spike_pct: float = 15.0,
    volume_avg_days: int = 20,
    ofi_by_sym: Optional[Dict[str, float]] = None,
) -> List[str]:
    """
    Run the screener on pre-fetched bars. Returns list of active symbols (top N opportunities).
    """
    scored = score_universe(
        bars_by_sym,
        z_threshold=z_threshold,
        volume_spike_pct=volume_spike_pct,
        volume_avg_days=volume_avg_days,
        top_n=top_n,
        ofi_by_sym=ofi_by_sym,
    )
    return [s for s, _ in scored]
