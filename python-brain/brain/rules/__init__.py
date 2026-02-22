"""
Business rules: pluggable checks used by the strategy.
- consensus: allow buy only when composite has consensus (e.g. 2 of 3 sources positive).
- daily_cap: block new buys when daily PnL >= 0.2% (lock in gains).
- drawdown: block new buys when drawdown from peak >= MAX_DRAWDOWN_PCT.
"""
from .consensus import consensus_allows_buy  # noqa: F401
from .daily_cap import is_daily_cap_reached, update_equity  # noqa: F401
from .drawdown import is_drawdown_halt, update_drawdown_peak  # noqa: F401
