"""Outbound URL safety: metadata hosts, scheme policy, provider endpoints."""

from __future__ import annotations

import pytest

from security.network import (
    assert_safe_provider_url,
    outbound_http_allowed_schemes,
    validate_remote_url,
)


def test_metadata_and_link_local_hosts_are_blocked():
    for url in (
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "https://169.254.1.1/secret",
    ):
        with pytest.raises(ValueError, match="Disallowed outbound host"):
            validate_remote_url(url, allowed_schemes=("http", "https"))


def test_http_allowed_only_for_loopback():
    assert outbound_http_allowed_schemes("http://127.0.0.1:8080/v1") == ("https", "http")
    assert outbound_http_allowed_schemes("http://localhost/v1") == ("https", "http")
    assert outbound_http_allowed_schemes("https://llm.example/v1") == ("https",)
    assert outbound_http_allowed_schemes("http://llm.example/v1") == ("https",)

    assert_safe_provider_url("http://127.0.0.1:11434/v1/chat/completions")
    assert_safe_provider_url("https://llm.example/v1/chat/completions")
    with pytest.raises(ValueError, match="Disallowed URL scheme"):
        assert_safe_provider_url("http://llm.example/v1/chat/completions")
