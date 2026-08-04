"""
Tests for the encrypted, integrity-checked assessment fact store.

The fact store holds PII (identity numbers, medical conditions, IBANs), so
files are now written as vault envelopes: Fernet-encrypted when
``PHINS_ENCRYPTION_KEY`` is configured, plain-scheme otherwise. Legacy
plaintext files must keep loading (no data loss on upgrade) and payloads carry
a ``facts_sha256`` tamper-evidence checksum.
"""

from __future__ import annotations

import json
import os

import pytest

from services.assessment_center_service import (
    AssessmentCenterService,
    FACT_STORE_FORMAT_V2,
)


def _ingest_sample_fact(svc: AssessmentCenterService, customer_id: str = "CUST-ENC-1"):
    svc.ingest_external_facts(
        customer_id=customer_id,
        source="unit_test",
        records=[{"policy_number": "POL-777", "provider": "TestCo",
                  "id_number": "123456782"}],
        fact_type="external_policy",
    )


def _fact_file(tmp_path, customer_id: str = "CUST-ENC-1"):
    return os.path.join(str(tmp_path), f"{customer_id}.json")


class TestEnvelopeFormat:
    def test_plain_envelope_without_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
        svc = AssessmentCenterService(fact_store_dir=str(tmp_path))
        _ingest_sample_fact(svc)

        with open(_fact_file(tmp_path), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        assert raw["format"] == FACT_STORE_FORMAT_V2
        assert raw["scheme"] == "plain"
        inner = json.loads(raw["ciphertext"])
        assert inner["customer_id"] == "CUST-ENC-1"
        assert inner["facts_sha256"]

    def test_fernet_encryption_with_key(self, tmp_path, monkeypatch):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setenv("PHINS_ENCRYPTION_KEY", key)

        svc = AssessmentCenterService(fact_store_dir=str(tmp_path))
        _ingest_sample_fact(svc)

        with open(_fact_file(tmp_path), "r", encoding="utf-8") as fh:
            content = fh.read()
        raw = json.loads(content)
        assert raw["format"] == FACT_STORE_FORMAT_V2
        assert raw["scheme"] == "fernet"
        # PII must not appear anywhere in the on-disk bytes.
        assert "123456782" not in content
        assert "POL-777" not in content

        # Round-trip: a fresh service instance decrypts and rehydrates.
        svc2 = AssessmentCenterService(fact_store_dir=str(tmp_path))
        facts = svc2.get_facts("CUST-ENC-1")
        assert any("POL-777" in json.dumps(f) for f in facts)

    def test_missing_key_leaves_file_intact_and_skips_load(self, tmp_path, monkeypatch):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setenv("PHINS_ENCRYPTION_KEY", key)
        svc = AssessmentCenterService(fact_store_dir=str(tmp_path))
        _ingest_sample_fact(svc)

        # Simulate a lost/rotated key on restart: load must not crash and the
        # file must remain on disk for recovery.
        monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
        svc2 = AssessmentCenterService(fact_store_dir=str(tmp_path))
        assert svc2.get_facts("CUST-ENC-1") == []
        assert os.path.isfile(_fact_file(tmp_path))


class TestLegacyCompatibility:
    def test_legacy_plaintext_file_still_loads(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
        legacy_payload = {
            "customer_id": "CUST-LEGACY-1",
            "saved_at": "2025-01-01T00:00:00Z",
            "facts": [{
                "fact_id": "FACT-LEGACY-1",
                "customer_id": "CUST-LEGACY-1",
                "fact_type": "insurance",
                "value": {"policy_number": "POL-OLD"},
                "label": "policy",
                "confidence": 1.0,
                "source": "legacy",
                "metadata": {},
                "captured_at": "2025-01-01T00:00:00Z",
            }],
        }
        with open(_fact_file(tmp_path, "CUST-LEGACY-1"), "w", encoding="utf-8") as fh:
            json.dump(legacy_payload, fh)

        svc = AssessmentCenterService(fact_store_dir=str(tmp_path))
        facts = svc.get_facts("CUST-LEGACY-1")
        assert len(facts) == 1

    def test_legacy_file_upgraded_to_v2_on_next_save(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
        legacy_payload = {
            "customer_id": "CUST-LEGACY-2",
            "saved_at": "2025-01-01T00:00:00Z",
            "facts": [{
                "fact_id": "FACT-LEGACY-2",
                "customer_id": "CUST-LEGACY-2",
                "fact_type": "insurance",
                "value": {"policy_number": "POL-OLD-2"},
                "label": "policy",
                "confidence": 1.0,
                "source": "legacy",
                "metadata": {},
                "captured_at": "2025-01-01T00:00:00Z",
            }],
        }
        with open(_fact_file(tmp_path, "CUST-LEGACY-2"), "w", encoding="utf-8") as fh:
            json.dump(legacy_payload, fh)

        svc = AssessmentCenterService(fact_store_dir=str(tmp_path))
        _ingest_sample_fact(svc, customer_id="CUST-LEGACY-2")

        with open(_fact_file(tmp_path, "CUST-LEGACY-2"), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        assert raw.get("format") == FACT_STORE_FORMAT_V2
        # Both the legacy fact and the new one survive the upgrade.
        facts = AssessmentCenterService(
            fact_store_dir=str(tmp_path)
        ).get_facts("CUST-LEGACY-2")
        dumped = json.dumps(facts)
        assert "POL-OLD-2" in dumped
        assert "POL-777" in dumped


class TestChecksum:
    def test_checksum_is_deterministic(self):
        facts = [{"a": 1, "b": [1, 2]}]
        c1 = AssessmentCenterService._facts_checksum(facts)
        c2 = AssessmentCenterService._facts_checksum(list(facts))
        assert c1 == c2
        assert len(c1) == 64

    def test_tampered_payload_detected_but_still_loads(self, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
        svc = AssessmentCenterService(fact_store_dir=str(tmp_path))
        _ingest_sample_fact(svc, customer_id="CUST-TAMPER")

        path = _fact_file(tmp_path, "CUST-TAMPER")
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        inner = json.loads(raw["ciphertext"])
        inner["facts"][0]["label"] = "tampered-label"
        raw["ciphertext"] = json.dumps(inner, separators=(",", ":"), sort_keys=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)

        import logging
        with caplog.at_level(logging.ERROR):
            svc2 = AssessmentCenterService(fact_store_dir=str(tmp_path))
        # Data still loads (never drop customer data silently)…
        assert svc2.get_facts("CUST-TAMPER")
        # …but the mismatch is loudly reported.
        assert any("checksum mismatch" in r.message.lower() for r in caplog.records)
