#!/usr/bin/env python3
"""
Scheduled BI job: KPI snapshot (BI-3) + materialized dashboard views (B10).

Intended for Render/Railway cron jobs or manual operator execution:

    ./scripts/entrypoint.sh bi-snapshot                 # snapshot + materialize
    ./scripts/entrypoint.sh bi-snapshot --materialize-only
    ./scripts/entrypoint.sh bi-snapshot --snapshot-only

Loads the portal module (which hydrates stores from the database when
``USE_DATABASE`` is enabled) and, from exactly the stores a request would
read (``portal.bi_data_sources()``):

* appends an immutable, checksummed KPI snapshot via
  ``services/bi_snapshot_service.py`` (trend history, append-only), and
* upserts the standard dashboards — executive dashboard, default revenue
  forecast, customer analytics — as materialized views under
  ``PHINS_BI_SNAPSHOT_DIR/materialized_views.json`` with their input
  fingerprint and ``computed_at``. A web process serving ``/api/bi/*`` adopts
  a view whose fingerprint matches its live stores and whose age is under the
  cache TTL, so the request path stops paying for the aggregation.

Idempotent: re-running with unchanged data rewrites the same views (fresh
``computed_at``) and appends one more snapshot row; it never duplicates or
mutates existing snapshot rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--snapshot-only', action='store_true', help='append the KPI snapshot only')
    group.add_argument('--materialize-only', action='store_true', help='refresh the materialized views only')
    args = parser.parse_args(argv)

    import web_portal.server as portal  # noqa: E402 (heavy import by design)
    from services.bi_analytics_service import get_bi_analytics_service
    from services.bi_snapshot_service import get_bi_snapshot_service

    data_sources = portal.bi_data_sources()
    bi_service = get_bi_analytics_service()
    output = {'success': True}

    if not args.materialize_only:
        dashboard = bi_service.get_executive_dashboard(
            customers=data_sources.get('customers', {}),
            policies=data_sources.get('policies', {}),
            claims=data_sources.get('claims', {}),
            billing=data_sources.get('billing', {}),
            balance_sheet=data_sources.get('balance_sheet', {}),
            suppliers=data_sources.get('suppliers', {}),
            deliveries=data_sources.get('deliveries', {}),
        )
        record = get_bi_snapshot_service().capture_snapshot(dashboard, source='cron')
        output['snapshot'] = {
            'snapshot_id': record.get('snapshot_id'),
            'captured_at': record.get('captured_at'),
            'metrics': record.get('metrics'),
        }

    if not args.snapshot_only:
        result = bi_service.materialize_views(data_sources, source='cron')
        output['materialized'] = {
            'persisted': result.get('persisted'),
            'path': result.get('path'),
            'written_at': result.get('written_at'),
            'views': result.get('views'),
            'errors': result.get('errors'),
            'error': result.get('error'),
        }
        output['success'] = bool(result.get('success'))

    print(json.dumps(output, default=str))
    return 0 if output['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
