"""Official Swiftness / Mislaka field extraction — identity, accumulation, severance.

These fixtures follow the affiliated-file layout savers receive from
https://www.swiftness.co.il (namespaced holdings XML, pitzuim XML, and a
Hebrew "דוח מידע מרוכז" table with ת.ז / סה״כ צבירה / פיצויים).
"""

import io
import zipfile
import unittest

from services.pension.agent import PensionDataAgent, get_pension_agent
from services.pension.cache import ParseResultCache
from services.pension.schema import map_hebrew_column, normalize_hebrew_header
from services.ai_risk_reports_service import init_ai_reports_service  # noqa: E402


class _NoDb:
    def __enter__(self):
        raise RuntimeError('no database in this test')

    def __exit__(self, *exc):
        return False


def _agent():
    return PensionDataAgent(
        parse_cache=ParseResultCache(max_entries=4, enabled=False, db_factory=lambda: _NoDb())
    )


OFFICIAL_HOLDINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/holdings">
  <KoteretKovetz>
    <SUG-MIMSHAK>1</SUG-MIMSHAK>
    <MISPAR-GIRSAT-XML>009</MISPAR-GIRSAT-XML>
  </KoteretKovetz>
  <YeshutYatzran>
    <SHEM-YATZRAN>מגדל</SHEM-YATZRAN>
    <KOD-MEZAHE-YATZRAN>1</KOD-MEZAHE-YATZRAN>
    <Mutzarim>
      <Mutzar>
        <SUG-MUTZAR>1</SUG-MUTZAR>
        <SHEM-MUTZAR>קרן פנסיה מקיפה</SHEM-MUTZAR>
        <NetuneiMutzar>
          <YeshutLakoach>
            <SUG-ZIHUI-LAKOACH>3</SUG-ZIHUI-LAKOACH>
            <MISPAR-ZIHUI-LAKOACH>123456782</MISPAR-ZIHUI-LAKOACH>
            <SHEM-PRATI>ישראל</SHEM-PRATI>
            <SHEM-MISHPACHA>ישראלי</SHEM-MISHPACHA>
            <TAARICH-LEYDA>19781111</TAARICH-LEYDA>
          </YeshutLakoach>
          <HeshbonotOPolisot>
            <HeshbonOPolisa>
              <MISPAR-POLISA-O-HESHBON>POL-HOLD-1</MISPAR-POLISA-O-HESHBON>
              <STATUS-POLISA-O-CHESHBON>1</STATUS-POLISA-O-CHESHBON>
              <TOTAL-CHISACHON-MTZBR>88000.50</TOTAL-CHISACHON-MTZBR>
              <YITRAT-PITZUIM>12000</YITRAT-PITZUIM>
              <Yitrot>
                <Yitra>
                  <KOD-SUG-HAFRASHA>1</KOD-SUG-HAFRASHA>
                  <SCHUM-TZVIRA>50000</SCHUM-TZVIRA>
                </Yitra>
                <Yitra>
                  <KOD-SUG-HAFRASHA>2</KOD-SUG-HAFRASHA>
                  <SCHUM-TZVIRA>26000.50</SCHUM-TZVIRA>
                </Yitra>
                <Yitra>
                  <KOD-SUG-HAFRASHA>3</KOD-SUG-HAFRASHA>
                  <SCHUM-TZVIRA>12000</SCHUM-TZVIRA>
                </Yitra>
              </Yitrot>
            </HeshbonOPolisa>
          </HeshbonotOPolisot>
        </NetuneiMutzar>
      </Mutzar>
    </Mutzarim>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')


SEVERANCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/pitzuim">
  <KoteretKovetz>
    <SUG-MIMSHAK>17</SUG-MIMSHAK>
  </KoteretKovetz>
  <YeshutLakoach>
    <MISPAR-ZIHUI-LAKOACH>123456782</MISPAR-ZIHUI-LAKOACH>
    <SHEM-LAKOACH>ישראל ישראלי</SHEM-LAKOACH>
  </YeshutLakoach>
  <NetuneiPitzuim>
    <SHEM-MAASIK>מעסיק לדוגמה</SHEM-MAASIK>
    <SACH-PITZUIM>4500</SACH-PITZUIM>
    <SEIF-14>1</SEIF-14>
  </NetuneiPitzuim>
</Mimshak>
""".encode('utf-8')


COMPONENT_AMOUNT_HOLDINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/holdings">
  <YeshutLakoach>
    <MISPAR-ZIHUI-LAKOACH>123456782</MISPAR-ZIHUI-LAKOACH>
  </YeshutLakoach>
  <YeshutYatzran>
    <SHEM-YATZRAN>מגדל</SHEM-YATZRAN>
    <Mutzar>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-WITH-TOTAL</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>100000</TOTAL-CHISACHON-MTZBR>
        <Yitra>
          <KOD-SUG-HAFRASHA>1</KOD-SUG-HAFRASHA>
          <SACH-YITRA>70000</SACH-YITRA>
        </Yitra>
        <Yitra>
          <KOD-SUG-HAFRASHA>3</KOD-SUG-HAFRASHA>
          <SACH-YITRA>30000</SACH-YITRA>
        </Yitra>
      </HeshbonOPolisa>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-COMPONENTS-ONLY</MISPAR-POLISA-O-HESHBON>
        <Yitra>
          <KOD-SUG-HAFRASHA>1</KOD-SUG-HAFRASHA>
          <ERECH-PIDYON>40000</ERECH-PIDYON>
        </Yitra>
        <Yitra>
          <KOD-SUG-HAFRASHA>3</KOD-SUG-HAFRASHA>
          <ERECH-PIDYON>10000</ERECH-PIDYON>
        </Yitra>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')


COVER_HOLDINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/holdings">
  <YeshutYatzran>
    <SHEM-YATZRAN>מגדל</SHEM-YATZRAN>
    <Mutzar>
      <SUG-MUTZAR>1</SUG-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-COVER-1</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>50000</TOTAL-CHISACHON-MTZBR>
        <KISUY-MAVET>400000</KISUY-MAVET>
        <DMEY-BITUACH-MAVET>85</DMEY-BITUACH-MAVET>
        <KISUY-OVDAN-KOSHER>12000</KISUY-OVDAN-KOSHER>
        <DMEY-BITUACH-AKW>40</DMEY-BITUACH-AKW>
        <Kisuyim>
          <Kisuy>
            <KOD-SUG-KISUY>4</KOD-SUG-KISUY>
            <SHEM-KISUY>שחרור</SHEM-KISUY>
            <SCHUM-KISUY>1</SCHUM-KISUY>
            <DMEY-BITUACH>15</DMEY-BITUACH>
          </Kisuy>
          <Kisuy>
            <KOD-SUG-KISUY>5</KOD-SUG-KISUY>
            <SHEM-KISUY>שארים</SHEM-KISUY>
            <SCHUM-KISUY>8000</SCHUM-KISUY>
            <DMEY-BITUACH>22</DMEY-BITUACH>
          </Kisuy>
          <Kisuy>
            <KOD-SUG-KISUY>6</KOD-SUG-KISUY>
            <SHEM-KISUY>סיעוד</SHEM-KISUY>
            <SCHUM-KISUY>5500</SCHUM-KISUY>
            <DMEY-BITUACH>30</DMEY-BITUACH>
          </Kisuy>
        </Kisuyim>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')


CONCENTRATED_CSV = (
    'שם מלא,ת.ז.,סה״כ צבירה,פיצויים,יצרן,מספר פוליסה,סוג מוצר\n'
    'ישראל ישראלי,123456782,"88,000.50",12000,מגדל,POL-HOLD-1,קרן פנסיה מקיפה\n'
).encode('utf-8')


class TestHebrewHeaderNormalization(unittest.TestCase):
    def test_gershayim_and_id_aliases_map_to_canonical_fields(self):
        self.assertEqual(normalize_hebrew_header('סה״כ צבירה'), 'סה"כ צבירה')
        self.assertEqual(normalize_hebrew_header('ת.ז.'), 'ת.ז')
        self.assertEqual(map_hebrew_column('סה״כ צבירה'), 'total_balance')
        self.assertEqual(map_hebrew_column('תעודת זהות'), 'id_number')
        self.assertEqual(map_hebrew_column('ת.ז'), 'id_number')
        self.assertEqual(map_hebrew_column('פיצויים'), 'severance_balance')
        self.assertEqual(map_hebrew_column('ביטוח חיים'), 'death_coverage')
        self.assertEqual(map_hebrew_column('סכום ביטוח למקרה מוות – חד פעמי'), 'death_lump_sum')
        self.assertEqual(map_hebrew_column('סכום ביטוח למקרה מוות - חד פעמי'), 'death_lump_sum')
        self.assertEqual(map_hebrew_column('סכום ביטוח למקרה מוות-חד פעמי'), 'death_lump_sum')
        self.assertNotEqual(map_hebrew_column('סכום ביטוח למקרה מוות – חד פעמי'), 'death_coverage')
        self.assertNotEqual(map_hebrew_column('סכום ביטוח למקרה מוות – חד פעמי'), 'total_balance')
        self.assertEqual(map_hebrew_column('אבדן כושר עבודה'), 'disability_coverage')
        self.assertEqual(map_hebrew_column('שחרור'), 'waiver_coverage')
        self.assertEqual(map_hebrew_column('שארים'), 'survivors_coverage')
        self.assertEqual(map_hebrew_column('סיעוד'), 'ltc_coverage')
        self.assertEqual(map_hebrew_column('עלות ביטוח חיים'), 'death_premium')
        self.assertEqual(map_hebrew_column('סה״כ חיסכון'), 'savings_balance')
        self.assertEqual(map_hebrew_column('יתרה'), 'balance')
        self.assertEqual(map_hebrew_column('יתרה כוללת'), 'total_balance')
        self.assertEqual(map_hebrew_column('תגמולים'), 'tagmulim_balance')
        self.assertEqual(map_hebrew_column('פרמיה ביטוח חיים'), 'death_premium')
        self.assertEqual(map_hebrew_column('פרמיה אבדן כושר'), 'disability_premium')
        self.assertEqual(map_hebrew_column('פרמיה שחרור'), 'waiver_premium')
        self.assertEqual(map_hebrew_column('פרמיה נכות'), 'invalidity_premium')
        self.assertEqual(map_hebrew_column('פרמיה שארים'), 'survivors_premium')
        self.assertEqual(map_hebrew_column('פרמיה סיעוד'), 'ltc_premium')
        self.assertEqual(map_hebrew_column('סה״כ פרמיה חודשית'), 'monthly_premium')
        self.assertEqual(map_hebrew_column('תאריך סטטוס'), 'status_date')
        self.assertEqual(map_hebrew_column('דמי ניהול מצבירה'), 'management_fee_savings')
        self.assertEqual(map_hebrew_column('דמי ניהול מהפקדה'), 'management_fee_deposits')
        self.assertEqual(map_hebrew_column('מסלול השקעה'), 'investment_track')
        self.assertEqual(map_hebrew_column('אחוז במסלול'), 'track_percent')
        self.assertEqual(map_hebrew_column('תשואה'), 'yield_rate')
        self.assertEqual(map_hebrew_column('תאריך נזילות'), 'liquidity_date')
        self.assertEqual(map_hebrew_column('הפקדה אחרונה'), 'last_deposit')
        self.assertEqual(map_hebrew_column('תאריך הפקדה אחרונה'), 'last_deposit_date')
        self.assertEqual(map_hebrew_column('סוג הפרשה'), 'contribution_type')


class TestOfficialMislakaXmlExtraction(unittest.TestCase):
    def setUp(self):
        self.agent = _agent()

    def test_namespaced_holdings_finds_id_accumulation_and_severance(self):
        data = self.agent._parse_mislaka_xml(OFFICIAL_HOLDINGS)
        self.assertEqual(data['client'].get('id_number'), '123456782')
        self.assertEqual(data['client'].get('first_name'), 'ישראל')
        self.assertEqual(len(data['accounts']), 1)
        account = data['accounts'][0]
        self.assertEqual(account['policy_number'], 'POL-HOLD-1')
        self.assertEqual(account['total_balance'], 88000.50)
        self.assertEqual(account['severance_balance'], 12000)
        self.assertEqual(account['provider'], 'מגדל')

    def test_uploaded_risk_covers_and_costs_are_parsed(self):
        data = self.agent._parse_mislaka_xml(COVER_HOLDINGS)
        account = data['accounts'][0]
        self.assertEqual(account['death_coverage'], 400000)
        self.assertEqual(account['death_premium'], 85)
        self.assertEqual(account['work_disability_coverage'], 12000)
        self.assertEqual(account['work_disability_premium'], 40)
        covers = account.get('risk_covers') or []
        names = {str(item.get('name')) for item in covers}
        self.assertIn('שחרור', names)
        self.assertIn('שארים', names)
        self.assertIn('סיעוד', names)
        by_name = {item['name']: item for item in covers}
        self.assertEqual(by_name['שחרור']['cost'], 15)
        self.assertEqual(by_name['שארים']['amount'], 8000)
        self.assertEqual(by_name['סיעוד']['cost'], 30)

    def test_yitra_component_amounts_do_not_replace_account_total(self):
        data = self.agent._parse_mislaka_xml(COMPONENT_AMOUNT_HOLDINGS)
        by_policy = {a['policy_number']: a for a in data['accounts']}
        self.assertEqual(by_policy['POL-WITH-TOTAL']['total_balance'], 100000)
        self.assertEqual(by_policy['POL-COMPONENTS-ONLY']['total_balance'], 50000)
        self.assertEqual(by_policy['POL-COMPONENTS-ONLY']['severance_balance'], 10000)

    def test_namespaced_severance_interface(self):
        data = self.agent._parse_mislaka_xml(SEVERANCE_XML)
        self.assertEqual(data['client'].get('id_number'), '123456782')
        self.assertEqual(data['severance'][0].get('total_severance'), 4500)
        self.assertTrue(data['severance'][0].get('section14'))

    def test_process_xml_enriches_totals(self):
        result = self.agent.process_xml_content(OFFICIAL_HOLDINGS)
        totals = result['data']['totals']
        self.assertEqual(totals['total_balance'], 88000.50)
        self.assertEqual(totals['total_severance'], 12000)
        self.assertIn('123456782', result['report'])


class TestSwiftnessAffiliatedShowcase(unittest.TestCase):
    """ZIP shaped like the last Swiftness Mislaka session: holdings + pitzuim + concentrated report."""

    def setUp(self):
        self.service = init_ai_reports_service()

    def _session_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('holdings_mivneachid.xml', OFFICIAL_HOLDINGS)
            zf.writestr('pitzuim.xml', SEVERANCE_XML)
            zf.writestr('doch_merukaz.csv', CONCENTRATED_CSV)
        return buf.getvalue()

    def test_csv_gershayim_headers_become_pension_data(self):
        parsed, _ = self.service.parse_content('doch_merukaz.csv', CONCENTRATED_CSV, 'csv')
        pension = parsed.get('pension_data') or {}
        self.assertEqual(pension.get('client', {}).get('id_number'), '123456782')
        self.assertEqual(pension.get('totals', {}).get('total_balance'), 88000.50)
        self.assertEqual(pension.get('totals', {}).get('total_severance'), 12000)

    def test_affiliated_zip_report_matches_uploaded_fields(self):
        parse_result = self.service.parse_file(
            'swiftness_last_session.zip',
            self._session_zip(),
            'zip',
            owner_id='CUST-OWNER-001',
            owner_role='customer',
        )
        self.assertEqual(parse_result['status'], 'completed')
        pension = parse_result['parsed_data']['pension_data']
        self.assertEqual(pension['client']['id_number'], '123456782')
        self.assertEqual(pension['totals']['total_balance'], 88000.50)
        self.assertEqual(pension['totals']['account_count'], 1)
        # Holdings פיצויים 12,000 plus the affiliated pitzuim row 4,500.
        self.assertEqual(pension['totals']['total_severance'], 16500.0)
        integrity = parse_result['parsed_data']['integrity']
        self.assertGreaterEqual(integrity['affiliated_files_processed'], 2)

        analysis = self.service.analyze(parse_result['document_id'])
        report = self.service.generate_report(analysis.id, language='hebrew')
        summary = report.metadata.get('savings_cover_id_summary', {})
        self.assertEqual(summary.get('customer_id'), '123456782')
        self.assertGreaterEqual(summary.get('total_savings') or 0, 88000.50)
        self.assertGreaterEqual(summary.get('total_severance') or 0, 12000)
        body = ' '.join(section.content or '' for section in report.sections)
        self.assertIn('123456782', body)
        self.assertTrue('צבירה' in body or 'פיצויים' in body)
        titles = ' | '.join(section.title or '' for section in report.sections)
        for banned in (
            'פרופיל נתונים',
            'Data Profile',
            'ניתוח סטטיסטי',
            'Statistical Analysis',
            'ניתוח מתאמים',
            'Correlation Analysis',
            'דפוסים ומגמות',
            'Patterns & Trends',
            'הערכת סיכון',
            'Risk Assessment',
            'מדדים מרכזיים',
            'Key Metrics',
            'מפת שיוכים',
            'Affiliation Mapping',
        ):
            self.assertNotIn(banned, titles)

        export_payload = self.service.build_report_download_summary(
            report_id=report.id,
            user_id='CUST-OWNER-001',
            user_role='customer',
        )
        self.assertTrue(export_payload.get('is_pension_data'))
        assessment = export_payload.get('pension_assessment') or {}
        self.assertEqual(assessment.get('client', {}).get('id_number'), '123456782')
        self.assertEqual(assessment.get('totals', {}).get('total_balance'), 88000.50)
        self.assertEqual(assessment.get('totals', {}).get('total_severance'), 16500.0)
        self.assertEqual(assessment.get('totals', {}).get('account_count'), 1)
        export_titles = [section.get('title') for section in export_payload.get('assessment_sections') or []]
        self.assertNotIn('פרופיל נתונים', export_titles)
        self.assertNotIn('Data Profile', export_titles)

        from pypdf import PdfReader
        from services.risk_reports.pdf_export import build_report_pdf_bytes
        pdf_bytes = build_report_pdf_bytes(export_payload)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        pdf_text = '\n'.join(
            (page.extract_text() or '') for page in PdfReader(io.BytesIO(pdf_bytes)).pages
        )
        self.assertIn('123456782', pdf_text)
        self.assertTrue('88000.50' in pdf_text or '88,000.50' in pdf_text)
        self.assertTrue('16,500.00' in pdf_text or '16500' in pdf_text)
        self.assertNotIn('Data Profile', pdf_text)
        self.assertNotIn('numeric_columns', pdf_text)
        self.assertNotIn('שלמות נתונים', pdf_text)
        self.assertNotIn('Data Integrity', pdf_text)
        self.assertNotIn('Data Completeness', pdf_text)
        self.assertNotIn('דו״ח ניתוח נתונים', pdf_text)
        self.assertNotIn('Data Analysis Report', pdf_text)
        self.assertNotIn('ID Validation', pdf_text)
        self.assertNotIn('תקינות מזהה', pdf_text)
        self.assertNotIn('integrity_issues', export_payload.get('savings_cover_id_summary') or {})
        self.assertEqual(export_payload.get('title'), 'ההערכה שלך')
        self.assertTrue(
            'ההערכה שלך' in pdf_text
            or 'הלש ךתרעהה' in pdf_text
            or 'Your Assessment' in pdf_text
        )
        self.assertIn('PHINS', pdf_text)
        chart_titles = [chart.get('title') for chart in export_payload.get('chart_summaries') or []]
        self.assertTrue(chart_titles)
        self.assertTrue(
            any('צבירה לפי יצרן' in str(title) or 'Savings by Provider' in str(title) or 'תגמולים' in str(title)
                or 'חיסכון מול כיסוי' in str(title)
                for title in chart_titles)
        )
        self.assertNotIn('כיסוי שדות זיהוי', chart_titles)
        from services.risk_reports.pdf_export import bidi_text
        chart_tokens = (
            'צבירה לפי יצרן',
            'Savings by Provider',
            'תגמולים מול פיצויים',
            'חיסכון מול כיסוי',
        )
        self.assertTrue(
            any(token in pdf_text for token in chart_tokens)
            or any(bidi_text(token, rtl=True) in pdf_text for token in chart_tokens)
        )


class TestMislakaAssessmentPdfHelpers(unittest.TestCase):
    def test_statistical_titles_are_classified(self):
        from services.risk_reports.pdf_export import (
            is_completeness_section_title,
            is_non_assessment_section_title,
            is_statistical_section_title,
        )
        self.assertTrue(is_statistical_section_title('פרופיל נתונים'))
        self.assertTrue(is_statistical_section_title('📊 Data Profile'))
        self.assertTrue(is_statistical_section_title('דו״ח ניתוח נתונים'))
        self.assertTrue(is_statistical_section_title('Data Analysis Report'))
        self.assertTrue(is_statistical_section_title('תוכן הנתונים שהועלו'))
        self.assertTrue(is_completeness_section_title('שלמות נתונים'))
        self.assertTrue(is_completeness_section_title('Data Integrity'))
        self.assertTrue(is_non_assessment_section_title('שלמות נתונים'))
        self.assertTrue(is_non_assessment_section_title('Affiliation Mapping Snapshot'))
        self.assertFalse(is_statistical_section_title('דו״ח ניתוח פנסיה וביטוח'))
        self.assertFalse(is_non_assessment_section_title('סה״כ צבירה ופיצויים'))
        self.assertFalse(is_non_assessment_section_title('הערכת הפנסיה והביטוח שלך'))


HOLDINGS_SPREADSHEET = (
    'מספר פוליסה,סוג מוצר,שם מוצר,יצרן,סטטוס,תאריך הצטרפות,תאריך נזילות,'
    'סה״כ חיסכון,תגמולים,פיצויים,יתרה,דמי ניהול מצבירה,דמי ניהול מהפקדה,'
    'הפקדה אחרונה,תאריך הפקדה אחרונה,מעסיק,סוג הפרשה,תאריך סטטוס,'
    'ביטוח חיים,פרמיה ביטוח חיים,אבדן כושר עבודה,פרמיה אבדן כושר,'
    'שחרור,פרמיה שחרור,נכות,פרמיה נכות,שארים,פרמיה שארים,סיעוד,פרמיה סיעוד,'
    'סה״כ פרמיה חודשית,מסלול השקעה,אחוז במסלול,תשואה\n'
    'POL-H,פוליסת חיסכון,מסלול כללי,הכשרה ביטוח,פעיל,01/01/2015,01/01/2030,'
    '420808.64,180000,90000,900000,0.6,1.5,2500,01/08/2026,מעסיק א,תגמולים,01/09/2026,'
    '500000,120,200000,40,10000,15,100000,25,80000,22,50000,30,252,מסלול מניות,60,7.2\n'
    'POL-H,פוליסת חיסכון,מסלול כללי,הכשרה ביטוח,פעיל,01/01/2015,01/01/2030,'
    '420808.64,180000,90000,900000,0.6,1.5,2500,01/08/2026,מעסיק א,תגמולים,01/09/2026,'
    '500000,120,200000,40,10000,15,100000,25,80000,22,50000,30,252,מסלול אגח,40,4.1\n'
    'POL-B,ביטוח סיכונים - חד פעמי,קופת גמל,מנורה,פעיל,01/06/2018,01/06/2028,'
    '10000,4000,2000,15000,0.3,1.0,500,01/08/2026,מעסיק ב,פיצויים,01/09/2026,'
    '0,0,0,0,0,0,0,0,0,0,0,0,0,מסלול כללי,100,3.0\n'
).encode('utf-8')


SLICE_SPREADSHEET = (
    'מספר פוליסה,יצרן,סה״כ חיסכון,מסלול השקעה\n'
    'POL-C,הכשרה ביטוח,200000.00,מסלול מניות\n'
    'POL-C,הכשרה ביטוח,220808.64,מסלול אגח\n'
).encode('utf-8')


class TestHoldingsSpreadsheetAccumulation(unittest.TestCase):
    """סה״כ חיסכון is צבירות. Track repeats count once. Covers stay separate."""

    def setUp(self):
        self.service = init_ai_reports_service()

    def test_repeated_track_savings_are_not_added_to_covers_or_balance(self):
        parsed, _ = self.service.parse_content('holdings.csv', HOLDINGS_SPREADSHEET, 'csv')
        pension = parsed.get('pension_data') or {}
        totals = pension.get('totals') or {}
        accounts = pension.get('accounts') or []
        self.assertEqual(len(accounts), 3)
        by_policy = {}
        for account in accounts:
            by_policy.setdefault(account['policy_number'], []).append(account)
        hachshara = by_policy['POL-H'][0]
        self.assertEqual(hachshara['provider'], 'הכשרה ביטוח')
        self.assertEqual(hachshara['savings_balance'], 420808.64)
        self.assertEqual(hachshara['tagmulim_balance'], 180000)
        self.assertEqual(hachshara['severance_balance'], 90000)
        self.assertEqual(hachshara['balance'], 900000)
        self.assertNotIn('total_balance', hachshara)
        self.assertEqual(hachshara['death_coverage'], 500000)
        self.assertEqual(hachshara['death_premium'], 120)
        self.assertEqual(hachshara['disability_premium'], 40)
        self.assertEqual(hachshara['monthly_premium'], 252)
        self.assertEqual(hachshara['status'], 'פעיל')
        self.assertEqual(hachshara['status_date'], '01/09/2026')
        self.assertEqual(hachshara['management_fee_savings'], 0.6)
        self.assertEqual(hachshara['management_fee_deposits'], 1.5)
        self.assertEqual(hachshara['liquidity_date'], '01/01/2030')
        self.assertEqual(hachshara['last_deposit'], 2500)
        self.assertEqual(hachshara['contribution_type'], 'תגמולים')
        self.assertEqual(hachshara['investment_track'], 'מסלול מניות')
        self.assertEqual(by_policy['POL-H'][1]['investment_track'], 'מסלול אגח')

        self.assertEqual(totals['total_balance'], 430808.64)
        self.assertEqual(totals['by_provider']['הכשרה ביטוח'], 420808.64)
        self.assertEqual(totals['by_provider']['מנורה'], 10000)
        self.assertEqual(totals['total_tagmulim'], 184000)
        self.assertEqual(totals['total_severance'], 92000)
        self.assertEqual(totals['total_yitra'], 915000)
        self.assertEqual(totals['account_count'], 2)
        self.assertLess(totals['total_balance'], totals['total_yitra'])

        analysis = self.service.analyze(
            self.service.parse_file(
                'holdings.csv', HOLDINGS_SPREADSHEET, 'csv',
                owner_id='CUST-OWNER-001', owner_role='customer',
            )['document_id']
        )
        report = self.service.generate_report(analysis.id, language='hebrew')
        summary = report.metadata.get('savings_cover_id_summary') or {}
        self.assertEqual(summary.get('total_savings'), 430808.64)
        self.assertEqual(summary.get('total_cover'), 940000)
        export_payload = self.service.build_report_download_summary(
            report_id=report.id, user_id='CUST-OWNER-001', user_role='customer',
        )
        assessment = export_payload.get('pension_assessment') or {}
        self.assertEqual(assessment['totals']['total_balance'], 430808.64)
        self.assertEqual(assessment['totals']['by_provider']['הכשרה ביטוח'], 420808.64)
        copied = assessment['accounts'][0]
        self.assertEqual(copied.get('death_premium'), 120)
        self.assertEqual(copied.get('death_coverage'), 500000)
        self.assertNotEqual(copied.get('total_balance'), 900000)
        covers = export_payload.get('risk_covers') or []
        life = next(item for item in covers if item.get('type_key') == 'life')
        self.assertEqual(life['amount'], 500000)
        self.assertEqual(life['cost'], 120)
        titles = [section.get('title') for section in export_payload.get('assessment_sections') or []]
        self.assertTrue(any('פוליסות' in str(title) for title in titles))
        from services.risk_reports.pdf_export import build_report_pdf_bytes
        pdf_bytes = build_report_pdf_bytes(export_payload)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_distinct_track_slices_still_sum(self):
        parsed, _ = self.service.parse_content('slices.csv', SLICE_SPREADSHEET, 'csv')
        totals = (parsed.get('pension_data') or {}).get('totals') or {}
        self.assertEqual(totals['total_balance'], 420808.64)
        self.assertEqual(totals['by_provider']['הכשרה ביטוח'], 420808.64)
        self.assertEqual(totals['account_count'], 1)


# Face amounts from a holdings grid column "סכום ביטוח למקרה מוות – חד פעמי".
# They are the lump-sum death benefit, not צבירה.
LUMP_SUM_DEATH_AMOUNTS = (
    3491.00,
    1181862.00,
    1194850.00,
    593289.00,
    0.00,
    1635322.00,
)


class TestLumpSumDeathBenefit(unittest.TestCase):
    """SCHUM-BITUH-LEMAVET / the חד פעמי death column stays a cover face amount."""

    def test_spreadsheet_column_keeps_each_uploaded_amount_out_of_accumulation(self):
        header = 'מספר פוליסה,יצרן,סה״כ חיסכון,סכום ביטוח למקרה מוות – חד פעמי'
        lines = [header]
        for index, amount in enumerate(LUMP_SUM_DEATH_AMOUNTS, start=1):
            lines.append(f'POL-D{index},הכשרה ביטוח,{index * 10},"{amount:,.2f}"')
        payload = ('\n'.join(lines) + '\n').encode('utf-8')
        service = init_ai_reports_service()
        parsed, _ = service.parse_content('lump-death.csv', payload, 'csv')
        pension = parsed.get('pension_data') or {}
        accounts = pension.get('accounts') or []
        totals = pension.get('totals') or {}
        self.assertEqual(len(accounts), 6)
        parsed_amounts = [account.get('death_lump_sum') for account in accounts]
        self.assertEqual(parsed_amounts, list(LUMP_SUM_DEATH_AMOUNTS))
        positive = [amount for amount in LUMP_SUM_DEATH_AMOUNTS if amount > 0]
        self.assertEqual(sum(positive), 4608814.00)
        self.assertEqual(totals.get('total_balance'), 210.0)
        self.assertLess(totals.get('total_balance'), 4608814.00)
        for account in accounts:
            self.assertNotEqual(account.get('total_balance'), account.get('death_lump_sum'))
            self.assertNotEqual(account.get('savings_balance'), account.get('death_lump_sum') or None)

        from services.risk_reports.pdf_export import collect_uploaded_risk_covers
        covers = collect_uploaded_risk_covers(accounts)
        lump = [row for row in covers if row.get('type_key') == 'death_lump_sum']
        self.assertEqual(
            sorted(row['amount'] for row in lump),
            sorted(positive),
        )
        self.assertTrue(all(row['title_he'] == 'סכום ביטוח למקרה מוות – חד פעמי' for row in lump))
        self.assertEqual(sum(row['amount'] for row in lump), 4608814.00)

    def test_xml_schum_bituh_lemavet_is_the_same_field(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak>
  <YeshutYatzran>
    <SHEM-YATZRAN>הכשרה ביטוח</SHEM-YATZRAN>
    <Mutzar>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-XML-LUMP</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON>10</TOTAL-CHISACHON>
        <SchumeiBituahYesodi>
          <SCHUM-BITUH-LEMAVET>1181862.00</SCHUM-BITUH-LEMAVET>
          <OFEN-TASHLUM-SCHUM-BITUAH>1</OFEN-TASHLUM-SCHUM-BITUAH>
        </SchumeiBituahYesodi>
        <Kisuyim>
          <Kisuy>
            <SHEM-KISUY>סכום ביטוח למקרה מוות – חד פעמי</SHEM-KISUY>
            <SCHUM-KISUY>3491</SCHUM-KISUY>
          </Kisuy>
        </Kisuyim>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')
        data = _agent()._parse_mislaka_xml(xml)
        account = data['accounts'][0]
        self.assertEqual(account.get('death_lump_sum'), 1181862.00)
        self.assertEqual(account.get('total_balance'), 10.0)
        nested = account.get('risk_covers') or []
        named = next(item for item in nested if item.get('amount') == 3491)
        self.assertIn('למקרה מוות', named.get('name') or '')
        self.assertIn('חד פעמי', named.get('name') or '')


class TestFacadeStillResolves(unittest.TestCase):
    def test_singleton_parses_official_holdings(self):
        agent = get_pension_agent()
        data = agent._parse_mislaka_xml(OFFICIAL_HOLDINGS)
        self.assertEqual(data['client']['id_number'], '123456782')


if __name__ == '__main__':
    unittest.main()
