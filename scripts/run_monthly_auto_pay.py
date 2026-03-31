#!/usr/bin/env python3
"""
Run the monthly PHINS auto-pay batch from a scheduler.

Intended for Render/Railway cron jobs or manual operator execution.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from web_portal.server import execute_monthly_auto_pay_cli  # noqa: E402


def main() -> int:
    return execute_monthly_auto_pay_cli(sys.argv[1:])


if __name__ == '__main__':
    raise SystemExit(main())
