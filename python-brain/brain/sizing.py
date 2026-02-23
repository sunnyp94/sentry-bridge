"""
Pillar 1: Risk-first position sizing.
Size by fixed risk per trade (0.5-2% of capital) using ATR so that one stop = one risk unit.
Optional Kelly Criterion to scale risk by win rate and avg win/loss.
"""
from collections import deque
from typing import Optional

from . import config

# Rolling round-trip PnLs for Kelly (win=True/False, pnl=float)
_trade_history: deque = deque(maxlen=200)


def record_round_trip(pnl: float) -> None:
    """Call after a round-trip trade closes; pnl is dollar PnL (positive = win)."""
    _trade_history.append((pnl >= 0, pnl))


def get_kelly_fraction() -> Optional[float]:
    """
    Kelly Criterion: f* = (p*b - q) / b where p=win rate, q=1-p, b=avg_win/avg_loss.
    Returns fraction in [0, 1] or None if insufficient data. Caller should cap at KELLY_FRACTION_CAP.
    """
    n = getattr(config, "KELLY_LOOKBACK_TRADES", 50)
    if len(_trade_history) < 10:
        return None
    recent = list(_trade_history)[-n:]
    wins = [pnl for is_win, pnl in recent if is_win and pnl > 0]
    losses = [abs(pnl) for is_win, pnl in recent if not is_win and pnl < 0]
    if not wins or not losses:
        return None
    w = len(wins) / len(recent)
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    if avg_loss <= 0:
        return None
    b = avg_win / avg_loss
    kelly = (w * b - (1 - w)) / b
    if kelly <= 0:
        return 0.0
    cap = getattr(config, "KELLY_FRACTION_CAP", 0.25)
    return min(1.0, min(kelly, cap))


def risk_based_shares(
    equity: float,
    price: float,
    atr: float,
    atr_stop_multiple: float,
    risk_pct: Optional[float] = None,
    kelly_scale: bool = False,
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
    if kelly_scale and getattr(config, "KELLY_SIZING_ENABLED", False):
        kf = get_kelly_fraction()
        if kf is not None and kf > 0:
            risk_pct = risk_pct * kf
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
            kelly_scale=True,
            max_qty=max_qty,
        )
    pct = getattr(config, "POSITION_SIZE_PCT", 0.01)
    if pct <= 0 or price <= 0:
        return 1
    raw = (equity * pct) / price
    return max(1, min(int(round(raw)), max_qty))
