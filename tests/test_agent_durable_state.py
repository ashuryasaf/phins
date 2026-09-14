"""A4: Claims Bot and Underwriting Bot artifacts are durable in DB mode.

Runs the bots against the shared SQLite test database with DB mode forced on
(``services.hydrated_store.db_mode_enabled``), then simulates a restart or a
peer instance by constructing a fresh service / wiping the cache.
"""

from __future__ import annotations

import os

import pytest

import services.hydrated_store as hs
from services import ai_audit_bridge as bridge
from services.claims_bot_service import ClaimsBotService
from services.underwriting_bot_service import (
    AssessmentStatus, MetadataType, ProcessingStatus, UnderwritingBotService,
)

PASSPORT_TEXT = (
    b"PASSPORT\nType: P\nCountry Code: GBR\nPassport No: 123456789\n"
    b"Surname: SMITH\nGiven Names: JOHN\nNationality: BRITISH\n"
    b"Date of Birth: 15 MAR 1985\nSex: M\nPlace of Birth: LONDON\n"
    b"Date of Issue: 01 JAN 2020\nDate of Expiry: 01 JAN 2030\n"
    b"Authority: HMPO\nMRZ: P<GBRSMITH<<JOHN<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n"
    b"1234567897GBR8503159M3001012<<<<<<<<<<<<<<04\n"
) * 40


def _purge(agent_id: str) -> None:
    from database.manager import DatabaseManager
    from database.models import AgentArtifact
    with DatabaseManager() as db:
        session = db.agent_artifacts.session
        session.query(AgentArtifact).filter(AgentArtifact.agent_id == agent_id).delete(
            synchronize_session=False)
        session.commit()


@pytest.fixture
def db_mode(monkeypatch):
    from database import init_database
    init_database()
    monkeypatch.setattr(hs, 'db_mode_enabled', lambda: True)
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda *a, **k: False)
    hs.reset_shared_stores()
    for agent in ('claims_bot', 'underwriting_bot'):
        _purge(agent)
    yield
    hs.reset_shared_stores()
    for agent in ('claims_bot', 'underwriting_bot'):
        _purge(agent)


def _claim_fixture():
    customers = {'CUST1': {'id': 'CUST1', 'name': 'Test'}}
    policies = {'POL1': {'id': 'POL1', 'start_date': '2020-01-01', 'coverage_amount': 100000}}
    claims = {'CLM1': {'id': 'CLM1', 'customer_id': 'CUST1', 'policy_id': 'POL1',
                       'claimed_amount': 1000, 'filed_date': '2024-01-01', 'type': 'medical'}}
    return customers, policies, claims


# --------------------------------------------------------------------------
# Claims Bot
# --------------------------------------------------------------------------
def test_claims_report_survives_restart_and_is_shared_across_instances(db_mode):
    customers, policies, claims = _claim_fixture()
    bot = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    assert bot.reports.durable is True
    report = bot.generate_probability_report('CLM1')
    expected = report.to_dict()

    # Restart: a brand-new process has an empty cache and re-hydrates.
    bot.reports.reset()
    again = bot.get_report(report.id)
    assert again is not None and again is not report          # a decoded copy ...
    assert again.to_dict() == expected                        # ... that is identical
    assert again.recommendation is report.recommendation      # enums, not strings
    assert bot.list_reports('CLM1')[0]['id'] == report.id

    # A second instance in the same process shares the store; a cold peer
    # (its own store over the same table) sees the row too.
    peer_same_process = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    assert peer_same_process.reports is bot.reports
    cold_peer = hs.ArtifactStore('claims_bot.reports', agent_id='claims_bot',
                                 kind='probability_report',
                                 record_type=type(report), ttl=1000.0)
    assert cold_peer[report.id].to_dict() == expected


def test_claims_retention_cap_is_a_db_side_prune(db_mode):
    customers, policies, claims = _claim_fixture()
    bot = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    bot.MAX_RETAINED_REPORTS = 2
    ids = [bot.generate_probability_report('CLM1').id for _ in range(4)]
    from database.manager import DatabaseManager
    with DatabaseManager() as db:
        assert db.agent_artifacts.count_for('claims_bot', 'probability_report') == 2
        kept = {aid for aid, *_ in db.agent_artifacts.iter_payloads('claims_bot', 'probability_report')}
    assert kept == set(ids[-2:])                              # oldest two pruned
    assert set(bot.reports.keys()) == kept                    # cache mirrors the prune
    listed = bot.list_reports('CLM1')
    assert [r['id'] for r in listed] == list(reversed(ids[-2:]))


def test_claims_health_probe_reports_durability_without_querying(db_mode, monkeypatch):
    import services.claims_bot_service as mod
    customers, policies, claims = _claim_fixture()
    bot = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    bot.generate_probability_report('CLM1')
    monkeypatch.setattr(mod, '_bot_instance', bot)
    loads_before = bot.reports.stats['hydrations']
    health = mod._claims_bot_health()
    assert health['durable'] is True and health['reports_retained'] == 1
    assert health['store']['name'] == 'claims_bot.reports'
    assert bot.reports.stats['hydrations'] == loads_before


# --------------------------------------------------------------------------
# Underwriting Bot
# --------------------------------------------------------------------------
def _uw_stores():
    customers = {'CUST-001': {'id': 'CUST-001', 'name': 'John Smith', 'date_of_birth': '1985-03-15',
                              'email': 'john@example.com'}}
    policies = {'POL-001': {'id': 'POL-001', 'customer_id': 'CUST-001', 'status': 'active'}}
    underwriting = {'UW-001': {'id': 'UW-001', 'customer_id': 'CUST-001', 'status': 'pending'}}
    return customers, policies, underwriting, {}


def test_underwriting_assessment_can_be_continued_by_a_fresh_instance(db_mode):
    customers, policies, underwriting, claims = _uw_stores()
    first = UnderwritingBotService(customers=customers, policies=policies,
                                   underwriting_apps=underwriting, claims=claims)
    assert first.assessments.durable is True
    assessment = first.start_assessment('UW-001', 'CUST-001', 'POL-001')
    meta = first.add_metadata(assessment.id, MetadataType.PASSPORT, 'passport.txt',
                              '/uploads/passport.txt', file_content=PASSPORT_TEXT,
                              mime_type='text/plain')
    result = first.process_metadata(meta.id, file_content=PASSPORT_TEXT)
    assert result['success'] is True
    extracted_before = dict(first.metadata_store[meta.id].extracted_data)
    assert extracted_before.get('full_name')

    # "Restart": drop every cache; the next instance hydrates from the table.
    hs.reset_shared_stores()
    for store in (first.assessments, first.metadata_store, first.reports):
        store.reset()
    second = UnderwritingBotService(customers=customers, policies=policies,
                                    underwriting_apps=underwriting, claims=claims)
    restored = second.assessments.get(assessment.id)
    assert restored is not None and restored is not assessment
    assert restored.status == AssessmentStatus.COLLECTING_METADATA
    assert len(restored.metadata_items) == 1
    item = restored.metadata_items[0]
    assert item.processing_status == ProcessingStatus.COMPLETED     # processed state persisted
    assert item.extracted_data == extracted_before                  # lossless round-trip
    assert second.metadata_store[meta.id].processing_status == ProcessingStatus.COMPLETED

    # The second instance finishes the assessment ...
    report = second.run_risk_assessment(assessment.id)
    assert second.assessments[assessment.id].status == AssessmentStatus.DECISION_READY
    decision = second.apply_decision(assessment.id, 'approve', decided_by='underwriter')
    assert decision['success'] is True and decision['report_id'] == report.id

    # ... and the first instance observes the outcome after its TTL lapses.
    first.assessments.coalescer.reset()
    first.reports.coalescer.reset()
    seen = first.assessments[assessment.id]
    assert seen.status == AssessmentStatus.APPROVED and seen.completed_at is not None
    assert seen.risk_report is not None and seen.risk_report.id == report.id
    assert first.get_report(report.id).to_dict() == report.to_dict()
    assert underwriting['UW-001']['bot_report_id'] == report.id


def test_underwriting_process_all_keeps_items_and_status_consistent(db_mode):
    customers, policies, underwriting, claims = _uw_stores()
    bot = UnderwritingBotService(customers=customers, policies=policies,
                                 underwriting_apps=underwriting, claims=claims)
    assessment = bot.start_assessment('UW-001', 'CUST-001', 'POL-001')
    bot.add_metadata(assessment.id, MetadataType.PASSPORT, 'p.txt', '/p.txt',
                     file_content=PASSPORT_TEXT, mime_type='text/plain')
    bot.add_metadata(assessment.id, MetadataType.PHOTO, 'selfie.jpg', '/s.jpg',
                     file_content=b'x', mime_type='image/jpeg')
    outcome = bot.process_all_metadata(assessment.id)
    # process_all has no bytes to hand over, so items fail — but the persisted
    # assessment must carry both the item states and the final status.
    assert outcome['total_processed'] == 2
    bot.assessments.reset()
    restored = bot.assessments[assessment.id]
    assert restored.status.value == outcome['status']
    assert {m.processing_status for m in restored.metadata_items} == {ProcessingStatus.FAILED}


def test_underwriting_retention_prunes_in_db(db_mode):
    customers, policies, underwriting, claims = _uw_stores()
    bot = UnderwritingBotService(customers=customers, policies=policies,
                                 underwriting_apps=underwriting, claims=claims)
    bot.MAX_RETAINED_ASSESSMENTS = 2
    ids = [bot.start_assessment('UW-001', 'CUST-001', 'POL-001').id for _ in range(4)]
    from database.manager import DatabaseManager
    with DatabaseManager() as db:
        assert db.agent_artifacts.count_for('underwriting_bot', 'assessment') == 2
    assert set(bot.assessments.keys()) == set(ids[-2:])


# --------------------------------------------------------------------------
# Video Agents _JobStore
# --------------------------------------------------------------------------
def _purge_video_jobs():
    from database.manager import DatabaseManager
    from database.models import VideoJob
    with DatabaseManager() as db:
        session = db.video_jobs.session
        session.query(VideoJob).delete(synchronize_session=False)
        session.commit()


@pytest.fixture
def video_db_mode(db_mode):
    _purge_video_jobs()
    yield
    _purge_video_jobs()


def _video_job(job_id, **extra):
    from datetime import datetime, timezone
    job = {"id": job_id, "campaign_id": "CMP-A4", "submitted_by": "media_ad",
           "provider": "mock", "provider_job_id": f"p-{job_id}", "pipeline_type": "explainer",
           "status": "processing", "progress_pct": 5,
           "created_at": datetime.now(timezone.utc).isoformat(), "provider_state": {}}
    job.update(extra)
    return job


def test_video_job_store_is_durable_and_shared(video_db_mode):
    import services.video_agents_service as mod
    store = mod._JobStore()
    assert store.durable is True
    store.add(_video_job("VJ-A4-1"))
    store.add(_video_job("VJ-A4-2", campaign_id="CMP-OTHER", submitted_by="someone"))
    assert store.update("VJ-A4-1", {"progress_pct": 40})["progress_pct"] == 40
    assert store.update("VJ-nope", {"x": 1}) is None

    # A fresh store (restart / peer instance) sees the same jobs and counts.
    peer = mod._JobStore()
    assert peer.get("VJ-A4-1")["progress_pct"] == 40
    assert {j["id"] for j in peer.list_all()} == {"VJ-A4-1", "VJ-A4-2"}
    assert [j["id"] for j in peer.list_by_campaign("CMP-A4")] == ["VJ-A4-1"]
    assert peer.count_campaign_jobs("CMP-A4") == 1
    assert peer.count_user_jobs_today("media_ad") == 1
    assert peer.count_all_jobs_today() == 2
    assert peer.snapshot()["durable"] is True


def test_video_mark_terminal_wins_exactly_once_across_stores(video_db_mode):
    """Webhook and poller on different instances: one terminal transition."""
    import threading
    import services.video_agents_service as mod
    webhook_side, poller_side = mod._JobStore(), mod._JobStore()
    webhook_side.add(_video_job("VJ-RACE"))
    assert poller_side.get("VJ-RACE")["status"] == "processing"

    barrier = threading.Barrier(2)
    results = {}

    def run(name, store, status):
        barrier.wait()
        results[name] = store.mark_terminal("VJ-RACE", {"status": status, "by": name})

    threads = [threading.Thread(target=run, args=("webhook", webhook_side, "completed")),
               threading.Thread(target=run, args=("poller", poller_side, "failed"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    winners = [k for k, v in results.items() if v is not None]
    assert len(winners) == 1, results
    winner = winners[0]
    for store in (webhook_side, poller_side):
        store._store.coalescer.reset()
        final = store.get("VJ-RACE")
        assert final["by"] == winner and final["status"] == results[winner]["status"]
        assert store.mark_terminal("VJ-RACE", {"status": "cancelled"}) is None   # already terminal
    assert webhook_side.mark_terminal("VJ-missing", {"status": "failed"}) is None


def test_video_webhook_handler_uses_durable_store(video_db_mode, monkeypatch):
    import services.video_agents_service as mod
    monkeypatch.setattr(mod, "_job_store", mod._JobStore())
    monkeypatch.setattr(mod, "_video_agents_service", None)
    mod._job_store.add(_video_job("VJ-WH", provider="kling", provider_job_id="k-1"))
    events = []
    monkeypatch.setattr(mod, "_audit_video_event", lambda *a, **k: events.append(a[0]))
    service = mod.VideoAgentsService()
    first = service.handle_webhook("VJ-WH", {"data": {"task_status": "succeed",
                                                      "url": "https://cdn/x.mp4"}})
    second = service.handle_webhook("VJ-WH", {"data": {"task_status": "succeed"}})
    assert first is not None and first["status"] == "completed"
    assert first["download_url"] == "https://cdn/x.mp4"
    assert second["status"] == "completed" and second["download_url"] == "https://cdn/x.mp4"
    assert service.handle_webhook("VJ-missing", {"status": "failed"}) is None
    assert events.count("video_job_completed") == 1                # audited exactly once
    # A different process reading the table sees the terminal state.
    assert mod._JobStore().get("VJ-WH")["status"] == "completed"


# --------------------------------------------------------------------------
# AI Risk Reports
# --------------------------------------------------------------------------
CSV = (b"policy_number,coverage_amount,premium,claim_count,risk_score\n"
       b"POL-001,100000,500,0,0.2\nPOL-002,200000,750,1,0.5\nPOL-003,150000,600,0,0.3\n"
       b"POL-004,90000,400,2,0.8\n")


@pytest.fixture
def risk_db_mode(db_mode, tmp_path, monkeypatch):
    import services.ai_risk_reports_service as mod
    _purge('ai_risk_reports')
    monkeypatch.setattr(mod, 'AI_REPORTS_DATA_FILE', str(tmp_path / 'never_written.json'))
    yield mod
    _purge('ai_risk_reports')


def test_risk_reports_pipeline_is_durable_and_peer_can_continue(risk_db_mode):
    mod = risk_db_mode
    first = mod.AIRiskReportsService()
    assert first._durable() is True
    parsed = first.parse_file('policies.csv', CSV, 'csv', owner_id='CUST-1', owner_role='customer')
    doc_id = parsed['document_id']
    analysis = first.analyze(doc_id)
    report = first.generate_report(analysis.id)
    assert not os.path.exists(mod.AI_REPORTS_DATA_FILE)              # no JSON file in DB mode
    assert first.save_data() is True

    # Restart / peer: nothing cached, everything hydrates from the table —
    # including the parsed rows, so the peer can analyse and report itself.
    hs.reset_shared_stores()
    for store in (first.documents, first.analyses, first.reports):
        store.reset()
    second = mod.AIRiskReportsService()
    assert second.load_data() is True                                 # table wins over the file
    doc = second.documents[doc_id]
    assert doc['row_count'] == 4 and len(doc['parsed_data']['rows']) == 4
    restored_analysis = second.analyses[analysis.id]
    assert second.to_dict(restored_analysis) == second.to_dict(analysis)
    assert second.to_dict(second.reports[report.id]) == second.to_dict(report)
    assert isinstance(restored_analysis.anomalies, list)
    assert restored_analysis.data_classification is analysis.data_classification

    again = second.analyze(doc_id)                                    # peer re-analyses the same upload
    assert again.document_id == doc_id and again.id != analysis.id
    second_report = second.generate_report(again.id)
    first.reports.coalescer.reset()
    assert second_report.id in first.reports                          # visible to the first instance
    listed = second.get_reports_for_user('CUST-1', 'customer')
    assert {r['report_id'] for r in listed} == {report.id, second_report.id}

    from database.manager import DatabaseManager
    with DatabaseManager() as db:
        assert db.agent_artifacts.count_for('ai_risk_reports', 'document') == 1
        assert db.agent_artifacts.count_for('ai_risk_reports', 'analysis') == 2
        assert db.agent_artifacts.count_for('ai_risk_reports', 'report') == 2


def test_risk_reports_legacy_json_is_migrated_once_into_the_table(risk_db_mode, tmp_path):
    mod = risk_db_mode
    # A pre-A4 deployment saved its state to the JSON file in memory mode.
    legacy = mod.AIRiskReportsService()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hs, 'db_mode_enabled', lambda: False)
        memory_only = mod.AIRiskReportsService()
        parsed = memory_only.parse_file('legacy.csv', CSV, 'csv', owner_id='CUST-9', owner_role='customer')
        analysis = memory_only.analyze(parsed['document_id'])
        assert memory_only.save_data() is True and os.path.exists(mod.AI_REPORTS_DATA_FILE)
    # First DB-mode boot with an empty table reads the file (write-through
    # migrates it); the second boot ignores the file because rows exist.
    assert legacy.load_data() is True
    assert analysis.id in legacy.analyses
    from database.manager import DatabaseManager
    with DatabaseManager() as db:
        assert db.agent_artifacts.count_for('ai_risk_reports', 'analysis') == 1
    os.remove(mod.AI_REPORTS_DATA_FILE)
    hs.reset_shared_stores()
    rebooted = mod.AIRiskReportsService()
    assert rebooted.load_data() is True and analysis.id in rebooted.analyses


# --------------------------------------------------------------------------
# Standalone worker: every adapter bound over the database-backed stores
# --------------------------------------------------------------------------
def test_standalone_worker_context_runs_claims_bot_job_with_web_parity(db_mode):
    from services import jobs as agent_jobs
    from services.agent_job_queue import AgentJobQueue
    from database.manager import DatabaseManager

    db = DatabaseManager()
    context = agent_jobs.worker_context(audit=None)
    assert context.sanitize_claim_report is agent_jobs.claims_bot_job.sanitize_claim_probability_report

    marker = f"A4-{os.getpid()}"
    context.customers[f"CUST-{marker}"] = {"id": f"CUST-{marker}", "name": "Durable Customer",
                                           "email": f"{marker}@example.com"}
    context.policies[f"POL-{marker}"] = {"id": f"POL-{marker}", "customer_id": f"CUST-{marker}",
                                         "start_date": "2020-01-01", "coverage_amount": 100000,
                                         "status": "active", "type": "health", "annual_premium": 1200.0}
    context.claims[f"CLM-{marker}"] = {"id": f"CLM-{marker}", "customer_id": f"CUST-{marker}",
                                       "policy_id": f"POL-{marker}", "claimed_amount": 1000,
                                       "filed_date": "2024-01-01", "type": "medical",
                                       "status": "pending"}
    try:
        worker = AgentJobQueue(db_manager=db, poll_interval=0.01)
        agent_jobs.register_all(worker, context)
        assert agent_jobs.claims_bot_job.JOB_TYPE in worker.handlers()
        assert agent_jobs.underwriting_bot_job.JOB_TYPE in worker.handlers()
        assert agent_jobs.video_job.JOB_TYPE in worker.handlers()

        job = agent_jobs.claims_bot_job.enqueue_probability_report(
            worker, claim_id=f"CLM-{marker}", claim=context.claims[f"CLM-{marker}"],
            submitted_by="adjuster")
        assert worker.process_once()["completed"] == 1
        row = worker.get_job(job["id"])
        assert row["status"] == "completed", row
        result = row["result"]["report"] if "report" in row["result"] else row["result"]
        assert result["claim_id"] == f"CLM-{marker}"
        for indicator in result["fraud_indicators"]["indicators"]:
            assert "evidence" not in indicator                     # redacted like the web route

        # The report the worker produced is in the durable store, so the web
        # process (a peer instance of the bot) can serve it by id.
        from database.manager import DatabaseManager as _DM
        with _DM() as peer_db:
            stored = list(peer_db.agent_artifacts.iter_payloads('claims_bot', 'probability_report'))
        assert [p[1]["claim_id"] for p in stored] == [f"CLM-{marker}"]
    finally:
        for store, key in ((context.claims, f"CLM-{marker}"), (context.policies, f"POL-{marker}"),
                           (context.customers, f"CUST-{marker}")):
            store.pop(key, None)
        from database.models import DocumentProcessingJob
        session = db.processing_jobs.session
        session.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.subject_id == f"CLM-{marker}").delete(synchronize_session=False)
        session.commit()


def test_memory_mode_is_untouched(monkeypatch):
    monkeypatch.setattr(hs, 'db_mode_enabled', lambda: False)
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda *a, **k: False)
    customers, policies, claims = _claim_fixture()
    a = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    b = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    assert a.reports is not b.reports and a.reports.durable is False
    report = a.generate_probability_report('CLM1')
    assert a.reports[report.id] is report                    # identity preserved
    assert b.get_report(report.id) is None                   # per-instance isolation
    uw = UnderwritingBotService(customers={}, policies={}, underwriting_apps={}, claims={})
    assessment = uw.start_assessment('UW-1', 'C-1', 'P-1')
    meta = uw.add_metadata(assessment.id, MetadataType.PASSPORT, 'p.txt', '/p',
                           file_content=PASSPORT_TEXT, mime_type='text/plain')
    uw.process_metadata(meta.id, file_content=PASSPORT_TEXT)
    assert assessment.metadata_items[0] is meta              # same object, as before A4
    assert meta.processing_status == ProcessingStatus.COMPLETED
