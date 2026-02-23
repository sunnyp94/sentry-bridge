"""
Signal modules: each produces a score or scores used by the strategy.
- news_sentiment: FinBERT/VADER on news (headline + summary).
- composite: combines News + Social (placeholder) + Momentum into composite score and consensus.
"""
from .composite import composite_score, CompositeResult  # noqa: F401
from .technical import technical_score  # noqa: F401


def score_news(payload: dict) -> float:
    """Lazy wrapper so FinBERT loads only when news scoring is used (e.g. not in backtest)."""
    from .news_sentiment import score_news as _score_news
    return _score_news(payload)


__all__ = ["score_news", "composite_score", "CompositeResult", "technical_score"]
