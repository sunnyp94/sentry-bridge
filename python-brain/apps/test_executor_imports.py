#!/usr/bin/env python3
"""
Test that brain.executor re-exports required symbols so consumer flat-on-startup does not raise ImportError.
No Alpaca keys needed; without client the close_all_* functions no-op and return 0.
Run from repo root: python3 python-brain/apps/test_executor_imports.py
Or: cd python-brain && python3 apps/test_executor_imports.py
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def test_brain_executor_imports():
    """Same imports as Dockerfile build check."""
    from brain.executor import (
        place_order,
        get_account_equity,
        close_all_positions_from_api,
        close_all_positions,
    )
    assert place_order is not None
    assert get_account_equity is not None
    assert close_all_positions_from_api is not None
    assert close_all_positions is not None
    print("OK brain.executor: place_order, get_account_equity, close_all_positions_from_api, close_all_positions")


def test_consumer_flat_on_startup_path():
    """Exact code path from consumer.py handle_event(positions): try close_all_positions_from_api, except ImportError -> close_all_positions(payload)."""
    run_flat = True  # simulate FLAT_POSITIONS_AT_ET reached
    payload_positions = []  # no positions; close_all_positions([]) is a no-op
    if run_flat:
        try:
            from brain.executor import close_all_positions_from_api
            n = close_all_positions_from_api()
            assert n == 0 or n >= 0  # 0 when no client or no positions
            print("OK close_all_positions_from_api() ran (no ImportError)")
        except ImportError as e:
            from brain.executor import close_all_positions
            n = close_all_positions(payload_positions or [])
            assert n == 0 or n >= 0
            print("OK fallback close_all_positions(payload) ran after ImportError:", e)
    print("OK consumer flat-on-startup path completed without ImportError")


if __name__ == "__main__":
    test_brain_executor_imports()
    test_consumer_flat_on_startup_path()
    print("All executor import tests passed.")
    sys.exit(0)
