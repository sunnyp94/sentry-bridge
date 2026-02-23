"""
Signal modules: each produces a score or scores used by the strategy.
- news_sentiment: FinBERT/VADER on news (headline + summary); used for kill switch.
- technical: RSI + MACD + 3 patterns; used for Green Light pattern check.
"""
from .technical import technical_score  # noqa: F401


def score_news(payload: dict) -> float:
    """Lazy wrapper so FinBERT loads only when news scoring is used (e.g. not in backtest)."""
    from .news_sentiment import score_news as _score_news
    return _score_news(payload)


__all__ = ["score_news", "technical_score"]
