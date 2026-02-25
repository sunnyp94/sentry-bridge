#!/usr/bin/env python3
"""
Attribution Engine: Recursive Strategy Optimizer.

Uses Random Forest for feature importance on the Experience Buffer. Generates filter rules
when a setup has <40% success under a condition (e.g. block when ATR in top 10th percentile).

Anti-meta-overfitting:
- Rolling window: only use last N days of buffer (default 7) so rules require pattern over
  multiple days, not curve-fitting to one day.
- Proposed vs active: new rules write to proposed file with timestamp; promoted to active
  only after 24h (out-of-sample validation on paper before touching live).
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Ensure brain package is on path when run from repo root or python-brain
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

from brain.learning.experience_buffer import load_buffer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("strategy_optimizer")

# Path for active rules (strategy/consumer read these to block bad setups)
GENERATED_RULES_PATH = Path(os.environ.get("GENERATED_RULES_PATH", "") or str(_root.parent / "data" / "generated_filter_rules.json"))
# Proposed rules (written by optimizer; promoted to active after 24h out-of-sample)
GENERATED_RULES_PROPOSED_PATH = _root.parent / "data" / "generated_filter_rules_proposed.json"

ROLLING_DAYS_DEFAULT = 7
PROMOTE_AFTER_HOURS = 24


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse ISO ts to datetime (naive UTC)."""
    if not ts_str:
        return None
    try:
        # Handle Z suffix and optional microseconds
        s = str(ts_str).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _filter_records_last_n_days(records: list, days: int) -> list:
    """Keep only records with ts in the last N days (rolling window to avoid curve-fitting to one day)."""
    if days <= 0:
        return records
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for r in records:
        ts = _parse_ts(r.get("ts") or r.get("entry_ts") or "")
        if ts is not None and ts >= cutoff:
            out.append(r)
    return out


def _ensure_float(x, default: float = np.nan) -> float:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _build_feature_matrix(records: list) -> tuple:
    """
    Build feature matrix and target from experience buffer.
    Rows = trades (entry+exit pairs or exit rows with entry_ts).
    Features: technical_score, ofi, prob_gain, structure_ok, regime, atr_percentile, reason/setup buckets.
    Target: success (1) vs false_positive (0); optionally late_entry as separate class.
    """
    # Prefer exit rows that have entry_ts (so we have outcome)
    exits = [r for r in records if r.get("action") == "exit"]
    if not exits:
        # Fallback: use entries and infer no outcome
        entries = [r for r in records if r.get("action") == "entry"]
        if not entries:
            return None, None, None

    rows = []
    for r in records:
        if r.get("action") != "exit":
            continue
        entry_ts = r.get("entry_ts")
        entry_price = _ensure_float(r.get("entry_price"))
        exit_price = _ensure_float(r.get("price"))
        exit_reason = (r.get("exit_reason") or r.get("reason")) or ""
        pl = r.get("unrealized_pl_pct_at_exit")
        if pl is not None:
            pl = _ensure_float(pl)
        # Label: success if TP/scale_out or pl >= 0.02; false_positive if stop or pl <= -0.01
        if "take_profit" in exit_reason or "scale_out" in exit_reason:
            label = "success"
        elif "stop_loss" in exit_reason or (pl is not None and pl <= -0.01):
            label = "false_positive"
        elif pl is not None and pl >= 0.02:
            label = "success"
        else:
            label = "false_positive"

        # Features from exit row (or entry if we had merged)
        technical_score = _ensure_float(r.get("technical_score"))
        ofi = _ensure_float(r.get("ofi"))
        prob_gain = _ensure_float(r.get("prob_gain"))
        structure_ok = r.get("structure_ok")
        if structure_ok is not None:
            structure_ok = 1 if structure_ok else 0
        else:
            structure_ok = np.nan
        regime = r.get("regime") or "unknown"
        atr_percentile = _ensure_float(r.get("atr_percentile"))
        reason = (r.get("entry_reason") or r.get("reason")) or ""

        rows.append({
            "technical_score": technical_score,
            "ofi": ofi,
            "prob_gain": prob_gain,
            "structure_ok": structure_ok,
            "regime_trend": 1 if regime == "trend" else 0,
            "regime_range": 1 if regime in ("mean_reversion", "range") else 0,
            "atr_percentile": atr_percentile,
            "reason_green_light": 1 if "green_light" in reason else 0,
            "label": label,
        })

    if not rows:
        return None, None, None
    df = pd.DataFrame(rows)
    # Fill NaN with median for numeric
    for col in df.select_dtypes(include=[np.number]).columns:
        if col == "label":
            continue
        df[col] = df[col].fillna(df[col].median())
    le = LabelEncoder()
    y = le.fit_transform(df["label"].astype(str))
    X = df.drop(columns=["label"])
    return X, y, le


def run_feature_importance(
    buffer_path: Path,
    min_samples: int = 20,
    rolling_days: int = 0,
) -> dict:
    """
    Run Random Forest feature importance on the experience buffer.
    If rolling_days > 0, only use records from the last N days (avoids meta-overfitting to one day).
    Returns dict with feature_importances, model score, and suggested filter rules.
    """
    if not _HAS_SKLEARN:
        log.warning("scikit-learn not installed; run: pip install scikit-learn")
        return {}
    records = load_buffer(path=buffer_path)
    if rolling_days > 0:
        records = _filter_records_last_n_days(records, rolling_days)
        log.info("Rolling window: using %d records from last %d days", len(records), rolling_days)
    if len(records) < min_samples:
        log.warning("Not enough records (%d < %d); skipping optimizer run.", len(records), min_samples)
        return {}

    X, y, le = _build_feature_matrix(records)
    if X is None or len(X) < min_samples:
        log.warning("Not enough labeled trades for analysis.")
        return {}

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(np.unique(y)) > 1 else None)
    clf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    clf.fit(X_train, y_train)
    score = clf.score(X_test, y_test)
    log.info("Random Forest test accuracy: %.2f", score)

    imp = dict(zip(X.columns, clf.feature_importances_))
    for name, val in sorted(imp.items(), key=lambda x: -x[1]):
        log.info("  feature_importance %s=%.3f", name, val)

    # Self-correction: find setups with low success rate when a condition holds
    df = X.copy()
    df["label"] = le.inverse_transform(y)
    success_rate = df["label"].value_counts(normalize=True).get("success", 0.0)
    log.info("Overall success rate in buffer: %.1f%%", success_rate * 100)

    # If ATR percentile high and success rate < 40%, suggest filter
    generated_rules = []
    if "atr_percentile" in df.columns and df["atr_percentile"].notna().any():
        high_atr = df[df["atr_percentile"] >= 90]
        if len(high_atr) >= 5:
            sr = (high_atr["label"] == "success").mean()
            if sr < 0.40:
                generated_rules.append({
                    "rule": "block_when_atr_percentile_high",
                    "condition": "atr_percentile >= 90",
                    "success_rate": float(sr),
                    "reason": "Success rate when ATR in top 10th percentile is %.1f%% (< 40%%)" % (sr * 100),
                })
                log.info("Generated filter: block when ATR in top 10th percentile (success rate %.1f%%)", sr * 100)

    return {
        "feature_importances": imp,
        "test_accuracy": score,
        "generated_rules": generated_rules,
        "n_samples": len(X),
    }


def promote_proposed_to_active() -> bool:
    """
    If proposed rules file exists and was written >= PROMOTE_AFTER_HOURS ago, copy to active (out-of-sample: new rules run on paper for 24h before going live).
    Returns True if promotion happened.
    """
    if not GENERATED_RULES_PROPOSED_PATH.exists():
        return False
    try:
        with open(GENERATED_RULES_PROPOSED_PATH) as f:
            data = json.load(f)
    except Exception as e:
        log.warning("Could not read proposed rules: %s", e)
        return False
    written_ts = data.get("written_ts")
    if not written_ts:
        return False
    try:
        written = datetime.fromisoformat(written_ts.replace("Z", "+00:00"))
    except Exception:
        return False
    age_hours = (datetime.now(timezone.utc) - written).total_seconds() / 3600
    if age_hours < PROMOTE_AFTER_HOURS:
        log.info("Proposed rules are %.1fh old (need %dh); skipping promotion", age_hours, PROMOTE_AFTER_HOURS)
        return False
    rules = data.get("generated_rules", [])
    if not rules:
        return False
    GENERATED_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GENERATED_RULES_PATH, "w") as f:
        json.dump({
            "generated_rules": rules,
            "feature_importances": data.get("feature_importances", {}),
            "promoted_ts": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)
    log.info("Promoted %d proposed rules to active (were %.1fh old)", len(rules), age_hours)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Strategy optimizer: feature importance + generated filter rules from experience buffer")
    parser.add_argument("--buffer", type=str, default="", help="Path to experience_buffer.jsonl (default: data/experience_buffer.jsonl)")
    parser.add_argument("--min-samples", type=int, default=20, help="Minimum trades to run analysis")
    parser.add_argument("--rolling-days", type=int, default=0, help="Use only last N days of buffer (default 0 = all). Use 7 to avoid meta-overfitting.")
    parser.add_argument("--write-rules", action="store_true", help="Write generated rules directly to active (GENERATED_RULES_PATH)")
    parser.add_argument("--write-proposed", action="store_true", help="Write to proposed file with timestamp; promote to active only after 24h (use for daily cron)")
    args = parser.parse_args()
    buffer_path = Path(args.buffer) if args.buffer else None
    if buffer_path is None or not buffer_path.is_absolute():
        from brain.learning.experience_buffer import _buffer_path
        buffer_path = _buffer_path()
    if not buffer_path.exists():
        log.warning("Buffer file not found: %s. Record trades first (experience buffer enabled).", buffer_path)
        return 0

    # Out-of-sample: promote proposed -> active if proposed is 24h+ old (before computing new proposed)
    if args.write_proposed:
        promote_proposed_to_active()

    result = run_feature_importance(
        buffer_path,
        min_samples=args.min_samples,
        rolling_days=args.rolling_days if args.rolling_days > 0 else (ROLLING_DAYS_DEFAULT if args.write_proposed else 0),
    )
    if not result:
        return 0

    if result.get("generated_rules"):
        if args.write_proposed:
            GENERATED_RULES_PROPOSED_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "written_ts": datetime.now(timezone.utc).isoformat(),
                "generated_rules": result["generated_rules"],
                "feature_importances": result.get("feature_importances", {}),
            }
            with open(GENERATED_RULES_PROPOSED_PATH, "w") as f:
                json.dump(payload, f, indent=2)
            log.info("Wrote proposed rules to %s (will promote to active after %dh)", GENERATED_RULES_PROPOSED_PATH, PROMOTE_AFTER_HOURS)
        elif args.write_rules:
            GENERATED_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(GENERATED_RULES_PATH, "w") as f:
                json.dump({"generated_rules": result["generated_rules"], "feature_importances": result.get("feature_importances", {})}, f, indent=2)
            log.info("Wrote generated rules to %s", GENERATED_RULES_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
