import pytest

from services.customer_communication_agent import CustomerCommunicationAgent
from services.notification_service import (
    MockEmailProvider,
    MockSMSProvider,
    NotificationChannel,
    NotificationService,
    OTPRequest,
    VerificationType,
    create_notification_service,
    reset_notification_service,
    reset_global_rate_limiter,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    reset_global_rate_limiter()
    reset_notification_service()
    yield
    reset_global_rate_limiter()
    reset_notification_service()


def _sample_policies():
    return [
        {
            "id": "POL-1",
            "type": "health",
            "status": "active",
            "coverage_amount": 250000,
            "annual_premium": 2400,
            "monthly_premium": 200,
        },
        {
            "id": "POL-2",
            "type": "auto",
            "status": "approved",
            "coverage_amount": 80000,
            "annual_premium": 1200,
            "monthly_premium": 100,
        },
        {
            "id": "POL-3",
            "type": "life",
            "status": "pending",
            "coverage_amount": 500000,
            "annual_premium": 3000,
            "monthly_premium": 250,
        },
    ]


def _sample_bills():
    return [
        {"id": "B1", "status": "outstanding", "amount_due": 210.0},
        {"id": "B2", "status": "partial", "amount": 120.0, "amount_paid": 20.0},
        {"id": "B3", "status": "paid", "amount": 180.0},
    ]


def _sample_accounts():
    return [
        {"name": "health_wallet", "balance": 5000},
        {"name": "investment", "balance": 12000},
    ]


def test_build_diversified_executive_report():
    service = create_notification_service(use_mock=True)
    agent = CustomerCommunicationAgent(notification_service=service)

    report = agent.build_diversified_executive_report(
        customer_id="CUST-1",
        policies=_sample_policies(),
        bills=_sample_bills(),
        accounts=_sample_accounts(),
        communities=[{"id": "COMM-1"}],
    )

    assert report.customer_id == "CUST-1"
    assert report.total_policies == 3
    assert report.active_policies == 2
    assert report.outstanding_bills == 2
    assert report.accounts_count == 2
    assert report.communities_count == 1
    assert report.total_coverage > 0
    assert 0 <= report.diversification_index <= 100
    assert len(report.highlights) >= 4


def test_send_welcome_package_success():
    service = create_notification_service(use_mock=True)
    agent = CustomerCommunicationAgent(notification_service=service)

    result = agent.send_welcome_package(
        customer_id="CUST-1",
        customer_name="Customer One",
        email="customer@example.com",
        policies=_sample_policies(),
        bills=_sample_bills(),
        accounts=_sample_accounts(),
    )

    assert result["success"] is True
    assert result["email"]["success"] is True
    assert "report" in result
    assert result["report"]["total_policies"] == 3


def test_send_welcome_package_requires_otp_validation_missing_code():
    service = create_notification_service(use_mock=True)
    agent = CustomerCommunicationAgent(notification_service=service)

    result = agent.send_welcome_package(
        customer_id="CUST-1",
        customer_name="Customer One",
        email="customer@example.com",
        policies=_sample_policies(),
        bills=_sample_bills(),
        accounts=_sample_accounts(),
        require_otp_validation=True,
    )

    assert result["success"] is False
    assert result["code"] == "OTP_CODE_REQUIRED"


def test_send_welcome_package_whatsapp_with_otp_validation():
    service = create_notification_service(use_mock=True)
    agent = CustomerCommunicationAgent(notification_service=service)

    otp_result = service.send_otp(OTPRequest(
        identifier="+14155551234",
        channel=NotificationChannel.SMS,
        verification_type=VerificationType.ACCOUNT_ACTIVATION,
    ))
    assert otp_result.success

    sms_body = service._sms_provider.sent_messages[0]["message"]
    otp_code = sms_body.split(": ")[1].split(".")[0]

    result = agent.send_welcome_package(
        customer_id="CUST-1",
        customer_name="Customer One",
        email="customer@example.com",
        policies=_sample_policies(),
        bills=_sample_bills(),
        accounts=_sample_accounts(),
        whatsapp_phone="+14155551234",
        require_otp_validation=True,
        otp_code=otp_code,
        otp_identifier="+14155551234",
        otp_verification_type=VerificationType.ACCOUNT_ACTIVATION,
    )

    # Email and WhatsApp are both sent; WhatsApp must pass OTP.
    assert result["email"]["success"] is True
    assert result["whatsapp"] is not None
    assert result["whatsapp"]["success"] is True


def test_send_welcome_package_with_invalid_otp_fails():
    service = create_notification_service(use_mock=True)
    agent = CustomerCommunicationAgent(notification_service=service)

    otp_result = service.send_otp(OTPRequest(
        identifier="customer@example.com",
        channel=NotificationChannel.EMAIL,
        verification_type=VerificationType.ACCOUNT_ACTIVATION,
    ))
    assert otp_result.success

    result = agent.send_welcome_package(
        customer_id="CUST-1",
        customer_name="Customer One",
        email="customer@example.com",
        policies=_sample_policies(),
        bills=_sample_bills(),
        accounts=_sample_accounts(),
        require_otp_validation=True,
        otp_code="000000",
        otp_identifier="customer@example.com",
        otp_verification_type=VerificationType.ACCOUNT_ACTIVATION,
    )

    assert result["success"] is False
    assert result["code"] in {"INVALID_CODE", "NO_ACTIVE_OTP", "OTP_VALIDATION_FAILED"}


def test_agent_without_injected_service_uses_shared_notification_service(monkeypatch):
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    monkeypatch.delenv("PHINS_USE_MOCK_NOTIFICATIONS", raising=False)

    agent = CustomerCommunicationAgent()

    assert isinstance(agent._notification_service, NotificationService)
    assert not isinstance(agent._notification_service._email_provider, MockEmailProvider)
    assert not isinstance(agent._notification_service._sms_provider, MockSMSProvider)
