"""
Executor: places buy/sell orders on Alpaca (paper by default).
Uses limit orders when USE_LIMIT_ORDERS=true and current_price is provided (reduces slippage).
Otherwise market orders. Also exposes get_account_equity() for rules.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

from brain.core import config
from brain.strategy import Decision

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
                            log.info("get_account_equity equity=%.2f", f)
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


def _get_latest_quote_price(symbol: str) -> Optional[float]:
    """Fetch latest quote mid from Alpaca data API. Used when USE_LIMIT_ORDERS=true but caller didn't provide price (e.g. buy before any stream data)."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest
    except ImportError:
        return None
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        return None
    try:
        client = StockHistoricalDataClient(key, secret)
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = client.get_stock_latest_quote(req)
        if not quotes or symbol not in quotes:
            return None
        q = quotes.get(symbol)
        if q is None:
            return None
        bid = getattr(q, "bid_price", None) or 0.0
        ask = getattr(q, "ask_price", None) or 0.0
        if bid > 0 and ask > 0:
            return round((float(bid) + float(ask)) / 2.0, 2)
        if bid > 0:
            return round(float(bid), 2)
        if ask > 0:
            return round(float(ask), 2)
        return None
    except Exception as e:
        log.debug("get_latest_quote_price %s: %s", symbol, e)
        return None


def place_order(decision: Decision, current_price: Optional[float] = None) -> bool:
    """
    Place order for the given decision. Returns True if submitted.
    When USE_LIMIT_ORDERS=true and current_price is set: submit limit order
    (buy below mid, sell above mid by LIMIT_ORDER_OFFSET_BPS) to reduce slippage.
    Otherwise submit market order.
    For buys when USE_LIMIT_ORDERS=true but no price was provided, fetches latest quote so limit is still used.
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
    # When limit orders are requested for a buy but no price was provided (e.g. no stream data yet), fetch latest quote
    if (
        config.USE_LIMIT_ORDERS
        and decision.action == "buy"
        and (current_price is None or current_price <= 0)
    ):
        fetched = _get_latest_quote_price(decision.symbol)
        if fetched is not None and fetched > 0:
            current_price = fetched
            log.info("place_order BUY using fetched quote price=%.2f for limit", current_price)
    price_str = f"{current_price:.2f}" if current_price is not None and current_price > 0 else "market"
    log.info("place_order %s %s qty=%d price=%s", decision.action.upper(), decision.symbol, decision.qty, price_str)
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


def close_all_positions(positions: List[Dict[str, Any]], reason: str = "flat_on_startup") -> int:
    """
    Cancel all open orders, then place market sell for each position.
    Used for flat-on-startup (safe restart). You cannot sell a position while it has an open order.
    positions: list of dicts with symbol, qty, optional side, optional current_price. May be empty (cancel-only).
    Returns number of sell orders submitted.
    """
    client = _client()
    if client is None or MarketOrderRequest is None or OrderSide is None or TimeInForce is None:
        log.warning("close_all_positions: no client or alpaca; skip")
        return 0
    # Cancel all open orders first so position sells are not blocked (and to clear pending orders on restart)
    try:
        result = client.cancel_orders()
        if isinstance(result, list) and result:
            log.info("flat_on_startup: cancelled %d open order(s)", len(result))
        elif result:
            log.info("flat_on_startup: cancelled open orders")
    except Exception as e:
        log.warning("flat_on_startup: cancel_orders failed (will still try to close positions): %s", e)
    if not positions:
        return 0
    placed = 0
    for p in positions:
        sym = (p.get("symbol") or "").strip()
        if not sym:
            continue
        qty = p.get("qty", 0)
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            continue
        side = (p.get("side") or "long").lower()
        if side == "short":
            qty = -qty
        sell_qty = abs(qty)
        if sell_qty <= 0:
            continue
        try:
            req = MarketOrderRequest(
                symbol=sym,
                qty=sell_qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            client.submit_order(req)
            placed += 1
            log.info("flat_on_startup sell %s qty=%d", sym, sell_qty)
        except Exception as e:
            log.warning("flat_on_startup sell %s qty=%d failed: %s", sym, sell_qty, e)
    if placed:
        log.info("flat_on_startup: placed %d sell order(s)", placed)
    return placed
