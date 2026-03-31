#!/usr/bin/env python3
"""
Railway cron compatibility runner for monthly PHINS auto-pay.

This delegates to the repo's canonical monthly auto-pay command.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.run_monthly_auto_pay import main  # noqa: E402


if __name__ == '__main__':
    raise SystemExit(main())
