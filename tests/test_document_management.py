"""
Document Management Test Suite

Tests for the enhanced document upload, viewing, and access-control features:
- Upload documents with document_type field (id, receipt, medical, authority, general)
- GET /api/documents/list with admin/customer access control
- GET /api/documents/list with admin filter by customer_id
- GET /api/documents/view?id= with access control
- GET /api/admin/customers-for-documents (admin-only)
- Data persists in POLICY_DOCUMENTS across operations
"""

import threading
import time
import json
import base64
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(('127.0.0.1', port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _post(url, payload, token=None):
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))


def _post_multipart(url, fields=None, files=None, token=None):
    """POST multipart/form-data payload with text fields and binary files."""
    fields = fields or {}
    files = files or []
    boundary = f"----PHINSBoundary{int(time.time() * 1000)}"
    body = bytearray()

    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode('utf-8'))
        body.extend(str(value).encode('utf-8'))
        body.extend(b"\r\n")

    for file_info in files:
        field = file_info['field']
        filename = file_info['filename']
        content_type = file_info.get('content_type', 'application/octet-stream')
        data = file_info.get('data', b'')
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode('utf-8')
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode('utf-8'))
        body.extend(data)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode('utf-8'))
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=bytes(body), headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))


def _get(url, token=None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))


def _init_port(base):
    """Make an initial request to trigger port state initialization (clearing in-memory state).
    The /api/health endpoint bypasses security checks and does not call _ensure_test_port_state,
    so we use /api/documents/list (returns 401 but still runs port initialization)."""
    try:
        _get(base + '/api/documents/list')
    except Exception:
        pass


def _inject_session(token, username, role, customer_id=''):
    """Directly inject a session into the server's SESSIONS dict for testing."""
    portal.SESSIONS[token] = {
        'username': username,
        'role': role,
        'customer_id': customer_id,
        'expires': (datetime.now() + timedelta(hours=1)).isoformat()
    }
    # Ensure user exists in USERS for require_role() lookup
    if username not in portal.USERS:
        portal.USERS[username] = {'role': role, 'username': username}


def test_upload_document_with_document_type():
    """Test that document_type is stored during upload."""
    port = 8200
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-upload-doctype-token'
    _inject_session(token, 'cust_user', 'customer', 'CUST-TEST-001')

    sample_data = base64.b64encode(b'test file content').decode()
    status, resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'id_card.pdf', 'type': 'application/pdf', 'size': 17, 'data': sample_data}],
        'entity_type': 'customer',
        'entity_id': 'CUST-TEST-001',
        'document_type': 'id',
        'description': 'Passport copy'
    }, token)

    assert status == 201, f"Expected 201, got {status}: {resp}"
    assert resp.get('success') is True
    assert len(resp.get('uploaded', [])) == 1

    uploaded = resp['uploaded'][0]
    assert uploaded.get('document_type') == 'id'

    doc_id = uploaded['id']
    doc = portal.POLICY_DOCUMENTS.get(doc_id)
    assert doc is not None, 'Document should be stored in POLICY_DOCUMENTS'
    assert doc.get('document_type') == 'id'
    assert doc.get('uploaded_by_customer') == 'CUST-TEST-001'

    srv.stop()


def test_upload_all_document_types():
    """Test all standard document types can be uploaded."""
    port = 8201
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-all-doctypes-token'
    _inject_session(token, 'cust_user2', 'customer', 'CUST-TEST-002')

    sample_data = base64.b64encode(b'sample').decode()
    for doc_type in ('id', 'receipt', 'medical', 'authority', 'general'):
        status, resp = _post(base + '/api/documents/upload', {
            'files': [{'name': f'{doc_type}_doc.pdf', 'type': 'application/pdf', 'size': 6, 'data': sample_data}],
            'entity_type': 'general',
            'document_type': doc_type,
            'description': f'Test {doc_type}'
        }, token)
        assert status == 201, f"Failed for doc_type={doc_type}: {resp}"
        doc_id = resp['uploaded'][0]['id']
        assert portal.POLICY_DOCUMENTS[doc_id]['document_type'] == doc_type

    srv.stop()


def test_documents_list_customer_sees_only_own():
    """Test that customers can only see their own documents."""
    port = 8202
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenA = 'phins_test-custA-token'
    tokenB = 'phins_test-custB-token'
    _inject_session(tokenA, 'custA', 'customer', 'CUST-A')
    _inject_session(tokenB, 'custB', 'customer', 'CUST-B')

    sample_data = base64.b64encode(b'data').decode()

    # Upload doc as customer A
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'a_doc.pdf', 'type': 'application/pdf', 'size': 4, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'id'
    }, tokenA)

    # Upload doc as customer B
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'b_doc.pdf', 'type': 'application/pdf', 'size': 4, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'receipt'
    }, tokenB)

    # Customer A should only see their own doc
    status_a, resp_a = _get(base + '/api/documents/list', tokenA)
    assert status_a == 200
    names_a = [d['name'] for d in resp_a['documents']]
    assert 'a_doc.pdf' in names_a
    assert 'b_doc.pdf' not in names_a

    # Customer B should only see their own doc
    status_b, resp_b = _get(base + '/api/documents/list', tokenB)
    assert status_b == 200
    names_b = [d['name'] for d in resp_b['documents']]
    assert 'b_doc.pdf' in names_b
    assert 'a_doc.pdf' not in names_b

    srv.stop()


def test_documents_list_admin_sees_all():
    """Test that admin sees all customers' documents."""
    port = 8203
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenCust = 'phins_test-cust-admin-vis-token'
    tokenAdmin = 'phins_test-admin-vis-token'
    _inject_session(tokenCust, 'custC', 'customer', 'CUST-C')
    _inject_session(tokenAdmin, 'admin', 'admin', '')

    sample_data = base64.b64encode(b'data').decode()
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'cust_c_doc.pdf', 'type': 'application/pdf', 'size': 4, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'medical'
    }, tokenCust)

    # Admin should see the document
    status, resp = _get(base + '/api/documents/list', tokenAdmin)
    assert status == 200
    assert resp.get('is_admin') is True
    names = [d['name'] for d in resp['documents']]
    assert 'cust_c_doc.pdf' in names

    srv.stop()


def test_documents_list_admin_filter_by_customer():
    """Test that admin can filter documents by customer_id."""
    port = 8204
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenD = 'phins_test-custD-token'
    tokenE = 'phins_test-custE-token'
    tokenAdmin = 'phins_test-admin-filter-token'
    _inject_session(tokenD, 'custD', 'customer', 'CUST-D')
    _inject_session(tokenE, 'custE', 'customer', 'CUST-E')
    _inject_session(tokenAdmin, 'admin2', 'admin', '')

    sample_data = base64.b64encode(b'data').decode()
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'd_doc.pdf', 'type': 'application/pdf', 'size': 4, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'id'
    }, tokenD)
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'e_doc.pdf', 'type': 'application/pdf', 'size': 4, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'receipt'
    }, tokenE)

    # Admin filters by CUST-D
    status, resp = _get(base + '/api/documents/list?customer_id=CUST-D', tokenAdmin)
    assert status == 200
    names = [d['name'] for d in resp['documents']]
    assert 'd_doc.pdf' in names
    assert 'e_doc.pdf' not in names

    srv.stop()


def test_document_view_owner_can_access():
    """Test that document owner can view their document."""
    port = 8205
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-view-owner-token'
    _inject_session(token, 'custF', 'customer', 'CUST-F')

    content = b'my file content'
    sample_data = base64.b64encode(content).decode()
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'myfile.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'general'
    }, token)

    # Get the doc id
    _, list_resp = _get(base + '/api/documents/list', token)
    doc_id = list_resp['documents'][0]['id']

    # View the doc
    status, view_resp = _get(base + f'/api/documents/view?id={doc_id}', token)
    assert status == 200, f"Expected 200, got {status}: {view_resp}"
    assert view_resp.get('success') is True
    assert view_resp.get('data') == sample_data
    assert view_resp.get('name') == 'myfile.txt'

    srv.stop()


def test_document_view_other_customer_denied():
    """Test that a different customer cannot view another's document."""
    port = 8206
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenG = 'phins_test-custG-token'
    tokenH = 'phins_test-custH-token'
    _inject_session(tokenG, 'custG', 'customer', 'CUST-G')
    _inject_session(tokenH, 'custH', 'customer', 'CUST-H')

    sample_data = base64.b64encode(b'secret').decode()
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'secret.pdf', 'type': 'application/pdf', 'size': 6, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'id'
    }, tokenG)

    # Get doc id (as owner)
    _, list_resp = _get(base + '/api/documents/list', tokenG)
    doc_id = list_resp['documents'][0]['id']

    # Try to view as a different customer
    status, view_resp = _get(base + f'/api/documents/view?id={doc_id}', tokenH)
    assert status == 403, f"Expected 403 Access Denied, got {status}: {view_resp}"

    srv.stop()


def test_document_view_admin_can_access_any():
    """Test that admin can view any customer's document."""
    port = 8207
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenCust = 'phins_test-cust-view-admin-token'
    tokenAdmin = 'phins_test-admin-view-token'
    _inject_session(tokenCust, 'custI', 'customer', 'CUST-I')
    _inject_session(tokenAdmin, 'admin3', 'admin', '')

    content = b'admin can see this'
    sample_data = base64.b64encode(content).decode()
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'private.pdf', 'type': 'application/pdf', 'size': len(content), 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'medical'
    }, tokenCust)

    _, list_resp = _get(base + '/api/documents/list', tokenAdmin)
    doc_ids = [d['id'] for d in list_resp['documents'] if d['name'] == 'private.pdf']
    assert doc_ids, 'Admin should see the document in list'
    doc_id = doc_ids[0]

    status, view_resp = _get(base + f'/api/documents/view?id={doc_id}', tokenAdmin)
    assert status == 200, f"Admin should be able to view: {view_resp}"
    assert view_resp.get('data') == sample_data

    srv.stop()


def test_claims_adjuster_can_access_all_documents():
    """Claims adjuster role should have full document-center visibility."""
    port = 8220
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token_cust = 'phins_test-claims-role-cust-token'
    token_claims = 'phins_test-claims-role-token'
    _inject_session(token_cust, 'custClaimsA', 'customer', 'CUST-CLAIMS-A')
    _inject_session(token_claims, 'claimsAdjusterA', 'claims_adjuster', '')

    content = b'claims team can review this'
    sample_data = base64.b64encode(content).decode()
    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'claims_visibility_doc.pdf', 'type': 'application/pdf', 'size': len(content), 'data': sample_data}],
        'entity_type': 'customer',
        'entity_id': 'CUST-CLAIMS-A',
        'document_type': 'medical'
    }, token_cust)
    doc_id = up_resp['uploaded'][0]['id']

    status_list, list_resp = _get(base + '/api/documents/list', token_claims)
    assert status_list == 200, f"Expected 200, got {status_list}: {list_resp}"
    assert list_resp.get('is_admin') is True
    names = [d['name'] for d in list_resp.get('documents', [])]
    assert 'claims_visibility_doc.pdf' in names

    status_view, view_resp = _get(base + f'/api/documents/view?id={doc_id}', token_claims)
    assert status_view == 200, f"Claims adjuster should view any document: {view_resp}"
    assert view_resp.get('data') == sample_data

    srv.stop()


def test_staff_upload_can_assign_customer_owner_by_entity():
    """Admin/staff uploads linked to customer entity should be visible to that customer."""
    port = 8221
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token_admin = 'phins_test-owner-infer-admin-token'
    token_customer = 'phins_test-owner-infer-customer-token'
    customer_id = 'CUST-OWNER-001'
    _inject_session(token_admin, 'ownerAdmin', 'admin', '')
    _inject_session(token_customer, 'ownerCustomer', 'customer', customer_id)

    sample_data = base64.b64encode(b'staff uploaded record').decode()
    status_up, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'staff_uploaded_for_customer.pdf', 'type': 'application/pdf', 'size': 21, 'data': sample_data}],
        'entity_type': 'customer',
        'entity_id': customer_id,
        'document_type': 'id'
    }, token_admin)
    assert status_up == 201, f"Upload failed: {up_resp}"
    assert up_resp['uploaded'][0].get('uploaded_by_customer') == customer_id

    status_list, list_resp = _get(base + '/api/documents/list', token_customer)
    assert status_list == 200
    names = [d['name'] for d in list_resp.get('documents', [])]
    assert 'staff_uploaded_for_customer.pdf' in names

    srv.stop()


def test_admin_customers_for_documents_endpoint():
    """Test the admin-only endpoint to get customer list for filtering."""
    port = 8208
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenAdmin = 'phins_test-admin-custs-token'
    tokenCust = 'phins_test-cust-custs-token'
    _inject_session(tokenAdmin, 'admin4', 'admin', '')
    _inject_session(tokenCust, 'custJ', 'customer', 'CUST-J')

    # Admin can access
    status, resp = _get(base + '/api/admin/customers-for-documents', tokenAdmin)
    assert status == 200, f"Admin should get customer list: {resp}"
    assert 'customers' in resp

    # Customer cannot access
    status2, resp2 = _get(base + '/api/admin/customers-for-documents', tokenCust)
    assert status2 == 403, f"Customer should be denied: {resp2}"

    srv.stop()


def test_document_view_requires_auth():
    """Test that unauthenticated requests are rejected."""
    port = 8209
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    status, resp = _get(base + '/api/documents/view?id=DOC-FAKE')
    assert status == 401, f"Expected 401, got {status}"

    status2, resp2 = _get(base + '/api/documents/list')
    assert status2 == 401, f"Expected 401, got {status2}"

    srv.stop()


def test_documents_list_includes_document_type_field():
    """Test that list response includes document_type for each document."""
    port = 8210
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-doctype-field-token'
    _inject_session(token, 'custK', 'customer', 'CUST-K')

    sample_data = base64.b64encode(b'data').decode()
    _post(base + '/api/documents/upload', {
        'files': [{'name': 'medical.pdf', 'type': 'application/pdf', 'size': 4, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'medical'
    }, token)

    _, list_resp = _get(base + '/api/documents/list', token)
    docs = list_resp.get('documents', [])
    assert len(docs) >= 1
    doc = next(d for d in docs if d['name'] == 'medical.pdf')
    assert doc.get('document_type') == 'medical'
    assert 'uploaded_by_customer' in doc
    assert 'has_data' in doc

    srv.stop()


# ── AI Document Analysis endpoint tests ─────────────────────────────────────


def test_analyze_medical_high_risk():
    """Analyze a medical document with terminal/high-risk content."""
    port = 8211
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-analyze-medical-token'
    _inject_session(token, 'custL', 'customer', 'CUST-L')

    content = (
        b"MEDICAL REPORT\n"
        b"Patient: John Doe\n"
        b"Diagnosis: Terminal illness - Stage 4 Lung Cancer\n"
        b"Risk Assessment: HIGH RISK\n"
    )
    sample_data = base64.b64encode(content).decode()

    # Upload a medical doc
    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'medical_terminal.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'underwriting',
        'entity_id': 'UW-TEST-001',
        'document_type': 'medical',
        'description': 'Terminal diagnosis'
    }, token)
    doc_id = up_resp['uploaded'][0]['id']

    # Run AI analysis
    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, token)
    assert status == 200, f"Expected 200, got {status}: {resp}"
    assert resp.get('success') is True
    a = resp.get('analysis', {})
    assert a.get('risk_level') in ('high', 'very_high'), f"Expected high/very_high, got: {a.get('risk_level')}"
    assert 'TERMINAL_CONDITION_DETECTED' in a.get('flags', []) or 'EXPLICIT_HIGH_RISK_FLAG' in a.get('flags', [])
    assert len(a.get('findings', [])) > 0
    assert a.get('recommendation') is not None
    assert a.get('risk_score', 0) >= 0.65

    # Analysis should be persisted in POLICY_DOCUMENTS
    assert portal.POLICY_DOCUMENTS[doc_id].get('ai_analysis') is not None

    srv.stop()


def test_analyze_death_certificate_genuine():
    """Analyze a death certificate with full authenticity markers."""
    port = 8212
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-analyze-death-token'
    _inject_session(token, 'custM', 'customer', 'CUST-M')

    content = (
        b"CERTIFICATE OF DEATH\n"
        b"Died on 2026-01-05. Cause of death: Cardiac Arrest.\n"
        b"Certificate No: DC-2026-00045\n"
        b"Issued by: Ministry of Health\n"
        b"Authorized Signatory: Dr. R. Cohen, Registrar\n"
        b"Official document.\n"
    )
    sample_data = base64.b64encode(content).decode()

    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'death_cert.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'claim', 'entity_id': 'CLM-TEST-001',
        'document_type': 'authority', 'description': 'Death certificate'
    }, token)
    doc_id = up_resp['uploaded'][0]['id']

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, token)
    assert status == 200, f"Expected 200, got {status}: {resp}"
    a = resp['analysis']
    assert 'DEATH_CERTIFICATE' in a['flags']
    assert 'AUTHENTICITY_VERIFIED' in a['flags']
    assert a['recommendation'] == 'process_death_claim'
    assert a['bi_insights']['claims_impact']['claim_type'] == 'Life / Death Benefit'

    srv.stop()


def test_analyze_death_certificate_requires_inquiry():
    """Analyze a death certificate with insufficient authenticity markers."""
    port = 8213
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-analyze-death-inq-token'
    _inject_session(token, 'custN', 'customer', 'CUST-N')

    # Only one authenticity marker
    content = b"Certificate of death for John. Issued by a doctor.\n"
    sample_data = base64.b64encode(content).decode()

    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'sketchy_cert.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'claim', 'document_type': 'authority', 'description': 'Death cert limited markers'
    }, token)
    doc_id = up_resp['uploaded'][0]['id']

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, token)
    assert status == 200
    a = resp['analysis']
    assert 'DEATH_CERTIFICATE' in a['flags']
    assert 'AUTHENTICITY_REQUIRES_INQUIRY' in a['flags'] or 'AUTHENTICITY_UNVERIFIABLE' in a['flags']
    assert a['recommendation'] == 'hold_pending_verification'

    srv.stop()


def test_analyze_disability_certificate():
    """Analyze a disability certificate."""
    port = 8214
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-analyze-dis-token'
    _inject_session(token, 'custO', 'customer', 'CUST-O')

    content = (
        b"DISABILITY CERTIFICATE\n"
        b"Disability Grade: 40%\n"
        b"National Insurance Institute\n"
        b"Certificate No: DIS-2026-001\n"
        b"Medical Examiner: Dr. Levi\n"
        b"Valid Until: 2028-01-01\n"
        b"Issued by: National Insurance\n"
    )
    sample_data = base64.b64encode(content).decode()

    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'dis_cert.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'claim', 'document_type': 'authority', 'description': 'Disability cert'
    }, token)
    doc_id = up_resp['uploaded'][0]['id']

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, token)
    assert status == 200
    a = resp['analysis']
    assert 'DISABILITY_CERTIFICATE' in a['flags']
    assert a['recommendation'] in ('process_disability_claim', 'hold_pending_verification')
    assert a['bi_insights']['claims_impact']['claim_type'] == 'Disability Benefit'

    srv.stop()


def test_analyze_billing_overdue():
    """Analyze a billing statement with overdue indicators."""
    port = 8215
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-analyze-billing-token'
    _inject_session(token, 'custP', 'customer', 'CUST-P')

    content = b"BILLING STATEMENT\nOutstanding: $3,750.00\nOverdue: $1,250.00\nLate fee applicable.\n"
    sample_data = base64.b64encode(content).decode()

    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'billing.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'receipt', 'description': 'Q1 billing'
    }, token)
    doc_id = up_resp['uploaded'][0]['id']

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, token)
    assert status == 200
    a = resp['analysis']
    assert 'BILLING_ANOMALY_OVERDUE' in a['flags']
    assert a['bi_insights']['billing_impact']['status'] == 'Anomaly detected'

    srv.stop()


def test_bill_payment_generates_accounting_book_and_invoice_documents():
    """Paying a bill should auto-generate accounting-book and invoice docs once."""
    port = 8223
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token_admin = 'phins_test-bill-doc-admin'
    token_customer = 'phins_test-bill-doc-customer'
    customer_id = 'CUST-BILL-DOCS'
    policy_id = 'POL-BILL-DOCS'
    bill_id = 'BILL-BILL-DOCS'

    _inject_session(token_admin, 'admin_bill_docs', 'admin', '')
    _inject_session(token_customer, 'custBillDocs', 'customer', customer_id)

    portal.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'Bill Doc Customer',
        'email': 'billdocs@example.com',
        'created_date': datetime.now().isoformat(),
    }
    portal.POLICIES[policy_id] = {
        'id': policy_id,
        'customer_id': customer_id,
        'status': 'active',
        'monthly_premium': 125.0,
        'billing': {'frequency': 'monthly', 'auto_pay': False},
    }
    portal.BILLING[bill_id] = {
        'id': bill_id,
        'bill_id': bill_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'amount': 125.0,
        'amount_due': 125.0,
        'amount_paid': 0.0,
        'status': 'outstanding',
        'created_date': datetime.now().isoformat(),
        'due_date': datetime.now().isoformat(),
    }

    status, resp = _post(base + '/api/billing/pay', {
        'bill_id': bill_id,
        'amount': 125.0,
        'payment_method': 'card'
    }, token_admin)
    assert status == 200, f"Expected 200, got {status}: {resp}"
    assert resp.get('success') is True
    docs = resp.get('documents_generated', [])
    assert len(docs) == 2
    doc_types = {doc.get('document_type') for doc in docs}
    assert doc_types == {'accounting_book', 'invoice'}

    bill = portal.BILLING[bill_id]
    linked_doc_ids = bill.get('document_ids', [])
    assert len(linked_doc_ids) == 2

    status_list, list_resp = _get(
        base + f'/api/documents/list?entity_type=billing&entity_id={bill_id}',
        token_customer
    )
    assert status_list == 200, f"Expected 200, got {status_list}: {list_resp}"
    listed = list_resp.get('documents', [])
    assert len(listed) == 2
    assert {doc.get('document_type') for doc in listed} == {'accounting_book', 'invoice'}

    # Re-paying the same bill should not create duplicate generated docs.
    existing_doc_ids = list(portal.BILLING[bill_id].get('document_ids', []))
    status2, resp2 = _post(base + '/api/billing/pay', {
        'bill_id': bill_id,
        'amount': 25.0,
        'payment_method': 'card'
    }, token_admin)
    assert status2 == 200, f"Expected 200, got {status2}: {resp2}"
    assert len(portal.BILLING[bill_id].get('document_ids', [])) == len(existing_doc_ids) == 2

    srv.stop()


def test_marketplace_purchase_generates_accounting_book_and_invoice_documents():
    """Service/product purchase should generate accounting documents linked to the purchase."""
    port = 8224
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token_customer = 'phins_test-purchase-doc-customer'
    customer_id = 'CUST-PURCHASE-DOCS'
    _inject_session(token_customer, 'custPurchaseDocs', 'customer', customer_id)

    portal.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'Purchase Doc Customer',
        'email': 'purchasedocs@example.com',
        'created_date': datetime.now().isoformat(),
    }
    portal.HEALTH_WALLETS[customer_id] = {
        'customer_id': customer_id,
        'balance': 1000.0,
        'monthly_deposit': 0.0,
        'transactions': [],
        'created_at': datetime.now().isoformat(),
    }

    status, resp = _post(base + '/api/health-wallet/purchase', {
        'customer_id': customer_id,
        'product_id': 'PROD-DOC-001',
        'product_name': 'Institutional Lab Service',
        'amount': 80.0,
        'category': 'medical_services',
        'provider': 'PHINS Labs',
        'payment_method': 'health_wallet'
    }, token_customer)
    assert status == 200, f"Expected 200, got {status}: {resp}"
    assert resp.get('success') is True
    purchase = resp.get('purchase', {})
    docs = resp.get('documents_generated', [])
    assert len(docs) == 2
    assert {doc.get('document_type') for doc in docs} == {'accounting_book', 'invoice'}

    purchase_id = purchase.get('id')
    assert purchase_id
    stored_purchase = portal.MEDICAL_PURCHASES[purchase_id]
    assert len(stored_purchase.get('document_ids', [])) == 2

    ledger_tx_id = purchase.get('ledger_tx_id')
    assert ledger_tx_id
    ledger_entry = portal.TRANSACTION_LEDGER[ledger_tx_id]
    assert len(ledger_entry.get('document_ids', [])) == 2

    status_list, list_resp = _get(
        base + f'/api/documents/list?entity_type=transaction&entity_id={ledger_tx_id}',
        token_customer
    )
    assert status_list == 200, f"Expected 200, got {status_list}: {list_resp}"
    listed = list_resp.get('documents', [])
    assert len(listed) == 2
    assert {doc.get('document_type') for doc in listed} == {'accounting_book', 'invoice'}

    srv.stop()


def test_analyze_requires_auth():
    """Unauthenticated analyze request should be rejected."""
    port = 8216
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': 'DOC-FAKE'})
    assert status == 401, f"Expected 401, got {status}"

    srv.stop()


def test_analyze_access_denied_for_other_customer():
    """Customer cannot analyze another customer's document."""
    port = 8217
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenOwner = 'phins_test-analyze-owner-token'
    tokenOther = 'phins_test-analyze-other-token'
    _inject_session(tokenOwner, 'custQ', 'customer', 'CUST-Q')
    _inject_session(tokenOther, 'custR', 'customer', 'CUST-R')

    sample_data = base64.b64encode(b'private content').decode()
    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'private.txt', 'type': 'text/plain', 'size': 15, 'data': sample_data}],
        'entity_type': 'general', 'document_type': 'id'
    }, tokenOwner)
    doc_id = up_resp['uploaded'][0]['id']

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, tokenOther)
    assert status == 403, f"Expected 403, got {status}: {resp}"

    srv.stop()


def test_analyze_admin_can_analyze_any_document():
    """Admin can analyze any customer's document."""
    port = 8218
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tokenCust = 'phins_test-analyze-cust-token'
    tokenAdmin = 'phins_test-analyze-admin-token'
    _inject_session(tokenCust, 'custS', 'customer', 'CUST-S')
    _inject_session(tokenAdmin, 'admin_analyze', 'admin', '')

    sample_data = base64.b64encode(b'some medical data').decode()
    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'cust_medical.txt', 'type': 'text/plain', 'size': 17, 'data': sample_data}],
        'entity_type': 'underwriting', 'document_type': 'medical'
    }, tokenCust)
    doc_id = up_resp['uploaded'][0]['id']

    status, resp = _post(base + '/api/documents/analyze', {'doc_id': doc_id}, tokenAdmin)
    assert status == 200, f"Admin should be able to analyze: {resp}"
    assert resp.get('success') is True

    srv.stop()


def test_analyze_persists_result_in_list():
    """After analysis, ai_analysis should appear in /api/documents/list response."""
    port = 8219
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = 'phins_test-analyze-persist-token'
    _inject_session(token, 'custT', 'customer', 'CUST-T')

    content = b"Medical report. Patient has diabetes and hypertension."
    sample_data = base64.b64encode(content).decode()
    _, up_resp = _post(base + '/api/documents/upload', {
        'files': [{'name': 'med2.txt', 'type': 'text/plain', 'size': len(content), 'data': sample_data}],
        'entity_type': 'underwriting', 'document_type': 'medical'
    }, token)
    doc_id = up_resp['uploaded'][0]['id']

    # Run analysis
    _post(base + '/api/documents/analyze', {'doc_id': doc_id}, token)

    # List should now return ai_analysis field
    _, list_resp = _get(base + '/api/documents/list', token)
    docs = list_resp.get('documents', [])
    target = next((d for d in docs if d['id'] == doc_id), None)
    assert target is not None
    assert target.get('ai_analysis') is not None, 'ai_analysis should be returned in list after analysis'
    assert target['ai_analysis'].get('risk_level') is not None

    srv.stop()


def test_seed_demo_documents_populates_on_empty():
    """seed_demo_documents should populate POLICY_DOCUMENTS when empty."""
    # Clear and re-seed
    portal.POLICY_DOCUMENTS.clear()
    portal.seed_demo_documents()
    assert len(portal.POLICY_DOCUMENTS) >= 7, (
        f"Expected at least 7 seeded documents, got {len(portal.POLICY_DOCUMENTS)}"
    )
    # Verify key document types are present
    doc_types = {d.get('document_type') for d in portal.POLICY_DOCUMENTS.values()}
    assert 'medical' in doc_types
    assert 'authority' in doc_types
    assert 'id' in doc_types
    assert 'receipt' in doc_types


def test_seed_demo_documents_is_idempotent():
    """seed_demo_documents should not add duplicates when called again."""
    portal.POLICY_DOCUMENTS.clear()
    portal.seed_demo_documents()
    count_after_first = len(portal.POLICY_DOCUMENTS)
    portal.seed_demo_documents()  # second call — should be no-op
    assert len(portal.POLICY_DOCUMENTS) == count_after_first, (
        'seed_demo_documents should not add documents when POLICY_DOCUMENTS is non-empty'
    )


def test_quote_submission_stores_registration_documents():
    """Quote submission must persist id/medical uploads into customer document center."""
    port = 8222
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    quote_fields = {
        'firstName': 'Quote',
        'lastName': 'Customer',
        'email': 'quote.customer@example.com',
        'phone': '+1-555-111-2222',
        'dob': '1991-04-10',
        'gender': 'Male',
        'address': '123 Persist Lane',
        'city': 'Tel Aviv',
        'postalCode': '61000',
        'occupation': 'Engineer',
        'smoking': 'NonSmoker',
        'preExisting': 'yes',
        'conditionsDetails': 'Diabetes',
        'coverageAmount': '250000',
        'policyTerm': '20',
    }
    quote_files = [
        {
            'field': 'idDocument',
            'filename': 'quote_id_doc_test.pdf',
            'content_type': 'application/pdf',
            'data': b'%PDF-1.4 fake id document',
        },
        {
            'field': 'medicalRecords',
            'filename': 'quote_med_record_1.pdf',
            'content_type': 'application/pdf',
            'data': b'%PDF-1.4 fake medical record 1',
        },
        {
            'field': 'medicalRecords',
            'filename': 'quote_med_record_2.pdf',
            'content_type': 'application/pdf',
            'data': b'%PDF-1.4 fake medical record 2',
        },
    ]

    status, resp = _post_multipart(base + '/api/submit-quote', fields=quote_fields, files=quote_files)
    assert status == 200, f"Expected 200, got {status}: {resp}"
    assert resp.get('success') is True
    assert resp.get('uploaded_documents'), "Expected registration documents to be stored"
    assert resp.get('document_upload_errors') == []

    customer_id = resp.get('customer_id')
    app_id = resp.get('application_id')
    login_username = resp.get('login_credentials', {}).get('username')
    assert customer_id and app_id and login_username

    # Create a customer session and verify uploaded registration docs are visible.
    token_customer = 'phins_test-quote-docs-customer-token'
    _inject_session(token_customer, login_username, 'customer', customer_id)

    status_list, list_resp = _get(base + '/api/documents/list', token_customer)
    assert status_list == 200, f"Expected 200, got {status_list}: {list_resp}"
    doc_names = {d['name'] for d in list_resp.get('documents', [])}
    assert 'quote_id_doc_test.pdf' in doc_names
    assert 'quote_med_record_1.pdf' in doc_names
    assert 'quote_med_record_2.pdf' in doc_names

    # Integrity metadata should be present for persisted records.
    for d in portal.POLICY_DOCUMENTS.values():
        if d.get('name') in {'quote_id_doc_test.pdf', 'quote_med_record_1.pdf', 'quote_med_record_2.pdf'}:
            assert d.get('uploaded_by_customer') == customer_id
            assert d.get('sha256')
            assert d.get('data_encoding') == 'base64'

    app_docs = portal.UNDERWRITING_APPLICATIONS.get(app_id, {}).get('documents', [])
    assert len(app_docs) >= 3

    srv.stop()

