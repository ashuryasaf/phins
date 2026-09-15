"""
B1 + B4 — shared evidence pipeline, model shadowing, real STT, fact-store
indexes and the OCR page cache.

Covers:
* fact-store indexes (by document / by field) stay consistent with the list
  through append, trim and reload, and contradiction detection is unchanged;
* page-level OCR cache: a re-run of the same PDF never rasterises again,
  failed pages are not cached, fan-out is bounded;
* ``services.evidence_facts``: bundles carry facts + contradictions +
  provenance, fingerprints are order-independent, the feature cache is
  bounded and copy-isolated;
* ``services.model_shadow``: the model never changes a decision, divergence
  is logged, drift alerts once per breach episode;
* Underwriting Bot: STT through the platform provider, feature cache hits on
  identical bytes, facts consumed with provenance, decisions logged and human
  counter-decisions recorded, singleton rebinding, package facade parity;
* Claims Bot: pipeline documents feed the document score, contradictions
  lower it and are flagged, reports carry provenance refs without snippets
  and a decision-log id;
* the A6 harness evaluates the Underwriting Bot from its decision log.
"""

import base64
import copy
import os
import struct
import sys
import types
import zlib
from datetime import datetime, date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import assessment_center_service as acs
from services import document_processing_service as dps
from services import evidence_facts
from services import model_shadow
from services.ai_decision_log import get_ai_decision_log
from services.assessment_center_service import AssessmentCenterService, Fact, _make_fact
from services.document_processing_service import DocumentProcessingService
from services.underwriting_bot_service import (
    AudioAnalyzer, MetadataType, ProcessingStatus, UnderwritingBotService, ValidationStatus,
    get_underwriting_bot_service, init_underwriting_bot_service,
)
from services.claims_bot_service import ClaimsBotService


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def doc_service(tmp_path):
    return DocumentProcessingService(storage_root=str(tmp_path / "docs"))


@pytest.fixture
def center(tmp_path, doc_service):
    return AssessmentCenterService(document_service=doc_service,
                                   fact_store_dir=str(tmp_path / "facts"))


@pytest.fixture
def wired(monkeypatch, doc_service, center):
    """Make the module singletons resolve to the isolated instances."""
    monkeypatch.setattr(acs, "_default_service", center)
    monkeypatch.setattr(dps, "_default_service", doc_service)
    evidence_facts.reset_feature_cache()
    model_shadow.reset_drift_monitor()
    yield doc_service, center
    evidence_facts.reset_feature_cache()
    model_shadow.reset_drift_monitor()


@pytest.fixture
def clean_decision_log():
    log = get_ai_decision_log()
    log.clear()
    yield log
    log.clear()


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _upload(doc_service, center, text, *, customer_id, entity_type=None, entity_id=None, name="doc.txt"):
    up = doc_service.upload_document(
        file_name=name, file_data_b64=_b64(text), mime_type="text/plain",
        customer_id=customer_id, entity_type=entity_type, entity_id=entity_id,
        skip_processing=False,
    )
    center.assess_document(up.document_id, customer_id=customer_id)
    return up


def _fact(customer, ftype, label, value, doc, sha="sha-" + "0" * 4, conf=0.9, **prov):
    f = _make_fact(customer, ftype, label, value, doc, sha, "test", conf)
    for k, v in prov.items():
        setattr(f, k, v)
    return f


# ── B4: fact-store indexes ───────────────────────────────────────────────────

def _brute_by_document(center, doc_ids):
    with center._lock:
        return [f for facts in center._facts.values() for f in facts if f.source_document_id in set(doc_ids)]


class TestFactIndexes:
    def test_facts_for_documents_is_exact_and_ignores_other_customers(self, center):
        center._store_facts("C1", [_fact("C1", "identity", "id_number", "123456782", "D1"),
                                   _fact("C1", "vital_sign", "bmi", 24.0, "D2")])
        center._store_facts("C2", [_fact("C2", "identity", "id_number", "999", "D3")])
        got = center.facts_for_documents(["D1", "D3", "D-missing"])
        assert {f.source_document_id for f in got} == {"D1", "D3"}
        assert [f.fact_id for f in got] == [f.fact_id for f in _brute_by_document(center, ["D1", "D3"])]
        assert center.facts_for_documents([]) == []
        summary = center.get_document_assessments(["D1", "D2"])
        assert summary["D1"]["facts_extracted"] == 1 and summary["D2"]["by_type"] == {"vital_sign": 1}

    def test_indexes_survive_trim_and_disk_reload(self, tmp_path, doc_service, monkeypatch):
        monkeypatch.setattr(acs, "MAX_FACTS_PER_CUSTOMER", 5)
        store_dir = str(tmp_path / "facts2")
        center = AssessmentCenterService(document_service=doc_service, fact_store_dir=store_dir)
        facts = [_fact("C1", "insurance", f"amount_{i}", float(i), f"D{i}", sha=f"s{i}") for i in range(8)]
        center._store_facts("C1", facts)
        kept = center.get_facts("C1")
        assert len(kept) == 5
        # oldest three were trimmed: their documents are gone from the index
        assert center.facts_for_documents(["D0", "D1", "D2"]) == []
        assert {f.source_document_id for f in center.facts_for_documents([f"D{i}" for i in range(8)])} == {
            "D3", "D4", "D5", "D6", "D7"}
        assert set(center._by_field["C1"]) == {("insurance", f"amount_{i}") for i in range(3, 8)}
        # a fresh instance rebuilds the same indexes from disk
        reloaded = AssessmentCenterService(document_service=doc_service, fact_store_dir=store_dir)
        assert {f.source_document_id for f in reloaded.facts_for_documents(["D5", "D7"])} == {"D5", "D7"}
        assert set(reloaded._by_field["C1"]) == set(center._by_field["C1"])
        reloaded.reset()
        assert reloaded._by_document == {} and reloaded._by_field == {}

    def test_conflict_detection_uses_index_and_matches_full_scan(self, center):
        center._store_facts("C1", [
            _fact("C1", "identity", "id_number", "123456782", "D1", sha="a"),
            _fact("C1", "identity", "id_number", "987654321", "D2", sha="b"),
            _fact("C1", "identity", "date_of_birth", "1980-05-01", "D1", sha="a"),
            _fact("C1", "identity", "date_of_birth", "01/05/1980", "D2", sha="b"),   # same date, no conflict
            _fact("C1", "medical", "condition", "asthma", "D1", sha="a"),             # not conflict-sensitive
            _fact("C1", "insurance", "annual_income", 80000, "D1", sha="a"),
            _fact("C1", "insurance", "annual_income", 120000, "D2", sha="b"),
        ])
        conflicts = center.detect_fact_conflicts("C1")
        fields = {c["field"] for c in conflicts}
        assert fields == {"identity:id_number", "insurance:annual_income"} or \
            {c["label"] for c in conflicts} == {"id_number", "annual_income"}
        stored = center.detect_and_store_conflicts("C1")
        assert len(stored) == 2
        # contradiction facts are indexed too, and never resolved (both values kept)
        assert all(f.fact_type == "contradiction" for f in stored)
        assert len(center._by_field["C1"][("contradiction", stored[0].label)]) >= 1
        assert len(center.get_facts("C1", fact_type="identity")) == 4


# ── B4: OCR page cache ───────────────────────────────────────────────────────

class _FakePage:
    mode = "RGB"

    def __init__(self, n):
        self.n = n


class _FakeTesseract:
    class TesseractNotFoundError(Exception):
        pass

    def __init__(self):
        self.calls = []
        self.fail_on = set()

    def image_to_string(self, img, lang=None):
        self.calls.append((getattr(img, "n", "img"), lang))
        if getattr(img, "n", None) in self.fail_on:
            raise RuntimeError("boom")
        return f"page-{getattr(img, 'n', 'img')} text"


@pytest.fixture
def fake_ocr(monkeypatch):
    tess = _FakeTesseract()
    rasterised = []

    def convert_from_bytes(raw, dpi=None, first_page=1, last_page=None):
        rasterised.append(len(raw))
        return [_FakePage(i) for i in range(1, 4)]

    monkeypatch.setitem(sys.modules, "pytesseract", tess)
    monkeypatch.setitem(sys.modules, "pdf2image", types.SimpleNamespace(convert_from_bytes=convert_from_bytes))
    DocumentProcessingService.reset_ocr_cache()
    yield tess, rasterised
    DocumentProcessingService.reset_ocr_cache()


class TestOcrPageCache:
    def test_second_run_of_same_pdf_never_rasterises(self, tmp_path, fake_ocr):
        tess, rasterised = fake_ocr
        svc = DocumentProcessingService(storage_root=str(tmp_path))
        raw = b"%PDF-1.4 fake"
        first = svc._ocr_pdf_page_chunks(raw)
        assert first == ["page-1 text", "page-2 text", "page-3 text"]
        assert len(rasterised) == 1 and len(tess.calls) == 3
        second = svc._ocr_pdf_page_chunks(raw)
        assert second == first
        assert len(rasterised) == 1, "cached PDF must not be rasterised again"
        assert len(tess.calls) == 3, "cached pages must not be OCR'd again"
        stats = DocumentProcessingService.ocr_cache_stats()
        assert stats["hits"] >= 3 and stats["entries"] == 4  # 3 pages + page count
        # a different file is a different key
        svc._ocr_pdf_page_chunks(b"%PDF-1.4 other")
        assert len(rasterised) == 2

    def test_failed_page_is_not_cached_and_retried(self, tmp_path, fake_ocr):
        tess, rasterised = fake_ocr
        svc = DocumentProcessingService(storage_root=str(tmp_path))
        tess.fail_on = {2}
        raw = b"%PDF-1.4 flaky"
        assert svc._ocr_pdf_page_chunks(raw) == ["page-1 text", "", "page-3 text"]
        tess.fail_on = set()
        again = svc._ocr_pdf_page_chunks(raw)
        assert again == ["page-1 text", "page-2 text", "page-3 text"]
        assert len(rasterised) == 2  # had to rasterise once more for the missing page
        assert [c[0] for c in tess.calls].count(2) == 2 and [c[0] for c in tess.calls].count(1) == 1

    def test_sequential_pool_and_page_cap(self, tmp_path, fake_ocr, monkeypatch):
        tess, rasterised = fake_ocr
        monkeypatch.setattr(DocumentProcessingService, "_OCR_POOL_SIZE", 1)
        monkeypatch.setattr(DocumentProcessingService, "_OCR_MAX_PDF_PAGES", 2)
        svc = DocumentProcessingService(storage_root=str(tmp_path))
        assert svc._ocr_pdf_page_chunks(b"%PDF cap") == ["page-1 text", "page-2 text"]
        assert len(tess.calls) == 2

    def test_health_probe_reports_cache(self, fake_ocr):
        payload = dps._document_intelligence_health()
        assert set(payload["ocr_cache"]) == {"entries", "hits", "misses"}


# ── evidence_facts ───────────────────────────────────────────────────────────

class TestEvidenceFacts:
    def test_bundle_collects_facts_contradictions_and_provenance(self, wired):
        doc_service, center = wired
        a = _upload(doc_service, center, "Teudat Zehut: 123456782 owner file", customer_id="C1",
                    entity_type="claim", entity_id="CLM-1", name="a.txt")
        b = _upload(doc_service, center, "Teudat Zehut: 987654324 second file", customer_id="C1",
                    entity_type="claim", entity_id="CLM-1", name="b.txt")
        bundle = evidence_facts.bundle_for_entity("claim", "CLM-1", customer_id="C1")
        assert set(bundle.document_ids) == {a.document_id, b.document_id}
        assert bundle.fingerprint == evidence_facts.fingerprint([b.sha256, a.sha256])
        assert bundle.fact_count >= 2 and "identity" in bundle.by_type()
        ids = {f["label"] for f in bundle.facts}
        assert "id_number" in ids
        assert bundle.contradictions, "two different id numbers must be a recorded contradiction"
        assert all(c["fact_type"] == "contradiction" for c in bundle.contradictions)
        prov = bundle.provenance()[0]
        assert set(prov) == set(evidence_facts.PROVENANCE_FIELDS)
        assert bundle.to_dict()["contradictions"] == len(bundle.contradictions)
        # unknown documents contribute nothing; failures degrade to empty
        assert evidence_facts.facts_for(["nope"]) == []
        assert evidence_facts.bundle_for([]).fact_count == 0

    def test_documents_for_entity_excludes_deleted(self, wired):
        doc_service, center = wired
        a = _upload(doc_service, center, "alpha", customer_id="C9", entity_type="claim", entity_id="CLM-9")
        b = _upload(doc_service, center, "beta", customer_id="C9", entity_type="claim", entity_id="CLM-9", name="b.txt")
        doc_service.delete_document(b.document_id)
        ids = [d["id"] for d in evidence_facts.documents_for_entity("claim", "CLM-9")]
        assert ids == [a.document_id]
        assert evidence_facts.documents_for_entity("", "") == []

    def test_feature_cache_is_bounded_and_copy_isolated(self):
        cache = evidence_facts.FeatureCache(max_entries=2)
        calls = []
        value, hit = cache.get_or_compute("ns", "sha1", lambda: calls.append(1) or {"x": [1]})
        assert hit is False and value == {"x": [1]}
        value["x"].append(2)  # mutate the returned copy
        again, hit = cache.get_or_compute("ns", "sha1", lambda: calls.append(1))
        assert hit is True and again == {"x": [1]} and len(calls) == 1
        cache.put("ns", "sha2", 2)
        cache.put("ns", "sha3", 3)  # evicts the LRU entry (sha1 was touched most recently before sha2/sha3)
        assert cache.stats()["entries"] == 2
        assert cache.get("ns", "sha1") == (None, False)
        # empty sha never caches
        v, hit = cache.get_or_compute("ns", "", lambda: 42)
        assert (v, hit) == (42, False) and cache.stats()["entries"] == 2
        assert evidence_facts.fingerprint([]) == ""


# ── model_shadow ─────────────────────────────────────────────────────────────

class _Handle:
    def __init__(self, score, name="uw_scorer", version="7"):
        self._score = score
        self.registry_id = f"{name}:{version}"

    def score(self, features):
        return self._score(features) if callable(self._score) else self._score


class _Registry:
    def __init__(self, handles):
        self.handles = handles

    def get_model(self, name):
        return self.handles.get(name)


class TestModelShadow:
    def test_no_artifact_means_rules_only(self):
        res = model_shadow.shadow_score("uw_scorer", {"a": 1.0}, 0.42, registry=_Registry({}))
        assert res.model_score is None and res.divergence is None
        assert res.model_version == "rules-v1" and res.consulted is False
        assert res.as_log_fields() == {"rule_score": 0.42, "model_score": None, "model_version": "rules-v1",
                                       "divergence": None, "drift_alert": False}

    def test_divergence_logged_and_model_errors_degrade(self):
        mon = model_shadow.DriftMonitor(threshold=0.25, window=10, min_samples=3)
        reg = _Registry({"uw_scorer": _Handle(0.9)})
        res = model_shadow.shadow_score("uw_scorer", {"a": 1}, 0.3, registry=reg, monitor=mon)
        assert res.model_score == 0.9 and res.divergence == pytest.approx(0.6)
        assert res.model_version == "uw_scorer:7" and res.rule_score == 0.3
        broken = _Registry({"uw_scorer": _Handle(lambda f: 1 / 0)})
        res = model_shadow.shadow_score("uw_scorer", {"a": 1}, 0.3, registry=broken, monitor=mon)
        assert res.model_score is None and res.model_version == "rules-v1"

    def test_drift_alert_once_per_breach_episode(self, monkeypatch):
        emitted = []
        monkeypatch.setattr(model_shadow, "_emit_drift_alert", lambda *a, **k: emitted.append(a[1]))
        mon = model_shadow.DriftMonitor(threshold=0.2, window=6, min_samples=3)
        bad = _Registry({"m": _Handle(1.0)})
        good = _Registry({"m": _Handle(0.5)})
        alerts = [model_shadow.shadow_score("m", {}, 0.5, registry=bad, monitor=mon).drift_alert for _ in range(4)]
        assert alerts == [False, False, True, False], "alert fires once when p95 crosses, after min_samples"
        assert emitted == ["m"]
        for _ in range(6):
            model_shadow.shadow_score("m", {}, 0.5, registry=good, monitor=mon)
        assert mon.status()["models"]["m"]["breached"] is False
        # re-armed: the next breach episode alerts exactly once again
        # (p95 of a 6-sample window is its maximum, so one bad sample breaches)
        assert model_shadow.shadow_score("m", {}, 0.5, registry=bad, monitor=mon).drift_alert is True
        assert model_shadow.shadow_score("m", {}, 0.5, registry=bad, monitor=mon).drift_alert is False
        assert emitted.count("m") == 2

    def test_drift_alert_writes_audit_row(self, monkeypatch):
        rows = []
        import services.ai_audit_bridge as bridge
        monkeypatch.setattr(bridge, "record_ai_audit", lambda *a, **k: rows.append((a, k)) or True)
        mon = model_shadow.DriftMonitor(threshold=0.1, window=5, min_samples=1)
        model_shadow.shadow_score("m", {}, 0.0, registry=_Registry({"m": _Handle(1.0)}), monitor=mon,
                                  agent_id="claims_bot")
        assert rows and rows[0][0][0] == "ai_model_drift" and rows[0][1]["username"] == "claims_bot"
        assert rows[0][0][3]["p95_divergence"] == 1.0


# ── Underwriting Bot ─────────────────────────────────────────────────────────

class _Provider:
    def __init__(self, text="I feel well, no medication", fail=False):
        self.text, self.fail, self.calls = text, fail, []

    def transcribe(self, raw, *, file_name="a", mime_type="m", language_hint=None, context=None):
        self.calls.append((file_name, mime_type, context))
        if self.fail:
            raise RuntimeError("provider down")
        return {"text": self.text, "language": "en", "segments": [{"start": 0, "end": 1, "text": self.text}],
                "provider": "fake", "model": "whisper-fake", "duration_seconds": 1.5}

    def describe(self):
        return {"provider": "fake", "model": "whisper-fake"}


def _audio_meta():
    from services.underwriting_bot_service import UnderwritingMetadata
    return UnderwritingMetadata(id="META-A", underwriting_id="UW-1", customer_id="CUST-1",
                                metadata_type=MetadataType.AUDIO, file_name="s.mp3", file_path="/uploads/s.mp3",
                                file_hash="h", file_size_bytes=3, mime_type="audio/mpeg", upload_date=datetime.now())


class TestUnderwritingBotStt:
    def test_platform_provider_transcribes_audio(self):
        provider = _Provider()
        res = AudioAnalyzer(transcription_provider=provider).analyze(_audio_meta(), file_content=b"ID3abc")
        assert res["processing_success"] is True
        assert res["transcription"] == "I feel well, no medication"
        assert "NO_STT_AVAILABLE" not in res["flags"] and "NO_SENTIMENT_MODEL" in res["flags"]
        assert res["stt"]["provider"] == "fake" and res["stt"]["segments"] == 1
        assert provider.calls[0][2]["customer_id"] == "CUST-1"

    def test_disabled_provider_keeps_no_stt_flag_and_failure_is_distinct(self, monkeypatch):
        monkeypatch.setenv("PHINS_TRANSCRIPTION_PROVIDER", "disabled")
        res = AudioAnalyzer().analyze(_audio_meta(), file_content=b"ID3abc")
        assert "NO_STT_AVAILABLE" in res["flags"] and res["processing_success"] is True
        failing = AudioAnalyzer(transcription_provider=_Provider(fail=True)).analyze(_audio_meta(), file_content=b"ID3")
        assert "STT_FAILED" in failing["flags"] and "NO_STT_AVAILABLE" not in failing["flags"]
        # caller-supplied transcription always wins and the provider is not called
        p = _Provider()
        res = AudioAnalyzer(transcription_provider=p).analyze(_audio_meta(), file_content=b"x", transcription="given")
        assert res["transcription"] == "given" and p.calls == []


def _bot(customers=None, **kw):
    return UnderwritingBotService(customers=customers if customers is not None else {"CUST-1": {"name": "A", "age": 40}},
                                  policies=kw.get("policies", {}), underwriting_apps=kw.get("apps", {}),
                                  claims=kw.get("claims", {}))


PASSPORT = (b"PASSPORT\nPassport No: 123456789\nSurname: SMITH\nGiven Names: JOHN\n"
            b"Date of Birth: 15 MAR 1985\nDate of Expiry: 01 JAN 2030\nNationality: BRITISH\n")


def _portrait_png(width: int = 480, height: int = 640, min_size: int = 8 * 1024) -> bytes:
    """PNG signature + valid IHDR, padded past the PhotoAnalyzer 5KB quality floor."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    crc = zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF
    head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", crc)
    return head + b"\x00" * max(0, min_size - len(head))


PORTRAIT_PNG = _portrait_png()


class TestUnderwritingBotEvidence:
    def test_feature_cache_hits_on_identical_bytes_only(self, wired):
        bot = _bot()
        a = bot.start_assessment(underwriting_id="UW-1", customer_id="CUST-1", policy_id="POL-1")
        calls = []
        real = bot.document_analyzer.analyze
        bot.document_analyzer.analyze = lambda *args, **kw: calls.append(1) or real(*args, **kw)
        m1 = bot.add_metadata(a.id, MetadataType.PASSPORT, "p.txt", "", file_content=PASSPORT, mime_type="text/plain")
        m2 = bot.add_metadata(a.id, MetadataType.PASSPORT, "p2.txt", "", file_content=PASSPORT, mime_type="text/plain")
        m3 = bot.add_metadata(a.id, MetadataType.PASSPORT, "p3.txt", "", file_content=PASSPORT + b"x", mime_type="text/plain")
        r1 = bot.process_metadata(m1.id, file_content=PASSPORT)["result"]
        r2 = bot.process_metadata(m2.id, file_content=PASSPORT)["result"]
        r3 = bot.process_metadata(m3.id, file_content=PASSPORT + b"x")["result"]
        assert (r1["feature_cache"], r2["feature_cache"], r3["feature_cache"]) == ("miss", "hit", "miss")
        assert len(calls) == 2
        assert r2["extracted_fields"] == r1["extracted_fields"]
        # the cached copy is isolated from the stored metadata object
        bot.metadata_store[m1.id].processing_result["extracted_fields"]["poison"] = True
        assert "poison" not in evidence_facts.get_feature_cache().get(
            f"uw:passport:{date.today().isoformat()}", m1.file_hash)[0]["extracted_fields"]

    def test_consumes_pipeline_facts_with_provenance_without_bytes(self, wired):
        doc_service, center = wired
        up = _upload(doc_service, center, "Teudat Zehut: 123456782. Email: alice@example.com",
                     customer_id="CUST-1", entity_type="underwriting", entity_id="UW-2")
        bot = _bot()
        a = bot.start_assessment(underwriting_id="UW-2", customer_id="CUST-1", policy_id="POL-1")
        m = bot.add_metadata(a.id, MetadataType.PASSPORT, "id.txt", "", document_id=up.document_id)
        assert bot.metadata_store[m.id].document_id == up.document_id
        out = bot.process_metadata(m.id)  # no bytes at all
        res = out["result"]
        assert out["success"] and res["processing_success"] is True
        assert "EVIDENCE_FROM_DOCUMENT_PIPELINE" in res["flags"]
        assert res["extracted_fields"]["id_number"] == "123456782"
        assert res["evidence"]["document_ids"] == [up.document_id]
        prov = next(f for f in res["evidence_facts"] if f["label"] == "id_number")["provenance"]
        assert prov["source_document_id"] == up.document_id and prov["source_document_sha256"] == up.sha256
        assert prov["char_start"] is not None and "123456782" in (prov["source_text"] or "")
        meta = bot.metadata_store[m.id]
        assert meta.processing_status == ProcessingStatus.COMPLETED
        assert meta.validation_status == ValidationStatus.VALID
        assert meta.extracted_data["id_number"] == "123456782" and meta.confidence_score > 0

    def test_recorded_contradiction_sends_item_to_suspicious(self, wired):
        doc_service, center = wired
        a_doc = _upload(doc_service, center, "Teudat Zehut: 123456782", customer_id="CUST-1",
                        entity_type="underwriting", entity_id="UW-3")
        _upload(doc_service, center, "Teudat Zehut: 987654324", customer_id="CUST-1",
                entity_type="underwriting", entity_id="UW-3", name="other.txt")
        assert center.get_facts("CUST-1", fact_type="contradiction")
        bot = _bot()
        a = bot.start_assessment(underwriting_id="UW-3", customer_id="CUST-1", policy_id="POL-1")
        m = bot.add_metadata(a.id, MetadataType.PASSPORT, "id.txt", "", document_id=a_doc.document_id)
        res = bot.process_metadata(m.id)["result"]
        assert "SUSPICIOUS_EVIDENCE_CONTRADICTION" in res["flags"]
        assert res["evidence_contradictions"][0]["label"] == "id_number"
        assert len(res["evidence_contradictions"][0]["values"]) == 2, "both values kept, none resolved"
        assert bot.metadata_store[m.id].validation_status == ValidationStatus.SUSPICIOUS

    def test_analyzer_result_wins_over_facts(self, wired):
        doc_service, center = wired
        up = _upload(doc_service, center, "Teudat Zehut: 123456782", customer_id="CUST-1")
        bot = _bot()
        a = bot.start_assessment(underwriting_id="UW-4", customer_id="CUST-1", policy_id="POL-1")
        m = bot.add_metadata(a.id, MetadataType.PASSPORT, "p.txt", "", file_content=PASSPORT, document_id=up.document_id)
        res = bot.process_metadata(m.id, file_content=PASSPORT)["result"]
        from_bytes = bot.document_analyzer.analyze(m, PASSPORT, "passport")["extracted_fields"]
        assert from_bytes and all(res["extracted_fields"][k] == v for k, v in from_bytes.items())  # bytes win
        assert res["extracted_fields"]["id_number"] == "123456782"                                # gap from facts
        assert "id_number" not in from_bytes

    def test_photo_features_survive_the_fact_merge(self, wired):
        doc_service, center = wired
        up = _upload(doc_service, center, "Teudat Zehut: 123456782", customer_id="CUST-1")
        bot = _bot()
        a = bot.start_assessment(underwriting_id="UW-5", customer_id="CUST-1", policy_id="POL-1")
        m = bot.add_metadata(a.id, MetadataType.PHOTO, "face.png", "", file_content=PORTRAIT_PNG,
                             document_id=up.document_id, mime_type="image/png")
        res = bot.process_metadata(m.id, file_content=PORTRAIT_PNG)["result"]
        names = {f["name"] for f in res["features"]}                       # analyzer output kept as-is
        assert {"detected_format", "image_quality", "portrait_shape_hint"} <= names
        assert res["extracted_fields"]["id_number"] == "123456782"         # facts land beside it
        assert bot.metadata_store[m.id].extracted_data["id_number"] == "123456782"


class TestUnderwritingBotDecisionLoop:
    def _full_run(self, bot, uw_id="UW-10"):
        a = bot.start_assessment(underwriting_id=uw_id, customer_id="CUST-1", policy_id="POL-1")
        m = bot.add_metadata(a.id, MetadataType.PASSPORT, "p.txt", "", file_content=PASSPORT)
        bot.process_metadata(m.id, file_content=PASSPORT)
        return a, bot.run_risk_assessment(a.id)

    def test_recommendation_logged_with_rule_and_model_scores(self, wired, clean_decision_log):
        bot = _bot()
        a, report = self._full_run(bot)
        assert report.decision_id.startswith("AIDEC-")
        rec = clean_decision_log.get(report.decision_id)
        assert rec["decision_type"] == "underwriting_bot_assessment"
        assert rec["entity_id"] == "UW-10" and rec["output"]["decision"] == report.recommendation.value
        assert rec["output"]["rule_score"] == round(report.overall_risk_score, 4)
        assert rec["output"]["model_score"] is None and rec["model_version"] == "rules-v1"
        assert rec["segment"] == "35_44|unknown"  # age band from the customer snapshot
        assert report.to_dict()["decision_id"] == report.decision_id
        assert report.model_shadow["divergence"] is None

    def test_shadow_model_never_changes_the_decision(self, wired, clean_decision_log, monkeypatch):
        import services.ai_model_registry as reg
        baseline = self._full_run(_bot(), "UW-11")[1]
        monkeypatch.setattr(reg, "get_model_registry", lambda: _Registry({"uw_scorer": _Handle(0.99)}))
        model_shadow.reset_drift_monitor()
        shadowed = self._full_run(_bot(), "UW-12")[1]
        assert shadowed.recommendation == baseline.recommendation
        assert shadowed.overall_risk_score == pytest.approx(baseline.overall_risk_score)
        assert shadowed.model_shadow["model_score"] == 0.99
        assert shadowed.model_shadow["model_version"] == "uw_scorer:7"
        assert shadowed.model_shadow["divergence"] == pytest.approx(abs(0.99 - baseline.overall_risk_score), abs=1e-3)
        rec = clean_decision_log.get(shadowed.decision_id)
        assert rec["output"]["model_score"] == 0.99 and rec["model_version"] == "uw_scorer:7"

    def test_human_counter_decision_is_recorded_bot_decision_is_not(self, wired, clean_decision_log):
        bot = _bot(apps={"UW-13": {"status": "pending"}})
        a, report = self._full_run(bot, "UW-13")
        # a bot-applied decision matching its own recommendation is not an override
        bot.apply_decision(a.id, report.recommendation.value.replace("_manual", ""), decided_by="bot")
        assert clean_decision_log.get(report.decision_id)["human_override"] is None
        # a human deciding differently is a labelled counter-decision
        human = "decline" if report.recommendation.value != "decline" else "approve"
        bot2 = _bot(apps={"UW-14": {"status": "pending"}})
        a2, report2 = self._full_run(bot2, "UW-14")
        out = bot2.apply_decision(a2.id, human, decided_by="underwriter@phins", notes="documents insufficient")
        assert out["success"]
        rec = clean_decision_log.get(report2.decision_id)
        assert rec["human_override"] == ("reject" if human == "decline" else "approve")
        assert rec["overridden_by"] == "underwriter@phins" and rec["override_reason"] == "documents insufficient"

    def test_customer_and_claims_stores_are_never_modified(self, wired):
        customers = {"CUST-1": {"name": "A", "age": 40, "email": "a@x"}}
        claims = {"CLM-1": {"customer_id": "CUST-1", "status": "paid"}}
        before = (copy.deepcopy(customers), copy.deepcopy(claims))
        bot = _bot(customers=customers, claims=claims, apps={"UW-15": {"status": "pending"}})
        a, _ = self._full_run(bot, "UW-15")
        bot.apply_decision(a.id, "approve", decided_by="underwriter", override_recommendation=True)
        assert (customers, claims) == before

    def test_harness_evaluates_the_underwriting_bot(self, wired, clean_decision_log):
        from services import agent_eval
        assert "underwriting_bot" in agent_eval.EVALUATORS
        reports = [self._full_run(_bot(), f"UW-2{i}")[1] for i in range(3)]
        # one explicit human label makes the segment evaluable at min_samples=1
        clean_decision_log.record_override(reports[0].decision_id, "approve", reason="ok", overridden_by="uw")
        payload = agent_eval.evaluate("underwriting_bot", min_samples=1)
        assert payload["agent_id"] == "underwriting_bot"
        assert payload["decisions_seen"] == 3 and payload["score_direction"] == "1 - risk_score"
        assert payload["live_rules"]["refer_max_risk"] == 0.75
        assert payload["thresholds"] == {"approve": pytest.approx(0.45), "reject": pytest.approx(0.25)}
        proposals = payload["proposal"]["proposals"]
        assert proposals, "one proposal per observed segment"
        for entry in proposals.values():
            assert "risk_rules" in entry
            assert entry["risk_rules"]["refer_max_risk"] == pytest.approx(1 - entry["reject"])

    def test_replay_scorer_matches_the_engine_risk_bands(self):
        from services.agent_eval import APPROVE, REJECT, REVIEW, underwriting_bot_scorer
        from services.underwriting_bot.report import RiskAssessmentEngine
        rules = RiskAssessmentEngine.DECISION_RULES
        live = {"approve": round(1 - rules["conditional_approve_max_risk"], 6),
                "reject": round(1 - rules["refer_max_risk"], 6)}

        def verdict(risk):
            return underwriting_bot_scorer(round(1 - risk, 6), live)

        # the engine's bands are closed on the upper side: 0.55 approves, 0.75 still refers
        assert verdict(rules["conditional_approve_max_risk"]) == APPROVE
        assert verdict(rules["refer_max_risk"]) == REVIEW
        assert verdict(rules["refer_max_risk"] + 0.01) == REJECT


class TestUnderwritingBotAccessorAndFacade:
    def test_accessor_rebinds_on_different_stores_only(self):
        a, b = {"CUST-A": {}}, {"CUST-B": {}}
        first = init_underwriting_bot_service(a, {}, {}, {})
        assert get_underwriting_bot_service() is first
        assert get_underwriting_bot_service(customers=a) is first
        second = get_underwriting_bot_service(customers=b)
        assert second is not first and second._customers is b
        assert get_underwriting_bot_service() is second
        audit = object()
        assert get_underwriting_bot_service(customers=b, audit_service=audit) is second
        assert second._audit is audit

    def test_facade_and_package_export_the_same_objects(self):
        import services.underwriting_bot as pkg
        import services.underwriting_bot_service as facade
        from services.underwriting_bot import features, report, service
        for name in facade.__all__:
            assert getattr(facade, name) is getattr(pkg, name), name
        assert facade.UnderwritingBotService is service.UnderwritingBotService
        assert facade.RiskAssessmentEngine is report.RiskAssessmentEngine
        assert facade.AudioAnalyzer is features.AudioAnalyzer
        from services.agent_runtime import get_descriptor
        assert get_descriptor("underwriting_bot").module == "services.underwriting_bot_service"

    def test_job_adapter_uses_the_shared_instance(self, wired, clean_decision_log):
        from services.jobs import underwriting_bot_job
        from services.jobs import JobContext
        customers = {}
        ctx = JobContext(customers=customers, policies={}, underwriting_apps={}, claims={}, audit=None)
        out = underwriting_bot_job.run_ai_assessment(ctx, filename="report.pdf", file_content=b"%PDF-1.4 x" * 20,
                                                    mime_type="application/pdf", actor="underwriter")
        assert out["decision_id"] and "model_shadow" in out
        assert get_underwriting_bot_service()._customers is customers


# ── Claims Bot ───────────────────────────────────────────────────────────────

def _claims_fixture():
    customers = {"CUST-1": {"name": "A", "age": 45, "email": "a@x.io"}}
    policies = {"POL-1": {"customer_id": "CUST-1", "start_date": "2020-01-01", "coverage_amount": 100000,
                          "type": "life", "status": "active"}}
    claims = {"CLM-1": {"id": "CLM-1", "customer_id": "CUST-1", "policy_id": "POL-1", "amount": 5000,
                        "type": "medical", "filed_date": "2024-06-01",
                        "description": "Routine hospital visit with supporting discharge letters attached."}}
    return customers, policies, claims


class TestClaimsBotEvidence:
    def test_pipeline_documents_count_as_evidence_with_provenance_refs(self, wired, clean_decision_log):
        doc_service, center = wired
        customers, policies, claims = _claims_fixture()
        bare = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        up = _upload(doc_service, center, "Discharge letter. Teudat Zehut: 123456782. BMI 24",
                     customer_id="CUST-1", entity_type="claim", entity_id="CLM-1")
        report = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        assert report.document_authenticity_score == pytest.approx(bare.document_authenticity_score + 0.05)
        assert report.evidence["document_ids"] == [up.document_id] and report.evidence["fact_count"] >= 1
        assert report.evidence_processed == 1
        refs = report.evidence_provenance
        assert refs and refs[0]["document_id"] == up.document_id and refs[0]["document_sha256"] == up.sha256
        assert all("source_text" not in r for r in refs), "reports never carry raw snippets"
        assert any("consumed with provenance" in k for k in report.key_findings)
        d = report.to_dict()
        assert d["evidence"]["provenance"] == refs and d["metadata"]["decision_id"] == report.decision_id
        rec = clean_decision_log.get(report.decision_id)
        assert rec["decision_type"] == "claims_bot_assessment" and rec["entity_id"] == "CLM-1"
        assert rec["output"]["rule_score"] == round(report.authenticity_probability, 4)
        assert rec["output"]["model_score"] is None and rec["output"]["decision"] == report.recommendation.value

    def test_contradiction_lowers_score_and_is_flagged_not_resolved(self, wired, clean_decision_log):
        doc_service, center = wired
        customers, policies, claims = _claims_fixture()
        _upload(doc_service, center, "Teudat Zehut: 123456782", customer_id="CUST-1",
                entity_type="claim", entity_id="CLM-1", name="a.txt")
        clean = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        _upload(doc_service, center, "Teudat Zehut: 987654324", customer_id="CUST-1",
                entity_type="claim", entity_id="CLM-1", name="b.txt")
        conflicted = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        assert conflicted.document_authenticity_score == pytest.approx(clean.document_authenticity_score - 0.25)
        assert conflicted.evidence["contradictions"] == 1
        assert any("Cross-document contradiction on id_number" in f for f in conflicted.red_flags)
        assert len(center.get_facts("CUST-1", fact_type="identity")) == 2, "both values remain on file"

    def test_shadow_model_never_changes_claims_decision(self, wired, clean_decision_log, monkeypatch):
        import services.ai_model_registry as reg
        customers, policies, claims = _claims_fixture()
        base = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        monkeypatch.setattr(reg, "get_model_registry", lambda: _Registry({"claims_scorer": _Handle(0.01, "claims_scorer")}))
        shadowed = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        assert shadowed.recommendation == base.recommendation
        assert shadowed.authenticity_probability == pytest.approx(base.authenticity_probability)
        assert shadowed.model_shadow["model_score"] == 0.01 and shadowed.model_shadow["model_version"] == "claims_scorer:7"
        assert clean_decision_log.get(shadowed.decision_id)["model_version"] == "claims_scorer:7"

    def test_report_without_document_service_still_generates(self, monkeypatch, clean_decision_log):
        import services.evidence_facts as ef
        monkeypatch.setattr(ef, "_document_service", lambda service=None: (_ for _ in ()).throw(RuntimeError("down")))
        customers, policies, claims = _claims_fixture()
        report = ClaimsBotService(customers, policies, claims, {}).generate_probability_report("CLM-1")
        assert report is not None and report.evidence["document_count"] == 0
