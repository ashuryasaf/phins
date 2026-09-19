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


class TestMislakaAssessmentPdfHelpers(unittest.TestCase):
    def test_statistical_titles_are_classified(self):
        from services.risk_reports.pdf_export import (
            is_non_assessment_section_title,
            is_statistical_section_title,
        )
        self.assertTrue(is_statistical_section_title('פרופיל נתונים'))
        self.assertTrue(is_statistical_section_title('📊 Data Profile'))
        self.assertTrue(is_non_assessment_section_title('Affiliation Mapping Snapshot'))
        self.assertFalse(is_statistical_section_title('דו״ח ניתוח פנסיה וביטוח'))
        self.assertFalse(is_non_assessment_section_title('סה״כ צבירה ופיצויים'))


class TestFacadeStillResolves(unittest.TestCase):
    def test_singleton_parses_official_holdings(self):
        agent = get_pension_agent()
        data = agent._parse_mislaka_xml(OFFICIAL_HOLDINGS)
        self.assertEqual(data['client']['id_number'], '123456782')


if __name__ == '__main__':
    unittest.main()
