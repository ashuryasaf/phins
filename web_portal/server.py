#!/usr/bin/env python3
"""
PHINS Web Portal Server

Lightweight HTTP server for the PHINS insurance platform.
Serves static files and JSON API endpoints.

Usage:
  python web_portal/server.py       # start on $PORT (default 8000)
  python web_portal/server.py --test  # run quick self-tests and exit
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse as urlparse
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SERVER_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", 8000))
ROOT = os.path.join(_SERVER_DIR, "static")
PHINS_TEST_MODE = str(os.environ.get("PHINS_TEST_MODE", "")).lower() in ("1", "true", "yes", "y")

# Media upload limits
MAX_REQUEST_SIZE = int(os.environ.get("MAX_REQUEST_SIZE", str(10 * 1024 * 1024)))  # 10 MB default
MAX_MEDIA_UPLOAD_SIZE = int(os.environ.get("MAX_MEDIA_UPLOAD_SIZE", "0"))  # 0 = unlimited

# Media webhook secret
MEDIA_PROVIDER_WEBHOOK_SECRET = os.environ.get(
    "MEDIA_PROVIDER_WEBHOOK_SECRET", secrets.token_urlsafe(32)
)

# Cleanup interval
CLEANUP_INTERVAL = 300  # seconds

# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def status_eq(item: Dict, *statuses: str) -> bool:
    item_status = (item.get("status") or "").lower().replace(" ", "_")
    return item_status in [s.lower().replace(" ", "_") for s in statuses]


def status_in(item: Dict, statuses: list) -> bool:
    item_status = (item.get("status") or "").lower().replace(" ", "_")
    return item_status in [s.lower().replace(" ", "_") for s in statuses]


def get_status_lower(item: Dict) -> str:
    return (item.get("status") or "").lower().replace(" ", "_")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_suspended_account(customer_id: str) -> bool:
    """Return True if the customer account is suspended."""
    if not customer_id:
        return False
    customer = CUSTOMERS.get(customer_id) or REGISTERED_CUSTOMERS.get(customer_id) or {}
    return str(customer.get("status") or "").lower() in {"suspended", "blocked", "banned"}


# ---------------------------------------------------------------------------
# Database support
# ---------------------------------------------------------------------------

USE_DATABASE = os.environ.get("USE_DATABASE", "true").lower() not in ("false", "0", "no")
database_enabled = False

if USE_DATABASE:
    try:
        from database import init_database, check_database_connection, get_database_info
        from database.seeds import seed_default_users
        from database.data_access import CUSTOMERS as DB_CUSTOMERS
        from database.data_access import POLICIES as DB_POLICIES
        from database.data_access import CLAIMS as DB_CLAIMS
        from database.data_access import UNDERWRITING_APPLICATIONS as DB_UNDERWRITING
        from database.data_access import SESSIONS as DB_SESSIONS
        from database.data_access import BILLING as DB_BILLING
        from database.data_access import USERS_DB as DB_USERS

        database_enabled = True
        print("✓ Database persistence enabled")

        try:
            init_database()
            seed_default_users()
        except Exception as _db_init_err:
            print(f"Warning: Database init/seed failed: {_db_init_err}")
    except ImportError as _db_import_err:
        print(f"Warning: Database support not available: {_db_import_err}")
        USE_DATABASE = False
else:
    print("⚠️  Running in volatile in-memory mode (USE_DATABASE=false)")

# ---------------------------------------------------------------------------
# In-memory storage
# ---------------------------------------------------------------------------

if USE_DATABASE and database_enabled:
    POLICIES = DB_POLICIES
    CLAIMS = DB_CLAIMS
    CUSTOMERS = DB_CUSTOMERS
    UNDERWRITING_APPLICATIONS = DB_UNDERWRITING
    SESSIONS = DB_SESSIONS
    BILLING = DB_BILLING
else:
    POLICIES: Dict[str, Dict[str, Any]] = {}
    CLAIMS: Dict[str, Dict[str, Any]] = {}
    CUSTOMERS: Dict[str, Dict[str, Any]] = {}
    UNDERWRITING_APPLICATIONS: Dict[str, Dict[str, Any]] = {}
    SESSIONS: Dict[str, Dict[str, Any]] = {}
    BILLING: Dict[str, Dict[str, Any]] = {}

REGISTERED_CUSTOMERS: Dict[str, Dict[str, Any]] = {}
HEALTH_WALLETS: Dict[str, Dict[str, Any]] = {}
MEDICAL_PURCHASES: Dict[str, Dict[str, Any]] = {}
NFT_LEDGER: Dict[str, Dict[str, Any]] = {}
CUSTOMER_ALLOCATIONS: Dict[str, Dict[str, Any]] = {}
INVESTMENT_ACCOUNTS: Dict[str, Dict[str, Any]] = {}
TRANSACTION_LEDGER: Dict[str, Dict[str, Any]] = {}
CLAIM_FILES: Dict[str, Dict[str, Any]] = {}
UNDERWRITING_FILES: Dict[str, Dict[str, Any]] = {}
AUDIT_LOG: List[Dict[str, Any]] = []
RATE_LIMIT: Dict[str, Any] = {}
FAILED_LOGINS: Dict[str, Any] = {}
BLOCKED_IPS: Dict[str, Any] = {}
SUSPICIOUS_PATTERNS: Dict[str, Any] = {}

# Media assets and processing jobs
MEDIA_ASSETS: Dict[str, Dict[str, Any]] = {}
MEDIA_PROCESSING_JOBS: Dict[str, Dict[str, Any]] = {}

# Design settings
DESIGN_SETTINGS: Dict[str, Any] = {
    "video_url": "",
    "video_poster": "",
    "tagline": "Comprehensive Protection for Your Future",
    "primary_color": "#0d47a1",
    "accent_color": "#ff6b35",
    "show_video": True,
    "show_contact": True,
    "show_quote_form": False,
    "show_products": False,
    "show_underwriting": False,
    "hero_video_id": "",
    "hero_background_id": "",
    "video_poster_id": "",
    "promo_banner_id": "",
    "updated_at": None,
    "updated_by": None,
}

# Invitation codes
INVITATION_CODES: Dict[str, Dict[str, Any]] = {}

# Balance sheet
PHINS_BALANCE_SHEET: Dict[str, Any] = {
    "account_id": "PHINS-MAIN-001",
    "name": "PHINS General Reserves",
    "created_at": None,
    "last_updated": None,
    "claims_reserve": 3500000.00,
    "operating_reserve": 0.00,
    "supplier_reserve": 0.00,
    "investment_reserve": 0.00,
    "total_revenue": 0.00,
    "revenue_breakdown": {
        "premium_income": 0.00,
        "management_fees": 0.00,
        "underwriting_fees": 0.00,
        "investment_earnings": 0.00,
        "late_fees": 0.00,
        "other_income": 0.00,
    },
    "total_expenses": 0.00,
    "expense_breakdown": {
        "claims_paid": 0.00,
        "supplier_payments": 0.00,
        "operating_costs": 0.00,
        "commissions": 0.00,
        "reinsurance": 0.00,
        "other_expenses": 0.00,
    },
    "transactions": [],
    "audit_log": [],
}

# Reinsurance contracts and actuarial simulations
REINSURANCE_CONTRACTS: Dict[str, Dict[str, Any]] = {}
ACTUARIAL_SIMULATIONS: Dict[str, Dict[str, Any]] = {}

# Supplier data
SUPPLIERS: Dict[str, Dict[str, Any]] = {}
SUPPLIER_OFFERS: Dict[str, Dict[str, Any]] = {}
SUPPLIER_ORDERS: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

STATE_LOCK = threading.RLock()
last_cleanup = datetime.now()

# Per-port initialization tracker (for tests)
_TEST_PORTS_INITIALIZED: set = set()

# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> Dict[str, str]:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return {"hash": hashed.hex(), "salt": salt}


def _verify_password(password: str, stored: Dict[str, str]) -> bool:
    try:
        hashed = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), stored["salt"].encode(), 100000
        )
        return hmac.compare_digest(hashed.hex(), stored["hash"])
    except Exception:
        return False


def _env_password(env_var: str, fallback: str) -> str:
    return os.environ.get(env_var, fallback)


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

USERS: Dict[str, Dict[str, Any]] = {
    "admin": {
        "username": "admin",
        "password_data": _hash_password(_env_password("PHINS_ADMIN_PASSWORD", "admin123")),
        "role": "admin",
        "name": "Admin User",
        "email": "admin@phins.ai",
    },
    "underwriter": {
        "username": "underwriter",
        "password_data": _hash_password(_env_password("PHINS_UNDERWRITER_PASSWORD", "under123")),
        "role": "underwriter",
        "name": "John Underwriter",
        "email": "underwriter@phins.ai",
    },
    "claims_adjuster": {
        "username": "claims_adjuster",
        "password_data": _hash_password(_env_password("PHINS_CLAIMS_PASSWORD", "claims123")),
        "role": "claims",
        "name": "Claims Adjuster",
        "email": "claims@phins.ai",
    },
    "accountant": {
        "username": "accountant",
        "password_data": _hash_password(_env_password("PHINS_ACCOUNTANT_PASSWORD", "acct123")),
        "role": "accountant",
        "name": "Accountant User",
        "email": "accountant@phins.ai",
    },
    "actuary": {
        "username": "actuary",
        "password_data": _hash_password(_env_password("PHINS_ACTUARY_PASSWORD", "actuary123")),
        "role": "actuary",
        "name": "Actuary User",
        "email": "actuary@phins.ai",
    },
}

# Test mode invitation code
if PHINS_TEST_MODE:
    INVITATION_CODES["TESTCODE2026"] = {
        "code": "TESTCODE2026",
        "status": "active",
        "used_count": 0,
        "max_uses": 9999,
        "created_by": "system",
        "created_at": "2026-01-01T00:00:00",
        "expires_at": "2099-12-31T23:59:59",
    }

# ---------------------------------------------------------------------------
# Security / auth imports
# ---------------------------------------------------------------------------

_AUTH_TOKENS_AVAILABLE = False
_SECURITY_HEADERS_AVAILABLE = False

try:
    from security import auth_tokens as _auth_tokens_module
    _AUTH_TOKENS_AVAILABLE = True
except ImportError:
    _auth_tokens_module = None  # type: ignore[assignment]

try:
    from security.headers import (
        json_security_headers,
        html_security_headers,
        static_asset_security_headers,
    )
    _SECURITY_HEADERS_AVAILABLE = True
except ImportError:
    def json_security_headers():  # type: ignore[misc]
        return [("X-Content-Type-Options", "nosniff"), ("Cache-Control", "no-store")]
    def html_security_headers():  # type: ignore[misc]
        return [("X-Content-Type-Options", "nosniff")]
    def static_asset_security_headers():  # type: ignore[misc]
        return [("X-Content-Type-Options", "nosniff")]

# ---------------------------------------------------------------------------
# Service imports
# ---------------------------------------------------------------------------

_MEDIA_GENERATION_AVAILABLE = False
_METRICS_AVAILABLE = False
_MARKETING_AGENT_AVAILABLE = False
_ACTUARIAL_AVAILABLE = False
_REINSURANCE_AVAILABLE = False
_VIDEO_AGENTS_AVAILABLE = False
_OTP_AVAILABLE = False

try:
    from services.media_generation_service import get_media_generation_service as _get_mgs
    get_media_generation_service = _get_mgs
    _MEDIA_GENERATION_AVAILABLE = True
except ImportError:
    def get_media_generation_service():  # type: ignore[misc]
        return None

try:
    from services.metrics_service import MetricsService
    _METRICS_AVAILABLE = True
except ImportError:
    MetricsService = None  # type: ignore[assignment,misc]

try:
    from services.marketing_sales_agent_service import get_marketing_sales_agent_service
    _MARKETING_AGENT_AVAILABLE = True
except ImportError:
    get_marketing_sales_agent_service = None  # type: ignore[assignment]

try:
    from services.actuarial_service import get_actuarial_service
    _ACTUARIAL_AVAILABLE = True
except ImportError:
    get_actuarial_service = None  # type: ignore[assignment]

try:
    from services.reinsurance_service import get_reinsurance_service
    _REINSURANCE_AVAILABLE = True
except ImportError:
    get_reinsurance_service = None  # type: ignore[assignment]

try:
    from web_portal.api_video_agents import (
        handle_video_providers,
        handle_generate_video_agent,
        handle_list_video_agent_jobs,
        handle_get_video_agent_job,
        handle_video_agent_webhook,
    )
    _VIDEO_AGENTS_AVAILABLE = True
except ImportError:
    _VIDEO_AGENTS_AVAILABLE = False

try:
    from services.otp_security_service import get_otp_security_service
    _OTP_AVAILABLE = True
except ImportError:
    get_otp_security_service = None  # type: ignore[assignment]

# Extension dispatchers
try:
    from web_portal.api_extensions import dispatch_get as _ext_get
except ImportError:
    def _ext_get(*a, **kw):  # type: ignore[misc]
        return None

try:
    from web_portal.api_extensions import dispatch_post as _ext_post
except ImportError:
    def _ext_post(*a, **kw):  # type: ignore[misc]
        return None

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

_SESSION_SECRET = os.environ.get("SESSION_SECRET_KEY", "")
_TOKEN_TTL_HOURS = 24


def _verify_legacy_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a legacy phins_ token."""
    if not token or not token.startswith("phins_"):
        return None
    try:
        body = token[6:]
        if "." not in body:
            return None
        b64_part, _sig = body.rsplit(".", 1)
        payload = base64.b64decode(b64_part + "==").decode()
        parts = payload.split(":")
        if len(parts) < 2:
            return None
        username, role = parts[0], parts[1]
        customer_id = parts[2] if len(parts) > 2 else ""
        return {
            "username": username,
            "role": role,
            "customer_id": customer_id or None,
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
    except Exception:
        return None


if _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None:
    _auth_tokens_module.register_legacy_verifier(_verify_legacy_token)


def _mint_token(username: str, role: str, customer_id: str = "") -> str:
    """Mint a session token (v2 if secret available, legacy otherwise)."""
    if _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None:
        secret = os.environ.get("SESSION_SECRET_KEY", "")
        if secret and len(secret.encode()) >= 32:
            try:
                expires = datetime.now() + timedelta(hours=_TOKEN_TTL_HOURS)
                token, _claims = _auth_tokens_module.create_token(
                    username=username,
                    role=role,
                    customer_id=customer_id or None,
                    expires_at=expires,
                )
                return token
            except Exception:
                pass
    # Legacy token
    payload = f"{username}:{role}:{customer_id}:{time.time()}"
    b64 = base64.b64encode(payload.encode()).decode()
    sig = hashlib.sha256(f"{payload}:{_SESSION_SECRET}".encode()).hexdigest()[:16]
    return f"phins_{b64}.{sig}"


def validate_session(token: str) -> Optional[Dict[str, Any]]:
    """Validate a session token and return session data or None."""
    if not token:
        return None

    # Check in-memory sessions first
    with STATE_LOCK:
        session = SESSIONS.get(token)
    if session:
        try:
            expires = datetime.fromisoformat(str(session.get("expires", "")))
            if expires > datetime.now():
                return session
        except Exception:
            pass
        with STATE_LOCK:
            SESSIONS.pop(token, None)
        return None

    # Try v2 token verification
    if _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None:
        try:
            session_data = _auth_tokens_module.verify_any_token(token)
            if session_data:
                return session_data
        except Exception:
            pass

    # Try legacy token
    return _verify_legacy_token(token)


def _revoke_user_sessions(username: str, exclude_token: str = "") -> None:
    """Revoke all sessions for a user (optionally excluding one token)."""
    with STATE_LOCK:
        to_remove = [
            t for t, s in SESSIONS.items()
            if s.get("username") == username and t != exclude_token
        ]
        for t in to_remove:
            jti = SESSIONS[t].get("jti")
            if jti and _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None:
                try:
                    _auth_tokens_module.revoke_token(jti, time.time() + 86400)
                except Exception:
                    pass
            del SESSIONS[t]

    if USE_DATABASE and database_enabled:
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                db_sessions = db.sessions.get_by_username(username)
                for db_session in db_sessions:
                    if db_session.token != exclude_token:
                        db.sessions.delete(db_session.token)
        except Exception:
            pass


def cleanup_stale_data() -> None:
    """Remove expired sessions and prune old data."""
    global last_cleanup
    now = datetime.now()
    if (now - last_cleanup).total_seconds() < CLEANUP_INTERVAL:
        return
    last_cleanup = now

    with STATE_LOCK:
        expired = [t for t, s in SESSIONS.items() if _session_expired(s)]
        for t in expired:
            SESSIONS.pop(t, None)

    if USE_DATABASE and database_enabled:
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                db.sessions.delete_expired_sessions()
        except Exception:
            pass

    if _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None:
        try:
            _auth_tokens_module.prune_revocations()
        except Exception:
            pass


def _session_expired(session: Dict[str, Any]) -> bool:
    try:
        expires = datetime.fromisoformat(str(session.get("expires", "")))
        return expires <= datetime.now()
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Media helpers
# ---------------------------------------------------------------------------


def safe_ascii_filename_stem(
    name: str, *, fallback: str = "asset", max_len: int = 80
) -> str:
    """Sanitize a filename stem to safe ASCII characters."""
    stem = re.sub(r"[^\w\s\-]", "", str(name or ""), flags=re.ASCII)
    stem = re.sub(r"[\s\-]+", "_", stem).strip("_")
    stem = stem[:max_len]
    return stem if stem else fallback


def compute_media_checksum(data: bytes) -> str:
    """Return SHA-256 hex digest of data bytes."""
    return hashlib.sha256(data).hexdigest()


def serialize_media_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
    """Return a safe, serializable copy of a media asset (no file_path)."""
    return {k: v for k, v in asset.items() if k != "file_path"}


def _video_job_summary(campaign_id: str = "") -> Dict[str, Any]:
    """Return a summary of video generation jobs for a campaign."""
    jobs = [
        j for j in MEDIA_PROCESSING_JOBS.values()
        if j.get("job_kind") in {"video_generation", "video_agent"}
        and (not campaign_id or j.get("campaign_id") == campaign_id)
    ]
    active = sum(1 for j in jobs if j.get("status") in {"queued", "processing"})
    completed = sum(1 for j in jobs if j.get("status") == "completed")
    failed = sum(1 for j in jobs if j.get("status") in {"failed", "cancelled"})
    return {
        "total": len(jobs),
        "active": active,
        "completed": completed,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Balance sheet helpers
# ---------------------------------------------------------------------------


def _init_balance_sheet() -> None:
    global PHINS_BALANCE_SHEET
    if PHINS_BALANCE_SHEET.get("created_at") is None:
        PHINS_BALANCE_SHEET["created_at"] = datetime.now().isoformat()
        PHINS_BALANCE_SHEET["last_updated"] = datetime.now().isoformat()


def _record_balance_sheet_transaction(
    tx_type: str,
    category: str,
    amount: float,
    description: str,
    actor: str = "SYSTEM",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    global PHINS_BALANCE_SHEET
    tx_id = (
        f"BS-{tx_type.upper()[:3]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        f"-{secrets.token_hex(2)}"
    )

    if tx_type == "revenue":
        if category in PHINS_BALANCE_SHEET["revenue_breakdown"]:
            PHINS_BALANCE_SHEET["revenue_breakdown"][category] += amount
        PHINS_BALANCE_SHEET["total_revenue"] += amount
        PHINS_BALANCE_SHEET["operating_reserve"] += amount
    elif tx_type == "expense":
        if category in PHINS_BALANCE_SHEET["expense_breakdown"]:
            PHINS_BALANCE_SHEET["expense_breakdown"][category] += amount
        PHINS_BALANCE_SHEET["total_expenses"] += amount
        if category == "claims_paid":
            PHINS_BALANCE_SHEET["claims_reserve"] -= amount
        else:
            PHINS_BALANCE_SHEET["operating_reserve"] -= amount

    PHINS_BALANCE_SHEET["last_updated"] = datetime.now().isoformat()

    tx = {
        "tx_id": tx_id,
        "type": tx_type,
        "category": category,
        "amount": amount,
        "description": description,
        "actor": actor,
        "metadata": metadata or {},
        "timestamp": datetime.now().isoformat(),
    }
    PHINS_BALANCE_SHEET["transactions"].append(tx)
    return tx


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def _audit(action: str, actor: str, details: str, resource_id: str = "") -> None:
    AUDIT_LOG.append({
        "id": f"AUD-{uuid.uuid4().hex[:8]}",
        "action": action,
        "actor": actor,
        "details": details,
        "resource_id": resource_id,
        "timestamp": datetime.now().isoformat(),
    })
    if len(AUDIT_LOG) > 10000:
        del AUDIT_LOG[:1000]


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Background video job processor
# ---------------------------------------------------------------------------


def _process_video_job(job_id: str) -> None:
    """Background thread: poll provider and update job status."""
    max_polls = 60
    poll_interval = 5.0

    for _ in range(max_polls):
        time.sleep(poll_interval)

        job = MEDIA_PROCESSING_JOBS.get(job_id)
        if not job:
            return
        if job.get("status") not in {"queued", "processing"}:
            return

        provider = str(job.get("provider") or "").lower()
        provider_job_id = str(job.get("provider_job_id") or "")
        provider_state = job.get("provider_state") or {}

        if not provider_job_id:
            job["status"] = "failed"
            job["message"] = "No provider job ID"
            return

        try:
            svc = get_media_generation_service()
            if svc is None:
                job["status"] = "failed"
                job["message"] = "Media generation service unavailable"
                return

            result = svc.poll_video_generation(
                provider=provider,
                provider_job_id=provider_job_id,
                provider_state=provider_state,
            )
        except Exception as exc:
            job["status"] = "failed"
            job["message"] = str(exc)
            return

        status = result.get("status", "processing")
        job["status"] = status
        job["message"] = result.get("message", "")
        job["provider_state"] = result.get("provider_state", provider_state)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()

        if status == "processing":
            job["progress_pct"] = min(90, int(job.get("progress_pct", 0)) + 10)
            continue

        if status == "failed":
            job["message"] = result.get("error", "Provider reported failure")
            return

        if status == "completed":
            download_url = result.get("download_url", "")
            if not download_url:
                job["status"] = "failed"
                job["message"] = "Completed but no download URL"
                return

            try:
                media_dir = os.environ.get("PHINS_MEDIA_DIR", "")
                if media_dir and os.path.isdir(media_dir):
                    asset_id = f"media-{uuid.uuid4().hex[:12]}"
                    file_path = os.path.join(media_dir, f"{asset_id}.mp4")
                    dl_result = svc.download_generated_video(
                        provider=provider,
                        download_url=download_url,
                        stream_to_path=file_path,
                    )
                    asset_data = ""
                    stored_externally = True
                else:
                    dl_result = svc.download_generated_video(
                        provider=provider,
                        download_url=download_url,
                    )
                    asset_data = dl_result.get("data_url", "")
                    file_path = ""
                    stored_externally = False
                    asset_id = f"media-{uuid.uuid4().hex[:12]}"
            except Exception as dl_exc:
                job["status"] = "failed"
                job["message"] = f"Download failed: {dl_exc}"
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            campaign_id = job.get("campaign_id", "")
            blueprint_index = job.get("blueprint_index", 0)
            asset_name = job.get("asset_name", f"Generated Video {blueprint_index + 1}")

            checksum = ""
            if asset_data and asset_data.startswith("data:") and "," in asset_data:
                try:
                    raw = base64.b64decode(asset_data.split(",", 1)[1])
                    checksum = compute_media_checksum(raw)
                except Exception:
                    pass

            asset = {
                "id": asset_id,
                "name": f"{asset_name}.mp4",
                "type": "video",
                "format": dl_result.get("content_type", "video/mp4"),
                "size": dl_result.get("size", 0),
                "url": download_url,
                "data": asset_data,
                "file_path": file_path if stored_externally else "",
                "stored_externally": stored_externally,
                "thumbnail": "",
                "source": "ai_video_generation",
                "checksum": checksum,
                "uploaded_at": now_iso,
                "uploaded_by": job.get("created_by", "system"),
                "metadata": {
                    "campaign_id": campaign_id,
                    "blueprint_index": blueprint_index,
                    "provider": provider,
                    "provider_model": job.get("provider_model", ""),
                    "provider_job_id": provider_job_id,
                    "job_id": job_id,
                },
            }
            MEDIA_ASSETS[asset_id] = asset

            job["status"] = "completed"
            job["progress_pct"] = 100
            job["generated_asset_id"] = asset_id
            job["download_url"] = f"/api/media/{asset_id}/download"
            job["message"] = "Video generation completed."
            job["updated_at"] = now_iso

            if job.get("auto_publish_to_hero"):
                DESIGN_SETTINGS["hero_video_id"] = asset_id

            return


# ---------------------------------------------------------------------------
# SRT time formatter
# ---------------------------------------------------------------------------


def _srt_time(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    s = int(seconds) % 60
    m = int(seconds) // 60 % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


class PortalHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the PHINS portal."""

    server_version = "PHINS/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def log_error(self, fmt: str, *args: Any) -> None:
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    def _get_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return ""

    def _require_session(self) -> Optional[Dict[str, Any]]:
        token = self._get_token()
        session = validate_session(token)
        if not session:
            self._send_json(401, {"error": "Authentication required"})
            return None
        return session

    def _require_role(self, *roles: str) -> Optional[Dict[str, Any]]:
        session = self._require_session()
        if not session:
            return None
        role = str(session.get("role") or "").lower()
        allowed = {r.lower() for r in roles}
        if role not in allowed:
            self._send_json(403, {"error": "Insufficient permissions"})
            return None
        return session

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in json_security_headers():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, max_size: int = 0) -> Optional[bytes]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            length = 0
        limit = max_size or MAX_REQUEST_SIZE
        if limit > 0 and length > limit:
            self._send_json(413, {"error": "Request body too large"})
            return None
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _parse_json_body(self) -> Optional[Dict[str, Any]]:
        raw = self._read_body()
        if raw is None:
            return None
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON body"})
            return None

    def _parse_query(self) -> Dict[str, List[str]]:
        parsed = urlparse.urlparse(self.path)
        return urlparse.parse_qs(parsed.query, keep_blank_values=True)

    def _path_only(self) -> str:
        return urlparse.urlparse(self.path).path

    @staticmethod
    def _safe_download_filename(name: str, *, fallback: str = "asset") -> str:
        stem = re.sub(r"[^\w\s\-]", "", str(name or ""), flags=re.ASCII)
        stem = re.sub(r"[\s\-]+", "_", stem).strip("_")
        return stem if stem else fallback

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        try:
            cleanup_stale_data()
            path = self._path_only()
            query = self._parse_query()
            token = self._get_token()
            session = validate_session(token) or {}

            if not path.startswith("/api/"):
                self._serve_static(path)
                return

            self._handle_get(path, query, session)
        except Exception:
            try:
                self._send_json(500, {"error": "Internal server error"})
            except Exception:
                pass

    def _handle_get(self, path: str, query: Dict, session: Dict) -> None:
        # Health check
        if path == "/api/health":
            self._send_json(200, {
                "status": "ok",
                "service": "phins",
                "timestamp": datetime.now().isoformat(),
            })
            return

        if path == "/api/login":
            self._send_json(200, {"message": "Use POST /api/login"})
            return

        if path == "/api/profile":
            s = self._require_session()
            if not s:
                return
            username = s.get("username", "")
            user = USERS.get(username) or {}
            self._send_json(200, {
                "username": username,
                "role": s.get("role", ""),
                "name": user.get("name", username),
                "email": user.get("email", ""),
                "customer_id": s.get("customer_id", ""),
            })
            return

        if path == "/api/policies":
            self._handle_get_policies(query, session)
            return

        if path == "/api/underwriting":
            self._handle_get_underwriting(query, session)
            return

        if path == "/api/claims":
            self._handle_get_claims(query, session)
            return

        if path == "/api/customers":
            self._handle_get_customers(query, session)
            return

        if path == "/api/customer/status":
            self._handle_get_customer_status(query, session)
            return

        if path == "/api/billing":
            self._handle_get_billing(query, session)
            return

        if path == "/api/metrics":
            self._handle_get_metrics(query, session)
            return

        if path == "/api/audit":
            s = self._require_session()
            if not s:
                return
            self._handle_get_audit(query, s)
            return

        if path == "/api/security/threats":
            s = self._require_session()
            if not s:
                return
            self._send_json(200, {
                "malicious_attempts": [],
                "blocked_ips": list(BLOCKED_IPS.keys()),
                "failed_logins": dict(FAILED_LOGINS),
                "statistics": {"total_blocked": len(BLOCKED_IPS)},
            })
            return

        if path == "/api/bi/actuary":
            self._handle_bi_actuary(query, session)
            return

        if path == "/api/bi/underwriting":
            self._handle_bi_underwriting(query, session)
            return

        if path == "/api/bi/accounting":
            self._handle_bi_accounting(query, session)
            return

        if path == "/api/bi/executive-dashboard":
            self._handle_bi_executive(query, session)
            return

        if path == "/api/admin/balance-sheet":
            s = self._require_session()
            if not s:
                return
            self._handle_get_balance_sheet(query, s)
            return

        if path == "/api/admin/marketing-sales-agent":
            s = self._require_session()
            if not s:
                return
            self._handle_get_marketing_agent(query, s)
            return

        if path == "/api/admin/marketing-sales-agent/latest":
            s = self._require_session()
            if not s:
                return
            self._handle_get_marketing_agent_latest(query, s)
            return

        if path == "/api/media":
            s = self._require_session()
            if not s:
                return
            self._handle_get_media(query, s)
            return

        if re.match(r"^/api/media/[^/]+$", path):
            asset_id = path.split("/")[-1]
            s = self._require_session()
            if not s:
                return
            self._handle_get_media_asset(asset_id, s)
            return

        if re.match(r"^/api/media/[^/]+/download$", path):
            asset_id = path.split("/")[-2]
            s = self._require_session()
            if not s:
                return
            self._handle_download_media(asset_id, s)
            return

        if re.match(r"^/api/media/[^/]+/subtitles$", path):
            asset_id = path.split("/")[-2]
            s = self._require_session()
            if not s:
                return
            self._handle_get_subtitles(asset_id, query, s)
            return

        if path == "/api/media/subtitles/download":
            s = self._require_session()
            if not s:
                return
            self._handle_download_subtitle(query, s)
            return

        if path == "/api/admin/media/video-jobs":
            s = self._require_session()
            if not s:
                return
            self._handle_get_video_jobs(query, s)
            return

        if path == "/api/admin/media/video-providers":
            s = self._require_session()
            if not s:
                return
            if _VIDEO_AGENTS_AVAILABLE:
                status_code, resp = handle_video_providers(s)
                self._send_json(status_code, resp)
            else:
                kling_enabled = bool(
                    os.environ.get("KLING_API_KEY")
                    or (os.environ.get("KLING_ACCESS_KEY") and os.environ.get("KLING_SECRET_KEY"))
                )
                self._send_json(200, {
                    "success": True,
                    "capabilities": {
                        "providers": {
                            "gemini": {
                                "enabled": bool(os.environ.get("GEMINI_API_KEY")),
                                "label": "Gemini / Veo",
                                "models": ["veo-3.1-generate-preview", "veo-3-fast-preview"],
                            },
                            "kling": {
                                "enabled": kling_enabled,
                                "label": "Kling",
                                "models": ["kling-v2.6-pro", "kling-v2.6-std"],
                            },
                        },
                        "default_provider": "gemini",
                    },
                })
            return

        if path == "/api/admin/media/video-agents/jobs":
            s = self._require_session()
            if not s:
                return
            if _VIDEO_AGENTS_AVAILABLE:
                status_code, resp = handle_list_video_agent_jobs(
                    s, query, MEDIA_PROCESSING_JOBS
                )
                self._send_json(status_code, resp)
            else:
                self._send_json(200, {
                    "success": True,
                    "jobs": [],
                    "summary": {"total": 0, "active": 0, "completed": 0, "failed": 0},
                })
            return

        if re.match(r"^/api/admin/media/video-agents/jobs/[^/]+$", path):
            job_id = path.split("/")[-1]
            s = self._require_session()
            if not s:
                return
            if _VIDEO_AGENTS_AVAILABLE:
                status_code, resp = handle_get_video_agent_job(
                    s, job_id, MEDIA_PROCESSING_JOBS
                )
                self._send_json(status_code, resp)
            else:
                self._send_json(404, {"error": "Job not found"})
            return

        if path == "/api/reinsurance/recommendation":
            s = self._require_session()
            if not s:
                return
            self._handle_reinsurance_recommendation(query, s)
            return

        if path.startswith("/api/actuarial"):
            s = self._require_session()
            if not s:
                return
            self._handle_actuarial_get(path, query, s)
            return

        # Extension dispatchers
        result = _ext_get(path, session, query, self._client_ip())
        if result is not None:
            status_code, resp = result
            self._send_json(status_code, resp)
            return

        self._send_json(404, {"error": f"Not found: {path}"})

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self) -> None:
        try:
            cleanup_stale_data()
            path = self._path_only()
            query = self._parse_query()
            token = self._get_token()
            session = validate_session(token) or {}

            # Multipart upload
            if path == "/api/media/upload" and "multipart/form-data" in self.headers.get(
                "Content-Type", ""
            ):
                s = self._require_session()
                if not s:
                    return
                self._handle_multipart_upload(s)
                return

            body = self._parse_json_body()
            if body is None:
                return

            self._handle_post(path, query, body, session)
        except Exception:
            try:
                self._send_json(500, {"error": "Internal server error"})
            except Exception:
                pass

    def _handle_post(self, path: str, query: Dict, body: Dict, session: Dict) -> None:
        if path == "/api/login":
            self._handle_login(body)
            return

        if path == "/api/logout":
            self._handle_logout(body, session)
            return

        if path == "/api/register":
            self._handle_register(body)
            return

        if path == "/api/policies/create":
            self._handle_create_policy(body, session)
            return

        if path == "/api/underwriting/approve":
            self._handle_underwriting_approve(body, session)
            return

        if path == "/api/underwriting/reject":
            self._handle_underwriting_reject(body, session)
            return

        if path == "/api/claims/create":
            self._handle_create_claim(body, session)
            return

        if path == "/api/claims/approve":
            self._handle_claim_approve(body, session)
            return

        if path == "/api/claims/reject":
            self._handle_claim_reject(body, session)
            return

        if path == "/api/claims/pay":
            self._handle_claim_pay(body, session)
            return

        if path == "/api/billing/create":
            self._handle_billing_create(body, session)
            return

        if path == "/api/billing/pay":
            self._handle_billing_pay(body, session)
            return

        if path == "/api/billing/stats":
            self._handle_billing_stats(body, session)
            return

        if path == "/api/media":
            s = self._require_session()
            if not s:
                return
            self._handle_create_media(body, s)
            return

        if re.match(r"^/api/media/[^/]+/subtitles$", path):
            asset_id = path.split("/")[-2]
            s = self._require_session()
            if not s:
                return
            self._handle_create_subtitle_job(asset_id, body, s)
            return

        if path.startswith("/api/provider/media-processing/callback"):
            self._handle_media_provider_callback(query, body)
            return

        if path == "/api/admin/media/video-jobs":
            s = self._require_session()
            if not s:
                return
            self._handle_create_video_job(body, s)
            return

        if path == "/api/admin/media/video-jobs/batch":
            s = self._require_session()
            if not s:
                return
            self._handle_batch_video_jobs(body, s)
            return

        if path == "/api/admin/media/video-jobs/retry":
            s = self._require_session()
            if not s:
                return
            self._handle_video_job_action("retry", body, s)
            return

        if path == "/api/admin/media/video-jobs/cancel":
            s = self._require_session()
            if not s:
                return
            self._handle_video_job_action("cancel", body, s)
            return

        if path == "/api/admin/media/video-agents/generate":
            s = self._require_session()
            if not s:
                return
            if _VIDEO_AGENTS_AVAILABLE:
                host = self.headers.get("Host", "localhost")
                base_url = f"http://{host}"
                status_code, resp = handle_generate_video_agent(
                    s, body, MEDIA_ASSETS, MEDIA_PROCESSING_JOBS, DESIGN_SETTINGS, base_url
                )
                self._send_json(status_code, resp)
            else:
                self._send_json(503, {"error": "Video agent service not available"})
            return

        if path == "/api/admin/media/video-agents/webhook":
            request_secret = (
                self.headers.get("X-Kling-Webhook-Secret", "")
                or self.headers.get("X-Media-Webhook-Secret", "")
            )
            if _VIDEO_AGENTS_AVAILABLE:
                status_code, resp = handle_video_agent_webhook(
                    body,
                    query,
                    MEDIA_PROCESSING_JOBS,
                    MEDIA_ASSETS,
                    DESIGN_SETTINGS,
                    webhook_secret=MEDIA_PROVIDER_WEBHOOK_SECRET,
                    request_secret=request_secret,
                )
                self._send_json(status_code, resp)
            else:
                self._send_json(200, {"success": True})
            return

        if path.startswith("/api/admin/marketing-sales-agent"):
            s = self._require_session()
            if not s:
                return
            self._handle_marketing_agent_post(path, body, s)
            return

        if path == "/api/actuarial/simulate":
            s = self._require_session()
            if not s:
                return
            self._handle_actuarial_simulate(body, s)
            return

        if path == "/api/reinsurance/contracts/bind":
            s = self._require_session()
            if not s:
                return
            self._handle_reinsurance_bind(body, s)
            return

        # Extension dispatchers
        result = _ext_post(
            path, session, body, self._client_ip(), self.headers.get("User-Agent", "")
        )
        if result is not None:
            status_code, resp = result
            self._send_json(status_code, resp)
            return

        self._send_json(404, {"error": f"Not found: {path}"})

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def do_DELETE(self) -> None:
        try:
            path = self._path_only()
            s = self._require_session()
            if not s:
                return

            if re.match(r"^/api/media/[^/]+$", path):
                asset_id = path.split("/")[-1]
                self._handle_delete_media(asset_id, s)
                return

            self._send_json(404, {"error": "Not found"})
        except Exception:
            self._send_json(500, {"error": "Internal server error"})

    # ------------------------------------------------------------------
    # Static file serving
    # ------------------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"

        safe_path = os.path.normpath(path.lstrip("/"))
        if safe_path.startswith(".."):
            self._send_json(403, {"error": "Forbidden"})
            return

        file_path = os.path.join(ROOT, safe_path)
        if not os.path.isfile(file_path):
            index_path = os.path.join(ROOT, "index.html")
            if os.path.isfile(index_path):
                file_path = index_path
            else:
                self._send_json(404, {"error": "Not found"})
                return

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            for name, value in html_security_headers():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self._send_json(500, {"error": "Failed to serve file"})

    # ------------------------------------------------------------------
    # Login / Auth
    # ------------------------------------------------------------------

    def _handle_login(self, body: Dict) -> None:
        username = str(body.get("username") or "").strip().lower()
        password = str(body.get("password") or "")
        captcha_token = str(body.get("captcha_token") or "").strip()

        if not username or not password:
            self._send_json(400, {"error": "Username and password required"})
            return

        # CAPTCHA check (skip in test mode)
        if not PHINS_TEST_MODE:
            if not captcha_token:
                self._send_json(
                    400,
                    {"error": "CAPTCHA verification required. Please reload and try again."},
                )
                return
            if _OTP_AVAILABLE and get_otp_security_service is not None:
                try:
                    otp_svc = get_otp_security_service()
                    with otp_svc._lock:
                        challenge = otp_svc._challenges.get(captcha_token)
                        if not challenge or not challenge.verified:
                            self._send_json(
                                400,
                                {"error": "CAPTCHA verification required. Please reload and try again."},
                            )
                            return
                        if challenge.expires_at < datetime.now():
                            self._send_json(
                                400,
                                {"error": "CAPTCHA verification required. Please reload and try again."},
                            )
                            return
                        del otp_svc._challenges[captcha_token]
                except RuntimeError:
                    self._send_json(
                        503, {"error": "CAPTCHA validation unavailable. Please try again."}
                    )
                    return
                except Exception:
                    self._send_json(
                        503, {"error": "CAPTCHA validation unavailable. Please try again."}
                    )
                    return

        # Find user
        user = USERS.get(username)
        if not user:
            for email, cust in REGISTERED_CUSTOMERS.items():
                if email.lower() == username or cust.get("username", "").lower() == username:
                    user = cust
                    break

        if not user:
            with STATE_LOCK:
                FAILED_LOGINS[username] = FAILED_LOGINS.get(username, 0) + 1
            self._send_json(401, {"error": "Invalid credentials"})
            return

        # Verify password
        password_data = user.get("password_data") or {}
        if password_data:
            if not _verify_password(password, password_data):
                with STATE_LOCK:
                    FAILED_LOGINS[username] = FAILED_LOGINS.get(username, 0) + 1
                self._send_json(401, {"error": "Invalid credentials"})
                return
        else:
            stored_pw = user.get("password", "")
            if stored_pw and password != stored_pw:
                self._send_json(401, {"error": "Invalid credentials"})
                return

        role = str(user.get("role") or "customer")
        customer_id = str(user.get("customer_id") or user.get("id") or "")
        token = _mint_token(username, role, customer_id)

        expires = (datetime.now() + timedelta(hours=_TOKEN_TTL_HOURS)).isoformat()
        session_data: Dict[str, Any] = {
            "username": username,
            "role": role,
            "customer_id": customer_id,
            "expires": expires,
            "name": user.get("name", username),
            "email": user.get("email", ""),
        }

        if _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None and token.startswith("phins2_"):
            try:
                claims = _auth_tokens_module.verify_v2_token(token)
                if claims:
                    session_data["jti"] = claims.jti
            except Exception:
                pass

        with STATE_LOCK:
            SESSIONS[token] = session_data
            FAILED_LOGINS.pop(username, None)

        _audit("login", username, f"Login from {self._client_ip()}")

        self._send_json(200, {
            "token": token,
            "username": username,
            "role": role,
            "name": user.get("name", username),
            "customer_id": customer_id,
        })

    def _handle_logout(self, body: Dict, session: Dict) -> None:
        token = self._get_token()
        if token:
            jti = session.get("jti")
            if jti and _AUTH_TOKENS_AVAILABLE and _auth_tokens_module is not None:
                try:
                    _auth_tokens_module.revoke_token(jti, time.time() + 86400)
                except Exception:
                    pass
            with STATE_LOCK:
                SESSIONS.pop(token, None)
        self._send_json(200, {"success": True})

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _handle_register(self, body: Dict) -> None:
        name = str(body.get("name") or "").strip()
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        phone = str(body.get("phone") or "").strip()
        dob = str(body.get("dob") or "").strip()
        invitation_code = str(body.get("invitation_code") or "").strip()

        if not name:
            self._send_json(400, {"error": "Name is required"})
            return
        if not email or "@" not in email:
            self._send_json(400, {"error": "Valid email is required"})
            return
        if not password or len(password) < 8:
            self._send_json(400, {"error": "Password must be at least 8 characters"})
            return
        if not invitation_code:
            self._send_json(400, {"error": "Invitation code is required"})
            return

        invite = INVITATION_CODES.get(invitation_code)
        if not invite:
            self._send_json(400, {"error": "Invalid invitation code", "code": "CODE_INVALID"})
            return
        if invite.get("status") == "used" and invite.get("used_count", 0) >= invite.get("max_uses", 1):
            self._send_json(400, {"error": "Invitation code has already been used", "code": "CODE_USED"})
            return
        if invite.get("status") not in {"active", "used"}:
            self._send_json(400, {"error": "Invitation code is not active", "code": "CODE_INACTIVE"})
            return

        if email in USERS or email in REGISTERED_CUSTOMERS:
            self._send_json(409, {"error": "Email already registered"})
            return

        customer_id = _new_id("CUST")
        now_iso = datetime.now().isoformat()

        customer = {
            "id": customer_id,
            "customer_id": customer_id,
            "name": name,
            "email": email,
            "phone": phone,
            "dob": dob,
            "status": "active",
            "created_at": now_iso,
            "role": "customer",
            "username": email,
        }

        user_record = {
            "username": email,
            "password_data": _hash_password(password),
            "role": "customer",
            "name": name,
            "email": email,
            "customer_id": customer_id,
            "id": customer_id,
        }

        with STATE_LOCK:
            CUSTOMERS[customer_id] = customer
            REGISTERED_CUSTOMERS[email] = customer
            USERS[email] = user_record
            invite["used_count"] = invite.get("used_count", 0) + 1
            if invite["used_count"] >= invite.get("max_uses", 1):
                invite["status"] = "used"

        _audit("register", email, f"Customer registered: {name}")

        self._send_json(201, {
            "success": True,
            "customer_id": customer_id,
            "email": email,
            "name": name,
        })

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------

    def _handle_get_policies(self, query: Dict, session: Dict) -> None:
        policy_id = str((query.get("id") or [""])[0]).strip()
        if policy_id:
            policy = POLICIES.get(policy_id)
            if not policy:
                self._send_json(404, {"error": "Policy not found"})
                return
            self._send_json(200, policy)
            return

        page = max(1, int((query.get("page") or ["1"])[0]))
        page_size = max(1, min(100, int((query.get("page_size") or ["20"])[0])))
        items = list(POLICIES.values())
        total = len(items)
        start = (page - 1) * page_size
        self._send_json(200, {
            "items": items[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
        })

    def _handle_create_policy(self, body: Dict, session: Dict) -> None:
        customer_name = str(body.get("customer_name") or "").strip()
        customer_email = str(body.get("customer_email") or "").strip().lower()
        policy_type = str(body.get("type") or "life").strip().lower()
        coverage_amount = safe_float(body.get("coverage_amount"), 0.0)
        risk_score = str(body.get("risk_score") or "medium").strip().lower()
        age = int(body.get("age") or 35)

        if not customer_name:
            self._send_json(400, {"error": "customer_name is required"})
            return
        if coverage_amount <= 0 or coverage_amount > 100_000_000:
            self._send_json(400, {"error": "Invalid coverage_amount"})
            return

        customer_id = _new_id("CUST")
        if customer_email:
            for cid, cust in CUSTOMERS.items():
                if cust.get("email", "").lower() == customer_email:
                    customer_id = cid
                    break

        now_iso = datetime.now().isoformat()
        customer = CUSTOMERS.get(customer_id) or {
            "id": customer_id,
            "name": customer_name,
            "email": customer_email,
            "phone": str(body.get("customer_phone") or ""),
            "status": "active",
            "created_at": now_iso,
        }
        CUSTOMERS[customer_id] = customer

        base_premium = coverage_amount * 0.005
        risk_multipliers = {"low": 0.8, "medium": 1.0, "high": 1.3, "very_high": 1.6}
        multiplier = risk_multipliers.get(risk_score, 1.0)
        annual_premium = round(base_premium * multiplier, 2)
        monthly_premium = round(annual_premium / 12, 2)

        policy_id = _new_id("POL")
        policy = {
            "id": policy_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "type": policy_type,
            "coverage_amount": coverage_amount,
            "annual_premium": annual_premium,
            "monthly_premium": monthly_premium,
            "risk_score": risk_score,
            "status": "pending_underwriting",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        POLICIES[policy_id] = policy

        uw_id = _new_id("UW")
        uw_app = {
            "id": uw_id,
            "policy_id": policy_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "type": policy_type,
            "coverage_amount": coverage_amount,
            "risk_score": risk_score,
            "age": age,
            "status": "pending",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        UNDERWRITING_APPLICATIONS[uw_id] = uw_app

        temp_password = secrets.token_urlsafe(8)
        provisioned_login = {
            "username": customer_email or customer_id,
            "temp_password": temp_password,
            "note": "Change password on first login",
        }

        _audit(
            "policy_create",
            session.get("username", "system"),
            f"Policy {policy_id} created for {customer_name}",
        )

        self._send_json(201, {
            "policy": policy,
            "customer": customer,
            "underwriting": uw_app,
            "provisioned_login": provisioned_login,
        })

    # ------------------------------------------------------------------
    # Underwriting
    # ------------------------------------------------------------------

    def _handle_get_underwriting(self, query: Dict, session: Dict) -> None:
        self._send_json(200, list(UNDERWRITING_APPLICATIONS.values()))

    def _handle_underwriting_approve(self, body: Dict, session: Dict) -> None:
        uw_id = str(body.get("id") or "").strip()
        if not uw_id:
            self._send_json(400, {"error": "id is required"})
            return
        app = UNDERWRITING_APPLICATIONS.get(uw_id)
        if not app:
            self._send_json(404, {"error": "Underwriting application not found"})
            return

        now_iso = datetime.now().isoformat()
        app["status"] = "approved"
        app["approved_by"] = str(
            body.get("approved_by") or session.get("username") or "underwriter"
        )
        app["approved_at"] = now_iso
        app["updated_at"] = now_iso

        policy = POLICIES.get(app.get("policy_id", ""))
        if policy:
            policy["status"] = "active"
            policy["updated_at"] = now_iso

        self._send_json(200, {"success": True, "application": app})

    def _handle_underwriting_reject(self, body: Dict, session: Dict) -> None:
        uw_id = str(body.get("id") or "").strip()
        if not uw_id:
            self._send_json(400, {"error": "id is required"})
            return
        app = UNDERWRITING_APPLICATIONS.get(uw_id)
        if not app:
            self._send_json(404, {"error": "Underwriting application not found"})
            return

        now_iso = datetime.now().isoformat()
        app["status"] = "rejected"
        app["rejection_reason"] = str(body.get("reason") or "Rejected by underwriter")
        app["rejected_by"] = str(
            body.get("rejected_by") or session.get("username") or "underwriter"
        )
        app["rejected_at"] = now_iso
        app["updated_at"] = now_iso

        policy = POLICIES.get(app.get("policy_id", ""))
        if policy:
            policy["status"] = "rejected"
            policy["updated_at"] = now_iso

        self._send_json(200, {"success": True, "application": app})

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def _handle_get_claims(self, query: Dict, session: Dict) -> None:
        status_filter = str((query.get("status") or [""])[0]).strip().lower()
        page = max(1, int((query.get("page") or ["1"])[0]))
        page_size = max(1, min(100, int((query.get("page_size") or ["20"])[0])))

        items = list(CLAIMS.values())
        if status_filter:
            items = [c for c in items if c.get("status", "").lower() == status_filter]

        total = len(items)
        start = (page - 1) * page_size
        self._send_json(200, {
            "items": items[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
        })

    def _handle_create_claim(self, body: Dict, session: Dict) -> None:
        policy_id = str(body.get("policy_id") or "").strip()
        customer_id = str(body.get("customer_id") or "").strip()
        claim_type = str(body.get("type") or "general").strip()
        description = str(body.get("description") or "").strip()
        claimed_amount = safe_float(body.get("claimed_amount"), 0.0)

        if not policy_id:
            self._send_json(400, {"error": "policy_id is required"})
            return

        claim_id = _new_id("CLM")
        now_iso = datetime.now().isoformat()
        claim = {
            "id": claim_id,
            "policy_id": policy_id,
            "customer_id": customer_id,
            "type": claim_type,
            "description": description,
            "claimed_amount": claimed_amount,
            "approved_amount": 0.0,
            "paid_amount": 0.0,
            "status": "pending",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        CLAIMS[claim_id] = claim
        self._send_json(201, claim)

    def _handle_claim_approve(self, body: Dict, session: Dict) -> None:
        claim_id = str(body.get("id") or "").strip()
        if not claim_id:
            self._send_json(400, {"error": "id is required"})
            return
        claim = CLAIMS.get(claim_id)
        if not claim:
            self._send_json(404, {"error": "Claim not found"})
            return

        now_iso = datetime.now().isoformat()
        claim["status"] = "approved"
        claim["approved_amount"] = safe_float(
            body.get("approved_amount"), claim.get("claimed_amount", 0.0)
        )
        claim["approved_by"] = str(
            body.get("approved_by") or session.get("username") or "adjuster"
        )
        claim["approved_at"] = now_iso
        claim["notes"] = str(body.get("notes") or "")
        claim["updated_at"] = now_iso

        self._send_json(200, {"success": True, "claim": claim})

    def _handle_claim_reject(self, body: Dict, session: Dict) -> None:
        claim_id = str(body.get("id") or "").strip()
        if not claim_id:
            self._send_json(400, {"error": "id is required"})
            return
        claim = CLAIMS.get(claim_id)
        if not claim:
            self._send_json(404, {"error": "Claim not found"})
            return

        now_iso = datetime.now().isoformat()
        claim["status"] = "rejected"
        claim["rejection_reason"] = str(body.get("reason") or "Rejected")
        claim["rejected_by"] = str(
            body.get("rejected_by") or session.get("username") or "adjuster"
        )
        claim["rejected_at"] = now_iso
        claim["updated_at"] = now_iso

        self._send_json(200, {"success": True, "claim": claim})

    def _handle_claim_pay(self, body: Dict, session: Dict) -> None:
        claim_id = str(body.get("id") or "").strip()
        if not claim_id:
            self._send_json(400, {"error": "id is required"})
            return
        claim = CLAIMS.get(claim_id)
        if not claim:
            self._send_json(404, {"error": "Claim not found"})
            return

        now_iso = datetime.now().isoformat()
        paid_amount = safe_float(
            claim.get("approved_amount"), claim.get("claimed_amount", 0.0)
        )
        claim["status"] = "paid"
        claim["paid_amount"] = paid_amount
        claim["payment_reference"] = f"PAY-{uuid.uuid4().hex[:8].upper()}"
        claim["payment_method"] = str(body.get("payment_method") or "bank_transfer")
        claim["processed_by"] = str(
            body.get("processed_by") or session.get("username") or "accountant"
        )
        claim["paid_at"] = now_iso
        claim["updated_at"] = now_iso

        _record_balance_sheet_transaction(
            "expense", "claims_paid", paid_amount, f"Claim {claim_id} paid"
        )

        self._send_json(200, {"success": True, "claim": claim})

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------

    def _handle_get_billing(self, query: Dict, session: Dict) -> None:
        items = list(BILLING.values())
        self._send_json(200, {"items": items, "total": len(items)})

    def _handle_billing_create(self, body: Dict, session: Dict) -> None:
        policy_id = str(body.get("policy_id") or "").strip()
        amount_due = safe_float(body.get("amount_due"), 0.0)
        due_days = int(body.get("due_days") or 30)

        if not policy_id:
            self._send_json(400, {"error": "policy_id is required"})
            return

        policy = POLICIES.get(policy_id) or {}
        customer_id = str(policy.get("customer_id") or "")

        bill_id = _new_id("BILL")
        now_iso = datetime.now().isoformat()
        due_date = (datetime.now() + timedelta(days=due_days)).isoformat()

        bill = {
            "id": bill_id,
            "bill_id": bill_id,
            "policy_id": policy_id,
            "customer_id": customer_id,
            "amount": amount_due,
            "amount_due": amount_due,
            "amount_paid": 0.0,
            "due_date": due_date,
            "status": "outstanding",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        BILLING[bill_id] = bill
        self._send_json(201, {"bill": bill})

    def _handle_billing_pay(self, body: Dict, session: Dict) -> None:
        bill_id = str(body.get("bill_id") or "").strip()
        amount = safe_float(body.get("amount"), 0.0)

        if not bill_id:
            self._send_json(400, {"error": "bill_id is required"})
            return

        bill = BILLING.get(bill_id)
        if not bill:
            self._send_json(404, {"error": "Bill not found"})
            return

        now_iso = datetime.now().isoformat()
        bill["amount_paid"] = round(bill.get("amount_paid", 0.0) + amount, 2)
        bill["updated_at"] = now_iso

        if bill["amount_paid"] >= bill.get("amount_due", 0.0):
            bill["status"] = "paid"
            bill["paid_at"] = now_iso
            _record_balance_sheet_transaction(
                "revenue", "premium_income", amount, f"Bill {bill_id} paid"
            )
        else:
            bill["status"] = "partial"

        self._send_json(200, {"bill": bill})

    def _handle_billing_stats(self, body: Dict, session: Dict) -> None:
        bills = list(BILLING.values())
        total_transactions = len(bills)
        successful = sum(
            1 for b in bills
            if status_in(b, ["paid", "partial"])
            and not is_suspended_account(b.get("customer_id", ""))
        )
        failed = sum(
            1 for b in bills
            if status_eq(b, "failed")
            and not is_suspended_account(b.get("customer_id", ""))
        )
        total_revenue = round(
            sum(
                safe_float(p.get("annual_premium"), 0.0)
                for p in POLICIES.values()
                if status_eq(p, "active")
                and not is_suspended_account(p.get("customer_id", ""))
            ),
            2,
        )

        self._send_json(200, {
            "total_transactions": total_transactions,
            "successful_payments": successful,
            "failed_payments": failed,
            "total_revenue": total_revenue,
        })

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def _handle_get_customers(self, query: Dict, session: Dict) -> None:
        self._send_json(200, list(CUSTOMERS.values()))

    def _handle_get_customer_status(self, query: Dict, session: Dict) -> None:
        customer_id = str((query.get("customer_id") or [""])[0]).strip()
        if not customer_id:
            self._send_json(400, {"error": "customer_id is required"})
            return

        customer = CUSTOMERS.get(customer_id)
        if not customer:
            self._send_json(404, {"error": "Customer not found"})
            return

        policies = [p for p in POLICIES.values() if p.get("customer_id") == customer_id]
        uw_apps = [
            u for u in UNDERWRITING_APPLICATIONS.values()
            if u.get("customer_id") == customer_id
        ]
        claims = [c for c in CLAIMS.values() if c.get("customer_id") == customer_id]
        active_policies = [p for p in policies if status_eq(p, "active")]
        overall_status = "active" if active_policies else "pending"

        self._send_json(200, {
            "customer": customer,
            "overall_status": overall_status,
            "policies": policies,
            "underwriting_applications": uw_apps,
            "claims": claims,
        })

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _handle_get_metrics(self, query: Dict, session: Dict) -> None:
        try:
            if _METRICS_AVAILABLE and MetricsService is not None:
                svc = MetricsService(POLICIES, CLAIMS, BILLING)
                metrics = svc.summary()
            else:
                raise RuntimeError("metrics service unavailable")
        except Exception:
            metrics = {
                "policies": {
                    "total": len(POLICIES),
                    "active": sum(1 for p in POLICIES.values() if status_eq(p, "active")),
                },
                "claims": {
                    "pending": sum(
                        1 for c in CLAIMS.values()
                        if status_in(c, ["pending", "under_review"])
                        and not is_suspended_account(c.get("customer_id", ""))
                    ),
                    "approved": sum(
                        1 for c in CLAIMS.values() if status_eq(c, "approved")
                    ),
                },
                "billing": {
                    "overdue": sum(
                        1 for b in BILLING.values() if status_eq(b, "overdue")
                    ),
                    "outstanding": sum(
                        1 for b in BILLING.values()
                        if status_in(b, ["outstanding", "partial"])
                        and not is_suspended_account(b.get("customer_id", ""))
                    ),
                },
            }

        self._send_json(200, {"metrics": metrics, "ts": datetime.now().isoformat()})

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _handle_get_audit(self, query: Dict, session: Dict) -> None:
        page = max(1, int((query.get("page") or ["1"])[0]))
        page_size = max(1, min(100, int((query.get("page_size") or ["20"])[0])))
        items = list(reversed(AUDIT_LOG))
        total = len(items)
        start = (page - 1) * page_size
        self._send_json(200, {
            "items": items[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
        })

    # ------------------------------------------------------------------
    # BI endpoints
    # ------------------------------------------------------------------

    def _handle_bi_actuary(self, query: Dict, session: Dict) -> None:
        policies = list(POLICIES.values())
        active = [p for p in policies if status_eq(p, "active")]
        total_exposure = sum(safe_float(p.get("coverage_amount"), 0) for p in active)
        avg_premium = (
            sum(safe_float(p.get("annual_premium"), 0) for p in active) / len(active)
            if active
            else 0
        )
        claims_list = list(CLAIMS.values())
        paid_claims = sum(
            safe_float(c.get("paid_amount"), 0)
            for c in claims_list
            if status_eq(c, "paid")
        )
        total_premium = sum(safe_float(p.get("annual_premium"), 0) for p in active)
        claims_ratio = round(paid_claims / total_premium, 4) if total_premium > 0 else 0

        reinsurance_expense = safe_float(
            PHINS_BALANCE_SHEET.get("expense_breakdown", {}).get("reinsurance"), 0
        )
        latest_sim = (
            max(
                ACTUARIAL_SIMULATIONS.values(),
                key=lambda s: s.get("created_at", ""),
                default={},
            )
            if ACTUARIAL_SIMULATIONS
            else {}
        )

        self._send_json(200, {
            "total_policies": len(policies),
            "active_policies": len(active),
            "total_exposure": total_exposure,
            "average_premium": round(avg_premium, 2),
            "risk_distribution": {"low": 0, "medium": 0, "high": 0},
            "claims_ratio": claims_ratio,
            "reinsurance": {
                "annual_expense_booked": reinsurance_expense,
                "latest_program": latest_sim.get("reinsurance_program", {}),
            },
        })

    def _handle_bi_underwriting(self, query: Dict, session: Dict) -> None:
        apps = list(UNDERWRITING_APPLICATIONS.values())
        pending = [a for a in apps if status_eq(a, "pending")]
        approved = [a for a in apps if status_eq(a, "approved")]
        rejected = [a for a in apps if status_eq(a, "rejected")]
        rejection_rate = round(len(rejected) / len(apps), 4) if apps else 0

        self._send_json(200, {
            "pending_applications": len(pending),
            "approved_this_month": len(approved),
            "rejection_rate": rejection_rate,
            "risk_assessment_distribution": {"low": 0, "medium": 0, "high": 0},
        })

    def _handle_bi_accounting(self, query: Dict, session: Dict) -> None:
        total_revenue = safe_float(PHINS_BALANCE_SHEET.get("total_revenue"), 0)
        total_expenses = safe_float(PHINS_BALANCE_SHEET.get("total_expenses"), 0)
        net_income = total_revenue - total_expenses
        profit_margin = round(net_income / total_revenue, 4) if total_revenue > 0 else 0

        self._send_json(200, {
            "total_revenue": total_revenue,
            "total_claims_paid": safe_float(
                PHINS_BALANCE_SHEET.get("expense_breakdown", {}).get("claims_paid"), 0
            ),
            "net_income": net_income,
            "profit_margin": profit_margin,
            "monthly_breakdown": [],
        })

    def _handle_bi_executive(self, query: Dict, session: Dict) -> None:
        self._send_json(200, {
            "total_customers": len(CUSTOMERS),
            "total_policies": len(POLICIES),
            "total_claims": len(CLAIMS),
            "total_revenue": safe_float(PHINS_BALANCE_SHEET.get("total_revenue"), 0),
        })

    # ------------------------------------------------------------------
    # Balance sheet
    # ------------------------------------------------------------------

    def _handle_get_balance_sheet(self, query: Dict, session: Dict) -> None:
        bs = dict(PHINS_BALANCE_SHEET)

        cumulative_from_bills = sum(
            safe_float(b.get("amount_paid"), 0)
            for b in BILLING.values()
            if status_in(b, ["paid", "partial"])
        )
        cumulative_from_ledger = safe_float(
            bs.get("revenue_breakdown", {}).get("premium_income"), 0
        )
        cumulative_premium = max(cumulative_from_bills, cumulative_from_ledger)

        bs["cumulative_premium"] = cumulative_premium
        bs.setdefault("revenue_breakdown", {})["premium_income"] = cumulative_premium
        bs["cumulative_premium_breakdown"] = {
            "from_bills": cumulative_from_bills,
            "from_ledger": cumulative_from_ledger,
        }

        self._send_json(200, {"balance_sheet": bs})

    # ------------------------------------------------------------------
    # Marketing sales agent
    # ------------------------------------------------------------------

    def _handle_get_marketing_agent(self, query: Dict, session: Dict) -> None:
        if not _MARKETING_AGENT_AVAILABLE or get_marketing_sales_agent_service is None:
            self._send_json(503, {"error": "Marketing agent service not available"})
            return

        vertical = str((query.get("vertical") or ["insurance"])[0])
        objective = str((query.get("objective") or ["growth"])[0])
        persona = str((query.get("persona") or ["families"])[0])
        region = str((query.get("region") or ["global"])[0])
        budget_tier = str((query.get("budget_tier") or ["balanced"])[0])
        networks_raw = str((query.get("networks") or ["linkedin,x"])[0])
        networks = [n.strip() for n in networks_raw.split(",") if n.strip()]

        svc = get_marketing_sales_agent_service()
        generated = svc.generate_campaign(
            vertical=vertical,
            objective=objective,
            persona=persona,
            region=region,
            budget_tier=budget_tier,
            social_networks=networks,
            generated_by=session.get("username", "admin"),
            customers=CUSTOMERS,
            policies=POLICIES,
            billing=BILLING,
            claims=CLAIMS,
            health_wallets=HEALTH_WALLETS,
            investment_accounts=INVESTMENT_ACCOUNTS,
            transaction_ledger=TRANSACTION_LEDGER,
        )

        latest_entry = {
            "campaign": generated["campaign"],
            "integrity": generated["integrity"],
            "assets_created": [],
            "lifecycle_status": "generated",
        }
        DESIGN_SETTINGS.setdefault("marketing_sales_agent", {})
        DESIGN_SETTINGS["marketing_sales_agent"]["latest_campaign"] = latest_entry

        self._send_json(200, {
            "success": True,
            "generated": generated,
            "latest_campaign": latest_entry,
        })

    def _handle_get_marketing_agent_latest(self, query: Dict, session: Dict) -> None:
        msa = DESIGN_SETTINGS.get("marketing_sales_agent") or {}
        latest = msa.get("latest_campaign")
        if not latest:
            self._send_json(404, {"error": "No generated campaign found"})
            return

        campaign_id = str(latest.get("campaign", {}).get("campaign_id") or "")
        summary = _video_job_summary(campaign_id)

        self._send_json(200, {
            "success": True,
            "latest_campaign": latest,
            "video_job_summary": summary,
        })

    def _handle_marketing_agent_post(self, path: str, body: Dict, session: Dict) -> None:
        self._send_json(200, {"success": True, "message": "Marketing agent action processed"})

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def _handle_get_media(self, query: Dict, session: Dict) -> None:
        assets = [serialize_media_asset(a) for a in MEDIA_ASSETS.values()]
        self._send_json(200, {"assets": assets, "total": len(assets)})

    def _handle_get_media_asset(self, asset_id: str, session: Dict) -> None:
        asset = MEDIA_ASSETS.get(asset_id)
        if not asset:
            self._send_json(404, {"error": "Asset not found"})
            return

        result = serialize_media_asset(asset)

        jobs = [
            j for j in MEDIA_PROCESSING_JOBS.values()
            if j.get("asset_id") == asset_id
        ]
        subtitle_jobs = [j for j in jobs if j.get("job_kind") == "subtitle"]
        subtitle_status = subtitle_jobs[0].get("status", "") if subtitle_jobs else ""

        result["processing"] = {"subtitle_status": subtitle_status}
        result["subtitles"] = [
            {
                "format": "srt",
                "language": j.get("language", "en"),
                "download_url": f"/api/media/subtitles/download?job_id={j['id']}",
            }
            for j in subtitle_jobs
            if j.get("status") == "completed"
        ]

        self._send_json(200, result)

    def _handle_create_media(self, body: Dict, session: Dict) -> None:
        name = str(body.get("name") or "").strip()
        asset_type = str(body.get("type") or "").strip().lower()
        asset_format = str(body.get("format") or "").strip()
        size = int(body.get("size") or 0)
        url = str(body.get("url") or "").strip()
        data = str(body.get("data") or "").strip()
        source = str(body.get("source") or "upload").strip()
        duration = int(body.get("duration") or 0)

        if not name:
            self._send_json(400, {"error": "name is required"})
            return
        if asset_type not in {"video", "image", "audio", "document", "text"}:
            self._send_json(400, {"error": "type must be one of: video, image, audio, document, text"})
            return
        if not url and not data:
            self._send_json(400, {"error": "Either data or url is required"})
            return

        asset_id = f"media-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        checksum = ""
        if data and data.startswith("data:") and "," in data:
            try:
                raw = base64.b64decode(data.split(",", 1)[1])
                checksum = compute_media_checksum(raw)
                if not size:
                    size = len(raw)
            except Exception:
                pass

        asset = {
            "id": asset_id,
            "name": name,
            "type": asset_type,
            "format": asset_format,
            "size": size,
            "url": url,
            "data": data,
            "thumbnail": "",
            "source": source,
            "duration": duration,
            "checksum": checksum,
            "uploaded_at": now_iso,
            "uploaded_by": session.get("username", "admin"),
            "metadata": body.get("metadata") or {},
        }
        MEDIA_ASSETS[asset_id] = asset
        self._send_json(201, {"asset": serialize_media_asset(asset)})

    def _handle_delete_media(self, asset_id: str, session: Dict) -> None:
        asset = MEDIA_ASSETS.get(asset_id)
        if not asset:
            self._send_json(404, {"error": "Asset not found"})
            return

        file_path = asset.get("file_path", "")
        if file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

        job_ids = [
            jid for jid, j in MEDIA_PROCESSING_JOBS.items()
            if j.get("asset_id") == asset_id
        ]
        for jid in job_ids:
            MEDIA_PROCESSING_JOBS.pop(jid, None)

        del MEDIA_ASSETS[asset_id]
        self._send_json(200, {"id": asset_id, "success": True})

    def _handle_download_media(self, asset_id: str, session: Dict) -> None:
        asset = MEDIA_ASSETS.get(asset_id)
        if not asset:
            self._send_json(404, {"error": "Asset not found"})
            return

        name = str(asset.get("name") or "asset")
        stem = self._safe_download_filename(os.path.splitext(name)[0])
        ext = os.path.splitext(name)[1] or ".bin"
        content_type = str(asset.get("format") or "application/octet-stream")

        file_path = asset.get("file_path", "")
        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                safe_name = f"{stem}{ext}".replace('"', "")
                self._send_raw(
                    200,
                    content,
                    content_type,
                    {"Content-Disposition": f'attachment; filename="{safe_name}"'},
                )
                return
            except Exception:
                self._send_json(500, {"error": "Failed to read file"})
                return

        data = str(asset.get("data") or "")
        if data.startswith("data:") and "," in data:
            try:
                header, encoded = data.split(",", 1)
                ct = header[5:].split(";")[0].strip() or content_type
                raw = base64.b64decode(encoded)
                safe_ext = re.sub(r"[^a-zA-Z0-9]", "_", ct.split("/")[-1])[:10]
                safe_name = f"{stem}_{safe_ext}{ext}".replace('"', "")
                self._send_raw(
                    200,
                    raw,
                    ct,
                    {"Content-Disposition": f'attachment; filename="{safe_name}"'},
                )
                return
            except Exception:
                self._send_json(500, {"error": "Failed to decode asset"})
                return

        self._send_json(404, {"error": "Asset has no downloadable content"})

    def _handle_multipart_upload(self, session: Dict) -> None:
        content_type = self.headers.get("Content-Type", "")
        boundary_match = re.search(r"boundary=([^\s;]+)", content_type)
        if not boundary_match:
            self._send_json(400, {"error": "Missing multipart boundary"})
            return

        boundary = boundary_match.group(1).encode()
        max_size = MAX_MEDIA_UPLOAD_SIZE if MAX_MEDIA_UPLOAD_SIZE > 0 else 500 * 1024 * 1024
        raw = self._read_body(max_size)
        if raw is None:
            return

        fields: Dict[str, str] = {}
        file_data: Optional[bytes] = None
        file_name = ""
        file_content_type = "application/octet-stream"

        parts = raw.split(b"--" + boundary)
        for part in parts[1:]:
            if part.startswith(b"--"):
                break
            if b"\r\n\r\n" not in part:
                continue
            header_section, body_section = part.split(b"\r\n\r\n", 1)
            body_section = body_section.rstrip(b"\r\n")
            headers_text = header_section.decode("utf-8", errors="replace")

            cd_match = re.search(
                r'Content-Disposition:[^\r\n]*name="([^"]+)"', headers_text, re.IGNORECASE
            )
            fn_match = re.search(
                r'Content-Disposition:[^\r\n]*filename="([^"]+)"', headers_text, re.IGNORECASE
            )
            ct_match = re.search(r"Content-Type:\s*([^\r\n]+)", headers_text, re.IGNORECASE)

            if fn_match:
                file_name = fn_match.group(1)
                file_data = body_section
                if ct_match:
                    file_content_type = ct_match.group(1).strip()
            elif cd_match:
                field_name = cd_match.group(1)
                fields[field_name] = body_section.decode("utf-8", errors="replace")

        if file_data is None:
            self._send_json(400, {"error": "No file in upload"})
            return

        name = fields.get("name") or file_name or "upload"
        asset_type = fields.get("type") or "video"
        source = fields.get("source") or "upload"

        asset_id = f"media-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        checksum = compute_media_checksum(file_data)

        media_dir = os.environ.get("PHINS_MEDIA_DIR", "")
        file_path = ""
        stored_externally = False
        if media_dir and os.path.isdir(media_dir):
            ext = os.path.splitext(file_name)[1] or ".bin"
            file_path = os.path.join(media_dir, f"{asset_id}{ext}")
            try:
                with open(file_path, "wb") as f:
                    f.write(file_data)
                stored_externally = True
            except Exception:
                file_path = ""

        asset = {
            "id": asset_id,
            "name": name,
            "type": asset_type,
            "format": file_content_type,
            "size": len(file_data),
            "url": f"/media-files/{asset_id}/{file_name}" if stored_externally else "",
            "data": (
                ""
                if stored_externally
                else f"data:{file_content_type};base64,{base64.b64encode(file_data).decode()}"
            ),
            "file_path": file_path,
            "stored_externally": stored_externally,
            "thumbnail": "",
            "source": source,
            "checksum": checksum,
            "uploaded_at": now_iso,
            "uploaded_by": session.get("username", "admin"),
        }
        MEDIA_ASSETS[asset_id] = asset
        self._send_json(201, {"asset": serialize_media_asset(asset)})

    # ------------------------------------------------------------------
    # Subtitle jobs
    # ------------------------------------------------------------------

    def _handle_create_subtitle_job(self, asset_id: str, body: Dict, session: Dict) -> None:
        asset = MEDIA_ASSETS.get(asset_id)
        if not asset:
            self._send_json(404, {"error": "Asset not found"})
            return

        job_id = f"sub-{uuid.uuid4().hex[:12]}"
        provider = str(body.get("provider") or "bridge").strip()
        language = str(body.get("language") or "en").strip()
        provider_job_id = f"prov-{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        callback_path = (
            f"/api/provider/media-processing/callback"
            f"?job_id={job_id}&token={secrets.token_urlsafe(8)}"
        )
        host = self.headers.get("Host", "localhost")
        callback_url = f"http://{host}{callback_path}"

        job = {
            "id": job_id,
            "job_kind": "subtitle",
            "asset_id": asset_id,
            "provider": provider,
            "provider_job_id": provider_job_id,
            "language": language,
            "status": "queued",
            "callback_path": callback_path,
            "callback_url": callback_url,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        MEDIA_PROCESSING_JOBS[job_id] = job
        self._send_json(202, {"subtitle_job": job})

    def _handle_get_subtitles(self, asset_id: str, query: Dict, session: Dict) -> None:
        jobs = [
            j for j in MEDIA_PROCESSING_JOBS.values()
            if j.get("asset_id") == asset_id and j.get("job_kind") == "subtitle"
        ]
        self._send_json(200, {"subtitle_jobs": jobs})

    def _handle_download_subtitle(self, query: Dict, session: Dict) -> None:
        job_id = str((query.get("job_id") or [""])[0]).strip()
        job = MEDIA_PROCESSING_JOBS.get(job_id)
        if not job or job.get("job_kind") != "subtitle":
            self._send_json(404, {"error": "Subtitle job not found"})
            return

        srt_content = job.get("srt_content", "")
        if not srt_content:
            self._send_json(404, {"error": "No subtitle content available"})
            return

        body = srt_content.encode("utf-8")
        self._send_raw(
            200,
            body,
            "application/x-subrip; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="subtitles.srt"'},
        )

    def _handle_media_provider_callback(self, query: Dict, body: Dict) -> None:
        """Handle provider webhook callbacks for media processing jobs."""
        job_id = str((query.get("job_id") or [""])[0]).strip()
        if not job_id:
            job_id = str(body.get("job_id") or "").strip()

        request_secret = self.headers.get("X-Media-Webhook-Secret", "")
        if request_secret != MEDIA_PROVIDER_WEBHOOK_SECRET:
            self._send_json(403, {"error": "Invalid webhook signature"})
            return

        job = MEDIA_PROCESSING_JOBS.get(job_id)
        if not job:
            self._send_json(404, {"error": "Job not found"})
            return

        status = str(body.get("status") or "").strip().lower()
        now_iso = datetime.now(timezone.utc).isoformat()

        if job.get("job_kind") == "subtitle":
            if status == "completed":
                transcript = str(body.get("transcript") or "").strip()
                segments = body.get("segments") or []

                srt_lines = []
                for i, seg in enumerate(segments, 1):
                    start_s = float(seg.get("start", 0))
                    end_s = float(seg.get("end", 0))
                    text = str(seg.get("text", "")).strip()
                    srt_lines.append(str(i))
                    srt_lines.append(f"{_srt_time(start_s)} --> {_srt_time(end_s)}")
                    srt_lines.append(text)
                    srt_lines.append("")

                srt_content = "\n".join(srt_lines)
                job["status"] = "completed"
                job["srt_content"] = srt_content
                job["transcript"] = transcript
                job["updated_at"] = now_iso

                track = {
                    "format": "srt",
                    "language": job.get("language", "en"),
                    "download_url": f"/api/media/subtitles/download?job_id={job_id}",
                }
                self._send_json(200, {"job": job, "track": track})
            else:
                job["status"] = status
                job["updated_at"] = now_iso
                self._send_json(200, {"job": job})
            return

        if job.get("job_kind") in {"video_generation", "video_agent"}:
            if status == "completed":
                download_url = str(
                    body.get("download_url") or body.get("url") or ""
                ).strip()
                job["status"] = "completed"
                job["download_url"] = download_url
                job["updated_at"] = now_iso
            elif status == "failed":
                job["status"] = "failed"
                job["message"] = str(body.get("error") or body.get("message") or "Failed")
                job["updated_at"] = now_iso
            self._send_json(200, {"job": job})
            return

        self._send_json(200, {"job": job})

    # ------------------------------------------------------------------
    # Video jobs
    # ------------------------------------------------------------------

    def _handle_get_video_jobs(self, query: Dict, session: Dict) -> None:
        campaign_id = str((query.get("campaign_id") or [""])[0]).strip()
        jobs = [
            j for j in MEDIA_PROCESSING_JOBS.values()
            if j.get("job_kind") in {"video_generation", "video_agent"}
            and (not campaign_id or j.get("campaign_id") == campaign_id)
        ]
        jobs_sorted = sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)
        active = sum(1 for j in jobs_sorted if j.get("status") in {"queued", "processing"})
        completed = sum(1 for j in jobs_sorted if j.get("status") == "completed")
        failed = sum(
            1 for j in jobs_sorted if j.get("status") in {"failed", "cancelled"}
        )

        self._send_json(200, {
            "jobs": jobs_sorted,
            "summary": {
                "total": len(jobs_sorted),
                "active": active,
                "completed": completed,
                "failed": failed,
            },
        })

    def _handle_create_video_job(self, body: Dict, session: Dict) -> None:
        campaign_id = str(body.get("campaign_id") or "").strip()
        blueprint_index = int(body.get("blueprint_index") or 0)
        provider = str(body.get("provider") or "gemini").strip().lower()
        model = str(body.get("provider_model") or body.get("model") or "").strip()
        poll_mode = str(body.get("poll_mode") or "poll").strip().lower()
        image_data_url = str(body.get("image_data_url") or "").strip()
        reference_image_asset_id = str(body.get("reference_image_asset_id") or "").strip()
        auto_publish = bool(body.get("auto_publish_to_hero", False))
        prompt_override = str(body.get("prompt_override") or "").strip()

        if not campaign_id:
            self._send_json(400, {"error": "campaign_id is required"})
            return

        msa = DESIGN_SETTINGS.get("marketing_sales_agent") or {}
        latest = msa.get("latest_campaign") or {}
        campaign = latest.get("campaign") or {}
        blueprints = campaign.get("ai_video_blueprints") or []

        if blueprint_index >= len(blueprints):
            self._send_json(400, {"error": f"Blueprint index {blueprint_index} out of range"})
            return

        blueprint = blueprints[blueprint_index]

        if reference_image_asset_id and not image_data_url:
            ref_asset = MEDIA_ASSETS.get(reference_image_asset_id)
            if ref_asset:
                image_data_url = str(
                    ref_asset.get("data") or ref_asset.get("url") or ""
                ).strip()

        storyboard = blueprint.get("storyboard") or []
        storyboard_text = " ".join(str(s) for s in storyboard)
        prompt = prompt_override or (
            f"{blueprint.get('title', '')}. "
            f"{blueprint.get('voiceover_style', '')}. "
            f"{storyboard_text}"
        ).strip()

        job_id = f"vj-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        host = self.headers.get("Host", "localhost")
        callback_path = (
            f"/api/provider/media-processing/callback"
            f"?job_id={job_id}&token={secrets.token_urlsafe(8)}"
        )
        callback_url = f"http://{host}{callback_path}" if poll_mode == "webhook" else ""

        try:
            svc = get_media_generation_service()
            if svc is None:
                raise RuntimeError("Media generation service not available")
            submit_result = svc.submit_video_generation(
                provider=provider,
                prompt=prompt,
                title=str(blueprint.get("title") or f"Video {blueprint_index + 1}"),
                model=model,
                aspect_ratio="16:9",
                duration_seconds=8,
                image_data_url=image_data_url,
                callback_url=callback_url,
                metadata={
                    "campaign_id": campaign_id,
                    "blueprint_index": blueprint_index,
                    "job_id": job_id,
                },
            )
        except Exception as exc:
            self._send_json(503, {"error": str(exc)})
            return

        job = {
            "id": job_id,
            "job_kind": "video_generation",
            "campaign_id": campaign_id,
            "blueprint_index": blueprint_index,
            "provider": provider,
            "provider_model": model,
            "provider_job_id": submit_result.get("provider_job_id", ""),
            "provider_state": submit_result.get("provider_state", {}),
            "status": "queued",
            "progress_pct": 0,
            "message": submit_result.get("message", "Queued"),
            "prompt": prompt,
            "image_data_url": image_data_url,
            "reference_image_asset_id": reference_image_asset_id,
            "poll_mode": poll_mode,
            "callback_path": callback_path,
            "callback_url": callback_url,
            "auto_publish_to_hero": auto_publish,
            "asset_name": str(blueprint.get("title") or f"Video {blueprint_index + 1}"),
            "generated_asset_id": "",
            "download_url": "",
            "created_at": now_iso,
            "updated_at": now_iso,
            "created_by": session.get("username", "admin"),
        }
        MEDIA_PROCESSING_JOBS[job_id] = job

        if poll_mode == "poll":
            t = threading.Thread(target=_process_video_job, args=(job_id,), daemon=True)
            t.start()

        self._send_json(202, {"job": job})

    def _handle_batch_video_jobs(self, body: Dict, session: Dict) -> None:
        campaign_id = str(body.get("campaign_id") or "").strip()
        provider = str(body.get("provider") or "gemini").strip().lower()
        model = str(body.get("provider_model") or body.get("model") or "").strip()
        poll_mode = str(body.get("poll_mode") or "poll").strip().lower()
        image_data_url = str(body.get("image_data_url") or "").strip()
        reference_image_asset_id = str(body.get("reference_image_asset_id") or "").strip()
        auto_publish_first = bool(body.get("auto_publish_to_hero", False))
        prompt_override = str(body.get("prompt_override") or "").strip()

        if not campaign_id:
            self._send_json(400, {"error": "campaign_id is required"})
            return

        msa = DESIGN_SETTINGS.get("marketing_sales_agent") or {}
        latest = msa.get("latest_campaign") or {}
        campaign = latest.get("campaign") or {}
        blueprints = campaign.get("ai_video_blueprints") or []

        if not blueprints:
            self._send_json(400, {"error": "No video blueprints found for campaign"})
            return

        if reference_image_asset_id and not image_data_url:
            ref_asset = MEDIA_ASSETS.get(reference_image_asset_id)
            if ref_asset:
                image_data_url = str(
                    ref_asset.get("data") or ref_asset.get("url") or ""
                ).strip()

        queued_jobs = []
        host = self.headers.get("Host", "localhost")
        now_iso = datetime.now(timezone.utc).isoformat()

        for idx, blueprint in enumerate(blueprints):
            storyboard = blueprint.get("storyboard") or []
            storyboard_text = " ".join(str(s) for s in storyboard)
            prompt = prompt_override or (
                f"{blueprint.get('title', '')}. "
                f"{blueprint.get('voiceover_style', '')}. "
                f"{storyboard_text}"
            ).strip()

            job_id = f"vj-{uuid.uuid4().hex[:12]}"
            callback_path = (
                f"/api/provider/media-processing/callback"
                f"?job_id={job_id}&token={secrets.token_urlsafe(8)}"
            )
            callback_url = f"http://{host}{callback_path}" if poll_mode == "webhook" else ""

            try:
                svc = get_media_generation_service()
                if svc is None:
                    raise RuntimeError("Media generation service not available")
                submit_result = svc.submit_video_generation(
                    provider=provider,
                    prompt=prompt,
                    title=str(blueprint.get("title") or f"Video {idx + 1}"),
                    model=model,
                    aspect_ratio="16:9",
                    duration_seconds=8,
                    image_data_url=image_data_url,
                    callback_url=callback_url,
                    metadata={
                        "campaign_id": campaign_id,
                        "blueprint_index": idx,
                        "job_id": job_id,
                    },
                )
            except Exception as exc:
                self._send_json(503, {"error": str(exc)})
                return

            job = {
                "id": job_id,
                "job_kind": "video_generation",
                "campaign_id": campaign_id,
                "blueprint_index": idx,
                "provider": provider,
                "provider_model": model,
                "provider_job_id": submit_result.get("provider_job_id", ""),
                "provider_state": submit_result.get("provider_state", {}),
                "status": "queued",
                "progress_pct": 0,
                "message": submit_result.get("message", "Queued"),
                "prompt": prompt,
                "image_data_url": image_data_url,
                "reference_image_asset_id": reference_image_asset_id,
                "poll_mode": poll_mode,
                "callback_path": callback_path,
                "callback_url": callback_url,
                "auto_publish_to_hero": auto_publish_first and idx == 0,
                "asset_name": str(blueprint.get("title") or f"Video {idx + 1}"),
                "generated_asset_id": "",
                "download_url": "",
                "created_at": now_iso,
                "updated_at": now_iso,
                "created_by": session.get("username", "admin"),
            }
            MEDIA_PROCESSING_JOBS[job_id] = job
            queued_jobs.append(job)

            if poll_mode == "poll":
                t = threading.Thread(target=_process_video_job, args=(job_id,), daemon=True)
                t.start()

        self._send_json(202, {
            "campaign_id": campaign_id,
            "queued_jobs": queued_jobs,
            "jobs": queued_jobs,
            "total": len(queued_jobs),
        })

    def _handle_video_job_action(self, action: str, body: Dict, session: Dict) -> None:
        job_id = str(body.get("job_id") or "").strip()
        job = MEDIA_PROCESSING_JOBS.get(job_id)
        if not job:
            self._send_json(404, {"error": "Job not found"})
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        if action == "cancel":
            job["status"] = "cancelled"
            job["updated_at"] = now_iso
        elif action == "retry":
            job["status"] = "queued"
            job["progress_pct"] = 0
            job["message"] = "Retrying..."
            job["updated_at"] = now_iso
            if job.get("poll_mode") == "poll":
                t = threading.Thread(target=_process_video_job, args=(job_id,), daemon=True)
                t.start()

        self._send_json(200, {"success": True, "job": job})

    # ------------------------------------------------------------------
    # Actuarial
    # ------------------------------------------------------------------

    def _handle_actuarial_get(self, path: str, query: Dict, session: Dict) -> None:
        self._send_json(200, {"message": "Actuarial endpoint", "path": path})

    def _handle_actuarial_simulate(self, body: Dict, session: Dict) -> None:
        if not _ACTUARIAL_AVAILABLE or get_actuarial_service is None:
            self._send_json(503, {"error": "Actuarial service not available"})
            return

        try:
            svc = get_actuarial_service()
            simulation = svc.run_simulation(**{k: v for k, v in body.items()})
            sim_id = simulation.get("simulation_id") or _new_id("SIM")
            simulation["simulation_id"] = sim_id
            ACTUARIAL_SIMULATIONS[sim_id] = simulation
            self._send_json(200, {"simulation": simulation})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    # ------------------------------------------------------------------
    # Reinsurance
    # ------------------------------------------------------------------

    def _handle_reinsurance_recommendation(self, query: Dict, session: Dict) -> None:
        if not _REINSURANCE_AVAILABLE or get_reinsurance_service is None:
            self._send_json(503, {"error": "Reinsurance service not available"})
            return

        simulation_id = str((query.get("simulation_id") or [""])[0]).strip()
        simulation = ACTUARIAL_SIMULATIONS.get(simulation_id) or {}

        try:
            svc = get_reinsurance_service()
            contract_count = int((query.get("contract_count") or ["1000"])[0])
            hedge_share_pct = float((query.get("hedge_share_pct") or ["30"])[0])
            objective = str((query.get("objective") or ["min_cost"])[0])
            recommendation = svc.recommend(
                simulation=simulation,
                contract_count=contract_count,
                hedge_share_pct=hedge_share_pct,
                objective=objective,
            )
            self._send_json(200, {"success": True, "recommended": recommendation})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_reinsurance_bind(self, body: Dict, session: Dict) -> None:
        if not _REINSURANCE_AVAILABLE or get_reinsurance_service is None:
            self._send_json(503, {"error": "Reinsurance service not available"})
            return

        try:
            quote = body.get("quote") or {}
            simulation_id = str(
                quote.get("phins_simulation_id") or body.get("portfolio_id") or ""
            ).strip()
            contract_cost = float(quote.get("phins_total_contract_cost") or 0)

            contract_id = _new_id("RC")
            now_iso = datetime.now().isoformat()
            contract = {
                "id": contract_id,
                "name": str(body.get("contract_name") or "Reinsurance Contract"),
                "simulation_id": simulation_id,
                "quote": quote,
                "status": "bound",
                "bound_at": now_iso,
                "bound_by": session.get("username", "admin"),
            }
            REINSURANCE_CONTRACTS[contract_id] = contract

            bs_tx = _record_balance_sheet_transaction(
                "expense",
                "reinsurance",
                contract_cost,
                f"Reinsurance contract {contract_id} bound",
                actor=session.get("username", "admin"),
            )

            self._send_json(201, {
                "success": True,
                "contract": contract,
                "simulation_id": simulation_id,
                "balance_sheet_transaction": bs_tx,
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

_init_balance_sheet()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server(port: int = PORT) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), PortalHandler)
    print(f"✓ PHINS Portal running on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    if "--test" in sys.argv:
        print("✓ Server module loaded successfully")
        sys.exit(0)
    run_server(PORT)
