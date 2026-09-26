# Regulation viewer

Read-only executive outline for a regulation account. The account sees the
same book the executive metrics are computed from, without customer secrets.

## Account

| Field | Value |
|---|---|
| Username | `regulator` |
| Role | `regulator` |
| Password | `PHINS_REGULATOR_PASSWORD` |
| Dashboard | `/regulator-dashboard.html` |

In test mode the legacy demo password is `regulator123` until the account
changes it. Production leaves the password unset until
`PHINS_REGULATOR_PASSWORD` is configured, which disables login.

The dashboard uses the PHINS navy, gold, and cyan gradients. Its report
studio shows or hides each section, switches charts between bar, line, and
doughnut, resizes the graphics, and downloads the chosen sections as an HTML
report, CSV tables, or JSON. Those choices stay in the browser. The sealed
numbers do not change.

`POST /api/regulator/credentials` changes this account's username and
password. The current password is required, the role stays `regulator`, and
an existing username cannot be taken. After a change the previous demo
password stops working. A new token is returned so the dashboard stays
signed in.

## Offer structure

The dashboard is one sealed document, `GET /api/regulator/outline`:

1. **Pricing kernel** — active tables version, config version, version catalog with integrity hashes, and basic premiums from `price_policy` on the published standard nonsmoker tariff (`phins_pure_risk_adjustable`, coverage 100,000, term 20 years, ADL 5, ages 30/40/50/60).
2. **Underwriting** — decision counts and risk bands. No applicant identity or medical detail.
3. **Claims** — counts and amounts in total, including disbursed, pending liability, and loss ratio.
4. **Investments** — account balances by route, policy investment value, and assets under management.
5. **Health** — health policy count and premium, plus health-wallet balance.
6. **Agent BI** — headcount, status mix, and commission totals.
7. **Integrity** — `outline_sha256`, source counts, and a reconciled flag.

Suspended sandbox accounts are excluded before the totals are built. Overlapping totals must match `compute_unified_financial_metrics`. A mismatch, or any identifier that survives redaction, refuses the response.

## Access

- `GET /api/regulator/outline` requires role `regulator`.
- Every other API returns 403 for that role.
- `POST`, `PUT`, and `DELETE` return 403 except `POST /api/logout` and `POST /api/regulator/credentials`.
- The role is not a staff role for `/internal/` or `/legal/` documents.

UML: `docs/uml/regulator_view.puml`.
