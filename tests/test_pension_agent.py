"""B5 — Pension Data Agent: package split, indexed / streaming XML parsing and
the content-addressed parse cache.

The pension parser's contract is its output dict; every test here pins that
the tree parser, the streaming parser and the cached path produce the same
``data`` for the same bytes, that malformed input is rejected on every path
(``defusedxml`` stays in front of the parser), and that the cache can never
serve one caller's mutations to another.
"""

import copy
import io
import json
import os
import sys
import time
import tracemalloc
import zipfile
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.pension_data_agent as facade  # noqa: E402
from services.pension import agent as agent_mod, cache as cache_mod, parsers as parsers_mod  # noqa: E402
from services.pension.agent import PensionDataAgent  # noqa: E402
from services.pension.cache import PARSER_VERSION, ParseResultCache, sha256_hex  # noqa: E402
from services.pension.parsers import MislakaParserMixin  # noqa: E402
from services.pension.schema import CompiledFields, MislakaSchemaMapping, tag_variants  # noqa: E402

STREAM_ENV = MislakaParserMixin.STREAM_MIN_BYTES_ENV


# --------------------------------------------------------------------------
# Fixtures: Mislaka-shaped documents
# --------------------------------------------------------------------------
SIMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<MislakaReport>
  <YeshutLakoach>
    <MISPAR-ZIHUI-LAKOACH>123456782</MISPAR-ZIHUI-LAKOACH>
    <TAARICH-LEYDA>19781111</TAARICH-LEYDA>
    <SHEM-LAKOACH>Test Client</SHEM-LAKOACH>
  </YeshutLakoach>
  <YeshutYatzran>
    <SHEM-YATZRAN>Provider A</SHEM-YATZRAN>
    <Mutzar>
      <SHEM-MUTZAR>Plan A</SHEM-MUTZAR>
      <HeshbonOPolisa>
        <MISPAR-POLISA-O-HESHBON>POL-XML-1</MISPAR-POLISA-O-HESHBON>
        <SALDO>10000</SALDO>
      </HeshbonOPolisa>
    </Mutzar>
  </YeshutYatzran>
</MislakaReport>""".encode('utf-8')


def realistic(n_providers=2, n_accounts=3, encoding='utf-8'):
    """Real Mislaka layout: header at the root, client / employer / accounts
    nested under every provider's products."""
    parts = [f'<?xml version="1.0" encoding="{encoding}"?>', '<Mimshak>',
             '  <KoteretKovetz>',
             '    <SUG-MIMSHAK>1</SUG-MIMSHAK>',
             '    <MISPAR-GIRSAT-XML>009</MISPAR-GIRSAT-XML>',
             '    <TAARICH-BITZUA>20240315101500</TAARICH-BITZUA>',
             '  </KoteretKovetz>']
    for p in range(n_providers):
        parts += ['  <YeshutYatzran>',
                  f'    <SHEM-YATZRAN>יצרן {p}</SHEM-YATZRAN>',
                  f'    <KOD-MEZAHE-YATZRAN>{510 + p}</KOD-MEZAHE-YATZRAN>',
                  '    <Mutzarim>']
        for a in range(n_accounts):
            parts += ['      <Mutzar>',
                      f'        <SUG-MUTZAR>{1 + (a % 3)}</SUG-MUTZAR>',
                      f'        <SHEM-MUTZAR>מוצר {p}-{a}</SHEM-MUTZAR>',
                      '        <NetuneiMutzar>',
                      '          <YeshutLakoach>',
                      '            <MISPAR-ZIHUI-LAKOACH>123456782</MISPAR-ZIHUI-LAKOACH>',
                      '            <SHEM-PRATI>ישראל</SHEM-PRATI>',
                      '            <SHEM-MISHPACHA>ישראלי</SHEM-MISHPACHA>',
                      '            <TAARICH-LEYDA>19781111</TAARICH-LEYDA>',
                      '          </YeshutLakoach>',
                      '          <YeshutMaasik>',
                      f'            <SHEM-MAASIK>מעסיק {a}</SHEM-MAASIK>',
                      f'            <KOD-MAASIK>{900 + a}</KOD-MAASIK>',
                      '          </YeshutMaasik>',
                      '          <HeshbonotOPolisot>',
                      '            <HeshbonOPolisa>',
                      f'              <MISPAR-POLISA-O-HESHBON>POL-{p}-{a}</MISPAR-POLISA-O-HESHBON>',
                      f'              <SHEM-MAASIK>מעסיק {a}</SHEM-MAASIK>',
                      f'              <TOTAL-CHISACHON-MTZBR>{1000 * (a + 1)},50</TOTAL-CHISACHON-MTZBR>',
                      f'              <YITRAT-PITZUIM>{250 * (a + 1)}</YITRAT-PITZUIM>',
                      '              <STATUS-POLISA-O-CHESHBON>1</STATUS-POLISA-O-CHESHBON>',
                      '              <SEIF-14>1</SEIF-14>',
                      '              <NetuneiHafrasha>',
                      '                <HAFRASHA-OVED>300</HAFRASHA-OVED>',
                      '                <HAFRASHA-MAASIK>450</HAFRASHA-MAASIK>',
                      '              </NetuneiHafrasha>',
                      '              <NetuneiPitzuim>',
                      f'                <SACH-PITZUIM>{5000 * (a + 1)}</SACH-PITZUIM>',
                      '                <SEIF-14>1</SEIF-14>',
                      '              </NetuneiPitzuim>',
                      '            </HeshbonOPolisa>',
                      '          </HeshbonotOPolisot>',
                      '        </NetuneiMutzar>',
                      '      </Mutzar>']
        parts += ['    </Mutzarim>', '  </YeshutYatzran>']
    parts.append('</Mimshak>')
    return '\n'.join(parts).encode(encoding)


# Standalone accounts, a root-level employer, an ``Account``/``Policy`` block,
# contributions outside any provider — every ``.//`` search the tree parser
# makes across the whole document is exercised.
MIXED_SHAPES = b"""<?xml version="1.0"?><Root><Header><SUG-MIMSHAK>17</SUG-MIMSHAK></Header>
<YeshutMaasik><SHEM-MAASIK>Root Employer</SHEM-MAASIK><KOD-MAASIK>1</KOD-MAASIK></YeshutMaasik>
<HeshbonOPolisa><MISPAR-POLISA-O-HESHBON>SA-1</MISPAR-POLISA-O-HESHBON><SALDO>5</SALDO></HeshbonOPolisa>
<YeshutYatzran><SHEM-YATZRAN>P</SHEM-YATZRAN><Mutzar>
  <HeshbonOPolisa><MISPAR-POLISA-O-HESHBON>SA-1</MISPAR-POLISA-O-HESHBON><SALDO>9</SALDO></HeshbonOPolisa>
  <HeshbonOPolisa><MISPAR-POLISA-O-HESHBON>P-2</MISPAR-POLISA-O-HESHBON></HeshbonOPolisa></Mutzar>
  <Account><MISPAR-POLISA-O-HESHBON>ACC-9</MISPAR-POLISA-O-HESHBON></Account>
  <NetuneiPitzuim><SACH-PITZUIM>100</SACH-PITZUIM></NetuneiPitzuim></YeshutYatzran>
<Policy><MISPAR-POLISA-O-HESHBON>POL-7</MISPAR-POLISA-O-HESHBON></Policy>
<NetuneiHafrasha><HAFRASHA-OVED>1</HAFRASHA-OVED></NetuneiHafrasha>
</Root>"""

FIXTURES = {
    'simple': SIMPLE,
    'realistic_small': realistic(2, 3),
    'realistic_medium': realistic(4, 25),
    'realistic_cp1255': realistic(1, 2, encoding='windows-1255'),
    'mixed_shapes': MIXED_SHAPES,
    'no_header': b"<R><YeshutYatzran><SHEM-YATZRAN>X</SHEM-YATZRAN></YeshutYatzran></R>",
}


def zip_of(*members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, m in enumerate(members):
            zf.writestr(f'file_{i}.xml', m)
    return buf.getvalue()


@pytest.fixture
def agent():
    """A private agent with the cache on but no durable tier."""
    return PensionDataAgent(parse_cache=ParseResultCache(max_entries=8, enabled=True,
                                                         db_factory=lambda: _NoDb()))


class _NoDb:
    def __enter__(self):
        raise RuntimeError('no database in this test')

    def __exit__(self, *exc):
        return False


@pytest.fixture
def tree_only(monkeypatch):
    monkeypatch.setenv(STREAM_ENV, str(10 ** 12))


@pytest.fixture
def stream_only(monkeypatch):
    monkeypatch.setenv(STREAM_ENV, '0')


# --------------------------------------------------------------------------
# Package split
# --------------------------------------------------------------------------
class TestPackageSplit:
    def test_facade_reexports_the_package_objects(self):
        assert facade.PensionDataAgent is agent_mod.PensionDataAgent
        assert facade.MislakaSchemaMapping is MislakaSchemaMapping
        assert facade.ClientProfile.__module__ == 'services.pension.profile'
        assert facade.get_pension_agent is agent_mod.get_pension_agent
        assert facade.is_pension_xml is agent_mod.is_pension_xml
        assert facade.get_pension_agent() is agent_mod.get_pension_agent()
        assert facade._pension_agent is agent_mod._pension_agent

    def test_affiliations_still_read_the_authoritative_mapping(self):
        from services.mislaka_affiliations import _schema_mapping
        assert _schema_mapping() is MislakaSchemaMapping

    def test_agent_descriptor_still_names_the_historical_module(self):
        from services.agent_runtime import get_descriptor
        desc = get_descriptor('pension_data_agent')
        assert desc is not None
        assert desc.module == 'services.pension_data_agent'

    def test_compiled_fields_mirror_the_schema_tables(self):
        for section, mapping in (
            (CompiledFields.HEADER, MislakaSchemaMapping.HEADER_FIELDS),
            (CompiledFields.ACCOUNT, MislakaSchemaMapping.ACCOUNT_FIELDS),
            (CompiledFields.SEVERANCE, MislakaSchemaMapping.SEVERANCE_FIELDS),
        ):
            assert [(t, f) for t, f, _ in section] == list(mapping.items())
            for tag, _, variants in section:
                assert variants == tag_variants(tag) and variants[0] == tag
        assert tag_variants('MISPAR-POLISA-O-HESHBON') == (
            'MISPAR-POLISA-O-HESHBON', 'MISPARPOLISAOHESHBON', 'MisparPolisaOHeshbon')
        assert tag_variants('Mutzar') == ('Mutzar',)

    def test_health_probe_reports_streaming_threshold_and_cache(self, monkeypatch):
        monkeypatch.setenv(STREAM_ENV, '4096')
        probe = facade._pension_agent_health()
        assert probe['status'] == 'ok' and probe['stream_min_bytes'] == 4096
        facade.get_pension_agent()
        probe = facade._pension_agent_health()
        assert probe['initialized'] is True
        assert probe['parse_cache']['parser_version'] == PARSER_VERSION


# --------------------------------------------------------------------------
# Indexed lookups
# --------------------------------------------------------------------------
class TestFindText:
    def test_index_matches_find_semantics_including_empty_first_match(self, agent):
        from defusedxml import ElementTree as ET
        root = ET.fromstring(
            b"<A><B><SALDO></SALDO></B><SALDO>7</SALDO><KOD-MAASIK>1</KOD-MAASIK>"
            b"<KodSug>x</KodSug><ShemMaasik> y </ShemMaasik></A>")
        scan = {t: agent._find_text(root, t) for t in ('SALDO', 'KOD-MAASIK', 'KOD-SUG', 'SHEM-MAASIK', 'MISSING')}
        with agent._parse_context():
            indexed = {t: agent._find_text(root, t) for t in scan}
        # find('.//SALDO') resolves to the *first* SALDO, whose text is empty → None
        assert scan == indexed == {'SALDO': None, 'KOD-MAASIK': '1', 'KOD-SUG': 'x',
                                   'SHEM-MAASIK': 'y', 'MISSING': None}

    def test_index_is_per_parse_and_never_leaks_between_threads(self, agent):
        import threading
        seen = {}

        def worker():
            seen['ctx'] = getattr(MislakaParserMixin._parse_local, 'ctx', None)

        with agent._parse_context() as ctx:
            assert getattr(MislakaParserMixin._parse_local, 'ctx') is ctx
            t = threading.Thread(target=worker)
            t.start()
            t.join()
        assert seen['ctx'] is None
        assert getattr(MislakaParserMixin._parse_local, 'ctx', None) is None


# --------------------------------------------------------------------------
# Streaming parser
# --------------------------------------------------------------------------
class TestStreamingParser:
    @pytest.mark.parametrize('name', sorted(FIXTURES))
    def test_streaming_output_equals_tree_output(self, agent, monkeypatch, name):
        xml = FIXTURES[name]
        monkeypatch.setenv(STREAM_ENV, str(10 ** 12))
        tree = agent._parse_mislaka_xml(xml)
        monkeypatch.setenv(STREAM_ENV, '0')
        stream = agent._parse_mislaka_xml(xml)
        assert stream == tree
        # and the whole processed result (minus the report timestamp) too
        agent.parse_cache.clear()
        monkeypatch.setenv(STREAM_ENV, str(10 ** 12))
        full_tree = agent.process_xml_content(xml)
        agent.parse_cache.clear()
        monkeypatch.setenv(STREAM_ENV, '0')
        full_stream = agent.process_xml_content(xml)
        assert full_stream['data'] == full_tree['data']
        assert full_stream['interface_type'] == full_tree['interface_type']

    def test_threshold_selects_the_path(self, agent, monkeypatch):
        calls = []
        real = agent._parse_mislaka_xml_streaming

        def spy(content):
            calls.append(len(content))
            return real(content)

        monkeypatch.setattr(agent, '_parse_mislaka_xml_streaming', spy)
        xml = realistic(1, 2)
        monkeypatch.setenv(STREAM_ENV, str(len(xml) + 1))
        agent._parse_mislaka_xml(xml)
        assert calls == []
        monkeypatch.setenv(STREAM_ENV, str(len(xml)))
        agent._parse_mislaka_xml(xml)
        assert calls == [len(xml)]
        assert MislakaParserMixin.stream_min_bytes() == len(xml)
        monkeypatch.setenv(STREAM_ENV, 'garbage')
        assert MislakaParserMixin.stream_min_bytes() == MislakaParserMixin.DEFAULT_STREAM_MIN_BYTES

    def test_streaming_bounds_peak_memory(self, agent, monkeypatch):
        xml = realistic(12, 120)  # ~2.5 MB, 1,440 accounts
        peaks = {}
        for label, threshold in (('tree', str(10 ** 12)), ('stream', '0')):
            monkeypatch.setenv(STREAM_ENV, threshold)
            tracemalloc.start()
            out = agent._parse_mislaka_xml(xml)
            _, peaks[label] = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert len(out['accounts']) == 12 * 120
        assert peaks['stream'] < 0.6 * peaks['tree'], peaks
        assert peaks['stream'] < 4 * len(xml), peaks

    @pytest.mark.parametrize('threshold', ['0', str(10 ** 12)])
    def test_malformed_and_entity_documents_are_rejected_on_both_paths(self, agent, monkeypatch, threshold):
        monkeypatch.setenv(STREAM_ENV, threshold)
        with pytest.raises(ValueError, match='Failed to parse XML'):
            agent._parse_mislaka_xml(realistic(1, 2)[:-40])
        with pytest.raises(ValueError, match='EntitiesForbidden'):
            agent._parse_mislaka_xml(b'<!DOCTYPE x [<!ENTITY e "boom">]><R>&e;</R>')
        assert agent.parse_cache.stats['puts'] == 0

    def test_undeclared_legacy_encoding_falls_back_to_tree_parse(self, agent, monkeypatch, stream_only):
        # windows-1255 bytes without a matching declaration: expat cannot
        # stream it; the tree parser's decode fallback still produces the client.
        xml = realistic(1, 1, encoding='windows-1255').replace(b'encoding="windows-1255"', b'')
        data = agent._parse_mislaka_xml(xml)
        assert data['client']['id_number'] == '123456782'
        assert data['accounts'][0]['policy_number'] == 'POL-0-0'

    def test_streaming_releases_provider_blocks_from_the_tree(self, agent, stream_only):
        harvested = []
        real = agent._release_block

        def spy(elem, parent, ctx):
            harvested.append(len(list(elem.iter())))
            real(elem, parent, ctx)
            assert len(list(elem.iter())) == 1  # cleared
            assert elem not in list(parent)  # detached

        agent._release_block = spy
        data = agent._parse_mislaka_xml(realistic(3, 4))
        assert len(harvested) == 3 and all(n > 50 for n in harvested)
        assert len(data['accounts']) == 12 and len(data['providers']) == 3


# --------------------------------------------------------------------------
# Parse cache
# --------------------------------------------------------------------------
class TestParseCache:
    def test_key_includes_parser_version_and_kind(self):
        assert ParseResultCache.key('xml', 'ab') == f'PENSION-xml-ab-v{PARSER_VERSION}'
        assert ParseResultCache.key('zip', 'ab') != ParseResultCache.key('xml', 'ab')

    def test_get_and_put_are_copy_isolated(self):
        cache = ParseResultCache(max_entries=4, enabled=True, db_factory=lambda: _NoDb())
        data = {'accounts': [{'policy_number': 'X'}]}
        cache.put('xml', 'sha', data)
        data['accounts'][0]['policy_number'] = 'MUTATED-SOURCE'
        first = cache.get('xml', 'sha')
        assert first == {'accounts': [{'policy_number': 'X'}]}
        first['accounts'].clear()
        assert cache.get('xml', 'sha') == {'accounts': [{'policy_number': 'X'}]}
        assert cache.stats['hits'] == 2 and cache.stats['misses'] == 0

    def test_lru_bound_and_disable_flag(self, monkeypatch):
        cache = ParseResultCache(max_entries=2, enabled=True, db_factory=lambda: _NoDb())
        for i in range(3):
            cache.put('xml', f's{i}', {'i': i})
        assert cache.get('xml', 's0') is None and cache.get('xml', 's2') == {'i': 2}
        monkeypatch.setenv(cache_mod.ENABLED_ENV, 'false')
        off = ParseResultCache(db_factory=lambda: _NoDb())
        off.put('xml', 'k', {'x': 1})
        assert off.enabled is False and off.get('xml', 'k') is None

    def test_xml_parse_is_served_from_cache_and_report_is_regenerated(self, agent, monkeypatch, tree_only):
        calls = []
        real = agent._parse_root
        monkeypatch.setattr(agent, '_parse_root', lambda root: calls.append(1) or real(root))
        first = agent.process_xml_content(SIMPLE)
        second = agent.process_xml_content(SIMPLE)
        assert calls == [1]
        assert second['data'] == first['data']
        assert agent.parse_cache.stats == {**agent.parse_cache.stats, 'hits': 1, 'misses': 1, 'puts': 1}
        # the report is rebuilt per call (it carries the generation timestamp)
        stamp = datetime.now().strftime('%d/%m/%Y')
        assert stamp in second['report']

    def test_zip_profile_is_cached_by_archive_hash_and_member_hash(self, agent, monkeypatch, tree_only):
        aggregate_calls, parse_calls = [], []
        real_aggregate, real_parse = agent._aggregate_zip, agent._parse_root
        monkeypatch.setattr(agent, '_aggregate_zip', lambda b: aggregate_calls.append(1) or real_aggregate(b))
        monkeypatch.setattr(agent, '_parse_root', lambda r: parse_calls.append(1) or real_parse(r))
        other = SIMPLE.replace(b'POL-XML-1', b'POL-XML-2').replace(b'Provider A', b'Provider B')

        first = agent.process_zip_content(zip_of(SIMPLE, other))
        assert aggregate_calls == [1] and parse_calls == [1, 1]
        assert first['file_count'] == 2 and 'Holdings' in first['interface_type']

        second = agent.process_zip_content(zip_of(SIMPLE, other))
        assert aggregate_calls == [1] and parse_calls == [1, 1]
        assert second['data'] == first['data'] and second['file_count'] == 2

        # a different archive containing an already-seen member re-parses only the new one
        third = agent.process_zip_content(zip_of(SIMPLE, SIMPLE.replace(b'POL-XML-1', b'POL-XML-3')))
        assert aggregate_calls == [1, 1] and parse_calls == [1, 1, 1]
        assert {a['policy_number'] for a in third['data']['accounts']} == {'POL-XML-1', 'POL-XML-3'}

    def test_cached_result_cannot_be_poisoned_by_a_consumer(self, agent, tree_only):
        first = agent.process_xml_content(SIMPLE)
        first['data']['client']['id_number'] = 'TAMPERED'
        first['data']['accounts'].clear()
        second = agent.process_xml_content(SIMPLE)
        assert second['data']['client']['id_number'] == '123456782'
        assert second['data']['accounts'][0]['policy_number'] == 'POL-XML-1'

    def test_malformed_input_is_never_cached(self, agent, tree_only):
        with pytest.raises(ValueError):
            agent.process_xml_content(b'<Mimshak><YeshutYatzran>')
        assert agent.parse_cache.stats['puts'] == 0
        with pytest.raises(ValueError):
            agent.process_zip_content(b'not a zip')
        assert agent.parse_cache.stats['puts'] == 0

    def test_broken_durable_tier_is_paused_not_fatal(self, agent, tree_only):
        cache = agent.parse_cache
        cache_mod_db_mode = cache_mod._db_mode
        try:
            cache_mod._db_mode = lambda: True
            agent.process_xml_content(SIMPLE)
            assert cache.stats['errors'] == 1  # the read failed once ...
            agent.process_xml_content(SIMPLE.replace(b'POL-XML-1', b'POL-XML-9'))
            assert cache.stats['errors'] == 1  # ... then the tier is paused, no more attempts
            assert cache.snapshot()['durable_paused'] is True
        finally:
            cache_mod._db_mode = cache_mod_db_mode


class TestDurableParseCache:
    """Second tier in ``agent_artifacts`` (SQLite)."""

    @staticmethod
    def _db():
        # The schema is created once per test (``durable`` fixture); in test
        # mode ``init_database()`` wipes the temp SQLite file, so calling it
        # here would erase the rows a "peer" is supposed to find.
        from database.manager import DatabaseManager
        return DatabaseManager()

    @pytest.fixture
    def durable(self, monkeypatch):
        from database import init_database
        init_database()
        monkeypatch.setattr(cache_mod, '_db_mode', lambda: True)
        return ParseResultCache(max_entries=3, enabled=True, db_factory=self._db)

    def test_round_trip_survives_a_fresh_process_and_peers_share_it(self, durable, monkeypatch):
        sha = sha256_hex(b'unique-%d' % int(time.time() * 1000))
        durable.put('xml', sha, {'accounts': [{'policy_number': 'D-1'}], 'n': 1})
        peer = ParseResultCache(max_entries=3, enabled=True, db_factory=self._db)
        assert peer.get('xml', sha) == {'accounts': [{'policy_number': 'D-1'}], 'n': 1}
        assert peer.stats['durable_hits'] == 1
        with self._db() as db:
            payload = db.agent_artifacts.get_payload(ParseResultCache.key('xml', sha))
        assert payload['parser_version'] == PARSER_VERSION and payload['sha256'] == sha

    def test_corrupted_row_is_skipped_and_old_parser_version_is_ignored(self, durable):
        sha = sha256_hex(b'corrupt-%d' % int(time.time() * 1000))
        durable.put('xml', sha, {'ok': True})
        key = ParseResultCache.key('xml', sha)
        with self._db() as db:
            from database.models import AgentArtifact
            row = db.agent_artifacts.session.get(AgentArtifact, key)
            row.payload_json = row.payload_json.replace('true', 'false')
            db.agent_artifacts.session.commit()
        peer = ParseResultCache(max_entries=3, enabled=True, db_factory=self._db)
        assert peer.get('xml', sha) is None  # checksum mismatch → not served
        old_sha = sha256_hex(b'old-%d' % int(time.time() * 1000))
        with self._db() as db:
            db.agent_artifacts.upsert(ParseResultCache.key('xml', old_sha), agent_id=cache_mod.AGENT_ID,
                                      kind=cache_mod.KIND,
                                      payload={'parser_version': '0', 'data': {'stale': True}})
        assert peer.get('xml', old_sha) is None

    def test_agent_reuses_a_peer_parse_without_touching_the_parser(self, durable, monkeypatch, tree_only):
        xml = SIMPLE.replace(b'POL-XML-1', b'POL-%d' % int(time.time() * 1000))
        writer = PensionDataAgent(parse_cache=durable)
        writer.process_xml_content(xml)
        reader = PensionDataAgent(parse_cache=ParseResultCache(max_entries=3, enabled=True, db_factory=self._db))
        monkeypatch.setattr(reader, '_parse_root', lambda root: pytest.fail('parser must not run'))
        out = reader.process_xml_content(xml)
        assert out['data']['accounts'][0]['policy_number'].startswith('POL-')


# --------------------------------------------------------------------------
# Risk Reports reuse
# --------------------------------------------------------------------------
class TestRiskReportsReuse:
    def test_same_xml_in_two_uploads_is_parsed_once(self, monkeypatch, tree_only):
        from services.ai_risk_reports_service import init_ai_reports_service
        shared = PensionDataAgent(parse_cache=ParseResultCache(max_entries=8, enabled=True,
                                                               db_factory=lambda: _NoDb()))
        monkeypatch.setattr(agent_mod, '_pension_agent', shared)
        calls = []
        real = shared._parse_root
        monkeypatch.setattr(shared, '_parse_root', lambda r: calls.append(1) or real(r))
        service = init_ai_reports_service()
        for name in ('first.xml', 'second.xml'):
            result = service.parse_file(name, SIMPLE, 'xml', owner_id='CUST-B5', owner_role='customer')
            assert result['status'] == 'completed'
            assert result['parsed_data']['pension_data']['accounts'][0]['policy_number'] == 'POL-XML-1'
        assert calls == [1]
        # the client block Risk Reports normalises in place did not leak into the cache
        cached = shared.parse_cache.get('xml', sha256_hex(SIMPLE))
        assert cached['client'] == {'id_number': '123456782', 'birth_date': '19781111', 'full_name': 'Test Client'}
