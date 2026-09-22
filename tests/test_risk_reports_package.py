"""B9: ``services.risk_reports`` package split, extractor delegation, chart cost.

Covers:
* the ``services.ai_risk_reports_service`` facade re-exports the package
  objects and forwards the two mutable module names both ways;
* ``parse_content`` is a pure dispatcher whose output equals ``parse_file``;
* PDF / image text extraction is delegated to ``DocumentProcessingService``
  (text layer reaches the Hebrew field extractor; no-text and no-extractor
  cases keep the historical metadata-only table);
* charts are JSON configs whose construction cost is a small fraction of a
  report (the measured basis for *not* rendering lazily).
"""

import io
import json
import os
import struct
import sys
import time
import zipfile
import zlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.ai_risk_reports_service as facade  # noqa: E402
import services.risk_reports as pkg  # noqa: E402
from services.risk_reports import analysis as analysis_mod  # noqa: E402
from services.risk_reports import charts as charts_mod  # noqa: E402
from services.risk_reports import models as models_mod  # noqa: E402
from services.risk_reports import parsers as parsers_mod  # noqa: E402
from services.risk_reports import render as render_mod  # noqa: E402
from services.risk_reports import service as service_mod  # noqa: E402
from services.risk_reports.parsers import (  # noqa: E402
    ParserMixin, ZIP_PASSWORD_REJECTED, ZIP_PASSWORD_REQUIRED,
)
from tests.test_pension_agent import FIXTURES  # noqa: E402


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(facade, 'AI_REPORTS_DATA_FILE', str(tmp_path / 'never.json'))
    svc = facade.init_ai_reports_service(load_persisted=False)
    yield svc
    facade._ai_reports_service = None


def _pdf_with_text(lines):
    """Minimal single-page PDF with a real text layer (pypdf-readable)."""
    def esc(s):
        return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    content = "BT /F1 14 Tf 40 750 Td 16 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    body = content.encode('latin-1', errors='replace')
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


TEXT_PDF = _pdf_with_text(["Policy Number: 4471-22", "Insured: Dana Levi",
                           "Premium: 1250 monthly", "Cover: 500000"])
# No text objects; the string literals stay below the extractor's
# meaningful-text floor, so this exercises the metadata-only path.
BARE_PDF = (b"%PDF-1.4\n1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type /Pages /Kids [3 0 R 4 0 R] /Count 2>>endobj\n"
            b"3 0 obj<</Type /Page /Parent 2 0 R>>endobj\n"
            b"4 0 obj<</Type /Page /Parent 2 0 R>>endobj\n"
            b"5 0 obj<</Title (Q3 Summary) /Author (PHINS)>>endobj\n"
            b"trailer<</Root 1 0 R /Info 5 0 R>>\n%%EOF")
PNG_640x480 = (b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
               + (640).to_bytes(4, 'big') + (480).to_bytes(4, 'big')
               + b'\x08\x02\x00\x00\x00' + b'\x00' * 32)
ENG_CSV = b"""policy_number,coverage_amount,premium,claim_count,risk_score
P1,100000,1200,0,2
P2,250000,2400,1,5
P3,50000,600,3,8
"""
HEB_CSV = """מספר_פוליסה,סוג_ביטוח,סכום_כיסוי,פרמיה_חודשית,סטטוס_תביעה
POL001,חיים,500000,250,אושרה
POL002,בריאות,200000,180,נדחתה
""".encode('utf-8')
ARABIC_CSV = """رقم الوثيقة,نوع التأمين,مبلغ التغطية,القسط
P-1,تأمين على الحياة,500000,250
P-2,تأمين صحي,200000,180
""".encode('utf-8')


def _zip_of(*members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for i, m in enumerate(members):
            z.writestr(f'm{i}.xml', m)
    return buf.getvalue()


def _as_member_bytes(payload):
    if isinstance(payload, str):
        return payload.encode('utf-8')
    return payload


def _zip_members(members):
    """Unencrypted archive. ``members`` is ``(name, bytes)``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members:
            zf.writestr(name, _as_member_bytes(payload))
    return buf.getvalue()


def _zipcrypto_encrypt(data: bytes, password: bytes) -> bytes:
    """Traditional ZIP encryption the stdlib reader accepts."""
    table = []
    for crc in range(256):
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
        table.append(crc)

    def crc32_byte(ch, crc):
        return (crc >> 8) ^ table[(crc ^ ch) & 0xFF]

    keys = [305419896, 591751049, 878082192]

    def update(c):
        keys[0] = crc32_byte(c, keys[0])
        keys[1] = (keys[1] + (keys[0] & 0xFF)) & 0xFFFFFFFF
        keys[1] = (keys[1] * 134775813 + 1) & 0xFFFFFFFF
        keys[2] = crc32_byte(keys[1] >> 24, keys[2])

    for byte in password:
        update(byte)

    check = (zlib.crc32(data) >> 24) & 0xFF
    plain = os.urandom(11) + bytes([check]) + data
    out = bytearray()
    for byte in plain:
        k = keys[2] | 2
        cipher = byte ^ (((k * (k ^ 1)) >> 8) & 0xFF)
        update(byte)
        out.append(cipher)
    return bytes(out)


def _zipcrypto_archive(members, password: str, encoding: str = 'utf-8') -> bytes:
    """Build a ZipCrypto archive. ``password`` is encoded with ``encoding``."""
    pwd = password.encode(encoding)
    parts = []
    central = []
    offset = 0
    for name, payload in members:
        data = _as_member_bytes(payload)
        name_b = name.encode('utf-8')
        crc = zlib.crc32(data) & 0xFFFFFFFF
        cipher = _zipcrypto_encrypt(data, pwd)
        flag = 0x1 | 0x800
        local = struct.pack(
            '<IHHHHHIIIHH',
            0x04034b50, 20, flag, 0, 0, 0, crc,
            len(cipher), len(data), len(name_b), 0,
        ) + name_b + cipher
        parts.append(local)
        central.append(struct.pack(
            '<IHHHHHHIIIHHHHHII',
            0x02014b50, 20, 20, flag, 0, 0, 0, crc,
            len(cipher), len(data), len(name_b),
            0, 0, 0, 0, 0, offset,
        ) + name_b)
        offset += len(local)
    body = b''.join(parts)
    directory = b''.join(central)
    eocd = struct.pack(
        '<IHHHHIIH',
        0x06054b50, 0, 0, len(members), len(members),
        len(directory), len(body), 0,
    )
    return body + directory + eocd


def _aes_archive(members, password: str) -> bytes:
    pyzipper = pytest.importorskip('pyzipper')
    buf = io.BytesIO()
    with pyzipper.AESZipFile(
        buf, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(password.encode('utf-8'))
        for name, payload in members:
            zf.writestr(name, _as_member_bytes(payload))
    return buf.getvalue()


# --------------------------------------------------------------------------
# package split
# --------------------------------------------------------------------------
class TestPackageSplit:
    def test_facade_reexports_package_objects(self):
        for name in pkg.__all__:
            assert getattr(facade, name) is getattr(pkg, name), name
        assert facade.AIRiskReportsService is service_mod.AIRiskReportsService
        assert facade.LanguageDetector is analysis_mod.LanguageDetector
        assert facade.DataType is models_mod.DataType
        assert facade._risk_report_audit is models_mod._risk_report_audit

    def test_service_is_composed_of_the_layer_mixins(self):
        mro = service_mod.AIRiskReportsService.__mro__
        assert parsers_mod.ParserMixin in mro
        assert analysis_mod.AnalysisMixin in mro
        assert charts_mod.ChartsMixin in mro
        assert render_mod.RenderMixin in mro
        # every method of the old god-class still resolves on the service
        for name in ('_parse_csv', '_parse_zip', '_parse_pension_xml', '_parse_pdf', '_parse_image',
                     '_profile_columns', '_extract_factors_advanced', '_calculate_risk_score_advanced',
                     '_generate_charts', '_generate_pension_charts', '_build_savings_cover_id_charts',
                     '_generate_sections', '_generate_pension_section', '_generate_recommendations',
                     'analyze', 'generate_report', 'authorize_access', 'save_data', 'load_data',
                     'build_report_download_summary', 'to_dict'):
            assert callable(getattr(service_mod.AIRiskReportsService, name)), name

    def test_mutable_names_are_forwarded_both_ways(self, monkeypatch):
        original = service_mod.AI_REPORTS_DATA_FILE
        monkeypatch.setattr(facade, 'AI_REPORTS_DATA_FILE', '/tmp/phins-b9-forward.json')
        assert service_mod.AI_REPORTS_DATA_FILE == '/tmp/phins-b9-forward.json'
        monkeypatch.undo()
        assert service_mod.AI_REPORTS_DATA_FILE == original
        assert facade.AI_REPORTS_DATA_FILE == original

        svc = facade.init_ai_reports_service(load_persisted=False)
        try:
            assert facade._ai_reports_service is svc is service_mod._ai_reports_service
            facade._ai_reports_service = None
            assert service_mod._ai_reports_service is None
            assert facade.get_ai_reports_service() is not svc
        finally:
            facade._ai_reports_service = None

    def test_facade_save_path_is_the_one_the_service_writes(self, tmp_path, monkeypatch):
        target = tmp_path / 'via_facade.json'
        monkeypatch.setattr(facade, 'AI_REPORTS_DATA_FILE', str(target))
        svc = facade.init_ai_reports_service(load_persisted=False)
        try:
            doc = svc.parse_file('a.csv', ENG_CSV, 'csv', owner_id='CUST-1', owner_role='customer')
            assert doc['status'] == 'completed'
            assert target.exists(), 'save_data must honour the facade-level path'
            assert doc['document_id'] in json.loads(target.read_text(encoding='utf-8'))['documents']
        finally:
            facade._ai_reports_service = None

    def test_descriptor_and_capabilities_still_name_the_historical_module(self):
        from services.agent_runtime import get_descriptor
        assert get_descriptor('ai_risk_reports').module == 'services.ai_risk_reports_service'
        from services.ai_capabilities import AGENT_MODULES
        assert 'services.ai_risk_reports_service' in AGENT_MODULES

    def test_layers_are_usable_standalone(self):
        parsed, encoding = ParserMixin().parse_content('x.csv', ENG_CSV, 'csv')
        assert encoding == 'utf-8' and parsed['columns'][0] == 'policy_number' and len(parsed['rows']) == 3
        lang, _name, _conf = analysis_mod.LanguageDetector.detect('פוליסת ביטוח חיים עם פרמיה חודשית')
        assert lang == 'hebrew'


# --------------------------------------------------------------------------
# parse_content dispatcher
# --------------------------------------------------------------------------
class TestParseContent:
    @pytest.mark.parametrize('name,content,ftype', [
        ('eng.csv', ENG_CSV, 'csv'), ('heb.csv', HEB_CSV, 'csv'),
        ('m.xml', FIXTURES['realistic_small'], 'xml'),
        ('b.zip', _zip_of(FIXTURES['simple'], FIXTURES['realistic_small']), 'zip'),
        ('bare.pdf', BARE_PDF, 'pdf'), ('img.png', PNG_640x480, 'png'),
        ('unknown.bin', b'\x00\x01\x02\x03' * 200, 'bin'),
        ('unknown.txt', b'a,b\n1,2\n', 'txt'),
    ])
    def test_parse_content_equals_parse_file(self, service, name, content, ftype):
        pure, encoding = service.parse_content(name, content, ftype)
        stored = service.parse_file(name, content, ftype, owner_id='CUST-1', owner_role='customer')
        assert stored['status'] == 'completed', stored.get('error')
        assert stored['encoding'] == encoding
        assert stored['parsed_data'] == pure
        assert stored['row_count'] == len(pure['rows'])

    def test_parse_content_is_pure(self, service):
        before = (len(service.documents), len(service.analyses), len(service.reports))
        service.parse_content('eng.csv', ENG_CSV, 'csv')
        assert (len(service.documents), len(service.analyses), len(service.reports)) == before

    def test_malformed_zip_raises_and_parse_file_reports_failed(self, service):
        with pytest.raises(Exception):
            service.parse_content('bad.zip', b'not a zip archive', 'zip')
        doc = service.parse_file('bad.zip', b'not a zip archive', 'zip', owner_id='CUST-1', owner_role='customer')
        assert doc['status'] == 'failed' and doc['error']

    def test_unknown_binary_falls_back_to_metadata_table(self, service):
        parsed, encoding = service.parse_content('blob.bin', b'\x00\x01\x02\x03' * 200, 'bin')
        assert encoding == 'binary' and parsed['file_type'] == 'binary'
        assert parsed['rows'][0]['filename'] == 'blob.bin'

    def test_language_detection_unchanged(self, service):
        heb = service.parse_file('h.csv', HEB_CSV, 'csv', owner_id='CUST-1', owner_role='customer')
        ara = service.parse_file('a.csv', ARABIC_CSV, 'csv', owner_id='CUST-1', owner_role='customer')
        assert service.analyze(heb['document_id']).language == 'hebrew'
        assert service.analyze(ara['document_id']).language == 'arabic'


# --------------------------------------------------------------------------
# PDF / image delegation to DocumentProcessingService
# --------------------------------------------------------------------------
class TestExtractorDelegation:
    def test_pdf_text_layer_reaches_the_rows(self, service):
        pytest.importorskip('pypdf')
        parsed, _ = service.parse_content('policy.pdf', TEXT_PDF, 'pdf')
        content_rows = [r for r in parsed['rows'] if r['category'] == 'content']
        assert [r['property'] for r in content_rows] == ['page_count', 'page_1_text']
        assert 'Policy Number: 4471-22' in content_rows[1]['value']
        assert parsed['text_extraction'] == 'document_intelligence'
        assert parsed['text_pages'][0]['page'] == 1
        assert parsed['text'][parsed['text_pages'][0]['char_start']:parsed['text_pages'][0]['char_end']] == parsed['text']
        assert parsed['page_count'] == 1  # '/Type /Pages' is no longer counted as a page

    def test_hebrew_pdf_text_drives_language_and_field_extraction(self, service, monkeypatch):
        pytest.importorskip('pypdf')
        # Text layer bytes are latin-1 in this minimal PDF, so the Hebrew
        # is injected the way the extractor returns it: through the shared
        # DocumentProcessingService. Patch its extractor to return the text a
        # Hebrew policy scan yields; the parser is what is under test.
        from services.document_processing_service import DocumentProcessingService
        hebrew = ("פוליסת ביטוח חיים\nמספר פוליסה: 778-2210\nשם המבוטח: דנה לוי\n"
                  "פרמיה: 250\nסכום ביטוח: 500,000\nתאריך תחילה: 01/01/2024")
        pages = [{'page': 1, 'char_start': 0, 'char_end': len(hebrew)}]
        calls = []

        def fake(self, raw, *, lang_hint=None):
            calls.append(lang_hint)
            return hebrew, pages
        monkeypatch.setattr(DocumentProcessingService, '_extract_pdf_text_with_pages', fake)
        doc = service.parse_file('policy_he.pdf', TEXT_PDF, 'pdf', owner_id='CUST-1', owner_role='customer')
        assert calls == [None]
        parsed = doc['parsed_data']
        assert next(r for r in parsed['rows'] if r['property'] == 'has_hebrew')['value'] == 'True'
        analysis = service.analyze(doc['document_id'])
        assert analysis.language == 'hebrew'
        names = {f.name for f in analysis.extracted_factors}
        assert any('778-2210' in str(f.value) for f in analysis.extracted_factors), names
        report = service.generate_report(analysis.id)
        assert report.language == 'hebrew' and report.sections

    def test_number_heavy_bilingual_pdf_still_extracts_hebrew_fields(self, service, monkeypatch):
        pytest.importorskip('pypdf')
        # A policy table of IDs and amounts with sparse Hebrew labels does not
        # classify as Hebrew, and its page rows sit after the metadata rows, so
        # only the extracted text itself can gate the field extraction.
        from services.document_processing_service import DocumentProcessingService
        body = "\n".join([
            "Policy Schedule / Table of Benefits",
            "ID 123456789  Ref 998877  Branch 0042  Agent 5512  Code 7781",
            "מספר פוליסה: 778-2210",
            "Gross 1,250.00  Net 1,100.00  Tax 150.00  Total 1,275.00",
            "פרמיה: 250",
            "סכום ביטוח: 500,000",
            "תאריך תחילה: 01/01/2024",
        ] + [f"Line {i}  value {i * 7}  amount {i * 13}.00" for i in range(80)])
        pages = [{'page': 1, 'char_start': 0, 'char_end': len(body)}]
        monkeypatch.setattr(DocumentProcessingService, '_extract_pdf_text_with_pages',
                            lambda self, raw, *, lang_hint=None: (body, pages))
        doc = service.parse_file('policy_schedule.pdf', TEXT_PDF, 'pdf',
                                 owner_id='CUST-1', owner_role='customer')
        analysis = service.analyze(doc['document_id'])
        assert analysis.language != 'hebrew'
        names = {f.name for f in analysis.extracted_factors}
        assert any('778-2210' in str(f.value) for f in analysis.extracted_factors), names

    def test_hebrew_filename_passes_a_language_hint(self, service, monkeypatch):
        from services.document_processing_service import DocumentProcessingService
        seen = []

        def fake(self, raw, *, lang_hint=None):
            seen.append(lang_hint)
            return '[PDF content - extraction yielded no text; image-only or encrypted]', []
        monkeypatch.setattr(DocumentProcessingService, '_extract_pdf_text_with_pages', fake)
        service.parse_content('פוליסה.pdf', BARE_PDF, 'pdf')
        assert seen == ['hebrew']

    def test_pdf_without_text_keeps_the_legacy_metadata_table(self, service):
        parsed, _ = service.parse_content('summary.pdf', BARE_PDF, 'pdf')
        props = [r['property'] for r in parsed['rows']]
        assert props == ['filename', 'file_type', 'file_size_bytes', 'file_size_kb', 'file_size_mb',
                         'page_count', 'title', 'author', 'document_type', 'source_name', 'has_hebrew']
        assert 'text' not in parsed and 'text_pages' not in parsed and 'text_extraction' not in parsed
        assert parsed['page_count'] == 2
        assert next(r for r in parsed['rows'] if r['property'] == 'title')['value'] == 'Q3 Summary'

    def test_extractor_marker_is_never_treated_as_text(self, service, monkeypatch):
        from services.document_processing_service import DocumentProcessingService
        marker = '[PDF content - extraction yielded no text; image-only or encrypted]'
        monkeypatch.setattr(DocumentProcessingService, '_extract_pdf_text_with_pages',
                            lambda self, raw, *, lang_hint=None: (marker, []))
        parsed, _ = service.parse_content('scan.pdf', BARE_PDF, 'pdf')
        assert 'text' not in parsed
        assert all(r['property'] != 'page_1_text' for r in parsed['rows'])

    def test_extractor_unavailable_degrades_to_metadata(self, service, monkeypatch):
        def boom():
            raise RuntimeError('document intelligence offline')
        monkeypatch.setattr(parsers_mod, '_document_service', boom)
        pdf, _ = service.parse_content('a.pdf', TEXT_PDF, 'pdf')
        img, _ = service.parse_content('a.png', PNG_640x480, 'png')
        assert 'text' not in pdf and pdf['page_count'] == 1
        assert next(r for r in img['rows'] if r['property'] == 'resolution')['value'] == '0x0'

    def test_image_dimensions_and_ocr_come_from_the_shared_extractor(self, service, monkeypatch):
        from services.document_processing_service import DocumentProcessingService
        calls = []

        def fake_ocr(self, raw, *, lang_hint=None):
            calls.append(len(raw))
            return 'תעודת זהות: 123456782\nפרמיה: 180'
        monkeypatch.setattr(DocumentProcessingService, '_ocr_image_bytes', fake_ocr)
        parsed, _ = service.parse_content('id_scan.png', PNG_640x480, 'png')
        assert calls == [len(PNG_640x480)]
        by_prop = {r['property']: r['value'] for r in parsed['rows']}
        assert by_prop['resolution'] == '640x480'
        assert by_prop['ocr_text'].startswith('תעודת זהות')
        assert parsed['text_extraction'] == 'ocr'

    def test_image_without_ocr_is_the_legacy_table(self, service, monkeypatch):
        from services.document_processing_service import DocumentProcessingService
        monkeypatch.setattr(DocumentProcessingService, '_ocr_image_bytes',
                            lambda self, raw, *, lang_hint=None: '')
        parsed, _ = service.parse_content('photo.png', PNG_640x480, 'png')
        assert [r['property'] for r in parsed['rows']] == [
            'filename', 'file_type', 'file_size_bytes', 'file_size_kb', 'width_px', 'height_px',
            'resolution', 'document_type', 'source_name']
        assert 'text' not in parsed

    def test_long_pdf_text_is_capped_per_row_but_kept_whole(self, service, monkeypatch):
        from services.document_processing_service import DocumentProcessingService
        page = ('policy premium coverage insured ' * 400).strip()  # ~12.8k chars
        text = page + '\n\n' + page
        pages = [{'page': 1, 'char_start': 0, 'char_end': len(page)},
                 {'page': 2, 'char_start': len(page) + 2, 'char_end': len(text)}]
        monkeypatch.setattr(DocumentProcessingService, '_extract_pdf_text_with_pages',
                            lambda self, raw, *, lang_hint=None: (text, pages))
        parsed, _ = service.parse_content('long.pdf', BARE_PDF, 'pdf')
        rows = [r for r in parsed['rows'] if r['property'].startswith('page_') and r['property'].endswith('_text')]
        assert [r['property'] for r in rows] == ['page_1_text', 'page_2_text']
        assert all(len(r['value']) == parsers_mod.TEXT_ROW_MAX_CHARS for r in rows)
        assert parsed['text'] == text and parsed['page_count'] == 2


# --------------------------------------------------------------------------
# charts: configs, not renders
# --------------------------------------------------------------------------
class TestChartsAreConfigs:
    def _report_for(self, service, name, content, ftype):
        doc = service.parse_file(name, content, ftype, owner_id='CUST-1', owner_role='customer')
        assert doc['status'] == 'completed', doc.get('error')
        analysis = service.analyze(doc['document_id'])
        return analysis, service.generate_report(analysis.id)

    def test_charts_are_json_data_without_rendered_payloads(self, service):
        _analysis, report = self._report_for(service, 'm.xml', FIXTURES['realistic_medium'], 'xml')
        assert report.charts
        blob = json.dumps(service.to_dict(report.charts), ensure_ascii=False)
        assert 'base64' not in blob and 'image/png' not in blob
        for chart in report.charts:
            assert chart.type in models_mod.ChartType
            assert isinstance(chart.data, dict)
            assert not any(isinstance(v, (bytes, bytearray)) for v in chart.data.values())

    def test_chart_config_cost_is_a_small_fraction_of_the_report(self, service):
        """Measured basis for building charts eagerly (design §B9 deviation)."""
        analysis, report = self._report_for(service, 'm.xml', FIXTURES['realistic_medium'], 'xml')
        doc = service.documents[analysis.document_id]['parsed_data']
        pension = doc.get('pension_data')

        def timed(fn, n=5):
            best = float('inf')
            for _ in range(n):
                t0 = time.perf_counter()
                fn()
                best = min(best, time.perf_counter() - t0)
            return best

        charts_s = timed(lambda: service._generate_charts(analysis, pension, doc))
        report_s = timed(lambda: service.generate_report(analysis.id))
        assert charts_s < 0.25, f"chart configs took {charts_s*1000:.1f} ms"
        assert charts_s <= max(0.5 * report_s, 0.005), (
            f"charts {charts_s*1000:.2f} ms vs report {report_s*1000:.2f} ms")
        # ~ how much of the report payload the configs are
        chart_bytes = len(json.dumps(service.to_dict(report.charts), ensure_ascii=False))
        report_bytes = len(json.dumps(service.to_dict(report), ensure_ascii=False))
        assert chart_bytes < report_bytes

    def test_non_pension_report_has_gauge_first(self, service):
        _analysis, report = self._report_for(service, 'e.csv', ENG_CSV, 'csv')
        assert report.charts[0].type is models_mod.ChartType.GAUGE
        assert report.charts[0].data['value'] == report.metadata['risk_score']


# --------------------------------------------------------------------------
# persistence round trip still covers the new parsed keys
# --------------------------------------------------------------------------
def test_json_persistence_round_trip_with_pdf_text(tmp_path, monkeypatch):
    pytest.importorskip('pypdf')
    target = tmp_path / 'rr.json'
    monkeypatch.setattr(facade, 'AI_REPORTS_DATA_FILE', str(target))
    svc = facade.init_ai_reports_service(load_persisted=False)
    try:
        doc = svc.parse_file('policy.pdf', TEXT_PDF, 'pdf', owner_id='CUST-1', owner_role='customer')
        analysis = svc.analyze(doc['document_id'])
        report = svc.generate_report(analysis.id)
        fresh = facade.init_ai_reports_service(load_persisted=True)
        assert report.id in fresh.reports and analysis.id in fresh.analyses
        assert fresh.reports[report.id].title == report.title
        assert fresh.documents[doc['document_id']]['parsed_data'] is None  # rows are not persisted to JSON
        assert svc.to_dict(fresh.reports[report.id].charts) == svc.to_dict(report.charts)
    finally:
        facade._ai_reports_service = None


# --------------------------------------------------------------------------
# password-protected ZIP intake
# --------------------------------------------------------------------------
class TestZipPassword:
    MEMBERS = (
        ('holdings.xml', FIXTURES['simple']),
        ('policies.csv', ENG_CSV),
    )

    def _assert_same_assessment(self, plain, opened):
        assert opened['rows'] == plain['rows']
        assert opened['columns'] == plain['columns']
        assert opened.get('pension_data') == plain.get('pension_data')
        assert opened['integrity']['zip_file_count'] == plain['integrity']['zip_file_count']
        assert opened['files'] == plain['files']

    def test_unencrypted_zip_ignores_a_supplied_password(self, service):
        plain_bytes = _zip_members(self.MEMBERS)
        plain, _ = service.parse_content('plain.zip', plain_bytes, 'zip')
        with_password, _ = service.parse_content(
            'plain.zip', plain_bytes, 'zip', file_password='not-used',
        )
        self._assert_same_assessment(plain, with_password)

    def test_zipcrypto_password_opens_the_same_data(self, service):
        plain_bytes = _zip_members(self.MEMBERS)
        locked = _zipcrypto_archive(self.MEMBERS, 'secret-pass')
        plain, _ = service.parse_content('plain.zip', plain_bytes, 'zip')
        opened, _ = service.parse_content(
            'locked.zip', locked, 'zip', file_password='secret-pass',
        )
        self._assert_same_assessment(plain, opened)
        stored = service.parse_file(
            'locked.zip', locked, 'zip',
            owner_id='CUST-1', owner_role='customer', file_password='secret-pass',
        )
        assert stored['status'] == 'completed', stored.get('error')
        blob = json.dumps(stored, ensure_ascii=False)
        assert 'secret-pass' not in blob
        assert 'file_password' not in stored
        analysis = service.analyze(stored['document_id'])
        assert analysis.id

    def test_missing_or_wrong_password_stores_nothing(self, service):
        locked = _zipcrypto_archive(self.MEMBERS, 'secret-pass')
        before = set(service.documents)
        with pytest.raises(ValueError, match='password-protected'):
            service.parse_content('locked.zip', locked, 'zip')
        missing = service.parse_file(
            'locked.zip', locked, 'zip', owner_id='CUST-1', owner_role='customer',
        )
        assert missing['status'] == 'failed'
        assert missing['error'] == ZIP_PASSWORD_REQUIRED
        assert missing['document_id'] not in service.documents
        wrong = service.parse_file(
            'locked.zip', locked, 'zip',
            owner_id='CUST-1', owner_role='customer', file_password='nope',
        )
        assert wrong['status'] == 'failed'
        assert wrong['error'] == ZIP_PASSWORD_REJECTED
        assert 'nope' not in wrong['error']
        assert 'secret-pass' not in wrong['error']
        assert wrong['document_id'] not in service.documents
        assert set(service.documents) == before

    def test_windows_hebrew_password_encoding(self, service):
        password = 'סוד'
        locked = _zipcrypto_archive(self.MEMBERS, password, encoding='cp1255')
        plain, _ = service.parse_content('plain.zip', _zip_members(self.MEMBERS), 'zip')
        opened, _ = service.parse_content(
            'locked.zip', locked, 'zip', file_password=password,
        )
        self._assert_same_assessment(plain, opened)

    def test_aes_password_opens_the_same_data(self, service):
        locked = _aes_archive(self.MEMBERS, 'aes-secret')
        plain, _ = service.parse_content('plain.zip', _zip_members(self.MEMBERS), 'zip')
        opened, _ = service.parse_content(
            'aes.zip', locked, 'zip', file_password='aes-secret',
        )
        self._assert_same_assessment(plain, opened)
        with pytest.raises(ValueError, match='password-protected'):
            service.parse_content('aes.zip', locked, 'zip')

    def test_dashboard_asks_for_the_password_before_analyze(self):
        html = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         'web_portal', 'static', 'risk-reports-dashboard.html'),
            encoding='utf-8',
        ).read()
        password_at = html.find('id="filePassword"')
        analyze_at = html.find('id="analyzeBtn"')
        assert 0 < password_at < analyze_at
        assert 'file_password' in html
        assert 'If the ZIP has one' in html

