import threading
import time
import json
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


def _get(url):
    with urlopen(url) as resp:
        return resp.read().decode('utf-8')


def _post(url, payload):
    data = json.dumps(payload).encode('utf-8')
    req = Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def test_apply_flow_provisions_account_and_status():
    # pick a non-default port to avoid conflicts
    port = 8011
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    # Step 1: Create application (Apply Now -> policies/create)
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Test User",
            "customer_email": "test.user@example.com",
            "type": "life",
            "coverage_amount": 100000,
            "risk_score": "medium"
        }
    ))

    assert 'customer' in create_resp
    assert 'policy' in create_resp
    assert 'underwriting' in create_resp
    assert 'provisioned_login' in create_resp

    cust = create_resp['customer']
    login = create_resp['provisioned_login']
    assert login['username'] == cust['email'] or login['username'].endswith('@example.com')
    assert isinstance(login['password'], str) and len(login['password']) >= 8

    # Step 2: Login with provisioned credentials
    login_resp = json.loads(_post(base + "/api/login", {
        "username": login['username'],
        "password": login['password']
    }))
    assert 'token' in login_resp
    assert login_resp['role'] == 'customer'
    assert login_resp.get('customer_id') == cust['id']

    # Step 3: Check customer status
    status_resp = json.loads(_get(base + f"/api/customer/status?customer_id={cust['id']}"))
    assert status_resp['customer']['id'] == cust['id']
    assert status_resp['overall_status'] in ['pending', 'no_application', 'active_policy', 'approved', 'rejected']
    assert any(p['id'] == create_resp['policy']['id'] for p in status_resp['policies'])

    # Step 4: Admin approves underwriting -> policy becomes active
    uw_id = create_resp['underwriting']['id']
    approve_resp = json.loads(_post(base + "/api/underwriting/approve", {
        "id": uw_id,
        "approved_by": "underwriter"
    }))
    assert approve_resp['success'] is True
    assert approve_resp['application']['status'] == 'approved'

    # Step 5: Status should reflect active policy now
    status_after = json.loads(_get(base + f"/api/customer/status?customer_id={cust['id']}"))
    assert status_after['overall_status'] in ['active_policy', 'approved']

    srv.stop()
