"""Investor-deck scenes stay sealed to the plan and play only when filmed."""

import copy
import json
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
    assign_slide_media,
    catalog,
    choose_presenter,
    clip_is_scene_length,
    fill_narration,
    fresh_scene,
    presentation_of,
    prompt_override,
    scene_view,
    seal_for_send,
    slide_specs,
    spec_for,
    stream_of,
    verify_media_assignment,
    verify_scene,
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
    again = choose_presenter(used, random.Random(1), exclude=used[0])
    assert again["id"] != used[0]


def test_only_a_matching_clip_enters_the_stream():
    plan = compute_plan()
    spec = spec_for("s06p01")
    sealed = seal_for_send("s06p01", None, plan, used_presenter_ids=[], rng=random.Random(2))
    assert verify_scene(sealed, spec)
    assert sealed["sealed_narration"] == fill_narration(spec["template"], plan)
    assert sealed["presenter_id"]
    direction = prompt_override(sealed)
    assert sealed["sealed_narration"] in direction
    assert "no readable text" in direction
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
    assert kept["narration"] == sealed["sealed_narration"]
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
    assert spoken_hash["figures_current"] is False
    assert spoken_hash["in_stream"] is False
    sealed_hash["last_job_id"] = "job-2"
    dropped = seal_for_send("s13p03", sealed_hash, shifted, used_presenter_ids=[], rng=random.Random(4))
    assert dropped["sealed_narration"] != sealed_hash["sealed_narration"]
    assert dropped["sealed_plan_hash"] == shifted["content_hash"]
    assert dropped["last_asset_id"] == ""
    assert dropped["asset_checksum"] == ""
    assert dropped["last_job_id"] == ""


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
        spoken = next(row for row in slide_six if row["paragraph_no"] == 1)["narration"]
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
    assert "4518" not in page
    assert "4,518" not in page
    assert 'href="/investor-deck.html" class="pitch-nav-link">Investor Deck</a>' in pitch
    assert "Present the 13 slides" in pitch
    assert "thirteen-slide investor deck" in pitch
    assert 'data-src="/investor-deck.html?embed=1&amp;edit=1"' in media
    assert "Chapter 2 · 13-slide deck" in media


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
