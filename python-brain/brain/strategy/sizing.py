"""
Pillar 1: Risk-first position sizing.
Size by fixed risk per trade (ATR-based) or by position size % of equity.
"""
from typing import Optional

from brain.core import config


def risk_based_shares(
    equity: float,
    price: float,
    atr: float,
    atr_stop_multiple: float,
    risk_pct: Optional[float] = None,
    max_qty: int = 2,
) -> int:
    """
    Position size so that if stop (ATR * mult) is hit, we lose risk_pct of equity.
    shares = (equity * risk_pct/100) / (ATR * atr_stop_multiple). Clamped to [1, max_qty].
    """
    if risk_pct is None or risk_pct <= 0:
        return 1
    if equity <= 0 or price <= 0 or atr <= 0:
        return 1
    risk_amount = equity * (risk_pct / 100.0)
    stop_per_share = atr * atr_stop_multiple
    if stop_per_share <= 0:
        return 1
    raw = risk_amount / stop_per_share
    qty = max(1, min(int(round(raw)), max_qty))
    return qty


def position_size_shares(
    equity: float,
    price: float,
    atr: Optional[float] = None,
    atr_stop_multiple: float = 2.0,
    max_qty: int = 2,
) -> int:
    """
    Use RISK_PCT_PER_TRADE when > 0 and ATR available; else POSITION_SIZE_PCT.
    """
    risk_pct = getattr(config, "RISK_PCT_PER_TRADE", 0)
    if risk_pct > 0 and atr is not None and atr > 0:
        return risk_based_shares(
            equity,
            price,
            atr,
            atr_stop_multiple,
            risk_pct=risk_pct,
            max_qty=max_qty,
        )
    pct = getattr(config, "POSITION_SIZE_PCT", 0.05)
    if pct <= 0 or price <= 0:
        return 1
    raw = (equity * pct) / price
    return max(1, min(int(round(raw)), max_qty))
