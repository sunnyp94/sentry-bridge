"""
Executor: places buy/sell orders on Alpaca (paper by default).
Uses limit orders when USE_LIMIT_ORDERS=true and current_price is provided (reduces slippage).
Otherwise market orders. Also exposes get_account_equity() for rules.
"""
import logging
import os
import time
from typing import Optional

from . import config
from .strategy import Decision

log = logging.getLogger("brain.executor")

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
except ImportError:
    TradingClient = None
    MarketOrderRequest = None
    LimitOrderRequest = None
    OrderSide = TimeInForce = None


def _client():
    """Build Alpaca TradingClient (paper when TRADE_PAPER or APCA_PAPER is true)."""
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return None
    paper = os.environ.get("APCA_PAPER", "true").lower() in ("true", "1", "yes") or os.environ.get("TRADE_PAPER", "").lower() in ("true", "1", "yes")
    return TradingClient(key, secret, paper=paper)


def get_account_equity() -> Optional[float]:
    """Return current account equity from Alpaca. Used by rules.daily_cap to compute daily PnL and 0.2% shutdown. None if unavailable."""
    if TradingClient is None:
        return None
    client = _client()
    if client is None:
        return None
    try:
        t0 = time.perf_counter()
        acc = client.get_account()
        log.info("latency step=get_account_equity ms=%.1f", (time.perf_counter() - t0) * 1000)
        if acc is None:
            return None
        eq = getattr(acc, "equity", None)
        if eq is None:
            return None
        return float(eq)
    except Exception:
        return None


def place_order(decision: Decision, current_price: Optional[float] = None) -> bool:
    """
    Place order for the given decision. Returns True if submitted.
    When USE_LIMIT_ORDERS=true and current_price is set: submit limit order
    (buy below mid, sell above mid by LIMIT_ORDER_OFFSET_BPS) to reduce slippage.
    Otherwise submit market order.
    """
    if decision.action == "hold" or decision.qty <= 0:
        return False
    if TradingClient is None or MarketOrderRequest is None:
        log.error("alpaca-py not installed. Run: python3 -m pip install alpaca-py (or: pip install -r requirements.txt)")
        return False
    client = _client()
    if client is None:
        log.error("APCA_API_KEY_ID / APCA_API_SECRET_KEY not set")
        return False
    side = OrderSide.BUY if decision.action == "buy" else OrderSide.SELL
    use_limit = config.USE_LIMIT_ORDERS and current_price is not None and current_price > 0 and LimitOrderRequest is not None
    try:
        t0 = time.perf_counter()
        if use_limit:
            bps = config.LIMIT_ORDER_OFFSET_BPS
            offset = bps / 10000.0
            if decision.action == "buy":
                limit_price = round(current_price * (1.0 - offset), 2)
            else:
                limit_price = round(current_price * (1.0 + offset), 2)
            req = LimitOrderRequest(
                symbol=decision.symbol,
                qty=decision.qty,
                side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price,
            )
            order = client.submit_order(req)
            log.info(
                "latency step=submit_order ms=%.1f LIMIT %s %d %s @ %.2f -> order id=%s",
                (time.perf_counter() - t0) * 1000, decision.action.upper(), decision.qty, decision.symbol, limit_price, getattr(order, "id", "?"),
            )
        else:
            req = MarketOrderRequest(
                symbol=decision.symbol,
                qty=decision.qty,
                side=side,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(req)
            log.info(
                "latency step=submit_order ms=%.1f %s %d %s -> order id=%s",
                (time.perf_counter() - t0) * 1000, decision.action.upper(), decision.qty, decision.symbol, getattr(order, "id", "?"),
            )
        return True
    except Exception as e:
        log.exception("order failed: %s", e)
        return False
