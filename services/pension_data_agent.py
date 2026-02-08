"""
Pension Data Agent Service - Enhanced Mislaka Support
=====================================================
Processes Israeli pension and insurance XML data files according to
the Mislaka (מסלקה) interface standards based on official XSD schemas.

Based on ChatGPT analysis of:
- mivneachid_holdings_kupotgemel_xsd_schema_009.xsd
- mivneachid_holdings_karnotpensiavatikot_xsd_schema_009.xsd
- mivneachid_holdings_karnotpensiahadashot_xsd_schema_009.xsd
- mivneachid_holdings_hevrotbituah_xsd_schema_009.xsd
- mivneachid_mimshak_pitzuim_xsd_schema_9300-9306_005.XSD
- Holdings Interface V9.7.7
- Severance Interface V5.9.38
- Event Interface V7.6.30
- Transference Interface V3.7.2

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
- Full XSD schema field mappings from official Mislaka specs
- Automatic interface type and product type detection via SUG-MIMSHAK
- Comprehensive Hebrew field extraction with proper encoding
- Data enrichment with financial metrics
- Professional report generation matching Mislaka standards (like PDF format)
- AI-powered recommendations
- ClientProfile aggregation for multiple XML files in ZIP
- Section 14 (סעיף 14) analysis and rights explanation

Data Source: swiftness.co.il / Mislaka clearinghouse
Author: PHINS Platform
"""

import os
import json
import io
import re
import zipfile
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict, field

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import lxml for better XML handling
try:
    from lxml import etree
    LXML_AVAILABLE = True
except ImportError:
    import xml.etree.ElementTree as etree
    LXML_AVAILABLE = False


# ============================================================================
# MISLAKA SCHEMA MAPPINGS - Based on official XSD schemas
# ============================================================================

class MislakaSchemaMapping:
    """
    Field mappings from Mislaka XSD schemas based on ChatGPT analysis.
    Based on:
    - mivneachid_holdings_*.xsd (v9.7.7)
    - mivneachid_mimshak_pitzuim_*.XSD (v5.9.38)
    - Holdings Interface V9.7.7 Excel specs
    - Severance Interface V5.9.38 Excel specs
    """
    
    # Interface type codes (SUG-MIMSHAK)
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
        6: {'name': 'Events', 'he': 'אירועים', 'schema': 'events_v7'},
        21: {'name': 'Events', 'he': 'אירועים', 'schema': 'events_v7'},
        
        # Transference interface
        22: {'name': 'Transference', 'he': 'העברה', 'schema': 'transference_v3'},
        33: {'name': 'Transference', 'he': 'העברה', 'schema': 'transference_v3'},
    }
    
    # Product type codes (SUG-MUTZAR / KOD-SUG-MUTZAR)
    PRODUCT_TYPE_CODES = {
        # Pension funds - קרנות פנסיה
        '1': {'name': 'pension_fund_new', 'he': 'קרן פנסיה חדשה', 'en': 'New Pension Fund'},
        '2': {'name': 'pension_fund_old', 'he': 'קרן פנסיה ותיקה', 'en': 'Old Pension Fund'},
        '3': {'name': 'pension_fund_comprehensive', 'he': 'קרן פנסיה מקיפה', 'en': 'Comprehensive Pension'},
        
        # Provident funds (Gemel) - קופות גמל
        '4': {'name': 'provident_fund', 'he': 'קופת גמל', 'en': 'Provident Fund'},
        '5': {'name': 'central_severance_fund', 'he': 'קופה מרכזית לפיצויים', 'en': 'Central Severance Fund'},
        '6': {'name': 'education_fund', 'he': 'קרן השתלמות', 'en': 'Education Fund'},
        
        # Insurance - ביטוח
        '7': {'name': 'managers_insurance', 'he': 'ביטוח מנהלים', 'en': 'Managers Insurance'},
        '8': {'name': 'life_insurance', 'he': 'ביטוח חיים', 'en': 'Life Insurance'},
        '9': {'name': 'pension_insurance', 'he': 'ביטוח פנסיוני', 'en': 'Pension Insurance'},
        
        # Others
        '10': {'name': 'savings_policy', 'he': 'פוליסת חיסכון', 'en': 'Savings Policy'},
        '11': {'name': 'risk_insurance', 'he': 'ביטוח ריסק', 'en': 'Risk Insurance'},
        '12': {'name': 'disability_insurance', 'he': 'ביטוח אובדן כושר עבודה', 'en': 'Disability Insurance'},
    }
    
    # Status codes (STATUS-POLISA-O-CHESHBON)
    STATUS_CODES = {
        '1': {'name': 'active', 'he': 'פעיל', 'en': 'Active'},
        '2': {'name': 'frozen', 'he': 'מוקפא', 'en': 'Frozen'},
        '3': {'name': 'closed', 'he': 'סגור', 'en': 'Closed'},
        '4': {'name': 'paid_up', 'he': 'משולם', 'en': 'Paid Up'},
        '5': {'name': 'transferred', 'he': 'הועבר', 'en': 'Transferred'},
        '6': {'name': 'pending', 'he': 'בהמתנה', 'en': 'Pending'},
    }
    
    # Environment codes (KOD-SVIVAT-AVODA)
    ENVIRONMENT_CODES = {
        '1': 'Test',
        '2': 'Production',
    }
    
    # Sender/Recipient type codes (KOD-SHOLECH / KOD-NIMAAN)
    ENTITY_TYPE_CODES = {
        '1': {'he': 'יצרן', 'en': 'Provider/Institution'},
        '2': {'he': 'מסלקה', 'en': 'Clearinghouse'},
        '3': {'he': 'מפיץ/סוכן', 'en': 'Distributor/Agent'},
        '4': {'he': 'עמית/חוסך', 'en': 'Saver/Client'},
        '5': {'he': 'מעסיק', 'en': 'Employer'},
        '6': {'he': 'לשכת שירות', 'en': 'Service Bureau'},
    }
    
    # ID type codes (SUG-MEZAHE-SHOLECH / SUG-ZIHUI-LAKOACH)
    ID_TYPE_CODES = {
        '1': {'he': 'ח.פ (חברה)', 'en': 'Company ID'},
        '2': {'he': 'ח.צ (שותפות)', 'en': 'Partnership ID'},
        '3': {'he': 'תעודת זהות', 'en': 'ID Card'},
        '4': {'he': 'דרכון', 'en': 'Passport'},
        '5': {'he': 'רישיון עסק', 'en': 'Business License'},
        '7': {'he': 'עמותה', 'en': 'Non-profit'},
        '8': {'he': 'אגודה שיתופית', 'en': 'Cooperative'},
        '9': {'he': 'חברה ממשלתית', 'en': 'Government Company'},
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
        'KOD-SVIVAT-AVODA': 'environment',
        'KodSvivatAvoda': 'environment',
        'KOD-SHOLEACH': 'sender_type',
        'KodSholeach': 'sender_type',
        'SUG-MEZAHE-SHOLECH': 'sender_id_type',
        'SugMezaheSholech': 'sender_id_type',
        'MISPAR-ZIHUI-SHOLECH': 'sender_id',
        'MisparZihuiSholech': 'sender_id',
        'SHEM-SHOLEACH': 'sender_name',
        'ShemSholeach': 'sender_name',
        'KOD-NIMAAN': 'recipient_type',
        'KodNimaan': 'recipient_type',
        'SHEM-MEKABEL': 'receiver_name',
        'ShemMekabel': 'receiver_name',
    }
    
    # Client field mappings (YeshutLakoach)
    CLIENT_FIELDS = {
        'MISPAR-ZIHUI-LAKOACH': 'id_number',
        'MisparZihuiLakoach': 'id_number',
        'MISPARZEHUT': 'id_number',
        'MisparZehut': 'id_number',
        'MISPAR-ZIHUY-MITPATZEACH': 'id_number',
        'MisparZihuiMitpatcheach': 'id_number',
        'SUG-ZIHUI-LAKOACH': 'id_type',
        'SugZihuiLakoach': 'id_type',
        'SugZihuiMitpatcheach': 'id_type',
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
        'KOD-MEZAHE-YATZRAN': 'code',
        'KodMezaheYatzran': 'code',
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
        'MISPAR-CHESHBON': 'policy_number',
        'MisparCheshbon': 'policy_number',
        
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
        'YITROT': 'total_balance',
        'Yitrot': 'total_balance',
        'SCHUM-HATZBARA': 'total_balance',
        'SchumHatzbara': 'total_balance',
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
        'MPR-MAASIK-BE-YATZRAN': 'employer_internal_id',
        'MprMaasikBeYatzran': 'employer_internal_id',
        
        # Coverage (for insurance)
        'SACH-KISUY': 'coverage_amount',
        'SachKisuy': 'coverage_amount',
        'KITZBA-CHODSHIT': 'monthly_pension',
        'KitzbaChodshit': 'monthly_pension',
        'KISUY-MAVET': 'death_coverage',
        'KisuyMavet': 'death_coverage',
        'KISUY-NECHUT': 'disability_coverage',
        'KisuyNechut': 'disability_coverage',
        
        # Section 14
        'SEIF-14': 'section14',
        'Seif14': 'section14',
        'ARTICLE14': 'section14',
        'article14': 'section14',
        'SI14': 'section14',
        'SACHIF-14': 'section14',
        'TAARICH-SEIF-14': 'section14_date',
        'TaarichSeif14': 'section14_date',
    }
    
    # Contribution field mappings (NetuneiHafrasha / PirteiHafrasha)
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
        'ERECH-PIDYON-PITZUIM-MAASEK-NOCHECHI': 'total_severance',
        'PITZUIM-LMSHICHA': 'available_severance',
        'PitzuimLmshicha': 'available_severance',
        'PITZUIM-SEIF14': 'section14_amount',
        'PitzuimSeif14': 'section14_amount',
        
        'SEIF-14': 'section14',
        'article14': 'section14',
        'ARTICLE14': 'section14',
        'ACHUZ-SEIF-14': 'section14_percentage',
        'AchuzSeif14': 'section14_percentage',
        
        'TAARICH-TCHILAT-AVODA': 'employment_start',
        'TaarichTchilatAvoda': 'employment_start',
        'TAARICH-SIUM-AVODA': 'employment_end',
        'TaarichSiumAvoda': 'employment_end',
    }
    
    # Known insurance company codes
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
        '12': 'אקסא',
    }
    
    # Known pension fund codes
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
# CLIENT PROFILE - Aggregated data from multiple XML files
# ============================================================================

@dataclass
class ClientProfile:
    """
    Aggregated client profile containing all data from multiple Mislaka sources.
    Used for ZIP files containing multiple XML files.
    """
    # Basic client info
    client_name: str = ""
    client_id: str = ""
    id_type: str = ""
    birth_date: str = ""
    gender: str = ""
    address: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    
    # Accounts and holdings
    accounts: List[Dict] = field(default_factory=list)
    
    # Severance details
    severance_balance: float = 0.0
    section14: bool = False
    section14_date: str = ""
    
    # Contributions/events
    contributions: List[Dict] = field(default_factory=list)
    events: List[Dict] = field(default_factory=list)
    
    # Employers
    employers: Set[str] = field(default_factory=set)
    
    # Providers
    providers: Set[str] = field(default_factory=set)
    
    # Derived metrics
    total_balance: float = 0.0
    total_savings: float = 0.0
    total_severance: float = 0.0
    total_coverage: float = 0.0
    
    # Metadata
    last_update: str = ""
    file_count: int = 0
    interface_types: Set[str] = field(default_factory=set)
    
    # Anomalies/alerts
    anomalies: List[str] = field(default_factory=list)
    
    def merge_data(self, data: Dict[str, Any]):
        """Merge data from a single parsed file into this profile."""
        # Merge client info
        client = data.get('client', {})
        if client:
            if isinstance(client, list) and client:
                client = client[0]
            
            if client.get('id_number'):
                if self.client_id and self.client_id != client['id_number']:
                    self.anomalies.append(f"ID mismatch: {self.client_id} vs {client['id_number']}")
                else:
                    self.client_id = client['id_number']
            
            if client.get('full_name'):
                self.client_name = client['full_name']
            elif client.get('first_name') or client.get('last_name'):
                self.client_name = f"{client.get('first_name', '')} {client.get('last_name', '')}".strip()
            
            if client.get('id_type'):
                self.id_type = client['id_type']
            if client.get('birth_date'):
                self.birth_date = client['birth_date']
            if client.get('phone'):
                self.phone = client['phone']
            if client.get('email'):
                self.email = client['email']
        
        # Merge accounts
        for acct in data.get('accounts', []):
            self.accounts.append(acct)
            if acct.get('provider'):
                self.providers.add(acct['provider'])
            if acct.get('employer_name'):
                self.employers.add(acct['employer_name'])
        
        # Merge contributions
        for contrib in data.get('contributions', []):
            self.contributions.append(contrib)
            if contrib.get('employer_name'):
                self.employers.add(contrib['employer_name'])
        
        # Merge severance
        for sev in data.get('severance', []):
            if sev.get('total_severance'):
                self.severance_balance += float(sev['total_severance'] or 0)
            if sev.get('section14'):
                self.section14 = True
            if sev.get('employer_name'):
                self.employers.add(sev['employer_name'])
        
        # Merge providers from providers list
        for prov in data.get('providers', []):
            if prov.get('name'):
                self.providers.add(prov['name'])
        
        # Update metadata
        header = data.get('header', {})
        if header.get('report_date') or header.get('created_at'):
            file_date = header.get('report_date') or header.get('created_at')
            if not self.last_update or file_date > self.last_update:
                self.last_update = file_date
        
        if data.get('interface_type'):
            self.interface_types.add(data['interface_type'])
        
        self.file_count += 1
    
    def finalize(self):
        """Compute derived totals after all merges."""
        self.total_balance = 0.0
        self.total_savings = 0.0
        self.total_severance = 0.0
        self.total_coverage = 0.0
        
        for acct in self.accounts:
            self.total_balance += float(acct.get('total_balance', 0) or 0)
            self.total_savings += float(acct.get('savings_balance', 0) or 0)
            self.total_severance += float(acct.get('severance_balance', 0) or 0)
            self.total_coverage += float(acct.get('coverage_amount', 0) or 0)
            
            # Check for Section 14
            if acct.get('section14'):
                self.section14 = True
        
        # Add external severance balance
        self.total_severance += self.severance_balance
        
        # Check for anomalies
        if self.total_balance < 0:
            self.anomalies.append("Total balance is negative")
        if not self.accounts:
            self.anomalies.append("No accounts found")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'client': {
                'full_name': self.client_name,
                'id_number': self.client_id,
                'id_type': self.id_type,
                'birth_date': self.birth_date,
                'phone': self.phone,
                'email': self.email,
            },
            'accounts': self.accounts,
            'contributions': self.contributions,
            'severance': [{
                'total_severance': self.total_severance,
                'section14': self.section14,
            }],
            'providers': list(self.providers),
            'employers': list(self.employers),
            'totals': {
                'total_balance': self.total_balance,
                'total_balance_formatted': f"₪{self.total_balance:,.2f}",
                'total_savings': self.total_savings,
                'total_savings_formatted': f"₪{self.total_savings:,.2f}",
                'total_severance': self.total_severance,
                'total_severance_formatted': f"₪{self.total_severance:,.2f}",
                'total_coverage': self.total_coverage,
                'account_count': len(self.accounts),
                'provider_count': len(self.providers),
                'providers': list(self.providers),
                'section14_coverage': self.section14,
            },
            'header': {
                'report_date': self.last_update,
                'file_count': self.file_count,
                'interface_types': list(self.interface_types),
            },
            'anomalies': self.anomalies,
        }


# ============================================================================
# PENSION DATA AGENT - Main processing class
# ============================================================================

class PensionDataAgent:
    """
    Enhanced Pension Data Agent for processing Mislaka (מסלקה) XML/ZIP data.
    Based on ChatGPT analysis of official XSD schemas and interface specs.
    """
    
    def __init__(self, schema_dir: str = None):
        """Initialize the agent with optional schema directory."""
        self.schema_dir = schema_dir or os.path.join(os.path.dirname(__file__), 'schemas')
        self.schema_mapping = MislakaSchemaMapping()
        self.schema_cache = {}
    
    def process_xml_content(self, xml_content: bytes) -> Dict[str, Any]:
        """
        Process a single XML content and generate report.
        
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
            'interface_type': data.get('interface_type', 'Unknown'),
            'schema_version': data.get('header', {}).get('schema_version', 'Unknown'),
        }
    
    def process_zip_content(self, zip_content: bytes) -> Dict[str, Any]:
        """
        Process a ZIP file containing multiple Mislaka XML files.
        
        Args:
            zip_content: Raw ZIP file bytes
            
        Returns:
            Dictionary with aggregated data and generated report
        """
        profile = ClientProfile()
        
        try:
            with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
                for filename in zf.namelist():
                    # Skip non-XML files and hidden files
                    if not filename.lower().endswith('.xml'):
                        continue
                    if filename.startswith('__') or filename.startswith('.'):
                        continue
                    
                    logger.info(f"Processing file: {filename}")
                    
                    try:
                        xml_bytes = zf.read(filename)
                        file_data = self._parse_mislaka_xml(xml_bytes)
                        profile.merge_data(file_data)
                    except Exception as e:
                        logger.error(f"Error processing {filename}: {e}")
                        profile.anomalies.append(f"Failed to parse {filename}: {str(e)}")
        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file format")
        
        # Finalize profile calculations
        profile.finalize()
        
        # Convert to standard data format
        data = profile.to_dict()
        
        # Enrich with health score
        data = self._enrich_data(data)
        
        # Generate report
        report = self._generate_professional_report(data)
        
        return {
            'data': data,
            'report': report,
            'language': 'hebrew',
            'interface_type': ', '.join(profile.interface_types) if profile.interface_types else 'Unknown',
            'file_count': profile.file_count,
        }
    
    def _parse_mislaka_xml(self, xml_content: bytes) -> Dict[str, Any]:
        """Parse Mislaka XML into structured data with proper encoding handling."""
        # Try to parse with automatic encoding detection
        try:
            if LXML_AVAILABLE:
                parser = etree.XMLParser(recover=True, encoding='utf-8')
                root = etree.fromstring(xml_content, parser)
            else:
                # Try UTF-8 first
                try:
                    root = etree.fromstring(xml_content.decode('utf-8', errors='replace'))
                except:
                    # Fall back to Windows-1255 (Hebrew)
                    root = etree.fromstring(xml_content.decode('windows-1255', errors='replace'))
        except Exception as e:
            # Last resort: try Windows-1255
            try:
                text = xml_content.decode('windows-1255', errors='replace')
                root = etree.fromstring(text)
            except Exception as e2:
                raise ValueError(f"Failed to parse XML: {e2}")
        
        data = {
            'header': {},
            'client': {},
            'providers': [],
            'accounts': [],
            'contributions': [],
            'severance': [],
            'employers': [],
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
        data['severance'] = self._parse_severance(root, interface_code)
        
        # Parse employers
        data['employers'] = self._parse_employers(root, accounts)
        
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
        
        # Format dates
        if header.get('created_at') and len(header['created_at']) == 14:
            try:
                dt = datetime.strptime(header['created_at'], '%Y%m%d%H%M%S')
                header['created_at_formatted'] = dt.strftime('%d/%m/%Y %H:%M')
            except:
                pass
        
        return header
    
    def _parse_client(self, root) -> Dict[str, Any]:
        """Parse client (YeshutLakoach) from XML."""
        client = {}
        
        # Try multiple element names
        client_tags = ['YeshutLakoach', 'YeshutLakohach', 'Lakoach', 'Mevutach', 'Client', 'ClientDetails']
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
        
        # Translate ID type
        if client.get('id_type'):
            id_type_info = self.schema_mapping.ID_TYPE_CODES.get(client['id_type'], {})
            client['id_type_name'] = id_type_info.get('he', client['id_type'])
        
        return client
    
    def _parse_providers_and_accounts(self, root) -> Tuple[List[Dict], List[Dict]]:
        """Parse providers (YeshutYatzran) and accounts (HeshbonOPolisa)."""
        providers = []
        accounts = []
        
        # Find all providers
        for provider_elem in root.findall('.//YeshutYatzran'):
            provider = {}
            
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
                account_tags = ['HeshbonOPolisa', 'PirteiHeshbon', 'Account', 'Policy', 'Plan', 'ReshimatKupa']
                for tag in account_tags:
                    for account_elem in product_elem.findall(f'.//{tag}'):
                        account = self._parse_account(account_elem, provider, product_info)
                        if account:
                            accounts.append(account)
        
        # Also find standalone accounts
        standalone_tags = ['HeshbonOPolisa', 'Account', 'Policy']
        for tag in standalone_tags:
            for account_elem in root.findall(f'.//{tag}'):
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
                                  'monthly_pension', 'management_fee_savings', 'management_fee_deposits',
                                  'death_coverage', 'disability_coverage']:
                    account[field_name] = self._parse_number(value)
                elif field_name == 'section14':
                    account[field_name] = value in ['1', 'כן', 'true', 'True', 'Y', 'yes']
                else:
                    account[field_name] = value
        
        # Translate product type
        product_type_code = account.get('product_type_code', '') or account.get('product_type', '')
        if product_type_code in self.schema_mapping.PRODUCT_TYPE_CODES:
            type_info = self.schema_mapping.PRODUCT_TYPE_CODES[product_type_code]
            account['product_type_name'] = type_info['he']
            account['product_type_en'] = type_info['en']
        
        # Translate status
        status_code = account.get('status_code', '')
        if status_code in self.schema_mapping.STATUS_CODES:
            status_info = self.schema_mapping.STATUS_CODES[status_code]
            account['status'] = status_info['he']
            account['status_en'] = status_info['en']
        elif not account.get('status'):
            account['status'] = 'פעיל'
            account['status_en'] = 'Active'
        
        return account
    
    def _parse_contributions(self, root) -> List[Dict[str, Any]]:
        """Parse contributions (NetuneiHafrasha / PirteiHafrasha)."""
        contributions = []
        
        contrib_tags = ['NetuneiHafrasha', 'PirteiHafrasha', 'Hafrasha', 'ReshimatHafrashot', 'Peula', 'Event', 'Transaction']
        
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
    
    def _parse_severance(self, root, interface_code: int) -> List[Dict[str, Any]]:
        """Parse severance data (NetuneiPitzuim)."""
        severance_list = []
        
        sev_tags = ['NetuneiPitzuim', 'PirteiPitzuim', 'Pitzuim', 'SeveranceDetails']
        
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
                            # Section 14 codes: 1 = Yes, 2 = No (from schema)
                            sev[field_name] = value in ['1', 'כן', 'true', 'True', 'Y', 'yes']
                        else:
                            sev[field_name] = value
                
                if sev:
                    severance_list.append(sev)
        
        return severance_list
    
    def _parse_employers(self, root, accounts: List[Dict]) -> List[Dict[str, Any]]:
        """Parse employer information."""
        employers = []
        seen = set()
        
        # Collect from accounts
        for acct in accounts:
            emp_id = acct.get('employer_id', '')
            emp_name = acct.get('employer_name', '')
            if emp_name and emp_name not in seen:
                seen.add(emp_name)
                employers.append({'id': emp_id, 'name': emp_name})
        
        # Find standalone employer elements
        for elem in root.findall('.//YeshutMaasik'):
            emp_name = self._find_text(elem, 'SHEM-MAASIK') or self._find_text(elem, 'ShemMaasik')
            emp_id = self._find_text(elem, 'KOD-MAASIK') or self._find_text(elem, 'KodMaasik')
            if emp_name and emp_name not in seen:
                seen.add(emp_name)
                employers.append({'id': emp_id, 'name': emp_name})
        
        return employers
    
    def _extract_all_elements(self, root) -> Dict[str, List[str]]:
        """Extract all text elements for additional analysis."""
        elements = {}
        
        def extract(elem, path=''):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if elem.text and elem.text.strip():
                if tag not in elements:
                    elements[tag] = []
                elements[tag].append(elem.text.strip())
            
            for child in elem:
                extract(child)
        
        extract(root)
        return elements
    
    def _find_text(self, elem, tag: str) -> Optional[str]:
        """Find text content of a tag, trying multiple naming conventions."""
        if elem is None:
            return None
        
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
            cleaned = str(value).replace(',', '').replace(' ', '')
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
        
        # Initialize totals if not present
        if 'totals' not in data:
            data['totals'] = {}
        
        totals = data['totals']
        
        # Calculate totals
        totals['total_balance'] = sum(float(a.get('total_balance', 0) or 0) for a in accounts)
        totals['total_savings'] = sum(float(a.get('savings_balance', 0) or 0) for a in accounts)
        totals['total_severance'] = sum(float(a.get('severance_balance', 0) or 0) for a in accounts)
        totals['total_severance'] += sum(float(s.get('total_severance', 0) or 0) for s in severance)
        totals['total_coverage'] = sum(float(a.get('coverage_amount', 0) or 0) for a in accounts)
        totals['account_count'] = len(accounts)
        totals['provider_count'] = len(set(a.get('provider', '') for a in accounts if a.get('provider')))
        totals['providers'] = list(set(a.get('provider', '') for a in accounts if a.get('provider')))
        
        # Format totals
        totals['total_balance_formatted'] = f"₪{totals['total_balance']:,.2f}"
        totals['total_savings_formatted'] = f"₪{totals['total_savings']:,.2f}"
        totals['total_severance_formatted'] = f"₪{totals['total_severance']:,.2f}"
        
        # Contribution analysis
        if contributions:
            total_employee = sum(float(c.get('employee_amount', 0) or 0) for c in contributions)
            total_employer = sum(float(c.get('employer_amount', 0) or 0) for c in contributions)
            total_sev_contrib = sum(float(c.get('severance_amount', 0) or 0) for c in contributions)
            
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
                    first_total = float(first.get('employee_amount', 0) or 0) + float(first.get('employer_amount', 0) or 0)
                    last_total = float(last.get('employee_amount', 0) or 0) + float(last.get('employer_amount', 0) or 0)
                    
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
        section14_severance = [s for s in severance if s.get('section14')]
        totals['section14_coverage'] = len(section14_accounts) > 0 or len(section14_severance) > 0
        totals['section14_accounts'] = len(section14_accounts)
        
        # Health score
        totals['health_score'] = self._calculate_health_score(totals)
        
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
            score['diversification'] = 70
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
        Format matches standard Israeli pension reports like the PDF example.
        """
        lines = []
        header = data.get('header', {})
        client = data.get('client', {})
        accounts = data.get('accounts', [])
        totals = data.get('totals', {})
        health = totals.get('health_score', {})
        contributions = data.get('contributions', [])
        severance = data.get('severance', [])
        
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
        if len(str(report_date)) == 8:
            try:
                formatted_date = f"{str(report_date)[6:8]}/{str(report_date)[4:6]}/{str(report_date)[:4]}"
            except:
                formatted_date = str(report_date)
        else:
            formatted_date = str(report_date)
        
        lines.extend([
            f"📅 תאריך הדו״ח: {formatted_date}",
            f"📋 סוג ממשק: {data.get('interface_type_he', 'אחזקות')} ({data.get('interface_type', 'Holdings')})",
            f"🔖 גרסת סכמה: {header.get('schema_version', 'N/A')}",
            "",
        ])
        
        # ===== CLIENT INFORMATION =====
        if client:
            client_name = client.get('full_name') or f"{client.get('first_name', '')} {client.get('last_name', '')}".strip()
            id_number = client.get('id_number', '')
            masked_id = self._mask_id(id_number) if id_number else 'לא זמין'
            
            lines.extend([
                "┌──────────────────────────────────────────────────────────────────────────┐",
                "│                        👤 פרטי לקוח / Client Details                     │",
                "└──────────────────────────────────────────────────────────────────────────┘",
                "",
                f"  שם מלא:        {client_name or 'לא זמין'}",
                f"  תעודת זהות:    {masked_id}",
            ])
            
            if client.get('id_type_name'):
                lines.append(f"  סוג זיהוי:     {client.get('id_type_name')}")
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
        if health:
            overall = health.get('overall', 0)
            rating_he = health.get('rating_he', 'לא ידוע')
            
            filled = int(overall / 10)
            empty = 10 - filled
            score_bar = '█' * filled + '░' * empty
            
            lines.extend([
                "┌──────────────────────────────────────────────────────────────────────────┐",
                "│                    🎯 ציון בריאות פיננסית / Health Score                 │",
                "└──────────────────────────────────────────────────────────────────────────┘",
                "",
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
                balance = float(acct.get('total_balance', 0) or 0)
                total_bal = totals.get('total_balance', 1) or 1
                pct = (balance / total_bal * 100) if total_bal > 0 else 0
                
                product_type = acct.get('product_type_name', acct.get('product_type', 'לא זמין'))
                
                lines.extend([
                    f"  ┌─── חשבון {i} ───────────────────────────────────────────────────────",
                    f"  │",
                    f"  │  מספר פוליסה:     {acct.get('policy_number', 'לא זמין')}",
                    f"  │  יצרן:            {acct.get('provider', 'לא זמין')}",
                    f"  │  סוג מוצר:        {product_type}",
                    f"  │  סטטוס:           {acct.get('status', 'פעיל')}",
                    f"  │",
                    f"  │  💰 יתרות:",
                    f"  │     • יתרה כוללת:  ₪{balance:,.2f} ({pct:.1f}%)",
                ])
                
                if float(acct.get('savings_balance', 0) or 0) > 0:
                    lines.append(f"  │     • חיסכון:      ₪{float(acct.get('savings_balance', 0)):,.2f}")
                if float(acct.get('severance_balance', 0) or 0) > 0:
                    lines.append(f"  │     • פיצויים:     ₪{float(acct.get('severance_balance', 0)):,.2f}")
                
                if acct.get('section14'):
                    lines.append(f"  │  📌 סעיף 14:       ✅ מכוסה")
                
                if float(acct.get('management_fee_savings', 0) or 0) > 0:
                    lines.append(f"  │  💳 דמי ניהול:     {float(acct.get('management_fee_savings', 0)):.2f}%")
                
                if acct.get('employer_name'):
                    lines.append(f"  │  🏢 מעסיק:         {acct.get('employer_name')}")
                
                # Insurance coverage
                if float(acct.get('death_coverage', 0) or 0) > 0:
                    lines.append(f"  │  🛡️ כיסוי מוות:    ₪{float(acct.get('death_coverage', 0)):,.0f}")
                if float(acct.get('disability_coverage', 0) or 0) > 0:
                    lines.append(f"  │  🛡️ כיסוי נכות:    ₪{float(acct.get('disability_coverage', 0)):,.0f}")
                
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
                "     • המעסיק אינו יכול לדרוש החזר של כספי הפיצויים",
                "",
            ])
        else:
            lines.extend([
                "  ⚠️ סטטוס: לא מכוסה תחת סעיף 14",
                "",
                "  📋 משמעות:",
                "     • פיצויי הפיטורים עשויים להיות תלויים באישור המעסיק",
                "     • בהתפטרות, המעסיק עשוי לדרוש החזר כספים",
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
            "📊 מקור: מסלקת הביטוח והפנסיה (swiftness.co.il)",
            "",
            "💡 הערה: דו״ח זה מבוסס על ניתוח אוטומטי של נתוני המסלקה.",
            "   לקבלת ייעוץ מקצועי, פנה ליועץ פנסיוני מוסמך.",
            "══════════════════════════════════════════════════════════════════════════",
        ])
        
        return '\n'.join(lines)
    
    def _generate_recommendations(self, data: Dict, totals: Dict, health: Dict) -> List[Dict]:
        """Generate AI recommendations based on comprehensive data analysis."""
        recommendations = []
        
        total_balance = totals.get('total_balance', 0)
        provider_count = totals.get('provider_count', 0)
        section14 = totals.get('section14_coverage', False)
        accounts = data.get('accounts', [])
        
        # Low savings warning
        if total_balance < 100000:
            recommendations.append({
                'priority': 'high',
                'title': 'הגדלת החיסכון הפנסיוני',
                'description': 'החיסכון הנוכחי נמוך מהמומלץ. שקול להגדיל את אחוזי ההפקדה או להפקיד סכומים נוספים באופן עצמאי.'
            })
        
        # Too many providers - consolidation
        if provider_count > 3:
            recommendations.append({
                'priority': 'medium',
                'title': 'איחוד חשבונות פנסיה',
                'description': f'יש לך חשבונות ב-{provider_count} יצרנים שונים. איחוד יכול להפחית דמי ניהול ולפשט את הניהול והמעקב.'
            })
        
        # No Section 14 coverage
        if not section14 and totals.get('total_severance', 0) > 0:
            recommendations.append({
                'priority': 'high',
                'title': 'בדיקת סעיף 14',
                'description': 'מומלץ לבדוק אפשרות להסדר סעיף 14 עם המעסיק להבטחת כספי הפיצויים והגנה במקרה של עזיבה.'
            })
        
        # Check for inactive accounts
        inactive_accounts = [a for a in accounts if a.get('status_en') in ['Frozen', 'Closed', 'Transferred']]
        if inactive_accounts:
            recommendations.append({
                'priority': 'medium',
                'title': 'בדיקת חשבונות לא פעילים',
                'description': f'נמצאו {len(inactive_accounts)} חשבונות לא פעילים. מומלץ לבדוק את מצבם ולשקול העברה או איחוד.'
            })
        
        # High management fees check
        high_fee_accounts = [a for a in accounts if float(a.get('management_fee_savings', 0) or 0) > 1.0]
        if high_fee_accounts:
            recommendations.append({
                'priority': 'medium',
                'title': 'בדיקת דמי ניהול גבוהים',
                'description': f'{len(high_fee_accounts)} חשבונות עם דמי ניהול מעל 1%. מומלץ לבדוק ולהשוות מול הצעות מתחרות.'
            })
        
        # Good standing message
        if health.get('overall', 0) >= 70:
            recommendations.append({
                'priority': 'low',
                'title': 'המשך מעקב שוטף',
                'description': 'המצב הפיננסי טוב. המשך לעקוב אחר ההפקדות ובצע בדיקה שנתית של תנאי הקופות.'
            })
        
        # Always recommend annual review
        recommendations.append({
            'priority': 'low',
            'title': 'בדיקה שנתית מקיפה',
            'description': 'מומלץ לבצע בדיקה שנתית של כל הקופות, להשוות דמי ניהול ותשואות, ולעדכן מוטבים.'
        })
        
        return recommendations[:6]
    
    def _mask_id(self, id_number: str) -> str:
        """Mask ID number for privacy."""
        if not id_number or len(id_number) < 5:
            return id_number or '***'
        return id_number[:2] + '*' * (len(id_number) - 4) + id_number[-2:]
    
    # ===== PUBLIC API =====
    
    def process_file(self, file_path: str) -> Dict[str, Any]:
        """Process XML file from disk."""
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Check if ZIP
        if file_path.lower().endswith('.zip') or content[:4] == b'PK\x03\x04':
            return self.process_zip_content(content)
        else:
            return self.process_xml_content(content)
    
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
