"""
Central config: all strategy parameters. Change defaults below or set env (e.g. in .env).

Env override: any name below can be set in the environment (e.g. SENTIMENT_BUY_THRESHOLD=0.22).

Quick reference (env name = default):
  Consensus:    USE_CONSENSUS, CONSENSUS_MIN_SOURCES_POSITIVE, CONSENSUS_POSITIVE_THRESHOLD
  Daily cap:    DAILY_CAP_ENABLED, DAILY_CAP_PCT
  Buy:          SENTIMENT_BUY_THRESHOLD, SENTIMENT_BUY_MIN_CONFIDENCE, PROB_GAIN_THRESHOLD
  Sell:         SENTIMENT_SELL_THRESHOLD, PROB_GAIN_SELL_THRESHOLD
  Sizing:       STRATEGY_MAX_QTY, POSITION_SIZE_PCT, STRATEGY_REGULAR_SESSION_ONLY
  Limit orders: USE_LIMIT_ORDERS, LIMIT_ORDER_OFFSET_BPS
  Drawdown:     DRAWDOWN_HALT_ENABLED, MAX_DRAWDOWN_PCT
  Kill switch:  KILL_SWITCH_SENTIMENT_THRESHOLD, KILL_SWITCH_RETURN_THRESHOLD
  Stop loss:    STOP_LOSS_PCT
  Session:      TRADING_START_ET (09:45), NO_NEW_BUYS_AFTER_ET (15:45), FLAT_BY_CLOSE_* (flat by 4pm ET)
  Opening:      NO_TRADE_FIRST_MINUTES_AFTER_OPEN (legacy)
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
# Position sizing: buy qty = (equity * POSITION_SIZE_PCT) / price, clamped to [1, STRATEGY_MAX_QTY]. 0 = use fixed qty (1).
POSITION_SIZE_PCT = _float("POSITION_SIZE_PCT", "0")  # e.g. 0.02 = 2% of equity per position
STRATEGY_REGULAR_SESSION_ONLY = _bool("STRATEGY_REGULAR_SESSION_ONLY", "true")

# -----------------------------------------------------------------------------
# Limit orders (avoid market-order slippage; buy below mid, sell above mid)
# -----------------------------------------------------------------------------
USE_LIMIT_ORDERS = _bool("USE_LIMIT_ORDERS", "true")
LIMIT_ORDER_OFFSET_BPS = _float("LIMIT_ORDER_OFFSET_BPS", "5")  # 5 bps = 0.05%; buy at mid*(1 - 0.0005), sell at mid*(1 + 0.0005)

# -----------------------------------------------------------------------------
# Max drawdown halt (no new buys when drawdown from peak >= this %)
# -----------------------------------------------------------------------------
DRAWDOWN_HALT_ENABLED = _bool("DRAWDOWN_HALT_ENABLED", "true")
MAX_DRAWDOWN_PCT = _float("MAX_DRAWDOWN_PCT", "2.0")

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
# Session: trading starts 9:45am ET, flat by 4pm ET (no overnight)
# -----------------------------------------------------------------------------
# No new buys before this time ET (24h "HH:MM"). Default 09:45 = 9:45am ET.
TRADING_START_ET = os.environ.get("TRADING_START_ET", "09:45").strip()
# No new buys after this time ET; only closing. Default 15:45 = 3:45pm ET.
NO_NEW_BUYS_AFTER_ET = os.environ.get("NO_NEW_BUYS_AFTER_ET", "15:45").strip()
# Legacy: first N minutes after 9:30am open (ignored if TRADING_START_ET is set).
NO_TRADE_FIRST_MINUTES_AFTER_OPEN = _int("NO_TRADE_FIRST_MINUTES_AFTER_OPEN", "15")

# Flat by market close: from this time ET we close all positions so flat by 4pm. Default 15:50 = 3:50pm ET.
FLAT_BY_CLOSE_ENABLED = _bool("FLAT_BY_CLOSE_ENABLED", "true")
FLAT_BY_CLOSE_START_ET = os.environ.get("FLAT_BY_CLOSE_START_ET", "15:50").strip()
