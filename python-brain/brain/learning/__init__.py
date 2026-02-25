"""
Learning module: experience buffer + generated rules.

- **Experience buffer** (experience_buffer.py): Records every entry/exit to data/experience_buffer.jsonl
  for the strategy optimizer. Use record_entry / record_exit when placing/closing trades; use load_buffer
  in the optimizer.
- **Generated rules** (generated_rules.py): Active filter rules (data/generated_filter_rules.json)
  produced by the optimizer after 24h out-of-sample. Use should_block_buy(context) before placing a buy.
"""
from brain.learning.experience_buffer import (
    load_buffer,
    record_entry,
    record_exit,
    label_trade_24h,
    MarketSnapshot,
)
from brain.learning.experience_buffer import _buffer_path  # for strategy_optimizer
from brain.learning.generated_rules import load_active_rules, should_block_buy

__all__ = [
    "load_buffer",
    "record_entry",
    "record_exit",
    "label_trade_24h",
    "MarketSnapshot",
    "_buffer_path",
    "load_active_rules",
    "should_block_buy",
]
