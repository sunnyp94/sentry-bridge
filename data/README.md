# Symbol lists for screener/discovery

**SCREENER_UNIVERSE=r2000_sp500_nasdaq100** (default) merges Russell 2000 + S&P 500 + Nasdaq 100 (no duplicates).

Generate or refresh the three files (one symbol per line):

```bash
python3 scripts/fetch_index_constituents.py
```

Run from **project root**. Writes: **data/r2000.txt**, **data/sp500.txt**, **data/nasdaq100.txt**. Sources: GitHub CSVs for S&P 500 and Russell 2000; Wikipedia for Nasdaq 100 (with built-in fallback if unavailable). You can also export from your broker and overwrite these files.

Optional single-index universes: **russell2000**, **sp500**, **nasdaq100**, **sp400** (sp400.txt for S&P MidCap 400). For quick tests, set **SCREENER_UNIVERSE=lab_12** in `.env`.
