"""Storyboard editor for longer PHINS media.

A storyboard is an ordered run of scenes for commercial and operational
video: stories, advertisements, investment education, insurance-agent
explainers, disclaimers, policy information, billing, claims, and
underwriting. Each scene has its own script and length (8 seconds unless
the operator sets another length).

Continuity is a checksum chain, not a guess:

- Scene 1 opens on the chosen first reference photo.
- Any scene may instead open on its own chosen reference.
- Otherwise a scene opens on the previous scene's ending screenshot.
- That ending still is captured from the rendered scene video (or from an
  operator-supplied still of that video) and sealed with SHA-256 before the
  next scene is allowed to render.

The document itself is sealed. ``integrity.document_sha256`` is the SHA-256
of the canonical JSON excluding the integrity block. A mismatch is reported
and blocks render. The editor never rewrites a sealed still or a media-library
file to make a chain look consistent.

Rendering goes through the video-agents job path with provider ``replicate``.
The requested duration is sent only when that model accepts it exactly.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("phins.storyboard_editor")

EDITOR_VERSION = 1
DEFAULT_SCENE_SECONDS = 8
MIN_SCENE_SECONDS = 2
MAX_SCENE_SECONDS = 15
MAX_SCENES = 24
MAX_SCRIPT_CHARS = 4000
MAX_SOURCE_SCRIPT_CHARS = 20000
MAX_INLINE_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SUPERSEDED = 8
VEO_DURATIONS = (4, 6, 8)
SURFACES = frozenset({"media", "growth", "solutions", "video-agents"})
REFERENCE_MODES = frozenset({"chain", "chosen"})
ALLOWED_IMAGE_MIME = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif",
})
_SCENE_MARK = re.compile(r"(?im)^\s*scene\s+\d+\s*[:.\-]?\s*")

PURPOSES: Dict[str, Dict[str, str]] = {
    "story": {
        "label": "Story",
        "pipeline_type": "storyboard_story",
        "prompt": (
            "Create a commercial story scene for PHINS. Warm, specific, and "
            "continuous with the reference still."
        ),
    },
    "advertisement": {
        "label": "Advertisement",
        "pipeline_type": "storyboard_advertisement",
        "prompt": (
            "Create a brand-safe advertisement scene for PHINS. State only the "
            "offer written in the script."
        ),
    },
    "investment_advice": {
        "label": "Investment advice",
        "pipeline_type": "storyboard_investment_advice",
        "prompt": (
            "Create an investment-education scene for PHINS. This is not a "
            "personal recommendation. Use only figures written in the script. "
            "Do not invent returns."
        ),
    },
    "insurance_agent": {
        "label": "Insurance agent",
        "pipeline_type": "storyboard_insurance_agent",
        "prompt": (
            "Create an insurance-agent scene for PHINS in plain language. "
            "Do not invent policy terms."
        ),
    },
    "disclaimer": {
        "label": "Disclaimer",
        "pipeline_type": "storyboard_disclaimer",
        "prompt": (
            "Deliver the disclaimer script verbatim. Do not paraphrase, "
            "shorten, or add legal lines."
        ),
    },
    "policy_information": {
        "label": "Policy information",
        "pipeline_type": "storyboard_policy_information",
        "prompt": (
            "Explain the policy using only the supplied script. Do not invent "
            "coverage, exclusions, or premiums."
        ),
    },
    "billing": {
        "label": "Billing data",
        "pipeline_type": "storyboard_billing",
        "prompt": (
            "Explain the billing scene using only amounts and dates written "
            "in the script. Do not invent balances."
        ),
    },
    "claims": {
        "label": "Claims",
        "pipeline_type": "claims_assistant",
        "prompt": (
            "Create a claims-tool scene for PHINS. Be exact and calm. Do not "
            "invent claim outcomes or payment amounts."
        ),
    },
    "underwriting": {
        "label": "Underwriting",
        "pipeline_type": "underwriting_assistant",
        "prompt": (
            "Create an underwriting-tool scene for PHINS. Explain only the "
            "steps and evidence named in the script. Do not invent a decision."
        ),
    },
}


class StoryboardError(Exception):
    """Base error. ``status`` is the HTTP status the API should return."""

    status = 400

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = {key: value for key, value in extra.items() if value is not None}


class StoryboardValidationError(StoryboardError):
    status = 400


class StoryboardNotFound(StoryboardError):
    status = 404


class StoryboardConflict(StoryboardError):
    status = 409


class StoryboardIntegrityError(StoryboardError):
    status = 409


class StoryboardProviderError(StoryboardError):
    status = 503


def purpose_catalog() -> List[Dict[str, str]]:
    """Public purpose list for the editor. No prompts that embed secrets."""
    return [
        {
            "id": key,
            "label": spec["label"],
            "pipeline_type": spec["pipeline_type"],
        }
        for key, spec in PURPOSES.items()
    ]


def split_script(text: str) -> List[str]:
    """Split a script into scene bodies.

    ``Scene 1:`` markers win. Otherwise blank lines separate scenes. A single
    block stays one scene.
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    if len(raw) > MAX_SOURCE_SCRIPT_CHARS:
        raise StoryboardValidationError(
            f"Script exceeds {MAX_SOURCE_SCRIPT_CHARS} characters."
        )
    if _SCENE_MARK.search(raw):
        parts = [part.strip() for part in _SCENE_MARK.split(raw) if part.strip()]
        if parts:
            return parts[:MAX_SCENES]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()]
    return (paragraphs or [raw])[:MAX_SCENES]


def coerce_duration(value: Any) -> int:
    """Whole seconds. Missing means 8. The provider must accept it exactly."""
    if value is None or value == "":
        return DEFAULT_SCENE_SECONDS
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise StoryboardValidationError(
            "duration_seconds must be a whole number of seconds."
        ) from None
    if number < MIN_SCENE_SECONDS or number > MAX_SCENE_SECONDS:
        raise StoryboardValidationError(
            f"Scene length must be between {MIN_SCENE_SECONDS} and "
            f"{MAX_SCENE_SECONDS} seconds."
        )
    return number


def duration_renders_exactly(model: str, requested: int) -> bool:
    """True when Replicate would be asked for this duration unchanged.

    Veo (and an empty model, because the platform default Replicate model is
    Veo) accepts 4, 6, or 8. Other Replicate video models accept 1–15, which
    this editor already clamps to 2–15.
    """
    requested = int(requested)
    label = str(model or "")
    if not label or "veo" in label.lower():
        return requested in VEO_DURATIONS
    return MIN_SCENE_SECONDS <= requested <= MAX_SCENE_SECONDS


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def document_sha256(board: Dict[str, Any]) -> str:
    body = {key: value for key, value in board.items() if key != "integrity"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _data_url(mime: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def decode_image_data_url(data_url: str) -> tuple:
    """Return ``(bytes, mime)`` for an allowed raster image data URL."""
    value = str(data_url or "").strip()
    if not value.startswith("data:") or "," not in value:
        raise StoryboardValidationError("Reference image must be a data URL.")
    header, encoded = value.split(",", 1)
    mime = header[5:].split(";", 1)[0].strip().lower() or "application/octet-stream"
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in ALLOWED_IMAGE_MIME:
        raise StoryboardValidationError(
            "Reference image must be JPEG, PNG, WebP, or GIF."
        )
    try:
        if ";base64" in header:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        else:
            from urllib.parse import unquote_to_bytes
            payload = unquote_to_bytes(encoded)
    except Exception as exc:
        raise StoryboardValidationError("Reference image data is not valid base64.") from exc
    if not payload:
        raise StoryboardValidationError("Reference image is empty.")
    if len(payload) > MAX_INLINE_IMAGE_BYTES:
        raise StoryboardValidationError("Reference image exceeds 2 MiB.")
    return payload, mime


def seal_reference(
    *,
    data_url: str = "",
    raw: Optional[bytes] = None,
    mime: str = "",
    asset_id: str = "",
    label: str = "",
    expected_sha256: str = "",
) -> Dict[str, Any]:
    """Seal image bytes. A claimed checksum that disagrees is refused."""
    if raw is None:
        raw, mime = decode_image_data_url(data_url)
    else:
        mime = str(mime or "image/png").split(";", 1)[0].strip().lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        if mime not in ALLOWED_IMAGE_MIME:
            raise StoryboardValidationError(
                "Reference image must be JPEG, PNG, WebP, or GIF."
            )
        if not raw:
            raise StoryboardValidationError("Reference image is empty.")
        if len(raw) > MAX_INLINE_IMAGE_BYTES:
            raise StoryboardValidationError("Reference image exceeds 2 MiB.")
    digest = _sha256_bytes(raw)
    claimed = str(expected_sha256 or "").strip().lower()
    if claimed and claimed != digest:
        raise StoryboardIntegrityError(
            "Reference checksum does not match the image bytes.",
            expected_sha256=claimed,
            actual_sha256=digest,
        )
    source = "asset" if str(asset_id or "").strip() else "inline"
    return {
        "source": source,
        "asset_id": str(asset_id or "").strip(),
        "sha256": digest,
        "mime": mime,
        "label": str(label or "").strip()[:200],
        "byte_length": len(raw),
        "data_url": _data_url(mime, raw),
    }


def _empty_reference() -> Dict[str, Any]:
    return {
        "source": "",
        "asset_id": "",
        "sha256": "",
        "mime": "",
        "label": "",
        "byte_length": 0,
        "data_url": "",
    }


def _reference_sha(reference: Optional[Dict[str, Any]]) -> str:
    if not isinstance(reference, dict):
        return ""
    return str(reference.get("sha256") or "").strip().lower()


def apply_chain(board: Dict[str, Any]) -> List[str]:
    """Write ``resolved_start_sha256`` from the chain rules. Return gaps.

    Gaps are honest draft states (the previous ending still is not sealed
    yet). They are not repairs.
    """
    errors: List[str] = []
    opening = _reference_sha(board.get("opening_reference"))
    previous_end = ""
    for scene in board.get("scenes") or []:
        mode = str(scene.get("reference_mode") or "chain")
        if mode == "chosen":
            sha = _reference_sha(scene.get("chosen_reference"))
            scene["resolved_start_sha256"] = sha
            if not sha:
                errors.append(
                    f"Scene {scene.get('index')}: chosen reference has no checksum."
                )
        elif int(scene.get("index") or 0) == 1:
            scene["resolved_start_sha256"] = opening
            if not opening:
                errors.append("Scene 1: choose an opening reference photo.")
        else:
            scene["resolved_start_sha256"] = previous_end
            if not previous_end:
                errors.append(
                    f"Scene {scene.get('index')}: waiting for the previous "
                    "scene's ending screenshot."
                )
        end = scene.get("end_screenshot") if isinstance(scene.get("end_screenshot"), dict) else {}
        previous_end = str(end.get("sha256") or "").strip().lower()
    return errors


def build_slide(board: Dict[str, Any]) -> Dict[str, Any]:
    """Ordered stills: opening photo, then each scene's ending screenshot."""
    frames: List[Dict[str, Any]] = []
    opening = board.get("opening_reference") if isinstance(board.get("opening_reference"), dict) else {}
    if opening.get("sha256"):
        frames.append({
            "role": "opening",
            "scene_index": 0,
            "sha256": opening.get("sha256") or "",
            "label": opening.get("label") or "Opening reference",
            "script": "",
            "duration_seconds": 0,
            "hands_off_to_scene": 1 if board.get("scenes") else None,
            "data_url": opening.get("data_url") or "",
            "mime": opening.get("mime") or "",
        })
    scenes = list(board.get("scenes") or [])
    for scene in scenes:
        end = scene.get("end_screenshot") if isinstance(scene.get("end_screenshot"), dict) else {}
        index = int(scene.get("index") or 0)
        frames.append({
            "role": "scene_end",
            "scene_index": index,
            "sha256": end.get("sha256") or "",
            "label": f"Scene {index} end",
            "script": str(scene.get("script") or ""),
            "duration_seconds": int(scene.get("duration_seconds") or DEFAULT_SCENE_SECONDS),
            "hands_off_to_scene": index + 1 if index < len(scenes) else None,
            "data_url": end.get("data_url") or "",
            "mime": end.get("mime") or "",
            "video_job_id": end.get("video_job_id") or scene.get("video_job_id") or "",
        })
    material = [
        {
            "role": frame["role"],
            "scene_index": frame["scene_index"],
            "sha256": frame["sha256"],
            "duration_seconds": frame["duration_seconds"],
            "script": frame.get("script") or "",
        }
        for frame in frames
    ]
    complete = bool(scenes) and all(
        str((scene.get("end_screenshot") or {}).get("sha256") or "")
        for scene in scenes
    )
    return {
        "frames": frames,
        "slide_sha256": hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest(),
        "complete": complete,
        "scene_count": len(scenes),
    }


def compile_scene_prompt(board: Dict[str, Any], scene: Dict[str, Any]) -> str:
    spec = PURPOSES[str(board.get("purpose") or "story")]
    total = len(board.get("scenes") or [])
    lines = [
        spec["prompt"],
        f"Scene {scene.get('index')} of {total}.",
        f"Duration: {scene.get('duration_seconds')} seconds.",
        f"Reference still SHA-256: {scene.get('resolved_start_sha256')}.",
        "Open on the supplied reference still and keep the same subject and setting.",
        "End on one clear still frame that can be the opening image of the next scene.",
        "Do not add titles, captions, or logos that are not in the script.",
        "Script:",
        str(scene.get("script") or "").strip(),
    ]
    return "\n".join(lines)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_last_frame_png(video_path: str) -> bytes:
    """PNG of the last frame. Raises when ffmpeg cannot produce one.

    The file is read as a local path only. No protocol other than ``file``
    is allowed, matching the platform's ffmpeg prefix.
    """
    path = str(video_path or "").strip()
    if not path or not os.path.isfile(path):
        raise StoryboardIntegrityError("Scene video file is not available for a screenshot.")
    if not _ffmpeg_available():
        raise StoryboardProviderError(
            "ffmpeg is not available to capture the ending screenshot."
        )
    dst = ""
    try:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        dst = handle.name
        handle.close()
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-y",
                "-protocol_whitelist", "file,crypto",
                "-sseof", "-0.05",
                "-i", path,
                "-frames:v", "1",
                "-f", "image2",
                dst,
            ],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
            raise StoryboardIntegrityError(
                "The scene video did not yield an ending screenshot."
            )
        with open(dst, "rb") as frame:
            payload = frame.read()
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise StoryboardIntegrityError("Ending screenshot is not a PNG.")
        if len(payload) > MAX_INLINE_IMAGE_BYTES:
            raise StoryboardValidationError("Ending screenshot exceeds 2 MiB.")
        return payload
    except subprocess.TimeoutExpired as exc:
        raise StoryboardIntegrityError("Ending screenshot capture timed out.") from exc
    finally:
        if dst and os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass


def _stamp_integrity(board: Dict[str, Any]) -> Dict[str, Any]:
    errors = apply_chain(board)
    slide = build_slide(board)
    board["integrity"] = {
        "editor_version": EDITOR_VERSION,
        "document_sha256": "",
        "slide_sha256": slide["slide_sha256"],
        "chain_ok": not errors,
        "chain_notes": errors,
        "scene_count": len(board.get("scenes") or []),
    }
    board["integrity"]["document_sha256"] = document_sha256(board)
    return board


def _integrity_matches(board: Dict[str, Any]) -> bool:
    stored = board.get("integrity") if isinstance(board.get("integrity"), dict) else {}
    recorded = str(stored.get("document_sha256") or "")
    if not recorded or recorded != document_sha256(board):
        return False
    fresh = copy.deepcopy(board)
    errors = apply_chain(fresh)
    if bool(stored.get("chain_ok")) != (not errors):
        return False
    if list(stored.get("chain_notes") or []) != errors:
        return False
    for original, walked in zip(board.get("scenes") or [], fresh.get("scenes") or []):
        if original.get("resolved_start_sha256") != walked.get("resolved_start_sha256"):
            return False
    slide = build_slide(board)
    return slide["slide_sha256"] == stored.get("slide_sha256")


def _new_scene(index: int, script: str, duration: int, mode: str = "chain") -> Dict[str, Any]:
    return {
        "index": index,
        "script": script,
        "duration_seconds": duration,
        "reference_mode": mode,
        "chosen_reference": None,
        "resolved_start_sha256": "",
        "end_screenshot": None,
        "video_job_id": "",
        "status": "draft",
        "provider_duration_seconds": None,
        "superseded_job_ids": [],
        "superseded_end_screenshots": [],
    }


def _supersede(scene: Dict[str, Any]) -> None:
    job_id = str(scene.get("video_job_id") or "")
    if job_id:
        history = list(scene.get("superseded_job_ids") or [])
        history.append(job_id)
        scene["superseded_job_ids"] = history[-MAX_SUPERSEDED:]
    end = scene.get("end_screenshot") if isinstance(scene.get("end_screenshot"), dict) else None
    if end and end.get("sha256"):
        stills = list(scene.get("superseded_end_screenshots") or [])
        stills.append({
            "sha256": end.get("sha256"),
            "video_job_id": end.get("video_job_id") or job_id,
            "byte_length": end.get("byte_length") or 0,
        })
        scene["superseded_end_screenshots"] = stills[-MAX_SUPERSEDED:]
    scene["video_job_id"] = ""
    scene["end_screenshot"] = None
    scene["provider_duration_seconds"] = None
    scene["status"] = "stale"


def _scene_has_output(scene: Dict[str, Any]) -> bool:
    end = scene.get("end_screenshot") if isinstance(scene.get("end_screenshot"), dict) else {}
    return bool(scene.get("video_job_id") or end.get("sha256"))


def _identity(scene: Dict[str, Any]) -> tuple:
    chosen = _reference_sha(scene.get("chosen_reference"))
    return (
        str(scene.get("script") or ""),
        int(scene.get("duration_seconds") or DEFAULT_SCENE_SECONDS),
        str(scene.get("reference_mode") or "chain"),
        chosen,
    )


def _normalize_script(value: Any) -> str:
    script = str(value or "").replace("\x00", "").strip()
    if len(script) > MAX_SCRIPT_CHARS:
        raise StoryboardValidationError(
            f"A scene script exceeds {MAX_SCRIPT_CHARS} characters."
        )
    return script


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, storyboard_id: str, details: Dict[str, Any]) -> None:
    """Best-effort audit. Checksums and ids only — never image bytes."""
    try:
        from services.ai_audit_bridge import record_ai_audit
        record_ai_audit(
            action=action,
            entity_type="storyboard",
            entity_id=storyboard_id,
            details=details,
            username="storyboard_editor",
        )
    except Exception as exc:
        logger.warning("storyboard audit failed (non-fatal): %s", exc)


def public_view(board: Dict[str, Any], *, include_media: bool) -> Dict[str, Any]:
    view = copy.deepcopy(board)
    view["integrity_ok"] = _integrity_matches(board)
    view["slide"] = build_slide(board)
    if include_media:
        return view

    def _strip(reference: Any) -> None:
        if isinstance(reference, dict):
            reference["data_url"] = ""

    _strip(view.get("opening_reference"))
    for scene in view.get("scenes") or []:
        _strip(scene.get("chosen_reference"))
        _strip(scene.get("end_screenshot"))
    for frame in view["slide"].get("frames") or []:
        frame["data_url"] = ""
    return view


class StoryboardEditor:
    """Durable storyboard documents behind the media storyboard editor."""

    def __init__(self, store: Any = None) -> None:
        if store is None:
            from services.hydrated_store import artifact_store
            store = artifact_store(
                "video_agents.storyboards",
                agent_id="video_agents",
                kind="storyboard",
                subject=lambda board: ("storyboard", str((board or {}).get("id") or "")),
            )
        self._store = store
        self._lock = threading.Lock()

    def _save(self, board: Dict[str, Any]) -> Dict[str, Any]:
        sealed = _stamp_integrity(board)
        self._store[sealed["id"]] = copy.deepcopy(sealed)
        return copy.deepcopy(sealed)

    def _load(self, storyboard_id: str) -> Dict[str, Any]:
        board = self._store.get(str(storyboard_id or "").strip())
        if not isinstance(board, dict):
            raise StoryboardNotFound(f"Storyboard {storyboard_id!r} was not found.")
        return copy.deepcopy(board)

    def _require_match(self, board: Dict[str, Any], expected_sha256: str) -> None:
        if not _integrity_matches(board):
            raise StoryboardIntegrityError(
                "Stored storyboard checksum does not match its contents.",
                document_sha256=str((board.get("integrity") or {}).get("document_sha256") or ""),
            )
        expected = str(expected_sha256 or "").strip().lower()
        actual = str((board.get("integrity") or {}).get("document_sha256") or "")
        if not expected:
            raise StoryboardValidationError("expected_sha256 is required.")
        if expected != actual:
            raise StoryboardConflict(
                "Storyboard changed since it was loaded.",
                document_sha256=actual,
            )

    def create(
        self,
        *,
        title: str = "",
        purpose: str = "advertisement",
        script: str = "",
        scenes: Optional[List[Dict[str, Any]]] = None,
        opening_reference: Optional[Dict[str, Any]] = None,
        provider_model: str = "",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        campaign_id: str = "",
        surface: str = "video-agents",
        created_by: str = "",
    ) -> Dict[str, Any]:
        purpose_key = str(purpose or "advertisement").strip().lower()
        if purpose_key not in PURPOSES:
            raise StoryboardValidationError(
                f"Unknown purpose {purpose_key!r}. "
                f"Supported: {sorted(PURPOSES)}."
            )
        surface_key = str(surface or "video-agents").strip().lower()
        if surface_key not in SURFACES:
            raise StoryboardValidationError(
                f"Unknown surface {surface_key!r}."
            )
        built = self._scenes_from_input(script, scenes)
        board = {
            "id": "SB-" + uuid.uuid4().hex[:12].upper(),
            "editor_version": EDITOR_VERSION,
            "title": str(title or "").strip()[:200] or PURPOSES[purpose_key]["label"],
            "purpose": purpose_key,
            "pipeline_type": PURPOSES[purpose_key]["pipeline_type"],
            "provider": "replicate",
            "provider_model": str(provider_model or "").strip(),
            "aspect_ratio": str(aspect_ratio or "16:9").strip() or "16:9",
            "resolution": str(resolution or "720p").strip() or "720p",
            "campaign_id": str(campaign_id or "").strip(),
            "surface": surface_key,
            "source_script": str(script or "")[:MAX_SOURCE_SCRIPT_CHARS],
            "opening_reference": opening_reference or _empty_reference(),
            "scenes": built,
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": str(created_by or "").strip(),
        }
        with self._lock:
            saved = self._save(board)
        _audit("storyboard_created", saved["id"], {
            "purpose": saved.get("purpose"),
            "surface": saved.get("surface"),
            "scene_count": len(saved.get("scenes") or []),
            "document_sha256": (saved.get("integrity") or {}).get("document_sha256"),
            "opening_sha256": _reference_sha(saved.get("opening_reference")),
        })
        return saved

    def _scenes_from_input(
        self,
        script: str,
        scenes: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        incoming = list(scenes or [])
        if not incoming and script:
            incoming = [
                {"script": part, "duration_seconds": DEFAULT_SCENE_SECONDS}
                for part in split_script(script)
            ]
        if not incoming:
            incoming = [{"script": "", "duration_seconds": DEFAULT_SCENE_SECONDS}]
        if len(incoming) > MAX_SCENES:
            raise StoryboardValidationError(f"A storyboard holds at most {MAX_SCENES} scenes.")
        built: List[Dict[str, Any]] = []
        for offset, item in enumerate(incoming, start=1):
            if not isinstance(item, dict):
                raise StoryboardValidationError("Each scene must be an object.")
            mode = str(item.get("reference_mode") or "chain").strip().lower()
            if mode not in REFERENCE_MODES:
                raise StoryboardValidationError(
                    "reference_mode must be 'chain' or 'chosen'."
                )
            scene = _new_scene(
                offset,
                _normalize_script(item.get("script")),
                coerce_duration(item.get("duration_seconds")),
                mode,
            )
            if mode == "chosen":
                chosen = item.get("chosen_reference")
                if isinstance(chosen, dict) and chosen.get("sha256"):
                    scene["chosen_reference"] = chosen
            built.append(scene)
        return built

    def get(self, storyboard_id: str) -> Dict[str, Any]:
        return self._load(storyboard_id)

    def list_boards(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        rows = []
        for key in list(self._store):
            board = self._store.get(key)
            if isinstance(board, dict):
                rows.append(board)
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return [copy.deepcopy(item) for item in rows[: max(1, min(int(limit or 50), 100))]]

    def update(
        self,
        storyboard_id: str,
        *,
        expected_sha256: str,
        title: Optional[str] = None,
        purpose: Optional[str] = None,
        provider_model: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        resolution: Optional[str] = None,
        campaign_id: Optional[str] = None,
        opening_reference: Any = None,
        scenes: Optional[List[Dict[str, Any]]] = None,
        remove_sealed: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            board = self._load(storyboard_id)
            self._require_match(board, expected_sha256)
            if purpose is not None:
                purpose_key = str(purpose or "").strip().lower()
                if purpose_key not in PURPOSES:
                    raise StoryboardValidationError(
                        f"Unknown purpose {purpose_key!r}."
                    )
                if purpose_key != board.get("purpose"):
                    self._supersede_all(board)
                board["purpose"] = purpose_key
                board["pipeline_type"] = PURPOSES[purpose_key]["pipeline_type"]
            if title is not None:
                board["title"] = str(title or "").strip()[:200] or board.get("title") or "Storyboard"
            if provider_model is not None:
                model = str(provider_model or "").strip()
                if model != str(board.get("provider_model") or ""):
                    self._supersede_all(board)
                board["provider_model"] = model
            if aspect_ratio is not None:
                board["aspect_ratio"] = str(aspect_ratio or "16:9").strip() or "16:9"
            if resolution is not None:
                board["resolution"] = str(resolution or "720p").strip() or "720p"
            if campaign_id is not None:
                board["campaign_id"] = str(campaign_id or "").strip()
            if isinstance(opening_reference, dict):
                previous = _reference_sha(board.get("opening_reference"))
                board["opening_reference"] = opening_reference
                if _reference_sha(opening_reference) != previous:
                    self._cascade_from(board, 1, include_start=True, only_chain_start=True)
            if scenes is not None:
                self._replace_scenes(board, scenes, remove_sealed=remove_sealed)
            board["provider"] = "replicate"
            board["updated_at"] = _now()
            return self._save(board)

    def _supersede_all(self, board: Dict[str, Any]) -> None:
        for scene in board.get("scenes") or []:
            if _scene_has_output(scene):
                _supersede(scene)

    def _cascade_from(
        self,
        board: Dict[str, Any],
        start_index: int,
        *,
        include_start: bool,
        only_chain_start: bool,
    ) -> None:
        """Invalidate rendered output that no longer matches its opening still.

        ``only_chain_start`` is for an opening-photo change: scene 1 is
        affected only when it chains from that photo. A scene with its own
        chosen reference keeps its sealed output.
        """
        cascade = True
        for scene in board.get("scenes") or []:
            index = int(scene.get("index") or 0)
            if index < start_index:
                continue
            if index > start_index and str(scene.get("reference_mode") or "") == "chosen":
                cascade = False
            if not cascade:
                continue
            if index == start_index and only_chain_start and scene.get("reference_mode") == "chosen":
                # The opening photo is not this scene's still, so later
                # scenes that chain from its ending screenshot stay sealed.
                return
            if index == start_index and not include_start:
                continue
            if _scene_has_output(scene):
                _supersede(scene)
            elif index != start_index:
                scene["status"] = "draft"

    def _replace_scenes(
        self,
        board: Dict[str, Any],
        incoming: List[Dict[str, Any]],
        *,
        remove_sealed: bool,
    ) -> None:
        if len(incoming) > MAX_SCENES:
            raise StoryboardValidationError(f"A storyboard holds at most {MAX_SCENES} scenes.")
        existing = list(board.get("scenes") or [])
        if len(incoming) < len(existing) and not remove_sealed:
            for scene in existing[len(incoming):]:
                if _scene_has_output(scene):
                    raise StoryboardIntegrityError(
                        "Removing a rendered scene needs remove_sealed=true. "
                        "The video job is kept; only the storyboard link is dropped.",
                        detached_job_ids=[
                            str(item.get("video_job_id") or "")
                            for item in existing[len(incoming):]
                            if item.get("video_job_id")
                        ],
                    )
        rebuilt: List[Dict[str, Any]] = []
        for offset, item in enumerate(incoming, start=1):
            if not isinstance(item, dict):
                raise StoryboardValidationError("Each scene must be an object.")
            mode = str(item.get("reference_mode") or "chain").strip().lower()
            if mode not in REFERENCE_MODES:
                raise StoryboardValidationError(
                    "reference_mode must be 'chain' or 'chosen'."
                )
            fresh = _new_scene(
                offset,
                _normalize_script(item.get("script")),
                coerce_duration(item.get("duration_seconds")),
                mode,
            )
            previous = existing[offset - 1] if offset <= len(existing) else None
            if mode == "chosen":
                incoming_ref = item.get("chosen_reference")
                if isinstance(incoming_ref, dict) and _reference_sha(incoming_ref):
                    fresh["chosen_reference"] = incoming_ref
                elif previous is not None and previous.get("reference_mode") == "chosen":
                    fresh["chosen_reference"] = copy.deepcopy(previous.get("chosen_reference"))
            if previous is not None:
                fresh["video_job_id"] = previous.get("video_job_id") or ""
                fresh["end_screenshot"] = copy.deepcopy(previous.get("end_screenshot"))
                fresh["status"] = previous.get("status") or "draft"
                fresh["provider_duration_seconds"] = previous.get("provider_duration_seconds")
                fresh["superseded_job_ids"] = list(previous.get("superseded_job_ids") or [])
                fresh["superseded_end_screenshots"] = list(
                    previous.get("superseded_end_screenshots") or []
                )
                if _identity(previous) != _identity(fresh):
                    if _scene_has_output(fresh):
                        _supersede(fresh)
                    else:
                        fresh["status"] = "draft"
            rebuilt.append(fresh)
        board["scenes"] = rebuilt
        # A changed scene clears every later chained scene whose opening
        # still would no longer match. Chosen scenes stay.
        for scene in rebuilt:
            if scene.get("status") == "stale":
                self._cascade_from(
                    board,
                    int(scene["index"]),
                    include_start=False,
                    only_chain_start=False,
                )

    def set_scene_reference(
        self,
        storyboard_id: str,
        index: int,
        *,
        expected_sha256: str,
        reference_mode: str,
        chosen_reference: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mode = str(reference_mode or "").strip().lower()
        if mode not in REFERENCE_MODES:
            raise StoryboardValidationError("reference_mode must be 'chain' or 'chosen'.")
        if mode == "chosen" and not _reference_sha(chosen_reference):
            raise StoryboardValidationError("A chosen scene reference needs a sealed image.")
        with self._lock:
            board = self._load(storyboard_id)
            self._require_match(board, expected_sha256)
            scene = self._scene(board, index)
            previous_mode = scene.get("reference_mode")
            previous_sha = _reference_sha(scene.get("chosen_reference"))
            scene["reference_mode"] = mode
            scene["chosen_reference"] = chosen_reference if mode == "chosen" else None
            changed = previous_mode != mode or previous_sha != _reference_sha(scene.get("chosen_reference"))
            if changed and _scene_has_output(scene):
                _supersede(scene)
            if changed:
                self._cascade_from(board, index, include_start=False, only_chain_start=False)
            board["updated_at"] = _now()
            return self._save(board)

    def _scene(self, board: Dict[str, Any], index: int) -> Dict[str, Any]:
        try:
            number = int(index)
        except (TypeError, ValueError):
            raise StoryboardValidationError("Scene index must be a whole number.") from None
        for scene in board.get("scenes") or []:
            if int(scene.get("index") or 0) == number:
                return scene
        raise StoryboardNotFound(f"Scene {number} was not found.")

    def verify(self, storyboard_id: str) -> Dict[str, Any]:
        board = self._load(storyboard_id)
        stored = board.get("integrity") if isinstance(board.get("integrity"), dict) else {}
        ok = _integrity_matches(board)
        return {
            "storyboard_id": board.get("id"),
            "ok": ok,
            "document_sha256": document_sha256(board),
            "stored_document_sha256": stored.get("document_sha256") or "",
            "slide_sha256": build_slide(board)["slide_sha256"],
            "stored_slide_sha256": stored.get("slide_sha256") or "",
            "chain_ok": bool(stored.get("chain_ok")),
            "chain_notes": list(stored.get("chain_notes") or []),
            "scene_count": len(board.get("scenes") or []),
        }

    def render_scene(
        self,
        storyboard_id: str,
        index: int,
        *,
        expected_sha256: str,
        submitter: Callable[[Dict[str, Any]], Dict[str, Any]],
        replicate_enabled: bool,
        provider_model: str,
        submitted_by: str,
    ) -> Dict[str, Any]:
        model = str(provider_model or "").strip()
        with self._lock:
            board = self._load(storyboard_id)
            self._require_match(board, expected_sha256)
            scene = self._scene(board, index)
            if str(scene.get("status") or "") in {"queued", "rendering"} and scene.get("video_job_id"):
                return {
                    "storyboard": board,
                    "job": {
                        "id": scene.get("video_job_id"),
                        "status": scene.get("status"),
                        "deduplicated": True,
                    },
                }
            if model and model != str(board.get("provider_model") or ""):
                board["provider_model"] = model
            model = str(board.get("provider_model") or model or "").strip()
            _stamp_integrity(board)
            if not _integrity_matches(board):
                raise StoryboardIntegrityError("Storyboard checksum could not be sealed.")
            if not str(scene.get("script") or "").strip():
                raise StoryboardValidationError("Write the scene script before rendering.")
            if not scene.get("resolved_start_sha256"):
                notes = list((board.get("integrity") or {}).get("chain_notes") or [])
                prefix = f"Scene {scene.get('index')}:"
                specific = next((item for item in notes if str(item).startswith(prefix)), "")
                raise StoryboardIntegrityError(
                    specific or (notes[0] if notes else "This scene has no opening reference yet.")
                )
            if not duration_renders_exactly(model, int(scene["duration_seconds"])):
                allowed = list(VEO_DURATIONS) if (not model or "veo" in model.lower()) else (
                    f"{MIN_SCENE_SECONDS}-{MAX_SCENE_SECONDS}"
                )
                raise StoryboardIntegrityError(
                    "This scene length is not an exact duration for the selected "
                    "Replicate model. The storyboard was not changed.",
                    allowed_durations=allowed,
                    duration_seconds=scene["duration_seconds"],
                    provider_model=model,
                )
            reference = self._resolved_reference(board, scene)
            image = str((reference or {}).get("data_url") or "")
            if not image or _reference_sha(reference) != scene.get("resolved_start_sha256"):
                raise StoryboardIntegrityError(
                    "The opening still for this scene is not sealed."
                )
            if not replicate_enabled:
                raise StoryboardProviderError(
                    "Replicate is not configured. Set REPLICATE_API_TOKEN to render a storyboard."
                )
            prompt = compile_scene_prompt(board, scene)
            submission = {
                "campaign_id": board.get("campaign_id") or "",
                "provider": "replicate",
                "pipeline_type": board.get("pipeline_type") or "storyboard_story",
                "title": f"{board.get('title') or 'Storyboard'} · scene {scene['index']}",
                "prompt_override": prompt,
                "provider_model": model,
                "aspect_ratio": board.get("aspect_ratio") or "16:9",
                "duration_seconds": int(scene["duration_seconds"]),
                "resolution": board.get("resolution") or "720p",
                "image_data_url": image,
                "submitted_by": submitted_by or "admin",
                "metadata": {
                    "storyboard_id": board["id"],
                    "scene_index": scene["index"],
                    "document_sha256": (board.get("integrity") or {}).get("document_sha256"),
                    "start_sha256": scene.get("resolved_start_sha256"),
                    "purpose": board.get("purpose"),
                    "surface": board.get("surface"),
                },
                "force": False,
            }
            try:
                job = submitter(submission)
            except StoryboardError:
                raise
            except Exception as exc:
                scene["status"] = "failed"
                board["updated_at"] = _now()
                failed = self._save(board)
                raise StoryboardProviderError(
                    f"Replicate submission failed: {exc}",
                    document_sha256=(failed.get("integrity") or {}).get("document_sha256"),
                ) from exc
            if not isinstance(job, dict) or not job.get("id"):
                raise StoryboardProviderError("Replicate did not return a video job.")
            scene["video_job_id"] = str(job.get("id"))
            scene["provider_duration_seconds"] = int(scene["duration_seconds"])
            status = str(job.get("status") or "queued").lower()
            scene["status"] = _scene_status_from_job(status, has_end=False)
            board["updated_at"] = _now()
            saved = self._save(board)
            return {
                "storyboard": saved,
                "job": {
                    "id": job.get("id"),
                    "status": job.get("status"),
                    "deduplicated": bool(job.get("deduplicated")),
                },
            }

    def _resolved_reference(self, board: Dict[str, Any], scene: Dict[str, Any]) -> Dict[str, Any]:
        if scene.get("reference_mode") == "chosen":
            chosen = scene.get("chosen_reference")
            return chosen if isinstance(chosen, dict) else {}
        if int(scene.get("index") or 0) == 1:
            opening = board.get("opening_reference")
            return opening if isinstance(opening, dict) else {}
        previous = self._scene(board, int(scene["index"]) - 1)
        end = previous.get("end_screenshot")
        return end if isinstance(end, dict) else {}

    def next_scene_index(self, board: Dict[str, Any]) -> Optional[int]:
        """Next scene whose opening still is sealed and which is not rendering."""
        walked = copy.deepcopy(board)
        apply_chain(walked)
        for scene in walked.get("scenes") or []:
            status = str(scene.get("status") or "")
            if status in {"queued", "rendering", "capturing"}:
                return None
            end = scene.get("end_screenshot") if isinstance(scene.get("end_screenshot"), dict) else {}
            if status == "ready" and end.get("sha256"):
                continue
            if scene.get("resolved_start_sha256"):
                return int(scene["index"])
            return None
        return None

    def note_job_status(
        self,
        storyboard_id: str,
        index: int,
        *,
        expected_sha256: str,
        job_status: str,
        job_id: str,
    ) -> Dict[str, Any]:
        """Copy a video-job status onto the scene. Does not invent a still."""
        with self._lock:
            board = self._load(storyboard_id)
            self._require_match(board, expected_sha256)
            scene = self._scene(board, index)
            if str(scene.get("video_job_id") or "") != str(job_id or ""):
                raise StoryboardConflict(
                    "That video job is not the job sealed on this scene.",
                    video_job_id=scene.get("video_job_id") or "",
                )
            end = scene.get("end_screenshot") if isinstance(scene.get("end_screenshot"), dict) else {}
            scene["status"] = _scene_status_from_job(job_status, has_end=bool(end.get("sha256")))
            board["updated_at"] = _now()
            return self._save(board)

    def record_end_frame(
        self,
        storyboard_id: str,
        index: int,
        *,
        expected_sha256: str,
        video_job_id: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/png",
        claimed_sha256: str = "",
        source: str = "extracted",
    ) -> Dict[str, Any]:
        """Seal the ending screenshot. A bad checksum does not advance the chain."""
        source_name = str(source or "extracted").strip().lower()
        if source_name not in {"extracted", "supplied"}:
            raise StoryboardValidationError("Screenshot source must be extracted or supplied.")
        sealed = seal_reference(
            raw=image_bytes,
            mime=image_mime or "image/png",
            label=f"Scene {index} end",
            expected_sha256=claimed_sha256,
        )
        with self._lock:
            board = self._load(storyboard_id)
            self._require_match(board, expected_sha256)
            scene = self._scene(board, index)
            current_job = str(scene.get("video_job_id") or "")
            if not current_job or current_job != str(video_job_id or ""):
                raise StoryboardConflict(
                    "Ending screenshot job does not match the scene video.",
                    video_job_id=current_job,
                )
            previous_end = _reference_sha(scene.get("end_screenshot"))
            scene["end_screenshot"] = {
                "sha256": sealed["sha256"],
                "mime": sealed["mime"],
                "data_url": sealed["data_url"],
                "source": source_name,
                "video_job_id": current_job,
                "byte_length": sealed["byte_length"],
            }
            scene["status"] = "ready"
            if previous_end and previous_end != sealed["sha256"]:
                self._cascade_from(
                    board, int(scene["index"]), include_start=False, only_chain_start=False,
                )
            board["updated_at"] = _now()
            saved = self._save(board)
        _audit("storyboard_end_frame", saved["id"], {
            "scene_index": index,
            "video_job_id": video_job_id,
            "sha256": sealed["sha256"],
            "source": source_name,
            "document_sha256": (saved.get("integrity") or {}).get("document_sha256"),
        })
        return saved


def _scene_status_from_job(job_status: str, *, has_end: bool) -> str:
    status = str(job_status or "").strip().lower()
    if has_end and status == "completed":
        return "ready"
    if status == "completed":
        return "capturing"
    if status in {"queued"}:
        return "queued"
    if status in {"processing", "rendering"}:
        return "rendering"
    if status in {"failed", "cancelled"}:
        return "failed"
    return "queued"


_EDITOR: Optional[StoryboardEditor] = None
_EDITOR_LOCK = threading.Lock()


def get_storyboard_editor() -> StoryboardEditor:
    global _EDITOR
    with _EDITOR_LOCK:
        if _EDITOR is None:
            _EDITOR = StoryboardEditor()
        return _EDITOR


def reset_storyboard_editor() -> None:
    """Drop the process singleton. Tests use a private editor instead."""
    global _EDITOR
    with _EDITOR_LOCK:
        _EDITOR = None
