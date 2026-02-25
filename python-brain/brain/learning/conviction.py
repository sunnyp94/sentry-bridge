"""
Reinforcement Reward & Conviction Score.

Reward: +1 for profit, -2 for stop loss (enforce 2:1 risk/reward mindset).
Conviction: per-setup running score used to scale position size (winning streak -> larger; losing -> smaller).
"""
import logging
from collections import defaultdict, deque
from typing import Dict, Optional

log = logging.getLogger("brain.conviction")

# Reward constants: penalize losses more than we reward wins (2:1)
REWARD_PROFIT = 1.0
REWARD_STOP_LOSS = -2.0
REWARD_OTHER_EXIT = 0.0  # e.g. scale_out, time exit

# Per-setup (reason) rolling reward and count; max history to keep
_SETUP_REWARDS: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
_SETUP_COUNTS: Dict[str, int] = defaultdict(int)


def reward_for_exit(exit_reason: str, unrealized_pl_pct: Optional[float]) -> float:
    """
    Return reward for this exit. +1 profit, -2 stop loss, 0 otherwise.
    """
    if exit_reason is None:
        return REWARD_OTHER_EXIT
    r = exit_reason.lower()
    if "stop_loss" in r:
        return REWARD_STOP_LOSS
    if "take_profit" in r or "scale_out" in r:
        return REWARD_PROFIT
    if unrealized_pl_pct is not None:
        if unrealized_pl_pct >= 0.01:
            return REWARD_PROFIT
        if unrealized_pl_pct <= -0.01:
            return REWARD_STOP_LOSS
    return REWARD_OTHER_EXIT


def record_outcome(setup_type: str, exit_reason: str, unrealized_pl_pct: Optional[float] = None) -> float:
    """
    Record trade outcome for setup_type (e.g. green_light_4pt) and return reward.
    """
    r = reward_for_exit(exit_reason, unrealized_pl_pct)
    _SETUP_REWARDS[setup_type].append(r)
    _SETUP_COUNTS[setup_type] += 1
    log.debug("conviction record setup=%s reward=%.1f pl_pct=%s", setup_type, r, unrealized_pl_pct)
    return r


def conviction_multiplier(setup_type: str, default: float = 1.0) -> float:
    """
    Return position size multiplier for this setup (0.5 to 1.5) based on recent rewards.
    Winning streak -> up to 1.5x; losing -> down to 0.5x.
    """
    history = _SETUP_REWARDS.get(setup_type)
    if not history or len(history) < 3:
        return default
    avg = sum(history) / len(history)
    # Map average reward to multiplier: avg -2 -> 0.5, avg 0 -> 1.0, avg +1 -> 1.5
    if avg <= -1.5:
        mult = 0.5
    elif avg >= 0.5:
        mult = 1.5
    else:
        # Linear between 0.5 and 1.5
        mult = 0.5 + (avg + 1.5) / 2.5
    return max(0.5, min(1.5, mult))


def get_setup_stats() -> Dict[str, dict]:
    """Return per-setup stats for logging."""
    out = {}
    for setup, q in _SETUP_REWARDS.items():
        if not q:
            continue
        out[setup] = {"count": _SETUP_COUNTS[setup], "avg_reward": sum(q) / len(q), "multiplier": conviction_multiplier(setup)}
    return out
