"""Solution video blueprints stay affiliated, editable, and off the public slot."""

import copy
import json
import threading
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from services.solution_video_blueprints import (
    SOLUTION_KEYS,
    SOLUTION_OUTLINES,
    SPOKEN_WORD_BUDGET,
    apply_blueprint_edit,
    blueprint_checksum,
    canonical_narration,
    fit_spoken_line,
    fresh_blueprint,
    growth_blueprint,
    prompt_override,
    verify_blueprint,
)


SOLUTIONS_HTML = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "solutions.html"


class _OutlineParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._divs = []
        self._capture = False
        self._buf = []
        self.found = {}

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag == "div":
            self._divs.append(ad.get("data-preview") or None)
        if tag == "li" and self._current():
            self._capture = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "li" and self._capture:
            text = " ".join("".join(self._buf).split())
            key = self._current()
            if key and text:
                self.found.setdefault(key, []).append(text)
            self._capture = False
        elif tag == "div" and self._divs:
            self._divs.pop()

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)

    def _current(self):
        for key in reversed(self._divs):
            if key:
                return key
        return ""


def _page_outlines():
    parser = _OutlineParser()
    parser.feed(SOLUTIONS_HTML.read_text(encoding="utf-8"))
    return parser.found


def test_blueprint_source_matches_the_public_solution_page():
    page = _page_outlines()
    assert set(page) == set(SOLUTION_KEYS)
    for key, outline in SOLUTION_OUTLINES.items():
        assert page[key] == outline["bullets"]


def test_edit_keeps_canonical_bullets_and_checksum():
    saved = apply_blueprint_edit(
        "billing",
        None,
        narration="Premium billing stays aligned with the ledger.",
        theme="Quiet navy ledger room",
        reference_image_asset_id="media-abc123",
    )
    assert saved["source_bullets"] == SOLUTION_OUTLINES["billing"]["bullets"]
    assert saved["narration"] == "Premium billing stays aligned with the ledger."
    assert verify_blueprint(saved)
    saved["narration"] = "tampered"
    assert not verify_blueprint(saved)
    reset = apply_blueprint_edit("billing", saved, reset_text=True)
    assert reset["narration"] == canonical_narration("billing")
    assert verify_blueprint(reset)
    assert fresh_blueprint("billing")["checksum"] == blueprint_checksum(fresh_blueprint("billing"))


def test_solution_send_drops_a_non_replicate_model_id():
    assert portal.solution_replicate_model("veo-3.1-generate-preview") == ""
    assert portal.solution_replicate_model("kling-v2.6-pro") == ""
    assert portal.solution_replicate_model("google/veo-3.1-fast") == "google/veo-3.1-fast"
    assert portal.solution_replicate_model("") == ""


def test_library_image_file_is_inlined_for_replicate(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(
        __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    asset_id = "media-solution-ref"
    portal.MEDIA_ASSETS[asset_id] = {
        "id": asset_id,
        "type": "image",
        "format": "image/png",
        "file_path": str(image),
        "url": f"/media-files/{asset_id}/shot.png",
        "data": "",
    }
    try:
        payload = portal.build_video_job_reference_image_data_url(asset_id)
    finally:
        portal.MEDIA_ASSETS.pop(asset_id, None)
    assert payload.startswith("data:image/png;base64,")
    assert "/media-files/" not in payload


def test_downloaded_video_thumbnail_is_a_frame_and_leaves_the_file_unchanged(tmp_path):
    import hashlib
    import subprocess

    film = tmp_path / "film.mp4"
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x180:d=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1", str(film),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    digest = hashlib.sha256(film.read_bytes()).hexdigest()
    asset = {
        "id": "media-frame",
        "name": "film.mp4",
        "type": "video",
        "file_path": str(film),
        "checksum": digest,
        "metadata": {},
    }
    portal.attach_generated_video_thumbnail(asset)
    assert asset["checksum"] == digest
    assert hashlib.sha256(film.read_bytes()).hexdigest() == digest
    assert asset["thumbnail"].startswith("data:image/jpeg;base64,")
    assert asset["metadata"]["generated_poster"] == "frame"


def test_growth_agent_can_play_a_stored_solution_film():
    admin = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"
    media = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin-media.html"
    admin_html = admin.read_text(encoding="utf-8")
    media_html = media.read_text(encoding="utf-8")
    assert "function playSolutionFilm" in admin_html
    assert "function replicateModelForSolutionSend" in admin_html
    assert "provider: 'replicate'" in admin_html
    assert "poll_mode: 'poll'" in admin_html
    assert "previewMedia('${safeId}')\">${media.type === 'video' ? 'Play' : 'View'}" in media_html


def test_spoken_line_stops_on_a_sentence_inside_eight_seconds():
    long_line = (
        "Premium billing stays aligned with the ledger. "
        "Every charge remains traceable to the policy. "
        "This extra sentence is the one that would run past eight seconds of calm speech."
    )
    fitted = fit_spoken_line(long_line)
    assert fitted.endswith(".")
    assert "extra sentence" not in fitted
    assert len(fitted.split()) <= SPOKEN_WORD_BUDGET
    # A single sentence is never chopped, even when it is longer than the budget.
    whole = "One uninterrupted sentence that is deliberately longer than eighteen words so the cut would land in the middle of the thought."
    kept = fit_spoken_line(whole)
    assert kept == whole
    assert "middle of the thought" in kept
    for key in SOLUTION_KEYS:
        spoken = canonical_narration(key)
        bullets = SOLUTION_OUTLINES[key]["bullets"]
        full = " ".join(f"{bullet.rstrip('.')}." for bullet in bullets)
        assert spoken
        assert spoken.endswith((".", "!", "?"))
        assert full.startswith(spoken)
        words = spoken.split()
        sentences = [part for part in spoken.split(".") if part.strip()]
        if len(sentences) > 1:
            assert len(words) <= SPOKEN_WORD_BUDGET
        brief = growth_blueprint({"title": key, "narration": full, "theme": "", "solution_key": key})
        assert brief["storyboard"][0] == spoken
        direction = prompt_override({"narration": full, "theme": "Quiet desk", "reference_image_asset_id": ""})
        assert "no readable text" in direction
        assert "On-screen" not in direction
        assert spoken in direction
        assert direction.rstrip().endswith('"')


class _Server(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
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
                "model": "google/veo-3.1-fast",
                "models": ["google/veo-3.1-fast"],
            },
            "gemini": {"enabled": False, "label": "Gemini", "models": []},
            "kling": {"enabled": False, "label": "Kling", "models": []},
        }

    def submit_video_generation(self, **kwargs):
        self.submissions.append(kwargs)
        return {
            "provider": "replicate",
            "provider_job_id": "pred-solution-1",
            "status": "queued",
            "message": "Stub accepted the solution blueprint.",
            "provider_state": {},
        }

    def poll_video_generation(self, **kwargs):
        return {
            "status": "completed",
            "message": "Stub stored the solution film.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": "https://cdn.example.com/generated/solution.mp4",
            "duration": 8,
            "provider_state": {},
        }

    def download_generated_video(self, **kwargs):
        return {
            "data_url": "data:video/mp4;base64,c3R1Yi12aWRlby1ieXRlcw==",
            "content_type": "video/mp4",
            "size": 16,
        }


def _inject(token, role="admin"):
    portal.SESSIONS[token] = {
        "username": "blueprint-admin",
        "role": role,
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }


def test_solution_blueprint_send_stores_a_library_film_without_replacing_the_page():
    srv = _Server()
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{srv.port}"
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass
    token = "phins_test_solution_blueprint_token"
    _inject(token)
    stub = _ReplicateStub()
    original = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub
    tagline_before = portal.DESIGN_SETTINGS.get("tagline")
    blueprints_before = copy.deepcopy(portal.DESIGN_SETTINGS.get("solution_video_blueprints"))
    assets_before = set(portal.MEDIA_ASSETS)
    jobs_before = set(portal.MEDIA_PROCESSING_JOBS)
    theater_before = {
        key: portal.DESIGN_SETTINGS.get(portal.solutions_theater_slot_key(key), "")
        for key in SOLUTION_KEYS
    }
    hero_before = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    portal.MEDIA_ASSETS["media-shot1"] = {
        "id": "media-shot1",
        "name": "actuarial-desk.png",
        "type": "image",
        "data": "data:image/png;base64,iVBORw0KGgo=",
    }
    try:
        status, denied = _json_request(base + "/api/admin/media/solution-blueprints")
        assert status == 403
        assert denied["error"]

        status, listing = _json_request(base + "/api/admin/media/solution-blueprints", token=token)
        assert status == 200
        assert listing["total"] == len(SOLUTION_KEYS)
        by_key = {item["solution_key"]: item for item in listing["blueprints"]}
        assert by_key["actuarial_investments"]["integrity_ok"] is True
        assert by_key["actuarial_investments"]["replaces_public_film"] is False

        status, saved = _json_request(
            base + "/api/admin/media/solution-blueprints",
            method="POST",
            token=token,
            payload={
                "solution_key": "actuarial_investments",
                "narration": "Inside Actuarial and Investments. Tables, reserves, and simulations stay first-class.",
                "theme": "Quiet navy actuarial desk",
                "reference_image_asset_id": "media-shot1",
            },
        )
        assert status == 200, saved
        assert saved["blueprint"]["checksum"]
        assert saved["blueprint"]["source_bullets"] == SOLUTION_OUTLINES["actuarial_investments"]["bullets"]
        assert portal.DESIGN_SETTINGS.get("solutions_theater_actuarial_investments_id", "") == theater_before["actuarial_investments"]

        status, bad_image = _json_request(
            base + "/api/admin/media/solution-blueprints",
            method="POST",
            token=token,
            payload={
                "solution_key": "billing",
                "narration": "Billing stays traceable.",
                "reference_image_asset_id": "missing-shot",
            },
        )
        assert status == 400
        assert "image" in bad_image["error"].lower()

        status, sent = _json_request(
            base + "/api/admin/media/solution-blueprints/send",
            method="POST",
            token=token,
            payload={
                "solution_key": "actuarial_investments",
                "provider": "replicate",
                "provider_model": "veo-3.1-generate-preview",
                "auto_publish_to_hero": True,
            },
        )
        assert status == 202, sent
        assert sent["auto_publish_to_hero"] is False
        assert sent["job"]["auto_publish_to_hero"] is False
        assert sent["job"]["solution_key"] == "actuarial_investments"
        assert sent["job"]["campaign_id"] == "SOL-actuarial_investments"
        assert stub.submissions
        prompt = stub.submissions[0]["prompt"]
        assert "Inside Actuarial and Investments" in prompt
        assert "Quiet navy actuarial desk" in prompt
        assert "no readable text" in prompt
        assert "complete sentence" in prompt
        assert "On-screen disclaimer" not in prompt
        assert "not personalized insurance" not in prompt
        assert stub.submissions[0]["duration_seconds"] == 8
        assert stub.submissions[0]["model"] == ""
        assert stub.submissions[0]["provider"] == "replicate"
        assert stub.submissions[0]["image_data_url"].startswith("data:image/png")
        assert portal.DESIGN_SETTINGS.get("hero_video_id", "") == hero_before
        assert {
            key: portal.DESIGN_SETTINGS.get(portal.solutions_theater_slot_key(key), "")
            for key in SOLUTION_KEYS
        } == theater_before

        asset_id = ""
        for _ in range(30):
            time.sleep(0.1)
            status, again = _json_request(base + "/api/admin/media/solution-blueprints", token=token)
            assert status == 200
            item = next(row for row in again["blueprints"] if row["solution_key"] == "actuarial_investments")
            asset_id = item.get("last_asset_id") or ""
            if asset_id and item["integrity_ok"]:
                break
        assert asset_id
        asset = portal.MEDIA_ASSETS[asset_id]
        assert asset["type"] == "video"
        assert asset["checksum"]
        assert asset["metadata"]["solution_key"] == "actuarial_investments"
        assert asset["metadata"]["generated_from"] == "solution_video_blueprint"
        assert item.get("playback_url", "").startswith("data:video/mp4")
        assert asset["metadata"]["blueprint_checksum"] == saved["blueprint"]["checksum"]
        assert portal.DESIGN_SETTINGS.get("solutions_theater_actuarial_investments_id", "") == ""

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert "solution_video_blueprints" not in public
        assert "Quiet navy actuarial desk" not in json.dumps(public)

        status, duplicate = _json_request(
            base + "/api/admin/media/solution-blueprints/send",
            method="POST",
            token=token,
            payload={"solution_key": "actuarial_investments", "provider": "replicate"},
        )
        assert status == 200
        assert duplicate["deduplicated"] is True
        assert len(stub.submissions) == 1

        stored = portal.DESIGN_SETTINGS["solution_video_blueprints"]["actuarial_investments"]
        stored["narration"] = "tampered narration"
        status, refused = _json_request(
            base + "/api/admin/media/solution-blueprints/send",
            method="POST",
            token=token,
            payload={"solution_key": "actuarial_investments", "provider": "replicate", "force": True},
        )
        assert status == 409
        assert len(stub.submissions) == 1

        status, settings = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"tagline": "Blueprint integrity holds"},
        )
        assert status == 200
        assert "actuarial_investments" in portal.DESIGN_SETTINGS["solution_video_blueprints"]
        assert portal.DESIGN_SETTINGS["tagline"] == "Blueprint integrity holds"
    finally:
        portal.get_media_generation_service = original
        for asset_id in list(portal.MEDIA_ASSETS):
            if asset_id not in assets_before:
                portal.MEDIA_ASSETS.pop(asset_id, None)
        portal.MEDIA_ASSETS.pop("media-shot1", None)
        for job_id in list(portal.MEDIA_PROCESSING_JOBS):
            if job_id not in jobs_before:
                portal.MEDIA_PROCESSING_JOBS.pop(job_id, None)
        if blueprints_before is None:
            portal.DESIGN_SETTINGS.pop("solution_video_blueprints", None)
        else:
            portal.DESIGN_SETTINGS["solution_video_blueprints"] = blueprints_before
        portal.DESIGN_SETTINGS["tagline"] = tagline_before
        portal.save_ledger_data()
        srv.stop()
