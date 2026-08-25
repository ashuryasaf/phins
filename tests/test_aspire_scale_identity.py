"""Closed-form Aspire-Invest identity — switched disability table + savings configurator."""

from pathlib import Path

from services.aspire_scale_identity import (
    DEFAULTS,
    UNIFIED_5Y_AVG,
    UNIFIED_5Y_EOY,
    UNIFIED_5Y_OPEX,
    UNIFIED_ANNUAL_PREMIUM,
    UNIFIED_AVG_IN_FORCE,
    UNIFIED_EOY_IN_FORCE,
    UNIFIED_OPEX,
    compute_aspire_identity,
    extend_in_force_path,
    parse_identity_query,
    published_table_rates,
    quote_risk_premium,
    unified_phins_ebitda,
)
from services.pricing_kernel import risk_reference_v1_factor

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"


def test_published_disability_table_is_switched_from_life():
    rates = published_table_rates()
    assert rates["life_rate_per_1000"] == 0.25
    assert rates["disability_rate_per_1000"] == 0.20


def test_quote_matches_kernel_age_curve_and_switched_disability():
    assert risk_reference_v1_factor(42) == 1.255
    q = quote_risk_premium(
        avg_age=42,
        face=1_000_000,
        life_rate_per_1000=0.25,
        disability_rate_per_1000=0.20,
    )
    assert q["life_monthly"] == 313.75
    assert q["disability_monthly"] == 62.75
    assert q["total_monthly"] == 376.50
    assert q["annual_premium"] == 4518.0
    # Same 0.25 on disability would NOT produce 62.75
    wrong = quote_risk_premium(
        avg_age=42,
        face=1_000_000,
        life_rate_per_1000=0.25,
        disability_rate_per_1000=0.25,
    )
    assert wrong["disability_monthly"] == 78.44  # 250 * 0.25 * 1.255
    assert wrong["annual_premium"] != 4518.0


def test_default_identity_reconciles():
    pack = compute_aspire_identity()
    assert pack["data_integrity"]["all_hold"] is True
    assert pack["quote"]["annual_premium"] == 4518.0
    years = {y["year"]: y for y in pack["years"]}
    assert years[2027]["risk_gwp"] == 54_216_000
    assert years[2028]["risk_gwp"] == 266_742_720
    assert years[2029]["risk_gwp"] == 733_348_206
    assert years[2029]["phins_take"] == 183_337_052
    assert years[2029]["insurance_take"] == 550_011_154
    # 30% of book × 300% add-on = 90% of risk GWP
    assert pack["savings"]["portfolio_multiple"] == 0.9
    assert years[2027]["savings_flow"] == 48_794_400
    assert years[2028]["savings_flow"] == 240_068_448
    assert years[2029]["savings_flow"] == 660_013_385
    for y in pack["years"]:
        assert y["phins_take"] + y["insurance_take"] == y["risk_gwp"]
        assert y["savings_flow"] != y["risk_gwp"]  # no longer 1/3 × 300%


def test_savings_presets_10_20_30():
    gwp = 54_216_000
    for pct, expected in ((0.10, 16_264_800), (0.20, 32_529_600), (0.30, 48_794_400)):
        pack = compute_aspire_identity(savings_election=pct, savings_addon=3.0)
        assert pack["years"][0]["savings_flow"] == expected
        assert pack["years"][0]["savings_flow"] == int(round(gwp * pct * 3.0))
        assert pack["data_integrity"]["all_hold"] is True


def test_age_and_face_readjust_premium():
    older = compute_aspire_identity(avg_age=50, face=1_000_000)
    younger = compute_aspire_identity(avg_age=35, face=1_000_000)
    assert older["quote"]["annual_premium"] > younger["quote"]["annual_premium"]
    bigger = compute_aspire_identity(avg_age=42, face=2_000_000)
    assert bigger["quote"]["annual_premium"] == 9036.0  # 2× face, same rates
    assert bigger["years"][0]["risk_gwp"] == 108_432_000


def test_parse_query_percent_conveniences():
    kwargs = parse_identity_query({
        "avg_age": ["42"],
        "savings_election_pct": ["20"],
        "savings_addon_pct": ["300"],
    })
    assert kwargs["savings_election"] == 0.20
    assert kwargs["savings_addon"] == 3.0
    pack = compute_aspire_identity(**kwargs)
    assert pack["savings"]["portfolio_multiple"] == 0.6


def test_dashboard_has_configurator_and_switched_table():
    html = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    start = html.index('id="aspire-invest-meeting-sep2026"')
    end = html.index('id="exec-summary-section"')
    section = html[start:end]
    assert 'id="aspire-configurator"' in section
    assert 'id="aspire-sav-elect"' in section
    assert 'data-elect="0.10"' in section
    assert 'data-elect="0.20"' in section
    assert 'data-elect="0.30"' in section
    assert "0.20" in section  # switched disability table
    assert "aspire-identity" in html
    assert "/api/pitch/aspire-identity" in html
    assert "Aspire identity configurator engine" in html
    assert "computeLocal" in html


def test_api_dispatch_default_and_savings_presets():
    from web_portal.api_extensions import dispatch_get

    status, payload = dispatch_get(
        "/api/pitch/aspire-identity", {}, {}, "127.0.0.1"
    )
    assert status == 200
    assert payload["quote"]["annual_premium"] == 4518.0
    assert payload["quote"]["disability_monthly"] == 62.75
    assert payload["data_integrity"]["all_hold"] is True
    assert payload["years"][0]["savings_flow"] == 48_794_400

    status, ten = dispatch_get(
        "/api/pitch/aspire-identity",
        {},
        {"savings_election_pct": ["10"], "savings_addon_pct": ["300"]},
        "127.0.0.1",
    )
    assert status == 200
    assert ten["years"][0]["savings_flow"] == 16_264_800
    assert ten["years"][0]["phins_take"] + ten["years"][0]["insurance_take"] == ten["years"][0]["risk_gwp"]

    status, bad = dispatch_get(
        "/api/pitch/aspire-identity",
        {},
        {"face": ["-1"]},
        "127.0.0.1",
    )
    assert status == 400
    assert "error" in bad


def test_unified_book_has_no_second_small_book():
    assert UNIFIED_ANNUAL_PREMIUM == 4518.0
    assert UNIFIED_EOY_IN_FORCE == (24_000, 94_080, 230_554)
    assert UNIFIED_AVG_IN_FORCE == (12_000, 59_040, 162_317)
    assert UNIFIED_OPEX == (32_400_000.0, 66_420_000.0, 116_868_240.0)
    ebitda = unified_phins_ebitda()
    assert ebitda[0] == 13_554_000 - 32_400_000
    assert ebitda[1] == 66_685_680 - 66_420_000
    assert ebitda[2] == 183_337_052 - 116_868_240
    extra = extend_in_force_path(2, 150_000)
    assert [r["eoy"] for r in extra] == list(UNIFIED_5Y_EOY)
    assert [r["avg"] for r in extra] == list(UNIFIED_5Y_AVG)
    assert UNIFIED_5Y_OPEX[:3] == UNIFIED_OPEX
    assert UNIFIED_5Y_OPEX[3] == 169_637_783.0
    assert UNIFIED_5Y_OPEX[4] == 202_927_845.0
