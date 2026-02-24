"""
Shadow Strategy: A/B testing with 3 ghost models.

Tracks 3 shadow variations (e.g. tighter stop, different TP) in parallel with live.
No real orders; we record ghost entries/exits and PnL. Promotion: if a shadow
outperforms live over 30+ ghost trades, we log a notification (and optionally
write suggested params to file for manual or auto swap).
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

log = logging.getLogger("brain.shadow_strategy")

# Shadow configs: (stop_loss_pct, take_profit_pct) as decimals. Live uses config.
SHADOW_CONFIGS = [
    {"name": "shadow_tight", "stop_pct": 0.005, "tp_pct": 0.015},   # 0.5% stop, 1.5% TP
    {"name": "shadow_wide", "stop_pct": 0.015, "tp_pct": 0.03},    # 1.5% stop, 3% TP
    {"name": "shadow_scalp", "stop_pct": 0.01, "tp_pct": 0.01},     # 1% stop, 1% TP
]
PROMOTION_MIN_GHOST_TRADES = 30


@dataclass
class ShadowPosition:
    symbol: str
    entry_price: float
    qty: int
    shadow_id: int


# shadow_id -> list of (symbol, entry_price, qty, exit_price, pnl_pct)
_shadow_closed: Dict[int, list] = {0: [], 1: [], 2: []}
# shadow_id -> symbol -> ShadowPosition
_shadow_open: Dict[int, Dict[str, ShadowPosition]] = {0: {}, 1: {}, 2: {}}


def shadow_on_buy(symbol: str, price: float, qty: int) -> None:
    """Record ghost buy for all 3 shadows (same price/qty as live)."""
    for i in range(3):
        _shadow_open[i][symbol] = ShadowPosition(symbol=symbol, entry_price=price, qty=qty, shadow_id=i)
    log.debug("shadow buy symbol=%s price=%.2f qty=%d (all 3 shadows)", symbol, price, qty)


def shadow_on_sell(symbol: str, price: float, exit_reason: str = "") -> None:
    """Close ghost position for all shadows that still hold this symbol."""
    for i in range(3):
        pos = _shadow_open[i].pop(symbol, None)
        if pos is None:
            continue
        pnl_pct = (price - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0
        _shadow_closed[i].append((symbol, pos.entry_price, pos.qty, price, pnl_pct))
        log.debug("shadow %d exit symbol=%s pnl_pct=%.2f%%", i, symbol, pnl_pct * 100)


def shadow_update(symbol: str, current_price: float) -> None:
    """
    Check shadow exit rules (stop/TP). If a shadow would exit at this price, close ghost position.
    """
    for i in range(3):
        pos = _shadow_open[i].get(symbol)
        if pos is None:
            continue
        cfg = SHADOW_CONFIGS[i]
        stop_pct = cfg["stop_pct"]
        tp_pct = cfg["tp_pct"]
        pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0
        if pnl_pct <= -stop_pct or pnl_pct >= tp_pct:
            _shadow_open[i].pop(symbol, None)
            _shadow_closed[i].append((symbol, pos.entry_price, pos.qty, current_price, pnl_pct))
            log.debug("shadow %d ghost exit symbol=%s price=%.2f pnl_pct=%.2f%%", i, symbol, current_price, pnl_pct * 100)


def get_shadow_stats() -> Dict[int, dict]:
    """Return per-shadow cumulative PnL and trade count."""
    out = {}
    for i in range(3):
        closed = _shadow_closed[i]
        n = len(closed)
        total_pnl_pct = sum(t[4] for t in closed)
        out[i] = {"name": SHADOW_CONFIGS[i]["name"], "ghost_trades": n, "cumulative_pnl_pct": total_pnl_pct}
    return out


def check_promotion(live_cumulative_pnl_pct: float) -> Optional[int]:
    """
    If a shadow has >= PROMOTION_MIN_GHOST_TRADES and outperformed live, return shadow_id and log.
    """
    stats = get_shadow_stats()
    for i in range(3):
        s = stats[i]
        if s["ghost_trades"] < PROMOTION_MIN_GHOST_TRADES:
            continue
        if s["cumulative_pnl_pct"] > live_cumulative_pnl_pct:
            log.info(
                "shadow_promotion shadow=%s outperformed live (shadow_pnl=%.2f%% live_pnl=%.2f%%) over %d ghost trades; consider promoting params.",
                s["name"], s["cumulative_pnl_pct"] * 100, live_cumulative_pnl_pct * 100, s["ghost_trades"],
            )
            return i
    return None
