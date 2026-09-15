"""Customer identity master: personal (national) ID number + nationality.

One write path for every surface that learns a customer's personal ID —
registration, the mandatory one-time login prompt, classic/chat apply, the
quote form, admin correction, assessment-center Mislaka linking — so every
downstream pipeline (underwriting, claims, assessments, pension, agents)
reads the same durable, normalised value from the customer record.

Integrity rules
---------------
* The plaintext ID is stored only encrypted at rest (``security.vault``) on
  the customer record; API responses, audit rows, ledger anchors and pipeline
  records carry a keyed hash and the last four characters, never the number.
* Nationality is an ISO 3166-1 alpha-2 code resolved from free text
  ("Israel", "ISR", "ישראל" -> ``IL``); the ID is validated and normalised per
  nationality (Israeli Teudat Zehut checksum, US SSN, UK NINO, Spanish DNI/NIE,
  Brazilian CPF, Italian codice fiscale, generic elsewhere).
* Write-once for the customer: a second, different value is refused (409);
  the same value is idempotent. Only an admin correction with a reason may
  change it, and every correction is appended to ``identity_history`` and
  anchored on the platform event ledger — nothing is overwritten silently.
* One person, one customer: the ``(nationality, national_id_hash)`` pair is
  unique across customers (service check in every mode, unique index in the
  database).
* A pipeline payload whose ID disagrees with the customer's recorded identity
  is flagged ``identity_mismatch`` for review — never auto-resolved.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from security.vault import decrypt_json, encrypt_json
from services.countries import country_name, resolve_country, search_countries

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

IDENTITY_SOURCES = (
    "registration", "login_prompt", "application", "chat", "quote",
    "assessment", "pension", "admin", "import",
)

# Fields the service owns on a customer record (in-memory dict and DB row).
# The encrypted number is NOT among them: customer dicts are serialised by
# many endpoints, so the blob is kept in ``_ENCRYPTED`` (in-memory mode) and
# on the ``customers.national_id_encrypted`` column (DB mode) only.
IDENTITY_FIELDS = (
    "nationality", "national_id_hash", "national_id_last4",
    "identity_captured_at", "identity_source", "identity_history",
)

# customer_id -> vault blob JSON (process-local; DB mode also writes the column)
_ENCRYPTED: Dict[str, str] = {}


def reset_process_state() -> None:
    """Test hook: forget process-local encrypted blobs (durable rows stay)."""
    _ENCRYPTED.clear()

# Legacy keys some older records/payloads used for the plaintext number. The
# service reads them once (migration) and never writes them back.
LEGACY_PLAINTEXT_KEYS = ("national_id", "id_number", "personal_id", "nationalId")


class IdentityError(ValueError):
    """Validation / policy failure with an API-friendly code and HTTP status."""

    def __init__(self, message: str, code: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {"error": str(self), "code": self.code}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def strict_mode() -> bool:
    """Whether new applications/claims must carry a complete identity.

    ``PHINS_IDENTITY_REQUIRED`` wins when set. Otherwise identity is required
    everywhere except under ``PHINS_TEST_MODE`` (the embedded test server),
    where the many pre-existing flows post applications without an ID; tests
    that exercise the gate enable it explicitly.
    """
    raw = os.environ.get("PHINS_IDENTITY_REQUIRED")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")
    return str(os.environ.get("PHINS_TEST_MODE", "")).lower() not in ("1", "true", "yes", "y")


def _hash_key() -> bytes:
    """Deployment-stable key for the lookup hash.

    ``PHINS_IDENTITY_HASH_KEY`` wins when set; otherwise the durable platform
    keyring answers: an existing ring ``identity-hash`` key, else the raw
    ``PHINS_ENCRYPTION_KEY`` bytes (the historical fallback, so every
    pre-keyring hash keeps matching byte for byte), else a ring key minted once
    per deployment and reused for every customer. The key is the
    join key for every pipeline record that references a customer identity, so
    it must never change for the life of the data — the keyring never replaces
    an existing key. An unusable keyring fails closed rather than hashing with a
    guessable constant.
    """
    from security.keyring import KeyringError, identity_hash_key

    try:
        return identity_hash_key()
    except KeyringError as exc:
        raise IdentityError(
            f"Identity keyring is unavailable ({exc}); the ID number was not processed",
            "identity_vault_unavailable", 503) from exc


# ---------------------------------------------------------------------------
# Nationality + ID validation
# ---------------------------------------------------------------------------
def resolve_nationality(value: Any) -> Optional[str]:
    return resolve_country(value)


def nationality_name(code: Any) -> Optional[str]:
    return country_name(code)


def countries_autocomplete(query: Any, limit: int = 12) -> List[Dict[str, str]]:
    return search_countries(query, limit=limit)


def israeli_id_checksum_ok(value: str) -> bool:
    """Teudat Zehut Luhn variant (same algorithm the chat + assessment center use)."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 9 or len(set(digits)) == 1:
        return False
    total = 0
    for i, digit in enumerate(digits):
        weighted = digit * (1 if i % 2 == 0 else 2)
        if weighted > 9:
            weighted -= 9
        total += weighted
    return total % 10 == 0


def _cpf_ok(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1)))
        check = (total * 10) % 11
        if (0 if check == 10 else check) != int(digits[size]):
            return False
    return True


def _spanish_letter(number: int) -> str:
    return "TRWAGMYFPDXBNJZSQVHLCKE"[number % 23]


ID_RULES: Dict[str, Dict[str, str]] = {
    "IL": {"label": "Teudat Zehut (9 digits)", "pattern": r"^\d{5,9}$", "example": "123456782"},
    "US": {"label": "Social Security Number (9 digits)", "pattern": r"^\d{9}$", "example": "123456789"},
    "GB": {"label": "National Insurance Number", "pattern": r"^[A-Z]{2}\d{6}[A-D]$", "example": "AB123456C"},
    "ES": {"label": "DNI / NIE", "pattern": r"^([0-9]{8}|[XYZ][0-9]{7})[A-Z]$", "example": "12345678Z"},
    "BR": {"label": "CPF (11 digits)", "pattern": r"^\d{11}$", "example": "12345678909"},
    "IT": {"label": "Codice fiscale (16 characters)", "pattern": r"^[A-Z0-9]{16}$", "example": "RSSMRA85T10A562S"},
    "IN": {"label": "Aadhaar (12 digits)", "pattern": r"^[2-9]\d{11}$", "example": "234567890123"},
    "FR": {"label": "Numéro de sécurité sociale (13–15 digits)", "pattern": r"^\d{13,15}$", "example": "1850578006048"},
}
GENERIC_RULE = {"label": "National ID / passport number (4–20 letters or digits)",
                "pattern": r"^[A-Z0-9]{4,20}$", "example": "AB1234567"}


def id_rule_for(nationality: Any) -> Dict[str, str]:
    code = str(nationality or "").upper()
    return dict(ID_RULES.get(code, GENERIC_RULE), nationality=code or None)


def normalize_national_id(raw: Any, nationality: Any) -> Tuple[str, str]:
    """Validate ``raw`` for ``nationality`` and return ``(alpha2, normalized_id)``.

    Raises ``IdentityError`` (400) with a specific code when either part is
    invalid. Separators (spaces, dashes, dots) are stripped; letters are upper
    cased; Israeli IDs are zero-padded to 9 digits before the checksum.
    """
    code = resolve_nationality(nationality)
    if not code:
        raise IdentityError("nationality is required (country name or ISO code)", "nationality_invalid")
    cleaned = re.sub(r"[\s\-\.\u2013/]", "", str(raw or "").strip()).upper()
    if not cleaned:
        raise IdentityError("national_id is required", "national_id_required")
    rule = ID_RULES.get(code, GENERIC_RULE)
    if not re.fullmatch(rule["pattern"], cleaned):
        raise IdentityError(f"national_id does not match the {rule['label']} format",
                            "national_id_invalid")
    if code == "IL":
        cleaned = cleaned.zfill(9)
        if not israeli_id_checksum_ok(cleaned):
            raise IdentityError("national_id failed the Israeli ID checksum", "national_id_invalid")
    elif code == "US":
        area, group, serial = cleaned[:3], cleaned[3:5], cleaned[5:]
        if area in ("000", "666") or area.startswith("9") or group == "00" or serial == "0000":
            raise IdentityError("national_id is not a valid SSN", "national_id_invalid")
    elif code == "BR":
        if not _cpf_ok(cleaned):
            raise IdentityError("national_id failed the CPF checksum", "national_id_invalid")
    elif code == "ES":
        body, letter = cleaned[:-1], cleaned[-1]
        numeric = body.translate(str.maketrans("XYZ", "012"))
        if _spanish_letter(int(numeric)) != letter:
            raise IdentityError("national_id failed the DNI/NIE check letter", "national_id_invalid")
    elif code == "GB":
        if cleaned[:2] in ("BG", "GB", "NK", "KN", "TN", "NT", "ZZ") or cleaned[0] in "DFIQUV" or cleaned[1] in "DFIQUVO":
            raise IdentityError("national_id is not a valid National Insurance Number", "national_id_invalid")
    return code, cleaned


# ---------------------------------------------------------------------------
# Hashing / masking / encryption
# ---------------------------------------------------------------------------
def hash_national_id(nationality: str, normalized_id: str) -> str:
    message = f"{str(nationality).upper()}:{normalized_id}".encode("utf-8")
    return hmac.new(_hash_key(), message, hashlib.sha256).hexdigest()


def mask_national_id(normalized_id: Any) -> str:
    text = str(normalized_id or "")
    if not text:
        return ""
    tail = text[-4:] if len(text) > 4 else text[-1:]
    return "*" * max(3, len(text) - len(tail)) + tail


def _plaintext_vault_allowed() -> bool:
    """Whether an unkeyed vault (``scheme: plain``) may hold the ID.

    Only for the embedded test server or an explicit local-dev opt-in; a real
    deployment whose vault key cannot be resolved must fail closed rather than
    write a personal ID in clear. In practice the platform keyring
    (``security/keyring.py``) mints a durable key on first use, so this guard
    only trips when that keyring itself is unusable.
    """
    for var in ("PHINS_IDENTITY_ALLOW_PLAINTEXT_VAULT", "PHINS_TEST_MODE"):
        if str(os.environ.get(var, "")).lower() in ("1", "true", "yes", "y", "on"):
            return True
    return False


def _encrypt(normalized_id: str, nationality: str) -> str:
    blob = encrypt_json({"national_id": normalized_id, "nationality": nationality})
    if blob.scheme != "fernet" and not _plaintext_vault_allowed():
        raise IdentityError(
            "Identity vault key is unavailable (platform keyring could not be read or created); "
            "the ID number was not stored",
            "identity_vault_unavailable", 503)
    return blob.to_json()


def vault_status() -> Dict[str, Any]:
    """Operator-facing health of the identity vault/hash keys (fingerprints only)."""
    from security.keyring import describe

    info = describe()
    keys = info.get("keys", {})
    return {
        "backend": info.get("backend"),
        "path": info.get("path"),
        "vault": keys.get("vault", {}),
        "identity_hash": keys.get("identity-hash", {}),
        "ready": bool(keys.get("vault", {}).get("available") and keys.get("identity-hash", {}).get("available")),
    }


def _store_encrypted(customer_id: str, blob: Optional[str]) -> None:
    if blob is None:
        _ENCRYPTED.pop(customer_id, None)
    else:
        _ENCRYPTED[customer_id] = blob
    if _db_enabled():
        from database.manager import DatabaseManager  # raises to the caller: DB mode must persist
        with DatabaseManager() as db:
            if db.customers.get_by_id(customer_id) is not None:
                db.customers.update(customer_id, national_id_encrypted=blob)


def _load_encrypted(customer_id: str) -> Optional[str]:
    blob = _ENCRYPTED.get(customer_id)
    if blob:
        return blob
    if _db_enabled():
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                row = db.customers.get_by_id(customer_id)
                blob = getattr(row, "national_id_encrypted", None) if row is not None else None
        except Exception as exc:
            logger.debug("identity blob load failed for %s: %s", customer_id, exc)
            blob = None
        if blob:
            _ENCRYPTED[customer_id] = str(blob)
            return str(blob)
    return None


def reveal_national_id(customer_id: Any) -> Optional[str]:
    """Decrypt the stored ID for a server-side regulated use (e.g. Mislaka).

    Never route the return value to an HTTP response.
    """
    blob = _load_encrypted(str(customer_id or ""))
    if not blob:
        return None
    try:
        data = decrypt_json(blob, default=None)
    except Exception:
        return None
    if isinstance(data, dict):
        return str(data.get("national_id") or "") or None
    return None


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------
def is_complete(record: Optional[Dict[str, Any]]) -> bool:
    return bool(record and record.get("national_id_hash") and record.get("nationality"))


def identity_required_for(record: Optional[Dict[str, Any]]) -> bool:
    """The one-time login prompt is due until the record is complete."""
    return not is_complete(record)


def _history(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = record.get("identity_history")
    if not raw:
        return []
    if isinstance(raw, list):
        return [h for h in raw if isinstance(h, dict)]
    try:
        parsed = json.loads(str(raw))
        return [h for h in parsed if isinstance(h, dict)] if isinstance(parsed, list) else []
    except Exception:
        return []


def identity_status(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """PII-safe view for the customer/admin UI (masked ID, no plaintext)."""
    record = record or {}
    complete = is_complete(record)
    last4 = str(record.get("national_id_last4") or "")
    return {
        "complete": complete,
        "required": not complete,
        "nationality": record.get("nationality") if complete else None,
        "nationality_name": nationality_name(record.get("nationality")) if complete else None,
        "national_id_masked": ("*" * 5 + last4) if complete and last4 else None,
        "captured_at": record.get("identity_captured_at") if complete else None,
        "source": record.get("identity_source") if complete else None,
        "corrections": len(_history(record)),
    }


def identity_reference(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What a pipeline record (application, claim, assessment) carries.

    A stable, PII-free pointer to the customer's identity: hash for equality
    checks and audit joins, last4 for human recognition, nationality for
    jurisdiction-specific processing. Never the number.
    """
    if not is_complete(record):
        return None
    record = record or {}
    last4 = str(record.get("national_id_last4") or "")
    return {
        "nationality": record.get("nationality"),
        "national_id_hash": record.get("national_id_hash"),
        "national_id_last4": last4,
        "national_id_masked": "*" * 5 + last4,
        "captured_at": record.get("identity_captured_at"),
    }


def matches(record: Optional[Dict[str, Any]], national_id: Any, nationality: Any = None) -> Optional[bool]:
    """Compare a supplied ID against the recorded identity by hash.

    Returns None when the record has no identity yet (nothing to compare),
    True/False otherwise. An unparseable supplied value counts as a mismatch.
    """
    if not is_complete(record):
        return None
    record = record or {}
    code = resolve_nationality(nationality) or str(record.get("nationality"))
    try:
        code, normalized = normalize_national_id(national_id, code)
    except IdentityError:
        return False
    return hmac.compare_digest(hash_national_id(code, normalized), str(record.get("national_id_hash") or ""))


# ---------------------------------------------------------------------------
# Lookup / uniqueness
# ---------------------------------------------------------------------------
def _db_enabled() -> bool:
    return str(os.environ.get("USE_DATABASE", "")).lower() in ("true", "1", "yes")


def find_customer_id_by_identity(nationality: str, national_id_hash: str,
                                 customers: Optional[Dict[str, Any]] = None,
                                 exclude_customer_id: Optional[str] = None) -> Optional[str]:
    """Return the id of the customer already holding this identity, if any."""
    if customers is not None:
        try:
            for cid, rec in list(customers.items()):
                if cid == exclude_customer_id or not isinstance(rec, dict):
                    continue
                if rec.get("national_id_hash") == national_id_hash and \
                        str(rec.get("nationality") or "").upper() == nationality:
                    return str(cid)
        except Exception as exc:  # store iteration is best-effort
            logger.debug("identity scan failed: %s", exc)
    if _db_enabled():
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                row = db.customers.get_by_identity(nationality, national_id_hash)
                if row is not None and str(row.id) != str(exclude_customer_id):
                    return str(row.id)
        except Exception as exc:
            logger.debug("identity DB lookup failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Write side
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.utcnow().isoformat()


def _store_record(customers: Dict[str, Any], customer_id: str, record: Dict[str, Any],
                  mirrors: Iterable[Dict[str, Any]] = ()) -> None:
    """Write the record back through every store so both modes persist.

    ``customers`` may be a plain dict (in-memory mode: the record object is
    mutated in place and re-assigned, a no-op) or a ``DatabaseDict`` (DB mode:
    ``__getitem__`` returned a copy, so the assignment is the write-through).
    """
    customers[customer_id] = record
    for mirror in mirrors:
        try:
            if customer_id in mirror and isinstance(mirror[customer_id], dict) and mirror[customer_id] is not record:
                mirror[customer_id].update({k: record.get(k) for k in IDENTITY_FIELDS})
        except Exception:
            pass


def _verify_durable(customer_id: str, nationality: str, national_id_hash: str,
                    blob: Optional[str]) -> None:
    """Read the row back after the write (DB mode only).

    Repository updates swallow ``IntegrityError`` and return ``None``, so a
    write refused by the unique index (a concurrent registration with the same
    ID) would otherwise leave the hash in the process cache but not in the
    database. Fail closed instead; the caller rolls the record back.
    """
    if not _db_enabled():
        return
    from database.manager import DatabaseManager
    with DatabaseManager() as db:
        row = db.customers.get_by_id(customer_id)
    if row is None:
        return  # not a DB-backed customer (in-memory record while DB is on)
    if str(getattr(row, "national_id_hash", "") or "") != national_id_hash or \
            str(getattr(row, "nationality", "") or "").upper() != nationality:
        raise IdentityError(
            "This ID number is already registered to another customer",
            "identity_in_use", 409)
    if blob and str(getattr(row, "national_id_encrypted", "") or "") != blob:
        raise IdentityError("Identity could not be stored durably", "identity_store_failed", 503)


def _strip_legacy_plaintext(record: Dict[str, Any]) -> None:
    for key in LEGACY_PLAINTEXT_KEYS:
        if key in record:
            record[key] = mask_national_id(record.get(key))


def set_identity(customers: Dict[str, Any], customer_id: str, national_id: Any, nationality: Any, *,
                 source: str, actor: str, allow_override: bool = False, reason: Optional[str] = None,
                 mirrors: Iterable[Dict[str, Any]] = (), audit: Any = None,
                 ledger: Any = None) -> Dict[str, Any]:
    """Record a customer's identity through the single write path.

    Returns ``identity_status(record)`` plus ``changed`` (False when the same
    identity was already recorded — idempotent retry). Raises ``IdentityError``:
    404 unknown customer, 400 invalid input, 409 ``identity_already_set`` when a
    different identity exists and ``allow_override`` is False, 409
    ``identity_in_use`` when another customer holds this identity, 400
    ``reason_required`` for an override without a reason.
    """
    if source not in IDENTITY_SOURCES:
        raise IdentityError(f"unknown identity source {source!r}", "source_invalid", 500)
    code, normalized = normalize_national_id(national_id, nationality)
    new_hash = hash_national_id(code, normalized)
    with _LOCK:
        try:
            record = customers[customer_id]
        except KeyError:
            record = None
        if not isinstance(record, dict):
            raise IdentityError("Customer not found", "customer_not_found", 404)

        current_hash = record.get("national_id_hash")
        current_code = str(record.get("nationality") or "").upper()
        if current_hash:
            if hmac.compare_digest(str(current_hash), new_hash) and current_code == code:
                status = identity_status(record)
                status["changed"] = False
                return status
            if not allow_override:
                raise IdentityError(
                    "An identity is already recorded for this customer; contact support to correct it",
                    "identity_already_set", 409)
            if not (reason or "").strip():
                raise IdentityError("A reason is required to correct a recorded identity",
                                    "reason_required", 400)

        holder = find_customer_id_by_identity(code, new_hash, customers, exclude_customer_id=customer_id)
        if holder:
            raise IdentityError("This ID number is already registered to another customer",
                                "identity_in_use", 409)

        now = _now()
        history = _history(record)
        if current_hash:
            history.append({
                "previous_nationality": current_code or None,
                "previous_national_id_hash": current_hash,
                "previous_national_id_last4": record.get("national_id_last4"),
                "changed_at": now,
                "changed_by": actor,
                "reason": (reason or "").strip(),
                "source": source,
            })
        previous_fields = {k: record.get(k) for k in IDENTITY_FIELDS}
        previous_blob = _ENCRYPTED.get(customer_id)
        # Encrypted number first: if the durable write fails nothing else moves.
        _store_encrypted(customer_id, _encrypt(normalized, code))
        record.update({
            "nationality": code,
            "national_id_hash": new_hash,
            "national_id_last4": normalized[-4:],
            "identity_captured_at": now,
            "identity_source": source,
            "identity_history": json.dumps(history) if history else None,
        })
        _strip_legacy_plaintext(record)
        try:
            _store_record(customers, customer_id, record, mirrors)
            _verify_durable(customer_id, code, new_hash, _ENCRYPTED.get(customer_id))
        except Exception:
            # Roll back so hash and blob never disagree.
            record.update(previous_fields)
            if previous_blob is None:
                _ENCRYPTED.pop(customer_id, None)
            else:
                _ENCRYPTED[customer_id] = previous_blob
            if _db_enabled():
                try:
                    _store_encrypted(customer_id, previous_blob)
                except Exception as exc:
                    logger.error("identity blob rollback failed for %s: %s", customer_id, exc)
            raise

    event = "identity_corrected" if current_hash else "identity_set"
    details = {"nationality": code, "national_id_hash": new_hash, "source": source,
               "corrections": len(history)}
    if audit is not None:
        try:
            audit.log(actor, event, "customer", customer_id, details)
        except Exception as exc:
            logger.warning("identity audit log failed for %s: %s", customer_id, exc)
    if ledger is not None:
        try:
            ledger.append_event(
                event_type=f"customer.{event}",
                entity_type="customer",
                entity_id=customer_id,
                customer_id=customer_id,
                actor=actor,
                payload={**details, "previous_national_id_hash": current_hash,
                         "reason": (reason or "").strip() or None},
                entry_id=f"CID-{customer_id}-{new_hash[:16]}",
            )
        except Exception as exc:
            logger.warning("identity ledger anchor failed for %s: %s", customer_id, exc)

    status = identity_status(record)
    status["changed"] = True
    return status


def reconcile_pipeline_identity(customers: Dict[str, Any], customer_id: str, national_id: Any,
                                nationality: Any, *, source: str, actor: str,
                                mirrors: Iterable[Dict[str, Any]] = (), audit: Any = None,
                                ledger: Any = None) -> Dict[str, Any]:
    """Apply an application/claim payload's identity fields to the customer.

    Outcomes (``result["outcome"]``):
      ``consistent``  recorded identity present; payload agrees or omits the ID
      ``mismatch``    recorded identity present but the payload's ID differs —
                      the customer record is left untouched and the caller must
                      flag its pipeline record for review
      ``captured``    no identity yet; the payload supplied a valid one, now set
      ``missing``     no identity yet and the payload has none (or an invalid one
                      — see ``error``); under ``strict_mode`` the caller rejects
    ``reference`` is the PII-free pointer to stamp on the pipeline record.
    """
    record = customers.get(customer_id) if hasattr(customers, "get") else None
    supplied = str(national_id or "").strip()
    if is_complete(record):
        if supplied:
            same = matches(record, supplied, nationality)
            if not same:
                return {"outcome": "mismatch", "reference": identity_reference(record),
                        "error": "national_id in the request does not match the customer's recorded identity"}
        return {"outcome": "consistent", "reference": identity_reference(record)}
    if not supplied:
        return {"outcome": "missing", "reference": None, "error": "national_id and nationality are required"}
    try:
        set_identity(customers, customer_id, supplied, nationality, source=source, actor=actor,
                     mirrors=mirrors, audit=audit, ledger=ledger)
    except IdentityError as exc:
        return {"outcome": "missing", "reference": None, "error": str(exc), "code": exc.code}
    record = customers.get(customer_id)
    return {"outcome": "captured", "reference": identity_reference(record)}


def resolve_lookup_id(customers: Dict[str, Any], customer_id: str, supplied_id: Any, *,
                      source: str, actor: str, nationality: str = "IL",
                      mirrors: Iterable[Dict[str, Any]] = (), audit: Any = None,
                      ledger: Any = None) -> Tuple[str, Optional[Tuple[int, Dict[str, Any]]]]:
    """Decide which personal ID a regulated external lookup (Mislaka pension
    clearing house, national registries) may use for ``customer_id``.

    * recorded identity + no ID supplied -> the recorded number, decrypted
      server-side, so nobody re-types (or mistypes) it;
    * recorded identity + a different ID -> (409 ``identity_mismatch``); the
      supplied value is compared under the *recorded* nationality, so a
      customer whose master is not ``nationality`` may still supply it;
    * no recorded identity + a valid ID -> captured once through
      ``set_identity`` (409 ``identity_in_use`` if another customer owns it);
    * unknown customer -> the supplied value untouched.
    Returns ``(id_to_use, error_response_or_None)``; the caller must never put
    ``id_to_use`` in an HTTP response.
    """
    supplied = str(supplied_id or "").strip()
    record = customers.get(customer_id) if (customer_id and hasattr(customers, "get")) else None
    if not isinstance(record, dict):
        return supplied, None
    if is_complete(record):
        if not supplied:
            return reveal_national_id(customer_id) or "", None
        if matches(record, supplied) is False:
            return supplied, (409, {
                "error": "id_number does not match the identity recorded for this customer",
                "code": "identity_mismatch",
            })
        return supplied, None
    if supplied:
        result = reconcile_pipeline_identity(
            customers, customer_id, supplied, nationality, source=source, actor=actor,
            mirrors=mirrors, audit=audit, ledger=ledger)
        if result.get("outcome") == "missing" and result.get("code") == "identity_in_use":
            return supplied, (409, {"error": result.get("error"), "code": "identity_in_use"})
    return supplied, None


def completion_report(customers: Dict[str, Any]) -> Dict[str, Any]:
    """Rollout monitoring for existing customers: how many still owe the prompt."""
    total = complete = 0
    by_nationality: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    try:
        items = list(customers.values())
    except Exception:
        items = []
    for rec in items:
        if not isinstance(rec, dict):
            continue
        total += 1
        if is_complete(rec):
            complete += 1
            by_nationality[str(rec.get("nationality"))] = by_nationality.get(str(rec.get("nationality")), 0) + 1
            src = str(rec.get("identity_source") or "unknown")
            by_source[src] = by_source.get(src, 0) + 1
    return {"customers": total, "complete": complete, "pending": total - complete,
            "completion_pct": round(100.0 * complete / total, 1) if total else 0.0,
            "by_nationality": by_nationality, "by_source": by_source,
            "strict_mode": strict_mode()}
