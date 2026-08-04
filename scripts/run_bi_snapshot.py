#!/usr/bin/env python3
"""
Capture a daily BI KPI snapshot from a scheduler (BI-3).

Intended for Render/Railway cron jobs or manual operator execution:

    ./scripts/entrypoint.sh bi-snapshot

Loads the portal module (which hydrates stores from the database when
``USE_DATABASE`` is enabled), computes the executive dashboard, and appends an
immutable, checksummed KPI snapshot via ``services/bi_snapshot_service.py``.
"""

from __future__ import annotations

import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main() -> int:
    import web_portal.server as portal  # noqa: E402 (heavy import by design)
    from services.bi_analytics_service import get_bi_analytics_service
    from services.bi_snapshot_service import get_bi_snapshot_service

    dashboard = get_bi_analytics_service().get_executive_dashboard(
        customers=getattr(portal, 'CUSTOMERS', {}),
        policies=getattr(portal, 'POLICIES', {}),
        claims=getattr(portal, 'CLAIMS', {}),
        billing=getattr(portal, 'BILLING', {}),
        balance_sheet=getattr(portal, 'PHINS_BALANCE_SHEET', {}),
        suppliers=getattr(portal, 'SUPPLIERS', {}),
        deliveries={},
    )
    record = get_bi_snapshot_service().capture_snapshot(dashboard, source='cron')
    print(json.dumps({
        'success': True,
        'snapshot_id': record.get('snapshot_id'),
        'captured_at': record.get('captured_at'),
        'metrics': record.get('metrics'),
    }, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
