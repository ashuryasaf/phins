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
from services.pension.schema import (
    account_accumulation,
    account_severance,
    accumulation_by_product,
    death_lump_sum,
    is_holdings_summary_row,
    map_hebrew_column,
    normalize_hebrew_header,
    portfolio_totals,
    product_family_label,
    stamp_account_accumulation,
    tagmulim_amount,
)
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

CONCENTRATED_CSV_WITH_FOOTER = (
    'שם מלא,ת.ז.,סה״כ צבירה,פיצויים,יצרן,מספר פוליסה,סוג מוצר\n'
    'ישראל ישראלי,123456782,"88,000.50",12000,מגדל,POL-HOLD-1,קרן פנסיה מקיפה\n'
    'סה״כ,,88000.50,12000,,סה״כ,צבירה כוללת\n'
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
        self.assertEqual(map_hebrew_column('ביטוח למקרה מוות'), 'death_coverage')
        self.assertEqual(map_hebrew_column('סכום חד פעמי'), 'death_coverage')
        self.assertEqual(map_hebrew_column('סכום חד-פעמי במקרה מוות'), 'death_coverage')
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
        self.assertTrue(pension['totals'].get('integrity', {}).get('accumulation_reconciles', True))
        self.assertEqual(pension['totals']['account_count'], 1)
        self.assertEqual(pension['accounts'][0].get('total_balance'), 88000.50)
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
        export_titles = [section.get('title') for section in export_payload.get('assessment_sections') or []]
        self.assertNotIn('פרופיל נתונים', export_titles)
        self.assertNotIn('Data Profile', export_titles)

        from pypdf import PdfReader
        from services.risk_reports.pdf_export import build_report_pdf_bytes, bidi_text
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

    def test_concentrated_footer_is_not_another_holding(self):
        parsed, _ = self.service.parse_content(
            'doch_merukaz.csv', CONCENTRATED_CSV_WITH_FOOTER, 'csv'
        )
        pension = parsed.get('pension_data') or {}
        self.assertEqual(len(pension.get('accounts') or []), 1)
        self.assertEqual(pension['totals']['total_balance'], 88000.50)
        self.assertEqual(pension['accounts'][0]['total_balance'], 88000.50)
        self.assertTrue(pension['totals']['integrity']['accumulation_reconciles'])

    def test_affiliated_zip_with_footer_keeps_official_tzvira(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('holdings_mivneachid.xml', OFFICIAL_HOLDINGS)
            zf.writestr('doch_merukaz.csv', CONCENTRATED_CSV_WITH_FOOTER)
        parse_result = self.service.parse_file(
            'swiftness_footer.zip',
            buf.getvalue(),
            'zip',
            owner_id='CUST-OWNER-001',
            owner_role='customer',
        )
        pension = parse_result['parsed_data']['pension_data']
        self.assertEqual(pension['totals']['total_balance'], 88000.50)
        self.assertEqual(sum(pension['totals']['by_product'].values()), 88000.50)
        self.assertEqual(len(pension['accounts']), 1)


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
        self.assertEqual(hachshara['total_balance'], 420808.64)
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
        self.assertEqual(totals['by_product']['פוליסת חיסכון'], 420808.64)
        self.assertEqual(totals['by_product']['ביטוח ריסק'], 10000)
        self.assertEqual(sum(totals['by_product'].values()), totals['total_balance'])
        self.assertEqual(totals['total_death_lump_sum'], 500000)
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


DEATH_LUMP_HOLDINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/holdings">
  <YeshutYatzran>
    <SHEM-YATZRAN>הראל</SHEM-YATZRAN>
    <Mutzar>
      <SUG-MUTZAR>7</SUG-MUTZAR>
      <SHEM-MUTZAR>ביטוח מנהלים</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-DEATH-1</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>120000</TOTAL-CHISACHON-MTZBR>
        <Kisuyim>
          <Kisuy>
            <KOD-SUG-KISUY>1</KOD-SUG-KISUY>
            <SHEM-KISUY>ביטוח למקרה מוות</SHEM-KISUY>
            <SCHUM-HAD-PEAMI>750000</SCHUM-HAD-PEAMI>
            <KITZBA-CHODSHIT>2500</KITZBA-CHODSHIT>
            <DMEY-BITUACH>60</DMEY-BITUACH>
          </Kisuy>
        </Kisuyim>
      </HeshbonOPolisa>
    </Mutzar>
    <Mutzar>
      <SUG-MUTZAR>1</SUG-MUTZAR>
      <SHEM-MUTZAR>קרן פנסיה מקיפה</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-PENS-1</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>80000</TOTAL-CHISACHON-MTZBR>
        <KISUY-MAVET>200000</KISUY-MAVET>
      </HeshbonOPolisa>
    </Mutzar>
    <Mutzar>
      <SUG-MUTZAR>4</SUG-MUTZAR>
      <SHEM-MUTZAR>קופת גמל</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-GEMEL-1</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>45000</TOTAL-CHISACHON-MTZBR>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')


class TestOfficialMislakaConcentrationAndDeathLump(unittest.TestCase):
    """ריכוז צבירה לפי סוג מוצר and סכום חד פעמי must match the official report."""

    def setUp(self):
        self.agent = _agent()

    def test_product_family_collapses_pension_variants(self):
        self.assertEqual(product_family_label({'product_type_code': '1'}), 'קרן פנסיה')
        self.assertEqual(product_family_label({'product_type_code': '3'}), 'קרן פנסיה')
        self.assertEqual(product_family_label({'product_type': '4'}), 'קופת גמל')
        self.assertEqual(product_family_label({'product_type': 'ביטוח סיכונים - חד פעמי'}), 'ביטוח ריסק')
        self.assertEqual(
            product_family_label({
                'product_type': 'ביטוח סיכונים - חד פעמי',
                'product_name': 'קופת גמל',
            }),
            'ביטוח ריסק',
        )
        self.assertEqual(product_family_label({'product_type_name': 'קרן פנסיה מקיפה'}), 'קרן פנסיה')

    def test_nested_schum_had_peami_is_death_lump_not_monthly(self):
        data = self.agent._parse_mislaka_xml(DEATH_LUMP_HOLDINGS)
        by_policy = {account['policy_number']: account for account in data['accounts']}
        death_account = by_policy['POL-DEATH-1']
        self.assertEqual(death_account['death_coverage'], 750000)
        self.assertEqual(death_account['death_monthly'], 2500)
        self.assertEqual(death_account['death_premium'], 60)
        self.assertNotEqual(death_account.get('monthly_pension'), 2500)
        covers = death_account.get('risk_covers') or []
        self.assertEqual(len(covers), 1)
        self.assertEqual(covers[0]['amount'], 750000)
        self.assertEqual(covers[0]['monthly'], 2500)
        self.assertEqual(death_lump_sum(death_account), 750000)

    def test_enrichment_matches_official_concentration_and_death_totals(self):
        result = self.agent.process_xml_content(DEATH_LUMP_HOLDINGS)
        totals = result['data']['totals']
        self.assertEqual(totals['total_balance'], 245000)
        self.assertEqual(totals['by_product']['קרן פנסיה'], 80000)
        self.assertEqual(totals['by_product']['ביטוח מנהלים'], 120000)
        self.assertEqual(totals['by_product']['קופת גמל'], 45000)
        self.assertEqual(sum(totals['by_product'].values()), totals['total_balance'])
        self.assertEqual(totals['total_death_lump_sum'], 950000)
        report = result['report']
        self.assertIn('ריכוז סכומי הצבירה לפי סוגי המוצרים', report)
        self.assertIn('ביטוח למקרה מוות', report)
        self.assertIn('סכום חד פעמי', report)

    def test_repeated_track_death_cover_counts_once(self):
        accounts = [
            {'policy_number': 'POL-H', 'death_coverage': 500000, 'total_balance': 420808.64, 'product_type': '10'},
            {'policy_number': 'POL-H', 'death_coverage': 500000, 'total_balance': 420808.64, 'product_type': '10'},
            {'policy_number': 'POL-B', 'death_coverage': 0, 'total_balance': 10000, 'product_type': '11'},
        ]
        self.assertEqual(accumulation_by_product(accounts)['פוליסת חיסכון'], 420808.64)
        self.assertEqual(accumulation_by_product(accounts)['ביטוח ריסק'], 10000)
        from services.pension.schema import deduped_sum
        self.assertEqual(deduped_sum(accounts, death_lump_sum), 500000)

    def test_summary_footer_and_stamp_keep_affiliated_tzvira(self):
        self.assertTrue(is_holdings_summary_row({
            'policy_number': 'סה״כ',
            'total_balance': 88000.50,
        }))
        self.assertFalse(is_holdings_summary_row({
            'policy_number': 'POL-HOLD-1',
            'savings_balance': 88000.50,
            'product_type': 'קרן פנסיה',
        }))
        stamped = {'policy_number': 'POL-H', 'savings_balance': 420808.64}
        self.assertEqual(stamp_account_accumulation(stamped), 420808.64)
        self.assertEqual(stamped['total_balance'], 420808.64)
        # A stamped סה"כ חיסכון stays חיסכון; only a תגמולים column is תגמולים.
        self.assertEqual(tagmulim_amount(stamped), 0.0)
        self.assertEqual(tagmulim_amount({'total_balance': 100000, 'savings_balance': 50000}), 50000)
        snap = portfolio_totals([
            {'policy_number': 'POL-H', 'savings_balance': 420808.64, 'product_type': '10'},
            {'policy_number': 'סה״כ', 'total_balance': 420808.64, 'product_type': 'צבירה כוללת'},
        ])
        self.assertEqual(snap['total_balance'], 420808.64)
        self.assertEqual(snap['total_savings'], 420808.64)
        self.assertEqual(snap['total_tagmulim'], 0)
        self.assertTrue(snap['integrity']['accumulation_reconciles'])

    def test_pension_agent_affiliated_zip_uses_official_tzvira(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('holdings_mivneachid.xml', OFFICIAL_HOLDINGS)
            zf.writestr('pitzuim.xml', SEVERANCE_XML)
            zf.writestr('doch_merukaz.csv', CONCENTRATED_CSV_WITH_FOOTER)
        result = _agent().process_zip_content(buf.getvalue())
        totals = result['data']['totals']
        self.assertEqual(totals['total_balance'], 88000.50)
        self.assertEqual(totals['total_severance'], 16500.0)
        self.assertEqual(len(result['data']['accounts']), 1)
        self.assertEqual(result['data']['accounts'][0]['total_balance'], 88000.50)
        self.assertTrue(totals['integrity']['accumulation_reconciles'])
        self.assertIn('צבירה', result['report'])

    def test_pension_agent_spreadsheet_zip_stamps_tzvira_kolelet(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('holdings.csv', HOLDINGS_SPREADSHEET)
        result = _agent().process_zip_content(buf.getvalue())
        totals = result['data']['totals']
        self.assertEqual(totals['total_balance'], 430808.64)
        self.assertEqual(totals['by_product']['פוליסת חיסכון'], 420808.64)
        self.assertEqual(totals['by_product']['ביטוח ריסק'], 10000)
        self.assertTrue(all(
            account.get('total_balance') for account in result['data']['accounts']
        ))


RISK_ONLY_SALDO_HOLDINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/holdings">
  <YeshutYatzran>
    <SHEM-YATZRAN>הראל</SHEM-YATZRAN>
    <Mutzar>
      <SUG-MUTZAR>11</SUG-MUTZAR>
      <SHEM-MUTZAR>ביטוח סיכונים</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-RISK-1</MISPAR-POLISA-O-HESHBON>
        <SALDO>500000</SALDO>
        <Kisuyim>
          <Kisuy>
            <KOD-SUG-KISUY>1</KOD-SUG-KISUY>
            <SHEM-KISUY>ביטוח למקרה מוות</SHEM-KISUY>
            <SCHUM-HAD-PEAMI>500000</SCHUM-HAD-PEAMI>
          </Kisuy>
        </Kisuyim>
      </HeshbonOPolisa>
    </Mutzar>
    <Mutzar>
      <SUG-MUTZAR>1</SUG-MUTZAR>
      <SHEM-MUTZAR>קרן פנסיה מקיפה</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-SAV-1</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>88000.50</TOTAL-CHISACHON-MTZBR>
        <YITRAT-PITZUIM>12000</YITRAT-PITZUIM>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')


LIFE_SUM_COVER_HOLDINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/holdings">
  <YeshutYatzran>
    <SHEM-YATZRAN>מגדל</SHEM-YATZRAN>
    <Mutzar>
      <SUG-MUTZAR>7</SUG-MUTZAR>
      <SHEM-MUTZAR>ביטוח מנהלים</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-LIFE-SUM</MISPAR-POLISA-O-HESHBON>
        <TOTAL-CHISACHON-MTZBR>88000.50</TOTAL-CHISACHON-MTZBR>
        <Kisuyim>
          <Kisuy>
            <SHEM-KISUY>ביטוח חיים</SHEM-KISUY>
            <SACH-KISUY>588000.50</SACH-KISUY>
          </Kisuy>
          <Kisuy>
            <KOD-SUG-KISUY>1</KOD-SUG-KISUY>
            <SHEM-KISUY>ביטוח למקרה מוות</SHEM-KISUY>
            <SCHUM-HAD-PEAMI>500000</SCHUM-HAD-PEAMI>
          </Kisuy>
        </Kisuyim>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</Mimshak>
""".encode('utf-8')


MULTI_EMPLOYER_PITZUIM = """<?xml version="1.0" encoding="UTF-8"?>
<Mimshak xmlns="http://www.swiftness.co.il/mivneachid/pitzuim">
  <KoteretKovetz>
    <SUG-MIMSHAK>17</SUG-MIMSHAK>
  </KoteretKovetz>
  <YeshutLakoach>
    <MISPAR-ZIHUI-LAKOACH>123456782</MISPAR-ZIHUI-LAKOACH>
  </YeshutLakoach>
  <NetuneiPitzuim>
    <YeshutMaasik>
      <SHEM-MAASIK>מעסיק אלפא</SHEM-MAASIK>
      <SACH-PITZUIM>12000</SACH-PITZUIM>
    </YeshutMaasik>
    <YeshutMaasik>
      <SHEM-MAASIK>מעסיק ביתא</SHEM-MAASIK>
      <SACH-PITZUIM>8000</SACH-PITZUIM>
    </YeshutMaasik>
    <YeshutMaasik>
      <SHEM-MAASIK>מעסיק גמא</SHEM-MAASIK>
      <SACH-PITZUIM>4500</SACH-PITZUIM>
    </YeshutMaasik>
  </NetuneiPitzuim>
</Mimshak>
""".encode('utf-8')


SWAP_AND_SEVERANCE_CSV = (
    'מספר פוליסה,סוג מוצר,יצרן,סה״כ חיסכון,יתרה,ביטוח חיים,פיצויים,מעסיק\n'
    'POL-LIFE,ביטוח מנהלים,מגדל,88000.50,500000,588000.50,12000,מעסיק אלפא\n'
    'POL-RISK,ביטוח סיכונים,הראל,0,500000,500000,0,\n'
    ',פיצויים,,0,0,0,8000,מעסיק ביתא\n'
    'POL-CENTRAL,קופה מרכזית לפיצויים,כלל,45000,45000,0,0,מעסיק גמא\n'
).encode('utf-8')


class TestSavingsCoverSeparationAndSeveranceSum(unittest.TestCase):
    """צבירה כוללת is savings only; ביטוח חיים is death face; פיצויים sums every pot."""

    def setUp(self):
        self.agent = _agent()
        self.service = init_ai_reports_service()

    def test_risk_saldo_is_not_tzvira_kolelet(self):
        result = self.agent.process_xml_content(RISK_ONLY_SALDO_HOLDINGS)
        totals = result['data']['totals']
        by_policy = {account['policy_number']: account for account in result['data']['accounts']}
        self.assertEqual(account_accumulation(by_policy['POL-RISK-1']), 0)
        self.assertEqual(by_policy['POL-RISK-1']['death_coverage'], 500000)
        self.assertEqual(by_policy['POL-SAV-1']['total_balance'], 88000.50)
        self.assertEqual(totals['total_balance'], 88000.50)
        self.assertEqual(totals['total_death_lump_sum'], 500000)
        self.assertNotIn('ביטוח ריסק', totals.get('by_product') or {})

    def test_life_sach_kisuy_sum_is_not_death_cover(self):
        result = self.agent.process_xml_content(LIFE_SUM_COVER_HOLDINGS)
        account = result['data']['accounts'][0]
        self.assertEqual(account_accumulation(account), 88000.50)
        self.assertEqual(death_lump_sum(account), 500000)
        self.assertEqual(account['death_coverage'], 500000)
        self.assertEqual(result['data']['totals']['total_balance'], 88000.50)
        self.assertEqual(result['data']['totals']['total_death_lump_sum'], 500000)

    def test_spreadsheet_swap_and_severance_pots_sum(self):
        parsed, _ = self.service.parse_content('swap.csv', SWAP_AND_SEVERANCE_CSV, 'csv')
        totals = (parsed.get('pension_data') or {}).get('totals') or {}
        accounts = (parsed.get('pension_data') or {}).get('accounts') or []
        by_policy = {account.get('policy_number'): account for account in accounts}
        self.assertEqual(account_accumulation(by_policy['POL-LIFE']), 88000.50)
        self.assertEqual(death_lump_sum(by_policy['POL-LIFE']), 500000)
        self.assertEqual(account_accumulation(by_policy['POL-RISK']), 0)
        self.assertEqual(death_lump_sum(by_policy['POL-RISK']), 500000)
        self.assertEqual(account_severance(by_policy['POL-CENTRAL']), 45000)
        self.assertEqual(totals['total_balance'], 133000.50)
        self.assertEqual(totals['total_death_lump_sum'], 1000000)
        self.assertEqual(totals['total_severance'], 65000)
        self.assertTrue(totals['integrity']['accumulation_reconciles'])

    def test_multi_employer_pitzuim_xml_sums_every_pot(self):
        data = self.agent._parse_mislaka_xml(MULTI_EMPLOYER_PITZUIM)
        amounts = sorted(float(row.get('total_severance') or 0) for row in data.get('severance') or [])
        self.assertEqual(amounts, [4500.0, 8000.0, 12000.0])
        result = self.agent.process_xml_content(MULTI_EMPLOYER_PITZUIM)
        self.assertEqual(result['data']['totals']['total_severance'], 24500.0)

    def test_same_policy_two_employers_same_amount_still_sum(self):
        snap = portfolio_totals([
            {'policy_number': 'POL-P', 'employer_name': 'מעסיק א', 'severance_balance': 5000, 'total_balance': 20000, 'product_type': '1'},
            {'policy_number': 'POL-P', 'employer_name': 'מעסיק ב', 'severance_balance': 5000, 'total_balance': 20000, 'product_type': '1'},
        ])
        self.assertEqual(snap['total_balance'], 20000)
        self.assertEqual(snap['total_severance'], 10000)

    def test_employer_only_pitzuim_row_is_not_a_footer(self):
        self.assertFalse(is_holdings_summary_row({
            'employer_name': 'מעסיק ביתא',
            'severance_balance': 8000,
        }))
        stamped = {
            'policy_number': 'POL-LIFE',
            'savings_balance': 88000.50,
            'balance': 500000,
            'death_coverage': 588000.50,
            'product_type': '7',
        }
        self.assertEqual(stamp_account_accumulation(stamped), 88000.50)
        self.assertEqual(stamped['total_balance'], 88000.50)
        self.assertEqual(stamped['death_coverage'], 500000)


class TestFacadeStillResolves(unittest.TestCase):
    def test_singleton_parses_official_holdings(self):
        agent = get_pension_agent()
        data = agent._parse_mislaka_xml(OFFICIAL_HOLDINGS)
        self.assertEqual(data['client']['id_number'], '123456782')


if __name__ == '__main__':
    unittest.main()
