import base64
import json
import threading
import time
from http.server import HTTPServer

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
      submit application -> admin approve -> policy artifacts + billing link + notification
      accept terms -> pay -> policy becomes active
      file claim -> claim ties to issuance + nft token
    """
    _reset_in_memory_state()

    port = 8141
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.25)
    base = f"http://127.0.0.1:{port}"

    try:
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
            json={"email": email, "password": "As11as11@", "name": "Pipeline Tester"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert reg.status_code in (200, 201), reg.text
        cust_token = _login(base, email, "As11as11@")

        # Submit quote (multipart).
        fields = {
            "email": email,
            "password": "As11as11@",
            "name": "Pipeline Tester",
            "coverage_amount": "100000",
            "age": "35",
            "policy_type": "disability",
            "jurisdiction": "US",
            "health_condition_score": "4",
            "savings_percentage": "50",
            "operational_reinsurance_load": "50",
            "familyHistory": "none",
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
        assert str(p.get("status")).lower() in ("billing_pending", "billing_review")
        assert p.get("issuance_id")
        assert p.get("nft_token")
        assert p.get("billing_link_url")
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
        assert any((n.get("kind") == "billing" and p.get("billing_link_url") in (n.get("link") or "")) for n in items)

        # Billing link resolve
        # Extract token from billing_link_url like /billing-link.html?token=...
        token = p["billing_link_url"].split("token=", 1)[-1]
        bill = requests.get(base + f"/api/billing/link?token={token}", timeout=10)
        assert bill.status_code == 200, bill.text
        bj = bill.json()
        assert bj.get("valid") is True

        # Accept terms (signature)
        # 1x1 transparent png
        png = base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")
        sig = requests.post(
            base + "/api/billing/link/accept",
            json={"token": token, "signer_name": "Pipeline Tester", "signature_data_url": f"data:image/png;base64,{png}"},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        assert sig.status_code == 200, sig.text
        assert sig.json().get("success") is True

        # Pay now (provide billing details so validation stays low-risk)
        pay = requests.post(
            base + "/api/billing/link/pay",
            json={
                "token": token,
                "billing_details": {
                    "payer_name": "Pipeline Tester",
                    "billing_country": "US",
                    "billing_postal": "10001",
                    "payment_method": "card",
                    "card_last4": "4242",
                    "card_network": "visa",
                    "signer_name": "Pipeline Tester",
                },
            },
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert pay.status_code in (200, 202), pay.text

        # If it went to review, approve review as admin to activate.
        if pay.status_code == 202:
            # Find bill_id via resolve
            bill2 = requests.get(base + f"/api/billing/link?token={token}", timeout=10).json()
            bill_id = (bill2.get("bill") or {}).get("id")
            assert bill_id
            rv = requests.post(
                base + "/api/admin/billing/review/approve",
                json={"bill_id": bill_id},
                headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                timeout=20,
            )
            assert rv.status_code == 200, rv.text

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
        assert str(pol.get("status")).lower() in ("active", "in_force")

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
        srv.stop()

