#!/usr/bin/env python3
"""
Backtest the strategy on real historical daily bars from Alpaca (Data API: IEX or SIP).
Uses same decide() and config as production. No news in backtest so sentiment = technical (RSI + MACD + patterns) + momentum proxy.
Run: python3 apps/backtest.py [--symbols ...] [--days 90] [--years 2]
"""
import argparse
import os
import sys
import warnings

# Suppress urllib3/OpenSSL version warning (environment-dependent, not actionable in backtest)
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*", module="urllib3")
from datetime import datetime, timezone, timedelta
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# So backtest can buy/sell any bar (no bar timestamps in this loop)
os.environ["BACKTEST_SESSION_SKIP"] = "1"

import numpy as np
import pandas as pd

from brain import config as brain_config
from brain.data import get_bars, SPY_SYMBOL
from brain.strategy import decide, probability_gain, Decision
from brain.signals.technical import technical_score
from brain.signals.microstructure import (
    vwap_from_ohlcv,
    vwap_distance_pct,
    atr_series,
    atr_stop_pct as atr_stop_pct_fn,
    atr_percentile_series,
    returns_zscore_from_prices,
)
from brain import sizing as brain_sizing
from brain import regime as brain_regime


def _build_symbol_series(bars_by_sym: dict, symbols: list, brain_config) -> tuple:
    """Build per-symbol series (closes, opens, payloads, technical, vwap, atr, zscore, sma). Returns (data_by_sym, n_min) or (None, 0)."""
    data_by_sym = {}
    n_min = 0
    for symbol in symbols:
        if symbol not in bars_by_sym:
            continue
        df = bars_by_sym[symbol].sort_index().copy()
        if "close" not in df.columns and "c" in df.columns:
            df["close"] = df["c"]
        if "open" not in df.columns and "o" in df.columns:
            df["open"] = df["o"]
        if "high" not in df.columns and "h" in df.columns:
            df["high"] = df["h"]
        if "low" not in df.columns and "l" in df.columns:
            df["low"] = df["l"]
        if "volume" not in df.columns and "v" in df.columns:
            df["volume"] = df["v"]
        if "close" not in df.columns:
            continue
        closes = df["close"].astype(float).tolist()
        opens = df["open"].astype(float).tolist() if "open" in df.columns else list(closes)
        highs = df["high"].astype(float).tolist() if "high" in df.columns else closes
        lows = df["low"].astype(float).tolist() if "low" in df.columns else closes
        volumes = df["volume"].astype(float).tolist() if "volume" in df.columns else [1.0] * len(closes)
        n = len(closes)
        if n < 30:
            continue
        vwap_series, _ = vwap_from_ohlcv(highs, lows, closes, volumes, lookback=getattr(brain_config, "VWAP_LOOKBACK", 20) or None)
        atr_list, _ = atr_series(highs, lows, closes, period=getattr(brain_config, "ATR_PERIOD", 14))
        atr_pct_lookback = getattr(brain_config, "ATR_PERCENTILE_LOOKBACK", 60)
        atr_pct_series, _ = atr_percentile_series(atr_list or [], lookback=atr_pct_lookback)
        zscore_series, _ = returns_zscore_from_prices(closes, period=getattr(brain_config, "ZSCORE_PERIOD", 20))
        returns_1d = df["close"].pct_change()
        returns_5d = df["close"].pct_change(5)
        vol_30d = df["close"].pct_change().rolling(30).std() * (252 ** 0.5)
        payloads = []
        for i in range(n):
            r1 = returns_1d.iloc[i] if not pd.isna(returns_1d.iloc[i]) else None
            r5 = returns_5d.iloc[i] if i >= 5 and not pd.isna(returns_5d.iloc[i]) else None
            v = vol_30d.iloc[i] if not pd.isna(vol_30d.iloc[i]) and vol_30d.iloc[i] > 0 else 0.25
            payloads.append({"return_1m": r1, "return_5m": r5, "annualized_vol_30d": v})
        technical_scores = []
        for i in range(n):
            s = technical_score(
                closes[: i + 1],
                rsi_period=brain_config.RSI_PERIOD,
                use_macd=getattr(brain_config, "USE_MACD", True),
                macd_fast=getattr(brain_config, "MACD_FAST", 12),
                macd_slow=getattr(brain_config, "MACD_SLOW", 26),
                macd_signal=getattr(brain_config, "MACD_SIGNAL", 9),
                use_patterns=getattr(brain_config, "USE_PATTERNS", True),
                pattern_lookback=getattr(brain_config, "PATTERN_LOOKBACK", 40),
                highs=highs[: i + 1] if highs and len(highs) >= i + 1 else None,
                lows=lows[: i + 1] if lows and len(lows) >= i + 1 else None,
            )
            technical_scores.append(s if s is not None else 0.0)
        sma_series = pd.Series(closes).rolling(getattr(brain_config, "TREND_SMA_PERIOD", 20), min_periods=getattr(brain_config, "TREND_SMA_PERIOD", 20)).mean()
        data_by_sym[symbol] = {
            "closes": closes,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "payloads": payloads,
            "technical_scores": technical_scores,
            "rsi_scores": technical_scores,
            "vwap_series": vwap_series,
            "atr_list": atr_list,
            "atr_percentile_series": atr_pct_series,
            "zscore_series": zscore_series,
            "sma_series": sma_series,
            "n": n,
        }
        n_min = min(n_min, n) if n_min else n
    return data_by_sym, n_min


def _momentum(p):
    r1, r5 = p.get("return_1m") or 0, p.get("return_5m") or 0
    r1 = max(-1, min(1, r1 * 15))
    r5 = max(-1, min(1, r5 * 5))
    return 0.6 * r1 + 0.4 * r5


def _build_spy_below_200ma(bars_by_sym: dict, n_min: int) -> list:
    """Build per-bar list: True when SPY close < 200-day SMA. Length n_min; align by bar index (0=oldest)."""
    out = [False] * n_min
    if SPY_SYMBOL not in bars_by_sym or n_min < 200:
        return out
    spy_df = bars_by_sym[SPY_SYMBOL].sort_index()
    if "close" not in spy_df.columns and "c" in spy_df.columns:
        spy_df = spy_df.copy()
        spy_df["close"] = spy_df["c"]
    if "close" not in spy_df.columns or len(spy_df) < n_min:
        return out
    closes = spy_df["close"].astype(float).iloc[-n_min:]
    sma200 = spy_df["close"].astype(float).rolling(200, min_periods=200).mean().iloc[-n_min:]
    for i in range(n_min):
        s = sma200.iloc[i] if i < len(sma200) else np.nan
        if not np.isnan(s) and s > 0:
            out[i] = float(closes.iloc[i]) < float(s)
    return out


def run_backtest_unified(symbols: list[str], days: int = 90, initial_cash: float = 100_000.0, debug: bool = False):
    """Single portfolio, bar-by-bar: when daily PnL >= DAILY_PROFIT_TARGET_PCT, flat all and no new buys (profit daily and stop)."""
    spy_regime_enabled = getattr(brain_config, "SPY_200MA_REGIME_ENABLED", False)
    fetch_symbols = list(symbols) + [SPY_SYMBOL] if spy_regime_enabled else list(symbols)
    bars_by_sym = get_bars(fetch_symbols, days)
    if not bars_by_sym:
        return None
    data_by_sym, n_min = _build_symbol_series(bars_by_sym, symbols, brain_config)
    if not data_by_sym or n_min < 30:
        return None
    symbols_list = list(data_by_sym.keys())
    spy_below_200ma_list = _build_spy_below_200ma(bars_by_sym, n_min) if spy_regime_enabled else [False] * n_min
    daily_target_pct = getattr(brain_config, "DAILY_PROFIT_TARGET_PCT", 0.1) / 100.0
    max_qty = getattr(brain_config, "STRATEGY_MAX_QTY", 2)
    position_size_pct = getattr(brain_config, "POSITION_SIZE_PCT", 0.01)
    vol_max = getattr(brain_config, "VOL_MAX_FOR_ENTRY", 0)
    atr_mult = getattr(brain_config, "ATR_STOP_MULTIPLE", 2.0)

    cash = initial_cash
    positions = {}  # symbol -> (qty, cost)
    bars_held = {}
    peak_unrealized = {}
    trades_by_sym = {s: [] for s in symbols_list}
    scale_out_done = {s: set() for s in symbols_list}  # levels (e.g. 0.01) already scaled per symbol
    try:
        scale_levels_pct = [float(x.strip()) / 100.0 for x in (getattr(brain_config, "SCALE_OUT_LEVELS_PCT", "1,2,3") or "1,2,3").split(",")]
    except Exception:
        scale_levels_pct = [0.01, 0.02, 0.03]
    scale_out_pct = getattr(brain_config, "SCALE_OUT_PCT_PER_LEVEL", 25) / 100.0
    scale_out_enabled = getattr(brain_config, "SCALE_OUT_ENABLED", False)
    regime_enabled = getattr(brain_config, "REGIME_FILTER_ENABLED", False)
    risk_pct = getattr(brain_config, "RISK_PCT_PER_TRADE", 0)
    corr_enabled = getattr(brain_config, "CORRELATION_CHECK_ENABLED", False)
    corr_thresh = getattr(brain_config, "CORRELATION_THRESHOLD", 0.7)
    corr_reduce = getattr(brain_config, "CORRELATION_SIZE_REDUCTION", 0.5)
    fill_at_next_open = getattr(brain_config, "BACKTEST_FILL_AT_NEXT_OPEN", True)
    commission = getattr(brain_config, "BACKTEST_COMMISSION_PER_TRADE", 0.0)
    slippage_bps = getattr(brain_config, "BACKTEST_SLIPPAGE_BPS", 0.0)
    slippage_mult_buy = 1.0 + (slippage_bps / 10000.0)
    slippage_mult_sell = 1.0 - (slippage_bps / 10000.0)
    days_hit_target = 0
    debug_hold_reasons = {} if debug else None
    debug_sell_reasons = {} if debug else None
    debug_bars_would_buy = 0
    debug_bars_mom_filter = 0

    for i in range(30, n_min):
        start_equity = cash + sum(positions.get(s, (0, 0))[0] * data_by_sym[s]["closes"][i] for s in symbols_list if s in data_by_sym)
        daily_target_hit = False

        for symbol in symbols_list:
            d = data_by_sym[symbol]
            closes = d["closes"]
            opens = d.get("opens", closes)
            close = float(closes[i])
            # Fill at next bar's open (no look-ahead): signal at close[i] -> execute at open[i+1]
            fill_open_next = float(opens[i + 1]) if fill_at_next_open and (i + 1) < len(opens) else close
            payload = d["payloads"][i].copy()
            payload["return_1m"] = payload["return_1m"] if payload["return_1m"] is not None else 0.0
            payload["return_5m"] = payload["return_5m"] if payload["return_5m"] is not None else 0.0
            prob = probability_gain(payload)
            sentiment = 0.7 * (d["rsi_scores"][i] or 0.0) + 0.3 * _momentum(payload)
            sentiment = max(-1.0, min(1.0, sentiment))
            mom = _momentum(payload)
            sma_val = d["sma_series"].iloc[i] if i < len(d["sma_series"]) and not pd.isna(d["sma_series"].iloc[i]) else None
            trend_ok = (close > float(sma_val)) if sma_val is not None else None
            position_qty, position_cost = positions.get(symbol, (0, 0.0))
            unrealized_pl_pct = (close - position_cost) / position_cost if position_cost and position_qty else None
            if position_qty > 0:
                bars_held[symbol] = bars_held.get(symbol, 0) + 1
                if unrealized_pl_pct is not None:
                    peak_unrealized[symbol] = max(peak_unrealized.get(symbol, 0), unrealized_pl_pct)
            vol_ok = (float(payload.get("annualized_vol_30d") or 0) <= vol_max) if vol_max > 0 else None
            vwap_series = d.get("vwap_series")
            vwap_dist = vwap_distance_pct(close, vwap_series[i]) if vwap_series and i < len(vwap_series) else None
            atr_val = d["atr_list"][i] if d["atr_list"] and i < len(d["atr_list"]) else None
            atr_stop_pct = atr_stop_pct_fn(close, atr_val, atr_mult) if atr_val and close else None
            atr_pct_val = None
            if d.get("atr_percentile_series") and i < len(d["atr_percentile_series"]):
                atr_pct_val = d["atr_percentile_series"][i]
            zscore_val = d["zscore_series"][i] if d.get("zscore_series") and i < len(d["zscore_series"]) else None

            did_scale_out = False
            if scale_out_enabled and position_qty > 0 and unrealized_pl_pct is not None:
                for level in scale_levels_pct:
                    if unrealized_pl_pct >= level and level not in scale_out_done[symbol]:
                        sell_qty = max(1, int(position_qty * scale_out_pct))
                        sell_qty = min(sell_qty, position_qty)
                        if sell_qty > 0:
                            fill_price = fill_open_next
                            proceeds = sell_qty * fill_price * slippage_mult_sell - commission
                            cash += proceeds
                            new_qty = position_qty - sell_qty
                            if new_qty <= 0:
                                positions[symbol] = (0, 0.0)
                                bars_held[symbol] = 0
                                peak_unrealized[symbol] = 0.0
                            else:
                                positions[symbol] = (new_qty, position_cost)
                            scale_out_done[symbol].add(level)
                            trades_by_sym[symbol].append(("sell", fill_price, sell_qty, proceeds))
                            did_scale_out = True
                        break  # one level per bar
            if did_scale_out:
                continue  # skip decide() this bar for this symbol

            # Regime (Pillar 2)
            regime = None
            if regime_enabled and len(closes) > i + 1:
                atr_list_sym = d.get("atr_list")
                regime = brain_regime.get_regime(closes[: i + 1], atr_list_sym[: i + 1] if atr_list_sym else None)

            # When daily target hit: no new buys (let winners run). Don't force-sell.
            daily_cap_reached = daily_target_hit
            d_dec = decide(
                symbol,
                sentiment=sentiment,
                prob_gain=prob,
                position_qty=position_qty,
                session="regular",
                unrealized_pl_pct=unrealized_pl_pct,
                consensus_ok=True,
                daily_cap_reached=daily_cap_reached,
                drawdown_halt=False,
                trend_ok=trend_ok,
                vol_ok=vol_ok,
                peak_unrealized_pl_pct=peak_unrealized.get(symbol) if position_qty > 0 else None,
                bars_held=bars_held.get(symbol) if position_qty > 0 else None,
                atr_stop_pct=atr_stop_pct,
                vwap_distance_pct=vwap_dist,
                returns_zscore=zscore_val,
                ofi=None,
                atr_percentile=atr_pct_val,
                entry_price=position_cost if position_qty > 0 else None,
                current_price=close,
                regime=regime,
                spy_below_200ma=spy_below_200ma_list[i] if spy_regime_enabled else None,
            )
            action = d_dec.action
            # Backtest filter: only block buy on big down days (relaxed: was mom<-0.10 or ret1d<-2%)
            # Only block buy on extreme down days (mean reversion wants moderate dips)
            r1 = payload.get("return_1m") or 0
            if action == "buy" and (mom < -0.40 or r1 < -0.08):
                if debug:
                    debug_bars_mom_filter += 1
                action = "hold"
            if debug:
                r = (d_dec.reason or "hold")[:60]
                if action == "hold":
                    debug_hold_reasons[r] = debug_hold_reasons.get(r, 0) + 1
                elif action == "sell":
                    debug_sell_reasons[r] = debug_sell_reasons.get(r, 0) + 1
                if d_dec.action == "buy" and position_qty == 0:
                    debug_bars_would_buy += 1

            if action == "buy" and position_qty == 0 and not daily_target_hit:
                # Fill at next bar's open (no look-ahead); skip buy on last bar if no next open
                fill_price = fill_open_next if (not fill_at_next_open or (i + 1) < n_min) else None
                if fill_price is None or fill_price <= 0:
                    pass
                else:
                    equity = cash + sum(positions.get(s, (0, 0))[0] * data_by_sym[s]["closes"][i] for s in symbols_list)
                    # Pillar 1: risk-based sizing when RISK_PCT_PER_TRADE > 0 and ATR available
                    if risk_pct > 0 and atr_val and atr_val > 0:
                        qty = brain_sizing.position_size_shares(equity, fill_price, atr=atr_val, atr_stop_multiple=atr_mult, max_qty=max_qty)
                    else:
                        qty = max(1, min(max_qty, int((equity * position_size_pct) / fill_price))) if position_size_pct > 0 else min(1, max_qty)
                    # Global filter: when SPY below 200 MA, reduce long size
                    if spy_regime_enabled and spy_below_200ma_list[i]:
                        mult = getattr(brain_config, "SPY_BELOW_200MA_LONG_SIZE_MULTIPLIER", 0.5)
                        qty = max(1, int(qty * mult))
                    # Correlation: reduce size if new position highly correlated with existing
                    if corr_enabled and qty > 1 and i >= 20:
                        c_s = np.array(closes[i - 21 : i + 1], dtype=float)
                        if np.any(c_s[:-1] == 0):
                            pass
                        else:
                            ret_s = np.diff(c_s) / c_s[:-1]
                            for other in symbols_list:
                                if other == symbol or positions.get(other, (0, 0))[0] <= 0:
                                    continue
                                o_closes = data_by_sym[other]["closes"]
                                if len(o_closes) < i + 1 or i < 20:
                                    continue
                                c_o = np.array(o_closes[i - 21 : i + 1], dtype=float)
                                if np.any(c_o[:-1] == 0) or len(c_o) < 21:
                                    continue
                                ret_o = np.diff(c_o) / c_o[:-1]
                                if len(ret_s) != len(ret_o):
                                    continue
                                corr = np.corrcoef(ret_s, ret_o)[0, 1]
                                if not np.isnan(corr) and corr >= corr_thresh:
                                    qty = max(1, int(qty * corr_reduce))
                                    break
                    cost = qty * fill_price * slippage_mult_buy + commission
                    if cash >= cost:
                        cash -= cost
                        positions[symbol] = (qty, fill_price)
                        bars_held[symbol] = 0
                        peak_unrealized[symbol] = 0.0
                        trades_by_sym[symbol].append(("buy", fill_price, qty, cost))
            elif action == "sell" and position_qty > 0:
                fill_price = fill_open_next
                proceeds = position_qty * fill_price * slippage_mult_sell - commission
                cost_basis = position_qty * position_cost
                pnl = proceeds - cost_basis
                if getattr(brain_config, "KELLY_SIZING_ENABLED", False):
                    brain_sizing.record_round_trip(pnl)
                cash += proceeds
                positions[symbol] = (0, 0.0)
                bars_held[symbol] = 0
                peak_unrealized[symbol] = 0.0
                trades_by_sym[symbol].append(("sell", fill_price, position_qty, proceeds))

            equity_now = cash + sum(positions.get(s, (0, 0))[0] * data_by_sym[s]["closes"][i] for s in symbols_list)
            if start_equity > 0 and (equity_now - start_equity) / start_equity >= daily_target_pct:
                daily_target_hit = True
                days_hit_target += 1

    # Final equity
    total_end = cash + sum(positions.get(s, (0, 0))[0] * data_by_sym[s]["closes"][n_min - 1] for s in symbols_list)
    # Expectancy E = (W×AvgW) − (L×AvgL): wins, losses, avg win $, avg loss $
    wins, losses, sum_win, sum_loss = 0, 0, 0.0, 0.0
    for _sym in symbols_list:
        trades = trades_by_sym[_sym]
        cost_basis = 0.0
        for t in trades:
            if t[0] == "buy":
                cost_basis = t[3]  # cost
            elif t[0] == "sell" and cost_basis > 0:
                pnl = t[3] - cost_basis  # proceeds - cost
                if pnl > 0:
                    wins += 1
                    sum_win += pnl
                else:
                    losses += 1
                    sum_loss += abs(pnl)
                cost_basis = 0.0
    avg_win = sum_win / wins if wins else 0.0
    avg_loss = sum_loss / losses if losses else 0.0
    expectancy = (wins * avg_win) - (losses * avg_loss) if (wins or losses) else 0.0

    results = []
    for symbol in symbols_list:
        qty, cost = positions.get(symbol, (0, 0))
        final_equity_sym = qty * data_by_sym[symbol]["closes"][n_min - 1] if qty else 0
        results.append({
            "symbol": symbol,
            "initial_cash": 0,
            "final_equity": final_equity_sym,
            "total_return_pct": (total_end - initial_cash) / initial_cash * 100 if initial_cash else 0,
            "num_trades": len(trades_by_sym[symbol]),
            "trades": trades_by_sym[symbol],
        })
    if debug and (debug_hold_reasons or debug_sell_reasons is not None):
        print("", file=sys.stderr)
        print("[debug] unified backtest: hold reasons (why no buy):", file=sys.stderr)
        for reason, count in sorted((debug_hold_reasons or {}).items(), key=lambda x: -x[1])[:15]:
            print("  %s -> %d" % (reason, count), file=sys.stderr)
        print("[debug] sell reasons:", file=sys.stderr)
        for reason, count in sorted((debug_sell_reasons or {}).items(), key=lambda x: -x[1])[:10]:
            print("  %s -> %d" % (reason, count), file=sys.stderr)
        print("[debug] decide() said buy (before mom filter)=%d bars; mom/ret1d filter blocked=%d" % (debug_bars_would_buy, debug_bars_mom_filter), file=sys.stderr)
    results.append("_unified_meta")  # marker
    results.append({
        "total_start": initial_cash,
        "total_end": total_end,
        "days_hit_target": days_hit_target,
        "n_bars": n_min - 30,
        "expectancy": expectancy,
        "wins": wins,
        "losses": losses,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    })
    return results


def main():
    parser = argparse.ArgumentParser(description="Backtest strategy on Alpaca daily bars")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated symbols (default: AAPL for minimal test)")
    parser.add_argument("--days", type=int, default=None, help="Days of history (default 90, or 365 * --years)")
    parser.add_argument("--years", type=float, default=None, help="Years of history (e.g. 2 for last 2 years); overrides --days")
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash (default 100000)")
    parser.add_argument("--debug", action="store_true", help="Print why buys are blocked (first symbol)")
    args = parser.parse_args()
    days = int(args.years * 365) if args.years is not None else (args.days if args.days is not None else 90)
    symbols = [s.strip().upper() for s in (args.symbols or os.environ.get("TICKERS", "AAPL")).split(",") if s.strip()]
    if not symbols:
        print("Provide --symbols or TICKERS env", file=sys.stderr)
        sys.exit(1)
    print("Backtest symbols=%s days=%d initial_cash=%.0f (config: brain.config + .env)" % (symbols, days, args.cash), file=sys.stderr)
    results = run_backtest_unified(symbols, days=days, initial_cash=args.cash, debug=args.debug)
    if not results:
        print("No bar data; check Alpaca keys and --symbols", file=sys.stderr)
        sys.exit(1)
    meta = results[-1]
    results = [r for r in results if isinstance(r, dict) and "symbol" in r and r.get("symbol")]
    total_start = meta["total_start"]
    total_end = meta["total_end"]
    days_hit_target = meta["days_hit_target"]
    n_bars = meta["n_bars"]
    total_pnl = total_end - total_start
    total_return_pct = (total_pnl / total_start * 100) if total_start else 0
    winners = [r for r in results if r.get("final_equity", 0) > r.get("initial_cash", 0)]
    losers = [r for r in results if r.get("final_equity", 0) < r.get("initial_cash", 0)]

    print("", file=sys.stderr)
    print("--- PnL by symbol ---", file=sys.stderr)
    for r in results:
        init = r.get("initial_cash", 0)
        fin = r.get("final_equity", 0)
        pnl = fin - init if init else 0
        sign = "+" if pnl >= 0 else ""
        print(
            "symbol=%s final_equity=%.2f pnl=%s%.2f (%.2f%%) num_trades=%d"
            % (r["symbol"], fin, sign, pnl, r.get("total_return_pct", 0), r.get("num_trades", 0)),
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    print("--- Summary ---", file=sys.stderr)
    print("total_start=%.2f total_end=%.2f total_pnl=%+.2f (%.2f%%)" % (total_start, total_end, total_pnl, total_return_pct), file=sys.stderr)
    print("days_hit_daily_cap=%d / %d (no new buys on those days; winners keep running)" % (days_hit_target, n_bars), file=sys.stderr)
    if isinstance(meta, dict) and "expectancy" in meta:
        E = meta["expectancy"]
        W, L = meta.get("wins", 0), meta.get("losses", 0)
        print("expectancy E=(W×AvgW)−(L×AvgL)=%.2f (wins=%d avg_win=%.2f losses=%d avg_loss=%.2f)" % (
            E, W, meta.get("avg_win", 0), L, meta.get("avg_loss", 0)), file=sys.stderr)
    print("winners=%d losers=%d flat=%d" % (len(winners), len(losers), len(results) - len(winners) - len(losers)), file=sys.stderr)
    if total_pnl < 0 and len(winners) > 0:
        winner_symbols = ",".join(r["symbol"] for r in sorted(winners, key=lambda x: -(x.get("final_equity", 0) - x.get("initial_cash", 0))))
        print("Tip: try a subset of profitable symbols: --symbols %s" % winner_symbols, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
