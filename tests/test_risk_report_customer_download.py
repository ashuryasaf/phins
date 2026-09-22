"""Customer-facing risk-report download: assessment only, no completeness dump."""

from __future__ import annotations

import io
import unittest

from services.ai_risk_reports_service import init_ai_reports_service
from services.risk_reports.pdf_export import (
    bidi_text,
    build_report_csv_bytes,
    build_report_pdf_bytes,
    customer_report_title,
    is_non_assessment_section_title,
    prepare_customer_download_sections,
    strip_completeness_copy,
)


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


if __name__ == '__main__':
    unittest.main()
