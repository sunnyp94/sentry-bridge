# Symbol lists for screener/discovery

**SCREENER_UNIVERSE=r2000_sp500_nasdaq100** (default) merges Russell 2000 + S&P 500 + Nasdaq 100 (no duplicates).

Generate or refresh the three files (one symbol per line):

```bash
python3 scripts/fetch_index_constituents.py
```

Writes: **r2000.txt**, **sp500.txt**, **nasdaq100.txt**. Sources: GitHub CSVs for S&P 500 and Russell 2000; Wikipedia fallback for Nasdaq 100. You can also export from Active Trader Pro (or your broker) and overwrite these files.

Optional single-index universes: **russell2000**, **sp500**, **nasdaq100**, **sp400** (sp400.txt for S&P MidCap 400). For quick tests, set **SCREENER_UNIVERSE=lab_12** in `.env`.
