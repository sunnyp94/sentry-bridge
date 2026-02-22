#!/usr/bin/env python3
"""
Stdin consumer: entry point when Go pipes NDJSON to the brain.
Reads events from stdin, updates state, runs strategy (composite + rules), places paper orders when enabled.
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
from collections import defaultdict
from datetime import datetime

from brain.strategy import (
    sentiment_score_from_news,
    update_and_get_sentiment_ema,
    get_sentiment_ema,
    set_kill_switch_from_news,
    set_kill_switch_from_returns,
    probability_gain,
    decide,
    Decision,
    STOP_LOSS_PCT,
)
from brain.signals.composite import composite_score
from brain.rules.consensus import consensus_allows_buy
from brain.rules.daily_cap import update_equity, is_daily_cap_reached

log = logging.getLogger("brain")


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
session_by_symbol: dict[str, str] = defaultdict(lambda: "regular")
ORDER_COOLDOWN_SEC = 60
last_order_time_by_symbol: dict[str, float] = {}


def _parse_unrealized_plpc(raw) -> float | None:
    """Parse Alpaca unrealized_plpc (string or number) to decimal. None if missing/invalid."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if abs(v) > 1.0:
        v = v / 100.0
    return v


def _try_place_order(d: Decision) -> bool:
    """If decision is buy/sell with qty, respect cooldown and place order. Returns True if placed."""
    if d.action not in ("buy", "sell") or d.qty <= 0:
        return False
    now = time.time()
    if now - last_order_time_by_symbol.get(d.symbol, 0) < ORDER_COOLDOWN_SEC:
        log.warning("skip order (cooldown) symbol=%s", d.symbol)
        return False
    if os.environ.get("TRADE_PAPER", "true").lower() not in ("true", "1", "yes"):
        return False
    from brain.executor import place_order
    if place_order(d):
        last_order_time_by_symbol[d.symbol] = now
        return True
    return False


def run_stop_loss_check() -> None:
    """On positions update: sell any position at or below 5% loss (STOP_LOSS_PCT)."""
    stop_decimal = STOP_LOSS_PCT / 100.0
    for sym, pl_pct in position_unrealized_pl_pct.items():
        if pl_pct is None or pl_pct > -stop_decimal:
            continue
        pos_qty = positions_qty.get(sym, 0)
        try:
            pos_qty = int(pos_qty)
        except (TypeError, ValueError):
            pos_qty = 0
        if pos_qty <= 0:
            continue
        combined = dict(last_payload_by_symbol.get(sym, {}))
        combined.setdefault("return_1m", 0)
        combined.setdefault("return_5m", 0)
        combined.setdefault("annualized_vol_30d", 0)
        prob = probability_gain(combined)
        sent_ema = get_sentiment_ema(sym)
        sess = session_by_symbol.get(sym, "regular")
        d = decide(sym, sent_ema, prob, pos_qty, sess, unrealized_pl_pct=pl_pct, consensus_ok=True, daily_cap_reached=is_daily_cap_reached())
        if d.action == "sell" and d.qty > 0:
            log.warning("stop_loss symbol=%s pl_pct=%.2f%% sell qty=%d reason=%s", d.symbol, pl_pct * 100, d.qty, d.reason)
            _try_place_order(d)


def run_strategy_on_news(payload: dict) -> None:
    symbols = payload.get("symbols") or []
    if not symbols:
        return
    composite_result = composite_score(news_payload=payload, symbol_payload=None, social_score=None)
    raw_news = composite_result.sources["news"]
    set_kill_switch_from_news(raw_news)
    consensus_ok = consensus_allows_buy(composite_result)
    daily_cap = is_daily_cap_reached()
    for sym in symbols:
        combined = dict(last_payload_by_symbol.get(sym, {}))
        combined.setdefault("return_1m", 0)
        combined.setdefault("return_5m", 0)
        combined.setdefault("annualized_vol_30d", 0)
        cr_sym = composite_score(news_payload=payload, symbol_payload=combined, social_score=None)
        sentiment_by_symbol[sym] = cr_sym.composite
        sent_ema = update_and_get_sentiment_ema(sym, cr_sym.composite)
        prob = probability_gain(combined)
        pos_qty = positions_qty.get(sym, 0)
        try:
            pos_qty = int(pos_qty)
        except (TypeError, ValueError):
            pos_qty = 0
        sess = session_by_symbol.get(sym, "regular")
        pl_pct = position_unrealized_pl_pct.get(sym)
        d = decide(sym, sent_ema, prob, pos_qty, sess, unrealized_pl_pct=pl_pct, consensus_ok=consensus_ok, daily_cap_reached=daily_cap)
        log.info(
            "strategy symbol=%s sources=%s sentiment_ema=%.2f prob_gain=%.2f consensus_ok=%s -> action=%s qty=%d reason=%s",
            d.symbol, cr_sym.sources, sent_ema, prob, consensus_ok, d.action, d.qty, d.reason,
        )
        _try_place_order(d)


def handle_event(ev: dict) -> None:
    """Update state from event and run strategy/stop-loss when relevant (news, positions)."""
    typ = ev.get("type", "?")
    payload = ev.get("payload") or {}

    if typ == "trade":
        sym = payload.get("symbol")
        if sym:
            last_payload_by_symbol[sym] = {**last_payload_by_symbol.get(sym, {}), **payload}
            session_by_symbol[sym] = payload.get("session") or "regular"
            set_kill_switch_from_returns(payload.get("return_1m"), payload.get("return_5m"))
    elif typ == "quote":
        sym = payload.get("symbol")
        if sym:
            last_payload_by_symbol[sym] = {**last_payload_by_symbol.get(sym, {}), **payload}
            session_by_symbol[sym] = payload.get("session") or "regular"
            set_kill_switch_from_returns(payload.get("return_1m"), payload.get("return_5m"))
    elif typ == "volatility":
        sym = payload.get("symbol")
        if sym:
            last_payload_by_symbol[sym] = {**last_payload_by_symbol.get(sym, {}), **payload}
    elif typ == "positions":
        positions_qty.clear()
        position_unrealized_pl_pct.clear()
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
                qty = -qty
            positions_qty[sym] = qty
            plpc = _parse_unrealized_plpc(p.get("unrealized_plpc"))
            if plpc is not None:
                position_unrealized_pl_pct[sym] = plpc
        try:
            from brain.executor import get_account_equity
            eq = get_account_equity()
            if eq is not None:
                update_equity(eq)
        except Exception:
            pass
        run_stop_loss_check()
    elif typ == "news":
        run_strategy_on_news(payload)


def main() -> None:
    from brain.log_config import init as init_logging
    init_logging()

    log.info("reading from stdin (NDJSON)")
    if os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID"):
        trade = os.environ.get("TRADE_PAPER", "true").lower() in ("true", "1", "yes")
        log.info("Alpaca keys set; TRADE_PAPER=%s (strategy will %s)", trade, "place paper orders" if trade else "log decisions only")
    else:
        log.info("No Alpaca keys; strategy will log decisions only (no orders)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            log_event(ev)
            handle_event(ev)
        except json.JSONDecodeError as e:
            log.error("invalid JSON: %s", e)
        except Exception as e:
            log.exception("error processing event")


if __name__ == "__main__":
    main()
