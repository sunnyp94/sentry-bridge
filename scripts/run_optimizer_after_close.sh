#!/usr/bin/env bash
# Run the strategy optimizer after market close. Promotes proposed->active if 24h old (out-of-sample),
# then runs optimizer with 7-day rolling window and writes proposed rules (promoted next day). See docs/OPTIMIZER_DAILY.md.
set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_ROOT"
python3 python-brain/apps/strategy_optimizer.py --write-proposed --rolling-days 7
