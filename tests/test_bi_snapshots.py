"""
Tests for BI KPI snapshots (BI-3): durable trend history for executive KPIs.

Covers the snapshot service (capture/list/trend/integrity/durability) and the
HTTP surface (`POST /api/bi/snapshots/capture`, `GET /api/bi/snapshots`).
"""

from __future__ import annotations

import json
import os

import requests

from services.bi_snapshot_service import (
    BISnapshotService,
    extract_kpi_metrics,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _admin_headers():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin", "password": "admin123",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


_SAMPLE_DASHBOARD = {
    "summary": {
        "total_customers": 10, "active_customers": 8,
        "total_policies": 12, "active_policies": 9,
        "monthly_revenue": 1500.0, "annual_revenue_projection": 18000.0,
    },
    "financial": {
        "total_assets": 100000.0, "total_liabilities": 20000.0,
        "net_worth": 80000.0, "claims_reserve": 30000.0,
        "outstanding_receivables": 500.0, "total_coverage": 900000.0,
        "loss_ratio": 12.5,
    },
    "claims": {
        "total": 4, "total_claimed": 4000.0, "total_paid": 1000.0,
        "approval_rate": 75.0,
    },
    "health_scores": {
        "financial_health": 88.0, "operational_health": 92.0,
        "overall_health": 90.0,
    },
}


class TestMetricExtraction:
    def test_extracts_flat_kpis(self):
        metrics = extract_kpi_metrics(_SAMPLE_DASHBOARD)
        assert metrics["total_customers"] == 10
        assert metrics["monthly_revenue"] == 1500.0
        assert metrics["net_worth"] == 80000.0
        assert metrics["loss_ratio"] == 12.5
        assert metrics["claims_approval_rate"] == 75.0
        assert metrics["overall_health_score"] == 90.0

    def test_missing_sections_become_none(self):
        metrics = extract_kpi_metrics({})
        assert metrics["total_customers"] is None
        assert metrics["net_worth"] is None


class TestSnapshotService:
    def test_capture_and_list(self, tmp_path):
        svc = BISnapshotService(snapshot_dir=str(tmp_path))
        record = svc.capture_snapshot(_SAMPLE_DASHBOARD, source="unit")
        assert record["snapshot_id"].startswith("BISNAP-")
        assert record["record_sha256"]
        assert record["metrics"]["total_customers"] == 10

        listing = svc.list_snapshots()
        assert listing["total"] == 1
        assert listing["items"][0]["snapshot_id"] == record["snapshot_id"]

    def test_trend_series_is_chronological(self, tmp_path):
        svc = BISnapshotService(snapshot_dir=str(tmp_path))
        for revenue in (100.0, 200.0, 300.0):
            dashboard = json.loads(json.dumps(_SAMPLE_DASHBOARD))
            dashboard["summary"]["monthly_revenue"] = revenue
            svc.capture_snapshot(dashboard, source="unit")
        trend = svc.trend("monthly_revenue")
        assert [p["value"] for p in trend["points"]] == [100.0, 200.0, 300.0]

    def test_durability_roundtrip(self, tmp_path):
        svc = BISnapshotService(snapshot_dir=str(tmp_path))
        record = svc.capture_snapshot(_SAMPLE_DASHBOARD, source="unit")

        # A fresh instance hydrates the snapshot from the JSONL file.
        svc2 = BISnapshotService(snapshot_dir=str(tmp_path))
        listing = svc2.list_snapshots()
        assert listing["total"] == 1
        assert listing["items"][0]["snapshot_id"] == record["snapshot_id"]
        assert svc2.verify_snapshot(listing["items"][0]) is True

    def test_tampered_snapshot_fails_verification(self, tmp_path):
        svc = BISnapshotService(snapshot_dir=str(tmp_path))
        record = svc.capture_snapshot(_SAMPLE_DASHBOARD, source="unit")
        tampered = dict(record)
        tampered["metrics"] = dict(tampered["metrics"], net_worth=999999.0)
        assert svc.verify_snapshot(record) is True
        assert svc.verify_snapshot(tampered) is False


class TestSnapshotHTTP:
    def test_capture_endpoint_requires_privileged_role(self):
        resp = requests.post(f"{BASE_URL}/api/bi/snapshots/capture", json={})
        assert resp.status_code == 403

    def test_capture_and_read_back(self):
        headers = _admin_headers()
        resp = requests.post(f"{BASE_URL}/api/bi/snapshots/capture",
                             json={}, headers=headers)
        assert resp.status_code == 201, resp.text
        record = resp.json()
        assert record["snapshot_id"].startswith("BISNAP-")
        assert "metrics" in record

        listing = requests.get(f"{BASE_URL}/api/bi/snapshots", headers=headers)
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert any(
            item["snapshot_id"] == record["snapshot_id"] for item in body["items"]
        )

        trend = requests.get(
            f"{BASE_URL}/api/bi/snapshots",
            params={"metric": "monthly_revenue"},
            headers=headers,
        )
        assert trend.status_code == 200
        trend_body = trend.json()
        assert trend_body["metric"] == "monthly_revenue"
        assert trend_body["count"] >= 1

    def test_list_endpoint_requires_privileged_role(self):
        resp = requests.get(f"{BASE_URL}/api/bi/snapshots")
        assert resp.status_code == 403
