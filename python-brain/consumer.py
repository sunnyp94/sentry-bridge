#!/usr/bin/env python3
"""
Brain consumer: reads NDJSON events from stdin (piped from Go engine).
- Logs all events (trades, quotes, news, volatility, positions, orders).
- Strategy: on news, computes sentiment + probability of gain and decides buy/sell/hold.
- Executor: when paper trading is enabled, places orders on Alpaca (paper account).

Positions = your current holdings (e.g. 10 shares AAPL). Orders = open buy/sell
orders not yet filled. Go sends these so the strategy knows what you own and
what's already pending.

Run by the Go engine when BRAIN_CMD is set. Set APCA_API_KEY_ID, APCA_API_SECRET_KEY
and TRADE_PAPER=true to enable paper trading (strategy decides; executor places orders).
"""
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

from strategy import (
    sentiment_score_from_news,
    update_and_get_sentiment_ema,
    get_sentiment_ema,
    set_kill_switch_from_news,
    set_kill_switch_from_returns,
    probability_gain,
    decide,
    Decision,
)

log = logging.getLogger("brain")


def format_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return ts


def log_event(ev: dict) -> None:
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


# --- Strategy state (updated from events) ---
sentiment_by_symbol: dict[str, float] = defaultdict(float)
last_payload_by_symbol: dict[str, dict] = {}
positions_qty: dict[str, int] = {}   # symbol -> signed qty (long positive)
position_unrealized_pl_pct: dict[str, float] = {}  # symbol -> decimal e.g. -0.05 for -5%
session_by_symbol: dict[str, str] = defaultdict(lambda: "regular")
ORDER_COOLDOWN_SEC = 60
last_order_time_by_symbol: dict[str, float] = {}

# 5% stop loss (must match strategy.STOP_LOSS_PCT)
STOP_LOSS_PCT_DECIMAL = 0.05


def _parse_unrealized_plpc(raw) -> float | None:
    """Parse Alpaca unrealized_plpc (string or number) to decimal. None if missing/invalid."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    # If |v| > 1 assume percent (e.g. -5.5) -> -0.055
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
    from executor import place_order
    if place_order(d):
        last_order_time_by_symbol[d.symbol] = now
        return True
    return False


def run_stop_loss_check() -> None:
    """On positions update: sell any position at or below 5% loss (STOP_LOSS_PCT)."""
    from strategy import STOP_LOSS_PCT
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
        d = decide(sym, sent_ema, prob, pos_qty, sess, unrealized_pl_pct=pl_pct)
        if d.action == "sell" and d.qty > 0:
            log.warning("stop_loss symbol=%s pl_pct=%.2f%% sell qty=%d reason=%s", d.symbol, pl_pct * 100, d.qty, d.reason)
            _try_place_order(d)


def run_strategy_on_news(payload: dict) -> None:
    symbols = payload.get("symbols") or []
    if not symbols:
        return
    # FinBERT (or VADER) on headline + summary for smarter signal; then EMA per symbol
    sent_raw = sentiment_score_from_news(payload)
    # Kill switch: very bad news disables all new buys (market tanks / bad news)
    set_kill_switch_from_news(sent_raw)
    for sym in symbols:
        sentiment_by_symbol[sym] = sent_raw
    for sym in symbols:
        sent_ema = update_and_get_sentiment_ema(sym, sent_raw)
        combined = dict(last_payload_by_symbol.get(sym, {}))
        combined.setdefault("return_1m", 0)
        combined.setdefault("return_5m", 0)
        combined.setdefault("annualized_vol_30d", 0)
        prob = probability_gain(combined)
        pos_qty = positions_qty.get(sym, 0)
        try:
            pos_qty = int(pos_qty)
        except (TypeError, ValueError):
            pos_qty = 0
        sess = session_by_symbol.get(sym, "regular")
        pl_pct = position_unrealized_pl_pct.get(sym)
        d = decide(sym, sent_ema, prob, pos_qty, sess, unrealized_pl_pct=pl_pct)
        log.info("strategy symbol=%s sentiment_raw=%.2f sentiment_ema=%.2f prob_gain=%.2f -> action=%s qty=%d reason=%s", d.symbol, sent_raw, sent_ema, prob, d.action, d.qty, d.reason)
        _try_place_order(d)


def handle_event(ev: dict) -> None:
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
        run_stop_loss_check()
    elif typ == "news":
        run_strategy_on_news(payload)


def main() -> None:
    from log_config import init as init_logging
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
