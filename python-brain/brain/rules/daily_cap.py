"""
Daily cap rule: when daily PnL >= DAILY_CAP_PCT (default 0.2%), block new buys for the rest of the day.
Sells (e.g. stop loss) still allowed. Consumer calls update_equity() on each positions update; strategy checks is_daily_cap_reached().
"""
import logging
from datetime import datetime
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from .. import config

log = logging.getLogger("brain.rules.daily_cap")

_start_equity: Optional[float] = None
_start_date_et: Optional[str] = None  # "YYYY-MM-DD" in ET
_current_equity: Optional[float] = None


def _today_et() -> str:
    if ZoneInfo is None:
        return datetime.utcnow().strftime("%Y-%m-%d")
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def update_equity(equity: float) -> None:
    """Call when you have fresh account equity (e.g. from Alpaca account or positions)."""
    global _current_equity, _start_equity, _start_date_et
    today = _today_et()
    if _start_date_et != today or _start_equity is None:
        _start_date_et = today
        _start_equity = equity
        log.debug("daily_cap start_equity=%.2f date=%s", equity, today)
    _current_equity = equity


def is_daily_cap_reached() -> bool:
    """
    True if we should stop new buys for the day:
    - daily PnL >= DAILY_CAP_PCT / DAILY_PROFIT_TARGET_PCT (lock in gains), or
    - daily PnL <= -DAILY_LOSS_CAP_PCT (daily loss cap; pro rule).
    Sells (e.g. stop loss) still allowed. Requires update_equity() to be called with current equity.
    """
    if _start_equity is None or _current_equity is None or _start_equity <= 0:
        return False
    pct = (_current_equity - _start_equity) / _start_equity

    # Daily loss cap and circuit breaker: no new buys when down too much for the day (death-spiral protection)
    loss_cap = getattr(config, "DAILY_LOSS_CAP_PCT", 0)
    circuit_breaker = getattr(config, "DAILY_DRAWDOWN_CIRCUIT_BREAKER_PCT", 5.0)
    loss_thresh = max(loss_cap, circuit_breaker) if loss_cap > 0 else circuit_breaker
    if loss_thresh > 0 and pct <= -loss_thresh / 100.0:
        log.info("daily_loss_cap/circuit_breaker: pnl_pct=%.2f%% <= -%.2f%% (pause all trading)", pct * 100, loss_thresh)
        return True

    # Daily gain cap: lock in gains (no new buys when we've hit target)
    target_pct = getattr(config, "DAILY_PROFIT_TARGET_PCT", config.DAILY_CAP_PCT)
    if not config.DAILY_CAP_ENABLED or target_pct <= 0:
        return False
    if pct >= target_pct / 100.0:
        log.info("daily_cap reached: pnl_pct=%.2f%% >= %.2f%% (lock in gains, no new buys)", pct * 100, target_pct)
        return True
    return False


def should_flat_all_for_daily_target() -> bool:
    """
    True when daily PnL >= DAILY_PROFIT_TARGET_PCT and FLAT_WHEN_DAILY_TARGET_HIT is set.
    Consumer should close all positions when this is True (profit daily and stop).
    """
    if _start_equity is None or _current_equity is None or _start_equity <= 0:
        return False
    if not getattr(config, "FLAT_WHEN_DAILY_TARGET_HIT", False):
        return False
    target_pct = getattr(config, "DAILY_PROFIT_TARGET_PCT", 0.1)
    if target_pct <= 0:
        return False
    pct = (_current_equity - _start_equity) / _start_equity
    if pct >= target_pct / 100.0:
        log.info("daily_target hit: pnl_pct=%.2f%% >= %.2f%% (flat all, stop for the day)", pct * 100, target_pct)
        return True
    return False
