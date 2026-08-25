"""
Tests for the investor FX rates feature.

Covers:
- the ``get_investor_fx_rates`` helper: payload shape, cross-rate integrity
  (every display currency derives consistently from the two USD legs), the
  keyless Frankfurter (ECB) live fallback used when Alpha Vantage is not
  configured, and the labelled static fallback when no live provider is
  reachable,
- the public, read-only ``/api/fx/rates`` HTTP endpoint served by the embedded
  test server (always 200, self-describing source).

These power the investor documents' currency display ($ / ₪ / €) and must keep
data integrity flawless regardless of which live provider is reachable.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

import web_portal.server as portal


VALID_SOURCES = {"alpha_vantage", "frankfurter_ecb", "mixed_live", "partial", "fallback"}


def _assert_rate_integrity(payload):
    assert payload["base"] == "USD"
    assert set(payload["symbols"]) == {"USD", "ILS", "EUR"}
    assert payload["source"] in VALID_SOURCES
    usd_ils = payload["usd_ils"]
    usd_eur = payload["usd_eur"]
    assert usd_ils > 0 and usd_eur > 0
    r = payload["rates"]
    # Every pairwise rate must derive consistently from the two USD legs.
    assert abs(r["USD"]["ILS"] - usd_ils) < 1e-9
    assert abs(r["USD"]["EUR"] - usd_eur) < 1e-9
    assert abs(r["ILS"]["USD"] - 1.0 / usd_ils) < 1e-9
    assert abs(r["EUR"]["ILS"] - usd_ils / usd_eur) < 1e-9
    assert abs(r["EUR"]["USD"] - 1.0 / usd_eur) < 1e-9
    assert abs(r["ILS"]["EUR"] - usd_eur / usd_ils) < 1e-9
    # Identity legs.
    for c in ("USD", "ILS", "EUR"):
        assert abs(r[c][c] - 1.0) < 1e-12


def test_get_investor_fx_rates_structure_and_integrity():
    payload = portal.get_investor_fx_rates()
    _assert_rate_integrity(payload)
    assert "as_of" in payload and "fetched_at" in payload
    assert isinstance(payload["live"], dict)
    assert isinstance(payload["providers"], dict)


def test_get_investor_fx_rates_frankfurter_when_alpha_vantage_disabled(monkeypatch):
    # With Alpha Vantage off, the keyless Frankfurter (ECB) feed must keep
    # the currency legs live instead of dropping straight to static values.
    monkeypatch.setattr(portal, "alpha_vantage_enabled", False, raising=False)
    monkeypatch.setattr(portal, "_FX_CACHE", {"data": None, "fetched_at": 0.0}, raising=False)
    monkeypatch.setattr(
        portal,
        "_fetch_investor_fx_frankfurter",
        lambda: (3.6512, 0.9231, "2026-08-25"),
        raising=False,
    )
    payload = portal.get_investor_fx_rates(force_refresh=True)
    _assert_rate_integrity(payload)
    assert payload["source"] == "frankfurter_ecb"
    assert payload["provider"] == "frankfurter_ecb"
    assert payload["usd_ils"] == pytest.approx(3.6512)
    assert payload["usd_eur"] == pytest.approx(0.9231)
    assert payload["live"] == {"USD_ILS": True, "USD_EUR": True}
    assert payload["providers"] == {
        "USD_ILS": "frankfurter_ecb",
        "USD_EUR": "frankfurter_ecb",
    }


def test_get_investor_fx_rates_frankfurter_partial_leg(monkeypatch):
    # A single missing leg must not void the other live leg.
    monkeypatch.setattr(portal, "alpha_vantage_enabled", False, raising=False)
    monkeypatch.setattr(portal, "_FX_CACHE", {"data": None, "fetched_at": 0.0}, raising=False)
    monkeypatch.setattr(
        portal,
        "_fetch_investor_fx_frankfurter",
        lambda: (3.6512, None, "2026-08-25"),
        raising=False,
    )
    payload = portal.get_investor_fx_rates(force_refresh=True)
    _assert_rate_integrity(payload)
    assert payload["source"] == "partial"
    assert payload["live"] == {"USD_ILS": True, "USD_EUR": False}
    assert payload["usd_eur"] == portal._FX_FALLBACK["USD_EUR"]


def test_get_investor_fx_rates_fallback_when_all_providers_down(monkeypatch):
    # Force every live provider off and bypass the cache so we exercise the
    # labelled static fallback deterministically.
    def _frankfurter_down():
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(portal, "alpha_vantage_enabled", False, raising=False)
    monkeypatch.setattr(portal, "_FX_CACHE", {"data": None, "fetched_at": 0.0}, raising=False)
    monkeypatch.setattr(portal, "_fetch_investor_fx_frankfurter", _frankfurter_down, raising=False)
    payload = portal.get_investor_fx_rates(force_refresh=True)
    _assert_rate_integrity(payload)
    assert payload["source"] == "fallback"
    assert payload["provider"] == "static_fallback"
    assert payload["usd_ils"] == portal._FX_FALLBACK["USD_ILS"]
    assert payload["usd_eur"] == portal._FX_FALLBACK["USD_EUR"]
    assert payload["live"] == {"USD_ILS": False, "USD_EUR": False}


def test_fx_rates_http_endpoint():
    base = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
    with urllib.request.urlopen(f"{base}/api/fx/rates", timeout=20) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read().decode("utf-8"))
    _assert_rate_integrity(payload)
