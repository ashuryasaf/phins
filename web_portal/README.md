# PHINS Web Portal (Demo)

This is a minimal, dependency-free web portal demo for PHINS. It includes a small Python server and a responsive static UI suitable for mobile devices.

Run tests:

```bash
python web_portal/server.py --test
```

Start the server locally (serves static files and simple API endpoints):

```bash
python web_portal/server.py
# then open http://localhost:8000 in your browser
```

Available demo endpoints:
- `GET /api/statement?customer_id=...` — returns a JSON statement
- `GET /api/allocations?customer_id=...` — returns allocations JSON

Static UI is at `web_portal/static/index.html` (mobile-first simple layout).

Notes:
- This server is a small demo; for production use, replace with FastAPI/Flask and secure auth.
- The server will try to call existing `accounting_engine` functions if available; otherwise it returns mock data.
