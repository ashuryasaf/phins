"""Signed-document seal and the sent/signed/opened/used ledger.

The chain is append-only. A tampered row is reported and blocks the next
event. A second copy of the same signature does not replace the sealed text.
"""

import hashlib
import json

import pytest

from services.document_use_ledger import (
    DocumentUseLedger,
    LedgerError,
    reset_document_use_ledger_for_tests,
)
from services.signed_document_archive import ArchiveError, SignedDocumentArchive


@pytest.fixture
def ledger(tmp_path):
    reset_document_use_ledger_for_tests()
    book = DocumentUseLedger(str(tmp_path / "use.json"))
    yield book
    reset_document_use_ledger_for_tests()


def test_ledger_chains_sent_signed_opened_and_used(ledger):
    sent = ledger.record(
        action="sent", idempotency_key="sent:shr_1", document_path="/business-plan.html",
        document_name="PHINS Unified Business Plan", share_id="shr_1", actor="admin",
    )
    signed = ledger.record(
        action="signed", idempotency_key="signed:LGLSIG-1", document_name="ACME",
        actor="Dana Levi", content_sha256="ab" * 32, entry_id="LGLSIG-1",
    )
    opened = ledger.record(
        action="opened", idempotency_key="opened:shr_1:/business-plan.html:202610181200",
        document_path="/business-plan.html", share_id="shr_1", actor="share viewer",
    )
    used = ledger.record(
        action="used", idempotency_key="used:shr_1:session", share_id="shr_1",
        actor="Dana Levi",
    )
    assert sent["prev_hash"] != signed["prev_hash"]
    assert signed["prev_hash"] == sent["entry_hash"]
    assert opened["prev_hash"] == signed["entry_hash"]
    assert used["prev_hash"] == opened["entry_hash"]
    report = ledger.list_events()
    assert report["intact"] is True
    assert report["total"] == 4
    assert [item["action"] for item in report["items"]] == ["used", "opened", "signed", "sent"]
    again = ledger.record(action="signed", idempotency_key="signed:LGLSIG-1", actor="Other")
    assert again["entry_hash"] == signed["entry_hash"]
    assert ledger.list_events()["total"] == 4


def test_ledger_refuses_a_broken_chain(ledger):
    ledger.record(action="sent", idempotency_key="sent:shr_1", share_id="shr_1", actor="admin")
    raw = json.loads(ledger.path.read_text(encoding="utf-8"))
    raw["entries"][0]["actor"] = "forged"
    ledger.path.write_text(json.dumps(raw), encoding="utf-8")
    report = ledger.list_events()
    assert report["intact"] is False
    with pytest.raises(LedgerError):
        ledger.record(action="opened", idempotency_key="opened:1", actor="share viewer")


def test_signed_archive_promotes_an_attestation_and_refuses_a_different_text(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("PHINS_DOCUMENT_USE_LEDGER_PATH", str(tmp_path / "use.json"))
    reset_document_use_ledger_for_tests()
    text = "Non-Disclosure Agreement\nReceiving Party ACME\n"
    digest = hashlib.sha256(text.encode()).hexdigest()
    archive = SignedDocumentArchive(str(tmp_path / "signed"))
    archive_id = archive.store_signature({
        "doc_type": "nda",
        "doc_instance_id": "LGL-NDA-X",
        "entry_id": "LGLSIG-1",
        "document_hash": digest,
        "signer_name": "Dana Levi",
        "content": {"source": "legal-docs"},
    })
    assert archive.get(archive_id)["document_text"] == ""
    promoted = archive.store({
        "nda_text": text,
        "nda_sha256": digest,
        "doc_instance_id": "LGL-NDA-X",
        "entry_id": "LGLSIG-1",
        "signer_name": "Dana Levi",
    })
    assert promoted == archive_id
    assert archive.get(archive_id)["nda_text"] == text
    with pytest.raises(ArchiveError):
        archive.store({
            "nda_text": text + "extra",
            "nda_sha256": hashlib.sha256((text + "extra").encode()).hexdigest(),
            "doc_instance_id": "LGL-NDA-X",
            "entry_id": "LGLSIG-1",
        })
    assert archive.get(archive_id)["nda_text"] == text
    from services.document_use_ledger import get_document_use_ledger
    report = get_document_use_ledger().list_events()
    assert report["intact"] is True
    assert report["total"] == 1
    assert report["items"][0]["action"] == "signed"
    html = __import__("services.signed_document_archive", fromlist=["render_signed_html"]).render_signed_html(
        archive.get(archive_id)
    )
    assert "PHINS_CAPTURE_GUARD" in html
    assert "Dana Levi" in html
    reset_document_use_ledger_for_tests()


def test_durable_seal_refuses_a_different_checksum_until_promoted():
    """Same rule as the media library: identical bytes are a no-op, a clash is refused."""
    import hashlib

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import SignedDocumentBlob
    from services.signed_document_store import (
        SignedDocumentIntegrityError,
        load_in_session,
        replace_verified_in_session,
        seal_in_session,
    )

    engine = create_engine("sqlite:///:memory:")
    SignedDocumentBlob.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    first = b'{"nda_text":"one"}\n'
    digest = seal_in_session(session, "nda-1", first, "signed_document")
    assert digest == hashlib.sha256(first).hexdigest()
    assert seal_in_session(session, "nda-1", first, "signed_document") == digest
    with pytest.raises(SignedDocumentIntegrityError):
        seal_in_session(session, "nda-1", b'{"nda_text":"two"}\n', "signed_document")
    assert load_in_session(session, "nda-1") == first
    promoted = b'{"nda_text":"full"}\n'
    replace_verified_in_session(session, "nda-1", promoted, digest, "signed_document")
    assert load_in_session(session, "nda-1") == promoted
    session.close()


def test_capture_guard_marks_a_shared_page_once():
    from services.document_capture_guard import inject

    page = "<html><body><p>terms</p></body></html>"
    once = inject(page, "ACME")
    twice = inject(once, "ACME")
    assert once.count("phins-capture-guard.js") == 1
    assert twice == once
    assert "terms" in twice
