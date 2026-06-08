"""
Tests for the Mislaka affiliation engine and the affiliation-rebuilt report.

Covers:
- Decoding raw Mislaka codes into named affiliations (product/status/provider).
- Adjustable reporting filters (policy number, product, status, provider, dates).
- Deterministic SHA-256 integrity envelope over the filtered projection.
- No fabrication: unknown codes are preserved verbatim, undated records are
  excluded from a date window rather than guessed.
- The report generator stays affiliation-structured and filter-aware.
"""

from __future__ import annotations

from services.mislaka_affiliations import (
    ReportFilters,
    apply_filters,
    build_affiliation_projection,
    decode_affiliations,
)
from services.mislaka_api_service import (
    MislakaPerson,
    MislakaPolicy,
    MislakaQueryResult,
    MislakaStatus,
)
from services.mislaka_report_generator import (
    build_mislaka_report_text,
    mislaka_facts,
)


def _policy(**kw):
    base = dict(
        policy_id="P", policy_number="POL", product_type="1", company_name="",
        company_code="01", start_date="2020-01-01", status="1",
    )
    base.update(kw)
    return MislakaPolicy(**base)


def _result(policies):
    return MislakaQueryResult(
        request_id="REQ-TEST",
        status=MislakaStatus.SUCCESS,
        timestamp="2026-01-01T00:00:00",
        person=MislakaPerson(id_number="123456782", first_name="Test", last_name="User"),
        policies=policies,
        total_policies=len(policies),
        total_accumulated=0,
        total_monthly_premium=0,
    )


class TestDecodeAffiliations:
    def test_known_codes_decode_to_named_affiliations(self):
        aff = decode_affiliations(_policy(product_type="1", status="1", company_code="01"))
        assert aff["product"]["name"] == "New Pension Fund"
        assert aff["product"]["decoded"] is True
        assert aff["status"]["name"] == "Active"
        assert aff["provider"]["name"] == "מגדל"  # company code 01
        assert aff["provider"]["decoded"] is True

    def test_unknown_codes_are_preserved_not_fabricated(self):
        aff = decode_affiliations(_policy(product_type="999", status="zz", company_code="ZZ"))
        assert aff["product"]["decoded"] is False
        assert aff["product"]["name"] == "999"  # raw code preserved
        assert aff["status"]["decoded"] is False
        assert aff["provider"]["decoded"] is False


class TestFilters:
    def test_filter_by_policy_number(self):
        pols = [_policy(policy_number="POL-1"), _policy(policy_number="POL-2")]
        out = apply_filters(pols, ReportFilters(policy_number="POL-2"))
        assert [p.policy_number for p in out] == ["POL-2"]

    def test_filter_by_product_accepts_code_or_name(self):
        pols = [_policy(product_type="1"), _policy(product_type="7")]
        assert len(apply_filters(pols, ReportFilters(product_type="1"))) == 1
        assert len(apply_filters(pols, ReportFilters(product_type="new pension fund"))) == 1
        assert len(apply_filters(pols, ReportFilters(product_type="managers insurance"))) == 1

    def test_filter_by_status_and_provider(self):
        pols = [
            _policy(policy_number="A", status="1", company_code="01"),
            _policy(policy_number="B", status="2", company_code="03"),
        ]
        assert [p.policy_number for p in apply_filters(pols, ReportFilters(status="active"))] == ["A"]
        assert [p.policy_number for p in apply_filters(pols, ReportFilters(provider="כלל"))] == ["B"]

    def test_date_window_filters_inclusive(self):
        pols = [
            _policy(policy_number="OLD", start_date="2019-01-01"),
            _policy(policy_number="MID", start_date="2021-06-15"),
            _policy(policy_number="NEW", start_date="2024-03-01"),
        ]
        out = apply_filters(pols, ReportFilters(date_from="2020-01-01", date_to="2022-12-31"))
        assert [p.policy_number for p in out] == ["MID"]

    def test_undated_record_excluded_by_date_filter_never_guessed(self):
        pols = [_policy(policy_number="NODATE", start_date="")]
        out = apply_filters(pols, ReportFilters(date_from="2000-01-01"))
        assert out == []  # excluded, not fabricated into the window


class TestProjectionIntegrity:
    def test_projection_is_deterministic(self):
        pols = [_policy(policy_number="A"), _policy(policy_number="B")]
        p1 = build_affiliation_projection(pols)
        p2 = build_affiliation_projection(pols)
        assert p1["integrity"]["sha256"] == p2["integrity"]["sha256"]

    def test_filter_changes_checksum_and_counts(self):
        pols = [_policy(policy_number="A"), _policy(policy_number="B")]
        full = build_affiliation_projection(pols)
        one = build_affiliation_projection(pols, filters=ReportFilters(policy_number="A"))
        assert full["policy_count"] == 2
        assert one["policy_count"] == 1
        assert one["source_policy_count"] == 2
        assert full["integrity"]["sha256"] != one["integrity"]["sha256"]

    def test_groups_are_sorted_membership(self):
        pols = [
            _policy(policy_number="A", company_code="03"),  # כלל
            _policy(policy_number="B", company_code="01"),  # מגדל
        ]
        proj = build_affiliation_projection(pols)
        providers = [g["affiliation"] for g in proj["groups"]["by_provider"]]
        assert providers == sorted(providers, key=str.lower)


class TestReportGenerator:
    def test_report_text_is_affiliation_structured(self):
        res = _result([_policy(policy_number="POL-1", product_type="1", company_code="01")])
        text, meta, data = build_mislaka_report_text(res)
        assert "MISLAKA AFFILIATION REPORT" in text
        assert "New Pension Fund" in text
        assert meta["data_hash_source"] == "affiliation_projection"
        assert data["accounts"][0]["affiliations"]["product"]["name"] == "New Pension Fund"

    def test_report_respects_filters_and_hash_matches_filtered_set(self):
        res = _result([
            _policy(policy_number="POL-1", start_date="2019-01-01"),
            _policy(policy_number="POL-2", start_date="2024-01-01"),
        ])
        _, meta_all, _ = build_mislaka_report_text(res)
        _, meta_filt, _ = build_mislaka_report_text(res, filters={"date_from": "2023-01-01"})
        assert meta_all["policy_count"] == 2
        assert meta_filt["policy_count"] == 1
        assert meta_filt["source_policy_count"] == 2
        assert meta_all["data_hash"] != meta_filt["data_hash"]

    def test_mislaka_facts_are_affiliation_enriched(self):
        res = _result([_policy(policy_number="POL-1", product_type="6", company_code="01")])
        rows = mislaka_facts(res)
        assert rows[0]["affiliation_product"] == "Education Fund"
        assert rows[0]["affiliation_provider"] == "מגדל"
        assert rows[0]["affiliations"]["product"]["decoded"] is True
