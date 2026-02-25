"""
Daily cap rule: soft-cap trailing stop on daily PnL (code defaults only).
- Once daily PnL >= DAILY_PROFIT_TARGET_PCT (0.5%), activate a trailing stop: if PnL drops
  SOFT_CAP_TRAILING_PCT (0.1%) from the day's peak, block new buys for the session. Runners keep running with scale-out.
- Daily loss cap / circuit breaker unchanged.
Consumer calls update_equity() on each positions update; strategy checks is_daily_cap_reached().
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
# Peak daily PnL (as decimal) once we've crossed the profit target; used for soft-cap trailing stop.
_peak_daily_pnl_pct: Optional[float] = None


def _today_et() -> str:
    if ZoneInfo is None:
        return datetime.utcnow().strftime("%Y-%m-%d")
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def update_equity(equity: float) -> None:
    """Call when you have fresh account equity (e.g. from Alpaca account or positions)."""
    global _current_equity, _start_equity, _start_date_et, _peak_daily_pnl_pct
    today = _today_et()
    if _start_date_et != today or _start_equity is None:
        _start_date_et = today
        _start_equity = equity
        _peak_daily_pnl_pct = None
        log.debug("daily_cap start_equity=%.2f date=%s", equity, today)
    _current_equity = equity


def is_daily_cap_reached() -> bool:
    """
    True if we should stop new buys for the day:
    - Daily loss cap / circuit breaker: pnl <= -X% (unchanged).
    - Soft-cap trailing: once daily PnL >= DAILY_PROFIT_TARGET_PCT (0.5%), track peak; if PnL drops
      SOFT_CAP_TRAILING_PCT (0.1%) from that peak, block new buys (e.g. hit +0.6% then drop to +0.5% = kill session).
    Sells and scale-out still allowed. Requires update_equity() to be called with current equity.
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

    # Soft-cap trailing stop: activation threshold and trail from config (code defaults 0.5% and 0.1%)
    if not config.DAILY_CAP_ENABLED:
        return False
    target_pct = getattr(config, "DAILY_PROFIT_TARGET_PCT", 0.5)
    trailing_pct = getattr(config, "SOFT_CAP_TRAILING_PCT", 0.1)
    activation = target_pct / 100.0
    trail = trailing_pct / 100.0

    global _peak_daily_pnl_pct
    if pct >= activation:
        if _peak_daily_pnl_pct is None:
            _peak_daily_pnl_pct = pct
        else:
            _peak_daily_pnl_pct = max(_peak_daily_pnl_pct, pct)
        # If we've dropped 0.1% from peak, kill session (no new buys)
        if _peak_daily_pnl_pct is not None and pct <= _peak_daily_pnl_pct - trail:
            log.info(
                "daily_cap soft_cap_trailing: pnl_pct=%.2f%% dropped %.2f%% from peak %.2f%% (no new buys)",
                pct * 100, trailing_pct, _peak_daily_pnl_pct * 100,
            )
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
    target_pct = getattr(config, "DAILY_PROFIT_TARGET_PCT", 0.5)
    if target_pct <= 0:
        return False
    pct = (_current_equity - _start_equity) / _start_equity
    if pct >= target_pct / 100.0:
        log.info("daily_target hit: pnl_pct=%.2f%% >= %.2f%% (flat all, stop for the day)", pct * 100, target_pct)
        return True
    return False
