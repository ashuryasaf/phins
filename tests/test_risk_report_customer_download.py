"""Customer-facing risk-report download: assessment only, no completeness dump."""

from __future__ import annotations

import io
import re
import unittest

from services.ai_risk_reports_service import init_ai_reports_service
from services.risk_reports.pdf_export import (
    BRAND_NAME,
    BRAND_TAGLINE,
    PHINS_GOLD_STRONG,
    PHINS_INK,
    bidi_text,
    build_report_csv_bytes,
    build_report_pdf_bytes,
    classify_cover_type,
    collect_uploaded_risk_covers,
    consultant_intro_copy,
    customer_assessment_narrative,
    customer_report_title,
    customer_signature_identity,
    is_non_assessment_section_title,
    is_staff_chart_title,
    prepare_customer_download_charts,
    prepare_customer_download_recommendations,
    prepare_customer_download_sections,
    strip_completeness_copy,
)


def _pdf_fill_color(hex_color: str) -> tuple:
    digits = hex_color.lstrip('#')
    return tuple(round(int(digits[i:i + 2], 16) / 255, 6) for i in (0, 2, 4))


def _pdf_text_by_fill_color(pdf_bytes: bytes) -> dict:
    """Group the strings drawn in a PDF by the fill colour in force."""
    from pypdf import PdfReader

    grouped: dict = {}
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        stream = page.get_contents().get_data().decode('latin-1')
        color = None
        for match in re.finditer(r'([\d.]+) ([\d.]+) ([\d.]+) rg|\((.*?)\) Tj', stream):
            if match.group(4) is None:
                color = tuple(round(float(match.group(i)), 6) for i in (1, 2, 3))
            else:
                grouped.setdefault(color, []).append(match.group(4))
    return grouped


class TestCustomerDownloadHelpers(unittest.TestCase):
    def test_generic_data_analysis_titles_are_excluded(self):
        self.assertTrue(is_non_assessment_section_title('דו״ח ניתוח נתונים'))
        self.assertTrue(is_non_assessment_section_title('דו"ח ניתוח נתונים'))
        self.assertTrue(is_non_assessment_section_title('Data Analysis Report'))
        self.assertTrue(is_non_assessment_section_title('שלמות נתונים'))
        self.assertTrue(is_non_assessment_section_title('Uploaded Data Content'))
        self.assertFalse(is_non_assessment_section_title('סיכום ההערכה'))
        self.assertFalse(is_non_assessment_section_title('Assessment Summary'))

    def test_strip_completeness_copy_drops_integrity_lines(self):
        text = (
            "סיכום ההערכה\n"
            "• שלמות נתונים: 82%\n"
            "• Data completeness: 82%\n"
            "• תקינות מזהה: תקין\n"
            "• סה״כ צבירה: ₪10,000\n"
        )
        cleaned = strip_completeness_copy(text)
        self.assertNotIn('שלמות נתונים', cleaned)
        self.assertNotIn('Data completeness', cleaned)
        self.assertNotIn('תקינות מזהה', cleaned)
        self.assertIn('סה״כ צבירה', cleaned)

    def test_prepare_sections_keeps_assessment_and_renames(self):
        prepared = prepare_customer_download_sections([
            {'title': 'תקציר מנהלים', 'content': 'ההערכה שלך לאחר הניתוח', 'columns': [], 'rows': []},
            {'title': 'דו״ח ניתוח נתונים', 'content': 'רשומות נותחו', 'columns': [], 'rows': []},
            {'title': 'שלמות נתונים', 'content': '82%', 'columns': [], 'rows': []},
            {'title': 'פרופיל נתונים', 'content': '• שלמות נתונים: 82%', 'columns': [], 'rows': []},
        ])
        titles = [section['title'] for section in prepared]
        self.assertEqual(titles, ['סיכום ההערכה'])
        self.assertEqual(prepared[0]['content'], 'ההערכה שלך לאחר הניתוח')

    def test_statistical_analyse_dump_is_stripped_from_narrative(self):
        raw = (
            "ניתוח AI מקיף של נתוני ביטוח:\n\n"
            "📊 סטטיסטיקה:\n"
            "• 10 רשומות נותחו\n"
            "• 13 שדות זוהו\n"
            "🎯 הערכת סיכון: 65/100 (גבוה)\n"
            "• שלמות נתונים: 82%\n"
        )
        cleaned = customer_assessment_narrative(raw)
        self.assertNotIn('רשומות נותחו', cleaned)
        self.assertNotIn('סטטיסטיקה', cleaned)
        self.assertNotIn('שלמות נתונים', cleaned)
        self.assertIn('הערכת סיכון', cleaned)

    def test_customer_title_replaces_data_analysis_report(self):
        self.assertEqual(
            customer_report_title({'title': 'דו״ח ניתוח נתונים', 'language': 'hebrew'}),
            'ההערכה שלך',
        )
        self.assertEqual(
            customer_report_title({'title': 'Data Analysis Report', 'language': 'english'}),
            'Your Assessment',
        )
        self.assertEqual(
            customer_report_title({
                'title': 'דו״ח ניתוח נתונים',
                'language': 'hebrew',
                'is_pension_data': True,
            }),
            'ההערכה שלך',
        )

    def test_staff_completeness_charts_are_excluded(self):
        self.assertTrue(is_staff_chart_title('ID Field Coverage'))
        self.assertTrue(is_staff_chart_title('כיסוי שדות זיהוי'))
        self.assertFalse(is_staff_chart_title('Savings vs Cover'))
        self.assertFalse(is_staff_chart_title('צבירה לפי יצרן'))
        prepared = prepare_customer_download_charts([
            {'title': 'Savings vs Cover', 'type': 'bar', 'series': [
                {'label': 'Savings', 'value': 10000}, {'label': 'Cover', 'value': 55000},
            ]},
            {'title': 'ID Field Coverage', 'type': 'doughnut', 'series': [
                {'label': 'With ID', 'value': 2}, {'label': 'Without ID', 'value': 0},
            ]},
            {'title': 'Risk Score', 'type': 'gauge', 'series': [{'label': 'value', 'value': 40}]},
        ])
        self.assertEqual([chart['title'] for chart in prepared], ['Savings vs Cover'])

    def test_staff_data_quality_recommendations_are_excluded(self):
        prepared = prepare_customer_download_recommendations([
            {'title': 'Review cover gap', 'description': 'Walk through the cover gap with your advisor.'},
            {'title': 'Data quality', 'description': '11 columns have >30% missing values'},
            {'title': 'Investigate data collection process for missing values', 'description': ''},
            # Wording the analyser actually emits for the data-quality note.
            {'title': 'Complete Missing Data',
             'description': 'Fields with missing data detected affecting analysis quality'},
            {'title': 'השלמת נתונים חסרים',
             'description': 'זוהו שדות עם נתונים חסרים המשפיעים על איכות הניתוח'},
        ])
        self.assertEqual([rec['title'] for rec in prepared], ['Review cover gap'])

    def test_navy_label_and_header_cells_are_gold(self):
        payload = {
            'language': 'english',
            'generated_at': '2026-09-22T10:00:00',
            'savings_cover_id_summary': {'customer_id': '123456782', 'total_savings': 10000},
            'assessment_sections': [{
                'title': 'Your Policy Details',
                'columns': ['PolicyNo'],
                'rows': [{'PolicyNo': 'POL-2001'}],
            }],
        }
        by_color = _pdf_text_by_fill_color(build_report_pdf_bytes(payload))
        gold = _pdf_fill_color(PHINS_GOLD_STRONG)
        ink = _pdf_fill_color(PHINS_INK)
        # Labels and data headers sit on the navy fill, values on the ice fill.
        self.assertIn('National ID', by_color.get(gold, []))
        self.assertIn('Total Savings', by_color.get(gold, []))
        self.assertIn('PolicyNo', by_color.get(gold, []))
        self.assertIn('123456782', by_color.get(ink, []))
        self.assertNotIn('National ID', by_color.get(ink, []))

    def test_uploaded_covers_are_collected_without_inventing_rows(self):
        covers = collect_uploaded_risk_covers([{
            'policy_number': 'POL-1',
            'provider': 'מגדל',
            'death_coverage': 400000,
            'death_premium': 85,
            'disability_coverage': 12000,
            'disability_premium': 40,
            'waiver_coverage': 0,
            'risk_covers': [
                {'code': '5', 'name': 'שארים', 'amount': 8000, 'cost': 22},
                {'code': '6', 'name': 'סיעוד', 'amount': 5500, 'cost': 30},
            ],
        }])
        keys = {cover['type_key'] for cover in covers}
        self.assertIn('life', keys)
        self.assertIn('disability_work', keys)
        self.assertIn('survivors', keys)
        self.assertIn('ltc', keys)
        self.assertNotIn('waiver', keys)
        self.assertEqual(collect_uploaded_risk_covers([{'policy_number': 'POL-2'}]), [])

    def test_cover_type_labels_match_consultant_vocabulary(self):
        self.assertEqual(classify_cover_type('1', ''), ('life', 'ביטוח חיים', 'Life Insurance'))
        self.assertEqual(classify_cover_type('', 'אבדן כושר עבודה')[0], 'disability_work')
        self.assertEqual(classify_cover_type('', 'שחרור')[0], 'waiver')
        self.assertEqual(classify_cover_type('', 'סיעוד')[0], 'ltc')

    def test_signature_identity_uses_uploaded_name_and_id(self):
        name, ident = customer_signature_identity({
            'pension_assessment': {
                'client': {'full_name': 'ישראל ישראלי', 'id_number': '123456782'},
            }
        })
        self.assertEqual(name, 'ישראל ישראלי')
        self.assertEqual(ident, '123456782')

    def test_consultant_intro_is_customer_facing(self):
        hebrew = consultant_intro_copy(True)
        english = consultant_intro_copy(False)
        self.assertIn('יועץ', hebrew)
        self.assertNotIn('שלמות', hebrew)
        self.assertIn('advisor', english.lower())
        self.assertIn('Analyse', english)

    def test_hebrew_bidi_reorders_mixed_text(self):
        try:
            from bidi.algorithm import get_display
        except ImportError:
            self.skipTest('python-bidi is required for RTL downloads')
        logical = 'ההערכה שלך'
        visual = bidi_text(logical, rtl=True)
        self.assertEqual(visual, get_display(logical, base_dir='R'))
        self.assertNotEqual(visual, logical)


class TestCustomerDownloadFromAnalyse(unittest.TestCase):
    def setUp(self):
        self.service = init_ai_reports_service()

    def test_generic_csv_download_omits_completeness_and_data_dump(self):
        csv_content = b"""customer_id,savings_balance,cover_amount,policy_number
123456782,10000,55000,POL-2001
123456780,8000,40000,POL-2002"""
        parse_result = self.service.parse_file(
            'customer_snapshot.csv',
            csv_content,
            'csv',
            owner_id='CUST-OWNER-001',
            owner_role='customer',
        )
        analysis = self.service.analyze(parse_result['document_id'])
        report = self.service.generate_report(analysis.id, language='english')
        self.assertTrue(report.title.startswith('Your'))
        self.assertIn('Assessment', report.title)

        export_payload = self.service.build_report_download_summary(
            report_id=report.id,
            user_id='CUST-OWNER-001',
            user_role='customer',
        )
        self.assertTrue(export_payload['title'].startswith('Your'))
        self.assertIn('Assessment', export_payload['title'])
        export_titles = [section.get('title') for section in export_payload.get('assessment_sections') or []]
        for banned in (
            'Data Profile',
            'Data Analysis Report',
            'Uploaded Data Content',
            'Data Integrity',
            'Statistical Analysis',
            'Key Metrics',
        ):
            self.assertNotIn(banned, export_titles)
        self.assertNotIn('integrity_issues', export_payload.get('savings_cover_id_summary') or {})

        blob = '\n'.join(
            (section.get('content') or '') + ' ' + (section.get('title') or '')
            for section in export_payload.get('assessment_sections') or []
        )
        self.assertNotIn('שלמות נתונים', blob)
        self.assertNotIn('Data completeness', blob)
        self.assertNotIn('records analyzed', blob.lower())
        self.assertNotIn('Data Analysis Report', blob)

        from pypdf import PdfReader
        pdf_bytes = build_report_pdf_bytes(export_payload)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        pdf_text = '\n'.join(
            (page.extract_text() or '') for page in PdfReader(io.BytesIO(pdf_bytes)).pages
        )
        self.assertNotIn('שלמות נתונים', pdf_text)
        self.assertNotIn('Data Integrity', pdf_text)
        self.assertNotIn('Data Analysis Report', pdf_text)
        self.assertNotIn('PHINS Savings & Insurance Report Summary', pdf_text)
        self.assertIn('Assessment', pdf_text)
        self.assertIn('Agent recommendations', pdf_text)
        self.assertIn('Customer', pdf_text)
        self.assertIn('Advisor', pdf_text)
        self.assertIn(BRAND_NAME, pdf_text)
        self.assertTrue(BRAND_TAGLINE in pdf_text or 'PHINS' in pdf_text)
        self.assertNotIn('ID Field Coverage', pdf_text)
        charts = export_payload.get('chart_summaries') or []
        self.assertTrue(charts)
        chart_titles = [chart.get('title') for chart in charts]
        self.assertTrue(any('Savings vs Cover' in str(title) for title in chart_titles))
        self.assertNotIn('ID Field Coverage', chart_titles)

        csv_bytes = build_report_csv_bytes(export_payload)
        csv_text = csv_bytes.decode('utf-8')
        self.assertIn('Assessment', csv_text)
        self.assertNotIn('שלמות נתונים', csv_text)
        self.assertNotIn('Records Analyzed', csv_text)
        self.assertNotIn('Data completeness', csv_text)

    def test_hebrew_pdf_is_rtl_and_customer_titled(self):
        csv_content = (
            "תעודת זהות,חיסכון,כיסוי\n"
            "123456782,10000,55000\n"
        ).encode('utf-8')
        parse_result = self.service.parse_file(
            'hebrew_snapshot.csv',
            csv_content,
            'csv',
            owner_id='CUST-OWNER-001',
            owner_role='customer',
        )
        analysis = self.service.analyze(parse_result['document_id'])
        report = self.service.generate_report(analysis.id, language='hebrew')
        self.assertIn('הערכ', report.title)
        export_payload = self.service.build_report_download_summary(
            report_id=report.id,
            user_id='CUST-OWNER-001',
            user_role='customer',
        )
        self.assertIn('הערכ', export_payload['title'])
        pdf_bytes = build_report_pdf_bytes(export_payload)
        from pypdf import PdfReader
        pdf_text = '\n'.join(
            (page.extract_text() or '') for page in PdfReader(io.BytesIO(pdf_bytes)).pages
        )
        self.assertNotIn('דו״ח ניתוח נתונים', pdf_text)
        self.assertNotIn('שלמות נתונים', pdf_text)
        # Logical and visual (bidi) forms are both acceptable after extract_text.
        self.assertTrue(
            'ההערכה שלך' in pdf_text or 'הלש ךתרעהה' in pdf_text
        )
        self.assertTrue('המלצות היועץ' in pdf_text or bidi_text('המלצות היועץ', rtl=True) in pdf_text)
        self.assertTrue('חתימות' in pdf_text or bidi_text('חתימות', rtl=True) in pdf_text)


class TestCoverAndSignatureDownload(unittest.TestCase):
    def test_pdf_lists_uploaded_covers_costs_and_signature_identity(self):
        summary = {
            'title': 'ההערכה שלך',
            'language': 'hebrew',
            'generated_at': '2026-09-22T12:00:00',
            'is_pension_data': True,
            'pension_assessment': {
                'client': {'full_name': 'ישראל ישראלי', 'id_number': '123456782'},
                'totals': {
                    'total_balance': 50000,
                    'total_savings': 50000,
                    'total_severance': 0,
                    'account_count': 1,
                },
                'accounts': [{
                    'policy_number': 'POL-COVER-1',
                    'provider': 'מגדל',
                    'product_type_name': 'קרן פנסיה מקיפה',
                    'total_balance': 50000,
                    'death_coverage': 400000,
                    'death_premium': 85,
                    'disability_coverage': 12000,
                    'disability_premium': 40,
                    'risk_covers': [
                        {'code': '4', 'name': 'שחרור', 'amount': 1, 'cost': 15},
                        {'code': '5', 'name': 'שארים', 'amount': 8000, 'cost': 22},
                        {'code': '6', 'name': 'סיעוד', 'amount': 5500, 'cost': 30},
                    ],
                }],
            },
            'risk_covers': collect_uploaded_risk_covers([{
                'policy_number': 'POL-COVER-1',
                'provider': 'מגדל',
                'death_coverage': 400000,
                'death_premium': 85,
                'disability_coverage': 12000,
                'disability_premium': 40,
                'risk_covers': [
                    {'code': '4', 'name': 'שחרור', 'amount': 1, 'cost': 15},
                    {'code': '5', 'name': 'שארים', 'amount': 8000, 'cost': 22},
                    {'code': '6', 'name': 'סיעוד', 'amount': 5500, 'cost': 30},
                ],
            }]),
            'recommendations': [
                {'title': 'סקירת כיסויים ביטוחיים', 'description': 'מומלץ לבדוק התאמת הכיסויים לצרכים'},
            ],
        }
        pdf_bytes = build_report_pdf_bytes(summary)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        from pypdf import PdfReader
        pdf_text = '\n'.join(
            (page.extract_text() or '') for page in PdfReader(io.BytesIO(pdf_bytes)).pages
        )
        for token in ('ביטוח חיים', 'אבדן כושר עבודה', 'שחרור', 'שארים', 'סיעוד', '400,000', '123456782'):
            self.assertTrue(
                token in pdf_text or bidi_text(token, rtl=True) in pdf_text,
                msg=f'missing {token}',
            )
        self.assertTrue('המלצות היועץ' in pdf_text or bidi_text('המלצות היועץ', rtl=True) in pdf_text)
        self.assertTrue('ישראל ישראלי' in pdf_text or bidi_text('ישראל ישראלי', rtl=True) in pdf_text)
        self.assertIn('________________', pdf_text)

        csv_text = build_report_csv_bytes(summary).decode('utf-8')
        self.assertIn('הכיסויים והעלויות שלך', csv_text)
        self.assertIn('400000', csv_text)
        self.assertIn('סיעוד', csv_text)


if __name__ == '__main__':
    unittest.main()
