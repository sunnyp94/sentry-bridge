"""
Load active generated filter rules (from strategy optimizer) and apply at decision time.

Rules are in data/generated_filter_rules.json (promoted from proposed after 24h out-of-sample).
Only block a buy when we have the required data and the rule condition matches; otherwise allow (not overly conservative).
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("brain.learning.generated_rules")

# Active rules path (brain/learning/ -> repo = 4 parents)
def _active_rules_path() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent  # learning -> brain -> python-brain -> repo
    return root / "data" / "generated_filter_rules.json"


def load_active_rules() -> List[Dict[str, Any]]:
    """Load active rules from disk (no cache so promotions take effect without restart). Returns list of rule dicts."""
    path = _active_rules_path()
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("generated_rules") or []
    except Exception as e:
        log.debug("generated_rules load failed: %s", e)
        return []


def should_block_buy(context: Dict[str, Any]) -> bool:
    """
    Return True if any active rule says we should block this buy. Context should have at least:
    - atr_percentile (optional float)
    - technical_score (optional float)
    - ofi (optional float)
    Only block when we have the data the rule needs and the condition matches; otherwise allow.
    """
    rules = load_active_rules()
    if not rules:
        return False
    for r in rules:
        rule_id = r.get("rule") or ""
        condition = (r.get("condition") or "").strip()
        if rule_id == "block_when_atr_percentile_high":
            atr_pct = context.get("atr_percentile")
            if atr_pct is None:
                continue  # no data -> don't block
            try:
                atr_pct = float(atr_pct)
            except (TypeError, ValueError):
                continue
            if atr_pct >= 90:
                log.info("generated_rule block buy: %s (atr_percentile=%.1f)", rule_id, atr_pct)
                return True
        # Add more rule types here as optimizer generates them; keep checks data-driven and not overly conservative
    return False
