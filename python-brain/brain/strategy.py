"""
Strategy: Green Light only. Single place that turns signals and rules into buy/sell/hold.
- Buy: 4-point checklist (Structure + Pattern + Momentum + OFI). No news/social/momentum.
- Structure: HTF trend (price > 50 EMA), pause longs on double top/H&S. Pattern at confluence (Z or VWAP). RSI/MACD energy; RSI>70 block unless OFI.
- Exit: stop 2×ATR, TP = TAKE_PROFIT_R_MULTIPLE×risk (e.g. 3R), VWAP target, trailing, breakeven. EXIT_ONLY_STOP_AND_TP = no sentiment/prob exit.
- All thresholds from config.py (env).
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

log = logging.getLogger("brain.strategy")

# Per-symbol sentiment EMA (smooths technical score for optional use).
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
    """Legacy / kill-switch: raw news score from headline+summary. Lazy-import to avoid loading FinBERT in backtest."""
    from .signals.news_sentiment import score_news
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


def is_after_no_new_buys() -> bool:
    """True if at or after NO_NEW_BUYS_AFTER_ET (e.g. 15:45) on a weekday — no new buys, only closes."""
    if os.environ.get("BACKTEST_SESSION_SKIP") == "1":
        return False
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
    daily_cap_reached: bool = False,
    drawdown_halt: bool = False,
    trend_ok: Optional[bool] = None,
    vol_ok: Optional[bool] = None,
    peak_unrealized_pl_pct: Optional[float] = None,
    bars_held: Optional[int] = None,
    atr_stop_pct: Optional[float] = None,
    vwap_distance_pct: Optional[float] = None,
    returns_zscore: Optional[float] = None,
    ofi: Optional[float] = None,
    atr_percentile: Optional[float] = None,
    entry_price: Optional[float] = None,
    current_price: Optional[float] = None,
    spy_below_200ma: Optional[bool] = None,
    scaled_50_at_vwap: bool = False,
    in_health_check_window: bool = False,
    technical_score: Optional[float] = None,
    structure_ok: Optional[bool] = None,
    ltf_prices: Optional[list] = None,
) -> Decision:
    """
    Green Light only: buy when 4-point checklist passes; exit on stop/TP/VWAP/trailing/breakeven only.
    """
    prob_thresh = config.PROB_GAIN_THRESHOLD
    max_qty = config.STRATEGY_MAX_QTY
    # Volatility-adjusted stop: ATR-based when enabled and available
    use_atr = getattr(config, "USE_ATR_STOP", False)
    if use_atr and atr_stop_pct is not None and atr_stop_pct > 0:
        stop_loss_pct = atr_stop_pct / 100.0
    else:
        stop_loss_pct = config.STOP_LOSS_PCT / 100.0
    # TP = 3× risk when TAKE_PROFIT_R_MULTIPLE set (e.g. stop 2 ATR → TP 6 ATR)
    r_mult = getattr(config, "TAKE_PROFIT_R_MULTIPLE", 0)
    if r_mult > 0 and use_atr and atr_stop_pct is not None and atr_stop_pct > 0:
        take_profit_pct = (atr_stop_pct / 100.0) * r_mult
    else:
        take_profit_pct = config.TAKE_PROFIT_PCT / 100.0 if config.TAKE_PROFIT_PCT > 0 else None
    vol_max = getattr(config, "VOL_MAX_FOR_ENTRY", 0)
    breakeven_act = getattr(config, "BREAKEVEN_ACTIVATION_PCT", 0) / 100.0 if getattr(config, "BREAKEVEN_ACTIVATION_PCT", 0) > 0 else None
    trail_act = getattr(config, "TRAILING_STOP_ACTIVATION_PCT", 0) / 100.0 if getattr(config, "TRAILING_STOP_ACTIVATION_PCT", 0) > 0 else None
    trail_pct = getattr(config, "TRAILING_STOP_PCT", 0) / 100.0 if getattr(config, "TRAILING_STOP_PCT", 0) > 0 else None
    max_hold_days = getattr(config, "MAX_HOLD_DAYS", 0) or 0

    if config.STRATEGY_REGULAR_SESSION_ONLY and session != "regular":
        return Decision("hold", symbol, 0, f"session={session}")

    have_position = position_qty > 0

    # 16:00 Portfolio Health Check: close all losing positions; keep winners with trailing ATR
    if in_health_check_window and have_position and unrealized_pl_pct is not None and unrealized_pl_pct < 0:
        return Decision("sell", symbol, min(abs(position_qty), max_qty), "portfolio_health_check_loser")

    # Stop loss (initial 2×ATR below entry; strategy already uses ATR when USE_ATR_STOP)
    if have_position and unrealized_pl_pct is not None and unrealized_pl_pct <= -stop_loss_pct:
        return Decision("sell", symbol, min(abs(position_qty), max_qty), f"stop_loss {unrealized_pl_pct*100:.2f}%")

    # Scale out 50% at VWAP (two-stage: lock half at mean reversion; trail the rest)
    take_profit_at_vwap = getattr(config, "TAKE_PROFIT_AT_VWAP", False)
    scale_out_50 = getattr(config, "SCALE_OUT_50_AT_VWAP", False)
    if take_profit_at_vwap and scale_out_50 and have_position and not scaled_50_at_vwap and vwap_distance_pct is not None and vwap_distance_pct >= 0:
        half_qty = max(1, abs(position_qty) // 2)
        return Decision("sell", symbol, min(half_qty, max_qty), "scale_out_50_at_vwap")
    # Full take profit at VWAP (when not scaling 50% or already scaled)
    if take_profit_at_vwap and have_position and vwap_distance_pct is not None and vwap_distance_pct >= 0:
        return Decision("sell", symbol, min(abs(position_qty), max_qty), "take_profit_at_vwap")
    # Take profit (fixed % when enabled)
    if take_profit_pct and have_position and unrealized_pl_pct is not None and unrealized_pl_pct >= take_profit_pct:
        return Decision("sell", symbol, min(abs(position_qty), max_qty), f"take_profit {unrealized_pl_pct*100:.2f}%")

    # Trailing ATR above VWAP: once price > VWAP, trail at TRAILING_ATR_MULTIPLE×ATR below peak (let winners run)
    trail_atr_above = getattr(config, "TRAILING_ATR_ABOVE_VWAP", False)
    if trail_atr_above and have_position and vwap_distance_pct is not None and vwap_distance_pct >= 0:
        if entry_price and entry_price > 0 and current_price and current_price > 0 and atr_stop_pct and atr_stop_pct > 0 and peak_unrealized_pl_pct is not None:
            atr_mult = getattr(config, "ATR_STOP_MULTIPLE", 2.0)
            trail_mult = getattr(config, "TRAILING_ATR_MULTIPLE", 1.5)
            peak_price = entry_price * (1.0 + peak_unrealized_pl_pct)
            atr_price = current_price * (atr_stop_pct / 100.0) / atr_mult  # ATR in price terms
            stop_level = peak_price - trail_mult * atr_price
            if current_price <= stop_level:
                return Decision("sell", symbol, min(abs(position_qty), max_qty), f"trailing_atr_above_vwap pl={unrealized_pl_pct*100:.2f}%" if unrealized_pl_pct is not None else "trailing_atr_above_vwap")

    # Breakeven at 50% of way to VWAP: once price has reached halfway to VWAP, don't give it back — sell if pl <= 0
    be_halfway = getattr(config, "BREAKEVEN_AT_HALFWAY_TO_VWAP", False)
    if be_halfway and have_position and entry_price and entry_price > 0 and current_price and current_price > 0 and vwap_distance_pct is not None:
        vwap_val = current_price / (1.0 + vwap_distance_pct / 100.0)
        if vwap_val > entry_price:
            progress = (current_price - entry_price) / (vwap_val - entry_price)
            if progress >= 0.5 and unrealized_pl_pct is not None and unrealized_pl_pct <= 0:
                return Decision("sell", symbol, min(abs(position_qty), max_qty), f"breakeven_halfway_to_vwap pl={unrealized_pl_pct*100:.2f}%")

    # Breakeven: once we've been up X%, don't give it back — sell if we drop to 0 or below
    if breakeven_act and have_position and unrealized_pl_pct is not None and peak_unrealized_pl_pct is not None:
        if peak_unrealized_pl_pct >= breakeven_act and unrealized_pl_pct <= 0:
            return Decision("sell", symbol, min(abs(position_qty), max_qty), f"breakeven pl={unrealized_pl_pct*100:.2f}%")

    # Trailing stop: once up trail_act, sell if we drop trail_pct from peak
    if trail_act and trail_pct and have_position and unrealized_pl_pct is not None and peak_unrealized_pl_pct is not None:
        if peak_unrealized_pl_pct >= trail_act and unrealized_pl_pct < peak_unrealized_pl_pct - trail_pct:
            return Decision("sell", symbol, min(abs(position_qty), max_qty), f"trailing_stop pl={unrealized_pl_pct*100:.2f}%")

    # Time stop: exit if held too long (avoid dead capital)
    if max_hold_days > 0 and have_position and bars_held is not None and bars_held >= max_hold_days:
        return Decision("sell", symbol, min(abs(position_qty), max_qty), f"max_hold_days={bars_held}")

    # Buy: kill switch
    if is_kill_switch_active():
        return Decision("hold", symbol, 0, "kill_switch_active")

    # Buy: daily cap (0.2% shutdown - lock in gains)
    if daily_cap_reached:
        return Decision("hold", symbol, 0, "daily_cap_reached")

    # Buy: max drawdown halt
    if drawdown_halt:
        return Decision("hold", symbol, 0, "drawdown_halt")

    # Buy: after no-new-buys time (e.g. after 3:45pm ET; only closes allowed)
    if not have_position and is_after_no_new_buys():
        return Decision("hold", symbol, 0, "after_no_new_buys")

    # Buy: Green Light — 4-point checklist. Liberal: when data missing, allow (don't block).
    if not have_position:
        # 1) Structure: HTF trend aligned. When unknown (None), allow (liberal).
        _structure_ok = structure_ok if structure_ok is not None else trend_ok
        if _structure_ok is False:
            return Decision("hold", symbol, 0, "green_light_structure")
        # 2) Pattern: valid at confluence. Scalp: technical >= TECHNICAL_MIN (e.g. -0.35); when no data, allow.
        confluence_z = getattr(config, "CONFLUENCE_Z_MAX", 0.5)
        tech_min = getattr(config, "TECHNICAL_MIN_FOR_ENTRY", -0.35)
        at_z = returns_zscore is not None and returns_zscore <= confluence_z
        at_vwap = vwap_distance_pct is not None and vwap_distance_pct >= 0
        no_confluence_data = returns_zscore is None and vwap_distance_pct is None
        # When no technical score, allow (scalp). When present, require >= tech_min and at confluence or no confluence data.
        pattern_ok = (technical_score is None) or (
            technical_score >= tech_min and (at_z or at_vwap or no_confluence_data)
        )
        if not pattern_ok:
            return Decision("hold", symbol, 0, "green_light_pattern")
        # 3) Momentum: scalp = skip (always allow); otherwise RSI divergence or MACD above zero when enough bars
        momentum_ok = True  # scalp: don't block on momentum
        if not getattr(config, "SCALP_SKIP_MOMENTUM", True) and ltf_prices and len(ltf_prices) >= 20:
            from .signals.technical import rsi_bullish_divergence, macd_histogram_above_zero
            momentum_ok = rsi_bullish_divergence(ltf_prices, period=getattr(config, "RSI_PERIOD", 14)) or macd_histogram_above_zero(ltf_prices)
        if not momentum_ok:
            return Decision("hold", symbol, 0, "green_light_momentum")
        # 4) Microstructure: OFI >= surge when available. Scalp: surge=0 so any OFI or no data passes.
        ofi_surge = getattr(config, "OFI_SURGE_FOR_ENTRY", 0.0)
        ofi_ok = (ofi is None) or (ofi >= ofi_surge)
        if not ofi_ok:
            return Decision("hold", symbol, 0, f"green_light_ofi {ofi:.2f}")
        # RSI overbought: allow up to RSI_OVERBOUGHT; above that need OFI >= min (liberal defaults).
        rsi_ob = getattr(config, "RSI_OVERBOUGHT", 75)
        rsi_ob_ofi_min = getattr(config, "RSI_OVERBOUGHT_OFI_MIN", 0.20)
        rsi_overbought_ok = True
        if ltf_prices and len(ltf_prices) >= getattr(config, "RSI_PERIOD", 14) + 1:
            from .signals.technical import rsi_value
            rsi_val = rsi_value(ltf_prices, getattr(config, "RSI_PERIOD", 14))
            if rsi_val is not None and rsi_val > rsi_ob:
                rsi_overbought_ok = ofi is not None and ofi >= rsi_ob_ofi_min
        if not rsi_overbought_ok:
            return Decision("hold", symbol, 0, "green_light_rsi_overbought")
        if prob_gain >= prob_thresh:
            return Decision("buy", symbol, min(1, max_qty), "green_light_4pt")

    return Decision("hold", symbol, 0, "green_light_not_met")


# Backward compatibility: expose constants used by consumer
STOP_LOSS_PCT = config.STOP_LOSS_PCT
