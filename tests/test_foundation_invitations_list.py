import web_portal.api_extensions as api_extensions
import web_portal.server as portal


class _FakeFoundationService:
    def __init__(self):
        self.requested_emails = []

    def get_pending_invitations(self, email):
        self.requested_emails.append(email)
        return [{"id": "INV-1", "invited_email": email}]


def test_handle_foundation_invitations_list_uses_session_email(monkeypatch):
    monkeypatch.setattr(api_extensions, "FOUNDATION_SERVICE_AVAILABLE", True)
    service = _FakeFoundationService()
    monkeypatch.setattr(api_extensions, "get_foundation_service", lambda: service)

    status, payload = api_extensions.handle_foundation_invitations_list(
        {"email": "member@example.com"}
    )

    assert status == 200
    assert service.requested_emails == ["member@example.com"]
    assert payload["total"] == 1
    assert payload["items"][0]["invited_email"] == "member@example.com"


def test_handle_foundation_invitations_list_falls_back_to_customers(monkeypatch):
    monkeypatch.setattr(api_extensions, "FOUNDATION_SERVICE_AVAILABLE", True)
    service = _FakeFoundationService()
    monkeypatch.setattr(api_extensions, "get_foundation_service", lambda: service)

    portal.CUSTOMERS["CUST-FOUNDATION-1"] = {"email": "customer@example.com"}

    status, payload = api_extensions.handle_foundation_invitations_list(
        {"customer_id": "CUST-FOUNDATION-1"}
    )

    assert status == 200
    assert service.requested_emails == ["customer@example.com"]
    assert payload["items"][0]["invited_email"] == "customer@example.com"


def test_handle_foundation_invitations_list_falls_back_to_registered_customers(monkeypatch):
    monkeypatch.setattr(api_extensions, "FOUNDATION_SERVICE_AVAILABLE", True)
    service = _FakeFoundationService()
    monkeypatch.setattr(api_extensions, "get_foundation_service", lambda: service)

    portal.REGISTERED_CUSTOMERS["CUST-FOUNDATION-2"] = {
        "email": "registered@example.com"
    }

    status, payload = api_extensions.handle_foundation_invitations_list(
        {"customer_id": "CUST-FOUNDATION-2"}
    )

    assert status == 200
    assert service.requested_emails == ["registered@example.com"]
    assert payload["items"][0]["invited_email"] == "registered@example.com"
