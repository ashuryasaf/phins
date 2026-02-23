import re
from pathlib import Path


CLAIMS_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "claims-adjuster-dashboard.html"


def _extract_inline_scripts(html: str) -> list[str]:
    return re.findall(r"<script(?:[^>]*)>(.*?)</script>", html, flags=re.S)


def test_claims_dashboard_main_script_is_not_truncated():
    content = CLAIMS_DASHBOARD_PATH.read_text(encoding="utf-8")
    scripts = _extract_inline_scripts(content)

    # The page should have two inline scripts:
    # 1) mobile nav toggle
    # 2) main dashboard logic
    assert len(scripts) == 2

    main_script = max(scripts, key=len)
    assert "generateAccumulativeRiskReport" in main_script
    assert "downloadProbabilityReportJSON" in main_script
    assert "updateRiskSummary" in main_script

    # Guard against inline HTML template strings breaking script parsing.
    assert "</script>" not in main_script


def test_claims_dashboard_handles_paginated_and_legacy_claim_shapes():
    content = CLAIMS_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "Array.isArray(data.items)" in content
    assert "Array.isArray(data.claims)" in content


def test_claims_dashboard_normalizes_status_variants():
    content = CLAIMS_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "function normalizeClaimStatus" in content
    assert "replace(/[_-]+/g, ' ')" in content
    assert "normalized === 'underreview'" in content
