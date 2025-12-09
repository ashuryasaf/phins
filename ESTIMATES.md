# PHINS UX/UI & Integration — Session Time Estimates

This document provides an estimated breakdown of work and sessions for the hybrid UX/UI plan (Business Central pages + Web Portal + Mobile-friendly UI), plus the connector integration work for authority validations.

Assumptions
- Small team (1 developer) working full-time on this project.
- Existing backend components and AL artifacts are present (tables and codeunits created earlier).
- Demos are acceptable for authentication for early iterations; production authentication integration (Azure AD/OAuth) is a separate phase.

Estimated Sessions (by task)

1) Planning & Specs — 1 session (2–4 hours)
- Confirm pages, API contracts, and user flows for BC pages, web portal, and mobile app. Create wireframes.

2) Business Central Pages (Partners/Admin) — 3 sessions (3 × 4 hours = 12 hours)
- Implement List and Card pages for `UserAccounts`, `PremiumAllocation`, `AccountingLedger`.
- Add actions for exporting CSV/PDF and posting allocations (demo permission checks).

3) Web Portal Backend (Demo API) — 2 sessions (2 × 4 hours = 8 hours)
- Upgrade the demo server to FastAPI (or keep simple server + optional upgrade later), add endpoints for login, statements, allocations, validations, and mobile-friendly tokens.

4) Connectors & Validation Stubs — 2 sessions (2 × 3 hours = 6 hours)
- Implement connector interfaces, secure credential storage plan, and demo stubs for National Insurance, Credit Card Issuers, and Health Authorities.

5) Web Portal Frontend (Sales/Claims, Mobile-first) — 4 sessions (4 × 4 hours = 16 hours)
- Build React (or PWA) frontend with views for Dashboard, Statements, Claims, and Account Settings. Ensure responsive and touch-friendly controls.

6) Mobile App / PWA Wrap — 1 session (4 hours)
- Wrap the web portal as a Progressive Web App and add manifest for installability; basic native-like navigation and offline caching.

7) Authentication & Roles Integration — 2 sessions (2 × 4 hours = 8 hours)
- Implement JWT token-based auth for web portal, migration path to Azure AD/OAuth for production, and apply BC permission sets for AL pages.

8) Testing, Demos & Handover — 2 sessions (2 × 3 hours = 6 hours)
- Automated smoke tests, manual UX checks on mobile viewport sizes, demo run and handoff notes.

Total Estimated Time
- Lower bound (fast iteration, minimal polish): ~52 hours (~6–8 working days)
- With polish, production auth, and documentation: ~80–120 hours (~2–4 weeks)

Prioritization (MVP path)
- Phase 1 (MVP, 1 week): BC pages minimal, demo web portal + connectors (stubs), token-based auth, responsive UI for statements.
- Phase 2 (production, 2–4 weeks): Full React portal, FastAPI backend, mobile PWA polish, secure connector integrations with real APIs and credential management.

Security & Compliance Notes
- Connector integrations require secure credentials (secrets vault), TLS, logging, and privacy review for health and financial data.
- Production deployments should include rate-limiting, retry/backoff, and robust error handling for third-party APIs.
