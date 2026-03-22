import os

from services.media_generation_service import MediaGenerationError, MediaGenerationService


def test_kling_supported_provider_config_reports_access_key_secret_key_mode(monkeypatch):
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    monkeypatch.setenv("KLING_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("KLING_SECRET_KEY", "test-secret-key")

    service = MediaGenerationService()
    config = service.supported_provider_config()["kling"]

    assert config["enabled"] is True
    assert config["auth_mode"] == "access_key_secret_key"


def test_kling_auth_headers_generate_bearer_token_from_access_key_secret_key(monkeypatch):
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    monkeypatch.setenv("KLING_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("KLING_SECRET_KEY", "test-secret-key")

    service = MediaGenerationService()
    headers = service._kling_auth_headers()

    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Authorization"].count(".") == 2


def test_kling_auth_headers_require_credentials(monkeypatch):
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)

    service = MediaGenerationService()

    try:
        service._kling_auth_headers()
    except MediaGenerationError as exc:
        assert "KLING_API_KEY or KLING_ACCESS_KEY/KLING_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("Expected Kling auth header generation to require credentials")
