"""Test configuration to ensure project root is importable.

This allows `pytest` to find top-level modules like `accounting_engine.py`
when tests are run from any working directory.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Add repository root to sys.path once
ROOT_DIR = Path(__file__).resolve().parents[1]
root_str = str(ROOT_DIR)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
