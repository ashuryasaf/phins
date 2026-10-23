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
    catalog,
    choose_presenter,
    clip_is_scene_length,
    fill_narration,
    fresh_scene,
    prompt_override,
    scene_view,
    seal_for_send,
    spec_for,
    stream_of,
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
