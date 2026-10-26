"""Investor-deck scenes stay sealed to the plan and play only when filmed."""

import copy
import json
import os
import random
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.business_plan_document import SLIDE_CHARTS, _fill, deck_slides
from services.business_plan_model import compute_plan
from services.investor_deck_video import (
    PRESENTERS,
    SCENE_SECONDS,
    InvestorDeckError,
    apply_scene_edit,
    WATERMARK_MAX_IMAGES,
    assign_slide_media,
    assign_watermark,
    catalog,
    choose_presenter,
    clip_is_scene_length,
    fill_narration,
    fresh_scene,
    presentation_of,
    prompt_override,
    scene_view,
    seal_for_send,
    short_script,
    slide_specs,
    spec_for,
    stream_of,
    verify_media_assignment,
    verify_scene,
    verify_watermark,
)


def test_catalog_follows_part_ii_and_does_not_invent_paragraphs():
    slides = deck_slides()
    rows = catalog()
    assert len(rows) == sum(len(slide["bullets"]) for slide in slides)
    slide_six = [row for row in rows if row["slide_no"] == 6]
    assert slide_six
    assert slide_six[0]["slide_title"] == "Product and pricing"
    assert slide_six[0]["paragraph_count"] == len(slides[5]["bullets"])
    assert [row["paragraph_no"] for row in slide_six] == list(range(1, len(slide_six) + 1))
    assert all(row["template"] == slides[5]["bullets"][row["paragraph_no"] - 1] for row in slide_six)
    charted = {row["slide_title"] for row in rows if row["chart_id"]}
    assert charted == set(SLIDE_CHARTS)
    assert {row["chart_id"] for row in rows if row["slide_title"] == "Market and expansion"} == {"in_force"}
    founder = [row for row in rows if row["photo"] == "founder"]
    assert founder and {row["slide_title"] for row in founder} == {"Founder"}
    assert all(row["duration_seconds"] == 15 for row in rows)


def test_narration_is_the_document_filler_and_presenters_spread():
    plan = compute_plan()
    for row in catalog():
        spoken = fill_narration(row["template"], plan)
        assert spoken == _fill(row["template"], plan, False).strip()
        assert "{" not in spoken
    used = []
    seen = set()
    sexes = set()
    ages = set()
    for _ in range(len(PRESENTERS)):
        chosen = choose_presenter(used, random.Random(0))
        # A fixed seed still advances as the used set grows, so the roster turns over.
        seen.add(chosen["id"])
        sexes.add(chosen["sex"])
        ages.add(chosen["age"])
        used.append(chosen["id"])
    assert seen == {item["id"] for item in PRESENTERS}
    assert sexes == {"woman", "man"}
    assert len(ages) >= 4
    assert {item["hair"] for item in PRESENTERS} >= {"red", "blonde", "brunette", "black"}
    assert all(int(item["age_years"]) >= 35 for item in PRESENTERS)
    again = choose_presenter(used, random.Random(1), exclude=used[0])
    assert again["id"] != used[0]


def test_only_a_matching_clip_enters_the_stream():
    plan = compute_plan()
    spec = spec_for("s06p01")
    sealed = seal_for_send("s06p01", None, plan, used_presenter_ids=[], rng=random.Random(2))
    assert verify_scene(sealed, spec)
    spoken = short_script(spec, plan)
    on_slide = fill_narration(spec["template"], plan)
    assert sealed["sealed_narration"] == spoken
    assert spoken != on_slide
    assert on_slide not in spoken
    assert "figures stay on this slide" in spoken
    assert sealed["presenter_id"]
    direction = prompt_override(sealed)
    assert sealed["sealed_narration"] in direction
    assert "must not be redrawn" in direction
    assert "{specimen_life_monthly}" not in direction
    asset = {
        "type": "video",
        "checksum": "abc123",
        "playback_url": "data:video/mp4;base64,AAAA",
    }
    sealed["last_asset_id"] = "asset-1"
    sealed["asset_checksum"] = "abc123"
    filmed = scene_view(spec, sealed, plan, asset)
    assert filmed["in_stream"] is True
    assert filmed["playback_url"].startswith("data:video/mp4")
    neighbor = scene_view(spec_for("s06p02"), None, plan, None)
    assert neighbor["in_stream"] is False
    stream = stream_of([neighbor, filmed])
    assert [item["scene_key"] for item in stream] == ["s06p01"]
    stale = dict(sealed)
    stale["sealed_narration"] = "A different sentence."
    stale["checksum"] = "0" * 64
    withheld = scene_view(spec, stale, plan, asset)
    assert withheld["integrity_ok"] is False
    assert withheld["in_stream"] is False
    assert withheld["playback_url"] == ""
    moved = dict(sealed)
    moved["sealed_narration"] = filmed["narration"] + " extra"
    from services.investor_deck_video import scene_checksum
    moved["checksum"] = scene_checksum(moved)
    drifted = scene_view(spec, moved, plan, asset)
    assert drifted["integrity_ok"] is True
    assert drifted["figures_current"] is False
    assert drifted["in_stream"] is False
    shifted = dict(plan)
    shifted["content_hash"] = "a" * 64
    assert sealed["sealed_plan_hash"] != shifted["content_hash"]
    kept = scene_view(spec, sealed, shifted, asset)
    assert kept["script"] == sealed["sealed_narration"]
    assert kept["narration"] == fill_narration(spec["template"], shifted)
    assert kept["figures_current"] is True
    assert kept["in_stream"] is True
    assert kept["playback_url"].startswith("data:video/mp4")
    sealed["last_job_id"] = "job-1"
    resealed = seal_for_send("s06p01", sealed, shifted, used_presenter_ids=[], rng=random.Random(2))
    assert resealed["sealed_narration"] == sealed["sealed_narration"]
    assert resealed["sealed_plan_hash"] == shifted["content_hash"]
    assert resealed["last_asset_id"] == "asset-1"
    assert resealed["asset_checksum"] == "abc123"
    assert resealed["last_job_id"] == "job-1"
    assert verify_scene(resealed, spec)
    still = scene_view(spec, resealed, shifted, asset)
    assert still["in_stream"] is True
    assert still["playback_url"].startswith("data:video/mp4")
    hash_line = spec_for("s13p03")
    sealed_hash = seal_for_send("s13p03", None, plan, used_presenter_ids=[], rng=random.Random(4))
    sealed_hash["last_asset_id"] = "asset-2"
    sealed_hash["asset_checksum"] = "abc123"
    spoken_hash = scene_view(hash_line, sealed_hash, shifted, asset)
    assert spoken_hash["narration"] != sealed_hash["sealed_narration"]
    assert spoken_hash["script"] == sealed_hash["sealed_narration"]
    assert spoken_hash["figures_current"] is True
    assert spoken_hash["in_stream"] is True
    assert shifted["content_hash"] not in spoken_hash["script"]
    assert shifted["content_hash"][:12] in spoken_hash["narration"]
    sealed_hash["last_job_id"] = "job-2"
    dropped = seal_for_send("s13p03", sealed_hash, shifted, used_presenter_ids=[], rng=random.Random(4))
    assert dropped["sealed_narration"] == sealed_hash["sealed_narration"]
    assert dropped["sealed_plan_hash"] == shifted["content_hash"]
    assert dropped["last_asset_id"] == "asset-2"
    assert dropped["asset_checksum"] == "abc123"
    assert dropped["last_job_id"] == "job-2"


def test_unfilled_figure_is_not_sealed_or_kept_in_the_stream():
    plan = compute_plan()
    spec = spec_for("s01p03")
    sealed = seal_for_send("s01p03", None, plan, used_presenter_ids=[], rng=random.Random(5))
    assert "figures stay on this slide" in sealed["sealed_narration"]
    broken = copy.deepcopy(plan)
    broken["plan_version"] = "v{seed}"
    on_slide = fill_narration(spec["template"], broken)
    assert "{seed}" in on_slide
    assert short_script(spec, broken) == on_slide
    try:
        seal_for_send("s01p03", sealed, broken, used_presenter_ids=[], rng=random.Random(5))
    except InvestorDeckError as exc:
        assert "could not be filled" in str(exc)
    else:
        raise AssertionError("unfilled figure was sealed")
    sealed["last_asset_id"] = "asset-1"
    sealed["asset_checksum"] = "abc123"
    withheld = scene_view(spec, sealed, broken, {
        "type": "video",
        "checksum": "abc123",
        "playback_url": "data:video/mp4;base64,AAAA",
    })
    assert "{seed}" in withheld["narration"]
    assert withheld["figures_current"] is False
    assert withheld["in_stream"] is False
    assert withheld["playback_url"] == ""


def test_theme_change_drops_the_film_link_and_reset_clears_the_seal():
    plan = compute_plan()
    sealed = seal_for_send(
        "s01p01", None, plan, used_presenter_ids=["p01"], rng=random.Random(3),
    )
    sealed["last_asset_id"] = "asset-9"
    sealed["asset_checksum"] = "deadbeef"
    edited = apply_scene_edit("s01p01", sealed, theme="Quiet navy office at dusk")
    assert edited["theme"] == "Quiet navy office at dusk"
    assert edited["last_asset_id"] == ""
    assert edited["sealed_narration"] == sealed["sealed_narration"]
    assert verify_scene(edited, spec_for("s01p01"))
    cleared = apply_scene_edit("s01p01", edited, reset=True)
    assert cleared["presenter_id"] == ""
    assert cleared["sealed_narration"] == ""
    assert cleared["theme"] == ""
    with_same = seal_for_send("s01p01", sealed, plan, used_presenter_ids=[], rng=random.Random(3))
    assert with_same["presenter_id"] == sealed["presenter_id"]
    assert with_same["last_asset_id"] == "asset-9"
    try:
        apply_scene_edit("s01p01", {"scene_key": "s01p01", "stored": True, "checksum": "nope"})
    except InvestorDeckError as exc:
        assert "checksum" in str(exc).lower()
    else:
        raise AssertionError("tampered scene was editable")


def test_fifteen_seconds_is_required():
    assert clip_is_scene_length("replicate", "bytedance/seedance-2.0") == SCENE_SECONDS
    assert clip_is_scene_length("replicate", "google/veo-3.1-fast") == 0
    assert clip_is_scene_length("kling", "kling-v2.6-pro") == 0
    assert clip_is_scene_length("kling", "kling-v3-text-to-video", evolink=True) == SCENE_SECONDS
    fresh = fresh_scene(spec_for("s02p01"))
    assert fresh["integrity_ok"] is True
    assert fresh["stored"] is False


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


def _json_request(url, method="GET", payload=None, token=None, cookie=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
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
            "provider_job_id": "pred-deck-1",
            "status": "queued",
            "message": "Stub accepted the deck scene.",
            "provider_state": {},
        }

    def poll_video_generation(self, **kwargs):
        return {
            "status": "completed",
            "message": "Stub stored the deck scene.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": "https://cdn.example.com/generated/deck.mp4",
            "duration": 15,
            "provider_state": {},
        }

    def download_generated_video(self, **kwargs):
        return {
            "data_url": "data:video/mp4;base64,ZGVjay12aWRlby1ieXRlcw==",
            "content_type": "video/mp4",
            "size": 16,
        }


def test_send_stores_one_scene_and_leaves_the_plan_and_placements_alone():
    srv = _Server()
    srv.start()
    time.sleep(0.2)
    portal = srv.portal
    base = f"http://127.0.0.1:{srv.port}"
    # The first request on a fresh test port clears in-memory sessions.
    # Warm the port before the admin token is stored.
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass
    token = "phins_test_investor_deck_token"
    portal.SESSIONS[token] = {
        "username": "deck-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    customer = "phins_test_investor_deck_customer"
    portal.SESSIONS[customer] = {
        "username": "deck-customer",
        "role": "customer",
        "customer_id": "CUST1",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    stub = _ReplicateStub()
    original = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub
    plan_before = compute_plan()["content_hash"]
    hero_before = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    tagline_before = portal.DESIGN_SETTINGS.get("tagline")
    scenes_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_scenes"))
    blueprints_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("solution_video_blueprints"))
    try:
        status, denied = _json_request(base + "/api/admin/media/investor-deck")
        assert status == 403
        status, denied = _json_request(base + "/api/admin/media/investor-deck", token=customer)
        assert status == 403

        status, listing = _json_request(base + "/api/admin/media/investor-deck", token=token)
        assert status == 200
        assert listing["stream_count"] == 0
        assert listing["plan"]["content_hash"] == plan_before
        assert listing["plan"]["integrity_all_hold"] is True
        slide_six = [row for row in listing["scenes"] if row["slide_no"] == 6]
        assert slide_six[0]["paragraph_count"] == len(slide_six)
        assert "in_force" in listing["charts"]
        assert listing["charts"]["in_force"]["svg"].startswith("<svg")
        assert any(engine["model"] == "bytedance/seedance-2.0" for engine in listing["engines"])
        opening = next(row for row in slide_six if row["paragraph_no"] == 1)
        spoken = opening["script"]
        assert "313.75" in opening["narration"]
        assert "313.75" not in spoken
        assert "{" not in spoken

        status, refused = _json_request(
            base + "/api/admin/media/investor-deck/send",
            method="POST",
            token=token,
            payload={
                "scene_key": "s06p01",
                "provider": "replicate",
                "provider_model": "google/veo-3.1-fast",
                "poll_mode": "poll",
            },
        )
        assert status == 409
        assert "15" in refused["error"]
        assert stub.submissions == []

        status, sent = _json_request(
            base + "/api/admin/media/investor-deck/send",
            method="POST",
            token=token,
            payload={
                "scene_key": "s06p01",
                "engine_id": "replicate-seedance",
                "provider": "replicate",
                "provider_model": "bytedance/seedance-2.0",
                "theme": "Quiet navy office",
                "poll_mode": "poll",
                "auto_publish_to_hero": True,
            },
        )
        assert status == 202, sent
        assert sent["duration_seconds"] == 15
        assert sent["auto_publish_to_hero"] is False
        assert sent["job"]["deck_scene_key"] == "s06p01"
        assert stub.submissions
        assert stub.submissions[0]["duration_seconds"] == 15
        assert spoken in stub.submissions[0]["prompt"]
        assert "313.75" not in stub.submissions[0]["prompt"]
        assert "must not be redrawn" in stub.submissions[0]["prompt"]
        assert "Quiet navy office" in stub.submissions[0]["prompt"]
        assert "auto_publish" not in stub.submissions[0] or stub.submissions[0].get("auto_publish_to_hero") in (None, False)
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert compute_plan()["content_hash"] == plan_before

        scene = {}
        for _ in range(40):
            time.sleep(0.1)
            status, again = _json_request(base + "/api/admin/media/investor-deck", token=token)
            scene = next(row for row in again["scenes"] if row["scene_key"] == "s06p01")
            if scene.get("in_stream"):
                break
        assert scene["in_stream"] is True
        assert scene["playback_url"].startswith("data:video/mp4")
        assert scene["figures_current"] is True
        assert scene["presenter_id"]
        assert again["stream_count"] == 1
        assert again["stream"][0]["scene_key"] == "s06p01"
        assert all(row["scene_key"] == "s06p01" or not row["in_stream"] for row in again["scenes"])
        asset = portal.MEDIA_ASSETS[scene["last_asset_id"]]
        assert asset["metadata"]["generated_from"] == "investor_deck_scene"
        assert asset["metadata"]["plan_content_hash"] == plan_before
        assert asset["checksum"]

        status, duplicate = _json_request(
            base + "/api/admin/media/investor-deck/send",
            method="POST",
            token=token,
            payload={
                "scene_key": "s06p01",
                "engine_id": "replicate-seedance",
                "provider": "replicate",
                "provider_model": "bytedance/seedance-2.0",
                "theme": "Quiet navy office",
                "poll_mode": "poll",
            },
        )
        assert status == 200
        assert duplicate["deduplicated"] is True
        assert len(stub.submissions) == 1

        status, mismatched = _json_request(
            base + "/api/admin/media/investor-deck/send",
            method="POST",
            token=token,
            payload={
                "scene_key": "s06p01",
                "engine_id": "replicate-seedance",
                "prompt_override": "A different script.",
                "poll_mode": "poll",
            },
        )
        assert status == 409
        assert len(stub.submissions) == 1

        stored = portal.DESIGN_SETTINGS["investor_deck_scenes"]["s06p01"]
        stored["checksum"] = "0" * 64
        status, blocked = _json_request(
            base + "/api/admin/media/investor-deck/send",
            method="POST",
            token=token,
            payload={"scene_key": "s06p01", "engine_id": "replicate-seedance", "poll_mode": "poll"},
        )
        assert status == 409
        assert "checksum" in blocked["error"].lower()

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert "investor_deck_scenes" not in public
        assert spoken not in json.dumps(public)

        status, saved = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"tagline": tagline_before, "investor_deck_scenes": {"s06p01": {"checksum": "tampered"}}},
        )
        assert status == 200
        assert "s06p01" in portal.DESIGN_SETTINGS.get("investor_deck_scenes", {})
        assert portal.DESIGN_SETTINGS["investor_deck_scenes"]["s06p01"].get("checksum") != "tampered"
        assert portal.DESIGN_SETTINGS.get("solution_video_blueprints") == blueprints_before
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
    finally:
        portal.get_media_generation_service = original
        if scenes_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_scenes", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_scenes"] = scenes_before
        portal.DESIGN_SETTINGS["tagline"] = tagline_before
        portal.DESIGN_SETTINGS["hero_video_id"] = hero_before
        if blueprints_before is None:
            portal.DESIGN_SETTINGS.pop("solution_video_blueprints", None)
        else:
            portal.DESIGN_SETTINGS["solution_video_blueprints"] = blueprints_before
        portal.SESSIONS.pop(token, None)
        portal.SESSIONS.pop(customer, None)
        # The send path flushes the shared ledger file. Put the restored
        # design document back on disk so a dev server does not load the
        # checksum this test zeroed, or the stub clip.
        for job_id, job in list(portal.MEDIA_PROCESSING_JOBS.items()):
            if not isinstance(job, dict):
                continue
            if job.get("requested_by") != "deck-admin":
                continue
            if str(job.get("deck_scene_key") or "") != "s06p01":
                continue
            portal.MEDIA_PROCESSING_JOBS.pop(job_id, None)
            asset_id = str(job.get("generated_asset_id") or "")
            if asset_id:
                portal.MEDIA_ASSETS.pop(asset_id, None)
        try:
            portal.save_ledger_data()
        except Exception:
            pass
        srv.stop()


def test_presentation_is_part_ii_and_a_video_plays_only_when_the_checksum_matches():
    slides = deck_slides()
    specs = slide_specs()
    assert len(specs) == 13
    assert [row["title"] for row in specs] == [slide["title"] for slide in slides]
    plan = compute_plan()
    plan_hash = plan["content_hash"]
    anchor = plan["anchor_book"]["rows"][0]["eoy_in_force"]
    record = assign_slide_media(7, "vid-deck-1", "abc123")
    assert verify_media_assignment(record, 7)
    asset = {
        "type": "video",
        "checksum": "abc123",
        "playback_url": "/media-files/vid-deck-1/office.mp4",
        "name": "Office film",
        "data": "do-not-touch",
    }
    filmed = [
        {"slide_no": 7, "paragraph_no": 2, "in_stream": True, "playback_url": "/clip.mp4",
         "narration": "second", "presenter_label": "Woman, early 30s"},
        {"slide_no": 7, "paragraph_no": 1, "in_stream": False, "playback_url": "/skipped.mp4"},
        {"slide_no": 1, "paragraph_no": 1, "in_stream": True, "playback_url": ""},
    ]
    view = presentation_of(
        plan,
        {"7": record},
        {"vid-deck-1": asset},
        filmed,
        photo_url="/api/business-plan/founder-portrait",
        charts={"in_force": {"svg": "<svg id='in_force'></svg>"}},
    )
    assert view["part"] == "II"
    assert view["slide_count"] == 13
    assert plan["content_hash"] == plan_hash
    assert plan["anchor_book"]["rows"][0]["eoy_in_force"] == anchor
    assert asset["data"] == "do-not-touch"
    assert asset["checksum"] == "abc123"
    market = view["slides"][6]
    assert market["title"] == "Market and expansion"
    assert market["chart_id"] == "in_force"
    assert market["chart_svg"].startswith("<svg")
    assert market["media"]["intact"] is True
    assert market["media"]["playback_url"].endswith("office.mp4")
    assert [clip["paragraph_no"] for clip in market["filmed"]] == [2]
    for spec, slide in zip(specs, view["slides"]):
        assert slide["bullets"] == [_fill(bullet, plan, False).strip() for bullet in spec["bullets"]]
        assert "{" not in "".join(slide["bullets"])
    founder = view["slides"][4]
    assert founder["title"] == "Founder"
    assert founder["photo_url"].endswith("founder-portrait")
    assert view["slides"][0]["photo_url"] == ""
    assert view["watermark"]["images"] == []
    assert view["watermark"]["withheld"] is False
    image = dict(asset, type="image")
    withheld = presentation_of(plan, {"7": record}, {"vid-deck-1": image})
    assert withheld["slides"][6]["media"]["intact"] is False
    assert withheld["slides"][6]["media"]["withheld"] is True
    assert withheld["slides"][6]["media"]["playback_url"] == ""
    assert image["checksum"] == "abc123"
    tampered = dict(record, checksum="0" * 64)
    broken = presentation_of(plan, {"7": tampered}, {"vid-deck-1": asset})
    assert broken["slides"][6]["media"]["playback_url"] == ""
    assert broken["slides"][6]["media"]["withheld"] is True
    assert tampered["checksum"] == "0" * 64
    try:
        assign_slide_media(14, "vid-deck-1", "abc123")
    except InvestorDeckError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("slide 14 was accepted")
    try:
        assign_slide_media(1, "vid-deck-1", "")
    except InvestorDeckError as exc:
        assert "checksum" in str(exc).lower()
    else:
        raise AssertionError("a video without a checksum was sealed")


def test_presentation_page_is_wired_and_does_not_bake_figures():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = (root / "web_portal" / "static" / "investor-deck.html").read_text(encoding="utf-8")
    pitch = (root / "web_portal" / "static" / "pitch-dashboard.html").read_text(encoding="utf-8")
    media = (root / "web_portal" / "static" / "admin-media.html").read_text(encoding="utf-8")
    assert "/api/admin/media/investor-deck/presentation" in page
    assert "/api/investor-deck/presentation?lang=" in page
    assert 'id="deck-lang"' in page
    assert r"/\/investor-deck\.he\.html?$/i" in page
    assert ".deck-assign[hidden]" in page
    assert ".deck-watermark[hidden]" in page
    assert 'id="deck-slide-picks"' in media
    assert "Show selected slides" in media
    assert "4518" not in page
    assert "4,518" not in page
    assert 'href="/investor-deck.html" class="pitch-nav-link">Investor Deck</a>' in pitch
    assert "Present the 13 slides" in pitch
    assert "thirteen-slide investor deck" in pitch
    assert 'data-src="/investor-deck.html?embed=1&amp;edit=1"' in media
    assert "Chapter 2 · 13-slide deck" in media
    assert 'id="deck-watermark"' in page
    assert "Use as watermark background" in page
    assert 'id="deck-upload"' in page
    assert "/api/media?brief=1" in page
    assert "Save this slide's look" in page
    assert "phins-media-library-updated" in media


def test_combine_video_stores_a_pointer_and_leaves_the_library_and_plan_alone():
    srv = _Server()
    srv.start()
    time.sleep(0.2)
    portal = srv.portal
    base = f"http://127.0.0.1:{srv.port}"
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass
    admin = "phins_test_deck_present_admin"
    actuary = "phins_test_deck_present_actuary"
    customer = "phins_test_deck_present_customer"
    portal.SESSIONS[admin] = {
        "username": "deck-present-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    portal.SESSIONS[actuary] = {
        "username": "deck-present-actuary",
        "role": "actuary",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    portal.SESSIONS[customer] = {
        "username": "deck-present-customer",
        "role": "customer",
        "customer_id": "CUST1",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    asset_id = "vid-deck-present"
    payload_bytes = "do-not-touch-library-bytes"
    portal.MEDIA_ASSETS[asset_id] = {
        "id": asset_id,
        "type": "video",
        "name": "Office film",
        "checksum": "a" * 64,
        "url": f"/media-files/{asset_id}/office.mp4",
        "data": payload_bytes,
    }
    portal.MEDIA_ASSETS["img-deck-present"] = {
        "id": "img-deck-present",
        "type": "image",
        "name": "Still",
        "checksum": "b" * 64,
        "url": "/media-files/img-deck-present/still.jpg",
    }
    plan_before = compute_plan()["content_hash"]
    hero_before = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    tagline_before = portal.DESIGN_SETTINGS.get("tagline")
    scenes_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_scenes"))
    media_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_slide_media"))
    updated_before = portal.DESIGN_SETTINGS.get("updated_at")
    try:
        status, denied = _json_request(base + "/api/admin/media/investor-deck/presentation")
        assert status == 403
        status, denied = _json_request(
            base + "/api/admin/media/investor-deck/presentation", token=customer,
        )
        assert status == 403
        status, listing = _json_request(
            base + "/api/admin/media/investor-deck/presentation", token=actuary,
        )
        assert status == 200, listing
        assert listing["slide_count"] == 13
        assert listing["can_assign"] is False
        assert listing["plan"]["content_hash"] == plan_before
        assert listing["plan"]["integrity_all_hold"] is True
        assert "{" not in "".join(listing["slides"][0]["bullets"])
        assert listing["watermark"]["images"] == []
        assert listing["watermark"]["withheld"] is False
        status, blocked = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=actuary,
            payload={"slide_no": 1, "asset_id": asset_id},
        )
        assert status == 403
        assert "investor_deck_slide_media" not in portal.DESIGN_SETTINGS or (
            portal.DESIGN_SETTINGS.get("investor_deck_slide_media") == media_before
        )

        status, image = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=admin,
            payload={"slide_no": 1, "asset_id": "img-deck-present"},
        )
        assert status == 400
        assert "video" in image["error"].lower()

        status, clash = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=admin,
            payload={"slide_no": 1, "asset_id": asset_id, "asset_checksum": "f" * 64},
        )
        assert status == 409
        assert portal.MEDIA_ASSETS[asset_id]["data"] == payload_bytes
        assert portal.MEDIA_ASSETS[asset_id]["checksum"] == "a" * 64

        status, saved = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=admin,
            payload={"slide_no": 1, "asset_id": asset_id},
        )
        assert status == 200, saved
        assert saved["presentation"]["can_assign"] is True
        opening = saved["presentation"]["slides"][0]
        assert opening["media"]["intact"] is True
        assert opening["media"]["playback_url"].endswith("office.mp4")
        assert opening["media"]["name"] == "Office film"
        stored = portal.DESIGN_SETTINGS["investor_deck_slide_media"]["1"]
        assert stored["asset_id"] == asset_id
        assert stored["asset_checksum"] == "a" * 64
        assert verify_media_assignment(stored, 1)
        assert portal.MEDIA_ASSETS[asset_id]["data"] == payload_bytes
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert compute_plan()["content_hash"] == plan_before
        assert portal.DESIGN_SETTINGS.get("investor_deck_scenes") == scenes_before

        status, watched = _json_request(
            base + "/api/admin/media/investor-deck/presentation", token=actuary,
        )
        assert status == 200
        assert watched["slides"][0]["media"]["playback_url"].endswith("office.mp4")
        assert watched["can_assign"] is False

        stored["checksum"] = "0" * 64
        status, withheld = _json_request(
            base + "/api/admin/media/investor-deck/presentation", token=actuary,
        )
        assert withheld["slides"][0]["media"]["withheld"] is True
        assert withheld["slides"][0]["media"]["playback_url"] == ""
        assert portal.DESIGN_SETTINGS["investor_deck_slide_media"]["1"]["checksum"] == "0" * 64
        assert portal.MEDIA_ASSETS[asset_id]["checksum"] == "a" * 64

        portal.DESIGN_SETTINGS["investor_deck_slide_media"]["1"] = stored
        stored["checksum"] = assign_slide_media(1, asset_id, "a" * 64)["checksum"]
        portal.MEDIA_ASSETS[asset_id]["checksum"] = "c" * 64
        status, drifted = _json_request(
            base + "/api/admin/media/investor-deck/presentation", token=admin,
        )
        assert drifted["slides"][0]["media"]["intact"] is False
        assert drifted["slides"][0]["media"]["playback_url"] == ""
        assert portal.DESIGN_SETTINGS["investor_deck_slide_media"]["1"]["asset_checksum"] == "a" * 64
        assert portal.MEDIA_ASSETS[asset_id]["checksum"] == "c" * 64
        assert portal.MEDIA_ASSETS[asset_id]["data"] == payload_bytes
        portal.MEDIA_ASSETS[asset_id]["checksum"] = "a" * 64

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert "investor_deck_slide_media" not in public
        assert payload_bytes not in json.dumps(public)

        status, settings = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=admin,
            payload={
                "tagline": tagline_before,
                "investor_deck_slide_media": {"1": {"checksum": "tampered"}},
            },
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["investor_deck_slide_media"]["1"]["asset_checksum"] == "a" * 64
        assert portal.DESIGN_SETTINGS["investor_deck_slide_media"]["1"]["checksum"] != "tampered"

        status, cleared = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=admin,
            payload={"slide_no": 1, "clear": True},
        )
        assert status == 200, cleared
        assert cleared["presentation"]["slides"][0]["media"]["playback_url"] == ""
        assert cleared["presentation"]["slides"][0]["media"]["withheld"] is False
        assert "1" not in (portal.DESIGN_SETTINGS.get("investor_deck_slide_media") or {})
        assert portal.MEDIA_ASSETS[asset_id]["data"] == payload_bytes
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert compute_plan()["content_hash"] == plan_before
    finally:
        portal.MEDIA_ASSETS.pop(asset_id, None)
        portal.MEDIA_ASSETS.pop("img-deck-present", None)
        if media_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_slide_media", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_slide_media"] = media_before
        if scenes_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_scenes", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_scenes"] = scenes_before
        portal.DESIGN_SETTINGS["tagline"] = tagline_before
        portal.DESIGN_SETTINGS["hero_video_id"] = hero_before
        if updated_before is None:
            portal.DESIGN_SETTINGS.pop("updated_at", None)
        else:
            portal.DESIGN_SETTINGS["updated_at"] = updated_before
        portal.SESSIONS.pop(admin, None)
        portal.SESSIONS.pop(actuary, None)
        portal.SESSIONS.pop(customer, None)
        srv.stop()


def test_watermark_is_library_images_and_a_mismatch_is_omitted():
    plan = compute_plan()
    plan_hash = plan["content_hash"]
    gold = {"type": "image", "checksum": "g" * 64, "playback_url": "/media-files/gold/mark.png", "name": "Gold", "data": "keep-gold"}
    navy = {"type": "image", "checksum": "n" * 64, "playback_url": "/media-files/navy/mark.png", "name": "Navy", "data": "keep-navy"}
    record = assign_watermark([
        {"asset_id": "img-gold", "asset_checksum": "g" * 64},
        {"asset_id": "img-gold", "asset_checksum": "g" * 64},
        {"asset_id": "img-navy", "asset_checksum": "n" * 64},
    ])
    assert verify_watermark(record)
    assert [item["asset_id"] for item in record["images"]] == ["img-gold", "img-navy"]
    view = presentation_of(plan, watermark=record, assets={"img-gold": gold, "img-navy": navy})
    shown = view["watermark"]
    assert shown["intact"] is True
    assert [item["name"] for item in shown["images"]] == ["Gold", "Navy"]
    assert shown["images"][0]["playback_url"].endswith("mark.png")
    assert plan["content_hash"] == plan_hash
    assert gold["data"] == "keep-gold"
    assert navy["data"] == "keep-navy"
    drifted = dict(navy, checksum="z" * 64)
    partial = presentation_of(plan, watermark=record, assets={"img-gold": gold, "img-navy": drifted})
    assert partial["watermark"]["withheld"] is True
    assert partial["watermark"]["images"][0]["intact"] is True
    assert partial["watermark"]["images"][1]["playback_url"] == ""
    assert record["images"][1]["asset_checksum"] == "n" * 64
    assert drifted["data"] == "keep-navy"
    video = dict(gold, type="video")
    refused = presentation_of(plan, watermark=record, assets={"img-gold": video, "img-navy": navy})
    assert refused["watermark"]["images"][0]["withheld"] is True
    assert refused["watermark"]["images"][1]["intact"] is True
    tampered = dict(record, checksum="0" * 64)
    broken = presentation_of(plan, watermark=tampered, assets={"img-gold": gold, "img-navy": navy})
    assert broken["watermark"]["images"] == []
    assert broken["watermark"]["withheld"] is True
    assert tampered["checksum"] == "0" * 64
    try:
        assign_watermark([{"asset_id": f"img-{i}", "asset_checksum": "a" * 8} for i in range(WATERMARK_MAX_IMAGES + 1)])
    except InvestorDeckError as exc:
        assert "at most" in str(exc)
    else:
        raise AssertionError("too many watermark images were sealed")
    try:
        assign_watermark([])
    except InvestorDeckError as exc:
        assert "images" in str(exc).lower()
    else:
        raise AssertionError("an empty watermark was sealed")


def test_watermark_stores_a_pointer_and_leaves_the_library_and_plan_alone():
    srv = _Server()
    srv.start()
    time.sleep(0.2)
    portal = srv.portal
    base = f"http://127.0.0.1:{srv.port}"
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass
    admin = "phins_test_deck_watermark_admin"
    actuary = "phins_test_deck_watermark_actuary"
    portal.SESSIONS[admin] = {
        "username": "deck-watermark-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    portal.SESSIONS[actuary] = {
        "username": "deck-watermark-actuary",
        "role": "actuary",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    gold_bytes = "do-not-touch-gold"
    navy_bytes = "do-not-touch-navy"
    portal.MEDIA_ASSETS["img-mark-gold"] = {
        "id": "img-mark-gold",
        "type": "image",
        "name": "Gold mark",
        "checksum": "d" * 64,
        "url": "/media-files/img-mark-gold/gold.png",
        "data": gold_bytes,
    }
    portal.MEDIA_ASSETS["img-mark-navy"] = {
        "id": "img-mark-navy",
        "type": "image",
        "name": "Navy mark",
        "checksum": "e" * 64,
        "url": "/media-files/img-mark-navy/navy.png",
        "data": navy_bytes,
    }
    portal.MEDIA_ASSETS["vid-mark-film"] = {
        "id": "vid-mark-film",
        "type": "video",
        "name": "Film",
        "checksum": "f" * 64,
        "url": "/media-files/vid-mark-film/film.mp4",
        "data": "do-not-touch-film",
    }
    plan_before = compute_plan()["content_hash"]
    hero_before = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    tagline_before = portal.DESIGN_SETTINGS.get("tagline")
    media_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_slide_media"))
    watermark_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_watermark"))
    updated_before = portal.DESIGN_SETTINGS.get("updated_at")
    path = base + "/api/admin/media/investor-deck/presentation"
    try:
        status, denied = _json_request(
            path, method="POST", token=actuary,
            payload={"watermark": True, "asset_ids": ["img-mark-gold"]},
        )
        assert status == 403
        assert portal.DESIGN_SETTINGS.get("investor_deck_watermark") == watermark_before

        status, video = _json_request(
            path, method="POST", token=admin,
            payload={"watermark": True, "asset_ids": ["vid-mark-film"]},
        )
        assert status == 400
        assert "image" in video["error"].lower()
        assert portal.MEDIA_ASSETS["vid-mark-film"]["data"] == "do-not-touch-film"

        status, clash = _json_request(
            path, method="POST", token=admin,
            payload={"watermark": True, "images": [
                {"asset_id": "img-mark-gold", "asset_checksum": "d" * 64},
                {"asset_id": "img-mark-navy", "asset_checksum": "0" * 64},
            ]},
        )
        assert status == 409
        assert portal.MEDIA_ASSETS["img-mark-gold"]["data"] == gold_bytes
        assert portal.MEDIA_ASSETS["img-mark-navy"]["checksum"] == "e" * 64
        assert portal.DESIGN_SETTINGS.get("investor_deck_watermark") == watermark_before

        status, saved = _json_request(
            path, method="POST", token=admin,
            payload={"watermark": True, "asset_ids": ["img-mark-gold", "img-mark-gold", "img-mark-navy"]},
        )
        assert status == 200, saved
        assert "not changed" in saved["message"]
        mark = saved["presentation"]["watermark"]
        assert mark["intact"] is True
        assert [item["name"] for item in mark["images"]] == ["Gold mark", "Navy mark"]
        assert mark["images"][0]["playback_url"].endswith("gold.png")
        stored = portal.DESIGN_SETTINGS["investor_deck_watermark"]
        assert verify_watermark(stored)
        assert [item["asset_id"] for item in stored["images"]] == ["img-mark-gold", "img-mark-navy"]
        assert portal.MEDIA_ASSETS["img-mark-gold"]["data"] == gold_bytes
        assert portal.MEDIA_ASSETS["img-mark-navy"]["data"] == navy_bytes
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert portal.DESIGN_SETTINGS.get("investor_deck_slide_media") == media_before
        assert compute_plan()["content_hash"] == plan_before
        assert saved["presentation"]["plan"]["content_hash"] == plan_before

        status, watched = _json_request(path, token=actuary)
        assert status == 200
        assert watched["can_assign"] is False
        assert [item["playback_url"] for item in watched["watermark"]["images"]] == [
            "/media-files/img-mark-gold/gold.png",
            "/media-files/img-mark-navy/navy.png",
        ]

        stored["checksum"] = "0" * 64
        status, withheld = _json_request(path, token=actuary)
        assert withheld["watermark"]["withheld"] is True
        assert withheld["watermark"]["images"] == []
        assert portal.DESIGN_SETTINGS["investor_deck_watermark"]["checksum"] == "0" * 64
        assert portal.MEDIA_ASSETS["img-mark-gold"]["data"] == gold_bytes

        stored["checksum"] = assign_watermark(stored["images"])["checksum"]
        portal.MEDIA_ASSETS["img-mark-navy"]["checksum"] = "c" * 64
        status, drifted = _json_request(path, token=admin)
        images = drifted["watermark"]["images"]
        assert images[0]["intact"] is True
        assert images[1]["playback_url"] == ""
        assert images[1]["withheld"] is True
        assert portal.DESIGN_SETTINGS["investor_deck_watermark"]["images"][1]["asset_checksum"] == "e" * 64
        assert portal.MEDIA_ASSETS["img-mark-navy"]["data"] == navy_bytes
        portal.MEDIA_ASSETS["img-mark-navy"]["checksum"] = "e" * 64

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert "investor_deck_watermark" not in public
        assert gold_bytes not in json.dumps(public)
        assert navy_bytes not in json.dumps(public)

        status, settings = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=admin,
            payload={
                "tagline": tagline_before,
                "investor_deck_watermark": {"checksum": "tampered", "images": []},
            },
        )
        assert status == 200
        assert verify_watermark(portal.DESIGN_SETTINGS["investor_deck_watermark"])
        assert portal.DESIGN_SETTINGS["investor_deck_watermark"]["checksum"] != "tampered"

        status, too_many = _json_request(
            path, method="POST", token=admin,
            payload={"watermark": True, "asset_ids": [f"img-missing-{i}" for i in range(WATERMARK_MAX_IMAGES + 1)]},
        )
        assert status == 400
        assert verify_watermark(portal.DESIGN_SETTINGS["investor_deck_watermark"])

        status, cleared = _json_request(
            path, method="POST", token=admin,
            payload={"watermark": True, "clear": True},
        )
        assert status == 200, cleared
        assert cleared["presentation"]["watermark"]["images"] == []
        assert cleared["presentation"]["watermark"]["withheld"] is False
        assert "investor_deck_watermark" not in portal.DESIGN_SETTINGS
        assert portal.MEDIA_ASSETS["img-mark-gold"]["data"] == gold_bytes
        assert portal.DESIGN_SETTINGS.get("investor_deck_slide_media") == media_before
        assert compute_plan()["content_hash"] == plan_before
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
    finally:
        for asset_id in ("img-mark-gold", "img-mark-navy", "vid-mark-film"):
            portal.MEDIA_ASSETS.pop(asset_id, None)
        if watermark_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_watermark", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_watermark"] = watermark_before
        if media_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_slide_media", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_slide_media"] = media_before
        portal.DESIGN_SETTINGS["tagline"] = tagline_before
        portal.DESIGN_SETTINGS["hero_video_id"] = hero_before
        if updated_before is None:
            portal.DESIGN_SETTINGS.pop("updated_at", None)
        else:
            portal.DESIGN_SETTINGS["updated_at"] = updated_before
        portal.SESSIONS.pop(admin, None)
        portal.SESSIONS.pop(actuary, None)
        srv.stop()


def test_slide_chrome_rejects_a_figure_and_a_drifted_image():
    from services.investor_deck_slideshow import assign_chrome, chrome_view, verify_chrome

    plan = compute_plan()
    plan_hash = plan["content_hash"]
    record = assign_chrome(
        3, theme="Quiet navy office", gradient="deep", wash=0.42,
        image_asset_id="img-office", image_checksum="ab12",
    )
    assert verify_chrome(record, 3)
    assert record["wash"] == "0.42"
    asset = {
        "type": "image", "checksum": "ab12", "playback_url": "/media-files/img-office/a.png",
        "name": "Office", "data": "keep-office",
    }
    view = chrome_view(3, record, {"img-office": asset})
    assert view["intact"] is True
    assert view["gradient"] == "deep"
    assert view["image"]["playback_url"].endswith("a.png")
    drifted = dict(asset, checksum="zz")
    withheld = chrome_view(3, record, {"img-office": drifted})
    assert withheld["theme"] == "Quiet navy office"
    assert withheld["image"]["withheld"] is True
    assert withheld["image"]["playback_url"] == ""
    assert record["image_checksum"] == "ab12"
    assert drifted["data"] == "keep-office"
    tampered = dict(record, checksum="0" * 64)
    broken = chrome_view(3, tampered, {"img-office": asset})
    assert broken["withheld"] is True
    assert broken["gradient"] == "letterhead"
    assert tampered["checksum"] == "0" * 64
    assert plan["content_hash"] == plan_hash
    try:
        assign_chrome(1, theme="Seed 6 million")
    except InvestorDeckError as exc:
        assert "figure" in str(exc).lower()
    else:
        raise AssertionError("a theme with a figure was sealed")


def test_library_upload_is_listed_and_slide_chrome_does_not_touch_the_plan():
    srv = _Server()
    srv.start()
    time.sleep(0.2)
    portal = srv.portal
    base = f"http://127.0.0.1:{srv.port}"
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass
    admin = "phins_test_deck_chrome_admin"
    actuary = "phins_test_deck_chrome_actuary"
    portal.SESSIONS[admin] = {
        "username": "deck-chrome-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    portal.SESSIONS[actuary] = {
        "username": "deck-chrome-actuary",
        "role": "actuary",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    tiny = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    plan_before = compute_plan()["content_hash"]
    hero_before = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    tagline_before = portal.DESIGN_SETTINGS.get("tagline")
    chrome_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_slide_chrome"))
    media_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_slide_media"))
    updated_before = portal.DESIGN_SETTINGS.get("updated_at")
    path = base + "/api/admin/media/investor-deck/presentation"
    created_id = ""
    try:
        status, blocked = _json_request(
            path, method="POST", token=actuary,
            payload={"chrome": True, "slide_no": 2, "theme": "Calm office", "gradient": "soft"},
        )
        assert status == 403
        assert portal.DESIGN_SETTINGS.get("investor_deck_slide_chrome") == chrome_before

        status, created = _json_request(
            base + "/api/media", method="POST", token=admin,
            payload={"name": "Office wash", "type": "image", "format": "image/png", "data": tiny, "source": "upload"},
        )
        assert status == 201, created
        created_id = created["asset"]["id"]
        assert created["asset"]["type"] == "image"
        assert created["asset"]["checksum"]
        file_bytes = portal.MEDIA_ASSETS[created_id].get("data")

        status, brief = _json_request(base + "/api/media?brief=1", token=admin)
        assert status == 200, brief
        listed = [item for item in brief["assets"] if item["id"] == created_id]
        assert listed and listed[0]["name"] == "Office wash"
        assert "data" not in listed[0]
        assert file_bytes == portal.MEDIA_ASSETS[created_id].get("data")

        status, saved = _json_request(
            path, method="POST", token=admin,
            payload={
                "chrome": True,
                "slide_no": 2,
                "theme": "Calm office",
                "gradient": "deep",
                "wash": 0.4,
                "image_asset_id": created_id,
            },
        )
        assert status == 200, saved
        assert "not changed" in saved["message"]
        chrome = saved["presentation"]["slides"][1]["chrome"]
        assert chrome["theme"] == "Calm office"
        assert chrome["gradient"] == "deep"
        assert chrome["wash"] == 0.4
        assert chrome["image"]["intact"] is True
        assert chrome["image"]["name"] == "Office wash"
        assert saved["presentation"]["slides"][1]["bullets"]
        assert "{" not in "".join(saved["presentation"]["slides"][1]["bullets"])
        stored = portal.DESIGN_SETTINGS["investor_deck_slide_chrome"]["2"]
        assert stored["image_checksum"] == portal.MEDIA_ASSETS[created_id]["checksum"]
        assert portal.MEDIA_ASSETS[created_id].get("data") == file_bytes
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert portal.DESIGN_SETTINGS.get("investor_deck_slide_media") == media_before
        assert compute_plan()["content_hash"] == plan_before

        status, watched = _json_request(path, token=actuary)
        assert watched["can_assign"] is False
        assert watched["slides"][1]["chrome"]["image"]["intact"] is True

        portal.MEDIA_ASSETS[created_id]["checksum"] = "c" * 64
        status, drifted = _json_request(path, token=admin)
        assert drifted["slides"][1]["chrome"]["theme"] == "Calm office"
        assert drifted["slides"][1]["chrome"]["image"]["withheld"] is True
        assert drifted["slides"][1]["chrome"]["image"]["playback_url"] == ""
        assert portal.DESIGN_SETTINGS["investor_deck_slide_chrome"]["2"]["image_checksum"] != "c" * 64
        portal.MEDIA_ASSETS[created_id]["checksum"] = stored["image_checksum"]

        status, clash = _json_request(
            path, method="POST", token=admin,
            payload={"chrome": True, "slide_no": 2, "image_asset_id": created_id, "image_checksum": "f" * 64},
        )
        assert status == 409
        assert portal.DESIGN_SETTINGS["investor_deck_slide_chrome"]["2"]["theme"] == "Calm office"
        assert portal.MEDIA_ASSETS[created_id].get("data") == file_bytes

        status, public = _json_request(base + "/api/design/settings")
        assert "investor_deck_slide_chrome" not in public
        assert tiny not in json.dumps(public)

        status, settings = _json_request(
            base + "/api/design/settings", method="POST", token=admin,
            payload={"tagline": tagline_before, "investor_deck_slide_chrome": {"2": {"theme": "tampered"}}},
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["investor_deck_slide_chrome"]["2"]["theme"] == "Calm office"

        status, cleared = _json_request(
            path, method="POST", token=admin,
            payload={"chrome": True, "slide_no": 2, "clear": True},
        )
        assert status == 200, cleared
        assert cleared["presentation"]["slides"][1]["chrome"]["theme"] == ""
        assert cleared["presentation"]["slides"][1]["chrome"]["gradient"] == "letterhead"
        assert "2" not in (portal.DESIGN_SETTINGS.get("investor_deck_slide_chrome") or {})
        assert portal.MEDIA_ASSETS[created_id].get("data") == file_bytes
        assert compute_plan()["content_hash"] == plan_before
    finally:
        if created_id:
            portal.MEDIA_ASSETS.pop(created_id, None)
        if chrome_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_slide_chrome", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_slide_chrome"] = chrome_before
        if media_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_slide_media", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_slide_media"] = media_before
        portal.DESIGN_SETTINGS["tagline"] = tagline_before
        portal.DESIGN_SETTINGS["hero_video_id"] = hero_before
        if updated_before is None:
            portal.DESIGN_SETTINGS.pop("updated_at", None)
        else:
            portal.DESIGN_SETTINGS["updated_at"] = updated_before
        portal.SESSIONS.pop(admin, None)
        portal.SESSIONS.pop(actuary, None)
        srv.stop()


def test_hebrew_presentation_uses_the_plan_words_and_a_broken_selection_hides_nothing():
    from services.business_plan_i18n import language_context, translator
    from services.investor_deck_video import (
        assign_visible_slides,
        presentation_of,
        restrict_slides,
        selection_view,
    )

    plan = compute_plan()
    with language_context(translator("he")):
        hebrew = presentation_of(plan)
    assert hebrew["slides"][1]["title"] == "הבעיה"
    for slide in hebrew["slides"]:
        for bullet in slide["bullets"]:
            assert "{" not in bullet
    with language_context(translator("en")):
        english = presentation_of(plan)
    assert english["slides"][1]["title"] == "The problem"
    record = assign_visible_slides([7, 1, 7])
    assert record["slides"] == [1, 7]
    narrowed = restrict_slides(english, record["slides"])
    assert [slide["slide_no"] for slide in narrowed["slides"]] == [1, 7]
    broken = dict(record, checksum="0" * 64)
    withheld = selection_view(broken)
    assert withheld["withheld"] is True
    assert withheld["intact"] is False
    assert withheld["slides"] == list(range(1, 14))
    missing = selection_view(None)
    assert missing["stored"] is False
    assert missing["withheld"] is False
    assert missing["slides"] == list(range(1, 14))


def test_pitch_password_reads_plan_figures_and_checksummed_video(monkeypatch, tmp_path):
    """The ilpitch cookie fills the slides. A share freezes that slide list."""
    import security.confidential_access as ca
    from services.confidential_share_service import (
        get_confidential_share_service,
        reset_confidential_share_service_for_tests,
    )
    from services.document_use_ledger import (
        get_document_use_ledger,
        reset_document_use_ledger_for_tests,
    )

    token_secret = "pitch-open-secret"
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", token_secret)
    monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 32)
    reset_confidential_share_service_for_tests()
    get_confidential_share_service(data_path=str(tmp_path / "shares.json"))
    reset_document_use_ledger_for_tests()
    get_document_use_ledger(data_path=str(tmp_path / "document-use.json"))

    srv = _Server()
    srv.start()
    time.sleep(0.2)
    portal = srv.portal
    base = f"http://127.0.0.1:{srv.port}"
    admin = "phins_test_deck_open_admin"
    media = "phins_test_deck_open_media"
    plan_before = compute_plan()["content_hash"]
    selection_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_visible_slides"))
    media_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("investor_deck_slide_media"))
    tagline_before = portal.DESIGN_SETTINGS.get("tagline")
    updated_before = portal.DESIGN_SETTINGS.get("updated_at")
    access_cookie = f"{ca.ACCESS_COOKIE_NAME}={ca.cookie_value_for_token(token_secret)}"
    share_id = ""
    ledger_path = portal.LEDGER_PERSISTENCE_FILE
    ledger_backup = tmp_path / "ledger-backup.json"
    had_ledger = os.path.isfile(ledger_path)
    if had_ledger:
        ledger_backup.write_bytes(open(ledger_path, "rb").read())
    try:
        _json_request(base + "/api/health")
        portal.MEDIA_ASSETS["vid-open-deck"] = {
            "id": "vid-open-deck",
            "type": "video",
            "checksum": "d" * 64,
            "name": "open-deck.mp4",
        }
        portal.SESSIONS[admin] = {
            "username": "deck-open-admin",
            "role": "admin",
            "customer_id": "",
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
        portal.SESSIONS[media] = {
            "username": "deck-open-media",
            "role": "media",
            "customer_id": "",
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
        status, denied = _json_request(base + "/api/investor-deck/presentation")
        assert status == 401, denied

        status, english = _json_request(
            base + "/api/investor-deck/presentation", cookie=access_cookie,
        )
        assert status == 200, english
        assert english["lang"] == "en"
        assert english["can_assign"] is False
        assert english["slide_count"] == 13
        assert english["slides"][1]["title"] == "The problem"
        assert english["slides"][0]["bullets"]
        for slide in english["slides"]:
            for bullet in slide["bullets"]:
                assert "{" not in bullet
        assert "catalog" not in english

        status, hebrew = _json_request(
            base + "/api/investor-deck/presentation?lang=he", cookie=access_cookie,
        )
        assert status == 200, hebrew
        assert hebrew["lang"] == "he"
        assert hebrew["slides"][1]["title"] == "הבעיה"

        status, assigned = _json_request(
            base + "/api/investor-deck/presentation", token=media,
        )
        assert status == 200, assigned
        assert assigned["can_assign"] is True
        assert len(assigned["catalog"]) == 13

        status, combined = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=media,
            payload={"slide_no": 1, "asset_id": "vid-open-deck"},
        )
        assert status == 200, combined
        playback = combined["presentation"]["slides"][0]["media"]["playback_url"]
        assert playback.startswith("/media-files/vid-open-deck/")
        assert portal.MEDIA_ASSETS["vid-open-deck"]["checksum"] == "d" * 64
        assert "data" not in portal.MEDIA_ASSETS["vid-open-deck"]
        assert "url" not in portal.MEDIA_ASSETS["vid-open-deck"]

        status, picked = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=media,
            payload={"visible_slides": [7, 1]},
        )
        assert status == 200, picked
        assert [slide["slide_no"] for slide in picked["presentation"]["slides"]] == [1, 7]
        assert picked["presentation"]["slides"][0]["media"]["playback_url"].startswith(
            "/media-files/vid-open-deck/"
        )
        assert compute_plan()["content_hash"] == plan_before

        status, narrowed_film = _json_request(
            base + "/api/investor-deck/film", cookie=access_cookie,
        )
        assert status == 200, narrowed_film
        assert "engines" not in narrowed_film
        assert {row["slide_no"] for row in narrowed_film["scenes"]} == {1, 7}
        assert {row["slide_no"] for row in narrowed_film["stream"]} <= {1, 7}
        assert narrowed_film["slide_count"] == 2
        status, lab = _json_request(
            base + "/api/admin/media/investor-deck", token=media,
        )
        assert status == 200, lab
        assert "engines" in lab
        assert len({row["slide_no"] for row in lab["scenes"]}) == 13
        hidden_lines = [
            row["narration"] for row in lab["scenes"] if row["slide_no"] not in (1, 7)
        ]
        assert hidden_lines
        filmed_body = json.dumps(narrowed_film)
        assert hidden_lines[0] not in filmed_body
        hidden_charts = {
            row["chart_id"]
            for row in lab["scenes"]
            if row["slide_no"] not in (1, 7) and row.get("chart_id")
        }
        shown_charts = {
            row["chart_id"]
            for row in lab["scenes"]
            if row["slide_no"] in (1, 7) and row.get("chart_id")
        }
        assert hidden_charts - shown_charts
        assert set(narrowed_film["charts"]) <= shown_charts

        composition = portal.PortalHandler._investor_deck_link_composition(object())
        assert composition["kind"] == "investor_deck"
        assert composition["visible_slides"] == [1, 7]
        status, created = _json_request(
            base + "/api/confidential/shares",
            method="POST",
            token=admin,
            payload={
                "path": "/investor-deck.he.html",
                "password": "deck-open-1",
                "max_uses": 3,
                "label": "Deck guest",
                "nda_required": False,
            },
        )
        assert status == 201, created
        share = created["share"]
        share_id = share["id"]
        assert share["nda_required"] is False
        assert share["lang"] == "he"
        assert share["scope"] == "/investor-deck.html"
        assert share["composition"]["visible_slides"] == [1, 7]
        assert share["composition"]["kind"] == "investor_deck"

        status, cleared = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=media,
            payload={"selection": True, "clear": True},
        )
        assert status == 200, cleared
        assert cleared["presentation"]["slide_count"] == 13

        status, live = _json_request(
            base + "/api/investor-deck/presentation", cookie=access_cookie,
        )
        assert status == 200, live
        assert live["slide_count"] == 13
        status, live_film = _json_request(
            base + "/api/investor-deck/film", cookie=access_cookie,
        )
        assert status == 200, live_film
        assert live_film["slide_count"] == 13
        assert "engines" not in live_film

        share_cookie = (
            f"{ca.SHARE_COOKIE_NAME}="
            + ca.mint_share_cookie(share_id=share_id, path="/investor-deck.he.html")
        )
        status, frozen = _json_request(
            base + "/api/investor-deck/presentation?lang=he", cookie=share_cookie,
        )
        assert status == 200, frozen
        assert [slide["slide_no"] for slide in frozen["slides"]] == [1, 7]
        assert frozen["lang"] == "he"
        assert frozen["selection"]["frozen"] is True
        assert frozen["slides"][0]["media"]["playback_url"].startswith("/media-files/vid-open-deck/")
        status, frozen_film = _json_request(
            base + "/api/investor-deck/film?lang=he", cookie=share_cookie,
        )
        assert status == 200, frozen_film
        assert frozen_film["lang"] == "he"
        assert frozen_film["selection"]["frozen"] is True
        assert {row["slide_no"] for row in frozen_film["scenes"]} == {1, 7}
        assert {row["slide_no"] for row in frozen_film["stream"]} <= {1, 7}
        assert "engines" not in frozen_film
        hidden_hebrew = next(
            row["narration"] for row in frozen_film["scenes"] if row["slide_no"] == 1
        )
        assert hidden_hebrew
        withheld_line = next(
            row["narration"] for row in lab["scenes"] if row["slide_no"] == 3
        )
        assert withheld_line not in json.dumps(frozen_film)

        stored = json.loads((tmp_path / "shares.json").read_text(encoding="utf-8"))
        stored["shares"][share_id]["composition"]["selection_checksum"] = "0" * 64
        (tmp_path / "shares.json").write_text(json.dumps(stored), encoding="utf-8")
        status, refused = _json_request(
            base + "/api/investor-deck/presentation", cookie=share_cookie,
        )
        assert status == 409, refused
        status, refused_film = _json_request(
            base + "/api/investor-deck/film", cookie=share_cookie,
        )
        assert status == 409, refused_film
        status, still_live = _json_request(
            base + "/api/investor-deck/presentation", cookie=access_cookie,
        )
        assert status == 200, still_live
        assert still_live["slide_count"] == 13

        portal.DESIGN_SETTINGS["investor_deck_visible_slides"] = {
            "slides": [1, 2],
            "checksum": "0" * 64,
        }
        try:
            portal.PortalHandler._investor_deck_link_composition(object())
        except ValueError as exc:
            assert "seal" in str(exc).lower()
        else:
            raise AssertionError("a broken slide seal was shared")
        status, broken_share = _json_request(
            base + "/api/confidential/shares",
            method="POST",
            token=admin,
            payload={
                "path": "/investor-deck.html",
                "password": "deck-open-1",
                "max_uses": 1,
                "label": "Deck guest",
            },
        )
        assert status == 400, broken_share
        status, shown = _json_request(
            base + "/api/investor-deck/presentation", cookie=access_cookie,
        )
        assert status == 200, shown
        assert shown["slide_count"] == 13
        assert shown["selection"]["withheld"] is True
        status, shown_film = _json_request(
            base + "/api/investor-deck/film", cookie=access_cookie,
        )
        assert status == 200, shown_film
        assert shown_film["slide_count"] == 13
        assert shown_film["selection"]["withheld"] is True
        assert "engines" not in shown_film

        class _Frozen:
            def _share_composition(self):
                return {
                    "kind": "investor_deck",
                    "visible_slides": [1, 7],
                    "selection_checksum": "0" * 64,
                }

        try:
            portal.PortalHandler._investor_deck_frozen_slides(_Frozen())
        except LookupError:
            pass
        else:
            raise AssertionError("a broken frozen snapshot was accepted")

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200, public
        assert "investor_deck_visible_slides" not in public

        sealed = portal.DESIGN_SETTINGS["investor_deck_visible_slides"]["checksum"]
        status, settings = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=admin,
            payload={
                "tagline": tagline_before,
                "investor_deck_visible_slides": {"slides": [3], "checksum": "e" * 64},
            },
        )
        assert status == 200, settings
        assert portal.DESIGN_SETTINGS["investor_deck_visible_slides"]["checksum"] == sealed

        status, restored = _json_request(
            base + "/api/admin/media/investor-deck/presentation",
            method="POST",
            token=admin,
            payload={"selection": True, "clear": True},
        )
        assert status == 200, restored
        assert restored["presentation"]["slide_count"] == 13
        assert "investor_deck_visible_slides" not in portal.DESIGN_SETTINGS
        assert compute_plan()["content_hash"] == plan_before
    finally:
        portal.MEDIA_ASSETS.pop("vid-open-deck", None)
        if selection_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_visible_slides", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_visible_slides"] = selection_before
        if media_before is None:
            portal.DESIGN_SETTINGS.pop("investor_deck_slide_media", None)
        else:
            portal.DESIGN_SETTINGS["investor_deck_slide_media"] = media_before
        portal.DESIGN_SETTINGS["tagline"] = tagline_before
        if updated_before is None:
            portal.DESIGN_SETTINGS.pop("updated_at", None)
        else:
            portal.DESIGN_SETTINGS["updated_at"] = updated_before
        portal.SESSIONS.pop(admin, None)
        portal.SESSIONS.pop(media, None)
        reset_confidential_share_service_for_tests()
        reset_document_use_ledger_for_tests()
        if had_ledger:
            open(ledger_path, "wb").write(ledger_backup.read_bytes())
        elif os.path.isfile(ledger_path):
            os.remove(ledger_path)
        srv.stop()
