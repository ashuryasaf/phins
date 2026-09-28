"""Lives-mode Scenario Lab premiums stay glued to the actuarial kernel.

Public evidence is not rewritten. The Israel book remains ILS 4,518 at age 42.
Sweden's implied vårdförsäkring average (SEK 6,312) stays an evidence identity,
not the lives-mode product price.
"""

from decimal import Decimal
from pathlib import Path

from services.aspire_scale_identity import (
    FX_USD,
    ISRAEL_BOOK_PREMIUM,
    MARKET_SPECS,
    all_market_quotes,
    israel_book_holds,
    quote_market,
)
from services.pricing_kernel import risk_reference_v1_factor

REPO = Path(__file__).resolve().parents[1]
PITCH = REPO / "web_portal" / "static" / "pitch-dashboard.html"
LAB_JS = REPO / "web_portal" / "static" / "phins-scenario-lab-kernel.js"
LAB_PDF = REPO / "web_portal" / "static" / "phins-scenario-lab-pdf.js"


def _html() -> str:
    return PITCH.read_text(encoding="utf-8")


def _market_block(market_id: str) -> str:
    html = _html()
    start = html.index(f'id: "{market_id}"')
    closer = html.index("    ];", start)
    nxt = html.find('id: "', start + 1)
    end = nxt if 0 < nxt < closer else closer
    return html[start:end]


def test_israel_book_is_the_kernel_identity():
    assert israel_book_holds() is True
    quote = quote_market("israel")
    assert quote["local_annual"] == ISRAEL_BOOK_PREMIUM
    assert quote["ils_annual"] == float(ISRAEL_BOOK_PREMIUM)
    assert quote["age"] == 42
    assert quote["age_factor"] == 1.255
    assert risk_reference_v1_factor(42) == 1.255
    assert quote["writes_public_evidence"] is False
    assert quote["pricing_source"] == "pricing_kernel"


def test_bulgaria_uses_official_mean_age_on_the_same_tables():
    quote = quote_market("bulgaria")
    assert quote["age"] == 45
    assert quote["age_basis"] == "nsi_2025_mean_age_45_4"
    assert quote["age_factor"] == 1.3
    assert quote["ils_annual"] == 4680.0
    assert quote["currency"] == "EUR"
    assert quote["local_annual"] == 1170
    assert quote["fx_per_ils"] == FX_USD["EUR"] / FX_USD["ILS"]
    assert quote["writes_public_evidence"] is False


def test_every_lab_market_html_premium_matches_kernel():
    html = _html()
    quotes = all_market_quotes()
    assert set(quotes) == set(MARKET_SPECS)
    for market_id, quote in quotes.items():
        block = _market_block(market_id)
        assert f"annualPremium: {quote['local_annual']}" in block
    assert "annualPremium: 720" not in html
    assert "annualPremium: 6312" not in html
    assert "annualPremium: 1900" not in html
    assert "annualPremium: 5500" not in html
    assert "annualPremium: 4518" in html


def test_public_averages_stay_out_of_the_kernel_price():
    html = _html()
    sweden = _market_block("sweden")
    japan = _market_block("japan")
    bulgaria = _market_block("bulgaria")
    assert "SEK 6,312" in sweden
    assert "annualPremium: 13321" in sweden
    assert "5.1 billion / 808,000" in sweden
    assert "JPY 6,225" in japan
    assert "annualPremium: 189682" in japan
    assert "BGN 870 million" in bulgaria
    assert "marketPremiumPool: 444824000" in bulgaria
    assert "annualPremium: 1170" in bulgaria
    assert "NSSI and NHIF levies are public funding, not commercial premium" in bulgaria


def test_wneurope_lives_tam_follows_kernel_not_public_blend():
    quote = quote_market("wneurope")
    assert quote["local_annual"] == 1130
    assert 5_700_000 * 4 * 1130 // 100 == 257_640_000
    assert "marketPremiumPool: 257640000" in _market_block("wneurope")
    assert "marketPremiumPool: 615600000" not in _html()


def test_browser_kernel_mirrors_python_pins_and_bulgaria_age():
    js = LAB_JS.read_text(encoding="utf-8")
    assert "ILS: 3.68" in js
    assert "EUR: 0.92" in js
    assert "bulgaria: { currency: 'EUR', age: 45" in js
    assert "riskReferenceV1Factor" in js
    assert "writesPublicEvidence: false" in js
    html = _html()
    assert '<script src="/phins-scenario-lab-kernel.js"></script>' in html
    assert "Reset to kernel quote" in html
    assert "Lives premium is the actuarial kernel" in html
    pdf = LAB_PDF.read_text(encoding="utf-8")
    assert "kernelYes" in pdf
    assert "ציטוט הליבה האקטוארית" in pdf


def test_israel_fx_round_trip_is_exact():
    quote = quote_market("israel")
    assert Decimal(quote["local_annual"]) == Decimal(ISRAEL_BOOK_PREMIUM)
    eur = quote_market("portugal")
    assert eur["local_annual"] == int(round(4518 * 0.92 / 3.68))


def test_kernel_stays_inside_issue_band_and_known_markets():
    import pytest
    with pytest.raises(ValueError):
        quote_market("israel", age=65)
    with pytest.raises(KeyError):
        quote_market("albania")
    assert set(MARKET_SPECS) == {
        "israel", "usa", "canada", "wneurope", "middleeast",
        "japan", "australia", "sweden", "portugal", "bulgaria",
    }
    for spec in MARKET_SPECS.values():
        assert spec["currency"] in FX_USD
        assert 3 <= spec["age"] < 65


def test_adapter_lives_in_aspire_identity_not_a_new_service_module():
    services = REPO / "services"
    assert not (services / "scenario_lab_kernel.py").exists()
    identity = (services / "aspire_scale_identity.py").read_text(encoding="utf-8")
    assert "def quote_market(" in identity
    assert "writes_public_evidence" in identity
