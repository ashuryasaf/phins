from datetime import datetime, timedelta, timezone
import time

from services.notification_queue_service import NotificationQueueService, QueueItemStatus
from services.notification_service import (
    NotificationChannel,
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
)


class _FakeNotificationService:
    def __init__(self):
        self.requests = []

    def send(self, request: NotificationRequest) -> NotificationResult:
        self.requests.append(request)
        return NotificationResult(
            success=True,
            notification_id=f"NOTIF-{len(self.requests)}",
            status=NotificationStatus.DELIVERED,
            sent_at=datetime.now(timezone.utc),
        )


def test_enqueue_uses_request_send_at_for_scheduled_delivery():
    fake_service = _FakeNotificationService()
    queue = NotificationQueueService(fake_service, worker_count=1, auto_start=True)

    try:
        request = NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="customer@example.com",
            subject="Scheduled",
            content="Queued for later",
            send_at=datetime.now(timezone.utc) + timedelta(seconds=0.25),
        )

        item_id = queue.enqueue(request)

        initial_status = queue.get_status(item_id)
        assert initial_status is not None
        assert initial_status["status"] == QueueItemStatus.SCHEDULED.value
        assert initial_status["scheduled_at"] is not None
        assert fake_service.requests == []

        deadline = time.time() + 3
        while time.time() < deadline and not fake_service.requests:
            time.sleep(0.05)

        assert len(fake_service.requests) == 1
        final_status = queue.get_status(item_id)
        assert final_status is not None
        assert final_status["status"] == QueueItemStatus.COMPLETED.value
    finally:
        queue.stop(wait=True)


def test_enqueue_marks_request_expired_when_request_expiry_is_in_past():
    fake_service = _FakeNotificationService()
    queue = NotificationQueueService(fake_service, worker_count=1, auto_start=False)

    request = NotificationRequest(
        channel=NotificationChannel.EMAIL,
        recipient="customer@example.com",
        subject="Expired",
        content="Should not send",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    item_id = queue.enqueue(request)

    status = queue.get_status(item_id)
    assert status is not None
    assert status["status"] == QueueItemStatus.EXPIRED.value
    assert status["completed_at"] is not None
    assert fake_service.requests == []
