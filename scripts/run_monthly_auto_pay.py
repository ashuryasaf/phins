#!/usr/bin/env python3
"""
Run the monthly PHINS auto-pay batch from a scheduler.

Intended for Render/Railway cron jobs or manual operator execution.
"""

from __future__ import annotations

import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from web_portal.server import execute_monthly_auto_pay_cli  # noqa: E402


def main() -> int:
    force = '--force' in sys.argv
    dry_run = '--dry-run' in sys.argv
    notify_users = '--no-notify' not in sys.argv
    report = execute_monthly_auto_pay_cli(
        force=force,
        dry_run=dry_run,
        notify_users=notify_users,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get('success', False) else 1


if __name__ == '__main__':
    raise SystemExit(main())
