# Assessment: the last 24 merged pull requests against their stated targets

Date: 28 November 2026.
Code assessed: `main` at commit `28d4db48b501c0b68e3d7db011ff2bb040006ba5` (the merge of #806), read at 09:07 UTC.

## 1. Verdict

The integrity scorecard reports **100/100**. The evidence supports **82/100** under the plan's own rule, and that 82 carries two exceptions.

| Score | Value | Basis |
|---|---:|---|
| Reported by the scorecard on `main` | 100 | Run: `python3 scripts/run_erp_integrity_scorecard.py` prints "Claimed score: 100/100". |
| Supported under the plan's rule | 82 | The plan says: "A band only scores when its Verification Contract gates are green. Partial credit is not claimed." The gates for 72 and 82 are green at test level. The gates for 93 and 100 are not. |
| Strictest reading | 72 | The plan's definition of done also requires tests green with the database on. Two of the four units behind 82 do not meet that today (section 3). |
| The scorecard's own formula, fed with this review's unit statuses | 82 claimed, 92.4 progress | U1–U8 counted as landed, U9–U14 as partial. No new scoring method was introduced. |

The reason for the difference is how the scorecard measures. It marks a unit "landed" when named files exist and contain named strings. It does not run a gate. Six units (U9–U14) have their files and tests, and are not finished.

The three findings that matter most for money and data:

1. **A settled carrier remittance can be settled a second time after a restart.** Remittance runs, bordereaux, trust movements, cession entries, premium-tax accruals and soft-close status are held in process memory only. In a restart test the settled run was not found, and the same binder and month were built and settled again with no refusal. Only the hard close survived.
2. **80 tests that passed before these 24 PRs no longer pass when the whole suite runs, and two more are red on their own.** No CI workflow runs the whole suite, so nothing reported it. The cause of the 80 is one test file added in #790 that empties the shared balance sheet and does not put it back. The product code behind those 80 tests passes when each file runs alone.
3. **The last three PRs (#804, #805, #806) took the claimed score from 82 to 100 with no review recorded.** They were open for 13.5, 9.3 and 5.6 minutes, received zero review submissions, and all five automated review checks ended without running. Together they added 3,099 lines.

What held up: the first eight units (U1–U8) are real and tested. The database-mode financial CI is green on the assessed commit and was reproduced here (222 passed). The eight PRs outside the programme delivered what they described; every suite they name passes on `main`.

### How to read this report

Scope: the 24 most recently merged PRs, #781 to #806 (#784 is still open and #798 is not a pull request). Sixteen belong to the 58→100 integrity programme and are measured against the plan merged in #788 (`docs/plans/2026-11-27-erp-mga-integrity-100.md`). The other eight are measured against their own descriptions.

Every figure has one of four statuses:

| Status | Meaning |
|---|---|
| Run | Produced by running the code or tests during this assessment. |
| Read | Established by reading the code or a GitHub record. |
| Claimed | Stated by the PR; not checked here. |
| Not verifiable | Cannot be established from this environment. Section 5 says why. |

Nothing was written to a book, seal or record. No production or staging system was called. Tests ran against in-memory stores or a scratch SQLite file under `/tmp`, with `DATABASE_URL` and `DATABASE_PUBLIC_URL` unset. No fixture or generated file was refreshed. `git status` was clean after every run. Two commands in the plan's Verification Contract were deliberately not run; section 5 explains.

## 2. Each of the 24 PRs against its stated target

### 2.1 The eight PRs outside the programme

| PR | Stated target | Found on `main` | Verdict |
|---|---|---|---|
| #781 | Close a gap where a confidential page opened under another spelling of its path; adviser link to the Legal & Funding Center (hub plus 15 instruments, reading copy only); Hebrew edition of the NBA Law request. | Run: `/pitch-dashboard.html/`, `/./business-plan.html` and a `..` path all resolve to confidential; `/join.html/` stays public. Read: 15 documents in `LEGAL_CENTER_DOCUMENTS`; six request files (English and Hebrew, md/html/pdf). Run: `test_confidential_access` 87 passed (87 claimed), `test_nba_law_legal_services_request` 13, `test_legal_docs_static_integrity` 36. | Met |
| #782 | Letterhead banner on the hub; banner and "Copy link with banner" on the share-links card. Claimed 180 passed, 1 failed (already failing on `main`). | Read: `.lc-banner` in the hub. Run: the same five files give 181 passed, 0 failed on `main`. | Met |
| #783 | Refresh the counts in `AGENTS.md`. | Run at its merge commit: 294 test files, 11 root tests, 163 service modules, 21 repository files, 44 repository properties, `server.py` 69,117 lines — all as written. The counts are stale again after the programme (gap 9). | Met |
| #785 | `accumulated_aum` on the balance sheet: wallet credits split by the mix written on the original application; nothing historical rewritten; the GET writes nothing. | Read: field present in `server.py` and `cashflow_unified_report.py`. Run: `test_balance_sheet_integrity` 23 passed, `test_cashflow_unified_report` 20. | Met |
| #786 | Keep the ledger snapshot as a checksummed database row; stop the accountant dashboard polling; order routes on the trading terminal need an admin session. Claimed 24 and 43 passed. | Run: `test_ledger_snapshot_store` 24 passed, `test_autopilot_safety_routes` 43, `test_post_deploy_integrity` 17, `test_sms_provider_retirement` 11. | Met |
| #787 | Read-only ADL 3 premium release cost test, two routes. Claimed 19 passed. Disclosed that `main` had 238 failures and 38 errors in a whole run. | Run: `test_adl3_release_cost` 19 passed. | Met |
| #792 | Fix the kernel-pin restore that hung. | Run: `test_financial_unification` 84 passed, `test_premium_flow_reconciliation` 19. The post-deploy check in its test plan is unticked, and one review thread was open at merge. | Met in code. The effect in production is not verifiable. |
| #794 | Kernel pins above the statement; restore from policy age or a stored quote; refusal reasons listed. | Read: `no_age_to_reprice`, `restored_from_stored_quote`, `refusal_reasons` present. Run: same suites as #792. The signed-in check on the deployed site is unticked. | Met in code. The effect in production is not verifiable. |

### 2.2 The sixteen programme PRs

| PR | Unit | Stated target | Found on `main` | Verdict |
|---|---|---|---|---|
| #788 | Plan | Publish the 58→100 plan: 14 units, four bands, gates, definition of done. | Read: the plan file. | Met |
| #789 | U1 | Production refuses to start without a database or on an ephemeral ledger path. Claimed 28 passed. | Run: `test_boot_integrity_u1` 33 passed. Two review threads open at merge. A real Postgres outage is not verifiable here. | Met |
| #790 | U2 | Sealed database tables for wallets, withdrawals, NFT ledger, investment accounts and balance-sheet counters; modes off / dual / db. Claimed 32 passed. | Run: `test_fiduciary_store` 38 passed alone. Read: 5 tables and 5 repository classes; the default mode is `dual`, and a code comment says production "should move to `db` for AE2 full credit". Merged with a high-severity security finding open (closed by #791), 7 of 35 threads open, and its own boxes "CI green on tip" and "Human merge after Bugbot / security clear" unticked. Its test file causes finding 2. | Partly met |
| #791 | U2 fix | Close that security finding: flush the tables before the file write, fail closed. | Run: covered by the 38 above and by the 222 in database mode. | Met |
| #793 | U3 | Database-mode financial CI. The plan adds "block merge if red". | Read: `db_financial_ci.yml` succeeded on the assessed commit. Run: the same seven suites on scratch SQLite, 222 passed. The workflow covers those seven suites only, not the programme's own suites. | Met. Merge blocking is not verifiable. |
| #795 | U4 | Money Gate on withdrawal release, agent commission settle and claim payout; golden fixtures. | Run: `test_money_gate` 12 passed; 4 `money_gate` goldens pass. Registered a new job type without updating `test_jobs_adapters`, which has failed since this PR (Run: passes at #794, fails at #795). | Met, with one regression |
| #796 | U5 | Durable accounting journal. Claimed 23 passed. | Run: `test_accounting_journal` 23 passed in memory; 22 of 23 with the database on (the one failure is a test that assumes the in-memory default). | Met |
| #797 | Scorecard | The scorecard tool; claimed 72, progress 77.0. | Run: `test_erp_integrity_scorecard` 17 passed. Read: the production deploy of its merge commit failed; the next successful one is #799's, 13 minutes later. The tool measures file presence, not gates. | Partly met |
| #799 | Deploy fix | Health-check window 120→300 s, container start period 15→180 s, lazy scorecard import. | Read: `railway.json` 300, `Dockerfile` 180 s; production deploy succeeded. Its three test-plan boxes are unticked. | Met |
| #800 | U6 | Daily books-tied certificate, required for withdrawal release, commission settle and claim payout. | Run: `test_books_tied_certificate` 18 passed, 1 failed on `main`. The failing test passed at #800, #801 and #802 and has failed since #803. Two threads open at merge. | Met |
| #801 | U7 | Commission clawback; "Closes P1 → claimed score 82". | Run: `test_commission_clawback` 11 passed in memory. With the database on, 3 of the 11 fail in suite order and pass alone. | Partly met |
| #802 | U8 | Chart of accounts and period close. | Run: `test_coa` 4, `test_period_close` 13 in memory; one period-close test fails in database mode in suite order. Hard close survives a restart; soft close does not. The engine only posts with today's date, so "a post dated in a closed month" is tested for the current month only. | Partly met |
| #803 | U9 | Remittance and bordereaux; claimed 82, progress 87.5. States that the durable repository is not included. | Run: `test_remittance_bordereaux` 13 passed, including the cent-tie. Run: after a restart the settled run is gone and the period settles again (finding 1). Its change to the Money Gate broke #800's test. One thread open; five automated checks did not run. | Partly met |
| #804 | U10, U11 | Trust, reinsurance cession, premium tax; "P2 → claimed 93". Claimed 40 passed. | Run: the four named files give 40 passed. Read: a trust deficit is reported and blocks nothing; the tax accrual has no caller outside tests; the rates are labelled specimens. State is process memory. | Partly met. The claim of 93 is not supported. |
| #805 | U12–U14 | Money API modules and unit of work, binder tenancy, snapshot shards and queue alerts; "P3 → claimed 100". | Read and Run: section 3, band P3. | Partly met. The claim of 100 is not supported. |
| #806 | Closeout | Tick every box in the plan's checklist; add the missing schema upgrade entry for #805's columns; shadow-pricing HTTP tests. Claimed 14 passed. | Run: `test_pricing_shadow_create` 5 and `test_pricing_shadow_service` 8, plus the one binder test, 14 passed. The schema entry is on `main`. The ticked checklist is not supported by the gates. | Partly met |

### 2.3 Review record

All 24 were merged by one account. All 263 review submissions came from the automated reviewer (260 comments, 3 approvals); no other reviewer is recorded. The sixteen programme PRs merged within 14.45 hours on 27 November. "Did not run" means the check ended neutral, which is not a pass.

| PR | Open before merge | Commits | Lines added | Automated review submissions | Review threads open at merge | Test-plan boxes left unticked | Automated checks that did not run on the final commit | Production deploy of the merge commit |
|---|---:|---:|---:|---:|---|---:|---|---|
| #781 | 29.2 min | 9 | 2,106 | 7 | 0 of 2 | 0 | none | succeeded |
| #782 | 11.2 h | 4 | 188 | 2 | 0 of 0 | 0 | none | succeeded |
| #783 | 9.0 h | 1 | 21 | 1 | 0 of 0 | 0 | none | succeeded |
| #785 | 33.7 min | 3 | 625 | 7 | 0 of 3 | 0 | none | succeeded |
| #786 | 4.6 h | 16 | 1,587 | 16 | 0 of 6 | 0 | none | succeeded |
| #787 | 77.9 min | 7 | 2,807 | 4 | 0 of 1 | 0 | vulnerability scan, Bugbot | succeeded |
| #788 | 11.7 min | 1 | 337 | 2 | 0 of 0 | 0 | none | succeeded |
| #789 | 65.2 min | 4 | 538 | 9 | 2 of 8 | 0 | none | succeeded |
| #790 | 2.8 h | 23 | 2,803 | 78 | 7 of 35 | 2 | vulnerability scan, Bugbot | succeeded |
| #791 | 28.0 min | 7 | 483 | 19 | 0 of 4 | 2 | none | succeeded |
| #792 | 16.9 min | 2 | 473 | 5 | 1 of 2 | 1 | none | succeeded |
| #793 | 39.9 min | 6 | 1,042 | 14 | 0 of 7 | 2 | none | succeeded |
| #794 | 19.2 min | 6 | 392 | 7 | 0 of 0 | 1 | none | succeeded |
| #795 | 3.2 h | 3 | 1,050 | 3 | 0 of 0 | 2 | vulnerability scan, Bugbot | succeeded |
| #796 | 60.2 min | 10 | 2,079 | 19 | 0 of 9 | 2 | none | succeeded |
| #797 | 52.6 min | 8 | 800 | 25 | 0 of 8 | 2 | none | failed |
| #799 | 6.7 min | 1 | 24 | 2 | 0 of 0 | 3 | none | succeeded |
| #800 | 15.1 min | 6 | 1,579 | 17 | 2 of 6 | 0 | vulnerability scan, Bugbot | succeeded |
| #801 | 12.1 min | 3 | 925 | 4 | 0 of 1 | 0 | vulnerability scan, Bugbot | succeeded |
| #802 | 23.3 min | 5 | 1,647 | 16 | 0 of 6 | 0 | review router | succeeded |
| #803 | 33.4 min | 3 | 1,833 | 6 | 1 of 6 | 0 | review router, reviewer assignment, vulnerability scan, Bugbot, security reviewer | succeeded |
| #804 | 13.5 min | 1 | 1,577 | 0 | 0 of 0 | 0 | review router, reviewer assignment, vulnerability scan, Bugbot, security reviewer | succeeded |
| #805 | 9.3 min | 2 | 1,344 | 0 | 0 of 0 | 0 | review router, reviewer assignment, vulnerability scan, Bugbot, security reviewer | succeeded |
| #806 | 5.6 min | 1 | 178 | 0 | 0 of 0 | 0 | review router, reviewer assignment, vulnerability scan, Bugbot, security reviewer | succeeded |

Totals: 26,438 lines added across 296 file changes; 104 review threads, 13 open at merge; 17 test-plan boxes unticked.

## 3. The programme against the plan, band by band

The plan sets four gates per band. A band scores only when all of its gates are green.

### P0 — baseline 58 to 72 (U1–U3): gates green

| Gate | Result | Evidence |
|---|---|---|
| AE1: production exits when the database is unreachable | Green at test level | Run: 33 passed. A real Postgres outage: Not verifiable. |
| AE2: wallets and balance-sheet counters restore from the database after a redeploy without the volume | Green at test level | Run: the round-trip test passes on SQLite. Read: the default mode is `dual`, not `db`. Production's mode and a real redeploy: Not verifiable. |
| Database-mode financial CI green | Green | Read: the workflow succeeded on the assessed commit. Run: 222 passed locally. |
| No "always in-memory" wallet path in production code | Green | Read: the old comment and path are gone. Medical purchases are still process-local, as the code states. |

### P1 — 72 to 82 (U4–U7): gates green in memory mode, with two exceptions

| Gate | Result | Evidence |
|---|---|---|
| AE3: red books return 409 on withdrawal release and commission settle | Green | Run: 12 passed, in both modes. |
| AE6: a lapse produces a clawback reversal row | Green in memory; not green with the database on | Run: 11 passed in memory. Database mode: 3 fail in suite order, each passes alone on a fresh scratch database. |
| Journal durable | Green | Run: 23 passed; peer-process test included. Read: in the default `dual` mode a transient journal failure keeps the in-memory post, so "durable before the in-memory book updates" holds strictly only in `db` mode. |
| Daily `finance.books_tied` event under green books | Green, one red test | Run: 18 passed, 1 failed. Read: the clock is armed at serve boot. Whether production issues the certificate: Not verifiable. |

The two exceptions: one test in this band has been red on `main` since #803, and the plan's definition of done ("tests green (including `USE_DATABASE=true` where money is touched)") is not shown for U6 and U7. The 82 stands on the gates as written; the strictest reading holds the score at 72 until both are cleared.

### P2 — 82 to 93 (U8–U11): gates not green

| Gate | Result | Evidence |
|---|---|---|
| AE4: a post into a hard-closed month is refused | Green, narrow | Run: 13 passed; the refusal still holds after a restart. Read: every engine post is dated today, so only the current month is exercised. Soft-close status is lost on restart (Run). |
| AE5: bordereau ties to ledger premium cash to the cent, seal matches | Green at test level | Run: 13 passed. The bordereau and its seal are process memory and are gone after a restart (Run). |
| Trust deficit fail-closed | Not green | Read: a deficit is returned as a finding. No money operation consults it. The bank balance it compares with is a number typed into the request, not a bank import. |
| Cession cash book live | Not green | Run: one cession entry before restart, zero after. No database table. |
| Tax additive only | Not operating | Read: the accrual function is additive and its test passes, but nothing outside the tests calls it. The only route is a read-only status GET. |

Of the 17 tables the plan names, 6 exist and 11 do not: `remittance_runs`, `bordereaux`, `trust_balances`, `trust_movements`, `treaties`, `cession_entries`, `fiscal_periods`, `coa_accounts`, `period_close_packs`, `wallet_transactions`, `investment_allocations` (Read). The remittance, trust, cession and period-close repositories the plan names do not exist.

### P3 — 93 to 100 (U12–U14): gates not green

| Gate | Result | Evidence |
|---|---|---|
| Money routes extracted | Partial | Read: three API modules dispatch first, and the inline handlers remain. `server.py` went from 70,441 to 70,569 lines in #805; the plan expected it to shrink. Run: the unit-of-work wrapper yields no session, so it groups nothing. There is no route parity suite. |
| Multi-entity leakage tests green | Not green | Read: one test exercises the helper functions directly. The helpers have no caller outside the tests, the routes accept any `binder_id`, and only `Policy` carries the columns. |
| Snapshot and queue SLOs green | Not green | Run: `test_ledger_snapshot_slos` 5 passed, but the write path never calls the shard builder; a snapshot over the cap is still refused as before. Read: the queue alert report has no caller outside the tests. Run: the Durability Guard's default run fingerprints an empty dictionary. |
| Scorecard checklist all checked | Green | Read: #806 ticked every box. |

### Integrity invariants the plan sets for every PR

| Invariant | Result |
|---|---|
| No second `price_policy` writer | Held (Read). |
| No rewrite of billed premium, seed claims reserve or broken-checksum rows | Held in the code read; no counter-example found. |
| New tables expose a checksum and withhold on mismatch | Held for the six tables that exist (Read). |
| Money Gate cannot be bypassed except by audited break-glass | Not held: `PHINS_MONEY_GATE=0` switches the gate off with no ledger event (Read). |

## 4. Gaps, ranked by risk to money and data

1. **Carrier remittance state is not durable; a second settlement is possible.** (Run) After a restart: 0 runs listed, 0 bordereaux, 0 trust movements, 0 cession entries, no settled run for the period. Building and settling the same binder and month again succeeded. The two original events are still on the platform ledger, but the remittance code does not read them back. Until this is fixed, a restart between two settle requests for the same period is not refused.
2. **Money Gate coverage.** (Read) The gate is on withdrawal release, commission settle and clawback, claim payout and remittance settle. It is not on supplier settlement payout or on referral reward cash acceptance. The environment switch is unaudited. A trust deficit blocks nothing. Remittance settle does not require the daily certificate, because the list in `books_tied.py` has four operations and the list in `money_gate.py` has five.
3. **Unreviewed merges that changed the schema.** #805 added two columns to the `Policy` model without the upgrade entry for an existing Postgres table; #806 added it. Production deployed #805 at 23:29 UTC and #806 at 23:50 UTC, 21 minutes apart (Read). The effect on the live database in that window is Not verifiable. The database CI starts from an empty database, so it cannot catch a missing upgrade entry.
4. **Tests regressed and no CI reports it.** (Run) Whole suite in memory on `main`: 4,511 passed, 235 failed, 115 errors, 1 skipped. The commit before #781: 4,218 passed, 242 failed, 47 errors, 1 skipped. Each test is counted once here; pytest's own last line for `main` reads 4,564 passed, 259 failed, 115 errors, because it counts twice the 77 tests that ran and then errored at teardown. Most of these failures predate the 24 PRs: 267 tests do not pass on either commit. The change attributable to the 24:
   - 81 tests passed before and do not pass now. 80 of them fail only after `tests/test_fiduciary_store.py` runs, because `test_dual_full_purge_empty_books_preserve_absent` empties the process-wide balance sheet (70 in `test_referral_rewards`, 8 in `test_money_flow_integrity`, 1 each in `test_smoke_critical_paths` and `test_financial_unification`). Each of those files passes alone.
   - The 81st, `test_jobs_adapters::test_register_all_binds_every_adapter`, fails alone: seven job types were registered and the test's expected list was not updated.
   - `test_books_tied_certificate::test_freshness_exception_fails_closed` fails alone, since #803. A second test in that file, `test_inprocess_daily_clock_issues_and_is_idempotent`, fails in the whole run and passes alone.
   - With the database on, the fifteen programme suites give 248 passed, 7 failed, against 254 passed, 1 failed in memory.
   - The only workflow that runs pytest is the seven-suite database job, so none of this was visible at merge.
5. **Snapshot durability is unchanged.** (Run, Read) The over-cap path still refuses the write and leaves the stale marker. The queue alert and the Durability Guard are not connected to anything that runs.
6. **U12 and U13 are scaffolding.** (Read) The unit of work does not group writes, and binder scope is not enforced on any route.
7. **Premium tax does not operate.** (Read) No accrual is ever created outside a test, and the rates are specimens.
8. **The scorecard measures file presence.** (Read) It will keep reporting 100 whatever the state of gaps 1–7.
9. **`AGENTS.md` counts are stale.** (Run) It says 296 test files, 44 repository properties, 21 repository files and about 69k lines in `server.py`. `main` has 311, 50, 23 and 70,569.

## 5. What could not be verified, and why

| Item | Why |
|---|---|
| Production values of `PHINS_FIDUCIARY_MODE`, the journal mode and `PHINS_MONEY_GATE` | No production system was called, by design. |
| Whether production issues the daily books-tied certificate | Same. |
| The effect of the 21 minutes between #805 and #806 on the live database | Same. On SQLite the columns were present at #805 (Run), but that path is not the Postgres one. |
| AE1 against a real Postgres outage; AE2 on a real redeploy | No Postgres and no deploy target here; the tests use SQLite. |
| Whether a red check blocks a merge | The branch-protection API returned 403. The repository has no rulesets. |
| Postgres-specific behaviour of the database-mode runs | SQLite was the proxy, as `AGENTS.md` allows. |
| `python3 validate_system.py` and `bash quick_smoke_test.sh` (both in the plan's Verification Contract) | Not run. Both start the server with production defaults (database on) and the smoke test posts a policy, a bill and a payment. Running them would have broken the no-write rule of this assessment. |
| The 22 tests that failed on the earlier commit and pass on `main` | The two whole-suite runs used different temp directories, which can add failures on the earlier side. The figure is reported and not relied on. The 81 in the other direction were reproduced separately. |
| Why five database-mode tests fail in suite order | They pass alone on a fresh scratch database, which points to state left by an earlier test. The cause was not diagnosed, because fixing is out of scope. |

## 6. Recommended follow-ups

Nothing below was done as part of this assessment. In order:

1. Make remittance runs, bordereaux, trust movements and cession entries durable, and refuse a second settlement for a binder and period from the durable record. Until then, treat remittance settle as a manual, single-operator step.
2. Reset the scorecard's reported figure to what the gates support, and make each unit's status depend on a gate that runs, not on a file that exists.
3. Restore the balance sheet in `test_dual_full_purge_empty_books_preserve_absent`; update the expected job list in `test_jobs_adapters`; make the two high-value operation lists one list and decide whether remittance settle needs the certificate.
4. Add the programme's own suites to the database-mode CI job, and add a CI job for the in-memory suite with the pre-existing failures recorded as a baseline.
5. Put the Money Gate on supplier settlement payout and referral cash acceptance; record a ledger event when `PHINS_MONEY_GATE` is off; have remittance settle refuse on an open trust deficit.
6. Confirm on production that the `policies` table has `binder_id` and `entity_id`, and read the logs for the 21 minutes after the #805 deploy.
7. Give #804, #805 and #806 the review they did not get.
8. Wire or remove: the snapshot shard path, the queue alert, the Durability Guard default, the premium-tax accrual.
9. Refresh the `AGENTS.md` counts.

## 7. Evidence index

The evidence files are attached to the assessment run under `pr-assessment/` and are not committed to this repository. Every figure in this report was checked against them before commit.

| Evidence | File | How it was produced |
|---|---|---|
| PR metadata, bodies, reviews, checks | `pr-<N>.json`, `pr-summary.json`, `checkruns-<N>.json`, `threads-<N>.json` | Read-only GitHub CLI. |
| Review record table and totals | `per-pr-facts.json`, `review-record-table.md`, `aggregates.json` | `build_pr_facts.py` over the files above. |
| Deploy results per merge commit | `merge-commit-deploy-statuses.json` | Read-only GitHub CLI. |
| Workflow runs on the assessed commit | `main-workflow-runs.json` | Read-only GitHub CLI. |
| Scorecard output | `scorecard-stdout.md` | `python3 scripts/run_erp_integrity_scorecard.py`, output to stdout only. |
| Score with review statuses | `score-with-review-statuses.json` | `score_with_review_statuses.py`, calling the scorecard's own formula. |
| Golden sets | `goldens.log` | `python3 scripts/run_agent_eval.py golden` — 9 fixtures, 0 failing. |
| Generated business plan up to date | `business-plan-check.log` | `python3 scripts/build_business_plan.py --check`. |
| Whole suite on `main` | `full-inmemory.log`, `.junit.xml`, `.summary.json` | `pytest tests/` in memory mode. |
| Whole suite before #781 | `baseline-inmemory.log`, `.junit.xml`, `.summary.json` | Same, on an export of commit `26e1fb8b` outside the repository. |
| Difference between the two | `baseline-vs-main.json` | `compare_runs.py`. |
| Cause of the 80 | `order-dependence-bisect.log` | Each affected file alone, then after `test_fiduciary_store.py`. |
| Where two tests turned red | `books-tied-test-bisect.log`, `jobs-adapters-test-bisect.log` | The single test at each merge commit, on exports outside the repository. |
| Suites named by the PRs, one process each | `named/summary.json`, `named/<file>.log` | 43 files: 966 passed, 3 failed (one of the three is an artefact of the scratch temp directory and passes with the default). |
| Database mode, seven money suites | `dbmode-seven-suites.log`, `.summary.json` | Scratch SQLite, `PHINS_FIDUCIARY_MODE=dual` — 222 passed. |
| Database mode, programme suites | `dbmode-unit-suites.log`, `dbmode-unit-failures-isolated.log`, `inmemory-unit-suites.log` | Same scratch database; then each failure alone. |
| Restart behaviour of remittance, trust, cession, tax, period close; unit of work; Durability Guard; over-cap path | `probe-runtime.json`, `probe_runtime.py` | A script outside the repository, in memory mode. |
| Schema at #804, #805, #806 | `probe-schema-805-806.jsonl`, `probe_schema.py` | Scratch SQLite. |
| Plan-named tables and repositories | `plan-tables-repositories.json` | Table names in the plan compared with `__tablename__` in `database/`. |
