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
    True if daily PnL >= DAILY_CAP_PCT (e.g. 0.2%) and we should stop new buys.
    Sells (e.g. stop loss) still allowed. Requires update_equity() to be called with current equity.
    """
    if not config.DAILY_CAP_ENABLED or config.DAILY_CAP_PCT <= 0:
        return False
    if _start_equity is None or _current_equity is None or _start_equity <= 0:
        return False
    pct = (_current_equity - _start_equity) / _start_equity
    if pct >= config.DAILY_CAP_PCT / 100.0:
        log.info("daily_cap reached: pnl_pct=%.2f%% >= %.2f%% (lock in gains, no new buys)", pct * 100, config.DAILY_CAP_PCT)
        return True
    return False
