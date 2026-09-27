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

The sign-in password is `regulator123` until an operator password is
configured. Set `PHINS_REGULATOR_PASSWORD` (8 characters or more) and sign
in once with it. That replaces a database hash left over from a boot where
the variable was missing, and it retires `regulator123`. Changing the
password in the regulation view retires both the demo password and the
environment password.

The dashboard uses the PHINS navy, gold, and cyan gradients. Its report
studio shows or hides each section, switches charts between bar, line, and
doughnut, resizes the graphics, and downloads the chosen sections as an HTML
report, CSV tables, or JSON. Those choices stay in the browser. The sealed
numbers do not change.

`POST /api/regulator/credentials` changes this account's username and
password. The current password is required, the role stays `regulator`, and
an existing username cannot be taken. After a change the previous demo
password stops working; in database mode that retirement is recorded durably,
so a restart or another replica cannot bring the old secret back, and a
replaced username stays retired instead of becoming free again. A new token is
returned so the dashboard stays signed in.

## Ask for inquiry

The regulation account can open a conversation on any outlined subject from
the dashboard card **Ask for inquiry**. The subjects are pricing, underwriting,
claims, investments, health, agents, billing, and integrity. Admin and actuary
do not see the card and cannot call the inquiry API.

`GET /api/regulator/inquiries` returns that account's inquiries and the
subject catalog. `POST /api/regulator/inquiries` with
`{ "name", "email", "subject", "message" }` opens one inquiry per account and
subject. Full name and email are required. Organization is always
`capital markets authority` and audience is always `regulations contact`;
the request cannot replace either one. A later message appends. The same
text as the latest turn is a duplicate and adds nothing. `opened_by` is the
signed-in username. The body cannot set a customer id.
Inquiry text is stored as written; the injection detectors that scan query
strings are not applied to it, so ordinary punctuation is not an attack.
A credential rename carries this account's inquiries to the new username, and
a rename whose rewrite cannot be recorded is refused with 503.

The thread lives in `REGULATOR_INQUIRIES`. In database mode each inquiry is an
`agent_artifacts` row (`agent_id` `regulator_inquiry`, `kind` `inquiry`) with
a checksum checked on load. The same write files a Business Relations row
(`BRI-…`, interest `regulator:<subject>`) so the admin queue shows the
contact. Both writes succeed before either cache updates. A failed write
leaves the previous records in place and returns 503.

Staff email and the acknowledgement to the contact email use the Business
Relations notification path (`PHINS_BUSINESS_INQUIRY_NOTIFY_EMAILS`, then
admin mailboxes, then `EMAIL_REPLY_TO`). The public solutions form cannot
submit audience `regulations contact`. The dashboard links to
`/solutions.html#contact` for that separate public conversation.

Inquiry text is not copied into the sealed outline.

## Offer structure

The dashboard is one sealed document, `GET /api/regulator/outline`:

1. **Pricing kernel** — active tables version, config version, version catalog with integrity hashes, and basic premiums from `price_policy` on the published standard nonsmoker tariff (`phins_pure_risk_adjustable`, coverage 100,000, term 20 years, ages 30/40/50/60). The illustration is priced at PHINS internal underwriting score 5, the multiplier-table unit (mortality ×1.0, disability incidence ×1.0). Score 5 is not the average internal score. Score 10 on this 1–10 scale is a fully disabled customer and meets global ADL 3+ (unable to perform 3 or more of 6 activities of daily living). The illustration is not a recorded health status and not a customer quote.
2. **Underwriting** — decision counts, risk bands, and the mean of assessed internal underwriting scores. The mean is null when no score was assessed. Unsourced and unassessed rows are not filled in with score 5. No applicant identity or medical detail.
3. **Claims** — counts and amounts in total. **Claims paid** is the admin balance-sheet “Claims Paid / Total Paid Out” figure: customer-ledger cash (`ledger_claims_paid`). Approved amounts on paid claim files stay on a separate row and do not replace that cash total. Open claims are `pending` and `under_review` only. Loss ratio is claims paid over active premium.
4. **Investments** — account balances by route, policy investment value, and assets under management. AUM is policy investment value plus health wallets, investment accounts, algo balance, and pipeline cash.
5. **Health** — health policy count and premium, plus health-wallet balance and deposits.
6. **Agent BI** — headcount, status mix, and commission totals.
7. **Billing** — billed, collected, outstanding, and collection rate from the billing stats, plus ledger premium collected, ledger claims paid, posted premium and claims, and the economic claims reserve.
8. **Integrity** — `outline_sha256`, source counts, and a reconciled flag.

Suspended sandbox accounts are excluded before the totals are built, including health wallets, investment accounts, algo balances, and pipeline cash. Overlapping totals must match `compute_unified_financial_metrics`, which is what the admin dashboard, accounting BI, claims counts, and billing stats use. A mismatch, or any identifier that survives redaction, refuses the response.

## Access

- `GET /api/regulator/outline` accepts roles `regulator`, `admin`, and `actuary`. All three read the same sealed document.
- The admin header and the actuary header link to `/regulator-dashboard.html`. The credential form and the inquiry card on that page are shown only for the `regulator` role.
- Every other API returns 403 for the `regulator` role.
- `POST`, `PUT`, and `DELETE` return 403 for that role except `POST /api/logout`, `POST /api/regulator/credentials`, and `POST /api/regulator/inquiries`.
- Admin and actuary cannot change the regulator password or open a regulator inquiry.
- The role is not a staff role for `/internal/` or `/legal/` documents.

UML: `docs/uml/regulator_view.puml`.
