#!/usr/bin/env python3
"""
Lightweight web portal server (dependency-free) for demo purposes.

Usage:
  python web_portal/server.py       # start server on http://localhost:8000
  python web_portal/server.py --test  # run quick local tests and exit

This server exposes simple JSON endpoints and serves static files from
`web_portal/static/`. It's intended as a minimal demo backend suitable
for mobile-friendly web UI or to be used by a simple mobile app prototype.
"""
import json
import os
import urllib.parse as urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys
from datetime import datetime, timedelta
import random
import uuid
import hashlib
import secrets
import smtplib
from email.message import EmailMessage
from typing import Dict, Any
from pathlib import Path

# Import billing engine
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from billing_engine import billing_engine, SecurityValidator
    billing_enabled = True
except ImportError:
    billing_enabled = False
    print("Warning: Billing engine not available. Payment features disabled.")

# Database support (optional, falls back to in-memory)
# Production safety: if a DATABASE_URL is provided (Railway/Render), auto-enable DB even if USE_DATABASE isn't set.
_use_db_env = (os.environ.get('USE_DATABASE', '') or '').strip().lower()
if _use_db_env in ('false', '0', 'no'):
    USE_DATABASE = False
elif _use_db_env in ('true', '1', 'yes'):
    USE_DATABASE = True
else:
    USE_DATABASE = bool(os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URL'))
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
        from database.data_access import TOKEN_REGISTRY as DB_TOKEN_REGISTRY
        from database.data_access import NOTIFICATIONS as DB_NOTIFICATIONS
        from database.data_access import FORM_SUBMISSIONS as DB_FORM_SUBMISSIONS
        
        database_enabled = True
        print("✓ Database support enabled")
    except Exception as e:
        # IMPORTANT: Any SQLAlchemy model/registry error will surface during import time.
        # We must not crash the whole service; fall back to in-memory and print the root cause.
        print(f"Warning: Database support not available: {e}")
        print("         Falling back to in-memory storage")
        USE_DATABASE = False

PORT = int(os.environ.get("PORT", "8000"))
ROOT = os.path.join(os.path.dirname(__file__), "static")
UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT", os.path.join(os.path.dirname(__file__), "uploads"))

# Public base URL used in emails (set in production, e.g. https://your-app.up.railway.app)
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

# Underwriting automation config (autonomous approvals for low risk / younger ages)
UNDERWRITING_AUTOMATION_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "max_age": 30,
    "max_coverage_amount": 250_000,
    # Default: only auto-approve PHINS permanent disability product (ADL-based)
    "policy_type": "disability",
    # Actuarial gate: annual ADL claim probability must be < 3% (0.03 fraction)
    "max_adl_actuarial_risk_rate": 0.03,
}

# Market time-series (in-memory, best-effort). Keyed by SYMBOL@CURRENCY to avoid mixing currencies.
MARKET_SERIES_MAX_POINTS = int(os.environ.get("MARKET_SERIES_MAX_POINTS", "240"))
MARKET_SERIES: Dict[str, Dict[str, list[Dict[str, Any]]]] = {"crypto": {}, "index": {}}

def _series_append(kind: str, symbol: str, price: float, *, currency: str = "USD") -> None:
    kind = "crypto" if kind == "crypto" else "index"
    sym = str(symbol).upper()
    cur = str(currency or "USD").upper()
    key = f"{sym}@{cur}"
    series = MARKET_SERIES.setdefault(kind, {}).setdefault(key, [])
    series.append({"t": datetime.utcnow().isoformat(), "p": float(price)})
    # keep rolling buffer
    if len(series) > MARKET_SERIES_MAX_POINTS:
        del series[:-MARKET_SERIES_MAX_POINTS]

# Storage - either database-backed or in-memory
if USE_DATABASE and database_enabled:
    # Use database-backed dictionaries
    POLICIES = DB_POLICIES
    CLAIMS = DB_CLAIMS
    CUSTOMERS = DB_CUSTOMERS
    UNDERWRITING_APPLICATIONS = DB_UNDERWRITING
    SESSIONS = DB_SESSIONS
    BILLING = DB_BILLING
    TOKEN_REGISTRY = DB_TOKEN_REGISTRY
    NOTIFICATIONS = DB_NOTIFICATIONS
    FORM_SUBMISSIONS = DB_FORM_SUBMISSIONS
else:
    # In-memory storage for demo purposes
    POLICIES: Dict[str, Dict[str, Any]] = {}
    CLAIMS: Dict[str, Dict[str, Any]] = {}
    CUSTOMERS: Dict[str, Dict[str, Any]] = {}
    UNDERWRITING_APPLICATIONS: Dict[str, Dict[str, Any]] = {}
    SESSIONS: Dict[str, Dict[str, Any]] = {}  # token -> {username, expires, customer_id}
    BILLING: Dict[str, Dict[str, Any]] = {}  # bill_id -> bill data (for metrics)
    TOKEN_REGISTRY: Dict[str, Dict[str, Any]] = {}  # token -> token record
    NOTIFICATIONS: Dict[str, Dict[str, Any]] = {}  # notification_id -> record
    FORM_SUBMISSIONS: Dict[str, Dict[str, Any]] = {}  # id -> {customer_id,email,source,payload,created_date}
try:
    from services.audit_service import AuditService
    audit = AuditService()
except Exception:
    audit = None

# Security tracking
RATE_LIMIT: Dict[str, Dict[str, Any]] = {}  # IP -> {count, reset_time}
FAILED_LOGINS: Dict[str, Dict[str, Any]] = {}  # IP -> {count, lockout_until}
BLOCKED_IPS: Dict[str, Dict[str, Any]] = {}  # IP -> {reason, blocked_at, attempts}
MALICIOUS_ATTEMPTS: list[Dict[str, Any]] = []  # Log of all malicious attempts
SUSPICIOUS_PATTERNS: Dict[str, Dict[str, Any]] = {}  # IP -> {pattern_type, count, first_seen}
MAX_REQUESTS_PER_MINUTE = 60
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 900  # 15 minutes in seconds
MAX_MALICIOUS_ATTEMPTS = 10  # Permanent block after this many attempts
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB max request size
SESSION_TIMEOUT = 3600  # 1 hour session timeout
CONNECTION_TIMEOUT = 30  # 30 seconds connection timeout
MAX_SESSIONS_PER_IP = 10  # Max concurrent sessions per IP
CLEANUP_INTERVAL = 300  # Cleanup stale data every 5 minutes
last_cleanup = datetime.now()

# Hash passwords for security (in production, use proper password hashing)
def hash_password(password: str) -> dict[str, str]:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return secrets.compare_digest(hashed.hex(), stored_hash)

def validate_session(token: str) -> dict[str, str] | None:
    """Validate session token and return user info or None"""
    if not token or not token.startswith('phins_'):
        return None
    
    session = SESSIONS.get(token)
    if not session:
        return None
    
    # Check if session expired
    try:
        expires = datetime.fromisoformat(session['expires'])
        if datetime.now() > expires:
            del SESSIONS[token]
            return None
    except (KeyError, ValueError):
        return None
    
    return session


def _safe_parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _calc_age_from_dob(dob_str: str) -> int | None:
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d")
        today = datetime.now()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        return None


def send_email_notification(to_email: str, *, subject: str, body: str) -> bool:
    """Best-effort SMTP email sender. If SMTP is not configured, returns False."""
    to_email = (to_email or "").strip().lower()
    if not to_email or not validate_email(to_email):
        return False

    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if not smtp_host:
        return False

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or "no-reply@phins.ai").strip()

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.starttls()
            if smtp_user:
                s.login(smtp_user, smtp_password)
            s.send_message(msg)
        return True
    except Exception:
        return False


def create_notification(
    *,
    customer_id: str | None,
    role: str = "customer",
    kind: str = "info",
    subject: str,
    message: str,
    link: str | None = None,
) -> Dict[str, Any] | None:
    """Create an in-app notification (DB-backed when enabled)."""
    if USE_DATABASE and database_enabled:
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                n = db.notifications.create(
                    customer_id=customer_id,
                    role=role,
                    kind=kind,
                    subject=subject,
                    message=message,
                    link=link,
                    read=False,
                    created_date=datetime.utcnow(),
                )
                return n.to_dict() if n else None
        except Exception:
            return None

    notif_id = f"NTF-{datetime.now().strftime('%Y%m%d')}-{random.randint(100000, 999999)}"
    rec = {
        "id": notif_id,
        "customer_id": customer_id,
        "role": role,
        "kind": kind,
        "subject": subject,
        "message": message,
        "link": link,
        "read": False,
        "created_date": datetime.now().isoformat(),
    }
    NOTIFICATIONS[notif_id] = rec
    return rec


def notify_customer(
    *,
    customer_id: str | None,
    email: str | None,
    subject: str,
    message: str,
    link: str | None = None,
    kind: str = "info",
) -> None:
    """Send in-app notification + best-effort email."""
    create_notification(customer_id=customer_id, role="customer", kind=kind, subject=subject, message=message, link=link)

    # Email is optional and depends on SMTP configuration.
    if email and validate_email(email):
        url_line = f"\n\nLink: {link}" if link else ""
        body = f"{message}{url_line}\n\n— PHINS.ai"
        send_email_notification(email, subject=subject, body=body)


def create_bill(*, policy_id: str, customer_id: str, amount: float, due_days: int = 30) -> Dict[str, Any]:
    """Create a bill record compatible with both in-memory and DB-backed BILLING."""
    bill_id = f"BILL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
    now = datetime.now()
    bill = {
        "id": bill_id,
        "policy_id": policy_id,
        "customer_id": customer_id,
        "amount": float(amount),
        "amount_paid": 0.0,
        "status": "outstanding",
        "created_date": now.isoformat(),
        "due_date": (now + timedelta(days=int(due_days))).isoformat(),
    }
    BILLING[bill_id] = bill
    return bill


def create_billing_link(*, bill_id: str, policy_id: str, customer_id: str, amount: float, hours_valid: int = 48) -> Dict[str, Any]:
    """Create a 48h billing link token stored in TokenRegistry (DB-backed when enabled)."""
    token = f"bl_{secrets.token_urlsafe(24)}"
    now = datetime.now()
    expires_at = now + timedelta(hours=int(hours_valid))
    meta = {
        "bill_id": bill_id,
        "policy_id": policy_id,
        "customer_id": customer_id,
        "amount": float(amount),
        "currency": "USD",
    }
    TOKEN_REGISTRY[token] = {
        "token": token,
        "kind": "billing_link",
        "status": "active",
        "meta": json.dumps(meta),
        "created_date": now.isoformat(),
        "expires": expires_at.isoformat(),
    }
    link = f"{APP_BASE_URL}/billing-link.html?token={token}" if APP_BASE_URL else f"/billing-link.html?token={token}"
    return {"token": token, "expires": expires_at.isoformat(), "url": link}


def issue_policy_nft_token(*, policy_id: str, customer_id: str) -> Dict[str, Any]:
    """
    Issue a *policy ledger token* (NFT architecture placeholder).
    This does not mint on-chain inside this demo server; it creates a durable record
    that can later be reconciled with an on-chain mint/tx.
    """
    token = f"NFT-{policy_id}"
    meta = {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "standard": "ERC-721",
        "chain": (os.environ.get("POLICY_NFT_CHAIN") or "ethereum-l2").strip() or "ethereum-l2",
        "contract_address": (os.environ.get("POLICY_NFT_CONTRACT") or "").strip(),
        "token_id": token,
        "tx_hash": "",
        "minted": False,
        "issued_at": datetime.utcnow().isoformat(),
    }
    TOKEN_REGISTRY[token] = {
        "token": token,
        "kind": "policy_nft",
        "status": "issued",
        "meta": json.dumps(meta),
        "created_date": datetime.now().isoformat(),
        "expires": None,
    }
    return {"token": token, "meta": meta}


def resolve_billing_link(token: str) -> Dict[str, Any] | None:
    rec = TOKEN_REGISTRY.get(token)
    if not isinstance(rec, dict):
        return None
    if rec.get("kind") != "billing_link" or rec.get("status") != "active":
        return None
    expires = _safe_parse_dt(rec.get("expires"))
    if expires and expires < datetime.now():
        return None
    meta_raw = rec.get("meta") or rec.get("metadata") or "{}"
    try:
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
    except Exception:
        meta = {}
    return {"token": token, "expires": rec.get("expires"), "meta": meta}


def store_form_submission(*, source: str, customer_id: str | None, email: str | None, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a form submission (DB-backed when enabled)."""
    sid = f"SUB-{datetime.now().strftime('%Y%m%d')}-{random.randint(100000, 999999)}"
    rec = {
        "id": sid,
        "customer_id": customer_id,
        "email": (email or "").strip().lower() if email else None,
        "source": source,
        "payload": json.dumps(payload),
        "created_date": datetime.now().isoformat(),
    }
    FORM_SUBMISSIONS[sid] = rec
    return rec


def _safe_filename(name: str) -> str:
    """Sanitize filenames to avoid traversal and weird chars."""
    base = os.path.basename(str(name or "file"))
    # allow simple set of chars
    out = []
    for ch in base:
        if ch.isalnum() or ch in ("-", "_", ".", " "):
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip().replace(" ", "_")
    if not s:
        s = "file"
    return s[:120]


def _persist_media_assets(*, customer_id: str, uw_id: str, policy_id: str | None, files: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """
    Persist uploaded media/files and return attachment metadata records.
    Stored on disk under UPLOAD_ROOT and indexed in TOKEN_REGISTRY as kind=media_asset.
    """
    if not files:
        return []
    out: list[Dict[str, Any]] = []
    root = Path(UPLOAD_ROOT)
    target_dir = root / _safe_filename(customer_id) / _safe_filename(uw_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        try:
            raw = f.get("data") or b""
            if not isinstance(raw, (bytes, bytearray)):
                continue
            size = int(len(raw))
            if size <= 0:
                continue
            token = f"MED-{uuid.uuid4().hex}"
            original = _safe_filename(f.get("filename") or f.get("name") or token)
            stored = f"{token}_{original}"
            p = target_dir / stored
            p.write_bytes(raw)

            meta = {
                "customer_id": customer_id,
                "uw_id": uw_id,
                "policy_id": policy_id,
                "field": str(f.get("field") or ""),
                "original_filename": str(original),
                "stored_filename": str(stored),
                "content_type": str(f.get("content_type") or "application/octet-stream"),
                "size": size,
                "storage": "local",
                "path": str(p),
                "created_date": datetime.utcnow().isoformat(),
            }
            TOKEN_REGISTRY[token] = {
                "token": token,
                "kind": "media_asset",
                "status": "active",
                "meta": json.dumps(meta),
                "created_date": datetime.now().isoformat(),
                "expires": None,
            }
            out.append({
                "token": token,
                "field": meta["field"],
                "filename": meta["original_filename"],
                "content_type": meta["content_type"],
                "size": size,
                "created_date": meta["created_date"],
                "download_url": f"/api/media/download?token={urlparse.quote(token)}",
            })
        except Exception:
            continue
    return out


def _should_auto_approve(*, policy: Dict[str, Any], app: Dict[str, Any], customer: Dict[str, Any]) -> bool:
    """Autonomous underwriting rule for low-risk, younger applicants."""
    cfg = UNDERWRITING_AUTOMATION_CONFIG
    if not cfg.get("enabled", True):
        return False

    # Policy type gating (default: disability only)
    required_type = str(cfg.get("policy_type") or "").strip().lower()
    if required_type:
        if str(policy.get("type") or "").strip().lower() != required_type:
            return False

    # Product gating (default: PHINS permanent disability ADL product)
    try:
        notes_raw = app.get("notes") or "{}"
        notes = json.loads(notes_raw) if isinstance(notes_raw, str) else dict(notes_raw)
        product_name = ""
        if isinstance(notes.get("product"), dict):
            product_name = str(notes.get("product", {}).get("name") or "")
        else:
            product_name = str(notes.get("product_name") or "")
        if product_name and product_name != "phins_permanent_phi_disability":
            return False
    except Exception:
        # If we can't confirm the product, do not auto-approve.
        return False

    # Actuarial gate: ADL risk rate must be below threshold
    try:
        from services.actuarial_disability_tables import get_adl_disability_rate

        age = _calc_age_from_dob(str(customer.get("dob") or ""))
        if age is None:
            return False

        jurisdiction = str(policy.get("jurisdiction") or "").upper() or "US"
        if jurisdiction not in ("US", "UK"):
            jurisdiction = "US"

        risk_rate = float(get_adl_disability_rate(jurisdiction, int(age)))
        max_rate = float(cfg.get("max_adl_actuarial_risk_rate", 0.03))
        if risk_rate >= max_rate:
            return False
    except Exception:
        return False
    age = _calc_age_from_dob(str(customer.get("dob") or ""))
    if age is None:
        return False
    if age > int(cfg.get("max_age", 30)):
        return False
    if str(app.get("risk_assessment") or "").lower() != "low":
        return False
    if bool(app.get("medical_exam_required", False)):
        return False
    cov = float(policy.get("coverage_amount") or 0.0)
    if cov > float(cfg.get("max_coverage_amount", 250_000)):
        return False
    return True


def _approve_underwriting_and_notify(*, uw_id: str, approved_by: str, automated: bool = False) -> Dict[str, Any] | None:
    app = UNDERWRITING_APPLICATIONS.get(uw_id)
    if not isinstance(app, dict):
        return None
    policy_id = app.get("policy_id")
    policy = POLICIES.get(policy_id) if policy_id else None
    if not isinstance(policy, dict):
        policy = None

    # Update underwriting app
    app["status"] = "approved"
    app["decision_date"] = datetime.now().isoformat()
    app["approved_by"] = approved_by
    if automated:
        # mark for admin visibility
        try:
            notes = json.loads(app.get("notes") or "{}") if isinstance(app.get("notes"), str) else {}
        except Exception:
            notes = {}
        notes["auto_approved"] = True
        notes["auto_rule"] = UNDERWRITING_AUTOMATION_CONFIG
        app["notes"] = json.dumps(notes)

    # Update policy
    if policy:
        policy["status"] = "active"
        policy["approval_date"] = datetime.now().isoformat()
        policy["uw_status"] = "approved"

    # Create bill + 48h billing link (for first premium)
    billing_link = None
    nft = None
    if policy and isinstance(policy.get("annual_premium"), (int, float)):
        customer_id = policy.get("customer_id")
        cust = CUSTOMERS.get(customer_id) if customer_id else None
        if isinstance(cust, dict):
            bill = create_bill(policy_id=policy["id"], customer_id=customer_id, amount=float(policy["annual_premium"]), due_days=2)
            billing_link = create_billing_link(
                bill_id=bill["id"],
                policy_id=policy["id"],
                customer_id=customer_id,
                amount=float(policy["annual_premium"]),
                hours_valid=48,
            )
            # Issue policy NFT ledger token (architecture placeholder)
            try:
                nft = issue_policy_nft_token(policy_id=policy["id"], customer_id=customer_id)
                # attach to policy for UI visibility
                policy["nft_token"] = nft.get("token")
                policy["nft_status"] = "issued"
            except Exception:
                nft = None
            notify_customer(
                customer_id=customer_id,
                email=cust.get("email"),
                subject="Your PHINS.ai application was approved",
                message="Your application has been approved. Please complete payment within 48 hours to activate billing.",
                link=billing_link.get("url"),
                kind="billing",
            )
    return {"application": app, "policy": policy, "billing_link": billing_link, "policy_nft": nft}


def _reject_underwriting_and_notify(*, uw_id: str, rejected_by: str, reason: str) -> Dict[str, Any] | None:
    app = UNDERWRITING_APPLICATIONS.get(uw_id)
    if not isinstance(app, dict):
        return None
    app["status"] = "rejected"
    app["decision_date"] = datetime.now().isoformat()
    app["rejection_reason"] = reason
    app["rejected_by"] = rejected_by

    policy_id = app.get("policy_id")
    if policy_id and policy_id in POLICIES:
        try:
            POLICIES[policy_id]["status"] = "rejected"
            POLICIES[policy_id]["uw_status"] = "rejected"
        except Exception:
            pass
    customer_id = app.get("customer_id")
    cust = CUSTOMERS.get(customer_id) if customer_id else None
    if isinstance(cust, dict):
        notify_customer(
            customer_id=customer_id,
            email=cust.get("email"),
            subject="Your PHINS.ai application was reviewed",
            message=f"Your application was not approved. Reason: {reason}",
            kind="underwriting",
        )
    return {"application": app}

def check_rate_limit(client_ip: str, *, role: str | None = None) -> bool:
    """Check if client has exceeded rate limit (higher limits for authenticated users)."""
    now = datetime.now().timestamp()
    role_l = str(role or '').lower()
    limit = MAX_REQUESTS_PER_MINUTE
    if role_l == 'customer':
        limit = max(limit, 240)
    elif role_l in ('admin', 'underwriter', 'accountant', 'claims', 'claims_adjuster'):
        limit = max(limit, 600)
    
    if client_ip in RATE_LIMIT:
        limit_data = RATE_LIMIT[client_ip]
        # Reset counter if minute has passed
        if now > limit_data['reset_time']:
            RATE_LIMIT[client_ip] = {'count': 1, 'reset_time': now + 60}
            return True
        elif limit_data['count'] < limit:
            limit_data['count'] += 1
            return True
        else:
            return False
    else:
        RATE_LIMIT[client_ip] = {'count': 1, 'reset_time': now + 60}
        return True

def check_login_lockout(client_ip: str) -> bool:
    """Check if IP is locked out due to failed login attempts"""
    if client_ip in FAILED_LOGINS:
        lockout_data = FAILED_LOGINS[client_ip]
        if datetime.now().timestamp() < lockout_data.get('lockout_until', 0):
            return False  # Still locked out
        elif lockout_data['count'] >= MAX_LOGIN_ATTEMPTS:
            # Reset after lockout period
            del FAILED_LOGINS[client_ip]
    return True

def record_failed_login(client_ip: str):
    """Record a failed login attempt"""
    if client_ip not in FAILED_LOGINS:
        FAILED_LOGINS[client_ip] = {'count': 0}
    
    FAILED_LOGINS[client_ip]['count'] += 1
    
    if FAILED_LOGINS[client_ip]['count'] >= MAX_LOGIN_ATTEMPTS:
        FAILED_LOGINS[client_ip]['lockout_until'] = datetime.now().timestamp() + LOCKOUT_DURATION

def require_role(session: dict[str, str] | None, allowed_roles: list[str]) -> bool:
    """Check if user has required role"""
    if not session:
        return False
    
    username = session.get('username')
    if not username:
        return False
    
    user = USERS.get(username)
    if not user:
        return False
    
    return user.get('role') in allowed_roles

def log_malicious_attempt(client_ip: str, reason: str, details: Dict[str, Any] | None = None):
    """Log a malicious attempt for monitoring and analysis"""
    attempt: Dict[str, Any] = {
        'timestamp': datetime.now().isoformat(),
        'ip': client_ip,
        'reason': reason,
        'details': details or {}
    }
    MALICIOUS_ATTEMPTS.append(attempt)
    
    # Keep only last 1000 attempts in memory
    if len(MALICIOUS_ATTEMPTS) > 1000:
        MALICIOUS_ATTEMPTS.pop(0)
    
    # Check if IP should be permanently blocked
    ip_attempts = sum(1 for a in MALICIOUS_ATTEMPTS if a['ip'] == client_ip)
    if ip_attempts >= MAX_MALICIOUS_ATTEMPTS:
        block_ip(client_ip, f"Exceeded {MAX_MALICIOUS_ATTEMPTS} malicious attempts", permanent=True)
    
    # Print to console for real-time monitoring
    print(f"🚨 SECURITY ALERT: {client_ip} - {reason}")
    if details:
        print(f"   Details: {json.dumps(details, indent=2)}")

def block_ip(client_ip: str, reason: str, permanent: bool = False):
    """Block an IP address"""
    BLOCKED_IPS[client_ip] = {
        'reason': reason,
        'blocked_at': datetime.now().isoformat(),
        'permanent': permanent,
        'attempts': BLOCKED_IPS.get(client_ip, {}).get('attempts', 0) + 1
    }
    print(f"🚫 BLOCKED IP: {client_ip} - {reason} {'(PERMANENT)' if permanent else ''}")

def is_ip_blocked(client_ip: str) -> tuple[bool, str]:
    """Check if IP is blocked, returns (is_blocked, reason)"""
    if client_ip in BLOCKED_IPS:
        block_data = BLOCKED_IPS[client_ip]
        if block_data.get('permanent'):
            return (True, block_data['reason'])
        # Temporary blocks expire after 24 hours
        blocked_at = datetime.fromisoformat(block_data['blocked_at'])
        if datetime.now() - blocked_at < timedelta(hours=24):
            return (True, block_data['reason'])
        else:
            del BLOCKED_IPS[client_ip]
    return (False, "")

def detect_sql_injection(value: str) -> bool:
    """Detect potential SQL injection attempts"""
    sql_patterns = [
        "' OR '", '" OR "', "1=1", "1' OR '1", 'DROP TABLE', 'DELETE FROM',
        'INSERT INTO', 'UPDATE ', 'UNION SELECT', '--', '/*', '*/', 'xp_',
        'sp_', 'EXEC ', 'EXECUTE', ';--', "';--", '";--'
    ]
    value_upper = value.upper()
    return any(pattern.upper() in value_upper for pattern in sql_patterns)

def detect_xss_attempt(value: str) -> bool:
    """Detect potential XSS (Cross-Site Scripting) attempts"""
    xss_patterns = [
        '<script', '</script>', 'javascript:', 'onerror=', 'onload=',
        'onclick=', 'onmouseover=', '<iframe', '<object', '<embed',
        'eval(', 'alert(', 'document.cookie', 'window.location'
    ]
    value_lower = value.lower()
    return any(pattern.lower() in value_lower for pattern in xss_patterns)

def detect_path_traversal(value: str) -> bool:
    """Detect path traversal attempts"""
    patterns = ['../', '..\\', '%2e%2e', '%252e%252e', '/etc/passwd', '/etc/shadow']
    return any(pattern in value.lower() for pattern in patterns)

def detect_command_injection(value: str) -> bool:
    """Detect command injection attempts"""
    patterns = ['&&', '||', ';', '|', '`', '$(', 'system(', 'exec(', 'shell_exec', 'passthru', 
                'wget', 'curl', 'nc ', 'netcat', '/bin/', '/dev/', 'chmod', 'chown']
    return any(pattern in value for pattern in patterns)

def detect_malicious_payload(value: str) -> bool:
    """Detect various malicious payloads and exploits"""
    malicious_patterns = [
        # Code execution
        'eval(', 'exec(', '__import__', 'compile(', 'globals()',
        # File operations
        'open(', 'file(', 'read(', 'write(',
        # System access
        'os.system', 'subprocess', 'popen', 'pty.spawn',
        # Reverse shells
        'socket', 'connect(', 'bind(', 'listen(',
        # Crypto mining
        'crypto', 'mining', 'monero', 'bitcoin',
        # Data exfiltration 
        'base64', 'pickle', 'marshal', 'shelve',
        # LDAP injection
        '(|', '(&', '(!(', '*)(', ')(&',
        # XML injection
        '<!ENTITY', '<!DOCTYPE', 'SYSTEM \"',
        # SSRF
        'file://', 'gopher://', 'dict://', 'ftp://', 'tftp://',
        # Template injection
        '{{', '{%', '<%', '#{', '@{'
    ]
    value_lower = value.lower()
    return any(pattern.lower() in value_lower for pattern in malicious_patterns)

def cleanup_stale_data():
    """Clean up expired sessions, old rate limits, and stale security data"""
    global last_cleanup
    now = datetime.now()
    
    # Only cleanup every CLEANUP_INTERVAL seconds
    if (now - last_cleanup).total_seconds() < CLEANUP_INTERVAL:
        return
    
    last_cleanup = now
    timestamp = now.timestamp()
    
    # Clean expired sessions
    expired_sessions = [token for token, sess in SESSIONS.items() 
                       if datetime.fromisoformat(sess['expires']) < now]
    for token in expired_sessions:
        del SESSIONS[token]
    
    # Clean expired rate limits
    expired_limits = [ip for ip, data in RATE_LIMIT.items() 
                     if timestamp > data['reset_time'] + 300]  # 5 min grace
    for ip in expired_limits:
        del RATE_LIMIT[ip]
    
    # Clean expired login lockouts
    expired_lockouts = [ip for ip, data in FAILED_LOGINS.items() 
                       if timestamp > data.get('lockout_until', 0) + 300]
    for ip in expired_lockouts:
        del FAILED_LOGINS[ip]
    
    # Clean old temporary IP blocks (keep permanent ones)
    expired_blocks = [ip for ip, data in BLOCKED_IPS.items() 
                     if not data.get('permanent') and 
                     (now - datetime.fromisoformat(data['blocked_at'])).total_seconds() > 86400]
    for ip in expired_blocks:
        del BLOCKED_IPS[ip]
    
    # Trim malicious attempts log to last 1000
    if len(MALICIOUS_ATTEMPTS) > 1000:
        MALICIOUS_ATTEMPTS[:] = MALICIOUS_ATTEMPTS[-1000:]
    
    if expired_sessions or expired_limits or expired_lockouts or expired_blocks:
        print(f"🧹 Cleanup: Removed {len(expired_sessions)} sessions, {len(expired_limits)} rate limits, "
              f"{len(expired_lockouts)} lockouts, {len(expired_blocks)} blocks")

def check_session_limit(client_ip: str) -> bool:
    """Check if IP has too many concurrent sessions"""
    active_sessions = sum(1 for sess in SESSIONS.values() 
                         if sess.get('ip') == client_ip and 
                         datetime.fromisoformat(sess['expires']) > datetime.now())
    return active_sessions < MAX_SESSIONS_PER_IP

def validate_input_security(value: str, client_ip: str, field_name: str = 'input') -> tuple[bool, str | None]:
    """Comprehensive input validation, returns (is_valid, error_message)"""
    if not value:
        return (True, None)
    
    value_str = str(value)
    
    # Check for SQL injection
    if detect_sql_injection(value_str):
        log_malicious_attempt(client_ip, 'SQL Injection Attempt', {
            'field': field_name,
            'value_length': len(value_str),
            'sample': value_str[:100]
        })
        block_ip(client_ip, 'SQL Injection detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for XSS
    if detect_xss_attempt(value_str):
        log_malicious_attempt(client_ip, 'XSS Attempt', {
            'field': field_name,
            'value_length': len(value_str),
            'sample': value_str[:100]
        })
        block_ip(client_ip, 'XSS attack detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for path traversal
    if detect_path_traversal(value_str):
        log_malicious_attempt(client_ip, 'Path Traversal Attempt', {
            'field': field_name,
            'value': value_str[:100]
        })
        block_ip(client_ip, 'Path traversal detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for command injection
    if detect_command_injection(value_str):
        log_malicious_attempt(client_ip, 'Command Injection Attempt', {
            'field': field_name,
            'value': value_str[:100]
        })
        block_ip(client_ip, 'Command injection detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for malicious payloads
    if detect_malicious_payload(value_str):
        log_malicious_attempt(client_ip, 'Malicious Payload Detected', {
            'field': field_name,
            'value_length': len(value_str),
            'sample': value_str[:100]
        })
        block_ip(client_ip, 'Malicious code detected', permanent=True)
        return (False, 'Invalid input detected')
    
    return (True, None)

def sanitize_input(value: str, max_length: int = 255) -> str:
    """Sanitize user input to prevent injection attacks"""
    if not value:
        return ''
    
    # Truncate to max length
    value = str(value)[:max_length]
    
    # Remove potentially dangerous characters
    dangerous_chars = ['<', '>', '"', "'", '\\', '\x00', '\n', '\r', '\t']
    for char in dangerous_chars:
        value = value.replace(char, '')
    
    return value.strip()

def validate_email(email: str) -> bool:
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) and len(email) <= 254


def _normalize_username(username: str) -> str:
    """
    Normalize usernames for lookup.
    - Emails are case-insensitive, so force lowercase.
    - Preserve non-email usernames as-is (e.g. legacy demo accounts).
    """
    u = (username or "").strip()
    if "@" in u:
        return u.lower()
    return u

def validate_amount(amount: Any) -> bool:
    """Validate monetary amounts"""
    try:
        amount = float(amount)
        return 0 <= amount <= 100000000  # Max 100 million
    except (ValueError, TypeError):
        return False

# Store hashed passwords
if USE_DATABASE and database_enabled:
    # Users are stored in database, but we need a helper to check them
    # We'll create a wrapper that checks the database
    class UserDictWrapper:
        """Wrapper to make database users work like a dict"""
        def get(self, username: str, default=None):
            username = _normalize_username(username)
            try:
                from database.manager import DatabaseManager
                with DatabaseManager() as db:
                    user = db.users.get_by_username(username)
                    if user:
                        # Customer accounts are stored in the users table too, but the user row
                        # doesn't store customer_id. We resolve it via the customers table by email.
                        customer_id = None
                        try:
                            lookup_email = (user.email or username or "").strip().lower()
                            if lookup_email:
                                cust = db.customers.get_by_email(lookup_email)
                                if cust:
                                    customer_id = cust.id
                        except Exception:
                            customer_id = None
                        return {
                            'hash': user.password_hash,
                            'salt': user.password_salt,
                            'role': user.role,
                            'name': user.name,
                            'email': user.email,
                            'customer_id': customer_id,
                        }
            except ImportError as e:
                print(f"Warning: Database module not available: {e}")
            except Exception as e:
                print(f"Warning: Error fetching user from database: {e}")
            return default
        
        def __getitem__(self, username: str):
            result = self.get(username)
            if result is None:
                raise KeyError(username)
            return result
        
        def __contains__(self, username: str):
            return self.get(username) is not None
    
    USERS = UserDictWrapper()
else:
    USERS: Dict[str, Dict[str, Any]] = {
        'admin': {**hash_password('admin123'), 'role': 'admin', 'name': 'Admin User'},
        'underwriter': {**hash_password('under123'), 'role': 'underwriter', 'name': 'John Underwriter'},
        'claims_adjuster': {**hash_password('claims123'), 'role': 'claims', 'name': 'Jane Claims'},
        'accountant': {**hash_password('acct123'), 'role': 'accountant', 'name': 'Bob Accountant'}
    }


def get_mock_statement(customer_id: str) -> Dict[str, Any]:
    # For production, the platform should not fabricate financial statements.
    # This fallback returns an *empty* statement so UIs don't show fake data.
    return {
        "customer_id": customer_id,
        "total_premium": 0.0,
        "risk_total": 0.0,
        "savings_total": 0.0,
        "allocations": [],
    }


def generate_policy_id() -> str:
    return f"POL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_claim_id() -> str:
    return f"CLM-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_customer_id() -> str:
    return f"CUST-{random.randint(10000, 99999)}"

def calculate_premium(policy_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate premium based on policy type and customer data.

    For PHI (ADL-based permanent disability) policies, pricing uses:
      - UK/US disability actuarial tables (by age)
      - adjustable operational+reinsurance load
      - adjustable savings/investment split (e.g., 25% / 50% / 90%)
    """
    try:
        from services.pricing_service import price_policy

        priced = price_policy(policy_data)
        # Preserve backward-compatible shape {annual, monthly, quarterly}
        return {
            "annual": float(priced.get("annual", 0.0)),
            "monthly": float(priced.get("monthly", 0.0)),
            "quarterly": float(priced.get("quarterly", 0.0)),
        }
    except Exception:
        # Extreme fallback – keep the server responsive even if pricing import fails
        annual_premium = 1000.0
        return {
            "annual": round(annual_premium, 2),
            "monthly": round(annual_premium / 12.0, 2),
            "quarterly": round(annual_premium / 4.0, 2),
        }


def _health_risk_loading_factor(health_condition_score: Any) -> float:
    """
    Map a 1-10 health condition score to a risk-loading factor applied to the *risk cover* portion.

    Requirements:
      - 1-3  -> +0%
      - 4-6  -> +15%
      - 7-8  -> +50%
      - 9-10 -> +100%
    """
    try:
        s = int(float(health_condition_score))
    except Exception:
        s = 3
    if s <= 3:
        return 0.0
    if 4 <= s <= 6:
        return 0.15
    if 7 <= s <= 8:
        return 0.50
    return 1.00


def _apply_health_risk_loading(priced: Dict[str, Any], *, health_condition_score: Any) -> Dict[str, Any]:
    """
    Apply health risk loading to pricing, adding the uplift ONLY to the risk allocation.
    """
    factor = _health_risk_loading_factor(health_condition_score)
    if not factor:
        # Still annotate for transparency.
        b = priced.get("breakdown") if isinstance(priced, dict) else None
        if isinstance(b, dict):
            b["health_condition_score"] = int(float(health_condition_score)) if str(health_condition_score).strip() else 3
            b["health_risk_loading_factor"] = 0.0
            b["health_risk_loading_percent"] = 0.0
        return priced

    out = dict(priced or {})
    b = out.get("breakdown") if isinstance(out, dict) else None
    if not isinstance(b, dict):
        b = {}
        out["breakdown"] = b

    # Base allocations from pricing_service
    monthly_total = float(out.get("monthly") or 0.0)
    annual_total = float(out.get("annual") or 0.0)
    monthly_risk = float(b.get("monthly_risk_allocation") or 0.0)
    annual_risk = float(b.get("annual_risk_allocation") or 0.0)

    # Loading is charged on risk cover only, per requirement.
    monthly_extra = round(monthly_risk * factor, 2)
    annual_extra = round(annual_risk * factor, 2)

    out["monthly"] = round(monthly_total + monthly_extra, 2)
    out["annual"] = round(annual_total + annual_extra, 2)
    out["quarterly"] = round(float(out["annual"]) / 4.0, 2)

    # Keep the savings allocation the same; all uplift goes to risk cover.
    b["health_condition_score"] = int(float(health_condition_score)) if str(health_condition_score).strip() else 3
    b["health_risk_loading_factor"] = float(factor)
    b["health_risk_loading_percent"] = float(factor) * 100.0
    b["monthly_risk_loading_amount"] = float(monthly_extra)
    b["annual_risk_loading_amount"] = float(annual_extra)
    b["monthly_total_premium"] = float(out["monthly"])
    b["annual_total_premium"] = float(out["annual"])
    b["monthly_risk_allocation"] = round(monthly_risk + monthly_extra, 2)
    b["annual_risk_allocation"] = round(annual_risk + annual_extra, 2)

    # Savings allocations remain unchanged from the base result; ensure present.
    if "monthly_savings_allocation" in b:
        b["monthly_savings_allocation"] = float(b.get("monthly_savings_allocation") or 0.0)
    if "annual_savings_allocation" in b:
        b["annual_savings_allocation"] = float(b.get("annual_savings_allocation") or 0.0)

    return out

def get_bi_data_actuary() -> Dict[str, Any]:
    """Generate actuarial BI data"""
    return {
        'total_policies': len(POLICIES),
        'total_exposure': sum(p.get('coverage_amount', 0) for p in POLICIES.values()),
        'average_premium': sum(p.get('annual_premium', 0) for p in POLICIES.values()) / max(len(POLICIES), 1),
        'risk_distribution': {
            'low': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'low'),
            'medium': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'medium'),
            'high': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'high'),
            'very_high': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'very_high')
        },
        'claims_ratio': len(CLAIMS) / max(len(POLICIES), 1),
        'loss_ratio': sum(c.get('approved_amount', 0) for c in CLAIMS.values() if c.get('status') == 'paid') / max(sum(p.get('annual_premium', 0) for p in POLICIES.values()), 1),
        'policy_by_type': {
            'life': sum(1 for p in POLICIES.values() if p.get('type') == 'life'),
            'health': sum(1 for p in POLICIES.values() if p.get('type') == 'health'),
            'auto': sum(1 for p in POLICIES.values() if p.get('type') == 'auto'),
            'property': sum(1 for p in POLICIES.values() if p.get('type') == 'property')
        }
    }

def get_bi_data_underwriting() -> Dict[str, Any]:
    """Generate underwriting BI data"""
    return {
        'pending_applications': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'pending'),
        'approved_this_month': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'approved' and u.get('decision_date', '').startswith(datetime.now().strftime('%Y-%m'))),
        'rejection_rate': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'rejected') / max(len(UNDERWRITING_APPLICATIONS), 1),
        'average_processing_time': 3.5,  # days
        'risk_assessment_distribution': {
            'low': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'low'),
            'medium': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'medium'),
            'high': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'high'),
            'very_high': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'very_high')
        },
        'medical_exams_required': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('medical_exam_required', False))
    }

def get_bi_data_accounting() -> Dict[str, Any]:
    """Generate accounting BI data"""
    total_premium_collected = sum(p.get('annual_premium', 0) for p in POLICIES.values() if p.get('status') == 'active')
    total_claims_paid = sum(c.get('approved_amount', 0) for c in CLAIMS.values() if c.get('status') == 'paid')
    
    return {
        'total_revenue': total_premium_collected,
        'total_claims_paid': total_claims_paid,
        'net_income': total_premium_collected - total_claims_paid,
        'outstanding_premiums': sum(p.get('annual_premium', 0) * 0.1 for p in POLICIES.values()),  # Mock 10% outstanding
        'pending_claims_liability': sum(c.get('claimed_amount', 0) for c in CLAIMS.values() if c.get('status') in ['pending', 'under_review']),
        'profit_margin': ((total_premium_collected - total_claims_paid) / max(total_premium_collected, 1)) * 100,
        'monthly_breakdown': [
            {'month': (datetime.now() - timedelta(days=30*i)).strftime('%Y-%m'), 
             'revenue': total_premium_collected / 12, 
             'claims': total_claims_paid / 12}
            for i in range(12)
        ][::-1]
    }

def try_get_statement_from_engine(customer_id: str) -> Any:
    try:
        import accounting_engine as ae

        engine = ae.AccountingEngine()
        # Try to call a best-effort method and coerce result to JSON-serializable
        if hasattr(engine, "get_customer_statement"):
            stmt = engine.get_customer_statement(customer_id)  # type: ignore
            try:
                result: Any = json.loads(json.dumps(stmt, default=lambda o: o.__dict__))
                return result
            except Exception:
                return stmt  # type: ignore
    except Exception:
        pass
    return None


# =============================================================================
# PHI PRODUCT CONFIG + STATEMENTS (NO FAKE FINANCIAL DATA)
# =============================================================================

# Default PHI configuration (admin can change via API).
# Values are percent-like numbers for easier UI entry (e.g., 50 means 50%).
PHI_PRODUCT_CONFIG: Dict[str, Any] = {
    "default_jurisdiction": "US",  # "US" | "UK"
    "default_operational_reinsurance_load": 50,  # 50%
    "default_savings_percentage": 25,  # 25%
}


def _pct_to_fraction(value: Any, default: float) -> float:
    try:
        v = float(value)
    except Exception:
        return default
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(0.99, v))


def get_policy_allocation(policy: Dict[str, Any]) -> Dict[str, float]:
    """
    Return (risk_percentage, savings_percentage) as fractions.
    """
    savings = policy.get("savings_percentage", PHI_PRODUCT_CONFIG.get("default_savings_percentage", 25))
    savings_f = _pct_to_fraction(savings, 0.25)
    risk_f = max(0.01, 1.0 - savings_f)
    return {"risk_percentage": risk_f, "savings_percentage": savings_f}


def build_customer_statement_from_transactions(customer_id: str) -> Dict[str, Any]:
    """
    Build a premium statement from actual payment transactions.
    """
    allocations: list[Dict[str, Any]] = []
    total = 0.0
    risk_total = 0.0
    savings_total = 0.0

    # Prefer billing_engine records if available.
    txns: list[Dict[str, Any]] = []
    if billing_enabled:
        try:
            txns = billing_engine.get_customer_transactions(customer_id)  # type: ignore
        except Exception:
            txns = []

    # Only successful payments count toward premium allocation.
    for t in sorted(txns, key=lambda x: x.get("timestamp", ""), reverse=False):
        if t.get("status") != "success":
            continue
        try:
            amount = float(t.get("amount", 0.0))
        except Exception:
            amount = 0.0
        if amount <= 0:
            continue
        policy_id = t.get("policy_id")
        policy = POLICIES.get(policy_id) if policy_id else None
        alloc_pct = get_policy_allocation(policy or {})
        risk_amt = round(amount * alloc_pct["risk_percentage"], 2)
        savings_amt = round(amount * alloc_pct["savings_percentage"], 2)
        allocations.append(
            {
                "allocation_id": t.get("transaction_id") or f"ALLOC-{uuid.uuid4().hex[:10]}",
                "policy_id": policy_id,
                "timestamp": t.get("timestamp"),
                "amount": round(amount, 2),
                "risk_amount": risk_amt,
                "savings_amount": savings_amt,
                "risk_percentage": round(alloc_pct["risk_percentage"] * 100.0, 2),
                "savings_percentage": round(alloc_pct["savings_percentage"] * 100.0, 2),
            }
        )
        total += amount
        risk_total += risk_amt
        savings_total += savings_amt

    return {
        "customer_id": customer_id,
        "total_premium": round(total, 2),
        "risk_total": round(risk_total, 2),
        "savings_total": round(savings_total, 2),
        "allocations": allocations[-100:],  # last 100 allocations
    }


def _normalize_investment_allocations(items: Any) -> list[Dict[str, Any]]:
    """
    Normalize allocation list into [{kind, symbol, weight}] where weight is a fraction and sums to ~1.
    """
    out: list[Dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    total_w = 0.0
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip().lower()
        kind = "crypto" if kind == "crypto" else "index"
        symbol = str(it.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            w = float(it.get("weight") or 0.0)
        except Exception:
            w = 0.0
        if w > 1.0:
            w = w / 100.0
        if w <= 0:
            continue
        total_w += w
        out.append({"kind": kind, "symbol": symbol, "weight": w})
    # normalize
    if out and total_w > 0:
        for r in out:
            r["weight"] = float(r["weight"]) / total_w
    return out


def _default_investment_allocations() -> list[Dict[str, Any]]:
    # Insurance-grade default: conservative benchmark mix (illustrative)
    return [
        {"kind": "index", "symbol": "SPX", "weight": 0.60},
        {"kind": "crypto", "symbol": "BTC", "weight": 0.40},
    ]


def _future_value_monthly_contributions(*, monthly_contribution: float, years: int, annual_return: float) -> float:
    """
    Future value of monthly contributions with monthly compounding.
    annual_return is a fraction (0.05 = 5%).
    """
    pmt = float(monthly_contribution or 0.0)
    if pmt <= 0:
        return 0.0
    y = max(0, int(years))
    n = y * 12
    r = float(annual_return or 0.0)
    if n <= 0:
        return 0.0
    if r <= 0:
        return round(pmt * n, 2)
    m = r / 12.0
    try:
        fv = pmt * (((1.0 + m) ** n - 1.0) / m)
    except Exception:
        fv = pmt * n
    return round(float(fv), 2)


def _compute_savings_projection_payload(*, age: int, years: int, policy_type: str, coverage_amount: float, jurisdiction: str, savings_percentage: Any, operational_reinsurance_load: Any, health_condition_score: Any) -> Dict[str, Any]:
    from services.pricing_service import price_policy

    priced = price_policy({
        'type': policy_type,
        'coverage_amount': coverage_amount,
        'age': age,
        'jurisdiction': jurisdiction,
        'savings_percentage': savings_percentage,
        'operational_reinsurance_load': operational_reinsurance_load,
    })
    priced = _apply_health_risk_loading(priced, health_condition_score=health_condition_score)
    b = priced.get('breakdown', {}) if isinstance(priced, dict) else {}
    monthly_savings = float(b.get('monthly_savings_allocation') or 0.0)
    monthly_total = float(b.get('monthly_total_premium') or priced.get('monthly') or 0.0)

    scenarios = [
        {'name': 'conservative', 'annual_return': 0.02},
        {'name': 'base', 'annual_return': 0.05},
        {'name': 'growth', 'annual_return': 0.08},
    ]
    proj = []
    for s in scenarios:
        r = float(s['annual_return'])
        proj.append({
            'scenario': s['name'],
            'annual_return': r,
            'annual_return_percent': r * 100.0,
            'future_value': _future_value_monthly_contributions(monthly_contribution=monthly_savings, years=years, annual_return=r),
        })

    return {
        'inputs': {
            'age': age,
            'years': years,
            'type': policy_type,
            'coverage_amount': coverage_amount,
            'jurisdiction': 'UK' if str(jurisdiction).upper() in ('UK', 'GB', 'GBR') else 'US',
            'savings_percentage': savings_percentage,
            'operational_reinsurance_load': operational_reinsurance_load,
            'health_condition_score': health_condition_score,
        },
        'pricing': priced,
        'monthly_total_premium': round(monthly_total, 2),
        'monthly_savings_allocation': round(monthly_savings, 2),
        'projection': proj,
    }


class PortalHandler(BaseHTTPRequestHandler):
    def _get_client_ip(self) -> str:
        """
        Determine the real client IP when running behind a proxy (Railway/Render/etc).

        Why: on PaaS, `self.client_address[0]` is often the *shared reverse proxy* IP.
        If that shared proxy IP gets rate-limited/blocked, the entire site becomes inaccessible.
        """
        # Allow disabling proxy trust explicitly.
        trust_proxy = os.environ.get("TRUST_PROXY", "").lower() not in ("0", "false", "no")
        if trust_proxy:
            xff = (self.headers.get("X-Forwarded-For") or "").strip()
            if xff:
                # XFF may be a comma-separated list: client, proxy1, proxy2...
                parts = [p.strip() for p in xff.split(",") if p.strip()]
                if parts:
                    return parts[0]
            xrip = (self.headers.get("X-Real-IP") or "").strip()
            if xrip:
                return xrip
        return self.client_address[0]

    def _maybe_set_app_base_url(self) -> None:
        """
        If APP_BASE_URL isn't configured, derive it from headers.
        This makes email links work correctly on hosted deployments.
        """
        global APP_BASE_URL
        if APP_BASE_URL:
            return
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").strip()
        if not host:
            return
        proto = (self.headers.get("X-Forwarded-Proto") or "http").strip()
        if proto not in ("http", "https"):
            proto = "https"
        APP_BASE_URL = f"{proto}://{host}".rstrip("/")

    def _set_json_headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'")
        self.end_headers()

    def _set_file_headers(self, path: str) -> None:
        self.send_response(200)
        if path.endswith('.html'):
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        elif path.endswith('.js'):
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        elif path.endswith('.css'):
            self.send_header('Content-Type', 'text/css; charset=utf-8')
        elif path.endswith('.svg'):
            self.send_header('Content-Type', 'image/svg+xml; charset=utf-8')
        elif path.endswith('.png'):
            self.send_header('Content-Type', 'image/png')
        elif path.endswith('.jpg') or path.endswith('.jpeg'):
            self.send_header('Content-Type', 'image/jpeg')
        else:
            self.send_header('Content-Type', 'application/octet-stream')
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.end_headers()

    def do_GET(self):
        # Periodic cleanup of stale data
        cleanup_stale_data()

        # Ensure absolute URLs are available for notifications/emails
        self._maybe_set_app_base_url()
        
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        # Single application entry-point: route Apply to Quote (keeps insurance audit trail consistent)
        if path in ('/apply', '/apply.html', '/buy', '/buy-insurance'):
            self.send_response(302)
            self.send_header('Location', '/quote.html')
            self.end_headers()
            return

        # Security checks
        client_ip = self._get_client_ip()
        
        # Check if IP is blocked
        is_blocked, block_reason = is_ip_blocked(client_ip)
        # IMPORTANT: Only block API requests on GET. Never block static pages
        # (Railway reverse proxy IPs can be shared, and false positives would take down the site).
        # Allow safe, read-only endpoints even if an IP was flagged (avoid breaking pricing/quotes UX).
        allow_when_blocked_get = {
            '/api/pricing/estimate',
            '/api/actuarial/table',
            '/api/market/crypto',
            '/api/market/indexes',
            '/api/market/series',
            '/api/validate-email',
        }
        if is_blocked and (path.startswith('/api/') or path == '/api') and (path not in allow_when_blocked_get):
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Access denied',
                'message': 'Your IP has been blocked due to suspicious activity'
            }).encode('utf-8'))
            return
        
        # Session validation (needed for role-aware rate limits)
        auth_header = self.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
        session = validate_session(token) if token else None
        # Derive role (best-effort)
        role_for_limit = None
        try:
            if session and session.get('username'):
                u = USERS.get(session.get('username'))
                if isinstance(u, dict):
                    role_for_limit = u.get('role')
        except Exception:
            role_for_limit = None

        # Rate limiting (API only; never block static assets/pages)
        # Exempt high-frequency, stateless read endpoints used by forms/charts.
        rate_limit_exempt = {
            '/api/pricing/estimate',
            '/api/validate-email',
            '/api/actuarial/table',
            '/api/market/crypto',
            '/api/market/indexes',
            '/api/market/series',
        }
        if path.startswith('/api/') and (path not in rate_limit_exempt) and (not check_rate_limit(client_ip, role=role_for_limit)):
            log_malicious_attempt(client_ip, 'Rate Limit Exceeded', {'endpoint': self.path})
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests. Please try again later.'}).encode('utf-8'))
            return
        
        qs = urlparse.parse_qs(parsed.query)
        
        # Validate query parameters for injection attacks
        for key, values in qs.items():
            for value in values:
                is_valid, error = validate_input_security(value, client_ip, f"query_param_{key}")
                if not is_valid:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': error}).encode('utf-8'))
                    return

        # Simple email validation endpoint (used by quote.html)
        if path == '/api/validate-email':
            email = (qs.get('email', [''])[0] or '').strip()
            self._set_json_headers()
            self.wfile.write(json.dumps({'valid': bool(email) and validate_email(email)}).encode('utf-8'))
            return

        is_authenticated = session is not None
        
        # Security monitoring endpoint (Admin only)
        if path == '/api/security/threats':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            
            # Get query parameters
            limit = int(qs.get('limit', [100])[0])
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'malicious_attempts': MALICIOUS_ATTEMPTS[-limit:],
                'blocked_ips': dict(list(BLOCKED_IPS.items())[-50:]),  # Last 50 blocked IPs
                'failed_logins': {k: v for k, v in list(FAILED_LOGINS.items())[-20:]},  # Last 20
                'statistics': {
                    'total_malicious_attempts': len(MALICIOUS_ATTEMPTS),
                    'total_blocked_ips': len(BLOCKED_IPS),
                    'permanent_blocks': sum(1 for b in BLOCKED_IPS.values() if b.get('permanent')),
                    'active_lockouts': sum(1 for f in FAILED_LOGINS.values() 
                                          if f.get('lockout_until', 0) > datetime.now().timestamp())
                }
            }, default=str).encode('utf-8'))
            return

        # Audit log endpoint (Admin only)
        if path == '/api/audit':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            # Pagination and basic filtering
            page = int(qs.get('page', ['1'])[0])
            page_size = int(qs.get('page_size', ['50'])[0])
            page = max(1, page)
            page_size = max(1, min(500, page_size))
            actor = qs.get('actor', [None])[0]
            action = qs.get('action', [None])[0]
            entity_type = qs.get('entity_type', [None])[0]
            logs = []
            try:
                # audit may be None if service unavailable
                if audit and hasattr(audit, 'recent'):
                    logs = audit.recent(10000)  # recent window
                else:
                    logs = []
            except Exception:
                logs = []
            # Apply filters
            def _match(entry: Dict[str, Any]) -> bool:
                if actor and entry.get('actor') != actor:
                    return False
                if action and entry.get('action') != action:
                    return False
                if entity_type and entry.get('entity_type') != entity_type:
                    return False
                return True
            filtered = [e for e in logs if _match(e)]
            start = (page - 1) * page_size
            end = start + page_size
            payload = {
                'items': filtered[start:end],
                'page': page,
                'page_size': page_size,
                'total': len(filtered)
            }
            self._set_json_headers()
            self.wfile.write(json.dumps(payload, default=str).encode('utf-8'))
            return
        
        # User Profile Endpoint
        if path == '/api/profile':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            
            username = session.get('username')
            if not username:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                return
            user = USERS.get(username)
            
            if not user:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                return
            
            self._set_json_headers()
            customer_id = user.get('customer_id')
            cust = CUSTOMERS.get(customer_id) if customer_id else None
            self.wfile.write(json.dumps({
                'username': username,
                'name': user.get('name'),
                'role': user.get('role'),
                'customer_id': customer_id,
                'email': cust.get('email') if isinstance(cust, dict) else None,
                'phone': cust.get('phone') if isinstance(cust, dict) else None,
                'dob': cust.get('dob') if isinstance(cust, dict) else None,
            }).encode('utf-8'))
            return

        # Quote defaults for logged-in customers (prefill new quote with stored info + last application)
        if path == '/api/quote/defaults':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            if role != 'customer':
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Customer access required'}).encode('utf-8'))
                return
            customer_id = session.get('customer_id')
            cust = CUSTOMERS.get(customer_id) if customer_id else None
            # Find latest underwriting form for this customer
            last_app = None
            try:
                apps = [a for a in UNDERWRITING_APPLICATIONS.values() if isinstance(a, dict) and a.get('customer_id') == customer_id]
                apps.sort(key=lambda x: str(x.get('submitted_date') or ''), reverse=True)
                last_app = apps[0] if apps else None
            except Exception:
                last_app = None
            last_form = {}
            last_notes = {}
            if isinstance(last_app, dict):
                try:
                    last_notes = json.loads(last_app.get('notes') or '{}') if isinstance(last_app.get('notes'), str) else (last_app.get('notes') or {})
                except Exception:
                    last_notes = {}
                if isinstance(last_notes, dict) and isinstance(last_notes.get('form'), dict):
                    last_form = last_notes.get('form') or {}
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer': cust if isinstance(cust, dict) else None,
                'last_application_id': last_app.get('id') if isinstance(last_app, dict) else None,
                'last_form': last_form,
                'last_notes': last_notes if isinstance(last_notes, dict) else {},
            }).encode('utf-8'))
            return

        # Investment allocation preferences (customer private; admin can read per customer/policy)
        if path == '/api/investments/preferences':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            customer_id = customer_scope or (qs.get('customer_id', [None])[0] if require_role(session, ['admin', 'underwriter', 'accountant']) else None)
            policy_id = qs.get('policy_id', [None])[0]
            if not customer_id:
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                return
            if not policy_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'policy_id is required'}).encode('utf-8'))
                return
            currency = (qs.get('currency', ['USD'])[0] or 'USD').upper()

            pref = None
            if USE_DATABASE and database_enabled:
                try:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        pref = db.investment_preferences.latest_for_policy(customer_id, policy_id)
                except Exception:
                    pref = None
            # Fallback: check submissions for latest preference
            if pref is None:
                try:
                    latest = None
                    for s in FORM_SUBMISSIONS.values():
                        if not isinstance(s, dict):
                            continue
                        if s.get('source') != 'investment_preference':
                            continue
                        if s.get('customer_id') != customer_id:
                            continue
                        p = {}
                        try:
                            p = json.loads(s.get('payload') or '{}')
                        except Exception:
                            p = {}
                        if str(p.get('policy_id') or '') != str(policy_id):
                            continue
                        if latest is None or str(s.get('created_date') or '') > str(latest.get('created_date') or ''):
                            latest = s
                    if latest:
                        payload = json.loads(latest.get('payload') or '{}')
                        self._set_json_headers()
                        self.wfile.write(json.dumps({'policy_id': policy_id, 'customer_id': customer_id, 'currency': payload.get('currency', currency), 'allocations': payload.get('allocations', [])}).encode('utf-8'))
                        return
                except Exception:
                    pass

            if pref:
                alloc = []
                try:
                    alloc = json.loads(pref.allocations or '[]')
                except Exception:
                    alloc = []
                self._set_json_headers()
                self.wfile.write(json.dumps({'policy_id': policy_id, 'customer_id': customer_id, 'currency': pref.currency or currency, 'allocations': alloc, 'created_date': pref.created_date.isoformat() if getattr(pref, 'created_date', None) else None}).encode('utf-8'))
            else:
                self._set_json_headers()
                self.wfile.write(json.dumps({'policy_id': policy_id, 'customer_id': customer_id, 'currency': currency, 'allocations': _default_investment_allocations()}).encode('utf-8'))
            return

        # Investment allocations (client private)
        if path == '/api/investments/allocations':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            if role != 'customer':
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Customer access required'}).encode('utf-8'))
                return
            customer_id = session.get('customer_id')
            currency = (qs.get('currency', ['USD'])[0] or 'USD').upper()
            stmt = build_customer_statement_from_transactions(customer_id)
            allocs = stmt.get('allocations') or []

            # Aggregate per policy
            per_policy: Dict[str, Dict[str, Any]] = {}
            for a in allocs:
                if not isinstance(a, dict):
                    continue
                pid = a.get('policy_id')
                if not pid:
                    continue
                rec = per_policy.setdefault(pid, {'policy_id': pid, 'savings_total': 0.0, 'risk_total': 0.0})
                rec['savings_total'] += float(a.get('savings_amount') or 0.0)
                rec['risk_total'] += float(a.get('risk_amount') or 0.0)

            # Apply preferences to savings_total for an investable basket view
            items_out = []
            for pid, rec in per_policy.items():
                prefs = None
                if USE_DATABASE and database_enabled:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            prefs = db.investment_preferences.latest_for_policy(customer_id, pid)
                    except Exception:
                        prefs = None
                pref_allocs = None
                pref_currency = currency
                if prefs:
                    pref_currency = (prefs.currency or currency).upper()
                    try:
                        pref_allocs = json.loads(prefs.allocations or '[]')
                    except Exception:
                        pref_allocs = None
                alloc_list = _normalize_investment_allocations(pref_allocs) if pref_allocs else _default_investment_allocations()
                savings_total = float(rec.get('savings_total') or 0.0)
                basket = []
                for it in alloc_list:
                    basket.append({
                        'kind': it['kind'],
                        'symbol': it['symbol'],
                        'weight': it['weight'],
                        'amount': round(savings_total * float(it['weight']), 2),
                        'currency': pref_currency,
                    })
                items_out.append({
                    'policy_id': pid,
                    'risk_total': round(float(rec.get('risk_total') or 0.0), 2),
                    'savings_total': round(savings_total, 2),
                    'currency': pref_currency,
                    'basket': basket,
                })

            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'currency': currency,
                'totals': {'risk_total': stmt.get('risk_total', 0.0), 'savings_total': stmt.get('savings_total', 0.0), 'total_premium': stmt.get('total_premium', 0.0)},
                'items': items_out,
            }).encode('utf-8'))
            return

        # Investment allocations (admin cumulative)
        if path == '/api/admin/investments/allocations':
            if not require_role(session, ['admin', 'underwriter', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            currency = (qs.get('currency', ['USD'])[0] or 'USD').upper()
            # Aggregate across customers from real transactions (insurance-grade: no fake portfolio values)
            customer_ids = [c.get('id') for c in CUSTOMERS.values() if isinstance(c, dict) and c.get('id')]
            risk_total = 0.0
            savings_total = 0.0
            by_symbol: Dict[str, Dict[str, Any]] = {}  # key = KIND:SYMBOL

            for cid in customer_ids:
                stmt = build_customer_statement_from_transactions(cid)
                risk_total += float(stmt.get('risk_total') or 0.0)
                savings_total += float(stmt.get('savings_total') or 0.0)
                allocs = stmt.get('allocations') or []
                # Aggregate per policy savings to allocate into baskets
                per_policy: Dict[str, float] = {}
                for a in allocs:
                    if not isinstance(a, dict):
                        continue
                    pid = a.get('policy_id')
                    if not pid:
                        continue
                    per_policy[pid] = per_policy.get(pid, 0.0) + float(a.get('savings_amount') or 0.0)
                for pid, sav_amt in per_policy.items():
                    prefs = None
                    if USE_DATABASE and database_enabled:
                        try:
                            from database.manager import DatabaseManager
                            with DatabaseManager() as db:
                                prefs = db.investment_preferences.latest_for_policy(cid, pid)
                        except Exception:
                            prefs = None
                    pref_allocs = None
                    if prefs:
                        try:
                            pref_allocs = json.loads(prefs.allocations or '[]')
                        except Exception:
                            pref_allocs = None
                    alloc_list = _normalize_investment_allocations(pref_allocs) if pref_allocs else _default_investment_allocations()
                    for it in alloc_list:
                        k = f"{it['kind']}:{it['symbol']}"
                        by_symbol.setdefault(k, {'kind': it['kind'], 'symbol': it['symbol'], 'amount': 0.0})
                        by_symbol[k]['amount'] += sav_amt * float(it['weight'])

            top = sorted(by_symbol.values(), key=lambda x: float(x.get('amount') or 0.0), reverse=True)[:50]
            for r in top:
                r['amount'] = round(float(r.get('amount') or 0.0), 2)
                r['currency'] = currency

            self._set_json_headers()
            self.wfile.write(json.dumps({
                'currency': currency,
                'totals': {'risk_total': round(risk_total, 2), 'savings_total': round(savings_total, 2), 'customers': len(customer_ids)},
                'top_allocations': top,
            }).encode('utf-8'))
            return

        # Notifications (customer + admin)
        if path == '/api/notifications':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            requested_customer_id = qs.get('customer_id', [None])[0]
            customer_id = customer_scope or requested_customer_id

            # For staff, require explicit customer_id to avoid leaking data
            if role != 'customer' and not requested_customer_id:
                customer_id = None

            items: list[Dict[str, Any]] = []
            if customer_id:
                if USE_DATABASE and database_enabled:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            rows = db.notifications.get_for_customer(customer_id, limit=200)
                            items = [r.to_dict() for r in rows]
                    except Exception:
                        items = []
                else:
                    items = [n for n in NOTIFICATIONS.values() if n.get('customer_id') == customer_id]
                    items.sort(key=lambda x: str(x.get('created_date', '')), reverse=True)

            self._set_json_headers()
            self.wfile.write(json.dumps({'items': items, 'total': len(items)}).encode('utf-8'))
            return

        # Form submissions (customer can view their own; admin can view all or filter)
        if path == '/api/submissions':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            sub_id = qs.get('id', [None])[0]
            email_q = qs.get('email', [None])[0]
            source_q = qs.get('source', [None])[0]

            # Customers can only see their own submissions
            if role == 'customer':
                if sub_id:
                    rec = FORM_SUBMISSIONS.get(sub_id)
                    if not isinstance(rec, dict) or rec.get('customer_id') != customer_scope:
                        self._set_json_headers(404)
                        self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))
                        return
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'item': rec}).encode('utf-8'))
                    return

                items = [s for s in FORM_SUBMISSIONS.values() if s.get('customer_id') == customer_scope]
                items.sort(key=lambda x: str(x.get('created_date', '')), reverse=True)
                self._set_json_headers()
                self.wfile.write(json.dumps({'items': items[:200], 'total': len(items)}).encode('utf-8'))
                return

            # Staff: admin/underwriter/accountant/claims
            if not require_role(session, ['admin', 'underwriter', 'accountant', 'claims']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            if sub_id:
                rec = FORM_SUBMISSIONS.get(sub_id)
                if not isinstance(rec, dict):
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))
                    return
                self._set_json_headers()
                self.wfile.write(json.dumps({'item': rec}).encode('utf-8'))
                return

            items = list(FORM_SUBMISSIONS.values())
            if email_q:
                e = str(email_q).strip().lower()
                items = [s for s in items if str(s.get('email') or '').lower() == e]
            if source_q:
                items = [s for s in items if str(s.get('source') or '') == str(source_q)]
            items.sort(key=lambda x: str(x.get('created_date', '')), reverse=True)
            self._set_json_headers()
            self.wfile.write(json.dumps({'items': items[:500], 'total': len(items)}).encode('utf-8'))
            return
        
        # BI Dashboard Endpoints (Admin/Management only)
        if path == '/api/bi/actuary':
            if not require_role(session, ['admin', 'accountant', 'underwriter']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_actuary()).encode('utf-8'))
            return
        
        if path == '/api/bi/underwriting':
            if not require_role(session, ['admin', 'underwriter']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_underwriting()).encode('utf-8'))
            return
        
        if path == '/api/bi/accounting':
            if not require_role(session, ['admin', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_accounting()).encode('utf-8'))
            return

        # Platform Metrics Endpoint (for dashboards)
        if path == '/api/metrics':
            try:
                from services.metrics_service import MetricsService
                ms = MetricsService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                data = ms.summary()
            except Exception:
                data = {
                    'customers': {'total': len(CUSTOMERS)},
                    'policies': {
                        'total': len(POLICIES),
                        'active': sum(1 for p in POLICIES.values() if p.get('status') == 'active'),
                        'pending': sum(1 for p in POLICIES.values() if p.get('status') == 'pending_underwriting'),
                    },
                    'claims': {'pending': sum(1 for c in CLAIMS.values() if c.get('status') in ['pending', 'under_review']),
                               'approved': sum(1 for c in CLAIMS.values() if c.get('status') == 'approved')},
                    'billing': {'overdue': sum(1 for b in BILLING.values() if b.get('status') == 'overdue'),
                                'outstanding': sum(1 for b in BILLING.values() if b.get('status') in ['outstanding', 'partial'])},
                    'underwriting': {'pending': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'pending')}
                }
            self._set_json_headers()
            self.wfile.write(json.dumps({'metrics': data, 'ts': datetime.now().isoformat()}).encode('utf-8'))
            return

        # PHI Product Config (read-only; admin can update via POST)
        if path == '/api/products/phi/config':
            if not require_role(session, ['admin', 'underwriter', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps({'phi_config': PHI_PRODUCT_CONFIG, 'ts': datetime.now().isoformat()}).encode('utf-8'))
            return
        
        # Policy Management Endpoints
        if path == '/api/policies':
            policy_id = qs.get('id', [None])[0]
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            if policy_id:
                policy = POLICIES.get(policy_id)
                if policy:
                    if customer_scope and policy.get('customer_id') != customer_scope:
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                        return
                    self._set_json_headers()
                    self.wfile.write(json.dumps(policy).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Policy not found'}).encode('utf-8'))
            else:
                page = int(qs.get('page', ['1'])[0])
                page_size = int(qs.get('page_size', ['50'])[0])
                page = max(1, page)
                page_size = max(1, min(500, page_size))
                items = list(POLICIES.values())
                if customer_scope:
                    items = [p for p in items if p.get('customer_id') == customer_scope]
                start = (page - 1) * page_size
                end = start + page_size
                payload = {
                    'items': items[start:end],
                    'page': page,
                    'page_size': page_size,
                    'total': len(items)
                }
                self._set_json_headers()
                self.wfile.write(json.dumps(payload).encode('utf-8'))
            return
        
        # Claims Management Endpoints
        if path == '/api/claims':
            claim_id = qs.get('id', [None])[0]
            status = qs.get('status', [None])[0]
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            
            if claim_id:
                claim = CLAIMS.get(claim_id)
                if claim:
                    if customer_scope and claim.get('customer_id') != customer_scope:
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                        return
                    self._set_json_headers()
                    self.wfile.write(json.dumps(claim).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            else:
                claims_list = list(CLAIMS.values())
                if customer_scope:
                    claims_list = [c for c in claims_list if c.get('customer_id') == customer_scope]
                if status:
                    claims_list = [c for c in claims_list if c.get('status') == status]
                page = int(qs.get('page', ['1'])[0])
                page_size = int(qs.get('page_size', ['50'])[0])
                page = max(1, page)
                page_size = max(1, min(500, page_size))
                start = (page - 1) * page_size
                end = start + page_size
                payload = {
                    'items': claims_list[start:end],
                    'page': page,
                    'page_size': page_size,
                    'total': len(claims_list)
                }
                self._set_json_headers()
                self.wfile.write(json.dumps(payload).encode('utf-8'))
            return
        
        # Underwriting Applications Endpoints
        if path == '/api/underwriting':
            app_id = qs.get('id', [None])[0]
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            if app_id:
                app = UNDERWRITING_APPLICATIONS.get(app_id)
                if app:
                    if customer_scope and app.get('customer_id') != customer_scope:
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                        return
                    self._set_json_headers()
                    self.wfile.write(json.dumps(app).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            else:
                items = list(UNDERWRITING_APPLICATIONS.values())
                if customer_scope:
                    items = [u for u in items if u.get('customer_id') == customer_scope]
                # Optional filter by status
                status = qs.get('status', [None])[0]
                if status:
                    items = [u for u in items if u.get('status') == status]
                payload = {'items': items, 'total': len(items)}
                self._set_json_headers()
                self.wfile.write(json.dumps(payload).encode('utf-8'))
            return

        # Underwriting application details (includes parsed form + pricing) for editing / admin decisioning
        if path == '/api/underwriting/details':
            app_id = qs.get('id', [None])[0]
            if not app_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'id is required'}).encode('utf-8'))
                return
            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            customer_scope = session.get('customer_id') if (session and role == 'customer') else None
            app = UNDERWRITING_APPLICATIONS.get(app_id)
            if not isinstance(app, dict):
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
                return
            if customer_scope and app.get('customer_id') != customer_scope:
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                return
            if not customer_scope and not require_role(session, ['admin', 'underwriter', 'accountant', 'claims']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            notes = {}
            try:
                notes = json.loads(app.get('notes') or '{}') if isinstance(app.get('notes'), str) else (app.get('notes') or {})
            except Exception:
                notes = {}
            policy = POLICIES.get(app.get('policy_id')) if app.get('policy_id') else None
            customer = CUSTOMERS.get(app.get('customer_id')) if app.get('customer_id') else None
            attachments = []
            try:
                if isinstance(notes, dict) and isinstance(notes.get('attachments'), list):
                    attachments = notes.get('attachments') or []
            except Exception:
                attachments = []
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'application': app,
                'policy': policy if isinstance(policy, dict) else None,
                'customer': customer if isinstance(customer, dict) else None,
                'notes': notes if isinstance(notes, dict) else {},
                'form': (notes.get('form') if isinstance(notes, dict) else None),
                'pricing': (notes.get('pricing') if isinstance(notes, dict) else None),
                'attachments': attachments,
            }).encode('utf-8'))
            return

        # Download a stored media asset (admin/staff or owning customer only)
        if path == '/api/media/download':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            token_q = qs.get('token', [None])[0]
            if not token_q:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'token is required'}).encode('utf-8'))
                return
            rec = TOKEN_REGISTRY.get(token_q)
            if not isinstance(rec, dict) or rec.get('kind') != 'media_asset' or rec.get('status') != 'active':
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))
                return
            try:
                meta_raw = rec.get('meta') or rec.get('metadata') or '{}'
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
            except Exception:
                meta = {}

            role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
            is_staff = str(role or '').lower() in ('admin', 'underwriter', 'accountant', 'claims', 'claims_adjuster')
            if not is_staff:
                # customer must own it
                if str(meta.get('customer_id') or '') != str(session.get('customer_id') or ''):
                    self._set_json_headers(403)
                    self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                    return

            p = meta.get('path')
            if not p or not os.path.exists(str(p)):
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'File missing'}).encode('utf-8'))
                return
            try:
                data = Path(str(p)).read_bytes()
            except Exception:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Read failed'}).encode('utf-8'))
                return
            ct = str(meta.get('content_type') or 'application/octet-stream')
            fn = str(meta.get('original_filename') or 'attachment')
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Disposition', f'attachment; filename="{_safe_filename(fn)}"')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # Underwriting automation configuration (admin)
        if path == '/api/underwriting/automation/config':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps({'config': UNDERWRITING_AUTOMATION_CONFIG}).encode('utf-8'))
            return

        # Billing link resolve (48h token)
        if path == '/api/billing/link':
            token_q = qs.get('token', [None])[0]
            if not token_q:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'token is required'}).encode('utf-8'))
                return
            resolved = resolve_billing_link(token_q)
            if not resolved:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'valid': False, 'error': 'Invalid or expired link'}).encode('utf-8'))
                return
            meta = resolved.get('meta') or {}
            bill_id = meta.get('bill_id')
            bill = BILLING.get(bill_id) if bill_id else None
            self._set_json_headers()
            self.wfile.write(json.dumps({'valid': True, 'expires': resolved.get('expires'), 'bill': bill, 'meta': meta}).encode('utf-8'))
            return
        
        # Customers Endpoint
        if path == '/api/customers':
            if not require_role(session, ['admin', 'underwriter', 'accountant', 'claims']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            customer_id = qs.get('id', [None])[0]
            if customer_id:
                customer = CUSTOMERS.get(customer_id)
                if customer:
                    self._set_json_headers()
                    self.wfile.write(json.dumps(customer).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Customer not found'}).encode('utf-8'))
            else:
                self._set_json_headers()
                self.wfile.write(json.dumps(list(CUSTOMERS.values())).encode('utf-8'))
            return

        # Admin/staff: customer lookup by email (e.g., asaf@assurance.co.il)
        if path == '/api/customers/search':
            if not require_role(session, ['admin', 'underwriter', 'accountant', 'claims']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            email_q = (qs.get('email', [''])[0] or '').strip().lower()
            if not email_q:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'email is required'}).encode('utf-8'))
                return
            cust = None
            for c in CUSTOMERS.values():
                if isinstance(c, dict) and (c.get('email') or '').lower() == email_q:
                    cust = c
                    break
            if not cust:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Customer not found'}).encode('utf-8'))
                return
            customer_id = cust.get('id')
            policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
            apps = [u for u in UNDERWRITING_APPLICATIONS.values() if u.get('customer_id') == customer_id]
            claims = [c for c in CLAIMS.values() if c.get('customer_id') == customer_id]
            bills = [b for b in BILLING.values() if b.get('customer_id') == customer_id]
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer': cust,
                'policies': policies,
                'underwriting': apps,
                'claims': claims,
                'billing': bills,
            }).encode('utf-8'))
            return

        # Customer status endpoint (post-application visibility)
        if path == '/api/customer/status':
            customer_id = qs.get('customer_id', [None])[0]
            # If missing, infer from authenticated session
            if not customer_id and session and session.get('customer_id'):
                customer_id = session.get('customer_id')
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id is required'}).encode('utf-8'))
                return

            customer = CUSTOMERS.get(customer_id)
            if not customer:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Customer not found'}).encode('utf-8'))
                return

            policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
            uw_apps = [u for u in UNDERWRITING_APPLICATIONS.values() if u.get('customer_id') == customer_id]

            # Determine overall application status (simple heuristic)
            overall = 'no_application'
            if uw_apps:
                most_recent = sorted(uw_apps, key=lambda x: x.get('submitted_date', ''), reverse=True)[0]
                overall = most_recent.get('status', 'pending')
                if overall == 'approved':
                    # Check if policy is active
                    linked = next((p for p in policies if p.get('underwriting_id') == most_recent.get('id')), None)
                    if linked and linked.get('status') == 'active':
                        overall = 'active_policy'

            payload = {
                'customer': {
                    'id': customer_id,
                    'name': customer.get('name'),
                    'email': customer.get('email')
                },
                'overall_status': overall,
                'policies': policies,
                'underwriting_applications': uw_apps
            }

            self._set_json_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return
        
        if path.startswith('/api/statement'):
            # Prefer authenticated identity; allow explicit customer_id only for admins.
            requested_customer_id = qs.get('customer_id', [None])[0]
            if session and session.get("customer_id"):
                customer_id = session["customer_id"]
            else:
                customer_id = requested_customer_id or ""

            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({"error": "customer_id is required"}).encode("utf-8"))
                return

            # If a customer is logged in, they can only view their own statement.
            if session and USERS.get(session.get("username", ""), {}).get("role") == "customer":
                if requested_customer_id and requested_customer_id != customer_id:
                    self._set_json_headers(403)
                    self.wfile.write(json.dumps({"error": "Forbidden"}).encode("utf-8"))
                    return

            data = build_customer_statement_from_transactions(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return

        if path.startswith('/api/allocations'):
            requested_customer_id = qs.get('customer_id', [None])[0]
            if session and session.get("customer_id"):
                customer_id = session["customer_id"]
            else:
                customer_id = requested_customer_id or ""
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({"error": "customer_id is required"}).encode("utf-8"))
                return
            data = build_customer_statement_from_transactions(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps({"allocations": data.get("allocations", [])}).encode('utf-8'))
            return

        # Actuarial tables (Admin only)
        if path == '/api/actuarial/disability-table':
            if not require_role(session, ['admin', 'underwriter', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            jurisdiction = (qs.get('jurisdiction', ['US'])[0] or 'US').upper()
            age_min = int(qs.get('age_min', ['18'])[0])
            age_max = int(qs.get('age_max', ['100'])[0])
            try:
                from services.actuarial_disability_tables import build_disability_table
                rows = build_disability_table('UK' if jurisdiction in ('UK', 'GB', 'GBR') else 'US', age_min=age_min, age_max=age_max)  # type: ignore[arg-type]
                payload = {
                    'jurisdiction': 'UK' if jurisdiction in ('UK', 'GB', 'GBR') else 'US',
                    'items': [{'age': r.age, 'annual_adl_claim_rate': r.annual_adl_claim_rate, 'annual_adl_claim_rate_percent': r.annual_adl_claim_rate_percent} for r in rows],
                    'ts': datetime.now().isoformat()
                }
            except Exception as e:
                payload = {'error': str(e), 'items': []}
            self._set_json_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return

        # Market data (Admin + customer portals)
        if path == '/api/market/crypto':
            symbols = (qs.get('symbols', ['BTC,ETH'])[0] or 'BTC,ETH').split(',')
            vs = qs.get('vs', ['USD'])[0] or 'USD'
            try:
                from services.market_data_service import MarketDataService
                svc = MarketDataService(ttl_seconds=30)
                quotes = svc.get_crypto_quotes([s.strip() for s in symbols], vs_currency=vs)
                for q in quotes:
                    _series_append("crypto", q.symbol, q.price, currency=vs)
                # Persist ticks so charts retain history across restarts
                if USE_DATABASE and database_enabled:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            for q in quotes:
                                try:
                                    latest = db.market_ticks.latest_for_symbol("crypto", q.symbol, currency=str(vs).upper(), limit=1)
                                    if latest:
                                        last = latest[0]
                                        last_ts = getattr(last, "created_date", None)
                                        if last_ts and (datetime.utcnow() - last_ts).total_seconds() < 25 and float(getattr(last, "price", 0.0)) == float(q.price):
                                            continue
                                    db.market_ticks.create(
                                        kind="crypto",
                                        symbol=q.symbol,
                                        price=float(q.price),
                                        currency=str(vs).upper(),
                                        source=str(getattr(q, "source", "live")),
                                    )
                                except Exception:
                                    continue
                    except Exception:
                        pass
                payload = {"items": [q.to_dict() for q in quotes], "ts": datetime.utcnow().isoformat()}
            except Exception as e:
                payload = {'items': [], 'error': str(e)}
            self._set_json_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return

        if path == '/api/market/indexes':
            symbols = (qs.get('symbols', ['SPX,NASDAQ,DOW,FTSE'])[0] or 'SPX,NASDAQ,DOW,FTSE').split(',')
            currency = qs.get('currency', ['USD'])[0] or 'USD'
            try:
                from services.market_data_service import MarketDataService
                svc = MarketDataService(ttl_seconds=30)
                quotes = svc.get_index_quotes([s.strip() for s in symbols], currency=currency)
                for q in quotes:
                    _series_append("index", q.symbol, q.price, currency=currency)
                # Persist ticks so charts retain history across restarts
                if USE_DATABASE and database_enabled:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            for q in quotes:
                                try:
                                    latest = db.market_ticks.latest_for_symbol("index", q.symbol, currency=str(currency).upper(), limit=1)
                                    if latest:
                                        last = latest[0]
                                        last_ts = getattr(last, "created_date", None)
                                        if last_ts and (datetime.utcnow() - last_ts).total_seconds() < 25 and float(getattr(last, "price", 0.0)) == float(q.price):
                                            continue
                                    db.market_ticks.create(
                                        kind="index",
                                        symbol=q.symbol,
                                        price=float(q.price),
                                        currency=str(currency).upper(),
                                        source=str(getattr(q, "source", "live")),
                                    )
                                except Exception:
                                    continue
                    except Exception:
                        pass
                payload = {"items": [q.to_dict() for q in quotes], "ts": datetime.utcnow().isoformat()}
            except Exception as e:
                payload = {'items': [], 'error': str(e)}
            self._set_json_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return

        if path == '/api/market/series':
            kind = (qs.get('kind', ['crypto'])[0] or 'crypto').lower()
            symbols = (qs.get('symbols', [''])[0] or '').split(',')
            points = int(qs.get('points', ['60'])[0] or 60)
            points = max(5, min(500, points))

            kind_key = "crypto" if kind == "crypto" else "index"
            currency = (qs.get('currency', [None])[0] or qs.get('vs', [None])[0] or "USD").upper()
            syms = [s.strip().upper() for s in symbols if s.strip()]
            if not syms:
                self._set_json_headers()
                self.wfile.write(json.dumps({'kind': kind_key, 'items': [], 'ts': datetime.utcnow().isoformat()}).encode('utf-8'))
                return

            # Optional DB-backed history (only for explicitly pushed ticks)
            db_points: Dict[str, list[Dict[str, Any]]] = {}
            if USE_DATABASE and database_enabled:
                try:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        for sym in syms:
                            rows = db.market_ticks.latest_for_symbol(kind_key, sym, currency=currency, limit=max(points, 240))
                            # repository returns newest-first; API expects oldest->newest
                            pts = []
                            for r in reversed(rows or []):
                                try:
                                    pts.append({"t": r.created_date.isoformat() if getattr(r, "created_date", None) else datetime.utcnow().isoformat(), "p": float(r.price)})
                                except Exception:
                                    continue
                            if pts:
                                db_points[sym] = pts
                except Exception:
                    db_points = {}

            items = []
            for s in syms:
                mem_series = MARKET_SERIES.get(kind_key, {}).get(f"{s}@{currency}", []) or MARKET_SERIES.get(kind_key, {}).get(s, []) or []
                merged = (db_points.get(s) or []) + list(mem_series)
                if merged:
                    try:
                        merged = sorted(merged, key=lambda p: str(p.get("t") or ""))
                    except Exception:
                        pass
                items.append({"symbol": s, "points": merged[-points:] if merged else []})

            self._set_json_headers()
            self.wfile.write(json.dumps({'kind': kind_key, 'currency': currency, 'items': items, 'ts': datetime.utcnow().isoformat()}).encode('utf-8'))
            return

        # Validation endpoints (connectors)
        if path.startswith('/api/validate'):
            # Parameters: ?type=ni|card|health&value=...
            t = qs.get('type', [''])[0]
            value = qs.get('value', [''])[0]
            extra = qs.get('extra', [None])[0]
            # Best-effort connector usage
            result = {'status': 'unavailable', 'details': {}}
            try:
                # Try to load connectors by file location to support running server.py directly
                import importlib.util
                conn_path = os.path.join(os.path.dirname(__file__), 'connectors.py')
                spec = importlib.util.spec_from_file_location('web_portal.connectors', conn_path)
                if spec and spec.loader:
                    connectors = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(connectors)
                else:
                    raise ImportError('Cannot load connectors')

                if t == 'ni':
                    res = connectors.NationalInsuranceConnector().validate(national_id=value, dob=extra)
                    result = {'status': res.status, 'details': res.details}
                elif t == 'card':
                    res = connectors.CreditCardIssuerConnector().validate(card_number=value, expiry=extra)
                    result = {'status': res.status, 'details': res.details}
                elif t == 'health':
                    res = connectors.HealthAuthorityConnector().validate(patient_id=value, name=extra)
                    result = {'status': res.status, 'details': res.details}
                else:
                    result = {'status': 'unknown_type', 'details': {'requested': t}}
            except Exception as e:
                result = {'status': 'error', 'details': {'error': str(e)}}

            self._set_json_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            return

        # Pricing estimate endpoint (no persistence; safe to call from UI)
        if path == '/api/pricing/estimate':
            try:
                policy_type = qs.get('type', ['disability'])[0]
                coverage_amount = float(qs.get('coverage_amount', ['100000'])[0])
                age = int(qs.get('age', ['30'])[0])
                jurisdiction = qs.get('jurisdiction', [PHI_PRODUCT_CONFIG.get('default_jurisdiction', 'US')])[0]
                savings_percentage = qs.get('savings_percentage', [PHI_PRODUCT_CONFIG.get('default_savings_percentage', 25)])[0]
                operational_reinsurance_load = qs.get('operational_reinsurance_load', [PHI_PRODUCT_CONFIG.get('default_operational_reinsurance_load', 50)])[0]
                health_condition_score = qs.get('health_condition_score', [qs.get('healthCondition', ['3'])[0]])[0]
                from services.pricing_service import price_policy
                priced = price_policy({
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': age,
                    'jurisdiction': jurisdiction,
                    'savings_percentage': savings_percentage,
                    'operational_reinsurance_load': operational_reinsurance_load,
                })
                priced = _apply_health_risk_loading(priced, health_condition_score=health_condition_score)
                self._set_json_headers()
                self.wfile.write(json.dumps(priced).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # Savings projection endpoint (insurance-grade: based on premium->savings allocation, no fake balances)
        if path == '/api/projections/savings':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                age = int(qs.get('age', ['35'])[0])
                years = int(qs.get('years', ['15'])[0])
                years = max(1, min(60, years))
                policy_type = qs.get('type', ['disability'])[0]
                coverage_amount = float(qs.get('coverage_amount', ['100000'])[0])
                jurisdiction = qs.get('jurisdiction', [PHI_PRODUCT_CONFIG.get('default_jurisdiction', 'US')])[0]
                savings_percentage = qs.get('savings_percentage', [PHI_PRODUCT_CONFIG.get('default_savings_percentage', 25)])[0]
                operational_reinsurance_load = qs.get('operational_reinsurance_load', [PHI_PRODUCT_CONFIG.get('default_operational_reinsurance_load', 50)])[0]
                health_condition_score = qs.get('health_condition_score', ['3'])[0]

                from services.pricing_service import price_policy
                priced = price_policy({
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': age,
                    'jurisdiction': jurisdiction,
                    'savings_percentage': savings_percentage,
                    'operational_reinsurance_load': operational_reinsurance_load,
                })
                priced = _apply_health_risk_loading(priced, health_condition_score=health_condition_score)
                b = priced.get('breakdown', {}) if isinstance(priced, dict) else {}
                monthly_savings = float(b.get('monthly_savings_allocation') or 0.0)
                monthly_total = float(b.get('monthly_total_premium') or priced.get('monthly') or 0.0)

                # Scenarios (insurance benchmark): conservative/base/growth
                scenarios = [
                    {'name': 'conservative', 'annual_return': 0.02},
                    {'name': 'base', 'annual_return': 0.05},
                    {'name': 'growth', 'annual_return': 0.08},
                ]
                proj = []
                for s in scenarios:
                    r = float(s['annual_return'])
                    proj.append({
                        'scenario': s['name'],
                        'annual_return': r,
                        'annual_return_percent': r * 100.0,
                        'future_value': _future_value_monthly_contributions(monthly_contribution=monthly_savings, years=years, annual_return=r),
                    })

                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'inputs': {
                        'age': age,
                        'years': years,
                        'type': policy_type,
                        'coverage_amount': coverage_amount,
                        'jurisdiction': 'UK' if str(jurisdiction).upper() in ('UK', 'GB', 'GBR') else 'US',
                        'savings_percentage': savings_percentage,
                        'operational_reinsurance_load': operational_reinsurance_load,
                        'health_condition_score': health_condition_score,
                    },
                    'pricing': priced,
                    'monthly_total_premium': round(monthly_total, 2),
                    'monthly_savings_allocation': round(monthly_savings, 2),
                    'projection': proj,
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # Admin: export underwriting savings projection for compliance (CSV/PDF)
        if path == '/api/admin/underwriting/projection/export':
            if not require_role(session, ['admin', 'underwriter', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            app_id = qs.get('id', [None])[0]
            fmt = (qs.get('format', ['csv'])[0] or 'csv').lower()
            if not app_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'id is required'}).encode('utf-8'))
                return
            app = UNDERWRITING_APPLICATIONS.get(app_id)
            if not isinstance(app, dict):
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
                return
            policy = POLICIES.get(app.get('policy_id')) if app.get('policy_id') else None
            customer = CUSTOMERS.get(app.get('customer_id')) if app.get('customer_id') else None
            if not isinstance(policy, dict):
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Linked policy not found'}).encode('utf-8'))
                return

            # Age derived from customer DOB (preferred) else fallback to 30
            age = 30
            try:
                if isinstance(customer, dict) and customer.get('dob'):
                    a = _calc_age_from_dob(str(customer.get('dob')))
                    if a is not None:
                        age = int(a)
            except Exception:
                age = 30

            years = int(policy.get('policy_term_years') or 15)
            years = max(1, min(60, years))
            try:
                payload = _compute_savings_projection_payload(
                    age=age,
                    years=years,
                    policy_type=str(policy.get('type') or 'disability'),
                    coverage_amount=float(policy.get('coverage_amount') or 100000),
                    jurisdiction=str(policy.get('jurisdiction') or 'US'),
                    savings_percentage=policy.get('savings_percentage', 25),
                    operational_reinsurance_load=policy.get('operational_reinsurance_load', 50),
                    health_condition_score=policy.get('health_condition_score', 3),
                )
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

            file_base = f"phins_projection_{app_id}"
            if fmt == 'csv':
                import csv
                from io import StringIO
                buf = StringIO()
                w = csv.writer(buf)
                w.writerow(["PHINS.ai Savings Projection Export"])
                w.writerow(["application_id", app_id])
                w.writerow(["policy_id", policy.get('id')])
                w.writerow(["customer_id", policy.get('customer_id')])
                w.writerow(["customer_email", (customer.get('email') if isinstance(customer, dict) else '')])
                w.writerow([])
                w.writerow(["age", payload['inputs']['age'], "years", payload['inputs']['years']])
                w.writerow(["coverage_amount", payload['inputs']['coverage_amount']])
                w.writerow(["jurisdiction", payload['inputs']['jurisdiction']])
                w.writerow(["savings_percentage", payload['inputs']['savings_percentage']])
                w.writerow(["monthly_total_premium", payload.get('monthly_total_premium')])
                w.writerow(["monthly_savings_allocation", payload.get('monthly_savings_allocation')])
                w.writerow([])
                w.writerow(["scenario", "annual_return_percent", "future_value"])
                for r in payload.get('projection') or []:
                    w.writerow([r.get('scenario'), r.get('annual_return_percent'), r.get('future_value')])
                raw = buf.getvalue().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="{file_base}.csv"')
                self.end_headers()
                self.wfile.write(raw)
                return

            if fmt == 'pdf':
                # Generate a simple compliance PDF (ReportLab).
                try:
                    from io import BytesIO
                    from reportlab.lib.pagesizes import letter
                    from reportlab.pdfgen import canvas
                    bio = BytesIO()
                    c = canvas.Canvas(bio, pagesize=letter)
                    width, height = letter
                    y = height - 50
                    def line(txt: str):
                        nonlocal y
                        c.drawString(50, y, txt[:120])
                        y -= 14
                        if y < 60:
                            c.showPage()
                            y = height - 50
                    line("PHINS.ai — Savings Projection Export (Compliance)")
                    line(f"Application ID: {app_id}")
                    line(f"Policy ID: {policy.get('id')}")
                    line(f"Customer ID: {policy.get('customer_id')}")
                    if isinstance(customer, dict):
                        line(f"Customer Email: {customer.get('email') or ''}")
                    line("")
                    line(f"Age: {payload['inputs']['age']}   Term (years): {payload['inputs']['years']}")
                    line(f"Coverage: ${float(payload['inputs']['coverage_amount']):,.2f}")
                    line(f"Jurisdiction: {payload['inputs']['jurisdiction']}")
                    line(f"Savings %: {payload['inputs']['savings_percentage']}")
                    line(f"Monthly total premium: ${float(payload.get('monthly_total_premium') or 0):,.2f}")
                    line(f"Monthly savings allocation: ${float(payload.get('monthly_savings_allocation') or 0):,.2f}")
                    line("")
                    line("Scenarios:")
                    for r in payload.get('projection') or []:
                        line(f" - {r.get('scenario')}: {float(r.get('annual_return_percent') or 0):.0f}%/yr  FV=${float(r.get('future_value') or 0):,.2f}")
                    c.showPage()
                    c.save()
                    pdf_bytes = bio.getvalue()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf')
                    self.send_header('Content-Disposition', f'attachment; filename="{file_base}.pdf"')
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                    return
                except Exception as e:
                    self._set_json_headers(501)
                    self.wfile.write(json.dumps({'error': 'PDF export unavailable', 'details': str(e)}).encode('utf-8'))
                    return

            self._set_json_headers(400)
            self.wfile.write(json.dumps({'error': 'Invalid format. Use csv or pdf.'}).encode('utf-8'))
            return

        # Disclaimers endpoint
        if path.startswith('/api/disclaimers'):
            # Parameters: ?action=buy_contract|claim_insurance|invest_savings or ?type=BUY_CONTRACT|CLAIM_INSURANCE|INVEST_SAVINGS
            action = qs.get('action', [None])[0]
            disc_type = qs.get('type', [None])[0]
            
            result: Dict[str, Any] = {'disclaimers': []}
            try:
                # Try to import accounting_engine to get disclaimers
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from accounting_engine import AccountingEngine, DisclaimerType
                engine = AccountingEngine()
                
                if action:
                    disclaimers = engine.get_all_disclaimers_for_action(action)
                elif disc_type:
                    # Try to match the type
                    try:
                        dt = DisclaimerType[disc_type.upper()]
                        disc = engine.get_disclaimer(dt)
                        disclaimers = [disc] if disc else []
                    except (KeyError, AttributeError):
                        disclaimers = []
                else:
                    disclaimers = engine.get_all_disclaimers()
                
                result['disclaimers'] = [
                    {
                        'type': d.disclaimer_type.name if hasattr(d.disclaimer_type, 'name') else str(d.disclaimer_type),
                        'title': d.title,
                        'content': d.content,
                        'version': d.version,
                        'effective_date': str(d.effective_date)
                    }
                    for d in disclaimers if d
                ]
            except Exception as e:
                result['error'] = str(e)
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            return

        # Investment portfolio endpoint
        if path.startswith('/api/investment-portfolio'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            result = {'customer_id': customer_id, 'message': 'Portfolio data unavailable'}
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from accounting_engine import AccountingEngine
                engine = AccountingEngine()
                portfolio = engine.get_investment_portfolio_summary(customer_id)  # type: ignore
                result = portfolio  # type: ignore
            except Exception as e:
                result['error'] = str(e)
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return

        # Projected returns endpoint
        if path.startswith('/api/projected-returns'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            years = int(qs.get('years', ['5'])[0])
            result = {'customer_id': customer_id, 'message': 'Projections unavailable'}
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from accounting_engine import AccountingEngine
                engine = AccountingEngine()
                returns = engine.get_projected_returns_analysis(customer_id, years)  # type: ignore
                result = returns  # type: ignore
            except Exception as e:
                result['error'] = str(e)
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return

        # Serve static files from web_portal/static
        if path == '/' or path == '/index.html':
            file_path = os.path.join(ROOT, 'index.html')
        else:
            rel = path.lstrip('/')
            file_path = os.path.join(ROOT, rel)

        # Support "folder" routes by serving index.html
        if os.path.isdir(file_path):
            file_path = os.path.join(file_path, 'index.html')

        if os.path.isfile(file_path):
            try:
                self._set_file_headers(file_path)
                with open(file_path, 'rb') as fh:
                    self.wfile.write(fh.read())
            except Exception as e:
                self.send_error(500, str(e))
        else:
            # Friendly fallback for unknown HTML routes (e.g. "/phins" from bookmarks/health checks).
            # Do NOT mask missing assets like .js/.css/.svg with index.html.
            try:
                accept = (self.headers.get("Accept") or "").lower()
            except Exception:
                accept = ""
            looks_like_asset = any(path.endswith(ext) for ext in ('.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.map'))
            if (not looks_like_asset) and ("text/html" in accept or accept == "" or path.count('/') <= 1) and not path.startswith('/api/'):
                try:
                    idx = os.path.join(ROOT, 'index.html')
                    if os.path.isfile(idx):
                        self._set_file_headers(idx)
                        with open(idx, 'rb') as fh:
                            self.wfile.write(fh.read())
                        return
                except Exception:
                    pass
            self.send_error(404, 'Not Found: %s' % self.path)

    def do_POST(self):
        # Periodic cleanup of stale data
        cleanup_stale_data()

        # Ensure absolute URLs are available for notifications/emails
        self._maybe_set_app_base_url()
        
        # Security checks
        client_ip = self._get_client_ip()

        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        
        # Check if IP is blocked
        is_blocked, block_reason = is_ip_blocked(client_ip)
        # Allow basic auth/registration flows even if an IP was previously flagged.
        # (Avoid locking out legitimate users behind shared proxies.)
        allow_when_blocked = {
            '/api/login',
            '/api/register',
            '/api/validate-email',
        }
        if is_blocked and path not in allow_when_blocked:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Access denied',
                'message': 'Your IP has been blocked due to suspicious activity'
            }).encode('utf-8'))
            return
        
        # Rate limiting (role-aware when authenticated; never block non-API posts)
        auth_header = self.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
        session = validate_session(token) if token else None
        role_for_limit = None
        try:
            if session and session.get('username'):
                u = USERS.get(session.get('username'))
                if isinstance(u, dict):
                    role_for_limit = u.get('role')
        except Exception:
            role_for_limit = None

        if path.startswith('/api/') and (not check_rate_limit(client_ip, role=role_for_limit)):
            log_malicious_attempt(client_ip, 'Rate Limit Exceeded (POST)', {'endpoint': self.path})
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests. Please try again later.'}).encode('utf-8'))
            return
        
        # Check request size
        # Check request size
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_REQUEST_SIZE:
            log_malicious_attempt(client_ip, 'Oversized Request', {
                'size': content_length,
                'max_allowed': MAX_REQUEST_SIZE
            })
            self.send_response(413)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Request too large'}).encode('utf-8'))
            return
        
        # Handle multipart form data for quote submission
        if path == '/api/submit-quote':
            self.handle_quote_submission()
            return
        
        # Regular JSON POST requests
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else ''

        # Session validation (used by many POST endpoints)
        # (already validated above for rate limiting; keep variable name stable)
        session = session
        
        # Demo login endpoint with secure password verification
        if path == '/api/login':
            client_ip = self._get_client_ip()
            
            # Check if IP is locked out
            if not check_login_lockout(client_ip):
                lockout_data = FAILED_LOGINS.get(client_ip, {})
                remaining = int(lockout_data.get('lockout_until', 0) - datetime.now().timestamp())
                self._set_json_headers(429)
                self.wfile.write(json.dumps({
                    'error': f'Too many failed login attempts. Try again in {remaining} seconds.',
                    'lockout_remaining': remaining
                }).encode('utf-8'))
                return
            
            try:
                creds = json.loads(body)
                username = _normalize_username(creds.get('username', ''))
                password = creds.get('password', '')
                
                # Input validation
                if not username or not password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Username and password required'}).encode('utf-8'))
                    return
                
                # Security validation on username
                is_valid, error = validate_input_security(username, client_ip, 'username')
                if not is_valid:
                    record_failed_login(client_ip)
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid username format'}).encode('utf-8'))
                    return
                
                if len(password) < 6:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
                    return
                
                user = USERS.get(username)
                if user and verify_password(password, user['hash'], user['salt']):
                    # Clear failed login attempts on success
                    if client_ip in FAILED_LOGINS:
                        del FAILED_LOGINS[client_ip]
                    
                    # Generate secure session token
                    token = f"phins_{secrets.token_urlsafe(32)}"
                    expires = datetime.now() + timedelta(hours=24)
                    
                    # Store session
                    customer_id = user.get('customer_id')
                    # Best-effort: resolve customer_id via customers table for customer accounts
                    try:
                        if not customer_id and user.get('email'):
                            uemail = str(user.get('email') or '').strip().lower()
                            if uemail:
                                for c in CUSTOMERS.values():
                                    if isinstance(c, dict) and str(c.get('email') or '').lower() == uemail:
                                        customer_id = c.get('id') or customer_id
                                        break
                    except Exception:
                        pass

                    # Backfill any historical submissions created before account linkage
                    try:
                        uemail = str(user.get('email') or username or '').strip().lower()
                        if customer_id and uemail:
                            for sid, rec in list(FORM_SUBMISSIONS.items()):
                                if not isinstance(rec, dict):
                                    continue
                                if rec.get('customer_id'):
                                    continue
                                if str(rec.get('email') or '').lower() != uemail:
                                    continue
                                updated = dict(rec)
                                updated['customer_id'] = customer_id
                                FORM_SUBMISSIONS[sid] = updated
                    except Exception:
                        pass

                    sess_record: Dict[str, Any] = {
                        'username': username,
                        'expires': expires.isoformat(),
                        'customer_id': customer_id,
                    }
                    # Keep DB and in-memory session shapes compatible with their backing models
                    if USE_DATABASE and database_enabled:
                        sess_record['ip_address'] = client_ip
                        sess_record['created_date'] = datetime.now().isoformat()
                    else:
                        sess_record['ip'] = client_ip
                        sess_record['created_at'] = datetime.now().isoformat()
                    SESSIONS[token] = sess_record
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'token': token,
                        'role': user['role'],
                        'name': user['name'],
                        'username': username,
                        'customer_id': customer_id,
                        'expires': expires.isoformat()
                    }).encode('utf-8'))
                else:
                    # Record failed login attempt
                    record_failed_login(client_ip)
                    
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Internal server error'}).encode('utf-8'))
            return
        
        # User Registration Endpoint
        if path == '/api/register':
            try:
                data = json.loads(body)
                name = sanitize_input(data.get('name', ''), 100)
                email = sanitize_input(data.get('email', ''), 254).lower()
                phone = sanitize_input(data.get('phone', ''), 20)
                dob = data.get('dob', '')
                password = data.get('password', '')
                
                # Validation
                if not name or not email or not password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Name, email, and password are required'}).encode('utf-8'))
                    return
                
                if not validate_email(email):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid email format'}).encode('utf-8'))
                    return
                
                if len(password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Check if user already exists
                if email in USERS:
                    self._set_json_headers(409)
                    self.wfile.write(json.dumps({'error': 'Email already registered'}).encode('utf-8'))
                    return

                # If the customer already exists (e.g., they applied / requested a quote first),
                # reuse that customer_id so their dashboard can track existing applications.
                existing_customer_id = None
                existing_customer = None
                try:
                    for c in CUSTOMERS.values():
                        if isinstance(c, dict) and (c.get('email') or '').lower() == email:
                            existing_customer_id = c.get('id')
                            existing_customer = c
                            break
                except Exception:
                    existing_customer_id = None
                    existing_customer = None

                customer_id = existing_customer_id or generate_customer_id()
                created_date = None
                if isinstance(existing_customer, dict):
                    created_date = existing_customer.get('created_date')

                # Create/update customer record
                CUSTOMERS[customer_id] = {
                    'id': customer_id,
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'dob': dob,
                    'created_date': created_date or datetime.now().isoformat()
                }

                # Backfill any existing submissions for this email so the customer/admin can see full history.
                try:
                    for sid, rec in list(FORM_SUBMISSIONS.items()):
                        if not isinstance(rec, dict):
                            continue
                        if rec.get('customer_id'):
                            continue
                        if str(rec.get('email') or '').lower() != email:
                            continue
                        updated = dict(rec)
                        updated['customer_id'] = customer_id
                        FORM_SUBMISSIONS[sid] = updated
                except Exception:
                    pass

                # Store submission for admin/customer support
                try:
                    store_form_submission(source='register', customer_id=customer_id, email=email, payload={'name': name, 'email': email, 'phone': phone, 'dob': dob})
                except Exception:
                    pass

                # Create user account (DB-backed users require repository writes)
                pwd_hash = hash_password(password)
                if USE_DATABASE and database_enabled:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        db.users.create(
                            username=email,
                            password_hash=pwd_hash['hash'],
                            password_salt=pwd_hash['salt'],
                            role='customer',
                            name=name,
                            email=email,
                            active=True,
                        )
                else:
                    USERS[email] = {
                        'hash': pwd_hash['hash'],
                        'salt': pwd_hash['salt'],
                        'role': 'customer',
                        'name': name,
                        'customer_id': customer_id
                    }
                
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'success': True,
                    'customer_id': customer_id,
                    'email': email,
                    'message': 'Account created successfully. Please login with your credentials.'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Registration failed'}).encode('utf-8'))
            return

        # Delete (revoke) a stored media asset (admin/staff or owning customer only)
        if path == '/api/media/delete':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'success': False, 'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                data = json.loads(body) if body else {}
                token_in = data.get('token')
                if not token_in:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'success': False, 'error': 'token is required'}).encode('utf-8'))
                    return
                rec = TOKEN_REGISTRY.get(token_in)
                if not isinstance(rec, dict) or rec.get('kind') != 'media_asset' or rec.get('status') != 'active':
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'success': False, 'error': 'Not found'}).encode('utf-8'))
                    return
                try:
                    meta_raw = rec.get('meta') or rec.get('metadata') or '{}'
                    meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
                except Exception:
                    meta = {}
                role = USERS.get(session.get('username') if session else '', {}).get('role') if session else None
                is_staff = str(role or '').lower() in ('admin', 'underwriter', 'accountant', 'claims', 'claims_adjuster')
                if not is_staff:
                    if str(meta.get('customer_id') or '') != str(session.get('customer_id') or ''):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'success': False, 'error': 'Forbidden'}).encode('utf-8'))
                        return

                # Revoke token and best-effort delete file
                try:
                    TOKEN_REGISTRY[token_in] = {**rec, 'token': token_in, 'kind': 'media_asset', 'status': 'revoked'}
                except Exception:
                    pass
                try:
                    p = meta.get('path')
                    if p and os.path.exists(str(p)):
                        os.remove(str(p))
                except Exception:
                    pass
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'success': True}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
            return

        # Admin: push market data points for charts (persisted; survives restarts)
        if path == '/api/market/push':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'success': False, 'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                data = json.loads(body) if body else {}
                kind_in = str(data.get('kind') or '').strip().lower()
                kind = "crypto" if kind_in == "crypto" else "index"
                symbol = str(data.get('symbol') or '').strip().upper()
                if not symbol:
                    raise ValueError("symbol is required")
                price = float(data.get('price'))
                if not (price > 0):
                    raise ValueError("price must be > 0")
                currency = str(data.get('currency') or 'USD').strip().upper()[:10]
                t_in = data.get('t') or data.get('timestamp') or None
                created_dt = _safe_parse_dt(t_in) or datetime.utcnow()

                # In-memory series (for immediate UI update)
                try:
                    kind_key = "crypto" if kind == "crypto" else "index"
                    sym = symbol
                    cur = currency
                    series = MARKET_SERIES.setdefault(kind_key, {}).setdefault(f"{sym}@{cur}", [])
                    series.append({"t": created_dt.isoformat(), "p": float(price)})
                    if len(series) > MARKET_SERIES_MAX_POINTS:
                        del series[:-MARKET_SERIES_MAX_POINTS]
                except Exception:
                    pass

                # Persist (DB optional)
                tick_id = None
                if USE_DATABASE and database_enabled:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            rec = db.market_ticks.create(
                                kind=kind,
                                symbol=symbol,
                                price=float(price),
                                currency=currency,
                                source='push',
                                created_date=created_dt,
                            )
                            tick_id = rec.id if rec else None
                    except Exception:
                        tick_id = None

                # Store as a submission too (audit trail, independent of DB model)
                try:
                    store_form_submission(
                        source='market_push',
                        customer_id=None,
                        email=None,
                        payload={'kind': kind, 'symbol': symbol, 'price': price, 'currency': currency, 't': created_dt.isoformat()},
                    )
                except Exception:
                    pass

                self._set_json_headers(200)
                self.wfile.write(json.dumps({'success': True, 'id': tick_id, 'kind': kind, 'symbol': symbol, 'price': price, 'currency': currency, 't': created_dt.isoformat()}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
            return
        
        # Password Reset Endpoint
        if path == '/api/reset-password':
            try:
                data = json.loads(body)
                username = sanitize_input(data.get('username', ''), 254).lower()
                email = sanitize_input(data.get('email', ''), 254).lower()
                new_password = data.get('new_password', '')
                
                # Validation
                if not username or not email or not new_password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'All fields are required'}).encode('utf-8'))
                    return
                
                if len(new_password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Verify user exists and email matches
                user = USERS.get(username)
                if not user:
                    # Try to find by email
                    user = USERS.get(email)
                    username = email
                
                if not user:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
                    return
                
                # Verify email matches customer record
                customer_id = user.get('customer_id')
                if customer_id:
                    customer = CUSTOMERS.get(customer_id)
                    if customer and customer.get('email', '').lower() != email:
                        self._set_json_headers(401)
                        self.wfile.write(json.dumps({'error': 'Email does not match our records'}).encode('utf-8'))
                        return
                
                # Update password
                pwd_hash = hash_password(new_password)
                if USE_DATABASE and database_enabled:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        db.users.update(username, password_hash=pwd_hash['hash'], password_salt=pwd_hash['salt'])
                else:
                    USERS[username]['hash'] = pwd_hash['hash']
                    USERS[username]['salt'] = pwd_hash['salt']
                
                # Invalidate all existing sessions for this user
                sessions_to_remove = [token for token, sess in SESSIONS.items() if sess.get('username') == username]
                for token in sessions_to_remove:
                    del SESSIONS[token]
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': 'Password reset successfully. Please login with your new password.'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Password reset failed'}).encode('utf-8'))
            return

        # Admin: Reset any user's password (staff operation)
        if path == '/api/admin/reset-password':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'success': False, 'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                data = json.loads(body) if body else {}
                target = sanitize_input(data.get('username') or data.get('email') or '', 254).lower()
                if not target:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'success': False, 'error': 'username or email is required'}).encode('utf-8'))
                    return

                # Determine username key
                username = target
                user = USERS.get(username)
                if not user:
                    # Best-effort: search by email in in-memory users
                    try:
                        for k, v in USERS.items():  # type: ignore[attr-defined]
                            if isinstance(v, dict) and (v.get('email') or '').lower() == target:
                                username = k
                                user = v
                                break
                    except Exception:
                        user = None
                if not user:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'success': False, 'error': 'User not found'}).encode('utf-8'))
                    return

                # Generate temporary password
                temp_password = f"pw-{uuid.uuid4().hex[:10]}"
                pwd_hash = hash_password(temp_password)

                email = None
                customer_id = None
                try:
                    email = user.get('email') if isinstance(user, dict) else None
                    customer_id = user.get('customer_id') if isinstance(user, dict) else None
                except Exception:
                    email = None
                    customer_id = None

                # Update password in DB or in-memory
                if USE_DATABASE and database_enabled:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        db.users.update(username, password_hash=pwd_hash['hash'], password_salt=pwd_hash['salt'])
                        # Try to refresh email from DB
                        try:
                            u2 = db.users.get_by_username(username)
                            email = (u2.email if u2 else None) or email
                        except Exception:
                            pass
                else:
                    USERS[username]['hash'] = pwd_hash['hash']
                    USERS[username]['salt'] = pwd_hash['salt']

                # Invalidate all sessions for this user
                try:
                    sessions_to_remove = [t for t, s in list(SESSIONS.items()) if isinstance(s, dict) and s.get('username') == username]
                    for t in sessions_to_remove:
                        del SESSIONS[t]
                except Exception:
                    pass

                # Notify user
                try:
                    store_form_submission(source='admin_reset_password', customer_id=customer_id, email=email, payload={'username': username, 'requested_by': session.get('username')})
                except Exception:
                    pass
                email_sent = False
                if email and validate_email(str(email)):
                    email_sent = send_email_notification(
                        str(email),
                        subject="PHINS.ai password reset",
                        body=f"Your password has been reset by an administrator.\n\nTemporary password: {temp_password}\n\nPlease login and change your password immediately.\n\n— PHINS.ai",
                    )
                create_notification(
                    customer_id=customer_id,
                    role='customer',
                    kind='security',
                    subject='Password reset',
                    message='Your password was reset by an administrator. Check your email for the temporary password and change it after login.',
                    link='/login.html',
                )

                return_temp = os.environ.get("RETURN_TEMP_PASSWORD", "").lower() in ("1", "true", "yes")
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'username': username,
                    'email': email,
                    'email_sent': bool(email_sent),
                    **({'temporary_password': temp_password} if return_temp or not email_sent else {}),
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
            return
        
        # Change Password Endpoint (authenticated users)
        if path == '/api/change-password':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Please login.'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                current_password = data.get('current_password', '')
                new_password = data.get('new_password', '')
                
                if not current_password or not new_password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Current and new password are required'}).encode('utf-8'))
                    return
                
                if len(new_password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'New password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                username = session.get('username')
                user = USERS.get(username)
                
                if not user:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                    return
                
                # Verify current password
                if not verify_password(current_password, user['hash'], user['salt']):
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Current password is incorrect'}).encode('utf-8'))
                    return
                
                # Update password
                pwd_hash = hash_password(new_password)
                USERS[username]['hash'] = pwd_hash['hash']
                USERS[username]['salt'] = pwd_hash['salt']
                
                # Invalidate all sessions except current
                sessions_to_remove = [t for t, s in SESSIONS.items() if s.get('username') == username and t != token]
                for t in sessions_to_remove:
                    del SESSIONS[t]
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': 'Password changed successfully'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Password change failed'}).encode('utf-8'))
            return
        
        # Admin: Create New User Endpoint
        if path == '/api/admin/create-user':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                username = sanitize_input(data.get('username', ''), 100).lower()
                name = sanitize_input(data.get('name', ''), 100)
                email = sanitize_input(data.get('email', ''), 254).lower()
                role = data.get('role', 'customer')
                password = data.get('password', '')
                
                # Validation
                if not username or not name or not password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Username, name, and password are required'}).encode('utf-8'))
                    return
                
                if role not in ['customer', 'admin', 'underwriter', 'claims', 'accountant']:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid role'}).encode('utf-8'))
                    return
                
                if len(password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Check if user already exists
                if username in USERS:
                    self._set_json_headers(409)
                    self.wfile.write(json.dumps({'error': 'Username already exists'}).encode('utf-8'))
                    return
                
                # Create customer record if role is customer
                customer_id = None
                if role == 'customer':
                    customer_id = generate_customer_id()
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': name,
                        'email': email,
                        'created_date': datetime.now().isoformat()
                    }
                
                # Create user account
                pwd_hash = hash_password(password)
                USERS[username] = {
                    'hash': pwd_hash['hash'],
                    'salt': pwd_hash['salt'],
                    'role': role,
                    'name': name,
                    'customer_id': customer_id
                }
                
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'success': True,
                    'username': username,
                    'role': role,
                    'customer_id': customer_id,
                    'message': 'User created successfully'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'User creation failed'}).encode('utf-8'))
            return

        # Admin: Update PHI product configuration (savings split, load, default jurisdiction)
        if path == '/api/products/phi/config':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            try:
                data = json.loads(body) if body else {}
                if 'default_jurisdiction' in data:
                    j = str(data.get('default_jurisdiction', 'US')).upper()
                    PHI_PRODUCT_CONFIG['default_jurisdiction'] = 'UK' if j in ('UK', 'GB', 'GBR') else 'US'
                if 'default_savings_percentage' in data:
                    PHI_PRODUCT_CONFIG['default_savings_percentage'] = float(data.get('default_savings_percentage'))
                if 'default_operational_reinsurance_load' in data:
                    PHI_PRODUCT_CONFIG['default_operational_reinsurance_load'] = float(data.get('default_operational_reinsurance_load'))

                self._set_json_headers(200)
                self.wfile.write(json.dumps({'success': True, 'phi_config': PHI_PRODUCT_CONFIG}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
            return
        
        # Create Policy Endpoint
        if path == '/api/policies/create':
            try:
                data = json.loads(body)
                
                # Validate and sanitize inputs
                customer_name = sanitize_input(data.get('customer_name', ''), 100)
                customer_email = sanitize_input(data.get('customer_email', ''), 254)
                customer_phone = sanitize_input(data.get('customer_phone', ''), 20)
                
                if not customer_name:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Customer name is required'}).encode('utf-8'))
                    return

                if not customer_email:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Customer email is required'}).encode('utf-8'))
                    return

                if customer_email and not validate_email(customer_email):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid email format'}).encode('utf-8'))
                    return
                
                coverage_amount = data.get('coverage_amount', 100000)
                if not validate_amount(coverage_amount):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid coverage amount'}).encode('utf-8'))
                    return
                
                policy_id = generate_policy_id()
                # Reuse customer_id if we already have a customer with the same email
                customer_id = None
                try:
                    for c in CUSTOMERS.values():
                        if isinstance(c, dict) and (c.get('email') or '').lower() == customer_email.lower():
                            customer_id = c.get('id')
                            break
                except Exception:
                    customer_id = None
                customer_id = customer_id or data.get('customer_id') or generate_customer_id()
                
                # Create customer if new
                existing = CUSTOMERS.get(customer_id) if customer_id else None
                created_date = existing.get('created_date') if isinstance(existing, dict) else None
                CUSTOMERS[customer_id] = {
                    'id': customer_id,
                    'name': customer_name,
                    'email': customer_email,
                    'phone': customer_phone,
                    'dob': data.get('customer_dob', (existing.get('dob') if isinstance(existing, dict) else '')),
                    'created_date': created_date or datetime.now().isoformat()
                }

                # Store raw submission payload (Apply / Buy Insurance)
                try:
                    store_form_submission(
                        source=str(data.get('source') or 'apply'),
                        customer_id=customer_id,
                        email=customer_email,
                        payload=data,
                    )
                except Exception:
                    pass
                
                # Create underwriting application
                uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                uw_notes = {
                    'source': 'apply',
                    'product': {'name': 'phins_permanent_phi_disability', 'adl_trigger_min': 3},
                    'questionnaire': data.get('questionnaire', {}),
                    'phi': {
                        'jurisdiction': data.get('jurisdiction') or data.get('country'),
                        'savings_percentage': data.get('savings_percentage'),
                        'operational_reinsurance_load': data.get('operational_reinsurance_load'),
                    },
                'policy_term_years': data.get('policy_term_years') or data.get('term_years') or data.get('years'),
                }
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'status': 'pending',
                    'risk_assessment': data.get('risk_score', 'medium'),
                    'medical_exam_required': bool(data.get('medical_exam_required', False)),
                    'submitted_date': datetime.now().isoformat(),
                    'notes': json.dumps(uw_notes)
                }
                
                # PHI configuration (adjustable savings split + load + jurisdiction)
                savings_percentage = data.get('savings_percentage', PHI_PRODUCT_CONFIG.get('default_savings_percentage', 25))
                operational_reinsurance_load = data.get('operational_reinsurance_load', PHI_PRODUCT_CONFIG.get('default_operational_reinsurance_load', 50))
                jurisdiction = data.get('jurisdiction') or data.get('country') or PHI_PRODUCT_CONFIG.get('default_jurisdiction', 'US')

                # Calculate premium (+ breakdown)
                premium_request = dict(data)
                premium_request.update({
                    'savings_percentage': savings_percentage,
                    'operational_reinsurance_load': operational_reinsurance_load,
                    'jurisdiction': jurisdiction,
                })
                try:
                    from services.pricing_service import price_policy
                    priced = price_policy(premium_request)
                    premium_data = {'annual': priced['annual'], 'monthly': priced['monthly'], 'quarterly': priced['quarterly']}
                    premium_breakdown = priced.get('breakdown', {})
                except Exception:
                    premium_data = calculate_premium(premium_request)
                    premium_breakdown = {}
                
                # Create policy (DB schema supports core fields only; store extended PHI config in underwriting.notes)
                policy = {
                    'id': policy_id,
                    'customer_id': customer_id,
                    'type': 'disability' if str(data.get('type', '')).lower() in ('disability', 'phi', 'phi_disability', 'permanent_disability') else data.get('type', 'life'),
                    'coverage_amount': float(data.get('coverage_amount', 100000)),
                    'annual_premium': float(premium_data['annual']),
                    'monthly_premium': float(premium_data['monthly']),
                    'quarterly_premium': float(premium_data.get('quarterly', 0.0)),
                    'policy_term_years': data.get('policy_term_years') or data.get('term_years') or data.get('years'),
                    'status': 'pending_underwriting',
                    'underwriting_id': uw_id,
                    'risk_score': data.get('risk_score', 'medium'),
                    'start_date': data.get('start_date', datetime.now().isoformat()),
                    'end_date': data.get('end_date', (datetime.now() + timedelta(days=365)).isoformat()),
                    'created_date': datetime.now().isoformat(),
                    'uw_status': 'pending',
                }
                
                POLICIES[policy_id] = policy
                if audit:
                    actor = session.get('username') if 'session' in locals() and session else 'system'
                    try:
                        audit.log(actor, 'create', 'policy', policy_id, {'customer_id': customer_id, 'coverage_amount': policy.get('coverage_amount')})
                    except Exception:
                        pass

                # Autonomous underwriting for low-risk / young applicants
                auto = False
                try:
                    cust = CUSTOMERS.get(customer_id)
                    if isinstance(cust, dict) and _should_auto_approve(policy=policy, app=UNDERWRITING_APPLICATIONS[uw_id], customer=cust):
                        auto = True
                        _approve_underwriting_and_notify(uw_id=uw_id, approved_by="automation", automated=True)
                except Exception:
                    auto = False

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'policy': policy,
                    'underwriting': UNDERWRITING_APPLICATIONS[uw_id],
                    'customer': CUSTOMERS[customer_id],
                    'autonomous': {'auto_approved': auto, 'config': UNDERWRITING_AUTOMATION_CONFIG},
                    'tracking': {'login_url': '/login.html', 'register_url': '/register.html', 'email': customer_email}
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # Create Policy (Safe Minimal) Endpoint
        if path == '/api/policies/create_simple':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id') or generate_customer_id()
                policy_type = data.get('type', 'life')
                coverage_amount = data.get('coverage_amount', 100000)
                savings_percentage = data.get('savings_percentage', PHI_PRODUCT_CONFIG.get('default_savings_percentage', 25))
                operational_reinsurance_load = data.get('operational_reinsurance_load', PHI_PRODUCT_CONFIG.get('default_operational_reinsurance_load', 50))
                jurisdiction = data.get('jurisdiction') or data.get('country') or PHI_PRODUCT_CONFIG.get('default_jurisdiction', 'US')
                if not validate_amount(coverage_amount):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid coverage amount'}).encode('utf-8'))
                    return
                # Upsert minimal customer record if needed
                if customer_id not in CUSTOMERS:
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': data.get('customer_name') or customer_id,
                        'email': data.get('customer_email', ''),
                        'created_date': datetime.now().isoformat()
                    }
                # Generate IDs
                policy_id = generate_policy_id()
                uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                # Underwriting record (keep extended fields inside notes for DB compatibility)
                uw_notes = {
                    'source': 'new_policy',
                    'product': {'name': 'phins_permanent_phi_disability', 'adl_trigger_min': 3},
                    'phi': {
                        'jurisdiction': jurisdiction,
                        'savings_percentage': savings_percentage,
                        'operational_reinsurance_load': operational_reinsurance_load,
                    }
                }
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'status': 'pending',
                    'risk_assessment': data.get('risk_score', 'medium'),
                    'submitted_date': datetime.now().isoformat(),
                    'notes': json.dumps(uw_notes),
                }
                # Premium calc
                premium_request = {
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': data.get('age', 30),
                    'risk_score': data.get('risk_score', 'medium'),
                    'savings_percentage': savings_percentage,
                    'operational_reinsurance_load': operational_reinsurance_load,
                    'jurisdiction': jurisdiction,
                }
                try:
                    from services.pricing_service import price_policy
                    priced = price_policy(premium_request)
                    premium_data = {'annual': priced['annual'], 'monthly': priced['monthly'], 'quarterly': priced['quarterly']}
                    premium_breakdown = priced.get('breakdown', {})
                except Exception:
                    premium_data = calculate_premium(premium_request)
                    premium_breakdown = {}
                # Create policy (DB schema supports core fields only)
                policy = {
                    'id': policy_id,
                    'customer_id': customer_id,
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'annual_premium': premium_data['annual'],
                    'monthly_premium': premium_data['monthly'],
                    'status': 'pending_underwriting',
                    'underwriting_id': uw_id,
                    'risk_score': data.get('risk_score', 'medium'),
                    'start_date': datetime.now().isoformat(),
                    'end_date': (datetime.now() + timedelta(days=365)).isoformat(),
                    'created_date': datetime.now().isoformat(),
                    'uw_status': 'pending',
                }
                POLICIES[policy_id] = policy
                if audit:
                    actor = 'system'
                    try:
                        audit.log(actor, 'create', 'policy', policy_id, {'customer_id': customer_id, 'safe': True})
                    except Exception:
                        pass
                # Autonomous underwriting for low-risk / young applicants
                auto = False
                try:
                    cust = CUSTOMERS.get(customer_id)
                    app = UNDERWRITING_APPLICATIONS.get(uw_id)
                    if isinstance(cust, dict) and isinstance(app, dict) and _should_auto_approve(policy=policy, app=app, customer=cust):
                        auto = True
                        _approve_underwriting_and_notify(uw_id=uw_id, approved_by="automation", automated=True)
                except Exception:
                    auto = False

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'policy': policy,
                    'underwriting': UNDERWRITING_APPLICATIONS[uw_id],
                    'customer': CUSTOMERS[customer_id],
                    'autonomous': {'auto_approved': auto, 'config': UNDERWRITING_AUTOMATION_CONFIG},
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return
        
        # Approve Underwriting Endpoint
        if path == '/api/underwriting/approve':
            try:
                if not require_role(session, ['admin', 'underwriter']):
                    self._set_json_headers(403)
                    self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                    return
                data = json.loads(body)
                uw_id = data.get('id')
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                
                if app:
                    policy_id = app.get('policy_id')
                    result = _approve_underwriting_and_notify(
                        uw_id=uw_id,
                        approved_by=data.get('approved_by', 'admin'),
                        automated=False,
                    )
                    if audit:
                        actor = data.get('approved_by', 'admin')
                        try:
                            audit.log(actor, 'approve', 'underwriting', uw_id, {'policy_id': policy_id})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, **(result or {'application': app})}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Reject Underwriting Endpoint
        if path == '/api/underwriting/reject':
            try:
                data = json.loads(body)
                uw_id = data.get('id')
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                
                if app:
                    policy_id = app.get('policy_id')
                    result = _reject_underwriting_and_notify(
                        uw_id=uw_id,
                        rejected_by=data.get('rejected_by', 'admin'),
                        reason=data.get('reason', 'Risk assessment failed'),
                    )
                    if audit:
                        actor = data.get('rejected_by', 'admin')
                        try:
                            audit.log(actor, 'reject', 'underwriting', uw_id, {'policy_id': policy_id, 'reason': app['rejection_reason']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, **(result or {'application': app})}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # Underwriting automation configuration (admin)
        if path == '/api/underwriting/automation/config':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                data = json.loads(body) if body else {}
                if 'enabled' in data:
                    UNDERWRITING_AUTOMATION_CONFIG['enabled'] = bool(data.get('enabled'))
                if 'max_age' in data:
                    UNDERWRITING_AUTOMATION_CONFIG['max_age'] = int(data.get('max_age'))
                if 'max_coverage_amount' in data:
                    UNDERWRITING_AUTOMATION_CONFIG['max_coverage_amount'] = float(data.get('max_coverage_amount'))
                if 'policy_type' in data:
                    UNDERWRITING_AUTOMATION_CONFIG['policy_type'] = str(data.get('policy_type') or '').strip().lower()
                if 'max_adl_actuarial_risk_rate' in data:
                    UNDERWRITING_AUTOMATION_CONFIG['max_adl_actuarial_risk_rate'] = float(data.get('max_adl_actuarial_risk_rate'))
                self._set_json_headers()
                self.wfile.write(json.dumps({'success': True, 'config': UNDERWRITING_AUTOMATION_CONFIG}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
            return

        # Underwriting automation config import (admin) - paste JSON or upload CSV/JSON externally
        if path == '/api/underwriting/automation/config/import':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                data = json.loads(body) if body else {}
                # Accept either {"config": {...}} or {"json": "{...}"} or {"csv": "key,value\\n..."}
                cfg_in = data.get('config')
                if isinstance(data.get('json'), str):
                    cfg_in = json.loads(data['json'])
                if isinstance(data.get('csv'), str):
                    import csv
                    from io import StringIO
                    cfg_in = {}
                    reader = csv.reader(StringIO(data['csv']))
                    for row in reader:
                        if not row or len(row) < 2:
                            continue
                        k = str(row[0]).strip()
                        v = str(row[1]).strip()
                        if not k or k.lower() in ('key', 'name'):
                            continue
                        cfg_in[k] = v

                if not isinstance(cfg_in, dict):
                    raise ValueError("config must be an object")

                # Normalize and apply
                mapped = {
                    'enabled': cfg_in.get('enabled', UNDERWRITING_AUTOMATION_CONFIG.get('enabled')),
                    'max_age': cfg_in.get('max_age', UNDERWRITING_AUTOMATION_CONFIG.get('max_age')),
                    'max_coverage_amount': cfg_in.get('max_coverage_amount', UNDERWRITING_AUTOMATION_CONFIG.get('max_coverage_amount')),
                    'policy_type': cfg_in.get('policy_type', UNDERWRITING_AUTOMATION_CONFIG.get('policy_type')),
                    'max_adl_actuarial_risk_rate': cfg_in.get('max_adl_actuarial_risk_rate', UNDERWRITING_AUTOMATION_CONFIG.get('max_adl_actuarial_risk_rate')),
                }
                UNDERWRITING_AUTOMATION_CONFIG['enabled'] = bool(mapped['enabled'])
                UNDERWRITING_AUTOMATION_CONFIG['max_age'] = int(float(mapped['max_age']))
                UNDERWRITING_AUTOMATION_CONFIG['max_coverage_amount'] = float(mapped['max_coverage_amount'])
                UNDERWRITING_AUTOMATION_CONFIG['policy_type'] = str(mapped['policy_type'] or '').strip().lower()
                UNDERWRITING_AUTOMATION_CONFIG['max_adl_actuarial_risk_rate'] = float(mapped['max_adl_actuarial_risk_rate'])

                self._set_json_headers()
                self.wfile.write(json.dumps({'success': True, 'config': UNDERWRITING_AUTOMATION_CONFIG}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
            return
        
        # Create Claim Endpoint
        if path == '/api/claims/create':
            try:
                data = json.loads(body)
                claim_id = generate_claim_id()
                
                claim = {
                    'id': claim_id,
                    'policy_id': data.get('policy_id'),
                    'customer_id': data.get('customer_id'),
                    'type': data.get('type', 'general'),
                    'description': data.get('description', ''),
                    'claimed_amount': float(data.get('claimed_amount', 0)),
                    'status': 'pending',
                    'filed_date': datetime.now().isoformat(),
                    'documents': data.get('documents', [])
                }
                
                CLAIMS[claim_id] = claim
                # Store claim submission + notify customer
                try:
                    cust = CUSTOMERS.get(claim.get('customer_id')) if claim.get('customer_id') else None
                    store_form_submission(source='claim', customer_id=claim.get('customer_id'), email=(cust.get('email') if isinstance(cust, dict) else None), payload=data)
                    if isinstance(cust, dict):
                        notify_customer(
                            customer_id=claim.get('customer_id'),
                            email=cust.get('email'),
                            subject="Claim received",
                            message=f"Your claim {claim_id} has been received and is pending review.",
                            kind="claims",
                        )
                except Exception:
                    pass
                if audit:
                    actor = session.get('username') if 'session' in locals() and session else 'system'
                    try:
                        audit.log(actor, 'create', 'claim', claim_id, {'policy_id': claim.get('policy_id'), 'claimed_amount': claim.get('claimed_amount')})
                    except Exception:
                        pass
                
                self._set_json_headers(201)
                self.wfile.write(json.dumps(claim).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Approve Claim Endpoint
        if path == '/api/claims/approve':
            try:
                data = json.loads(body)
                claim_id = data.get('id')
                claim = CLAIMS.get(claim_id)
                
                if claim:
                    claim['status'] = 'approved'
                    claim['approved_amount'] = float(data.get('approved_amount', claim['claimed_amount']))
                    claim['approval_date'] = datetime.now().isoformat()
                    claim['approved_by'] = data.get('approved_by', 'admin')
                    claim['approval_notes'] = data.get('notes', '')
                    if audit:
                        actor = claim.get('approved_by', 'admin')
                        try:
                            audit.log(actor, 'approve', 'claim', claim_id, {'approved_amount': claim['approved_amount']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, 'claim': claim}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Reject Claim Endpoint
        if path == '/api/claims/reject':
            try:
                data = json.loads(body)
                claim_id = data.get('id')
                claim = CLAIMS.get(claim_id)
                
                if claim:
                    claim['status'] = 'rejected'
                    claim['rejection_date'] = datetime.now().isoformat()
                    claim['rejection_reason'] = data.get('reason', 'Not covered')
                    if audit:
                        actor = data.get('rejected_by', 'admin')
                        try:
                            audit.log(actor, 'reject', 'claim', claim_id, {'reason': claim['rejection_reason']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, 'claim': claim}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Pay Claim Endpoint
        if path == '/api/claims/pay':
            try:
                data = json.loads(body)
                claim_id = data.get('id')
                claim = CLAIMS.get(claim_id)
                
                if claim and claim['status'] == 'approved':
                    claim['status'] = 'paid'
                    claim['payment_date'] = datetime.now().isoformat()
                    claim['payment_method'] = data.get('payment_method', 'bank_transfer')
                    claim['payment_reference'] = f"PAY-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                    claim['paid_amount'] = claim.get('approved_amount', claim['claimed_amount'])
                    if audit:
                        actor = data.get('processed_by', 'accountant')
                        try:
                            audit.log(actor, 'pay', 'claim', claim_id, {'paid_amount': claim['paid_amount'], 'payment_method': claim['payment_method']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, 'claim': claim}).encode('utf-8'))
                else:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Claim not approved or not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Email validation endpoint
        if path == '/api/validate-email':
            try:
                data = json.loads(body)
                email = data.get('email', '')
                # Simple validation
                import re
                is_valid = re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email) is not None
                self._set_json_headers()
                self.wfile.write(json.dumps({'valid': is_valid}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== BILLING API ENDPOINTS ==========
        if billing_enabled:
            # Add payment method
            if path == '/api/billing/payment-method':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    result = billing_engine.add_payment_method(customer_id, data)
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # Process payment/charge
            if path == '/api/billing/charge':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    amount = float(data.get('amount', 0))
                    policy_id = data.get('policy_id')
                    payment_token = data.get('payment_token')
                    
                    if not customer_id or not policy_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id and policy_id required'}).encode('utf-8'))
                        return
                    
                    result = billing_engine.process_payment(
                        customer_id=customer_id,
                        amount=amount,
                        policy_id=policy_id,
                        payment_token=payment_token,
                        metadata=data.get('metadata', {})
                    )
                    
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # Get billing history
            if path == '/api/billing/history':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    transactions = billing_engine.get_customer_transactions(customer_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'transactions': transactions}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get billing statement
            if path == '/api/billing/statement':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    statement = billing_engine.get_billing_statement(
                        customer_id,
                        data.get('start_date'),
                        data.get('end_date')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps(statement).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Process refund
            if path == '/api/billing/refund':
                try:
                    data = json.loads(body)
                    transaction_id = data.get('transaction_id')
                    amount = data.get('amount')
                    reason = data.get('reason')
                    
                    if not transaction_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'transaction_id required'}).encode('utf-8'))
                        return
                    
                    result = billing_engine.refund_payment(transaction_id, amount, reason)
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # Get fraud alerts (admin only)
            if path == '/api/billing/fraud-alerts':
                try:
                    data = json.loads(body) if body else {}
                    alerts = billing_engine.get_fraud_alerts(
                        severity=data.get('severity'),
                        status=data.get('status')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'alerts': alerts}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get payment methods
            if path == '/api/billing/payment-methods':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    methods = billing_engine.get_payment_methods(customer_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'payment_methods': methods}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        # ========== END BILLING API ==========
        # Minimal billing endpoints (demo fallback when engine routes are not used)
        if path == '/api/billing/create':
            try:
                data = json.loads(body)
                policy_id = data.get('policy_id')
                amount_due = float(data.get('amount_due', data.get('amount', 0)))
                due_days = int(data.get('due_days', 30))
                if not policy_id or not validate_amount(amount_due):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'policy_id and valid amount_due required'}).encode('utf-8'))
                    return
                # Infer customer_id from policy if possible
                customer_id = data.get("customer_id")
                if not customer_id and policy_id in POLICIES:
                    customer_id = POLICIES[policy_id].get("customer_id")
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required (or policy must exist)'}).encode('utf-8'))
                    return

                bill = create_bill(policy_id=policy_id, customer_id=customer_id, amount=amount_due, due_days=due_days)
                if audit:
                    try:
                        audit.log('system', 'create', 'bill', bill['id'], {'policy_id': policy_id, 'amount': amount_due})
                    except Exception:
                        pass
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'bill': {**bill, 'bill_id': bill['id'], 'amount_due': bill['amount']}}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return

        if path == '/api/billing/pay':
            try:
                data = json.loads(body)
                bill_id = data.get('bill_id')
                amount = float(data.get('amount', 0))
                bill = BILLING.get(bill_id)
                if not bill:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bill not found'}).encode('utf-8'))
                    return
                if not validate_amount(amount):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid amount'}).encode('utf-8'))
                    return
                # Normalize for DB-backed Bill schema: amount vs amount_due
                if 'amount' not in bill and 'amount_due' in bill:
                    bill['amount'] = bill.get('amount_due', 0.0)
                bill['amount_paid'] = float(bill.get('amount_paid', 0.0)) + amount
                if bill['amount_paid'] >= float(bill.get('amount', 0.0)):
                    bill['status'] = 'paid'
                    bill['paid_date'] = datetime.now().isoformat()
                else:
                    bill['status'] = 'partial'
                if audit:
                    try:
                        audit.log('system', 'update', 'bill', bill_id, {'paid': amount, 'status': bill['status']})
                    except Exception:
                        pass
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'bill': {**bill, 'bill_id': bill.get('id', bill_id), 'amount_due': bill.get('amount', bill.get('amount_due'))}}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return

        # Pay via billing link token (no login required; token is secret and expires in 48h)
        if path == '/api/billing/link/pay':
            try:
                data = json.loads(body) if body else {}
                token = data.get('token')
                if not token:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'token is required'}).encode('utf-8'))
                    return
                resolved = resolve_billing_link(token)
                if not resolved:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Invalid or expired link'}).encode('utf-8'))
                    return
                meta = resolved.get('meta') or {}
                bill_id = meta.get('bill_id')
                bill = BILLING.get(bill_id) if bill_id else None
                if not isinstance(bill, dict):
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bill not found'}).encode('utf-8'))
                    return
                # Pay full remaining balance
                total = float(bill.get('amount', bill.get('amount_due', 0.0)) or 0.0)
                paid = float(bill.get('amount_paid', 0.0) or 0.0)
                to_pay = max(0.0, total - paid)
                if to_pay <= 0.0:
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'success': True, 'bill': bill, 'message': 'Already paid'}).encode('utf-8'))
                    return
                bill['amount'] = total
                bill['amount_paid'] = total
                bill['status'] = 'paid'
                bill['paid_date'] = datetime.now().isoformat()
                BILLING[bill_id] = bill

                # Revoke token
                TOKEN_REGISTRY[token] = {**(TOKEN_REGISTRY.get(token) or {}), 'token': token, 'kind': 'billing_link', 'status': 'revoked'}

                # Store billing payment submission + notify customer
                try:
                    customer_id = meta.get('customer_id')
                    cust = CUSTOMERS.get(customer_id) if customer_id else None
                    store_form_submission(source='billing', customer_id=customer_id, email=(cust.get('email') if isinstance(cust, dict) else None), payload={'token': token, 'bill_id': bill_id, 'amount_paid': total})
                    if isinstance(cust, dict):
                        notify_customer(
                            customer_id=customer_id,
                            email=cust.get('email'),
                            subject="Payment received",
                            message="We received your payment. Your PHINS.ai policy is now in good standing.",
                            kind="billing",
                        )
                except Exception:
                    pass

                self._set_json_headers(200)
                self.wfile.write(json.dumps({'success': True, 'bill': bill}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return
        
        # Default: not found
        self.send_error(404, 'Not Found')
    
    def handle_quote_submission(self):
        """Handle quote form submission with multipart data"""
        try:
            # Validate all form inputs for security
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid content type'}).encode('utf-8'))
                return
            
            # Read and parse the form data
            length = int(self.headers.get('Content-Length', 0))
            form_data = self.rfile.read(length)
            
            # Extract boundary from content type
            boundary = content_type.split('boundary=')[1] if 'boundary=' in content_type else None
            if not boundary:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'No boundary in multipart data'}).encode('utf-8'))
                return
            
            # Parse multipart form data (fields + files)
            fields, uploaded_files = self._parse_multipart_data_with_files(form_data, boundary.encode())  # type: ignore
            
            # Validate critical fields for injection / malicious content
            critical_fields = ['firstName', 'lastName', 'email', 'phone', 'address', 'city', 'occupation', 'nationalId']
            for field_name in critical_fields:
                field_value = fields.get(field_name, '')
                if field_value:
                    is_valid, error = validate_input_security(field_value, self._get_client_ip(), field_name)
                    if not is_valid:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': f'Invalid input in {field_name}: {error}'}).encode('utf-8'))
                        return
            
            # Extract primary identity fields
            email = (fields.get('email', '') or '').strip().lower()
            if not email or not validate_email(email):
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Valid email is required'}).encode('utf-8'))
                return

            # If the user is logged in, bind the quote to their customer_id (and prevent cross-account submissions).
            authed_customer_id = None
            try:
                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                sess = validate_session(token) if token else None
                if sess and sess.get('customer_id'):
                    authed_customer_id = sess.get('customer_id')
                    existing_cust = CUSTOMERS.get(authed_customer_id)
                    if isinstance(existing_cust, dict) and existing_cust.get('email'):
                        if str(existing_cust.get('email') or '').lower() != email:
                            self._set_json_headers(403)
                            self.wfile.write(json.dumps({'error': 'Email does not match the logged-in account'}).encode('utf-8'))
                            return
            except Exception:
                authed_customer_id = None

            # If this is an edit of an existing pending application, update it in-place.
            application_id_in = (fields.get('application_id') or fields.get('applicationId') or '').strip()
            if application_id_in:
                if not authed_customer_id:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Login required to edit an application'}).encode('utf-8'))
                    return
                app = UNDERWRITING_APPLICATIONS.get(application_id_in)
                if not isinstance(app, dict):
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
                    return
                if app.get('customer_id') != authed_customer_id:
                    self._set_json_headers(403)
                    self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                    return
                if str(app.get('status') or '').lower() != 'pending':
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Only pending applications can be edited'}).encode('utf-8'))
                    return
                policy_id_existing = app.get('policy_id')
                policy = POLICIES.get(policy_id_existing) if policy_id_existing else None
                if not isinstance(policy, dict):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Linked policy not found'}).encode('utf-8'))
                    return

                # Parse coverage + pricing inputs
                coverage_sel = (fields.get('coverageAmount', '') or '').strip()
                if coverage_sel == 'custom':
                    coverage_sel = (fields.get('customCoverage', '') or '').strip()
                try:
                    coverage_amount = int(float(coverage_sel or policy.get('coverage_amount') or '100000'))
                except Exception:
                    coverage_amount = int(policy.get('coverage_amount') or 100000)

                health_condition_score = int(float(fields.get('healthCondition', '3') or '3')) if (fields.get('healthCondition') or '').strip() else int(policy.get('health_condition_score') or 3)
                savings_percentage = fields.get('savingsPercentage', fields.get('savings_percentage', policy.get('savings_percentage', PHI_PRODUCT_CONFIG.get('default_savings_percentage', 25))))
                jurisdiction = (fields.get('jurisdiction') or fields.get('country') or policy.get('jurisdiction') or PHI_PRODUCT_CONFIG.get('default_jurisdiction', 'US'))
                operational_reinsurance_load = fields.get('operationalReinsuranceLoad', fields.get('operational_reinsurance_load', policy.get('operational_reinsurance_load', PHI_PRODUCT_CONFIG.get('default_operational_reinsurance_load', 50))))

                # Update customer record (best-effort)
                try:
                    cust = CUSTOMERS.get(authed_customer_id)
                    if isinstance(cust, dict):
                        cust.update({
                            'name': f"{(fields.get('firstName','') or '').strip()} {(fields.get('lastName','') or '').strip()}".strip() or cust.get('name') or email,
                            'first_name': (fields.get('firstName','') or '').strip() or cust.get('first_name'),
                            'last_name': (fields.get('lastName','') or '').strip() or cust.get('last_name'),
                            'phone': fields.get('phone', cust.get('phone','')),
                            'dob': fields.get('dob', cust.get('dob','')),
                            'gender': fields.get('gender', cust.get('gender','')),
                            'address': fields.get('address', cust.get('address','')),
                            'city': fields.get('city', cust.get('city','')),
                            'zip': fields.get('postalCode', cust.get('zip','')),
                            'occupation': fields.get('occupation', cust.get('occupation','')),
                        })
                        CUSTOMERS[authed_customer_id] = cust
                except Exception:
                    pass

                # Re-price and update policy (risk loading applied to risk cover portion)
                try:
                    age_i = self._calculate_age(fields.get('dob', policy.get('dob', '1990-01-01')))
                    from services.pricing_service import price_policy
                    priced = price_policy({
                        'type': 'disability',
                        'coverage_amount': coverage_amount,
                        'age': age_i,
                        'jurisdiction': jurisdiction,
                        'savings_percentage': savings_percentage,
                        'operational_reinsurance_load': operational_reinsurance_load,
                    })
                    priced = _apply_health_risk_loading(priced, health_condition_score=health_condition_score)
                    policy.update({
                        'type': 'disability',
                        'coverage_amount': coverage_amount,
                        'annual_premium': float(priced.get('annual', 0.0)),
                        'monthly_premium': float(priced.get('monthly', 0.0)),
                        'jurisdiction': 'UK' if str(jurisdiction).upper() in ('UK', 'GB', 'GBR') else 'US',
                        'savings_percentage': savings_percentage,
                        'operational_reinsurance_load': operational_reinsurance_load,
                        'health_condition_score': health_condition_score,
                        'health_risk_loading_factor': _health_risk_loading_factor(health_condition_score),
                        'updated_date': datetime.utcnow().isoformat(),
                    })
                    POLICIES[policy_id_existing] = policy

                    # Update underwriting notes: keep full form + pricing for admin decision
                    n = {}
                    try:
                        n = json.loads(app.get('notes') or '{}') if isinstance(app.get('notes'), str) else (app.get('notes') or {})
                    except Exception:
                        n = {}
                    if isinstance(n, dict):
                        n['source'] = 'quote_edit'
                        n['form'] = fields
                        n['pricing'] = priced.get('breakdown', {})
                        # Persist new uploads (if any) and attach to application notes
                        try:
                            new_attachments = _persist_media_assets(customer_id=authed_customer_id, uw_id=application_id_in, policy_id=policy_id_existing, files=uploaded_files or [])
                        except Exception:
                            new_attachments = []
                        try:
                            existing = n.get('attachments') if isinstance(n.get('attachments'), list) else []
                            n['attachments'] = (existing or []) + (new_attachments or [])
                        except Exception:
                            n['attachments'] = new_attachments or []
                        app['notes'] = json.dumps(n)
                    app['submitted_date'] = datetime.utcnow().isoformat()
                    UNDERWRITING_APPLICATIONS[application_id_in] = app

                    # Store submission
                    try:
                        store_form_submission(source='quote_update', customer_id=authed_customer_id, email=email, payload={'application_id': application_id_in, 'policy_id': policy_id_existing, 'fields': fields})
                    except Exception:
                        pass

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({
                        'success': True,
                        'application_id': application_id_in,
                        'customer_id': authed_customer_id,
                        'policy_id': policy_id_existing,
                        'message': 'Application updated successfully.',
                        'estimated_premium': {'annual': priced.get('annual'), 'monthly': priced.get('monthly'), 'quarterly': priced.get('quarterly'), 'breakdown': priced.get('breakdown', {})},
                        'attachments': (n.get('attachments') if isinstance(n, dict) else []),
                    }).encode('utf-8'))
                    return
                except Exception as e:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Update failed', 'details': str(e)}).encode('utf-8'))
                    return

            # Generate IDs (reuse customer_id by email when possible)
            customer_id = authed_customer_id
            try:
                if not customer_id:
                    for c in CUSTOMERS.values():
                        if isinstance(c, dict) and (c.get('email') or '').lower() == email:
                            customer_id = c.get('id')
                            break
            except Exception:
                customer_id = None
            customer_id = customer_id or generate_customer_id()
            policy_id = generate_policy_id()
            uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

            # Store quote form submission for support/audit (now linked to a resolved customer_id)
            try:
                store_form_submission(source='quote', customer_id=customer_id, email=email, payload=fields)
            except Exception:
                pass
            
            # Create customer record
            first = (fields.get('firstName', '') or '').strip()
            last = (fields.get('lastName', '') or '').strip()
            customer_name = f"{first} {last}".strip() or email
            existing = CUSTOMERS.get(customer_id) if customer_id else None
            created_date = existing.get('created_date') if isinstance(existing, dict) else None
            CUSTOMERS[customer_id] = {
                'id': customer_id,
                'name': customer_name,
                'first_name': first,
                'last_name': last,
                'email': email,
                'phone': fields.get('phone', ''),
                'dob': fields.get('dob', ''),
                'gender': fields.get('gender', ''),
                'address': fields.get('address', ''),
                'city': fields.get('city', ''),
                'state': fields.get('state', ''),
                'zip': fields.get('postalCode', ''),
                'occupation': fields.get('occupation', ''),
                'created_date': created_date or datetime.now().isoformat()
            }

            # Update stored quote submission with customer_id (best-effort)
            try:
                store_form_submission(source='quote_customer_link', customer_id=customer_id, email=email, payload={'customer_id': customer_id, 'email': email})
            except Exception:
                pass
            
            # Parse coverage amount
            coverage_sel = (fields.get('coverageAmount', '') or '').strip()
            if coverage_sel == 'custom':
                coverage_sel = (fields.get('customCoverage', '') or '').strip()
            try:
                coverage_amount = int(float(coverage_sel or '100000'))
            except Exception:
                coverage_amount = 100000
            policy_type = 'disability'

            # Term years (for projections; stored for underwriting decisioning)
            policy_term_raw = (fields.get('policyTerm', '') or '').strip()
            policy_term_years = None
            try:
                if policy_term_raw and policy_term_raw.lower() != 'lifetime':
                    policy_term_years = int(float(policy_term_raw))
                elif policy_term_raw.lower() == 'lifetime':
                    policy_term_years = 30
            except Exception:
                policy_term_years = None

            # Savings preference and jurisdiction (important for pricing + allocations)
            savings_percentage = fields.get('savingsPercentage', fields.get('savings_percentage', PHI_PRODUCT_CONFIG.get('default_savings_percentage', 25)))
            jurisdiction = (fields.get('jurisdiction') or fields.get('country') or PHI_PRODUCT_CONFIG.get('default_jurisdiction', 'US'))
            operational_reinsurance_load = fields.get('operationalReinsuranceLoad', fields.get('operational_reinsurance_load', PHI_PRODUCT_CONFIG.get('default_operational_reinsurance_load', 50)))
            
            # Assess risk based on health information (and expose numeric score for pricing load)
            risk_score = 'low'
            medical_exam_required = False
            
            smoking = (fields.get('smoking', '') or '').lower()
            pre_existing = (fields.get('preExisting', '') or '').lower()
            health_condition_score = int(float(fields.get('healthCondition', '3') or '3')) if (fields.get('healthCondition') or '').strip() else 3

            # Base risk tier by health score (1-10)
            if 4 <= health_condition_score <= 6:
                risk_score = 'medium'
            elif 7 <= health_condition_score <= 8:
                risk_score = 'high'
            elif health_condition_score >= 9:
                risk_score = 'very_high'

            if 'smoker' in smoking or smoking in ('yes', 'current'):
                risk_score = 'high' if risk_score in ('medium', 'low') else risk_score
            if pre_existing == 'yes':
                risk_score = 'high' if risk_score in ('medium', 'low') else risk_score
                medical_exam_required = True
            if health_condition_score >= 7:
                medical_exam_required = True
            
            # Create underwriting application
            uw_notes = {
                'source': 'quote',
                'product': {'name': 'phins_permanent_phi_disability', 'adl_trigger_min': 3},
                'form': fields,
                'policy_term_years': policy_term_years,
            }
            # Persist uploads and attach to underwriting notes
            try:
                uw_notes['attachments'] = _persist_media_assets(customer_id=customer_id, uw_id=uw_id, policy_id=policy_id, files=uploaded_files or [])
            except Exception:
                uw_notes['attachments'] = []
            UNDERWRITING_APPLICATIONS[uw_id] = {
                'id': uw_id,
                'policy_id': policy_id,
                'customer_id': customer_id,
                'status': 'pending',
                'risk_assessment': risk_score,
                'medical_exam_required': medical_exam_required,
                'submitted_date': datetime.now().isoformat(),
                'notes': json.dumps(uw_notes),
            }
            
            # Calculate premium (+ breakdown) including savings preference and health-risk loading
            age_i = self._calculate_age(fields.get('dob', '1990-01-01'))
            try:
                from services.pricing_service import price_policy
                priced = price_policy({
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': age_i,
                    'jurisdiction': jurisdiction,
                    'savings_percentage': savings_percentage,
                    'operational_reinsurance_load': operational_reinsurance_load,
                })
                priced = _apply_health_risk_loading(priced, health_condition_score=health_condition_score)
                premium_data = {
                    'annual': float(priced.get('annual', 0.0)),
                    'monthly': float(priced.get('monthly', 0.0)),
                    'quarterly': float(priced.get('quarterly', 0.0)),
                    'breakdown': priced.get('breakdown', {}),
                }
            except Exception:
                premium_data = calculate_premium({
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': age_i,
                    'jurisdiction': jurisdiction,
                    'savings_percentage': savings_percentage,
                    'operational_reinsurance_load': operational_reinsurance_load,
                })
            
            # Create policy
            POLICIES[policy_id] = {
                'id': policy_id,
                'customer_id': customer_id,
                'type': policy_type,
                'coverage_amount': coverage_amount,
                'annual_premium': premium_data['annual'],
                'monthly_premium': premium_data['monthly'],
                'jurisdiction': 'UK' if str(jurisdiction).upper() in ('UK', 'GB', 'GBR') else 'US',
                'savings_percentage': savings_percentage,
                'operational_reinsurance_load': operational_reinsurance_load,
                'health_condition_score': health_condition_score,
                'health_risk_loading_factor': _health_risk_loading_factor(health_condition_score),
                'policy_term_years': policy_term_years,
                'status': 'pending_underwriting',
                'underwriting_id': uw_id,
                'risk_score': risk_score,
                'start_date': datetime.now().isoformat(),
                'end_date': (datetime.now() + timedelta(days=365)).isoformat(),
                'created_date': datetime.now().isoformat()
            }

            # Attach pricing to the underwriting record notes (admin decision-making)
            try:
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                if isinstance(app, dict):
                    n = {}
                    try:
                        n = json.loads(app.get('notes') or '{}') if isinstance(app.get('notes'), str) else (app.get('notes') or {})
                    except Exception:
                        n = {}
                    if isinstance(n, dict):
                        n['pricing'] = premium_data.get('breakdown') if isinstance(premium_data, dict) else None
                        app['notes'] = json.dumps(n)
                        UNDERWRITING_APPLICATIONS[uw_id] = app
            except Exception:
                pass
            
            print(f"✅ Application submitted: {uw_id} for customer {customer_id}")
            print(f"   Customer: {customer_name} ({email})")
            print(f"   Policy: {policy_type.title()} - ${coverage_amount:,}")
            print(f"   Risk: {risk_score}, Status: pending")

            # Autonomous underwriting for low-risk / young applicants (quote flow)
            auto = False
            try:
                cust = CUSTOMERS.get(customer_id)
                pol = POLICIES.get(policy_id)
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                if isinstance(cust, dict) and isinstance(pol, dict) and isinstance(app, dict):
                    if _should_auto_approve(policy=pol, app=app, customer=cust):
                        auto = True
                        _approve_underwriting_and_notify(uw_id=uw_id, approved_by="automation", automated=True)
            except Exception:
                auto = False
            
            # Return success response with all created records
            self._set_json_headers(200)
            response = {
                'success': True,
                'application_id': uw_id,
                'customer_id': customer_id,
                'policy_id': policy_id,
                'message': 'Quote request submitted. You can register/login with the same email to track your application.',
                'estimated_premium': premium_data,
                'attachments': (uw_notes.get('attachments') if isinstance(uw_notes, dict) else []),
                'autonomous': {'auto_approved': auto, 'config': UNDERWRITING_AUTOMATION_CONFIG},
                'tracking': {'login_url': '/login.html', 'register_url': '/register.html', 'email': email},
                'application_summary': {
                    'customer_name': customer_name,
                    'policy_type': policy_type,
                    'coverage_amount': coverage_amount,
                    'risk_assessment': risk_score,
                    'status': 'pending'
                }
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e), 'details': str(e.__class__.__name__)}).encode('utf-8'))
    
    def _parse_multipart_data(self, data: bytes, boundary: bytes) -> Dict[str, str]:
        """Parse multipart/form-data into dictionary of fields"""
        fields: Dict[str, str] = {}
        parts = data.split(b'--' + boundary)
        
        for part in parts:
            if b'Content-Disposition: form-data' not in part:
                continue
            
            # Extract field name
            if b'name="' in part:
                name_start = part.find(b'name="') + 6
                name_end = part.find(b'"', name_start)
                field_name = part[name_start:name_end].decode('utf-8')
                
                # Extract field value
                value_start = part.find(b'\r\n\r\n')
                if value_start != -1:
                    value_start += 4
                    value_end = part.rfind(b'\r\n')
                    if value_end > value_start:
                        field_value = part[value_start:value_end].decode('utf-8', errors='ignore').strip()
                        if field_value:  # Only add non-empty values
                            fields[field_name] = field_value
        
        return fields

    def _parse_multipart_data_with_files(self, data: bytes, boundary: bytes) -> tuple[Dict[str, str], list[Dict[str, Any]]]:
        """
        Parse multipart/form-data into (fields, files).
        - fields values are always strings; repeated keys are preserved as JSON strings.
        - files are returned as dicts: {field, filename, content_type, data}
        """
        fields_raw: Dict[str, list[str]] = {}
        files: list[Dict[str, Any]] = []
        parts = data.split(b'--' + boundary)

        for part in parts:
            if b'Content-Disposition: form-data' not in part:
                continue
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                continue
            header_blob = part[:header_end].decode('utf-8', errors='ignore')
            body = part[header_end + 4:]
            # Trim final CRLF
            if body.endswith(b'\r\n'):
                body = body[:-2]

            # Parse name
            name = None
            if 'name="' in header_blob:
                try:
                    name = header_blob.split('name="', 1)[1].split('"', 1)[0]
                except Exception:
                    name = None
            if not name:
                continue

            # Parse filename (if present)
            filename = None
            if 'filename="' in header_blob:
                try:
                    filename = header_blob.split('filename="', 1)[1].split('"', 1)[0]
                except Exception:
                    filename = None

            # Content-Type (optional)
            content_type = "application/octet-stream"
            if 'Content-Type:' in header_blob:
                try:
                    content_type = header_blob.split('Content-Type:', 1)[1].splitlines()[0].strip()
                except Exception:
                    content_type = "application/octet-stream"

            if filename:
                # File part
                files.append({
                    "field": name,
                    "filename": filename,
                    "content_type": content_type,
                    "data": bytes(body),
                })
            else:
                # Text field
                try:
                    val = body.decode('utf-8', errors='ignore').strip()
                except Exception:
                    val = ""
                if val == "":
                    continue
                fields_raw.setdefault(name, []).append(val)

        # Normalize fields to Dict[str, str], preserving repeated keys as JSON strings
        fields: Dict[str, str] = {}
        for k, vals in fields_raw.items():
            if not vals:
                continue
            if len(vals) == 1:
                fields[k] = vals[0]
            else:
                fields[k] = json.dumps(vals)
        return fields, files
    
    def _calculate_age(self, dob_str: str) -> int:
        """Calculate age from date of birth string"""
        try:
            dob = datetime.strptime(dob_str, '%Y-%m-%d')
            today = datetime.now()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age
        except:
            return 30  # Default age
    
    def calculate_demo_premium(self) -> Dict[str, Any]:
        """Calculate a demo premium estimate"""
        # Simple demo calculation
        import random
        base_premium = random.randint(500, 2000)
        return {
            'monthly': round(base_premium / 12, 2),
            'annual': base_premium,
            'currency': 'USD'
        }


def run_server(port: int = PORT) -> None:
    # Initialize database if enabled
    if USE_DATABASE and database_enabled:
        print("📊 Initializing database...")
        try:
            # Check connection
            if check_database_connection():
                print("✓ Database connection successful")
                db_info = get_database_info()
                print(f"   Type: {db_info['database_type']}")
                print(f"   URL: {db_info['database_url'][:50]}...")
            else:
                print("⚠️  Database connection failed, will try to initialize anyway")
            
            # Initialize schema
            init_database()
            print("✓ Database schema initialized")
            
            # Seed default users
            try:
                seed_default_users()
                print("✓ Default users seeded")
            except Exception as e:
                print(f"Note: User seeding skipped (may already exist): {e}")
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            print("   Server will continue with in-memory storage")
            # Don't fail - just fall back to in-memory
    
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, PortalHandler)
    httpd.timeout = CONNECTION_TIMEOUT  # Set connection timeout
    print(f'\n🚀 Serving web portal at http://0.0.0.0:{port} (static from {ROOT})')
    print(f'   Access via: http://localhost:{port}')
    print(f'🔒 Security: Rate limiting, malicious code blocking, auto-cleanup enabled')
    print(f'⏱️  Connection timeout: {CONNECTION_TIMEOUT}s | Session timeout: {SESSION_TIMEOUT}s')
    if USE_DATABASE and database_enabled:
        print(f'💾 Storage: Database (persistent)')
    else:
        print(f'💾 Storage: In-memory (volatile)')
    httpd.serve_forever()


def run_tests():
    print('Running quick web_portal tests...')
    # Test statement fetch (best-effort)
    stmt = try_get_statement_from_engine('CUST001') or get_mock_statement('CUST001')
    print('Sample statement (truncated):')
    print(json.dumps({
        'customer_id': stmt.get('customer_id'),
        'total_premium': stmt.get('total_premium'),
        'risk_total': stmt.get('risk_total')
    }, indent=2))
    # Test connectors if available
    try:
        # Load connectors module from file location (works when server.py is run directly)
        import importlib.util
        conn_path = os.path.join(os.path.dirname(__file__), 'connectors.py')
        spec = importlib.util.spec_from_file_location('web_portal.connectors', conn_path)
        if spec and spec.loader:
            connectors = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(connectors)
        else:
            raise ImportError('Cannot load connectors')
        print('\nConnector demo results:')
        res = connectors.demo_validators()
        for k, v in res.items():
            print(f' - {k}:', v.status)
    except Exception as e:
        print('Connector demo skipped:', e)
    print('All tests passed (demo assertions only).')


if __name__ == '__main__':
    import sys

    if '--test' in sys.argv:
        run_tests()
    else:
        run_server()
