#!/bin/sh
# When DISCOVERY_ENABLED=true: run discovery 7:00–9:30 ET (every 5 min), then at market open start the engine.
# Else when ACTIVE_SYMBOLS_FILE is set: run scanner once, then start the Go engine.
# Go reads tickers from ACTIVE_SYMBOLS_FILE at startup.
if [ -n "$ACTIVE_SYMBOLS_FILE" ]; then
  if [ "$DISCOVERY_ENABLED" = "true" ] || [ "$DISCOVERY_ENABLED" = "1" ]; then
    echo "[entrypoint] discovery phase 7:00–9:30 ET; then starting engine at market open"
    cd /app && python3 /app/python-brain/apps/run_discovery_until_open.py || exit 1
  else
    echo "[entrypoint] running scanner -> $ACTIVE_SYMBOLS_FILE"
    cd /app && python3 /app/python-brain/apps/run_screener.py --out "$ACTIVE_SYMBOLS_FILE" || true
  fi
fi
exec "$@"
