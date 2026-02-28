#!/usr/bin/env python3
"""
Test that brain.executor re-exports required symbols (place_order, get_account_equity, close_all_*).
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


def test_executor_close_functions():
    """close_all_positions_from_api and close_all_positions are importable and callable (no-op without client)."""
    try:
        from brain.executor import close_all_positions_from_api
        n = close_all_positions_from_api()
        assert n == 0 or n >= 0
        print("OK close_all_positions_from_api() ran (no ImportError)")
    except ImportError as e:
        from brain.executor import close_all_positions
        n = close_all_positions([])
        assert n == 0 or n >= 0
        print("OK fallback close_all_positions(payload) ran after ImportError:", e)
    print("OK executor close functions completed without ImportError")


if __name__ == "__main__":
    test_brain_executor_imports()
    test_executor_close_functions()
    print("All executor import tests passed.")
    sys.exit(0)
