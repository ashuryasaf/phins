"""
Tests for the Business Relations inquiry pipeline.

Covers:
  * public intake: POST /api/business/inquiries (contact + demo requests from
    the public solutions/intro page) — validation, sanitization, idempotency
  * admin review: GET /api/admin/business-inquiries (role-gated list w/ filters)
  * admin triage: POST /api/admin/business-inquiries/<id>/status (status
    history integrity)
"""

import json
import os

from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal


BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _post(path, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _login(username, password):
    body, status = _post("/api/login", {"username": username, "password": password})
    assert status == 200, f"login failed for {username}: {body}"
    return body["token"], body.get("role")


def _valid_payload(**overrides):
    payload = {
        "inquiry_type": "demo",
        "name": "Dana Levi",
        "email": "dana.levi@example.com",
        "organization": "Example Health Group",
        "audience": "enterprise",
        "interest": "underwriting",
        "message": "We would like a walkthrough of the underwriting workbench.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# public intake
# ---------------------------------------------------------------------------
def test_public_inquiry_submission_success():
    body, status = _post("/api/business/inquiries", _valid_payload())
    assert status == 200, body
    assert body["success"] is True
    inquiry = body["inquiry"]
    assert inquiry["id"].startswith("BRI-")
    assert inquiry["status"] == "new"
    assert inquiry["created_at"]
    # The public response must stay minimal: no echo of message/email.
    assert "email" not in inquiry
    assert "message" not in inquiry

    # Stored record holds the full validated submission with a history trail.
    record = portal.BUSINESS_INQUIRIES[inquiry["id"]]
    assert record["email"] == "dana.levi@example.com"
    assert record["audience"] == "enterprise"
    assert record["interest"] == "underwriting"
    assert record["status_history"][0]["status"] == "new"
    assert record["status_history"][0]["changed_by"] == "public_form"


def test_public_inquiry_requires_name_and_valid_email():
    body, status = _post("/api/business/inquiries", _valid_payload(name=""))
    assert status == 400 and "error" in body

    body, status = _post("/api/business/inquiries", _valid_payload(email="not-an-email"))
    assert status == 400 and "error" in body


def test_public_inquiry_rejects_unknown_enums():
    body, status = _post("/api/business/inquiries", _valid_payload(inquiry_type="spam"))
    assert status == 400 and "inquiry_type" in body["error"]

    body, status = _post("/api/business/inquiries", _valid_payload(audience="alien"))
    assert status == 400 and "audience" in body["error"]

    body, status = _post("/api/business/inquiries", _valid_payload(interest="secrets"))
    assert status == 400 and "interest" in body["error"]


def test_public_inquiry_sanitizes_html_input():
    body, status = _post(
        "/api/business/inquiries",
        _valid_payload(name="Dana <script>alert(1)</script>", message="hello <b>world</b>"),
    )
    assert status == 200, body
    record = portal.BUSINESS_INQUIRIES[body["inquiry"]["id"]]
    assert "<" not in record["name"] and ">" not in record["name"]
    assert "<" not in record["message"] and ">" not in record["message"]


def test_public_inquiry_duplicate_open_request_is_idempotent():
    first, status = _post("/api/business/inquiries", _valid_payload())
    assert status == 200

    second, status = _post("/api/business/inquiries", _valid_payload(message="Second ping"))
    assert status == 200
    assert second.get("duplicate") is True
    assert second["inquiry"]["id"] == first["inquiry"]["id"]
    assert len(portal.BUSINESS_INQUIRIES) == 1

    # A different interest area is a genuinely new inquiry.
    third, status = _post("/api/business/inquiries", _valid_payload(interest="claims"))
    assert status == 200
    assert third.get("duplicate") is None
    assert third["inquiry"]["id"] != first["inquiry"]["id"]
    assert len(portal.BUSINESS_INQUIRIES) == 2


# ---------------------------------------------------------------------------
# admin review + triage
# ---------------------------------------------------------------------------
def test_admin_list_requires_admin_role():
    _, status = _get("/api/admin/business-inquiries")
    assert status == 403

    underwriter_token, _ = _login("underwriter", "under123")
    _, status = _get("/api/admin/business-inquiries", token=underwriter_token)
    assert status == 403


def test_admin_list_returns_inquiries_with_filters():
    _post("/api/business/inquiries", _valid_payload())
    _post(
        "/api/business/inquiries",
        _valid_payload(
            inquiry_type="contact",
            email="joe@example.org",
            name="Joe Broker",
            audience="partner",
            interest="mga_solutions",
        ),
    )

    admin_token, _ = _login("admin", "admin123")
    body, status = _get("/api/admin/business-inquiries", token=admin_token)
    assert status == 200
    assert body["total"] == 2
    assert body["new_count"] == 2
    assert {i["interest"] for i in body["items"]} == {"underwriting", "mga_solutions"}

    body, status = _get(
        "/api/admin/business-inquiries?audience=partner&inquiry_type=contact",
        token=admin_token,
    )
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["email"] == "joe@example.org"

    body, status = _get("/api/admin/business-inquiries?search=dana", token=admin_token)
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Dana Levi"


def test_admin_status_update_flow_keeps_history():
    created, _ = _post("/api/business/inquiries", _valid_payload())
    inquiry_id = created["inquiry"]["id"]

    admin_token, _ = _login("admin", "admin123")

    # invalid status rejected
    body, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "vanished"},
        token=admin_token,
    )
    assert status == 400 and "status" in body["error"]

    # unknown inquiry -> 404
    _, status = _post(
        "/api/admin/business-inquiries/BRI-000000-DEADBEEF/status",
        {"status": "contacted"},
        token=admin_token,
    )
    assert status == 404

    # non-admin cannot triage
    _, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "contacted"},
    )
    assert status == 403

    body, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "contacted", "note": "Intro call scheduled"},
        token=admin_token,
    )
    assert status == 200
    assert body["inquiry"]["status"] == "contacted"
    history = body["inquiry"]["status_history"]
    assert [h["status"] for h in history] == ["new", "contacted"]
    assert history[-1]["changed_by"] == "admin"
    assert history[-1]["note"] == "Intro call scheduled"

    # once contacted, a new submission with the same email/interest is a new record
    again, status = _post("/api/business/inquiries", _valid_payload())
    assert status == 200
    assert again.get("duplicate") is None
    assert again["inquiry"]["id"] != inquiry_id


# ---------------------------------------------------------------------------
# Durability + cross-instance consistency (DB mode)
# ---------------------------------------------------------------------------
def test_db_mode_inquiry_survives_restart(monkeypatch):
    """Send Inquiry / Request Demo records must survive an in-memory wipe."""
    from database import init_database
    from database.manager import DatabaseManager

    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    init_database()
    portal.BUSINESS_INQUIRIES.clear()
    portal._BUSINESS_INQUIRY_LAST_HYDRATE = 0.0

    body, status = _post(
        "/api/business/inquiries",
        _valid_payload(
            inquiry_type="demo",
            email="durable.demo@example.com",
            interest="billing",
            name="Durable Demo",
        ),
    )
    assert status == 200, body
    inquiry_id = body["inquiry"]["id"]

    # Confirm write-through landed in the durable table.
    with DatabaseManager() as db:
        row = db.business_inquiries.get_by_id(inquiry_id)
        assert row is not None
        assert row.inquiry_type == "demo"
        assert row.email == "durable.demo@example.com"
        assert row.status == "new"

    # Simulate restart: wipe only the per-instance cache.
    portal.BUSINESS_INQUIRIES.clear()
    portal._BUSINESS_INQUIRY_LAST_HYDRATE = 0.0

    admin_token, _ = _login("admin", "admin123")
    listed, status = _get("/api/admin/business-inquiries", token=admin_token)
    assert status == 200
    match = [i for i in listed["items"] if i["id"] == inquiry_id]
    assert len(match) == 1
    assert match[0]["email"] == "durable.demo@example.com"
    assert match[0]["interest"] == "billing"
    assert match[0]["status_history"][0]["status"] == "new"


def test_db_mode_inquiry_cross_instance_visibility(monkeypatch):
    """A peer instance's durable write must appear on admin after refresh-on-read."""
    from database import init_database
    from database.manager import DatabaseManager

    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    init_database()
    portal.BUSINESS_INQUIRIES.clear()
    portal._BUSINESS_INQUIRY_LAST_HYDRATE = 0.0

    peer_id = "BRI-209901-PEER0001"
    with DatabaseManager() as db:
        ok = db.business_inquiries.upsert_from_dict(peer_id, {
            "id": peer_id,
            "inquiry_type": "contact",
            "name": "Peer Writer",
            "email": "peer@example.com",
            "organization": "Peer Co",
            "audience": "partner",
            "interest": "mga_solutions",
            "message": "Written by another instance",
            "status": "new",
            "created_at": "2099-01-01T00:00:00",
            "updated_at": "2099-01-01T00:00:00",
            "status_history": [
                {"status": "new", "changed_at": "2099-01-01T00:00:00", "changed_by": "public_form"},
            ],
        })
        assert ok is True

    admin_token, _ = _login("admin", "admin123")
    listed, status = _get("/api/admin/business-inquiries", token=admin_token)
    assert status == 200
    match = [i for i in listed["items"] if i["id"] == peer_id]
    assert len(match) == 1
    assert match[0]["name"] == "Peer Writer"

    # Peer status change must also become visible after forced refresh.
    with DatabaseManager() as db:
        db.business_inquiries.upsert_from_dict(peer_id, {
            **match[0],
            "status": "contacted",
            "updated_at": "2099-01-01T01:00:00",
            "status_history": match[0]["status_history"] + [
                {"status": "contacted", "changed_at": "2099-01-01T01:00:00", "changed_by": "peer-admin"},
            ],
        })

    portal._BUSINESS_INQUIRY_LAST_HYDRATE = 0.0
    listed, status = _get(
        "/api/admin/business-inquiries?status=contacted",
        token=admin_token,
    )
    assert status == 200
    match = [i for i in listed["items"] if i["id"] == peer_id]
    assert len(match) == 1
    assert match[0]["status"] == "contacted"


def test_db_mode_status_update_persists(monkeypatch):
    """Admin triage status changes must write through and reload after cache wipe."""
    from database import init_database
    from database.manager import DatabaseManager

    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    init_database()
    portal.BUSINESS_INQUIRIES.clear()
    portal._BUSINESS_INQUIRY_LAST_HYDRATE = 0.0

    created, status = _post(
        "/api/business/inquiries",
        _valid_payload(
            inquiry_type="contact",
            email="triage.persist@example.com",
            interest="claims",
            name="Triage Persist",
        ),
    )
    assert status == 200, created
    inquiry_id = created["inquiry"]["id"]

    admin_token, _ = _login("admin", "admin123")
    body, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "qualified", "note": "Ready for follow-up"},
        token=admin_token,
    )
    assert status == 200, body
    assert body["inquiry"]["status"] == "qualified"

    portal.BUSINESS_INQUIRIES.clear()
    portal._BUSINESS_INQUIRY_LAST_HYDRATE = 0.0

    with DatabaseManager() as db:
        row = db.business_inquiries.get_by_id(inquiry_id)
        assert row is not None
        assert row.status == "qualified"
        history = row.to_dict()["status_history"]
        assert [h["status"] for h in history] == ["new", "qualified"]
        assert history[-1]["note"] == "Ready for follow-up"

    listed, status = _get("/api/admin/business-inquiries", token=admin_token)
    assert status == 200
    match = [i for i in listed["items"] if i["id"] == inquiry_id]
    assert len(match) == 1
    assert match[0]["status"] == "qualified"


# ---------------------------------------------------------------------------
# Admin email alerts on new inquiry / demo request
# ---------------------------------------------------------------------------
def test_admin_email_sent_with_full_inquiry_details(monkeypatch):
    """New non-duplicate inquiries must email configured admins with all fields."""
    captured = []

    class _FakeResult:
        success = True
        error_message = None

        def to_dict(self):
            return {"success": True}

    class _FakeNotificationService:
        def send(self, request):
            captured.append(request)
            return _FakeResult()

    monkeypatch.setenv("PHINS_BUSINESS_INQUIRY_NOTIFY_EMAILS", "ops@phins.ai,relations@phins.ai")
    monkeypatch.setattr(
        portal,
        "_resolve_business_inquiry_notify_emails",
        lambda: ["ops@phins.ai", "relations@phins.ai"],
    )
    monkeypatch.setattr(
        "services.notification_service.get_notification_service",
        lambda: _FakeNotificationService(),
    )

    body, status = _post(
        "/api/business/inquiries",
        _valid_payload(
            inquiry_type="demo",
            email="alert.demo@example.com",
            name="Alert Demo",
            organization="Alert Org",
            audience="investor",
            interest="actuarial_investments",
            message="Please schedule a platform demo for our investment committee.",
        ),
    )
    assert status == 200, body
    assert body.get("duplicate") is None
    inquiry_id = body["inquiry"]["id"]

    # 2 admin alerts + 1 sender welcome/confirmation
    assert len(captured) == 3, f"expected 3 emails, got {len(captured)}"
    recipients = {req.recipient for req in captured}
    assert recipients == {"ops@phins.ai", "relations@phins.ai", "alert.demo@example.com"}

    admin_mails = [
        req for req in captured
        if req.metadata.get("event") == "inquiry_received"
    ]
    assert len(admin_mails) == 2
    sample = admin_mails[0]
    assert "Business Relations" in sample.subject
    assert inquiry_id in sample.subject
    assert "Alert Demo" in sample.content
    assert "alert.demo@example.com" in sample.content
    assert "Alert Org" in sample.content
    assert "investor" in sample.content
    assert "actuarial_investments" in sample.content
    assert "investment committee" in sample.content
    assert sample.html_content and inquiry_id in sample.html_content
    assert sample.metadata.get("category") == "business_inquiry"
    assert sample.metadata.get("inquiry_id") == inquiry_id
    assert sample.metadata.get("inquiry_type") == "demo"

    sender_mails = [
        req for req in captured
        if req.metadata.get("event") == "inquiry_sender_confirmation"
    ]
    assert len(sender_mails) == 1
    sender = sender_mails[0]
    assert sender.recipient == "alert.demo@example.com"
    assert "confirmation" in sender.subject.lower()
    assert inquiry_id in sender.subject
    assert "Welcome" in sender.html_content or "welcome" in sender.content.lower()
    assert "Alert Demo" in sender.content
    assert "Alert Org" in sender.content
    assert "Actuarial & Investments" in sender.content
    assert "investment committee" in sender.content
    assert sender.metadata.get("inquiry_id") == inquiry_id


def test_admin_email_not_sent_on_duplicate_inquiry(monkeypatch):
    """Idempotent duplicates must not re-spam admins."""
    calls = {"count": 0}

    def _spy(record):
        calls["count"] += 1
        return {
            "attempted": True,
            "sent": ["ops@phins.ai"],
            "failed": [],
            "recipients": ["ops@phins.ai"],
        }

    monkeypatch.setattr(portal, "_notify_business_inquiry_received", _spy)

    first, status = _post(
        "/api/business/inquiries",
        _valid_payload(email="dup.alert@example.com", interest="platform"),
    )
    assert status == 200
    assert first.get("duplicate") is None
    assert calls["count"] == 1

    second, status = _post(
        "/api/business/inquiries",
        _valid_payload(
            email="dup.alert@example.com",
            interest="platform",
            message="ping again",
        ),
    )
    assert status == 200
    assert second.get("duplicate") is True
    assert calls["count"] == 1


def test_resolve_business_inquiry_notify_emails_from_env(monkeypatch):
    monkeypatch.setenv(
        "PHINS_BUSINESS_INQUIRY_NOTIFY_EMAILS",
        " Alpha@Phins.ai , bad-address, beta@phins.ai, alpha@phins.ai ",
    )
    emails = portal._resolve_business_inquiry_notify_emails()
    assert emails == ["alpha@phins.ai", "beta@phins.ai"]


def test_format_business_inquiry_admin_email_escapes_html():
    subject, content, html = portal._format_business_inquiry_admin_email({
        "id": "BRI-209901-SAFE0001",
        "inquiry_type": "contact",
        "name": "Eve <script>",
        "email": "eve@example.com",
        "organization": "Org & Co",
        "audience": "partner",
        "interest": "claims",
        "message": "Hello <b>world</b>",
        "status": "new",
        "created_at": "2099-01-01T00:00:00",
    })
    assert "BRI-209901-SAFE0001" in subject
    assert "Eve <script>" in content
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Org &amp; Co" in html
    assert "&lt;b&gt;world&lt;/b&gt;" in html


def test_format_sender_confirmation_includes_welcome_and_details():
    subject, content, html = portal._format_business_inquiry_sender_confirmation_email({
        "id": "BRI-209901-WELCOME1",
        "inquiry_type": "demo",
        "name": "Dana Levi",
        "email": "dana@example.com",
        "organization": "Example Health",
        "audience": "enterprise",
        "interest": "underwriting",
        "message": "Looking forward to a walkthrough.",
        "status": "new",
        "created_at": "2099-01-01T12:00:00",
    })
    assert "confirmation" in subject.lower()
    assert "BRI-209901-WELCOME1" in subject
    assert "Hello Dana Levi" in content
    assert "Welcome" in html
    assert "Enterprise" in content
    assert "Underwriting" in content
    assert "Looking forward to a walkthrough." in content
    assert "dana@example.com" in content
    assert "Example Health" in html


def test_sender_confirmation_still_sent_without_admin_recipients(monkeypatch):
    """Visitor confirmation must not depend on admin notify env being set."""
    captured = []

    class _FakeResult:
        success = True
        error_message = None

    class _FakeNotificationService:
        def send(self, request):
            captured.append(request)
            return _FakeResult()

    monkeypatch.setattr(portal, "_resolve_business_inquiry_notify_emails", lambda: [])
    monkeypatch.setattr(
        "services.notification_service.get_notification_service",
        lambda: _FakeNotificationService(),
    )

    body, status = _post(
        "/api/business/inquiries",
        _valid_payload(
            email="visitor.only@example.com",
            name="Visitor Only",
            interest="billing",
            inquiry_type="contact",
        ),
    )
    assert status == 200, body
    assert len(captured) == 1
    assert captured[0].recipient == "visitor.only@example.com"
    assert captured[0].metadata.get("event") == "inquiry_sender_confirmation"


def test_db_mode_persist_failure_rejects_public_submission(monkeypatch):
    """When DB is the durable store, a failed write must not claim success."""
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    monkeypatch.setattr(portal, "_persist_business_inquiry", lambda *_a, **_k: False)
    monkeypatch.setattr(portal, "_hydrate_business_inquiries", lambda force=False: None)

    before = len(portal.BUSINESS_INQUIRIES)
    body, status = _post(
        "/api/business/inquiries",
        _valid_payload(email="fail.persist@example.com", interest="smart_contracts"),
    )
    assert status == 503
    assert "error" in body
    assert len(portal.BUSINESS_INQUIRIES) == before


def test_business_inquiry_notify_limiter_caps_ip_and_mailbox(monkeypatch):
    monkeypatch.setenv("PHINS_BUSINESS_INQUIRY_NOTIFY_MAX_PER_IP", "1")
    monkeypatch.setenv("PHINS_BUSINESS_INQUIRY_NOTIFY_MAX_PER_MAILBOX", "1")
    monkeypatch.setenv("PHINS_BUSINESS_INQUIRY_NOTIFY_WINDOW_SECONDS", "600")
    portal.reset_business_inquiry_notify_hits()
    assert portal.business_inquiry_notify_allowed("ip", "203.0.113.9") is True
    assert portal.business_inquiry_notify_allowed("ip", "203.0.113.9") is False
    assert portal.business_inquiry_notify_allowed("mailbox", "once@example.com") is True
    assert portal.business_inquiry_notify_allowed("mailbox", "once@example.com") is False
    assert portal.business_inquiry_notify_allowed("mailbox", "other@example.com") is True


def test_inquiry_notify_skips_mail_when_source_ip_limited(monkeypatch):
    captured = []

    class _FakeResult:
        success = True
        error_message = None

    class _FakeNotificationService:
        def send(self, request):
            captured.append(request)
            return _FakeResult()

    monkeypatch.setenv("PHINS_BUSINESS_INQUIRY_NOTIFY_MAX_PER_IP", "1")
    monkeypatch.setenv("PHINS_BUSINESS_INQUIRY_NOTIFY_MAX_PER_MAILBOX", "200")
    portal.reset_business_inquiry_notify_hits()
    monkeypatch.setattr(
        portal,
        "_resolve_business_inquiry_notify_emails",
        lambda: ["ops@phins.ai"],
    )
    monkeypatch.setattr(
        "services.notification_service.get_notification_service",
        lambda: _FakeNotificationService(),
    )

    record = {
        "id": "BRI-209901-RATELIM1",
        "inquiry_type": "contact",
        "name": "Rate Limit",
        "email": "rate.limit@example.com",
        "organization": "Org",
        "audience": "other",
        "interest": "platform",
        "message": "hello",
        "status": "new",
        "created_at": "2099-01-01T00:00:00",
        "_source_ip": "198.51.100.20",
    }
    first = portal._notify_business_inquiry_received(dict(record))
    assert first.get("skipped") is None
    assert first.get("sender_confirmation", {}).get("sent") is True
    first_count = len(captured)
    assert first_count >= 1

    second = portal._notify_business_inquiry_received(
        dict(record, id="BRI-209901-RATELIM2")
    )
    assert second.get("skipped") == "source_rate_limited"
    assert len(captured) == first_count
