import json
import os
import threading
import time
from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler

import requests

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


class _WebhookCapture:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests: list[dict] = []
        self.event = threading.Event()

    def add(self, payload: dict):
        with self.lock:
            self.requests.append(payload)
        self.event.set()

    def last(self) -> dict | None:
        with self.lock:
            return self.requests[-1] if self.requests else None


class _WebhookServerThread(threading.Thread):
    def __init__(self, httpd: HTTPServer):
        super().__init__(daemon=True)
        self.httpd = httpd

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _start_sms_webhook(cap: _WebhookCapture) -> tuple[_WebhookServerThread, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            try:
                n = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                n = 0
            raw = self.rfile.read(n) if n else b""
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {"_raw": raw.decode("utf-8", errors="replace")}
            cap.add(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, fmt, *args):  # silence noisy logs
            return

    httpd = HTTPServer(("127.0.0.1", 0), Handler)  # bind ephemeral port
    port = httpd.server_address[1]
    t = _WebhookServerThread(httpd)
    return t, f"http://127.0.0.1:{port}/sms"


def _reset_in_memory_state():
    # Only safe when running in-memory mode.
    for d in (
        portal.POLICIES,
        portal.CLAIMS,
        portal.CUSTOMERS,
        portal.UNDERWRITING_APPLICATIONS,
        portal.SESSIONS,
        portal.BILLING,
        portal.TOKEN_REGISTRY,
        portal.NOTIFICATIONS,
        portal.FORM_SUBMISSIONS,
        portal.RATE_LIMIT,
        portal.FAILED_LOGINS,
        portal.BLOCKED_IPS,
        portal.SUSPICIOUS_PATTERNS,
    ):
        try:
            d.clear()
        except Exception:
            pass
    try:
        portal.MALICIOUS_ATTEMPTS.clear()
    except Exception:
        pass


def _login(base: str, username: str, password: str) -> str:
    r = requests.post(
        base + "/api/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("token", "").startswith("phins_")
    return j["token"]


def _make_valid_pdf_bytes(text: str) -> bytes:
    # ReportLab is a runtime dependency of the portal (used for policy PDFs).
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    bio = BytesIO()
    c = canvas.Canvas(bio, pagesize=letter)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return bio.getvalue()


def test_pipeline_approve_to_policy_to_billing_to_claims():
    """
    Pipeline test:
      submit application (includes billing method on file) -> admin approve -> policy artifacts + billing setup + notification
      file claim -> claim ties to issuance + nft token
    """
    _reset_in_memory_state()

    port = 8141
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.25)
    base = f"http://127.0.0.1:{port}"

    try:
        # Stand up local SMS webhook capture and point platform at it.
        cap = _WebhookCapture()
        sms_srv, sms_url = _start_sms_webhook(cap)
        sms_srv.start()
        os.environ["SMS_WEBHOOK_URL"] = sms_url

        # Admin login + upload master conditions PDF (required for package PDF).
        admin_token = _login(base, "admin", "As11as11@")
        cond_pdf = _make_valid_pdf_bytes("MASTER CONDITIONS (TEST)")
        up = requests.post(
            base + "/api/admin/policy-terms/conditions/upload",
            files={"file": ("conditions.pdf", cond_pdf, "application/pdf")},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert up.status_code == 200, up.text

        # Register + login customer.
        email = "pipeline.tester@example.com"
        reg = requests.post(
            base + "/api/register",
            json={"email": email, "password": "As11as11@", "name": "Pipeline Tester", "phone": "+15550000001"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert reg.status_code in (200, 201), reg.text
        cust_token = _login(base, email, "As11as11@")

        # Submit quote (multipart).
        fields = {
            "email": email,
            "firstName": "Pipeline",
            "lastName": "Tester",
            "dob": "1990-01-01",
            "gender": "Male",
            "phone": "+15550000001",
            "address": "1 Test Street",
            "city": "Testville",
            "postalCode": "10001",
            "occupation": "Engineer",
            "nationalId": "A1234567",
            "healthCondition": "4",
            "height": "180",
            "weight": "80",
            "smoking": "NonSmoker",
            "preExisting": "no",
            "maritalStatus": "Single",
            "incomeRange": "50000-100000",
            "exercise": "3-4",
            "coverageAmount": "100000",
            "policyTerm": "15",
            "jurisdiction": "US",
            "savingsPercentage": "50",
            "operationalReinsuranceLoad": "50",
            "familyHistory": "none",
            "truthDeclaration": "on",
            "privacyConsent": "on",
            "termsAccept": "on",
            "signature": "Pipeline Tester",
            # Billing method on file (validated at submission time)
            "paymentMethod": "credit_card",
            "payerName": "Pipeline Tester",
            "billingCountry": "US",
            "billingPostal": "10001",
            "cardNetwork": "visa",
            "cardLast4": "4242",
        }
        submit = requests.post(
            base + "/api/submit-quote",
            data=fields,
            files={"mediaUpload": ("empty.txt", b"", "text/plain")},
            headers={"Authorization": f"Bearer {cust_token}"},
            timeout=30,
        )
        assert submit.status_code == 200, submit.text
        sj = submit.json()
        uw_id = sj["application_id"]
        policy_id = sj["policy_id"]

        # Approve underwriting (admin).
        appr = requests.post(
            base + "/api/underwriting/approve",
            json={"id": uw_id, "approved_by": "admin"},
            headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
            timeout=30,
        )
        assert appr.status_code == 200, appr.text
        aj = appr.json()
        assert aj.get("success") is True
        p = aj.get("policy") or {}

        # Policy + artifacts created.
        assert p.get("id") == policy_id
        assert str(p.get("status")).lower() in ("active", "in_force", "billing_review")
        assert p.get("issuance_id")
        assert p.get("nft_token")
        assert p.get("bill_id")
        assert p.get("billing_due_date")
        assert (p.get("billing_method") or (p.get("billing_profile") or {}).get("method"))
        assert p.get("policy_terms_url")
        assert p.get("policy_package_url")  # requires master conditions pdf
        assert p.get("policy_terms_csv_url")
        assert p.get("projection_pdf_token")
        assert p.get("projection_csv_token")

        # Customer receives notification in PHINS account.
        notifs = requests.get(
            base + "/api/notifications",
            headers={"Authorization": f"Bearer {cust_token}"},
            timeout=10,
        )
        assert notifs.status_code == 200, notifs.text
        nj = notifs.json()
        items = nj.get("items") or []
        assert any((n.get("kind") == "billing" and "approved" in str(n.get("subject") or "").lower()) for n in items)

        # SMS webhook should have been called for the approval notification.
        assert cap.event.wait(timeout=5.0), "Expected SMS webhook call, but none received"
        sms_payload = cap.last() or {}
        assert sms_payload.get("to") == "+15550000001"
        assert "PHINS.ai" in (sms_payload.get("message") or "") or "PHINS" in (sms_payload.get("message") or "")
        # Include policy artifact links in SMS payload (best-effort)
        assert "Policy terms" in (sms_payload.get("message") or "") or "policy" in (sms_payload.get("message") or "").lower()

        # Policy should be active now.
        pols = requests.get(
            base + "/api/policies?page=1&page_size=50",
            headers={"Authorization": f"Bearer {cust_token}"},
            timeout=10,
        )
        assert pols.status_code == 200, pols.text
        pj = pols.json()
        items = pj.get("items") or []
        pol = next((x for x in items if x.get("id") == policy_id), None)
        assert pol is not None
        assert str(pol.get("status")).lower() in ("active", "in_force", "billing_review")

        # File claim (customer). Must bind to issuance + nft token.
        cl = requests.post(
            base + "/api/claims/create",
            json={"policy_id": policy_id, "type": "disability", "claimed_amount": 1000, "description": "Test claim"},
            headers={"Authorization": f"Bearer {cust_token}", "Content-Type": "application/json"},
            timeout=10,
        )
        assert cl.status_code == 201, cl.text
        cj = cl.json()
        assert cj.get("policy_id") == policy_id
        assert cj.get("issuance_id") == pol.get("issuance_id")
        assert cj.get("nft_token") == pol.get("nft_token")
    finally:
        try:
            sms_srv.stop()
        except Exception:
            pass
        os.environ.pop("SMS_WEBHOOK_URL", None)
        srv.stop()

