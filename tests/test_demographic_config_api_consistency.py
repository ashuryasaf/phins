"""Demographic Risk Factors must be durable and consistent across Save /
GET / reload, and must flow into every pricing consumer attached to the
central store (simulate, contract-spec, kernel application pricing)."""

from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from services.actuarial_service import ActuarialTablesStore, get_actuarial_store
from services.pricing_kernel import (
    PricingCustomer,
    get_product,
    price_policy,
    pricing_config_from_underwriting,
    table_set_from_store,
)
from services.pricing_shadow_service import price_application_with_kernel


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    monkeypatch.setenv("USE_DATABASE", "false")
    import services.actuarial_service as asvc
    asvc._actuarial_store = None
    store = get_actuarial_store()
    yield store
    asvc._actuarial_store = None


def _post(base, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req) as resp:
        return json.loads(resp.read()), resp.status


def _get(base, path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(base + path, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read()), resp.status


def test_public_config_dict_includes_demographic_factors(isolated_store):
    cfg = isolated_store.public_config_dict()
    assert "smoker_mortality_factor" in cfg
    assert "ethnicity_mortality_factors" in cfg
    assert "ethnicity_disability_factors" in cfg
    assert "male_mortality_factor" in cfg
    assert "female_disability_factor" in cfg
    assert "life_share_of_coverage_post65" in cfg
    assert "post_disability_premium_factor" in cfg
    assert "config_version" in cfg
    assert cfg["ethnicity_mortality_factors"]["asian"] == pytest.approx(1.0)


def test_save_then_get_preserves_demographic_factors(isolated_store, tmp_path, monkeypatch):
    """The bug: GET /api/actuarial/config used to omit demographics, so after
    Save Pricing Parameters the UI reloaded 1.0 and a second save wiped the
    operator's adjustments."""
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    monkeypatch.setenv("USE_DATABASE", "false")
    import services.actuarial_service as asvc
    asvc._actuarial_store = None

    httpd = HTTPServer(("127.0.0.1", 0), portal.PortalHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.2)
        base = f"http://127.0.0.1:{port}"
        login, _ = _post(base, "/api/login", {"username": "admin", "password": "admin123"})
        token = login["token"]

        payload = {
            "smoker_mortality_factor": 1.85,
            "smoker_disability_factor": 1.4,
            "female_mortality_factor": 0.88,
            "male_disability_factor": 1.05,
            "ethnicity_mortality_factors": {
                "asian": 0.92,
                "african": 1.15,
                "caucasian": 1.0,
                "hispanic": 1.0,
                "other": 1.0,
            },
            "ethnicity_disability_factors": {
                "asian": 0.95,
                "african": 1.1,
                "caucasian": 1.0,
                "hispanic": 1.0,
                "other": 1.0,
            },
        }
        saved, status = _post(base, "/api/actuarial/config", payload, token)
        assert status == 200
        assert saved["success"] is True
        assert saved["persisted"] is True
        # POST response itself must carry the full demographic block.
        assert saved["config"]["smoker_mortality_factor"] == pytest.approx(1.85)
        assert saved["config"]["ethnicity_mortality_factors"]["asian"] == pytest.approx(0.92)

        fetched, status = _get(base, "/api/actuarial/config", token)
        assert status == 200
        cfg = fetched["config"]
        assert cfg["smoker_mortality_factor"] == pytest.approx(1.85)
        assert cfg["smoker_disability_factor"] == pytest.approx(1.4)
        assert cfg["female_mortality_factor"] == pytest.approx(0.88)
        assert cfg["male_disability_factor"] == pytest.approx(1.05)
        assert cfg["ethnicity_mortality_factors"]["asian"] == pytest.approx(0.92)
        assert cfg["ethnicity_mortality_factors"]["african"] == pytest.approx(1.15)
        assert cfg["ethnicity_disability_factors"]["asian"] == pytest.approx(0.95)
        assert cfg["config_version"]

        # Contract-spec surfaces the same durable demographics.
        spec, status = _get(base, "/api/actuarial/contract-spec", token)
        assert status == 200
        demo = spec["contract"]["demographic_risk_factors"]
        assert demo["smoker_mortality_factor"] == pytest.approx(1.85)
        assert demo["ethnicity_mortality_factors"]["asian"] == pytest.approx(0.92)
    finally:
        httpd.shutdown()
        httpd.server_close()
        asvc._actuarial_store = None


def test_saved_demographics_flow_to_simulate_and_application_pricing(isolated_store, monkeypatch):
    store = isolated_store
    store.update_config(
        {
            "smoker_mortality_factor": 2.0,
            "smoker_disability_factor": 1.5,
            "female_mortality_factor": 0.85,
        },
        user="pytest",
    )

    # Kernel pricing for a smoker must exceed an identical nonsmoker.
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config, savings_rate=0.0)
    product = get_product("phins_pure_risk_adjustable")
    smoker = price_policy(
        PricingCustomer(
            age=40, coverage=500_000, term_years=20, adl_level=5,
            smoking_status="smoker", gender="male",
        ),
        product, tables, cfg,
    )
    nonsmoker = price_policy(
        PricingCustomer(
            age=40, coverage=500_000, term_years=20, adl_level=5,
            smoking_status="nonsmoker", gender="male",
        ),
        product, tables, cfg,
    )
    assert smoker.annual_premium > nonsmoker.annual_premium
    assert smoker.demographic_mortality_factor == pytest.approx(2.0)

    # Simulation provenance stamps the same factors.
    from services.actuarial_service import PortfolioSimulator, SimulationParams
    sim = PortfolioSimulator(store)
    result = sim.generate_portfolio(SimulationParams(
        customer_count=80,
        age_min=30, age_max=45,
        smoker_pct=100.0, former_smoker_pct=0.0,
        policy_term_mode="fixed", policy_term_fixed=10,
    ))
    demo = result["pricing_kernel"]["demographic_risk_factors"]
    assert demo["smoker_mortality_factor"] == pytest.approx(2.0)
    assert demo["female_mortality_factor"] == pytest.approx(0.85)

    # Application / new-policy kernel path also uses the durable store.
    monkeypatch.setenv("PHINS_KERNEL_BILLING_ENABLED", "1")
    monkeypatch.setattr(
        "services.actuarial_service.get_actuarial_store", lambda: store
    )
    priced = price_application_with_kernel({
        "type": "life",
        "coverage_amount": 500000,
        "age": 40,
        "term_years": 20,
        "gender": "male",
        "questionnaire": {"smoke": "yes"},
    })
    assert priced is not None
    assert priced["demographic_mortality_factor"] == pytest.approx(2.0)
    assert priced["annual"] > 0


def test_dashboard_wires_demographic_status_and_dirty_tracking():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1]
            / "web_portal" / "static" / "actuary-dashboard.html").read_text(encoding="utf-8")
    assert 'id="demo-factors-status"' in html
    assert "wirePricingParamsDirtyTracking" in html
    assert "markPricingParamsDirty" in html
    assert "smoker_mortality_factor: num('factor-smoker-mort')" in html
    assert "ethnicity_mortality_factors" in html
    assert "loadContractSpec" in html
    assert "Demographic risk factors (persisted)" in html
