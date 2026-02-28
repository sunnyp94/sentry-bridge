"""Shared parsers used by consumer and execution (avoids duplicate logic)."""
from typing import Any, Optional


def parse_unrealized_plpc(raw: Any) -> Optional[float]:
    """
    Parse Alpaca unrealized_plpc (string or number) to decimal. None if missing/invalid.
    If value has abs > 1, treat as percent and convert to decimal (e.g. -2 -> -0.02).
    """
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if abs(v) > 1.0:
        v = v / 100.0
    return v
