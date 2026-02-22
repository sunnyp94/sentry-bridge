"""
Central config: all strategy parameters. Change defaults below or set env (e.g. in .env).

Env override: any name below can be set in the environment (e.g. SENTIMENT_BUY_THRESHOLD=0.22).

Quick reference (env name = default):
  Consensus:    USE_CONSENSUS, CONSENSUS_MIN_SOURCES_POSITIVE, CONSENSUS_POSITIVE_THRESHOLD
  Daily cap:    DAILY_CAP_ENABLED, DAILY_CAP_PCT
  Buy:          SENTIMENT_BUY_THRESHOLD, SENTIMENT_BUY_MIN_CONFIDENCE, PROB_GAIN_THRESHOLD
  Sell:         SENTIMENT_SELL_THRESHOLD, PROB_GAIN_SELL_THRESHOLD
  Sizing:       STRATEGY_MAX_QTY, STRATEGY_REGULAR_SESSION_ONLY
  Kill switch:  KILL_SWITCH_SENTIMENT_THRESHOLD, KILL_SWITCH_RETURN_THRESHOLD
  Stop loss:    STOP_LOSS_PCT
  Opening:      NO_TRADE_FIRST_MINUTES_AFTER_OPEN
  Sentiment:    SENTIMENT_EMA_ALPHA
"""
import os


def _bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() in ("true", "1", "yes")


def _float(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


# -----------------------------------------------------------------------------
# Consensus (require multiple sources positive before allowing buy)
# -----------------------------------------------------------------------------
USE_CONSENSUS = _bool("USE_CONSENSUS", "true")
CONSENSUS_MIN_SOURCES_POSITIVE = _int("CONSENSUS_MIN_SOURCES_POSITIVE", "2")   # e.g. 2 of 3 (news, social, momentum)
CONSENSUS_POSITIVE_THRESHOLD = _float("CONSENSUS_POSITIVE_THRESHOLD", "0.15")  # score >= this counts as "positive"

# -----------------------------------------------------------------------------
# Daily cap (lock in gains — no new buys when daily PnL >= threshold)
# -----------------------------------------------------------------------------
DAILY_CAP_ENABLED = _bool("DAILY_CAP_ENABLED", "true")
DAILY_CAP_PCT = _float("DAILY_CAP_PCT", "0.2")  # 0.2% = stop new buys for the day

# -----------------------------------------------------------------------------
# Buy thresholds (all required for a buy: sentiment EMA, min confidence, prob_gain)
# -----------------------------------------------------------------------------
SENTIMENT_EMA_ALPHA = _float("SENTIMENT_EMA_ALPHA", "0.35")
SENTIMENT_BUY_THRESHOLD = _float("SENTIMENT_BUY_THRESHOLD", "0.18")
SENTIMENT_BUY_MIN_CONFIDENCE = _float("SENTIMENT_BUY_MIN_CONFIDENCE", "0.25")
PROB_GAIN_THRESHOLD = _float("PROB_GAIN_THRESHOLD", "0.54")

# -----------------------------------------------------------------------------
# Sell thresholds (bearish sentiment or prob_gain below threshold)
# -----------------------------------------------------------------------------
SENTIMENT_SELL_THRESHOLD = _float("SENTIMENT_SELL_THRESHOLD", "-0.18")
PROB_GAIN_SELL_THRESHOLD = _float("PROB_GAIN_SELL_THRESHOLD", "0.42")

# -----------------------------------------------------------------------------
# Sizing and session
# -----------------------------------------------------------------------------
STRATEGY_MAX_QTY = _int("STRATEGY_MAX_QTY", "2")
STRATEGY_REGULAR_SESSION_ONLY = _bool("STRATEGY_REGULAR_SESSION_ONLY", "true")

# -----------------------------------------------------------------------------
# Kill switch (no new buys when very bad news or sharp negative returns)
# -----------------------------------------------------------------------------
KILL_SWITCH_SENTIMENT_THRESHOLD = _float("KILL_SWITCH_SENTIMENT_THRESHOLD", "-0.50")
KILL_SWITCH_RETURN_THRESHOLD = _float("KILL_SWITCH_RETURN_THRESHOLD", "-0.05")

# -----------------------------------------------------------------------------
# Stop loss (sell when position unrealized PnL <= -this %)
# -----------------------------------------------------------------------------
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", "5.0")

# -----------------------------------------------------------------------------
# Opening window (no new buys in first N minutes after market open)
# -----------------------------------------------------------------------------
NO_TRADE_FIRST_MINUTES_AFTER_OPEN = _int("NO_TRADE_FIRST_MINUTES_AFTER_OPEN", "15")
