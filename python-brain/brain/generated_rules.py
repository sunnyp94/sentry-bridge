# Re-export from learning module for backward compatibility.
# Prefer: from brain.learning.generated_rules import ... or from brain.learning import ...
from brain.learning.generated_rules import load_active_rules, should_block_buy

__all__ = ["load_active_rules", "should_block_buy"]
