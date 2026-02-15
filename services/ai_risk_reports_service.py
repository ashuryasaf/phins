"""
AI Risk & Reports Analysis Service
===================================
Provides AI-powered analysis of uploaded documents (CSV/XLS/ZIP) to generate
intelligent reports with recommendations for insurance, investment, and risk assessment.

Features:
- Multi-language support (including Hebrew, Arabic, etc.)
- Auto-detection of data types (insurance, investment, risk, savings)
- Pattern recognition and anomaly detection
- Risk scoring and factor extraction
- Automated report generation with charts
- Personalized recommendations

Author: PHINS Platform
"""

import csv
import io
import json
import os
import re
import hashlib
import zipfile
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field, asdict
import random
import base64


class DataType(Enum):
    INSURANCE = "insurance"
    INVESTMENT = "investment"
    RISK = "risk"
    SAVINGS = "savings"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ChartType(Enum):
    PIE = "pie"
    BAR = "bar"
    LINE = "line"
    GAUGE = "gauge"
    SCATTER = "scatter"
    DOUGHNUT = "doughnut"


class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    sample_values: List[Any]
    semantic_type: str = ""
    is_key_field: bool = False


@dataclass
class Factor:
    name: str
    value: Any
    importance: float
    category: str


@dataclass
class Pattern:
    type: str
    description: str
    affected_rows: List[int]
    significance: float


@dataclass
class Anomaly:
    type: str
    severity: Severity
    description: str
    affected_data: Dict
    recommendation: str


@dataclass
class ChartConfig:
    type: ChartType
    title: str
    data: Dict
    options: Dict = field(default_factory=dict)


@dataclass
class ReportSection:
    title: str
    content: str
    data_table: Optional[Dict] = None
    order: int = 0


@dataclass
class Recommendation:
    id: str
    category: str
    priority: Priority
    title: str
    description: str
    action_items: List[str]
    expected_impact: str


@dataclass
class AnalysisResult:
    id: str
    document_id: str
    language: str
    language_name: str
    data_classification: DataType
    extracted_factors: List[Factor]
    patterns_found: List[Pattern]
    anomalies: List[Anomaly]
    risk_score: float
    confidence: float
    processing_time_ms: int
    summary: str
    key_metrics: Dict[str, Any]


@dataclass
class GeneratedReport:
    id: str
    analysis_id: str
    report_type: str
    language: str
    title: str
    sections: List[ReportSection]
    charts: List[ChartConfig]
    recommendations: List[Recommendation]
    generated_at: str
    metadata: Dict[str, Any]


class LanguageDetector:
    """Detects language from text content"""
    
    # Language patterns - character ranges and common words
    LANGUAGE_PATTERNS = {
        'hebrew': {
            'chars': r'[\u0590-\u05FF]',  # Hebrew Unicode range
            'words': ['של', 'את', 'על', 'עם', 'לא', 'זה', 'או', 'כי', 'אם', 'גם'],
            'name': 'עברית (Hebrew)'
        },
        'arabic': {
            'chars': r'[\u0600-\u06FF]',  # Arabic Unicode range
            'words': ['من', 'في', 'على', 'إلى', 'أن', 'هذا', 'التي', 'مع'],
            'name': 'العربية (Arabic)'
        },
        'english': {
            'chars': r'[a-zA-Z]',
            'words': ['the', 'is', 'and', 'of', 'to', 'in', 'for', 'with', 'that', 'this'],
            'name': 'English'
        },
        'spanish': {
            'chars': r'[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ]',
            'words': ['el', 'la', 'de', 'que', 'en', 'los', 'del', 'las', 'por', 'con'],
            'name': 'Español (Spanish)'
        },
        'french': {
            'chars': r'[a-zA-ZàâäéèêëïîôùûüÿçœæÀÂÄÉÈÊËÏÎÔÙÛÜŸÇŒÆ]',
            'words': ['le', 'la', 'de', 'et', 'est', 'en', 'que', 'les', 'des', 'du'],
            'name': 'Français (French)'
        },
        'german': {
            'chars': r'[a-zA-ZäöüßÄÖÜ]',
            'words': ['der', 'die', 'und', 'ist', 'von', 'den', 'das', 'mit', 'für', 'auf'],
            'name': 'Deutsch (German)'
        },
        'russian': {
            'chars': r'[\u0400-\u04FF]',  # Cyrillic Unicode range
            'words': ['и', 'в', 'на', 'не', 'что', 'он', 'как', 'это', 'по', 'но'],
            'name': 'Русский (Russian)'
        },
        'chinese': {
            'chars': r'[\u4e00-\u9fff]',  # CJK Unified Ideographs
            'words': [],  # Chinese doesn't use word boundaries the same way
            'name': '中文 (Chinese)'
        },
        'japanese': {
            'chars': r'[\u3040-\u309F\u30A0-\u30FF]',  # Hiragana and Katakana
            'words': [],
            'name': '日本語 (Japanese)'
        }
    }
    
    @classmethod
    def detect(cls, text: str) -> Tuple[str, str, float]:
        """
        Detect the primary language of text.
        Returns: (language_code, language_name, confidence)
        """
        if not text or len(text.strip()) < 5:
            return 'english', 'English', 0.5
        
        scores = {}
        text_lower = text.lower()
        
        for lang, patterns in cls.LANGUAGE_PATTERNS.items():
            score = 0
            
            # Check character patterns
            char_matches = len(re.findall(patterns['chars'], text))
            char_ratio = char_matches / max(len(text), 1)
            score += char_ratio * 60
            
            # Check common words
            if patterns['words']:
                word_matches = sum(1 for word in patterns['words'] if word in text_lower)
                word_score = (word_matches / len(patterns['words'])) * 40
                score += word_score
            
            scores[lang] = score
        
        # Get the highest scoring language
        best_lang = max(scores, key=scores.get)
        confidence = min(scores[best_lang] / 100, 1.0)
        
        # Default to English if confidence is too low
        if confidence < 0.2:
            return 'english', 'English', 0.5
        
        return best_lang, cls.LANGUAGE_PATTERNS[best_lang]['name'], confidence


class HebrewDocumentExtractor:
    """
    Extracts structured data from Hebrew insurance/financial documents.
    Uses pattern recognition to identify key fields.
    """
    
    # Hebrew field patterns for insurance documents
    FIELD_PATTERNS = {
        'policy_number': [
            r'מספר פוליס[הא][\s:]*([0-9\-/]+)',
            r'פוליס[הא]\s*מס[פ\'][\s:]*([0-9\-/]+)',
            r'policy[\s#:]*([0-9\-/]+)',
        ],
        'id_number': [
            r'ת\.?ז\.?[\s:]*([0-9]{9})',
            r'תעודת זהות[\s:]*([0-9]{9})',
            r'מספר זהות[\s:]*([0-9]{9})',
            r'ת"ז[\s:]*([0-9]{9})',
        ],
        'start_date': [
            r'תאריך תחילה[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
            r'תחילת ביטוח[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
            r'מתאריך[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
            r'start date[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
        ],
        'end_date': [
            r'תאריך סיום[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
            r'תום תקופה[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
            r'עד תאריך[\s:]*([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})',
        ],
        'premium': [
            r'פרמי[הא][\s:]*[₪$]?[\s]*([0-9,\.]+)',
            r'תשלום חודשי[\s:]*[₪$]?[\s]*([0-9,\.]+)',
            r'premium[\s:]*[₪$]?[\s]*([0-9,\.]+)',
            r'סכום לתשלום[\s:]*[₪$]?[\s]*([0-9,\.]+)',
        ],
        'cover_amount': [
            r'סכום ביטוח[\s:]*[₪$]?[\s]*([0-9,\.]+)',
            r'סכום כיסוי[\s:]*[₪$]?[\s]*([0-9,\.]+)',
            r'cover[\s:]*[₪$]?[\s]*([0-9,\.]+)',
            r'סכום מבוטח[\s:]*[₪$]?[\s]*([0-9,\.]+)',
        ],
        'insured_name': [
            r'שם המבוטח[\s:]*([א-ת\s]+)',
            r'שם מלא[\s:]*([א-ת\s]+)',
            r'מבוטח[\s:]*([א-ת\s]+)',
        ],
        'pension_type': [
            r'סוג פנסיה[\s:]*([א-ת\s]+)',
            r'תוכנית פנסיה[\s:]*([א-ת\s]+)',
            r'קרן פנסיה[\s:]*([א-ת\s]+)',
        ],
        'insurance_type': [
            r'סוג ביטוח[\s:]*([א-ת\s]+)',
            r'סוג פוליסה[\s:]*([א-ת\s]+)',
            r'סוג הכיסוי[\s:]*([א-ת\s]+)',
        ],
        'beneficiary': [
            r'מוטב[\s:]*([א-ת\s]+)',
            r'מוטבים[\s:]*([א-ת\s]+)',
            r'שם מוטב[\s:]*([א-ת\s]+)',
        ],
    }
    
    # Insurance product types (Hebrew)
    PRODUCT_TYPES = {
        'life': ['ביטוח חיים', 'חיים', 'life'],
        'health': ['ביטוח בריאות', 'בריאות', 'health'],
        'pension': ['פנסיה', 'גמל', 'pension', 'קרן פנסיה'],
        'car': ['ביטוח רכב', 'רכב', 'חובה', 'מקיף'],
        'home': ['ביטוח דירה', 'דירה', 'מבנה', 'תכולה'],
        'travel': ['ביטוח נסיעות', 'נסיעות לחו"ל'],
        'business': ['ביטוח עסק', 'עסקי', 'אחריות מקצועית'],
    }
    
    @classmethod
    def extract_fields(cls, text: str) -> Dict[str, Any]:
        """Extract structured fields from Hebrew document text."""
        extracted = {}
        
        for field_name, patterns in cls.FIELD_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    # Clean up numeric values
                    if field_name in ['premium', 'cover_amount']:
                        value = value.replace(',', '')
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    extracted[field_name] = value
                    break
        
        # Detect product type
        text_lower = text.lower()
        for product_type, keywords in cls.PRODUCT_TYPES.items():
            if any(kw in text_lower for kw in keywords):
                extracted['product_type'] = product_type
                break
        
        return extracted
    
    @classmethod
    def analyze_policy_age(cls, start_date_str: str) -> Dict[str, Any]:
        """Analyze policy age and status."""
        try:
            # Try various date formats
            for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d/%m/%y', '%d-%m-%y']:
                try:
                    start_date = datetime.strptime(start_date_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                return {}
            
            today = datetime.now()
            age_days = (today - start_date).days
            age_years = age_days / 365.25
            
            return {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'policy_age_years': round(age_years, 1),
                'policy_age_days': age_days,
                'is_mature': age_years > 10,
                'status': 'veteran' if age_years > 20 else ('mature' if age_years > 10 else ('established' if age_years > 5 else 'new'))
            }
        except Exception:
            return {}
    
    @classmethod
    def calculate_coverage_ratio(cls, premium: float, cover_amount: float) -> Dict[str, Any]:
        """Calculate coverage efficiency metrics."""
        if premium <= 0 or cover_amount <= 0:
            return {}
        
        ratio = cover_amount / premium
        annual_cost_per_1000 = (premium * 12) / (cover_amount / 1000)
        
        return {
            'coverage_ratio': round(ratio, 2),
            'annual_cost_per_1000_cover': round(annual_cost_per_1000, 2),
            'efficiency_rating': 'excellent' if ratio > 5000 else ('good' if ratio > 2000 else ('fair' if ratio > 1000 else 'review_recommended'))
        }


class DataClassifier:
    """Classifies the type of data based on column names and content"""
    
    INSURANCE_KEYWORDS = [
        'policy', 'premium', 'coverage', 'claim', 'insured', 'beneficiary',
        'deductible', 'underwriting', 'risk', 'פוליסה', 'ביטוח', 'כיסוי',
        'תביעה', 'פרמיה', 'מבוטח', 'סכום', 'השתתפות עצמית',
        # Extended Hebrew insurance terms
        'תאריך תחילה', 'תאריך סיום', 'סכום ביטוח', 'מוטב', 'מוטבים',
        'קרן פנסיה', 'גמל', 'ביטוח חיים', 'ביטוח בריאות', 'ביטוח רכב',
        'חובה', 'מקיף', 'צד ג', 'ביטוח דירה', 'תכולה', 'מבנה',
        'אחריות מקצועית', 'ביטוח נסיעות', 'ביטוח משכנתא'
    ]
    
    INVESTMENT_KEYWORDS = [
        'portfolio', 'stock', 'bond', 'fund', 'yield', 'return', 'asset',
        'equity', 'dividend', 'market', 'תיק', 'השקעה', 'מניה', 'אגרת חוב',
        'קרן', 'תשואה', 'נכס', 'דיבידנד',
        # Extended Hebrew investment terms
        'קופת גמל', 'קרן השתלמות', 'פיקדון', 'תיק ניירות ערך',
        'מדד', 'שוק ההון', 'ניהול תיקים', 'חיסכון לכל ילד'
    ]
    
    RISK_KEYWORDS = [
        'risk', 'score', 'assessment', 'rating', 'exposure', 'probability',
        'impact', 'mitigation', 'סיכון', 'ציון', 'הערכה', 'דירוג', 'חשיפה',
        # Extended Hebrew risk terms
        'הערכת סיכונים', 'ניהול סיכונים', 'סיכון תפעולי', 'סיכון שוק'
    ]
    
    SAVINGS_KEYWORDS = [
        'savings', 'balance', 'deposit', 'withdrawal', 'interest', 'account',
        'חיסכון', 'יתרה', 'הפקדה', 'משיכה', 'ריבית', 'חשבון',
        # Extended Hebrew savings terms
        'תוכנית חיסכון', 'חיסכון פנסיוני', 'קופת חיסכון', 'חיסכון לטווח ארוך'
    ]
    
    @classmethod
    def classify(cls, columns: List[str], sample_data: List[Dict]) -> Tuple[DataType, float]:
        """
        Classify the data type based on columns and content.
        Returns: (data_type, confidence)
        """
        # Combine all text for analysis
        all_text = ' '.join(columns).lower()
        if sample_data:
            for row in sample_data[:10]:
                all_text += ' ' + ' '.join(str(v).lower() for v in row.values() if v)
        
        scores = {
            DataType.INSURANCE: sum(1 for kw in cls.INSURANCE_KEYWORDS if kw.lower() in all_text),
            DataType.INVESTMENT: sum(1 for kw in cls.INVESTMENT_KEYWORDS if kw.lower() in all_text),
            DataType.RISK: sum(1 for kw in cls.RISK_KEYWORDS if kw.lower() in all_text),
            DataType.SAVINGS: sum(1 for kw in cls.SAVINGS_KEYWORDS if kw.lower() in all_text),
        }
        
        total_score = sum(scores.values())
        if total_score == 0:
            return DataType.UNKNOWN, 0.3
        
        best_type = max(scores, key=scores.get)
        confidence = scores[best_type] / max(total_score, 1)
        
        # Check for mixed data
        high_scores = [t for t, s in scores.items() if s > 0 and s >= scores[best_type] * 0.5]
        if len(high_scores) > 1:
            return DataType.MIXED, confidence * 0.8
        
        return best_type, min(confidence + 0.3, 1.0)


class AIRiskReportsService:
    """Main service for AI-powered risk and reports analysis"""
    
    def __init__(self):
        self.documents: Dict[str, Dict] = {}
        self.analyses: Dict[str, AnalysisResult] = {}
        self.reports: Dict[str, GeneratedReport] = {}
    
    def parse_file(self, filename: str, file_content: bytes, file_type: str, 
                   owner_id: str = None, owner_role: str = None) -> Dict[str, Any]:
        """
        Parse uploaded file and extract structured data.
        Supports CSV, XLS (as CSV), and ZIP containing CSV files.
        
        Args:
            filename: Name of the uploaded file
            file_content: Raw bytes of the file
            file_type: Type of file (csv, xls, xlsx, zip)
            owner_id: ID of the user who uploaded the file (for data isolation)
            owner_role: Role of the user (admin, customer, etc.)
        """
        doc_id = f"DOC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        result = {
            'document_id': doc_id,
            'filename': filename,
            'file_type': file_type,
            'file_size': len(file_content),
            'status': 'processing',
            'parsed_data': None,
            'error': None,
            'owner_id': owner_id,
            'owner_role': owner_role,
            'created_at': datetime.now().isoformat()
        }
        
        try:
            file_type_lower = file_type.lower()
            
            if file_type_lower == 'zip':
                # Handle ZIP file
                parsed = self._parse_zip(file_content)
                encoding = 'utf-8'
            elif file_type_lower in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                # Handle image files
                parsed = self._parse_image(file_content, filename, file_type_lower)
                encoding = 'binary'
            elif file_type_lower == 'pdf':
                # Handle PDF files
                parsed = self._parse_pdf(file_content, filename)
                encoding = 'binary'
            elif file_type_lower == 'xml':
                # Handle Mislaka / pension XML files
                parsed = self._parse_pension_xml(file_content, filename)
                encoding = 'utf-8'
            elif file_type_lower in ['xls', 'xlsx']:
                # Handle Excel files properly using openpyxl / xlrd
                parsed = self._parse_excel(file_content, filename, file_type_lower)
                encoding = 'binary'
                # If _parse_excel returned empty (libraries missing), detect and warn
                if not parsed.get('rows') and not parsed.get('columns'):
                    print(f"[AI_REPORTS] Excel parse returned no data for {filename}. "
                          "Ensure openpyxl (xlsx) or xlrd (xls) is installed.")
            elif file_type_lower == 'csv':
                # Parse CSV text files
                encoding = self._detect_encoding(file_content)
                text_content = file_content.decode(encoding, errors='replace')
                parsed = self._parse_csv(text_content)
            else:
                # Unknown type - detect if binary before trying CSV
                if self._is_binary_content(file_content):
                    # Binary file: try Excel first, then fall back to metadata-only
                    parsed = self._parse_excel(file_content, filename, 'xlsx')
                    encoding = 'binary'
                    if not parsed.get('rows'):
                        parsed = {
                            'columns': ['filename', 'size_bytes', 'type', 'note'],
                            'rows': [{
                                'filename': filename,
                                'size_bytes': len(file_content),
                                'type': file_type,
                                'note': 'Binary file - use specific format for full parsing'
                            }],
                            'file_type': 'binary'
                        }
                else:
                    # Try to parse as CSV text
                    encoding = self._detect_encoding(file_content)
                    text_content = file_content.decode(encoding, errors='replace')
                    parsed = self._parse_csv(text_content)
            
            result['encoding'] = encoding
            result['parsed_data'] = parsed
            result['status'] = 'completed'
            result['row_count'] = len(parsed.get('rows', []))
            result['column_count'] = len(parsed.get('columns', []))
            
            # Store document
            self.documents[doc_id] = result
            
            # Auto-save for persistence
            self.save_data()
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result
    
    def _detect_encoding(self, content: bytes) -> str:
        """Detect file encoding"""
        # Check for BOM markers
        if content.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        if content.startswith(b'\xff\xfe'):
            return 'utf-16-le'
        if content.startswith(b'\xfe\xff'):
            return 'utf-16-be'
        
        # Try common encodings
        for encoding in ['utf-8', 'windows-1255', 'iso-8859-8', 'windows-1252', 'latin-1']:
            try:
                content.decode(encoding)
                return encoding
            except (UnicodeDecodeError, LookupError):
                continue
        
        return 'utf-8'
    
    @staticmethod
    def _is_binary_content(content: bytes) -> bool:
        """
        Detect whether file content is binary (not parseable as plain text).
        Checks for common binary file signatures and control character density.
        """
        if not content:
            return False
        # Check known binary file signatures
        binary_signatures = [
            b'PK',           # ZIP / OOXML (xlsx, docx, etc.)
            b'\xd0\xcf\x11', # OLE2 (xls, doc, etc.)
            b'\x89PNG',      # PNG
            b'\xff\xd8\xff', # JPEG
            b'GIF8',         # GIF
            b'%PDF',         # PDF
            b'RIFF',         # RIFF (webp, wav, etc.)
        ]
        header = content[:8]
        for sig in binary_signatures:
            if header.startswith(sig):
                return True
        # Check for high density of non-text bytes in first 512 bytes
        sample = content[:512]
        non_text = sum(1 for b in sample if b < 0x09 or (0x0E <= b < 0x20 and b != 0x1B))
        return (non_text / max(len(sample), 1)) > 0.10

    @staticmethod
    def _normalize_policy_number(policy_number: Any) -> str:
        """Normalize policy/account identifiers for stable display (no commas/breaks)."""
        if policy_number is None:
            return ''
        text = str(policy_number).strip()
        if not text:
            return ''
        text = (
            text.replace('\u200f', '')
            .replace('\u200e', '')
            .replace('\u00a0', ' ')
        )
        text = re.sub(r'[\r\n\t]+', '', text)
        text = text.replace(' ', '').replace(',', '')
        return text

    @staticmethod
    def _safe_numeric(value: Any) -> float:
        """Safely convert formatted numeric values to float."""
        if value is None or value == '':
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        if not raw:
            return 0.0

        negative = False
        if raw.startswith('(') and raw.endswith(')'):
            negative = True
            raw = raw[1:-1]

        cleaned = (
            raw.replace('₪', '')
            .replace('$', '')
            .replace('€', '')
            .replace('%', '')
            .replace('\u200f', '')
            .replace('\u200e', '')
            .replace('\u00a0', ' ')
            .strip()
        )
        cleaned = re.sub(r'\s+', '', cleaned)

        if cleaned.endswith('-'):
            negative = True
            cleaned = cleaned[:-1]

        # Handle mixed thousand/decimal separators.
        if ',' in cleaned and '.' in cleaned:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            comma_parts = cleaned.split(',')
            if len(comma_parts) == 2 and len(comma_parts[1]) <= 2:
                cleaned = '.'.join(comma_parts)
            else:
                cleaned = ''.join(comma_parts)
        elif cleaned.count('.') > 1:
            prefix, suffix = cleaned.rsplit('.', 1)
            cleaned = prefix.replace('.', '') + '.' + suffix

        match = re.search(r'-?\d+(?:\.\d+)?', cleaned)
        if not match:
            return 0.0
        try:
            parsed = float(match.group(0))
            return -parsed if negative and parsed > 0 else parsed
        except (ValueError, TypeError):
            return 0.0

    def _calculate_policy_balance(self, account: Dict[str, Any]) -> float:
        """
        Calculate per-policy balance with fallbacks.
        Prefers explicit total_balance, then direct balance, then component sum.
        """
        total_balance = self._safe_numeric(account.get('total_balance'))
        if total_balance > 0:
            return total_balance
        direct_balance = self._safe_numeric(account.get('balance'))
        if direct_balance > 0:
            return direct_balance
        return (
            self._safe_numeric(account.get('savings_balance'))
            + self._safe_numeric(account.get('investment_balance'))
            + self._safe_numeric(account.get('severance_balance'))
        )

    def _extract_policy_cumulative_metrics(
        self,
        rows: List[Dict[str, Any]],
        columns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Build per-policy savings/investment/balance aggregates from tabular rows.
        Returns ordered rows with cumulative totals for report tables/charts.
        """
        if not rows:
            return []

        available_columns = list(columns or [])
        if not available_columns:
            available_columns = list({k for row in rows for k in (row or {}).keys()})

        normalized_map = {col: str(col or '').strip().lower() for col in available_columns}

        policy_keywords = ['policy_number', 'policy number', 'policy no', 'policy', 'מספר פוליסה', 'מס פוליסה', 'מספר חשבון', 'account number', 'account no']
        savings_keywords = ['savings', 'saving', 'חיסכון', 'תגמולים']
        investment_keywords = ['investment', 'investments', 'השקעה', 'השקעות']
        severance_keywords = ['severance', 'פיצויים']
        balance_keywords = ['balance', 'יתרה', 'צבירה']
        provider_keywords = ['provider', 'יצרן', 'company', 'חברה', 'carrier', 'insurer']
        product_keywords = ['product', 'type', 'סוג מוצר', 'מוצר', 'plan', 'תוכנית', 'מסלול']
        status_keywords = ['status', 'state', 'סטטוס', 'מצב']
        employer_keywords = ['employer', 'מעסיק', 'company employer', 'שם מעסיק']
        period_keywords = ['period', 'חודש', 'תקופה', 'date', 'תאריך']

        def has_any_keyword(text: str, keywords: List[str]) -> bool:
            return any(keyword in text for keyword in keywords)

        def policy_column_score(normalized: str) -> int:
            if normalized in ['policy_number', 'מספר פוליסה', 'account_number', 'מספר חשבון']:
                return 5
            if any(term in normalized for term in ['policy_number', 'מספר פוליסה', 'account number', 'מספר חשבון']):
                return 4
            if 'policy' in normalized and 'type' not in normalized and 'status' not in normalized:
                return 3
            if 'account' in normalized and 'type' not in normalized:
                return 2
            if has_any_keyword(normalized, policy_keywords):
                return 1
            return 0

        policy_column = None
        best_policy_score = 0
        for col, normalized in normalized_map.items():
            score = policy_column_score(normalized)
            if score > best_policy_score:
                policy_column = col
                best_policy_score = score
        if not policy_column:
            return []

        savings_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, savings_keywords)]
        investment_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, investment_keywords)]
        severance_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, severance_keywords)]
        classified = set(savings_columns + investment_columns + severance_columns)
        balance_columns = [
            col for col, normalized in normalized_map.items()
            if col not in classified and has_any_keyword(normalized, balance_keywords)
        ]
        provider_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, provider_keywords)]
        product_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, product_keywords)]
        status_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, status_keywords)]
        employer_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, employer_keywords)]
        period_columns = [col for col, normalized in normalized_map.items() if has_any_keyword(normalized, period_keywords)]

        if not (savings_columns or investment_columns or severance_columns or balance_columns):
            return []

        policy_totals: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            policy_value = self._normalize_policy_number(row.get(policy_column, ''))
            if not policy_value:
                continue

            if policy_value not in policy_totals:
                policy_totals[policy_value] = {
                    'policy_number': policy_value,
                    'savings_total': 0.0,
                    'investments_total': 0.0,
                    'severance_total': 0.0,
                    'balance_total': 0.0,
                    'records_count': 0,
                    'provider_values': [],
                    'provider_seen': set(),
                    'product_values': [],
                    'product_seen': set(),
                    'status_values': [],
                    'status_seen': set(),
                    'employer_values': [],
                    'employer_seen': set(),
                    'period_values': [],
                    'period_seen': set(),
                }

            bucket = policy_totals[policy_value]
            bucket['records_count'] += 1
            bucket['savings_total'] += sum(self._safe_numeric(row.get(col)) for col in savings_columns)
            bucket['investments_total'] += sum(self._safe_numeric(row.get(col)) for col in investment_columns)
            bucket['severance_total'] += sum(self._safe_numeric(row.get(col)) for col in severance_columns)
            bucket['balance_total'] += sum(self._safe_numeric(row.get(col)) for col in balance_columns)

            detail_specs = [
                ('provider', provider_columns),
                ('product', product_columns),
                ('status', status_columns),
                ('employer', employer_columns),
                ('period', period_columns),
            ]
            for detail_key, detail_columns in detail_specs:
                seen_key = f'{detail_key}_seen'
                values_key = f'{detail_key}_values'
                for detail_col in detail_columns:
                    raw_detail = row.get(detail_col)
                    if raw_detail is None:
                        continue
                    detail_value = str(raw_detail).strip()
                    if not detail_value:
                        continue
                    if detail_value not in bucket[seen_key]:
                        bucket[seen_key].add(detail_value)
                        bucket[values_key].append(detail_value)

        if not policy_totals:
            return []

        cumulative_total = 0.0
        results: List[Dict[str, Any]] = []

        def summarize(values: List[str], max_items: int = 4) -> str:
            if not values:
                return ''
            if len(values) <= max_items:
                return ' | '.join(values)
            return ' | '.join(values[:max_items]) + f' | +{len(values) - max_items}'

        for policy, bucket in policy_totals.items():
            derived_total = bucket['savings_total'] + bucket['investments_total'] + bucket['severance_total']
            policy_total = bucket['balance_total'] if bucket['balance_total'] > 0 else derived_total
            cumulative_total += policy_total

            provider_values = bucket['provider_values']
            product_values = bucket['product_values']
            status_values = bucket['status_values']
            employer_values = bucket['employer_values']
            period_values = bucket['period_values']

            results.append({
                'policy_number': policy,
                'savings_total': bucket['savings_total'],
                'investments_total': bucket['investments_total'],
                'severance_total': bucket['severance_total'],
                'balance_total': bucket['balance_total'],
                'policy_total': policy_total,
                'cumulative_total': cumulative_total,
                'records_count': bucket['records_count'],
                'provider': summarize(provider_values),
                'product': summarize(product_values),
                'status': summarize(status_values),
                'employer': summarize(employer_values),
                'period': summarize(period_values),
                'provider_primary': provider_values[0] if provider_values else '',
                'product_primary': product_values[0] if product_values else '',
            })

        return results

    def _build_policy_cumulative_section_from_rows(
        self,
        rows: List[Dict[str, Any]],
        columns: Optional[List[str]],
        is_hebrew: bool
    ) -> Optional[ReportSection]:
        """Build an affiliated per-policy cumulative section from generic uploaded rows."""
        policy_metrics = self._extract_policy_cumulative_metrics(rows, columns)
        if not policy_metrics:
            return None

        table_rows = []
        for metric in policy_metrics:
            table_rows.append({
                'מספר פוליסה' if is_hebrew else 'Policy Number': metric['policy_number'],
                'יצרנים' if is_hebrew else 'Providers': metric.get('provider', ''),
                'מוצרים/מסלולים' if is_hebrew else 'Products/Plans': metric.get('product', ''),
                'סטטוס' if is_hebrew else 'Status': metric.get('status', ''),
                'מעסיקים' if is_hebrew else 'Employers': metric.get('employer', ''),
                'תקופות' if is_hebrew else 'Periods': metric.get('period', ''),
                'סכום חסכונות' if is_hebrew else 'Savings Sum': metric['savings_total'],
                'סכום השקעות' if is_hebrew else 'Investments Sum': metric['investments_total'],
                'סכום פיצויים' if is_hebrew else 'Severance Sum': metric['severance_total'],
                'סכום יתרות' if is_hebrew else 'Balance Sum': metric['balance_total'],
                'יתרה מחושבת לפוליסה' if is_hebrew else 'Computed Policy Total': metric['policy_total'],
                'יתרה מצטברת' if is_hebrew else 'Cumulative Total': metric['cumulative_total'],
                'מספר רשומות' if is_hebrew else 'Records': metric['records_count'],
            })

        return ReportSection(
            title='חישוב מצטבר חיסכון/השקעה לפי פוליסה' if is_hebrew else 'Per-Policy Savings/Investment Cumulative Totals',
            content='סיכום מפורט על בסיס כל הרשומות שהועלו.' if is_hebrew
            else 'Detailed cumulative totals based on all uploaded records.',
            data_table={
                'columns': list(table_rows[0].keys()),
                'rows': table_rows,
                'show_all': True
            },
            order=6
        )

    def _build_uploaded_data_table_section(self, doc_data: Dict[str, Any], is_hebrew: bool) -> Optional[ReportSection]:
        """Build full uploaded affiliated data table section (all rows, no sampling)."""
        if not doc_data:
            return None

        rows = doc_data.get('rows', []) or []
        if not rows:
            return None

        preferred_columns = doc_data.get('columns', []) or []
        if preferred_columns:
            resolved_columns = list(preferred_columns)
        else:
            resolved_columns = list({k for row in rows for k in (row or {}).keys()})

        policy_like_columns = {
            col for col in resolved_columns
            if any(term in str(col).lower() for term in ['policy', 'מספר פוליסה', 'account number', 'מספר חשבון'])
        }
        normalized_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized_row = dict(row)
            for col in policy_like_columns:
                if col in normalized_row:
                    normalized_row[col] = self._normalize_policy_number(normalized_row.get(col))
            normalized_rows.append(normalized_row)

        record_count = len(normalized_rows)
        title = (
            f'📊 נתונים שחולצו ({record_count} רשומות) - טבלת שיוך מלאה'
            if is_hebrew
            else f'📊 Extracted Data ({record_count} Records) - Full Affiliated Table'
        )
        content = (
            'הקצאה מלאה של כל הנתונים שחולצו לקונטקסט דוח שיוכים/סיכון/חיסכון.'
            if is_hebrew
            else 'Full allocation of all extracted records into affiliated savings/risk report context.'
        )

        return ReportSection(
            title=title,
            content=content,
            data_table={
                'columns': resolved_columns,
                'rows': normalized_rows,
                'show_all': True
            },
            order=3
        )

    def _normalize_policy_like_fields_in_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize policy/account-like identifiers in a row without mutating source."""
        normalized = dict(row)
        for key, value in row.items():
            key_norm = str(key or '').lower()
            if any(token in key_norm for token in ['policy', 'מספר פוליסה', 'מס פוליסה', 'מספר חשבון', 'account number']):
                normalized[key] = self._normalize_policy_number(value)
        return normalized

    @staticmethod
    def _get_pdf_example_allocation_model() -> List[Dict[str, Any]]:
        """
        Allocation model inspired by uploaded sample report:
        כפיר כהן מסלקה 122022.pdf
        """
        return [
            {
                'key': 'policy_status',
                'order': 4,
                'title_he': 'סטטוס פוליסות (הקצאה לפי דוח לדוגמה)',
                'title_en': 'Policy Status (Example-Driven Allocation)',
                'keywords': ['סטטוס', 'status', 'מספר פוליסה', 'policy', 'וותק', 'seniority', 'מעמד']
            },
            {
                'key': 'plan_details',
                'order': 5,
                'title_he': 'רשימת תוכניות ופרטי מוצר',
                'title_en': 'Plan List & Product Details',
                'keywords': ['תוכנית', 'plan', 'product', 'מוצר', 'גיל פרישה', 'retirement', 'דמי ניהול', 'management fee']
            },
            {
                'key': 'balances_forecast',
                'order': 6,
                'title_he': 'יתרות, חיסכון ותחזיות עתידיות',
                'title_en': 'Balances, Savings, and Future Forecast',
                'keywords': ['יתרה', 'balance', 'צבירה', 'חיסכון', 'savings', 'קצבה', 'pension', 'forecast', 'צפוי', 'הון']
            },
            {
                'key': 'coverage_protection',
                'order': 7,
                'title_he': 'כיסויים והגנות ביטוחיות',
                'title_en': 'Insurance Coverage & Protections',
                'keywords': ['כיסוי', 'coverage', 'מוות', 'death', 'אובדן כושר', 'disability', 'פרמיה', 'premium', 'insured']
            },
            {
                'key': 'investment_assets',
                'order': 8,
                'title_he': 'מסלולי השקעה והרכב נכסים',
                'title_en': 'Investment Tracks and Asset Allocation',
                'keywords': ['השקעה', 'investment', 'מסלול', 'track', 'asset', 'נכסים', 'חשיפה', 'equity', 'שארפ', 'std']
            },
            {
                'key': 'contributions_debts',
                'order': 9,
                'title_he': 'הפקדות, הפרשות, חוב ופיגורים',
                'title_en': 'Deposits, Contributions, Debt & Arrears',
                'keywords': ['הפקדה', 'contribution', 'הפרשה', 'salary', 'שכר', 'employee', 'employer', 'חוב', 'פיגור']
            },
            {
                'key': 'beneficiaries',
                'order': 10,
                'title_he': 'מוטבים ושארים',
                'title_en': 'Beneficiaries & Dependents',
                'keywords': ['מוטב', 'beneficiary', 'זיקה', 'relation', 'אחוז', 'percentage', 'שם מוטב']
            },
            {
                'key': 'employers_addresses',
                'order': 11,
                'title_he': 'פרטי מעסיקים וכתובות',
                'title_en': 'Employers and Address Records',
                'keywords': ['מעסיק', 'employer', 'כתובת', 'address', 'יישוב', 'city', 'רחוב', 'טלפון', 'email', 'מיקוד']
            },
            {
                'key': 'operational_additional',
                'order': 12,
                'title_he': 'נתונים תפעוליים ונתונים נוספים',
                'title_en': 'Operational and Additional Data',
                'keywords': ['מיופה', 'proxy', 'שיעבוד', 'lien', 'עיקול', 'operational', 'מסלקה', 'קידוד', 'תביעה', 'claim', 'הלוואה', 'loan']
            },
        ]

    def _categorize_rows_by_pdf_example(
        self,
        rows: List[Dict[str, Any]],
        columns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Allocate rows to example-model categories using column+value signals."""
        model = self._get_pdf_example_allocation_model()
        category_rows: Dict[str, List[Dict[str, Any]]] = {item['key']: [] for item in model}
        category_lookup = {item['key']: item for item in model}

        if not rows:
            return {
                'model': model,
                'category_rows': category_rows,
                'summary': [],
                'total_rows': 0,
            }

        all_columns = list(columns or [])
        if not all_columns:
            all_columns = list({k for row in rows for k in (row or {}).keys()})

        normalized_column_map = {col: str(col or '').lower().strip() for col in all_columns}
        policy_columns = [
            col for col, col_norm in normalized_column_map.items()
            if any(token in col_norm for token in ['policy', 'מספר פוליסה', 'מס פוליסה', 'מספר חשבון', 'account number'])
        ]
        if not policy_columns:
            policy_columns = [all_columns[0]] if all_columns else []

        category_columns: Dict[str, List[str]] = {}
        for item in model:
            matched_columns = []
            for col, col_norm in normalized_column_map.items():
                if any(keyword in col_norm for keyword in item.get('keywords', [])):
                    matched_columns.append(col)
            # Always keep policy identity as anchor columns.
            for policy_col in policy_columns:
                if policy_col not in matched_columns:
                    matched_columns.insert(0, policy_col)
            category_columns[item['key']] = matched_columns

        for item in model:
            key = item['key']
            selected_columns = category_columns.get(key, [])
            if not selected_columns:
                continue

            projected_rows: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized_row = self._normalize_policy_like_fields_in_row(row)
                projected = {col: normalized_row.get(col, '') for col in selected_columns if col in normalized_row}
                data_values = [str(projected.get(col, '')).strip() for col in selected_columns if col not in policy_columns]
                has_data = any(value for value in data_values) if data_values else any(str(v).strip() for v in projected.values())
                if has_data:
                    projected_rows.append(projected)

            if projected_rows:
                category_rows[key] = projected_rows

        total_rows = len([r for r in rows if isinstance(r, dict)])
        allocated_rows = sum(len(v) for v in category_rows.values())
        # Categories can overlap by design (same row can serve multiple report sections).
        unallocated_rows = 0 if allocated_rows > 0 else total_rows

        summary = []
        for item in model:
            key = item['key']
            rows_count = len(category_rows.get(key, []))
            if rows_count <= 0:
                continue
            summary.append({
                'key': key,
                'title_he': item['title_he'],
                'title_en': item['title_en'],
                'count': rows_count,
                'percent': round((rows_count / max(total_rows, 1)) * 100, 2),
                'columns': len(category_columns.get(key, [])),
                'order': item.get('order', 99),
            })

        return {
            'model': model,
            'lookup': category_lookup,
            'category_rows': category_rows,
            'summary': summary,
            'total_rows': total_rows,
            'unallocated_rows': unallocated_rows,
            'allocation_model': 'kfir_122022_pdf',
        }

    def _build_pdf_example_allocation_sections(self, doc_data: Dict[str, Any], is_hebrew: bool) -> List[ReportSection]:
        """Build allocation sections inspired by the uploaded sample PDF structure."""
        if not doc_data:
            return []
        rows = doc_data.get('rows', []) or []
        columns = doc_data.get('columns', []) or []
        if not rows:
            return []

        allocation = self._categorize_rows_by_pdf_example(rows, columns)
        summary_rows = []
        for entry in allocation.get('summary', []):
            summary_rows.append({
                'קטגוריה' if is_hebrew else 'Category': entry['title_he'] if is_hebrew else entry['title_en'],
                'כמות רשומות' if is_hebrew else 'Records': entry['count'],
                'שדות משויכים' if is_hebrew else 'Mapped Fields': entry.get('columns', 0),
                'אחוז מסך הרשומות' if is_hebrew else 'Percent of Records': entry['percent'],
            })

        sections: List[ReportSection] = []
        if summary_rows:
            sections.append(ReportSection(
                title='מפת הקצאת נתונים לפי דוח לדוגמה (12/2022)' if is_hebrew else 'Data Allocation Map by Example Report (12/2022)',
                content='הקצאה לפי מבנה דוח כפיר כהן 12/2022 לצורך דוח סיכונים וחיסכון מפורט.' if is_hebrew
                else 'Allocation by Kfir Cohen 12/2022 report structure for detailed savings/risk reporting.',
                data_table={
                    'columns': list(summary_rows[0].keys()),
                    'rows': summary_rows,
                    'show_all': True
                },
                order=4
            ))

        category_lookup = allocation.get('lookup', {})
        for entry in sorted(allocation.get('summary', []), key=lambda item: item.get('order', 99)):
            key = entry['key']
            rows_for_category = allocation.get('category_rows', {}).get(key, [])
            if not rows_for_category:
                continue

            base_columns = [col for col in columns if any(col in row for row in rows_for_category)]
            additional_columns: List[str] = []
            for row in rows_for_category:
                for col in row.keys():
                    if col not in base_columns and col not in additional_columns:
                        additional_columns.append(col)
            resolved_columns = base_columns + additional_columns
            item = category_lookup.get(key, {})

            sections.append(ReportSection(
                title=f"{item.get('title_he') if is_hebrew else item.get('title_en')} ({len(rows_for_category)})",
                content='רשומות שהוקצו אוטומטית לפי מודל הדוח לדוגמה.' if is_hebrew
                else 'Rows auto-allocated according to the example report model.',
                data_table={
                    'columns': resolved_columns,
                    'rows': rows_for_category,
                    'show_all': True
                },
                order=item.get('order', 99)
            ))

        return sections
    
    def _parse_csv(self, text_content: str) -> Dict[str, Any]:
        """Parse CSV content"""
        # Try different delimiters
        for delimiter in [',', ';', '\t', '|']:
            try:
                reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)
                rows = list(reader)
                if rows and len(rows[0]) > 1:
                    columns = list(rows[0].keys()) if rows else []
                    return {
                        'columns': columns,
                        'rows': rows,
                        'delimiter': delimiter
                    }
            except Exception:
                continue
        
        # Fallback: simple line parsing
        lines = text_content.strip().split('\n')
        if lines:
            columns = lines[0].split(',')
            rows = []
            for line in lines[1:]:
                values = line.split(',')
                rows.append(dict(zip(columns, values)))
            return {'columns': columns, 'rows': rows, 'delimiter': ','}
        
        return {'columns': [], 'rows': [], 'delimiter': ','}
    
    def _parse_excel(self, content: bytes, filename: str, ext: str) -> Dict[str, Any]:
        """
        Parse Excel files (.xls and .xlsx) from Mislaka data.
        Extracts pension and insurance data from Excel format.
        
        IMPORTANT: XLSX files are ZIP-based OOXML archives. They MUST be parsed
        with openpyxl (xlsx) or xlrd (xls) - never as plain text/CSV, which
        would produce garbled PK!... binary output.
        """
        rows = []
        columns = []
        pension_data = None
        sheet_names = []
        parse_method = None
        
        try:
            if ext == 'xlsx':
                # Use openpyxl for .xlsx files
                try:
                    import openpyxl
                    from openpyxl import load_workbook
                    
                    wb = load_workbook(filename=io.BytesIO(content), data_only=True)
                    sheet_names = wb.sheetnames
                    parse_method = 'openpyxl'
                    
                    for sheet_name in wb.sheetnames:
                        sheet = wb[sheet_name]
                        sheet_rows = list(sheet.iter_rows(values_only=True))
                        
                        if not sheet_rows:
                            continue
                        
                        # First row as headers
                        header_row = sheet_rows[0] if sheet_rows else []
                        sheet_columns = [str(h).strip() if h else f'col_{i}' for i, h in enumerate(header_row)]
                        
                        # Add columns that don't exist yet
                        for col in sheet_columns:
                            if col and col not in columns:
                                columns.append(col)
                        
                        # Process data rows
                        for row in sheet_rows[1:]:
                            if row and any(cell is not None for cell in row):
                                row_dict = {}
                                for i, cell in enumerate(row):
                                    if i < len(sheet_columns):
                                        col_name = sheet_columns[i]
                                        # Convert dates, numbers etc. to string representation
                                        if cell is None:
                                            row_dict[col_name] = ''
                                        elif hasattr(cell, 'isoformat'):
                                            row_dict[col_name] = cell.isoformat()
                                        else:
                                            row_dict[col_name] = cell
                                rows.append(row_dict)
                    
                    wb.close()
                    print(f"[AI_REPORTS] Successfully parsed XLSX '{filename}': "
                          f"{len(sheet_names)} sheets, {len(columns)} columns, {len(rows)} rows")
                    
                except ImportError:
                    print("[AI_REPORTS] WARNING: openpyxl not installed. "
                          "Cannot parse XLSX files. Install with: pip install openpyxl")
                except Exception as e:
                    print(f"[AI_REPORTS] openpyxl error parsing '{filename}': {e}")
                    
            elif ext == 'xls':
                # Use xlrd for older .xls files
                try:
                    import xlrd
                    
                    wb = xlrd.open_workbook(file_contents=content)
                    parse_method = 'xlrd'
                    
                    for sheet_idx in range(wb.nsheets):
                        sheet = wb.sheet_by_index(sheet_idx)
                        sheet_names.append(sheet.name)
                        
                        if sheet.nrows == 0:
                            continue
                        
                        # First row as headers
                        header_row = sheet.row_values(0) if sheet.nrows > 0 else []
                        sheet_columns = [str(h).strip() if h else f'col_{i}' for i, h in enumerate(header_row)]
                        
                        # Add columns that don't exist yet
                        for col in sheet_columns:
                            if col and col not in columns:
                                columns.append(col)
                        
                        # Process data rows
                        for row_idx in range(1, sheet.nrows):
                            row = sheet.row_values(row_idx)
                            if row and any(cell for cell in row):
                                row_dict = {}
                                for i, cell in enumerate(row):
                                    if i < len(sheet_columns):
                                        col_name = sheet_columns[i]
                                        row_dict[col_name] = cell if cell else ''
                                rows.append(row_dict)
                    
                    print(f"[AI_REPORTS] Successfully parsed XLS '{filename}': "
                          f"{len(sheet_names)} sheets, {len(columns)} columns, {len(rows)} rows")
                    
                except ImportError:
                    print("[AI_REPORTS] WARNING: xlrd not installed. "
                          "Cannot parse XLS files. Install with: pip install xlrd")
                except Exception as e:
                    print(f"[AI_REPORTS] xlrd error parsing '{filename}': {e}")
            
            # Try to detect if this is Mislaka pension data
            if rows and columns:
                pension_data = self._detect_mislaka_excel_data(columns, rows, filename)
            
        except Exception as e:
            print(f"[AI_REPORTS] Error parsing Excel file {filename}: {e}")
        
        return {
            'columns': columns,
            'rows': rows,
            'pension_data': pension_data,
            'file_type': 'excel',
            'original_filename': filename,
            'sheet_names': sheet_names,
            'parse_method': parse_method or 'none'
        }
    
    def _detect_mislaka_excel_data(self, columns: List[str], rows: List[Dict], filename: str) -> Optional[Dict[str, Any]]:
        """
        Detect and extract Mislaka pension data from Excel columns/rows.
        Maps Hebrew column names to pension data structure.
        """
        # Hebrew column name mappings for Mislaka data
        column_mappings = {
            # Client fields
            'שם': 'client_name',
            'שם מלא': 'client_name', 
            'שם פרטי': 'first_name',
            'שם משפחה': 'last_name',
            'תעודת זהות': 'id_number',
            'ת.ז': 'id_number',
            'ת"ז': 'id_number',
            'מספר זהות': 'id_number',
            'תאריך לידה': 'birth_date',
            
            # Provider/Product fields
            'יצרן': 'provider',
            'שם יצרן': 'provider',
            'חברה': 'provider',
            'שם חברה': 'provider',
            'מוצר': 'product_name',
            'שם מוצר': 'product_name',
            'סוג מוצר': 'product_type',
            'סוג קופה': 'product_type',
            
            # Policy fields
            'מספר פוליסה': 'policy_number',
            'מס פוליסה': 'policy_number',
            'מספר חשבון': 'policy_number',
            'מס חשבון': 'policy_number',
            
            # Balance fields
            'יתרה': 'balance',
            'יתרה כוללת': 'total_balance',
            'סך צבירה': 'total_balance',
            'צבירה': 'total_balance',
            'סה"כ צבירה': 'total_balance',
            'יתרת תגמולים': 'savings_balance',
            'תגמולים': 'savings_balance',
            'יתרת השקעות': 'investment_balance',
            'השקעות': 'investment_balance',
            'יתרת השקעה': 'investment_balance',
            'יתרת פיצויים': 'severance_balance',
            'פיצויים': 'severance_balance',
            
            # Fee fields
            'דמי ניהול': 'management_fee',
            'דמי ניהול מצבירה': 'management_fee_savings',
            'דמי ניהול מהפקדות': 'management_fee_deposits',
            'עמלה': 'management_fee',
            
            # Status fields
            'סטטוס': 'status',
            'מצב': 'status',
            'סטטוס פוליסה': 'status',
            
            # Section 14
            'סעיף 14': 'section14',
            'סעיף14': 'section14',
            
            # Employer
            'מעסיק': 'employer_name',
            'שם מעסיק': 'employer_name',
        }
        
        # Check if this looks like pension data
        pension_indicators = ['יצרן', 'פוליסה', 'צבירה', 'יתרה', 'תגמולים', 'פיצויים', 'קופה', 'פנסיה', 'ביטוח', 'גמל']
        columns_lower = [str(c).lower() for c in columns]
        
        is_pension_data = any(
            any(indicator in col for indicator in pension_indicators) 
            for col in columns_lower
        )
        
        if not is_pension_data:
            return None
        
        # Map columns to standardized names
        mapped_columns = {}
        for col in columns:
            col_str = str(col).strip()
            for hebrew_name, english_name in column_mappings.items():
                if hebrew_name in col_str or col_str == hebrew_name:
                    mapped_columns[col] = english_name
                    break
        
        # Extract client and account data
        client_info = {}
        accounts = []
        
        for row in rows:
            account = {}
            
            for original_col, value in row.items():
                if original_col in mapped_columns:
                    mapped_name = mapped_columns[original_col]
                    
                    # Convert value
                    if value is not None and value != '':
                        if mapped_name in ['total_balance', 'savings_balance', 'severance_balance', 
                                          'investment_balance', 'balance', 'management_fee',
                                          'management_fee_savings', 'management_fee_deposits']:
                            try:
                                account[mapped_name] = float(str(value).replace(',', '').replace('₪', '').strip())
                            except:
                                account[mapped_name] = 0
                        elif mapped_name == 'policy_number':
                            account[mapped_name] = self._normalize_policy_number(value)
                        elif mapped_name == 'section14':
                            account[mapped_name] = str(value).lower() in ['כן', 'yes', '1', 'true', 'v', '✓']
                        elif mapped_name in ['client_name', 'first_name', 'last_name', 'id_number', 'birth_date']:
                            client_info[mapped_name] = str(value).strip()
                        else:
                            account[mapped_name] = str(value).strip()
            
            if account.get('provider') or account.get('policy_number') or self._calculate_policy_balance(account) > 0:
                accounts.append(account)
        
        # Build full name if we have parts
        if client_info.get('first_name') or client_info.get('last_name'):
            parts = [client_info.get('first_name', ''), client_info.get('last_name', '')]
            client_info['full_name'] = ' '.join(p for p in parts if p)
        elif client_info.get('client_name'):
            client_info['full_name'] = client_info['client_name']
        
        if not accounts and not client_info:
            return None
        
        # Calculate totals
        total_balance = sum(self._calculate_policy_balance(a) for a in accounts)
        total_savings = sum(self._safe_numeric(a.get('savings_balance')) for a in accounts)
        total_investments = sum(self._safe_numeric(a.get('investment_balance')) for a in accounts)
        total_severance = sum(self._safe_numeric(a.get('severance_balance')) for a in accounts)
        
        return {
            'client': client_info,
            'accounts': accounts,
            'totals': {
                'total_balance': total_balance,
                'total_balance_formatted': f"₪{total_balance:,.0f}",
                'total_savings': total_savings,
                'total_savings_balance': total_savings,
                'total_savings_formatted': f"₪{total_savings:,.0f}",
                'total_investments': total_investments,
                'total_investments_formatted': f"₪{total_investments:,.0f}",
                'total_severance': total_severance,
                'total_severance_balance': total_severance,
                'total_severance_formatted': f"₪{total_severance:,.0f}",
                'account_count': len(accounts),
                'provider_count': len(set(a.get('provider', '') for a in accounts if a.get('provider'))),
                'providers': list(set(a.get('provider', '') for a in accounts if a.get('provider'))),
            },
            'header': {
                'source': 'Excel',
                'filename': filename,
            }
        }
    
    def _parse_zip(self, content: bytes) -> Dict[str, Any]:
        """Parse ZIP file containing CSV, XML (pension), image, and PDF files"""
        combined_data = {'columns': [], 'rows': [], 'files': [], 'pension_data': None}
        
        with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
            for name in zf.namelist():
                # Skip directories and hidden files
                if name.endswith('/') or name.startswith('__') or name.startswith('.'):
                    continue
                
                name_lower = name.lower()
                ext = name_lower.split('.')[-1] if '.' in name_lower else ''
                
                with zf.open(name) as f:
                    file_content = f.read()
                
                parsed = None
                file_type = ext
                
                if ext == 'csv':
                    encoding = self._detect_encoding(file_content)
                    text_content = file_content.decode(encoding, errors='replace')
                    parsed = self._parse_csv(text_content)
                elif ext == 'xml':
                    # Check if it's a pension/insurance XML file
                    parsed = self._parse_pension_xml(file_content, name)
                    if parsed:
                        file_type = 'pension_xml'
                        # Store pension data separately for enhanced analysis
                        if parsed.get('pension_data'):
                            combined_data['pension_data'] = parsed.get('pension_data')
                elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    parsed = self._parse_image(file_content, name, ext)
                elif ext == 'pdf':
                    parsed = self._parse_pdf(file_content, name)
                elif ext in ['xls', 'xlsx']:
                    # Parse Excel files properly
                    parsed = self._parse_excel(file_content, name, ext)
                    if parsed:
                        file_type = 'excel'
                        # Check if this looks like Mislaka data
                        if parsed.get('pension_data'):
                            combined_data['pension_data'] = parsed.get('pension_data')
                
                if parsed:
                    combined_data['files'].append({
                        'name': name,
                        'type': file_type,
                        'columns': parsed.get('columns', []),
                        'row_count': len(parsed.get('rows', []))
                    })
                    
                    # Merge columns and rows
                    for col in parsed.get('columns', []):
                        if col not in combined_data['columns']:
                            combined_data['columns'].append(col)
                    combined_data['rows'].extend(parsed.get('rows', []))
        
        return combined_data
    
    def _parse_pension_xml(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Parse Israeli pension/insurance XML files using the PensionDataAgent.
        
        Supports Mislaka (מסלקה) interface standards:
        - Type 1: Holdings (אחזקות)
        - Type 2: Pre-Advice (הודעה מקדימה)
        - Type 3: Holdings + Pre-Advice Combined
        - Type 17: Severance (פיצויים)
        """
        try:
            from services.pension_data_agent import get_pension_agent, is_pension_xml
            
            # Check if this is a pension XML file
            if not is_pension_xml(content):
                # Not a pension XML, try to parse as generic XML
                return self._parse_generic_xml(content, filename)
            
            # Process with PensionDataAgent
            agent = get_pension_agent()
            result = agent.process_xml_content(content)
            
            pension_data = result.get('data', {})
            report_text = result.get('report', '')
            
            # Convert to CSV-like format for AI analysis
            columns, rows = agent.to_csv_format(pension_data)
            
            # Add summary data as additional rows
            summary = pension_data.get('summary', {})
            header = pension_data.get('header', {})
            clients = pension_data.get('client', [])
            
            # Add header info as rows
            meta_rows = [
                {'מספר פוליסה': 'סוג ממשק', 'יצרן': pension_data.get('interface_type', ''), 'סוג מוצר': '', 'שם מוצר': '', 'סטטוס': '', 'יתרה': '', 'פיצויים': '', 'מעסיק': ''},
                {'מספר פוליסה': 'גרסת סכמה', 'יצרן': header.get('schema_version', ''), 'סוג מוצר': '', 'שם מוצר': '', 'סטטוס': '', 'יתרה': '', 'פיצויים': '', 'מעסיק': ''},
            ]
            
            # Add client info
            if clients:
                client = clients[0] if isinstance(clients, list) else clients
                meta_rows.append({
                    'מספר פוליסה': 'לקוח',
                    'יצרן': client.get('name', ''),
                    'סוג מוצר': '',
                    'שם מוצר': '',
                    'סטטוס': '',
                    'יתרה': '',
                    'פיצויים': '',
                    'מעסיק': ''
                })
            
            # Prepend meta rows
            all_rows = meta_rows + rows
            
            return {
                'columns': columns,
                'rows': all_rows,
                'delimiter': None,
                'file_type': 'pension_xml',
                'original_filename': filename,
                'pension_data': pension_data,
                'pension_report': report_text
            }
            
        except ImportError:
            print("[AI_REPORTS] PensionDataAgent not available, falling back to generic XML parsing")
            return self._parse_generic_xml(content, filename)
        except Exception as e:
            print(f"[AI_REPORTS] Error parsing pension XML: {e}")
            return self._parse_generic_xml(content, filename)
    
    def _parse_generic_xml(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Parse generic XML file into tabular format.
        """
        try:
            import xml.etree.ElementTree as ET
            
            # Decode content
            encoding = self._detect_encoding(content)
            xml_str = content.decode(encoding, errors='replace')
            
            # Parse XML
            root = ET.fromstring(xml_str)
            
            # Extract all leaf elements as rows
            columns = ['element', 'value', 'path']
            rows = []
            
            def extract_elements(elem, path=""):
                current_path = f"{path}/{elem.tag}" if path else elem.tag
                
                # If element has text content
                if elem.text and elem.text.strip():
                    rows.append({
                        'element': elem.tag,
                        'value': elem.text.strip(),
                        'path': current_path
                    })
                
                # Process attributes
                for attr, val in elem.attrib.items():
                    rows.append({
                        'element': f"{elem.tag}@{attr}",
                        'value': val,
                        'path': current_path
                    })
                
                # Process children
                for child in elem:
                    extract_elements(child, current_path)
            
            extract_elements(root)
            
            return {
                'columns': columns,
                'rows': rows,
                'delimiter': None,
                'file_type': 'xml',
                'original_filename': filename
            }
            
        except Exception as e:
            print(f"[AI_REPORTS] Error parsing generic XML: {e}")
            return {'columns': [], 'rows': [], 'file_type': 'xml', 'error': str(e)}
    
    def _parse_image(self, content: bytes, filename: str, file_type: str) -> Dict[str, Any]:
        """
        Parse image file and extract metadata for analysis.
        Creates a structured data format from image properties.
        """
        # Basic image metadata extraction
        file_size = len(content)
        
        # Try to detect image dimensions from header
        width, height = 0, 0
        if file_type in ['png']:
            # PNG header: width at bytes 16-19, height at bytes 20-23
            if len(content) >= 24:
                width = int.from_bytes(content[16:20], 'big')
                height = int.from_bytes(content[20:24], 'big')
        elif file_type in ['jpg', 'jpeg']:
            # JPEG - simplified dimension detection
            # Look for SOF0 marker (0xFF 0xC0)
            try:
                i = 0
                while i < len(content) - 10:
                    if content[i] == 0xFF and content[i+1] in [0xC0, 0xC1, 0xC2]:
                        height = int.from_bytes(content[i+5:i+7], 'big')
                        width = int.from_bytes(content[i+7:i+9], 'big')
                        break
                    i += 1
            except:
                pass
        
        # Extract any text from filename for language detection
        filename_text = filename.replace('_', ' ').replace('-', ' ')
        
        # Create structured data for analysis
        columns = ['property', 'value', 'category']
        rows = [
            {'property': 'filename', 'value': filename, 'category': 'metadata'},
            {'property': 'file_type', 'value': file_type.upper(), 'category': 'metadata'},
            {'property': 'file_size_bytes', 'value': str(file_size), 'category': 'metadata'},
            {'property': 'file_size_kb', 'value': str(round(file_size / 1024, 2)), 'category': 'metadata'},
            {'property': 'width_px', 'value': str(width), 'category': 'dimensions'},
            {'property': 'height_px', 'value': str(height), 'category': 'dimensions'},
            {'property': 'resolution', 'value': f'{width}x{height}', 'category': 'dimensions'},
            {'property': 'document_type', 'value': 'image', 'category': 'classification'},
            {'property': 'source_name', 'value': filename_text, 'category': 'context'},
        ]
        
        return {
            'columns': columns,
            'rows': rows,
            'delimiter': None,
            'file_type': 'image',
            'original_filename': filename
        }
    
    def _parse_pdf(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Parse PDF file and extract metadata for analysis.
        Creates a structured data format from PDF properties.
        """
        file_size = len(content)
        
        # Basic PDF metadata extraction
        page_count = 0
        title = filename
        author = ''
        creation_date = ''
        
        # Simple PDF parsing for metadata
        try:
            content_str = content[:4096].decode('latin-1', errors='ignore')
            
            # Count pages (approximate)
            page_count = content.count(b'/Type /Page') or content.count(b'/Type/Page')
            
            # Extract title if present
            if '/Title' in content_str:
                start = content_str.find('/Title')
                if start != -1:
                    # Try to extract title value
                    paren_start = content_str.find('(', start)
                    paren_end = content_str.find(')', paren_start) if paren_start != -1 else -1
                    if paren_start != -1 and paren_end != -1:
                        title = content_str[paren_start+1:paren_end][:100]
            
            # Extract author if present
            if '/Author' in content_str:
                start = content_str.find('/Author')
                if start != -1:
                    paren_start = content_str.find('(', start)
                    paren_end = content_str.find(')', paren_start) if paren_start != -1 else -1
                    if paren_start != -1 and paren_end != -1:
                        author = content_str[paren_start+1:paren_end][:100]
        except:
            pass
        
        # Extract text from filename for context
        filename_text = filename.replace('_', ' ').replace('-', ' ').replace('.pdf', '')
        
        # Detect if filename contains Hebrew
        has_hebrew = bool(re.search(r'[\u0590-\u05FF]', filename_text))
        
        # Create structured data for analysis
        columns = ['property', 'value', 'category']
        rows = [
            {'property': 'filename', 'value': filename, 'category': 'metadata'},
            {'property': 'file_type', 'value': 'PDF', 'category': 'metadata'},
            {'property': 'file_size_bytes', 'value': str(file_size), 'category': 'metadata'},
            {'property': 'file_size_kb', 'value': str(round(file_size / 1024, 2)), 'category': 'metadata'},
            {'property': 'file_size_mb', 'value': str(round(file_size / (1024*1024), 2)), 'category': 'metadata'},
            {'property': 'page_count', 'value': str(page_count), 'category': 'content'},
            {'property': 'title', 'value': title, 'category': 'metadata'},
            {'property': 'author', 'value': author, 'category': 'metadata'},
            {'property': 'document_type', 'value': 'pdf', 'category': 'classification'},
            {'property': 'source_name', 'value': filename_text, 'category': 'context'},
            {'property': 'has_hebrew', 'value': str(has_hebrew), 'category': 'language'},
        ]
        
        return {
            'columns': columns,
            'rows': rows,
            'delimiter': None,
            'file_type': 'pdf',
            'original_filename': filename,
            'page_count': page_count
        }
    
    def analyze(self, document_id: str) -> AnalysisResult:
        """
        Perform advanced AI/BI analysis on parsed document using inductive reasoning.
        
        This method learns from the uploaded data through:
        1. Statistical profiling of all columns
        2. Inductive pattern recognition
        3. Correlation analysis between fields
        4. Domain-specific semantic analysis
        5. Language-aware interpretation
        
        Returns comprehensive analysis with factors, patterns, and risk assessment.
        """
        start_time = datetime.now()
        
        if document_id not in self.documents:
            raise ValueError(f"Document {document_id} not found")
        
        doc = self.documents[document_id]
        parsed = doc.get('parsed_data', {})
        columns = parsed.get('columns', [])
        rows = parsed.get('rows', [])
        
        # =====================================================================
        # PHASE 1: INDUCTIVE DATA PROFILING
        # Learn the structure and semantics of the uploaded data
        # =====================================================================
        
        # Combine all text for language detection
        all_text = ' '.join(columns)
        for row in rows[:50]:  # Sample more rows for better detection
            all_text += ' ' + ' '.join(str(v) for v in row.values() if v)
        
        # Detect language with confidence
        lang_code, lang_name, lang_confidence = LanguageDetector.detect(all_text)
        
        # Classify data type using semantic analysis
        data_type, type_confidence = DataClassifier.classify(columns, rows)
        
        # =====================================================================
        # PHASE 2: HEBREW DOCUMENT EXTRACTION (for Hebrew insurance documents)
        # Extract structured fields from Hebrew documents using pattern recognition
        # =====================================================================
        
        hebrew_extracted = {}
        if lang_code == 'hebrew' or any(re.search(r'[\u0590-\u05FF]', str(v)) for row in rows[:10] for v in row.values()):
            hebrew_extracted = self._extract_hebrew_document_data(all_text, rows)
        
        # =====================================================================
        # PHASE 3: ADVANCED STATISTICAL ANALYSIS (BI)
        # Compute comprehensive statistics for each column
        # =====================================================================
        
        column_profiles = self._profile_columns(columns, rows)
        
        # =====================================================================
        # PHASE 4: CORRELATION & RELATIONSHIP DISCOVERY
        # Find relationships between different data fields
        # =====================================================================
        
        correlations = self._find_correlations(columns, rows, column_profiles)
        
        # =====================================================================
        # PHASE 5: INDUCTIVE PATTERN LEARNING
        # Discover patterns and rules from the data
        # =====================================================================
        
        # Extract factors with enhanced analysis
        factors = self._extract_factors_advanced(columns, rows, data_type, column_profiles)
        
        # Add Hebrew document factors if available
        if hebrew_extracted:
            factors.extend(self._create_hebrew_document_factors(hebrew_extracted, lang_code))
        
        # Find patterns using inductive reasoning
        patterns = self._find_patterns_advanced(rows, data_type, column_profiles, correlations)
        
        # Add Hebrew-specific patterns
        if hebrew_extracted:
            patterns.extend(self._find_hebrew_patterns(hebrew_extracted))
        
        # Detect anomalies with statistical backing
        anomalies = self._detect_anomalies_advanced(rows, data_type, column_profiles)
        
        # =====================================================================
        # PHASE 6: DOMAIN-SPECIFIC INSIGHTS
        # Apply domain knowledge based on detected data type
        # =====================================================================
        
        domain_insights = self._generate_domain_insights(data_type, column_profiles, rows, lang_code, hebrew_extracted)
        
        # =====================================================================
        # PHASE 6: RISK ASSESSMENT
        # Calculate comprehensive risk score
        # =====================================================================
        
        risk_score = self._calculate_risk_score_advanced(
            factors, patterns, anomalies, correlations, domain_insights
        )
        
        # Generate language-aware summary with insights
        summary = self._generate_summary_advanced(
            lang_code, data_type, len(rows), factors, risk_score, 
            column_profiles, domain_insights
        )
        
        # Extract comprehensive key metrics
        key_metrics = self._extract_key_metrics_advanced(
            rows, columns, data_type, column_profiles, correlations, domain_insights
        )
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        analysis_id = f"ANA-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        result = AnalysisResult(
            id=analysis_id,
            document_id=document_id,
            language=lang_code,
            language_name=lang_name,
            data_classification=data_type,
            extracted_factors=factors,
            patterns_found=patterns,
            anomalies=anomalies,
            risk_score=risk_score,
            confidence=min((lang_confidence + type_confidence) / 2, 1.0),
            processing_time_ms=processing_time,
            summary=summary,
            key_metrics=key_metrics
        )
        
        self.analyses[analysis_id] = result
        
        # Auto-save for persistence
        self.save_data()
        
        return result
    
    # =========================================================================
    # ADVANCED BI/AI ANALYSIS METHODS
    # These methods provide deep inductive analysis of uploaded data
    # =========================================================================
    
    def _profile_columns(self, columns: List[str], rows: List[Dict]) -> Dict[str, Dict]:
        """
        Create comprehensive statistical profiles for each column.
        This is the foundation of inductive data analysis.
        """
        profiles = {}
        
        for col in columns:
            profile = {
                'name': col,
                'type': 'unknown',
                'count': 0,
                'null_count': 0,
                'unique_count': 0,
                'numeric': False,
                'values': [],
                'stats': {}
            }
            
            values = []
            numeric_values = []
            
            for row in rows:
                val = row.get(col)
                if val is None or str(val).strip() == '':
                    profile['null_count'] += 1
                else:
                    profile['count'] += 1
                    values.append(str(val))
                    
                    # Try to parse as numeric
                    try:
                        clean_val = str(val).replace(',', '').replace('₪', '').replace('$', '').replace('€', '').replace('%', '')
                        num_val = float(clean_val)
                        numeric_values.append(num_val)
                    except (ValueError, TypeError):
                        pass
            
            profile['unique_count'] = len(set(values))
            profile['values'] = values[:100]  # Store sample
            
            # Determine column type and compute statistics
            if len(numeric_values) > len(values) * 0.5:  # More than 50% numeric
                profile['numeric'] = True
                profile['type'] = 'numeric'
                
                if numeric_values:
                    sorted_vals = sorted(numeric_values)
                    n = len(numeric_values)
                    mean_val = sum(numeric_values) / n
                    
                    # Variance and std dev
                    variance = sum((x - mean_val) ** 2 for x in numeric_values) / n if n > 0 else 0
                    std_dev = variance ** 0.5
                    
                    # Quartiles
                    q1_idx = int(n * 0.25)
                    q2_idx = int(n * 0.5)
                    q3_idx = int(n * 0.75)
                    
                    profile['stats'] = {
                        'min': round(min(numeric_values), 2),
                        'max': round(max(numeric_values), 2),
                        'sum': round(sum(numeric_values), 2),
                        'mean': round(mean_val, 2),
                        'median': round(sorted_vals[q2_idx] if n > 0 else 0, 2),
                        'std_dev': round(std_dev, 2),
                        'variance': round(variance, 2),
                        'q1': round(sorted_vals[q1_idx] if n > 0 else 0, 2),
                        'q3': round(sorted_vals[q3_idx] if n > 0 else 0, 2),
                        'iqr': round((sorted_vals[q3_idx] - sorted_vals[q1_idx]) if n > 0 else 0, 2),
                        'count': n,
                        'range': round(max(numeric_values) - min(numeric_values), 2)
                    }
                    
                    # Detect distribution shape
                    if std_dev > 0:
                        skewness = sum((x - mean_val) ** 3 for x in numeric_values) / (n * std_dev ** 3)
                        profile['stats']['skewness'] = round(skewness, 3)
                        profile['stats']['distribution'] = 'normal' if abs(skewness) < 0.5 else ('right_skewed' if skewness > 0 else 'left_skewed')
            else:
                profile['type'] = 'categorical'
                # Frequency distribution for categorical
                freq = {}
                for v in values:
                    freq[v] = freq.get(v, 0) + 1
                
                sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
                profile['stats'] = {
                    'top_values': sorted_freq[:10],
                    'unique_ratio': round(profile['unique_count'] / max(len(values), 1), 3),
                    'mode': sorted_freq[0][0] if sorted_freq else None,
                    'mode_count': sorted_freq[0][1] if sorted_freq else 0
                }
            
            # Semantic type detection
            col_lower = col.lower()
            if any(x in col_lower for x in ['date', 'time', 'תאריך']):
                profile['semantic_type'] = 'datetime'
            elif any(x in col_lower for x in ['email', 'מייל']):
                profile['semantic_type'] = 'email'
            elif any(x in col_lower for x in ['phone', 'טלפון', 'נייד']):
                profile['semantic_type'] = 'phone'
            elif any(x in col_lower for x in ['price', 'amount', 'premium', 'מחיר', 'סכום', 'פרמיה']):
                profile['semantic_type'] = 'currency'
            elif any(x in col_lower for x in ['percent', 'rate', 'אחוז', 'שיעור']):
                profile['semantic_type'] = 'percentage'
            elif any(x in col_lower for x in ['id', 'number', 'מספר', 'מזהה']):
                profile['semantic_type'] = 'identifier'
            elif any(x in col_lower for x in ['name', 'שם']):
                profile['semantic_type'] = 'name'
            elif any(x in col_lower for x in ['status', 'סטטוס', 'מצב']):
                profile['semantic_type'] = 'status'
            else:
                profile['semantic_type'] = 'general'
            
            profiles[col] = profile
        
        return profiles
    
    def _find_correlations(self, columns: List[str], rows: List[Dict], 
                          profiles: Dict[str, Dict]) -> List[Dict]:
        """
        Find correlations between numeric columns.
        Uses Pearson correlation coefficient.
        """
        correlations = []
        numeric_cols = [col for col, p in profiles.items() if p['numeric']]
        
        if len(numeric_cols) < 2 or len(rows) < 3:
            return correlations
        
        # Extract numeric values for each column
        col_values = {}
        for col in numeric_cols:
            values = []
            for row in rows:
                try:
                    val = float(str(row.get(col, 0)).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                    values.append(val)
                except:
                    values.append(0)
            col_values[col] = values
        
        # Calculate correlations between pairs
        for i, col1 in enumerate(numeric_cols):
            for col2 in numeric_cols[i+1:]:
                vals1 = col_values[col1]
                vals2 = col_values[col2]
                
                n = len(vals1)
                mean1 = sum(vals1) / n
                mean2 = sum(vals2) / n
                
                # Covariance
                cov = sum((vals1[j] - mean1) * (vals2[j] - mean2) for j in range(n)) / n
                
                # Standard deviations
                std1 = (sum((x - mean1) ** 2 for x in vals1) / n) ** 0.5
                std2 = (sum((x - mean2) ** 2 for x in vals2) / n) ** 0.5
                
                # Pearson correlation
                if std1 > 0 and std2 > 0:
                    corr = cov / (std1 * std2)
                    
                    if abs(corr) > 0.3:  # Only significant correlations
                        correlations.append({
                            'column1': col1,
                            'column2': col2,
                            'correlation': round(corr, 3),
                            'strength': 'strong' if abs(corr) > 0.7 else ('moderate' if abs(corr) > 0.5 else 'weak'),
                            'direction': 'positive' if corr > 0 else 'negative'
                        })
        
        # Sort by absolute correlation
        correlations.sort(key=lambda x: abs(x['correlation']), reverse=True)
        return correlations[:10]  # Top 10 correlations
    
    def _extract_factors_advanced(self, columns: List[str], rows: List[Dict], 
                                  data_type: DataType, profiles: Dict[str, Dict]) -> List[Factor]:
        """
        Extract key factors using advanced statistical analysis.
        IMPORTANT: Excludes ID/policy numbers from statistical analysis - 
        these are for display only, not for statistical calculations.
        """
        factors = []
        
        # Columns to EXCLUDE from statistical analysis (IDs, policy numbers, etc.)
        # These should only be used for display/identification, not statistics
        exclude_patterns = [
            'id', 'מספר', 'תז', 'ת.ז', 'ת"ז', 'זהות', 'פוליסה', 'חשבון', 
            'policy', 'account', 'number', 'num', 'code', 'קוד', 'מזהה',
            'phone', 'טלפון', 'נייד', 'zip', 'מיקוד', 'index', 'row'
        ]
        
        # Columns that ARE meaningful for statistical analysis (financial data)
        meaningful_patterns = [
            'balance', 'יתרה', 'צבירה', 'תגמולים', 'פיצויים', 'חיסכון',
            'premium', 'פרמיה', 'הפקדה', 'תשלום',
            'coverage', 'כיסוי', 'ביטוח', 'סכום',
            'fee', 'דמי', 'עמלה', 'ניהול',
            'return', 'תשואה', 'רווח', 'הפסד',
            'salary', 'שכר', 'משכורת',
            'amount', 'סכום', 'ערך', 'שווי'
        ]
        
        def should_exclude_column(col_name: str) -> bool:
            """Check if column should be excluded from statistical analysis."""
            col_lower = str(col_name).lower()
            
            # Check if it's an identifier/number column
            for pattern in exclude_patterns:
                if pattern in col_lower:
                    return True
            
            return False
        
        def is_meaningful_financial_column(col_name: str, semantic_type: str) -> bool:
            """Check if column is meaningful for financial analysis."""
            col_lower = str(col_name).lower()
            
            # Currency and percentage are always meaningful
            if semantic_type in ['currency', 'percentage']:
                return True
            
            # Check for financial keywords
            for pattern in meaningful_patterns:
                if pattern in col_lower:
                    return True
            
            return False
        
        # Add statistical factors ONLY for meaningful numeric columns
        for col, profile in profiles.items():
            if profile['numeric'] and profile['stats']:
                # Skip ID/policy number columns - CRITICAL
                if should_exclude_column(col):
                    continue
                
                # Only analyze columns that are meaningful for financial analysis
                semantic_type = profile.get('semantic_type', '')
                if not is_meaningful_financial_column(col, semantic_type):
                    continue
                
                stats = profile['stats']
                
                # Determine importance based on variance and semantic type
                importance = 0.5
                if semantic_type == 'currency':
                    importance = 0.9
                elif semantic_type == 'percentage':
                    importance = 0.8
                elif stats.get('std_dev', 0) > stats.get('mean', 1) * 0.5:
                    importance = 0.7  # High variability is important
                
                factors.append(Factor(
                    name=f"{col} Analysis",
                    value={
                        'mean': stats.get('mean'),
                        'median': stats.get('median'),
                        'range': f"{stats.get('min')} - {stats.get('max')}",
                        'std_dev': stats.get('std_dev'),
                        'distribution': stats.get('distribution', 'unknown')
                    },
                    importance=importance,
                    category='statistical'
                ))
        
        # Add categorical distribution factors
        for col, profile in profiles.items():
            if not profile['numeric'] and profile['stats'].get('top_values'):
                top_vals = profile['stats']['top_values'][:5]
                
                factors.append(Factor(
                    name=f"{col} Distribution",
                    value={
                        'unique_values': profile['unique_count'],
                        'top_categories': [{'value': v, 'count': c} for v, c in top_vals],
                        'concentration': profile['stats'].get('unique_ratio', 0)
                    },
                    importance=0.6 if profile.get('semantic_type') == 'status' else 0.4,
                    category='categorical'
                ))
        
        # Data type specific factors
        if data_type == DataType.INSURANCE:
            factors.append(Factor(
                name='Insurance Data Profile',
                value={
                    'record_count': len(rows),
                    'data_completeness': round(sum(1 for p in profiles.values() if p['null_count'] == 0) / max(len(profiles), 1) * 100, 1),
                    'domain': 'insurance'
                },
                importance=0.95,
                category='domain'
            ))
        elif data_type == DataType.INVESTMENT:
            factors.append(Factor(
                name='Investment Data Profile',
                value={
                    'record_count': len(rows),
                    'numeric_fields': sum(1 for p in profiles.values() if p['numeric']),
                    'domain': 'investment'
                },
                importance=0.95,
                category='domain'
            ))
        
        return factors[:15]  # Return top 15 factors
    
    def _find_patterns_advanced(self, rows: List[Dict], data_type: DataType,
                               profiles: Dict[str, Dict], correlations: List[Dict]) -> List[Pattern]:
        """
        Find patterns using inductive reasoning.
        """
        patterns = []
        
        if len(rows) < 2:
            return patterns
        
        # Pattern 1: Data completeness patterns
        incomplete_cols = [col for col, p in profiles.items() if p['null_count'] > len(rows) * 0.1]
        if incomplete_cols:
            patterns.append(Pattern(
                type='data_quality',
                description=f"Incomplete data in {len(incomplete_cols)} columns: {', '.join(incomplete_cols[:3])}",
                affected_rows=list(range(len(rows))),
                significance=0.8
            ))
        
        # Pattern 2: Value concentration (potential data issues)
        for col, profile in profiles.items():
            if not profile['numeric'] and profile['stats'].get('unique_ratio', 1) < 0.1:
                mode = profile['stats'].get('mode')
                mode_count = profile['stats'].get('mode_count', 0)
                if mode_count > len(rows) * 0.5:
                    patterns.append(Pattern(
                        type='value_concentration',
                        description=f"High concentration in '{col}': '{mode}' appears in {mode_count}/{len(rows)} records ({round(mode_count/len(rows)*100)}%)",
                        affected_rows=[],
                        significance=0.6
                    ))
        
        # Pattern 3: Correlation-based patterns
        for corr in correlations[:3]:
            direction = "increases" if corr['direction'] == 'positive' else "decreases"
            patterns.append(Pattern(
                type='correlation',
                description=f"{corr['strength'].capitalize()} {corr['direction']} correlation: When '{corr['column1']}' increases, '{corr['column2']}' {direction} (r={corr['correlation']})",
                affected_rows=[],
                significance=abs(corr['correlation'])
            ))
        
        # Pattern 4: Distribution patterns
        for col, profile in profiles.items():
            if profile['numeric'] and profile['stats'].get('distribution'):
                dist = profile['stats']['distribution']
                if dist != 'normal':
                    patterns.append(Pattern(
                        type='distribution',
                        description=f"'{col}' shows {dist.replace('_', ' ')} distribution (skewness: {profile['stats'].get('skewness', 0)})",
                        affected_rows=[],
                        significance=0.5
                    ))
        
        # Pattern 5: Outlier patterns
        for col, profile in profiles.items():
            if profile['numeric'] and profile['stats']:
                q1 = profile['stats'].get('q1', 0)
                q3 = profile['stats'].get('q3', 0)
                iqr = profile['stats'].get('iqr', 0)
                if iqr > 0:
                    lower_bound = q1 - 1.5 * iqr
                    upper_bound = q3 + 1.5 * iqr
                    
                    outlier_count = 0
                    for row in rows:
                        try:
                            val = float(str(row.get(col, 0)).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                            if val < lower_bound or val > upper_bound:
                                outlier_count += 1
                        except:
                            pass
                    
                    if outlier_count > 0:
                        patterns.append(Pattern(
                            type='outliers',
                            description=f"'{col}' has {outlier_count} outlier values outside normal range [{round(lower_bound,2)}, {round(upper_bound,2)}]",
                            affected_rows=[],
                            significance=min(outlier_count / len(rows) + 0.3, 1.0)
                        ))
        
        return patterns[:10]
    
    def _detect_anomalies_advanced(self, rows: List[Dict], data_type: DataType,
                                   profiles: Dict[str, Dict]) -> List[Anomaly]:
        """
        Detect anomalies using statistical methods.
        """
        anomalies = []
        
        if len(rows) < 3:
            return anomalies
        
        # Z-score based anomaly detection for numeric columns
        for col, profile in profiles.items():
            if profile['numeric'] and profile['stats']:
                mean = profile['stats'].get('mean', 0)
                std_dev = profile['stats'].get('std_dev', 0)
                
                if std_dev > 0:
                    extreme_values = []
                    for i, row in enumerate(rows):
                        try:
                            val = float(str(row.get(col, 0)).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                            z_score = abs(val - mean) / std_dev
                            if z_score > 3:  # More than 3 standard deviations
                                extreme_values.append({'row': i, 'value': val, 'z_score': round(z_score, 2)})
                        except:
                            pass
                    
                    if extreme_values:
                        severity = Severity.CRITICAL if len(extreme_values) > 5 else (
                            Severity.HIGH if len(extreme_values) > 2 else Severity.MEDIUM
                        )
                        anomalies.append(Anomaly(
                            type='statistical_outlier',
                            severity=severity,
                            description=f"Found {len(extreme_values)} extreme values in '{col}' (>3 standard deviations from mean)",
                            affected_data={'column': col, 'outliers': extreme_values[:5]},
                            recommendation=f"Review extreme values in '{col}' for data accuracy"
                        ))
        
        # Data quality anomalies
        high_null_cols = [col for col, p in profiles.items() if p['null_count'] > len(rows) * 0.3]
        if high_null_cols:
            anomalies.append(Anomaly(
                type='data_quality',
                severity=Severity.HIGH,
                description=f"{len(high_null_cols)} columns have >30% missing values: {', '.join(high_null_cols[:3])}",
                affected_data={'columns': high_null_cols},
                recommendation="Investigate data collection process for missing values"
            ))
        
        # Suspicious value patterns
        for col, profile in profiles.items():
            if profile['numeric'] and profile['stats']:
                # Check for suspicious zero concentration
                zero_count = sum(1 for row in rows if str(row.get(col, '')).strip() in ['0', '0.0', '0.00'])
                if zero_count > len(rows) * 0.3 and zero_count < len(rows) * 0.9:
                    anomalies.append(Anomaly(
                        type='suspicious_pattern',
                        severity=Severity.MEDIUM,
                        description=f"'{col}' has {round(zero_count/len(rows)*100)}% zero values - may indicate data issues",
                        affected_data={'column': col, 'zero_count': zero_count},
                        recommendation=f"Verify if zero values in '{col}' are intentional"
                    ))
        
        return anomalies[:8]
    
    def _extract_hebrew_document_data(self, all_text: str, rows: List[Dict]) -> Dict[str, Any]:
        """
        Extract structured data from Hebrew insurance/financial documents.
        Uses the HebrewDocumentExtractor for pattern-based extraction.
        """
        extracted = HebrewDocumentExtractor.extract_fields(all_text)
        
        # Also scan all row values for additional data
        for row in rows:
            row_text = ' '.join(str(v) for v in row.values() if v)
            row_extracted = HebrewDocumentExtractor.extract_fields(row_text)
            for key, value in row_extracted.items():
                if key not in extracted:
                    extracted[key] = value
        
        # Analyze policy age if start date found
        if 'start_date' in extracted:
            age_info = HebrewDocumentExtractor.analyze_policy_age(extracted['start_date'])
            extracted.update(age_info)
        
        # Calculate coverage ratio if premium and cover found
        if 'premium' in extracted and 'cover_amount' in extracted:
            try:
                premium = float(extracted['premium']) if isinstance(extracted['premium'], str) else extracted['premium']
                cover = float(extracted['cover_amount']) if isinstance(extracted['cover_amount'], str) else extracted['cover_amount']
                ratio_info = HebrewDocumentExtractor.calculate_coverage_ratio(premium, cover)
                extracted.update(ratio_info)
            except (ValueError, TypeError):
                pass
        
        return extracted
    
    def _create_hebrew_document_factors(self, hebrew_extracted: Dict[str, Any], lang: str) -> List[Factor]:
        """
        Create analysis factors from extracted Hebrew document data.
        """
        factors = []
        is_hebrew = lang == 'hebrew'
        
        # Policy Information Factor
        policy_info = {}
        if 'policy_number' in hebrew_extracted:
            policy_info['מספר פוליסה' if is_hebrew else 'policy_number'] = hebrew_extracted['policy_number']
        if 'insurance_type' in hebrew_extracted:
            policy_info['סוג ביטוח' if is_hebrew else 'insurance_type'] = hebrew_extracted['insurance_type']
        if 'product_type' in hebrew_extracted:
            policy_info['סוג מוצר' if is_hebrew else 'product_type'] = hebrew_extracted['product_type']
        
        if policy_info:
            factors.append(Factor(
                name='פרטי פוליסה' if is_hebrew else 'Policy Details',
                value=policy_info,
                importance=0.95,
                category='hebrew_insurance'
            ))
        
        # Financial Details Factor
        financial_info = {}
        if 'premium' in hebrew_extracted:
            financial_info['פרמיה חודשית' if is_hebrew else 'monthly_premium'] = f"₪{hebrew_extracted['premium']}"
        if 'cover_amount' in hebrew_extracted:
            financial_info['סכום כיסוי' if is_hebrew else 'cover_amount'] = f"₪{hebrew_extracted['cover_amount']:,}" if isinstance(hebrew_extracted['cover_amount'], (int, float)) else f"₪{hebrew_extracted['cover_amount']}"
        if 'coverage_ratio' in hebrew_extracted:
            financial_info['יחס כיסוי/פרמיה' if is_hebrew else 'coverage_ratio'] = hebrew_extracted['coverage_ratio']
        if 'efficiency_rating' in hebrew_extracted:
            rating_map = {'excellent': 'מצוין', 'good': 'טוב', 'fair': 'סביר', 'review_recommended': 'מומלץ לבדיקה'}
            financial_info['דירוג יעילות' if is_hebrew else 'efficiency'] = rating_map.get(hebrew_extracted['efficiency_rating'], hebrew_extracted['efficiency_rating']) if is_hebrew else hebrew_extracted['efficiency_rating']
        
        if financial_info:
            factors.append(Factor(
                name='נתונים כספיים' if is_hebrew else 'Financial Details',
                value=financial_info,
                importance=0.9,
                category='hebrew_insurance'
            ))
        
        # Policy Timeline Factor
        timeline_info = {}
        if 'start_date' in hebrew_extracted:
            timeline_info['תאריך תחילה' if is_hebrew else 'start_date'] = hebrew_extracted.get('start_date', hebrew_extracted.get('start_date'))
        if 'policy_age_years' in hebrew_extracted:
            timeline_info['ותק הפוליסה' if is_hebrew else 'policy_age'] = f"{hebrew_extracted['policy_age_years']} שנים" if is_hebrew else f"{hebrew_extracted['policy_age_years']} years"
        if 'status' in hebrew_extracted:
            status_map = {'veteran': 'ותיקה', 'mature': 'בשלה', 'established': 'מבוססת', 'new': 'חדשה'}
            timeline_info['סטטוס' if is_hebrew else 'status'] = status_map.get(hebrew_extracted['status'], hebrew_extracted['status']) if is_hebrew else hebrew_extracted['status']
        
        if timeline_info:
            factors.append(Factor(
                name='ציר זמן הפוליסה' if is_hebrew else 'Policy Timeline',
                value=timeline_info,
                importance=0.85,
                category='hebrew_insurance'
            ))
        
        # Insured Person Factor
        person_info = {}
        if 'id_number' in hebrew_extracted:
            # Mask ID for privacy
            id_num = hebrew_extracted['id_number']
            masked_id = id_num[:2] + '*****' + id_num[-2:] if len(id_num) >= 4 else '***'
            person_info['ת.ז.' if is_hebrew else 'id'] = masked_id
        if 'insured_name' in hebrew_extracted:
            person_info['שם מבוטח' if is_hebrew else 'insured_name'] = hebrew_extracted['insured_name']
        if 'beneficiary' in hebrew_extracted:
            person_info['מוטב' if is_hebrew else 'beneficiary'] = hebrew_extracted['beneficiary']
        
        if person_info:
            factors.append(Factor(
                name='פרטי מבוטח' if is_hebrew else 'Insured Details',
                value=person_info,
                importance=0.8,
                category='hebrew_insurance'
            ))
        
        return factors
    
    def _find_hebrew_patterns(self, hebrew_extracted: Dict[str, Any]) -> List[Pattern]:
        """
        Find patterns specific to Hebrew insurance documents.
        """
        patterns = []
        
        # Policy age pattern
        if 'policy_age_years' in hebrew_extracted:
            age = hebrew_extracted['policy_age_years']
            if age > 20:
                patterns.append(Pattern(
                    type='policy_veteran',
                    description=f"פוליסה ותיקה מאוד ({age} שנים) - מומלץ לבדוק תנאים מול מוצרים חדשים בשוק",
                    affected_rows=[],
                    significance=0.9
                ))
            elif age > 10:
                patterns.append(Pattern(
                    type='policy_mature',
                    description=f"פוליסה בשלה ({age} שנים) - ייתכן שצברה ערכים או בונוסים",
                    affected_rows=[],
                    significance=0.7
                ))
        
        # Coverage efficiency pattern
        if 'efficiency_rating' in hebrew_extracted:
            rating = hebrew_extracted['efficiency_rating']
            if rating == 'review_recommended':
                patterns.append(Pattern(
                    type='coverage_efficiency',
                    description="יחס כיסוי/פרמיה נמוך - מומלץ לבחון חלופות בשוק",
                    affected_rows=[],
                    significance=0.85
                ))
            elif rating == 'excellent':
                patterns.append(Pattern(
                    type='coverage_efficiency',
                    description="יחס כיסוי/פרמיה מצוין - הפוליסה מספקת ערך טוב",
                    affected_rows=[],
                    significance=0.6
                ))
        
        # Product type patterns
        if 'product_type' in hebrew_extracted:
            ptype = hebrew_extracted['product_type']
            if ptype == 'pension':
                patterns.append(Pattern(
                    type='pension_product',
                    description="מוצר פנסיוני - יש לבדוק דמי ניהול ומסלול השקעה",
                    affected_rows=[],
                    significance=0.8
                ))
            elif ptype == 'life':
                patterns.append(Pattern(
                    type='life_insurance',
                    description="ביטוח חיים - יש לוודא שסכום הכיסוי מתאים לצרכים הנוכחיים",
                    affected_rows=[],
                    significance=0.75
                ))
        
        return patterns
    
    def _generate_domain_insights(self, data_type: DataType, profiles: Dict[str, Dict],
                                  rows: List[Dict], lang: str, 
                                  hebrew_extracted: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Generate domain-specific insights based on data type.
        Enhanced with Hebrew document extraction insights.
        """
        insights = {
            'domain': data_type.value,
            'language': lang,
            'key_findings': [],
            'recommendations': [],
            'metrics': {},
            'hebrew_data': hebrew_extracted or {}
        }
        
        # Find currency/amount columns
        currency_cols = [col for col, p in profiles.items() 
                        if p.get('semantic_type') == 'currency' or 
                        any(x in col.lower() for x in ['amount', 'premium', 'price', 'סכום', 'פרמיה', 'מחיר'])]
        
        is_hebrew = lang == 'hebrew'
        
        # Add Hebrew document insights if available
        if hebrew_extracted:
            # Policy details finding
            if 'policy_number' in hebrew_extracted:
                insights['key_findings'].append({
                    'type': 'policy_identification',
                    'finding': f"זוהתה פוליסה מס': {hebrew_extracted['policy_number']}" if is_hebrew else f"Identified policy: {hebrew_extracted['policy_number']}",
                    'detail': hebrew_extracted.get('insurance_type', hebrew_extracted.get('product_type', ''))
                })
            
            # Financial metrics finding
            if 'premium' in hebrew_extracted:
                premium = hebrew_extracted['premium']
                insights['key_findings'].append({
                    'type': 'premium_analysis',
                    'finding': f"פרמיה חודשית: ₪{premium}" if is_hebrew else f"Monthly Premium: ₪{premium}",
                    'detail': f"עלות שנתית: ₪{float(premium) * 12:,.0f}" if is_hebrew else f"Annual cost: ₪{float(premium) * 12:,.0f}"
                })
                insights['metrics']['premium'] = {
                    'monthly': premium,
                    'annual': float(premium) * 12 if isinstance(premium, (int, float)) else premium
                }
            
            if 'cover_amount' in hebrew_extracted:
                cover = hebrew_extracted['cover_amount']
                insights['key_findings'].append({
                    'type': 'coverage_analysis',
                    'finding': f"סכום כיסוי: ₪{cover:,}" if is_hebrew and isinstance(cover, (int, float)) else f"Cover Amount: ₪{cover}",
                    'detail': ''
                })
                insights['metrics']['cover_amount'] = cover
            
            # Policy age finding
            if 'policy_age_years' in hebrew_extracted:
                age = hebrew_extracted['policy_age_years']
                status = hebrew_extracted.get('status', '')
                status_hebrew = {'veteran': 'ותיקה', 'mature': 'בשלה', 'established': 'מבוססת', 'new': 'חדשה'}.get(status, status)
                insights['key_findings'].append({
                    'type': 'policy_age',
                    'finding': f"ותק הפוליסה: {age} שנים" if is_hebrew else f"Policy Age: {age} years",
                    'detail': f"סטטוס: {status_hebrew}" if is_hebrew else f"Status: {status}"
                })
            
            # Coverage efficiency finding
            if 'efficiency_rating' in hebrew_extracted:
                rating = hebrew_extracted['efficiency_rating']
                rating_hebrew = {'excellent': 'מצוין', 'good': 'טוב', 'fair': 'סביר', 'review_recommended': 'מומלץ לבדיקה'}.get(rating, rating)
                insights['key_findings'].append({
                    'type': 'efficiency_rating',
                    'finding': f"דירוג יעילות: {rating_hebrew}" if is_hebrew else f"Efficiency Rating: {rating}",
                    'detail': f"יחס כיסוי/פרמיה: {hebrew_extracted.get('coverage_ratio', 'N/A')}" if is_hebrew else f"Coverage ratio: {hebrew_extracted.get('coverage_ratio', 'N/A')}"
                })
            
            # Hebrew-specific recommendations
            if is_hebrew:
                if hebrew_extracted.get('policy_age_years', 0) > 15:
                    insights['recommendations'].append('פוליסה ותיקה - מומלץ לבדוק האם התנאים עדיין תחרותיים')
                if hebrew_extracted.get('efficiency_rating') == 'review_recommended':
                    insights['recommendations'].append('יחס כיסוי/פרמיה נמוך - כדאי לקבל הצעות מחיר נוספות')
                if 'pension' in str(hebrew_extracted.get('product_type', '')):
                    insights['recommendations'].append('מוצר פנסיוני - בדוק דמי ניהול ומסלולי השקעה')
                insights['recommendations'].append('ודא שהמוטבים מעודכנים')
                insights['recommendations'].append('בדוק התאמת סכומי הכיסוי לצרכים הנוכחיים')
        
        if data_type == DataType.INSURANCE:
            insights['key_findings'].append({
                'type': 'domain_classification',
                'finding': 'ניתוח נתוני ביטוח' if is_hebrew else 'Insurance data analysis',
                'detail': f'{len(rows)} רשומות נותחו' if is_hebrew else f'{len(rows)} records analyzed'
            })
            
            # Insurance-specific metrics
            for col in currency_cols[:2]:
                if col in profiles and profiles[col]['stats']:
                    stats = profiles[col]['stats']
                    insights['metrics'][col] = {
                        'total': stats.get('sum', 0),
                        'average': stats.get('mean', 0),
                        'range': f"{stats.get('min', 0)} - {stats.get('max', 0)}"
                    }
            
            if is_hebrew and not hebrew_extracted:
                insights['recommendations'].append('בדוק כיסויים ביטוחיים מול צרכים')
                insights['recommendations'].append('השווה פרמיות לממוצע בשוק')
            elif not is_hebrew:
                insights['recommendations'].append('Review coverage adequacy against needs')
                insights['recommendations'].append('Compare premiums to market average')
                
        elif data_type == DataType.INVESTMENT:
            insights['key_findings'].append({
                'type': 'domain_classification',
                'finding': 'ניתוח תיק השקעות' if is_hebrew else 'Investment portfolio analysis',
                'detail': f'{len(rows)} נכסים נותחו' if is_hebrew else f'{len(rows)} assets analyzed'
            })
            
            if is_hebrew:
                insights['recommendations'].append('בדוק פיזור התיק')
                insights['recommendations'].append('נתח יחס תשואה/סיכון')
            else:
                insights['recommendations'].append('Review portfolio diversification')
                insights['recommendations'].append('Analyze return/risk ratio')
                
        elif data_type == DataType.SAVINGS:
            insights['key_findings'].append({
                'type': 'domain_classification',
                'finding': 'ניתוח חיסכון' if is_hebrew else 'Savings analysis',
                'detail': f'{len(rows)} רשומות' if is_hebrew else f'{len(rows)} records'
            })
            
        elif data_type == DataType.RISK:
            insights['key_findings'].append({
                'type': 'domain_classification',
                'finding': 'הערכת סיכונים' if is_hebrew else 'Risk assessment',
                'detail': f'{len(rows)} גורמי סיכון נותחו' if is_hebrew else f'{len(rows)} risk factors analyzed'
            })
        
        # Add data quality insight
        complete_cols = sum(1 for p in profiles.values() if p['null_count'] == 0)
        completeness = round(complete_cols / max(len(profiles), 1) * 100, 1)
        
        insights['key_findings'].append({
            'type': 'data_quality',
            'finding': f'שלמות נתונים: {completeness}%' if is_hebrew else f'Data completeness: {completeness}%',
            'detail': f'{complete_cols}/{len(profiles)} שדות מלאים' if is_hebrew else f'{complete_cols}/{len(profiles)} fields complete'
        })
        
        return insights
    
    def _calculate_risk_score_advanced(self, factors: List[Factor], patterns: List[Pattern],
                                       anomalies: List[Anomaly], correlations: List[Dict],
                                       domain_insights: Dict) -> float:
        """
        Calculate comprehensive risk score using multiple factors.
        """
        base_score = 35  # Start at low-medium risk
        
        # Factor-based adjustment
        for factor in factors:
            if factor.category == 'statistical':
                # High variance increases risk
                if isinstance(factor.value, dict) and factor.value.get('std_dev', 0) > factor.value.get('mean', 1) * 0.5:
                    base_score += 5
        
        # Pattern-based adjustment
        for pattern in patterns:
            if pattern.type == 'data_quality':
                base_score += 10
            elif pattern.type == 'outliers':
                base_score += pattern.significance * 8
            elif pattern.type == 'correlation':
                # Negative correlations in financial data can be risk indicators
                pass
        
        # Anomaly-based adjustment
        for anomaly in anomalies:
            if anomaly.severity == Severity.CRITICAL:
                base_score += 15
            elif anomaly.severity == Severity.HIGH:
                base_score += 10
            elif anomaly.severity == Severity.MEDIUM:
                base_score += 5
            else:
                base_score += 2
        
        # Domain-specific adjustment
        domain = domain_insights.get('domain', 'unknown')
        if domain == 'risk':
            base_score += 15  # Risk data inherently higher
        
        return min(max(base_score, 0), 100)
    
    def _generate_summary_advanced(self, lang: str, data_type: DataType, row_count: int,
                                   factors: List[Factor], risk_score: float,
                                   profiles: Dict[str, Dict], domain_insights: Dict) -> str:
        """
        Generate comprehensive language-aware summary.
        """
        risk_level = 'נמוך' if lang == 'hebrew' else 'Low'
        if risk_score >= 60:
            risk_level = 'גבוה' if lang == 'hebrew' else 'High'
        elif risk_score >= 30:
            risk_level = 'בינוני' if lang == 'hebrew' else 'Medium'
        
        numeric_cols = sum(1 for p in profiles.values() if p['numeric'])
        cat_cols = len(profiles) - numeric_cols
        
        if lang == 'hebrew':
            type_names = {
                'insurance': 'ביטוח',
                'investment': 'השקעות',
                'risk': 'סיכונים',
                'savings': 'חיסכון',
                'mixed': 'מעורב',
                'unknown': 'כללי'
            }
            type_name = type_names.get(data_type.value, 'נתונים')
            
            summary = f"""ניתוח AI מקיף של נתוני {type_name}:

📊 סטטיסטיקה:
• {row_count} רשומות נותחו
• {len(profiles)} שדות זוהו ({numeric_cols} מספריים, {cat_cols} קטגוריים)
• {len(factors)} גורמים מרכזיים חולצו

🎯 הערכת סיכון: {risk_score:.0f}/100 ({risk_level})

📈 תובנות עיקריות:
"""
            for finding in domain_insights.get('key_findings', [])[:3]:
                summary += f"• {finding['finding']}: {finding['detail']}\n"
            
        else:
            type_names = {
                'insurance': 'Insurance',
                'investment': 'Investment',
                'risk': 'Risk',
                'savings': 'Savings',
                'mixed': 'Mixed',
                'unknown': 'General'
            }
            type_name = type_names.get(data_type.value, 'Data')
            
            summary = f"""Comprehensive AI Analysis of {type_name} Data:

📊 Statistics:
• {row_count} records analyzed
• {len(profiles)} fields identified ({numeric_cols} numeric, {cat_cols} categorical)
• {len(factors)} key factors extracted

🎯 Risk Assessment: {risk_score:.0f}/100 ({risk_level})

📈 Key Insights:
"""
            for finding in domain_insights.get('key_findings', [])[:3]:
                summary += f"• {finding['finding']}: {finding['detail']}\n"
        
        return summary
    
    def _extract_key_metrics_advanced(self, rows: List[Dict], columns: List[str],
                                      data_type: DataType, profiles: Dict[str, Dict],
                                      correlations: List[Dict], domain_insights: Dict) -> Dict[str, Any]:
        """
        Extract comprehensive key metrics including BI indicators.
        """
        metrics = {
            'total_records': len(rows),
            'total_columns': len(columns),
            'data_type': data_type.value,
            'numeric_columns': sum(1 for p in profiles.values() if p['numeric']),
            'categorical_columns': sum(1 for p in profiles.values() if not p['numeric']),
            'correlation_count': len(correlations)
        }
        
        # Data quality metrics
        total_cells = len(rows) * len(columns)
        null_cells = sum(p['null_count'] for p in profiles.values())
        metrics['data_completeness'] = round((1 - null_cells / max(total_cells, 1)) * 100, 1)
        
        # Add column-specific metrics
        for col, profile in list(profiles.items())[:10]:
            if profile['numeric'] and profile['stats']:
                metrics[f'{col}_total'] = profile['stats'].get('sum', 0)
                metrics[f'{col}_avg'] = profile['stats'].get('mean', 0)
                metrics[f'{col}_min'] = profile['stats'].get('min', 0)
                metrics[f'{col}_max'] = profile['stats'].get('max', 0)
        
        # Add domain metrics
        metrics['domain_metrics'] = domain_insights.get('metrics', {})
        
        # Add top correlations
        if correlations:
            metrics['top_correlation'] = {
                'fields': f"{correlations[0]['column1']} ↔ {correlations[0]['column2']}",
                'strength': correlations[0]['correlation']
            }
        
        return metrics
    
    def _extract_factors(self, columns: List[str], rows: List[Dict], data_type: DataType) -> List[Factor]:
        """Extract key factors from the data"""
        factors = []
        
        # Identify numeric columns
        numeric_cols = []
        for col in columns:
            if rows:
                sample = rows[0].get(col, '')
                try:
                    float(str(sample).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                    numeric_cols.append(col)
                except (ValueError, TypeError):
                    pass
        
        # Calculate statistics for numeric columns
        for col in numeric_cols[:5]:  # Top 5 numeric columns
            values = []
            for row in rows:
                try:
                    val = float(str(row.get(col, 0)).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                    values.append(val)
                except (ValueError, TypeError):
                    continue
            
            if values:
                avg = sum(values) / len(values)
                total = sum(values)
                factors.append(Factor(
                    name=col,
                    value={'average': round(avg, 2), 'total': round(total, 2), 'count': len(values)},
                    importance=0.7 if data_type != DataType.UNKNOWN else 0.5,
                    category='numeric_metric'
                ))
        
        # Data type specific factors
        if data_type == DataType.INSURANCE:
            factors.append(Factor(
                name='Coverage Analysis',
                value={'records': len(rows), 'type': 'insurance'},
                importance=0.9,
                category='insurance'
            ))
        elif data_type == DataType.INVESTMENT:
            factors.append(Factor(
                name='Portfolio Analysis',
                value={'records': len(rows), 'type': 'investment'},
                importance=0.9,
                category='investment'
            ))
        elif data_type == DataType.RISK:
            factors.append(Factor(
                name='Risk Assessment',
                value={'records': len(rows), 'type': 'risk'},
                importance=0.95,
                category='risk'
            ))
        
        return factors
    
    def _find_patterns(self, rows: List[Dict], data_type: DataType) -> List[Pattern]:
        """Find patterns in the data"""
        patterns = []
        
        if len(rows) < 2:
            return patterns
        
        # Look for duplicate values
        for key in list(rows[0].keys())[:5]:
            values = [row.get(key) for row in rows if row.get(key)]
            unique_values = set(values)
            if len(values) > len(unique_values):
                dup_count = len(values) - len(unique_values)
                patterns.append(Pattern(
                    type='duplicate_values',
                    description=f'Found {dup_count} duplicate values in column "{key}"',
                    affected_rows=[i for i, v in enumerate(values) if values.count(v) > 1],
                    significance=0.6
                ))
        
        # Look for empty values
        empty_counts = {}
        for key in rows[0].keys():
            empty_count = sum(1 for row in rows if not row.get(key))
            if empty_count > 0:
                empty_counts[key] = empty_count
        
        if empty_counts:
            max_empty = max(empty_counts.values())
            if max_empty > len(rows) * 0.1:  # More than 10% empty
                patterns.append(Pattern(
                    type='missing_data',
                    description=f'Found columns with missing data: {list(empty_counts.keys())}',
                    affected_rows=list(range(len(rows))),
                    significance=0.7
                ))
        
        return patterns
    
    def _detect_anomalies(self, rows: List[Dict], data_type: DataType) -> List[Anomaly]:
        """Detect anomalies in the data"""
        anomalies = []
        
        if len(rows) < 3:
            return anomalies
        
        # Look for outliers in numeric columns
        for key in list(rows[0].keys())[:5]:
            values = []
            for row in rows:
                try:
                    val = float(str(row.get(key, 0)).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                    values.append(val)
                except (ValueError, TypeError):
                    continue
            
            if len(values) >= 3:
                avg = sum(values) / len(values)
                std_dev = (sum((x - avg) ** 2 for x in values) / len(values)) ** 0.5
                
                if std_dev > 0:
                    outliers = [v for v in values if abs(v - avg) > 2 * std_dev]
                    if outliers:
                        anomalies.append(Anomaly(
                            type='outlier',
                            severity=Severity.MEDIUM if len(outliers) < 3 else Severity.HIGH,
                            description=f'Found {len(outliers)} outlier values in column "{key}"',
                            affected_data={'column': key, 'outliers': outliers[:5]},
                            recommendation=f'Review the extreme values in {key} for accuracy'
                        ))
        
        return anomalies
    
    def _calculate_risk_score(self, factors: List[Factor], patterns: List[Pattern], anomalies: List[Anomaly]) -> float:
        """Calculate overall risk score (0-100)"""
        base_score = 50  # Start at medium risk
        
        # Adjust based on anomalies
        for anomaly in anomalies:
            if anomaly.severity == Severity.CRITICAL:
                base_score += 20
            elif anomaly.severity == Severity.HIGH:
                base_score += 10
            elif anomaly.severity == Severity.MEDIUM:
                base_score += 5
            else:
                base_score += 2
        
        # Adjust based on patterns
        for pattern in patterns:
            if pattern.type == 'missing_data':
                base_score += pattern.significance * 15
            elif pattern.type == 'duplicate_values':
                base_score += pattern.significance * 5
        
        # Adjust based on factors
        for factor in factors:
            if factor.category == 'risk':
                base_score += factor.importance * 10
        
        return min(max(base_score, 0), 100)
    
    def _generate_summary(self, lang: str, data_type: DataType, row_count: int, 
                          factors: List[Factor], risk_score: float) -> str:
        """Generate a summary of the analysis"""
        summaries = {
            'hebrew': {
                'insurance': f'ניתוח נתוני ביטוח: {row_count} רשומות נותחו. ציון סיכון: {risk_score:.1f}/100.',
                'investment': f'ניתוח תיק השקעות: {row_count} רשומות נותחו. ציון סיכון: {risk_score:.1f}/100.',
                'risk': f'הערכת סיכונים: {row_count} רשומות נותחו. ציון סיכון כולל: {risk_score:.1f}/100.',
                'savings': f'ניתוח חיסכון: {row_count} רשומות נותחו. ציון סיכון: {risk_score:.1f}/100.',
                'default': f'ניתוח נתונים: {row_count} רשומות נותחו. ציון סיכון: {risk_score:.1f}/100.'
            },
            'english': {
                'insurance': f'Insurance data analysis: {row_count} records analyzed. Risk score: {risk_score:.1f}/100.',
                'investment': f'Investment portfolio analysis: {row_count} records analyzed. Risk score: {risk_score:.1f}/100.',
                'risk': f'Risk assessment analysis: {row_count} records analyzed. Overall risk score: {risk_score:.1f}/100.',
                'savings': f'Savings analysis: {row_count} records analyzed. Risk score: {risk_score:.1f}/100.',
                'default': f'Data analysis: {row_count} records analyzed. Risk score: {risk_score:.1f}/100.'
            }
        }
        
        lang_summaries = summaries.get(lang, summaries['english'])
        return lang_summaries.get(data_type.value, lang_summaries['default'])
    
    def _extract_key_metrics(self, rows: List[Dict], columns: List[str], data_type: DataType) -> Dict[str, Any]:
        """Extract key metrics from the data"""
        metrics = {
            'total_records': len(rows),
            'columns_count': len(columns),
            'data_type': data_type.value
        }
        
        # Calculate totals for numeric columns
        for col in columns[:10]:
            values = []
            for row in rows:
                try:
                    val = float(str(row.get(col, 0)).replace(',', '').replace('₪', '').replace('$', '').replace('€', ''))
                    values.append(val)
                except (ValueError, TypeError):
                    continue
            
            if values:
                metrics[f'{col}_total'] = round(sum(values), 2)
                metrics[f'{col}_avg'] = round(sum(values) / len(values), 2)
                metrics[f'{col}_min'] = round(min(values), 2)
                metrics[f'{col}_max'] = round(max(values), 2)
        
        return metrics
    
    def generate_report(self, analysis_id: str, language: str = None) -> GeneratedReport:
        """Generate a comprehensive report from analysis results"""
        if analysis_id not in self.analyses:
            raise ValueError(f"Analysis {analysis_id} not found")
        
        analysis = self.analyses[analysis_id]
        lang = language or analysis.language
        
        report_id = f"RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        # Retrieve original document data for content analysis
        doc_data = None
        pension_data = None
        pension_report = None
        if analysis.document_id in self.documents:
            doc = self.documents[analysis.document_id]
            doc_data = doc.get('parsed_data', {})
            # Check for pension data from ZIP files
            if doc_data:
                pension_data = doc_data.get('pension_data')
                pension_report = doc_data.get('pension_report')
        
        affiliation_matrix = self._build_affiliation_matrix_metadata(doc_data, pension_data, analysis)

        # Generate sections based on data type (now with original data and pension data)
        sections = self._generate_sections(
            analysis,
            lang,
            doc_data,
            pension_data,
            pension_report,
            affiliation_matrix
        )
        
        # Generate charts - pass pension_data for specialized pension charts
        charts = self._generate_charts(analysis, pension_data, doc_data, affiliation_matrix)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(analysis, lang)
        
        # Determine report title
        titles = {
            'hebrew': {
                'insurance': 'דו״ח ניתוח ביטוח',
                'investment': 'דו״ח ניתוח השקעות',
                'risk': 'דו״ח הערכת סיכונים',
                'savings': 'דו״ח ניתוח חיסכון',
                'default': 'דו״ח ניתוח נתונים'
            },
            'english': {
                'insurance': 'Insurance Analysis Report',
                'investment': 'Investment Analysis Report',
                'risk': 'Risk Assessment Report',
                'savings': 'Savings Analysis Report',
                'default': 'Data Analysis Report'
            }
        }
        
        lang_titles = titles.get(lang, titles['english'])
        title = lang_titles.get(analysis.data_classification.value, lang_titles['default'])

        allocation_snapshot = {}
        if doc_data:
            allocation_info = self._categorize_rows_by_pdf_example(
                doc_data.get('rows', []) or [],
                doc_data.get('columns', []) or []
            )
            allocation_snapshot = {
                'model': allocation_info.get('allocation_model', 'kfir_122022_pdf'),
                'total_rows': allocation_info.get('total_rows', 0),
                'unallocated_rows': allocation_info.get('unallocated_rows', 0),
                'categories': len(allocation_info.get('summary', [])),
            }
        
        report = GeneratedReport(
            id=report_id,
            analysis_id=analysis_id,
            report_type=analysis.data_classification.value,
            language=lang,
            title=title,
            sections=sections,
            charts=charts,
            recommendations=recommendations,
            generated_at=datetime.now().isoformat(),
            metadata={
                'document_id': analysis.document_id,
                'risk_score': analysis.risk_score,
                'confidence': analysis.confidence,
                'processing_time_ms': analysis.processing_time_ms,
                # Include raw pension data for frontend display
                'pension_data': pension_data if pension_data else None,
                'is_pension_data': pension_data is not None or pension_report is not None,
                'affiliation_snapshot': self._build_affiliation_snapshot_metadata(),
                'affiliation_matrix': affiliation_matrix,
                'example_allocation_snapshot': allocation_snapshot,
            }
        )
        
        self.reports[report_id] = report
        
        # Auto-save for persistence
        self.save_data()
        
        return report
    
    def _generate_sections(self, analysis: AnalysisResult, lang: str, 
                          doc_data: Dict[str, Any] = None,
                          pension_data: Dict[str, Any] = None,
                          pension_report: str = None,
                          affiliation_matrix: Dict[str, Any] = None) -> List[ReportSection]:
        """Generate comprehensive report sections with AI/BI insights and actual data content"""
        sections = []
        is_hebrew = lang == 'hebrew'
        
        # 1. Executive Summary
        sections.append(ReportSection(
            title='תקציר מנהלים' if is_hebrew else 'Executive Summary',
            content=analysis.summary,
            order=1
        ))
        
        # 2. PENSION DATA SECTION - Display pension report from PensionDataAgent
        if pension_data or pension_report:
            pension_section = self._generate_pension_section(pension_data, pension_report, is_hebrew)
            if pension_section:
                sections.append(ReportSection(
                    title='דו״ח ניתוח פנסיה וביטוח' if is_hebrew else 'Pension & Insurance Analysis Report',
                    content=pension_section,
                    order=2
                ))
            sections.extend(self._build_pension_affiliated_sections(pension_data, is_hebrew))
        
        # 3. ACTUAL DATA CONTENT SECTION - Show extracted data from the files
        if doc_data:
            data_content_section = self._generate_data_content_section(doc_data, analysis, is_hebrew)
            if data_content_section:
                sections.append(ReportSection(
                    title='תוכן הנתונים שהועלו' if is_hebrew else 'Uploaded Data Content',
                    content=data_content_section,
                    order=3
                ))
            full_data_section = self._build_uploaded_data_table_section(doc_data, is_hebrew)
            if full_data_section:
                sections.append(full_data_section)
            policy_cumulative_section = self._build_policy_cumulative_section_from_rows(
                doc_data.get('rows', []) or [],
                doc_data.get('columns', []) or [],
                is_hebrew
            )
            if policy_cumulative_section:
                sections.append(policy_cumulative_section)
            sections.extend(self._build_pdf_example_allocation_sections(doc_data, is_hebrew))
        
        # 3. Hebrew Insurance Details (if extracted)
        hebrew_factors = [f for f in analysis.extracted_factors if f.category == 'hebrew_insurance']
        if hebrew_factors:
            hebrew_content = self._generate_hebrew_insurance_section(hebrew_factors, is_hebrew)
            sections.append(ReportSection(
                title='פרטי פוליסת ביטוח' if is_hebrew else 'Insurance Policy Details',
                content=hebrew_content,
                order=3
            ))
        
        # 4. Data Profile Overview
        total_records = analysis.key_metrics.get('total_records', 0)
        numeric_cols = analysis.key_metrics.get('numeric_columns', 0)
        cat_cols = analysis.key_metrics.get('categorical_columns', 0)
        completeness = analysis.key_metrics.get('data_completeness', 100)
        
        if is_hebrew:
            profile_content = f"""📊 פרופיל הנתונים:

• סה"כ רשומות: {total_records}
• שדות מספריים: {numeric_cols}
• שדות קטגוריים: {cat_cols}
• שלמות נתונים: {completeness}%
• סוג נתונים: {analysis.data_classification.value}
• שפה: {analysis.language_name}
• רמת ביטחון: {analysis.confidence:.0%}"""
        else:
            profile_content = f"""📊 Data Profile:

• Total Records: {total_records}
• Numeric Fields: {numeric_cols}
• Categorical Fields: {cat_cols}
• Data Completeness: {completeness}%
• Data Type: {analysis.data_classification.value}
• Language: {analysis.language_name}
• Confidence Level: {analysis.confidence:.0%}"""
        
        sections.append(ReportSection(
            title='פרופיל נתונים' if is_hebrew else 'Data Profile',
            content=profile_content,
            order=2
        ))
        
        # 3. Statistical Analysis (BI Metrics)
        # SKIP for pension data - the pension report already shows meaningful data clearly
        # Statistical analysis of IDs/policy numbers is meaningless
        if not pension_report:  # Only show statistical analysis for non-pension data
            stat_factors = [f for f in analysis.extracted_factors if f.category == 'statistical']
            if stat_factors:
                if is_hebrew:
                    stats_lines = ['📈 ניתוח סטטיסטי מפורט:\n']
                    for f in stat_factors[:8]:
                        if isinstance(f.value, dict):
                            stats_lines.append(f"🔹 {f.name}:")
                            stats_lines.append(f"   • ממוצע: {f.value.get('mean', 'N/A')}")
                            stats_lines.append(f"   • חציון: {f.value.get('median', 'N/A')}")
                            stats_lines.append(f"   • טווח: {f.value.get('range', 'N/A')}")
                            stats_lines.append(f"   • סטיית תקן: {f.value.get('std_dev', 'N/A')}")
                            stats_lines.append(f"   • התפלגות: {f.value.get('distribution', 'N/A')}")
                            stats_lines.append("")
                else:
                    stats_lines = ['📈 Detailed Statistical Analysis:\n']
                    for f in stat_factors[:8]:
                        if isinstance(f.value, dict):
                            stats_lines.append(f"🔹 {f.name}:")
                            stats_lines.append(f"   • Mean: {f.value.get('mean', 'N/A')}")
                            stats_lines.append(f"   • Median: {f.value.get('median', 'N/A')}")
                            stats_lines.append(f"   • Range: {f.value.get('range', 'N/A')}")
                            stats_lines.append(f"   • Std Dev: {f.value.get('std_dev', 'N/A')}")
                            stats_lines.append(f"   • Distribution: {f.value.get('distribution', 'N/A')}")
                            stats_lines.append("")
                
                sections.append(ReportSection(
                    title='ניתוח סטטיסטי' if is_hebrew else 'Statistical Analysis',
                    content='\n'.join(stats_lines),
                    order=3
                ))
        
        # 4. Correlation Insights
        top_corr = analysis.key_metrics.get('top_correlation')
        if top_corr:
            if is_hebrew:
                corr_content = f"""🔗 מתאמים שזוהו:

• הקשר החזק ביותר: {top_corr.get('fields', '')}
• עוצמת המתאם: {top_corr.get('strength', 0)}

💡 משמעות: מתאמים אלו מצביעים על קשרים פוטנציאליים בין משתנים שיש לקחת בחשבון בניתוח."""
            else:
                corr_content = f"""🔗 Correlations Discovered:

• Strongest Relationship: {top_corr.get('fields', '')}
• Correlation Strength: {top_corr.get('strength', 0)}

💡 Significance: These correlations indicate potential relationships between variables that should be considered in the analysis."""
            
            sections.append(ReportSection(
                title='ניתוח מתאמים' if is_hebrew else 'Correlation Analysis',
                content=corr_content,
                order=4
            ))
        
        # 5. Patterns & Trends
        if analysis.patterns_found:
            if is_hebrew:
                patterns_lines = ['🔍 דפוסים ומגמות שזוהו:\n']
                for i, p in enumerate(analysis.patterns_found, 1):
                    patterns_lines.append(f"{i}. [{p.type}] {p.description}")
                    patterns_lines.append(f"   משמעות: {p.significance:.0%}")
                    patterns_lines.append("")
            else:
                patterns_lines = ['🔍 Identified Patterns & Trends:\n']
                for i, p in enumerate(analysis.patterns_found, 1):
                    patterns_lines.append(f"{i}. [{p.type}] {p.description}")
                    patterns_lines.append(f"   Significance: {p.significance:.0%}")
                    patterns_lines.append("")
            
            sections.append(ReportSection(
                title='דפוסים ומגמות' if is_hebrew else 'Patterns & Trends',
                content='\n'.join(patterns_lines),
                order=5
            ))
        
        # 6. Anomalies & Warnings
        if analysis.anomalies:
            if is_hebrew:
                anomaly_lines = ['⚠️ חריגות ואזהרות:\n']
                severity_map = {'critical': '🔴 קריטי', 'high': '🟠 גבוה', 'medium': '🟡 בינוני', 'low': '🟢 נמוך'}
                for a in analysis.anomalies:
                    sev_label = severity_map.get(a.severity.value, a.severity.value)
                    anomaly_lines.append(f"• {sev_label}: {a.description}")
                    anomaly_lines.append(f"  📋 המלצה: {a.recommendation}")
                    anomaly_lines.append("")
            else:
                anomaly_lines = ['⚠️ Anomalies & Warnings:\n']
                severity_map = {'critical': '🔴 Critical', 'high': '🟠 High', 'medium': '🟡 Medium', 'low': '🟢 Low'}
                for a in analysis.anomalies:
                    sev_label = severity_map.get(a.severity.value, a.severity.value)
                    anomaly_lines.append(f"• {sev_label}: {a.description}")
                    anomaly_lines.append(f"  📋 Recommendation: {a.recommendation}")
                    anomaly_lines.append("")
            
            sections.append(ReportSection(
                title='חריגות ואזהרות' if is_hebrew else 'Anomalies & Warnings',
                content='\n'.join(anomaly_lines),
                order=6
            ))
        
        # 7. Risk Assessment
        risk_score = analysis.risk_score
        if risk_score < 30:
            risk_level = 'נמוך' if is_hebrew else 'Low'
            risk_color = '🟢'
            risk_desc = 'הנתונים מצביעים על רמת סיכון נמוכה' if is_hebrew else 'Data indicates low risk level'
        elif risk_score < 60:
            risk_level = 'בינוני' if is_hebrew else 'Medium'
            risk_color = '🟡'
            risk_desc = 'יש לשים לב לגורמי סיכון מסוימים' if is_hebrew else 'Some risk factors require attention'
        else:
            risk_level = 'גבוה' if is_hebrew else 'High'
            risk_color = '🔴'
            risk_desc = 'נדרשת בדיקה מעמיקה של גורמי הסיכון' if is_hebrew else 'In-depth review of risk factors required'
        
        if is_hebrew:
            risk_content = f"""🎯 הערכת סיכון כוללת:

{risk_color} ציון סיכון: {risk_score:.0f}/100
📊 רמת סיכון: {risk_level}

{risk_desc}

גורמים המשפיעים על הציון:
• מספר חריגות: {len(analysis.anomalies)}
• דפוסים חריגים: {len([p for p in analysis.patterns_found if p.significance > 0.5])}
• שלמות נתונים: {completeness}%"""
        else:
            risk_content = f"""🎯 Overall Risk Assessment:

{risk_color} Risk Score: {risk_score:.0f}/100
📊 Risk Level: {risk_level}

{risk_desc}

Factors Affecting Score:
• Number of anomalies: {len(analysis.anomalies)}
• Unusual patterns: {len([p for p in analysis.patterns_found if p.significance > 0.5])}
• Data completeness: {completeness}%"""
        
        sections.append(ReportSection(
            title='הערכת סיכון' if is_hebrew else 'Risk Assessment',
            content=risk_content,
            order=7
        ))
        
        # 8. Key Metrics Table
        metrics_items = []
        for k, v in list(analysis.key_metrics.items())[:15]:
            if not k.startswith('domain_') and k != 'top_correlation':
                if isinstance(v, float):
                    metrics_items.append(f"• {k}: {v:.2f}")
                else:
                    metrics_items.append(f"• {k}: {v}")
        
        sections.append(ReportSection(
            title='מדדים מרכזיים' if is_hebrew else 'Key Metrics',
            content='\n'.join(metrics_items),
            data_table=analysis.key_metrics,
            order=8
        ))

        # 9. Affiliation Snapshot (Mislaka schema codes)
        affiliation_section = self._build_affiliation_mapping_section(is_hebrew)
        if affiliation_section:
            sections.append(affiliation_section)

        matrix_sections = self._build_affiliation_matrix_sections(affiliation_matrix, is_hebrew)
        if matrix_sections:
            sections.extend(matrix_sections)
        
        # 10. Swiftness Data Resources & References
        swiftness_section = self._generate_swiftness_resources_section(is_hebrew)
        if swiftness_section:
            sections.append(ReportSection(
                title='משאבי נתונים - Swiftness' if is_hebrew else 'Swiftness Data Resources',
                content=swiftness_section,
                order=10
            ))
        
        return sections

    def _build_affiliation_snapshot_metadata(self) -> Dict[str, Any]:
        """Build compact affiliation metadata without mutating source mappings."""
        try:
            from services.pension_data_agent import MislakaSchemaMapping

            return {
                'interface_codes': len(MislakaSchemaMapping.INTERFACE_CODES),
                'product_types': len(MislakaSchemaMapping.PRODUCT_TYPE_CODES),
                'entity_types': len(MislakaSchemaMapping.ENTITY_TYPE_CODES),
                'status_codes': len(MislakaSchemaMapping.STATUS_CODES),
                'id_types': len(MislakaSchemaMapping.ID_TYPE_CODES),
                'environment_codes': len(MislakaSchemaMapping.ENVIRONMENT_CODES),
                'source': 'MislakaSchemaMapping'
            }
        except Exception:
            return {}

    @staticmethod
    def _normalize_affiliation_term(value: Any) -> str:
        """Normalize text for affiliation matrix matching."""
        if value is None:
            return ''
        text = str(value).strip().lower()
        if not text:
            return ''
        text = (
            text.replace('\u200f', '')
            .replace('\u200e', '')
            .replace('\u00a0', ' ')
        )
        text = re.sub(r'\s+', ' ', text)
        return text

    def _build_affiliation_matrix_metadata(
        self,
        doc_data: Optional[Dict[str, Any]],
        pension_data: Optional[Dict[str, Any]],
        analysis: Optional[AnalysisResult] = None
    ) -> Dict[str, Any]:
        """
        Build a comprehensive metadata affiliation matrix from uploaded data.
        Allocates relevant metadata into matrix groups with coverage and matches.
        """
        try:
            from services.pension_data_agent import MislakaSchemaMapping
        except Exception:
            return {}

        doc_data = doc_data or {}
        rows = doc_data.get('rows', []) or []
        columns = doc_data.get('columns', []) or []
        files = doc_data.get('files', []) or []
        pension_data = pension_data or {}

        source_terms: List[str] = []
        for col in columns:
            normalized_col = self._normalize_affiliation_term(col)
            if normalized_col:
                source_terms.append(normalized_col)

        for row in rows:
            if not isinstance(row, dict):
                continue
            for value in row.values():
                normalized_val = self._normalize_affiliation_term(value)
                if normalized_val:
                    source_terms.append(normalized_val)

        for acct in pension_data.get('accounts', []) or []:
            if not isinstance(acct, dict):
                continue
            for value in acct.values():
                normalized_val = self._normalize_affiliation_term(value)
                if normalized_val:
                    source_terms.append(normalized_val)

        source_text = ' | '.join(source_terms)

        matrix_groups = [
            ('interface_codes', 'Interfaces', 'ממשקים', MislakaSchemaMapping.INTERFACE_CODES),
            ('product_types', 'Product Types', 'סוגי מוצר', MislakaSchemaMapping.PRODUCT_TYPE_CODES),
            ('entity_types', 'Entity Types', 'סוגי ישות', MislakaSchemaMapping.ENTITY_TYPE_CODES),
            ('status_codes', 'Status Codes', 'סטטוסים', MislakaSchemaMapping.STATUS_CODES),
            ('id_types', 'ID Types', 'סוגי זיהוי', MislakaSchemaMapping.ID_TYPE_CODES),
            ('environment_codes', 'Environment Codes', 'סביבות', MislakaSchemaMapping.ENVIRONMENT_CODES),
        ]

        summary_rows: List[Dict[str, Any]] = []
        detail_rows: List[Dict[str, Any]] = []
        group_term_catalog: Dict[str, Dict[str, Any]] = {}

        for group_key, group_en, group_he, mapping in matrix_groups:
            available = len(mapping or {})
            matched = 0
            hit_count = 0
            group_terms = set()

            for code, info in (mapping or {}).items():
                if isinstance(info, dict):
                    label_terms = [
                        str(code),
                        info.get('he', ''),
                        info.get('en', ''),
                        info.get('name', ''),
                        info.get('schema', ''),
                    ]
                    name_he = info.get('he', info.get('name', ''))
                    name_en = info.get('en', info.get('name', ''))
                    schema = info.get('schema', '')
                else:
                    label_terms = [str(code), str(info)]
                    name_he = str(info)
                    name_en = str(info)
                    schema = ''

                labels = []
                for term in label_terms:
                    normalized_term = self._normalize_affiliation_term(term)
                    if normalized_term and normalized_term not in labels and len(normalized_term) >= 2:
                        labels.append(normalized_term)
                        group_terms.add(normalized_term)

                entry_hits = 0
                for label in labels:
                    if label in source_text:
                        entry_hits += source_text.count(label)

                if entry_hits > 0:
                    matched += 1
                    hit_count += entry_hits
                    detail_rows.append({
                        'group_key': group_key,
                        'group_en': group_en,
                        'group_he': group_he,
                        'code': str(code),
                        'name_he': name_he,
                        'name_en': name_en,
                        'schema': schema,
                        'hits': entry_hits,
                    })

            coverage_pct = round((matched / max(available, 1)) * 100, 2)
            summary_rows.append({
                'group_key': group_key,
                'group_en': group_en,
                'group_he': group_he,
                'available': available,
                'matched': matched,
                'unmatched': max(available - matched, 0),
                'coverage_pct': coverage_pct,
                'hit_count': hit_count,
            })
            group_term_catalog[group_key] = {
                'group_en': group_en,
                'group_he': group_he,
                'terms': group_terms,
            }

        example_model = self._get_pdf_example_allocation_model()
        normalized_columns = [(col, self._normalize_affiliation_term(col)) for col in columns]
        column_matrix_rows: List[Dict[str, Any]] = []
        section_column_counter: Dict[str, int] = {}
        covered_columns = 0

        for col, normalized_col in normalized_columns:
            if not normalized_col:
                continue

            sample_values = []
            for row in rows[:200]:
                if not isinstance(row, dict):
                    continue
                raw_val = row.get(col)
                if raw_val is None:
                    continue
                val = str(raw_val).strip()
                if not val:
                    continue
                if val not in sample_values:
                    sample_values.append(val)
                if len(sample_values) >= 3:
                    break

            normalized_samples = [self._normalize_affiliation_term(val) for val in sample_values]
            combined_text = ' | '.join([normalized_col] + [val for val in normalized_samples if val])

            best_group_key = ''
            best_group_score = 0
            best_group_terms: List[str] = []
            for group_key, group_cfg in group_term_catalog.items():
                group_score = 0
                matched_terms = []
                for term in group_cfg.get('terms', set()):
                    if not term:
                        continue
                    if term in combined_text:
                        weight = 3 if term in normalized_col else 1
                        group_score += combined_text.count(term) * weight
                        matched_terms.append(term)
                if group_score > best_group_score:
                    best_group_score = group_score
                    best_group_key = group_key
                    best_group_terms = matched_terms

            best_section_key = ''
            best_section_score = 0
            best_section_he = ''
            best_section_en = ''
            for section in example_model:
                section_score = 0
                for keyword in section.get('keywords', []):
                    normalized_keyword = self._normalize_affiliation_term(keyword)
                    if normalized_keyword and normalized_keyword in combined_text:
                        section_score += combined_text.count(normalized_keyword)
                if section_score > best_section_score:
                    best_section_score = section_score
                    best_section_key = section.get('key', '')
                    best_section_he = section.get('title_he', '')
                    best_section_en = section.get('title_en', '')

            if best_group_key:
                covered_columns += 1
            if best_section_key:
                section_column_counter[best_section_key] = section_column_counter.get(best_section_key, 0) + 1

            group_cfg = group_term_catalog.get(best_group_key, {})
            column_matrix_rows.append({
                'source_column': col,
                'normalized_column': normalized_col,
                'mapped_group_key': best_group_key,
                'mapped_group_en': group_cfg.get('group_en', ''),
                'mapped_group_he': group_cfg.get('group_he', ''),
                'group_score': best_group_score,
                'matched_terms_count': len(best_group_terms),
                'matched_terms': ' | '.join(best_group_terms[:8]),
                'wishful_section_key': best_section_key,
                'wishful_section_he': best_section_he,
                'wishful_section_en': best_section_en,
                'section_score': best_section_score,
                'sample_values': ' | '.join(sample_values),
            })

        total_matrix_columns = len([col for _, col in normalized_columns if col])
        section_matrix_rows = []
        for section in example_model:
            mapped_columns = section_column_counter.get(section.get('key', ''), 0)
            section_matrix_rows.append({
                'section_key': section.get('key', ''),
                'section_he': section.get('title_he', ''),
                'section_en': section.get('title_en', ''),
                'mapped_columns': mapped_columns,
                'coverage_pct': round((mapped_columns / max(total_matrix_columns, 1)) * 100, 2),
                'keywords_count': len(section.get('keywords', [])),
            })

        policy_metrics = self._extract_policy_cumulative_metrics(rows, columns)
        policy_total = sum(metric.get('policy_total', 0) for metric in policy_metrics)
        policy_savings = sum(metric.get('savings_total', 0) for metric in policy_metrics)
        policy_investments = sum(metric.get('investments_total', 0) for metric in policy_metrics)
        policy_severance = sum(metric.get('severance_total', 0) for metric in policy_metrics)
        cumulative_total = policy_metrics[-1].get('cumulative_total', 0) if policy_metrics else 0

        source_context = {
            'document_rows': len(rows),
            'document_columns': len(columns),
            'files_count': len(files),
            'pension_accounts': len(pension_data.get('accounts', []) or []),
            'pension_contributions': len(pension_data.get('contributions', []) or []),
            'column_matrix_total': total_matrix_columns,
            'column_matrix_covered': covered_columns,
            'column_matrix_uncovered': max(total_matrix_columns - covered_columns, 0),
            'wishful_sections_covered': len([r for r in section_matrix_rows if r.get('mapped_columns', 0) > 0]),
            'analysis_language': analysis.language if analysis else '',
            'analysis_type': analysis.data_classification.value if analysis else '',
        }

        policy_aggregate = {
            'policy_count': len(policy_metrics),
            'policy_total': policy_total,
            'savings_total': policy_savings,
            'investments_total': policy_investments,
            'severance_total': policy_severance,
            'cumulative_total': cumulative_total,
        }

        return {
            'matrix_version': '1.1',
            'summary_rows': summary_rows,
            'detail_rows': detail_rows,
            'column_matrix_rows': column_matrix_rows,
            'section_matrix_rows': section_matrix_rows,
            'source_context': source_context,
            'policy_aggregate': policy_aggregate,
            'column_coverage': {
                'total': total_matrix_columns,
                'covered': covered_columns,
                'uncovered': max(total_matrix_columns - covered_columns, 0),
                'coverage_pct': round((covered_columns / max(total_matrix_columns, 1)) * 100, 2),
            },
            'model': 'mislaka_affiliation_matrix',
        }

    def _build_affiliation_matrix_sections(
        self,
        affiliation_matrix: Optional[Dict[str, Any]],
        is_hebrew: bool
    ) -> List[ReportSection]:
        """Build report sections for metadata affiliation matrix allocation."""
        matrix = affiliation_matrix or {}
        summary_rows = matrix.get('summary_rows', []) or []
        detail_rows = matrix.get('detail_rows', []) or []
        column_matrix_rows = matrix.get('column_matrix_rows', []) or []
        section_matrix_rows = matrix.get('section_matrix_rows', []) or []
        source_context = matrix.get('source_context', {}) or {}
        policy_aggregate = matrix.get('policy_aggregate', {}) or {}
        column_coverage = matrix.get('column_coverage', {}) or {}

        sections: List[ReportSection] = []
        if not summary_rows:
            return sections

        summary_table_rows = []
        for row in summary_rows:
            summary_table_rows.append({
                'קבוצת שיוך' if is_hebrew else 'Affiliation Group': row.get('group_he') if is_hebrew else row.get('group_en'),
                'סה״כ ערכים' if is_hebrew else 'Total Values': row.get('available', 0),
                'מותאם לנתונים' if is_hebrew else 'Matched': row.get('matched', 0),
                'ללא התאמה' if is_hebrew else 'Unmatched': row.get('unmatched', 0),
                'כיסוי %' if is_hebrew else 'Coverage %': row.get('coverage_pct', 0),
                'פגיעות התאמה' if is_hebrew else 'Match Hits': row.get('hit_count', 0),
            })

        sections.append(ReportSection(
            title='מטריצת שיוכי מטא-דאטה' if is_hebrew else 'Metadata Affiliation Matrix',
            content='הקצאה מחדש של מטא-דאטה לדוח לפי מטריצת שיוכים מלאה.' if is_hebrew
            else 'Re-affiliated metadata allocation by full affiliation matrix.',
            data_table={
                'columns': list(summary_table_rows[0].keys()),
                'rows': summary_table_rows,
                'show_all': True
            },
            order=9
        ))

        if detail_rows:
            detail_table_rows = []
            for row in detail_rows:
                detail_table_rows.append({
                    'קבוצה' if is_hebrew else 'Group': row.get('group_he') if is_hebrew else row.get('group_en'),
                    'קוד' if is_hebrew else 'Code': row.get('code', ''),
                    'שם' if is_hebrew else 'Name': row.get('name_he') if is_hebrew else row.get('name_en'),
                    'סכמה' if is_hebrew else 'Schema': row.get('schema', ''),
                    'פגיעות' if is_hebrew else 'Hits': row.get('hits', 0),
                })

            sections.append(ReportSection(
                title='פירוט התאמות מטריצת שיוכים' if is_hebrew else 'Affiliation Matrix Match Details',
                content='פירוט ערכי מטריצה שזוהו בנתונים שהועלו.' if is_hebrew
                else 'Detailed matrix values identified in uploaded data.',
                data_table={
                    'columns': list(detail_table_rows[0].keys()),
                    'rows': detail_table_rows,
                    'show_all': True
                },
                order=9
            ))

        if section_matrix_rows:
            section_table_rows = []
            for row in section_matrix_rows:
                section_table_rows.append({
                    'חלק מודל דוח' if is_hebrew else 'Wishful Report Section': row.get('section_he') if is_hebrew else row.get('section_en'),
                    'עמודות שהוקצו' if is_hebrew else 'Allocated Columns': row.get('mapped_columns', 0),
                    'כיסוי % מעמודות המקור' if is_hebrew else 'Source Column Coverage %': row.get('coverage_pct', 0),
                    'מספר מילות מפתח' if is_hebrew else 'Keyword Count': row.get('keywords_count', 0),
                })

            sections.append(ReportSection(
                title='כיסוי מודל דוח רצוי (שיוך למסמך לדוגמה)' if is_hebrew else 'Wishful Report Model Coverage (Example-Driven)',
                content='הקצאת עמודות המקור לחלקי הדוח לפי מודל היעד מהמסמך המצורף.' if is_hebrew
                else 'Source-column allocation to target report sections based on the attached example model.',
                data_table={
                    'columns': list(section_table_rows[0].keys()),
                    'rows': section_table_rows,
                    'show_all': True
                },
                order=9
            ))

        if column_matrix_rows:
            column_table_rows = []
            for row in column_matrix_rows:
                column_table_rows.append({
                    'עמודת מקור' if is_hebrew else 'Source Column': row.get('source_column', ''),
                    'עמודה מנורמלת' if is_hebrew else 'Normalized Column': row.get('normalized_column', ''),
                    'קבוצת שיוך' if is_hebrew else 'Affiliation Group': row.get('mapped_group_he') if is_hebrew else row.get('mapped_group_en'),
                    'ציון שיוך' if is_hebrew else 'Affiliation Score': row.get('group_score', 0),
                    'התאמות מונח' if is_hebrew else 'Matched Terms': row.get('matched_terms', ''),
                    'חלק יעד בדוח' if is_hebrew else 'Target Report Section': row.get('wishful_section_he') if is_hebrew else row.get('wishful_section_en'),
                    'ציון חלק יעד' if is_hebrew else 'Target Section Score': row.get('section_score', 0),
                    'דוגמאות ערכים' if is_hebrew else 'Sample Values': row.get('sample_values', ''),
                })

            sections.append(ReportSection(
                title='מטריצת שיוך עמודות מקור' if is_hebrew else 'Source Column Affiliation Matrix',
                content='שיוך מלא של כל עמודות המקור למטריצת ההשתייכות ולמבנה הדוח הרצוי.' if is_hebrew
                else 'Full source-column mapping to affiliation groups and wishful report structure.',
                data_table={
                    'columns': list(column_table_rows[0].keys()),
                    'rows': column_table_rows,
                    'show_all': True
                },
                order=9
            ))

        context_rows = [
            {'מדד' if is_hebrew else 'Metric': 'מספר רשומות מקור' if is_hebrew else 'Source Rows', 'ערך' if is_hebrew else 'Value': source_context.get('document_rows', 0)},
            {'מדד' if is_hebrew else 'Metric': 'מספר עמודות מקור' if is_hebrew else 'Source Columns', 'ערך' if is_hebrew else 'Value': source_context.get('document_columns', 0)},
            {'מדד' if is_hebrew else 'Metric': 'מספר קבצים' if is_hebrew else 'Files', 'ערך' if is_hebrew else 'Value': source_context.get('files_count', 0)},
            {'מדד' if is_hebrew else 'Metric': 'סה״כ עמודות במטריצת שיוך' if is_hebrew else 'Column Matrix Total', 'ערך' if is_hebrew else 'Value': source_context.get('column_matrix_total', 0)},
            {'מדד' if is_hebrew else 'Metric': 'עמודות מכוסות במטריצה' if is_hebrew else 'Covered Matrix Columns', 'ערך' if is_hebrew else 'Value': source_context.get('column_matrix_covered', 0)},
            {'מדד' if is_hebrew else 'Metric': 'עמודות ללא שיוך' if is_hebrew else 'Uncovered Matrix Columns', 'ערך' if is_hebrew else 'Value': source_context.get('column_matrix_uncovered', 0)},
            {'מדד' if is_hebrew else 'Metric': 'כיסוי עמודות %' if is_hebrew else 'Column Coverage %', 'ערך' if is_hebrew else 'Value': column_coverage.get('coverage_pct', 0)},
            {'מדד' if is_hebrew else 'Metric': 'חלקי דוח רצוי מכוסים' if is_hebrew else 'Covered Wishful Sections', 'ערך' if is_hebrew else 'Value': source_context.get('wishful_sections_covered', 0)},
            {'מדד' if is_hebrew else 'Metric': 'פוליסות מזוהות' if is_hebrew else 'Identified Policies', 'ערך' if is_hebrew else 'Value': policy_aggregate.get('policy_count', 0)},
            {'מדד' if is_hebrew else 'Metric': 'סה״כ חיסכון מזוהה' if is_hebrew else 'Identified Savings Total', 'ערך' if is_hebrew else 'Value': policy_aggregate.get('savings_total', 0)},
            {'מדד' if is_hebrew else 'Metric': 'סה״כ השקעות מזוהה' if is_hebrew else 'Identified Investments Total', 'ערך' if is_hebrew else 'Value': policy_aggregate.get('investments_total', 0)},
            {'מדד' if is_hebrew else 'Metric': 'יתרה מצטברת מזוהה' if is_hebrew else 'Identified Cumulative Total', 'ערך' if is_hebrew else 'Value': policy_aggregate.get('cumulative_total', 0)},
        ]

        sections.append(ReportSection(
            title='מדדי הקצאת מטא-דאטה ושיוך' if is_hebrew else 'Metadata Allocation and Affiliation Metrics',
            content='מדדי מקור והקצאה לצורך בקרה ושלמות נתונים.' if is_hebrew
            else 'Source and allocation metrics for integrity and control.',
            data_table={
                'columns': list(context_rows[0].keys()),
                'rows': context_rows,
                'show_all': True
            },
            order=9
        ))

        return sections

    def _generate_affiliation_matrix_charts(
        self,
        affiliation_matrix: Optional[Dict[str, Any]],
        lang_code: str
    ) -> List[ChartConfig]:
        """Generate charts from metadata affiliation matrix coverage."""
        matrix = affiliation_matrix or {}
        summary_rows = matrix.get('summary_rows', []) or []
        section_matrix_rows = matrix.get('section_matrix_rows', []) or []
        column_coverage = matrix.get('column_coverage', {}) or {}

        is_hebrew = lang_code == 'hebrew'
        charts: List[ChartConfig] = []

        if len(summary_rows) >= 2:
            labels = [row.get('group_he') if is_hebrew else row.get('group_en') for row in summary_rows]
            coverage_values = [row.get('coverage_pct', 0) for row in summary_rows]
            match_values = [row.get('matched', 0) for row in summary_rows]

            hit_rows = [row for row in summary_rows if row.get('hit_count', 0) > 0]
            hit_labels = [row.get('group_he') if is_hebrew else row.get('group_en') for row in hit_rows]
            hit_values = [row.get('hit_count', 0) for row in hit_rows]

            charts.extend([
                ChartConfig(
                    type=ChartType.BAR,
                    title='כיסוי מטריצת שיוכים (%)' if is_hebrew else 'Affiliation Matrix Coverage (%)',
                    data={
                        'labels': labels,
                        'values': coverage_values,
                    },
                    options={
                        'horizontal': True,
                        'colors': ['#0ea5e9', '#2563eb', '#16a34a', '#f59e0b', '#ef4444', '#8b5cf6'],
                    }
                ),
                ChartConfig(
                    type=ChartType.BAR,
                    title='ערכים מותאמים לפי קבוצת שיוך' if is_hebrew else 'Matched Values by Affiliation Group',
                    data={
                        'labels': labels,
                        'values': match_values,
                    },
                    options={
                        'horizontal': False,
                        'colors': ['#0891b2', '#1d4ed8', '#15803d', '#d97706', '#dc2626', '#7c3aed'],
                    }
                )
            ])

            if hit_labels and hit_values:
                charts.append(ChartConfig(
                    type=ChartType.PIE,
                    title='פיזור פגיעות שיוך לפי קבוצה' if is_hebrew else 'Affiliation Match Hits Distribution',
                    data={
                        'labels': hit_labels,
                        'values': hit_values,
                    },
                    options={
                        'colors': ['#0ea5e9', '#2563eb', '#16a34a', '#f59e0b', '#ef4444', '#8b5cf6'],
                    }
                ))

        section_rows_with_columns = [row for row in section_matrix_rows if row.get('mapped_columns', 0) > 0]
        if section_rows_with_columns:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='כיסוי חלקי מודל דוח רצוי' if is_hebrew else 'Wishful Report Section Coverage',
                data={
                    'labels': [
                        row.get('section_he') if is_hebrew else row.get('section_en')
                        for row in section_rows_with_columns
                    ],
                    'values': [row.get('mapped_columns', 0) for row in section_rows_with_columns],
                },
                options={
                    'horizontal': True,
                    'colors': ['#14b8a6', '#0ea5e9', '#6366f1', '#22c55e', '#f59e0b', '#f97316', '#ec4899'],
                }
            ))

        total_columns = column_coverage.get('total', 0)
        covered_columns = column_coverage.get('covered', 0)
        uncovered_columns = column_coverage.get('uncovered', 0)
        if total_columns > 0:
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='כיסוי שיוך עמודות מקור' if is_hebrew else 'Source Column Affiliation Coverage',
                data={
                    'labels': ['מכוסה' if is_hebrew else 'Covered', 'ללא שיוך' if is_hebrew else 'Uncovered'],
                    'values': [covered_columns, uncovered_columns],
                },
                options={
                    'colors': ['#10b981', '#f97316'],
                }
            ))

        return charts

    def _build_pension_affiliated_sections(self, pension_data: Dict[str, Any], is_hebrew: bool) -> List[ReportSection]:
        """Build table-oriented sections aligned with the Nituach Tik report model."""
        sections: List[ReportSection] = []
        if not pension_data:
            return sections

        accounts = pension_data.get('accounts', []) or []
        contributions = pension_data.get('contributions', []) or []
        totals = pension_data.get('totals', {}) or {}
        employers = pension_data.get('employers', []) or []

        if accounts:
            status_rows = []
            cumulative_balance = 0.0
            for acct in accounts:
                policy_number = self._normalize_policy_number(acct.get('policy_number', ''))
                policy_balance = self._calculate_policy_balance(acct)
                cumulative_balance += policy_balance
                status_rows.append({
                    'מספר פוליסה' if is_hebrew else 'Policy Number': policy_number,
                    'יצרן' if is_hebrew else 'Provider': acct.get('provider', ''),
                    'סוג מוצר' if is_hebrew else 'Product Type': acct.get('product_type_name', acct.get('product_type', '')),
                    'סטטוס' if is_hebrew else 'Status': acct.get('status', acct.get('status_en', '')),
                    'יתרה' if is_hebrew else 'Balance': policy_balance,
                    'יתרה מצטברת' if is_hebrew else 'Cumulative Balance': cumulative_balance,
                    'פיצויים' if is_hebrew else 'Severance': acct.get('severance_balance', 0),
                    'מעסיק' if is_hebrew else 'Employer': acct.get('employer_name', ''),
                    'סעיף 14' if is_hebrew else 'Section 14': ('כן' if acct.get('section14') else 'לא') if is_hebrew else ('Yes' if acct.get('section14') else 'No'),
                })

            sections.append(ReportSection(
                title='סטטוס פוליסות (טבלת שיוכים)' if is_hebrew else 'Policy Status (Affiliation Table)',
                content='מבט טבלאי על פוליסות לפי שיוכי מסלקה.' if is_hebrew else 'Table view of policies by Mislaka affiliation mappings.',
                data_table={
                    'columns': list(status_rows[0].keys()) if status_rows else [],
                    'rows': status_rows,
                    'show_all': True
                },
                order=3
            ))

            plan_rows = []
            for acct in accounts:
                policy_balance = self._calculate_policy_balance(acct)
                plan_rows.append({
                    'מספר פוליסה' if is_hebrew else 'Policy Number': self._normalize_policy_number(acct.get('policy_number', '')),
                    'תאריך תחילה' if is_hebrew else 'Start Date': acct.get('start_date', ''),
                    'דמי ניהול מצבירה %' if is_hebrew else 'Mgmt Fee Savings %': acct.get('management_fee_savings', 0),
                    'דמי ניהול מהפקדה %' if is_hebrew else 'Mgmt Fee Deposits %': acct.get('management_fee_deposits', 0),
                    'כיסוי חיים' if is_hebrew else 'Life Coverage': acct.get('death_coverage', 0),
                    'כיסוי אכ"ע' if is_hebrew else 'Disability Coverage': acct.get('disability_coverage', 0),
                    'תגמולים' if is_hebrew else 'Savings': acct.get('savings_balance', 0),
                    'השקעות' if is_hebrew else 'Investments': acct.get('investment_balance', 0),
                    'פיצויים' if is_hebrew else 'Severance': acct.get('severance_balance', 0),
                    'יתרה' if is_hebrew else 'Balance': policy_balance,
                })

            sections.append(ReportSection(
                title='רשימת תוכניות (פירוט טבלאי)' if is_hebrew else 'Plan Details (Tabular)',
                content='פירוט תוכניות לפי מודל הדוח המסונף.' if is_hebrew else 'Detailed plan view aligned with the affiliated report model.',
                data_table={
                    'columns': list(plan_rows[0].keys()) if plan_rows else [],
                    'rows': plan_rows,
                    'show_all': True
                },
                order=4
            ))

        if contributions:
            contribution_rows = []
            for contrib in contributions:
                contribution_rows.append({
                    'תקופה' if is_hebrew else 'Period': contrib.get('period', ''),
                    'מעסיק' if is_hebrew else 'Employer': contrib.get('employer_name', ''),
                    'הפקדת עובד' if is_hebrew else 'Employee Amount': contrib.get('employee_amount', 0),
                    'הפקדת מעסיק' if is_hebrew else 'Employer Amount': contrib.get('employer_amount', 0),
                    'פיצויים' if is_hebrew else 'Severance': contrib.get('severance_amount', 0),
                    'סה״כ' if is_hebrew else 'Total': contrib.get('total_amount', 0),
                })

            sections.append(ReportSection(
                title='פירוט הפקדות וחובות' if is_hebrew else 'Contribution Details',
                content='רצף הפקדות לפי תקופה לצורכי בקרה ותאימות.' if is_hebrew else 'Period-level contribution trail for control and reconciliation.',
                data_table={
                    'columns': list(contribution_rows[0].keys()) if contribution_rows else [],
                    'rows': contribution_rows,
                    'show_all': True
                },
                order=5
            ))

        if employers or accounts:
            employer_values = []
            seen = set()
            for acct in accounts:
                emp_name = (acct.get('employer_name') or '').strip()
                if emp_name and emp_name not in seen:
                    seen.add(emp_name)
                    employer_values.append({
                        'שם מעסיק' if is_hebrew else 'Employer Name': emp_name,
                        'מספר מעסיק' if is_hebrew else 'Employer ID': acct.get('employer_id', ''),
                        'סעיף 14' if is_hebrew else 'Section 14': ('כן' if acct.get('section14') else 'לא') if is_hebrew else ('Yes' if acct.get('section14') else 'No'),
                    })
            for emp in employers:
                emp_name = (emp.get('name') or '').strip() if isinstance(emp, dict) else str(emp).strip()
                if emp_name and emp_name not in seen:
                    seen.add(emp_name)
                    employer_values.append({
                        'שם מעסיק' if is_hebrew else 'Employer Name': emp_name,
                        'מספר מעסיק' if is_hebrew else 'Employer ID': emp.get('id', '') if isinstance(emp, dict) else '',
                        'סעיף 14' if is_hebrew else 'Section 14': '',
                    })

            if employer_values:
                sections.append(ReportSection(
                    title='פרטי מעסיקים' if is_hebrew else 'Employer Information',
                    content='שיוך מעסיקים לחשבונות ולזכויות.' if is_hebrew else 'Employer affiliation to accounts and severance rights.',
                    data_table={
                        'columns': list(employer_values[0].keys()),
                        'rows': employer_values,
                        'show_all': True
                    },
                    order=6
                ))

        if totals:
            total_balance = totals.get('total_balance', 0)
            if not total_balance:
                total_balance = sum(self._calculate_policy_balance(a) for a in accounts)
            total_savings = totals.get('total_savings', totals.get('total_savings_balance', 0))
            if not total_savings:
                total_savings = sum(self._safe_numeric(a.get('savings_balance')) for a in accounts)
            total_investments = totals.get('total_investments', totals.get('total_investment_balance', 0))
            if not total_investments:
                total_investments = sum(self._safe_numeric(a.get('investment_balance')) for a in accounts)
            total_severance = totals.get('total_severance', totals.get('total_severance_balance', 0))
            if not total_severance:
                total_severance = sum(self._safe_numeric(a.get('severance_balance')) for a in accounts)

            totals_rows = [{
                'שדה' if is_hebrew else 'Metric': 'סה״כ צבירה' if is_hebrew else 'Total Balance',
                'ערך' if is_hebrew else 'Value': total_balance
            }, {
                'שדה' if is_hebrew else 'Metric': 'סה״כ חסכונות' if is_hebrew else 'Total Savings',
                'ערך' if is_hebrew else 'Value': total_savings
            }, {
                'שדה' if is_hebrew else 'Metric': 'סה״כ השקעות' if is_hebrew else 'Total Investments',
                'ערך' if is_hebrew else 'Value': total_investments
            }, {
                'שדה' if is_hebrew else 'Metric': 'סה״כ פיצויים' if is_hebrew else 'Total Severance',
                'ערך' if is_hebrew else 'Value': total_severance
            }, {
                'שדה' if is_hebrew else 'Metric': 'יתרה מצטברת (כל הפוליסות)' if is_hebrew else 'Cumulative Balance (All Policies)',
                'ערך' if is_hebrew else 'Value': total_balance
            }, {
                'שדה' if is_hebrew else 'Metric': 'מספר פוליסות' if is_hebrew else 'Policy Count',
                'ערך' if is_hebrew else 'Value': totals.get('account_count', len(accounts))
            }]

            sections.append(ReportSection(
                title='סיכום כספי (מודל דוח)' if is_hebrew else 'Financial Summary (Model-Aligned)',
                content='תקציר כספי לצורך השוואה מול מודל הדוח המסונף.' if is_hebrew else 'Financial summary aligned with the affiliated report model.',
                data_table={
                    'columns': list(totals_rows[0].keys()),
                    'rows': totals_rows,
                    'show_all': True
                },
                order=7
            ))

        return sections

    def _build_affiliation_mapping_section(self, is_hebrew: bool) -> Optional[ReportSection]:
        """Build a compact affiliations map section from authoritative schema constants."""
        try:
            from services.pension_data_agent import MislakaSchemaMapping
        except Exception:
            return None

        rows: List[Dict[str, Any]] = []

        for code, info in sorted(MislakaSchemaMapping.INTERFACE_CODES.items(), key=lambda item: int(item[0]))[:20]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'ממשק' if is_hebrew else 'Interface',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', info.get('name', '')),
                'שיוך' if is_hebrew else 'Affiliation': info.get('schema', info.get('name', ''))
            })

        for code, info in sorted(MislakaSchemaMapping.PRODUCT_TYPE_CODES.items(), key=lambda item: str(item[0]))[:20]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'מוצר' if is_hebrew else 'Product',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', info.get('name', '')),
                'שיוך' if is_hebrew else 'Affiliation': info.get('en', '')
            })

        for code, info in sorted(MislakaSchemaMapping.STATUS_CODES.items(), key=lambda item: str(item[0]))[:10]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'סטטוס' if is_hebrew else 'Status',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', info.get('name', '')),
                'שיוך' if is_hebrew else 'Affiliation': info.get('en', '')
            })

        for code, info in sorted(MislakaSchemaMapping.ID_TYPE_CODES.items(), key=lambda item: str(item[0]))[:10]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'זיהוי' if is_hebrew else 'ID Type',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', ''),
                'שיוך' if is_hebrew else 'Affiliation': info.get('en', '')
            })

        return ReportSection(
            title='מפת שיוכים (Affiliations)' if is_hebrew else 'Affiliation Mapping Snapshot',
            content='טבלת שיוכים לפי מסלקה: ממשקים, מוצרים, סטטוסים וסוגי זיהוי.' if is_hebrew
            else 'Affiliation map by Mislaka schema: interfaces, products, statuses, and ID types.',
            data_table={
                'columns': list(rows[0].keys()) if rows else [],
                'rows': rows
            },
            order=9
        )
    
    def _generate_swiftness_resources_section(self, is_hebrew: bool) -> str:
        """Generate a report section with Swiftness affiliated links and resources."""
        try:
            from services.swiftness_data_service import get_swiftness_data_service
            svc = get_swiftness_data_service()
            catalog = svc.get_resource_catalog()
            model = svc.get_report_model()
        except Exception:
            return ''
        
        lines = []
        meta = catalog.get('metadata', {})
        
        if is_hebrew:
            lines.append('📥 משאבי נתונים מ-Swiftness לעבודה מול המסלקה:\n')
            lines.append(f'סה"כ משאבים: {meta.get("total_resources", 0)}')
            lines.append(f'ממשקים: {", ".join(meta.get("interfaces", []))}')
            lines.append(f'סוגי קבצים: {", ".join(t.upper() for t in meta.get("file_types", []))}')
            lines.append('')
            lines.append('🔗 קישורים ישירים:')
            for link in catalog.get('quick_links', []):
                lines.append(f'  • {link.get("label_he", link["label"])}: {link["url"]}')
            lines.append('')
            lines.append('📋 כללי מערכת (סכימות וטבלאות קודים):')
            for res in catalog.get('system_general', [])[:6]:
                lines.append(f'  • {res["name"]} ({res.get("file_type", "").upper()}'
                             f'{" v" + res["version"] if res.get("version") else ""})')
            lines.append('')
            lines.append('📂 קבצים עדכניים לעבודה מול המסלקה:')
            for res in catalog.get('mislaka_work_files', [])[:6]:
                lines.append(f'  • {res["name"]} ({res.get("file_type", "").upper()})')
            
            # Report model summary
            model_meta = model.get('metadata', {})
            sections_count = len(model.get('sections', []))
            lines.append('')
            lines.append(f'📊 מודל דוח מקיף: {sections_count} חלקים')
            for sec in model.get('sections', []):
                fields_count = len(sec.get('data_fields', []))
                lines.append(f'  {sec["order"]}. {sec["title_he"]} ({fields_count} שדות)')
            
            # Data integrity
            rules = model_meta.get('data_integrity_rules', [])
            if rules:
                lines.append('')
                lines.append('🛡️ כללי שלמות נתונים:')
                for rule in rules:
                    lines.append(f'  ✓ {rule}')
        else:
            lines.append('📥 Swiftness Data Resources for Mislaka Integration:\n')
            lines.append(f'Total Resources: {meta.get("total_resources", 0)}')
            lines.append(f'Interfaces: {", ".join(meta.get("interfaces", []))}')
            lines.append(f'File Types: {", ".join(t.upper() for t in meta.get("file_types", []))}')
            lines.append('')
            lines.append('🔗 Direct Links:')
            for link in catalog.get('quick_links', []):
                lines.append(f'  • {link["label"]}: {link["url"]}')
            lines.append('')
            lines.append('📋 System General (Schemas & Code Tables):')
            for res in catalog.get('system_general', [])[:6]:
                lines.append(f'  • {res.get("name_en", res["name"])} ({res.get("file_type", "").upper()}'
                             f'{" v" + res["version"] if res.get("version") else ""})')
            lines.append('')
            lines.append('📂 Latest Mislaka Work Files:')
            for res in catalog.get('mislaka_work_files', [])[:6]:
                lines.append(f'  • {res.get("name_en", res["name"])} ({res.get("file_type", "").upper()})')
            
            # Report model summary
            model_meta = model.get('metadata', {})
            sections_count = len(model.get('sections', []))
            lines.append('')
            lines.append(f'📊 Comprehensive Report Model: {sections_count} sections')
            for sec in model.get('sections', []):
                fields_count = len(sec.get('data_fields', []))
                lines.append(f'  {sec["order"]}. {sec["title_en"]} ({fields_count} fields)')
            
            # Data integrity
            rules = model_meta.get('data_integrity_rules', [])
            if rules:
                lines.append('')
                lines.append('🛡️ Data Integrity Rules:')
                for rule in rules:
                    lines.append(f'  ✓ {rule}')
        
        return '\n'.join(lines)
    
    def _generate_data_content_section(self, doc_data: Dict[str, Any], 
                                        analysis: AnalysisResult, is_hebrew: bool) -> str:
        """
        Generate a section showing actual data content from uploaded files.
        This displays the real values from CSV/ZIP files, not just statistics.
        """
        content_lines = []
        
        columns = doc_data.get('columns', [])
        rows = doc_data.get('rows', [])
        files = doc_data.get('files', [])
        
        # If from ZIP, show file list
        if files:
            if is_hebrew:
                content_lines.append("📁 קבצים שנותחו מתוך ה-ZIP:")
            else:
                content_lines.append("📁 Files analyzed from ZIP:")
            
            for f in files:
                content_lines.append(f"  • {f.get('name', 'Unknown')} ({f.get('row_count', 0)} שורות)" if is_hebrew else f"  • {f.get('name', 'Unknown')} ({f.get('row_count', 0)} rows)")
            content_lines.append("")
        
        # Show column headers
        if columns:
            if is_hebrew:
                content_lines.append(f"📋 עמודות הנתונים ({len(columns)}):")
            else:
                content_lines.append(f"📋 Data Columns ({len(columns)}):")
            
            # Display columns in a formatted way
            col_display = []
            for col in columns[:20]:  # Limit to 20 columns
                col_display.append(f"  • {col}")
            content_lines.extend(col_display)
            if len(columns) > 20:
                content_lines.append(f"  ... ועוד {len(columns) - 20} עמודות" if is_hebrew else f"  ... and {len(columns) - 20} more columns")
            content_lines.append("")
        
        # Show sample data rows as table
        if rows:
            if is_hebrew:
                content_lines.append(f"📊 נתונים שחולצו ({len(rows)} רשומות):")
                content_lines.append("=" * 50)
                content_lines.append("✓ כל הרשומות מוקצות בטבלת שיוך מלאה בחלק הייעודי בדוח.")
            else:
                content_lines.append(f"📊 Extracted Data ({len(rows)} records):")
                content_lines.append("=" * 50)
                content_lines.append("✓ All records are allocated in the dedicated full affiliated table section.")
            
            # Display preview rows here; full dataset is provided in the affiliated data table section.
            preview_rows = rows[:5]
            for i, row in enumerate(preview_rows, 1):
                if is_hebrew:
                    content_lines.append(f"\n🔹 רשומה {i}:")
                else:
                    content_lines.append(f"\n🔹 Record {i}:")
                
                for key, value in row.items():
                    if value and str(value).strip():
                        # Clean and format the value
                        val_str = str(value).strip()
                        # Detect if it's a numeric value
                        try:
                            num_val = float(val_str.replace(',', '').replace('₪', '').replace('$', ''))
                            if num_val > 1000:
                                val_str = f"₪{num_val:,.0f}" if any(x in key.lower() for x in ['premium', 'cover', 'amount', 'סכום', 'פרמיה', 'כיסוי']) else f"{num_val:,.0f}"
                        except ValueError:
                            pass
                        content_lines.append(f"    {key}: {val_str}")
            
            if len(rows) > len(preview_rows):
                remaining = len(rows) - len(preview_rows)
                content_lines.append(
                    f"\n... ועוד {remaining} רשומות (מוצגות במלואן בטבלת השיוך)"
                    if is_hebrew
                    else f"\n... and {remaining} more records (fully shown in affiliated table)"
                )
        
        # Extract and highlight key insurance/financial fields
        key_fields = self._extract_key_fields_from_data(rows, is_hebrew)
        if key_fields:
            content_lines.append("")
            if is_hebrew:
                content_lines.append("🎯 שדות מרכזיים שזוהו:")
            else:
                content_lines.append("🎯 Key Fields Identified:")
            
            for field_name, field_value in key_fields.items():
                content_lines.append(f"  • {field_name}: {field_value}")
        
        return '\n'.join(content_lines) if content_lines else ""
    
    def _generate_pension_section(self, pension_data: Dict[str, Any], 
                                   pension_report: str, is_hebrew: bool) -> str:
        """
        Generate a comprehensive pension and insurance report section.
        Uses data from the enhanced PensionDataAgent for Mislaka XML files.
        
        Supports the full Mislaka interface standards:
        - Holdings Interface (v9.7.7)
        - Severance Interface (v5.9.38)
        - Event Interface (v7.6.30)
        - Transference Interface (v3.7.2)
        
        This displays:
        - Professional Mislaka report generated by PensionDataAgent
        - Account summaries with balances by provider/product type
        - Section 14 status and severance details
        - Health score and AI recommendations
        - Contribution analysis and trends
        """
        content_lines = []
        
        # If we have the pre-generated Mislaka pension report, include it
        if pension_report:
            content_lines.append(pension_report)
            content_lines.append("")
            content_lines.append("─" * 50)
            content_lines.append("")
        
        # If we have structured pension data, add detailed breakdown
        if pension_data:
            # Support both 'totals' (new) and 'summary' (legacy) keys
            totals = pension_data.get('totals', pension_data.get('summary', {}))
            accounts = pension_data.get('accounts', [])
            clients = pension_data.get('client', {})
            if isinstance(clients, list) and clients:
                clients = clients[0]
            header = pension_data.get('header', {})
            contributions = pension_data.get('contributions', [])
            severance = pension_data.get('severance', [])
            
            if is_hebrew:
                # Financial summary section with health score
                health_score = totals.get('health_score', {})
                if health_score:
                    content_lines.append("🎯 ציון בריאות פיננסית:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• ציון כולל: {health_score.get('overall', 0)}/100 ({health_score.get('rating_he', 'לא ידוע')})")
                    content_lines.append(f"• ציון חסכונות: {health_score.get('savings', 0)}/100")
                    content_lines.append(f"• ציון פיזור: {health_score.get('diversification', 0)}/100")
                    content_lines.append(f"• ציון סעיף 14: {health_score.get('section14', 0)}/100")
                    content_lines.append("")
                
                # Financial summary section
                content_lines.append("💰 סיכום כספי מפורט:")
                content_lines.append("=" * 40)
                content_lines.append(f"• סה״כ יתרה בחשבונות: {totals.get('total_balance_formatted', '₪0')}")
                content_lines.append(f"• סה״כ חסכונות: {totals.get('total_savings_formatted', '₪0')}")
                content_lines.append(f"• סה״כ פיצויים צבורים: {totals.get('total_severance_formatted', '₪0')}")
                content_lines.append(f"• מספר חשבונות/פוליסות: {totals.get('account_count', 0)}")
                content_lines.append(f"• מספר יצרנים/חברות: {totals.get('provider_count', 0)}")
                
                # Providers
                providers = totals.get('providers', [])
                if providers:
                    content_lines.append(f"• יצרנים: {', '.join(providers)}")
                content_lines.append("")
                
                # Section 14 status
                content_lines.append("📌 סעיף 14 (פיצויים):")
                if totals.get('section14_coverage'):
                    content_lines.append("• סטטוס: ✅ מכוסה")
                    content_lines.append("• ✅ הלקוח מכוסה תחת סעיף 14 - פיצויים מובטחים")
                    content_lines.append(f"• מספר חשבונות עם סעיף 14: {totals.get('section14_accounts', 0)}")
                else:
                    content_lines.append("• סטטוס: ⚠️ לא מכוסה")
                    content_lines.append("• ⚠️ אין כיסוי סעיף 14 - יש לבדוק עם המעסיק")
                content_lines.append("")
                
                # Contribution summary
                contrib_totals = totals.get('contributions', {})
                if contrib_totals:
                    content_lines.append("📈 סיכום הפקדות:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• הפקדות עובד: ₪{contrib_totals.get('employee_total', 0):,.2f}")
                    content_lines.append(f"• הפקדות מעסיק: ₪{contrib_totals.get('employer_total', 0):,.2f}")
                    content_lines.append(f"• הפקדות פיצויים: ₪{contrib_totals.get('severance_total', 0):,.2f}")
                    content_lines.append(f"• סה״כ הפקדות: ₪{contrib_totals.get('grand_total', 0):,.2f}")
                    content_lines.append(f"• תקופות: {contrib_totals.get('periods_count', 0)}")
                    content_lines.append("")
                
                # Contribution trend
                trend = totals.get('contribution_trend')
                if trend:
                    trend_he = totals.get('contribution_trend_he', trend)
                    content_lines.append("📈 מגמת הפקדות:")
                    content_lines.append(f"• מגמה: {trend_he}")
                    content_lines.append("")
                
                # Missing months warning
                missing = totals.get('missing_contribution_months', [])
                if missing:
                    content_lines.append("⚠️ אזהרה - חודשים חסרים:")
                    content_lines.append(f"• נמצאו {len(missing)} חודשים ללא הפקדות")
                    content_lines.append(f"• חודשים: {', '.join(missing)}")
                    content_lines.append("")
                
                # Account details
                if accounts:
                    content_lines.append("📁 פירוט חשבונות:")
                    content_lines.append("-" * 40)
                    total_balance = totals.get('total_balance', 0) or sum(self._calculate_policy_balance(a) for a in accounts)
                    cumulative_balance = 0.0
                    for i, acct in enumerate(accounts, 1):
                        balance = self._calculate_policy_balance(acct)
                        cumulative_balance += balance
                        pct = (balance / total_balance * 100) if total_balance > 0 else 0
                        policy_number = self._normalize_policy_number(acct.get('policy_number', '')) or 'לא ידוע'
                        content_lines.append(f"\n🔹 חשבון {i}:")
                        content_lines.append(f"   • מספר פוליסה: {policy_number}")
                        if acct.get('provider'):
                            content_lines.append(f"   • יצרן: {acct.get('provider')}")
                        if acct.get('product_type_name') or acct.get('product_name') or acct.get('product_type'):
                            content_lines.append(f"   • סוג מוצר: {acct.get('product_type_name', acct.get('product_name', acct.get('product_type', 'לא ידוע')))}")
                        if acct.get('status'):
                            content_lines.append(f"   • סטטוס: {acct.get('status')}")
                        content_lines.append(f"   • יתרה: ₪{balance:,.2f} ({pct:.1f}% מהכולל)")
                        content_lines.append(f"   • יתרה מצטברת: ₪{cumulative_balance:,.2f}")
                        if acct.get('savings_balance', 0) > 0:
                            content_lines.append(f"   • חיסכון: ₪{acct.get('savings_balance', 0):,.2f}")
                        if acct.get('investment_balance', 0) > 0:
                            content_lines.append(f"   • השקעות: ₪{acct.get('investment_balance', 0):,.2f}")
                        if acct.get('severance_balance', 0) > 0:
                            content_lines.append(f"   • פיצויים: ₪{acct.get('severance_balance', 0):,.2f}")
                        if acct.get('section14'):
                            content_lines.append(f"   • סעיף 14: ✅ מכוסה")
                        if acct.get('management_fee_savings', 0) > 0:
                            content_lines.append(f"   • דמי ניהול: {acct.get('management_fee_savings', 0):.2f}%")
                        if acct.get('employer_name'):
                            content_lines.append(f"   • מעסיק: {acct.get('employer_name')}")
                    
                    content_lines.append("")
            
            else:
                # English version
                health_score = totals.get('health_score', {})
                if health_score:
                    content_lines.append("🎯 Financial Health Score:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• Overall Score: {health_score.get('overall', 0)}/100 ({health_score.get('rating', 'unknown')})")
                    content_lines.append(f"• Savings Score: {health_score.get('savings', 0)}/100")
                    content_lines.append(f"• Diversification Score: {health_score.get('diversification', 0)}/100")
                    content_lines.append(f"• Section 14 Score: {health_score.get('section14', 0)}/100")
                    content_lines.append("")
                
                content_lines.append("💰 Detailed Financial Summary:")
                content_lines.append("=" * 40)
                content_lines.append(f"• Total Account Balance: {totals.get('total_balance_formatted', '₪0')}")
                content_lines.append(f"• Total Savings: {totals.get('total_savings_formatted', '₪0')}")
                content_lines.append(f"• Total Severance Accrued: {totals.get('total_severance_formatted', '₪0')}")
                content_lines.append(f"• Number of Accounts/Policies: {totals.get('account_count', 0)}")
                content_lines.append(f"• Number of Providers: {totals.get('provider_count', 0)}")
                
                providers = totals.get('providers', [])
                if providers:
                    content_lines.append(f"• Providers: {', '.join(providers)}")
                content_lines.append("")
                
                # Section 14 status
                content_lines.append("📌 Section 14 (Severance):")
                content_lines.append(f"• Covered: {'Yes' if totals.get('section14_coverage') else 'No'}")
                if totals.get('section14_coverage'):
                    content_lines.append("• ✅ Client is covered under Section 14 - severance is secured")
                    content_lines.append(f"• Accounts with Section 14: {totals.get('section14_accounts', 0)}")
                else:
                    content_lines.append("• ⚠️ No Section 14 coverage - verify with employer")
                content_lines.append("")
                
                # Contribution summary
                contrib_totals = totals.get('contributions', {})
                if contrib_totals:
                    content_lines.append("📈 Contribution Summary:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• Employee Contributions: ₪{contrib_totals.get('employee_total', 0):,.2f}")
                    content_lines.append(f"• Employer Contributions: ₪{contrib_totals.get('employer_total', 0):,.2f}")
                    content_lines.append(f"• Severance Contributions: ₪{contrib_totals.get('severance_total', 0):,.2f}")
                    content_lines.append(f"• Total Contributions: ₪{contrib_totals.get('grand_total', 0):,.2f}")
                    content_lines.append(f"• Periods: {contrib_totals.get('periods_count', 0)}")
                    content_lines.append("")
                
                # Contribution trend
                trend = totals.get('contribution_trend')
                if trend:
                    content_lines.append("📈 Contribution Trend:")
                    content_lines.append(f"• Trend: {trend.capitalize()}")
                    content_lines.append("")
                
                # Missing months warning
                missing = totals.get('missing_contribution_months', [])
                if missing:
                    content_lines.append("⚠️ Warning - Missing Months:")
                    content_lines.append(f"• Found {len(missing)} months without contributions")
                    content_lines.append(f"• Months: {', '.join(missing)}")
                    content_lines.append("")
                
                # Account details
                if accounts:
                    content_lines.append("📁 Account Details:")
                    content_lines.append("-" * 40)
                    total_balance = totals.get('total_balance', 0) or sum(self._calculate_policy_balance(a) for a in accounts)
                    cumulative_balance = 0.0
                    for i, acct in enumerate(accounts, 1):
                        balance = self._calculate_policy_balance(acct)
                        cumulative_balance += balance
                        pct = (balance / total_balance * 100) if total_balance > 0 else 0
                        policy_number = self._normalize_policy_number(acct.get('policy_number', '')) or 'Unknown'
                        content_lines.append(f"\n🔹 Account {i}:")
                        content_lines.append(f"   • Policy Number: {policy_number}")
                        content_lines.append(f"   • Balance: ₪{balance:,.2f} ({pct:.1f}% of total)")
                        content_lines.append(f"   • Cumulative Balance: ₪{cumulative_balance:,.2f}")
                        if acct.get('provider'):
                            content_lines.append(f"   • Provider: {acct.get('provider')}")
                        if acct.get('product_name') or acct.get('product_type'):
                            content_lines.append(f"   • Product: {acct.get('product_name', acct.get('product_type', 'Unknown'))}")
                        if acct.get('status'):
                            content_lines.append(f"   • Status: {acct.get('status')}")
                        if acct.get('savings_balance', 0) > 0:
                            content_lines.append(f"   • Savings: ₪{acct.get('savings_balance', 0):,.2f}")
                        if acct.get('investment_balance', 0) > 0:
                            content_lines.append(f"   • Investments: ₪{acct.get('investment_balance', 0):,.2f}")
                        if acct.get('severance_balance', 0) > 0:
                            content_lines.append(f"   • Severance: ₪{acct.get('severance_balance', 0):,.2f}")
                        if acct.get('employer'):
                            emp = acct['employer']
                            if isinstance(emp, dict):
                                content_lines.append(f"   • Employer: {emp.get('name', '')}")
                    
                    content_lines.append("")
        
        return '\n'.join(content_lines) if content_lines else ""
    
    def _extract_key_fields_from_data(self, rows: List[Dict], is_hebrew: bool) -> Dict[str, Any]:
        """
        Extract key financial/insurance fields from the actual data rows.
        """
        key_fields = {}
        
        # Keywords to look for
        important_keys = {
            'policy': ['policy', 'פוליסה', 'מספר פוליסה', 'policy_number'],
            'premium': ['premium', 'פרמיה', 'תשלום', 'payment', 'חודשי'],
            'cover': ['cover', 'כיסוי', 'סכום ביטוח', 'סכום', 'coverage', 'amount'],
            'date': ['date', 'תאריך', 'start', 'תחילה', 'end', 'סיום'],
            'id': ['id', 'ת.ז', 'תעודת זהות', 'מספר זהות', 'identity'],
            'name': ['name', 'שם', 'מבוטח', 'insured'],
            'type': ['type', 'סוג', 'תוכנית', 'plan', 'מסלול'],
            'pension': ['pension', 'פנסיה', 'גמל', 'קרן'],
            'beneficiary': ['beneficiary', 'מוטב', 'מוטבים'],
        }
        
        for row in rows[:20]:  # Check first 20 rows
            for col_name, value in row.items():
                if not value or not str(value).strip():
                    continue
                
                col_lower = col_name.lower()
                value_str = str(value).strip()
                
                for field_type, keywords in important_keys.items():
                    if any(kw in col_lower for kw in keywords):
                        label_map = {
                            'policy': 'מספר פוליסה' if is_hebrew else 'Policy Number',
                            'premium': 'פרמיה' if is_hebrew else 'Premium',
                            'cover': 'סכום כיסוי' if is_hebrew else 'Cover Amount',
                            'date': col_name,
                            'id': 'מספר זהות' if is_hebrew else 'ID Number',
                            'name': 'שם' if is_hebrew else 'Name',
                            'type': 'סוג' if is_hebrew else 'Type',
                            'pension': 'פנסיה' if is_hebrew else 'Pension',
                            'beneficiary': 'מוטב' if is_hebrew else 'Beneficiary',
                        }
                        
                        label = label_map.get(field_type, col_name)
                        
                        # Format numeric values
                        if field_type in ['premium', 'cover']:
                            try:
                                num_val = float(value_str.replace(',', '').replace('₪', '').replace('$', ''))
                                value_str = f"₪{num_val:,.0f}"
                            except ValueError:
                                pass
                        
                        # Mask ID numbers for privacy
                        if field_type == 'id' and len(value_str) >= 6:
                            value_str = value_str[:2] + '****' + value_str[-2:]
                        
                        if label not in key_fields:
                            key_fields[label] = value_str
                        break
        
        return key_fields
    
    def _generate_hebrew_insurance_section(self, hebrew_factors: List[Factor], 
                                            is_hebrew: bool) -> str:
        """
        Generate a detailed section showing extracted Hebrew insurance policy details.
        """
        content_lines = []
        
        if is_hebrew:
            content_lines.append("📋 פרטי הפוליסה שחולצו מהמסמכים:\n")
        else:
            content_lines.append("📋 Policy Details Extracted from Documents:\n")
        
        for factor in hebrew_factors:
            # Add factor name as header
            content_lines.append(f"▸ {factor.name}:")
            
            if isinstance(factor.value, dict):
                for key, val in factor.value.items():
                    content_lines.append(f"    • {key}: {val}")
            else:
                content_lines.append(f"    {factor.value}")
            
            content_lines.append("")
        
        # Add importance rating
        if hebrew_factors:
            avg_importance = sum(f.importance for f in hebrew_factors) / len(hebrew_factors)
            if is_hebrew:
                content_lines.append(f"📈 רמת חשיבות ממוצעת: {avg_importance:.0%}")
            else:
                content_lines.append(f"📈 Average Importance: {avg_importance:.0%}")
        
        return '\n'.join(content_lines)
    
    def _generate_charts(
        self,
        analysis: AnalysisResult,
        pension_data: Dict = None,
        doc_data: Dict[str, Any] = None,
        affiliation_matrix: Dict[str, Any] = None
    ) -> List[ChartConfig]:
        """
        Generate chart configurations.
        
        For pension data, generates meaningful financial charts:
        - Cumulative savings by provider
        - Savings vs Severance breakdown
        - Insurance coverage breakdown
        """
        charts = []
        
        source_rows = (doc_data or {}).get('rows', []) if doc_data else []
        source_columns = (doc_data or {}).get('columns', []) if doc_data else []

        # Check if we have pension data for specialized charts
        if pension_data:
            charts.extend(self._generate_pension_charts(pension_data, analysis.language))
            charts.extend(self._generate_policy_cumulative_charts_from_rows(source_rows, source_columns, analysis.language))
            charts.extend(self._generate_pdf_example_allocation_charts(source_rows, source_columns, analysis.language))
            charts.extend(self._generate_affiliation_matrix_charts(affiliation_matrix, analysis.language))
            return charts  # Pension flow includes all relevant pension/policy charts
        
        # Risk Score Gauge (for non-pension data)
        charts.append(ChartConfig(
            type=ChartType.GAUGE,
            title='Risk Score',
            data={
                'value': analysis.risk_score,
                'min': 0,
                'max': 100,
                'thresholds': [30, 60, 80]
            },
            options={'colors': ['#4caf50', '#ffeb3b', '#ff9800', '#f44336']}
        ))
        
        # Factors Importance Bar Chart - only for meaningful factors
        meaningful_factors = [f for f in analysis.extracted_factors[:8] 
                            if f.category in ['domain', 'currency', 'financial']]
        if meaningful_factors:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='Factors Importance',
                data={
                    'labels': [f.name for f in meaningful_factors],
                    'values': [f.importance * 100 for f in meaningful_factors]
                },
                options={'horizontal': True}
            ))
        
        # Data Distribution Pie Chart - only meaningful totals
        if analysis.key_metrics:
            # Filter to only financial totals, not counts
            financial_metrics = {k: v for k, v in analysis.key_metrics.items() 
                               if isinstance(v, (int, float)) and 
                               (k.endswith('_total') or 'balance' in k.lower() or 
                                'savings' in k.lower() or 'coverage' in k.lower()) and
                               v > 0}
            if financial_metrics:
                charts.append(ChartConfig(
                    type=ChartType.PIE,
                    title='Data Distribution',
                    data={
                        'labels': list(financial_metrics.keys())[:6],
                        'values': list(financial_metrics.values())[:6]
                    }
                ))

        # Add detailed policy savings/investment charts when fields exist.
        charts.extend(self._generate_policy_cumulative_charts_from_rows(source_rows, source_columns, analysis.language))
        charts.extend(self._generate_pdf_example_allocation_charts(source_rows, source_columns, analysis.language))
        charts.extend(self._generate_affiliation_matrix_charts(affiliation_matrix, analysis.language))
        
        return charts

    def _generate_pdf_example_allocation_charts(
        self,
        rows: List[Dict[str, Any]],
        columns: Optional[List[str]],
        lang_code: str
    ) -> List[ChartConfig]:
        """Generate charts for example-driven data allocation coverage."""
        allocation = self._categorize_rows_by_pdf_example(rows, columns)
        summary = allocation.get('summary', [])
        if len(summary) < 2:
            return []

        is_hebrew = lang_code == 'hebrew'
        labels = [entry['title_he'] if is_hebrew else entry['title_en'] for entry in summary]
        counts = [entry['count'] for entry in summary]
        percents = [entry['percent'] for entry in summary]

        return [
            ChartConfig(
                type=ChartType.BAR,
                title='התפלגות רשומות לפי קטגוריות דוח לדוגמה' if is_hebrew else 'Record Allocation by Example Report Categories',
                data={
                    'labels': labels,
                    'values': counts,
                },
                options={
                    'horizontal': True,
                    'colors': ['#0ea5e9', '#2563eb', '#16a34a', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#f97316', '#64748b'],
                }
            ),
            ChartConfig(
                type=ChartType.PIE,
                title='כיסוי הקצאת נתונים (%)' if is_hebrew else 'Allocation Coverage (%)',
                data={
                    'labels': labels,
                    'values': percents,
                },
                options={
                    'colors': ['#0ea5e9', '#2563eb', '#16a34a', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#f97316', '#64748b'],
                }
            ),
        ]

    def _generate_policy_cumulative_charts_from_rows(
        self,
        rows: List[Dict[str, Any]],
        columns: Optional[List[str]],
        lang_code: str
    ) -> List[ChartConfig]:
        """Generate policy-level cumulative charts from uploaded tabular rows."""
        policy_metrics = self._extract_policy_cumulative_metrics(rows, columns)
        if not policy_metrics:
            return []

        is_hebrew = lang_code == 'hebrew'
        labels = [metric['policy_number'] for metric in policy_metrics]
        savings_values = [metric['savings_total'] for metric in policy_metrics]
        investments_values = [metric['investments_total'] for metric in policy_metrics]
        policy_totals = [metric['policy_total'] for metric in policy_metrics]
        cumulative_totals = [metric['cumulative_total'] for metric in policy_metrics]

        charts: List[ChartConfig] = []

        if any(value > 0 for value in policy_totals):
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='יתרה לפוליסה (סיכום)' if is_hebrew else 'Policy Totals (Balance Summary)',
                data={
                    'labels': labels,
                    'values': policy_totals,
                },
                options={
                    'horizontal': False,
                    'colors': ['#1d4ed8'],
                    'currency': True,
                    'currency_symbol': '₪',
                }
            ))

        if any(value > 0 for value in cumulative_totals):
            charts.append(ChartConfig(
                type=ChartType.LINE,
                title='יתרה מצטברת לפי פוליסה' if is_hebrew else 'Cumulative Balance by Policy',
                data={
                    'labels': labels,
                    'values': cumulative_totals,
                },
                options={
                    'colors': ['#0ea5e9'],
                    'currency': True,
                    'currency_symbol': '₪',
                }
            ))

        if any(value > 0 for value in savings_values):
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='חיסכון מצטבר לפי פוליסה' if is_hebrew else 'Savings Sum by Policy',
                data={
                    'labels': labels,
                    'values': savings_values,
                },
                options={
                    'horizontal': False,
                    'colors': ['#16a34a'],
                    'currency': True,
                    'currency_symbol': '₪',
                }
            ))

        if any(value > 0 for value in investments_values):
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='השקעות מצטברות לפי פוליסה' if is_hebrew else 'Investments Sum by Policy',
                data={
                    'labels': labels,
                    'values': investments_values,
                },
                options={
                    'horizontal': False,
                    'colors': ['#f59e0b'],
                    'currency': True,
                    'currency_symbol': '₪',
                }
            ))

        provider_totals: Dict[str, float] = {}
        product_totals: Dict[str, float] = {}
        for metric in policy_metrics:
            policy_total = metric.get('policy_total', 0) or 0
            provider_label = metric.get('provider_primary') or ('לא ידוע' if is_hebrew else 'Unknown')
            product_label = metric.get('product_primary') or ('לא מוגדר' if is_hebrew else 'Undefined')
            if policy_total > 0:
                provider_totals[provider_label] = provider_totals.get(provider_label, 0) + policy_total
                product_totals[product_label] = product_totals.get(product_label, 0) + policy_total

        if provider_totals and len(provider_totals) > 1:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='סך יתרה לפי יצרן (הקצאת רשומות)' if is_hebrew else 'Total Balance by Provider (Record Allocation)',
                data={
                    'labels': list(provider_totals.keys()),
                    'values': list(provider_totals.values()),
                },
                options={
                    'colors': ['#2563eb', '#16a34a', '#f59e0b', '#ef4444', '#7c3aed', '#14b8a6'],
                    'currency': True,
                    'currency_symbol': '₪',
                }
            ))

        if product_totals and len(product_totals) > 1:
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='סך יתרה לפי מוצר/מסלול' if is_hebrew else 'Total Balance by Product/Plan',
                data={
                    'labels': list(product_totals.keys()),
                    'values': list(product_totals.values()),
                },
                options={
                    'colors': ['#0ea5e9', '#22c55e', '#f97316', '#e11d48', '#6366f1', '#84cc16'],
                    'currency': True,
                    'currency_symbol': '₪',
                }
            ))

        return charts
    
    def _generate_pension_charts(self, pension_data: Dict, lang_code: str) -> List[ChartConfig]:
        """
        Generate specialized charts for pension/Mislaka data.
        
        Creates meaningful visualizations:
        1. Cumulative savings by provider (bar chart)
        2. Savings vs Severance breakdown (doughnut)
        3. Insurance coverage breakdown (pie chart)
        """
        charts = []
        is_hebrew = lang_code == 'hebrew'
        
        totals = pension_data.get('totals', {})
        accounts = pension_data.get('accounts', [])
        
        # 1. Cumulative Savings by Provider (Bar Chart)
        provider_totals = {}
        for acct in accounts:
            provider = acct.get('provider', 'לא ידוע' if is_hebrew else 'Unknown')
            balance = self._calculate_policy_balance(acct)
            if provider and balance > 0:
                provider_totals[provider] = provider_totals.get(provider, 0) + balance
        
        if provider_totals:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='צבירה לפי יצרן' if is_hebrew else 'Savings by Provider',
                data={
                    'labels': list(provider_totals.keys()),
                    'values': list(provider_totals.values())
                },
                options={
                    'horizontal': False,
                    'colors': ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))

        # 1b. Cumulative Balance by Policy (Bar Chart)
        cumulative_labels = []
        cumulative_values = []
        cumulative_balance = 0.0
        for idx, acct in enumerate(accounts, 1):
            balance = self._calculate_policy_balance(acct)
            if balance <= 0:
                continue
            cumulative_balance += balance
            policy_number = self._normalize_policy_number(acct.get('policy_number', ''))
            if not policy_number:
                policy_number = f"פוליסה {idx}" if is_hebrew else f"Policy {idx}"
            cumulative_labels.append(policy_number)
            cumulative_values.append(cumulative_balance)

        if cumulative_labels and cumulative_values:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='יתרה מצטברת לפי פוליסה' if is_hebrew else 'Cumulative Balance by Policy',
                data={
                    'labels': cumulative_labels,
                    'values': cumulative_values
                },
                options={
                    'horizontal': False,
                    'colors': ['#0ea5e9'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 2. Savings vs Severance Breakdown (Doughnut Chart)
        total_savings = totals.get('total_savings_balance', 0)
        total_severance = totals.get('total_severance_balance', 0)
        
        if not total_savings and not total_severance:
            # Calculate from accounts
            total_savings = sum(a.get('savings_balance', 0) or 0 for a in accounts)
            total_severance = sum(a.get('severance_balance', 0) or 0 for a in accounts)
        
        if total_savings > 0 or total_severance > 0:
            labels = ['תגמולים', 'פיצויים'] if is_hebrew else ['Savings', 'Severance']
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='תגמולים מול פיצויים' if is_hebrew else 'Savings vs Severance',
                data={
                    'labels': labels,
                    'values': [total_savings, total_severance]
                },
                options={
                    'colors': ['#4CAF50', '#FF9800'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 3. Insurance Coverage Breakdown (Pie Chart)
        coverage_totals = {}
        for acct in accounts:
            death_coverage = acct.get('death_coverage', 0) or 0
            disability_coverage = acct.get('disability_coverage', 0) or 0
            
            if death_coverage > 0:
                label = 'ביטוח חיים' if is_hebrew else 'Life Insurance'
                coverage_totals[label] = coverage_totals.get(label, 0) + death_coverage
            if disability_coverage > 0:
                label = 'אובדן כושר' if is_hebrew else 'Disability'
                coverage_totals[label] = coverage_totals.get(label, 0) + disability_coverage
        
        if coverage_totals:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='כיסויים ביטוחיים' if is_hebrew else 'Insurance Coverage',
                data={
                    'labels': list(coverage_totals.keys()),
                    'values': list(coverage_totals.values())
                },
                options={
                    'colors': ['#E91E63', '#3F51B5'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 4. Product Type Distribution (Pie Chart)
        product_balances = {}
        for acct in accounts:
            product_type = acct.get('product_type_name', '') or acct.get('product_type', '')
            if not product_type:
                product_type = 'לא מוגדר' if is_hebrew else 'Undefined'
            balance = self._calculate_policy_balance(acct)
            if balance > 0:
                product_balances[product_type] = product_balances.get(product_type, 0) + balance
        
        if product_balances and len(product_balances) > 1:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='צבירה לפי סוג מוצר' if is_hebrew else 'Savings by Product Type',
                data={
                    'labels': list(product_balances.keys()),
                    'values': list(product_balances.values())
                },
                options={
                    'colors': ['#009688', '#795548', '#607D8B', '#FF5722', '#673AB7'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 5. Total Summary Gauge (if we have total balance)
        total_balance = totals.get('total_balance', 0)
        if not total_balance:
            total_balance = sum(self._calculate_policy_balance(a) for a in accounts)
        
        if total_balance > 0:
            charts.append(ChartConfig(
                type=ChartType.GAUGE,
                title='סה״כ חיסכון' if is_hebrew else 'Total Savings',
                data={
                    'value': total_balance,
                    'display_value': f'₪{total_balance:,.0f}',
                    'min': 0,
                    'max': total_balance * 1.2,  # 20% headroom
                    'thresholds': [total_balance * 0.25, total_balance * 0.5, total_balance * 0.75]
                },
                options={
                    'colors': ['#ffeb3b', '#8BC34A', '#4CAF50', '#2196F3'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        return charts
    
    def _generate_recommendations(self, analysis: AnalysisResult, lang: str) -> List[Recommendation]:
        """Generate actionable recommendations"""
        recommendations = []
        rec_id = 1
        
        # High risk score recommendation
        if analysis.risk_score > 70:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='risk',
                priority=Priority.URGENT,
                title='סקירת סיכונים דחופה' if lang == 'hebrew' else 'Urgent Risk Review Required',
                description='ציון הסיכון הכולל גבוה ומצריך התייחסות מיידית' if lang == 'hebrew' 
                           else 'The overall risk score is high and requires immediate attention',
                action_items=[
                    'סקור את כל החריגות שזוהו' if lang == 'hebrew' else 'Review all identified anomalies',
                    'בדוק את הנתונים החריגים' if lang == 'hebrew' else 'Verify outlier data points',
                    'עדכן את הערכת הסיכון' if lang == 'hebrew' else 'Update risk assessment'
                ],
                expected_impact='הפחתת רמת הסיכון ב-20-30%' if lang == 'hebrew' else 'Risk level reduction of 20-30%'
            ))
            rec_id += 1
        
        # Missing data recommendation
        missing_patterns = [p for p in analysis.patterns_found if p.type == 'missing_data']
        if missing_patterns:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='data_quality',
                priority=Priority.HIGH,
                title='השלמת נתונים חסרים' if lang == 'hebrew' else 'Complete Missing Data',
                description='זוהו שדות עם נתונים חסרים המשפיעים על איכות הניתוח' if lang == 'hebrew'
                           else 'Fields with missing data detected affecting analysis quality',
                action_items=[
                    'אסוף את הנתונים החסרים' if lang == 'hebrew' else 'Collect missing data',
                    'עדכן את המערכת' if lang == 'hebrew' else 'Update the system',
                    'הרץ ניתוח מחדש' if lang == 'hebrew' else 'Re-run analysis'
                ],
                expected_impact='שיפור דיוק הניתוח ב-15-25%' if lang == 'hebrew' else 'Analysis accuracy improvement of 15-25%'
            ))
            rec_id += 1
        
        # Anomalies recommendation
        if analysis.anomalies:
            high_severity = [a for a in analysis.anomalies if a.severity in [Severity.HIGH, Severity.CRITICAL]]
            if high_severity:
                recommendations.append(Recommendation(
                    id=f"REC-{rec_id}",
                    category='anomalies',
                    priority=Priority.HIGH,
                    title='טיפול בחריגות קריטיות' if lang == 'hebrew' else 'Address Critical Anomalies',
                    description=f'זוהו {len(high_severity)} חריגות ברמה גבוהה או קריטית' if lang == 'hebrew'
                               else f'{len(high_severity)} high or critical anomalies detected',
                    action_items=[a.recommendation for a in high_severity[:3]],
                    expected_impact='הפחתת סיכון והגברת אמינות הנתונים' if lang == 'hebrew' 
                                   else 'Risk reduction and improved data reliability'
                ))
                rec_id += 1
        
        # Data type specific recommendations
        if analysis.data_classification == DataType.INSURANCE:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='insurance',
                priority=Priority.MEDIUM,
                title='סקירת כיסויים ביטוחיים' if lang == 'hebrew' else 'Review Insurance Coverage',
                description='מומלץ לבדוק התאמת הכיסויים לצרכים' if lang == 'hebrew'
                           else 'Review coverage adequacy against needs',
                action_items=[
                    'השווה כיסויים לסיכונים' if lang == 'hebrew' else 'Compare coverage to risks',
                    'בדוק חפיפות בפוליסות' if lang == 'hebrew' else 'Check for policy overlaps',
                    'עדכן סכומי ביטוח' if lang == 'hebrew' else 'Update coverage amounts'
                ],
                expected_impact='אופטימיזציה של הוצאות ביטוח' if lang == 'hebrew' else 'Insurance expense optimization'
            ))
            rec_id += 1
        elif analysis.data_classification == DataType.INVESTMENT:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='investment',
                priority=Priority.MEDIUM,
                title='איזון תיק השקעות' if lang == 'hebrew' else 'Portfolio Rebalancing',
                description='בדוק את פיזור התיק ואיזון הסיכון' if lang == 'hebrew'
                           else 'Review portfolio diversification and risk balance',
                action_items=[
                    'נתח פיזור נכסים' if lang == 'hebrew' else 'Analyze asset allocation',
                    'בדוק התאמה לפרופיל סיכון' if lang == 'hebrew' else 'Check risk profile alignment',
                    'שקול איזון מחדש' if lang == 'hebrew' else 'Consider rebalancing'
                ],
                expected_impact='שיפור יחס תשואה/סיכון' if lang == 'hebrew' else 'Improved return/risk ratio'
            ))
            rec_id += 1
        
        return recommendations
    
    def get_documents_for_user(self, user_id: str, user_role: str) -> List[Dict]:
        """
        Get all documents accessible to a user.
        Admins can see all documents, customers only see their own.
        
        Args:
            user_id: The user's ID
            user_role: The user's role (admin, customer, etc.)
            
        Returns:
            List of document metadata (without parsed_data for efficiency)
        """
        results = []
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        
        for doc_id, doc in self.documents.items():
            # Admin roles can see all documents
            if is_admin or doc.get('owner_id') == user_id:
                # Return summary without heavy parsed_data
                results.append({
                    'document_id': doc['document_id'],
                    'filename': doc['filename'],
                    'file_type': doc['file_type'],
                    'file_size': doc['file_size'],
                    'status': doc['status'],
                    'row_count': doc.get('row_count', 0),
                    'column_count': doc.get('column_count', 0),
                    'owner_id': doc.get('owner_id'),
                    'created_at': doc.get('created_at')
                })
        
        # Sort by created_at descending
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return results
    
    def get_reports_for_user(self, user_id: str, user_role: str) -> List[Dict]:
        """
        Get all reports accessible to a user.
        Admins can see all reports, customers only see their own.
        
        Args:
            user_id: The user's ID
            user_role: The user's role
            
        Returns:
            List of report summaries
        """
        results = []
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        
        for report_id, report in self.reports.items():
            # Get the associated analysis to check ownership
            analysis = self.analyses.get(report.analysis_id)
            if not analysis:
                continue
            
            doc = self.documents.get(analysis.document_id)
            if not doc:
                continue
            
            # Check access permission
            if is_admin or doc.get('owner_id') == user_id:
                results.append({
                    'report_id': report.id,
                    'title': report.title,
                    'report_type': report.report_type,
                    'language': report.language,
                    'generated_at': report.generated_at,
                    'analysis_id': report.analysis_id,
                    'document_id': analysis.document_id,
                    'filename': doc.get('filename'),
                    'risk_score': report.metadata.get('risk_score'),
                    'confidence': report.metadata.get('confidence'),
                    'owner_id': doc.get('owner_id')
                })
        
        # Sort by generated_at descending
        results.sort(key=lambda x: x.get('generated_at', ''), reverse=True)
        return results

    def revoke_reports_for_date(self, user_id: str, user_role: str, target_date: date,
                                scope: str = "self") -> Dict[str, Any]:
        """
        Revoke (delete) reports generated on a specific date.
        Also removes orphaned analyses/documents when possible.

        Args:
            user_id: The requesting user ID
            user_role: The requesting user role
            target_date: Date to revoke (date object)
            scope: "self" (default) or "all" (admin only)

        Returns:
            Summary dict with counts of removed items.
        """
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        allow_all = is_admin and scope == "all"

        reports_to_remove = []
        analyses_to_check = set()
        documents_to_check = set()

        for report_id, report in list(self.reports.items()):
            report_dt = self._parse_report_datetime(report.generated_at)
            if not report_dt or report_dt.date() != target_date:
                continue

            analysis = self.analyses.get(report.analysis_id)
            if not analysis:
                continue

            doc = self.documents.get(analysis.document_id)
            if not doc:
                continue

            if not allow_all and doc.get('owner_id') != user_id:
                continue

            reports_to_remove.append(report_id)
            analyses_to_check.add(report.analysis_id)
            documents_to_check.add(analysis.document_id)

        # Remove reports
        for report_id in reports_to_remove:
            self.reports.pop(report_id, None)

        # Remove analyses not referenced by any remaining report
        analyses_removed = 0
        for analysis_id in analyses_to_check:
            if not any(r.analysis_id == analysis_id for r in self.reports.values()):
                self.analyses.pop(analysis_id, None)
                analyses_removed += 1

        # Remove documents not referenced by any remaining analysis
        documents_removed = 0
        for document_id in documents_to_check:
            if not any(a.document_id == document_id for a in self.analyses.values()):
                self.documents.pop(document_id, None)
                documents_removed += 1

        # Persist changes
        self.save_data()

        return {
            'success': True,
            'target_date': target_date.isoformat(),
            'reports_removed': len(reports_to_remove),
            'analyses_removed': analyses_removed,
            'documents_removed': documents_removed
        }

    def _parse_report_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse report datetime from stored string values."""
        if not date_str:
            return None
        try:
            if date_str.endswith('Z'):
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return datetime.fromisoformat(date_str)
        except ValueError:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return None
    
    def authorize_access(self, resource_type: str, resource_id: str, 
                        user_id: str, user_role: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a user is authorized to access a specific resource.
        
        Args:
            resource_type: 'document', 'analysis', or 'report'
            resource_id: The ID of the resource
            user_id: The user's ID
            user_role: The user's role
            
        Returns:
            Tuple of (is_authorized, error_message)
        """
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        
        if is_admin:
            return True, None
        
        if resource_type == 'document':
            doc = self.documents.get(resource_id)
            if not doc:
                return False, f"Document {resource_id} not found"
            if doc.get('owner_id') != user_id:
                return False, "Access denied: You can only access your own documents"
            return True, None
        
        elif resource_type == 'analysis':
            analysis = self.analyses.get(resource_id)
            if not analysis:
                return False, f"Analysis {resource_id} not found"
            doc = self.documents.get(analysis.document_id)
            if not doc:
                return False, "Associated document not found"
            if doc.get('owner_id') != user_id:
                return False, "Access denied: You can only access your own analyses"
            return True, None
        
        elif resource_type == 'report':
            report = self.reports.get(resource_id)
            if not report:
                return False, f"Report {resource_id} not found"
            analysis = self.analyses.get(report.analysis_id)
            if not analysis:
                return False, "Associated analysis not found"
            doc = self.documents.get(analysis.document_id)
            if not doc:
                return False, "Associated document not found"
            if doc.get('owner_id') != user_id:
                return False, "Access denied: You can only access your own reports"
            return True, None
        
        return False, f"Unknown resource type: {resource_type}"
    
    def get_report_by_id(self, report_id: str, user_id: str = None, user_role: str = None) -> Optional[GeneratedReport]:
        """
        Get a specific report by ID with access control.
        
        Args:
            report_id: The report ID
            user_id: The requesting user's ID (for access control)
            user_role: The requesting user's role
            
        Returns:
            The report if found and authorized, None otherwise
        """
        if user_id and user_role:
            is_authorized, error = self.authorize_access('report', report_id, user_id, user_role)
            if not is_authorized:
                return None
        
        return self.reports.get(report_id)
    
    def to_dict(self, obj) -> Dict:
        """Convert dataclass objects to dictionaries for JSON serialization"""
        if hasattr(obj, '__dataclass_fields__'):
            result = {}
            for field_name in obj.__dataclass_fields__:
                value = getattr(obj, field_name)
                result[field_name] = self.to_dict(value)
            return result
        elif isinstance(obj, list):
            return [self.to_dict(item) for item in obj]
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: self.to_dict(v) for k, v in obj.items()}
        else:
            return obj
    
    # =========================================================================
    # PERSISTENCE - Save and Load Data
    # =========================================================================
    
    def save_data(self, filepath: str = None) -> bool:
        """
        Save all documents, analyses, and reports to a JSON file.
        
        Args:
            filepath: Optional custom filepath. Defaults to AI_REPORTS_DATA_FILE.
            
        Returns:
            True if successful, False otherwise
        """
        if filepath is None:
            filepath = AI_REPORTS_DATA_FILE
        
        try:
            # Convert analyses to serializable format
            analyses_data = {}
            for aid, analysis in self.analyses.items():
                analyses_data[aid] = self.to_dict(analysis)
            
            # Convert reports to serializable format
            reports_data = {}
            for rid, report in self.reports.items():
                reports_data[rid] = self.to_dict(report)
            
            # Prepare documents (remove parsed_data to save space - can be re-parsed)
            documents_data = {}
            for did, doc in self.documents.items():
                doc_copy = doc.copy()
                # Keep only metadata, not the full parsed data
                if 'parsed_data' in doc_copy:
                    doc_copy['has_parsed_data'] = doc_copy['parsed_data'] is not None
                    # Store column info but not full row data to save space
                    if doc_copy['parsed_data']:
                        doc_copy['columns'] = doc_copy['parsed_data'].get('columns', [])
                    del doc_copy['parsed_data']
                documents_data[did] = doc_copy
            
            data = {
                'saved_at': datetime.now().isoformat(),
                'version': '1.0',
                'documents': documents_data,
                'analyses': analyses_data,
                'reports': reports_data,
                'stats': {
                    'total_documents': len(self.documents),
                    'total_analyses': len(self.analyses),
                    'total_reports': len(self.reports)
                }
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
            
            # Write to temp file first for atomic operation
            temp_file = filepath + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, default=str, indent=2, ensure_ascii=False)
            
            # Atomic rename
            os.rename(temp_file, filepath)
            print(f"[AI_REPORTS] Saved data to {filepath} ({len(self.documents)} docs, {len(self.analyses)} analyses, {len(self.reports)} reports)")
            return True
            
        except Exception as e:
            print(f"[AI_REPORTS] Error saving data: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def load_data(self, filepath: str = None) -> bool:
        """
        Load documents, analyses, and reports from a JSON file.
        
        Args:
            filepath: Optional custom filepath. Defaults to AI_REPORTS_DATA_FILE.
            
        Returns:
            True if successful, False otherwise
        """
        if filepath is None:
            filepath = AI_REPORTS_DATA_FILE
        
        if not os.path.exists(filepath):
            print(f"[AI_REPORTS] No saved data file found at {filepath}")
            return False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load documents
            documents_data = data.get('documents', {})
            for did, doc in documents_data.items():
                # Restore minimal document structure
                doc['parsed_data'] = None  # Will need to re-upload to re-parse
                self.documents[did] = doc
            
            # Load analyses - reconstruct AnalysisResult objects
            analyses_data = data.get('analyses', {})
            for aid, analysis_dict in analyses_data.items():
                try:
                    # Reconstruct factors
                    factors = [Factor(**f) for f in analysis_dict.get('extracted_factors', [])]
                    
                    # Reconstruct patterns
                    patterns = [Pattern(**p) for p in analysis_dict.get('patterns_found', [])]
                    
                    # Reconstruct anomalies
                    anomalies = []
                    for a in analysis_dict.get('anomalies', []):
                        a_copy = a.copy()
                        a_copy['severity'] = Severity(a_copy['severity'])
                        anomalies.append(Anomaly(**a_copy))
                    
                    # Reconstruct analysis
                    analysis = AnalysisResult(
                        id=analysis_dict['id'],
                        document_id=analysis_dict['document_id'],
                        language=analysis_dict['language'],
                        language_name=analysis_dict['language_name'],
                        data_classification=DataType(analysis_dict['data_classification']),
                        extracted_factors=factors,
                        patterns_found=patterns,
                        anomalies=anomalies,
                        risk_score=analysis_dict['risk_score'],
                        confidence=analysis_dict['confidence'],
                        processing_time_ms=analysis_dict['processing_time_ms'],
                        summary=analysis_dict['summary'],
                        key_metrics=analysis_dict['key_metrics']
                    )
                    self.analyses[aid] = analysis
                except Exception as e:
                    print(f"[AI_REPORTS] Error loading analysis {aid}: {e}")
            
            # Load reports - reconstruct GeneratedReport objects
            reports_data = data.get('reports', {})
            for rid, report_dict in reports_data.items():
                try:
                    # Reconstruct sections
                    sections = [ReportSection(**s) for s in report_dict.get('sections', [])]
                    
                    # Reconstruct charts
                    charts = []
                    for c in report_dict.get('charts', []):
                        c_copy = c.copy()
                        c_copy['type'] = ChartType(c_copy['type'])
                        charts.append(ChartConfig(**c_copy))
                    
                    # Reconstruct recommendations
                    recommendations = []
                    for r in report_dict.get('recommendations', []):
                        r_copy = r.copy()
                        r_copy['priority'] = Priority(r_copy['priority'])
                        recommendations.append(Recommendation(**r_copy))
                    
                    # Reconstruct report
                    report = GeneratedReport(
                        id=report_dict['id'],
                        analysis_id=report_dict['analysis_id'],
                        report_type=report_dict['report_type'],
                        language=report_dict['language'],
                        title=report_dict['title'],
                        sections=sections,
                        charts=charts,
                        recommendations=recommendations,
                        generated_at=report_dict['generated_at'],
                        metadata=report_dict.get('metadata', {})
                    )
                    self.reports[rid] = report
                except Exception as e:
                    print(f"[AI_REPORTS] Error loading report {rid}: {e}")
            
            print(f"[AI_REPORTS] Loaded data from {filepath} ({len(self.documents)} docs, {len(self.analyses)} analyses, {len(self.reports)} reports)")
            return True
            
        except Exception as e:
            print(f"[AI_REPORTS] Error loading data: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_persistence_stats(self) -> Dict[str, Any]:
        """Get statistics about stored data"""
        return {
            'total_documents': len(self.documents),
            'total_analyses': len(self.analyses),
            'total_reports': len(self.reports),
            'documents_by_owner': self._count_by_owner(self.documents),
            'reports_by_type': self._count_by_type()
        }
    
    def _count_by_owner(self, collection: Dict) -> Dict[str, int]:
        """Count items by owner"""
        counts = {}
        for item in collection.values():
            owner = item.get('owner_id', 'unknown')
            counts[owner] = counts.get(owner, 0) + 1
        return counts
    
    def _count_by_type(self) -> Dict[str, int]:
        """Count reports by type"""
        counts = {}
        for report in self.reports.values():
            rtype = report.report_type
            counts[rtype] = counts.get(rtype, 0) + 1
        return counts


# Persistence file path
AI_REPORTS_DATA_FILE = os.environ.get('AI_REPORTS_DATA_FILE', 'data/ai_reports_data.json')

# Singleton instance
_ai_reports_service: AIRiskReportsService = None


def get_ai_reports_service() -> AIRiskReportsService:
    """Get or create the AI reports service singleton, loading saved data if available"""
    global _ai_reports_service
    if _ai_reports_service is None:
        _ai_reports_service = AIRiskReportsService()
        # Load persisted data on first access
        _ai_reports_service.load_data()
    return _ai_reports_service


def init_ai_reports_service(load_persisted: bool = True) -> AIRiskReportsService:
    """
    Initialize the AI reports service.
    
    Args:
        load_persisted: If True, load previously saved data from disk.
                       Set to False for testing with fresh state.
    """
    global _ai_reports_service
    _ai_reports_service = AIRiskReportsService()
    if load_persisted:
        _ai_reports_service.load_data()
    return _ai_reports_service
