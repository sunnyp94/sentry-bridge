"""Strategy: decide, sizing, shadow (A/B) variants."""
from .strategy import (
    decide,
    Decision,
    probability_gain,
    sentiment_score_from_news,
    update_and_get_sentiment_ema,
    get_sentiment_ema,
    set_kill_switch_from_news,
    set_kill_switch_from_returns,
    is_kill_switch_active,
    set_kill_switch,
    STOP_LOSS_PCT,
)
from . import sizing
from . import shadow_strategy
from .shadow_strategy import (
    shadow_on_buy,
    shadow_on_sell,
    shadow_update,
    check_promotion,
    get_shadow_stats,
    ShadowPosition,
    SHADOW_CONFIGS,
    PROMOTION_MIN_GHOST_TRADES,
)

__all__ = [
    "decide",
    "Decision",
    "probability_gain",
    "sentiment_score_from_news",
    "update_and_get_sentiment_ema",
    "get_sentiment_ema",
    "set_kill_switch_from_news",
    "set_kill_switch_from_returns",
    "is_kill_switch_active",
    "set_kill_switch",
    "STOP_LOSS_PCT",
    "sizing",
    "shadow_strategy",
    "shadow_on_buy",
    "shadow_on_sell",
    "shadow_update",
    "check_promotion",
    "get_shadow_stats",
    "ShadowPosition",
    "SHADOW_CONFIGS",
    "PROMOTION_MIN_GHOST_TRADES",
]
