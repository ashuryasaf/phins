# PHINS Agent / Broker Ecosystem ("AgentOS") — Design & Implementation

> **Status: APPROVED & IMPLEMENTED (v1).** The model below was approved; the v1
> vertical slice is now implemented in this PR. `docs/uml/agent_ecosystem.puml`
> remains the model of record.
>
> **Confirmed decisions (formerly §9 open questions):**
> 1. Hierarchy: `parent_agent_id` reserved on the model; **single-level payouts in v1**.
> 2. Commission basis: **all three supported** (`premium` default, `gmv`, `one_time`).
> 3. **Recurring while active** — once per policy for the initial term, then once
>    per renewal term (keyed by `period`, driven by the paid premium bill book; §C).
> 4. Customer visibility: **yes** — `referring_agent_id` is surfaced ("referred by").
> 5. Demo agent: **seeded** (`agent` / `PHINS_AGENT_PASSWORD`; demo `agent123` in test mode).
> 6. Payouts: accrual + dashboard in v1; **`agent_payouts` runs (calculated → settled,
>    platform-ledger anchored) shipped in §C** together with the broker funnel.

## Implemented in v1

| Layer | Files |
|---|---|
| Schema | `database/models.py` (`Agent`, `AgentInvitation`, `AgentAffiliation`, `AgentCommission`; `Customer/Supplier.referring_agent_id`), `database/__init__.py` (`upgrade_schema`) |
| Repositories | `database/repositories/agent_repository.py`, wired in `repositories/__init__.py` + `database/manager.py` |
| Service | `services/agent_ecosystem_service.py` (in-memory authoritative + hash-chained ledger + best-effort DB write-through) |
| API | `web_portal/api_agent_ecosystem.py`, dispatched from `web_portal/server.py` (GET + POST) |
| Auth | `agent` role added to login fallback users, legacy demo passwords, and `database/seeds.py` |
| UI | `web_portal/static/agent-portal.html`, `web_portal/static/admin-agents.html` (linked from `unified-workbench.html`) |
| Tests | `tests/test_agent_ecosystem.py` (service, HTTP role scope, idempotency, ledger integrity, DB round-trip) |

Demo: log in to `/agent-portal.html` as `agent`/`agent123`, and manage from
`/admin-agents.html` as `admin`/`admin123` (demo passwords work in test/demo mode only).

### Admin password reset (shipped)

`admin-agents.html` adds a **Reset PW** action per agent. `POST /api/admin/agents/reset-password`
(admin-only, handled inline in `server.py` because it touches the auth/users stores)
accepts `{agent_id|username, new_password?}`; when no password is given it returns a
generated temporary one. The reset is scoped to accounts that have an agent profile (it
cannot reset other staff/admin accounts), writes through to the durable `users` table in
DB mode, updates the in-memory auth fallback, and records a secret-free entry on the
hash-chained platform event ledger. Covered by `test_http_admin_reset_agent_password`.

### Post-merge follow-ups (shipped)

- **Sign-in CAPTCHA**: the agent and admin portals now run the canonical CAPTCHA
  challenge/verify before `/api/login` (production rejected logins that omitted a
  verified token with "CAPTCHA verification required"). `login.js` also routes the
  `agent` role to `/agent-portal.html`.
- **Agent-community dashboard**: `admin-agents.html` is now a full community control
  center — community KPIs, agent roster with editable default rates, invitation
  approvals (lock rate in advance), per-agent network drill, commission ledger audit,
  and a live hash-chain integrity badge. Backed by new read-only admin endpoints
  `GET /api/admin/agents/overview|affiliations|network|ledger` and
  `community_overview()` (which calls `verify_ledger_integrity()`).
- **Durable persistence hardening**: in DB mode the durable tables are the source of
  truth. The in-memory dicts became a short-lived per-instance cache that is
  **refreshed from the database on read** (coalesced to once per `PHINS_AGENT_HYDRATE_TTL`,
  default 1.5s) and **force-refreshed on every write/decision**, replacing the previous
  hydrate-once-at-startup snapshot. This makes agent data **survive restarts** and stay
  **consistent across multiple instances** (a peer's new agent / approval / affiliation /
  suspension becomes visible) while preserving idempotent accrual and the hash-chained
  ledger. Also fixed a latent write-through bug where agent `created_date`/`updated_date`
  ISO strings were rejected by the SQLite `DateTime` columns (datetime columns are now
  left to their DB defaults). Covered by `test_db_mode_durability_survives_restart` and
  `test_db_mode_cross_instance_visibility`.

### §C follow-ups (shipped): per-renewal commission, payout runs, broker funnel

Companion to `docs/agent_operations_optimization_design.md` §C / §G.

- **Per-renewal recurring commission.** `AgentCommission.period` distinguishes the
  once-per-policy initial-term accrual (`period=''`, `source_event_id=policy:{id}`,
  `source_type=policy_premium`) from a renewal term (`period=YYYY-MM-DD` term start,
  `source_event_id=policy:{id}:{period}`, `source_type=policy_renewal`). The renewal
  term of a bill is derived deterministically by `renewal_period_for_bill` from the
  policy anniversary (`start_date`/`effective_date`/… normalised to midnight; Feb 29
  rolls to Feb 28) and the bill's `billing_period_start`/`due_date`/`paid_date`; a
  policy with no start date or an unpaid bill never accrues (under-count is possible,
  double-count is not). The in-memory idempotency key is
  `(source_event_id, affiliation_id, period)`; because the period is embedded in
  `source_event_id`, the existing two-column DB unique constraint still enforces it
  with no migration of a monetary table. Accrual is driven three ways, all idempotent:
  the billing hook `accrue_for_paid_bill` (called from `process_customer_premium_payment`
  via `accrue_agent_commission_for_paid_bills` in `server.py`), the read-time
  `recompute_commissions(policies, bills)` sweep, and admin recompute.
  `connection_integrity` now audits every commission row (`amount = base_amount × rate`),
  treats renewals as recurring add-ons on top of the initial term, and checks
  payout linkage (`payout_id` ↔ run, `payable`/`paid` ↔ run status).
- **Payout runs** (`agent_payouts`, id prefix `APAY`). `run_payouts(agent_id?,
  idempotency_key?)` sweeps `accrued` commissions into one `calculated` run per agent
  (suspended agents are skipped and reported), copying amounts and content-addressing
  the run by `commissions_hash`; swept commissions move to `payable`. A repeated
  caller key returns the original run untouched. `settle_payout(payout_id,
  external_payout_reference?)` re-verifies the swept set (existence, ownership,
  linkage, `payable` status, per-row arithmetic, `gross_amount = Σ amount`, hash chain),
  appends the `agent.payout.settled` anchor on the **platform event ledger**
  (deterministic id `AGPAY-{payout_id}`, so a retry re-uses the anchor) **before**
  any status changes, then marks commissions `paid` and the run `settled`. If the anchor
  write raises, nothing changes (fail closed); settling a settled run returns
  `already_settled`. Like supplier settlements it records the external reference and
  never calls a payment rail.
- **Broker funnel.** `agent_funnel` reports stage counts and conversion %
  (`invitations_created → approved → redeemed → affiliated_customers →
  customers_with_policy → customers_paying → customers_renewed`), commission totals
  (lifetime / initial / renewal / accrued / payable / paid), payout counts, and a BI
  summary computed by `bi_analytics_service` **restricted to the agent's own affiliated
  customers** with the per-customer `top_customers` block dropped — aggregates only,
  no PII, no other agent's subtree.
- **Routes.** Agent: `GET /api/agent/funnel`, `GET /api/agent/payouts`. Admin:
  `GET /api/admin/agents/funnel?agent_id=`, `GET /api/admin/agents/payouts[?agent_id=&status=]`,
  `POST /api/admin/agents/payouts/run {agent_id?, idempotency_key?, settle?,
  external_payout_reference?}`, `POST /api/admin/agents/payouts/settle {payout_id,
  external_payout_reference?}`. Both portals gained a funnel / payout-runs card
  (`agent-portal.html`, `admin-agents.html`). The lifecycle verb is *settle* rather than
  *execute*: `detect_sql_injection` (`web_portal/server.py`) flags the substring `EXECUTE`
  in query strings, so `?status=executed` would have been logged and blocked as an
  injection attempt.
- **Tests** (`tests/test_agent_ecosystem.py`): renewal accrues once per term and never
  twice, follows the policy anniversary (not the calendar year), never accrues without
  a start date or paid status; billing hook on premium payment; payout run idempotent
  on caller key / content / status and settlement anchored on the platform ledger;
  settlement fails closed on a tampered swept set and on an anchor-write failure;
  suspended agents skipped; funnel scoped to the agent's subtree; HTTP role scope for
  every new route; DB-mode renewals + payouts survive a restart.

Render the diagrams:

```bash
plantuml -tsvg docs/uml/agent_ecosystem.puml -o rendered
```

---

## 1. Why this exists

The deck (`web_portal/static/unicorn-investor-deck.html`) positions **AgentOS for
Insurance** — a cockpit that "turns every insurance agent into a 10× operator." In the
current codebase that layer does **not** exist:

- Seeded roles are `admin, actuary, supplier, underwriter, claims, accountant, media,
  customer` — there is **no `agent`/`broker` role** (`database/seeds.py`,
  `database/models.py`).
- "agent" in `services/` today means **AI agents/bots** (e.g.
  `marketing_sales_agent_service.py`), not a human-agent product.

This design adds a real agent role, login, a minimal portal, an invitation-driven
**affiliation hierarchy**, an **admin-approved revenue-share** model, and an
**agents-management** surface in the admin dashboard — all on top of the existing
append-only, hash-chained ledger so **data integrity is preserved**.

## 2. Goals (mapped to the request)

| Request | Design element |
|---|---|
| A real agent role + login | `role='agent'` on existing `User`/`Session`; `Agent` profile table |
| Minimal AgentOS portal | `agent-portal.html`: dashboard, invitations, my network, income |
| Agent invites customers, suppliers, (sub-agents) | `AgentInvitation` (invitee_type) + redemption in register/apply/supplier-register |
| Shared revenue **adjusted by admin in advance, per invitation** | `proposed_rate` (agent) → admin **locks** `commission_rate` before the invite is sendable |
| See customer outline (affiliated only) — hierarchy integrity | `AgentAffiliation` + scoped, PII-minimized "outline" queries |
| Income dashboard / sub-admin features | `AgentCommission` projection + ledger; agent-scoped read APIs |
| Admin dashboard → agents management | Admin section: agents CRUD, approval queue, networks, commissions, payouts |
| Keep data integrity | Locked terms snapshots + hash-chained ledger accrual + idempotency + audit logs |

## 3. Reuse of existing patterns (no reinvention)

- **Invitations + commission**: `SupplierInvitationCode` already has `referrer_id` and
  `commission_override` — the agent invitation mirrors and formalizes this.
- **Hash-chained ledger**: `PlatformLedgerEntry` (`sequence_no`, `previous_hash`,
  `entry_hash`) via `services/platform_event_ledger_service.py` — every commission and
  affiliation event is appended here.
- **Auth**: existing `User` + `Session` + token auth; add `agent` role (kept out of
  `is_staff()` so agents do not get admin-portal scope).
- **Settlement**: `services/supplier_settlement_service.py` + marketplace repos
  (`idempotency`, `outbox`) are the template for agent payouts (phase 2).
- **Validation/error/pagination shapes** per `AGENTS.md` (`{"error": ...}`,
  `{"items": [], "page":1, "page_size":50, "total":0}`).

## 4. Data model (new + touched)

New tables: `agents`, `agent_invitations`, `agent_affiliations`, `agent_commissions`
(+ `agent_payouts` in phase 2). Touched: `Customer.referring_agent_id`,
`Supplier.referring_agent_id`, `User.role` accepts `agent`. Full attributes and
relationships are in **`docs/uml/agent_ecosystem.puml`** (page 2).

### Integrity invariants (the "hierarchy integrity" the request asks for)

1. **One active affiliation per principal** — a customer/supplier has at most one active
   referring agent → no double-counted commission.
2. **Locked terms** — `commission_rate` is immutable once an invitation is approved and
   once an affiliation is created; re-pricing requires a **new** invitation/affiliation
   version (append-only, never in-place edits).
3. **Ledger-backed** — every `AgentCommission` row is backed 1:1 by a hash-chained
   `PlatformLedgerEntry`. Reversals (refunds/chargebacks) are **compensating entries**,
   never deletes/updates.
4. **Idempotent accrual** — unique `(source_event_id, affiliation_id)` prevents double
   accrual; reuses the marketplace `idempotency` repository.
5. **Scope isolation** — agents can only read their own subtree; the customer "outline"
   excludes PII/medical and exposes only name, status, policy count, and the premium
   basis that drives their commission (avoids cross-tenant leakage per `AGENTS.md` §10).

## 5. Revenue-share engine

On revenue events that already post to the platform ledger — **policy premium paid**
(`billing_service`) and **marketplace order settled** (`marketplace_service`) — a
commission hook looks up the principal's **active** affiliation, computes
`amount = base_amount × locked_rate`, and appends an `agent.commission.accrued` ledger
entry plus an `agent_commissions` projection row. See UML page 4.

Accounting stance (capital-light, per deck): commission is an **expense/revenue-share**
booking, **never** booked as new PHINS revenue.

## 6. API surface (proposed)

**Agent (role=agent), all scoped to own subtree:**
- `POST /api/agent/invitations` — propose invitation (`pending_approval`)
- `GET /api/agent/invitations` — list/track
- `GET /api/agent/network/customers` — paginated affiliated-customer **outline**
- `GET /api/agent/network/suppliers`
- `GET /api/agent/income/summary` — accrued / payable / paid totals + counts
- `GET /api/agent/income/ledger` — per-affiliation commission lines
- `GET /api/agent/funnel` — broker funnel (own subtree, aggregates only) — §C
- `GET /api/agent/payouts` — own payout runs — §C

**Admin (role=admin) — Agents Management:**
- `GET/POST /api/admin/agents`, `PATCH /api/admin/agents/{id}` (suspend, default rate)
- `GET /api/admin/agent-invitations?status=pending_approval`
- `POST /api/admin/agent-invitations/{code}/approve` `{commission_rate}` (locks rate)
- `POST /api/admin/agent-invitations/{code}/reject`
- `GET /api/admin/agents/{id}/affiliations` (network tree)
- `GET /api/admin/agents/{id}/commissions`
- `POST /api/admin/agents/payouts/run`, `POST /api/admin/agents/payouts/settle`,
  `GET /api/admin/agents/payouts`, `GET /api/admin/agents/funnel?agent_id=` — §C
  (shipped as flat admin routes rather than `/agents/{id}/payouts`)

**Public/redemption:** reuse `/api/invitations/validate?code=`; redemption happens in
the existing register/apply and supplier-register flows, creating the affiliation with
the locked rate.

## 7. Agent portal (minimal) & Admin agents-management

- **Agent portal** (`agent-portal.html`): income dashboard (KPIs + trend), invitations
  (create → awaiting-approval → sent → accepted), my network (affiliated customer/supplier
  outline), payout history.
- **Admin dashboard → Agents management**: agents list + create/suspend + default rate;
  **invitation approval queue** (adjust/lock commission in advance); per-agent network
  tree, commission ledger, and payout runs; commission reversal (compensating entry).
  Every admin action is written to `AuditLog`.

## 8. Phasing (implementation, after approval — described by scope, not calendar)

1. **Schema & migration**: new tables + `referring_agent_id` columns; in-memory parity;
   `database/seeds.py` demo agent + repository wiring.
2. **Auth/role**: add `agent` role to login, session, route guards (kept out of staff).
3. **Services**: `agent_ecosystem_service.py` (invitations/affiliations/scope) +
   `agent_commission_service.py` (accrual engine, idempotency, ledger append).
4. **APIs**: agent + admin endpoints (server.py / api_extensions.py wiring).
5. **Revenue hooks**: subscribe accrual to existing premium/settlement events.
6. **UI**: `agent-portal.html` + admin agents-management section.
7. **Tests**: success/failure paths, scope isolation, idempotency, ledger-chain integrity,
   in-memory + DB modes.

Blast-radius note: touches `database/` (models/seeds/repos), `web_portal/server.py` +
`api_extensions.py` (routing/auth), `services/` (2 new), and static UI — additive and
behind the new role, so existing flows are unaffected.

## 9. Decisions (confirmed) and follow-ups

All six decisions were confirmed (see the status box at the top) and are implemented
in v1. Tracked follow-ups:

- ~~**Per-renewal accrual**~~ — shipped (§C): `accrue_for_policy(policy, period)` keyed
  on the renewal term, driven by paid premium bills.
- **Automatic event hooks**: the billing "premium paid" hook is shipped (§C,
  `accrue_agent_commission_for_paid_bills`); the marketplace "order settled" hook
  remains a follow-up (the `gmv` basis is accepted on invitations but nothing drives
  its accrual from the order book yet; premium basis is driven from the policy and
  paid-bill books).
- ~~**`agent_payouts` settlement run**~~ — shipped (§C). **Sub-agent payouts**
  (hierarchy roll-up) remain a follow-up.
- **Self-serve redemption** inside the customer/supplier registration flows (v1 redeems
  via the admin endpoint, which is sufficient to prove the full lifecycle).
