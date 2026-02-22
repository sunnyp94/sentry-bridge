"""
Consensus rule: allow buy only when composite has enough "positive" sources (see config CONSENSUS_MIN_SOURCES_POSITIVE).
Strategy calls consensus_allows_buy(composite_result) before allowing a buy.
"""
from ..signals.composite import CompositeResult


def consensus_allows_buy(composite_result: CompositeResult) -> bool:
    """True if the composite has enough positive sources to allow a buy."""
    return composite_result.consensus_ok
