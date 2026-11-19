"""Health-wallet withdrawal: chat intake, hold, sealed document, retention window.

A customer asks to move money from the health wallet to a bank account. The
request is a Phin chat that starts from the customer record already on file
and collects the amount, the bank account, an identity document, a portrait
cut from that document, a bank document, and a drawn signature.

Filing does three things, in this order, and undoes the first if a later one
fails:

1. The amount leaves the wallet balance into a hold (``withdrawal_hold``).
2. The signature is anchored through the legal-document signer
   (``LGL-WDR-<id>``), over the SHA-256 of the sealed request.
3. The wallet NFT is minted (``wallet_withdrawal_request``) carrying that
   same SHA-256, so the document is part of the wallet's NFT ledger.

The hold stays for a retention window. During it customer relations may
contact the customer and place one offer at a time. Only the customer can
reverse: by cancelling, or by accepting an offer. Staff never return or move
the money on the customer's behalf, except to decline the request (the hold
goes back to the same wallet) or to release the payout once the window has
ended.

Not stored here: the national ID number (only the customer master's
reference: nationality, hash, last four) and the full bank account number
outside the vault.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

STEPS: Tuple[str, ...] = (
    "details", "amount", "reason", "bank", "id_document", "photo",
    "bank_document", "signature", "review",
)
STEP_NAMES: Dict[str, str] = {
    "details": "my details", "amount": "the amount", "reason": "the reason", "bank": "the bank account",
    "id_document": "my identity document", "photo": "my photo", "bank_document": "my bank document",
    "signature": "my signature",
}
OPEN_STATUSES = frozenset({"draft", "held"})
CLOSED_STATUSES = frozenset({"discarded", "reversed", "declined", "paid_out"})
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
DOCUMENT_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"})
MIN_AMOUNT = 1.0
DEFAULT_RETENTION_DAYS = 3
MAX_RETENTION_DAYS = 14
MAX_EXTENSION_DAYS = 4
DOC_TYPE = "wallet_withdrawal"

REASONS: Dict[str, str] = {
    "medical_expense": "A medical expense outside the marketplace",
    "need_cash": "I need the cash for something else",
    "moving_provider": "I am moving to another provider",
    "not_using": "I am not using the health wallet",
    "other": "Another reason",
}

# What customer relations can do during the window. ``offer`` methods place
# one open offer the customer may accept; nothing moves until they do.
RETENTION_METHODS: Dict[str, Dict[str, Any]] = {
    "outreach_call": {
        "label": "Call the customer", "kind": "contact",
        "hint": "Record the call and what was said.",
    },
    "outreach_message": {
        "label": "Send a message", "kind": "contact",
        "hint": "Email and WhatsApp on file, under the consent and daily-cap rules.",
    },
    "offer_keep_in_wallet": {
        "label": "Offer: keep it in the health wallet", "kind": "offer",
        "hint": "The whole hold returns to the wallet when the customer accepts.",
    },
    "offer_partial": {
        "label": "Offer: withdraw less", "kind": "offer", "needs": "keep_amount",
        "hint": "The kept part returns to the wallet. The rest is still paid out.",
    },
    "offer_move_to_savings": {
        "label": "Offer: move it to savings", "kind": "offer", "next": "/savings-portfolio.html",
        "hint": "The hold returns to the wallet and the customer moves it to savings themselves.",
    },
    "offer_premium_credit": {
        "label": "Offer: use it for premiums", "kind": "offer", "next": "/billing.html",
        "hint": "The hold returns to the wallet and the customer pays premiums from it.",
    },
    "extend_hold": {
        "label": "Extend the window", "kind": "hold", "needs": "days",
        "hint": "Once per request, up to four days, with a reason.",
    },
    "escalate": {
        "label": "Escalate to a manager", "kind": "escalation",
        "hint": "Opens an escalation on the customer's timeline.",
    },
    "note": {
        "label": "Add a note", "kind": "note",
        "hint": "A desk note. The customer does not see it.",
    },
}

# The first step the bar proposes for each stated reason. Staff choose freely.
SUGGESTED_METHOD: Dict[str, str] = {
    "medical_expense": "outreach_call",
    "need_cash": "offer_partial",
    "moving_provider": "escalate",
    "not_using": "offer_move_to_savings",
    "other": "outreach_call",
}

RETENTION_ROLES = frozenset({
    "admin", "accountant", "claims", "claims_adjuster", "adjuster", "underwriter", "compliance",
})
PAYOUT_ROLES = frozenset({"admin", "accountant"})

_LOCK = threading.RLock()
_FALLBACK_STORE: Dict[str, Dict[str, Any]] = {}


class WithdrawalError(Exception):
    """A request that cannot proceed. ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


# ---------------------------------------------------------------------------
# Portal access
# ---------------------------------------------------------------------------
def _portal():
    return sys.modules.get("web_portal.server") or sys.modules.get("server")


def _store() -> Dict[str, Dict[str, Any]]:
    portal = _portal()
    store = getattr(portal, "WALLET_WITHDRAWALS", None) if portal else None
    return store if isinstance(store, dict) else _FALLBACK_STORE


def _wallets() -> Dict[str, Dict[str, Any]]:
    portal = _portal()
    store = getattr(portal, "HEALTH_WALLETS", None) if portal else None
    if not isinstance(store, dict):
        raise WithdrawalError("The health wallet is not available", 503, "wallet_unavailable")
    return store


def _persist() -> None:
    portal = _portal()
    save = getattr(portal, "save_ledger_data", None) if portal else None
    if callable(save):
        threading.Thread(target=save, daemon=True).start()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _money(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return round(number, 2)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def retention_days() -> int:
    try:
        days = int(str(os.environ.get("PHINS_WITHDRAWAL_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)).strip())
    except ValueError:
        days = DEFAULT_RETENTION_DAYS
    return max(0, min(MAX_RETENTION_DAYS, days))


def _lock_for(customer_id: str):
    from services.savings_pipeline_service import named_row_lock

    return named_row_lock(f"wallet-withdrawal:{customer_id}")


# ---------------------------------------------------------------------------
# Customer record
# ---------------------------------------------------------------------------
def _customer_record(customer_id: str) -> Dict[str, Any]:
    portal = _portal()
    lookup = getattr(portal, "get_customer_with_fallback", None) if portal else None
    record = lookup(customer_id) if callable(lookup) else None
    if not isinstance(record, dict):
        store = getattr(portal, "CUSTOMERS", None) if portal else None
        record = store.get(customer_id) if hasattr(store, "get") else None
    if not isinstance(record, dict):
        raise WithdrawalError("Customer record not found", 404, "customer_not_found")
    return record


def _holder_details(customer_id: str, login: str = "") -> Dict[str, Any]:
    """Personal details as the customer master holds them. Nothing is written."""
    record = _customer_record(customer_id)
    name = str(record.get("name") or record.get("full_name") or "").strip()
    if not name:
        name = " ".join(
            part for part in (str(record.get("first_name") or "").strip(), str(record.get("last_name") or "").strip())
            if part
        )
    email = str(record.get("email") or "").strip()
    if not email and "@" in str(login or ""):
        email = str(login).strip()
    address = record.get("address")
    if isinstance(address, dict):
        address = ", ".join(str(part) for part in address.values() if part)
    details: Dict[str, Any] = {
        "name": name,
        "email": email,
        "phone": str(record.get("phone") or record.get("mobile") or "").strip(),
        "address": str(address or "").strip(),
        "date_of_birth": str(record.get("dob") or record.get("date_of_birth") or "").strip(),
    }
    try:
        from services.customer_identity_service import identity_reference

        reference = identity_reference(record)
    except Exception:
        reference = None
    if reference:
        details["identity"] = {
            "nationality": reference.get("nationality"),
            "national_id_hash": reference.get("national_id_hash"),
            "national_id_last4": reference.get("national_id_last4"),
            "national_id_masked": reference.get("national_id_masked"),
        }
    else:
        details["identity"] = None
    return details


def _fold_name(value: Any) -> str:
    return " ".join(str(value or "").lower().replace(",", " ").split())


# ---------------------------------------------------------------------------
# Bank account
# ---------------------------------------------------------------------------
def _valid_iban(value: str) -> bool:
    if not (15 <= len(value) <= 34) or not value.isalnum() or not value[:2].isalpha() or not value[2:4].isdigit():
        return False
    rearranged = value[4:] + value[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _clean_bank(value: Any, holder_name: str) -> Tuple[Dict[str, Any], str, List[str]]:
    """Validate the bank answer. Returns (public part, full account, flags)."""
    if not isinstance(value, dict):
        raise WithdrawalError("Bank details must be filled in", 400, "bank_invalid")
    holder = " ".join(str(value.get("holder") or "").split())[:120]
    bank_name = " ".join(str(value.get("bank_name") or "").split())[:120]
    branch = " ".join(str(value.get("branch") or "").split())[:60]
    swift = "".join(str(value.get("swift") or "").split()).upper()
    account_raw = "".join(ch for ch in str(value.get("account") or value.get("iban") or "") if ch not in " -.").upper()
    if len(holder) < 2:
        raise WithdrawalError("Enter the account holder's name", 400, "bank_holder_required")
    if len(bank_name) < 2:
        raise WithdrawalError("Enter the bank's name", 400, "bank_name_required")
    try:
        from services.countries import resolve_country

        country = resolve_country(value.get("country"))
    except Exception:
        country = None
    if not country:
        raise WithdrawalError("Choose the country of the bank account", 400, "bank_country_required")
    if account_raw[:2].isalpha():
        if not _valid_iban(account_raw):
            raise WithdrawalError("That IBAN does not pass its check digits", 400, "bank_account_invalid")
        kind = "iban"
    else:
        if not account_raw.isdigit() or not (4 <= len(account_raw) <= 20):
            raise WithdrawalError("Enter an IBAN, or an account number of 4 to 20 digits", 400, "bank_account_invalid")
        kind = "account_number"
        if not branch:
            raise WithdrawalError("Enter the branch for this account number", 400, "bank_branch_required")
    if swift and not (len(swift) in (8, 11) and swift.isalnum()):
        raise WithdrawalError("A SWIFT code has 8 or 11 characters", 400, "bank_swift_invalid")
    flags: List[str] = []
    if _fold_name(holder) != _fold_name(holder_name):
        flags.append("third_party_account")
    public = {
        "holder": holder,
        "bank_name": bank_name,
        "branch": branch,
        "country": country,
        "swift": swift,
        "account_kind": kind,
        "account_last4": account_raw[-4:],
        "account_sha256": hashlib.sha256(account_raw.encode("utf-8")).hexdigest(),
    }
    return public, account_raw, flags


def _vault_account(account: str) -> str:
    from security.vault import encrypt_json

    blob = encrypt_json({"account": account})
    if blob.scheme != "fernet":
        raise WithdrawalError(
            "The bank account cannot be stored securely right now", 503, "bank_vault_unavailable",
        )
    return blob.to_json()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _decode_upload(data_b64: Any) -> bytes:
    raw = str(data_b64 or "")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        raise WithdrawalError("The file could not be read", 400, "file_unreadable")
    if not blob:
        raise WithdrawalError("The file is empty", 400, "file_empty")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise WithdrawalError("The file is larger than 6 MB", 413, "file_too_large")
    return blob


def _sniff_mime(blob: bytes) -> str:
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob[:5] == b"%PDF-":
        return "application/pdf"
    return ""


_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}


def _seal_file(record: Dict[str, Any], blob: bytes, mime: str, *, label: str, category: str,
               description: str) -> Dict[str, Any]:
    """File the bytes in the document archive and return their reference."""
    file_name = f"{record['id']}-{label}{_EXTENSIONS.get(mime, '.bin')}"
    try:
        from services.document_processing_service import get_document_service

        stored = get_document_service().upload_document(
            file_name=file_name,
            file_data_b64=base64.b64encode(blob).decode("ascii"),
            mime_type=mime,
            category=category,
            description=description,
            entity_type="wallet_withdrawal",
            entity_id=record["id"],
            customer_id=record["customer_id"],
            uploaded_by=record["customer_id"],
            uploaded_by_role="customer",
            skip_processing=True,
        )
    except ValueError as exc:
        raise WithdrawalError(str(exc), 400, "file_refused")
    except Exception:
        raise WithdrawalError("The file could not be sealed", 503, "file_not_stored")
    digest = hashlib.sha256(blob).hexdigest()
    stored_sha = str(getattr(stored, "sha256", "") or "")
    if stored_sha and stored_sha != digest:
        raise WithdrawalError("The stored file does not match the upload", 503, "file_not_stored")
    return {
        "document_id": str(getattr(stored, "document_id", "") or ""),
        "sha256": digest,
        "mime_type": mime,
        "size": len(blob),
        "file_name": file_name,
        "sealed_at": _iso(),
    }


def _read_file(reference: Optional[Dict[str, Any]]) -> Optional[bytes]:
    """Stored bytes, only when they still match the SHA-256 on the request."""
    if not isinstance(reference, dict) or not reference.get("document_id"):
        return None
    try:
        from services.document_processing_service import get_document_service

        found = get_document_service().get_document(reference["document_id"], include_data=True)
    except Exception:
        return None
    if not isinstance(found, dict) or not found.get("data"):
        return None
    try:
        blob = base64.b64decode(found["data"])
    except Exception:
        return None
    if hashlib.sha256(blob).hexdigest() != reference.get("sha256"):
        return None
    return blob


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
def _get(withdrawal_id: str) -> Dict[str, Any]:
    record = _store().get(str(withdrawal_id or ""))
    if not isinstance(record, dict):
        raise WithdrawalError("Withdrawal request not found", 404, "not_found")
    return record


def _own(customer_id: str, withdrawal_id: str) -> Dict[str, Any]:
    record = _get(withdrawal_id)
    if str(record.get("customer_id") or "") != str(customer_id or ""):
        # The same answer as an unknown id: another customer's request is not confirmed.
        raise WithdrawalError("Withdrawal request not found", 404, "not_found")
    return record


def _open_for(customer_id: str) -> Optional[Dict[str, Any]]:
    for record in _store().values():
        if (isinstance(record, dict) and record.get("customer_id") == customer_id
                and record.get("status") in OPEN_STATUSES):
            return record
    return None


def _wallet_balance(customer_id: str) -> float:
    wallet = _wallets().get(customer_id)
    return _money(wallet.get("balance")) if isinstance(wallet, dict) else 0.0


def _say(record: Dict[str, Any], who: str, text: str) -> None:
    record.setdefault("messages", []).append({"from": who, "text": str(text)[:600], "at": _iso()})
    if len(record["messages"]) > 120:
        del record["messages"][:-120]


def _touch(record: Dict[str, Any]) -> None:
    record["updated_at"] = _iso()


def _next_step(record: Dict[str, Any]) -> str:
    done = record.get("answers") or {}
    for step in STEPS:
        if step == "review":
            return "review"
        if not done.get(step):
            return step
    return "review"


def _invalidate_from(record: Dict[str, Any], step: str) -> None:
    """A changed answer clears what was attested on top of it."""
    answers = record.setdefault("answers", {})
    if step != "signature" and answers.get("signature"):
        answers.pop("signature", None)
        record.pop("signature", None)
    if step == "id_document":
        answers.pop("photo", None)
        (record.get("documents") or {}).pop("portrait", None)
        (record.get("documents") or {}).pop("photo_source", None)


def _prompt(record: Dict[str, Any], step: str) -> Dict[str, Any]:
    """The bot's question for a step, with what the page needs to ask it."""
    balance = _wallet_balance(record["customer_id"])
    details = record.get("details") or {}
    first = (details.get("name") or "").split(" ")[0] or "there"
    if step == "details":
        return {
            "id": step,
            "prompt": f"Hi {first}. I will use the details we already hold for you. Are these still right?",
            "input": {"type": "confirm_details", "details": _public_details(details)},
        }
    if step == "amount":
        return {
            "id": step,
            "prompt": f"Your health wallet holds ${balance:,.2f}. How much would you like to withdraw?",
            "input": {"type": "amount", "min": MIN_AMOUNT, "max": balance, "currency": "USD"},
        }
    if step == "reason":
        return {
            "id": step,
            "prompt": "What is the withdrawal for? This helps us see whether there is a better option for you.",
            "input": {"type": "choice", "options": [{"value": key, "label": label} for key, label in REASONS.items()],
                      "note": True},
        }
    if step == "bank":
        return {
            "id": step,
            "prompt": "Which bank account should receive the money? The account number is stored encrypted and shown as its last four digits.",
            "input": {"type": "bank", "holder": details.get("name") or ""},
        }
    if step == "id_document":
        return {
            "id": step,
            "prompt": "Please upload a picture of your identity document (ID card, passport, or driving licence). A clear photo works best.",
            "input": {"type": "upload", "kind": "id_document", "accept": "image/jpeg,image/png,image/webp,application/pdf"},
        }
    if step == "photo":
        source = _photo_source_reference(record)
        if source is None:
            return {
                "id": step,
                "prompt": "I could not cut a photo from that file. Please upload a picture of any document that shows your face.",
                "input": {"type": "upload", "kind": "photo_source", "accept": "image/jpeg,image/png,image/webp"},
            }
        return {
            "id": step,
            "prompt": "I marked your photo on the document. Move or resize the frame if it is off, then confirm.",
            "input": {"type": "photo_crop"},
        }
    if step == "bank_document":
        return {
            "id": step,
            "prompt": "Please upload a bank document that shows this account in your name (a statement header, a void cheque, or an account confirmation).",
            "input": {"type": "upload", "kind": "bank_document", "accept": "image/jpeg,image/png,image/webp,application/pdf"},
        }
    if step == "signature":
        return {
            "id": step,
            "prompt": "Last step: type your full legal name and draw your signature to authorise the withdrawal.",
            "input": {"type": "signature", "signer_name": details.get("name") or ""},
        }
    days = retention_days()
    return {
        "id": "review",
        "prompt": (
            "Everything is here. When you file, the amount leaves your wallet balance and is held"
            + (f" for {days} day{'s' if days != 1 else ''} before the bank transfer." if days else " until the bank transfer is released.")
            + " You can cancel during that time and the money returns to your wallet."
        ),
        "input": {"type": "review", "portrait": portrait_data_url(record)},
    }


def _public_details(details: Dict[str, Any]) -> Dict[str, Any]:
    identity = details.get("identity") or {}
    return {
        "name": details.get("name") or "",
        "email": details.get("email") or "",
        "phone": details.get("phone") or "",
        "address": details.get("address") or "",
        "nationality": identity.get("nationality") or "",
        "national_id_masked": identity.get("national_id_masked") or "",
        "identity_on_file": bool(identity),
    }


def _public_document(reference: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(reference, dict):
        return None
    return {key: reference.get(key) for key in ("document_id", "sha256", "mime_type", "size", "file_name", "sealed_at",
                                                 "box", "method", "source")
            if reference.get(key) is not None}


def _window(record: Dict[str, Any]) -> Dict[str, Any]:
    retention = record.get("retention") or {}
    release_after = _parse(retention.get("release_after"))
    remaining = None
    if release_after is not None:
        remaining = max(0, int((release_after - _now()).total_seconds()))
    return {
        "window_days": retention.get("window_days"),
        "release_after": retention.get("release_after"),
        "seconds_left": remaining,
        "window_ended": remaining == 0,
        "extended": bool(retention.get("extended")),
    }


def _public_offer(offer: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(offer, dict):
        return None
    method = RETENTION_METHODS.get(str(offer.get("method") or ""), {})
    return {
        "offer_id": offer.get("offer_id"),
        "method": offer.get("method"),
        "label": method.get("label", ""),
        "message": offer.get("message") or "",
        "keep_amount": offer.get("keep_amount"),
        "made_at": offer.get("made_at"),
        "status": offer.get("status"),
        "next": method.get("next"),
    }


def _summary(record: Dict[str, Any]) -> Dict[str, Any]:
    seal = record.get("seal") or {}
    return {
        "id": record.get("id"),
        "customer_id": record.get("customer_id"),
        "status": record.get("status"),
        "amount": _money(record.get("amount")),
        "requested_amount": _money(record.get("requested_amount")),
        "currency": record.get("currency") or "USD",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "filed_at": seal.get("filed_at"),
        "nft_token_id": seal.get("nft_token_id"),
        "record_sha256": seal.get("record_sha256"),
        "bank": {key: (record.get("bank") or {}).get(key)
                 for key in ("holder", "bank_name", "branch", "country", "swift", "account_kind", "account_last4")},
        "reason": record.get("reason"),
        "flags": list(record.get("flags") or []),
        "closed": record.get("closed"),
        "window": _window(record) if record.get("status") == "held" else None,
    }


def customer_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """What the owning customer sees. Desk notes and the vault are left out."""
    view = _summary(record)
    retention = record.get("retention") or {}
    offer = retention.get("offer")
    view.update({
        "details": _public_details(record.get("details") or {}),
        "documents": {key: _public_document(value) for key, value in (record.get("documents") or {}).items()},
        "signature": ({"signer_name": (record.get("signature") or {}).get("signer_name"),
                       "sha256": (record.get("signature") or {}).get("sha256"),
                       "signed_at": (record.get("signature") or {}).get("signed_at")}
                      if record.get("signature") else None),
        "answers": {step: bool((record.get("answers") or {}).get(step)) for step in STEPS[:-1]},
        "steps": list(STEPS),
        "wallet_balance": _wallet_balance(record["customer_id"]),
        "offer": _public_offer(offer) if isinstance(offer, dict) and offer.get("status") == "open" else None,
        "amendments": [
            {key: item.get(key) for key in ("at", "kind", "from_amount", "to_amount", "returned")}
            for item in record.get("amendments") or []
        ],
        "messages": list(record.get("messages") or []),
        "can_edit": record.get("status") == "draft",
        "can_cancel": record.get("status") in ("draft", "held"),
    })
    if record.get("status") == "draft":
        view["step"] = _prompt(record, _next_step(record))
    return view


def staff_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """The desk's view: the customer view plus the retention trail. No vault."""
    view = customer_view(record)
    view.pop("messages", None)
    retention = record.get("retention") or {}
    view["retention"] = {
        "flag": bool(retention.get("flag")),
        "attempts": list(retention.get("attempts") or []),
        "offer": _public_offer(retention.get("offer")),
        "trail_intact": _attempts_intact(record),
    }
    view["seal_intact"] = seal_intact(record) if record.get("seal") else None
    view["suggested_method"] = SUGGESTED_METHOD.get(str((record.get("reason") or {}).get("code") or ""), "outreach_call")
    return view


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
def open_request(customer_id: str, login: str = "") -> Dict[str, Any]:
    """Start a withdrawal, or return the one already open for this customer."""
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        raise WithdrawalError("Customer required", 403, "forbidden")
    with _LOCK:
        existing = _open_for(customer_id)
        if existing is not None:
            return customer_view(existing)
        details = _holder_details(customer_id, login)
        if _wallet_balance(customer_id) < MIN_AMOUNT:
            raise WithdrawalError("Your health wallet has no balance to withdraw", 409, "wallet_empty")
        stamp = _now()
        withdrawal_id = f"WDR-{stamp.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
        flags = [] if details.get("identity") else ["identity_not_on_file"]
        record: Dict[str, Any] = {
            "id": withdrawal_id,
            "customer_id": customer_id,
            "status": "draft",
            "source": "health_wallet",
            "currency": "USD",
            "amount": 0.0,
            "requested_amount": 0.0,
            "details": details,
            "answers": {},
            "documents": {},
            "flags": flags,
            "messages": [],
            "created_at": _iso(stamp),
            "updated_at": _iso(stamp),
        }
        _store()[withdrawal_id] = record
        _say(record, "bot", _prompt(record, "details")["prompt"])
        _persist()
        return customer_view(record)


def get_request(customer_id: str, withdrawal_id: str) -> Dict[str, Any]:
    with _LOCK:
        return customer_view(_own(customer_id, withdrawal_id))


def list_requests(customer_id: str) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [
            _summary(record) for record in _store().values()
            if isinstance(record, dict) and record.get("customer_id") == customer_id
            and record.get("status") != "discarded"
        ]
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows


def _draft(customer_id: str, withdrawal_id: str) -> Dict[str, Any]:
    record = _own(customer_id, withdrawal_id)
    if record.get("status") != "draft":
        raise WithdrawalError("This request is already filed and can no longer be edited", 409, "already_filed")
    return record


def _advance(record: Dict[str, Any], step: str, echo: str) -> Dict[str, Any]:
    answers = record.setdefault("answers", {})
    changed = bool(answers.get(step))
    answers[step] = True
    upcoming = _prompt(record, _next_step(record))["prompt"]
    if changed:
        # An edit is said as an edit, so the thread does not read as if the
        # customer answered the same question twice.
        _say(record, "user", f"Changed {STEP_NAMES.get(step, step)}: {echo}")
        _say(record, "bot", "Updated. " + upcoming)
    else:
        _say(record, "user", echo)
        _say(record, "bot", upcoming)
    _touch(record)
    _persist()
    return customer_view(record)


def answer(customer_id: str, withdrawal_id: str, step: str, value: Any) -> Dict[str, Any]:
    """Record one typed answer (details, amount, reason, bank)."""
    step = str(step or "").strip()
    with _LOCK:
        record = _draft(customer_id, withdrawal_id)
        answers = record.setdefault("answers", {})
        if step not in ("details", "amount", "reason", "bank"):
            raise WithdrawalError("That step is not answered here", 400, "step_invalid")
        position = STEPS.index(step)
        if any(not answers.get(earlier) for earlier in STEPS[:position]):
            raise WithdrawalError("An earlier answer is still missing", 409, "step_out_of_order")
        if step == "details":
            confirmed = value is True or (isinstance(value, dict) and value.get("confirm") is True) or value == "confirm"
            if not confirmed:
                raise WithdrawalError(
                    "Please confirm your details, or update them in your profile first", 400, "details_not_confirmed",
                )
            # Read again so the request carries the record as it is now.
            record["details"] = _holder_details(customer_id, (record.get("details") or {}).get("email") or "")
            _invalidate_from(record, step)
            return _advance(record, step, "Yes, these are right.")
        if step == "amount":
            amount = _money(value.get("amount") if isinstance(value, dict) else value)
            balance = _wallet_balance(customer_id)
            if amount < MIN_AMOUNT:
                raise WithdrawalError(f"The smallest withdrawal is ${MIN_AMOUNT:,.2f}", 400, "amount_invalid")
            if amount > balance + 1e-9:
                raise WithdrawalError(
                    f"Your health wallet holds ${balance:,.2f}. Choose an amount up to that.", 400, "amount_exceeds_balance",
                )
            record["amount"] = amount
            record["requested_amount"] = amount
            _invalidate_from(record, step)
            return _advance(record, step, f"${amount:,.2f}")
        if step == "reason":
            code = str((value.get("code") if isinstance(value, dict) else value) or "").strip()
            if code not in REASONS:
                raise WithdrawalError("Choose one of the reasons", 400, "reason_invalid")
            note = " ".join(str((value.get("note") if isinstance(value, dict) else "") or "").split())[:300]
            record["reason"] = {"code": code, "label": REASONS[code], "note": note}
            _invalidate_from(record, step)
            return _advance(record, step, REASONS[code] + (f" · {note}" if note else ""))
        public, account, flags = _clean_bank(value, (record.get("details") or {}).get("name") or "")
        record["bank_vault"] = _vault_account(account)
        record["bank"] = public
        kept = [flag for flag in record.get("flags") or [] if flag != "third_party_account"]
        record["flags"] = kept + flags
        _invalidate_from(record, step)
        label = "IBAN" if public["account_kind"] == "iban" else "account"
        return _advance(
            record, step,
            f"{public['holder']} · {public['bank_name']} · {label} ending {public['account_last4']}",
        )


def _photo_source_reference(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The file the portrait is cut from: another upload first, else the ID."""
    documents = record.get("documents") or {}
    other = documents.get("photo_source")
    if isinstance(other, dict):
        return other
    identity = documents.get("id_document")
    if isinstance(identity, dict) and identity.get("portrait_ready"):
        return identity
    return None


def attach_document(customer_id: str, withdrawal_id: str, kind: str, mime_type: str, data_b64: Any) -> Dict[str, Any]:
    """Seal an uploaded identity document, bank document, or photo source."""
    kind = str(kind or "").strip()
    if kind not in ("id_document", "bank_document", "photo_source"):
        raise WithdrawalError("Unknown upload", 400, "upload_kind_invalid")
    blob = _decode_upload(data_b64)
    mime = _sniff_mime(blob)
    if mime not in DOCUMENT_MIME_TYPES:
        raise WithdrawalError("Upload a JPEG, PNG, WebP, or PDF file", 400, "file_type_refused")
    if kind == "photo_source" and mime == "application/pdf":
        raise WithdrawalError("Upload a picture for the photo, not a PDF", 400, "file_type_refused")
    portrait_ready = False
    if kind in ("id_document", "photo_source"):
        from services import id_photo_crop

        try:
            id_photo_crop.load_image(blob, mime)
            portrait_ready = True
        except id_photo_crop.PhotoCropError as exc:
            if kind == "photo_source" or exc.code not in ("photo_source_not_image",):
                raise WithdrawalError(str(exc), 400, exc.code)
    with _LOCK:
        record = _draft(customer_id, withdrawal_id)
        answers = record.setdefault("answers", {})
        step = "photo" if kind == "photo_source" else kind
        position = STEPS.index(step)
        if any(not answers.get(earlier) for earlier in STEPS[:position]):
            raise WithdrawalError("An earlier answer is still missing", 409, "step_out_of_order")
        labels = {
            "id_document": ("id", "identity", "Identity document for a wallet withdrawal"),
            "bank_document": ("bank", "financial", "Bank account document for a wallet withdrawal"),
            "photo_source": ("photo-source", "identity", "Document image used for the withdrawal portrait"),
        }
        label, category, description = labels[kind]
        reference = _seal_file(record, blob, mime, label=label, category=category, description=description)
        if kind != "bank_document":
            reference["portrait_ready"] = portrait_ready
        record.setdefault("documents", {})[kind] = reference
        if kind == "photo_source":
            (record.get("documents") or {}).pop("portrait", None)
            answers.pop("photo", None)
            _invalidate_from(record, "photo")
            _say(record, "user", "Uploaded a picture for the photo.")
            _say(record, "bot", _prompt(record, "photo")["prompt"])
            _touch(record)
            _persist()
            return customer_view(record)
        _invalidate_from(record, kind)
        echo = "Uploaded my identity document." if kind == "id_document" else "Uploaded my bank document."
        return _advance(record, kind, echo)


def photo_source(customer_id: str, withdrawal_id: str) -> Dict[str, Any]:
    """Preview of the document and the proposed portrait box for the crop screen."""
    from services import id_photo_crop

    with _LOCK:
        record = _draft(customer_id, withdrawal_id)
        reference = _photo_source_reference(record)
        if reference is None:
            raise WithdrawalError("Upload a picture of a document that shows your face", 409, "photo_source_missing")
        reference = dict(reference)
    blob = _read_file(reference)
    if blob is None:
        raise WithdrawalError("The document could not be read back intact", 409, "document_checksum_mismatch")
    try:
        image = id_photo_crop.load_image(blob, reference.get("mime_type") or "")
        proposal = id_photo_crop.propose_portrait_box(image)
        preview = id_photo_crop.preview_jpeg(image)
    except id_photo_crop.PhotoCropError as exc:
        raise WithdrawalError(str(exc), 400, exc.code)
    return {
        "preview": "data:image/jpeg;base64," + base64.b64encode(preview).decode("ascii"),
        "box": proposal["box"],
        "method": proposal["method"],
        "aspect": id_photo_crop.PORTRAIT_ASPECT,
        "source_sha256": reference.get("sha256"),
    }


def confirm_photo(customer_id: str, withdrawal_id: str, box: Any) -> Dict[str, Any]:
    """Cut the portrait from the sealed document at the box the customer confirmed."""
    from services import id_photo_crop

    with _LOCK:
        record = _draft(customer_id, withdrawal_id)
        answers = record.setdefault("answers", {})
        if any(not answers.get(earlier) for earlier in STEPS[:STEPS.index("photo")]):
            raise WithdrawalError("An earlier answer is still missing", 409, "step_out_of_order")
        reference = _photo_source_reference(record)
        if reference is None:
            raise WithdrawalError("Upload a picture of a document that shows your face", 409, "photo_source_missing")
        blob = _read_file(reference)
        if blob is None:
            raise WithdrawalError("The document could not be read back intact", 409, "document_checksum_mismatch")
        try:
            image = id_photo_crop.load_image(blob, reference.get("mime_type") or "")
            proposal = id_photo_crop.propose_portrait_box(image)
            chosen = proposal["box"] if box in (None, "", "proposal") else box
            jpeg, used = id_photo_crop.crop_portrait(image, chosen)
        except id_photo_crop.PhotoCropError as exc:
            raise WithdrawalError(str(exc), 400, exc.code)
        portrait = _seal_file(
            record, jpeg, "image/jpeg", label="portrait", category="identity",
            description="Portrait cut from the customer's document for a wallet withdrawal",
        )
        portrait["box"] = used
        portrait["method"] = proposal["method"] if used == proposal["box"] else "customer_box"
        portrait["source"] = {
            "document_id": reference.get("document_id"),
            "sha256": reference.get("sha256"),
            "kind": "photo_source" if (record.get("documents") or {}).get("photo_source") is reference else "id_document",
        }
        record.setdefault("documents", {})["portrait"] = portrait
        _invalidate_from(record, "photo")
        return _advance(record, "photo", "That is my photo.")


def portrait_data_url(record: Dict[str, Any]) -> str:
    blob = _read_file((record.get("documents") or {}).get("portrait"))
    return "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii") if blob else ""


def sign(customer_id: str, withdrawal_id: str, signer_name: Any, image_data: Any) -> Dict[str, Any]:
    """Record the typed legal name and the drawn signature."""
    from services.chat_application_service import inspect_drawn_signature

    name = " ".join(str(signer_name or "").split())[:160]
    if len(name) < 2:
        raise WithdrawalError("Type your full legal name", 400, "signer_name_required")
    checked = inspect_drawn_signature(image_data)
    if not checked.get("ok") or not checked.get("present"):
        raise WithdrawalError(
            checked.get("error") or "Please draw your signature in the signature panel.", 400, "signature_invalid",
        )
    blob = base64.b64decode(checked["data_b64"])
    with _LOCK:
        record = _draft(customer_id, withdrawal_id)
        answers = record.setdefault("answers", {})
        if any(not answers.get(earlier) for earlier in STEPS[:STEPS.index("signature")]):
            raise WithdrawalError("An earlier answer is still missing", 409, "step_out_of_order")
        reference = _seal_file(
            record, blob, "image/png", label="signature", category="legal",
            description="Drawn signature authorising a wallet withdrawal",
        )
        flags = [flag for flag in record.get("flags") or [] if flag != "signer_name_differs"]
        if _fold_name(name) != _fold_name((record.get("details") or {}).get("name")):
            flags.append("signer_name_differs")
        record["flags"] = flags
        record["signature"] = {
            "signer_name": name,
            "sha256": checked["sha256"],
            "document_id": reference["document_id"],
            "signed_at": _iso(),
            "method": "drawn_canvas",
        }
        return _advance(record, "signature", f"Signed as {name}.")


# ---------------------------------------------------------------------------
# Filing: hold, anchor, NFT
# ---------------------------------------------------------------------------
def _sealed_snapshot(record: Dict[str, Any], balance_before: float, balance_after: float,
                     filed_at: str, release_after: str, window_days: int) -> Dict[str, Any]:
    details = record.get("details") or {}
    identity = details.get("identity") or {}
    documents = record.get("documents") or {}

    def _doc(key: str) -> Dict[str, Any]:
        item = documents.get(key) or {}
        return {"document_id": item.get("document_id"), "sha256": item.get("sha256"), "mime_type": item.get("mime_type")}

    portrait = documents.get("portrait") or {}
    return {
        "withdrawal_id": record["id"],
        "customer_id": record["customer_id"],
        "source": "health_wallet",
        "currency": record.get("currency") or "USD",
        "amount": _money(record.get("amount")),
        "filed_at": filed_at,
        "holder": {
            "name": details.get("name") or "",
            "email": details.get("email") or "",
            "phone": details.get("phone") or "",
            "address": details.get("address") or "",
            "nationality": identity.get("nationality") or "",
            "national_id_hash": identity.get("national_id_hash") or "",
            "national_id_last4": identity.get("national_id_last4") or "",
        },
        "reason": dict(record.get("reason") or {}),
        "bank": dict(record.get("bank") or {}),
        "documents": {
            "id_document": _doc("id_document"),
            "bank_document": _doc("bank_document"),
            "portrait": {
                **_doc("portrait"),
                "box": portrait.get("box"),
                "method": portrait.get("method"),
                "source_sha256": (portrait.get("source") or {}).get("sha256"),
            },
        },
        "signature": {
            key: (record.get("signature") or {}).get(key)
            for key in ("signer_name", "sha256", "document_id", "signed_at", "method")
        },
        "wallet": {"balance_before": balance_before, "balance_after": balance_after},
        "flags": sorted(record.get("flags") or []),
        "retention_window_days": window_days,
        "release_after": release_after,
    }


def seal_intact(record: Dict[str, Any]) -> bool:
    seal = record.get("seal") or {}
    sealed = record.get("sealed")
    return bool(isinstance(sealed, dict) and seal.get("record_sha256") and _sha(sealed) == seal.get("record_sha256"))


def _wallet_row(wallet: Dict[str, Any], kind: str, amount: float, withdrawal_id: str, note: str = "") -> Dict[str, Any]:
    row = {
        "id": f"TXN-{_now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
        "type": kind,
        "amount": _money(amount),
        "withdrawal_id": withdrawal_id,
        "timestamp": datetime.now().isoformat(),
        "balance_after": _money(wallet.get("balance")),
    }
    if note:
        row["note"] = note
    wallet.setdefault("transactions", []).append(row)
    return row


def _return_to_wallet(record: Dict[str, Any], amount: float, note: str) -> Dict[str, Any]:
    """Put part or all of the hold back on the wallet it came from."""
    from services.savings_pipeline_service import credit_account_balance

    wallet = _wallets().get(record["customer_id"])
    if not isinstance(wallet, dict):
        raise WithdrawalError("The health wallet is not available", 503, "wallet_unavailable")
    if credit_account_balance(wallet, amount) is None:
        raise WithdrawalError("The hold could not be returned", 503, "wallet_unavailable")
    return _wallet_row(wallet, "withdrawal_reversal", amount, record["id"], note)


def _record_nft(record: Dict[str, Any], tx_type: str, amount: float, description: str,
                extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    portal = _portal()
    writer = getattr(portal, "record_transaction", None) if portal else None
    if not callable(writer):
        raise WithdrawalError("The ledger is not available", 503, "ledger_unavailable")
    metadata = {
        "withdrawal_id": record["id"],
        "record_sha256": (record.get("seal") or {}).get("record_sha256"),
        "document": f"/wallet-withdraw-chat.html?id={record['id']}",
        "source_system": "wallet_withdrawal",
    }
    if tx_type != "wallet_withdrawal_paid":
        # A hold and its return stay inside the customer's own money.
        metadata["cash_event"] = False
    metadata.update(extra or {})
    return writer(record["customer_id"], tx_type, _money(amount), description, metadata)


def file_request(customer_id: str, withdrawal_id: str, *, client_ip: str = "",
                 session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Hold the amount, anchor the signature, and mint the wallet NFT."""
    from services.savings_pipeline_service import credit_account_balance, debit_account_balance

    with _lock_for(customer_id), _LOCK:
        record = _draft(customer_id, withdrawal_id)
        answers = record.get("answers") or {}
        missing = [step for step in STEPS[:-1] if not answers.get(step)]
        if missing:
            raise WithdrawalError("The request is not complete yet", 409, "incomplete")
        for key in ("id_document", "bank_document", "portrait"):
            if _read_file((record.get("documents") or {}).get(key)) is None:
                raise WithdrawalError(
                    "A document on this request no longer matches its checksum", 409, "document_checksum_mismatch",
                )
        signature = record.get("signature") or {}
        signature_blob = _read_file({"document_id": signature.get("document_id"), "sha256": signature.get("sha256")})
        if signature_blob is None:
            raise WithdrawalError("The signature no longer matches its checksum", 409, "signature_checksum_mismatch")
        portal = _portal()
        signer = getattr(portal, "_legal_doc_sign", None) if portal else None
        if not callable(signer):
            raise WithdrawalError("The signature cannot be anchored right now", 503, "ledger_unavailable")
        wallet = _wallets().get(customer_id)
        amount = _money(record.get("amount"))
        balance_before = _money(wallet.get("balance")) if isinstance(wallet, dict) else 0.0
        if not isinstance(wallet, dict) or amount < MIN_AMOUNT:
            raise WithdrawalError("The health wallet cannot cover this withdrawal", 409, "amount_exceeds_balance")
        balance_after = debit_account_balance(wallet, amount)
        if balance_after is None:
            raise WithdrawalError(
                f"Your health wallet now holds ${balance_before:,.2f}. Change the amount and sign again.",
                409, "amount_exceeds_balance",
            )
        hold_row = _wallet_row(wallet, "withdrawal_hold", amount, record["id"])
        anchor_request: Optional[Dict[str, Any]] = None
        stamp = _now()
        window_days = retention_days()
        release_after = _iso(stamp + timedelta(days=window_days))
        sealed = _sealed_snapshot(record, balance_before, _money(balance_after), _iso(stamp), release_after, window_days)
        digest = _sha(sealed)
        instance = f"LGL-{record['id']}"
        try:
            request = {
                "docType": DOC_TYPE,
                "docInstanceId": instance,
                "role": "Account holder",
                "signerName": signature.get("signer_name"),
                "documentHash": digest,
                "signedAt": signature.get("signed_at"),
                "signerTitle": "Health wallet withdrawal",
                "context": "wallet_withdrawal",
                "signatureMethod": "drawn_canvas",
                "content": sealed,
            }
            status, anchored = signer(request, client_ip, session)
            if status == 200:
                anchor_request = request
            if status != 200:
                raise WithdrawalError(
                    str((anchored or {}).get("error") or "The signature could not be anchored"), 503, "anchor_failed",
                )
            record["sealed"] = sealed
            record["seal"] = {
                "record_sha256": digest,
                "filed_at": _iso(stamp),
                "legal_doc_instance": instance,
                "legal_entry_id": anchored.get("entry_id"),
                "legal_entry_hash": anchored.get("entry_hash"),
                "wallet_transaction_id": hold_row["id"],
            }
            ledger_tx = _record_nft(
                record, "wallet_withdrawal_request", amount,
                f"Health wallet withdrawal {record['id']} held for payout",
                {
                    "wallet_transaction_id": hold_row["id"],
                    "previous_balance": balance_before,
                    "new_balance": _money(balance_after),
                    "bank_account_last4": (record.get("bank") or {}).get("account_last4"),
                    "legal_doc_instance": instance,
                    "legal_entry_id": anchored.get("entry_id"),
                    "release_after": release_after,
                    "portrait_sha256": ((record.get("documents") or {}).get("portrait") or {}).get("sha256"),
                    "signature_sha256": signature.get("sha256"),
                },
            )
            if not ledger_tx.get("nft_token_id"):
                raise WithdrawalError("The wallet NFT could not be minted", 503, "nft_failed")
        except Exception as exc:
            # The hold comes back before anything else is said.
            credit_account_balance(wallet, amount)
            wallet["transactions"] = [row for row in wallet.get("transactions") or [] if row is not hold_row]
            if anchor_request is not None:
                # The anchor attests a hold that no longer exists, so it is voided.
                try:
                    signer({**anchor_request, "event": "void"}, client_ip,
                           session or {"username": "wallet_withdrawal", "role": "system"})
                except Exception:
                    record.setdefault("flags", []).append("anchor_void_pending")
            record.pop("sealed", None)
            record.pop("seal", None)
            _touch(record)
            _persist()
            if isinstance(exc, WithdrawalError):
                raise
            raise WithdrawalError("The withdrawal could not be filed. Nothing was held.", 503, "filing_failed")
        record["seal"]["nft_token_id"] = ledger_tx.get("nft_token_id")
        record["seal"]["ledger_tx_id"] = ledger_tx.get("id")
        hold_row["nft_token_id"] = ledger_tx.get("nft_token_id")
        hold_row["ledger_tx_id"] = ledger_tx.get("id")
        record["status"] = "held"
        record["retention"] = {
            "flag": True,
            "window_days": window_days,
            "release_after": release_after,
            "extended": False,
            "attempts": [],
            "offer": None,
        }
        _say(record, "user", "File the withdrawal.")
        _say(record, "bot", (
            f"Filed. ${amount:,.2f} is held from your wallet under {record['id']}."
            + (f" The bank transfer is released after {window_days} day{'s' if window_days != 1 else ''}." if window_days else "")
            + " You can cancel until then."
        ))
        _touch(record)
        _persist()
        return customer_view(record)


# ---------------------------------------------------------------------------
# Customer reversal
# ---------------------------------------------------------------------------
def _amend(record: Dict[str, Any], kind: str, from_amount: float, to_amount: float, returned: float,
           extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    trail = record.setdefault("amendments", [])
    entry = {
        "at": _iso(),
        "kind": kind,
        "from_amount": _money(from_amount),
        "to_amount": _money(to_amount),
        "returned": _money(returned),
        "previous_sha256": trail[-1]["sha256"] if trail else (record.get("seal") or {}).get("record_sha256") or "",
    }
    entry.update(extra or {})
    entry["sha256"] = _sha(entry)
    trail.append(entry)
    return entry


def _amendments_intact(record: Dict[str, Any]) -> bool:
    previous = (record.get("seal") or {}).get("record_sha256") or ""
    for entry in record.get("amendments") or []:
        body = {key: value for key, value in entry.items() if key != "sha256"}
        if entry.get("previous_sha256") != previous or _sha(body) != entry.get("sha256"):
            return False
        previous = entry["sha256"]
    return True


def _close(record: Dict[str, Any], status: str, by: str, reason: str = "") -> None:
    record["status"] = status
    record["closed"] = {"status": status, "at": _iso(), "by": by, "reason": str(reason or "")[:300]}
    retention = record.get("retention")
    if isinstance(retention, dict):
        retention["flag"] = False
        offer = retention.get("offer")
        if isinstance(offer, dict) and offer.get("status") == "open":
            offer["status"] = "accepted" if status == "reversed" and by == "customer_offer" else "closed"


def _held(record: Dict[str, Any]) -> None:
    if record.get("status") != "held":
        raise WithdrawalError("This request is not on hold", 409, "not_held")
    if not seal_intact(record) or not _amendments_intact(record):
        raise WithdrawalError(
            "This request no longer matches its seal and cannot be changed", 409, "seal_mismatch",
        )


def cancel(customer_id: str, withdrawal_id: str, reason: str = "") -> Dict[str, Any]:
    """The customer withdraws the request. A hold returns to the wallet in full."""
    with _lock_for(customer_id), _LOCK:
        record = _own(customer_id, withdrawal_id)
        if record.get("status") == "draft":
            _close(record, "discarded", "customer", reason)
            _touch(record)
            _persist()
            return customer_view(record)
        _held(record)
        amount = _money(record.get("amount"))
        row = _return_to_wallet(record, amount, "Withdrawal cancelled by the customer")
        _amend(record, "reversed", amount, 0.0, amount, {"by": "customer"})
        _close(record, "reversed", "customer", reason)
        try:
            ledger_tx = _record_nft(
                record, "wallet_withdrawal_reversed", amount,
                f"Health wallet withdrawal {record['id']} cancelled; hold returned",
                {"wallet_transaction_id": row["id"], "reversed_by": "customer"},
            )
            row["nft_token_id"] = ledger_tx.get("nft_token_id")
        except Exception:
            record.setdefault("flags", []).append("reversal_seal_pending")
        _say(record, "bot", f"Cancelled. ${amount:,.2f} is back in your health wallet.")
        _touch(record)
        _persist()
        return customer_view(record)


def accept_offer(customer_id: str, withdrawal_id: str, offer_id: str) -> Dict[str, Any]:
    """The customer accepts the open retention offer."""
    with _lock_for(customer_id), _LOCK:
        record = _own(customer_id, withdrawal_id)
        _held(record)
        retention = record.get("retention") or {}
        offer = retention.get("offer")
        if not isinstance(offer, dict) or offer.get("status") != "open" or offer.get("offer_id") != str(offer_id or ""):
            raise WithdrawalError("That offer is no longer open", 409, "offer_closed")
        amount = _money(record.get("amount"))
        method = str(offer.get("method") or "")
        keep = amount if method != "offer_partial" else min(amount, _money(offer.get("keep_amount")))
        if keep <= 0:
            raise WithdrawalError("That offer is no longer open", 409, "offer_closed")
        full = keep >= amount - 1e-9
        row = _return_to_wallet(record, keep, f"Accepted: {RETENTION_METHODS[method]['label']}")
        _amend(record, "reversed" if full else "reduced", amount, round(amount - keep, 2), keep,
               {"by": "customer", "offer_id": offer.get("offer_id"), "method": method})
        offer["status"] = "accepted"
        offer["accepted_at"] = _iso()
        if full:
            _close(record, "reversed", "customer_offer", RETENTION_METHODS[method]["label"])
        else:
            record["amount"] = round(amount - keep, 2)
            record["released_back"] = round(_money(record.get("released_back")) + keep, 2)
        try:
            ledger_tx = _record_nft(
                record, "wallet_withdrawal_reversed" if full else "wallet_withdrawal_reduced", keep,
                f"Health wallet withdrawal {record['id']}: ${keep:,.2f} returned on the customer's acceptance",
                {"wallet_transaction_id": row["id"], "offer_id": offer.get("offer_id"), "method": method,
                 "remaining_amount": 0.0 if full else record["amount"]},
            )
            row["nft_token_id"] = ledger_tx.get("nft_token_id")
        except Exception:
            record.setdefault("flags", []).append("reversal_seal_pending")
        _append_attempt(record, actor="customer", role="customer", method=method, outcome="accepted",
                        note=f"Customer accepted; ${keep:,.2f} returned to the wallet.")
        _say(record, "bot", (
            f"Done. ${keep:,.2f} is back in your health wallet."
            + ("" if full else f" ${record['amount']:,.2f} is still held for the bank transfer.")
        ))
        _touch(record)
        _persist()
        view = customer_view(record)
        view["next"] = RETENTION_METHODS[method].get("next")
        return view


def decline_offer(customer_id: str, withdrawal_id: str, offer_id: str) -> Dict[str, Any]:
    with _lock_for(customer_id), _LOCK:
        record = _own(customer_id, withdrawal_id)
        _held(record)
        offer = (record.get("retention") or {}).get("offer")
        if not isinstance(offer, dict) or offer.get("status") != "open" or offer.get("offer_id") != str(offer_id or ""):
            raise WithdrawalError("That offer is no longer open", 409, "offer_closed")
        offer["status"] = "declined"
        offer["declined_at"] = _iso()
        _append_attempt(record, actor="customer", role="customer", method=str(offer.get("method")),
                        outcome="declined", note="Customer declined the offer.")
        _touch(record)
        _persist()
        return customer_view(record)


# ---------------------------------------------------------------------------
# Retention desk
# ---------------------------------------------------------------------------
def _append_attempt(record: Dict[str, Any], *, actor: str, role: str, method: str, outcome: str,
                    note: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    retention = record.setdefault("retention", {})
    trail = retention.setdefault("attempts", [])
    entry = {
        "seq": len(trail) + 1,
        "at": _iso(),
        "actor": str(actor or "")[:120],
        "role": str(role or "")[:40],
        "method": method,
        "outcome": outcome,
        "note": " ".join(str(note or "").split())[:500],
        "previous_sha256": trail[-1]["sha256"] if trail else "",
    }
    entry.update(extra or {})
    entry["sha256"] = _sha(entry)
    trail.append(entry)
    return entry


def _attempts_intact(record: Dict[str, Any]) -> bool:
    previous = ""
    for entry in (record.get("retention") or {}).get("attempts") or []:
        body = {key: value for key, value in entry.items() if key != "sha256"}
        if entry.get("previous_sha256") != previous or _sha(body) != entry.get("sha256"):
            return False
        previous = entry["sha256"]
    return True


def retention_board(status: str = "held") -> Dict[str, Any]:
    """Flagged customers for the retention bar, soonest release first."""
    with _LOCK:
        rows = []
        for record in _store().values():
            if not isinstance(record, dict) or record.get("status") in ("draft", "discarded"):
                continue
            if status and status != "all" and record.get("status") != status:
                continue
            view = staff_view(record)
            view["customer_name"] = (record.get("details") or {}).get("name") or record.get("customer_id")
            rows.append(view)
    rows.sort(key=lambda row: (
        0 if row["status"] == "held" else 1,
        str((row.get("window") or {}).get("release_after") or row.get("updated_at") or ""),
    ))
    held = [row for row in rows if row["status"] == "held"]
    return {
        "items": rows,
        "total": len(rows),
        "flagged": len([row for row in held if (row.get("retention") or {}).get("flag")]),
        "held_amount": round(sum(row["amount"] for row in held), 2),
        "ready_to_release": len([row for row in held if (row.get("window") or {}).get("window_ended")]),
        "methods": [
            {"id": key, "label": spec["label"], "kind": spec["kind"], "needs": spec.get("needs"), "hint": spec["hint"]}
            for key, spec in RETENTION_METHODS.items()
        ],
        "retention_days": retention_days(),
    }


def get_for_staff(withdrawal_id: str) -> Dict[str, Any]:
    with _LOCK:
        record = _get(withdrawal_id)
        view = staff_view(record)
        view["customer_name"] = (record.get("details") or {}).get("name") or record.get("customer_id")
        return view


def record_retention(withdrawal_id: str, *, actor: str, role: str, method: str, note: str = "",
                     keep_amount: Any = None, days: Any = None, message: str = "",
                     channels: str = "both") -> Dict[str, Any]:
    """One retention step by customer relations. Money moves only if the customer accepts."""
    method = str(method or "").strip()
    spec = RETENTION_METHODS.get(method)
    if spec is None:
        raise WithdrawalError("Unknown retention method", 400, "method_invalid")
    note = " ".join(str(note or "").split())[:500]
    message = " ".join(str(message or "").split())[:600]
    customer_id = str(_get(withdrawal_id).get("customer_id") or "")
    with _lock_for(customer_id), _LOCK:
        record = _get(withdrawal_id)
        _held(record)
        if not _attempts_intact(record):
            raise WithdrawalError("The retention trail no longer matches its checksums", 409, "trail_mismatch")
        retention = record["retention"]
        extra: Dict[str, Any] = {}
        outcome = "recorded"
        kind = spec["kind"]
        if kind in ("contact", "note") and method != "outreach_message" and not note:
            raise WithdrawalError("Write what was said or noted", 400, "note_required")
        if method == "outreach_message":
            if not message:
                raise WithdrawalError("Write the message to send", 400, "message_required")
            portal = _portal()
            sender = getattr(portal, "send_admin_customer_outreach", None) if portal else None
            if not callable(sender):
                raise WithdrawalError("Customer messaging is not available", 503, "messaging_unavailable")
            result = sender(
                customer_id, template="message", channels=channels or "both",
                subject="About your health wallet withdrawal", custom_message=message,
                actor=f"customer_relations:{actor}",
            )
            outcome = "sent" if result.get("success") else "not_sent"
            extra["delivery"] = {
                "success": bool(result.get("success")),
                "error": str(result.get("error") or "")[:200],
                "channels": channels or "both",
            }
            note = note or message
        elif kind == "offer":
            open_offer = retention.get("offer")
            if isinstance(open_offer, dict) and open_offer.get("status") == "open":
                raise WithdrawalError("An offer is already open on this request", 409, "offer_open")
            amount = _money(record.get("amount"))
            keep = amount
            if method == "offer_partial":
                keep = _money(keep_amount)
                if keep <= 0 or keep >= amount:
                    raise WithdrawalError(
                        f"The kept amount must be more than $0 and less than ${amount:,.2f}", 400, "keep_amount_invalid",
                    )
            offer = {
                "offer_id": f"OFR-{secrets.token_hex(4).upper()}",
                "method": method,
                "keep_amount": keep,
                "message": message or note,
                "made_by": str(actor or "")[:120],
                "made_at": _iso(),
                "status": "open",
            }
            retention["offer"] = offer
            outcome = "offered"
            extra["offer_id"] = offer["offer_id"]
            extra["keep_amount"] = keep
        elif method == "extend_hold":
            if retention.get("extended"):
                raise WithdrawalError("The window was already extended once", 409, "already_extended")
            try:
                extra_days = int(days)
            except (TypeError, ValueError):
                raise WithdrawalError("Choose 1 to 4 days", 400, "days_invalid")
            if not (1 <= extra_days <= MAX_EXTENSION_DAYS):
                raise WithdrawalError("Choose 1 to 4 days", 400, "days_invalid")
            if not note:
                raise WithdrawalError("Give the reason for the extension", 400, "note_required")
            current = _parse(retention.get("release_after")) or _now()
            retention["release_after"] = _iso(current + timedelta(days=extra_days))
            retention["extended"] = True
            outcome = "extended"
            extra["days"] = extra_days
            extra["release_after"] = retention["release_after"]
        elif method == "escalate":
            if not note:
                raise WithdrawalError("Give the reason for the escalation", 400, "note_required")
            try:
                from services.customer_agent.escalation import get_escalation_desk

                escalation = get_escalation_desk().escalate(
                    customer_id=customer_id, reason=f"Wallet withdrawal {record['id']}: {note}",
                    source_agent="customer_relations", actor=actor,
                    customer_name=(record.get("details") or {}).get("name"),
                    context={"withdrawal_id": record["id"], "amount": _money(record.get("amount"))},
                )
                extra["escalation_id"] = getattr(escalation, "report_id", None)
                outcome = "escalated"
            except Exception:
                raise WithdrawalError("The escalation could not be opened", 503, "escalation_unavailable")
        _append_attempt(record, actor=actor, role=role, method=method, outcome=outcome, note=note, extra=extra)
        _touch(record)
        _persist()
        view = staff_view(record)
        view["customer_name"] = (record.get("details") or {}).get("name") or customer_id
        return view


def release(withdrawal_id: str, *, actor: str, role: str, reference: str = "") -> Dict[str, Any]:
    """Pay out a held request once its window has ended."""
    customer_id = str(_get(withdrawal_id).get("customer_id") or "")
    with _lock_for(customer_id), _LOCK:
        record = _get(withdrawal_id)
        _held(record)
        window = _window(record)
        if not window["window_ended"]:
            raise WithdrawalError(
                "The retention window has not ended yet", 409, "window_open",
            )
        if decrypt_bank_account(record) is None:
            raise WithdrawalError("The bank account cannot be read from the vault", 409, "bank_vault_unreadable")
        amount = _money(record.get("amount"))
        if amount < 0.01:
            raise WithdrawalError("Nothing is left to pay out", 409, "nothing_to_pay")
        ledger_tx = _record_nft(
            record, "wallet_withdrawal_paid", amount,
            f"Health wallet withdrawal {record['id']} paid to bank account ending {(record.get('bank') or {}).get('account_last4')}",
            {"released_by": actor, "payout_reference": str(reference or "")[:80],
             "bank_account_last4": (record.get("bank") or {}).get("account_last4")},
        )
        record["payout"] = {
            "at": _iso(), "by": str(actor or "")[:120], "amount": amount,
            "reference": str(reference or "")[:80], "nft_token_id": ledger_tx.get("nft_token_id"),
        }
        _append_attempt(record, actor=actor, role=role, method="release", outcome="paid_out",
                        note=f"${amount:,.2f} released to the bank account.")
        _close(record, "paid_out", str(actor or "staff"), "")
        _say(record, "bot", f"${amount:,.2f} was sent to your bank account ending {(record.get('bank') or {}).get('account_last4')}.")
        _touch(record)
        _persist()
        return get_for_staff(withdrawal_id)


def decline(withdrawal_id: str, *, actor: str, role: str, reason: str) -> Dict[str, Any]:
    """Refuse a held request. The hold returns to the customer's own wallet."""
    reason = " ".join(str(reason or "").split())[:300]
    if len(reason) < 4:
        raise WithdrawalError("Give the reason for declining", 400, "reason_required")
    customer_id = str(_get(withdrawal_id).get("customer_id") or "")
    with _lock_for(customer_id), _LOCK:
        record = _get(withdrawal_id)
        _held(record)
        amount = _money(record.get("amount"))
        row = _return_to_wallet(record, amount, "Withdrawal declined")
        _amend(record, "declined", amount, 0.0, amount, {"by": str(actor or "")[:120]})
        _append_attempt(record, actor=actor, role=role, method="decline", outcome="declined", note=reason)
        _close(record, "declined", str(actor or "staff"), reason)
        try:
            ledger_tx = _record_nft(
                record, "wallet_withdrawal_reversed", amount,
                f"Health wallet withdrawal {record['id']} declined; hold returned",
                {"wallet_transaction_id": row["id"], "reversed_by": "staff_decline"},
            )
            row["nft_token_id"] = ledger_tx.get("nft_token_id")
        except Exception:
            record.setdefault("flags", []).append("reversal_seal_pending")
        _say(record, "bot", f"This withdrawal was declined: {reason} ${amount:,.2f} is back in your health wallet.")
        _touch(record)
        _persist()
        return get_for_staff(withdrawal_id)


def decrypt_bank_account(record: Dict[str, Any]) -> Optional[str]:
    from security.vault import decrypt_json

    data = decrypt_json(str(record.get("bank_vault") or ""), default=None)
    account = str((data or {}).get("account") or "") if isinstance(data, dict) else ""
    if not account:
        return None
    if hashlib.sha256(account.encode("utf-8")).hexdigest() != (record.get("bank") or {}).get("account_sha256"):
        return None
    return account


def bank_details(withdrawal_id: str) -> Dict[str, Any]:
    """Full payout instructions. The caller checks the role first."""
    with _LOCK:
        record = _get(withdrawal_id)
        account = decrypt_bank_account(record)
        if account is None:
            raise WithdrawalError("The bank account cannot be read from the vault", 409, "bank_vault_unreadable")
        bank = dict(record.get("bank") or {})
        bank.pop("account_sha256", None)
        bank["account"] = account
        return {"id": record["id"], "amount": _money(record.get("amount")), "bank": bank}


def withdrawn_net(customer_id: str) -> float:
    """Wallet money this customer has on hold or already paid out."""
    total = 0.0
    for record in _store().values():
        if (isinstance(record, dict) and record.get("customer_id") == customer_id
                and record.get("status") in ("held", "paid_out")):
            total += _money(record.get("amount"))
    return round(total, 2)


def withdrawn_by_customer() -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for record in _store().values():
        if isinstance(record, dict) and record.get("status") in ("held", "paid_out"):
            customer_id = str(record.get("customer_id") or "")
            totals[customer_id] = round(totals.get(customer_id, 0.0) + _money(record.get("amount")), 2)
    return totals


# ---------------------------------------------------------------------------
# The unified document
# ---------------------------------------------------------------------------
def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _row(label: str, value: Any, code: bool = False) -> str:
    if value is None or str(value).strip() == "":
        return ""
    shown = f"<code>{_e(value)}</code>" if code else _e(value)
    return f"<tr><th>{_e(label)}</th><td>{shown}</td></tr>"


_DOCUMENT_STYLE = """
<style>
.wdr-head { display: flex; gap: 22px; align-items: flex-start; flex-wrap: wrap; margin-bottom: 8px; }
.wdr-photo { width: 144px; height: 180px; border-radius: 10px; object-fit: cover; border: 2px solid #c4a35a; background: #eef1f6; }
.wdr-photo-missing { display: flex; align-items: center; justify-content: center; color: #6b7280; font-size: 12px; text-align: center; padding: 8px; box-sizing: border-box; }
.wdr-amount { font-family: "Space Grotesk", Inter, sans-serif; font-size: 34px; color: #0b1f3a; margin: 2px 0; }
.wdr-status { display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; background: #0b1f3a; color: #f3e6c0; }
.wdr-status.reversed, .wdr-status.declined { background: #7a2f2f; }
.wdr-status.paid_out { background: #0f6b45; }
.wdr-sign { display: flex; gap: 24px; align-items: flex-end; flex-wrap: wrap; margin: 6px 0 14px; }
.wdr-sign img { height: 96px; max-width: 320px; border-bottom: 1px solid #0b1f3a; background: #fff; }
.wdr-sign div { font-size: 12px; color: #4b5563; }
.wdr-sign strong { display: block; font-size: 15px; color: #0b1f3a; }
.wdr-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 0 28px; }
.phins-doc table.wdr th { width: 42%; background: transparent; color: #4b5563; font-weight: 500; }
.phins-doc table.wdr td code { word-break: break-all; }
</style>
"""


def render_document(withdrawal_id: str) -> str:
    """The unified withdrawal document. Refused when the seal does not match."""
    from services.phins_document import render_phins_document

    with _LOCK:
        record = _get(withdrawal_id)
        if record.get("status") in ("draft", "discarded") or not record.get("seal"):
            raise WithdrawalError("This request has not been filed", 409, "not_filed")
        if not seal_intact(record) or not _amendments_intact(record):
            raise WithdrawalError(
                "This document no longer matches its seal and is withheld", 409, "seal_mismatch",
            )
        sealed = json.loads(_canonical(record["sealed"]))
        seal = dict(record.get("seal") or {})
        status = str(record.get("status") or "")
        amount_now = _money(record.get("amount"))
        amendments = [dict(item) for item in record.get("amendments") or []]
        payout = dict(record.get("payout") or {})
        closed = dict(record.get("closed") or {})
        portrait_ref = dict((record.get("documents") or {}).get("portrait") or {})
        signature_ref = {"document_id": (record.get("signature") or {}).get("document_id"),
                         "sha256": (record.get("signature") or {}).get("sha256")}
    # A picture is shown only while its bytes still match the sealed SHA-256.
    portrait_ok = portrait_ref.get("sha256") == sealed["documents"]["portrait"].get("sha256")
    portrait = _read_file(portrait_ref) if portrait_ok else None
    signature_ok = signature_ref.get("sha256") == sealed["signature"].get("sha256")
    signature = _read_file(signature_ref) if signature_ok else None
    holder = sealed["holder"]
    bank = sealed["bank"]
    documents = sealed["documents"]
    photo_html = (
        f'<img class="wdr-photo" alt="Account holder" src="data:image/jpeg;base64,{base64.b64encode(portrait).decode("ascii")}">'
        if portrait else '<div class="wdr-photo wdr-photo-missing">Photo withheld: the file does not match its seal</div>'
    )
    signature_html = (
        f'<img alt="Signature" src="data:image/png;base64,{base64.b64encode(signature).decode("ascii")}">'
        if signature else '<div>Signature image withheld: the file does not match its seal</div>'
    )
    status_label = {
        "held": "Held for payout", "reversed": "Reversed by the customer",
        "declined": "Declined", "paid_out": "Paid out",
    }.get(status, status)
    account_label = "IBAN" if bank.get("account_kind") == "iban" else "Account number"
    identity_line = (
        f"{_e(holder.get('nationality'))} · ID ending {_e(holder.get('national_id_last4'))}"
        if holder.get("national_id_last4") else "No identity on the customer master"
    )
    body = [_DOCUMENT_STYLE]
    body.append(
        '<div class="wdr-head">' + photo_html + '<div>'
        f'<span class="wdr-status {_e(status)}">{_e(status_label)}</span>'
        f'<div class="wdr-amount">${sealed["amount"]:,.2f} {_e(sealed.get("currency"))}</div>'
        f'<p class="sub">Withdrawal from the health wallet of <strong>{_e(holder.get("name"))}</strong><br>'
        f'Request <code>{_e(sealed["withdrawal_id"])}</code> · filed {_e(sealed["filed_at"][:19].replace("T", " "))} UTC</p>'
        + (f'<p class="sub">Amount now on this request: <strong>${amount_now:,.2f}</strong></p>'
           if status == "held" and abs(amount_now - sealed["amount"]) > 0.005 else "")
        + '</div></div>'
    )
    body.append('<div class="wdr-cols"><div><h2>Account holder</h2><table class="wdr">'
                + _row("Name", holder.get("name")) + _row("Customer", sealed["customer_id"], True)
                + _row("Email", holder.get("email")) + _row("Phone", holder.get("phone"))
                + _row("Address", holder.get("address"))
                + f"<tr><th>Identity</th><td>{identity_line}</td></tr>"
                + '</table></div>')
    body.append('<div><h2>Transfer</h2><table class="wdr">'
                + _row("From", "PHINS health wallet")
                + _row("Wallet before", f"${sealed['wallet']['balance_before']:,.2f}")
                + _row("Wallet after the hold", f"${sealed['wallet']['balance_after']:,.2f}")
                + _row("Account holder", bank.get("holder")) + _row("Bank", bank.get("bank_name"))
                + _row("Branch", bank.get("branch")) + _row("Country", bank.get("country"))
                + _row(account_label, "•••• " + str(bank.get("account_last4") or ""))
                + _row("SWIFT", bank.get("swift"))
                + _row("Reason given", (sealed.get("reason") or {}).get("label"))
                + _row("Customer's note", (sealed.get("reason") or {}).get("note"))
                + _row("Released after", str(sealed.get("release_after") or "")[:19].replace("T", " ") + " UTC")
                + '</table></div></div>')
    body.append('<h2>Authorisation</h2><p class="sub">I ask PHINS to transfer the amount above from my health wallet '
                'to the bank account above, and I confirm the documents attached to this request are mine.</p>'
                '<div class="wdr-sign">' + signature_html
                + f'<div><strong>{_e(sealed["signature"].get("signer_name"))}</strong>'
                  f'Signed {_e(str(sealed["signature"].get("signed_at") or "")[:19].replace("T", " "))} UTC · drawn signature</div></div>')
    body.append('<h2>Attached evidence</h2><table class="wdr">'
                + _row("Identity document", documents["id_document"].get("sha256"), True)
                + _row("Portrait cut from", documents["portrait"].get("source_sha256"), True)
                + _row("Portrait", documents["portrait"].get("sha256"), True)
                + _row("Bank document", documents["bank_document"].get("sha256"), True)
                + _row("Signature", sealed["signature"].get("sha256"), True)
                + '</table>')
    if sealed.get("flags"):
        body.append('<p class="note">Review notes: ' + _e(", ".join(flag.replace("_", " ") for flag in sealed["flags"])) + '</p>')
    if amendments or payout or closed:
        rows = "".join(
            f"<tr><td>{_e(str(item.get('at') or '')[:19].replace('T', ' '))}</td><td>{_e(item.get('kind'))}</td>"
            f"<td>${_money(item.get('from_amount')):,.2f} → ${_money(item.get('to_amount')):,.2f}</td>"
            f"<td>${_money(item.get('returned')):,.2f} returned to the wallet</td></tr>"
            for item in amendments
        )
        if payout:
            rows += (f"<tr><td>{_e(str(payout.get('at') or '')[:19].replace('T', ' '))}</td><td>paid out</td>"
                     f"<td>${_money(payout.get('amount')):,.2f}</td><td>NFT <code>{_e(payout.get('nft_token_id'))}</code></td></tr>")
        if closed and closed.get("reason"):
            rows += (f"<tr><td>{_e(str(closed.get('at') or '')[:19].replace('T', ' '))}</td><td>{_e(closed.get('status'))}</td>"
                     f"<td colspan=\"2\">{_e(closed.get('reason'))}</td></tr>")
        body.append('<h2>After filing</h2><table><thead><tr><th>When (UTC)</th><th>Event</th><th>Amount</th><th>Detail</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>')
    body.append('<h2>Seal</h2><table class="wdr">'
                + _row("Wallet NFT", seal.get("nft_token_id"), True)
                + _row("Document SHA-256", seal.get("record_sha256"), True)
                + _row("Signature anchor", seal.get("legal_doc_instance"), True)
                + _row("Ledger entry", seal.get("legal_entry_id"), True)
                + '</table>')
    footer = (f"Sealed {_e(sealed['filed_at'][:10])} · SHA-256 {_e(str(seal.get('record_sha256') or '')[:16])}… · "
              f"wallet NFT {_e(seal.get('nft_token_id'))}")
    return render_phins_document(
        title=f"Health wallet withdrawal {sealed['withdrawal_id']}",
        eyebrow="Health wallet withdrawal",
        subtitle=sealed["withdrawal_id"],
        body_html="\n".join(body),
        footer=footer,
    )


def render_document_for_customer(customer_id: str, withdrawal_id: str) -> str:
    with _LOCK:
        _own(customer_id, withdrawal_id)
    return render_document(withdrawal_id)


def reset_wallet_withdrawals() -> None:
    """Test helper: empty the fallback store."""
    with _LOCK:
        _FALLBACK_STORE.clear()
