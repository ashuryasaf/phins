"""Demo-OTP exposure must never be possible in production (F2).

``PHINS_EXPOSE_DEMO_OTP`` is a demo aid that returns the live verification code
in the API response. Without a production guard, setting it on a production
deployment — or leaving it set after a demo — hands an attacker the code for any
account they can name, including password-reset codes. That is a direct
account-takeover primitive.

These tests pin:

* the production guard on the blanket exposure flag,
* that ``PHINS_ENVIRONMENT=production`` (the documented variable, used by
  ``scripts/entrypoint.sh`` and ``security.secrets_policy``) is actually
  recognised as production by the OTP paths, and
* that test mode keeps working so the harness can still assert on
  ``demo_otp_code``.
"""

import importlib

import pytest

from web_portal import api_extensions


@pytest.fixture
def otp_module(monkeypatch):
    """api_extensions with the demo-OTP flag forced on, test mode off."""
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", True)
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    for name in (
        "PHINS_ENVIRONMENT",
        "ENVIRONMENT",
        "ENV",
        "PHINS_ENV",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_NAME",
        "RENDER",
        "NODE_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    return api_extensions


@pytest.mark.parametrize(
    "env_name,env_value",
    [
        ("PHINS_ENVIRONMENT", "production"),
        ("PHINS_ENVIRONMENT", "prod"),
        ("PHINS_ENVIRONMENT", "live"),
        ("ENVIRONMENT", "production"),
        ("RAILWAY_ENVIRONMENT", "production"),
        ("PHINS_ENV", "production"),
        ("NODE_ENV", "production"),
    ],
)
def test_demo_otp_is_refused_in_production(otp_module, monkeypatch, env_name, env_value):
    monkeypatch.setenv(env_name, env_value)
    assert otp_module._is_production_runtime() is True
    assert otp_module._demo_otp_exposure_allowed() is False


def test_phins_environment_production_is_detected(otp_module, monkeypatch):
    """Regression: PHINS_ENVIRONMENT was previously not inspected here."""
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    assert otp_module._is_production_runtime() is True


def test_demo_otp_allowed_outside_production(otp_module, monkeypatch):
    monkeypatch.setenv("PHINS_ENVIRONMENT", "development")
    assert otp_module._is_production_runtime() is False
    assert otp_module._demo_otp_exposure_allowed() is True


def test_test_mode_is_never_production(monkeypatch):
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", True)
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", True)
    monkeypatch.setenv("PHINS_TEST_MODE", "true")
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    # The pytest harness relies on demo_otp_code being returned.
    assert api_extensions._demo_otp_exposure_allowed() is True


def test_disabled_flag_is_respected_regardless_of_environment(monkeypatch):
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", False)
    monkeypatch.setenv("PHINS_ENVIRONMENT", "development")
    assert api_extensions._demo_otp_exposure_allowed() is False


def test_otp_code_is_stripped_from_production_responses(otp_module, monkeypatch):
    """End-to-end: the sanitizer must not attach demo_otp_code in production."""
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    raw = {
        "success": True,
        "data": {
            "verification_id": "OTP_1",
            "otp_code": "123456",
            "email": "victim@example.com",
            "phone": "+15555550100",
            "masked_email": "v***@example.com",
            "delivery_channel": "email",
            "expires_in_seconds": 300,
        },
    }
    sanitized, otp_code, context = otp_module._prepare_otp_client_response(raw)

    # The code is still handed to the internal delivery path...
    assert otp_code == "123456"
    assert context["email"] == "victim@example.com"
    # ...but never to the client.
    assert "demo_otp_code" not in sanitized
    serialized = repr(sanitized)
    assert "123456" not in serialized
    assert "otp_code" not in sanitized["data"]
    # Contact details are not echoed back either; only masked forms.
    assert "email" not in sanitized["data"]
    assert "phone" not in sanitized["data"]
    assert sanitized["masked_email"] == "v***@example.com"


def test_otp_code_is_exposed_when_explicitly_enabled_outside_production(otp_module, monkeypatch):
    monkeypatch.setenv("PHINS_ENVIRONMENT", "staging")
    raw = {"success": True, "data": {"verification_id": "OTP_2", "otp_code": "654321"}}
    sanitized, _otp_code, _context = otp_module._prepare_otp_client_response(raw)
    assert sanitized["demo_otp_code"] == "654321"


def test_registration_fallback_also_refuses_production(otp_module, monkeypatch):
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    monkeypatch.delenv("PHINS_ALLOW_REGISTRATION_DEMO_OTP_FALLBACK", raising=False)
    response: dict = {}
    applied = otp_module._apply_registration_demo_otp_fallback(
        response, "999888", "registration"
    )
    assert applied is False
    assert "demo_otp_code" not in response


def test_server_shares_the_same_guard(monkeypatch):
    """server.py's password-reset paths must use the same rule."""
    server = importlib.import_module("web_portal.server")
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", True)
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    assert server._demo_otp_exposure_allowed() is False

    monkeypatch.setenv("PHINS_ENVIRONMENT", "development")
    assert server._demo_otp_exposure_allowed() is True
