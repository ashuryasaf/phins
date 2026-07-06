"""
Legal & Compliance Endpoints Test Suite

Tests the legal API endpoints and static legal pages:
- /api/legal/privacy-policy — returns privacy policy metadata
- /api/legal/terms-of-use — returns terms of use metadata
- /api/legal/stats — returns compliance stats for admin dashboard
- /api/legal/consent/status — returns consent status (authenticated)
- /privacy-policy.html — static privacy policy page
- /terms-of-use.html — static terms of use page
"""

import json
import os
from urllib.request import urlopen, Request
from urllib.error import HTTPError

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _get(url, token=None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8'), resp.status


def _post(url, payload, token=None):
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8'), resp.status


def _get_admin_token():
    body, status = _post(f"{BASE_URL}/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    assert status == 200, f"Login failed with status {status}"
    data = json.loads(body)
    return data.get('token')


class TestPrivacyPolicyAPI:

    def test_privacy_policy_endpoint_returns_200(self):
        body, status = _get(f"{BASE_URL}/api/legal/privacy-policy")
        assert status == 200

    def test_privacy_policy_returns_valid_json(self):
        body, status = _get(f"{BASE_URL}/api/legal/privacy-policy")
        data = json.loads(body)
        assert data['title'] == 'Privacy Policy'
        assert data['version'] == '1.0'
        assert data['url'] == '/privacy-policy.html'

    def test_privacy_policy_has_effective_date(self):
        body, _ = _get(f"{BASE_URL}/api/legal/privacy-policy")
        data = json.loads(body)
        assert 'effective_date' in data
        assert 'last_updated' in data

    def test_privacy_policy_has_sections(self):
        body, _ = _get(f"{BASE_URL}/api/legal/privacy-policy")
        data = json.loads(body)
        assert 'sections' in data
        assert len(data['sections']) >= 10
        assert 'AI & Automated Decision-Making' in data['sections']
        assert 'Health & Medical Data (HIPAA)' in data['sections']
        assert 'Your Rights' in data['sections']

    def test_privacy_policy_has_compliance_frameworks(self):
        body, _ = _get(f"{BASE_URL}/api/legal/privacy-policy")
        data = json.loads(body)
        frameworks = data.get('compliance_frameworks', [])
        assert 'GDPR' in frameworks
        assert 'EU AI Act' in frameworks
        assert 'HIPAA' in frameworks
        assert 'CCPA/CPRA' in frameworks
        assert 'LGPD' in frameworks
        assert 'POPIA' in frameworks

    def test_privacy_policy_has_contact_info(self):
        body, _ = _get(f"{BASE_URL}/api/legal/privacy-policy")
        data = json.loads(body)
        assert 'contact' in data
        assert data['contact']['dpo_email'] == 'privacy@phins.com'


class TestTermsOfUseAPI:

    def test_terms_of_use_endpoint_returns_200(self):
        body, status = _get(f"{BASE_URL}/api/legal/terms-of-use")
        assert status == 200

    def test_terms_of_use_returns_valid_json(self):
        body, status = _get(f"{BASE_URL}/api/legal/terms-of-use")
        data = json.loads(body)
        assert data['title'] == 'Terms of Use'
        assert data['version'] == '1.0'
        assert data['url'] == '/terms-of-use.html'

    def test_terms_of_use_has_effective_date(self):
        body, _ = _get(f"{BASE_URL}/api/legal/terms-of-use")
        data = json.loads(body)
        assert 'effective_date' in data
        assert 'last_updated' in data

    def test_terms_of_use_has_sections(self):
        body, _ = _get(f"{BASE_URL}/api/legal/terms-of-use")
        data = json.loads(body)
        assert 'sections' in data
        assert len(data['sections']) >= 10
        assert 'AI-Powered Services & Limitations' in data['sections']
        assert 'Insurance Products & Services' in data['sections']
        assert 'Investment Services' in data['sections']
        assert 'Health & Wellness Services' in data['sections']

    def test_terms_of_use_has_governing_law(self):
        body, _ = _get(f"{BASE_URL}/api/legal/terms-of-use")
        data = json.loads(body)
        assert 'governing_law' in data

    def test_terms_of_use_has_contact_info(self):
        body, _ = _get(f"{BASE_URL}/api/legal/terms-of-use")
        data = json.loads(body)
        assert 'contact' in data
        assert data['contact']['legal_email'] == 'legal@phins.com'


class TestLegalStatsAPI:

    def test_legal_stats_returns_200(self):
        body, status = _get(f"{BASE_URL}/api/legal/stats")
        assert status == 200

    def test_legal_stats_returns_documents(self):
        body, _ = _get(f"{BASE_URL}/api/legal/stats")
        data = json.loads(body)
        assert 'documents' in data
        assert data['total_documents'] == 2
        doc_names = [d['name'] for d in data['documents']]
        assert 'Privacy Policy' in doc_names
        assert 'Terms of Use' in doc_names

    def test_legal_stats_documents_are_active(self):
        body, _ = _get(f"{BASE_URL}/api/legal/stats")
        data = json.loads(body)
        for doc in data['documents']:
            assert doc['status'] == 'active'
            assert 'version' in doc
            assert 'url' in doc

    def test_legal_stats_compliance_frameworks(self):
        body, _ = _get(f"{BASE_URL}/api/legal/stats")
        data = json.loads(body)
        assert 'compliance_frameworks' in data
        framework_names = [f['name'] for f in data['compliance_frameworks']]
        assert 'GDPR' in framework_names
        assert 'EU AI Act' in framework_names
        assert 'HIPAA' in framework_names
        for fw in data['compliance_frameworks']:
            assert fw['status'] == 'compliant'

    def test_legal_stats_all_compliant_flag(self):
        body, _ = _get(f"{BASE_URL}/api/legal/stats")
        data = json.loads(body)
        assert data['all_compliant'] is True


class TestConsentStatusAPI:

    def test_consent_status_requires_auth(self):
        try:
            _get(f"{BASE_URL}/api/legal/consent/status")
            assert False, "Should have returned 401"
        except HTTPError as e:
            assert e.code == 401

    def test_consent_status_with_auth(self):
        token = _get_admin_token()
        if not token:
            return
        body, status = _get(f"{BASE_URL}/api/legal/consent/status", token=token)
        assert status == 200
        data = json.loads(body)
        assert 'privacy_policy' in data
        assert 'terms_of_use' in data
        assert data['privacy_policy']['version'] == '1.0'
        assert data['terms_of_use']['version'] == '1.0'


class TestLegalStaticPages:

    def test_privacy_policy_page_loads(self):
        body, status = _get(f"{BASE_URL}/privacy-policy.html")
        assert status == 200
        assert 'Privacy Policy' in body
        assert 'PHINS' in body

    def test_privacy_policy_page_has_required_sections(self):
        body, _ = _get(f"{BASE_URL}/privacy-policy.html")
        assert 'AI &amp; Automated Decision-Making' in body or 'AI & Automated Decision-Making' in body
        assert 'GDPR' in body
        assert 'HIPAA' in body
        assert 'EU AI Act' in body
        assert 'CCPA' in body
        assert 'Data Security' in body
        assert 'Your Rights' in body

    def test_privacy_policy_page_has_contact_info(self):
        body, _ = _get(f"{BASE_URL}/privacy-policy.html")
        assert 'privacy@phins.com' in body
        assert 'Data Protection Officer' in body

    def test_terms_of_use_page_loads(self):
        body, status = _get(f"{BASE_URL}/terms-of-use.html")
        assert status == 200
        assert 'Terms of Use' in body
        assert 'PHINS' in body

    def test_terms_of_use_page_has_required_sections(self):
        body, _ = _get(f"{BASE_URL}/terms-of-use.html")
        assert 'AI-Powered Services' in body
        assert 'Insurance Products' in body
        assert 'Investment Services' in body
        assert 'Health' in body
        assert 'Dispute Resolution' in body
        assert 'Intellectual Property' in body

    def test_terms_of_use_page_has_contact_info(self):
        body, _ = _get(f"{BASE_URL}/terms-of-use.html")
        assert 'legal@phins.com' in body

    def test_terms_of_use_links_to_privacy_policy(self):
        body, _ = _get(f"{BASE_URL}/terms-of-use.html")
        assert '/privacy-policy.html' in body

    def test_privacy_policy_links_to_terms_of_use(self):
        body, _ = _get(f"{BASE_URL}/privacy-policy.html")
        assert '/terms-of-use.html' in body


class TestLegalLinksIntegration:

    def test_index_page_is_minimal_landing(self):
        # The redesigned landing page intentionally carries no footer link
        # clutter; legal links remain on login/register/apply/dashboard pages.
        body, _ = _get(f"{BASE_URL}/index.html")
        assert '/privacy-policy.html' not in body
        assert '/terms-of-use.html' not in body
        assert '/login.html' in body

    def test_apply_page_has_legal_links(self):
        body, _ = _get(f"{BASE_URL}/apply.html")
        assert '/privacy-policy.html' in body
        assert '/terms-of-use.html' in body

    def test_login_page_is_minimal(self):
        # The redesigned login page intentionally carries no footer link
        # clutter; legal links remain on apply/dashboard pages.
        body, _ = _get(f"{BASE_URL}/login.html")
        assert '/privacy-policy.html' not in body
        assert '/terms-of-use.html' not in body

    def test_register_page_is_minimal(self):
        body, _ = _get(f"{BASE_URL}/register.html")
        assert '/privacy-policy.html' not in body
        assert '/terms-of-use.html' not in body

    def test_dashboard_has_legal_links(self):
        body, _ = _get(f"{BASE_URL}/dashboard.html")
        assert '/privacy-policy.html' in body
        assert '/terms-of-use.html' in body
