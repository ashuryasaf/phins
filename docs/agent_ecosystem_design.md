# PHINS Agent / Broker Ecosystem ("AgentOS") — Design & Scoping

> **Status: DESIGN / SCOPING ONLY — awaiting approval. No implementation in this PR.**
>
> This document and `docs/uml/agent_ecosystem.puml` model the missing agent/broker
> layer so the investor deck's **AgentOS** claim is backed by working software.
> Implementation will follow in the **same PR** once the model is approved.

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

**Admin (role=admin) — Agents Management:**
- `GET/POST /api/admin/agents`, `PATCH /api/admin/agents/{id}` (suspend, default rate)
- `GET /api/admin/agent-invitations?status=pending_approval`
- `POST /api/admin/agent-invitations/{code}/approve` `{commission_rate}` (locks rate)
- `POST /api/admin/agent-invitations/{code}/reject`
- `GET /api/admin/agents/{id}/affiliations` (network tree)
- `GET /api/admin/agents/{id}/commissions`
- `POST /api/admin/agents/{id}/payouts` (settlement run — phase 2)

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

## 9. Open questions (need your decision before implementation)

1. **Sub-agents / hierarchy depth**: single-level agent→principal, or multi-level
   agent→sub-agent trees with cascading override commissions? (UML supports both;
   default proposal: support `parent_agent_id` but enable only single-level payouts in v1.)
2. **Commission basis**: percentage of premium (default), of marketplace GMV, and/or a
   one-time bounty per accepted invite? (Model supports all three via `commission_basis`.)
3. **Recurring vs one-time**: commission on first premium only, or on every renewal while
   the affiliation stays active? (Proposal: recurring while active.)
4. **Customer consent/visibility**: should affiliated customers see that an agent is
   attached to their account? (Proposal: yes, a neutral "referred by" line.)
5. **Demo agent account**: create a seeded `agent` demo login (env-var password, like the
   other roles) for the PR's manual testing? (Proposal: yes, `PHINS_AGENT_PASSWORD`.)
6. **Payouts in v1**: include `agent_payouts` settlement now, or accrual + dashboard only
   in v1 and payouts in a follow-up? (Proposal: accrual + dashboard in v1.)

Please review the UML (`docs/uml/agent_ecosystem.puml`) and answer §9; I'll then
implement on this branch and push to the same PR.
