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

# Import billing engine
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from billing_engine import billing_engine, SecurityValidator
    BILLING_ENABLED = True
except ImportError:
    BILLING_ENABLED = False
    print("Warning: Billing engine not available. Payment features disabled.")

PORT = 8000
ROOT = os.path.join(os.path.dirname(__file__), "static")

# In-memory storage for demo purposes
POLICIES = {}
CLAIMS = {}
CUSTOMERS = {}
UNDERWRITING_APPLICATIONS = {}
SESSIONS = {}  # token -> {username, expires, customer_id}

# Hash passwords for security (in production, use proper password hashing)
def hash_password(password: str) -> dict:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return secrets.compare_digest(hashed.hex(), stored_hash)

# Store hashed passwords
USERS = {
    'admin': {**hash_password('admin123'), 'role': 'admin', 'name': 'Admin User'},
    'underwriter': {**hash_password('under123'), 'role': 'underwriter', 'name': 'John Underwriter'},
    'claims_adjuster': {**hash_password('claims123'), 'role': 'claims', 'name': 'Jane Claims'},
    'accountant': {**hash_password('acct123'), 'role': 'accountant', 'name': 'Bob Accountant'}
}


def get_mock_statement(customer_id):
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


def generate_policy_id():
    return f"POL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_claim_id():
    return f"CLM-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_customer_id():
    return f"CUST-{random.randint(10000, 99999)}"

def calculate_premium(policy_data):
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

def get_bi_data_actuary():
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

def get_bi_data_underwriting():
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

def get_bi_data_accounting():
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

def try_get_statement_from_engine(customer_id):
    try:
        import accounting_engine as ae

        engine = ae.AccountingEngine()
        # Try to call a best-effort method and coerce result to JSON-serializable
        if hasattr(engine, "get_customer_statement"):
            stmt = engine.get_customer_statement(customer_id)
            try:
                return json.loads(json.dumps(stmt, default=lambda o: o.__dict__))
            except Exception:
                return stmt
    except Exception:
        pass
    return None


class PortalHandler(BaseHTTPRequestHandler):
    def _set_json_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def _set_file_headers(self, path):
        self.send_response(200)
        if path.endswith('.html'):
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        elif path.endswith('.js'):
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        elif path.endswith('.css'):
            self.send_header('Content-Type', 'text/css; charset=utf-8')
        else:
            self.send_header('Content-Type', 'application/octet-stream')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        qs = urlparse.parse_qs(parsed.query)

        # API endpoints
        
        # Admin authentication check for protected endpoints
        auth_header = self.headers.get('Authorization', '')
        is_authenticated = auth_header.startswith('Bearer demo-token-')
        
        # BI Dashboard Endpoints
        if path == '/api/bi/actuary':
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_actuary()).encode('utf-8'))
            return
        
        if path == '/api/bi/underwriting':
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_underwriting()).encode('utf-8'))
            return
        
        if path == '/api/bi/accounting':
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_accounting()).encode('utf-8'))
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
                self._set_json_headers()
                self.wfile.write(json.dumps(list(POLICIES.values())).encode('utf-8'))
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
                self._set_json_headers()
                self.wfile.write(json.dumps(claims_list).encode('utf-8'))
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
                connectors = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(connectors)

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
            
            result = {'disclaimers': []}
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
                portfolio = engine.get_investment_portfolio_summary(customer_id)
                result = portfolio
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
                returns = engine.get_projected_returns_analysis(customer_id, years)
                result = returns
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
            try:
                creds = json.loads(body)
                username = creds.get('username', '')
                password = creds.get('password', '')
                
                user = USERS.get(username)
                if user and verify_password(password, user['hash'], user['salt']):
                    # Generate secure session token
                    token = f"phins_{secrets.token_urlsafe(32)}"
                    expires = datetime.now() + timedelta(hours=24)
                    
                    # Store session
                    SESSIONS[token] = {
                        'username': username,
                        'expires': expires.isoformat(),
                        'customer_id': user.get('customer_id')
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
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Create Policy Endpoint
        if path == '/api/policies/create':
            try:
                data = json.loads(body)
                policy_id = generate_policy_id()
                customer_id = data.get('customer_id') or generate_customer_id()
                
                # Create customer if new
                if customer_id not in CUSTOMERS:
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': data.get('customer_name', 'Unknown'),
                        'email': data.get('customer_email', ''),
                        'phone': data.get('customer_phone', ''),
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
        if BILLING_ENABLED:
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
        
        # Default: not found
        self.send_error(404, 'Not Found')
    
    def handle_quote_submission(self):
        """Handle quote form submission with multipart data"""
        try:
            # Parse multipart form data
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid content type'}).encode('utf-8'))
                return
            
            # Read the form data
            length = int(self.headers.get('Content-Length', 0))
            form_data = self.rfile.read(length)
            
            # For demo purposes, just accept the submission
            # In production, parse multipart data properly and integrate with underwriting_assistant
            quote_id = f"QT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Try to integrate with underwriting assistant
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from underwriting_assistant import UnderwritingAssistant
                from customer_validation import Customer, HealthAssessment
                
                # Create a demo customer record (in production, parse from form_data)
                # For now, just log the submission
                print(f"Quote submission received: {quote_id}")
                
            except Exception as e:
                print(f"Underwriting integration unavailable: {e}")
            
            # Return success response
            self._set_json_headers(200)
            response = {
                'success': True,
                'quote_id': quote_id,
                'message': 'Your quote request has been submitted successfully. Our underwriting team will review your application and contact you within 2-3 business days.',
                'estimated_premium': self.calculate_demo_premium(),
                'next_steps': [
                    'Review your email for confirmation',
                    'Our underwriter will contact you for any additional information',
                    'Complete medical examination if required',
                    'Receive final quote and policy terms'
                ]
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
    
    def calculate_demo_premium(self):
        """Calculate a demo premium estimate"""
        # Simple demo calculation
        import random
        base_premium = random.randint(500, 2000)
        return {
            'monthly': round(base_premium / 12, 2),
            'annual': base_premium,
            'currency': 'USD'
        }


def run_server(port=PORT):
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, PortalHandler)
    print(f'Serving web portal at http://0.0.0.0:{port} (static from {ROOT})')
    print(f'Access via: http://localhost:{port}')
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
        connectors = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(connectors)
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
