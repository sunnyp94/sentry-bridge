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
    consensus_ok: bool = True,
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
    regime: Optional[str] = None,
    spy_below_200ma: Optional[bool] = None,
    scaled_50_at_vwap: bool = False,
    in_health_check_window: bool = False,
) -> Decision:
    """
    Orchestrate rules and thresholds into a single decision.
    vol_ok: when False, no new buy (vol too high). peak_unrealized_pl_pct/bars_held for trailing/breakeven/max_hold.
    atr_stop_pct: when USE_ATR_STOP and set, use this as stop distance (%); else fixed STOP_LOSS_PCT.
    vwap_distance_pct: % distance from VWAP (positive = above); used for mean-reversion filter and TP-at-VWAP exit.
    returns_zscore: z-score of recent return; trigger at ZSCORE_TRIGGER_ENTRY (e.g. -2.5).
    ofi: order flow imbalance [-1,1]; trigger requires OFI >= OFI_SURGE_FOR_ENTRY when USE_OFI.
    atr_percentile: 0-100; filter requires ATR in [ATR_PERCENTILE_MIN, ATR_PERCENTILE_MAX] (tradable band).
    entry_price, current_price: for breakeven-at-halfway-to-VWAP and trailing ATR above VWAP (backtest/live when available).
    spy_below_200ma: when True and SPY_200MA_REGIME_ENABLED, use stricter Z for longs and (when shorts exist) favor shorts.
    """
    buy_thresh = config.SENTIMENT_BUY_THRESHOLD
    buy_min_conf = config.SENTIMENT_BUY_MIN_CONFIDENCE
    prob_thresh = config.PROB_GAIN_THRESHOLD
    sell_sentiment_thresh = config.SENTIMENT_SELL_THRESHOLD
    prob_sell_thresh = config.PROB_GAIN_SELL_THRESHOLD
    max_qty = config.STRATEGY_MAX_QTY
    # Volatility-adjusted stop: ATR-based when enabled and available
    use_atr = getattr(config, "USE_ATR_STOP", False)
    if use_atr and atr_stop_pct is not None and atr_stop_pct > 0:
        stop_loss_pct = atr_stop_pct / 100.0
    else:
        stop_loss_pct = config.STOP_LOSS_PCT / 100.0
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

    # Sell: bearish or prob drop (skipped when EXIT_ONLY_STOP_AND_TP — hold until stop or take-profit)
    if not getattr(config, "EXIT_ONLY_STOP_AND_TP", False) and have_position and (sentiment <= sell_sentiment_thresh or prob_gain < prob_sell_thresh):
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

    # Buy: after no-new-buys time (e.g. after 3:45pm ET; only closes allowed)
    if not have_position and is_after_no_new_buys():
        return Decision("hold", symbol, 0, "after_no_new_buys")

    # Buy: consensus (e.g. 2 of 3 sources positive; if News positive but Social meh -> stay cash)
    if not consensus_ok:
        return Decision("hold", symbol, 0, "consensus_not_met")

    # Pillar 2: Regime filter — only fire mean-reversion in choppy regime, trend in trending regime
    if getattr(config, "REGIME_FILTER_ENABLED", False) and regime is not None and not have_position:
        use_vwap = getattr(config, "USE_VWAP_ANCHOR", False)
        use_z = getattr(config, "USE_ZSCORE_MEAN_REVERSION", False)
        if regime == "trend" and (use_vwap or use_z) and (trend_ok is False or not config.TREND_FILTER_ENABLED):
            return Decision("hold", symbol, 0, "regime_trend_no_mr")
        if regime == "mean_reversion" and config.TREND_FILTER_ENABLED and trend_ok is True and not (use_vwap or use_z):
            return Decision("hold", symbol, 0, "regime_mr_no_trend")

    # Buy: trend filter (only long when price above SMA when enabled)
    if config.TREND_FILTER_ENABLED and not have_position and trend_ok is False:
        return Decision("hold", symbol, 0, "trend_filter_below_sma")

    # Buy: volatility filter (don't open in extreme vol — improves forward robustness)
    if vol_max > 0 and vol_ok is False and not have_position:
        return Decision("hold", symbol, 0, "vol_too_high")

    # Buy: VWAP filter — only long when price below VWAP (mean reversion bias), or no buy when extended above
    use_vwap = getattr(config, "USE_VWAP_ANCHOR", False)
    vwap_long_only_below = getattr(config, "VWAP_LONG_ONLY_BELOW", True)
    vwap_extended_pct = getattr(config, "VWAP_MEAN_REVERSION_PCT", 2.0)
    if use_vwap and not have_position and vwap_distance_pct is not None:
        if vwap_long_only_below and vwap_distance_pct > 0:
            return Decision("hold", symbol, 0, "vwap_above_no_long")
        if not vwap_long_only_below and vwap_distance_pct > vwap_extended_pct:
            return Decision("hold", symbol, 0, f"vwap_extended {vwap_distance_pct:.1f}%")
    # Two-stage entry: only long when price is at least N×ATR below VWAP and OFI shows buying pressure
    entry_atr_below = getattr(config, "TWO_STAGE_ENTRY_ATR_BELOW_VWAP", 0)
    if entry_atr_below > 0 and not have_position and vwap_distance_pct is not None and atr_stop_pct is not None:
        atr_mult = getattr(config, "ATR_STOP_MULTIPLE", 2.0)
        # Require price <= VWAP - N×ATR  =>  vwap_distance_pct <= - (N × ATR/VWAP %). ATR% ≈ atr_stop_pct/atr_mult.
        threshold_pct = - (entry_atr_below * atr_stop_pct / atr_mult)
        if vwap_distance_pct > threshold_pct:
            return Decision("hold", symbol, 0, f"two_stage_entry price not {entry_atr_below}×ATR below vwap ({vwap_distance_pct:.2f}% > {threshold_pct:.2f}%)")
    if entry_atr_below > 0 and not have_position and ofi is not None and ofi < 0:
        return Decision("hold", symbol, 0, f"two_stage_entry ofi_negative {ofi:.2f}")
    # Buy: ATR tradable band — only trade when ATR in percentile range (avoid extreme vol)
    atr_pct_min = getattr(config, "ATR_PERCENTILE_MIN", 0)
    atr_pct_max = getattr(config, "ATR_PERCENTILE_MAX", 100)
    if atr_percentile is not None and not have_position:
        if atr_pct_max < 100 and atr_percentile > atr_pct_max:
            return Decision("hold", symbol, 0, f"atr_percentile_high {atr_percentile:.0f}")
        if atr_pct_min > 0 and atr_percentile < atr_pct_min:
            return Decision("hold", symbol, 0, f"atr_percentile_low {atr_percentile:.0f}")

    # Z-Score trigger: entry when Z <= ZSCORE_TRIGGER_ENTRY (-2.5 or -3.0); boost sentiment for oversold
    # Global filter: when SPY below 200 MA, use stricter Z (SPY_BELOW_200MA_Z_TIGHTEN) for long entry
    effective_sentiment = sentiment
    use_zscore = getattr(config, "USE_ZSCORE_MEAN_REVERSION", False)
    zscore_trigger = getattr(config, "ZSCORE_TRIGGER_ENTRY", -2.5)
    zscore_thresh = getattr(config, "ZSCORE_MEAN_REVERSION_BUY", -2.5)
    if getattr(config, "SPY_200MA_REGIME_ENABLED", False) and spy_below_200ma is True:
        z_tighten = getattr(config, "SPY_BELOW_200MA_Z_TIGHTEN", -2.8)
        zscore_trigger = z_tighten
        zscore_thresh = z_tighten
    ofi_surge = getattr(config, "OFI_SURGE_FOR_ENTRY", 0.25)
    use_ofi_trigger = getattr(config, "USE_OFI", False) and ofi_surge > 0
    if use_zscore and not have_position and returns_zscore is not None and returns_zscore <= zscore_thresh:
        boost = min(0.20, (zscore_thresh - returns_zscore) * 0.05)
        effective_sentiment = sentiment + boost
    # Trigger (when MICROSTRUCTURE_ENTRY_MODE): require Z <= zscore_trigger and OFI >= surge
    micro_mode = getattr(config, "MICROSTRUCTURE_ENTRY_MODE", False)
    if micro_mode and not have_position and use_zscore and (returns_zscore is None or returns_zscore > zscore_trigger):
        return Decision("hold", symbol, 0, f"z_above_trigger {returns_zscore:.2f}" if returns_zscore is not None else "z_na")
    # Require OFI >= surge only when OFI data is present (backtest has no tape; live requires it)
    if micro_mode and not have_position and use_ofi_trigger and ofi is not None and ofi < ofi_surge:
        return Decision("hold", symbol, 0, f"ofi_below_surge {ofi:.2f}")

    # Buy: conviction + prob_gain
    if not have_position and effective_sentiment >= buy_thresh and effective_sentiment >= buy_min_conf and prob_gain >= prob_thresh:
        return Decision("buy", symbol, min(1, max_qty), f"sentiment={effective_sentiment:.2f} prob_gain={prob_gain:.2f}")

    return Decision("hold", symbol, 0, f"sentiment={sentiment:.2f} prob_gain={prob_gain:.2f}")


# Backward compatibility: expose constants used by consumer
STOP_LOSS_PCT = config.STOP_LOSS_PCT
