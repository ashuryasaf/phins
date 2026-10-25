"""Durable apply-chat sessions, keyed by the resume code the applicant holds.

A restart must reopen the same application: the same resume code, the same
answer chain, and the same drawn signature. Each session is one checksummed
document. A checksum that does not match is left on disk and is not resumed,
so a torn or edited file cannot be filed under the old code.

Database mode stores the document in ``agent_artifacts``
(``chat_application`` / ``session``), which already verifies sha256 on read.
Without a database the same document is an atomic file under
``PHINS_CHAT_SESSIONS_DIR``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger("phins.chat_session_store")

_AGENT_ID = "chat_application"
_KIND = "session"
_ID_RE = re.compile(r"^CHAPP-[A-Za-z0-9-]+$")


def canonical_text(payload: Any) -> str:
    """Stable JSON. Key order must not change the digest."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def session_digest(session: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_text(session).encode("utf-8")).hexdigest()


def _payload(session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "resume_code": session.get("resume_code"),
        "session": session,
    }


def _accept(artifact_id: str, payload: Any) -> Optional[Dict[str, Any]]:
    """Return the session when the envelope still names the same code."""
    if not isinstance(payload, dict):
        return None
    session = payload.get("session")
    if not isinstance(session, dict):
        return None
    if str(session.get("id") or "") != str(artifact_id or ""):
        return None
    if not _ID_RE.match(str(session.get("id") or "")):
        return None
    code = str(session.get("resume_code") or "")
    if not code.startswith("PHINS-CHAT-"):
        return None
    if str(payload.get("resume_code") or "") != code:
        return None
    return session


class ChatSessionStore(Protocol):
    def load(self) -> Tuple[List[Dict[str, Any]], int]:
        """Return ``(sessions, rejected_count)``."""

    def save(self, session: Dict[str, Any]) -> bool:
        """Persist one session. False means the memory copy is the only copy."""


def _default_directory() -> Path:
    configured = os.environ.get("PHINS_CHAT_SESSIONS_DIR")
    if configured:
        return Path(configured)
    if os.environ.get("PHINS_TEST_MODE", "").lower() in ("1", "true", "yes"):
        return Path(tempfile.gettempdir()) / f"phins_test_chat_sessions_{os.getpid()}"
    volume = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    for candidate in (volume, "/data"):
        if not candidate:
            continue
        root = Path(candidate)
        try:
            if root.is_dir() and os.access(root, os.W_OK):
                return root / "phins_chat_sessions"
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / "phins_chat_sessions"


class FileChatSessionStore:
    """One JSON file per application. The checksum covers the exact payload text."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, application_id: str) -> Path:
        if not _ID_RE.match(application_id):
            raise ValueError("application id is not a safe file name")
        return self.directory / f"{application_id}.json"

    def load(self) -> Tuple[List[Dict[str, Any]], int]:
        if not self.directory.is_dir():
            return [], 0
        accepted: List[Dict[str, Any]] = []
        rejected = 0
        for path in sorted(self.directory.glob("CHAPP-*.json")):
            session = self._read(path)
            if session is None:
                rejected += 1
                continue
            accepted.append(session)
        if rejected:
            logger.error(
                "chat session store skipped %s file(s) whose checksum did not match",
                rejected,
            )
        return accepted, rejected

    def _read(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.error("chat session file %s could not be read: %s", path.name, exc)
            return None
        if not isinstance(envelope, dict):
            return None
        text = envelope.get("payload_json")
        digest = str(envelope.get("checksum") or "")
        if not isinstance(text, str) or not digest:
            return None
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != digest:
            logger.error("chat session checksum mismatch for %s; file was not resumed", path.name)
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return _accept(path.stem, payload)

    def save(self, session: Dict[str, Any]) -> bool:
        application_id = str(session.get("id") or "")
        try:
            text = canonical_text(_payload(session))
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            body = json.dumps(
                {"checksum": digest, "payload_json": text},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.directory, 0o700)
            except OSError:
                pass
            target = self._path(application_id)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f".{application_id}.",
                suffix=".tmp",
                delete=False,
            )
            tmp_name = handle.name
            try:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, target)
            try:
                dir_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except (OSError, TypeError, ValueError) as exc:
            logger.error("chat session %s was not written: %s", application_id, exc)
            return False
        confirmed = self._read(target)
        if confirmed is None or session_digest(confirmed) != session_digest(session):
            logger.error("chat session %s failed read-back; resume was not sealed", application_id)
            return False
        return True


class ArtifactChatSessionStore:
    """``agent_artifacts`` copy. The repository refuses a row whose checksum fails."""

    def load(self) -> Tuple[List[Dict[str, Any]], int]:
        try:
            from database.manager import DatabaseManager
        except ImportError as exc:
            logger.error("chat session store has no database manager: %s", exc)
            return [], 0
        accepted: List[Dict[str, Any]] = []
        rejected = 0
        try:
            with DatabaseManager() as db:
                rows = list(db.agent_artifacts.iter_payloads(_AGENT_ID, _KIND))
        except Exception as exc:
            logger.error("chat sessions could not be loaded: %s", exc)
            return [], 0
        for artifact_id, payload, _updated, _meta in rows:
            session = _accept(artifact_id, payload)
            if session is None:
                rejected += 1
                logger.error(
                    "chat session %s envelope does not match its id; row was not resumed",
                    artifact_id,
                )
                continue
            accepted.append(session)
        return accepted, rejected

    def save(self, session: Dict[str, Any]) -> bool:
        application_id = str(session.get("id") or "")
        if not _ID_RE.match(application_id):
            logger.error("chat session id %s was not written", application_id)
            return False
        try:
            from database.manager import DatabaseManager

            with DatabaseManager() as db:
                db.agent_artifacts.upsert(
                    application_id,
                    agent_id=_AGENT_ID,
                    kind=_KIND,
                    payload=_payload(session),
                    subject_type="policy_application",
                    subject_id=application_id,
                )
        except Exception as exc:
            logger.error("chat session %s was not written: %s", application_id, exc)
            return False
        return True


def open_chat_session_store(directory: Optional[str] = None) -> ChatSessionStore:
    """File store when a directory is requested or the database is off."""
    if directory:
        return FileChatSessionStore(Path(directory))
    try:
        from services.hydrated_store import db_mode_enabled
    except ImportError:
        db_mode_enabled = lambda: False  # type: ignore
    if db_mode_enabled():
        return ArtifactChatSessionStore()
    return FileChatSessionStore(_default_directory())
