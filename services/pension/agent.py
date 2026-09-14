"""``PensionDataAgent`` — orchestration, singleton, health probe and agent
registration.

Split out of ``services/pension_data_agent.py`` (B5). The historical module
re-exports everything from here, so ``from services.pension_data_agent import
PensionDataAgent`` keeps working.
"""

import io
import logging
import os
import zipfile
from typing import Any, Dict, Optional

from services.agent_metrics import instrument_agent
from services.pension.cache import ParseResultCache, sha256_hex
from services.pension.parsers import MislakaParserMixin
from services.pension.profile import ClientProfile
from services.pension.report import PensionReportMixin
from services.pension.schema import MislakaSchemaMapping

logger = logging.getLogger('services.pension_data_agent')

# lxml is detected for the health probe only; parsing always goes through defusedxml.
try:  # pragma: no cover - depends on the environment
    import lxml  # noqa: F401
    LXML_AVAILABLE = True
except ImportError:  # pragma: no cover
    LXML_AVAILABLE = False


class PensionDataAgent(MislakaParserMixin, PensionReportMixin):
    """
    Enhanced Pension Data Agent for processing Mislaka (מסלקה) XML/ZIP data.
    Based on ChatGPT analysis of official XSD schemas and interface specs.
    """
    
    def __init__(self, schema_dir: str = None, parse_cache: Optional[ParseResultCache] = None):
        """Initialize the agent with optional schema directory."""
        # ``services/schemas`` — the historical location, kept after the package split.
        self.schema_dir = schema_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'schemas')
        self.schema_mapping = MislakaSchemaMapping()
        self.schema_cache = {}
        self.parse_cache = parse_cache if parse_cache is not None else ParseResultCache()

    # -- cached parsing ---------------------------------------------------------
    def parse_xml_cached(self, xml_content: bytes) -> Dict[str, Any]:
        """``_parse_mislaka_xml`` through the content-addressed cache.

        A malformed document is never cached: the parser raises before the
        ``put`` and the same bytes are re-parsed (and fail again) next time.
        """
        digest = sha256_hex(xml_content)
        cached = self.parse_cache.get('xml', digest)
        if cached is not None:
            return cached
        data = self._parse_mislaka_xml(xml_content)
        self.parse_cache.put('xml', digest, data)
        return data

    @instrument_agent('pension_data_agent')
    def process_xml_content(self, xml_content: bytes) -> Dict[str, Any]:
        """
        Process a single XML content and generate report.
        
        Args:
            xml_content: Raw XML bytes from Mislaka file
            
        Returns:
            Dictionary with parsed data and generated report
        """
        # Parse XML (cached by content hash; enrichment/report are recomputed)
        data = self.parse_xml_cached(xml_content)
        
        # Enrich with derived metrics
        data = self._enrich_data(data)
        
        # Generate professional report
        report = self._generate_professional_report(data)
        
        return {
            'data': data,
            'report': report,
            'language': 'hebrew',
            'interface_type': data.get('interface_type', 'Unknown'),
            'schema_version': data.get('header', {}).get('schema_version', 'Unknown'),
        }
    
    @instrument_agent('pension_data_agent')
    def process_zip_content(self, zip_content: bytes) -> Dict[str, Any]:
        """
        Process a ZIP file containing Mislaka XML and Excel files.
        
        Args:
            zip_content: Raw ZIP file bytes
            
        Returns:
            Dictionary with aggregated data and generated report
        """
        digest = sha256_hex(zip_content)
        data = self.parse_cache.get('zip', digest)
        if data is None:
            data = self._aggregate_zip(zip_content)
            self.parse_cache.put('zip', digest, data)

        header = data.get('header', {}) if isinstance(data.get('header'), dict) else {}
        interface_types = header.get('interface_types') or []
        file_count = header.get('file_count', 0)

        # Enrich with health score
        data = self._enrich_data(data)
        
        # Generate report
        report = self._generate_professional_report(data)
        
        return {
            'data': data,
            'report': report,
            'language': 'hebrew',
            'interface_type': ', '.join(interface_types) if interface_types else 'Unknown',
            'file_count': file_count,
        }

    def _aggregate_zip(self, zip_content: bytes) -> Dict[str, Any]:
        """Parse every member of the archive into one ``ClientProfile`` and
        return its ``to_dict()`` (the cacheable, pre-enrichment aggregate)."""
        profile = ClientProfile()
        
        try:
            with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
                for filename in zf.namelist():
                    # Skip hidden files
                    if filename.startswith('__') or filename.startswith('.'):
                        continue
                    
                    name_lower = filename.lower()
                    ext = name_lower.split('.')[-1] if '.' in name_lower else ''
                    
                    logger.info(f"Processing file: {filename}")
                    
                    try:
                        file_bytes = zf.read(filename)
                        
                        if ext == 'xml':
                            # Process XML file (per-member cache: the same XML
                            # inside another archive is not parsed twice)
                            file_data = self.parse_xml_cached(file_bytes)
                            profile.merge_data(file_data)
                        elif ext in ['xls', 'xlsx']:
                            # Process Excel file
                            file_data = self._parse_mislaka_excel(file_bytes, filename, ext)
                            if file_data:
                                profile.merge_data(file_data)
                        elif ext == 'csv':
                            # Process CSV file
                            file_data = self._parse_mislaka_csv(file_bytes, filename)
                            if file_data:
                                profile.merge_data(file_data)
                    except Exception as e:
                        logger.error(f"Error processing {filename}: {e}")
                        profile.anomalies.append(f"Failed to parse {filename}: {str(e)}")
        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file format")
        
        # Finalize profile calculations
        profile.finalize()
        
        # Convert to standard data format
        return profile.to_dict()

    def process_file(self, file_path: str) -> Dict[str, Any]:
        """Process XML file from disk."""
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Check if ZIP
        if file_path.lower().endswith('.zip') or content[:4] == b'PK\x03\x04':
            return self.process_zip_content(content)
        else:
            return self.process_xml_content(content)


# ============================================================================
# SINGLETON AND HELPERS
# ============================================================================

_pension_agent = None


def get_pension_agent() -> PensionDataAgent:
    """Get or create PensionDataAgent singleton."""
    global _pension_agent
    if _pension_agent is None:
        _pension_agent = PensionDataAgent()
    return _pension_agent


def is_pension_xml(content: bytes) -> bool:
    """Check if content appears to be Mislaka pension XML."""
    try:
        if not content.strip().startswith(b'<?xml') and not content.strip().startswith(b'<'):
            return False
        
        # Try multiple encodings
        try:
            content_str = content.decode('utf-8', errors='replace')[:5000]
        except:
            content_str = content.decode('windows-1255', errors='replace')[:5000]
        
        markers = [
            'SUG-MIMSHAK', 'SugMimshak',
            'KoteretKovetz', 'YeshutYatzran',
            'HeshbonOPolisa', 'PirteiHeshbon',
            'MISPAR-POLISA', 'MisparPolisa',
            'SHEM-YATZRAN', 'ShemYatzran',
            'HAFRASHA-OVED', 'HafrashaOved',
            'NetuneiPitzuim', 'PITZUIM',
            'YeshutLakoach', 'Mutzar',
            'MISPAR-ZIHUI-LAKOACH', 'MisparZihuiLakoach',
        ]
        
        return any(marker in content_str for marker in markers)
    except:
        return False


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _pension_agent_health() -> Dict[str, Any]:
    """Read-only probe: never instantiates the agent."""
    probe: Dict[str, Any] = {
        'status': 'ok',
        'initialized': _pension_agent is not None,
        'lxml_available': LXML_AVAILABLE,
        'stream_min_bytes': MislakaParserMixin.stream_min_bytes(),
    }
    if _pension_agent is not None:
        probe['parse_cache'] = _pension_agent.parse_cache.snapshot()
    return probe


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='pension_data_agent',
        name='Pension Data Agent (Mislaka)',
        version='1.0.0',
        module='services.pension_data_agent',
        description=(
            'Parses Israeli Mislaka clearinghouse XML/ZIP exports (holdings, '
            'severance, event, transference interfaces), aggregates a client '
            'profile, and renders Hebrew/English pension reports.'
        ),
        entry_url='/risk-reports-dashboard.html',
        api={'method': 'POST', 'path': '/api/mislaka/import'},
        roles=('admin', 'underwriter', 'actuary'),
        deterministic=True,
        sample_prompts=(
            'Import this Mislaka ZIP and summarise the pension holdings',
        ),
    ), health_fn=_pension_agent_health)
except Exception as _reg_exc:  # pragma: no cover
    logger.warning("pension data agent registration skipped: %s", _reg_exc)


__all__ = ['PensionDataAgent', 'get_pension_agent', 'is_pension_xml', 'LXML_AVAILABLE',
           'MislakaSchemaMapping', 'ClientProfile']
