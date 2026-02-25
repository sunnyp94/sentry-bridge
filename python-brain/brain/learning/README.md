# Learning Module

This module holds everything related to **learning from trades** and **generated filter rules**.

## Contents

| File | Purpose |
|------|--------|
| **experience_buffer.py** | Records every entry/exit to `data/experience_buffer.jsonl`. The strategy optimizer (run daily after 4pm ET) reads this buffer with a 7-day rolling window and writes *proposed* rules; after 24h they are promoted to *active*. |
| **generated_rules.py** | Loads *active* rules from `data/generated_filter_rules.json` and exposes `should_block_buy(context)`. The consumer calls this before placing a buy; only blocks when the rule has the required data and the condition matches. |

## Usage

- **Recording trades**: Use `record_entry` / `record_exit` from `brain.learning.experience_buffer` (or `brain.learning`) when the app places or closes a trade.
- **Before placing a buy**: Call `should_block_buy(context)` from `brain.learning.generated_rules` (or `brain.learning`); if `True`, skip the buy.
- **Optimizer**: `apps/strategy_optimizer.py` uses `load_buffer` and `_buffer_path` from `brain.learning.experience_buffer`. Run via `scripts/run_optimizer_after_close.sh` (e.g. cron at 4pm ET).

## Backward compatibility

`brain.experience_buffer` and `brain.generated_rules` still exist as thin re-exports so existing imports keep working. New code should use `brain.learning` or `brain.learning.experience_buffer` / `brain.learning.generated_rules`.
