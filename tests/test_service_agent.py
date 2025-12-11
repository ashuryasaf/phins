import sys
import os
import pytest
from datetime import date, datetime

# Make sure repo root is importable when running tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from service_agent import CustomerServiceAgent
from underwriting_assistant import NotificationManager
from customer_validation import (
    Customer,
    IdentificationDocument,
    HealthAssessment,
    Gender,
    SmokingStatus,
    PersonalStatus,
)


def make_customer() -> Customer:
    ident = IdentificationDocument(
        document_type=None,  # type: ignore
        document_id="ID123456",
        issue_date=date(2020, 1, 1),
        expiry_date=None,
    )

    health = HealthAssessment(condition_level=2, assessment_date=datetime.now())

    customer = Customer(
        first_name="Alice",
        last_name="Smith",
        gender=Gender.FEMALE,
        birthdate=date(1990, 6, 15),
        identification=ident,
        smoking_status=SmokingStatus.NON_SMOKER,
        personal_status=PersonalStatus.SINGLE,
        address="123 Elm St",
        city="Metropolis",
        state_province="NY",
        postal_code="12345",
        health_assessment=health,
        email="alice@example.com",
        phone="+15551234567",
    )

    customer.customer_id = "CUST_TEST_1"
    return customer


def test_send_correspondence_and_acknowledgement():
    nm = NotificationManager()
    svc = CustomerServiceAgent("svc_1", notification_mgr=nm)

    # register a customer in the underlying service
    cust = make_customer()
    svc.customer_service.customers[cust.customer_id] = cust

    # send correspondence
    ctx = {"customer_name": cust.full_name, "policy_id": "POL_123"}
    delivery = svc.send_correspondence(cust.customer_id, "premium_allocation", ctx)

    assert delivery.customer_id == cust.customer_id
    assert len(nm.delivery_queue) >= 1


def test_handle_inquiry_and_ack():
    nm = NotificationManager()
    svc = CustomerServiceAgent("svc_2", notification_mgr=nm)
    cust = make_customer()
    svc.customer_service.customers[cust.customer_id] = cust

    result = svc.handle_inquiry(cust.customer_id, channel="email", message="I have a question about my bill")
    assert "interaction" in result
    assert "acknowledgement" in result
    assert len(svc.interactions) == 1


def test_suggest_upsell_rules():
    svc = CustomerServiceAgent("svc_3")
    cust = make_customer()
    # ensure household not present -> suggestions still include Investment Booster
    suggestions = svc.suggest_upsell(cust)
    assert isinstance(suggestions, list)
    assert any(s["offer"] == "Investment Booster" for s in suggestions)
