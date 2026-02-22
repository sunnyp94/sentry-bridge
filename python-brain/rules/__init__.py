"""
Business rules: pluggable checks used by the strategy.
- consensus: allow buy only when composite has consensus (e.g. 2 of 3 sources positive).
- daily_cap: block new buys when daily PnL >= 0.2% (lock in gains).
"""
from rules.consensus import consensus_allows_buy  # noqa: F401
from rules.daily_cap import is_daily_cap_reached, update_equity  # noqa: F401
