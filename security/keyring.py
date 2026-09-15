"""
PHINS Platform Keyring — durable data-encryption keys without hand configuration.

Problem this solves
-------------------
``security.vault`` encrypts regulated payloads (customer ID numbers, assessment
facts, actuarial tables) with a Fernet key taken from ``PHINS_ENCRYPTION_KEY``.
A deployment that never set that variable had no key at all, so the customer
identity master (which refuses to store a personal ID in clear) failed closed
with ``identity_vault_unavailable`` on the customer's first login.

Model: **one data key per purpose, many records** (a platform DEK). The key is
created once and then reused by every record and every replica:

* ``vault``          — Fernet key behind ``security.vault`` (all vaulted data)
* ``identity-hash``  — HMAC key for ``customers.national_id_hash`` (lookups /
                       uniqueness / cross-pipeline join key)

Resolution order (per purpose)
------------------------------
1. An explicitly configured environment variable always wins
   (``PHINS_ENCRYPTION_KEY`` / ``PHINS_IDENTITY_HASH_KEY``).
2. Otherwise the durable keyring:
   * ``USE_DATABASE=true`` -> row in ``platform_keys`` (shared by all replicas,
     created race-safely with a fixed primary key). No file fallback in DB mode:
     a replica that silently minted its own key would produce data the others
     cannot read, so DB failure fails closed instead.
   * in-memory mode -> JSON file at ``PHINS_KEYRING_PATH`` (default: the
     Railway volume / ``/data`` when mounted, else the temp dir, mirroring the
     ledger persistence file), written atomically with mode 0600.
3. A key that already exists in the keyring is never replaced. Once the first
   record is encrypted/hashed with it, the key is authoritative for the life of
   the data; ``vault_keys()`` still returns *both* the env key and the ring key
   so blobs written under either remain decryptable (MultiFernet).
4. ``identity-hash`` continuity: before the keyring existed the hash fell back
   to the raw bytes of ``PHINS_ENCRYPTION_KEY``. That exact behaviour is kept
   (an existing ring key > raw ``PHINS_ENCRYPTION_KEY`` > mint a ring key), so
   no stored ``national_id_hash`` ever stops matching, and the env key is never
   copied into the keyring store.

Fingerprints (``sha256(material)[:16]``) are safe to log and are what
``describe()`` exposes to operators; key material never leaves this module
except to the crypto primitives.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PURPOSE_VAULT = "vault"
PURPOSE_IDENTITY_HASH = "identity-hash"
PURPOSES = (PURPOSE_VAULT, PURPOSE_IDENTITY_HASH)

_ENV_FOR_PURPOSE = {
    PURPOSE_VAULT: "PHINS_ENCRYPTION_KEY",
    PURPOSE_IDENTITY_HASH: "PHINS_IDENTITY_HASH_KEY",
}

_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_FILE_VERSION = 1


class KeyringError(RuntimeError):
    """The durable keyring could not be read or created (fail closed)."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).lower() in ("1", "true", "yes", "y", "on")


def _db_enabled() -> bool:
    # Same rule as web_portal/server.py: database mode is the documented
    # default, so only an explicit opt-out selects the file backend. Reading it
    # any other way would let a deployment that trusts the default keep its
    # keys in a local file while its data lives in the shared database.
    return str(os.environ.get("USE_DATABASE", "true")).strip().lower() not in ("false", "0", "no")


def fingerprint(material: str) -> str:
    return hashlib.sha256(str(material).encode("utf-8")).hexdigest()[:16]


def is_valid_fernet_key(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        return len(base64.urlsafe_b64decode(value.strip().encode("utf-8"))) == 32
    except Exception:
        return False


def _generate_material(purpose: str) -> str:
    # 32 random bytes, urlsafe base64: a Fernet key for ``vault`` and an
    # equally strong HMAC key for ``identity-hash``.
    from cryptography.fernet import Fernet  # type: ignore

    return Fernet.generate_key().decode("ascii")


def _legacy_hash_material() -> Optional[str]:
    """Pre-keyring behaviour: ``national_id_hash`` was keyed with the raw bytes
    of ``PHINS_ENCRYPTION_KEY`` when no dedicated hash key was set. Deployments
    that already hashed IDs that way must keep matching, so that exact value is
    still used (in memory only — it is never copied into the keyring store)."""
    value = (os.environ.get("PHINS_ENCRYPTION_KEY") or "").strip()
    return value or None


def _explicit_env(purpose: str) -> Optional[str]:
    var = _ENV_FOR_PURPOSE.get(purpose)
    value = (os.environ.get(var) or "").strip() if var else ""
    if not value:
        return None
    if purpose == PURPOSE_VAULT and not is_valid_fernet_key(value):
        logger.error("%s is set but is not a valid Fernet key; ignoring it", var)
        return None
    return value


# ---------------------------------------------------------------------------
# file backend (in-memory / no-database deployments)
# ---------------------------------------------------------------------------
def keyring_path() -> str:
    explicit = os.environ.get("PHINS_KEYRING_PATH")
    if explicit:
        return explicit
    for d in (os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""), "/data"):
        if d and os.path.isdir(d):
            return os.path.join(d, "phins_keyring.json")
    return os.path.join(tempfile.gettempdir(), "phins_keyring.json")


def _file_read(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"version": _FILE_VERSION, "keys": {}}
    if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
        raise KeyringError(f"keyring file {path} is malformed")
    return data


def _file_write(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # mkstemp: unpredictable name, O_CREAT|O_EXCL (and O_NOFOLLOW where
    # available), mode 0600 -- no symlink/pre-planted-file race in the key dir.
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".phins_keyring.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@contextmanager
def _file_mint_lock(path: str):
    """Serialize the read-modify-write of the ring across processes.

    Without it two processes minting *different* purposes each replace the file
    with a snapshot that never held the other's key, so one key is lost. The
    lock lives on a sidecar file because the ring itself is replaced (a new
    inode) on every write. Platforms without ``fcntl`` keep the old behaviour.
    """
    try:
        import fcntl  # type: ignore
    except ImportError:  # pragma: no cover - non-POSIX
        yield
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _file_get_or_create(purpose: str, create: bool) -> Optional[Dict[str, Any]]:
    path = keyring_path()
    try:
        entry = _file_read(path)["keys"].get(purpose)
        if entry and entry.get("material"):
            return dict(entry, source=entry.get("source") or "file")
        if not create:
            return None
        with _file_mint_lock(path):
            # Re-read under the lock: the file on disk is the single source of
            # truth, and every purpose already in it must survive this write.
            data = _file_read(path)
            entry = data["keys"].get(purpose)
            if entry and entry.get("material"):
                logger.info("keyring: another process created the %s key first; using it", purpose)
            else:
                material = _generate_material(purpose)
                entry = {
                    "material": material,
                    "fingerprint": fingerprint(material),
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "source": "generated",
                }
                data["keys"][purpose] = entry
                _file_write(path, data)
        if path.startswith(tempfile.gettempdir()):
            logger.warning(
                "keyring: %s key stored at ephemeral path %s — set PHINS_KEYRING_PATH "
                "(or mount /data) so vaulted data survives a container restart",
                purpose, path,
            )
        return dict(entry, source=entry.get("source") or "file")
    except KeyringError:
        raise
    except Exception as exc:
        raise KeyringError(f"keyring file {path} unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# database backend
# ---------------------------------------------------------------------------
def _db_get_or_create(purpose: str, create: bool) -> Optional[Dict[str, Any]]:
    try:
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        from database import get_engine
        from database.models import PlatformKey
    except Exception as exc:  # pragma: no cover - DB stack missing
        raise KeyringError(f"database keyring unavailable: {exc}") from exc

    key_id = f"KEY-{purpose.upper()}"
    try:
        engine = get_engine()
        # The table is part of Base.metadata (created by init_database); make
        # sure it exists even when the keyring is touched before schema sync.
        PlatformKey.__table__.create(engine, checkfirst=True)

        def _read(session: Session) -> Optional[Dict[str, Any]]:
            row = session.query(PlatformKey).filter(PlatformKey.purpose == purpose).first()
            if row is None:
                return None
            return {
                "material": row.material,
                "fingerprint": row.fingerprint,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "source": row.source or "database",
            }

        with Session(engine) as session:
            found = _read(session)
            if found or not create:
                return found
            material = _generate_material(purpose)
            session.add(PlatformKey(
                id=key_id,
                purpose=purpose,
                material=material,
                fingerprint=fingerprint(material),
                source="generated",
                created_by="keyring",
            ))
            logger.warning(
                "[SECURITY] keyring: minted the %s key into platform_keys (fingerprint %s). "
                "It is stored alongside the data it protects; set %s from a KMS/secret "
                "manager for key/ciphertext separation.",
                purpose, fingerprint(material), _ENV_FOR_PURPOSE[purpose],
            )
            try:
                session.commit()
            except IntegrityError:
                # Lost the race against another replica: its key is the one.
                session.rollback()
            found = _read(session)
            if found is None:
                raise KeyringError(f"platform_keys row for {purpose} vanished after insert")
            return found
    except KeyringError:
        raise
    except Exception as exc:
        raise KeyringError(f"database keyring unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def ring_key(purpose: str, *, create: bool = True) -> Optional[Dict[str, Any]]:
    """Return the durable keyring entry for ``purpose`` (creating it if asked).

    Never consults the environment override; see :func:`resolve`. Raises
    :class:`KeyringError` when the backing store cannot be used.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown key purpose: {purpose}")
    with _LOCK:
        cached = _CACHE.get(purpose)
        if cached:
            return cached
        entry = _db_get_or_create(purpose, create) if _db_enabled() else _file_get_or_create(purpose, create)
        if entry:
            _CACHE[purpose] = entry
        return entry


def resolve(purpose: str) -> Dict[str, Any]:
    """Resolve the *primary* key for ``purpose``.

    Returns ``{"material", "fingerprint", "source"}`` where ``source`` is
    ``env`` for an operator-supplied key, otherwise the keyring backend's
    label. Raises :class:`KeyringError` if neither is available.
    """
    explicit = _explicit_env(purpose)
    if explicit:
        return {"material": explicit, "fingerprint": fingerprint(explicit), "source": "env"}
    if purpose == PURPOSE_IDENTITY_HASH:
        # Continuity order: a ring key that already exists is authoritative
        # (the deployment has hashed under it); otherwise the legacy
        # PHINS_ENCRYPTION_KEY raw bytes reproduce every pre-keyring hash
        # exactly; only a deployment with neither mints a ring key.
        existing = ring_key(purpose, create=False)
        if existing:
            return existing
        legacy = _legacy_hash_material()
        if legacy:
            return {"material": legacy, "fingerprint": fingerprint(legacy), "source": "legacy-encryption-key"}
    entry = ring_key(purpose, create=True)
    if not entry:
        raise KeyringError(f"no {purpose} key available")
    return entry


def vault_keys() -> List[str]:
    """Fernet keys for ``security.vault``: primary first, then any other key
    that data may have been written under (so rotation never orphans blobs).
    """
    keys: List[str] = []
    explicit = _explicit_env(PURPOSE_VAULT)
    if explicit:
        keys.append(explicit)
    try:
        entry = ring_key(PURPOSE_VAULT, create=not explicit)
    except KeyringError as exc:
        if not explicit:
            logger.error("keyring: %s", exc)
        entry = None
    if entry and is_valid_fernet_key(entry.get("material")) and entry["material"] not in keys:
        keys.append(entry["material"])
    return keys


def identity_hash_key() -> bytes:
    """Stable HMAC key for ``national_id_hash`` (env override, else keyring)."""
    return resolve(PURPOSE_IDENTITY_HASH)["material"].encode("utf-8")


def describe() -> Dict[str, Any]:
    """Operator-facing summary (fingerprints only; never key material)."""
    out: Dict[str, Any] = {
        "backend": "database" if _db_enabled() else "file",
        "path": None if _db_enabled() else keyring_path(),
        "keys": {},
    }
    for purpose in PURPOSES:
        try:
            info = resolve(purpose)
            out["keys"][purpose] = {
                "available": True,
                "source": info["source"],
                "fingerprint": info["fingerprint"],
                "env_var": _ENV_FOR_PURPOSE[purpose],
            }
        except KeyringError as exc:
            out["keys"][purpose] = {"available": False, "error": str(exc), "env_var": _ENV_FOR_PURPOSE[purpose]}
    return out


def reset_cache() -> None:
    """Drop the in-process cache (tests / after a backend switch)."""
    with _LOCK:
        _CACHE.clear()
