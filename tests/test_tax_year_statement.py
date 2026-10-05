"""Customer tax-year premium statement: unified totals, policy sheets, branded PDF."""

from __future__ import annotations

import base64
import hashlib
import io
from datetime import datetime

import web_portal.server as portal
from services.notification_service import (
    MockEmailProvider,
    NotificationChannel,
    NotificationRequest,
    create_notification_service,
)
from services.tax_year_statement_pdf import (
    STATEMENT_STANDARD,
    render_tax_year_statement_pdf,
    statement_filename,
)


def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


def _pdf_page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def _seed_customer(customer_id: str = 'CUST-TAX-STMT') -> str:
    portal.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'Asaf Assurance',
        'email': 'asaf.assurance@example.com',
        'phone': '+15550001111',
        'address': '1 Health Plaza',
        'city': 'Tel Aviv',
        'created_date': datetime.now().isoformat(),
    }
    portal.CUSTOMER_ALLOCATIONS[customer_id] = {
        **portal.DEFAULT_CUSTOMER_ALLOCATION,
        'savings_pct': 40.0,
        'risk_pct': 60.0,
        'customer_id': customer_id,
    }
    return customer_id


def _seed_policy(customer_id: str, policy_id: str, monthly: float, coverage: float, ptype: str = 'life') -> None:
    portal.POLICIES[policy_id] = {
        'id': policy_id,
        'customer_id': customer_id,
        'status': 'active',
        'type': ptype,
        'monthly_premium': monthly,
        'annual_premium': round(monthly * 12, 2),
        'coverage_amount': coverage,
        'risk_allocation': 60.0,
        'savings_allocation': 40.0,
        'billing': {'frequency': 'monthly'},
        'created_date': f'{datetime.now().year}-01-15T00:00:00',
    }


def _seed_paid_bill(customer_id: str, policy_id: str, bill_id: str, amount: float) -> None:
    stamp = datetime.now().isoformat()
    portal.BILLING[bill_id] = {
        'id': bill_id,
        'bill_id': bill_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'amount': amount,
        'amount_due': amount,
        'amount_paid': amount,
        'status': 'paid',
        'created_date': stamp,
        'paid_date': stamp,
    }


def test_tax_year_report_unifies_all_policies_and_reconciles():
    customer_id = _seed_customer()
    _seed_policy(customer_id, 'POL-LIFE-1', 100.0, 250000.0, 'life')
    _seed_policy(customer_id, 'POL-ADL-2', 50.0, 80000.0, 'adl')
    _seed_paid_bill(customer_id, 'POL-LIFE-1', 'BILL-LIFE-1', 100.0)
    _seed_paid_bill(customer_id, 'POL-ADL-2', 'BILL-ADL-2', 50.0)

    report = portal._build_tax_year_premium_report(customer_id, 0.0)

    assert report['tax_year'] == datetime.now().year
    assert report['statement_standard'] == STATEMENT_STANDARD
    summary = report['tax_year_summary']
    assert summary['paid_premium_total'] == 150.0
    assert summary['premium_paid_tax_year'] == 150.0
    assert summary['risk_paid_total'] == 90.0
    assert summary['savings_paid_total'] == 60.0
    assert summary['risk_paid_tax_year'] == 90.0
    assert summary['savings_paid_tax_year'] == 60.0
    assert summary['policy_count'] == 2
    assert summary['paid_bill_count'] == 2

    sheets = {item['policy_id']: item for item in report['policies']}
    assert set(sheets) == {'POL-LIFE-1', 'POL-ADL-2'}
    assert sheets['POL-LIFE-1']['paid_premium_total'] == 100.0
    assert sheets['POL-LIFE-1']['risk_paid_total'] == 60.0
    assert sheets['POL-LIFE-1']['savings_paid_total'] == 40.0
    assert sheets['POL-ADL-2']['paid_premium_total'] == 50.0
    assert sheets['POL-ADL-2']['risk_paid_total'] == 30.0
    assert sheets['POL-ADL-2']['savings_paid_total'] == 20.0

    assert report['integrity']['policies_sum_matches_unified'] is True
    assert report['integrity']['premium_equals_risk_plus_savings'] is True
    assert report['integrity']['residual_unallocated'] == 0.0
    digest = report['integrity']['statement_sha256']
    assert len(digest) == 64
    assert digest == portal._tax_year_statement_sha256(report)
    replay = portal._build_tax_year_premium_report(customer_id, 0.0)
    assert replay['integrity']['statement_sha256'] == digest


def test_tax_year_report_uses_ledger_allocations_when_present():
    customer_id = _seed_customer()
    _seed_policy(customer_id, 'POL-LEDGER', 200.0, 100000.0)
    _seed_paid_bill(customer_id, 'POL-LEDGER', 'BILL-LEDGER', 200.0)
    portal.TRANSACTION_LEDGER['TX-LEDGER'] = {
        'id': 'TX-LEDGER',
        'customer_id': customer_id,
        'type': 'premium_payment',
        'amount': 200.0,
        'timestamp': datetime.now().isoformat(),
        'metadata': {
            'policy_id': 'POL-LEDGER',
            'bill_id': 'BILL-LEDGER',
            'savings_allocation': 80.0,
            'risk_allocation': 120.0,
        },
    }

    report = portal._build_tax_year_premium_report(customer_id, 200.0)
    sheet = report['policies'][0]
    assert sheet['paid_premium_total'] == 200.0
    assert sheet['risk_paid_total'] == 120.0
    assert sheet['savings_paid_total'] == 80.0
    assert report['tax_year_summary']['paid_premium_total'] == 200.0


def test_tax_year_statement_pdf_has_brand_and_one_sheet_per_policy():
    customer_id = _seed_customer()
    _seed_policy(customer_id, 'POL-LIFE-1', 100.0, 250000.0, 'life')
    _seed_policy(customer_id, 'POL-ADL-2', 50.0, 80000.0, 'adl')
    _seed_paid_bill(customer_id, 'POL-LIFE-1', 'BILL-LIFE-1', 100.0)
    _seed_paid_bill(customer_id, 'POL-ADL-2', 'BILL-ADL-2', 50.0)
    report = portal._build_tax_year_premium_report(customer_id, 0.0)

    pdf_bytes = render_tax_year_statement_pdf(report)
    assert pdf_bytes.startswith(b'%PDF')
    assert _pdf_page_count(pdf_bytes) >= 3
    text = _pdf_text(pdf_bytes)
    assert 'PHINS' in text
    assert 'Personal Health Insurance' in text
    assert 'Tax Year' in text
    assert 'Asaf Assurance' in text
    assert 'POL-LIFE-1' in text
    assert 'POL-ADL-2' in text
    assert '$150.00' in text
    assert '$90.00' in text
    assert '$60.00' in text
    assert report['integrity']['statement_sha256'][:16] in text
    assert STATEMENT_STANDARD in text


def test_notification_uses_real_totals_and_attaches_pdf():
    customer_id = _seed_customer()
    _seed_policy(customer_id, 'POL-LIFE-1', 125.0, 100000.0)
    _seed_paid_bill(customer_id, 'POL-LIFE-1', 'BILL-ONE', 125.0)
    report = portal._build_tax_year_premium_report(customer_id, 125.0)
    pdf_bytes = render_tax_year_statement_pdf(report)
    statement_doc = {
        'id': 'DOC-STATEMENT-1',
        'name': statement_filename(report['tax_year'], customer_id),
        'data': base64.b64encode(pdf_bytes).decode('ascii'),
        'sha256': hashlib.sha256(pdf_bytes).hexdigest(),
    }

    service = create_notification_service(use_mock=True)
    import services.notification_service as notif

    previous = dict(notif._notification_service_instances)
    notif._notification_service_instances.clear()
    notif._notification_service_instances[True] = service
    try:
        result = portal.notify_customer_tax_year_report_available(
            customer_id=customer_id,
            report_payload=report,
            document_ids=[statement_doc['id']],
            statement_document=statement_doc,
        )
    finally:
        notif._notification_service_instances.clear()
        notif._notification_service_instances.update(previous)

    assert '$125.00' in result['content']
    assert '$0.00' not in result['content']
    assert 'DOC-' not in result['content'] or 'Documents' in result['content']
    assert 'attached as a PDF' in result['content']
    assert 'POL-LIFE-1' in result['content']
    assert result['attachment_filename']
    assert '<html>' in result['html_content']
    assert '#0e2f63' in result['html_content']
    assert '#f7e2a0' in result['html_content']

    provider = service._email_provider
    assert isinstance(provider, MockEmailProvider)
    assert provider.sent_emails
    email = provider.sent_emails[-1]
    assert email['attachments']
    assert email['attachments'][0]['filename'].endswith('.pdf')
    assert email['attachments'][0]['size'] == len(pdf_bytes)
    assert email['attachments'][0]['sha256'] == hashlib.sha256(pdf_bytes).hexdigest()
    assert '$125.00' in email['body']


def test_upsert_statement_is_idempotent_for_unchanged_totals():
    customer_id = _seed_customer()
    for doc_id, doc in list(portal.POLICY_DOCUMENTS.items()):
        if doc.get('entity_id') == customer_id and doc.get('document_type') == 'tax_year_statement':
            portal.POLICY_DOCUMENTS.pop(doc_id, None)
    _seed_policy(customer_id, 'POL-LIFE-1', 80.0, 90000.0)
    _seed_paid_bill(customer_id, 'POL-LIFE-1', 'BILL-80', 80.0)
    report = portal._build_tax_year_premium_report(customer_id, 80.0)

    first, changed_first = portal._upsert_customer_tax_year_statement(customer_id, report)
    second, changed_second = portal._upsert_customer_tax_year_statement(customer_id, report)
    assert changed_first is True
    assert changed_second is False
    assert first['id'] == second['id']
    assert first['type'] == 'application/pdf'
    raw = base64.b64decode(first['data'])
    assert raw.startswith(b'%PDF')
    assert first['sha256'] == hashlib.sha256(raw).hexdigest()


def test_email_provider_records_pdf_attachment():
    service = create_notification_service(use_mock=True)
    pdf = b'%PDF-1.4 test-statement'
    result = service.send(NotificationRequest(
        channel=NotificationChannel.EMAIL,
        recipient='asaf.assurance@example.com',
        subject='PHINS tax-year premium statement 2026',
        content='Statement attached',
        attachments=[{
            'filename': 'PHINS_Tax_Year_Statement_2026.pdf',
            'content_type': 'application/pdf',
            'content': pdf,
        }],
        customer_id='CUST-TAX-STMT',
    ))
    assert result.success
    email = service._email_provider.sent_emails[-1]
    assert email['attachments'][0]['filename'] == 'PHINS_Tax_Year_Statement_2026.pdf'
    assert email['attachments'][0]['sha256'] == hashlib.sha256(pdf).hexdigest()
    history = service.get_history(customer_id='CUST-TAX-STMT')
    assert history[-1]['attachments'][0]['filename'] == 'PHINS_Tax_Year_Statement_2026.pdf'
    assert 'content' not in history[-1]
