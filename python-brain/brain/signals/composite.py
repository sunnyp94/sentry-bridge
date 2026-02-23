"""
Composite score: News + Social (placeholder) + Momentum + Technical (RSI + MACD + 3 patterns).
Technical = RSI, MACD, double top / inverted H&S / bull-bear flag only. No other indicators.
Consensus_ok when >= CONSENSUS_MIN_SOURCES_POSITIVE sources are >= threshold.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from .. import config


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
    price_series: Optional[List[float]] = None,
) -> CompositeResult:
    """
    Build composite from News + Social (optional) + Momentum + optional Technical (RSI).
    consensus_ok = at least CONSENSUS_MIN_SOURCES_POSITIVE sources are >= CONSENSUS_POSITIVE_THRESHOLD.
    When USE_TECHNICAL_INDICATORS=true, pass price_series (recent closes/mids) for RSI-based technical source.
    """
    thresh = config.CONSENSUS_POSITIVE_THRESHOLD
    min_positive = config.CONSENSUS_MIN_SOURCES_POSITIVE
    use_consensus = config.USE_CONSENSUS

    sources: Dict[str, float] = {}

    # 1) News (lazy-import so backtest can use technical without loading FinBERT)
    if news_payload:
        from .news_sentiment import score_news
        sources["news"] = score_news(news_payload)
    else:
        sources["news"] = 0.0

    # 2) Social (placeholder)
    if social_score is not None:
        sources["social"] = social_score
    else:
        sources["social"] = 0.0

    # 3) Momentum (from price/returns)
    if symbol_payload:
        sources["momentum"] = _momentum_score(symbol_payload)
    else:
        sources["momentum"] = 0.0

    # 4) Technical (RSI + MACD + 3 patterns) when enabled
    if config.USE_TECHNICAL_INDICATORS and price_series:
        from .technical import technical_score
        tech = technical_score(
            price_series,
            rsi_period=config.RSI_PERIOD,
            use_macd=getattr(config, "USE_MACD", True),
            macd_fast=getattr(config, "MACD_FAST", 12),
            macd_slow=getattr(config, "MACD_SLOW", 26),
            macd_signal=getattr(config, "MACD_SIGNAL", 9),
            use_patterns=getattr(config, "USE_PATTERNS", True),
            pattern_lookback=getattr(config, "PATTERN_LOOKBACK", 40),
        )
        sources["technical"] = tech if tech is not None else 0.0
    else:
        sources["technical"] = 0.0

    # Composite = simple average of available sources
    n = len(sources)
    composite = sum(sources.values()) / n if n else 0.0
    composite = max(-1.0, min(1.0, composite))

    # Consensus: at least min_positive sources must be "positive" (>= thresh)
    num_positive = sum(1 for v in sources.values() if v >= thresh)
    consensus_ok = (not use_consensus) or (num_positive >= min_positive)

    return CompositeResult(sources=sources, composite=composite, consensus_ok=consensus_ok, num_positive=num_positive)
