"""The Swiss Re Israel meeting deck (8 December 2026) is filled from the plan,
filmed with the investor-deck method, and never writes the plan."""

import copy
import importlib.util
import json
import random
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from security import confidential_access
from services.business_plan_document import _PLACEHOLDER, _fill, fmt
from services.business_plan_model import compute_plan
from services.investor_deck_video import (
    SCENE_SECONDS,
    fill_narration,
    parse_campaign_id,
    prompt_override,
    seal_for_send,
    short_script,
    spec_for as deck_spec_for,
    verify_scene,
)
from services.reinsurer_meeting_deck import (
    DECK_ID,
    MEETING,
    SCENARIO_CESSIONS,
    SLIDE_CHARTS,
    STORE_NAME,
    catalog,
    chart_spec,
    charts,
    deck_slides,
    fill,
    fill_reinsurer_figures,
    is_reinsurer_scene_key,
    placeholder_keys,
    presentation_of,
    reinsurer_figures,
    reinsurer_view,
    render_markdown,
    scene_storage_key,
    slide_specs,
    spec_for,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_portal" / "static"
DOCS = STATIC / "investor-docs"
MD_PATH = DOCS / "swiss-re-israel-meeting-8dec2026-deck.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The reinsurer view is an identity on the plan, and the scenarios are the
# same model with a different cession
# ---------------------------------------------------------------------------
def test_reinsurer_view_is_an_identity_on_the_carrier_rows():
    plan = compute_plan()
    view = reinsurer_view(plan)
    assert plan["canonical"] is True
    inputs = plan["inputs"]
    assert view["cession_rate"] == inputs["cession_rate"]
    assert view["technical_margin"] == pytest.approx(1 - inputs["expected_loss_ratio"] - inputs["ceding_commission"])
    assert view["breakeven_claims_ratio"] == pytest.approx(1 - inputs["ceding_commission"])
    carrier_rows = plan["carrier_view"]["rows"]
    group_rows = plan["group"]["rows"]
    assert [row["year"] for row in view["rows"]] == [row["year"] for row in carrier_rows]
    for row, carrier, group in zip(view["rows"], carrier_rows, group_rows):
        assert row["ceded_premium"] == pytest.approx(carrier["risk_gwp"] * inputs["cession_rate"])
        assert row["technical_result"] == pytest.approx(
            carrier["ceded_premium"] - carrier["ceded_claims"] - carrier["ceding_commission"]
        )
        assert row["technical_result"] == pytest.approx(row["ceded_premium"] * view["technical_margin"])
        assert row["group_envelope"] == pytest.approx(group["risk_gwp"] * inputs["cession_rate"])
    totals = view["totals"]
    assert totals["technical_result"] == pytest.approx(
        totals["ceded_premium"] - totals["ceded_claims"] - totals["ceding_commission"]
    )
    # The pilot year, in full precision, as the integrity notices state it.
    first = view["rows"][0]
    assert first["year"] == 2027
    assert first["risk_gwp"] == pytest.approx(54_216_000)
    assert first["ceded_premium"] == pytest.approx(9_758_880)
    assert first["ceding_commission"] == pytest.approx(2_439_720)
    assert first["ceded_claims"] == pytest.approx(6_050_505.60)
    assert first["technical_result"] == pytest.approx(1_268_654.40)


def test_quota_share_scenarios_are_labelled_and_leave_phins_unchanged():
    plan = compute_plan()
    view = reinsurer_view(plan)
    assert [s["cession_rate"] for s in view["scenarios"]] == list(SCENARIO_CESSIONS)
    for scenario in view["scenarios"]:
        assert scenario["canonical"] is False
        assert scenario["integrity_all_hold"] is True
        assert scenario["content_hash"] != plan["content_hash"]
        overrides = dict(plan["inputs"])
        overrides["cession_rate"] = scenario["cession_rate"]
        alt = compute_plan(overrides)
        assert alt["content_hash"] == scenario["content_hash"]
        assert scenario["ceded_premium_2027"] == pytest.approx(
            view["rows"][0]["risk_gwp"] * scenario["cession_rate"]
        )
        # The cession moves the carrier/reinsurer split only.
        assert scenario["phins_revenue_5y"] == pytest.approx(view["phins_revenue_5y"])
        assert scenario["group_ebitda_5y"] == pytest.approx(view["group_ebitda_5y"])
        assert scenario["carrier_margin"] < view["rows"][0]["carrier_margin"]
    # Computing scenarios does not move the plan.
    assert compute_plan()["content_hash"] == plan["content_hash"]


# ---------------------------------------------------------------------------
# Slides, placeholders and figures
# ---------------------------------------------------------------------------
def test_every_placeholder_fills_from_the_plan_and_nothing_is_typed():
    plan = compute_plan()
    figures = reinsurer_figures(plan)
    keys = placeholder_keys()
    assert keys
    for key in keys:
        if key.startswith("re_"):
            assert key in figures, key
    for slide in deck_slides():
        for text in [slide.get("kicker") or "", *slide["bullets"]]:
            filled = fill(text, plan)
            assert "{" not in filled and "}" not in filled, filled
    fx = float(plan["presentation"]["fx_usd_ils"])
    view = reinsurer_view(plan)
    assert fill_reinsurer_figures("{re_result_0}", plan) == fmt(view["rows"][0]["technical_result"], "ilsm", fx)
    assert fill_reinsurer_figures("{re_ceded_5y_usd}", plan) == fmt(view["totals"]["ceded_premium"], "usdm", fx)
    assert fill_reinsurer_figures("{re_qs30_hash}", plan) == fmt(view["scenarios"][0]["content_hash"], "hash", fx)
    # An unknown reinsurer key is left as written, never guessed.
    assert fill_reinsurer_figures("{re_not_a_key}", plan) == "{re_not_a_key}"
    # The document's own registry still fills the plan keys.
    assert fill("{premium}", plan) == _fill("{premium}", plan, False).strip()


def test_catalog_is_one_scene_per_paragraph_with_the_meeting_in_slide_one():
    slides = deck_slides()
    rows = catalog()
    assert len(rows) == sum(len(slide["bullets"]) for slide in slides) == 24
    assert len(slides) == 12
    assert rows[0]["scene_key"] == "re-s01p01"
    assert all(is_reinsurer_scene_key(row["scene_key"]) for row in rows)
    assert not is_reinsurer_scene_key("s01p01") and not is_reinsurer_scene_key("he-s01p01")
    assert scene_storage_key(5, 2) == "re-s05p02"
    assert all(row["duration_seconds"] == SCENE_SECONDS == 15 for row in rows)
    assert all(row["lang"] == "en" for row in rows)
    assert MEETING["counterpart"] in slides[0]["kicker"]
    assert MEETING["date"] == "2026-12-08"
    charted = {row["slide_title"] for row in rows if row["chart_id"]}
    assert charted == set(SLIDE_CHARTS)
    assert {spec["chart_id"] for spec in slide_specs() if spec["chart_id"]} == set(SLIDE_CHARTS.values())
    assert spec_for("re-s05p01")["chart_id"] == "ceded_line"
    assert spec_for("s05p01") is None
    assert spec_for("re-s99p01") is None
    # The investor-deck registry delegates reinsurer keys and keeps its own.
    assert deck_spec_for("re-s05p01") == spec_for("re-s05p01")
    assert deck_spec_for("s05p01")["scene_key"] == "s05p01"


def test_charts_are_the_plans_own_and_the_ceded_line_is_computed():
    plan = compute_plan()
    rendered = charts(plan)
    assert set(rendered) == set(SLIDE_CHARTS.values())
    for chart_id, item in rendered.items():
        assert item["svg"].startswith("<svg"), chart_id
    ceded = chart_spec(plan, "ceded_line")
    view = reinsurer_view(plan)
    assert ceded["kind"] == "grouped_bars"
    assert ceded["categories"] == [str(row["year"]) for row in view["rows"]]
    by_label = {series["label"]: series["values"] for series in ceded["series"]}
    assert by_label["Ceded premium"] == pytest.approx([row["ceded_premium"] for row in view["rows"]])
    assert by_label["Technical result"] == pytest.approx([row["technical_result"] for row in view["rows"]])


# ---------------------------------------------------------------------------
# Investor-deck method: short script, seal, verify, prompt
# ---------------------------------------------------------------------------
def test_scenes_seal_with_the_investor_deck_method():
    plan = compute_plan()
    spec = spec_for("re-s05p01")
    on_slide = fill_narration(spec["template"], plan)
    spoken = short_script(spec, plan)
    assert "₪" in on_slide and "{" not in on_slide
    assert "₪" not in spoken
    assert "The figures stay on this slide" in spoken
    assert spec["slide_title"] in spoken
    sealed = seal_for_send("re-s05p01", None, plan, used_presenter_ids=[], rng=random.Random(5))
    assert sealed["campaign_id"] == "DECK-re-s05p01"
    assert sealed["sealed_narration"] == spoken
    assert sealed["sealed_plan_hash"] == plan["content_hash"]
    assert verify_scene(sealed, spec)
    assert verify_scene(sealed, deck_spec_for("s05p01")) is False
    direction = prompt_override(sealed)
    assert spoken in direction
    assert "in Hebrew" not in direction
    assert parse_campaign_id("DECK-re-s05p01") == "re-s05p01"
    # A paragraph without a figure is spoken in full.
    plain = spec_for("re-s01p01")
    assert short_script(plain, plan) == fill_narration(plain["template"], plan)


def test_presentation_carries_the_script_and_the_reinsurer_view():
    plan = compute_plan()
    view = presentation_of(plan, [])
    assert view["deck"] == DECK_ID == "reinsurer"
    assert view["slide_count"] == 12 and view["scene_count"] == 24
    assert view["film_seconds_max"] == 24 * SCENE_SECONDS
    assert view["meeting"]["counterpart"] == MEETING["counterpart"]
    assert view["reinsurer_view"]["totals"]["ceded_premium"] == pytest.approx(
        reinsurer_view(plan)["totals"]["ceded_premium"]
    )
    for slide in view["slides"]:
        assert "{" not in "".join(slide["bullets"])
        assert slide["script"] == []
        assert slide["filmed"] == []
    # A scene listing with scripts flows through to the slide.
    scenes = [{
        "scene_key": "re-s05p01", "slide_no": 5, "paragraph_no": 1,
        "script": "spoken", "narration": "on slide", "presenter_label": "Dana", "in_stream": False, "stored": True,
    }]
    with_scripts = presentation_of(plan, scenes)
    fifth = next(s for s in with_scripts["slides"] if s["slide_no"] == 5)
    assert fifth["script"][0]["spoken"] == "spoken"
    assert fifth["script"][0]["duration_seconds"] == SCENE_SECONDS
    assert fifth["script"][0]["playback_url"] == ""


# ---------------------------------------------------------------------------
# Confidential scope
# ---------------------------------------------------------------------------
def test_reinsurer_deck_is_its_own_confidential_scope():
    assert confidential_access.is_confidential_path("/reinsurer-deck.html")
    assert confidential_access.is_confidential_path("/api/admin/media/reinsurer-deck/presentation")
    assert not confidential_access.is_confidential_path("/api/admin/media/reinsurer-deck")
    assert confidential_access.share_scope_root("/api/admin/media/reinsurer-deck/presentation") == "/reinsurer-deck.html"
    assert confidential_access.share_scope_root("/reinsurer-deck.html") == "/reinsurer-deck.html"
    assert confidential_access.share_scope_root("/investor-deck.html") == "/investor-deck.html"
    assert confidential_access.is_reinsurer_deck_page("/reinsurer-deck.html")
    assert not confidential_access.is_reinsurer_deck_page("/investor-deck.html")
    assert confidential_access.is_investor_deck_scope_path("/reinsurer-deck.html")
    assert not confidential_access.is_investor_deck_page("/reinsurer-deck.html")


# ---------------------------------------------------------------------------
# HTTP: lab, presentation, send — through the investor-deck plumbing
# ---------------------------------------------------------------------------
class _Server(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        import web_portal.server as portal
        self.portal = portal
        self.httpd = HTTPServer(("127.0.0.1", 0), portal.PortalHandler)
        self.port = self.httpd.server_address[1]

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _json_request(url, method="GET", payload=None, token=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


class _ReplicateStub:
    def __init__(self):
        self.submissions = []

    def supported_provider_config(self):
        return {
            "replicate": {
                "enabled": True,
                "label": "Replicate",
                "model": "bytedance/seedance-2.0",
                "models": ["bytedance/seedance-2.0", "google/veo-3.1-fast"],
            },
            "gemini": {"enabled": False, "label": "Gemini", "models": []},
            "kling": {"enabled": False, "label": "Kling", "models": []},
        }

    def submit_video_generation(self, **kwargs):
        self.submissions.append(kwargs)
        return {
            "provider": "replicate",
            "provider_job_id": "pred-re-deck-1",
            "status": "queued",
            "message": "Stub accepted the reinsurer deck scene.",
            "provider_state": {},
        }

    def poll_video_generation(self, **kwargs):
        return {
            "status": "completed",
            "message": "Stub stored the reinsurer deck scene.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": "https://cdn.example.com/generated/re-deck.mp4",
            "duration": 15,
            "provider_state": {},
        }

    def download_generated_video(self, **kwargs):
        return {
            "data_url": "data:video/mp4;base64,cmUtZGVjay12aWRlby1ieXRlcw==",
            "content_type": "video/mp4",
            "size": 18,
        }


def test_http_lab_presentation_and_send_keep_the_investor_deck_untouched():
    srv = _Server()
    srv.start()
    time.sleep(0.2)
    portal = srv.portal
    base = f"http://127.0.0.1:{srv.port}"
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass
    token = "phins_test_reinsurer_deck_token"
    portal.SESSIONS[token] = {
        "username": "re-deck-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    customer = "phins_test_reinsurer_deck_customer"
    portal.SESSIONS[customer] = {
        "username": "re-deck-customer",
        "role": "customer",
        "customer_id": "CUST1",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    actuary = "phins_test_reinsurer_deck_actuary"
    portal.SESSIONS[actuary] = {
        "username": "re-deck-actuary",
        "role": "actuary",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    stub = _ReplicateStub()
    original = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub
    plan_before = compute_plan()["content_hash"]
    hero_before = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    investor_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_scenes"))
    hebrew_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_scenes_he"))
    reinsurer_before = copy.deepcopy(portal.DESIGN_SETTINGS.get(STORE_NAME))
    try:
        status, _ = _json_request(base + "/api/admin/media/reinsurer-deck")
        assert status == 403
        status, _ = _json_request(base + "/api/admin/media/reinsurer-deck", token=customer)
        assert status == 403
        status, _ = _json_request(base + "/api/admin/media/reinsurer-deck/presentation")
        assert status == 403
        status, _ = _json_request(base + "/api/admin/media/reinsurer-deck/presentation", token=customer)
        assert status == 403

        status, lab = _json_request(base + "/api/admin/media/reinsurer-deck", token=token)
        assert status == 200, lab
        assert lab["deck"] == "reinsurer"
        assert lab["meeting"]["counterpart"] == MEETING["counterpart"]
        assert lab["slide_count"] == 12 and lab["scene_count"] == 24
        assert lab["stream_count"] == 0
        assert lab["plan"]["content_hash"] == plan_before
        assert lab["plan"]["integrity_all_hold"] is True
        assert "ceded_line" in lab["charts"] and lab["charts"]["ceded_line"]["svg"].startswith("<svg")
        assert all(row["scene_key"].startswith("re-") for row in lab["scenes"])
        ceded = next(row for row in lab["scenes"] if row["scene_key"] == "re-s05p01")
        assert "₪" in ceded["narration"]
        assert "₪" not in ceded["script"]
        assert "{" not in ceded["script"]

        status, show = _json_request(base + "/api/admin/media/reinsurer-deck/presentation", token=actuary)
        assert status == 200, show
        assert show["can_assign"] is False
        assert show["deck"] == "reinsurer"
        assert show["plan"]["content_hash"] == plan_before
        assert len(show["slides"]) == 12
        assert all("{" not in "".join(slide["bullets"]) for slide in show["slides"])
        fifth = next(slide for slide in show["slides"] if slide["slide_no"] == 5)
        assert fifth["chart_svg"].startswith("<svg")
        # The script sheet lists every paragraph before anything is filmed.
        assert [row["paragraph_no"] for row in fifth["script"]] == [1, 2]
        assert all(row["in_stream"] is False and row["playback_url"] == "" for row in fifth["script"])
        assert fifth["script"][0]["spoken"] == ceded["script"]
        assert fifth["filmed"] == []
        assert show["filmed_count"] == 0
        assert show["reinsurer_view"]["scenarios"][0]["canonical"] is False

        status, as_admin = _json_request(base + "/api/admin/media/reinsurer-deck/presentation", token=token)
        assert status == 200 and as_admin["can_assign"] is True

        status, refused = _json_request(
            base + "/api/admin/media/reinsurer-deck/send",
            method="POST",
            token=token,
            payload={
                "scene_key": "re-s05p01",
                "provider": "replicate",
                "provider_model": "google/veo-3.1-fast",
                "poll_mode": "poll",
            },
        )
        assert status == 409
        assert "15" in refused["error"]
        assert stub.submissions == []

        status, wrong_deck = _json_request(
            base + "/api/admin/media/reinsurer-deck/send",
            method="POST",
            token=token,
            payload={"scene_key": "re-s05p01", "engine_id": "replicate-seedance", "poll_mode": "poll",
                     "prompt_override": "A different script."},
        )
        assert status == 409
        assert stub.submissions == []

        status, sent = _json_request(
            base + "/api/admin/media/reinsurer-deck/send",
            method="POST",
            token=token,
            payload={
                "scene_key": "re-s05p01",
                "engine_id": "replicate-seedance",
                "provider": "replicate",
                "provider_model": "bytedance/seedance-2.0",
                "theme": "Quiet navy boardroom",
                "poll_mode": "poll",
                "auto_publish_to_hero": True,
            },
        )
        assert status == 202, sent
        assert sent["duration_seconds"] == 15
        assert sent["auto_publish_to_hero"] is False
        assert sent["job"]["deck_scene_key"] == "re-s05p01"
        assert stub.submissions and stub.submissions[0]["duration_seconds"] == 15
        assert ceded["script"] in stub.submissions[0]["prompt"]
        assert "₪" not in stub.submissions[0]["prompt"]
        assert "Quiet navy boardroom" in stub.submissions[0]["prompt"]
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert compute_plan()["content_hash"] == plan_before

        scene = {}
        for _ in range(40):
            time.sleep(0.1)
            status, again = _json_request(base + "/api/admin/media/reinsurer-deck", token=token)
            scene = next(row for row in again["scenes"] if row["scene_key"] == "re-s05p01")
            if scene.get("in_stream"):
                break
        assert scene["in_stream"] is True
        assert scene["playback_url"].startswith("data:video/mp4")
        assert scene["figures_current"] is True
        assert scene["presenter_id"]
        assert again["stream_count"] == 1
        assert again["stream"][0]["scene_key"] == "re-s05p01"
        asset = portal.MEDIA_ASSETS[scene["last_asset_id"]]
        assert asset["metadata"]["plan_content_hash"] == plan_before
        assert asset["checksum"]

        # The scene lives in its own store; the investor-deck stores are untouched.
        assert "re-s05p01" in (portal.DESIGN_SETTINGS.get(STORE_NAME) or {})
        assert portal.DESIGN_SETTINGS.get("investor_deck_scenes") == investor_before
        assert portal.DESIGN_SETTINGS.get("investor_deck_scenes_he") == hebrew_before

        status, show_again = _json_request(base + "/api/admin/media/reinsurer-deck/presentation", token=actuary)
        assert status == 200
        fifth = next(slide for slide in show_again["slides"] if slide["slide_no"] == 5)
        assert fifth["filmed"] and fifth["filmed"][0]["paragraph_no"] == 1
        assert fifth["script"][0]["in_stream"] is True
        assert fifth["script"][0]["spoken"] == ceded["script"]
        assert fifth["script"][0]["playback_url"].startswith("data:video/mp4")

        # The investor deck does not list the reinsurer scene.
        status, investor = _json_request(base + "/api/admin/media/investor-deck", token=token)
        assert status == 200
        assert all(not row["scene_key"].startswith("re-") for row in investor["scenes"])
        assert investor["stream_count"] == sum(1 for row in investor["scenes"] if row["in_stream"])

        status, saved = _json_request(
            base + "/api/admin/media/reinsurer-deck",
            method="POST",
            token=token,
            payload={"scene_key": "re-s02p01", "theme": "Gold boardroom"},
        )
        assert status == 200, saved
        assert saved["scene"]["theme"] == "Gold boardroom"
        assert saved["scene"]["scene_key"] == "re-s02p01"
        assert "re-s02p01" in portal.DESIGN_SETTINGS[STORE_NAME]
        assert "re-s02p01" not in (portal.DESIGN_SETTINGS.get("investor_deck_scenes") or {})

        # A tampered seal blocks the next send.
        stored = portal.DESIGN_SETTINGS[STORE_NAME]["re-s05p01"]
        stored["checksum"] = "0" * 64
        status, blocked = _json_request(
            base + "/api/admin/media/reinsurer-deck/send",
            method="POST",
            token=token,
            payload={"scene_key": "re-s05p01", "engine_id": "replicate-seedance", "poll_mode": "poll"},
        )
        assert status == 409
        assert "checksum" in blocked["error"].lower()

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert STORE_NAME not in public
        assert ceded["script"] not in json.dumps(public)
    finally:
        portal.get_media_generation_service = original
        for name, before in ((STORE_NAME, reinsurer_before), ("investor_deck_scenes", investor_before),
                             ("investor_deck_scenes_he", hebrew_before)):
            if before is None:
                portal.DESIGN_SETTINGS.pop(name, None)
            else:
                portal.DESIGN_SETTINGS[name] = before
        for key in (token, customer, actuary):
            portal.SESSIONS.pop(key, None)
        srv.stop()


# ---------------------------------------------------------------------------
# Pages, pitch bar, diary, meeting pack
# ---------------------------------------------------------------------------
def test_presentation_page_and_lab_are_wired_for_the_reinsurer_deck():
    page = _read(STATIC / "reinsurer-deck.html")
    assert "/api/admin/media/reinsurer-deck/presentation" in page
    assert "Hillel Damelin" in page
    assert "ui-clarity.js" in page
    assert "investor-deck-lab.js" in page
    assert "deck: 'reinsurer'" in page
    assert 'id="deck-script"' in page and 'id="deck-sheet"' in page
    assert "₪" not in page  # figures come from the plan, never the file
    lab = _read(STATIC / "investor-deck-lab.js")
    assert "/api/admin/media/reinsurer-deck" in lab
    assert "'/reinsurer-deck.html'" in lab
    assert "idlDeck" in lab
    media = _read(STATIC / "admin-media.html")
    assert "setInvestorDeckChoice('reinsurer')" in media
    assert "reinsurer-deck" in media


def test_pitch_bar_addresses_the_unified_plan_and_matches_the_model():
    html = _read(STATIC / "pitch-dashboard.html")
    assert '<a href="#swissre-israel-meeting-8dec2026" class="pitch-nav-link">' in html
    assert '"swissre-israel-meeting-8dec2026",' in html
    start = html.index('<section id="swissre-israel-meeting-8dec2026"')
    end = html.index("</section>", start)
    section = html[start:end]
    assert "Hillel Damelin" in section
    assert "8 December 2026" in section
    assert 'href="#unified-business-plan-card"' in section
    assert 'href="#reinsurer-ceo-assessment-nov2026"' in section
    assert 'href="/reinsurer-deck.html"' in section
    assert "swiss-re-israel-meeting-8dec2026-deck.pdf" in section
    assert "swiss-re-israel-meeting-8dec2026-deck.html" in section
    assert "exec-integrity-note" in section
    assert "does not write the platform ledger" in section
    # The one-standard card links the meeting.
    assert 'Swiss Re Israel · Damelin · 8 Dec · meeting deck' in html
    plan = compute_plan()
    view = reinsurer_view(plan)
    fx = view["fx_usd_ils"]
    assert plan["content_hash"].startswith("9128223e1c222388")
    for row in view["rows"]:
        assert fmt(row["ceded_premium"], "ilsm", fx) in section
        assert fmt(row["technical_result"], "ilsm", fx) in section
        assert fmt(row["technical_result"], "usdm", fx) in section
        assert fmt(row["group_envelope"], "ilsm", fx) in section
    assert fmt(view["totals"]["ceded_premium"], "ilsm", fx) in section
    assert fmt(view["totals"]["technical_result"], "ilsm", fx) in section
    assert fmt(view["totals"]["technical_result"], "usdm", fx) in section
    for scenario in view["scenarios"]:
        assert fmt(scenario["ceded_premium_5y"], "ilsm", fx) in section
        assert fmt(scenario["technical_result_5y"], "ilsm", fx) in section
        assert fmt(scenario["carrier_margin"], "pct1", fx) in section
        assert scenario["content_hash"][:16] in section
    assert "9,758,880" in section and "1,268,654.40" in section
    assert "764,896,948.20" in section and "99,436,603.27" in section
    assert f"{view['totals']['ceded_premium']:,.2f}" == "764,896,948.20"
    assert f"{view['totals']['technical_result']:,.2f}" == "99,436,603.27"


def test_diary_seeds_the_swiss_re_meeting_on_v10():
    html = _read(STATIC / "pitch-dashboard.html")
    assert 'var STORAGE_ID = "phins.il.meeting.diary.v10"' in html
    assert 'localStorage.getItem("phins.il.meeting.diary.v10") || localStorage.getItem("phins.il.meeting.diary.v9")' in html
    assert 'date: "2026-12-08"' in html
    assert "Mr. Hillel Damelin — Regional CEO Israel, Swiss Re" in html
    assert "ILS 9,758,880" in html


def test_meeting_pack_markdown_is_a_fresh_render_and_is_registered():
    plan = compute_plan()
    fresh = render_markdown(plan)
    assert MD_PATH.is_file()
    assert _read(MD_PATH) == fresh
    assert "{" not in re.sub(r"`[^`]*`", "", fresh.split("## Slides and film script")[1].split("## Data integrity")[0])
    assert "Hillel Damelin" in fresh
    assert "re-s05p01" in fresh
    assert "scenario" in fresh
    assert plan["content_hash"][:16] in fresh
    view = reinsurer_view(plan)
    fx = view["fx_usd_ils"]
    assert fmt(view["totals"]["technical_result"], "ilsm", fx) in fresh
    for scenario in view["scenarios"]:
        assert scenario["content_hash"][:12] in fresh
    # The build script agrees with itself.
    spec = importlib.util.spec_from_file_location("build_reinsurer_deck_brief", ROOT / "scripts" / "build_reinsurer_deck_brief.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0
    # PDF + designed HTML registration and committed outputs.
    gen = importlib.util.spec_from_file_location("generate_investor_pdfs", ROOT / "scripts" / "generate_investor_pdfs.py")
    gen_module = importlib.util.module_from_spec(gen)
    sys.modules[gen.name] = gen_module
    gen.loader.exec_module(gen_module)
    sources = {src for src, _, _ in gen_module.DOCUMENTS}
    assert "investor-docs/swiss-re-israel-meeting-8dec2026-deck.md" in sources
    assert "investor-docs/swiss-re-israel-meeting-8dec2026-deck.md" in gen_module.DESIGNED_BRIEFS
    assert (DOCS / "swiss-re-israel-meeting-8dec2026-deck.pdf").is_file()
    designed = _read(DOCS / "swiss-re-israel-meeting-8dec2026-deck.html")
    assert "Hillel Damelin" in designed
    assert fmt(view["totals"]["ceded_premium"], "ilsm", fx) in designed
