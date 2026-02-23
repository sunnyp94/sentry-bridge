"""
News sentiment: one score in [-1, 1] from headline + summary using FinBERT (or VADER if FinBERT unavailable).
Used for kill-switch (bad news) in strategy.
"""
from typing import Optional

_finbert_pipeline = None
try:
    from transformers import pipeline
    _finbert_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert")
except Exception:
    pass

_vader_analyzer = None
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader_analyzer = SentimentIntensityAnalyzer()
except ImportError:
    pass


def _finbert(text: str) -> Optional[float]:
    if not _finbert_pipeline or not text or len(text.strip()) < 3:
        return None
    try:
        out = _finbert_pipeline(text[:512], truncation=True)
        if not out:
            return None
        label = ((out[0] or {}).get("label") or "").lower()
        score = (out[0] or {}).get("score", 0.5)
        if label == "positive":
            return score
        if label == "negative":
            return -score
        return 0.0
    except Exception:
        return None


def _vader(text: str) -> float:
    if not _vader_analyzer or not text:
        return 0.0
    scores = _vader_analyzer.polarity_scores(text)
    return float(scores.get("compound", 0.0))


def _single(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    s = _finbert(t)
    if s is not None:
        return s
    return _vader(t)


def score_news(payload: dict) -> float:
    """
    News sentiment from headline + summary. [-1, 1].
    Slightly weight headline over summary.
    """
    headline = (payload.get("headline") or "").strip()
    summary = (payload.get("summary") or "").strip()[:500]
    if not headline:
        return 0.0
    head_sent = _single(headline)
    if not summary or len(summary) < 20:
        return head_sent
    summary_sent = _single(summary)
    return 0.55 * head_sent + 0.45 * summary_sent
