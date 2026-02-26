#!/bin/sh
# When DISCOVERY_ENABLED=true: loop (discovery 7:00–9:30 ET → engine 9:30–4pm ET → sleep until 7am). Engine exits at 4pm; discovery sleeps overnight and weekends.
# Else when ACTIVE_SYMBOLS_FILE is set: run scanner once, then start the Go engine.
# Go reads tickers from ACTIVE_SYMBOLS_FILE at startup.
if [ -n "$ACTIVE_SYMBOLS_FILE" ]; then
  if [ "$DISCOVERY_ENABLED" = "true" ] || [ "$DISCOVERY_ENABLED" = "1" ]; then
    echo "[entrypoint] discovery 7:00–9:30 ET; engine 9:30–4pm ET; then sleep until 7am (idle weekends)"
    cd /app
    while true; do
      python3 /app/python-brain/apps/run_discovery_until_open.py || exit 1
      echo "[entrypoint] starting engine (exits at 4pm ET)"
      "$@" || exit 1
      echo "[entrypoint] engine exited; next: discovery will sleep until 7am ET then run 7–9:30"
    done
  else
    echo "[entrypoint] running scanner -> $ACTIVE_SYMBOLS_FILE"
    cd /app && python3 /app/python-brain/apps/run_screener.py --out "$ACTIVE_SYMBOLS_FILE" || true
  fi
fi
exec "$@"
