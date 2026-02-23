"""
Strategy: single place that turns signals and rules into buy/sell/hold.
- Uses composite score (news + social + momentum) and consensus_ok from the consumer.
- Applies rules in order: stop loss -> sell (bearish/prob drop) -> kill switch -> daily cap -> opening window -> consensus -> buy thresholds.
- All thresholds and flags come from config.py (env). Add new rules in rules/ and call them from decide().
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Literal, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import os
from . import config
from .signals.news_sentiment import score_news

log = logging.getLogger("brain.strategy")

# Per-symbol sentiment EMA (smooths composite score so one headline doesn't flip the decision).
_sentiment_ema: Dict[str, float] = {}
# Kill switch: when True, no new buys (set by bad news, market stress, or KILL_SWITCH env).
_kill_switch_active = os.environ.get("KILL_SWITCH", "").lower() in ("true", "1", "yes")


def update_and_get_sentiment_ema(symbol: str, raw_sentiment: float) -> float:
    """Update per-symbol sentiment EMA and return smoothed value."""
    alpha = config.SENTIMENT_EMA_ALPHA
    prev = _sentiment_ema.get(symbol, raw_sentiment)
    ema = alpha * raw_sentiment + (1 - alpha) * prev
    _sentiment_ema[symbol] = ema
    return ema


def get_sentiment_ema(symbol: str) -> float:
    return _sentiment_ema.get(symbol, 0.0)


def sentiment_score_from_news(payload: dict) -> float:
    """Legacy / kill-switch: raw news score from headline+summary."""
    return score_news(payload)


def is_kill_switch_active() -> bool:
    return _kill_switch_active


def set_kill_switch_from_news(raw_sentiment: float) -> None:
    global _kill_switch_active
    if not _kill_switch_active and raw_sentiment <= config.KILL_SWITCH_SENTIMENT_THRESHOLD:
        _kill_switch_active = True
        log.warning("kill_switch ON (bad news sentiment=%.2f)", raw_sentiment)


def set_kill_switch_from_returns(return_1m: Optional[float], return_5m: Optional[float]) -> None:
    global _kill_switch_active
    thresh = config.KILL_SWITCH_RETURN_THRESHOLD
    if return_1m is not None and return_1m <= thresh and not _kill_switch_active:
        _kill_switch_active = True
        log.warning("kill_switch ON (market stress return_1m=%.2f%%)", return_1m * 100)
    if return_5m is not None and return_5m <= thresh and not _kill_switch_active:
        _kill_switch_active = True
        log.warning("kill_switch ON (market stress return_5m=%.2f%%)", return_5m * 100)


def set_kill_switch(active: bool) -> None:
    global _kill_switch_active
    _kill_switch_active = active


def _parse_et_time(s: str) -> Optional[tuple]:
    """Parse 'HH:MM' (24h) -> (hour, minute) or None."""
    if not s or ":" not in s:
        return None
    parts = s.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except (TypeError, ValueError):
        return None


def is_before_trading_start() -> bool:
    """True if before TRADING_START_ET (e.g. 09:45) on a weekday — no new buys."""
    if not config.TRADING_START_ET or ZoneInfo is None:
        return is_in_opening_no_trade_window()
    start = _parse_et_time(config.TRADING_START_ET)
    if start is None:
        return is_in_opening_no_trade_window()
    try:
        et = datetime.now(ZoneInfo("America/New_York"))
        if et.weekday() > 4:
            return True
        return (et.hour < start[0]) or (et.hour == start[0] and et.minute < start[1])
    except Exception:
        return False


def is_after_no_new_buys() -> bool:
    """True if at or after NO_NEW_BUYS_AFTER_ET (e.g. 15:45) on a weekday — no new buys, only closes."""
    if not config.NO_NEW_BUYS_AFTER_ET or ZoneInfo is None:
        return False
    end = _parse_et_time(config.NO_NEW_BUYS_AFTER_ET)
    if end is None:
        return False
    try:
        et = datetime.now(ZoneInfo("America/New_York"))
        if et.weekday() > 4:
            return False
        return (et.hour > end[0]) or (et.hour == end[0] and et.minute >= end[1])
    except Exception:
        return False


def is_in_opening_no_trade_window() -> bool:
    """True if in first NO_TRADE_FIRST_MINUTES_AFTER_OPEN after 9:30am ET (fallback when TRADING_START_ET not used)."""
    if config.NO_TRADE_FIRST_MINUTES_AFTER_OPEN <= 0 or ZoneInfo is None:
        return False
    try:
        et = datetime.now(ZoneInfo("America/New_York"))
        if et.weekday() > 4 or et.hour != 9 or et.minute < 30:
            return False
        return et.minute < 30 + config.NO_TRADE_FIRST_MINUTES_AFTER_OPEN
    except Exception:
        return False


def probability_gain(payload: dict) -> float:
    """Heuristic probability of gain [0, 1] from return_1m, return_5m, volatility."""
    ret1 = payload.get("return_1m")
    ret5 = payload.get("return_5m")
    vol = payload.get("annualized_vol_30d")
    if ret1 is None and ret5 is None and vol is None:
        return 0.5
    r = 0.0
    if ret1 is not None:
        r += 0.6 * (max(-1, min(1, ret1)) + 1) / 2
    if ret5 is not None:
        r += 0.4 * (max(-1, min(1, ret5)) + 1) / 2
    if r == 0:
        r = 0.5
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
    consensus_ok: bool = True,
    daily_cap_reached: bool = False,
    drawdown_halt: bool = False,
) -> Decision:
    """
    Orchestrate rules and thresholds into a single decision.
    consensus_ok: require multiple sources positive (see rules.consensus).
    daily_cap_reached: 0.2% shutdown - no new buys (see rules.daily_cap).
    drawdown_halt: no new buys when drawdown from peak >= MAX_DRAWDOWN_PCT (see rules.drawdown).
    """
    buy_thresh = config.SENTIMENT_BUY_THRESHOLD
    buy_min_conf = config.SENTIMENT_BUY_MIN_CONFIDENCE
    prob_thresh = config.PROB_GAIN_THRESHOLD
    sell_sentiment_thresh = config.SENTIMENT_SELL_THRESHOLD
    prob_sell_thresh = config.PROB_GAIN_SELL_THRESHOLD
    max_qty = config.STRATEGY_MAX_QTY
    stop_loss_pct = config.STOP_LOSS_PCT / 100.0

    if config.STRATEGY_REGULAR_SESSION_ONLY and session != "regular":
        return Decision("hold", symbol, 0, f"session={session}")

    have_position = position_qty > 0

    # Stop loss
    if have_position and unrealized_pl_pct is not None and unrealized_pl_pct <= -stop_loss_pct:
        return Decision("sell", symbol, min(abs(position_qty), max_qty), f"stop_loss {unrealized_pl_pct*100:.2f}%")

    # Sell: bearish or prob drop
    if have_position and (sentiment <= sell_sentiment_thresh or prob_gain < prob_sell_thresh):
        return Decision("sell", symbol, min(abs(position_qty), max_qty), f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")

    # Buy: kill switch
    if is_kill_switch_active():
        return Decision("hold", symbol, 0, "kill_switch_active")

    # Buy: daily cap (0.2% shutdown - lock in gains)
    if daily_cap_reached:
        return Decision("hold", symbol, 0, "daily_cap_reached")

    # Buy: max drawdown halt
    if drawdown_halt:
        return Decision("hold", symbol, 0, "drawdown_halt")

    # Buy: before session start (e.g. before 9:45am ET)
    if not have_position and is_before_trading_start():
        return Decision("hold", symbol, 0, "before_trading_start")
    # Buy: after no-new-buys time (e.g. after 3:45pm ET; only closes allowed)
    if not have_position and is_after_no_new_buys():
        return Decision("hold", symbol, 0, "after_no_new_buys")

    # Buy: consensus (e.g. 2 of 3 sources positive; if News positive but Social meh -> stay cash)
    if not consensus_ok:
        return Decision("hold", symbol, 0, "consensus_not_met")

    # Buy: conviction + prob_gain
    if not have_position and sentiment >= buy_thresh and sentiment >= buy_min_conf and prob_gain >= prob_thresh:
        return Decision("buy", symbol, min(1, max_qty), f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")

    return Decision("hold", symbol, 0, f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")


# Backward compatibility: expose constants used by consumer
STOP_LOSS_PCT = config.STOP_LOSS_PCT
