#!/usr/bin/env python3
"""
Fetch Russell 2000, S&P 500, and Nasdaq 100 constituent lists and write data/r2000.txt,
data/sp500.txt, data/nasdaq100.txt (one symbol per line, no duplicates).
Run from project root: python3 scripts/fetch_index_constituents.py
Sources: GitHub CSVs for S&P 500 and Russell 2000; Wikipedia for Nasdaq 100.
"""
import csv
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests: pip install requests", file=sys.stderr)
    sys.exit(1)

# Project root (parent of scripts/)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
R2000_URL = "https://raw.githubusercontent.com/ikoniaris/Russell2000/master/russell_2000_components.csv"
NASDAQ100_WIKI = "https://en.wikipedia.org/wiki/Nasdaq-100"
REQ_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IndexConstituents/1.0)"}

# Fallback Nasdaq 100 if Wikipedia blocks (current as of late 2025 / Jan 2026)
NASDAQ100_FALLBACK = """ADBE AMD ABNB ALNY GOOGL GOOG AMZN AEP AMGN ADI AAPL AMAT APP ARM ASML TEAM ADSK ADP AXON BKR BKNG AVGO CDNS CHTR CTAS CSCO CCEP CTSH CMCSA CEG CPRT CSGP COST CRWD CSX DDOG DXCM FANG DASH EA EXC FAST FER FTNT GEHC GILD HON IDXX INSM INTC INTU ISRG KDP KLAC KHC LRCX LIN MAR MRVL MELI META MCHP MU MSFT MSTR MDLZ MPWR MNST NFLX NVDA NXPI ORLY ODFL PCAR PLTR PANW PAYX PYPL PDD PEP QCOM REGN ROP ROST STX SHOP SBUX SNPS TMUS TTWO TSLA TXN TRI VRSK VRTX WMT WBD WDC WDAY XEL ZS""".split()


def _clean_symbol(s: str) -> str:
    return s.strip().upper().split("#")[0].strip()


def _dedupe_and_write(symbols: list[str], path: Path, label: str) -> int:
    seen = set()
    out = []
    for s in symbols:
        t = _clean_symbol(s)
        if t and len(t) <= 6 and t.isalpha() and t not in seen:
            seen.add(t)
            out.append(t)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} symbols to {path} ({label})")
    return len(out)


def fetch_sp500() -> list[str]:
    r = requests.get(SP500_URL, timeout=30, headers=REQ_HEADERS)
    r.raise_for_status()
    reader = csv.DictReader(r.text.strip().split("\n"))
    return [row["Symbol"] for row in reader if row.get("Symbol")]


def fetch_r2000() -> list[str]:
    r = requests.get(R2000_URL, timeout=30, headers=REQ_HEADERS)
    r.raise_for_status()
    reader = csv.DictReader(r.text.strip().split("\n"))
    return [row["Ticker"] for row in reader if row.get("Ticker")]


def fetch_nasdaq100() -> list[str]:
    try:
        import pandas as pd
        tables = pd.read_html(NASDAQ100_WIKI)
        for t in tables:
            cols = [c for c in t.columns if isinstance(c, str) and "ticker" in c.lower()]
            if cols:
                return t[cols[0]].astype(str).str.strip().str.upper().dropna().tolist()
            if len(t.columns) >= 1 and len(t) >= 90:
                return t.iloc[:, 0].astype(str).str.strip().str.upper().dropna().tolist()
    except Exception:
        pass
    try:
        r = requests.get(NASDAQ100_WIKI, timeout=30, headers=REQ_HEADERS)
        r.raise_for_status()
        tickers = []
        for line in r.text.split("\n"):
            m = re.match(r"\|\s*([A-Z]{2,5})\s*\|\s*\[?", line)
            if m:
                tickers.append(m.group(1))
        if len(tickers) >= 90:
            return tickers
    except Exception:
        pass
    return list(NASDAQ100_FALLBACK)


def main() -> int:
    print("Fetching index constituents...")
    # S&P 500
    try:
        syms = fetch_sp500()
        _dedupe_and_write(syms, DATA_DIR / "sp500.txt", "S&P 500")
    except Exception as e:
        print(f"S&P 500 failed: {e}", file=sys.stderr)
        return 1
    # Russell 2000
    try:
        syms = fetch_r2000()
        _dedupe_and_write(syms, DATA_DIR / "r2000.txt", "Russell 2000")
    except Exception as e:
        print(f"Russell 2000 failed: {e}", file=sys.stderr)
        return 1
    # Nasdaq 100 (from Wikipedia table in page)
    try:
        syms = fetch_nasdaq100()
        if len(syms) < 90:
            # Fallback: pandas read_html if available
            try:
                import pandas as pd
                tables = pd.read_html(NASDAQ100_WIKI)
                for t in tables:
                    if "Ticker" in (t.columns.tolist() if hasattr(t, "columns") else []):
                        syms = t["Ticker"].astype(str).str.strip().dropna().tolist()
                        break
            except Exception:
                pass
        _dedupe_and_write(syms, DATA_DIR / "nasdaq100.txt", "Nasdaq 100")
    except Exception as e:
        print(f"Nasdaq 100 failed: {e}", file=sys.stderr)
        return 1
    print("Done. Scanner uses r2000_sp500_nasdaq100 to combine all three (deduped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
