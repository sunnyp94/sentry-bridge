#!/bin/sh
# Run the stock scanner before the trading day when ACTIVE_SYMBOLS_FILE is set (opportunity engine).
# Then start the Go engine (which reads tickers from that file when set).
if [ -n "$ACTIVE_SYMBOLS_FILE" ]; then
  echo "[entrypoint] running scanner -> $ACTIVE_SYMBOLS_FILE"
  cd /app && python3 /app/python-brain/apps/run_screener.py --out "$ACTIVE_SYMBOLS_FILE" || true
fi
exec "$@"
