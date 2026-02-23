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
