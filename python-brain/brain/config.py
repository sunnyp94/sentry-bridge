"""
Central config: all thresholds and feature flags from environment variables.
Edit this file or set env (e.g. in .env) to tune strategy without changing strategy.py.
Used by: strategy, signals.composite, rules.daily_cap.
"""
import os


def _bool(name: str, default: str = "false") -> bool:
    """Parse env as boolean (true/1/yes -> True)."""
    return os.environ.get(name, default).lower() in ("true", "1", "yes")


def _float(name: str, default: str) -> float:
    """Parse env as float; on error return default."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _int(name: str, default: str) -> int:
    """Parse env as int; on error return default."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


# ----- Signals (composite score) -----
# Use 3-source consensus: require at least N sources "positive" to allow buy (avoids single sensational headline).
USE_CONSENSUS = _bool("USE_CONSENSUS", "true")
CONSENSUS_MIN_SOURCES_POSITIVE = _int("CONSENSUS_MIN_SOURCES_POSITIVE", "2")  # e.g. 2 of 3
CONSENSUS_POSITIVE_THRESHOLD = _float("CONSENSUS_POSITIVE_THRESHOLD", "0.15")  # score >= this = "positive"

# ----- Daily cap (lock in gains) -----
# When daily PnL >= this %, stop new buys for the day. "Most bots lose because they keep trading after they've won."
DAILY_CAP_PCT = _float("DAILY_CAP_PCT", "0.2")  # 0.2% = lock in gains
DAILY_CAP_ENABLED = _bool("DAILY_CAP_ENABLED", "true")

# ----- Sentiment / strategy -----
SENTIMENT_EMA_ALPHA = _float("SENTIMENT_EMA_ALPHA", "0.35")
SENTIMENT_BUY_THRESHOLD = _float("SENTIMENT_BUY_THRESHOLD", "0.18")
SENTIMENT_BUY_MIN_CONFIDENCE = _float("SENTIMENT_BUY_MIN_CONFIDENCE", "0.25")
SENTIMENT_SELL_THRESHOLD = _float("SENTIMENT_SELL_THRESHOLD", "-0.18")
PROB_GAIN_THRESHOLD = _float("PROB_GAIN_THRESHOLD", "0.54")
PROB_GAIN_SELL_THRESHOLD = _float("PROB_GAIN_SELL_THRESHOLD", "0.42")
STRATEGY_MAX_QTY = _int("STRATEGY_MAX_QTY", "2")
STRATEGY_REGULAR_SESSION_ONLY = _bool("STRATEGY_REGULAR_SESSION_ONLY", "true")

# ----- Kill switch -----
KILL_SWITCH_SENTIMENT_THRESHOLD = _float("KILL_SWITCH_SENTIMENT_THRESHOLD", "-0.50")
KILL_SWITCH_RETURN_THRESHOLD = _float("KILL_SWITCH_RETURN_THRESHOLD", "-0.05")

# ----- Stop loss -----
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", "5.0")

# ----- Opening window -----
NO_TRADE_FIRST_MINUTES_AFTER_OPEN = _int("NO_TRADE_FIRST_MINUTES_AFTER_OPEN", "15")
