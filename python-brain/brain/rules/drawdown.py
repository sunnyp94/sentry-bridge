"""
Max drawdown rule: when (peak_equity - current_equity) / peak_equity >= MAX_DRAWDOWN_PCT,
block new buys until equity recovers. Sells (e.g. stop loss) still allowed.
Consumer calls update_drawdown_peak() whenever equity is known; strategy checks is_drawdown_halt().
"""
import logging
from typing import Optional

from .. import config

log = logging.getLogger("brain.rules.drawdown")

_peak_equity: Optional[float] = None
_current_equity: Optional[float] = None


def update_drawdown_peak(equity: float) -> None:
    """Call when you have fresh account equity. Updates peak (running high) and current."""
    global _peak_equity, _current_equity
    _current_equity = equity
    if _peak_equity is None or equity > _peak_equity:
        _peak_equity = equity


def is_drawdown_halt() -> bool:
    """
    True if drawdown from peak >= MAX_DRAWDOWN_PCT and we should block new buys.
    Sells still allowed. Requires update_drawdown_peak() to be called with current equity.
    """
    if not config.DRAWDOWN_HALT_ENABLED or config.MAX_DRAWDOWN_PCT <= 0:
        return False
    if _peak_equity is None or _current_equity is None or _peak_equity <= 0:
        return False
    drawdown_pct = (_peak_equity - _current_equity) / _peak_equity
    if drawdown_pct >= config.MAX_DRAWDOWN_PCT / 100.0:
        log.warning(
            "drawdown_halt: drawdown=%.2f%% >= %.2f%% (no new buys)",
            drawdown_pct * 100,
            config.MAX_DRAWDOWN_PCT,
        )
        return True
    return False
