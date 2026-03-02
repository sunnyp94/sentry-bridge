#!/bin/sh
# Discovery mode (ACTIVE_SYMBOLS_FILE = path to watchlist): On every full market open day, discovery runs 7:00–9:30 ET every 5 min and writes the priority watchlist. If the next run would be after 9:30 ET, the app uses the ACTIVE_SYMBOLS_FILE it last wrote. At 9:30 ET the engine starts with that file; at 4pm ET it exits; then we sleep until 7am next full trading day.
if [ -n "$ACTIVE_SYMBOLS_FILE" ]; then
  echo "[entrypoint] discovery 7:00–9:30 ET (every 5 min on full market days); engine 9:30–4pm ET; sleep until 7am"
  cd /app
  while true; do
    python3 /app/python-brain/apps/run_discovery_until_open.py || exit 1
    echo "[entrypoint] starting engine (exits at 4pm ET)"
    "$@" || exit 1
    echo "[entrypoint] engine exited; next: discovery will sleep until 7am ET then run 7–9:30"
  done
fi
exec "$@"
