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
    """Return current account equity from Alpaca. Used for daily cap and position sizing. None only if API/client unavailable after retries."""
    if TradingClient is None:
        log.warning("get_account_equity: alpaca-py not installed")
        return None
    client = _client()
    if client is None:
        log.warning("get_account_equity: APCA_API_KEY_ID or APCA_API_SECRET_KEY not set")
        return None
    last_error = None
    for attempt in range(3):
        try:
            t0 = time.perf_counter()
            acc = client.get_account()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log.info("latency step=get_account_equity ms=%.1f", elapsed_ms)
            if acc is None:
                last_error = "client.get_account() returned None"
                log.warning("get_account_equity (attempt %d/3): %s", attempt + 1, last_error)
                if attempt < 2:
                    time.sleep(1.0)
                continue
            for attr in ("equity", "portfolio_value", "last_equity"):
                val = getattr(acc, attr, None)
                if val is not None:
                    try:
                        f = float(val)
                        if f > 0:
                            return f
                    except (TypeError, ValueError):
                        pass
            last_error = "account has no usable equity/portfolio_value/last_equity"
            log.warning("get_account_equity (attempt %d/3): %s (acc=%s)", attempt + 1, last_error, type(acc).__name__)
        except Exception as e:
            last_error = str(e)
            log.warning("get_account_equity (attempt %d/3): %s", attempt + 1, e, exc_info=True)
        if attempt < 2:
            time.sleep(1.0)
    log.error("get_account_equity: failed after 3 attempts. Last error: %s", last_error)
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
