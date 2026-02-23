"""
Central config: all strategy parameters. Change defaults below or set env (e.g. in .env).

Env override: any name below can be set in the environment (e.g. SENTIMENT_BUY_THRESHOLD=0.22).

Quick reference (env name = default):
  Consensus:    USE_CONSENSUS, CONSENSUS_MIN_SOURCES_POSITIVE, CONSENSUS_POSITIVE_THRESHOLD
  Daily cap:    DAILY_CAP_ENABLED, DAILY_CAP_PCT, DAILY_LOSS_CAP_PCT
  Buy:          SENTIMENT_BUY_THRESHOLD, SENTIMENT_BUY_MIN_CONFIDENCE, PROB_GAIN_THRESHOLD
  Sell:         EXIT_ONLY_STOP_AND_TP, SENTIMENT_SELL_THRESHOLD, PROB_GAIN_SELL_THRESHOLD
  Sizing:       STRATEGY_MAX_QTY, POSITION_SIZE_PCT, STRATEGY_REGULAR_SESSION_ONLY
  Limit orders: USE_LIMIT_ORDERS, LIMIT_ORDER_OFFSET_BPS
  Drawdown:     DRAWDOWN_HALT_ENABLED, MAX_DRAWDOWN_PCT
  Kill switch:  KILL_SWITCH_SENTIMENT_THRESHOLD, KILL_SWITCH_RETURN_THRESHOLD
  Stop loss:    STOP_LOSS_PCT, TAKE_PROFIT_PCT (0=off)
  Robustness:   VOL_MAX_FOR_ENTRY, BREAKEVEN_ACTIVATION_PCT, TRAILING_STOP_*, MAX_HOLD_DAYS
  Microstructure: USE_ATR_STOP, ATR_PERIOD, ATR_STOP_MULTIPLE | VWAP_* | ZSCORE_* (pro-style indicators)
  Session:      NO_NEW_BUYS_AFTER_ET (15:45)
  Technical:    RSI + MACD + 3 patterns only (USE_TECHNICAL_INDICATORS, RSI_PERIOD, USE_MACD, USE_PATTERNS, PATTERN_LOOKBACK)
  Trend:        TREND_FILTER_ENABLED, TREND_SMA_PERIOD (only long when price > SMA)
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
# Pro-style defaults: cut losers fast (tight stop), let winners run (take-profit),
# stricter entry (fewer trades), hold through noise (wider sell bands), trend filter.
# Override any in .env.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Consensus (require multiple sources positive — avoid single-signal entries)
# -----------------------------------------------------------------------------
USE_CONSENSUS = _bool("USE_CONSENSUS", "true")
CONSENSUS_MIN_SOURCES_POSITIVE = _int("CONSENSUS_MIN_SOURCES_POSITIVE", "2")   # 2 of 3 (news, social, momentum)
CONSENSUS_POSITIVE_THRESHOLD = _float("CONSENSUS_POSITIVE_THRESHOLD", "0.15")  # score >= this = "positive"

# -----------------------------------------------------------------------------
# Daily profit target: make a small gain and stop (no new buys; optionally flat all)
# Daily loss cap: no new buys when daily PnL <= -X% (stop the bleeding)
# -----------------------------------------------------------------------------
DAILY_CAP_ENABLED = _bool("DAILY_CAP_ENABLED", "true")
# When portfolio is up this much for the day: no new buys (lock in gains, don't add risk). Let winners run unless FLAT_WHEN_DAILY_TARGET_HIT.
DAILY_PROFIT_TARGET_PCT = _float("DAILY_PROFIT_TARGET_PCT", "0.25")  # 0.25% daily = no new buys; existing positions keep running
DAILY_CAP_PCT = _float("DAILY_CAP_PCT", "0.25")  # no new buys when daily PnL >= this
DAILY_LOSS_CAP_PCT = _float("DAILY_LOSS_CAP_PCT", "1.0")  # -1% daily loss = no new buys
# Daily drawdown circuit breaker: pause ALL trading if daily loss >= this % (black-swan protection)
DAILY_DRAWDOWN_CIRCUIT_BREAKER_PCT = _float("DAILY_DRAWDOWN_CIRCUIT_BREAKER_PCT", "5.0")  # 5% = pro standard
# When True, also close all positions when daily target hit. Default false = let winners run (only stop new buys).
FLAT_WHEN_DAILY_TARGET_HIT = _bool("FLAT_WHEN_DAILY_TARGET_HIT", "false")

# -----------------------------------------------------------------------------
# Buy thresholds (stricter = fewer, higher-quality mean-reversion entries)
# -----------------------------------------------------------------------------
SENTIMENT_EMA_ALPHA = _float("SENTIMENT_EMA_ALPHA", "0.35")
# Balanced: enough entries for mean reversion, not noise
SENTIMENT_BUY_THRESHOLD = _float("SENTIMENT_BUY_THRESHOLD", "0.10")
SENTIMENT_BUY_MIN_CONFIDENCE = _float("SENTIMENT_BUY_MIN_CONFIDENCE", "0.18")
PROB_GAIN_THRESHOLD = _float("PROB_GAIN_THRESHOLD", "0.50")

# -----------------------------------------------------------------------------
# Sell thresholds (hold through noise — exit only on clear failure or take-profit/stop)
# EXIT_ONLY_STOP_AND_TP: when true, only exit on stop-loss or take-profit (no sentiment/prob exit)
# -----------------------------------------------------------------------------
EXIT_ONLY_STOP_AND_TP = _bool("EXIT_ONLY_STOP_AND_TP", "true")  # force R:R; no whipsaw exit
SENTIMENT_SELL_THRESHOLD = _float("SENTIMENT_SELL_THRESHOLD", "-0.32")
PROB_GAIN_SELL_THRESHOLD = _float("PROB_GAIN_SELL_THRESHOLD", "0.32")

# -----------------------------------------------------------------------------
# Sizing and session (Pillar 1: Risk First)
# -----------------------------------------------------------------------------
STRATEGY_MAX_QTY = _int("STRATEGY_MAX_QTY", "4")  # higher risk: allow larger position per symbol
# Position sizing: when RISK_PCT_PER_TRADE > 0, size by risk (qty = risk_amount / (ATR*mult)); else use POSITION_SIZE_PCT.
RISK_PCT_PER_TRADE = _float("RISK_PCT_PER_TRADE", "2.0")  # 2% capital at risk per trade (higher risk / reward)
POSITION_SIZE_PCT = _float("POSITION_SIZE_PCT", "0.02")  # 2% of equity per position when risk sizing off
STRATEGY_REGULAR_SESSION_ONLY = _bool("STRATEGY_REGULAR_SESSION_ONLY", "true")
# Kelly Criterion: scale risk by optimal fraction from win rate and avg win/loss (cap at KELLY_FRACTION_CAP)
KELLY_SIZING_ENABLED = _bool("KELLY_SIZING_ENABLED", "false")
KELLY_FRACTION_CAP = _float("KELLY_FRACTION_CAP", "0.25")  # max fraction of capital per trade (quarter-Kelly)
KELLY_LOOKBACK_TRADES = _int("KELLY_LOOKBACK_TRADES", "50")  # use last N round-trips for W and R
# Correlation: reduce size when adding position in symbol highly correlated with existing positions
CORRELATION_CHECK_ENABLED = _bool("CORRELATION_CHECK_ENABLED", "false")
CORRELATION_THRESHOLD = _float("CORRELATION_THRESHOLD", "0.7")  # if corr > this with any open position, reduce size
CORRELATION_SIZE_REDUCTION = _float("CORRELATION_SIZE_REDUCTION", "0.5")  # multiply qty by this when correlated

# -----------------------------------------------------------------------------
# Limit orders (reduce slippage; buy below mid, sell above mid)
# -----------------------------------------------------------------------------
USE_LIMIT_ORDERS = _bool("USE_LIMIT_ORDERS", "true")
LIMIT_ORDER_OFFSET_BPS = _float("LIMIT_ORDER_OFFSET_BPS", "5")

# -----------------------------------------------------------------------------
# Max drawdown halt (no new buys when drawdown from peak >= this % — avoid revenge trading)
# -----------------------------------------------------------------------------
DRAWDOWN_HALT_ENABLED = _bool("DRAWDOWN_HALT_ENABLED", "true")
MAX_DRAWDOWN_PCT = _float("MAX_DRAWDOWN_PCT", "2.5")

# -----------------------------------------------------------------------------
# Technical: RSI + MACD + 3 patterns (double top, inverted H&S, bull/bear flag) only
# -----------------------------------------------------------------------------
USE_TECHNICAL_INDICATORS = _bool("USE_TECHNICAL_INDICATORS", "true")
RSI_PERIOD = _int("RSI_PERIOD", "14")
USE_MACD = _bool("USE_MACD", "true")
MACD_FAST = _int("MACD_FAST", "12")
MACD_SLOW = _int("MACD_SLOW", "26")
MACD_SIGNAL = _int("MACD_SIGNAL", "9")
USE_PATTERNS = _bool("USE_PATTERNS", "true")
PATTERN_LOOKBACK = _int("PATTERN_LOOKBACK", "40")

# -----------------------------------------------------------------------------
# Trend filter and Regime (off by default; clean focus on RSI/MACD/patterns)
# -----------------------------------------------------------------------------
TREND_FILTER_ENABLED = _bool("TREND_FILTER_ENABLED", "false")
TREND_SMA_PERIOD = _int("TREND_SMA_PERIOD", "20")
# Regime filter: only fire mean-reversion signals in choppy regime, trend signals in trending regime
REGIME_FILTER_ENABLED = _bool("REGIME_FILTER_ENABLED", "false")
REGIME_LOOKBACK = _int("REGIME_LOOKBACK", "20")  # bars for trend/volatility detection
REGIME_TREND_SMA_PERIOD = _int("REGIME_TREND_SMA_PERIOD", "20")
REGIME_VOLATILITY_PCT = _float("REGIME_VOLATILITY_PCT", "70")  # above this percentile = choppy → mean reversion

# -----------------------------------------------------------------------------
# Global filter: SPY 200-day MA (when SPY < 200 MA: more cautious on longs, more aggressive on shorts when added)
# -----------------------------------------------------------------------------
SPY_200MA_REGIME_ENABLED = _bool("SPY_200MA_REGIME_ENABLED", "false")
# When SPY below 200 MA: require stricter Z for long entry (e.g. -2.8 instead of -2.5)
SPY_BELOW_200MA_Z_TIGHTEN = _float("SPY_BELOW_200MA_Z_TIGHTEN", "-2.8")
# When SPY below 200 MA: multiply long position size by this (e.g. 0.5 = half size)
SPY_BELOW_200MA_LONG_SIZE_MULTIPLIER = _float("SPY_BELOW_200MA_LONG_SIZE_MULTIPLIER", "0.5")

# -----------------------------------------------------------------------------
# Kill switch (no new buys when very bad news or sharp negative returns)
# -----------------------------------------------------------------------------
KILL_SWITCH_SENTIMENT_THRESHOLD = _float("KILL_SWITCH_SENTIMENT_THRESHOLD", "-0.50")
KILL_SWITCH_RETURN_THRESHOLD = _float("KILL_SWITCH_RETURN_THRESHOLD", "-0.05")

# -----------------------------------------------------------------------------
# Stop loss and take profit — tight for "profit daily and stop" (lock small gains)
# -----------------------------------------------------------------------------
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", "1.0")
TAKE_PROFIT_PCT = _float("TAKE_PROFIT_PCT", "5.0")  # 5% fixed TP when VWAP far; primary target = VWAP

# -----------------------------------------------------------------------------
# Robustness (improve forward-looking edge, not just backtest fit)
# -----------------------------------------------------------------------------
# Don't open new buy when annualized vol > this (avoid blow-ups in chaos)
# Allow growth names; 0 = no vol filter
VOL_MAX_FOR_ENTRY = _float("VOL_MAX_FOR_ENTRY", "1.0")  # 0 = disabled
# Move stop to breakeven after 1% profit
BREAKEVEN_ACTIVATION_PCT = _float("BREAKEVEN_ACTIVATION_PCT", "1.0")  # 0 = disabled
# Trailing stop: once up 2%, sell if we drop 1% from peak
TRAILING_STOP_ACTIVATION_PCT = _float("TRAILING_STOP_ACTIVATION_PCT", "2.0")  # 0 = disabled
TRAILING_STOP_PCT = _float("TRAILING_STOP_PCT", "1.0")
# Scale out: lock 25% at 1%, 2%, 3%; false = let full position run to VWAP/TP (better in backtest)
SCALE_OUT_ENABLED = _bool("SCALE_OUT_ENABLED", "false")
SCALE_OUT_LEVELS_PCT = os.environ.get("SCALE_OUT_LEVELS_PCT", "1,2,3")  # comma-separated % (e.g. 1,2,3)
SCALE_OUT_PCT_PER_LEVEL = _float("SCALE_OUT_PCT_PER_LEVEL", "25")  # sell this % of position at each level
# Time stop: exit if held this many days and not at TP (avoid dead capital); 0 = disabled
MAX_HOLD_DAYS = _int("MAX_HOLD_DAYS", "10")

# -----------------------------------------------------------------------------
# Microstructure / volatility (pro-style: VWAP anchor, ATR stops, z-score mean reversion)
# -----------------------------------------------------------------------------
# ATR-based stop: 20-period ATR, 2.0× below entry (anti-shakeout); never use fixed % for stop
USE_ATR_STOP = _bool("USE_ATR_STOP", "true")
ATR_PERIOD = _int("ATR_PERIOD", "20")  # spec: 20-period ATR
ATR_STOP_MULTIPLE = _float("ATR_STOP_MULTIPLE", "2.0")  # 2× ATR below entry (realistic; 1.5 = tighter)
# VWAP = Fair Value anchor: only long when price significantly below VWAP; exit target = return to VWAP
USE_VWAP_ANCHOR = _bool("USE_VWAP_ANCHOR", "true")
VWAP_LONG_ONLY_BELOW = _bool("VWAP_LONG_ONLY_BELOW", "true")  # do not enter at VWAP; only oversold stretch below
VWAP_FAIR_VALUE_BAND_STD = _float("VWAP_FAIR_VALUE_BAND_STD", "1.0")  # ±1 std dev band around VWAP (for deviation logic)
VWAP_MEAN_REVERSION_PCT = _float("VWAP_MEAN_REVERSION_PCT", "2.0")  # above VWAP by this % = extended, no buy
VWAP_LOOKBACK = _int("VWAP_LOOKBACK", "20")  # rolling VWAP window (0 = expanding)
# Z-Score: Z=(x−μ)/σ. Trigger at -3.0 (extreme oversold) or -2.5 for entry
USE_ZSCORE_MEAN_REVERSION = _bool("USE_ZSCORE_MEAN_REVERSION", "true")
ZSCORE_MEAN_REVERSION_BUY = _float("ZSCORE_MEAN_REVERSION_BUY", "-2.0")  # z <= this → boost sentiment
ZSCORE_TRIGGER_ENTRY = _float("ZSCORE_TRIGGER_ENTRY", "-2.0")  # when MICROSTRUCTURE_ENTRY_MODE: require Z <= this for buy
ZSCORE_PERIOD = _int("ZSCORE_PERIOD", "20")
# ATR tradable band: only trade when ATR is within this percentile range (avoid extreme vol)
ATR_PERCENTILE_MIN = _float("ATR_PERCENTILE_MIN", "10")   # min percentile (e.g. 10 = not too quiet)
ATR_PERCENTILE_MAX = _float("ATR_PERCENTILE_MAX", "90")  # max percentile (e.g. 90 = not extreme spike)
ATR_PERCENTILE_LOOKBACK = _int("ATR_PERCENTILE_LOOKBACK", "60")  # bars for percentile calc
# OFI: require surge in aggressive buying for entry (absorption → breakout)
USE_OFI = _bool("USE_OFI", "true")
OFI_SURGE_FOR_ENTRY = _float("OFI_SURGE_FOR_ENTRY", "0.25")  # require OFI >= this for trigger (e.g. 0.25 = buying pressure)
OFI_WINDOW_TRADES = _int("OFI_WINDOW_TRADES", "100")  # rolling window (last N trades per symbol)
# Exit: primary profit target = return to Daily VWAP (mean reversion)
TAKE_PROFIT_AT_VWAP = _bool("TAKE_PROFIT_AT_VWAP", "true")  # sell when price >= VWAP (primary target)
# Let winners run: at 50% of way to VWAP move stop to breakeven; above VWAP use trailing ATR stop
BREAKEVEN_AT_HALFWAY_TO_VWAP = _bool("BREAKEVEN_AT_HALFWAY_TO_VWAP", "true")  # when price 50% toward VWAP, lock breakeven
TRAILING_ATR_ABOVE_VWAP = _bool("TRAILING_ATR_ABOVE_VWAP", "true")  # above VWAP: trailing stop at TRAILING_ATR_MULTIPLE×ATR below peak
TRAILING_ATR_MULTIPLE = _float("TRAILING_ATR_MULTIPLE", "1.5")  # e.g. 1.5× ATR trailing when price > VWAP
# When true, entry requires filter (price below VWAP, ATR tradable) AND trigger (Z <= ZSCORE_TRIGGER_ENTRY, OFI >= surge)
# When true, require Z <= ZSCORE_TRIGGER_ENTRY for every buy (on daily bars this yields very few trades; use -1.5 or live tape)
MICROSTRUCTURE_ENTRY_MODE = _bool("MICROSTRUCTURE_ENTRY_MODE", "false")

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Opportunity Engine (screener): activate only top N symbols by Z/volume/OFI
# -----------------------------------------------------------------------------
# When true, only run strategy for symbols in the active list (from run_screener output).
OPPORTUNITY_ENGINE_ENABLED = _bool("OPPORTUNITY_ENGINE_ENABLED", "false")
# Screener: which tickers have |Z| above threshold or volume spike; deploy top N only.
SCREENER_TOP_N = _int("SCREENER_TOP_N", "5")
SCREENER_Z_THRESHOLD = _float("SCREENER_Z_THRESHOLD", "1.2")  # |Z| >= this = candidate (lower = more anomalies; was 2.0)
SCREENER_VOLUME_SPIKE_PCT = _float("SCREENER_VOLUME_SPIKE_PCT", "10")  # 10% vs 20d avg (lower = more qualify)
SCREENER_UNIVERSE = os.environ.get("SCREENER_UNIVERSE", "r2000_sp500_nasdaq100")  # r2000_sp500_nasdaq100 | lab_12 | russell2000 | sp500 | sp400 | nasdaq100 | env | alpaca_equity_500 | file:path
# Need 21+ trading days for Z/vol (20d). 35 calendar days ~= 25 trading days.
SCREENER_LOOKBACK_DAYS = _int("SCREENER_LOOKBACK_DAYS", "35")  # bars for Z and 20d vol avg
SCREENER_CHUNK_SIZE = _int("SCREENER_CHUNK_SIZE", "100")  # bar fetch chunk size for large universes
SCREENER_CHUNK_DELAY_SEC = _float("SCREENER_CHUNK_DELAY_SEC", "0.5")  # delay between chunks (rate limit)
# Where screener writes today's active symbols (file path). Consumer reads this when OPPORTUNITY_ENGINE_ENABLED.
ACTIVE_SYMBOLS_FILE = os.environ.get("ACTIVE_SYMBOLS_FILE", "").strip()  # e.g. data/active_symbols.txt
# When set, run scanner daily at this time ET on full trading days (e.g. 09:30 = market open). Also runs at container start.
SCREENER_RUN_AT_ET = os.environ.get("SCREENER_RUN_AT_ET", "09:30").strip()  # "09:30" = market open ET

# -----------------------------------------------------------------------------
# Two-Stage Intelligence: Discovery (8:00–9:30 ET) → Execution (9:30+)
# -----------------------------------------------------------------------------
DISCOVERY_ENABLED = _bool("DISCOVERY_ENABLED", "false")
DISCOVERY_START_ET = os.environ.get("DISCOVERY_START_ET", "08:00").strip()
DISCOVERY_END_ET = os.environ.get("DISCOVERY_END_ET", "09:30").strip()
DISCOVERY_INTERVAL_MIN = _int("DISCOVERY_INTERVAL_MIN", "5")
DISCOVERY_TOP_N = _int("DISCOVERY_TOP_N", "10")
TWO_STAGE_ENTRY_ATR_BELOW_VWAP = _float("TWO_STAGE_ENTRY_ATR_BELOW_VWAP", "1.0")
SCALE_OUT_50_AT_VWAP = _bool("SCALE_OUT_50_AT_VWAP", "true")
PORTFOLIO_HEALTH_CHECK_ET = os.environ.get("PORTFOLIO_HEALTH_CHECK_ET", "16:00").strip()

# -----------------------------------------------------------------------------
# Session: no new buys after 3:45pm ET; overnight carry for winners
# -----------------------------------------------------------------------------
# No new buys after this time ET; only closing. Default 15:45 = 3:45pm ET.
NO_NEW_BUYS_AFTER_ET = os.environ.get("NO_NEW_BUYS_AFTER_ET", "15:45").strip()
# Overnight: only close positions that are in loss before 4pm; let winners run (trailing ATR handles exit, gap-up potential)
OVERNIGHT_CARRY_ENABLED = _bool("OVERNIGHT_CARRY_ENABLED", "true")
CLOSE_LOSSES_BY_ET = os.environ.get("CLOSE_LOSSES_BY_ET", "15:50").strip()  # in this window, close only losing positions

# -----------------------------------------------------------------------------
# Backtest accuracy: execution and costs
# -----------------------------------------------------------------------------
# Fill at next bar's open (removes look-ahead; signal at close T -> fill at open T+1)
BACKTEST_FILL_AT_NEXT_OPEN = _bool("BACKTEST_FILL_AT_NEXT_OPEN", "true")
# Commission per trade (e.g. 0 for Alpaca commission-free; 0.5 for conservative)
BACKTEST_COMMISSION_PER_TRADE = _float("BACKTEST_COMMISSION_PER_TRADE", "0")
# Slippage in basis points (e.g. 5 = 0.05% on each fill)
BACKTEST_SLIPPAGE_BPS = _float("BACKTEST_SLIPPAGE_BPS", "0")
