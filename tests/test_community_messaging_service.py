import pytest

from services.community_messaging_service import CommunityMessagingService
from services.notification_service import (
    MockEmailProvider,
    create_notification_service,
    get_notification_service,
    reset_global_rate_limiter,
    reset_notification_service,
)


class _StubFoundationService:
    def __init__(self):
        self._members = [
            {
                "id": "MEM-1",
                "foundation_id": "FND-001",
                "member_id": "user-founder",
                "display_name": "Founder User",
                "role": "founder",
                "status": "active",
                "email": "founder@example.com",
            },
            {
                "id": "MEM-2",
                "foundation_id": "FND-001",
                "member_id": "user-member",
                "display_name": "Member User",
                "role": "member",
                "status": "active",
                "email": "member@example.com",
            },
            {
                "id": "MEM-3",
                "foundation_id": "FND-001",
                "member_id": "user-pending",
                "display_name": "Pending User",
                "role": "member",
                "status": "pending",
                "email": "pending@example.com",
            },
        ]

    def _get_member_by_user(self, foundation_id: str, user_id: str):
        for member in self._members:
            if member["foundation_id"] == foundation_id and member["member_id"] == user_id:
                return member
        return None

    def get_foundation_members(self, foundation_id: str, include_pending: bool = False):
        items = [m for m in self._members if m["foundation_id"] == foundation_id]
        if include_pending:
            return items
        return [m for m in items if m["status"] == "active"]


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    reset_global_rate_limiter()
    reset_notification_service()
    yield
    reset_global_rate_limiter()
    reset_notification_service()


@pytest.fixture
def messaging_service():
    foundation_service = _StubFoundationService()
    notification_service = create_notification_service(use_mock=True)
    service = CommunityMessagingService(
        foundation_service=foundation_service,
        notification_service=notification_service,
    )
    return service, notification_service


def test_create_thread_and_notify_other_members(messaging_service):
    service, notification_service = messaging_service

    result = service.create_thread(
        foundation_id="FND-001",
        sender_user_id="user-founder",
        title="Premium billing cadence",
        message="Let's align billing reminders with monthly cycles.",
        tags=["Billing", "MONTHLY", "billing"],
        notify_members=True,
    )

    assert result["success"] is True
    thread = result["thread"]
    message = result["message"]
    assert thread["status"] == "open"
    assert thread["message_count"] == 1
    assert thread["participants"] == ["user-founder"]
    assert thread["tags"] == ["billing", "monthly"]
    assert message["content"] == "Let's align billing reminders with monthly cycles."

    sent_emails = notification_service._email_provider.sent_emails
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == "member@example.com"
    assert "New community thread" in sent_emails[0]["subject"]


def test_reply_and_close_permission_flow(messaging_service):
    service, _ = messaging_service

    created = service.create_thread(
        foundation_id="FND-001",
        sender_user_id="user-founder",
        title="Coverage discussion",
        message="Opening discussion about coverage mix.",
        notify_members=False,
    )
    assert created["success"] is True
    thread_id = created["thread"]["thread_id"]

    reply = service.post_reply(
        foundation_id="FND-001",
        thread_id=thread_id,
        sender_user_id="user-member",
        content="I suggest we review life + health allocations.",
        notify_members=False,
    )
    assert reply["success"] is True
    assert reply["message"]["sender_user_id"] == "user-member"

    thread_snapshot = service.get_thread(
        foundation_id="FND-001",
        user_id="user-founder",
        thread_id=thread_id,
    )
    assert thread_snapshot["success"] is True
    assert thread_snapshot["thread"]["message_count"] == 2
    assert thread_snapshot["thread"]["participants"] == ["user-founder", "user-member"]
    assert thread_snapshot["count"] == 2

    forbidden_close = service.close_thread(
        foundation_id="FND-001",
        thread_id=thread_id,
        actor_user_id="user-member",
    )
    assert forbidden_close["success"] is False
    assert forbidden_close["error_code"] == "FORBIDDEN"

    allowed_close = service.close_thread(
        foundation_id="FND-001",
        thread_id=thread_id,
        actor_user_id="user-founder",
    )
    assert allowed_close["success"] is True
    assert allowed_close["thread"]["status"] == "closed"

    post_after_close = service.post_reply(
        foundation_id="FND-001",
        thread_id=thread_id,
        sender_user_id="user-member",
        content="This should not be accepted.",
        notify_members=False,
    )
    assert post_after_close["success"] is False
    assert post_after_close["error_code"] == "THREAD_CLOSED"


def test_non_member_access_is_rejected(messaging_service):
    service, _ = messaging_service

    create_result = service.create_thread(
        foundation_id="FND-001",
        sender_user_id="outsider",
        title="Unauthorized",
        message="This should fail.",
    )
    assert create_result["success"] is False
    assert create_result["error_code"] == "UNAUTHORIZED"

    list_result = service.list_threads(
        foundation_id="FND-001",
        user_id="outsider",
    )
    assert list_result["success"] is False
    assert list_result["error_code"] == "UNAUTHORIZED"


def test_default_service_uses_shared_notification_runtime(monkeypatch):
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    monkeypatch.delenv("PHINS_USE_MOCK_NOTIFICATIONS", raising=False)

    service = CommunityMessagingService(
        foundation_service=_StubFoundationService(),
        notification_service=None,
    )

    assert service._notification_service is get_notification_service()
    assert not isinstance(service._notification_service._email_provider, MockEmailProvider)
