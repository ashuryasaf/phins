import re
from pathlib import Path


RISK_REPORTS_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "risk-reports-dashboard.html"


def _extract_inline_scripts(html: str) -> list[str]:
    return re.findall(r"<script(?:[^>]*)>(.*?)</script>", html, flags=re.S)


def test_risk_reports_dashboard_keeps_uploaded_evidence_hooks():
    content = RISK_REPORTS_DASHBOARD_PATH.read_text(encoding="utf-8")
    scripts = _extract_inline_scripts(content)

    assert scripts
    main_script = max(scripts, key=len)

    assert "let uploadedEvidenceSnapshots = [];" in main_script
    assert "uploaded_data_affiliations" in main_script
    assert "uploadedEvidence: uploadedEvidenceSnapshots" in main_script


def test_risk_reports_dashboard_renders_uploaded_evidence_sections():
    content = RISK_REPORTS_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "function getUploadedEvidenceSnapshots" in content
    assert "function renderUploadedEvidenceInsights" in content
    assert "function renderCustomer360Insights" in content
    assert "function buildUploadedEvidenceSections" in content
    assert "Exact source values preserved" in content
    assert "Uploaded Data Affiliation Summary" in content
    assert "Customer 360 BI Summary" in content
    assert "ZIP Internal Modules" in content
