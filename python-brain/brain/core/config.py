"""
Central config: all strategy parameters. Change defaults below or set env (e.g. in .env).

Current strategy: Green Light only (4-point checklist + prob_gain). Entry/exit use keys referenced
in brain/strategy.py. Keys marked (reserved) are defined for env compatibility but not read by the
current strategy — use them when adding plug-in rules (e.g. sentiment entry, VWAP/Z-score filters).
"""
import os


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
# Pro-style defaults. Override numeric/time/path params in .env; no feature flags in env.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Daily profit target: soft-cap trailing stop
# -----------------------------------------------------------------------------
DAILY_CAP_ENABLED = True
DAILY_PROFIT_TARGET_PCT = 0.5
DAILY_CAP_PCT = 0.5
SOFT_CAP_TRAILING_PCT = 0.1
DAILY_LOSS_CAP_PCT = _float("DAILY_LOSS_CAP_PCT", "1.0")
DAILY_DRAWDOWN_CIRCUIT_BREAKER_PCT = _float("DAILY_DRAWDOWN_CIRCUIT_BREAKER_PCT", "5.0")
FLAT_WHEN_DAILY_TARGET_HIT = False  # let winners run; only stop new buys when target hit

# -----------------------------------------------------------------------------
# Buy thresholds
# -----------------------------------------------------------------------------
SENTIMENT_EMA_ALPHA = _float("SENTIMENT_EMA_ALPHA", "0.35")
SENTIMENT_BUY_THRESHOLD = _float("SENTIMENT_BUY_THRESHOLD", "0.10")
SENTIMENT_BUY_MIN_CONFIDENCE = _float("SENTIMENT_BUY_MIN_CONFIDENCE", "0.18")
PROB_GAIN_THRESHOLD = _float("PROB_GAIN_THRESHOLD", "0.12")

# -----------------------------------------------------------------------------
# Sell thresholds (reserved for plug-in)
# -----------------------------------------------------------------------------
EXIT_ONLY_STOP_AND_TP = True
SENTIMENT_SELL_THRESHOLD = _float("SENTIMENT_SELL_THRESHOLD", "-0.32")
PROB_GAIN_SELL_THRESHOLD = _float("PROB_GAIN_SELL_THRESHOLD", "0.32")

# -----------------------------------------------------------------------------
# Sizing and session
# -----------------------------------------------------------------------------
STRATEGY_MAX_QTY = _int("STRATEGY_MAX_QTY", "12")
RISK_PCT_PER_TRADE = _float("RISK_PCT_PER_TRADE", "0")
POSITION_SIZE_PCT = _float("POSITION_SIZE_PCT", "0.05")
STRATEGY_REGULAR_SESSION_ONLY = True
ORDER_COOLDOWN_SEC = _int("ORDER_COOLDOWN_SEC", "30")
STRATEGY_INTERVAL_SEC = _int("STRATEGY_INTERVAL_SEC", "45")
CORRELATION_CHECK_ENABLED = False
CORRELATION_THRESHOLD = _float("CORRELATION_THRESHOLD", "0.7")
CORRELATION_SIZE_REDUCTION = _float("CORRELATION_SIZE_REDUCTION", "0.5")

# -----------------------------------------------------------------------------
# Limit orders
# -----------------------------------------------------------------------------
USE_LIMIT_ORDERS = True
LIMIT_ORDER_OFFSET_BPS = _float("LIMIT_ORDER_OFFSET_BPS", "5")

# -----------------------------------------------------------------------------
# Max drawdown halt
# -----------------------------------------------------------------------------
DRAWDOWN_HALT_ENABLED = True
MAX_DRAWDOWN_PCT = _float("MAX_DRAWDOWN_PCT", "5.0")

# -----------------------------------------------------------------------------
# Technical: RSI + MACD + patterns
# -----------------------------------------------------------------------------
USE_TECHNICAL_INDICATORS = True
RSI_PERIOD = _int("RSI_PERIOD", "14")
USE_MACD = True
MACD_FAST = _int("MACD_FAST", "12")
MACD_SLOW = _int("MACD_SLOW", "26")
MACD_SIGNAL = _int("MACD_SIGNAL", "9")
USE_PATTERNS = True
PATTERN_LOOKBACK = _int("PATTERN_LOOKBACK", "40")

# -----------------------------------------------------------------------------
# Trend filter and Regime
# -----------------------------------------------------------------------------
TREND_FILTER_ENABLED = True
TREND_SMA_PERIOD = _int("TREND_SMA_PERIOD", "20")
REGIME_FILTER_ENABLED = True
REGIME_LOOKBACK = _int("REGIME_LOOKBACK", "20")
REGIME_TREND_SMA_PERIOD = _int("REGIME_TREND_SMA_PERIOD", "20")
REGIME_VOLATILITY_PCT = _float("REGIME_VOLATILITY_PCT", "70")

# -----------------------------------------------------------------------------
# Kill switch
# -----------------------------------------------------------------------------
KILL_SWITCH_SENTIMENT_THRESHOLD = _float("KILL_SWITCH_SENTIMENT_THRESHOLD", "-0.50")
KILL_SWITCH_RETURN_THRESHOLD = _float("KILL_SWITCH_RETURN_THRESHOLD", "-0.05")

# -----------------------------------------------------------------------------
# Stop loss and take profit
# -----------------------------------------------------------------------------
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", "1.0")
TAKE_PROFIT_PCT = _float("TAKE_PROFIT_PCT", "2.0")

# -----------------------------------------------------------------------------
# Robustness
# -----------------------------------------------------------------------------
VOL_MAX_FOR_ENTRY = _float("VOL_MAX_FOR_ENTRY", "0")
BREAKEVEN_ACTIVATION_PCT = _float("BREAKEVEN_ACTIVATION_PCT", "1.0")
TRAILING_STOP_ACTIVATION_PCT = _float("TRAILING_STOP_ACTIVATION_PCT", "2.0")
TRAILING_STOP_PCT = _float("TRAILING_STOP_PCT", "1.0")
SCALE_OUT_ENABLED = True
SCALE_OUT_LEVELS_PCT = os.environ.get("SCALE_OUT_LEVELS_PCT", "1,2,3")
SCALE_OUT_PCT_PER_LEVEL = _float("SCALE_OUT_PCT_PER_LEVEL", "25")
MAX_HOLD_DAYS = _int("MAX_HOLD_DAYS", "10")

# -----------------------------------------------------------------------------
# Microstructure / volatility
# -----------------------------------------------------------------------------
USE_ATR_STOP = True
ATR_PERIOD = _int("ATR_PERIOD", "20")
ATR_STOP_MULTIPLE = _float("ATR_STOP_MULTIPLE", "2.0")
VWAP_LOOKBACK = _int("VWAP_LOOKBACK", "20")
USE_VWAP_ANCHOR = True
VWAP_LONG_ONLY_BELOW = True
VWAP_FAIR_VALUE_BAND_STD = _float("VWAP_FAIR_VALUE_BAND_STD", "1.0")
VWAP_MEAN_REVERSION_PCT = _float("VWAP_MEAN_REVERSION_PCT", "2.0")
USE_ZSCORE_MEAN_REVERSION = True
ZSCORE_MEAN_REVERSION_BUY = _float("ZSCORE_MEAN_REVERSION_BUY", "-2.0")
ZSCORE_TRIGGER_ENTRY = _float("ZSCORE_TRIGGER_ENTRY", "-2.0")
ZSCORE_PERIOD = _int("ZSCORE_PERIOD", "20")
ATR_PERCENTILE_MIN = _float("ATR_PERCENTILE_MIN", "10")
ATR_PERCENTILE_MAX = _float("ATR_PERCENTILE_MAX", "90")
ATR_PERCENTILE_LOOKBACK = _int("ATR_PERCENTILE_LOOKBACK", "60")
MICROSTRUCTURE_ENTRY_MODE = True
USE_OFI = True
OFI_SURGE_FOR_ENTRY = _float("OFI_SURGE_FOR_ENTRY", "0.0")
OFI_WINDOW_TRADES = _int("OFI_WINDOW_TRADES", "100")
TAKE_PROFIT_AT_VWAP = True
BREAKEVEN_AT_HALFWAY_TO_VWAP = True
TRAILING_ATR_ABOVE_VWAP = True
TRAILING_ATR_MULTIPLE = _float("TRAILING_ATR_MULTIPLE", "1.5")

# -----------------------------------------------------------------------------
# Green Light
# -----------------------------------------------------------------------------
STRUCTURE_EMA_PERIOD = _int("STRUCTURE_EMA_PERIOD", "50")
CONFLUENCE_Z_MAX = _float("CONFLUENCE_Z_MAX", "0.5")
TAKE_PROFIT_R_MULTIPLE = _float("TAKE_PROFIT_R_MULTIPLE", "1.2")
RSI_OVERBOUGHT = _float("RSI_OVERBOUGHT", "80")
RSI_OVERBOUGHT_OFI_MIN = _float("RSI_OVERBOUGHT_OFI_MIN", "0.10")
TECHNICAL_MIN_FOR_ENTRY = _float("TECHNICAL_MIN_FOR_ENTRY", "-0.35")
SCALP_SKIP_MOMENTUM = True

# -----------------------------------------------------------------------------
# Opportunity Engine (screener / discovery)
# -----------------------------------------------------------------------------
OPPORTUNITY_ENGINE_ENABLED = True
SCREENER_TOP_N = _int("SCREENER_TOP_N", "5")
SCREENER_Z_THRESHOLD = _float("SCREENER_Z_THRESHOLD", "1.2")
SCREENER_VOLUME_SPIKE_PCT = _float("SCREENER_VOLUME_SPIKE_PCT", "10")
SCREENER_MIN_VOLUME = _int("SCREENER_MIN_VOLUME", "2000000")
SCREENER_UNIVERSE = os.environ.get("SCREENER_UNIVERSE", "r2000_sp500_nasdaq100")
SCREENER_LOOKBACK_DAYS = _int("SCREENER_LOOKBACK_DAYS", "35")
SCREENER_CHUNK_SIZE = _int("SCREENER_CHUNK_SIZE", "100")
SCREENER_CHUNK_DELAY_SEC = _float("SCREENER_CHUNK_DELAY_SEC", "0.5")
SCREENER_PARALLEL_CHUNKS = _int("SCREENER_PARALLEL_CHUNKS", "4")
ACTIVE_SYMBOLS_FILE = os.environ.get("ACTIVE_SYMBOLS_FILE", "").strip()
SCREENER_RUN_AT_ET = os.environ.get("SCREENER_RUN_AT_ET", "09:30").strip()

# -----------------------------------------------------------------------------
# Two-Stage: Discovery (7:00–9:30 ET) → Execution (9:30+)
# -----------------------------------------------------------------------------
DISCOVERY_ENABLED = True
DISCOVERY_START_ET = os.environ.get("DISCOVERY_START_ET", "07:00").strip()
DISCOVERY_END_ET = os.environ.get("DISCOVERY_END_ET", "09:30").strip()
DISCOVERY_INTERVAL_MIN = _int("DISCOVERY_INTERVAL_MIN", "5")
DISCOVERY_TOP_N = _int("DISCOVERY_TOP_N", "10")
MARKET_CLOSE_ET = os.environ.get("MARKET_CLOSE_ET", "16:00").strip()
TWO_STAGE_ENTRY_ATR_BELOW_VWAP = _float("TWO_STAGE_ENTRY_ATR_BELOW_VWAP", "1.0")
SCALE_OUT_50_AT_VWAP = True
PORTFOLIO_HEALTH_CHECK_ET = os.environ.get("PORTFOLIO_HEALTH_CHECK_ET", "16:00").strip()

# -----------------------------------------------------------------------------
# Session: overnight carry
# -----------------------------------------------------------------------------
NO_NEW_BUYS_AFTER_ET = os.environ.get("NO_NEW_BUYS_AFTER_ET", "15:45").strip()
OVERNIGHT_CARRY_ENABLED = True
CLOSE_LOSSES_BY_ET = os.environ.get("CLOSE_LOSSES_BY_ET", "15:50").strip()
# Smart Position Management: EOD prune at 15:50 ET — close only losers (unrealized_plpc < threshold)
EOD_PRUNE_AT_ET = os.environ.get("EOD_PRUNE_AT_ET", "15:50").strip()
EOD_PRUNE_STOP_LOSS_PCT = _float("EOD_PRUNE_STOP_LOSS_PCT", "-2.0")  # -2% (decimal -0.02)

# -----------------------------------------------------------------------------
# Strategy optimizer (always runs after market close)
# -----------------------------------------------------------------------------
OPTIMIZER_RUN_AT_ET = os.environ.get("OPTIMIZER_RUN_AT_ET", "16:05").strip()
EXPERIENCE_BUFFER_ENABLED = True
SHADOW_STRATEGY_ENABLED = True
