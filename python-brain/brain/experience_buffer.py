"""
Experience Buffer: Recursive Strategy Optimizer — Data Collection.

Saves a MarketSnapshot for every entry and exit. Snapshots capture indicator state
(Z-Score, RSI, MACD, OFI, ATR) and market regime (trend vs range). Trades are labeled
24h later: Success (hit target), False Positive (pattern failed), Late Entry (price moved before entry).
"""
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("brain.experience_buffer")

# Default path: repo data dir or env EXPERIENCE_BUFFER_PATH
def _buffer_path() -> Path:
    p = os.environ.get("EXPERIENCE_BUFFER_PATH", "").strip()
    if p:
        return Path(p)
    root = Path(__file__).resolve().parent.parent.parent  # python-brain -> repo
    return root / "data" / "experience_buffer.jsonl"


@dataclass
class MarketSnapshot:
    """State of indicators and regime at a decision moment. Used for entry and exit."""
    symbol: str
    ts: str  # ISO timestamp
    action: str  # "entry" | "exit"
    price: Optional[float] = None
    qty: Optional[int] = None
    reason: str = ""  # e.g. green_light_4pt, stop_loss, take_profit
    # Indicators (None when unavailable)
    z_score: Optional[float] = None
    rsi: Optional[float] = None
    macd_above_zero: Optional[bool] = None
    ofi: Optional[float] = None
    atr_pct: Optional[float] = None
    atr_percentile: Optional[float] = None
    technical_score: Optional[float] = None
    prob_gain: Optional[float] = None
    structure_ok: Optional[bool] = None
    regime: Optional[str] = None  # "trend" | "range" | "neutral"
    # For exit: realized outcome (set when we record exit)
    exit_reason: Optional[str] = None
    unrealized_pl_pct_at_exit: Optional[float] = None
    # Label set 24h later: "success" | "false_positive" | "late_entry" | None
    label_24h: Optional[str] = None
    label_ts: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# In-memory: track open entries by (symbol) so we can attach exit to entry and write labeled trade
_open_entries: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def record_entry(
    symbol: str,
    price: float,
    qty: int,
    reason: str,
    *,
    z_score: Optional[float] = None,
    rsi: Optional[float] = None,
    macd_above_zero: Optional[bool] = None,
    ofi: Optional[float] = None,
    atr_pct: Optional[float] = None,
    atr_percentile: Optional[float] = None,
    technical_score: Optional[float] = None,
    prob_gain: Optional[float] = None,
    structure_ok: Optional[bool] = None,
    regime: Optional[str] = None,
) -> None:
    """Record an entry snapshot. Call when we place a buy order."""
    if os.environ.get("EXPERIENCE_BUFFER_ENABLED", "true").lower() in ("false", "0", "no"):
        return
    path = _buffer_path()
    ts = datetime.utcnow().isoformat() + "Z"
    snap = MarketSnapshot(
        symbol=symbol,
        ts=ts,
        action="entry",
        price=price,
        qty=qty,
        reason=reason,
        z_score=z_score,
        rsi=rsi,
        macd_above_zero=macd_above_zero,
        ofi=ofi,
        atr_pct=atr_pct,
        atr_percentile=atr_percentile,
        technical_score=technical_score,
        prob_gain=prob_gain,
        structure_ok=structure_ok,
        regime=regime,
    )
    with _lock:
        _open_entries[symbol] = snap.to_dict()
    _append_snapshot(path, snap.to_dict())
    log.debug("experience_buffer entry symbol=%s reason=%s price=%.2f qty=%d", symbol, reason, price, qty)


def record_exit(
    symbol: str,
    price: float,
    qty: int,
    reason: str,
    unrealized_pl_pct: Optional[float] = None,
    *,
    z_score: Optional[float] = None,
    rsi: Optional[float] = None,
    ofi: Optional[float] = None,
    technical_score: Optional[float] = None,
    regime: Optional[str] = None,
) -> None:
    """Record an exit snapshot and link to entry (for 24h labeling)."""
    path = _buffer_path()
    if os.environ.get("EXPERIENCE_BUFFER_ENABLED", "true").lower() in ("false", "0", "no"):
        return
    ts = datetime.utcnow().isoformat() + "Z"
    snap = MarketSnapshot(
        symbol=symbol,
        ts=ts,
        action="exit",
        price=price,
        qty=qty,
        reason=reason,
        exit_reason=reason,
        unrealized_pl_pct_at_exit=unrealized_pl_pct,
        z_score=z_score,
        rsi=rsi,
        ofi=ofi,
        technical_score=technical_score,
        regime=regime,
    )
    entry = None
    with _lock:
        entry = _open_entries.pop(symbol, None)
    # Write exit row (includes entry_ts for joining in optimizer)
    row = snap.to_dict()
    if entry:
        row["entry_ts"] = entry.get("ts")
        row["entry_reason"] = entry.get("reason")
        row["entry_price"] = entry.get("price")
    _append_snapshot(path, row)
    log.debug("experience_buffer exit symbol=%s reason=%s pl_pct=%s", symbol, reason, unrealized_pl_pct)


def _append_snapshot(path: Path, row: Dict[str, Any]) -> None:
    try:
        _ensure_dir(path)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("experience_buffer write failed: %s", e)


def load_buffer(path: Optional[Path] = None, max_lines: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load all records from buffer (for strategy_optimizer)."""
    p = path or _buffer_path()
    if not p.exists():
        return []
    out = []
    try:
        with open(p) as f:
            for i, line in enumerate(f):
                if max_lines is not None and i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    except Exception as e:
        log.warning("experience_buffer load failed: %s", e)
    return out


def label_trade_24h(
    entry_ts: str,
    entry_price: float,
    exit_ts: str,
    exit_price: float,
    exit_reason: str,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> str:
    """
    Label a trade 24h after exit. Returns "success" | "false_positive" | "late_entry".
    Success: hit target (TP or scale-out). False Positive: pattern failed (stop). Late Entry: moved before we entered.
    """
    ret_pct = (exit_price - entry_price) / entry_price if entry_price and entry_price > 0 else 0.0
    if "take_profit" in exit_reason or "scale_out" in exit_reason or ret_pct >= take_profit_pct:
        return "success"
    if "stop_loss" in exit_reason or ret_pct <= -stop_loss_pct:
        return "false_positive"
    # Could add late_entry heuristic: e.g. if entry was >X% above prior low. For now use neutral.
    return "false_positive"
