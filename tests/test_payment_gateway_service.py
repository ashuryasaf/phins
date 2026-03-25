import pytest


def test_should_use_payment_test_mode_defaults_true_for_non_production(monkeypatch):
    from services.payment_gateway_service import should_use_payment_test_mode

    monkeypatch.delenv("PHINS_PAYMENT_TEST_MODE", raising=False)
    monkeypatch.setenv("PHINS_ENV", "development")

    assert should_use_payment_test_mode() is True


def test_should_use_payment_test_mode_defaults_false_for_production(monkeypatch):
    from services.payment_gateway_service import should_use_payment_test_mode

    monkeypatch.delenv("PHINS_PAYMENT_TEST_MODE", raising=False)
    monkeypatch.setenv("PHINS_ENV", "production")

    assert should_use_payment_test_mode() is False


def test_should_use_payment_test_mode_honors_explicit_override(monkeypatch):
    from services.payment_gateway_service import should_use_payment_test_mode

    monkeypatch.setenv("PHINS_PAYMENT_TEST_MODE", "true")
    monkeypatch.setenv("PHINS_ENV", "production")
    assert should_use_payment_test_mode() is True

    monkeypatch.setenv("PHINS_PAYMENT_TEST_MODE", "false")
    assert should_use_payment_test_mode() is False


def test_get_payment_gateway_uses_runtime_default(monkeypatch):
    import services.payment_gateway_service as payment_gateway_service

    monkeypatch.delenv("PHINS_PAYMENT_TEST_MODE", raising=False)
    monkeypatch.setenv("PHINS_ENV", "production")
    payment_gateway_service._payment_gateway = None
    try:
        gateway = payment_gateway_service.get_payment_gateway()
        assert gateway.test_mode is False
    finally:
        payment_gateway_service._payment_gateway = None
