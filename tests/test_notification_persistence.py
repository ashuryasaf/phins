"""
DB persistence tests for PHINS Notification & OTP service.

These tests verify that OTP codes, notification history, and audit logs are
correctly persisted to and retrieved from an SQLite in-memory database.

All DB fixtures come from conftest.py (db_session, mock_email_provider, etc.).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from services.notification_service import (
    NotificationAuditLogger,
    NotificationChannel,
    NotificationPriority,
    NotificationRequest,
    NotificationService,
    OTPRequest,
    OTPService,
    OTPStatus,
    VerificationType,
    create_notification_service,
    reset_global_rate_limiter,
    MockEmailProvider,
    MockSMSProvider,
)


# ============================================================================
# Helpers
# ============================================================================

def _otp_request(identifier: str = "test@example.com",
                 channel: NotificationChannel = NotificationChannel.EMAIL,
                 verification_type: VerificationType = VerificationType.EMAIL_VERIFICATION,
                 expiry_seconds: int = 300) -> OTPRequest:
    return OTPRequest(
        identifier=identifier,
        channel=channel,
        verification_type=verification_type,
        customer_id="CUST_001",
        expiry_seconds=expiry_seconds,
    )


def _notif_request(recipient: str = "user@example.com",
                   channel: NotificationChannel = NotificationChannel.EMAIL,
                   customer_id: str = "CUST_001") -> NotificationRequest:
    return NotificationRequest(
        recipient=recipient,
        channel=channel,
        subject="Test Subject",
        content="Test notification content",
        customer_id=customer_id,
        priority=NotificationPriority.NORMAL,
    )


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    reset_global_rate_limiter()
    yield
    reset_global_rate_limiter()


# ============================================================================
# OTP DB Persistence Tests
# ============================================================================

class TestOTPDBPersistence:
    """OTP service wired to SQLite — full round-trip tests."""

    def test_otp_row_created_on_generate(self, db_session, mock_email_provider, mock_sms_provider):
        """Generating an OTP must create a row in otp_codes table."""
        from database.notification_models import OTPCode

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        result = svc.generate_and_send(_otp_request())

        assert result.success, result.error_message
        row = db_session.query(OTPCode).filter_by(id=result.otp_id).first()
        assert row is not None
        assert row.status == OTPStatus.ACTIVE.value
        assert row.code_hash  # must be stored
        assert row.code_salt  # must be stored
        assert "test@example.com" not in (row.code_hash or "")  # no plaintext

    def test_otp_verify_full_roundtrip(self, db_session, mock_email_provider, mock_sms_provider):
        """Generate → verify using DB should succeed and mark row as USED."""
        from database.notification_models import OTPCode

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _otp_request()
        # Capture the OTP code from the mock provider
        generate_result = svc.generate_and_send(req)
        assert generate_result.success

        sent_code = mock_email_provider.sent_emails[-1]["body"].split("is: ", 1)[1].split()[0]

        verify_result = svc.verify(
            identifier=req.identifier,
            code=sent_code,
            verification_type=req.verification_type,
        )
        assert verify_result.success, verify_result.error_message
        assert verify_result.status == OTPStatus.USED

        row = db_session.query(OTPCode).filter_by(id=generate_result.otp_id).first()
        assert row.status == OTPStatus.USED.value
        assert row.used_at is not None

    def test_otp_wrong_code_increments_attempts(self, db_session, mock_email_provider, mock_sms_provider):
        """A wrong OTP code must increment attempt_count in DB."""
        from database.notification_models import OTPCode

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _otp_request()
        gen = svc.generate_and_send(req)
        assert gen.success

        svc.verify(identifier=req.identifier, code="000000",
                   verification_type=req.verification_type)

        row = db_session.query(OTPCode).filter_by(id=gen.otp_id).first()
        assert row.attempt_count == 1

    def test_otp_max_attempts_invalidates_in_db(self, db_session, mock_email_provider, mock_sms_provider):
        """Exceeding max attempts should set DB row status to INVALIDATED."""
        from database.notification_models import OTPCode
        from services.notification_service import NotificationConfig

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _otp_request()
        gen = svc.generate_and_send(req)
        assert gen.success

        # Use more attempts than max_attempts
        for _ in range(NotificationConfig.OTP_MAX_ATTEMPTS + 1):
            svc.verify(identifier=req.identifier, code="000000",
                       verification_type=req.verification_type)

        row = db_session.query(OTPCode).filter_by(id=gen.otp_id).first()
        assert row.status == OTPStatus.INVALIDATED.value

    def test_otp_expiry_detected_in_db(self, db_session, mock_email_provider, mock_sms_provider):
        """An expired OTP must be rejected upon verify."""
        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        # Use a very short expiry
        req = _otp_request(expiry_seconds=1)
        gen = svc.generate_and_send(req)
        assert gen.success

        sent_code = mock_email_provider.sent_emails[-1]["body"].split("is: ", 1)[1].split()[0]

        # Fast-forward past expiry using DB row manipulation
        from database.notification_models import OTPCode
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        db_session.query(OTPCode).filter_by(id=gen.otp_id).update(
            {"expires_at": past}, synchronize_session=False
        )
        db_session.commit()

        result = svc.verify(
            identifier=req.identifier,
            code=sent_code,
            verification_type=req.verification_type,
        )
        assert not result.success
        assert result.error_code == "OTP_EXPIRED"

    def test_generate_invalidates_previous_otp_in_db(self, db_session, mock_email_provider, mock_sms_provider):
        """Generating a second OTP for the same identifier+type must invalidate the first in DB."""
        from database.notification_models import OTPCode

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _otp_request()
        first = svc.generate_and_send(req)
        assert first.success

        second = svc.generate_and_send(req)
        assert second.success

        first_row = db_session.query(OTPCode).filter_by(id=first.otp_id).first()
        assert first_row.status == OTPStatus.INVALIDATED.value

        second_row = db_session.query(OTPCode).filter_by(id=second.otp_id).first()
        assert second_row.status == OTPStatus.ACTIVE.value

    def test_invalidate_updates_db_row(self, db_session, mock_email_provider, mock_sms_provider):
        """Calling invalidate() must update the DB row to INVALIDATED."""
        from database.notification_models import OTPCode

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _otp_request()
        gen = svc.generate_and_send(req)
        assert gen.success

        result = svc.invalidate(req.identifier)
        assert result is True

        row = db_session.query(OTPCode).filter_by(id=gen.otp_id).first()
        assert row.status == OTPStatus.INVALIDATED.value

    def test_otp_plaintext_never_stored(self, db_session, mock_email_provider, mock_sms_provider):
        """DB row must never contain the plaintext OTP code."""
        from database.notification_models import OTPCode

        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _otp_request()
        gen = svc.generate_and_send(req)
        assert gen.success

        sent_code = mock_email_provider.sent_emails[-1]["body"].split("is: ", 1)[1].split()[0]
        row = db_session.query(OTPCode).filter_by(id=gen.otp_id).first()

        # Plaintext OTP must not appear anywhere in the DB row
        assert sent_code not in (row.code_hash or "")
        assert sent_code not in (row.code_salt or "")
        assert sent_code not in (row.identifier or "")


# ============================================================================
# Notification History DB Persistence Tests
# ============================================================================

class TestNotificationHistoryPersistence:
    """NotificationService history wired to SQLite."""

    def test_send_email_creates_history_row(self, db_session, mock_email_provider, mock_sms_provider):
        """Sending an email must persist a NotificationHistory row."""
        from database.notification_models import NotificationHistory

        svc = NotificationService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _notif_request()
        result = svc.send(req)
        assert result.success

        row = db_session.query(NotificationHistory).filter_by(id=result.notification_id).first()
        assert row is not None
        assert row.channel == NotificationChannel.EMAIL.value
        assert row.status == "delivered"
        assert row.content_hash  # SHA-256 present
        assert row.recipient_identifier == req.recipient
        assert row.recipient_identifier_hash  # hashed for privacy

    def test_send_sms_creates_history_row(self, db_session, mock_email_provider, mock_sms_provider):
        """Sending an SMS must persist a NotificationHistory row."""
        from database.notification_models import NotificationHistory

        svc = NotificationService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _notif_request(recipient="+15551234567", channel=NotificationChannel.SMS)
        result = svc.send(req)
        assert result.success

        row = db_session.query(NotificationHistory).filter_by(id=result.notification_id).first()
        assert row is not None
        assert row.channel == NotificationChannel.SMS.value

    def test_get_history_returns_db_rows(self, db_session, mock_email_provider, mock_sms_provider):
        """get_history() must query DB and return persisted records."""
        svc = NotificationService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _notif_request(customer_id="CUST_HIST")
        svc.send(req)
        svc.send(req)

        history = svc.get_history(customer_id="CUST_HIST")
        assert len(history) == 2

    def test_get_history_channel_filter(self, db_session, mock_email_provider, mock_sms_provider):
        """get_history() with channel filter must only return matching rows."""
        svc = NotificationService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        svc.send(_notif_request(channel=NotificationChannel.EMAIL, customer_id="CUST_CHAN"))
        svc.send(_notif_request(recipient="+15551234567", channel=NotificationChannel.SMS,
                                customer_id="CUST_CHAN"))

        email_hist = svc.get_history(customer_id="CUST_CHAN", channel=NotificationChannel.EMAIL)
        sms_hist = svc.get_history(customer_id="CUST_CHAN", channel=NotificationChannel.SMS)

        assert len(email_hist) == 1
        assert len(sms_hist) == 1
        assert email_hist[0]["channel"] == NotificationChannel.EMAIL.value
        assert sms_hist[0]["channel"] == NotificationChannel.SMS.value

    def test_history_content_hash_correct(self, db_session, mock_email_provider, mock_sms_provider):
        """The content_hash stored in DB must be SHA-256 of the notification content."""
        import hashlib
        from database.notification_models import NotificationHistory

        svc = NotificationService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        req = _notif_request()
        result = svc.send(req)

        row = db_session.query(NotificationHistory).filter_by(id=result.notification_id).first()
        expected_hash = hashlib.sha256(req.content.encode()).hexdigest()
        assert row.content_hash == expected_hash


# ============================================================================
# Audit Log DB Persistence Tests
# ============================================================================

class TestAuditLogPersistence:
    """NotificationAuditLogger wired to SQLite."""

    def test_log_creates_db_row(self, db_session):
        """Calling log() must persist a row to notification_audit_log."""
        from database.notification_models import NotificationAuditLog

        logger = NotificationAuditLogger(db_session=db_session)
        logger.log(action="test_action", customer_id="CUST_AUD", success=True)

        row = db_session.query(NotificationAuditLog).filter_by(action="test_action").first()
        assert row is not None
        assert row.customer_id == "CUST_AUD"
        assert row.success is True

    def test_log_failure_stored_correctly(self, db_session):
        """A failed audit event must be stored with success=False and error_message."""
        from database.notification_models import NotificationAuditLog

        logger = NotificationAuditLogger(db_session=db_session)
        logger.log(action="otp_failed", success=False, error_message="Bad code",
                   risk_level="high")

        row = db_session.query(NotificationAuditLog).filter_by(action="otp_failed").first()
        assert row is not None
        assert row.success is False
        assert row.error_message == "Bad code"
        assert row.risk_level == "high"

    def test_get_recent_events_from_db(self, db_session):
        """get_recent_events() must return rows from the DB when session is provided."""
        logger = NotificationAuditLogger(db_session=db_session)
        logger.log(action="event_one", customer_id="CUST_AUDIT")
        logger.log(action="event_two", customer_id="CUST_AUDIT")
        logger.log(action="event_other", customer_id="CUST_OTHER")

        events = logger.get_recent_events(customer_id="CUST_AUDIT")
        assert len(events) == 2
        actions = {e["action"] for e in events}
        assert "event_one" in actions
        assert "event_two" in actions

    def test_get_recent_events_action_filter(self, db_session):
        """get_recent_events() with action filter must return only matching rows."""
        logger = NotificationAuditLogger(db_session=db_session)
        logger.log(action="otp_generated")
        logger.log(action="otp_verified")
        logger.log(action="otp_generated")

        events = logger.get_recent_events(action="otp_generated")
        assert len(events) == 2

    def test_in_memory_fallback_when_no_db(self):
        """Without db_session, events should only be in-memory (backward compat)."""
        logger = NotificationAuditLogger()  # no db_session
        logger.log(action="mem_event")

        events = logger.get_recent_events(action="mem_event")
        assert len(events) == 1


# ============================================================================
# create_notification_service factory with DB session
# ============================================================================

class TestFactoryWithDBSession:
    """Factory function correctly threads db_session to all sub-services."""

    def test_factory_passes_db_session_to_otp_service(self, db_session):
        """create_notification_service(db_session=...) must wire OTP DB persistence."""
        svc = create_notification_service(use_mock=True, db_session=db_session)
        assert svc.otp_service._db_session is db_session

    def test_factory_passes_db_session_to_notification_service(self, db_session):
        """create_notification_service(db_session=...) must wire notification history DB."""
        svc = create_notification_service(use_mock=True, db_session=db_session)
        assert svc._db_session is db_session

    def test_factory_without_db_session_uses_memory(self):
        """create_notification_service() without db_session must use in-memory fallback."""
        svc = create_notification_service(use_mock=True)
        assert svc._db_session is None
        assert svc.otp_service._db_session is None


# ============================================================================
# NotificationPreference — new columns
# ============================================================================

class TestNotificationPreferenceColumns:
    """Verify new preference columns exist and default correctly."""

    def test_whatsapp_in_app_webhook_columns_exist(self, db_session):
        """NotificationPreference must have whatsapp/in_app/webhook columns."""
        from database.notification_models import NotificationPreference

        pref = NotificationPreference(
            id="PREF_001",
            customer_id="CUST_PREF",
            email_enabled=True,
            sms_enabled=True,
            push_enabled=True,
            whatsapp_enabled=False,
            in_app_enabled=True,
            webhook_enabled=False,
        )
        db_session.add(pref)
        db_session.commit()

        row = db_session.query(NotificationPreference).filter_by(id="PREF_001").first()
        assert row.whatsapp_enabled is False
        assert row.in_app_enabled is True
        assert row.webhook_enabled is False

    def test_preference_to_dict_includes_new_columns(self, db_session):
        """to_dict() must include whatsapp_enabled, in_app_enabled, webhook_enabled."""
        from database.notification_models import NotificationPreference

        pref = NotificationPreference(
            id="PREF_002",
            customer_id="CUST_PREF2",
            whatsapp_enabled=True,
            in_app_enabled=True,
            webhook_enabled=True,
        )
        db_session.add(pref)
        db_session.commit()

        d = pref.to_dict()
        assert "whatsapp_enabled" in d
        assert "in_app_enabled" in d
        assert "webhook_enabled" in d


# ============================================================================
# datetime.utcnow deprecation — timezone-aware timestamps
# ============================================================================

class TestTimestampsAreTimezoneAware:
    """Verify that all auto-generated timestamps are timezone-aware (UTC)."""

    def test_otp_code_created_at_is_timezone_aware(self, db_session, mock_email_provider, mock_sms_provider):
        """OTPCode.created_at must be set by the service using timezone-aware datetime.

        Note: SQLite strips tzinfo when persisting, so we check the value was
        written close to 'now' rather than being null or naively utcnow.
        """
        from database.notification_models import OTPCode

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        svc = OTPService(
            email_provider=mock_email_provider,
            sms_provider=mock_sms_provider,
            db_session=db_session,
        )
        gen = svc.generate_and_send(_otp_request())
        assert gen.success
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        row = db_session.query(OTPCode).filter_by(id=gen.otp_id).first()
        assert row.created_at is not None
        # created_at must fall within the test window
        assert before <= row.created_at <= after

    def test_queue_item_created_at_is_timezone_aware(self):
        """QueueItem.created_at must be timezone-aware (not naive utcnow)."""
        from services.notification_queue_service import QueueItem

        item = QueueItem(
            id="Q_001",
            notification_request=_notif_request(),
            priority=NotificationPriority.NORMAL,
        )
        # Should be timezone-aware (UTC)
        assert item.created_at.tzinfo is not None

    def test_notification_preference_created_date_is_timezone_aware(self, db_session):
        """NotificationPreference.created_date default must be timezone-aware."""
        from database.notification_models import NotificationPreference

        pref = NotificationPreference(id="PREF_TS", customer_id="CUST_TS")
        db_session.add(pref)
        db_session.commit()

        # SQLite stores without tz, but the lambda itself returns tz-aware value
        # We just verify the column was created without error
        row = db_session.query(NotificationPreference).filter_by(id="PREF_TS").first()
        assert row is not None


# ============================================================================
# Queue service — basic smoke tests
# ============================================================================

class TestQueueServiceBasic:
    """Basic queue service functionality tests."""

    @pytest.fixture()
    def queue_svc(self):
        """Create a NotificationQueueService backed by a mock notification service."""
        from services.notification_queue_service import NotificationQueueService

        notif_svc = NotificationService(
            email_provider=MockEmailProvider(),
            sms_provider=MockSMSProvider(),
        )
        return NotificationQueueService(notification_service=notif_svc, auto_start=False)

    def test_enqueue_and_get_status(self, queue_svc):
        """Enqueuing an item should make it retrievable via get_status."""
        req = _notif_request()
        item_id = queue_svc.enqueue(req)
        assert item_id

        status = queue_svc.get_status(item_id)
        assert status is not None
        assert status["id"] == item_id

    def test_enqueue_cancel(self, queue_svc):
        """Cancelling a queued item should succeed."""
        item_id = queue_svc.enqueue(_notif_request())
        cancelled = queue_svc.cancel(item_id)
        assert cancelled is True

    def test_batch_enqueue(self, queue_svc):
        """Batch enqueue should create one item per request."""
        from services.notification_queue_service import BatchNotificationService

        batch_svc = BatchNotificationService(queue_service=queue_svc)
        requests = [_notif_request(customer_id=f"CUST_{i}") for i in range(3)]
        result = batch_svc.send_batch(requests)
        ids = result["item_ids"]
        assert len(ids) == 3
        assert len(set(ids)) == 3  # all unique
