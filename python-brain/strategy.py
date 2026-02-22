"""
Strategy: decide buy/sell/hold from sentiment (news) and probability of gain (price/vol).
Uses FinBERT (finance-trained transformer) when available for headline + summary;
falls back to VADER. Uses per-symbol sentiment EMA so one noisy headline doesn't flip decisions.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Literal, Optional

log = logging.getLogger("strategy")

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # Python < 3.9

# FinBERT (transformers + torch) for finance-specific sentiment
_finbert_pipeline = None
try:
    from transformers import pipeline
    _finbert_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert")
except Exception:
    pass

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader_analyzer = SentimentIntensityAnalyzer()
except ImportError:
    _vader_analyzer = None

# Per-symbol sentiment EMA (alpha=0.3 = 30% new, 70% old) for stable decisions
SENTIMENT_EMA_ALPHA = float(os.environ.get("SENTIMENT_EMA_ALPHA", "0.35"))
_sentiment_ema: Dict[str, float] = {}

# Kill switch: when active, no buy signals (only hold or sell). Set by env, bad news, or market stress.
_kill_switch_active = os.environ.get("KILL_SWITCH", "").lower() in ("true", "1", "yes")
KILL_SWITCH_SENTIMENT_THRESHOLD = float(os.environ.get("KILL_SWITCH_SENTIMENT_THRESHOLD", "-0.50"))
KILL_SWITCH_RETURN_THRESHOLD = float(os.environ.get("KILL_SWITCH_RETURN_THRESHOLD", "-0.05"))  # e.g. -5% return
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "5.0"))  # e.g. 5 = 5% stop loss
# No new buys in first N minutes after market open (9:30 ET); sells (e.g. stop loss) still allowed.
NO_TRADE_FIRST_MINUTES_AFTER_OPEN = int(os.environ.get("NO_TRADE_FIRST_MINUTES_AFTER_OPEN", "15"))


def _sentiment_finbert(text: str) -> Optional[float]:
    """FinBERT: positive/negative/neutral -> +1 / -1 / 0. Returns None if unavailable."""
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


def _sentiment_vader(text: str) -> float:
    """VADER compound score in [-1, 1]. Positive = bullish, negative = bearish."""
    if not _vader_analyzer or not text:
        return 0.0
    scores = _vader_analyzer.polarity_scores(text)
    return float(scores.get("compound", 0.0))


def _sentiment_single(text: str) -> float:
    """Single-text sentiment. FinBERT if available, else VADER."""
    t = (text or "").strip()
    if not t:
        return 0.0
    s = _sentiment_finbert(t)
    if s is not None:
        return s
    return _sentiment_vader(t)


def sentiment_score(headline: str) -> float:
    """Legacy: sentiment from headline only. Prefer sentiment_score_from_news(payload)."""
    return _sentiment_single(headline or "")


def sentiment_score_from_news(payload: dict) -> float:
    """
    Smarter sentiment from full news: headline + summary (when present).
    Combines both with FinBERT/VADER for a stronger signal. -1 (bearish) to +1 (bullish).
    """
    headline = (payload.get("headline") or "").strip()
    summary = (payload.get("summary") or "").strip()[:500]
    if not headline:
        return 0.0
    head_sent = _sentiment_single(headline)
    if not summary or len(summary) < 20:
        return head_sent
    summary_sent = _sentiment_single(summary)
    # Slightly weight headline (more timely); summary adds context
    return 0.55 * head_sent + 0.45 * summary_sent


def update_and_get_sentiment_ema(symbol: str, raw_sentiment: float) -> float:
    """
    Update per-symbol sentiment EMA and return the smoothed value.
    Use this in decide() so one noisy headline doesn't flip buy/sell.
    """
    alpha = SENTIMENT_EMA_ALPHA
    prev = _sentiment_ema.get(symbol, raw_sentiment)
    ema = alpha * raw_sentiment + (1 - alpha) * prev
    _sentiment_ema[symbol] = ema
    return ema


def get_sentiment_ema(symbol: str) -> float:
    """Return current sentiment EMA for symbol (e.g. for stop-loss check on positions update)."""
    return _sentiment_ema.get(symbol, 0.0)


def is_kill_switch_active() -> bool:
    """True when buys are disabled (manual env, bad news, or market stress)."""
    return _kill_switch_active


def set_kill_switch_from_news(raw_sentiment: float) -> None:
    """
    If this news is very negative (bad news), activate kill switch so no new buys.
    Threshold is KILL_SWITCH_SENTIMENT_THRESHOLD (default -0.5).
    """
    global _kill_switch_active
    if not _kill_switch_active and raw_sentiment <= KILL_SWITCH_SENTIMENT_THRESHOLD:
        _kill_switch_active = True
        log.warning("kill_switch ON (bad news sentiment=%.2f)", raw_sentiment)


def set_kill_switch_from_returns(return_1m: Optional[float], return_5m: Optional[float]) -> None:
    """
    If recent returns are very negative (market tanks), activate kill switch so no new buys.
    Threshold is KILL_SWITCH_RETURN_THRESHOLD (default -5% = -0.05).
    """
    global _kill_switch_active
    thresh = KILL_SWITCH_RETURN_THRESHOLD
    if return_1m is not None and return_1m <= thresh and not _kill_switch_active:
        _kill_switch_active = True
        log.warning("kill_switch ON (market stress return_1m=%.2f%%)", return_1m * 100)
    if return_5m is not None and return_5m <= thresh and not _kill_switch_active:
        _kill_switch_active = True
        log.warning("kill_switch ON (market stress return_5m=%.2f%%)", return_5m * 100)


def set_kill_switch(active: bool) -> None:
    """Manually set kill switch (e.g. from env at startup or external signal)."""
    global _kill_switch_active
    _kill_switch_active = active


def is_in_opening_no_trade_window() -> bool:
    """
    True if we're in the first NO_TRADE_FIRST_MINUTES_AFTER_OPEN minutes after market open (9:30 AM ET).
    Used to avoid new buys during the volatile opening; sells (e.g. stop loss) still allowed.
    """
    if NO_TRADE_FIRST_MINUTES_AFTER_OPEN <= 0:
        return False
    if ZoneInfo is None:
        return False
    try:
        et = datetime.now(ZoneInfo("America/New_York"))
        # Weekday 0=Mon .. 4=Fri
        if et.weekday() > 4:
            return False
        # 9:30 AM = minute 0 of regular session; 9:44 = minute 14
        if et.hour != 9:
            return False
        if et.minute < 30:
            return False
        return et.minute < 30 + NO_TRADE_FIRST_MINUTES_AFTER_OPEN  # 9:30..9:44 for 15 min
    except Exception:
        return False


def probability_gain(payload: dict) -> float:
    """
    Heuristic probability of trading for a gain [0, 1] from recent returns and volatility.
    Uses return_1m, return_5m, annualized_vol_30d when present.
    """
    ret1 = payload.get("return_1m")
    ret5 = payload.get("return_5m")
    vol = payload.get("annualized_vol_30d")
    if ret1 is None and ret5 is None and vol is None:
        return 0.5  # no data → neutral
    # Prefer positive short-term momentum; penalize very high vol
    r = 0.0
    if ret1 is not None:
        r += 0.6 * (max(-1, min(1, ret1)) + 1) / 2  # map [-1,1] -> [0,1]
    if ret5 is not None:
        r += 0.4 * (max(-1, min(1, ret5)) + 1) / 2
    if r == 0:
        r = 0.5
    # Reduce prob if volatility is very high (e.g. > 50% annualized)
    if vol is not None and vol > 0.5:
        r *= 0.7
    return min(1.0, max(0.0, r))


@dataclass
class Decision:
    action: Literal["hold", "buy", "sell"]
    symbol: str
    qty: int = 0
    reason: str = ""


def decide(
    symbol: str,
    sentiment: float,
    prob_gain: float,
    position_qty: int,
    session: str,
    unrealized_pl_pct: Optional[float] = None,
) -> Decision:
    """
    Smarter strategy: sentiment should be EMA-smoothed from the consumer.
    Kill switch: when active, no buys (only hold or sell).
    5% stop loss: sell when unrealized_pl_pct <= -STOP_LOSS_PCT (e.g. -5%).
    """
    buy_thresh = float(os.environ.get("SENTIMENT_BUY_THRESHOLD", "0.18"))
    buy_min_confidence = float(os.environ.get("SENTIMENT_BUY_MIN_CONFIDENCE", "0.25"))
    prob_thresh = float(os.environ.get("PROB_GAIN_THRESHOLD", "0.54"))
    sell_sentiment_thresh = float(os.environ.get("SENTIMENT_SELL_THRESHOLD", "-0.18"))
    prob_sell_thresh = float(os.environ.get("PROB_GAIN_SELL_THRESHOLD", "0.42"))
    max_qty = int(os.environ.get("STRATEGY_MAX_QTY", "2"))
    stop_loss_pct = STOP_LOSS_PCT / 100.0  # e.g. 0.05 for 5%
    trade_only_regular = os.environ.get("STRATEGY_REGULAR_SESSION_ONLY", "true").lower() in ("true", "1", "yes")
    if trade_only_regular and session != "regular":
        return Decision("hold", symbol, 0, f"session={session}")

    have_position = position_qty > 0

    # 5% stop loss: sell when position is down >= STOP_LOSS_PCT (e.g. 5%)
    if have_position and unrealized_pl_pct is not None and unrealized_pl_pct <= -stop_loss_pct:
        qty = min(abs(position_qty), max_qty)
        return Decision("sell", symbol, qty, f"stop_loss {unrealized_pl_pct*100:.2f}%")

    # Sell: sustained bearish sentiment (EMA) or we have position and prob_gain dropped
    if have_position and (sentiment <= sell_sentiment_thresh or prob_gain < prob_sell_thresh):
        qty = min(abs(position_qty), max_qty)
        return Decision("sell", symbol, qty, f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")

    # Buy: kill switch blocks all buys (market tanks, bad news, or manual)
    if is_kill_switch_active():
        return Decision("hold", symbol, 0, "kill_switch_active")

    # Buy: no new buys in first N minutes after market open (9:30–9:44 ET); avoid opening volatility
    if not have_position and is_in_opening_no_trade_window():
        return Decision("hold", symbol, 0, "opening_15min_no_trade")

    # Buy: clear bullish conviction (sentiment above threshold and above min confidence) + prob_gain
    if not have_position and sentiment >= buy_thresh and sentiment >= buy_min_confidence and prob_gain >= prob_thresh:
        return Decision("buy", symbol, min(1, max_qty), f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")

    return Decision("hold", symbol, 0, f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")
