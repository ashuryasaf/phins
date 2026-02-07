"""
Pension Data Agent Service - Enhanced Mislaka Support
=====================================================
Processes Israeli pension and insurance XML data files according to
the Mislaka (מסלקה) interface standards based on official XSD schemas.

Supported Interfaces:
- Holdings Interface (v9.7.7):
  * kupotgemel - קופות גמל (Provident Funds)
  * karnotpensiavatikot - קרנות פנסיה ותיקות (Old Pension Funds)  
  * karnotpensiahadashot - קרנות פנסיה חדשות (New Pension Funds)
  * hevrotbituah - חברות ביטוח (Insurance Companies)

- Severance Interface (v5.9.38):
  * Interface codes 9300, 9301, 9302, 9303, 9305, 9306

- Event Interface (v7.6.30)
- Transference Interface (v3.7.2)

Features:
- Full XSD schema field mappings
- Automatic interface type and product type detection
- Comprehensive Hebrew field extraction
- Data enrichment with financial metrics
- Professional report generation matching Mislaka standards
- AI-powered recommendations

Data Source: swiftness.co.il / Mislaka clearinghouse
Author: PHINS Platform
"""

import os
import json
import io
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field

# Try to import lxml for better XML handling
try:
    from lxml import etree
    LXML_AVAILABLE = True
except ImportError:
    import xml.etree.ElementTree as etree
    LXML_AVAILABLE = False


# ============================================================================
# DATA CLASSES - Structured data models for Mislaka data
# ============================================================================

@dataclass
class MislakaHeader:
    """File header information from KoteretKovetz"""
    interface_code: int = 0
    interface_type: str = ""
    schema_version: str = ""
    file_id: str = ""
    created_at: str = ""
    report_date: str = ""
    sender_id: str = ""
    sender_name: str = ""
    receiver_id: str = ""
    receiver_name: str = ""


@dataclass
class MislakaClient:
    """Client/Person information from YeshutLakoach"""
    id_number: str = ""
    id_type: str = ""  # 1=Israeli ID, 2=Passport, etc.
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    birth_date: str = ""
    gender: str = ""
    address: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class MislakaProvider:
    """Provider/Company information from YeshutYatzran"""
    code: str = ""
    name: str = ""
    provider_type: str = ""  # Insurance company, pension fund, etc.


@dataclass
class MislakaProduct:
    """Product information from Mutzar"""
    code: str = ""
    name: str = ""
    product_type: str = ""
    product_type_code: str = ""
    sub_type: str = ""
    status: str = ""
    start_date: str = ""
    

@dataclass
class MislakaAccount:
    """Account/Policy information from HeshbonOPolisa"""
    policy_number: str = ""
    provider: str = ""
    provider_code: str = ""
    product_type: str = ""
    product_type_code: str = ""
    product_name: str = ""
    status: str = ""
    status_code: str = ""
    start_date: str = ""
    
    # Balances
    total_balance: float = 0.0
    savings_balance: float = 0.0
    severance_balance: float = 0.0
    employer_severance: float = 0.0
    compensation_balance: float = 0.0
    
    # Investment track
    investment_track: str = ""
    investment_track_code: str = ""
    
    # Management fees
    management_fee_savings: float = 0.0
    management_fee_deposits: float = 0.0
    
    # Employer info
    employer_id: str = ""
    employer_name: str = ""
    
    # Coverage info
    coverage_amount: float = 0.0
    monthly_pension: float = 0.0
    
    # Section 14
    section14: bool = False
    section14_date: str = ""


@dataclass
class MislakaContribution:
    """Contribution record from NetuneiHafrasha"""
    period: str = ""  # YYYY-MM format
    employee_id: str = ""
    employer_id: str = ""
    employer_name: str = ""
    
    # Contribution amounts
    employee_amount: float = 0.0
    employer_amount: float = 0.0
    severance_amount: float = 0.0
    total_amount: float = 0.0
    
    # Salary base
    salary_base: float = 0.0
    
    # Status
    status: str = ""
    received_date: str = ""


@dataclass
class MislakaSeverance:
    """Severance record from NetuneiPitzuim"""
    employee_id: str = ""
    policy_number: str = ""
    employer_id: str = ""
    employer_name: str = ""
    
    # Severance amounts
    total_severance: float = 0.0
    available_severance: float = 0.0
    section14_amount: float = 0.0
    
    # Section 14 status
    section14: bool = False
    section14_percentage: float = 0.0
    
    # Employment info
    employment_start: str = ""
    employment_end: str = ""


# ============================================================================
# MISLAKA SCHEMA MAPPINGS - Based on official XSD schemas
# ============================================================================

class MislakaSchemaMapping:
    """
    Field mappings from Mislaka XSD schemas.
    Based on:
    - mivneachid_holdings_*.xsd (v9.7.7)
    - mivneachid_mimshak_pitzuim_*.XSD (v5.9.38)
    """
    
    # Interface type codes
    INTERFACE_CODES = {
        # Holdings interfaces
        1: {'name': 'Holdings', 'he': 'אחזקות', 'schema': 'holdings_v9'},
        2: {'name': 'PreAdvice', 'he': 'הודעה מקדימה', 'schema': 'holdings_v9'},
        3: {'name': 'HoldingsPreAdvice', 'he': 'אחזקות + הודעה מקדימה', 'schema': 'holdings_v9'},
        
        # Severance interfaces (pitzuim)
        17: {'name': 'Severance', 'he': 'פיצויים', 'schema': 'pitzuim_v5'},
        9300: {'name': 'SeveranceRequest', 'he': 'בקשה לנתוני פיצויים', 'schema': 'pitzuim_9300'},
        9301: {'name': 'SeveranceResponse', 'he': 'תשובה לבקשת פיצויים', 'schema': 'pitzuim_9301'},
        9302: {'name': 'SeveranceQuery', 'he': 'שאילתת פיצויים', 'schema': 'pitzuim_9302'},
        9303: {'name': 'SeveranceData', 'he': 'נתוני פיצויים', 'schema': 'pitzuim_9303'},
        9305: {'name': 'SeveranceUpdate', 'he': 'עדכון פיצויים', 'schema': 'pitzuim_9305'},
        9306: {'name': 'SeveranceConfirm', 'he': 'אישור פיצויים', 'schema': 'pitzuim_9306'},
        
        # Event interface
        21: {'name': 'Events', 'he': 'אירועים', 'schema': 'events_v7'},
        
        # Transference interface
        22: {'name': 'Transference', 'he': 'העברה', 'schema': 'transference_v3'},
    }
    
    # Product type codes (SUG-MUTZAR)
    PRODUCT_TYPE_CODES = {
        # Pension funds
        '1': {'name': 'pension_fund_new', 'he': 'קרן פנסיה חדשה'},
        '2': {'name': 'pension_fund_old', 'he': 'קרן פנסיה ותיקה'},
        '3': {'name': 'pension_fund_comprehensive', 'he': 'קרן פנסיה מקיפה'},
        
        # Provident funds (Gemel)
        '4': {'name': 'provident_fund', 'he': 'קופת גמל'},
        '5': {'name': 'central_severance_fund', 'he': 'קופה מרכזית לפיצויים'},
        '6': {'name': 'education_fund', 'he': 'קרן השתלמות'},
        
        # Insurance
        '7': {'name': 'managers_insurance', 'he': 'ביטוח מנהלים'},
        '8': {'name': 'life_insurance', 'he': 'ביטוח חיים'},
        '9': {'name': 'pension_insurance', 'he': 'ביטוח פנסיוני'},
        
        # Others
        '10': {'name': 'savings_policy', 'he': 'פוליסת חיסכון'},
        '11': {'name': 'risk_insurance', 'he': 'ביטוח ריסק'},
    }
    
    # Status codes (STATUS-POLISA-O-CHESHBON)
    STATUS_CODES = {
        '1': {'name': 'active', 'he': 'פעיל'},
        '2': {'name': 'frozen', 'he': 'מוקפא'},
        '3': {'name': 'closed', 'he': 'סגור'},
        '4': {'name': 'paid_up', 'he': 'משולם'},
        '5': {'name': 'transferred', 'he': 'הועבר'},
        '6': {'name': 'pending', 'he': 'בהמתנה'},
    }
    
    # Header field mappings (KoteretKovetz)
    HEADER_FIELDS = {
        'SUG-MIMSHAK': 'interface_code',
        'SugMimshak': 'interface_code',
        'MISPAR-GIRSAT-XML': 'schema_version',
        'MisparGirsatXml': 'schema_version',
        'TAARICH-BITZUA': 'created_at',
        'TaarichBitzua': 'created_at',
        'TAARICH-HAFAKAT-HADOCH': 'report_date',
        'TaarichHafakatHadoch': 'report_date',
        'MISPAR-HAKOVETZ': 'file_id',
        'MisparHakovetz': 'file_id',
        'KOD-SHOLEACH': 'sender_id',
        'KodSholeach': 'sender_id',
        'SHEM-SHOLEACH': 'sender_name',
        'ShemSholeach': 'sender_name',
        'KOD-MEKABEL': 'receiver_id',
        'KodMekabel': 'receiver_id',
        'SHEM-MEKABEL': 'receiver_name',
        'ShemMekabel': 'receiver_name',
    }
    
    # Client field mappings (YeshutLakoach)
    CLIENT_FIELDS = {
        'MISPAR-ZIHUI-LAKOACH': 'id_number',
        'MisparZihuiLakoach': 'id_number',
        'MISPARZEHUT': 'id_number',
        'MisparZehut': 'id_number',
        'SUG-ZIHUI-LAKOACH': 'id_type',
        'SugZihuiLakoach': 'id_type',
        'SHEM-PRATI': 'first_name',
        'ShemPrati': 'first_name',
        'SHEM-MISHPACHA': 'last_name',
        'ShemMishpacha': 'last_name',
        'SHEM-LAKOACH': 'full_name',
        'ShemLakoach': 'full_name',
        'TAARICH-LEYDA': 'birth_date',
        'TaarichLeyda': 'birth_date',
        'MIN': 'gender',
        'KTOVET': 'address',
        'Ktovet': 'address',
        'YISHUV': 'city',
        'Yishuv': 'city',
        'TELEFON': 'phone',
        'Telefon': 'phone',
        'EMAIL': 'email',
        'Email': 'email',
    }
    
    # Provider field mappings (YeshutYatzran)
    PROVIDER_FIELDS = {
        'KOD-YATZRAN': 'code',
        'KodYatzran': 'code',
        'SHEM-YATZRAN': 'name',
        'ShemYatzran': 'name',
        'SUG-YATZRAN': 'provider_type',
        'SugYatzran': 'provider_type',
    }
    
    # Product field mappings (Mutzar)
    PRODUCT_FIELDS = {
        'KOD-MUTZAR': 'code',
        'KodMutzar': 'code',
        'SHEM-MUTZAR': 'name',
        'ShemMutzar': 'name',
        'SUG-MUTZAR': 'product_type',
        'SugMutzar': 'product_type',
        'KOD-SUG-MUTZAR': 'product_type_code',
        'KodSugMutzar': 'product_type_code',
        'SUG-KUPA': 'sub_type',
        'SugKupa': 'sub_type',
        'STATUS-MUTZAR': 'status',
        'StatusMutzar': 'status',
        'TAARICH-TCHILAT-MUTZAR': 'start_date',
        'TaarichTchilatMutzar': 'start_date',
    }
    
    # Account field mappings (HeshbonOPolisa / PirteiHeshbon)
    ACCOUNT_FIELDS = {
        # Policy number
        'MISPAR-POLISA-O-HESHBON': 'policy_number',
        'MisparPolisaOHeshbon': 'policy_number',
        'MISPAR-POLISA': 'policy_number',
        'MisparPolisa': 'policy_number',
        'MISPAR-HESHBON': 'policy_number',
        'MisparHeshbon': 'policy_number',
        
        # Status
        'STATUS-POLISA-O-CHESHBON': 'status_code',
        'StatusPolisaOCheshbon': 'status_code',
        'STATUS-HESHBON': 'status_code',
        'StatusHeshbon': 'status_code',
        
        # Start date
        'TAARICH-TCHILAT-HESHBON': 'start_date',
        'TaarichTchilatHeshbon': 'start_date',
        'TAARICH-TCHILAT-BITUACH': 'start_date',
        'TaarichTchilatBituach': 'start_date',
        
        # Balances
        'SALDO': 'total_balance',
        'Saldo': 'total_balance',
        'YITRA-KOLELET': 'total_balance',
        'YitraKolelet': 'total_balance',
        'YITRA-CHISACHON': 'savings_balance',
        'YitraChisachon': 'savings_balance',
        'YITRA-PITZUIM': 'severance_balance',
        'YitraPitzuim': 'severance_balance',
        'KFIFA-PITZUIM': 'severance_balance',
        'KfifaPitzuim': 'severance_balance',
        'PITZUEY-MAASIK': 'employer_severance',
        'PitzueyMaasik': 'employer_severance',
        'YITRA-TAGMULIM': 'compensation_balance',
        'YitraTagmulim': 'compensation_balance',
        
        # Investment track
        'MASLUL-HASHKAA': 'investment_track',
        'MaslulHashkaa': 'investment_track',
        'KOD-MASLUL': 'investment_track_code',
        'KodMaslul': 'investment_track_code',
        
        # Management fees
        'DMEY-NIHUL-CHISACHON': 'management_fee_savings',
        'DmeyNihulChisachon': 'management_fee_savings',
        'DMEY-NIHUL-HAFKADOT': 'management_fee_deposits',
        'DmeyNihulHafkadot': 'management_fee_deposits',
        
        # Employer
        'KOD-MAASIK': 'employer_id',
        'KodMaasik': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        'ShemMaasik': 'employer_name',
        
        # Coverage
        'SACH-KISUY': 'coverage_amount',
        'SachKisuy': 'coverage_amount',
        'KITZBA-CHODSHIT': 'monthly_pension',
        'KitzbaChodshit': 'monthly_pension',
        
        # Section 14
        'SEIF-14': 'section14',
        'Seif14': 'section14',
        'ARTICLE14': 'section14',
        'SI14': 'section14',
        'TAARICH-SEIF-14': 'section14_date',
        'TaarichSeif14': 'section14_date',
    }
    
    # Contribution field mappings (NetuneiHafrasha)
    CONTRIBUTION_FIELDS = {
        'CHODESH-DIO': 'period',
        'ChodeshDio': 'period',
        'CHODESH': 'period',
        'Chodesh': 'period',
        'TKUFA': 'period',
        'Tkufa': 'period',
        
        'MISPAR-ZIHUI-LAKOACH': 'employee_id',
        'KOD-MAASIK': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        
        'HAFRASHA-OVED': 'employee_amount',
        'HafrashaOved': 'employee_amount',
        'HAFRASHA-MAASIK': 'employer_amount',
        'HafrashaMaasik': 'employer_amount',
        'HAFRASHA-PITZUIM': 'severance_amount',
        'HafrashaPitzuim': 'severance_amount',
        'SACH-HAFRASHA': 'total_amount',
        'SachHafrasha': 'total_amount',
        
        'SACHAR-KOVEA': 'salary_base',
        'SacharKovea': 'salary_base',
        
        'STATUS-HAFRASHA': 'status',
        'StatusHafrasha': 'status',
        'TAARICH-KLITA': 'received_date',
        'TaarichKlita': 'received_date',
    }
    
    # Severance field mappings (NetuneiPitzuim)
    SEVERANCE_FIELDS = {
        'MISPAR-ZIHUI-LAKOACH': 'employee_id',
        'MISPAR-POLISA': 'policy_number',
        'KOD-MAASIK': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        
        'KSF-PITZUIM-TZVUR': 'total_severance',
        'KsfPitzuimTzvur': 'total_severance',
        'SACH-PITZUIM': 'total_severance',
        'SachPitzuim': 'total_severance',
        'PITZUIM-LMSHICHA': 'available_severance',
        'PitzuimLmshicha': 'available_severance',
        'PITZUIM-SEIF14': 'section14_amount',
        'PitzuimSeif14': 'section14_amount',
        
        'SEIF-14': 'section14',
        'ACHUZ-SEIF-14': 'section14_percentage',
        'AchuzSeif14': 'section14_percentage',
        
        'TAARICH-TCHILAT-AVODA': 'employment_start',
        'TaarichTchilatAvoda': 'employment_start',
        'TAARICH-SIUM-AVODA': 'employment_end',
        'TaarichSiumAvoda': 'employment_end',
    }
    
    # Insurance company codes (from hevrotbituah schema)
    INSURANCE_COMPANIES = {
        '1': 'מגדל',
        '2': 'הראל',
        '3': 'כלל',
        '4': 'פניקס',
        '5': 'הפניקס',
        '6': 'מנורה מבטחים',
        '7': 'איילון',
        '8': 'ביטוח ישיר',
        '9': 'שירביט',
        '10': 'הכשרה',
        '11': 'ליברה',
        '12': 'אקסה',
    }
    
    # Pension fund codes (from karnotpensiahadashot/vatikot schemas)
    PENSION_FUNDS = {
        '512': 'מיטב דש',
        '513': 'אלטשולר שחם',
        '514': 'מור',
        '515': 'הלמן אלדובי',
        '516': 'אנליסט',
        '517': 'פסגות',
        '518': 'מנורה מבטחים פנסיה',
        '519': 'הראל פנסיה',
        '520': 'מגדל מקפת',
        '521': 'כלל פנסיה',
    }


# ============================================================================
# PENSION DATA AGENT - Main processing class
# ============================================================================

class PensionDataAgent:
    """
    Enhanced Pension Data Agent for processing Mislaka (מסלקה) XML data.
    
    Handles all interface types from the Israeli pension clearinghouse:
    - Holdings (אחזקות) - Account balances and holdings
    - Severance (פיצויים) - Severance pay data
    - Events (אירועים) - Policy events
    - Transference (העברה) - Transfer between providers
    
    Generates professional reports matching Mislaka standards.
    """
    
    def __init__(self, schema_dir: str = None):
        """Initialize the agent with optional schema directory."""
        self.schema_dir = schema_dir or os.path.join(os.path.dirname(__file__), 'schemas')
        self.schema_mapping = MislakaSchemaMapping()
        self.schema_cache = {}
        
        # Load schemas if available
        self._load_schemas()
    
    def _load_schemas(self):
        """Load XSD schemas for validation."""
        if not os.path.isdir(self.schema_dir):
            return
        
        schema_files = {
            'holdings_v9': 'mivneachid_holdings_*.xsd',
            'pitzuim_v5': 'mivneachid_mimshak_pitzuim_*.XSD',
        }
        
        # Schema loading is optional - we can parse without validation
        pass
    
    def process_xml_content(self, xml_content: bytes) -> Dict[str, Any]:
        """
        Main entry point - process XML content and generate report.
        
        Args:
            xml_content: Raw XML bytes from Mislaka file
            
        Returns:
            Dictionary with parsed data and generated report
        """
        # Parse XML
        data = self._parse_mislaka_xml(xml_content)
        
        # Enrich with derived metrics
        data = self._enrich_data(data)
        
        # Generate professional report
        report = self._generate_professional_report(data)
        
        return {
            'data': data,
            'report': report,
            'language': 'hebrew',
            'interface_type': data.get('header', {}).get('interface_type', 'Unknown'),
            'schema_version': data.get('header', {}).get('schema_version', 'Unknown'),
        }
    
    def _parse_mislaka_xml(self, xml_content: bytes) -> Dict[str, Any]:
        """
        Parse Mislaka XML into structured data.
        """
        # Parse XML
        try:
            if LXML_AVAILABLE:
                parser = etree.XMLParser(recover=True, encoding='utf-8')
                root = etree.fromstring(xml_content, parser)
            else:
                root = etree.fromstring(xml_content.decode('utf-8', errors='replace'))
        except Exception as e:
            raise ValueError(f"Failed to parse XML: {e}")
        
        data = {
            'header': {},
            'client': {},
            'providers': [],
            'accounts': [],
            'contributions': [],
            'severance': [],
            'totals': {},
            'raw_elements': {}
        }
        
        # Parse header
        data['header'] = self._parse_header(root)
        
        # Determine interface type
        interface_code = data['header'].get('interface_code', 1)
        data['interface_code'] = interface_code
        interface_info = self.schema_mapping.INTERFACE_CODES.get(
            interface_code, 
            {'name': f'Type{interface_code}', 'he': f'סוג {interface_code}'}
        )
        data['interface_type'] = interface_info['name']
        data['interface_type_he'] = interface_info['he']
        
        # Parse client
        data['client'] = self._parse_client(root)
        
        # Parse providers and accounts
        providers, accounts = self._parse_providers_and_accounts(root)
        data['providers'] = providers
        data['accounts'] = accounts
        
        # Parse contributions
        data['contributions'] = self._parse_contributions(root)
        
        # Parse severance data
        data['severance'] = self._parse_severance(root)
        
        # Extract all raw text elements for additional analysis
        data['raw_elements'] = self._extract_all_elements(root)
        
        return data
    
    def _parse_header(self, root) -> Dict[str, Any]:
        """Parse header (KoteretKovetz) from XML."""
        header = {}
        
        # Find header element
        header_elem = root.find('.//KoteretKovetz')
        if header_elem is None:
            header_elem = root.find('.//Header')
        if header_elem is None:
            header_elem = root
        
        # Extract fields using mapping
        for xml_tag, field_name in self.schema_mapping.HEADER_FIELDS.items():
            value = self._find_text(header_elem, xml_tag)
            if value:
                if field_name == 'interface_code':
                    try:
                        header[field_name] = int(value)
                    except:
                        header[field_name] = 1
                else:
                    header[field_name] = value
        
        # Add interface type name
        interface_code = header.get('interface_code', 1)
        interface_info = self.schema_mapping.INTERFACE_CODES.get(interface_code, {})
        header['interface_type'] = interface_info.get('name', f'Type{interface_code}')
        header['interface_type_he'] = interface_info.get('he', f'סוג {interface_code}')
        
        return header
    
    def _parse_client(self, root) -> Dict[str, Any]:
        """Parse client (YeshutLakoach) from XML."""
        client = {}
        
        # Try multiple element names
        client_tags = ['YeshutLakoach', 'YeshutLakohach', 'Lakoach', 'Mevutach', 'Client']
        client_elem = None
        
        for tag in client_tags:
            client_elem = root.find(f'.//{tag}')
            if client_elem is not None:
                break
        
        if client_elem is None:
            return client
        
        # Extract fields
        for xml_tag, field_name in self.schema_mapping.CLIENT_FIELDS.items():
            value = self._find_text(client_elem, xml_tag)
            if value:
                client[field_name] = value
        
        # Build full name if not present
        if not client.get('full_name') and (client.get('first_name') or client.get('last_name')):
            parts = [client.get('first_name', ''), client.get('last_name', '')]
            client['full_name'] = ' '.join(p for p in parts if p)
        
        return client
    
    def _parse_providers_and_accounts(self, root) -> Tuple[List[Dict], List[Dict]]:
        """Parse providers (YeshutYatzran) and accounts (HeshbonOPolisa)."""
        providers = []
        accounts = []
        
        # Find all providers
        for provider_elem in root.findall('.//YeshutYatzran'):
            provider = {}
            
            # Extract provider fields
            for xml_tag, field_name in self.schema_mapping.PROVIDER_FIELDS.items():
                value = self._find_text(provider_elem, xml_tag)
                if value:
                    provider[field_name] = value
            
            if provider:
                providers.append(provider)
            
            # Find products under this provider
            for product_elem in provider_elem.findall('.//Mutzar'):
                product_info = {}
                
                for xml_tag, field_name in self.schema_mapping.PRODUCT_FIELDS.items():
                    value = self._find_text(product_elem, xml_tag)
                    if value:
                        product_info[field_name] = value
                
                # Find accounts under this product
                for account_elem in product_elem.findall('.//HeshbonOPolisa'):
                    account = self._parse_account(account_elem, provider, product_info)
                    if account:
                        accounts.append(account)
                
                # Also check PirteiHeshbon
                for account_elem in product_elem.findall('.//PirteiHeshbon'):
                    account = self._parse_account(account_elem, provider, product_info)
                    if account:
                        accounts.append(account)
        
        # Also find standalone accounts
        for account_elem in root.findall('.//HeshbonOPolisa'):
            # Check if already processed
            policy_num = self._find_text(account_elem, 'MISPAR-POLISA-O-HESHBON')
            if policy_num and not any(a.get('policy_number') == policy_num for a in accounts):
                account = self._parse_account(account_elem, {}, {})
                if account:
                    accounts.append(account)
        
        return providers, accounts
    
    def _parse_account(self, elem, provider: Dict, product_info: Dict) -> Dict[str, Any]:
        """Parse a single account element."""
        account = {
            'provider': provider.get('name', ''),
            'provider_code': provider.get('code', ''),
            'product_type': product_info.get('product_type', ''),
            'product_type_code': product_info.get('product_type_code', ''),
            'product_name': product_info.get('name', ''),
        }
        
        # Extract account fields
        for xml_tag, field_name in self.schema_mapping.ACCOUNT_FIELDS.items():
            value = self._find_text(elem, xml_tag)
            if value:
                # Convert numeric fields
                if field_name in ['total_balance', 'savings_balance', 'severance_balance',
                                  'employer_severance', 'compensation_balance', 'coverage_amount',
                                  'monthly_pension', 'management_fee_savings', 'management_fee_deposits']:
                    account[field_name] = self._parse_number(value)
                elif field_name == 'section14':
                    account[field_name] = value in ['1', 'כן', 'true', 'True', 'Y']
                else:
                    account[field_name] = value
        
        # Translate product type
        product_type_code = account.get('product_type_code', '')
        if product_type_code in self.schema_mapping.PRODUCT_TYPE_CODES:
            type_info = self.schema_mapping.PRODUCT_TYPE_CODES[product_type_code]
            account['product_type_name'] = type_info['he']
            account['product_type_en'] = type_info['name']
        
        # Translate status
        status_code = account.get('status_code', '')
        if status_code in self.schema_mapping.STATUS_CODES:
            status_info = self.schema_mapping.STATUS_CODES[status_code]
            account['status'] = status_info['he']
            account['status_en'] = status_info['name']
        
        return account
    
    def _parse_contributions(self, root) -> List[Dict[str, Any]]:
        """Parse contributions (NetuneiHafrasha)."""
        contributions = []
        
        contrib_tags = ['NetuneiHafrasha', 'PirteiHafrasha', 'Hafrasha', 'ReshimatHafrashot']
        
        for tag in contrib_tags:
            for elem in root.findall(f'.//{tag}'):
                contrib = {}
                
                for xml_tag, field_name in self.schema_mapping.CONTRIBUTION_FIELDS.items():
                    value = self._find_text(elem, xml_tag)
                    if value:
                        if field_name in ['employee_amount', 'employer_amount', 
                                         'severance_amount', 'total_amount', 'salary_base']:
                            contrib[field_name] = self._parse_number(value)
                        else:
                            contrib[field_name] = value
                
                if contrib:
                    contributions.append(contrib)
        
        return contributions
    
    def _parse_severance(self, root) -> List[Dict[str, Any]]:
        """Parse severance data (NetuneiPitzuim)."""
        severance_list = []
        
        sev_tags = ['NetuneiPitzuim', 'PirteiPitzuim', 'Pitzuim']
        
        for tag in sev_tags:
            for elem in root.findall(f'.//{tag}'):
                sev = {}
                
                for xml_tag, field_name in self.schema_mapping.SEVERANCE_FIELDS.items():
                    value = self._find_text(elem, xml_tag)
                    if value:
                        if field_name in ['total_severance', 'available_severance', 
                                         'section14_amount', 'section14_percentage']:
                            sev[field_name] = self._parse_number(value)
                        elif field_name == 'section14':
                            sev[field_name] = value in ['1', 'כן', 'true', 'True', 'Y']
                        else:
                            sev[field_name] = value
                
                if sev:
                    severance_list.append(sev)
        
        return severance_list
    
    def _extract_all_elements(self, root) -> Dict[str, List[str]]:
        """Extract all text elements for additional analysis."""
        elements = {}
        
        def extract(elem, path=''):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            current_path = f"{path}/{tag}" if path else tag
            
            if elem.text and elem.text.strip():
                if tag not in elements:
                    elements[tag] = []
                elements[tag].append(elem.text.strip())
            
            for child in elem:
                extract(child, current_path)
        
        extract(root)
        return elements
    
    def _find_text(self, elem, tag: str) -> Optional[str]:
        """Find text content of a tag, trying multiple naming conventions."""
        # Try exact match
        found = elem.find(f'.//{tag}')
        if found is not None and found.text:
            return found.text.strip()
        
        # Try without hyphens
        tag_no_hyphen = tag.replace('-', '')
        found = elem.find(f'.//{tag_no_hyphen}')
        if found is not None and found.text:
            return found.text.strip()
        
        # Try CamelCase
        tag_camel = ''.join(word.capitalize() for word in tag.split('-'))
        found = elem.find(f'.//{tag_camel}')
        if found is not None and found.text:
            return found.text.strip()
        
        return None
    
    def _parse_number(self, value: str) -> float:
        """Parse numeric string to float."""
        if not value:
            return 0.0
        try:
            # Remove formatting
            cleaned = value.replace(',', '').replace(' ', '')
            cleaned = cleaned.replace('₪', '').replace('$', '').replace('€', '')
            cleaned = cleaned.replace("'", '')  # Hebrew thousands separator
            return float(cleaned)
        except:
            return 0.0
    
    def _enrich_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich parsed data with calculated metrics."""
        accounts = data.get('accounts', [])
        contributions = data.get('contributions', [])
        severance = data.get('severance', [])
        
        totals = {
            'total_balance': 0.0,
            'total_savings': 0.0,
            'total_severance': 0.0,
            'total_coverage': 0.0,
            'account_count': len(accounts),
            'provider_count': len(set(a.get('provider', '') for a in accounts if a.get('provider'))),
            'providers': list(set(a.get('provider', '') for a in accounts if a.get('provider'))),
        }
        
        # Sum account balances
        for acct in accounts:
            totals['total_balance'] += acct.get('total_balance', 0)
            totals['total_savings'] += acct.get('savings_balance', 0)
            totals['total_severance'] += acct.get('severance_balance', 0)
            totals['total_coverage'] += acct.get('coverage_amount', 0)
        
        # Format totals
        totals['total_balance_formatted'] = f"₪{totals['total_balance']:,.2f}"
        totals['total_savings_formatted'] = f"₪{totals['total_savings']:,.2f}"
        totals['total_severance_formatted'] = f"₪{totals['total_severance']:,.2f}"
        
        # Contribution analysis
        if contributions:
            total_employee = sum(c.get('employee_amount', 0) for c in contributions)
            total_employer = sum(c.get('employer_amount', 0) for c in contributions)
            total_sev_contrib = sum(c.get('severance_amount', 0) for c in contributions)
            
            totals['contributions'] = {
                'employee_total': total_employee,
                'employer_total': total_employer,
                'severance_total': total_sev_contrib,
                'grand_total': total_employee + total_employer + total_sev_contrib,
                'periods_count': len(contributions),
            }
            
            # Contribution trend
            try:
                sorted_contribs = sorted(contributions, key=lambda x: x.get('period', ''))
                if len(sorted_contribs) >= 2:
                    first = sorted_contribs[0]
                    last = sorted_contribs[-1]
                    first_total = (first.get('employee_amount', 0) + first.get('employer_amount', 0))
                    last_total = (last.get('employee_amount', 0) + last.get('employer_amount', 0))
                    
                    if last_total > first_total * 1.1:
                        totals['contribution_trend'] = 'increasing'
                        totals['contribution_trend_he'] = 'עולה'
                    elif last_total < first_total * 0.9:
                        totals['contribution_trend'] = 'decreasing'
                        totals['contribution_trend_he'] = 'יורד'
                    else:
                        totals['contribution_trend'] = 'stable'
                        totals['contribution_trend_he'] = 'יציב'
            except:
                pass
        
        # Section 14 status
        section14_accounts = [a for a in accounts if a.get('section14')]
        totals['section14_coverage'] = len(section14_accounts) > 0
        totals['section14_accounts'] = len(section14_accounts)
        
        # Health score
        totals['health_score'] = self._calculate_health_score(totals)
        
        data['totals'] = totals
        return data
    
    def _calculate_health_score(self, totals: Dict) -> Dict[str, Any]:
        """Calculate financial health score."""
        score = {
            'overall': 0,
            'savings': 0,
            'diversification': 0,
            'section14': 0,
            'rating': 'unknown',
            'rating_he': 'לא ידוע',
        }
        
        total_balance = totals.get('total_balance', 0)
        provider_count = totals.get('provider_count', 0)
        
        # Savings score
        if total_balance >= 1000000:
            score['savings'] = 100
        elif total_balance >= 500000:
            score['savings'] = 80
        elif total_balance >= 200000:
            score['savings'] = 60
        elif total_balance >= 50000:
            score['savings'] = 40
        else:
            score['savings'] = 20
        
        # Diversification score
        if provider_count >= 3:
            score['diversification'] = 70  # Too many - recommend consolidation
        elif provider_count == 2:
            score['diversification'] = 90
        elif provider_count == 1:
            score['diversification'] = 70
        else:
            score['diversification'] = 50
        
        # Section 14 score
        if totals.get('section14_coverage'):
            score['section14'] = 100
        elif totals.get('total_severance', 0) > 0:
            score['section14'] = 70
        else:
            score['section14'] = 50
        
        # Overall
        score['overall'] = int(
            score['savings'] * 0.5 +
            score['diversification'] * 0.2 +
            score['section14'] * 0.3
        )
        
        if score['overall'] >= 80:
            score['rating'] = 'excellent'
            score['rating_he'] = 'מצוין'
        elif score['overall'] >= 60:
            score['rating'] = 'good'
            score['rating_he'] = 'טוב'
        elif score['overall'] >= 40:
            score['rating'] = 'fair'
            score['rating_he'] = 'סביר'
        else:
            score['rating'] = 'needs_attention'
            score['rating_he'] = 'דורש תשומת לב'
        
        return score
    
    def _generate_professional_report(self, data: Dict[str, Any]) -> str:
        """
        Generate professional Mislaka-style report.
        Format matches standard Israeli pension reports.
        """
        lines = []
        header = data.get('header', {})
        client = data.get('client', {})
        accounts = data.get('accounts', [])
        totals = data.get('totals', {})
        health = totals.get('health_score', {})
        
        # ===== REPORT HEADER =====
        lines.extend([
            "╔══════════════════════════════════════════════════════════════════════════╗",
            "║                                                                          ║",
            "║      📊 דו״ח מסלקת הביטוח והפנסיה - ניתוח מקיף                           ║",
            "║      Mislaka Pension & Insurance Clearinghouse Report                    ║",
            "║                                                                          ║",
            "╚══════════════════════════════════════════════════════════════════════════╝",
            "",
        ])
        
        # ===== REPORT INFO =====
        report_date = header.get('report_date') or header.get('created_at') or datetime.now().strftime('%Y%m%d')
        if len(report_date) == 8:
            try:
                formatted_date = f"{report_date[6:8]}/{report_date[4:6]}/{report_date[:4]}"
            except:
                formatted_date = report_date
        else:
            formatted_date = report_date
        
        lines.extend([
            f"📅 תאריך הדו״ח: {formatted_date}",
            f"📋 סוג ממשק: {data.get('interface_type_he', 'אחזקות')} ({data.get('interface_type', 'Holdings')})",
            f"🔖 גרסת סכמה: {header.get('schema_version', 'N/A')}",
            "",
        ])
        
        # ===== CLIENT INFORMATION =====
        if client:
            lines.extend([
                "┌──────────────────────────────────────────────────────────────────────────┐",
                "│                        👤 פרטי לקוח / Client Details                     │",
                "└──────────────────────────────────────────────────────────────────────────┘",
                "",
            ])
            
            client_name = client.get('full_name') or f"{client.get('first_name', '')} {client.get('last_name', '')}".strip()
            id_number = client.get('id_number', '')
            masked_id = self._mask_id(id_number) if id_number else 'לא זמין'
            
            lines.extend([
                f"  שם מלא:        {client_name or 'לא זמין'}",
                f"  תעודת זהות:    {masked_id}",
            ])
            
            if client.get('birth_date'):
                lines.append(f"  תאריך לידה:    {client.get('birth_date')}")
            if client.get('phone'):
                lines.append(f"  טלפון:         {client.get('phone')}")
            if client.get('email'):
                lines.append(f"  דוא״ל:         {client.get('email')}")
            
            lines.append("")
        
        # ===== FINANCIAL SUMMARY =====
        lines.extend([
            "┌──────────────────────────────────────────────────────────────────────────┐",
            "│                      💰 סיכום כספי / Financial Summary                   │",
            "└──────────────────────────────────────────────────────────────────────────┘",
            "",
        ])
        
        lines.extend([
            f"  ┌─────────────────────────────────────────────────────────────────────┐",
            f"  │  סה״כ נכסים:                      {totals.get('total_balance_formatted', '₪0'):>20}  │",
            f"  │  ─────────────────────────────────────────────────────────────────  │",
            f"  │    • חיסכון פנסיוני:              {totals.get('total_savings_formatted', '₪0'):>20}  │",
            f"  │    • פיצויים צבורים:              {totals.get('total_severance_formatted', '₪0'):>20}  │",
            f"  │  ─────────────────────────────────────────────────────────────────  │",
            f"  │  מספר חשבונות/פוליסות:           {totals.get('account_count', 0):>20}  │",
            f"  │  מספר יצרנים:                    {totals.get('provider_count', 0):>20}  │",
            f"  └─────────────────────────────────────────────────────────────────────┘",
            "",
        ])
        
        # ===== HEALTH SCORE =====
        lines.extend([
            "┌──────────────────────────────────────────────────────────────────────────┐",
            "│                    🎯 ציון בריאות פיננסית / Health Score                 │",
            "└──────────────────────────────────────────────────────────────────────────┘",
            "",
        ])
        
        overall = health.get('overall', 0)
        rating_he = health.get('rating_he', 'לא ידוע')
        
        # Visual score bar
        filled = int(overall / 10)
        empty = 10 - filled
        score_bar = '█' * filled + '░' * empty
        
        lines.extend([
            f"  ציון כולל: [{score_bar}] {overall}/100 ({rating_he})",
            "",
            f"  📊 פירוט ציונים:",
            f"     • חסכונות: {health.get('savings', 0)}/100",
            f"     • פיזור: {health.get('diversification', 0)}/100",
            f"     • סעיף 14: {health.get('section14', 0)}/100",
            "",
        ])
        
        # ===== PROVIDERS =====
        providers = totals.get('providers', [])
        if providers:
            lines.extend([
                "┌──────────────────────────────────────────────────────────────────────────┐",
                "│                       🏢 יצרנים / Providers                              │",
                "└──────────────────────────────────────────────────────────────────────────┘",
                "",
            ])
            
            for i, provider in enumerate(providers, 1):
                lines.append(f"  {i}. {provider}")
            lines.append("")
        
        # ===== ACCOUNT DETAILS =====
        if accounts:
            lines.extend([
                "┌──────────────────────────────────────────────────────────────────────────┐",
                "│                    📁 פירוט חשבונות / Account Details                    │",
                "└──────────────────────────────────────────────────────────────────────────┘",
                "",
            ])
            
            for i, acct in enumerate(accounts[:10], 1):
                balance = acct.get('total_balance', 0)
                total_bal = totals.get('total_balance', 1)
                pct = (balance / total_bal * 100) if total_bal > 0 else 0
                
                lines.extend([
                    f"  ┌─── חשבון {i} ───────────────────────────────────────────────────────",
                    f"  │",
                    f"  │  מספר פוליסה:     {acct.get('policy_number', 'לא זמין')}",
                    f"  │  יצרן:            {acct.get('provider', 'לא זמין')}",
                    f"  │  סוג מוצר:        {acct.get('product_type_name', acct.get('product_type', 'לא זמין'))}",
                    f"  │  סטטוס:           {acct.get('status', 'פעיל')}",
                    f"  │",
                    f"  │  💰 יתרות:",
                    f"  │     • יתרה כוללת:  ₪{balance:,.2f} ({pct:.1f}%)",
                ])
                
                if acct.get('savings_balance', 0) > 0:
                    lines.append(f"  │     • חיסכון:      ₪{acct.get('savings_balance', 0):,.2f}")
                if acct.get('severance_balance', 0) > 0:
                    lines.append(f"  │     • פיצויים:     ₪{acct.get('severance_balance', 0):,.2f}")
                
                if acct.get('section14'):
                    lines.append(f"  │  📌 סעיף 14:       ✅ מכוסה")
                
                if acct.get('management_fee_savings', 0) > 0:
                    lines.append(f"  │  💳 דמי ניהול:     {acct.get('management_fee_savings', 0):.2f}%")
                
                if acct.get('employer_name'):
                    lines.append(f"  │  🏢 מעסיק:         {acct.get('employer_name')}")
                
                lines.extend([
                    f"  │",
                    f"  └─────────────────────────────────────────────────────────────────────",
                    "",
                ])
            
            if len(accounts) > 10:
                lines.append(f"  📌 ... ועוד {len(accounts) - 10} חשבונות נוספים")
                lines.append("")
        
        # ===== CONTRIBUTION SUMMARY =====
        contrib_totals = totals.get('contributions', {})
        if contrib_totals:
            lines.extend([
                "┌──────────────────────────────────────────────────────────────────────────┐",
                "│                      📈 סיכום הפקדות / Contributions                     │",
                "└──────────────────────────────────────────────────────────────────────────┘",
                "",
            ])
            
            lines.extend([
                f"  הפקדות עובד:        ₪{contrib_totals.get('employee_total', 0):,.2f}",
                f"  הפקדות מעסיק:       ₪{contrib_totals.get('employer_total', 0):,.2f}",
                f"  הפקדות פיצויים:     ₪{contrib_totals.get('severance_total', 0):,.2f}",
                f"  ─────────────────────────────────────────",
                f"  סה״כ הפקדות:        ₪{contrib_totals.get('grand_total', 0):,.2f}",
                "",
            ])
            
            if totals.get('contribution_trend_he'):
                lines.append(f"  📊 מגמת הפקדות: {totals.get('contribution_trend_he')}")
                lines.append("")
        
        # ===== SECTION 14 STATUS =====
        lines.extend([
            "┌──────────────────────────────────────────────────────────────────────────┐",
            "│                      📌 סעיף 14 / Section 14 Status                      │",
            "└──────────────────────────────────────────────────────────────────────────┘",
            "",
        ])
        
        if totals.get('section14_coverage'):
            lines.extend([
                "  ✅ סטטוס: מכוסה תחת סעיף 14",
                "",
                "  📋 משמעות הכיסוי:",
                "     • פיצויי הפיטורין שייכים לעובד ומובטחים בקופה",
                "     • אין צורך באישור המעסיק למשיכת הפיצויים",
                "     • הכספים מוגנים גם במקרה של פיטורין",
                "",
            ])
        else:
            lines.extend([
                "  ⚠️ סטטוס: לא מכוסה תחת סעיף 14",
                "",
                "  📋 משמעות:",
                "     • פיצויי הפיטורים עשויים להיות תלויים באישור המעסיק",
                "     • מומלץ לבדוק את תנאי העסקה מול המעסיק",
                "     • שקול לבקש הסדר סעיף 14 מהמעסיק",
                "",
            ])
        
        # ===== AI RECOMMENDATIONS =====
        recommendations = self._generate_recommendations(data, totals, health)
        
        lines.extend([
            "┌──────────────────────────────────────────────────────────────────────────┐",
            "│                     🤖 המלצות AI / AI Recommendations                    │",
            "└──────────────────────────────────────────────────────────────────────────┘",
            "",
        ])
        
        for i, rec in enumerate(recommendations, 1):
            priority_icon = '🔴' if rec['priority'] == 'high' else ('🟡' if rec['priority'] == 'medium' else '🟢')
            lines.extend([
                f"  {priority_icon} המלצה {i}: {rec['title']}",
                f"     {rec['description']}",
                "",
            ])
        
        # ===== FOOTER =====
        lines.extend([
            "══════════════════════════════════════════════════════════════════════════",
            f"📅 דו״ח הופק: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            "🔒 נתוני תעודת זהות מוסתרים להגנת הפרטיות",
            "",
            "💡 הערה: דו״ח זה מבוסס על ניתוח אוטומטי של נתוני המסלקה.",
            "   לקבלת ייעוץ מקצועי, פנה ליועץ פנסיוני מוסמך.",
            "══════════════════════════════════════════════════════════════════════════",
        ])
        
        return '\n'.join(lines)
    
    def _generate_recommendations(self, data: Dict, totals: Dict, health: Dict) -> List[Dict]:
        """Generate AI recommendations based on data analysis."""
        recommendations = []
        
        total_balance = totals.get('total_balance', 0)
        provider_count = totals.get('provider_count', 0)
        section14 = totals.get('section14_coverage', False)
        
        # Low savings
        if total_balance < 100000:
            recommendations.append({
                'priority': 'high',
                'title': 'הגדלת החיסכון הפנסיוני',
                'description': 'החיסכון הנוכחי נמוך מהמומלץ. שקול להגדיל את אחוזי ההפקדה או להפקיד סכומים נוספים.'
            })
        
        # Too many providers
        if provider_count > 3:
            recommendations.append({
                'priority': 'medium',
                'title': 'איחוד חשבונות פנסיה',
                'description': f'יש לך חשבונות ב-{provider_count} יצרנים שונים. איחוד יכול להפחית דמי ניהול ולפשט את הניהול.'
            })
        
        # No Section 14
        if not section14 and totals.get('total_severance', 0) > 0:
            recommendations.append({
                'priority': 'medium',
                'title': 'בדיקת סעיף 14',
                'description': 'מומלץ לבדוק אפשרות להסדר סעיף 14 עם המעסיק להבטחת כספי הפיצויים.'
            })
        
        # Good standing
        if health.get('overall', 0) >= 70:
            recommendations.append({
                'priority': 'low',
                'title': 'המשך מעקב שוטף',
                'description': 'המצב הפיננסי טוב. המשך לעקוב אחר ההפקדות ובצע בדיקה שנתית.'
            })
        
        # Always recommend fee review
        recommendations.append({
            'priority': 'low',
            'title': 'בדיקת דמי ניהול',
            'description': 'מומלץ לבדוק את דמי הניהול ולהשוות מול הצעות מתחרות.'
        })
        
        return recommendations[:5]
    
    def _mask_id(self, id_number: str) -> str:
        """Mask ID number for privacy."""
        if not id_number or len(id_number) < 5:
            return id_number or '***'
        return id_number[:2] + '*' * (len(id_number) - 4) + id_number[-2:]
    
    # ===== PUBLIC API =====
    
    def process_file(self, file_path: str) -> Dict[str, Any]:
        """Process XML file from disk."""
        with open(file_path, 'rb') as f:
            return self.process_xml_content(f.read())
    
    def to_csv_format(self, data: Dict[str, Any]) -> Tuple[List[str], List[Dict]]:
        """Convert to CSV format for AI analysis integration."""
        columns = [
            'מספר פוליסה', 'יצרן', 'סוג מוצר', 'שם מוצר',
            'סטטוס', 'יתרה כוללת', 'חיסכון', 'פיצויים', 'מעסיק', 'סעיף 14'
        ]
        
        rows = []
        for acct in data.get('accounts', []):
            rows.append({
                'מספר פוליסה': acct.get('policy_number', ''),
                'יצרן': acct.get('provider', ''),
                'סוג מוצר': acct.get('product_type_name', acct.get('product_type', '')),
                'שם מוצר': acct.get('product_name', ''),
                'סטטוס': acct.get('status', 'פעיל'),
                'יתרה כוללת': acct.get('total_balance', 0),
                'חיסכון': acct.get('savings_balance', 0),
                'פיצויים': acct.get('severance_balance', 0),
                'מעסיק': acct.get('employer_name', ''),
                'סעיף 14': 'כן' if acct.get('section14') else 'לא'
            })
        
        # Summary row
        totals = data.get('totals', {})
        rows.append({
            'מספר פוליסה': 'סה״כ',
            'יצרן': '',
            'סוג מוצר': '',
            'שם מוצר': '',
            'סטטוס': '',
            'יתרה כוללת': totals.get('total_balance', 0),
            'חיסכון': totals.get('total_savings', 0),
            'פיצויים': totals.get('total_severance', 0),
            'מעסיק': '',
            'סעיף 14': ''
        })
        
        return columns, rows
    
    def generate_report_text(self, data: Dict[str, Any], language: str = 'hebrew') -> str:
        """Generate report text (alias for compatibility)."""
        return self._generate_professional_report(data)


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
        
        content_str = content.decode('utf-8', errors='replace')[:5000]
        
        markers = [
            'SUG-MIMSHAK', 'SugMimshak',
            'KoteretKovetz', 'YeshutYatzran',
            'HeshbonOPolisa', 'PirteiHeshbon',
            'MISPAR-POLISA', 'MisparPolisa',
            'SHEM-YATZRAN', 'ShemYatzran',
            'HAFRASHA-OVED', 'HafrashaOved',
            'NetuneiPitzuim', 'PITZUIM',
            'YeshutLakoach', 'Mutzar',
        ]
        
        return any(marker in content_str for marker in markers)
    except:
        return False
