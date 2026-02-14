#!/usr/bin/env python3
"""
Test Suite for AI Risk & Reports Analysis Service
=================================================

This test suite demonstrates the full functionality of the AI-powered
risk and reports analysis system, including:

1. Multi-language detection (Hebrew, English, etc.)
2. Data type classification (Insurance, Investment, Risk, Savings)
3. Pattern recognition and anomaly detection
4. Risk scoring and factor extraction
5. Automated report generation with charts
6. Personalized recommendations

Run with: python -m pytest tests/test_ai_risk_reports.py -v
Or directly: python tests/test_ai_risk_reports.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
from datetime import datetime

from services.ai_risk_reports_service import (
    AIRiskReportsService,
    LanguageDetector,
    DataClassifier,
    DataType,
    ChartType,
    Priority,
    Severity,
    get_ai_reports_service,
    init_ai_reports_service
)


class TestLanguageDetector(unittest.TestCase):
    """Test language detection capabilities"""
    
    def test_english_detection(self):
        """Detect English text"""
        text = "This is a policy document for insurance coverage with premium payments."
        lang, name, confidence = LanguageDetector.detect(text)
        self.assertEqual(lang, 'english')
        self.assertIn('English', name)
        self.assertGreater(confidence, 0.3)
    
    def test_hebrew_detection(self):
        """Detect Hebrew text"""
        text = "זה מסמך פוליסת ביטוח עם פרטי כיסוי ופרמיה חודשית של לקוח"
        lang, name, confidence = LanguageDetector.detect(text)
        self.assertEqual(lang, 'hebrew')
        self.assertIn('Hebrew', name)
        self.assertGreater(confidence, 0.3)
    
    def test_arabic_detection(self):
        """Detect Arabic text"""
        text = "هذه وثيقة تأمين تحتوي على تفاصيل التغطية والقسط الشهري"
        lang, name, confidence = LanguageDetector.detect(text)
        self.assertEqual(lang, 'arabic')
        self.assertIn('Arabic', name)
    
    def test_mixed_language(self):
        """Handle mixed language text"""
        text = "Policy פוליסה number 12345 מספר"
        lang, name, confidence = LanguageDetector.detect(text)
        # Should detect primary language
        self.assertIn(lang, ['english', 'hebrew'])
    
    def test_empty_text(self):
        """Handle empty or short text"""
        lang, name, confidence = LanguageDetector.detect("")
        self.assertEqual(lang, 'english')  # Default
        self.assertEqual(confidence, 0.5)


class TestDataClassifier(unittest.TestCase):
    """Test data type classification"""
    
    def test_insurance_classification(self):
        """Classify insurance data"""
        columns = ['policy_number', 'coverage_amount', 'premium', 'claim_status']
        sample_data = [
            {'policy_number': 'POL-001', 'coverage_amount': 100000, 'premium': 500, 'claim_status': 'none'}
        ]
        data_type, confidence = DataClassifier.classify(columns, sample_data)
        self.assertEqual(data_type, DataType.INSURANCE)
        self.assertGreater(confidence, 0.4)
    
    def test_investment_classification(self):
        """Classify investment data"""
        columns = ['portfolio_id', 'stock_name', 'yield', 'return', 'asset_value']
        sample_data = [
            {'portfolio_id': 'INV-001', 'stock_name': 'AAPL', 'yield': 2.5, 'return': 12.3, 'asset_value': 50000}
        ]
        data_type, confidence = DataClassifier.classify(columns, sample_data)
        self.assertEqual(data_type, DataType.INVESTMENT)
    
    def test_risk_classification(self):
        """Classify risk data"""
        columns = ['risk_score', 'exposure', 'probability', 'impact', 'mitigation']
        sample_data = [
            {'risk_score': 75, 'exposure': 'high', 'probability': 0.3, 'impact': 'severe', 'mitigation': 'planned'}
        ]
        data_type, confidence = DataClassifier.classify(columns, sample_data)
        self.assertEqual(data_type, DataType.RISK)
    
    def test_hebrew_insurance_classification(self):
        """Classify Hebrew insurance data"""
        columns = ['מספר_פוליסה', 'סכום_כיסוי', 'פרמיה', 'סטטוס_תביעה']
        sample_data = [
            {'מספר_פוליסה': 'POL-001', 'סכום_כיסוי': 100000, 'פרמיה': 500, 'סטטוס_תביעה': 'אין'}
        ]
        data_type, confidence = DataClassifier.classify(columns, sample_data)
        self.assertEqual(data_type, DataType.INSURANCE)


class TestFileProcessing(unittest.TestCase):
    """Test file parsing capabilities"""
    
    def setUp(self):
        """Initialize service for tests"""
        self.service = init_ai_reports_service()
    
    def test_csv_parsing_english(self):
        """Parse English CSV file"""
        csv_content = b"""policy_number,coverage,premium,status
POL-001,100000,500,active
POL-002,200000,750,active
POL-003,150000,600,pending"""
        
        result = self.service.parse_file('test.csv', csv_content, 'csv')
        
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['row_count'], 3)
        self.assertEqual(result['column_count'], 4)
        self.assertIn('policy_number', result['parsed_data']['columns'])
    
    def test_csv_parsing_hebrew(self):
        """Parse Hebrew CSV file with UTF-8 encoding"""
        csv_content = """מספר_פוליסה,סכום_כיסוי,פרמיה,סטטוס
POL-001,100000,500,פעיל
POL-002,200000,750,פעיל
POL-003,150000,600,ממתין""".encode('utf-8')
        
        result = self.service.parse_file('test_hebrew.csv', csv_content, 'csv')
        
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['row_count'], 3)
        self.assertIn('מספר_פוליסה', result['parsed_data']['columns'])
    
    def test_semicolon_delimiter(self):
        """Parse CSV with semicolon delimiter"""
        csv_content = b"""name;amount;date
John;1000;2024-01-15
Jane;2000;2024-02-20"""
        
        result = self.service.parse_file('test.csv', csv_content, 'csv')
        
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(result['parsed_data']['delimiter'], ';')
    
    def test_encoding_detection(self):
        """Test encoding detection for different encodings"""
        # UTF-8 with BOM
        utf8_bom = b'\xef\xbb\xbf' + b'name,value\ntest,100'
        encoding = self.service._detect_encoding(utf8_bom)
        self.assertEqual(encoding, 'utf-8-sig')


class TestAIAnalysis(unittest.TestCase):
    """Test AI analysis capabilities"""
    
    def setUp(self):
        """Initialize service and create test document"""
        self.service = init_ai_reports_service()
        
        # Create test document
        csv_content = b"""policy_number,coverage_amount,premium,claim_count,risk_score
POL-001,100000,500,0,25
POL-002,200000,750,1,45
POL-003,150000,600,0,30
POL-004,500000,1500,3,85
POL-005,75000,350,0,20"""
        
        self.parse_result = self.service.parse_file('test_insurance.csv', csv_content, 'csv')
        self.doc_id = self.parse_result['document_id']
    
    def test_analysis_execution(self):
        """Run analysis and verify results"""
        analysis = self.service.analyze(self.doc_id)
        
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.document_id, self.doc_id)
        self.assertEqual(analysis.language, 'english')
        self.assertEqual(analysis.data_classification, DataType.INSURANCE)
    
    def test_risk_score_calculation(self):
        """Verify risk score is calculated"""
        analysis = self.service.analyze(self.doc_id)
        
        self.assertGreaterEqual(analysis.risk_score, 0)
        self.assertLessEqual(analysis.risk_score, 100)
    
    def test_factor_extraction(self):
        """Verify factors are extracted"""
        analysis = self.service.analyze(self.doc_id)
        
        self.assertGreater(len(analysis.extracted_factors), 0)
        
        # Check factor structure
        for factor in analysis.extracted_factors:
            self.assertIsNotNone(factor.name)
            self.assertIsNotNone(factor.value)
            self.assertGreaterEqual(factor.importance, 0)
            self.assertLessEqual(factor.importance, 1)
    
    def test_pattern_detection(self):
        """Verify patterns are detected"""
        analysis = self.service.analyze(self.doc_id)
        
        # Should find some patterns in the data
        self.assertIsInstance(analysis.patterns_found, list)
    
    def test_anomaly_detection(self):
        """Verify anomalies are detected"""
        analysis = self.service.analyze(self.doc_id)
        
        # The POL-004 with high coverage and risk score should be flagged
        self.assertIsInstance(analysis.anomalies, list)
    
    def test_key_metrics_extraction(self):
        """Verify key metrics are extracted"""
        analysis = self.service.analyze(self.doc_id)
        
        self.assertIn('total_records', analysis.key_metrics)
        self.assertEqual(analysis.key_metrics['total_records'], 5)
    
    def test_summary_generation(self):
        """Verify summary is generated"""
        analysis = self.service.analyze(self.doc_id)
        
        self.assertIsNotNone(analysis.summary)
        self.assertGreater(len(analysis.summary), 20)


class TestReportGeneration(unittest.TestCase):
    """Test report generation capabilities"""
    
    def setUp(self):
        """Initialize service, create document, and run analysis"""
        self.service = init_ai_reports_service()
        
        csv_content = b"""policy_number,coverage_amount,premium,claim_count
POL-001,100000,500,0
POL-002,200000,750,1
POL-003,150000,600,0"""
        
        parse_result = self.service.parse_file('report_test.csv', csv_content, 'csv')
        self.analysis = self.service.analyze(parse_result['document_id'])
    
    def test_report_generation(self):
        """Generate report from analysis"""
        report = self.service.generate_report(self.analysis.id)
        
        self.assertIsNotNone(report)
        self.assertEqual(report.analysis_id, self.analysis.id)
        self.assertIsNotNone(report.title)
    
    def test_report_sections(self):
        """Verify report has sections"""
        report = self.service.generate_report(self.analysis.id)
        
        self.assertGreater(len(report.sections), 0)
        
        # Check section structure
        for section in report.sections:
            self.assertIsNotNone(section.title)
            self.assertIsNotNone(section.content)
    
    def test_report_charts(self):
        """Verify report has charts"""
        report = self.service.generate_report(self.analysis.id)
        
        self.assertGreater(len(report.charts), 0)
        
        # Check chart structure
        for chart in report.charts:
            self.assertIsInstance(chart.type, ChartType)
            self.assertIsNotNone(chart.title)
            self.assertIsNotNone(chart.data)
    
    def test_report_recommendations(self):
        """Verify report has recommendations"""
        report = self.service.generate_report(self.analysis.id)
        
        self.assertGreater(len(report.recommendations), 0)
        
        # Check recommendation structure
        for rec in report.recommendations:
            self.assertIsNotNone(rec.id)
            self.assertIsNotNone(rec.title)
            self.assertIsNotNone(rec.description)
            self.assertIsInstance(rec.priority, Priority)
            self.assertGreater(len(rec.action_items), 0)
    
    def test_language_override(self):
        """Test language override in report generation"""
        report_en = self.service.generate_report(self.analysis.id, 'english')
        report_he = self.service.generate_report(self.analysis.id, 'hebrew')
        
        self.assertEqual(report_en.language, 'english')
        self.assertEqual(report_he.language, 'hebrew')
        
        # Titles should be different
        self.assertNotEqual(report_en.title, report_he.title)


class TestPensionAffiliatedReportGeneration(unittest.TestCase):
    """Regression tests for pension-affiliated table/chart generation"""

    def setUp(self):
        self.service = init_ai_reports_service()
        csv_content = b"""policy_number,coverage_amount,premium,savings_amount,investment_amount,provider_name,product_type,status,employer_name,period
POL-001,100000,500,10000,5000,Phoenix,Managers,Active,SunFood,2022-10
POL-002,150000,620,3000,2000,Ayalon,Basic,Active,SunFood,2022-11"""
        parse_result = self.service.parse_file('pension_seed.csv', csv_content, 'csv')
        self.doc_id = parse_result['document_id']
        self.analysis = self.service.analyze(self.doc_id)

        # Inject pension-style parsed data to trigger Mislaka-affiliated path.
        self.service.documents[self.doc_id]['parsed_data']['pension_data'] = {
            'accounts': [
                {
                    'policy_number': '6,962,791,015',
                    'provider': 'הפניקס',
                    'product_type_name': 'מנהלים ושכירים',
                    'status': 'פעיל',
                    'total_balance': 214697,
                    'savings_balance': 111400,
                    'severance_balance': 103297,
                    'management_fee_savings': 0.5,
                    'management_fee_deposits': 3.0,
                    'death_coverage': 1077601,
                    'disability_coverage': 15000,
                    'employer_name': 'סאן פוד טרייד 2016 בע"מ',
                    'section14': True,
                    'start_date': '2018-02-01',
                },
                {
                    'policy_number': '13272595',
                    'provider': 'איילון',
                    'product_type_name': 'ביטוח יסודי',
                    'status': 'פעיל',
                    'total_balance': 0,
                    'savings_balance': 1200,
                    'investment_balance': 800,
                    'severance_balance': 500,
                    'death_coverage': 2091908,
                    'employer_name': 'סאן פוד טרייד 2016 בע"מ',
                    'section14': False,
                    'start_date': '2022-07-01',
                },
            ],
            'contributions': [
                {
                    'period': '2022-10',
                    'employer_name': 'סאן פוד טרייד 2016 בע"מ',
                    'employee_amount': 1200,
                    'employer_amount': 1300,
                    'severance_amount': 1666,
                    'total_amount': 4166,
                }
            ],
            'totals': {
                'total_balance': 217197,
                'total_savings': 112600,
                'total_investments': 800,
                'total_severance': 103797,
                'account_count': 2,
                'provider_count': 2,
                'section14_coverage': True,
            },
            'employers': [{'name': 'סאן פוד טרייד 2016 בע"מ'}],
        }

    def test_generate_report_with_pension_data_has_affiliated_tables(self):
        report = self.service.generate_report(self.analysis.id, language='hebrew')
        titles = [section.title for section in report.sections]

        self.assertTrue(any('סטטוס פוליסות' in title for title in titles))
        self.assertTrue(any('מפת שיוכים' in title for title in titles))

        table_sections = [section for section in report.sections if section.data_table]
        self.assertGreater(len(table_sections), 0)
        self.assertTrue(
            any(
                isinstance(section.data_table, dict) and
                isinstance(section.data_table.get('rows'), list) and
                section.data_table.get('rows')
                for section in table_sections
            )
        )

    def test_generate_report_with_pension_data_charts_regression(self):
        # Regression for analysis.language_code typo in pension chart generation.
        report = self.service.generate_report(self.analysis.id, language='hebrew')
        self.assertGreater(len(report.charts), 0)
        self.assertTrue(any(chart.type in [ChartType.BAR, ChartType.PIE, ChartType.DOUGHNUT, ChartType.GAUGE] for chart in report.charts))
        self.assertTrue(
            any(
                ('מצטברת' in chart.title) or ('Cumulative' in chart.title)
                for chart in report.charts
            )
        )

    def test_policy_balance_cumulative_and_policy_number_normalization(self):
        report = self.service.generate_report(self.analysis.id, language='hebrew')
        status_section = next(
            (section for section in report.sections if 'סטטוס פוליסות' in section.title),
            None
        )
        self.assertIsNotNone(status_section)
        rows = status_section.data_table.get('rows', [])
        self.assertGreaterEqual(len(rows), 2)

        self.assertEqual(rows[0].get('מספר פוליסה'), '6962791015')
        self.assertEqual(rows[0].get('יתרה'), 214697)
        self.assertEqual(rows[0].get('יתרה מצטברת'), 214697)

        # Fallback balance = savings + investment + severance when total_balance is missing/zero.
        self.assertEqual(rows[1].get('יתרה'), 2500)
        self.assertEqual(rows[1].get('יתרה מצטברת'), 217197)

    def test_uploaded_all_rows_table_and_policy_cumulative_section(self):
        report = self.service.generate_report(self.analysis.id, language='hebrew')

        full_data_section = next(
            (section for section in report.sections if '📊 נתונים שחולצו' in section.title),
            None
        )
        self.assertIsNotNone(full_data_section)
        self.assertIn('רשומות', full_data_section.title)
        full_rows = full_data_section.data_table.get('rows', [])
        self.assertEqual(len(full_rows), 2)

        cumulative_section = next(
            (section for section in report.sections if 'חישוב מצטבר' in section.title),
            None
        )
        self.assertIsNotNone(cumulative_section)
        cumulative_rows = cumulative_section.data_table.get('rows', [])
        self.assertEqual(len(cumulative_rows), 2)
        self.assertEqual(cumulative_rows[0].get('סכום חסכונות'), 10000)
        self.assertEqual(cumulative_rows[0].get('סכום השקעות'), 5000)
        self.assertEqual(cumulative_rows[0].get('יצרנים'), 'Phoenix')
        self.assertEqual(cumulative_rows[0].get('מוצרים/מסלולים'), 'Managers')
        self.assertEqual(cumulative_rows[0].get('יתרה מחושבת לפוליסה'), 15000)
        self.assertEqual(cumulative_rows[0].get('יתרה מצטברת'), 15000)
        self.assertEqual(cumulative_rows[1].get('יתרה מצטברת'), 20000)


class TestHebrewWorkflow(unittest.TestCase):
    """Test complete workflow with Hebrew data"""
    
    def setUp(self):
        """Initialize service"""
        self.service = init_ai_reports_service()
    
    def test_hebrew_insurance_workflow(self):
        """Complete workflow with Hebrew insurance data"""
        # Hebrew CSV content with more Hebrew text to ensure detection
        csv_content = """מספר_פוליסה,סוג_ביטוח,סכום_כיסוי,פרמיה_חודשית,סטטוס_תביעה,ציון_סיכון
פוליסה_ראשונה,ביטוח_חיים,100000,450,ללא_תביעה,נמוך
פוליסה_שניה,ביטוח_בריאות,250000,850,בטיפול,בינוני
פוליסה_שלישית,ביטוח_רכב,180000,620,אושר,נמוך
פוליסה_רביעית,ביטוח_דירה,500000,1800,נדחה,גבוה
פוליסה_חמישית,ביטוח_נסיעות,120000,480,ללא_תביעה,נמוך""".encode('utf-8')
        
        # 1. Parse file
        parse_result = self.service.parse_file('ביטוח_לקוחות.csv', csv_content, 'csv')
        self.assertEqual(parse_result['status'], 'completed')
        self.assertEqual(parse_result['row_count'], 5)
        
        # 2. Analyze
        analysis = self.service.analyze(parse_result['document_id'])
        self.assertEqual(analysis.language, 'hebrew')
        self.assertEqual(analysis.data_classification, DataType.INSURANCE)
        
        # 3. Generate Hebrew report
        report = self.service.generate_report(analysis.id)
        self.assertEqual(report.language, 'hebrew')
        
        # Verify Hebrew title
        self.assertIn('ביטוח', report.title)
        
        # Verify recommendations in Hebrew
        self.assertGreater(len(report.recommendations), 0)
    
    def test_hebrew_investment_workflow(self):
        """Complete workflow with Hebrew investment data"""
        csv_content = """מזהה_תיק,שם_נכס,תשואה,סיכון,שווי
INV-001,מניות_טכנולוגיה,12.5,גבוה,50000
INV-002,אגרות_חוב,4.2,נמוך,100000
INV-003,נדלן,8.1,בינוני,200000""".encode('utf-8')
        
        # Parse
        parse_result = self.service.parse_file('תיק_השקעות.csv', csv_content, 'csv')
        self.assertEqual(parse_result['status'], 'completed')
        
        # Analyze
        analysis = self.service.analyze(parse_result['document_id'])
        self.assertEqual(analysis.language, 'hebrew')
        self.assertEqual(analysis.data_classification, DataType.INVESTMENT)
        
        # Generate report
        report = self.service.generate_report(analysis.id)
        self.assertIn('השקעות', report.title)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def setUp(self):
        """Initialize service"""
        self.service = init_ai_reports_service()
    
    def test_empty_file(self):
        """Handle empty file"""
        csv_content = b""
        result = self.service.parse_file('empty.csv', csv_content, 'csv')
        # Should complete but with no rows
        self.assertEqual(result['row_count'], 0)
    
    def test_single_row(self):
        """Handle file with single data row"""
        csv_content = b"name,value\ntest,100"
        result = self.service.parse_file('single.csv', csv_content, 'csv')
        self.assertEqual(result['row_count'], 1)
        
        # Should be able to analyze
        analysis = self.service.analyze(result['document_id'])
        self.assertIsNotNone(analysis)
    
    def test_missing_document(self):
        """Handle missing document ID"""
        with self.assertRaises(ValueError):
            self.service.analyze('nonexistent-doc-id')
    
    def test_missing_analysis(self):
        """Handle missing analysis ID"""
        with self.assertRaises(ValueError):
            self.service.generate_report('nonexistent-analysis-id')
    
    def test_numeric_with_currency(self):
        """Handle numeric values with currency symbols"""
        csv_content = """item,amount
Premium,$500
Coverage,$100000
Claim,1234.56""".encode('utf-8')
        
        result = self.service.parse_file('currency.csv', csv_content, 'csv')
        analysis = self.service.analyze(result['document_id'])
        
        # Should handle currency parsing
        self.assertIsNotNone(analysis.key_metrics)


class TestServiceSingleton(unittest.TestCase):
    """Test service singleton pattern"""
    
    def test_singleton_instance(self):
        """Verify singleton returns same instance"""
        service1 = get_ai_reports_service()
        service2 = get_ai_reports_service()
        self.assertIs(service1, service2)
    
    def test_init_creates_new(self):
        """Verify init creates fresh instance"""
        service1 = get_ai_reports_service()
        service2 = init_ai_reports_service()
        # After init, get should return the new instance
        service3 = get_ai_reports_service()
        self.assertIs(service2, service3)


class TestJSONSerialization(unittest.TestCase):
    """Test JSON serialization of results"""
    
    def setUp(self):
        """Initialize service with test data"""
        self.service = init_ai_reports_service()
        csv_content = b"name,value\ntest,100"
        result = self.service.parse_file('json_test.csv', csv_content, 'csv')
        self.analysis = self.service.analyze(result['document_id'])
        self.report = self.service.generate_report(self.analysis.id)
    
    def test_analysis_serialization(self):
        """Verify analysis can be serialized to JSON"""
        analysis_dict = self.service.to_dict(self.analysis)
        json_str = json.dumps(analysis_dict, default=str)
        
        self.assertIsInstance(json_str, str)
        parsed = json.loads(json_str)
        self.assertEqual(parsed['id'], self.analysis.id)
    
    def test_report_serialization(self):
        """Verify report can be serialized to JSON"""
        report_dict = self.service.to_dict(self.report)
        json_str = json.dumps(report_dict, default=str)
        
        self.assertIsInstance(json_str, str)
        parsed = json.loads(json_str)
        self.assertEqual(parsed['id'], self.report.id)
        self.assertIn('sections', parsed)
        self.assertIn('charts', parsed)
        self.assertIn('recommendations', parsed)


def run_demo():
    """Run a demonstration of the AI Risk & Reports service"""
    print("\n" + "="*70)
    print("     AI RISK & REPORTS ANALYSIS - DEMONSTRATION")
    print("="*70 + "\n")
    
    service = init_ai_reports_service()
    
    # Demo 1: English Insurance Data
    print("📊 Demo 1: Analyzing English Insurance Data")
    print("-" * 50)
    
    insurance_csv = b"""policy_number,coverage_amount,monthly_premium,claims_count,risk_score
POL-2024-001,250000,850,0,25
POL-2024-002,500000,1500,2,65
POL-2024-003,175000,625,1,40
POL-2024-004,1000000,3200,5,95
POL-2024-005,300000,950,0,30"""
    
    result = service.parse_file('insurance_portfolio.csv', insurance_csv, 'csv')
    print(f"✓ Parsed: {result['filename']} ({result['row_count']} records)")
    
    analysis = service.analyze(result['document_id'])
    print(f"✓ Language: {analysis.language_name}")
    print(f"✓ Data Type: {analysis.data_classification.value}")
    print(f"✓ Risk Score: {analysis.risk_score:.1f}/100")
    print(f"✓ Confidence: {analysis.confidence:.0%}")
    
    report = service.generate_report(analysis.id)
    print(f"✓ Report: {report.title}")
    print(f"✓ Sections: {len(report.sections)}")
    print(f"✓ Charts: {len(report.charts)}")
    print(f"✓ Recommendations: {len(report.recommendations)}")
    
    # Demo 2: Hebrew Insurance Data
    print("\n" + "📊 Demo 2: Analyzing Hebrew Insurance Data (עברית)")
    print("-" * 50)
    
    hebrew_csv = """מספר_פוליסה,סכום_ביטוח,פרמיה_חודשית,תביעות,ציון_סיכון
POL-001,250000,850,0,25
POL-002,500000,1500,2,65
POL-003,175000,625,1,40
POL-004,1000000,3200,5,95
POL-005,300000,950,0,30""".encode('utf-8')
    
    result = service.parse_file('פוליסות_ביטוח.csv', hebrew_csv, 'csv')
    print(f"✓ Parsed: {result['filename']} ({result['row_count']} records)")
    
    analysis = service.analyze(result['document_id'])
    print(f"✓ Language: {analysis.language_name}")
    print(f"✓ Data Type: {analysis.data_classification.value}")
    print(f"✓ Risk Score: {analysis.risk_score:.1f}/100")
    
    report = service.generate_report(analysis.id)
    print(f"✓ Report Title: {report.title}")
    
    # Show sample recommendation
    if report.recommendations:
        rec = report.recommendations[0]
        print(f"\n💡 Top Recommendation:")
        print(f"   [{rec.priority.value.upper()}] {rec.title}")
        print(f"   {rec.description}")
    
    print("\n" + "="*70)
    print("     DEMONSTRATION COMPLETE")
    print("="*70 + "\n")


if __name__ == '__main__':
    # Check for demo mode
    if '--demo' in sys.argv:
        run_demo()
    else:
        # Run tests
        print("\nRunning AI Risk & Reports Analysis Test Suite...\n")
        unittest.main(verbosity=2)
