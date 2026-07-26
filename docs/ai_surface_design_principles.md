# PHINS AI Surface — Design Principles & Data-Integrity Notes

This note documents the deliberate design of the PHINS AI surface
(`claims_bot_service`, `assessment_ai_service`, `ai_risk_reports_service`,
`ai_trading_engine`, `video_agents_service`,
`bi_analytics_service`, `ai_decision_log`, `ai_model_registry`) and the
data-integrity guarantees added by the agent-native hardening work.

It exists so future contributors do not "fix" intentional determinism, and so
the audit trail and durability guarantees are not accidentally regressed.

## 1. Determinism is intentional (do not move adjudication into prompts)

Most PHINS "AI" is **deterministic, rule/statistics based — by design**, not by
omission:

- **Claims adjudication** (`claims_bot_service.py`): weighted component scores,
  fraud indicators, hidden-condition detection, and the approve/deny/refer
  recommendation are explicit, reproducible Python. Money- and coverage-adjacent
  decisions must be explainable and replayable for compliance.
- **Trading signals & AutoPilot** (`ai_trading_engine.py`): indicators, signal
  generation, position sizing, and pre-trade risk checks use fixed thresholds.
- **Risk scoring** (`ai_risk_reports_service.py`): statistical profiling,
  anomaly rules (z-score / IQR), and additive risk scores.
- **BI insights** (`bi_analytics_service.py`): threshold rules over computed
  dashboards (e.g. loss-ratio / approval-rate triggers).
- **Automated underwriting/claims** (`ai_automation_controller.py`): rule scorer
  is authoritative; a trained model may *inform* (logged for drift) but the
  rules decide.

**Rule of thumb:** prompts may *explain* a decision; they must never *make* a
payout, pricing, underwriting, or trade-execution decision. A low
"prompt-native" score on this surface is correct for a regulated insurer/fintech.

## 2. The LLM template: `assessment_ai_service`

The one clean LLM-backed path is the assessment advisory narrative. It is the
pattern to copy for any *future* generative narration:

- **Off by default.** The live-LLM path runs only when
  `PHINS_ASSESSMENT_AI_ENABLED` is truthy and an OpenAI-compatible endpoint is
  configured (`PHINS_ASSESSMENT_AI_ENDPOINT`, `PHINS_ASSESSMENT_AI_API_KEY`,
  `PHINS_ASSESSMENT_AI_MODEL`, `PHINS_ASSESSMENT_AI_TIMEOUT`).
- **Deterministic fallback.** With the LLM disabled or failing, a deterministic
  offline narrative is produced — behavior never depends on a network call.
- **Facts-only, non-authoritative.** The system prompt forbids inventing
  numbers/identifiers/conclusions and forbids issuing a final underwriting
  decision; the model summarizes already-extracted facts and flags items for
  human review.
- **Egress redaction.** `PHINS_ASSESSMENT_AI_REDACT` redacts fact values before
  they leave the platform. Any new LLM feature handling customer data must
  provide equivalent redaction and must not send full PII payloads.

## 3. Durable audit parity (data-integrity guarantees)

`services/ai_audit_bridge.py` is the keystone. It mirrors AI events into the
durable `audit_logs` table, and is wired at server startup
(`run_server` / `bootstrap_runtime_state_for_command`) when a database is
configured. Contract:

- **Best-effort, never fatal.** A DB failure must never raise into a live AI
  decision/trade path. In-memory state stays the runtime source of truth; the
  DB mirror is additive durability.
- **Additive / append-only.** Each event writes a new row; nothing mutates or
  deletes prior rows.

Surfaces wired for audit parity:

| Surface | Durable audit events |
|---|---|
| `ai_decision_log` (via bridge) | `ai_decision`, `ai_decision_override` |
| `claims_bot_service` | `claims_bot_*` (e.g. `claims_bot_probability_report_generated`) |
| `ai_trading_engine` | `ai_bot_trade_executed` (per executed bot trade) |
| `ai_risk_reports_service` | `risk_report_document_uploaded`, `risk_report_generated`, `risk_report_revoked` |
| `video_agents_service` | `video_job_submitted`, `video_job_completed`, `video_job_failed` |

These give the in-memory/JSON-backed AI stores an independent compliance trail
that survives process restarts.

> Note: `ai_decision_log` durable persistence was previously wired **only in
> tests**. It is now wired in the running server, so the AI decision trail is
> durable in production database mode.

## 4. Capability discovery (agent + human parity)

`services/ai_capabilities.py` is a single machine-readable catalog of AI
features (description, UI entry URL, programmatic API, allowed roles, sample
prompts), served role-filtered at `GET /api/ai/capabilities`. It is the
foundation for action parity: whatever a user can discover and do, an agent can
discover and invoke through the same descriptors.

## 5. Canonical BI path

`services/bi_analytics_service.py` is reachable via
`web_portal/api_bi_analytics.py`, wired into `do_GET` at
`/api/bi/{executive-dashboard,delivery-analytics,customer-analytics,
supplier-analytics,insights,revenue-forecast}`. Previously these handlers were
implemented but unrouted, leaving two divergent BI paths; the service now has a
single canonical aggregation route.

## 6. Stock data helpers

The Investment AI tool (`investment_ai_tool_service`) was removed in July 2026.
Its shared live stock data helpers (Alpha Vantage quotes/technicals/news and
the live-resolving `STOCK_DATABASE` fallback used by the trading platform)
now live in `services/stock_data_service.py`. Terminal API authentication
moved to `services/terminal_access_service.py` (`TERMINAL_ACCESS_KEY`, with
the legacy `INVESTMENT_AI_ACCESS_KEY` environment variable still honored).

---

_Last updated: July 25, 2026 — Investment AI removal; market data extraction._
