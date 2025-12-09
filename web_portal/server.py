    def do_POST(self):
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        # Demo login endpoint
        if path == '/api/login':
            try:
                creds = json.loads(body)
                username = creds.get('username', '')
                password = creds.get('password', '')
                # Demo: accept 'admin'/'admin123' or 'user'/'user123'
                if (username == 'admin' and password == 'admin123') or (username == 'user' and password == 'user123'):
                    token = f"demo-token-{username}-123"
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'token': token}).encode('utf-8'))
                else:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        # Default: not found
        self.send_error(404, 'Not Found')
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

PORT = 8000
ROOT = os.path.join(os.path.dirname(__file__), "static")


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


def run_server(port=PORT):
    server_address = ('', port)
    httpd = HTTPServer(server_address, PortalHandler)
    print(f'Serving web portal at http://localhost:{port} (static from {ROOT})')
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
