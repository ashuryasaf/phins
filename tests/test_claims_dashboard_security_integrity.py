from pathlib import Path


CLAIMS_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "claims-adjuster-dashboard.html"
SERVER_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
CLAIMS_JOB_PATH = Path(__file__).resolve().parents[1] / "services" / "jobs" / "claims_bot_job.py"


def test_claims_dashboard_escapes_dynamic_content_in_core_views():
    content = CLAIMS_DASHBOARD_PATH.read_text(encoding="utf-8")

    # Core sanitization helpers should exist.
    assert "function escapeHtml(value)" in content
    assert "function escapeForSingleQuotedJs(value)" in content
    assert "function sanitizeClaimForUI(claim)" in content

    # Dynamic HTML in key claim views should be escaped.
    assert "Claim #${escapeHtml(claimId || 'N/A')}" in content
    assert "${escapeHtml(claim.description || 'No description provided')}" in content
    assert "${escapeHtml(formatCustomerLabel(claim))}" in content
    assert "openReview('${reportClaimIdJs}')" in content


def test_claims_dashboard_report_exports_do_not_include_plain_customer_email():
    content = CLAIMS_DASHBOARD_PATH.read_text(encoding="utf-8")

    # CSV export header must not include raw email column.
    assert "Claim ID,Customer,Amount,Risk Score,Risk Level,Fraud Flags,Key Factors,Status,Filed Date" in content
    assert "Claim ID,Customer,Email,Amount,Risk Score,Risk Level,Fraud Flags,Key Factors,Status,Filed Date" not in content

    # Risk table should not directly render underwriting customer email.
    assert "ra.analysis.uwData?.customer_email" not in content
    assert "function csvSafeCell(value)" in content


def test_claims_server_enforces_claims_auth_and_state_transitions():
    content = SERVER_PATH.read_text(encoding="utf-8")

    # Authorization hooks on mutating/report claim endpoints.
    assert "if path == '/api/claims/approve':" in content
    assert "if session and not is_claims_review_role(effective_role):" in content
    assert "if path == '/api/claims/reject':" in content
    assert "if path == '/api/claims/pay':" in content
    assert "if session and not is_claims_payment_role(effective_role):" in content
    assert "if path.startswith('/api/claim/') and path.endswith('/pay'):" in content
    assert "if path == '/api/claims/probability-report':" in content
    assert "Claims report access denied" in content

    # Data integrity and leakage controls should exist.
    assert "persist_claim_update_to_database(claim_id" in content
    assert "persist_claim_update_to_database(claim_id, claim)" not in content
    assert "sanitize_claim_probability_report(report)" in content
    # The evidence redaction lives in the shared adapter (A4) so the inline
    # route and the standalone worker redact identically; server.py delegates.
    assert "from services.jobs.claims_bot_job import sanitize_claim_probability_report" in content
    shared = CLAIMS_JOB_PATH.read_text(encoding="utf-8")
    assert "cleaned.pop('evidence', None)" in shared
    assert "Claim has already been paid" in content


def test_claims_probability_report_sanitizer_strips_evidence_on_server_path():
    import sys

    root = str(Path(__file__).resolve().parents[1])
    for entry in (root, str(Path(root) / "web_portal")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    from web_portal import server

    report = {
        "claim_id": "CLM-1",
        "risk_score": 0.4,
        "fraud_indicators": {
            "count": 2,
            "high_severity_count": 0,
            "indicators": [
                {"type": "x", "evidence": ["raw doc text"], "severity": 0.9},
                {"type": "y", "evidence": ["raw doc text"], "severity": 0.2},
            ],
        },
    }
    cleaned = server.sanitize_claim_probability_report(report)
    assert "evidence" not in str(cleaned)
    assert cleaned["fraud_indicators"]["count"] == 2
    assert cleaned["fraud_indicators"]["high_severity_count"] == 1
    # Input is left untouched so the compliance trail keeps the full record.
    assert report["fraud_indicators"]["indicators"][0]["evidence"] == ["raw doc text"]

def test_ui_clarity_injection_skips_script_blocks():
    content = SERVER_PATH.read_text(encoding="utf-8")

    # Ensure UI-clarity injection targets the last real body close tag.
    assert "def _inject_ui_clarity_script(html_content: str) -> str:" in content
    assert "Some static pages contain \"</body>\" inside JavaScript template literals." in content
    assert "body_close_regex = re.compile(r'</body\\s*>', flags=re.IGNORECASE)" in content
    assert "matches = list(body_close_regex.finditer(html_content))" in content
