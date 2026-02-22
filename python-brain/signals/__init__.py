"""
Signal modules: each produces a score or scores used by the strategy.
- news_sentiment: FinBERT/VADER on news (headline + summary).
- composite: combines News + Social (placeholder) + Momentum into composite score and consensus.
"""
from signals.news_sentiment import score_news  # noqa: F401
from signals.composite import composite_score, CompositeResult  # noqa: F401
__all__ = ["score_news", "composite_score", "CompositeResult"]
