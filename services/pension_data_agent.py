"""
Pension Data Agent Service
==========================
Processes Israeli pension and insurance XML data files according to
the Mislaka (מסלקה) interface standards.

Supports interface types:
- Type 1: Holdings (אחזקות)
- Type 2: Pre-Advice (הודעה מקדימה)
- Type 3: Holdings + Pre-Advice Combined
- Type 17: Severance (פיצויים)

Author: PHINS Platform
"""

import os
import json
import io
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict

# Try to import lxml, fall back to xml.etree if not available
try:
    from lxml import etree
    LXML_AVAILABLE = True
except ImportError:
    import xml.etree.ElementTree as etree
    LXML_AVAILABLE = False


@dataclass
class PensionAccount:
    """Represents a pension/insurance account"""
    provider: str
    product_type: str
    product_name: str
    policy_number: str
    status: str
    balance: float = 0.0
    severance_balance: float = 0.0
    employer_id: str = ""
    employer_name: str = ""


@dataclass
class Contribution:
    """Represents a contribution record"""
    employee_id: str
    name: str
    period: str
    employee_contribution: float = 0.0
    employer_contribution: float = 0.0
    severance_contribution: float = 0.0


@dataclass
class SeveranceRecord:
    """Represents severance pay information"""
    employee_id: str = ""
    policy_number: str = ""
    total_severance: float = 0.0
    employer: str = ""
    section14: bool = None


class PensionDataAgent:
    """
    Agent for processing Israeli pension and insurance XML data files.
    
    Handles the standard Mislaka (מסלקה) XML interfaces for:
    - Holdings reports
    - Contribution reports  
    - Severance (פיצויים) reports
    """
    
    # Interface type codes
    INTERFACE_TYPES = {
        1: "Holdings",           # אחזקות
        2: "PreAdvice",          # הודעה מקדימה
        3: "Holdings+PreAdvice", # משולב
        17: "Severance",         # פיצויים
        21: "Events",            # אירועים
        22: "Transference",      # העברה
    }
    
    # Hebrew field mappings
    HEBREW_FIELD_MAP = {
        # Header fields
        'SUG-MIMSHAK': 'interface_type',
        'MISPAR-GIRSAT-XML': 'schema_version',
        'TAARICH-BITZUA': 'created_at',
        'MISPAR-HAKOVETZ': 'file_id',
        'KOD-SHOLEACH': 'sender_id',
        'SHEM-SHOLEACH': 'sender_name',
        
        # Client fields
        'MISPAR-ZIHUI-LAKOACH': 'client_id',
        'MISPARZEHUT': 'id_number',
        'SHEM-LAKOACH': 'client_name',
        'SHEM-Prati': 'first_name',
        'SHEM-Mishpacha': 'last_name',
        'TAARICH-LEYDA': 'birth_date',
        
        # Account fields
        'MISPAR-POLISA-O-HESHBON': 'policy_number',
        'STATUS-POLISA-O-CHESHBON': 'status',
        'SALDO': 'balance',
        'KOD-SUG-MUTZAR': 'product_type_code',
        'SUG-MUTZAR': 'product_type',
        'SHEM-MUTZAR': 'product_name',
        'SHEM-YATZRAN': 'provider_name',
        
        # Employer fields
        'KOD-MAASIK': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        
        # Contribution fields
        'CHODESH-DIO': 'report_month',
        'CHODESH': 'month',
        'HAFRASHA-OVED': 'employee_contribution',
        'HAFRASHA-MAASIK': 'employer_contribution',
        'HAFRASHA-PITZUIM': 'severance_contribution',
        
        # Severance fields
        'KFIFA-PITZUIM': 'severance_accrued',
        'KSF-PITZUIM-TZVUR': 'total_severance',
        'ARTICLE14': 'section14',
        'SI14': 'section14_flag',
    }
    
    # Product type mappings (Hebrew to English)
    PRODUCT_TYPES = {
        'פנסיה': 'pension',
        'קרן פנסיה': 'pension_fund',
        'גמל': 'provident',
        'קופת גמל': 'provident_fund',
        'השתלמות': 'education_fund',
        'קרן השתלמות': 'education_fund',
        'ביטוח חיים': 'life_insurance',
        'ביטוח מנהלים': 'managers_insurance',
        'פיצויים': 'severance',
    }
    
    def __init__(self, schema_dir: str = None):
        """
        Initialize the Pension Data Agent.
        
        Args:
            schema_dir: Directory containing XSD schema files (optional)
        """
        self.schema_dir = schema_dir or os.path.join(os.path.dirname(__file__), 'schemas')
        self.schemas = {
            1: "holdings_v9.xsd",
            2: "holdings_v9.xsd",
            3: "holdings_v9.xsd",
            17: "severance_v5.xsd",
        }
        self.schema_cache = {}
        
        # Try to preload schemas if available
        if os.path.isdir(self.schema_dir):
            for code, filename in self.schemas.items():
                path = os.path.join(self.schema_dir, filename)
                if os.path.isfile(path) and LXML_AVAILABLE:
                    try:
                        schema_doc = etree.parse(path)
                        self.schema_cache[code] = etree.XMLSchema(schema_doc)
                    except Exception as e:
                        print(f"[PENSION] Warning: Could not load schema {filename}: {e}")
    
    def detect_interface_type(self, xml_content: bytes) -> int:
        """
        Detect interface type by reading SUG-MIMSHAK from the XML content.
        
        Args:
            xml_content: Raw XML bytes
            
        Returns:
            Interface type code (1, 2, 3, 17, etc.)
        """
        try:
            if LXML_AVAILABLE:
                parser = etree.XMLParser(recover=True, encoding='utf-8')
                root = etree.fromstring(xml_content, parser)
            else:
                root = etree.fromstring(xml_content.decode('utf-8', errors='replace'))
        except Exception as e:
            raise ValueError(f"Invalid XML format: {e}")
        
        # Find SUG-MIMSHAK element
        node = root.find(".//SUG-MIMSHAK")
        if node is None:
            # Try alternative names
            for alt in ['SugMimshak', 'SUGMIMSHAK', 'sug-mimshak']:
                node = root.find(f".//{alt}")
                if node is not None:
                    break
        
        if node is None or node.text is None:
            # Default to Holdings if not found
            return 1
        
        try:
            interface_code = int(node.text.strip())
        except ValueError:
            raise ValueError(f"Invalid SUG-MIMSHAK value: {node.text}")
        
        return interface_code
    
    def validate_xml(self, xml_content: bytes, interface_code: int) -> bool:
        """
        Validate XML content against XSD schema if available.
        
        Args:
            xml_content: Raw XML bytes
            interface_code: Interface type code
            
        Returns:
            True if valid or no schema available
        """
        if not LXML_AVAILABLE:
            return True  # Skip validation without lxml
        
        if interface_code not in self.schema_cache:
            return True  # No schema loaded, skip validation
        
        try:
            xml_schema = self.schema_cache[interface_code]
            doc = etree.fromstring(xml_content)
            
            if not xml_schema.validate(doc):
                errors = [str(err) for err in xml_schema.error_log]
                print(f"[PENSION] XML validation warnings: {errors[:3]}")
                # Don't fail on validation, just warn
            
            return True
        except Exception as e:
            print(f"[PENSION] Validation error (non-fatal): {e}")
            return True
    
    def parse_xml(self, xml_content: bytes, interface_code: int = None) -> Dict[str, Any]:
        """
        Parse XML content into structured Python dict.
        
        Args:
            xml_content: Raw XML bytes
            interface_code: Interface type (auto-detected if not provided)
            
        Returns:
            Structured data dictionary
        """
        # Auto-detect interface type if not provided
        if interface_code is None:
            interface_code = self.detect_interface_type(xml_content)
        
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
            'interface_code': interface_code,
            'interface_type': self.INTERFACE_TYPES.get(interface_code, f"Type{interface_code}"),
        }
        
        # 1. Parse Header
        data['header'] = self._parse_header(root, interface_code)
        
        # 2. Parse Client Info
        data['client'] = self._parse_clients(root)
        
        # 3. Parse Accounts/Products
        data['accounts'] = self._parse_accounts(root)
        
        # 4. Parse Contributions
        data['contributions'] = self._parse_contributions(root)
        
        # 5. Parse Severance Details
        data['severance'] = self._parse_severance(root, interface_code, data['accounts'])
        
        # 6. Parse Employers
        data['employers'] = self._extract_employers(data['accounts'], data['header'])
        
        return data
    
    def _parse_header(self, root, interface_code: int) -> Dict[str, Any]:
        """Parse header information from XML."""
        header = {
            'interface_code': interface_code,
            'interface_type': self.INTERFACE_TYPES.get(interface_code, f"Type{interface_code}"),
        }
        
        # Find header element
        header_node = root.find(".//KoteretKovetz")
        if header_node is None:
            header_node = root.find(".//Header")
        if header_node is None:
            header_node = root  # Use root if no specific header
        
        # Extract header fields
        field_mappings = [
            ('MISPAR-GIRSAT-XML', 'schema_version'),
            ('TAARICH-BITZUA', 'created_at'),
            ('MISPAR-HAKOVETZ', 'file_id'),
            ('KOD-SHOLEACH', 'sender_id'),
            ('SHEM-SHOLEACH', 'sender_name'),
            ('KOD-MEKABEL', 'receiver_id'),
            ('SHEM-MEKABEL', 'receiver_name'),
        ]
        
        for xml_tag, dict_key in field_mappings:
            value = header_node.findtext(xml_tag)
            if value is None:
                value = header_node.findtext(xml_tag.replace('-', ''))
            if value:
                header[dict_key] = value.strip()
        
        return header
    
    def _parse_clients(self, root) -> List[Dict[str, Any]]:
        """Parse client/person information."""
        clients = []
        
        # Try different client element names
        client_tags = ['YeshutLakoach', 'YeshutLakohach', 'Lakoach', 'Client', 'Person']
        
        for tag in client_tags:
            for client_node in root.findall(f".//{tag}"):
                client = {}
                
                # ID number
                for id_tag in ['MISPAR-ZIHUI-LAKOACH', 'MISPARZEHUT', 'MISPAR-ZEHUT', 'IdNumber']:
                    val = client_node.findtext(id_tag)
                    if val:
                        client['id_number'] = val.strip()
                        break
                
                # Name
                for name_tag in ['SHEM-LAKOACH', 'SHEM-Prati', 'SHEM-MALE', 'Name']:
                    val = client_node.findtext(name_tag)
                    if val:
                        client['name'] = val.strip()
                        break
                
                # First/Last name separately
                first = client_node.findtext('SHEM-Prati')
                last = client_node.findtext('SHEM-Mishpacha')
                if first and last:
                    client['first_name'] = first.strip()
                    client['last_name'] = last.strip()
                    if 'name' not in client:
                        client['name'] = f"{first.strip()} {last.strip()}"
                
                # Birth date
                for date_tag in ['TAARICH-LEYDA', 'BirthDate']:
                    val = client_node.findtext(date_tag)
                    if val:
                        client['birth_date'] = val.strip()
                        break
                
                if client:
                    clients.append(client)
        
        return clients
    
    def _parse_accounts(self, root) -> List[Dict[str, Any]]:
        """Parse account/product information."""
        accounts = []
        
        # Iterate through providers (YeshutYatzran)
        for provider in root.findall(".//YeshutYatzran"):
            provider_name = provider.findtext("SHEM-YATZRAN") or ""
            provider_code = provider.findtext("KOD-YATZRAN") or ""
            
            # Iterate through products (Mutzar)
            for product in provider.findall(".//Mutzar"):
                product_type = product.findtext("KOD-SUG-MUTZAR") or product.findtext("SUG-MUTZAR") or ""
                product_name = product.findtext("SHEM-MUTZAR") or ""
                
                # Iterate through accounts/policies (HeshbonOPolisa)
                for acct in product.findall(".//HeshbonOPolisa"):
                    account = {
                        'provider': provider_name.strip(),
                        'provider_code': provider_code.strip(),
                        'product_type': self._translate_product_type(product_type),
                        'product_type_raw': product_type.strip(),
                        'product_name': product_name.strip(),
                        'policy_number': '',
                        'status': '',
                        'balance': 0.0,
                        'severance_balance': 0.0,
                    }
                    
                    # Policy number
                    for tag in ['MISPAR-POLISA-O-HESHBON', 'MISPAR-POLISA', 'PolicyNumber']:
                        val = acct.findtext(tag)
                        if val:
                            account['policy_number'] = val.strip()
                            break
                    
                    # Status
                    for tag in ['STATUS-POLISA-O-CHESHBON', 'STATUS', 'Status']:
                        val = acct.findtext(tag)
                        if val:
                            account['status'] = val.strip()
                            break
                    
                    # Balance
                    for tag in ['SALDO', 'Saldo', 'Balance', 'YITRA']:
                        val = acct.findtext(f".//{tag}")
                        if val:
                            account['balance'] = self._parse_number(val)
                            break
                    
                    # Severance balance
                    for tag in ['KFIFA-PITZUIM', 'PITZUIM', 'SeveranceBalance']:
                        val = acct.findtext(f".//{tag}")
                        if val:
                            account['severance_balance'] = self._parse_number(val)
                            break
                    
                    # Employer info
                    employer_name = acct.findtext(".//SHEM-MAASIK")
                    employer_id = acct.findtext(".//KOD-MAASIK")
                    if employer_name or employer_id:
                        account['employer'] = {
                            'id': employer_id.strip() if employer_id else '',
                            'name': employer_name.strip() if employer_name else ''
                        }
                    
                    accounts.append(account)
        
        # Also check for direct account elements
        for acct in root.findall(".//HeshbonOPolisa"):
            # Check if already processed (under provider)
            policy_num = acct.findtext("MISPAR-POLISA-O-HESHBON") or acct.findtext("MISPAR-POLISA")
            if policy_num and not any(a.get('policy_number') == policy_num.strip() for a in accounts):
                account = {
                    'provider': '',
                    'product_type': '',
                    'product_name': '',
                    'policy_number': policy_num.strip(),
                    'status': acct.findtext("STATUS-POLISA-O-CHESHBON") or '',
                    'balance': self._parse_number(acct.findtext(".//SALDO") or "0"),
                    'severance_balance': self._parse_number(acct.findtext(".//KFIFA-PITZUIM") or "0"),
                }
                accounts.append(account)
        
        return accounts
    
    def _parse_contributions(self, root) -> List[Dict[str, Any]]:
        """Parse contribution records."""
        contributions = []
        
        # Try different contribution element names
        contrib_tags = ['PirteiHafrasha', 'Hafrasha', 'Contribution', 'NetuneiHafrasha']
        
        for tag in contrib_tags:
            for contrib in root.findall(f".//{tag}"):
                record = {
                    'employee_id': '',
                    'name': '',
                    'period': '',
                    'employee_contribution': 0.0,
                    'employer_contribution': 0.0,
                    'severance_contribution': 0.0,
                }
                
                # Employee ID
                for id_tag in ['MISPAR-ZIHUI-LAKOACH', 'MISPARZEHUT']:
                    val = contrib.findtext(id_tag)
                    if val:
                        record['employee_id'] = val.strip()
                        break
                
                # Name
                record['name'] = contrib.findtext('SHEM-LAKOACH') or ''
                
                # Period (month)
                for period_tag in ['CHODESH-DIO', 'CHODESH', 'Period']:
                    val = contrib.findtext(period_tag)
                    if val:
                        record['period'] = val.strip()
                        break
                
                # Contribution amounts
                emp_val = contrib.findtext('HAFRASHA-OVED')
                if emp_val:
                    record['employee_contribution'] = self._parse_number(emp_val)
                
                empr_val = contrib.findtext('HAFRASHA-MAASIK')
                if empr_val:
                    record['employer_contribution'] = self._parse_number(empr_val)
                
                sev_val = contrib.findtext('HAFRASHA-PITZUIM')
                if sev_val:
                    record['severance_contribution'] = self._parse_number(sev_val)
                
                if record['period'] or record['employee_contribution'] or record['employer_contribution']:
                    contributions.append(record)
        
        return contributions
    
    def _parse_severance(self, root, interface_code: int, accounts: List[Dict]) -> List[Dict[str, Any]]:
        """Parse severance (פיצויים) details."""
        severance_list = []
        
        # For severance interface (17)
        if interface_code == 17:
            for emp in root.findall(".//NetuneiPitzuim"):
                record = {
                    'employee_id': emp.findtext("MISPAR-ZIHUI-LAKOACH") or '',
                    'total_severance': self._parse_number(emp.findtext("KSF-PITZUIM-TZVUR") or "0"),
                    'section14': None,
                }
                
                # Section 14 flag
                sec14_val = emp.findtext("ARTICLE14") or emp.findtext("article14") or emp.findtext("SI14")
                if sec14_val:
                    record['section14'] = sec14_val.strip() == "1"
                
                severance_list.append(record)
        
        # Also extract from accounts
        for acct in accounts:
            if acct.get('severance_balance', 0) > 0:
                sev_entry = {
                    'policy_number': acct.get('policy_number', ''),
                    'severance_balance': acct.get('severance_balance', 0),
                    'employer': acct.get('employer', {}).get('name', ''),
                    'section14': None,
                }
                
                # Check for Section 14 flag in the document
                sec14_node = root.find(".//SI14")
                if sec14_node is not None and sec14_node.text:
                    sev_entry['section14'] = sec14_node.text.strip() == "1"
                
                severance_list.append(sev_entry)
        
        return severance_list
    
    def _extract_employers(self, accounts: List[Dict], header: Dict) -> List[Dict[str, str]]:
        """Extract unique employers from accounts."""
        employers = []
        seen = set()
        
        for acct in accounts:
            if 'employer' in acct:
                emp = acct['employer']
                emp_id = emp.get('id', '')
                emp_name = emp.get('name', '')
                key = (emp_id, emp_name)
                if key not in seen and (emp_id or emp_name):
                    seen.add(key)
                    employers.append({'id': emp_id, 'name': emp_name})
        
        # Add sender as employer if not already present
        if header.get('sender_name'):
            key = (header.get('sender_id', ''), header['sender_name'])
            if key not in seen:
                employers.append({
                    'id': header.get('sender_id', ''),
                    'name': header['sender_name']
                })
        
        return employers
    
    def _translate_product_type(self, hebrew_type: str) -> str:
        """Translate Hebrew product type to English."""
        if not hebrew_type:
            return ''
        hebrew_type = hebrew_type.strip()
        return self.PRODUCT_TYPES.get(hebrew_type, hebrew_type)
    
    def _parse_number(self, value: str) -> float:
        """Parse a numeric string to float."""
        if not value:
            return 0.0
        try:
            # Remove commas, spaces, and currency symbols
            cleaned = value.replace(',', '').replace(' ', '').replace('₪', '').replace('$', '')
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def enrich_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich parsed data with derived metrics and summary.
        
        Args:
            data: Parsed data dictionary
            
        Returns:
            Enriched data with summary section
        """
        summary = {}
        
        # Total balance
        total_balance = sum(acct.get('balance', 0) for acct in data.get('accounts', []))
        summary['total_balance'] = round(total_balance, 2)
        summary['total_balance_formatted'] = f"₪{total_balance:,.2f}"
        
        # Total severance
        total_severance = sum(acct.get('severance_balance', 0) for acct in data.get('accounts', []))
        summary['total_severance'] = round(total_severance, 2)
        summary['total_severance_formatted'] = f"₪{total_severance:,.2f}"
        
        # Account count
        summary['account_count'] = len(data.get('accounts', []))
        
        # Provider count
        providers = set(acct.get('provider', '') for acct in data.get('accounts', []) if acct.get('provider'))
        summary['provider_count'] = len(providers)
        summary['providers'] = list(providers)
        
        # Contribution trend
        contributions = data.get('contributions', [])
        if contributions:
            try:
                contributions.sort(key=lambda x: x.get('period', ''))
            except:
                pass
            
            if len(contributions) >= 2:
                first = contributions[0]
                last = contributions[-1]
                
                sum_first = (first.get('employee_contribution', 0) + 
                           first.get('employer_contribution', 0) + 
                           first.get('severance_contribution', 0))
                sum_last = (last.get('employee_contribution', 0) + 
                          last.get('employer_contribution', 0) + 
                          last.get('severance_contribution', 0))
                
                if sum_last > sum_first * 1.1:
                    summary['contribution_trend'] = 'increasing'
                    summary['contribution_trend_he'] = 'עולה'
                elif sum_last < sum_first * 0.9:
                    summary['contribution_trend'] = 'decreasing'
                    summary['contribution_trend_he'] = 'יורד'
                else:
                    summary['contribution_trend'] = 'stable'
                    summary['contribution_trend_he'] = 'יציב'
            else:
                summary['contribution_trend'] = 'insufficient_data'
        
        # Total contributions
        total_emp = sum(c.get('employee_contribution', 0) for c in contributions)
        total_empr = sum(c.get('employer_contribution', 0) for c in contributions)
        total_sev = sum(c.get('severance_contribution', 0) for c in contributions)
        summary['total_employee_contributions'] = round(total_emp, 2)
        summary['total_employer_contributions'] = round(total_empr, 2)
        summary['total_severance_contributions'] = round(total_sev, 2)
        
        # Missing months detection
        if contributions:
            periods = {c.get('period') for c in contributions if c.get('period')}
            try:
                sorted_periods = sorted(periods)
                if len(sorted_periods) >= 2:
                    # Try to detect missing months (assuming YYYY-MM format)
                    # This is a simplified check
                    summary['contribution_periods'] = sorted_periods
                    summary['first_period'] = sorted_periods[0]
                    summary['last_period'] = sorted_periods[-1]
            except:
                pass
        
        # Section 14 status
        section14_any = any(
            s.get('section14') is True 
            for s in data.get('severance', [])
        )
        section14_explicit_false = any(
            s.get('section14') is False 
            for s in data.get('severance', [])
        )
        
        summary['section14_any'] = section14_any
        summary['section14_all'] = section14_any and not section14_explicit_false
        summary['section14_status'] = 'כן' if section14_any else 'לא'
        
        data['summary'] = summary
        return data
    
    def generate_report_text(self, data: Dict[str, Any], language: str = 'hebrew') -> str:
        """
        Generate a human-readable report from the parsed data.
        
        Args:
            data: Enriched data dictionary
            language: 'hebrew' or 'english'
            
        Returns:
            Formatted report text
        """
        summary = data.get('summary', {})
        header = data.get('header', {})
        clients = data.get('client', [])
        accounts = data.get('accounts', [])
        
        is_hebrew = language == 'hebrew'
        
        if is_hebrew:
            report_lines = [
                "📊 דו״ח ניתוח נתוני פנסיה וביטוח",
                "=" * 40,
                "",
                "📋 פרטי הקובץ:",
                f"  • סוג ממשק: {data.get('interface_type', 'לא ידוע')}",
                f"  • גרסת סכמה: {header.get('schema_version', 'לא ידוע')}",
                f"  • תאריך הפקה: {header.get('created_at', 'לא ידוע')}",
                "",
            ]
            
            # Client info
            if clients:
                client = clients[0] if isinstance(clients, list) else clients
                report_lines.extend([
                    "👤 פרטי לקוח:",
                    f"  • שם: {client.get('name', 'לא ידוע')}",
                    f"  • ת.ז.: {self._mask_id(client.get('id_number', ''))}",
                    "",
                ])
            
            # Summary
            report_lines.extend([
                "💰 סיכום כספי:",
                f"  • סה״כ יתרה: {summary.get('total_balance_formatted', '₪0')}",
                f"  • סה״כ פיצויים: {summary.get('total_severance_formatted', '₪0')}",
                f"  • מספר חשבונות: {summary.get('account_count', 0)}",
                f"  • מספר יצרנים: {summary.get('provider_count', 0)}",
                "",
            ])
            
            # Accounts
            if accounts:
                report_lines.append("📁 פירוט חשבונות:")
                for i, acct in enumerate(accounts[:10], 1):
                    report_lines.append(f"\n  🔹 חשבון {i}:")
                    report_lines.append(f"     • מספר פוליסה: {acct.get('policy_number', 'לא ידוע')}")
                    report_lines.append(f"     • יצרן: {acct.get('provider', 'לא ידוע')}")
                    report_lines.append(f"     • סוג מוצר: {acct.get('product_name', acct.get('product_type', 'לא ידוע'))}")
                    report_lines.append(f"     • יתרה: ₪{acct.get('balance', 0):,.2f}")
                    if acct.get('severance_balance', 0) > 0:
                        report_lines.append(f"     • פיצויים: ₪{acct.get('severance_balance', 0):,.2f}")
                    if acct.get('employer'):
                        report_lines.append(f"     • מעסיק: {acct['employer'].get('name', '')}")
                
                if len(accounts) > 10:
                    report_lines.append(f"\n  ... ועוד {len(accounts) - 10} חשבונות")
                report_lines.append("")
            
            # Section 14
            report_lines.extend([
                "📌 סעיף 14:",
                f"  • סטטוס: {summary.get('section14_status', 'לא ידוע')}",
                "",
            ])
            
            # Contribution trend
            if summary.get('contribution_trend'):
                report_lines.extend([
                    "📈 מגמת הפקדות:",
                    f"  • מגמה: {summary.get('contribution_trend_he', summary.get('contribution_trend'))}",
                    f"  • סה״כ הפקדות עובד: ₪{summary.get('total_employee_contributions', 0):,.2f}",
                    f"  • סה״כ הפקדות מעסיק: ₪{summary.get('total_employer_contributions', 0):,.2f}",
                    "",
                ])
        
        else:
            # English version
            report_lines = [
                "📊 Pension & Insurance Data Analysis Report",
                "=" * 45,
                "",
                "📋 File Details:",
                f"  • Interface Type: {data.get('interface_type', 'Unknown')}",
                f"  • Schema Version: {header.get('schema_version', 'Unknown')}",
                f"  • Created: {header.get('created_at', 'Unknown')}",
                "",
            ]
            
            if clients:
                client = clients[0] if isinstance(clients, list) else clients
                report_lines.extend([
                    "👤 Client Information:",
                    f"  • Name: {client.get('name', 'Unknown')}",
                    f"  • ID: {self._mask_id(client.get('id_number', ''))}",
                    "",
                ])
            
            report_lines.extend([
                "💰 Financial Summary:",
                f"  • Total Balance: {summary.get('total_balance_formatted', '₪0')}",
                f"  • Total Severance: {summary.get('total_severance_formatted', '₪0')}",
                f"  • Number of Accounts: {summary.get('account_count', 0)}",
                f"  • Number of Providers: {summary.get('provider_count', 0)}",
                "",
                "📌 Section 14 Status:",
                f"  • Covered: {'Yes' if summary.get('section14_any') else 'No'}",
                "",
            ])
        
        return '\n'.join(report_lines)
    
    def _mask_id(self, id_number: str) -> str:
        """Mask ID number for privacy."""
        if not id_number or len(id_number) < 5:
            return id_number or '***'
        return id_number[:2] + '*' * (len(id_number) - 4) + id_number[-2:]
    
    def process_xml_content(self, xml_content: bytes) -> Dict[str, Any]:
        """
        Main entry point to process XML content.
        
        Args:
            xml_content: Raw XML bytes
            
        Returns:
            Dictionary with 'data' and 'report' keys
        """
        # Detect interface type
        interface_code = self.detect_interface_type(xml_content)
        
        # Validate (non-fatal)
        self.validate_xml(xml_content, interface_code)
        
        # Parse
        data = self.parse_xml(xml_content, interface_code)
        
        # Enrich
        data = self.enrich_data(data)
        
        # Determine language
        language = 'hebrew'  # Default to Hebrew for Israeli pension data
        
        # Generate report
        report = self.generate_report_text(data, language)
        
        return {
            'data': data,
            'report': report,
            'language': language
        }
    
    def process_file(self, file_path: str) -> Dict[str, Any]:
        """
        Process an XML file from disk.
        
        Args:
            file_path: Path to XML file
            
        Returns:
            Dictionary with 'data' and 'report' keys
        """
        with open(file_path, 'rb') as f:
            xml_content = f.read()
        
        return self.process_xml_content(xml_content)
    
    def to_csv_format(self, data: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Convert parsed pension data to CSV-like format for AI analysis.
        
        Returns:
            Tuple of (columns, rows)
        """
        columns = [
            'מספר פוליסה', 'יצרן', 'סוג מוצר', 'שם מוצר', 
            'סטטוס', 'יתרה', 'פיצויים', 'מעסיק'
        ]
        
        rows = []
        for acct in data.get('accounts', []):
            rows.append({
                'מספר פוליסה': acct.get('policy_number', ''),
                'יצרן': acct.get('provider', ''),
                'סוג מוצר': acct.get('product_type', ''),
                'שם מוצר': acct.get('product_name', ''),
                'סטטוס': acct.get('status', ''),
                'יתרה': acct.get('balance', 0),
                'פיצויים': acct.get('severance_balance', 0),
                'מעסיק': acct.get('employer', {}).get('name', '') if acct.get('employer') else ''
            })
        
        # Add summary row
        summary = data.get('summary', {})
        rows.append({
            'מספר פוליסה': 'סה״כ',
            'יצרן': '',
            'סוג מוצר': '',
            'שם מוצר': '',
            'סטטוס': '',
            'יתרה': summary.get('total_balance', 0),
            'פיצויים': summary.get('total_severance', 0),
            'מעסיק': ''
        })
        
        return columns, rows


# Singleton instance
_pension_agent = None


def get_pension_agent() -> PensionDataAgent:
    """Get or create PensionDataAgent singleton."""
    global _pension_agent
    if _pension_agent is None:
        _pension_agent = PensionDataAgent()
    return _pension_agent


def is_pension_xml(content: bytes) -> bool:
    """
    Check if content appears to be a pension/insurance XML file.
    
    Args:
        content: File content bytes
        
    Returns:
        True if appears to be pension XML
    """
    try:
        # Check for XML declaration
        if not content.strip().startswith(b'<?xml') and not content.strip().startswith(b'<'):
            return False
        
        # Look for pension-specific elements
        content_str = content.decode('utf-8', errors='replace')[:5000]  # Check first 5KB
        
        pension_markers = [
            'SUG-MIMSHAK',
            'KoteretKovetz',
            'YeshutYatzran',
            'HeshbonOPolisa',
            'MISPAR-POLISA',
            'SHEM-YATZRAN',
            'HAFRASHA-OVED',
            'PITZUIM',
        ]
        
        return any(marker in content_str for marker in pension_markers)
    except:
        return False
