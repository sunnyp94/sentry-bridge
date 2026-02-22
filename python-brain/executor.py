"""
Execute strategy decisions on Alpaca (paper trading by default).
Uses alpaca-py; credentials from APCA_API_KEY_ID, APCA_API_SECRET_KEY.
"""
import logging
import os
from typing import Optional

from strategy import Decision

log = logging.getLogger("executor")

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest
except ImportError:
    TradingClient = None
    MarketOrderRequest = None
    OrderSide = TimeInForce = None


def _client():
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return None
    paper = os.environ.get("APCA_PAPER", "true").lower() in ("true", "1", "yes") or os.environ.get("TRADE_PAPER", "").lower() in ("true", "1", "yes")
    return TradingClient(key, secret, paper=paper)


def place_order(decision: Decision) -> bool:
    """Place a market order for the given decision. Returns True if submitted."""
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
    try:
        req = MarketOrderRequest(
            symbol=decision.symbol,
            qty=decision.qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        log.info("%s %d %s -> order id=%s", decision.action.upper(), decision.qty, decision.symbol, getattr(order, "id", "?"))
        return True
    except Exception as e:
        log.exception("order failed: %s", e)
        return False
