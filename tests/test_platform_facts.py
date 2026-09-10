"""Live platform facts for investor / partner surfaces.

Covers:
- ``count_service_modules`` / ``get_platform_facts`` against the real
  ``services/`` layer and the canonical IL book identity,
- the public, read-only ``/api/platform/facts`` HTTP endpoint (always 200),
- HTML surfaces that bind to the payload so stale ``64+`` claims cannot return.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import web_portal.server as portal


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_portal" / "static"


def _live_module_count():
    return len(list((ROOT / "services").glob("*.py")))


def test_count_service_modules_matches_services_layer():
    assert portal.count_service_modules() == _live_module_count()
    assert portal.count_service_modules() >= 100


def test_get_platform_facts_matches_il_book_identity():
    payload = portal.get_platform_facts()
    assert payload["service_modules"] == _live_module_count()
    assert payload["source"] == "services/*.py"
    book = payload["investor_book"]
    assert book["currency"] == "ILS"
    assert book["premium"] == 4518.0
    assert book["take_rate"] == 0.25
    avg = book["avg_in_force"]
    gwp = [avg[i] * book["premium"] for i in range(3)]
    nr = [g * book["take_rate"] for g in gwp]
    assert book["gwp"] == gwp
    assert book["net_revenue"] == nr
    ebitda = [nr[i] - book["opex"][i] for i in range(3)]
    assert book["ebitda"] == ebitda
    assert book["eoy_in_force"] == [24000, 94080, 230554]
    assert book["avg_in_force"] == [12000, 59040, 162317]


def test_get_platform_facts_follows_live_module_count(monkeypatch):
    monkeypatch.setattr(portal, "count_service_modules", lambda root=None: 107)
    payload = portal.get_platform_facts()
    assert payload["service_modules"] == 107


def test_platform_facts_http_endpoint():
    base = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
    import urllib.request

    with urllib.request.urlopen(f"{base}/api/platform/facts", timeout=20) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload["service_modules"] == _live_module_count()
    assert payload["investor_book"]["premium"] == 4518.0
    assert "error" not in payload


@pytest.mark.parametrize(
    "rel",
    [
        "pitch-dashboard.html",
        "unicorn-investor-deck.html",
        "unicorn-executive-summary.html",
        "seed-investor-deck.html",
        "legal/term-sheet.html",
        "legal/trademark-ip.html",
        "internal/phins-ai-tech-partner-business-plan.html",
        "internal/phins-insurer-mga-business-plan.html",
        "platform-facts.js",
        "investor-docs/regulatory-meeting-27jul-brief.md",
        "investor-docs/regulatory-preruling-avi-ovadia-brief.md",
    ],
)
def test_investor_surfaces_have_no_stale_64plus(rel):
    text = (STATIC / rel).read_text(encoding="utf-8")
    assert "64+" not in text, f"{rel} still carries the stale 64+ module claim"


@pytest.mark.parametrize(
    "rel",
    [
        "pitch-dashboard.html",
        "unicorn-investor-deck.html",
        "unicorn-executive-summary.html",
        "seed-investor-deck.html",
        "legal/term-sheet.html",
        "internal/phins-ai-tech-partner-business-plan.html",
        "internal/phins-insurer-mga-business-plan.html",
    ],
)
def test_investor_surfaces_bind_live_module_count(rel):
    text = (STATIC / rel).read_text(encoding="utf-8")
    assert "data-live-modules" in text
    assert "/platform-facts.js" in text
    count = _live_module_count()
    assert f">{count}<" in text
