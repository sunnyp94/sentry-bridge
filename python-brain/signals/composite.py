"""
Composite score: combines News (FinBERT/VADER) + Social (placeholder) + Momentum (return_1m/5m).
Consensus_ok = True only when at least CONSENSUS_MIN_SOURCES_POSITIVE sources are >= threshold,
so a single sensational headline doesn't drive buys; if News is positive but Social is "meh", stay cash.
"""
from dataclasses import dataclass
from typing import Dict, Optional

import config
from signals.news_sentiment import score_news  # noqa: I202


@dataclass
class CompositeResult:
    """Result of combining multiple signal sources."""
    sources: Dict[str, float]  # e.g. {"news": 0.3, "social": 0.0, "momentum": 0.2}
    composite: float           # combined score in [-1, 1]
    consensus_ok: bool         # True if >= CONSENSUS_MIN_SOURCES_POSITIVE are above threshold
    num_positive: int


def _momentum_score(payload: dict) -> float:
    """Map return_1m / return_5m to a score in [-1, 1]. No data -> 0 (neutral)."""
    ret1 = payload.get("return_1m")
    ret5 = payload.get("return_5m")
    if ret1 is None and ret5 is None:
        return 0.0
    r = 0.0
    if ret1 is not None:
        r += 0.6 * max(-1, min(1, ret1))
    if ret5 is not None:
        r += 0.4 * max(-1, min(1, ret5))
    return r


def composite_score(
    news_payload: Optional[dict] = None,
    symbol_payload: Optional[dict] = None,
    social_score: Optional[float] = None,
) -> CompositeResult:
    """
    Build composite from News + Social (optional) + Momentum (from market payload).
    consensus_ok = at least CONSENSUS_MIN_SOURCES_POSITIVE sources are >= CONSENSUS_POSITIVE_THRESHOLD.
    Social is placeholder (no data yet): pass None -> treated as 0 = "meh".
    """
    thresh = config.CONSENSUS_POSITIVE_THRESHOLD
    min_positive = config.CONSENSUS_MIN_SOURCES_POSITIVE
    use_consensus = config.USE_CONSENSUS

    sources: Dict[str, float] = {}

    # 1) News
    if news_payload:
        sources["news"] = score_news(news_payload)
    else:
        sources["news"] = 0.0

    # 2) Social (placeholder: no feed yet; plug Twitter/Reddit later)
    if social_score is not None:
        sources["social"] = social_score
    else:
        sources["social"] = 0.0

    # 3) Momentum (from price/returns)
    if symbol_payload:
        sources["momentum"] = _momentum_score(symbol_payload)
    else:
        sources["momentum"] = 0.0

    # Composite = simple average of available sources
    n = len(sources)
    composite = sum(sources.values()) / n if n else 0.0
    composite = max(-1.0, min(1.0, composite))

    # Consensus: at least min_positive sources must be "positive" (>= thresh)
    num_positive = sum(1 for v in sources.values() if v >= thresh)
    consensus_ok = (not use_consensus) or (num_positive >= min_positive)

    return CompositeResult(sources=sources, composite=composite, consensus_ok=consensus_ok, num_positive=num_positive)
