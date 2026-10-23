"""Crisis session drop and the 24/7 cyber autopilot.

The drop is the cyber desk's restart for signed-in access. An admin asks
for a one-time code from the OTP service, confirms it, and every open
session is closed — including the admin who requested it. Stateless
tokens die with them because each token carries a session generation, and
the drop advances that generation. Customer, policy, claim, and billing
records are read only so the drop can prove it did not change them.

The autopilot is the assessment center for that same pipeline. It scores
the edge controls, the detection signals, and the checksums on the
generation record and the crisis journal. Identical input inside the
cadence reuses the previous record. It never closes a session.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, Sequence

from services.otp_security_service import OTPPurpose, OTPSecurityService

AUTOPILOT_RING = 64
CRISIS_PURPOSE = OTPPurpose.CRISIS_LOCKDOWN
_REFRESH_SECONDS = 1.0


class CrisisIntegrityError(RuntimeError):
    """A checksummed control record could not be sealed."""


def canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seal(body: Mapping[str, Any]) -> Dict[str, Any]:
    data = {key: body[key] for key in body if key != "checksum"}
    data["checksum"] = sha256_text(canonical(data))
    return data


def checksum_ok(data: Mapping[str, Any]) -> bool:
    if not isinstance(data, Mapping) or "checksum" not in data:
        return False
    expected = str(data.get("checksum") or "")
    body = {key: value for key, value in data.items() if key != "checksum"}
    actual = sha256_text(canonical(body))
    if len(actual) != len(expected):
        return False
    return hmac.compare_digest(actual, expected)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(blob)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def crisis_directory() -> Path:
    raw = (os.environ.get("PHINS_CYBER_CRISIS_DIR") or "").strip()
    path = Path(raw) if raw else Path(tempfile.gettempdir()) / "phins_cyber_crisis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fingerprint_records(named: Mapping[str, Any]) -> Dict[str, Any]:
    """Identity fingerprint of business maps.

    Keys and a small projection (status/role and field count) are hashed.
    Values that carry personal data are not copied into the digest input
    beyond that projection. The drop uses this to prove the maps were not
    rewritten.
    """
    report: Dict[str, Any] = {}
    for name in sorted(named):
        mapping = named[name]
        try:
            items = list(mapping.items())
        except Exception:
            report[name] = {"count": None, "projection_sha256": None, "readable": False}
            continue
        lines = []
        for key, value in items:
            if isinstance(value, dict):
                marker = value.get("status") or value.get("role") or ""
                lines.append(f"{key}|{marker}|{len(value)}")
            else:
                lines.append(f"{key}|{type(value).__name__}")
        lines.sort()
        report[name] = {
            "count": len(lines),
            "projection_sha256": sha256_text("\n".join(lines)),
            "readable": True,
        }
    return report


def autopilot_cadence_seconds() -> float:
    raw = (os.environ.get("PHINS_CYBER_AUTOPILOT_CADENCE_SECONDS") or "").strip()
    if not raw:
        return 60.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 60.0


def score_pipeline(telemetry: Mapping[str, Any]) -> Dict[str, Any]:
    """Read-only posture score. Does not read or write platform records."""
    findings = []
    recommendations = []
    score = 0

    def add(points: int, finding: str) -> None:
        nonlocal score
        score += points
        findings.append(finding)

    if not telemetry.get("firewall_enabled", False):
        add(15, "Firewall is not active on the request edge")
    if not telemetry.get("ids_enabled", False):
        add(15, "Intrusion detection is not active")
    if not telemetry.get("file_scanner_enabled", False):
        add(10, "Upload scanner is not active")
    if not telemetry.get("request_sanitizer_enabled", False):
        add(10, "Request sanitizer is not active")
    if not telemetry.get("generation_intact", True):
        add(40, "Session generation record failed its checksum")
    if not telemetry.get("journal_intact", True):
        add(40, "Crisis journal chain failed its checksum")

    attempts = _as_int(telemetry.get("malicious_attempts"))
    permanent = _as_int(telemetry.get("permanent_blocks"))
    alerts = _as_int(telemetry.get("active_alerts"))
    lockouts = _as_int(telemetry.get("lockouts"))
    quarantined = _as_int(telemetry.get("quarantined"))
    sessions = _as_int(telemetry.get("active_sessions"))

    if attempts > 100:
        add(30, f"{attempts} malicious attempts are on the recent log")
    elif attempts > 20:
        add(15, f"{attempts} malicious attempts are on the recent log")
    elif attempts > 0:
        add(5, f"{attempts} malicious attempt(s) are on the recent log")
    if permanent > 5:
        add(20, f"{permanent} addresses are permanently blocked")
    elif permanent > 0:
        findings.append(f"{permanent} address(es) are permanently blocked")
    if alerts > 5:
        add(25, f"{alerts} security alerts are still unacknowledged")
    elif alerts > 0:
        add(10, f"{alerts} security alert(s) are still unacknowledged")
    if lockouts > 3:
        add(15, f"{lockouts} login lockouts are active")
    elif lockouts > 0:
        findings.append(f"{lockouts} login lockout(s) are active")
    if quarantined > 0:
        add(10, f"{quarantined} upload(s) are in quarantine")
        recommendations.append("Review the quarantine log and the source addresses")
    if sessions > 50:
        recommendations.append("Session count is high. Confirm the logins are expected")

    stages = {
        "edge_firewall": "up" if telemetry.get("firewall_enabled") else "down",
        "intrusion_detection": "up" if telemetry.get("ids_enabled") else "down",
        "upload_scanner": "up" if telemetry.get("file_scanner_enabled") else "down",
        "request_sanitizer": "up" if telemetry.get("request_sanitizer_enabled") else "down",
        "session_generation": "up" if telemetry.get("generation_intact", True) else "down",
        "crisis_journal": "up" if telemetry.get("journal_intact", True) else "down",
        "identity": "watch" if lockouts else "up",
        "detection": "watch" if alerts else "up",
    }
    if score >= 40:
        recommendations.append(
            "Use Drop all on Login Activity after the one-time code. "
            "That closes every open session, including the operator who confirms it. "
            "Autopilot does not close sessions."
        )
    elif score < 10:
        recommendations.append(
            "No crisis signal. Autopilot holds this assessment until the pipeline changes."
        )
    if any(state == "down" for state in stages.values()):
        recommendations.append("Restore any down pipeline control before standing down the desk")

    capped = min(score, 100)
    if capped >= 60:
        level = "CRITICAL"
    elif capped >= 40:
        level = "HIGH"
    elif capped >= 20:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {
        "risk_level": level,
        "risk_score": capped,
        "findings": findings,
        "recommendations": recommendations,
        "pipeline": stages,
        "signals": {
            "malicious_attempts": attempts,
            "permanent_blocks": permanent,
            "active_alerts": alerts,
            "lockouts": lockouts,
            "quarantined": quarantined,
            "active_sessions": sessions,
            "customers": _as_int(telemetry.get("customers")),
            "policies": _as_int(telemetry.get("policies")),
            "claims": _as_int(telemetry.get("claims")),
            "billing": _as_int(telemetry.get("billing")),
        },
    }


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _record_hash(body: Mapping[str, Any]) -> str:
    material = {key: value for key, value in body.items() if key != "record_hash"}
    return sha256_text(canonical(material))


class CrisisCenter:
    """Process-local crisis controls backed by checksummed files."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = threading.RLock()
        self._generation = 0
        self._generation_intact = True
        self._generation_loaded = False
        self._corrupt_latched = False
        self._refresh_at = 0.0
        self._journal_intact = True
        self._journal_loaded = False
        self._journal: list = []
        self._autopilot_mode = "assess"
        self._autopilot_loaded = False
        self._chain_intact = True
        self._chain_anchor = ""
        self._chain: list = []
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._durable_read: Optional[Callable[[], Optional[Mapping[str, Any]]]] = None
        self._durable_write: Optional[Callable[[Mapping[str, Any]], bool]] = None

    # ------------------------------------------------------------------
    # Session generation
    # ------------------------------------------------------------------

    @property
    def generation_path(self) -> Path:
        return self.directory / "session_generation.json"

    def generation(self) -> int:
        with self._lock:
            self._load_generation()
            self._refresh_generation()
            return self._generation

    def generation_intact(self) -> bool:
        with self._lock:
            self._load_generation()
            return self._generation_intact

    def blocks(self, claims: Optional[Mapping[str, Any]]) -> bool:
        """True when ``claims`` belong to a generation the drop has closed."""
        current = self.generation()
        if current <= 0:
            return False
        if not isinstance(claims, Mapping):
            return True
        try:
            claimed = int(claims.get("session_generation", 0) or 0)
        except (TypeError, ValueError):
            return True
        return claimed != current

    def _load_generation(self) -> None:
        if self._generation_loaded:
            return
        self._generation_loaded = True
        path = self.generation_path
        if not path.exists():
            return
        data = _read_json(path)
        if not data or not checksum_ok(data):
            self._fail_closed_generation()
            return
        try:
            self._generation = max(0, int(data.get("generation") or 0))
        except (TypeError, ValueError):
            self._fail_closed_generation()

    def _refresh_generation(self) -> None:
        now = time.time()
        if now - self._refresh_at < _REFRESH_SECONDS:
            return
        self._refresh_at = now
        path = self.generation_path
        if path.exists():
            data = _read_json(path)
            if data and checksum_ok(data):
                try:
                    stored = int(data.get("generation") or 0)
                except (TypeError, ValueError):
                    stored = self._generation
                if stored > self._generation:
                    self._generation = stored
                    self._generation_intact = True
            elif not self._corrupt_latched:
                self._fail_closed_generation()
        reader = self._durable_read
        if reader is None:
            return
        try:
            remote = reader()
        except Exception:
            return
        if not isinstance(remote, Mapping) or not checksum_ok(remote):
            return
        try:
            remote_gen = int(remote.get("generation") or 0)
        except (TypeError, ValueError):
            return
        if remote_gen > self._generation:
            self._generation = remote_gen
            self._generation_intact = True
            try:
                _write_json(self.generation_path, seal(dict(remote)))
            except OSError:
                pass

    def _fail_closed_generation(self) -> None:
        """A damaged generation file closes current sessions once."""
        if self._corrupt_latched:
            self._generation_intact = False
            return
        self._corrupt_latched = True
        self._generation_intact = False
        self._generation += 1
        try:
            self._persist_generation(self._generation)
            self._generation_intact = True
        except (OSError, CrisisIntegrityError):
            self._generation_intact = False

    def _persist_generation(self, generation: int) -> Dict[str, Any]:
        payload = seal({
            "generation": int(generation),
            "updated_at": _now_iso(),
        })
        _write_json(self.generation_path, payload)
        # Read back before trusting the write.
        written = _read_json(self.generation_path)
        if not written or not checksum_ok(written):
            raise CrisisIntegrityError("session generation record failed verification")
        if int(written.get("generation") or -1) != int(generation):
            raise CrisisIntegrityError("session generation record did not match the write")
        return written

    def advance_generation(self) -> int:
        with self._lock:
            self._load_generation()
            previous = self._generation
            proposed = previous + 1
            try:
                payload = self._persist_generation(proposed)
            except (OSError, CrisisIntegrityError) as exc:
                raise CrisisIntegrityError(str(exc)) from exc
            writer = self._durable_write
            if writer is not None:
                durable_ok = False
                try:
                    durable_ok = bool(writer(payload))
                except Exception:
                    durable_ok = False
                if not durable_ok:
                    try:
                        if previous <= 0 and self.generation_path.exists():
                            self.generation_path.unlink()
                        else:
                            self._persist_generation(previous)
                    except (OSError, CrisisIntegrityError):
                        pass
                    raise CrisisIntegrityError("durable session generation write failed")
            self._generation = proposed
            self._generation_intact = True
            self._corrupt_latched = False
            return proposed

    # ------------------------------------------------------------------
    # Journal
    # ------------------------------------------------------------------

    @property
    def journal_path(self) -> Path:
        return self.directory / "crisis_journal.json"

    def journal_intact(self) -> bool:
        with self._lock:
            self._load_journal()
            return self._journal_intact

    def _load_journal(self) -> None:
        if self._journal_loaded:
            return
        self._journal_loaded = True
        path = self.journal_path
        if not path.exists():
            self._journal = []
            self._journal_intact = True
            return
        data = _read_json(path)
        if not data or not checksum_ok(data):
            self._journal = []
            self._journal_intact = False
            return
        entries = data.get("entries")
        if not isinstance(entries, list) or not self._chain_ok(entries, ""):
            self._journal = []
            self._journal_intact = False
            return
        self._journal = entries
        self._journal_intact = True

    def _chain_ok(self, entries: Sequence[Any], anchor: str) -> bool:
        previous = anchor or ""
        for entry in entries:
            if not isinstance(entry, dict):
                return False
            if str(entry.get("previous_hash") or "") != previous:
                return False
            if str(entry.get("record_hash") or "") != _record_hash(entry):
                return False
            previous = str(entry["record_hash"])
        return True

    def _append_chain_file(
        self,
        path: Path,
        entries: list,
        anchor: str,
        entry: Dict[str, Any],
        *,
        limit: Optional[int] = None,
    ) -> Optional[list]:
        body = dict(entry)
        body.pop("record_hash", None)
        body["previous_hash"] = entries[-1]["record_hash"] if entries else (anchor or "")
        body["record_hash"] = _record_hash(body)
        updated = list(entries)
        updated.append(body)
        chain_anchor = anchor or ""
        if limit is not None:
            while len(updated) > limit:
                dropped = updated.pop(0)
                chain_anchor = str(dropped.get("record_hash") or "")
        payload = seal({"anchor": chain_anchor, "entries": updated})
        try:
            _write_json(path, payload)
        except OSError:
            return None
        written = _read_json(path)
        if not written or not checksum_ok(written):
            return None
        if written.get("entries") != updated:
            return None
        return updated

    def _append_journal(self, entry: Mapping[str, Any]) -> bool:
        self._load_journal()
        if not self._journal_intact:
            return False
        updated = self._append_chain_file(
            self.journal_path, self._journal, "", dict(entry)
        )
        if updated is None:
            return False
        self._journal = updated
        return True

    def reseal_journal(self, actor: str) -> Dict[str, Any]:
        """Archive a broken journal and start a new chain. Evidence is kept."""
        with self._lock:
            self._load_journal()
            if self._journal_intact:
                return {"resealed": False, "journal_intact": True}
            archive_name = ""
            path = self.journal_path
            if path.exists():
                archive = path.with_name(
                    f"crisis_journal.broken-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
                )
                os.replace(path, archive)
                archive_name = archive.name
            self._journal = []
            self._journal_intact = True
            self._journal_loaded = True
            sealed = self._append_journal({
                "action": "journal_resealed",
                "actor": actor,
                "archive": archive_name,
                "at": _now_iso(),
            })
            return {
                "resealed": bool(sealed),
                "journal_intact": self._journal_intact and bool(sealed),
                "archive": archive_name,
            }

    # ------------------------------------------------------------------
    # Drop
    # ------------------------------------------------------------------

    def drop_all_sessions(
        self,
        *,
        actor: str,
        verification_id: str,
        sessions: MutableMapping[str, Any],
        lock: Optional[threading.Lock] = None,
        revoke_jti: Optional[Callable[[str, float], None]] = None,
        delete_db_sessions: Optional[Callable[[], int]] = None,
        integrity_sources: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Close every session in ``sessions`` and advance the generation.

        ``integrity_sources`` are read before and after. They are not written.
        The requester is included because nothing is excluded from the clear.
        """
        sources = integrity_sources or {}
        before = fingerprint_records(sources)
        with self._lock:
            if not self.journal_intact():
                return {
                    "ok": False,
                    "status": 409,
                    "error": "Crisis journal checksum does not match. Reseal it before a drop.",
                    "code": "crisis_journal_integrity",
                }
            intent_ok = self._append_journal({
                "action": "drop_all_sessions",
                "phase": "intent",
                "actor": str(actor or ""),
                "verification_id": str(verification_id or ""),
                "generation_before": self.generation(),
                "integrity_before": before,
                "at": _now_iso(),
            })
            if not intent_ok:
                return {
                    "ok": False,
                    "status": 503,
                    "error": "Crisis journal could not be sealed. No sessions were closed.",
                    "code": "crisis_journal_unavailable",
                }
            try:
                new_generation = self.advance_generation()
            except CrisisIntegrityError:
                return {
                    "ok": False,
                    "status": 503,
                    "error": "Session generation could not be sealed. No sessions were closed.",
                    "code": "crisis_generation_unavailable",
                }

        held = lock or threading.Lock()
        removed: list = []
        with held:
            removed = list(sessions.items())
            sessions.clear()

        revoked = 0
        for token, sess in removed:
            if _revoke_session_token(token, sess, revoke_jti):
                revoked += 1

        db_deleted = 0
        db_error = None
        if delete_db_sessions is not None:
            try:
                db_deleted = int(delete_db_sessions() or 0)
            except Exception as exc:
                db_error = type(exc).__name__

        after = fingerprint_records(sources)
        intact = before == after
        with self._lock:
            self._append_journal({
                "action": "drop_all_sessions",
                "phase": "completed",
                "actor": str(actor or ""),
                "verification_id": str(verification_id or ""),
                "generation": new_generation,
                "sessions_dropped": len(removed),
                "tokens_revoked": revoked,
                "db_sessions_deleted": db_deleted,
                "db_clear_error": db_error,
                "integrity_intact": intact,
                "integrity_after": after,
                "at": _now_iso(),
            })
        return {
            "ok": True,
            "success": True,
            "dropped": True,
            "requester_included": True,
            "sessions_dropped": len(removed),
            "tokens_revoked": revoked,
            "db_sessions_deleted": db_deleted,
            "db_clear_error": db_error,
            "generation": new_generation,
            "integrity_intact": intact,
            "integrity_before": before,
            "integrity_after": after,
            "relogin_required": True,
            "message": (
                "All open sessions were closed, including the one that "
                "confirmed this drop. Business records were not modified."
            ),
        }

    # ------------------------------------------------------------------
    # OTP challenge binding
    # ------------------------------------------------------------------

    def bind_challenge(self, verification_id: str, username: str, email: str) -> None:
        with self._lock:
            self._pending[str(verification_id)] = {
                "username": str(username),
                "email": str(email or "").strip().lower(),
                "created": time.time(),
            }

    def challenge_matches(self, verification_id: str, username: str, email: str) -> bool:
        with self._lock:
            row = self._pending.get(str(verification_id))
            if not row:
                return False
            if time.time() - float(row.get("created") or 0) > 600:
                self._pending.pop(str(verification_id), None)
                return False
            return (
                row.get("username") == str(username)
                and row.get("email") == str(email or "").strip().lower()
            )

    def release_challenge(self, verification_id: str) -> None:
        with self._lock:
            self._pending.pop(str(verification_id), None)

    def confirm_drop(
        self,
        otp_service: OTPSecurityService,
        *,
        username: str,
        email: str,
        verification_id: str,
        otp_code: str,
        ip_address: str,
        sessions: MutableMapping[str, Any],
        lock: Optional[threading.Lock] = None,
        revoke_jti: Optional[Callable[[str, float], None]] = None,
        delete_db_sessions: Optional[Callable[[], int]] = None,
        integrity_sources: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.challenge_matches(verification_id, username, email):
            return {
                "ok": False,
                "status": 400,
                "error": "This code was not issued for the current admin session.",
                "code": "crisis_challenge_mismatch",
            }
        verified = otp_service.verify_otp(
            verification_id=verification_id,
            otp_code=str(otp_code or ""),
            ip_address=ip_address,
        )
        if not verified.success:
            return {
                "ok": False,
                "status": 400,
                "error": verified.message or "The one-time code was not accepted.",
                "code": verified.error_code or "INVALID_OTP",
            }
        consumed = otp_service.consume_verification(
            verification_id,
            expected_email=email,
            expected_purpose=CRISIS_PURPOSE,
            expected_user_type="staff",
            ip_address=ip_address,
        )
        if not consumed.success:
            return {
                "ok": False,
                "status": 400,
                "error": consumed.message or "The one-time code could not be consumed.",
                "code": consumed.error_code or "OTP_NOT_VERIFIED",
            }
        self.release_challenge(verification_id)
        return self.drop_all_sessions(
            actor=username,
            verification_id=verification_id,
            sessions=sessions,
            lock=lock,
            revoke_jti=revoke_jti,
            delete_db_sessions=delete_db_sessions,
            integrity_sources=integrity_sources,
        )

    # ------------------------------------------------------------------
    # Autopilot
    # ------------------------------------------------------------------

    @property
    def autopilot_path(self) -> Path:
        return self.directory / "autopilot_chain.json"

    @property
    def autopilot_mode_path(self) -> Path:
        return self.directory / "autopilot_mode.json"

    def autopilot_mode(self) -> str:
        with self._lock:
            self._load_autopilot()
            return self._autopilot_mode

    def chain_intact(self) -> bool:
        with self._lock:
            self._load_autopilot()
            return self._chain_intact

    def set_autopilot_mode(self, mode: str) -> Dict[str, Any]:
        normalized = str(mode or "").strip().lower()
        if normalized not in ("assess", "off"):
            return {
                "ok": False,
                "status": 400,
                "error": "mode must be assess or off",
                "code": "autopilot_mode_invalid",
            }
        with self._lock:
            self._load_autopilot()
            payload = seal({"mode": normalized, "updated_at": _now_iso()})
            try:
                _write_json(self.autopilot_mode_path, payload)
            except OSError:
                return {
                    "ok": False,
                    "status": 503,
                    "error": "Autopilot mode could not be saved.",
                    "code": "autopilot_mode_unavailable",
                }
            written = _read_json(self.autopilot_mode_path)
            if not written or not checksum_ok(written) or written.get("mode") != normalized:
                return {
                    "ok": False,
                    "status": 503,
                    "error": "Autopilot mode failed its checksum.",
                    "code": "autopilot_mode_unavailable",
                }
            self._autopilot_mode = normalized
            status = self._status_unlocked()
            status["ok"] = True
            return status

    def reseal_autopilot(self, actor: str) -> Dict[str, Any]:
        with self._lock:
            self._load_autopilot()
            if self._chain_intact:
                status = self._status_unlocked()
                status["resealed"] = False
                return status
            archive_name = ""
            path = self.autopilot_path
            if path.exists():
                archive = path.with_name(
                    f"autopilot_chain.broken-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
                )
                os.replace(path, archive)
                archive_name = archive.name
            self._chain = []
            self._chain_anchor = ""
            self._chain_intact = True
            sealed = self._append_assessment({
                "id": _assessment_id(),
                "ts": _now_iso(),
                "mode": self._autopilot_mode,
                "risk_level": "LOW",
                "risk_score": 0,
                "findings": ["Autopilot chain was resealed after a checksum failure."],
                "recommendations": ["The broken chain file was kept beside the new one."],
                "pipeline": {},
                "signals": {},
                "input_fingerprint": "",
                "actor": actor,
                "archive": archive_name,
                "action": "chain_resealed",
            })
            status = self._status_unlocked()
            status["resealed"] = bool(sealed)
            status["archive"] = archive_name
            return status

    def assess(self, telemetry: Mapping[str, Any]) -> Dict[str, Any]:
        """Record a pipeline assessment, or reuse the last one when nothing moved."""
        snapshot = dict(telemetry or {})
        with self._lock:
            self._load_autopilot()
            if self._autopilot_mode != "assess":
                status = self._status_unlocked()
                status["coalesced"] = False
                status["assessing"] = False
                return status
            if not self._chain_intact:
                status = self._status_unlocked()
                status["coalesced"] = False
                status["assessing"] = False
                status["findings"] = [
                    "Autopilot chain checksum failed. Assessments are paused until the chain is resealed."
                ]
                return status
            fingerprint = sha256_text(canonical(_signal_fingerprint(snapshot)))
            last = self._chain[-1] if self._chain else None
            if isinstance(last, dict) and last.get("input_fingerprint") == fingerprint:
                age = _age_seconds(str(last.get("ts") or ""))
                if age is not None and age < autopilot_cadence_seconds():
                    reused = dict(last)
                    reused["coalesced"] = True
                    reused["assessing"] = True
                    reused["chain_intact"] = True
                    reused["mode"] = self._autopilot_mode
                    return reused
            scored = score_pipeline(snapshot)
            record = {
                "id": _assessment_id(),
                "ts": _now_iso(),
                "mode": "assess",
                "action": "assess",
                "input_fingerprint": fingerprint,
                "closes_sessions": False,
                **scored,
            }
            if not self._append_assessment(record):
                return {
                    "ok": False,
                    "status": 503,
                    "error": "Autopilot assessment could not be sealed.",
                    "code": "autopilot_chain_unavailable",
                    "chain_intact": self._chain_intact,
                }
            stored = dict(self._chain[-1])
            stored["coalesced"] = False
            stored["assessing"] = True
            stored["chain_intact"] = True
            stored["mode"] = self._autopilot_mode
            return stored

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._load_generation()
            self._load_journal()
            self._load_autopilot()
            return self._status_unlocked()

    def _status_unlocked(self) -> Dict[str, Any]:
        last = dict(self._chain[-1]) if self._chain else None
        return {
            "mode": self._autopilot_mode,
            "cadence_seconds": autopilot_cadence_seconds(),
            "assessing": self._autopilot_mode == "assess",
            "chain_intact": self._chain_intact,
            "assessments_retained": len(self._chain),
            "generation": self._generation if self._generation_loaded else self.generation(),
            "generation_intact": self._generation_intact,
            "journal_intact": self._journal_intact,
            "last": last,
            "closes_sessions": False,
        }

    def _load_autopilot(self) -> None:
        if not self._autopilot_loaded:
            self._autopilot_loaded = True
            mode_data = _read_json(self.autopilot_mode_path) if self.autopilot_mode_path.exists() else None
            if mode_data and checksum_ok(mode_data) and mode_data.get("mode") in ("assess", "off"):
                self._autopilot_mode = str(mode_data["mode"])
            elif mode_data:
                # A damaged mode file keeps the center watching.
                self._autopilot_mode = "assess"
            chain = _read_json(self.autopilot_path) if self.autopilot_path.exists() else None
            if chain is None and not self.autopilot_path.exists():
                self._chain = []
                self._chain_anchor = ""
                self._chain_intact = True
            elif not chain or not checksum_ok(chain):
                self._chain = []
                self._chain_anchor = ""
                self._chain_intact = False
            else:
                entries = chain.get("entries") if isinstance(chain.get("entries"), list) else None
                anchor = str(chain.get("anchor") or "")
                if entries is None or not self._chain_ok(entries, anchor):
                    self._chain = []
                    self._chain_anchor = ""
                    self._chain_intact = False
                else:
                    self._chain = entries
                    self._chain_anchor = anchor
                    self._chain_intact = True

    def _append_assessment(self, entry: Mapping[str, Any]) -> bool:
        if not self._chain_intact:
            return False
        updated = self._append_chain_file(
            self.autopilot_path,
            self._chain,
            self._chain_anchor,
            dict(entry),
            limit=AUTOPILOT_RING,
        )
        if updated is None:
            return False
        written = _read_json(self.autopilot_path)
        anchor = str((written or {}).get("anchor") or "")
        self._chain = updated
        self._chain_anchor = anchor
        self._chain_intact = True
        return True


def _signal_fingerprint(telemetry: Mapping[str, Any]) -> Dict[str, Any]:
    keys = (
        "firewall_enabled",
        "ids_enabled",
        "file_scanner_enabled",
        "request_sanitizer_enabled",
        "generation_intact",
        "journal_intact",
        "malicious_attempts",
        "permanent_blocks",
        "blocked_ips",
        "active_alerts",
        "lockouts",
        "quarantined",
        "active_sessions",
        "customers",
        "policies",
        "claims",
        "billing",
    )
    return {key: telemetry.get(key) for key in keys}


def _age_seconds(ts: str) -> Optional[float]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _assessment_id() -> str:
    return f"CYB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _revoke_session_token(
    token: Any,
    sess: Any,
    revoke_jti: Optional[Callable[[str, float], None]],
) -> bool:
    if revoke_jti is None:
        return False
    jti = None
    exp = time.time() + 3600
    if isinstance(sess, Mapping):
        jti = sess.get("jti")
        raw_exp = sess.get("expires")
        try:
            exp = datetime.fromisoformat(str(raw_exp)).timestamp()
        except (TypeError, ValueError):
            pass
    if not jti and isinstance(token, str) and token.startswith("phins2_"):
        try:
            from security.auth_tokens import verify_v2_token

            claims = verify_v2_token(token)
        except Exception:
            claims = None
        if claims is not None:
            jti = claims.jti
            exp = claims.expires_at
    if not jti:
        return False
    revoke_jti(str(jti), float(exp))
    return True


_CENTER: Optional[CrisisCenter] = None
_CENTER_DIR: Optional[Path] = None


def get_crisis_center() -> CrisisCenter:
    global _CENTER, _CENTER_DIR
    directory = crisis_directory()
    if _CENTER is None or _CENTER_DIR != directory:
        _CENTER = CrisisCenter(directory)
        _CENTER_DIR = directory
    return _CENTER


def bind_durable_generation(
    read: Optional[Callable[[], Optional[Mapping[str, Any]]]],
    write: Optional[Callable[[Mapping[str, Any]], bool]],
) -> None:
    center = get_crisis_center()
    center._durable_read = read
    center._durable_write = write


def current_session_generation() -> int:
    try:
        return get_crisis_center().generation()
    except Exception:
        return 0


def session_generation_blocks(claims: Optional[Mapping[str, Any]]) -> bool:
    """True when ``claims`` were issued under a generation a drop has closed.

    A damaged generation file is handled inside the center, which moves the
    generation forward. An unexpected failure here leaves current sessions
    in place rather than locking the portal.
    """
    try:
        return get_crisis_center().blocks(claims)
    except Exception:
        return False


def crisis_public_status() -> Dict[str, Any]:
    center = get_crisis_center()
    status = center.status()
    return {
        "generation": status.get("generation", 0),
        "generation_intact": status.get("generation_intact", False),
        "journal_intact": status.get("journal_intact", False),
        "requester_included": True,
        "closes_business_records": False,
    }
