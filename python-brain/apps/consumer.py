#!/usr/bin/env python3
"""
Stdin consumer: entry point when Go pipes NDJSON to the brain.
Reads events from stdin, updates state, runs strategy (Green Light: technical + structure + OFI), places paper orders when enabled.
Invoked by Go via BRAIN_CMD, e.g. python3 /app/python-brain/apps/consumer.py
"""
import sys
from pathlib import Path

# Ensure python-brain root is on path so "brain" package resolves (e.g. when run from Docker /app).
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
import logging
import os
import time
from collections import defaultdict, deque
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

_PERF = time.perf_counter

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from brain.strategy import (
    update_and_get_sentiment_ema,
    get_sentiment_ema,
    set_kill_switch_from_news,
    set_kill_switch_from_returns,
    probability_gain,
    decide,
    Decision,
    STOP_LOSS_PCT,
)
from brain.signals import score_news, technical_score
from brain.rules.daily_cap import update_equity, is_daily_cap_reached, should_flat_all_for_daily_target
from brain.rules.drawdown import update_drawdown_peak, is_drawdown_halt
from brain.market_calendar import is_full_trading_day
from brain import config as brain_config
from brain.core.parse_utils import parse_unrealized_plpc
try:
    from brain.execution.smart_position_management import is_morning_flush, run_eod_prune, is_eod_prune_time
except ImportError:
    def is_morning_flush():
        return False
    def run_eod_prune(*args, **kwargs):
        return (0, 0)
    def is_eod_prune_time(*args, **kwargs):
        return False
from brain.discovery import run_discovery, DiscoveryEngine, _parse_et_time as discovery_parse_et

# OFI (Order Flow Imbalance) from live trade/quote when USE_OFI=true (brain.signals.microstructure.OFITracker)
_ofi_tracker: Optional[object] = None

# Opportunity Engine: active symbols from screener (cached by file mtime)
_active_symbols_cache: Optional[set] = None
_active_symbols_path: Optional[str] = None
_active_symbols_mtime: Optional[float] = None

def _get_active_symbols() -> Optional[set]:
    """When OPPORTUNITY_ENGINE_ENABLED, return set of symbols to activate (from ACTIVE_SYMBOLS_FILE). None = no filter."""
    global _active_symbols_cache, _active_symbols_path, _active_symbols_mtime
    if not getattr(brain_config, "OPPORTUNITY_ENGINE_ENABLED", False):
        return None
    path = getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
    if not path:
        return None
    try:
        st = os.stat(path)
        if _active_symbols_path == path and _active_symbols_mtime == st.st_mtime and _active_symbols_cache is not None:
            return _active_symbols_cache
    except OSError:
        return _active_symbols_cache  # keep previous if file gone
    try:
        with open(path) as f:
            symbols = [line.strip().upper() for line in f if line.strip()]
        _active_symbols_cache = set(symbols)
        _active_symbols_path = path
        _active_symbols_mtime = os.stat(path).st_mtime
        return _active_symbols_cache
    except OSError:
        _active_symbols_cache = set()
        _active_symbols_path = path
        _active_symbols_mtime = None
        return _active_symbols_cache


def _get_ofi_tracker():
    global _ofi_tracker
    if _ofi_tracker is None and getattr(brain_config, "USE_OFI", False):
        from brain.signals.microstructure import OFITracker
        _ofi_tracker = OFITracker(window_trades=getattr(brain_config, "OFI_WINDOW_TRADES", 100))
    return _ofi_tracker


log = logging.getLogger("brain")


def _trend_ok(sym: str) -> Optional[bool]:
    """When TREND_FILTER_ENABLED, True if price > SMA(TREND_SMA_PERIOD). Else None (no filter)."""
    if not getattr(brain_config, "TREND_FILTER_ENABLED", False):
        return None
    period = getattr(brain_config, "TREND_SMA_PERIOD", 20)
    prices = list(price_history_by_symbol.get(sym, []))
    if len(prices) < period:
        return None
    sma = sum(prices[-period:]) / period
    return prices[-1] > sma


def _vol_ok(sym: str) -> Optional[bool]:
    """When VOL_MAX_FOR_ENTRY > 0, True if annualized_vol_30d <= vol_max (no new buy when vol too high). Else None."""
    vol_max = getattr(brain_config, "VOL_MAX_FOR_ENTRY", 0)
    if vol_max <= 0:
        return None
    combined = last_payload_by_symbol.get(sym, {})
    vol = combined.get("annualized_vol_30d")
    if vol is None:
        return None
    try:
        return float(vol) <= vol_max
    except (TypeError, ValueError):
        return None


def format_ts(ts: str) -> str:
    """Format ISO ts for log output (HH:MM:SS)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return ts


def log_event(ev: dict) -> None:
    """Log one event (trade, quote, news, volatility, positions, orders) at INFO with key fields."""
    typ = ev.get("type", "?")
    ts = format_ts(ev.get("ts", ""))
    payload = ev.get("payload") or {}

    if typ == "trade":
        log.info(
            "trade symbol=%s price=%.2f size=%s vol_1m=%s ret_1m=%.4f session=%s ts=%s",
            payload.get("symbol"), payload.get("price", 0), payload.get("size"),
            payload.get("volume_1m"), payload.get("return_1m", 0), payload.get("session"), ts,
        )
    elif typ == "quote":
        log.info(
            "quote symbol=%s bid=%.2f ask=%.2f mid=%.2f ts=%s",
            payload.get("symbol"), payload.get("bid"), payload.get("ask"), payload.get("mid"), ts,
        )
    elif typ == "news":
        symbols = ",".join(payload.get("symbols") or [])
        log.info("news symbols=%s headline=%s ts=%s", symbols, (payload.get("headline") or "")[:60], ts)
    elif typ == "volatility":
        log.info("volatility symbol=%s annualized_30d=%.2f%% ts=%s", payload.get("symbol"), (payload.get("annualized_vol_30d") or 0) * 100, ts)
    elif typ == "positions":
        positions = payload.get("positions") or []
        log.info("positions count=%d ts=%s", len(positions), ts)
        for p in positions[:5]:
            log.debug("  position %s %s qty=%s mv=%s", p.get("symbol"), p.get("side"), p.get("qty"), p.get("market_value"))
    elif typ == "orders":
        orders = payload.get("orders") or []
        log.info("orders count=%d ts=%s", len(orders), ts)
        for o in orders[:5]:
            log.debug("  order %s %s qty=%s status=%s", o.get("symbol"), o.get("side"), o.get("qty"), o.get("status"))
    else:
        log.info("event type=%s payload=%s ts=%s", typ, json.dumps(payload)[:80], ts)


# --- In-memory state (updated from Go events) ---
sentiment_by_symbol: dict[str, float] = defaultdict(float)
last_payload_by_symbol: dict[str, dict] = {}
positions_qty: dict[str, int] = {}
position_unrealized_pl_pct: dict[str, float] = {}
position_entry_price: dict[str, float] = {}
position_current_price: dict[str, float] = {}
# Peak unrealized PnL per symbol (so breakeven/trailing can fire without VWAP/ATR from bars)
position_peak_unrealized_pl_pct: dict[str, float] = {}
# Entry timestamp per symbol for max_hold_days (seconds since epoch)
position_entry_time: dict[str, float] = {}
# Two-stage: track symbols for which we already scaled out 50% at VWAP (runner remains with trailing ATR)
_scaled_50_at_vwap: set = set()
# Scale-out: levels (e.g. 0.01, 0.02, 0.03) already hit per symbol
_scale_out_done: dict[str, set] = {}
# Session: default "regular" so buys allowed unless pipe sends session=pre_open (or other). Only explicit non-regular blocks.
session_by_symbol: dict[str, str] = defaultdict(lambda: "regular")
ORDER_COOLDOWN_SEC = getattr(brain_config, "ORDER_COOLDOWN_SEC", 30)
last_order_time_by_symbol: dict[str, float] = {}
# Rolling price history per symbol for RSI/technical (when USE_TECHNICAL_INDICATORS=true)
price_history_by_symbol: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
# Rolling (price, size) per symbol for intraday VWAP (used by decide() for scale-out/TP/trailing at VWAP)
_vwap_trades_by_symbol: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
# Cached equity from last positions event (avoids extra Alpaca call when sizing a buy)
_last_equity: Optional[float] = None
# EOD prune: run once per calendar day (ET) at 15:50
_eod_prune_done_date: Optional[str] = None


def _get_vwap(symbol: str) -> Optional[float]:
    """Volume-weighted average price from recent trades (rolling window). None if insufficient data."""
    trades = list(_vwap_trades_by_symbol.get(symbol, []))
    if not trades:
        return None
    total_pv = sum(p * s for p, s in trades)
    total_s = sum(s for _, s in trades)
    if total_s <= 0:
        return None
    return total_pv / total_s


def _get_vwap_distance_pct(symbol: str, current_price: Optional[float]) -> Optional[float]:
    """Percentage distance of current price from VWAP (positive = above VWAP). None if no VWAP or price."""
    if current_price is None or current_price <= 0:
        return None
    vwap = _get_vwap(symbol)
    if vwap is None:
        return None
    from brain.signals.microstructure import vwap_distance_pct as _vwap_dist
    return _vwap_dist(current_price, vwap)


def _get_price(symbol: str) -> Optional[float]:
    """Last known price or mid for symbol (from trade/quote payload or positions)."""
    p = last_payload_by_symbol.get(symbol, {})
    for key in ("price", "mid"):
        v = p.get(key)
        if v is None:
            continue
        try:
            f = float(v)
            if f > 0:
                return f
        except (TypeError, ValueError):
            continue
    # Fallback: position current price (e.g. for sells or when stream hasn't sent this symbol yet)
    cp = position_current_price.get(symbol)
    if cp is not None:
        try:
            f = float(cp)
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    return None


def _try_place_order(
    d: Decision,
    skip_cooldown: bool = False,
    price_override: Optional[float] = None,
    snapshot_context: Optional[dict] = None,
) -> bool:
    """If decision is buy/sell with qty, respect cooldown, apply position sizing (buy), place order. Returns True if placed.
    snapshot_context: optional dict for experience buffer (technical_score, ofi, prob_gain, structure_ok, unrealized_pl_pct for exits)."""
    global _last_equity
    if d.action not in ("buy", "sell") or d.qty <= 0:
        return False
    now = time.time()
    if not skip_cooldown and (now - last_order_time_by_symbol.get(d.symbol, 0) < ORDER_COOLDOWN_SEC):
        log.warning("skip order (cooldown) symbol=%s", d.symbol)
        return False
    # Place orders when: (1) TRADE_PAPER=true (paper), or (2) TRADE_PAPER=false and LIVE_TRADING_ENABLED=true (live).
    # When TRADE_PAPER=false and LIVE_TRADING_ENABLED is not set: log only, no orders.
    paper = os.environ.get("TRADE_PAPER", "true").lower() in ("true", "1", "yes")
    live_ok = os.environ.get("LIVE_TRADING_ENABLED", "").lower() in ("true", "1", "yes")
    if not paper and not live_ok:
        return False
    from brain.executor import place_order, get_account_equity
    price = price_override if price_override is not None and price_override > 0 else _get_price(d.symbol)
    # Position sizing: always 5% of actual account equity from Alpaca (no fallback; skip buy if equity unavailable).
    # Skip sizing for any "cover short" buy (exit/close); only size for new long entry (green_light_4pt).
    _is_cover_buy = d.action == "buy" and (d.reason or "").strip() != "green_light_4pt"
    if d.action == "buy" and not _is_cover_buy:
        if not price or price <= 0:
            log.error("position_size: no price for %s; skipping buy", d.symbol)
            return False
        equity = get_account_equity()
        if equity is not None and equity > 0:
            _last_equity = equity
        if equity is None or equity <= 0:
            log.error("position_size: cannot get account equity from Alpaca; skipping buy for %s (check get_account_equity logs)", d.symbol)
            return False
        pct = getattr(brain_config, "POSITION_SIZE_PCT", 0.05)
        max_pct_per_sym = 0.06  # hard cap so no single symbol exceeds 6% (safety)
        existing_qty = positions_qty.get(d.symbol, 0) or 0
        try:
            existing_qty = int(existing_qty)
        except (TypeError, ValueError):
            existing_qty = 0
        if existing_qty < 0:
            log.warning("position_size: %s is short (qty=%d); skip new long entry", d.symbol, existing_qty)
            return False
        target_dollar = equity * pct
        existing_value = existing_qty * price
        remaining_dollar = max(0.0, target_dollar - existing_value)
        cap_dollar = (equity * max_pct_per_sym) - existing_value
        remaining_dollar = min(remaining_dollar, max(0.0, cap_dollar))
        qty = int(remaining_dollar / price) if price > 0 and remaining_dollar >= price else 0
        if qty <= 0:
            if existing_qty > 0:
                log.info("position_size: %s already at/over 5%% (qty=%d); skip add", d.symbol, existing_qty)
            else:
                log.warning("position_size: qty would be 0 for %s; skip buy", d.symbol)
            return False
        qty = max(1, min(qty, brain_config.STRATEGY_MAX_QTY))
        d = Decision(d.action, d.symbol, qty, d.reason)
        log.info("position_size equity=%.2f price=%.2f pct=%.0f%% existing_qty=%d -> qty=%d", equity, price, pct * 100, existing_qty, qty)
        # Active generated rules (promoted after 24h out-of-sample): block buy only when rule has data and matches
        try:
            from brain.learning.generated_rules import should_block_buy
            ctx = (snapshot_context or {}).copy()
            if should_block_buy(ctx):
                log.info("skip buy %s (generated_rule)", d.symbol)
                return False
        except Exception as e:
            log.debug("generated_rules check skipped: %s", e)
    elif _is_cover_buy:
        if not price or price <= 0:
            log.error("cover_short: no price for %s; skipping buy", d.symbol)
            return False
    price_str = f"{price:.2f}" if price is not None and price > 0 else "market"
    log.info("order %s %s qty=%d price=%s reason=%s", d.action.upper(), d.symbol, d.qty, price_str, d.reason or "")
    # Ensure order lines appear in log file: log to root and flush (handles hierarchy/buffering on some setups)
    logging.getLogger().info("ORDER %s %s qty=%d price=%s reason=%s", d.action.upper(), d.symbol, d.qty, price_str, d.reason or "")
    for h in logging.getLogger().handlers:
        if getattr(h, "flush", None):
            h.flush()
    if place_order(d, current_price=price):
        last_order_time_by_symbol[d.symbol] = now
        # Optimistic update: count this order as position so we don't double-buy before next positions event
        if d.action == "buy":
            positions_qty[d.symbol] = positions_qty.get(d.symbol, 0) + d.qty
        elif d.action == "sell":
            positions_qty[d.symbol] = positions_qty.get(d.symbol, 0) - d.qty
        # Experience buffer: record entry/exit snapshot for strategy optimizer
        try:
            from brain.learning.experience_buffer import record_entry, record_exit
            ctx = snapshot_context or {}
            if d.action == "buy" and price and price > 0:
                if (d.reason or "").strip() == "green_light_4pt":
                    record_entry(
                        d.symbol, price, d.qty, d.reason,
                        technical_score=ctx.get("technical_score"),
                        ofi=ctx.get("ofi"),
                        prob_gain=ctx.get("prob_gain"),
                        structure_ok=ctx.get("structure_ok"),
                        regime=ctx.get("regime"),
                    )
                else:
                    record_exit(
                        d.symbol, price, d.qty, d.reason,
                        unrealized_pl_pct=ctx.get("unrealized_pl_pct"),
                        technical_score=ctx.get("technical_score"),
                        ofi=ctx.get("ofi"),
                        regime=ctx.get("regime"),
                    )
            elif d.action == "sell" and price and price > 0:
                record_exit(
                    d.symbol, price, d.qty, d.reason,
                    unrealized_pl_pct=ctx.get("unrealized_pl_pct"),
                    technical_score=ctx.get("technical_score"),
                    ofi=ctx.get("ofi"),
                    regime=ctx.get("regime"),
                )
        except Exception as e:
            log.debug("experience_buffer record skipped: %s", e)
        # Shadow strategy: record ghost buy/sell for 3 shadow models (long-only; cover buys are not new longs)
        try:
            from brain.shadow_strategy import shadow_on_buy, shadow_on_sell, shadow_update
            if d.action == "buy" and price and price > 0 and (d.reason or "").strip() == "green_light_4pt":
                shadow_on_buy(d.symbol, price, d.qty)
            elif d.action == "sell" and price and price > 0:
                shadow_on_sell(d.symbol, price, d.reason)
        except Exception as e:
            log.debug("shadow_strategy record skipped: %s", e)
        return True
    return False


def _run_scale_out_check() -> None:
    """Scale-out: long sell 25% at 1%, 2%, 3%; short cover 25% at same levels (let runner ride)."""
    if not getattr(brain_config, "SCALE_OUT_ENABLED", False):
        return
    try:
        levels_pct = [float(x.strip()) / 100.0 for x in (getattr(brain_config, "SCALE_OUT_LEVELS_PCT", "1,2,3") or "1,2,3").split(",")]
    except Exception:
        levels_pct = [0.01, 0.02, 0.03]
    scale_pct = getattr(brain_config, "SCALE_OUT_PCT_PER_LEVEL", 25) / 100.0
    for sym, pl_pct in position_unrealized_pl_pct.items():
        if pl_pct is None or pl_pct < 0:
            continue
        pos_qty = positions_qty.get(sym, 0)
        try:
            pos_qty = int(pos_qty)
        except (TypeError, ValueError):
            pos_qty = 0
        if pos_qty == 0:
            continue
        done = _scale_out_done.setdefault(sym, set())
        for level in levels_pct:
            if pl_pct >= level and level not in done:
                size = max(1, int(abs(pos_qty) * scale_pct))
                size = min(size, abs(pos_qty))
                if pos_qty > 0:
                    d = Decision("sell", sym, size, f"scale_out_{int(level*100)}pct")
                    log.info("scale_out symbol=%s pl_pct=%.2f%% sell qty=%d", sym, pl_pct * 100, size)
                else:
                    d = Decision("buy", sym, size, f"scale_out_{int(level*100)}pct")
                    log.info("scale_out symbol=%s pl_pct=%.2f%% cover qty=%d", sym, pl_pct * 100, size)
                _try_place_order(d, skip_cooldown=True, snapshot_context={"unrealized_pl_pct": pl_pct})
                done.add(level)
                break


def run_stop_loss_check() -> None:
    """On positions update: sell long at/below stop, buy to cover short at/below stop (via decide())."""
    if is_morning_flush():
        return  # Morning guardrail: no automated selling 09:30–09:45 ET (protect overnight holds)
    _run_scale_out_check()
    stop_decimal = STOP_LOSS_PCT / 100.0
    for sym, pl_pct in position_unrealized_pl_pct.items():
        if pl_pct is None or pl_pct > -stop_decimal:
            continue
        pos_qty = positions_qty.get(sym, 0)
        try:
            pos_qty = int(pos_qty)
        except (TypeError, ValueError):
            pos_qty = 0
        if pos_qty == 0:
            continue
        combined = dict(last_payload_by_symbol.get(sym, {}))
        combined.setdefault("return_1m", 0)
        combined.setdefault("return_5m", 0)
        combined.setdefault("annualized_vol_30d", 0)
        prob = probability_gain(combined)
        sent_ema = get_sentiment_ema(sym)
        sess = session_by_symbol.get(sym, "regular")
        cur_price = position_current_price.get(sym) or combined.get("price") or combined.get("mid")
        try:
            cur_price = float(cur_price) if cur_price is not None else None
        except (TypeError, ValueError):
            cur_price = None
        entry_ts = position_entry_time.get(sym)
        bars_held_days = max(0, int((time.time() - entry_ts) / 86400)) if entry_ts and entry_ts > 0 else None
        vwap_dist = _get_vwap_distance_pct(sym, cur_price)
        d = decide(sym, sent_ema, prob, pos_qty, sess, unrealized_pl_pct=pl_pct, daily_cap_reached=is_daily_cap_reached(), trend_ok=_trend_ok(sym), vol_ok=_vol_ok(sym), ofi=combined.get("ofi"), entry_price=position_entry_price.get(sym), current_price=cur_price, vwap_distance_pct=vwap_dist, scaled_50_at_vwap=(sym in _scaled_50_at_vwap), in_health_check_window=_is_in_health_check_window(), technical_score=None, peak_unrealized_pl_pct=position_peak_unrealized_pl_pct.get(sym), bars_held=bars_held_days)
        if d.action in ("sell", "buy") and d.qty > 0:
            log.warning("stop_loss symbol=%s pl_pct=%.2f%% %s qty=%d reason=%s", d.symbol, pl_pct * 100, d.action, d.qty, d.reason)
            _try_place_order(d, snapshot_context={"unrealized_pl_pct": pl_pct, "ofi": combined.get("ofi")})


def _is_in_health_check_window() -> bool:
    """True if full trading day ET >= PORTFOLIO_HEALTH_CHECK_ET (e.g. 16:00): close all losers, keep winners with trailing ATR."""
    check_et = getattr(brain_config, "PORTFOLIO_HEALTH_CHECK_ET", "").strip()
    if not check_et or ZoneInfo is None:
        return False
    try:
        et = datetime.now(ZoneInfo("America/New_York"))
        if not is_full_trading_day(et.date()):
            return False
        parts = check_et.strip().split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return (et.hour > h) or (et.hour == h and et.minute >= m)
    except Exception:
        return False


def run_portfolio_health_check() -> None:
    """At 16:00 ET (PORTFOLIO_HEALTH_CHECK_ET): close all losing positions; winners keep trailing ATR."""
    if is_morning_flush():
        return  # Morning guardrail: no automated selling 09:30–09:45 ET
    if not _is_in_health_check_window():
        return
    for sym, qty in list(positions_qty.items()):
        if qty == 0:
            continue
        pl_pct = position_unrealized_pl_pct.get(sym)
        if pl_pct is None or pl_pct >= 0:
            continue
        size = max(1, min(abs(qty), brain_config.STRATEGY_MAX_QTY))
        if qty > 0:
            d = Decision("sell", sym, size, "portfolio_health_check_loser")
        else:
            d = Decision("buy", sym, size, "close_short_health_check")
        log.info("portfolio_health_check symbol=%s pl_pct=%.2f%% close %s (qty=%d)", sym, pl_pct * 100, "short" if qty < 0 else "loser", size)
        _try_place_order(d, skip_cooldown=True)


def run_eod_prune_if_due() -> None:
    """Smart Position Management: at 15:50 ET (once per day), close only losing positions via API; profitable = Hold."""
    global _eod_prune_done_date
    if not is_eod_prune_time(getattr(brain_config, "EOD_PRUNE_AT_ET", "15:50")):
        return
    try:
        if ZoneInfo:
            today_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        else:
            today_et = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        today_et = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _eod_prune_done_date == today_et:
        return
    _eod_prune_done_date = today_et
    threshold_pct = getattr(brain_config, "EOD_PRUNE_STOP_LOSS_PCT", -2.0)
    closed, hold = run_eod_prune(stop_loss_pct=threshold_pct, eod_prune_at_et=getattr(brain_config, "EOD_PRUNE_AT_ET", "15:50"))
    log.info("EOD prune done closed=%d hold=%d (threshold=%.1f%%)", closed, hold, threshold_pct)


def run_close_losses_before_close() -> None:
    """Overnight carry: only run EOD prune at 15:50 ET (close losers via API; winners held). No in-memory close loop."""
    if is_morning_flush():
        return  # Morning guardrail: no automated selling 09:30–09:45 ET
    run_eod_prune_if_due()  # At 15:50 ET: API-based EOD prune once per day (only logic for closing-window close)


def run_flat_when_daily_target() -> None:
    """When daily PnL >= target and FLAT_WHEN_DAILY_TARGET_HIT: close all positions (profit daily and stop)."""
    if is_morning_flush():
        return  # Morning guardrail: no automated selling 09:30–09:45 ET
    if not should_flat_all_for_daily_target():
        return
    for sym, qty in list(positions_qty.items()):
        try:
            q = int(qty)
        except (TypeError, ValueError):
            continue
        if q == 0:
            continue
        size = max(1, min(abs(q), brain_config.STRATEGY_MAX_QTY))
        if q > 0:
            d = Decision("sell", sym, size, "daily_target_hit")
        else:
            d = Decision("buy", sym, size, "daily_target_hit")
        log.info("daily_target_hit symbol=%s qty=%d (flat all, stop for the day)", sym, d.qty)
        _try_place_order(d, skip_cooldown=True)


_last_strategy_run_time: float = 0.0


def run_strategy_for_symbols(symbols: list) -> None:
    """Run Green Light strategy (decide + place order) for each symbol. Uses tape data only (no news)."""
    if not symbols:
        return
    daily_cap = is_daily_cap_reached()
    drawdown_halt = is_drawdown_halt()
    t0 = _PERF()
    for sym in symbols:
        combined = dict(last_payload_by_symbol.get(sym, {}))
        combined.setdefault("return_1m", 0)
        combined.setdefault("return_5m", 0)
        combined.setdefault("annualized_vol_30d", 0)
        price_series = list(price_history_by_symbol[sym]) if brain_config.USE_TECHNICAL_INDICATORS else None
        tech = technical_score(
            price_series or [],
            rsi_period=getattr(brain_config, "RSI_PERIOD", 14),
            use_macd=getattr(brain_config, "USE_MACD", True),
            macd_fast=getattr(brain_config, "MACD_FAST", 12),
            macd_slow=getattr(brain_config, "MACD_SLOW", 26),
            macd_signal=getattr(brain_config, "MACD_SIGNAL", 9),
            use_patterns=getattr(brain_config, "USE_PATTERNS", True),
            pattern_lookback=getattr(brain_config, "PATTERN_LOOKBACK", 40),
        ) if price_series else None
        sent_ema = update_and_get_sentiment_ema(sym, tech if tech is not None else 0.0)
        prob = probability_gain(combined)
        pos_qty = positions_qty.get(sym, 0)
        try:
            pos_qty = int(pos_qty)
        except (TypeError, ValueError):
            pos_qty = 0
        sess = session_by_symbol.get(sym, "regular")
        pl_pct = position_unrealized_pl_pct.get(sym)
        cur_price = position_current_price.get(sym) or combined.get("price") or combined.get("mid")
        try:
            cur_price = float(cur_price) if cur_price is not None else None
        except (TypeError, ValueError):
            cur_price = None
        _structure_ok = _trend_ok(sym)
        _ltf_prices = list(price_history_by_symbol.get(sym, []))
        entry_ts = position_entry_time.get(sym)
        bars_held_days = max(0, int((time.time() - entry_ts) / 86400)) if entry_ts and entry_ts > 0 else None
        vwap_dist = _get_vwap_distance_pct(sym, cur_price)
        d = decide(sym, sent_ema, prob, pos_qty, sess, unrealized_pl_pct=pl_pct, daily_cap_reached=daily_cap, drawdown_halt=drawdown_halt, trend_ok=_trend_ok(sym), vol_ok=_vol_ok(sym), ofi=combined.get("ofi"), entry_price=position_entry_price.get(sym), current_price=cur_price, vwap_distance_pct=vwap_dist, scaled_50_at_vwap=(sym in _scaled_50_at_vwap), in_health_check_window=_is_in_health_check_window(), technical_score=tech, structure_ok=_structure_ok, ltf_prices=_ltf_prices, peak_unrealized_pl_pct=position_peak_unrealized_pl_pct.get(sym), bars_held=bars_held_days)
        if d.reason == "scale_out_50_at_vwap":
            _scaled_50_at_vwap.add(sym)
        log.info(
            "strategy symbol=%s technical=%.2f prob_gain=%.2f -> action=%s qty=%d reason=%s",
            d.symbol, tech or 0, prob, d.action, d.qty, d.reason,
        )
        snapshot_ctx = {
            "technical_score": tech,
            "ofi": combined.get("ofi"),
            "prob_gain": prob,
            "structure_ok": _structure_ok,
            "unrealized_pl_pct": pl_pct,
        }
        _try_place_order(d, price_override=cur_price, snapshot_context=snapshot_ctx)
        # Shadow: update ghost exit rules (tighter/loose stop-TP) when we have a position and price
        if pos_qty > 0 and cur_price is not None and cur_price > 0:
            try:
                from brain.shadow_strategy import shadow_update
                shadow_update(sym, cur_price)
            except Exception:
                pass
    log.debug("latency step=strategy_run symbols=%d ms=%.1f", len(symbols), (_PERF() - t0) * 1000)


def _maybe_run_strategy_interval() -> None:
    """If STRATEGY_INTERVAL_SEC has elapsed, run strategy for watchlist (not news-triggered)."""
    global _last_strategy_run_time
    interval = getattr(brain_config, "STRATEGY_INTERVAL_SEC", 45)
    if interval <= 0:
        return
    now = time.time()
    if now - _last_strategy_run_time < interval:
        return
    _last_strategy_run_time = now
    active = _get_active_symbols()
    if active is not None:
        symbols = list(active)
    else:
        symbols = list(last_payload_by_symbol.keys())
    if not symbols:
        return
    log.info("strategy interval run symbols=%s", symbols[:20])
    run_strategy_for_symbols(symbols)


def run_strategy_on_news(payload: dict) -> None:
    """On news: only update kill switch. Buys/sells are triggered by periodic strategy run, not news."""
    raw_news = score_news(payload)
    set_kill_switch_from_news(raw_news)


def handle_event(ev: dict) -> None:
    """Update state from event and run strategy/stop-loss when relevant (news, positions)."""
    typ = ev.get("type", "?")
    payload = ev.get("payload") or {}
    # Single gate: trading logic only on full trading days (market_calendar: weekends, holidays, half-days excluded).
    today_et = datetime.now(ZoneInfo("America/New_York")).date() if ZoneInfo else None
    _is_full_trading_day = today_et is not None and is_full_trading_day(today_et)

    if typ == "trade":
        sym = payload.get("symbol")
        if sym:
            tracker = _get_ofi_tracker()
            if tracker is not None:
                p = payload.get("price")
                size = payload.get("size") or 0
                try:
                    size = int(size)
                except (TypeError, ValueError):
                    size = 0
                if p is not None and isinstance(p, (int, float)) and p > 0 and size > 0:
                    prev = last_payload_by_symbol.get(sym, {})
                    ofi = tracker.update_trade(sym, float(p), size, bid=prev.get("bid"), ask=prev.get("ask"))
                    if ofi is not None:
                        payload = {**payload, "ofi": ofi}
            last_payload_by_symbol[sym] = {**last_payload_by_symbol.get(sym, {}), **payload}
            session_by_symbol[sym] = payload.get("session") or "regular"
            set_kill_switch_from_returns(payload.get("return_1m"), payload.get("return_5m"))
            p = payload.get("price")
            size = payload.get("size", 0)
            try:
                size = int(size) if size is not None else 0
            except (TypeError, ValueError):
                size = 0
            if p is not None and isinstance(p, (int, float)) and p > 0:
                price_history_by_symbol[sym].append(float(p))
            if p is not None and isinstance(p, (int, float)) and p > 0 and size > 0:
                _vwap_trades_by_symbol[sym].append((float(p), size))
    elif typ == "quote":
        sym = payload.get("symbol")
        if sym:
            tracker = _get_ofi_tracker()
            if tracker is not None:
                tracker.update_quote(sym, payload.get("bid"), payload.get("ask"))
            last_payload_by_symbol[sym] = {**last_payload_by_symbol.get(sym, {}), **payload}
            session_by_symbol[sym] = payload.get("session") or "regular"
            set_kill_switch_from_returns(payload.get("return_1m"), payload.get("return_5m"))
            mid = payload.get("mid")
            if mid is not None and isinstance(mid, (int, float)) and mid > 0:
                price_history_by_symbol[sym].append(float(mid))
    elif typ == "volatility":
        sym = payload.get("symbol")
        if sym:
            last_payload_by_symbol[sym] = {**last_payload_by_symbol.get(sym, {}), **payload}
    elif typ == "positions":
        global _last_equity
        positions_qty.clear()
        position_unrealized_pl_pct.clear()
        position_entry_price.clear()
        position_current_price.clear()
        # Keep position_peak_unrealized_pl_pct and position_entry_time; clean up after we rebuild positions
        for p in payload.get("positions") or []:
            sym = p.get("symbol")
            if not sym:
                continue
            qty = p.get("qty", 0)
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                qty = 0
            side = (p.get("side") or "long").lower()
            if side == "short":
                # Always store short as negative (API may send + or - qty)
                qty = -abs(qty)
            positions_qty[sym] = qty
            plpc = parse_unrealized_plpc(p.get("unrealized_plpc"))
            if plpc is not None:
                position_unrealized_pl_pct[sym] = plpc
                # Track peak so breakeven/trailing can fire (long and short)
                cur_peak = position_peak_unrealized_pl_pct.get(sym, plpc)
                position_peak_unrealized_pl_pct[sym] = max(cur_peak, plpc)
            if qty != 0:
                if sym not in position_entry_time:
                    position_entry_time[sym] = time.time()
                try:
                    cb = float(p.get("cost_basis") or 0)
                    abs_qty = abs(qty)
                    if cb > 0 and abs_qty > 0:
                        position_entry_price[sym] = cb / abs_qty
                except (TypeError, ValueError):
                    pass
                try:
                    cp = float(p.get("current_price") or 0)
                    if cp > 0:
                        position_current_price[sym] = cp
                except (TypeError, ValueError):
                    pass
        # Drop peak/entry_time/scale_out state only when position is flat (long and short use these while held)
        for sym in list(position_entry_time):
            if positions_qty.get(sym, 0) == 0:
                position_entry_time.pop(sym, None)
                position_peak_unrealized_pl_pct.pop(sym, None)
                _scale_out_done.pop(sym, None)
        for sym in list(_scaled_50_at_vwap):
            if positions_qty.get(sym, 0) == 0:
                _scaled_50_at_vwap.discard(sym)
        # Long-run: prune symbol-keyed caches to active list + positions so memory stays bounded
        active = _get_active_symbols()
        if active is not None:
            keep = set(positions_qty.keys()) | set(active)
            for sym in list(last_payload_by_symbol):
                if sym not in keep:
                    last_payload_by_symbol.pop(sym, None)
            for sym in list(session_by_symbol):
                if sym not in keep:
                    session_by_symbol.pop(sym, None)
            for sym in list(sentiment_by_symbol):
                if sym not in keep:
                    sentiment_by_symbol.pop(sym, None)
            for sym in list(price_history_by_symbol):
                if sym not in keep:
                    price_history_by_symbol.pop(sym, None)
            for sym in list(last_order_time_by_symbol):
                if sym not in keep:
                    last_order_time_by_symbol.pop(sym, None)
            for sym in list(_vwap_trades_by_symbol):
                if sym not in keep:
                    _vwap_trades_by_symbol.pop(sym, None)
        get_equity_ms = 0.0
        try:
            from brain.executor import get_account_equity
            t0 = _PERF()
            eq = get_account_equity()
            get_equity_ms = (_PERF() - t0) * 1000
            if eq is not None:
                _last_equity = eq
                update_equity(eq)
                update_drawdown_peak(eq)
        except Exception:
            pass
        t1 = _PERF()
        if _is_full_trading_day:
            run_stop_loss_check()
            run_flat_when_daily_target()
            run_close_losses_before_close()
            run_portfolio_health_check()
        else:
            log.info("skip trading (stop-loss/close/health): not a full trading day (weekend/holiday/half-day)")
        stop_loss_ms = (_PERF() - t1) * 1000
        log.debug("latency step=positions get_equity_ms=%.1f stop_loss_ms=%.1f", get_equity_ms, stop_loss_ms)
    elif typ == "news":
        if _is_full_trading_day:
            run_strategy_on_news(payload)
        else:
            log.info("skip strategy on news: not a full trading day (weekend/holiday/half-day)")
    # Periodic strategy run (Green Light) — only on full trading days
    if _is_full_trading_day:
        _maybe_run_strategy_interval()


def _run_scanner_at_startup() -> None:
    """Run the stock scanner once to refresh the daily opportunity pool (startup or 8am ET).
    May be invoked from a background thread at startup so the consumer can read stdin immediately."""
    path = getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
    if not path:
        return
    import subprocess
    # Repo root (sentry-bridge or /app in Docker) so paths like data/active_symbols.txt resolve correctly
    root = Path(__file__).resolve().parent.parent.parent
    script = root / "python-brain" / "apps" / "run_screener.py"
    if not script.exists():
        script = root / "apps" / "run_screener.py"
    if not script.exists():
        log.warning("run_screener.py not found at %s; skip scan", script)
        return
    try:
        log.info("running scanner to refresh opportunity pool -> %s", path)
        out_path = Path(path)
        if not out_path.is_absolute():
            out_path = root / path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(script), "--out", str(out_path)],
            cwd=str(root),
            env=os.environ,
            timeout=300,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            log.info("scanner finished; opportunity pool written to %s", path)
        else:
            log.warning("scanner exited %s: %s", result.returncode, (result.stderr or result.stdout or "")[:500])
    except subprocess.TimeoutExpired:
        log.warning("scanner timed out after 300s")
    except Exception as e:
        log.warning("scanner failed: %s", e)


def _run_optimizer_after_close() -> None:
    """Run the strategy optimizer (promote proposed->active, then run with 7-day rolling window)."""
    import subprocess
    root = Path(__file__).resolve().parent.parent.parent
    script = root / "python-brain" / "apps" / "strategy_optimizer.py"
    if not script.exists():
        script = root / "apps" / "strategy_optimizer.py"
    if not script.exists():
        log.warning("strategy_optimizer.py not found at %s; skip optimizer run", script)
        return
    try:
        et_now = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M") if ZoneInfo else "post-market"
        log.info("running strategy optimizer (post-market) at %s ET", et_now)
        result = subprocess.run(
            [sys.executable, str(script), "--write-proposed", "--rolling-days", "7"],
            cwd=str(root),
            env=os.environ,
            timeout=600,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            log.info("strategy optimizer finished")
        else:
            log.warning("strategy optimizer exited %s: %s", result.returncode, (result.stderr or result.stdout or "")[:500])
    except subprocess.TimeoutExpired:
        log.warning("strategy optimizer timed out after 600s")
    except Exception as e:
        log.warning("strategy optimizer failed: %s", e)


def _parse_run_at_et(s: str) -> Optional[tuple]:
    """Parse SCREENER_RUN_AT_ET (e.g. '07:00' or '7:00') -> (hour, minute) or None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    except (ValueError, IndexError):
        pass
    return None


def _scheduler_loop() -> None:
    """Background loop: at SCREENER_RUN_AT_ET (e.g. 8am ET) on full trading days, run the scanner."""
    run_at = getattr(brain_config, "SCREENER_RUN_AT_ET", "").strip()
    parsed = _parse_run_at_et(run_at)
    if not parsed or not ZoneInfo:
        log.warning("scanner scheduler disabled: SCREENER_RUN_AT_ET=%r or no zoneinfo", run_at)
        return
    hour, minute = parsed
    et = ZoneInfo("America/New_York")
    log.info("scanner scheduler started; will run at %02d:%02d ET on full trading days", hour, minute)
    while True:
        now_et = datetime.now(et)
        today_run = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_et >= today_run or not is_full_trading_day(today_run.date()):
            d = (now_et.date() + timedelta(days=1)) if now_et >= today_run else now_et.date()
            while not is_full_trading_day(d):
                d += timedelta(days=1)
            next_run = datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=et)
        else:
            next_run = today_run
        sleep_secs = (next_run - now_et).total_seconds()
        if sleep_secs > 0:
            log.debug("scanner next run at %s ET (in %.0fs)", next_run, sleep_secs)
            time.sleep(sleep_secs)
        run_date = next_run.date()
        if is_full_trading_day(run_date):
            if getattr(brain_config, "DISCOVERY_ENABLED", False):
                log.info("handoff: running discovery (Priority Watchlist) at %02d:%02d ET", hour, minute)
                run_discovery(
                    top_n=getattr(brain_config, "DISCOVERY_TOP_N", 10),
                    lookback_days=getattr(brain_config, "SCREENER_LOOKBACK_DAYS", 35),
                    z_threshold=2.0,
                    volume_spike_pct=15.0,
                )
            else:
                _run_scanner_at_startup()
        else:
            log.info("skip scanner: %s is not a full trading day", run_date)


def _optimizer_scheduler_loop() -> None:
    """Background loop: after market close (default 16:05 ET) on full trading days, run the strategy optimizer. Always on."""
    run_at = getattr(brain_config, "OPTIMIZER_RUN_AT_ET", "16:05").strip() or "16:05"
    parsed = _parse_run_at_et(run_at)
    if not ZoneInfo:
        log.warning("optimizer scheduler disabled: no zoneinfo")
        return
    if not parsed:
        parsed = (16, 5)
        log.info("optimizer scheduler using default 16:05 ET")
    hour, minute = parsed
    et = ZoneInfo("America/New_York")
    log.info("optimizer scheduler started; will run at %02d:%02d ET on full trading days", hour, minute)
    while True:
        now_et = datetime.now(et)
        today_run = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_et >= today_run or not is_full_trading_day(today_run.date()):
            d = (now_et.date() + timedelta(days=1)) if now_et >= today_run else now_et.date()
            while not is_full_trading_day(d):
                d += timedelta(days=1)
            next_run = datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=et)
        else:
            next_run = today_run
        sleep_secs = (next_run - now_et).total_seconds()
        if sleep_secs > 0:
            log.debug("optimizer next run at %s ET (in %.0fs)", next_run, sleep_secs)
            time.sleep(sleep_secs)
        run_date = next_run.date()
        if is_full_trading_day(run_date):
            log.info("running strategy optimizer at %02d:%02d ET", hour, minute)
            _run_optimizer_after_close()
        else:
            log.info("skip optimizer: %s is not a full trading day", run_date)


def main() -> None:
    from brain.log_config import init as init_logging
    init_logging()

    # Opportunity engine: scanner or two-stage discovery (7:00–9:30 ET) + handoff at 9:30.
    if getattr(brain_config, "OPPORTUNITY_ENGINE_ENABLED", False):
        path = getattr(brain_config, "ACTIVE_SYMBOLS_FILE", "").strip()
        run_at_et = getattr(brain_config, "SCREENER_RUN_AT_ET", "").strip()
        discovery_enabled = getattr(brain_config, "DISCOVERY_ENABLED", False)
        if path:
            if discovery_enabled and ZoneInfo:
                from brain.discovery import _in_discovery_window
                if _in_discovery_window(
                    discovery_parse_et(getattr(brain_config, "DISCOVERY_START_ET", "07:00")),
                    discovery_parse_et(getattr(brain_config, "DISCOVERY_END_ET", "09:30")),
                ):
                    run_discovery(top_n=getattr(brain_config, "DISCOVERY_TOP_N", 10))
                else:
                    # Run in background so we don't block stdin loop (scanner can take 2–5 min).
                    threading.Thread(target=_run_scanner_at_startup, daemon=True).start()
            else:
                threading.Thread(target=_run_scanner_at_startup, daemon=True).start()
        if path and run_at_et and _parse_run_at_et(run_at_et):
            t = threading.Thread(target=_scheduler_loop, daemon=True)
            t.start()
        if path and discovery_enabled:
            start_et = discovery_parse_et(getattr(brain_config, "DISCOVERY_START_ET", "07:00"))
            end_et = discovery_parse_et(getattr(brain_config, "DISCOVERY_END_ET", "09:30"))
            interval_min = getattr(brain_config, "DISCOVERY_INTERVAL_MIN", 5)
            engine = DiscoveryEngine(
                start_et=start_et,
                end_et=end_et,
                interval_sec=interval_min * 60,
                top_n=getattr(brain_config, "DISCOVERY_TOP_N", 10),
            )
            threading.Thread(target=engine.run_loop, daemon=True).start()
        active = _get_active_symbols()
        log.info("opportunity_engine enabled; active_symbols from %s: %s", path or "(no file)", list(active)[:20] if active else [])

    # Strategy optimizer: always run once per day after market close (16:05 ET unless overridden in config).
    if ZoneInfo:
        threading.Thread(target=_optimizer_scheduler_loop, daemon=True).start()

    log.info("reading from stdin (NDJSON)")
    if os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID"):
        paper = os.environ.get("TRADE_PAPER", "true").lower() in ("true", "1", "yes")
        live_ok = os.environ.get("LIVE_TRADING_ENABLED", "").lower() in ("true", "1", "yes")
        mode = "place paper orders" if paper else ("place live orders" if live_ok else "log decisions only")
        log.info("Alpaca keys set; TRADE_PAPER=%s LIVE_TRADING_ENABLED=%s (strategy will %s)", paper, live_ok, mode)
    else:
        log.info("No Alpaca keys; strategy will log decisions only (no orders)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            log_event(ev)
            t0 = _PERF()
            handle_event(ev)
            log.debug("latency step=event_handle type=%s ms=%.1f", ev.get("type", "?"), (_PERF() - t0) * 1000)
        except json.JSONDecodeError as e:
            log.error("invalid JSON: %s", e)
        except Exception as e:
            log.exception("error processing event")


if __name__ == "__main__":
    main()
