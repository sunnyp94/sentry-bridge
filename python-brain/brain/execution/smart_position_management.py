"""
Smart Position Management: EOD pruning (close only losers at 15:50 ET) and morning guardrail
(no automated selling 09:30–09:45 ET). Uses pytz for strict America/New_York time.
Do not use a blanket close_all_positions; use run_eod_prune() and is_morning_flush() instead.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from brain.core.parse_utils import parse_unrealized_plpc

log = logging.getLogger("brain.execution.smart_position_management")

try:
    import pytz
    ET = pytz.timezone("America/New_York")
except ImportError:
    ET = None
    log.warning("pytz not installed; is_morning_flush and run_eod_prune time checks will be disabled")


# -----------------------------------------------------------------------------
# 1) Morning Guardrail (Time-Blocker)
# -----------------------------------------------------------------------------

def is_morning_flush() -> bool:
    """
    Return True if current time is between 09:30 and 09:45 AM EST (inclusive start, exclusive end).
    Use to wrap automated selling logic so overnight holds are never sold during the opening
    15 minutes (protects from wide bid-ask spreads and gap-downs).
    """
    if ET is None:
        return False
    from datetime import datetime
    try:
        now = datetime.now(ET)
    except Exception:
        return False
    if now.weekday() > 4:  # Saturday=5, Sunday=6
        return False
    return (now.hour == 9 and 30 <= now.minute < 45)


def _now_et():
    """Current datetime in America/New_York (for EOD prune window)."""
    if ET is None:
        return None
    from datetime import datetime
    try:
        return datetime.now(ET)
    except Exception:
        return None


def is_eod_prune_time(eod_prune_at_et: str = "15:50") -> bool:
    """
    Return True when current ET is within the EOD prune window (e.g. 15:50–15:51)
    so we run the prune once at 15:50. Uses (hour, minute) >= (15, 50) and < (15, 52)
    to avoid running every second.
    """
    if not eod_prune_at_et or ET is None:
        return False
    now = _now_et()
    if now is None or now.weekday() > 4:
        return False
    parts = eod_prune_at_et.strip().split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return False
    # Run in the 2-minute window starting at (h, m) to avoid running every second
    if now.hour != h:
        return False
    return m <= now.minute < m + 2


# -----------------------------------------------------------------------------
# 2) End of Day (EOD) Pruning
# -----------------------------------------------------------------------------

def _get_positions_from_api() -> List[Dict[str, Any]]:
    """Fetch open positions from Alpaca. Returns list of dicts with symbol, qty, side, unrealized_plpc."""
    try:
        from brain.execution.executor import _client
        client = _client()
        if client is None:
            return []
        positions = client.get_all_positions()
    except Exception as e:
        log.warning("EOD prune: get_all_positions failed: %s", e)
        return []
    if not positions:
        return []
    if isinstance(positions, dict) and "positions" in positions:
        positions = positions.get("positions") or []
    out = []
    for pos in positions:
        sym = getattr(pos, "symbol", None) or (pos.get("symbol") if isinstance(pos, dict) else None)
        if not sym:
            continue
        sym = str(sym).strip()
        qty_raw = getattr(pos, "qty", None) if not isinstance(pos, dict) else pos.get("qty")
        try:
            qty = int(float(qty_raw)) if qty_raw is not None else 0
        except (TypeError, ValueError):
            qty = 0
        side = (getattr(pos, "side", None) or (pos.get("side") if isinstance(pos, dict) else "long")).lower()
        plpc_raw = getattr(pos, "unrealized_plpc", None) if not isinstance(pos, dict) else pos.get("unrealized_plpc")
        plpc = parse_unrealized_plpc(plpc_raw)
        out.append({"symbol": sym, "qty": qty, "side": side, "unrealized_plpc": plpc})
    return out


def run_eod_prune(
    stop_loss_pct: float = -2.0,
    eod_prune_at_et: str = "15:50",
) -> Tuple[int, int]:
    """
    Run exactly at 15:50 EST (configurable): loop through all open positions from the API.
    - If unrealized_plpc < stop_loss_pct (e.g. -2% → -0.02), execute market close for that position.
    - If position is profitable (plpc >= 0 or missing), log as Hold and do not sell.
    Handles both longs (sell to close) and shorts (buy to cover); qty from API is positive for long
    and may be negative for short — we close by symbol via close_position(symbol).
    Returns (closed_count, hold_count). Uses Alpaca API so it works after app restart with stale state.
    """
    closed, hold = 0, 0
    if ET is None:
        log.warning("EOD prune: pytz not available; skip")
        return (0, 0)
    now = _now_et()
    if now is None or now.weekday() > 4:
        return (0, 0)
    threshold = float(stop_loss_pct) / 100.0 if abs(stop_loss_pct) >= 1.0 else float(stop_loss_pct)  # allow -2 or -0.02
    positions = _get_positions_from_api()
    if not positions:
        log.debug("EOD prune: no open positions")
        return (0, 0)
    try:
        from brain.execution.executor import close_position
    except ImportError:
        log.warning("EOD prune: executor.close_position not available")
        return (0, 0)
    for p in positions:
        sym = p.get("symbol", "").strip()
        if not sym:
            continue
        plpc = p.get("unrealized_plpc")
        if plpc is None:
            log.info("EOD prune %s: no unrealized_plpc; Hold (do not close)", sym)
            hold += 1
            continue
        if plpc >= threshold:
            log.info("EOD prune %s: unrealized_plpc=%.2f%% >= threshold %.2f%% -> Hold", sym, plpc * 100, threshold * 100)
            hold += 1
            continue
        try:
            if close_position(sym):
                closed += 1
                log.info("EOD prune %s: closed (unrealized_plpc=%.2f%% < %.2f%%)", sym, plpc * 100, threshold * 100)
            else:
                hold += 1
        except Exception as e:
            log.warning("EOD prune %s: close failed: %s", sym, e)
    return (closed, hold)


# -----------------------------------------------------------------------------
# 3) Startup with positions from previous day (longs and shorts)
# -----------------------------------------------------------------------------
# The main app (consumer) rebuilds positions from the first "positions" event (payload from Go/Alpaca),
# stores longs as positive qty and shorts as negative, and uses is_morning_flush() to block
# automated selling 09:30–09:45. EOD prune (15:50) and morning guardrail handle closing and protection.
