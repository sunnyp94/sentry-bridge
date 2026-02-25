# Run Strategy Optimizer Daily After 4pm ET

The **strategy optimizer** reads `data/experience_buffer.jsonl` (filled by the live app on every entry/exit), runs a Random Forest for feature importance, and suggests filter rules. Running it **after market close** (e.g. 4pm ET) lets the system learn from the day’s trades for the next session.

**Anti-meta-overfitting:**

- **Rolling window**: The daily script uses only the **last 7 days** of buffer data so rules require a pattern over multiple days, not curve-fitting to one day.
- **Out-of-sample (24h)**: New rules are written to `data/generated_filter_rules_proposed.json` with a timestamp. They are **promoted to active** (`data/generated_filter_rules.json`) only after **24 hours**, so the “new” parameters run on paper for one day before affecting live behavior.

The live app reads only **active** rules and blocks a buy only when a rule has the required data and the condition matches (e.g. block when ATR in top 10th percentile). Position sizing remains **always 5% of equity**; no .env or config changes required.

## What to run

From the **repo root** (or set `REPO_ROOT` to that path):

```bash
./scripts/run_optimizer_after_close.sh
```

This (1) promotes proposed → active if proposed is 24h+ old, (2) runs the optimizer with a 7-day rolling window and writes to **proposed**. Next day’s run promotes today’s proposed to active.

Or call the optimizer directly:

```bash
# Daily cron style: rolling window + proposed (promote next day)
python3 python-brain/apps/strategy_optimizer.py --write-proposed --rolling-days 7

# Legacy: write directly to active (no 24h delay)
python3 python-brain/apps/strategy_optimizer.py --write-rules
```

- Default buffer: `data/experience_buffer.jsonl`.
- Requires `scikit-learn` (in `python-brain/requirements.txt`).

## Scheduling (cron)

Run once per weekday after 4pm ET.

- **If your cron uses ET** (e.g. `TZ=America/New_York`):
  - `0 16 * * 1-5` → 4:00pm ET Mon–Fri.

- **If your cron uses UTC** (4pm ET ≈ 21:00 UTC in winter, 20:00 in summer; use 21:00 to be safe):
  - `0 21 * * 1-5` → 4pm ET (winter) Mon–Fri.

Example (host; replace `/path/to/sentry-bridge` with your repo root):

```bash
# 4pm ET weekdays (cron in ET)
0 16 * * 1-5 cd /path/to/sentry-bridge && ./scripts/run_optimizer_after_close.sh
```

Or with UTC:

```bash
0 21 * * 1-5 cd /path/to/sentry-bridge && ./scripts/run_optimizer_after_close.sh
```

## Docker / GCP VM

- **Same host as the app**: The app writes to `data/experience_buffer.jsonl` (e.g. bind-mounted). Run the script on the **host** so it sees the same `data/` directory:
  - `cd /path/to/sentry-bridge && ./scripts/run_optimizer_after_close.sh`
  Schedule that with cron on the host as above.

- **One-off container** (if you prefer to run inside Docker): From the host, with the same `data/` mount:
  - `docker compose run --rm -v "$(pwd)/data:/app/data" app python3 /app/python-brain/apps/strategy_optimizer.py --write-proposed --rolling-days 7`
  Schedule that command with cron instead of the script, or wrap it in a small script that `cd`s to the repo and runs the `docker compose run` line.

No `.env` or app config changes are required; the optimizer reads the buffer path from the same defaults as the live app (or `EXPERIENCE_BUFFER_PATH` if you set it elsewhere).
