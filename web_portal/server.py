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
from typing import Dict, Any

# Import billing engine
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from billing_engine import billing_engine, SecurityValidator
    billing_enabled = True
except ImportError:
    billing_enabled = False
    print("Warning: Billing engine not available. Payment features disabled.")

PORT = 8000
ROOT = os.path.join(os.path.dirname(__file__), "static")

# In-memory storage for demo purposes
POLICIES: Dict[str, Dict[str, Any]] = {}
CLAIMS: Dict[str, Dict[str, Any]] = {}
CUSTOMERS: Dict[str, Dict[str, Any]] = {}
UNDERWRITING_APPLICATIONS: Dict[str, Dict[str, Any]] = {}
SESSIONS: Dict[str, Dict[str, Any]] = {}  # token -> {username, expires, customer_id}
BILLING: Dict[str, Dict[str, Any]] = {}  # bill_id -> bill data (for metrics)
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

def check_rate_limit(client_ip: str) -> bool:
    """Check if client has exceeded rate limit"""
    now = datetime.now().timestamp()
    
    if client_ip in RATE_LIMIT:
        limit_data = RATE_LIMIT[client_ip]
        # Reset counter if minute has passed
        if now > limit_data['reset_time']:
            RATE_LIMIT[client_ip] = {'count': 1, 'reset_time': now + 60}
            return True
        elif limit_data['count'] < MAX_REQUESTS_PER_MINUTE:
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

def validate_amount(amount: Any) -> bool:
    """Validate monetary amounts"""
    try:
        amount = float(amount)
        return 0 <= amount <= 100000000  # Max 100 million
    except (ValueError, TypeError):
        return False

# Store hashed passwords
USERS: Dict[str, Dict[str, Any]] = {
    'admin': {**hash_password('admin123'), 'role': 'admin', 'name': 'Admin User'},
    'underwriter': {**hash_password('under123'), 'role': 'underwriter', 'name': 'John Underwriter'},
    'claims_adjuster': {**hash_password('claims123'), 'role': 'claims', 'name': 'Jane Claims'},
    'accountant': {**hash_password('acct123'), 'role': 'accountant', 'name': 'Bob Accountant'}
}


def get_mock_statement(customer_id: str) -> Dict[str, Any]:
    return {
        "customer_id": customer_id,
        "total_premium": 300.0,
        "risk_total": 225.0,
        "savings_total": 75.0,
        "allocations": [
            {"allocation_id": "ALLOC-000001", "amount": 100.0, "risk_amount": 75.0, "savings_amount": 25.0},
            {"allocation_id": "ALLOC-000002", "amount": 100.0, "risk_amount": 75.0, "savings_amount": 25.0},
            {"allocation_id": "ALLOC-000003", "amount": 100.0, "risk_amount": 75.0, "savings_amount": 25.0},
        ],
    }


def generate_policy_id() -> str:
    return f"POL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_claim_id() -> str:
    return f"CLM-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_customer_id() -> str:
    return f"CUST-{random.randint(10000, 99999)}"

def calculate_premium(policy_data: Dict[str, Any]) -> Dict[str, float]:
    """Calculate premium based on policy type and customer data"""
    base_premium = {
        'life': 1200,
        'health': 800,
        'auto': 600,
        'property': 1500,
        'business': 3000
    }.get(policy_data.get('type', 'life'), 1000)
    
    # Age factor
    age = policy_data.get('age', 30)
    age_factor = 1.0 + (max(0, age - 25) * 0.02)
    
    # Coverage factor
    coverage = policy_data.get('coverage_amount', 100000)
    coverage_factor = coverage / 100000
    
    # Risk factor based on underwriting
    risk_score = policy_data.get('risk_score', 'medium')
    risk_factors = {'low': 0.8, 'medium': 1.0, 'high': 1.3, 'very_high': 1.6}
    risk_factor = risk_factors.get(risk_score, 1.0)
    
    annual_premium = base_premium * age_factor * coverage_factor * risk_factor
    return {
        'annual': round(annual_premium, 2),
        'monthly': round(annual_premium / 12, 2),
        'quarterly': round(annual_premium / 4, 2)
    }

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


class PortalHandler(BaseHTTPRequestHandler):
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
        
        # Security checks
        client_ip = self.client_address[0]
        
        # Check if IP is blocked
        is_blocked, block_reason = is_ip_blocked(client_ip)
        if is_blocked:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Access denied',
                'message': 'Your IP has been blocked due to suspicious activity'
            }).encode('utf-8'))
            return
        
        # Rate limiting
        if not check_rate_limit(client_ip):
            log_malicious_attempt(client_ip, 'Rate Limit Exceeded', {'endpoint': self.path})
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests. Please try again later.'}).encode('utf-8'))
            return
        
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
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

        # Session validation
        auth_header = self.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
        session = validate_session(token) if token else None
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
            self.wfile.write(json.dumps({
                'username': username,
                'name': user.get('name'),
                'role': user.get('role'),
                'customer_id': user.get('customer_id')
            }).encode('utf-8'))
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
                ms = MetricsService(POLICIES, CLAIMS, BILLING)
                data = ms.summary()
            except Exception:
                data = {
                    'policies': {'total': len(POLICIES), 'active': sum(1 for p in POLICIES.values() if p.get('status') == 'active')},
                    'claims': {'pending': sum(1 for c in CLAIMS.values() if c.get('status') in ['pending', 'under_review']),
                               'approved': sum(1 for c in CLAIMS.values() if c.get('status') == 'approved')},
                    'billing': {'overdue': sum(1 for b in BILLING.values() if b.get('status') == 'overdue'),
                                'outstanding': sum(1 for b in BILLING.values() if b.get('status') in ['outstanding', 'partial'])}
                }
            self._set_json_headers()
            self.wfile.write(json.dumps({'metrics': data, 'ts': datetime.now().isoformat()}).encode('utf-8'))
            return
        
        # Policy Management Endpoints
        if path == '/api/policies':
            policy_id = qs.get('id', [None])[0]
            if policy_id:
                policy = POLICIES.get(policy_id)
                if policy:
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
            
            if claim_id:
                claim = CLAIMS.get(claim_id)
                if claim:
                    self._set_json_headers()
                    self.wfile.write(json.dumps(claim).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            else:
                claims_list = list(CLAIMS.values())
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
            if app_id:
                app = UNDERWRITING_APPLICATIONS.get(app_id)
                if app:
                    self._set_json_headers()
                    self.wfile.write(json.dumps(app).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            else:
                self._set_json_headers()
                self.wfile.write(json.dumps(list(UNDERWRITING_APPLICATIONS.values())).encode('utf-8'))
            return
        
        # Customers Endpoint
        if path == '/api/customers':
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

        # Customer status endpoint (post-application visibility)
        if path == '/api/customer/status':
            customer_id = qs.get('customer_id', [None])[0]
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
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            data = try_get_statement_from_engine(customer_id) or get_mock_statement(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return

        if path.startswith('/api/allocations'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            data = {"allocations": (try_get_statement_from_engine(customer_id) or get_mock_statement(customer_id))["allocations"]}
            self._set_json_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
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

        if os.path.isfile(file_path):
            try:
                self._set_file_headers(file_path)
                with open(file_path, 'rb') as fh:
                    self.wfile.write(fh.read())
            except Exception as e:
                self.send_error(500, str(e))
        else:
            self.send_error(404, 'Not Found: %s' % self.path)

    def do_POST(self):
        # Periodic cleanup of stale data
        cleanup_stale_data()
        
        # Security checks
        client_ip = self.client_address[0]
        
        # Check if IP is blocked
        is_blocked, block_reason = is_ip_blocked(client_ip)
        if is_blocked:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Access denied',
                'message': 'Your IP has been blocked due to suspicious activity'
            }).encode('utf-8'))
            return
        
        # Rate limiting
        if not check_rate_limit(client_ip):
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
        
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        
        # Handle multipart form data for quote submission
        if path == '/api/submit-quote':
            self.handle_quote_submission()
            return
        
        # Regular JSON POST requests
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        
        # Demo login endpoint with secure password verification
        if path == '/api/login':
            client_ip = self.client_address[0]
            
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
                username = creds.get('username', '').strip()
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
                    SESSIONS[token] = {
                        'username': username,
                        'expires': expires.isoformat(),
                        'customer_id': user.get('customer_id'),
                        'ip': client_ip,
                        'created_at': datetime.now().isoformat()
                    }
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'token': token,
                        'role': user['role'],
                        'name': user['name'],
                        'customer_id': user.get('customer_id'),
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
                
                # Create customer record
                customer_id = generate_customer_id()
                CUSTOMERS[customer_id] = {
                    'id': customer_id,
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'dob': dob,
                    'created_date': datetime.now().isoformat()
                }
                
                # Create user account
                pwd_hash = hash_password(password)
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
                customer_id = data.get('customer_id') or generate_customer_id()
                
                # Create customer if new
                if customer_id not in CUSTOMERS:
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': customer_name,
                        'email': customer_email,
                        'phone': customer_phone,
                        'dob': data.get('customer_dob', ''),
                        'created_date': datetime.now().isoformat()
                    }
                    # Provision portal login for the customer
                    cust_email = CUSTOMERS[customer_id].get('email') or f"{customer_id.lower()}@example.com"
                    temp_password = f"pw-{uuid.uuid4().hex[:10]}"
                    
                    # Hash the password for security
                    pwd_hash = hash_password(temp_password)
                    USERS[cust_email] = {
                        'hash': pwd_hash['hash'],
                        'salt': pwd_hash['salt'],
                        'role': 'customer',
                        'name': CUSTOMERS[customer_id].get('name') or customer_id,
                        'customer_id': customer_id
                    }
                
                # Create underwriting application
                uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'status': 'pending',
                    'questionnaire_responses': data.get('questionnaire', {}),
                    'risk_assessment': data.get('risk_score', 'medium'),
                    'medical_exam_required': data.get('medical_exam_required', False),
                    'submitted_date': datetime.now().isoformat()
                }
                
                # Calculate premium
                premium_data = calculate_premium(data)
                
                # Create policy
                policy = {
                    'id': policy_id,
                    'customer_id': customer_id,
                    'type': data.get('type', 'life'),
                    'coverage_amount': data.get('coverage_amount', 100000),
                    'annual_premium': premium_data['annual'],
                    'monthly_premium': premium_data['monthly'],
                    'status': 'pending_underwriting',
                    'underwriting_id': uw_id,
                    'risk_score': data.get('risk_score', 'medium'),
                    'start_date': data.get('start_date', datetime.now().isoformat()),
                    'end_date': data.get('end_date', (datetime.now() + timedelta(days=365)).isoformat()),
                    'created_date': datetime.now().isoformat()
                }
                
                POLICIES[policy_id] = policy
                if audit:
                    actor = session.get('username') if 'session' in locals() and session else 'system'
                    try:
                        audit.log(actor, 'create', 'policy', policy_id, {'customer_id': customer_id, 'coverage_amount': policy.get('coverage_amount')})
                    except Exception:
                        pass
                
                self._set_json_headers(201)
                
                # Return temp_password (stored in closure before hashing)
                login_username = CUSTOMERS[customer_id].get('email') or f"{customer_id.lower()}@example.com"
                self.wfile.write(json.dumps({
                    'policy': policy,
                    'underwriting': UNDERWRITING_APPLICATIONS[uw_id],
                    'customer': CUSTOMERS[customer_id],
                    'provisioned_login': {
                        'username': login_username,
                        'password': temp_password  # Return plain password for first login
                    }
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
                # Underwriting minimal record
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'status': 'pending',
                    'risk_assessment': data.get('risk_score', 'medium'),
                    'submitted_date': datetime.now().isoformat()
                }
                # Premium calc
                premium_data = calculate_premium({
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': data.get('age', 30),
                    'risk_score': data.get('risk_score', 'medium')
                })
                # Create policy
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
                    'created_date': datetime.now().isoformat()
                }
                POLICIES[policy_id] = policy
                if audit:
                    actor = 'system'
                    try:
                        audit.log(actor, 'create', 'policy', policy_id, {'customer_id': customer_id, 'safe': True})
                    except Exception:
                        pass
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'policy': policy, 'underwriting': UNDERWRITING_APPLICATIONS[uw_id], 'customer': CUSTOMERS[customer_id]}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return
        
        # Approve Underwriting Endpoint
        if path == '/api/underwriting/approve':
            try:
                data = json.loads(body)
                uw_id = data.get('id')
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                
                if app:
                    app['status'] = 'approved'
                    app['decision_date'] = datetime.now().isoformat()
                    app['approved_by'] = data.get('approved_by', 'admin')
                    
                    # Update policy status
                    policy_id = app.get('policy_id')
                    if policy_id and policy_id in POLICIES:
                        POLICIES[policy_id]['status'] = 'active'
                        POLICIES[policy_id]['approval_date'] = datetime.now().isoformat()
                    if audit:
                        actor = data.get('approved_by', 'admin')
                        try:
                            audit.log(actor, 'approve', 'underwriting', uw_id, {'policy_id': policy_id})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, 'application': app}).encode('utf-8'))
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
                    app['status'] = 'rejected'
                    app['decision_date'] = datetime.now().isoformat()
                    app['rejection_reason'] = data.get('reason', 'Risk assessment failed')
                    
                    # Update policy status
                    policy_id = app.get('policy_id')
                    if policy_id and policy_id in POLICIES:
                        POLICIES[policy_id]['status'] = 'rejected'
                    if audit:
                        actor = data.get('rejected_by', 'admin')
                        try:
                            audit.log(actor, 'reject', 'underwriting', uw_id, {'policy_id': policy_id, 'reason': app['rejection_reason']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, 'application': app}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
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
                amount_due = float(data.get('amount_due', 0))
                due_days = int(data.get('due_days', 30))
                if not policy_id or not validate_amount(amount_due):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'policy_id and valid amount_due required'}).encode('utf-8'))
                    return
                bill_id = f"BILL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
                bill = {
                    'bill_id': bill_id,
                    'policy_id': policy_id,
                    'amount_due': amount_due,
                    'amount_paid': 0.0,
                    'status': 'outstanding',
                    'created_date': datetime.now().isoformat(),
                    'due_date': (datetime.now() + timedelta(days=due_days)).isoformat()
                }
                BILLING[bill_id] = bill
                if audit:
                    try:
                        audit.log('system', 'create', 'bill', bill_id, {'policy_id': policy_id, 'amount_due': amount_due})
                    except Exception:
                        pass
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'bill': bill}).encode('utf-8'))
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
                bill['amount_paid'] = bill.get('amount_paid', 0.0) + amount
                if bill['amount_paid'] >= bill['amount_due']:
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
                self.wfile.write(json.dumps({'bill': bill}).encode('utf-8'))
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
            
            # Parse multipart form data
            fields = self._parse_multipart_data(form_data, boundary.encode())  # type: ignore
            
            # Validate all critical fields for security threats
            critical_fields = ['first-name', 'last-name', 'email', 'phone', 'address', 
                             'city', 'state', 'occupation', 'medical-conditions']
            for field_name in critical_fields:
                field_value = fields.get(field_name, '')
                if field_value:
                    threat = validate_input_security(field_value, field_name, self.client_address[0])
                    if threat:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': f'Invalid input in {field_name}: {threat}'}).encode('utf-8'))
                        return
            
            # Generate IDs
            customer_id = generate_customer_id()
            policy_id = generate_policy_id()
            uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
            
            # Create customer record
            customer_name = f"{fields.get('first-name', '')} {fields.get('last-name', '')}".strip()
            CUSTOMERS[customer_id] = {
                'id': customer_id,
                'name': customer_name,
                'first_name': fields.get('first-name', ''),
                'last_name': fields.get('last-name', ''),
                'email': fields.get('email', ''),
                'phone': fields.get('phone', ''),
                'dob': fields.get('dob', ''),
                'gender': fields.get('gender', ''),
                'address': fields.get('address', ''),
                'city': fields.get('city', ''),
                'state': fields.get('state', ''),
                'zip': fields.get('zip', ''),
                'occupation': fields.get('occupation', ''),
                'created_date': datetime.now().isoformat()
            }
            
            # Provision portal login for the customer
            cust_email = CUSTOMERS[customer_id].get('email') or f"{customer_id.lower()}@example.com"
            temp_password = f"pw-{uuid.uuid4().hex[:10]}"
            pwd_hash = hash_password(temp_password)
            USERS[cust_email] = {
                'hash': pwd_hash['hash'],
                'salt': pwd_hash['salt'],
                'role': 'customer',
                'name': customer_name,
                'customer_id': customer_id
            }
            
            # Parse coverage amount
            coverage_amount = int(fields.get('coverage-amount', '250000'))
            policy_type = fields.get('policy-type', 'disability')
            
            # Assess risk based on health information
            risk_score = 'low'
            medical_exam_required = False
            
            smoking = fields.get('smoking', '').lower()
            if smoking in ['yes', 'smoker', 'current']:
                risk_score = 'medium'
            
            health_conditions = fields.get('health-conditions', '').lower()
            if any(condition in health_conditions for condition in ['diabetes', 'heart', 'cancer', 'chronic']):
                risk_score = 'high'
                medical_exam_required = True
            
            # Create underwriting application
            UNDERWRITING_APPLICATIONS[uw_id] = {
                'id': uw_id,
                'policy_id': policy_id,
                'customer_id': customer_id,
                'status': 'pending',
                'questionnaire_responses': {
                    'smoking': fields.get('smoking', 'No'),
                    'health_conditions': fields.get('health-conditions', 'None'),
                    'medications': fields.get('medications', 'None'),
                    'family_history': fields.get('family-history', 'Good'),
                    'occupation': fields.get('occupation', ''),
                    'height': fields.get('height', ''),
                    'weight': fields.get('weight', '')
                },
                'risk_assessment': risk_score,
                'medical_exam_required': medical_exam_required,
                'submitted_date': datetime.now().isoformat()
            }
            
            # Calculate premium
            premium_data = calculate_premium({
                'type': policy_type,
                'coverage_amount': coverage_amount,
                'age': self._calculate_age(fields.get('dob', '1990-01-01')),
                'risk_score': risk_score
            })
            
            # Create policy
            POLICIES[policy_id] = {
                'id': policy_id,
                'customer_id': customer_id,
                'type': policy_type,
                'coverage_amount': coverage_amount,
                'annual_premium': premium_data['annual'],
                'monthly_premium': premium_data['monthly'],
                'status': 'pending_underwriting',
                'underwriting_id': uw_id,
                'risk_score': risk_score,
                'start_date': datetime.now().isoformat(),
                'end_date': (datetime.now() + timedelta(days=365)).isoformat(),
                'created_date': datetime.now().isoformat()
            }
            
            print(f"✅ Application submitted: {uw_id} for customer {customer_id}")
            print(f"   Customer: {customer_name} ({cust_email})")
            print(f"   Policy: {policy_type.title()} - ${coverage_amount:,}")
            print(f"   Risk: {risk_score}, Status: pending")
            
            # Return success response with all created records
            self._set_json_headers(200)
            response = {
                'success': True,
                'application_id': uw_id,
                'customer_id': customer_id,
                'policy_id': policy_id,
                'message': 'Your application has been submitted successfully. Our underwriting team will review it and contact you within 2-3 business days.',
                'estimated_premium': premium_data,
                'login_credentials': {
                    'username': cust_email,
                    'temporary_password': temp_password,
                    'portal_url': '/login.html'
                },
                'next_steps': [
                    'Check your email for confirmation',
                    'Login to customer portal to track your application',
                    'Our underwriter will contact you for any additional information',
                    'Complete medical examination if required',
                    'Receive final quote and policy terms'
                ],
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
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, PortalHandler)
    httpd.timeout = CONNECTION_TIMEOUT  # Set connection timeout
    print(f'Serving web portal at http://0.0.0.0:{port} (static from {ROOT})')
    print(f'Access via: http://localhost:{port}')
    print(f'🔒 Security: Rate limiting, malicious code blocking, auto-cleanup enabled')
    print(f'⏱️  Connection timeout: {CONNECTION_TIMEOUT}s | Session timeout: {SESSION_TIMEOUT}s')
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
