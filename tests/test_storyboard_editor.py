"""Storyboard editor: scene chain, Replicate handoff, and checksum integrity."""

from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
import threading

import pytest

import web_portal.api_extensions as api_extensions
from services.media_generation_service import MediaGenerationService
from services.storyboard_editor import (
    DEFAULT_SCENE_SECONDS,
    StoryboardConflict,
    StoryboardEditor,
    StoryboardIntegrityError,
    StoryboardProviderError,
    StoryboardValidationError,
    VEO_DURATIONS,
    build_slide,
    concatenate_videos,
    document_sha256,
    duration_renders_exactly,
    extract_last_frame_png,
    reset_storyboard_editor,
    seal_reference,
    split_script,
)
from services.video_agents_service import BATCH_PIPELINE_TYPES, SUPPORTED_PIPELINE_TYPES

# 1x1 PNG.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PNG_URL = "data:image/png;base64," + base64.b64encode(_PNG).decode("ascii")
_PNG_SHA = hashlib.sha256(_PNG).hexdigest()

_PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _opening():
    return seal_reference(data_url=_PNG_URL, label="opening")


def _editor():
    return StoryboardEditor()


def test_script_splits_into_eight_second_scenes():
    scenes = split_script("Scene 1: Open on the desk.\n\nScene 2: Show the policy card.")
    assert scenes == ["Open on the desk.", "Show the policy card."]
    board = _editor().create(
        title="Care ad",
        purpose="advertisement",
        script="First line of the offer.\n\nSecond line of the offer.",
        opening_reference=_opening(),
        surface="media",
        created_by="admin",
    )
    assert [scene["duration_seconds"] for scene in board["scenes"]] == [
        DEFAULT_SCENE_SECONDS,
        DEFAULT_SCENE_SECONDS,
    ]
    assert DEFAULT_SCENE_SECONDS == 8
    assert board["scenes"][0]["resolved_start_sha256"] == _PNG_SHA
    assert board["scenes"][1]["resolved_start_sha256"] == ""
    assert board["integrity"]["chain_ok"] is False
    assert board["integrity_ok"] if "integrity_ok" in board else document_sha256(board) == board["integrity"]["document_sha256"]


def test_end_screenshot_becomes_the_next_scenes_opening():
    editor = _editor()
    board = editor.create(
        purpose="story",
        script="Scene 1: Dawn.\nScene 2: The wallet.",
        opening_reference=_opening(),
        surface="video-agents",
    )
    rendered = editor.render_scene(
        board["id"],
        1,
        expected_sha256=board["integrity"]["document_sha256"],
        submitter=lambda params: {"id": "job-1", "status": "queued"},
        replicate_enabled=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="admin",
    )["storyboard"]
    sealed = editor.record_end_frame(
        board["id"],
        1,
        expected_sha256=rendered["integrity"]["document_sha256"],
        video_job_id="job-1",
        image_bytes=_PNG_B,
        image_mime="image/png",
        source="extracted",
    )
    end_sha = sealed["scenes"][0]["end_screenshot"]["sha256"]
    assert end_sha == hashlib.sha256(_PNG_B).hexdigest()
    assert sealed["scenes"][1]["resolved_start_sha256"] == end_sha
    assert sealed["scenes"][1]["reference_mode"] == "chain"
    slide = build_slide(sealed)
    assert slide["frames"][0]["role"] == "opening"
    assert slide["frames"][1]["sha256"] == end_sha
    assert slide["frames"][1]["hands_off_to_scene"] == 2
    assert slide["slide_sha256"] == sealed["integrity"]["slide_sha256"]


def test_chosen_scene_reference_does_not_follow_the_previous_still():
    editor = _editor()
    chosen = seal_reference(raw=_PNG_B, mime="image/png", label="scene 2")
    board = editor.create(
        purpose="insurance_agent",
        scenes=[
            {"script": "Meet the agent.", "duration_seconds": 8},
            {
                "script": "Show the card.",
                "duration_seconds": 8,
                "reference_mode": "chosen",
                "chosen_reference": chosen,
            },
        ],
        opening_reference=_opening(),
        surface="solutions",
    )
    assert board["scenes"][1]["resolved_start_sha256"] == chosen["sha256"]
    rendered = editor.render_scene(
        board["id"], 1,
        expected_sha256=board["integrity"]["document_sha256"],
        submitter=lambda params: {"id": "job-a", "status": "processing"},
        replicate_enabled=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="media",
    )["storyboard"]
    sealed = editor.record_end_frame(
        board["id"], 1,
        expected_sha256=rendered["integrity"]["document_sha256"],
        video_job_id="job-a",
        image_bytes=_PNG,
        image_mime="image/png",
    )
    assert sealed["scenes"][1]["resolved_start_sha256"] == chosen["sha256"]
    assert sealed["scenes"][1]["resolved_start_sha256"] != sealed["scenes"][0]["end_screenshot"]["sha256"]


def test_bad_end_frame_checksum_does_not_advance_the_chain():
    editor = _editor()
    board = editor.create(
        purpose="disclaimer",
        scenes=[{"script": "Read the disclaimer.", "duration_seconds": 8}],
        opening_reference=_opening(),
    )
    rendered = editor.render_scene(
        board["id"], 1,
        expected_sha256=board["integrity"]["document_sha256"],
        submitter=lambda params: {"id": "job-d", "status": "queued"},
        replicate_enabled=True,
        provider_model="google/veo-3.1",
        submitted_by="admin",
    )["storyboard"]
    with pytest.raises(StoryboardIntegrityError):
        editor.record_end_frame(
            board["id"], 1,
            expected_sha256=rendered["integrity"]["document_sha256"],
            video_job_id="job-d",
            image_bytes=_PNG_B,
            image_mime="image/png",
            claimed_sha256="ab" * 32,
        )
    fresh = editor.get(board["id"])
    assert fresh["scenes"][0]["end_screenshot"] is None
    assert fresh["integrity"]["document_sha256"] == rendered["integrity"]["document_sha256"]


def test_stale_hash_refuses_the_write():
    editor = _editor()
    board = editor.create(purpose="billing", script="Your bill is 120.", opening_reference=_opening())
    with pytest.raises(StoryboardConflict):
        editor.update(board["id"], expected_sha256="0" * 64, title="Changed")
    assert editor.get(board["id"])["title"] == board["title"]


def test_tampered_document_is_reported_and_not_repaired():
    editor = _editor()
    board = editor.create(purpose="policy_information", script="The term is one year.", opening_reference=_opening())
    stored = editor.get(board["id"])
    stored["integrity"]["document_sha256"] = "f" * 64
    editor._store[board["id"]] = stored
    report = editor.verify(board["id"])
    assert report["ok"] is False
    assert report["document_sha256"] != report["stored_document_sha256"]
    with pytest.raises(StoryboardIntegrityError):
        editor.render_scene(
            board["id"], 1,
            expected_sha256="f" * 64,
            submitter=lambda params: (_ for _ in ()).throw(AssertionError("must not submit")),
            replicate_enabled=True,
            provider_model="google/veo-3.1-fast",
            submitted_by="admin",
        )
    assert editor.get(board["id"])["opening_reference"]["sha256"] == _PNG_SHA


def test_duration_must_match_the_replicate_model_exactly():
    for model, seconds in (
        ("google/veo-3.1-fast", 8),
        ("google/veo-3.1-fast", 10),
        ("google/veo-3.1-fast", 4),
        ("bytedance/seedance-2.0", 10),
        ("bytedance/seedance-2.0", 8),
        ("bytedance/seedance-2.0", 3),
    ):
        snapped = MediaGenerationService._replicate_duration(model, seconds)
        assert duration_renders_exactly(model, seconds) is (snapped == seconds)
    assert 8 in VEO_DURATIONS
    editor = _editor()
    board = editor.create(
        purpose="advertisement",
        scenes=[{"script": "Ten second cut.", "duration_seconds": 10}],
        opening_reference=_opening(),
        provider_model="google/veo-3.1-fast",
    )
    with pytest.raises(StoryboardIntegrityError) as exc:
        editor.render_scene(
            board["id"], 1,
            expected_sha256=board["integrity"]["document_sha256"],
            submitter=lambda params: (_ for _ in ()).throw(AssertionError("must not submit")),
            replicate_enabled=True,
            provider_model="google/veo-3.1-fast",
            submitted_by="admin",
        )
    assert "not an exact duration" in str(exc.value)
    assert editor.get(board["id"])["scenes"][0]["status"] == "draft"
    seedance = editor.create(
        purpose="advertisement",
        scenes=[{"script": "Ten second cut.", "duration_seconds": 10}],
        opening_reference=_opening(),
        provider_model="bytedance/seedance-2.0",
    )
    calls = []
    rendered = editor.render_scene(
        seedance["id"], 1,
        expected_sha256=seedance["integrity"]["document_sha256"],
        submitter=lambda params: calls.append(params) or {"id": "job-s", "status": "queued"},
        replicate_enabled=True,
        provider_model="bytedance/seedance-2.0",
        submitted_by="admin",
    )["storyboard"]
    assert calls[0]["provider"] == "replicate"
    assert calls[0]["duration_seconds"] == 10
    assert calls[0]["image_data_url"].startswith("data:image/png")
    assert "Ten second cut." in calls[0]["prompt_override"]
    assert _PNG_SHA in calls[0]["prompt_override"]
    assert rendered["scenes"][0]["video_job_id"] == "job-s"


def test_scene_two_cannot_render_before_the_end_still_exists():
    editor = _editor()
    board = editor.create(
        purpose="claims",
        script="Gather the documents.\n\nExplain the review.",
        opening_reference=_opening(),
    )
    with pytest.raises(StoryboardIntegrityError, match="previous scene"):
        editor.render_scene(
            board["id"], 2,
            expected_sha256=board["integrity"]["document_sha256"],
            submitter=lambda params: (_ for _ in ()).throw(AssertionError("must not submit")),
            replicate_enabled=True,
            provider_model="google/veo-3.1-fast",
            submitted_by="admin",
        )


def test_replicate_disabled_does_not_submit():
    editor = _editor()
    board = editor.create(purpose="underwriting", script="Evidence list.", opening_reference=_opening())
    with pytest.raises(StoryboardProviderError):
        editor.render_scene(
            board["id"], 1,
            expected_sha256=board["integrity"]["document_sha256"],
            submitter=lambda params: (_ for _ in ()).throw(AssertionError("must not submit")),
            replicate_enabled=False,
            provider_model="google/veo-3.1-fast",
            submitted_by="admin",
        )
    assert editor.get(board["id"])["scenes"][0]["video_job_id"] == ""


def test_failed_submission_leaves_the_board_ready_for_the_same_retry():
    editor = _editor()
    board = editor.create(
        purpose="billing",
        script="The amount due is 120.",
        opening_reference=_opening(),
        provider_model="google/veo-3.1-fast",
    )
    sha = board["integrity"]["document_sha256"]

    def _down(params):
        raise RuntimeError("provider is down")

    with pytest.raises(StoryboardProviderError) as exc:
        editor.render_scene(
            board["id"], 1,
            expected_sha256=sha,
            submitter=_down,
            replicate_enabled=True,
            provider_model="google/veo-3.1-fast",
            submitted_by="admin",
        )
    assert exc.value.extra["document_sha256"] == sha
    stored = editor.get(board["id"])
    assert stored["integrity"]["document_sha256"] == sha
    assert stored["scenes"][0]["status"] == "draft"
    retried = editor.render_scene(
        board["id"], 1,
        expected_sha256=sha,
        submitter=lambda params: {"id": "job-retry", "status": "queued"},
        replicate_enabled=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="admin",
    )
    assert retried["storyboard"]["scenes"][0]["video_job_id"] == "job-retry"


def test_a_slow_submission_does_not_block_another_board():
    editor = _editor()
    rendering = editor.create(
        purpose="claims", script="Gather the documents.", opening_reference=_opening(),
        provider_model="google/veo-3.1-fast",
    )
    other = editor.create(
        purpose="story", script="Dawn.", opening_reference=_opening(),
    )
    submitting = threading.Event()
    release = threading.Event()

    def _slow(params):
        submitting.set()
        assert release.wait(10)
        return {"id": "job-slow", "status": "queued"}

    worker = threading.Thread(
        target=editor.render_scene,
        args=(rendering["id"], 1),
        kwargs={
            "expected_sha256": rendering["integrity"]["document_sha256"],
            "submitter": _slow,
            "replicate_enabled": True,
            "provider_model": "google/veo-3.1-fast",
            "submitted_by": "admin",
        },
    )
    worker.start()
    try:
        assert submitting.wait(10)
        renamed = editor.update(
            other["id"],
            expected_sha256=other["integrity"]["document_sha256"],
            title="Edited while the provider is slow",
        )
        assert renamed["title"] == "Edited while the provider is slow"
    finally:
        release.set()
        worker.join(10)
    assert editor.get(rendering["id"])["scenes"][0]["video_job_id"] == "job-slow"


def test_a_save_during_a_submission_still_links_the_billed_job():
    editor = _editor()
    board = editor.create(
        purpose="claims", script="Gather the documents.", opening_reference=_opening(),
        provider_model="google/veo-3.1-fast",
    )
    submitting = threading.Event()
    release = threading.Event()

    def _slow(params):
        submitting.set()
        assert release.wait(10)
        return {"id": "job-inflight", "status": "queued"}

    worker = threading.Thread(
        target=editor.render_scene,
        args=(board["id"], 1),
        kwargs={
            "expected_sha256": board["integrity"]["document_sha256"],
            "submitter": _slow,
            "replicate_enabled": True,
            "provider_model": "google/veo-3.1-fast",
            "submitted_by": "admin",
        },
    )
    worker.start()
    try:
        assert submitting.wait(10)
        saved = editor.update(
            board["id"],
            expected_sha256=board["integrity"]["document_sha256"],
            title="Renamed while the scene is submitting",
        )
        # A second render of the same scene must not bill the provider again.
        with pytest.raises(StoryboardConflict):
            editor.render_scene(
                board["id"], 1,
                expected_sha256=saved["integrity"]["document_sha256"],
                submitter=lambda params: (_ for _ in ()).throw(AssertionError("must not submit")),
                replicate_enabled=True,
                provider_model="google/veo-3.1-fast",
                submitted_by="admin",
            )
    finally:
        release.set()
        worker.join(10)
    linked = editor.get(board["id"])
    assert linked["title"] == "Renamed while the scene is submitting"
    assert linked["scenes"][0]["video_job_id"] == "job-inflight"
    assert linked["scenes"][0]["status"] == "queued"


def test_an_edited_scene_does_not_take_the_job_it_no_longer_describes():
    editor = _editor()
    board = editor.create(
        purpose="claims", script="Gather the documents.", opening_reference=_opening(),
        provider_model="google/veo-3.1-fast",
    )
    submitting = threading.Event()
    release = threading.Event()
    outcome = {}

    def _slow(params):
        submitting.set()
        assert release.wait(10)
        return {"id": "job-voided", "status": "queued"}

    def _render():
        try:
            editor.render_scene(
                board["id"], 1,
                expected_sha256=board["integrity"]["document_sha256"],
                submitter=_slow,
                replicate_enabled=True,
                provider_model="google/veo-3.1-fast",
                submitted_by="admin",
            )
        except StoryboardConflict as exc:
            outcome["conflict"] = exc

    worker = threading.Thread(target=_render)
    worker.start()
    try:
        assert submitting.wait(10)
        editor.update(
            board["id"],
            expected_sha256=board["integrity"]["document_sha256"],
            scenes=[{"script": "Rewritten line.", "duration_seconds": 8}],
        )
    finally:
        release.set()
        worker.join(10)
    assert outcome["conflict"].extra["video_job_id"] == "job-voided"
    assert editor.get(board["id"])["scenes"][0]["video_job_id"] == ""


def test_changing_scene_one_supersedes_the_chain_and_keeps_a_chosen_scene():
    editor = _editor()
    chosen = seal_reference(raw=_PNG_B, mime="image/png", label="own")
    board = editor.create(
        purpose="investment_advice",
        scenes=[
            {"script": "Markets move.", "duration_seconds": 8},
            {"script": "This is not a recommendation.", "duration_seconds": 8},
            {
                "script": "Your own photo.",
                "duration_seconds": 6,
                "reference_mode": "chosen",
                "chosen_reference": chosen,
            },
        ],
        opening_reference=_opening(),
        provider_model="google/veo-3.1-fast",
    )
    first = editor.render_scene(
        board["id"], 1,
        expected_sha256=board["integrity"]["document_sha256"],
        submitter=lambda params: {"id": "job-1", "status": "queued"},
        replicate_enabled=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="admin",
    )["storyboard"]
    sealed = editor.record_end_frame(
        board["id"], 1,
        expected_sha256=first["integrity"]["document_sha256"],
        video_job_id="job-1",
        image_bytes=_PNG_B,
        image_mime="image/png",
    )
    second = editor.render_scene(
        board["id"], 2,
        expected_sha256=sealed["integrity"]["document_sha256"],
        submitter=lambda params: {"id": "job-2", "status": "queued"},
        replicate_enabled=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="admin",
    )["storyboard"]
    third = editor.render_scene(
        board["id"], 3,
        expected_sha256=second["integrity"]["document_sha256"],
        submitter=lambda params: {"id": "job-3", "status": "queued"},
        replicate_enabled=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="admin",
    )["storyboard"]
    updated = editor.update(
        board["id"],
        expected_sha256=third["integrity"]["document_sha256"],
        scenes=[
            {"script": "Markets move. Revised.", "duration_seconds": 8},
            {"script": "This is not a recommendation.", "duration_seconds": 8},
            {"script": "Your own photo.", "duration_seconds": 6, "reference_mode": "chosen"},
        ],
    )
    assert updated["scenes"][0]["status"] == "stale"
    assert "job-1" in updated["scenes"][0]["superseded_job_ids"]
    assert updated["scenes"][0]["end_screenshot"] is None
    assert updated["scenes"][1]["status"] == "stale"
    assert "job-2" in updated["scenes"][1]["superseded_job_ids"]
    assert updated["scenes"][2]["video_job_id"] == "job-3"
    assert updated["scenes"][2]["status"] == "queued"


def test_storyboard_pipelines_are_not_in_the_default_batch():
    assert len(BATCH_PIPELINE_TYPES) == 5
    assert "storyboard_advertisement" not in BATCH_PIPELINE_TYPES
    assert "storyboard_advertisement" in SUPPORTED_PIPELINE_TYPES
    assert "claims_assistant" in BATCH_PIPELINE_TYPES


def test_svg_reference_is_rejected():
    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>").decode()
    with pytest.raises(StoryboardValidationError):
        seal_reference(data_url=svg)


def test_api_create_chain_and_auth(monkeypatch):
    reset_storyboard_editor()
    admin = {"username": "admin", "role": "admin"}
    assert api_extensions.handle_storyboard_list(None)[0] == 401
    assert api_extensions.handle_storyboard_list({"role": "customer", "username": "c"})[0] == 403

    status, created = api_extensions.handle_storyboard_create(admin, {
        "title": "Billing explainer",
        "purpose": "billing",
        "script": "The amount due is 120.\n\nPay by the first.",
        "opening_reference": {"data_url": _PNG_URL, "label": "invoice"},
        "surface": "growth",
    })
    assert status == 201
    board = created["storyboard"]
    assert board["integrity_ok"] is True
    assert board["scenes"][0]["duration_seconds"] == 8
    assert board["provider"] == "replicate"
    assert board["opening_reference"]["sha256"] == _PNG_SHA

    listed = api_extensions.handle_storyboard_list(admin)[1]
    assert listed["total"] == 1
    assert listed["items"][0]["opening_reference"]["data_url"] == ""
    assert "billing" in {item["id"] for item in listed["purposes"]}

    calls = []

    def _submit(params):
        calls.append(params)
        return {"id": "job-api", "status": "queued", "deduplicated": False}

    monkeypatch.setattr(api_extensions, "_submit_storyboard_scene", _submit)
    monkeypatch.setattr(
        api_extensions, "_storyboard_connection",
        lambda provider, model: (True, provider or "replicate", ""),
    )
    status, rendered = api_extensions.handle_storyboard_render(admin, board["id"], "1", {
        "expected_sha256": board["integrity"]["document_sha256"],
    })
    assert status == 201
    assert calls[0]["provider"] == "replicate"
    assert calls[0]["pipeline_type"] == "storyboard_billing"
    assert calls[0]["duration_seconds"] == 8
    assert "120" in calls[0]["prompt_override"]
    status, blocked = api_extensions.handle_storyboard_render(admin, board["id"], "2", {
        "expected_sha256": rendered["storyboard"]["integrity"]["document_sha256"],
    })
    assert status == 409
    assert len(calls) == 1

    status, conflict = api_extensions.handle_storyboard_update(admin, board["id"], {
        "expected_sha256": board["integrity"]["document_sha256"],
        "title": "Too late",
    })
    assert status == 409
    assert api_extensions.handle_storyboard_get(admin, board["id"])[1]["storyboard"]["title"] == "Billing explainer"


def test_saved_script_survives_a_reload():
    reset_storyboard_editor()
    admin = {"username": "admin", "role": "admin"}
    board = api_extensions.handle_storyboard_create(admin, {
        "purpose": "story",
        "script": "First paste.",
        "opening_reference": {"data_url": _PNG_URL},
    })[1]["storyboard"]
    status, updated = api_extensions.handle_storyboard_update(admin, board["id"], {
        "expected_sha256": board["integrity"]["document_sha256"],
        "script": "Scene 1: The sealed line.",
        "scenes": [{"script": "The sealed line.", "duration_seconds": 8}],
    })
    assert status == 200
    reloaded = api_extensions.handle_storyboard_get(admin, board["id"])[1]["storyboard"]
    assert reloaded["source_script"] == "Scene 1: The sealed line."
    kept = api_extensions.handle_storyboard_update(admin, board["id"], {
        "expected_sha256": updated["storyboard"]["integrity"]["document_sha256"],
        "title": "Renamed",
    })[1]["storyboard"]
    assert kept["source_script"] == "Scene 1: The sealed line."


def test_api_library_checksum_mismatch_is_refused(monkeypatch):
    reset_storyboard_editor()

    class _Portal:
        MEDIA_ASSETS = {
            "img-1": {
                "id": "img-1",
                "type": "image",
                "name": "desk",
                "checksum": "0" * 64,
                "data": _PNG_URL,
            }
        }

        @staticmethod
        def decode_media_data_url(url):
            payload, mime = __import__(
                "services.storyboard_editor", fromlist=["decode_image_data_url"]
            ).decode_image_data_url(url)
            return payload, mime

        @staticmethod
        def compute_media_checksum(payload):
            return hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(api_extensions, "_portal_module", lambda: _Portal())
    status, body = api_extensions.handle_storyboard_create(
        {"username": "media", "role": "media"},
        {
            "purpose": "advertisement",
            "script": "One scene.",
            "opening_reference": {"asset_id": "img-1", "sha256": _PNG_SHA},
            "surface": "media",
        },
    )
    assert status == 409
    assert "checksum" in body["error"].lower()
    assert api_extensions.handle_storyboard_list({"username": "media", "role": "media"})[1]["total"] == 0


def test_extract_last_frame_rejects_a_non_video(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"this is not a video")
    with pytest.raises(StoryboardIntegrityError):
        extract_last_frame_png(str(path))


def test_extract_last_frame_seals_a_real_clip(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=32x32:d=1",
            "-pix_fmt", "yuv420p", str(clip),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    frame = extract_last_frame_png(str(clip))
    assert frame.startswith(b"\x89PNG\r\n\x1a\n")
    sealed = seal_reference(raw=frame, mime="image/png", label="end")
    assert sealed["sha256"] == hashlib.sha256(frame).hexdigest()


def test_growth_agent_job_keeps_the_scene_duration_and_still(monkeypatch):
    captured = {}

    class _FakeProvider:
        def submit_video_generation(self, **kwargs):
            captured.update(kwargs)
            return {
                "provider_job_id": "pred-storyboard",
                "status": "queued",
                "provider_state": {},
                "message": "accepted",
            }

    import web_portal.server as portal
    monkeypatch.setattr(portal, "get_media_generation_service", lambda: _FakeProvider())
    job = portal.create_media_video_job(
        campaign_id="SB-DURATION",
        blueprint_index=0,
        blueprint={"title": "Scene 1"},
        requested_by="admin",
        provider="replicate",
        provider_model="bytedance/seedance-2.0",
        image_data_url="data:image/png;base64,aaaa",
        prompt_override="Hold the still.",
        duration_seconds=10,
        aspect_ratio="9:16",
        resolution="720p",
        submit_inline=True,
    )
    try:
        assert captured["duration_seconds"] == 10
        assert captured["aspect_ratio"] == "9:16"
        assert captured["image_data_url"] == "data:image/png;base64,aaaa"
        assert captured["provider"] == "replicate"
        assert job["duration_seconds"] == 10
        assert job["status"] == "queued"
        assert str(job["id"]).startswith("mjob-")
    finally:
        portal.MEDIA_PROCESSING_JOBS.pop(job["id"], None)


def test_scene_one_without_a_photo_asks_the_provider_to_generate_it():
    editor = _editor()
    board = editor.create(purpose="advertisement", script="Open on the kitchen table.")
    assert board["provider"] == "replicate"
    assert board["scenes"][0]["start_source"] == "generated"
    assert board["integrity"]["chain_ok"] is True
    calls = []
    rendered = editor.render_scene(
        board["id"], 1,
        expected_sha256=board["integrity"]["document_sha256"],
        submitter=lambda params: calls.append(params) or {"id": "job-gen", "status": "queued"},
        provider="replicate",
        provider_connected=True,
        provider_model="google/veo-3.1-fast",
        submitted_by="admin",
    )["storyboard"]
    assert calls[0]["image_data_url"] == ""
    assert calls[0]["provider"] == "replicate"
    assert "Generate the opening picture" in calls[0]["prompt_override"]
    assert rendered["scenes"][0]["video_job_id"] == "job-gen"


def test_kling_duration_is_sent_only_when_kling_would_keep_it():
    assert duration_renders_exactly("kling-v2.6-pro", 8, "kling") is False
    assert duration_renders_exactly("kling-v2.6-pro", 5, "kling") is True
    assert duration_renders_exactly("veo-3.1-generate-preview", 8, "gemini") is True
    assert duration_renders_exactly("veo-3.1-generate-preview", 10, "gemini") is False
    editor = _editor()
    board = editor.create(
        purpose="disclaimer",
        provider="kling",
        scenes=[{"script": "This is general information.", "duration_seconds": 5}],
        opening_reference=_opening(),
    )
    calls = []
    editor.render_scene(
        board["id"], 1,
        expected_sha256=board["integrity"]["document_sha256"],
        submitter=lambda params: calls.append(params) or {"id": "job-k", "status": "queued", "provider": "kling"},
        provider="kling",
        provider_connected=True,
        provider_model="kling-v2.6-pro",
        submitted_by="admin",
    )
    assert calls[0]["provider"] == "kling"
    assert calls[0]["duration_seconds"] == 5
    refused = editor.create(
        purpose="disclaimer",
        provider="kling",
        scenes=[{"script": "This is general information.", "duration_seconds": 8}],
        opening_reference=_opening(),
    )
    with pytest.raises(StoryboardIntegrityError, match="exact duration"):
        editor.render_scene(
            refused["id"], 1,
            expected_sha256=refused["integrity"]["document_sha256"],
            submitter=lambda params: (_ for _ in ()).throw(AssertionError("must not submit")),
            provider="kling",
            provider_connected=True,
            provider_model="kling-v2.6-pro",
            submitted_by="admin",
        )


def test_scene_files_join_without_rewriting_them(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    clips = []
    for color in ("blue", "red"):
        path = tmp_path / f"{color}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s=32x32:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                str(path),
            ],
            check=True, capture_output=True, timeout=30,
        )
        clips.append(path)
    before = [path.read_bytes() for path in clips]
    film = concatenate_videos([str(path) for path in clips])
    assert film[4:8] == b"ftyp"
    assert [path.read_bytes() for path in clips] == before
    editor = _editor()
    board = editor.create(
        purpose="story",
        scenes=[
            {"script": "First.", "duration_seconds": 8},
            {"script": "Second.", "duration_seconds": 8},
        ],
        opening_reference=_opening(),
    )
    first_sha = hashlib.sha256(before[0]).hexdigest()
    second_sha = hashlib.sha256(before[1]).hexdigest()
    with pytest.raises(StoryboardIntegrityError, match="not sealed"):
        editor.record_film(
            board["id"],
            expected_sha256=board["integrity"]["document_sha256"],
            asset_id="media-film",
            sha256=hashlib.sha256(film).hexdigest(),
            byte_length=len(film),
            scene_sha256=[first_sha, second_sha],
        )
