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
from datetime import datetime
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


class DataClassifier:
    """Classifies the type of data based on column names and content"""
    
    INSURANCE_KEYWORDS = [
        'policy', 'premium', 'coverage', 'claim', 'insured', 'beneficiary',
        'deductible', 'underwriting', 'risk', 'פוליסה', 'ביטוח', 'כיסוי',
        'תביעה', 'פרמיה', 'מבוטח', 'סכום', 'השתתפות עצמית'
    ]
    
    INVESTMENT_KEYWORDS = [
        'portfolio', 'stock', 'bond', 'fund', 'yield', 'return', 'asset',
        'equity', 'dividend', 'market', 'תיק', 'השקעה', 'מניה', 'אגרת חוב',
        'קרן', 'תשואה', 'נכס', 'דיבידנד'
    ]
    
    RISK_KEYWORDS = [
        'risk', 'score', 'assessment', 'rating', 'exposure', 'probability',
        'impact', 'mitigation', 'סיכון', 'ציון', 'הערכה', 'דירוג', 'חשיפה'
    ]
    
    SAVINGS_KEYWORDS = [
        'savings', 'balance', 'deposit', 'withdrawal', 'interest', 'account',
        'חיסכון', 'יתרה', 'הפקדה', 'משיכה', 'ריבית', 'חשבון'
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
            elif file_type_lower in ['csv', 'xls', 'xlsx']:
                # Parse as CSV (XLS files should be converted to CSV format)
                encoding = self._detect_encoding(file_content)
                text_content = file_content.decode(encoding, errors='replace')
                parsed = self._parse_csv(text_content)
            else:
                # Try to parse as CSV
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
    
    def _parse_zip(self, content: bytes) -> Dict[str, Any]:
        """Parse ZIP file containing CSV, image, and PDF files"""
        combined_data = {'columns': [], 'rows': [], 'files': []}
        
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
                
                if ext == 'csv':
                    encoding = self._detect_encoding(file_content)
                    text_content = file_content.decode(encoding, errors='replace')
                    parsed = self._parse_csv(text_content)
                elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    parsed = self._parse_image(file_content, name, ext)
                elif ext == 'pdf':
                    parsed = self._parse_pdf(file_content, name)
                elif ext in ['xls', 'xlsx']:
                    # Try to parse as CSV (basic support)
                    try:
                        encoding = self._detect_encoding(file_content)
                        text_content = file_content.decode(encoding, errors='replace')
                        parsed = self._parse_csv(text_content)
                    except:
                        pass
                
                if parsed:
                    combined_data['files'].append({
                        'name': name,
                        'type': ext,
                        'columns': parsed.get('columns', []),
                        'row_count': len(parsed.get('rows', []))
                    })
                    
                    # Merge columns and rows
                    for col in parsed.get('columns', []):
                        if col not in combined_data['columns']:
                            combined_data['columns'].append(col)
                    combined_data['rows'].extend(parsed.get('rows', []))
        
        return combined_data
    
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
        Perform AI analysis on parsed document.
        Returns comprehensive analysis with factors, patterns, and risk assessment.
        """
        start_time = datetime.now()
        
        if document_id not in self.documents:
            raise ValueError(f"Document {document_id} not found")
        
        doc = self.documents[document_id]
        parsed = doc.get('parsed_data', {})
        columns = parsed.get('columns', [])
        rows = parsed.get('rows', [])
        
        # Combine all text for language detection
        all_text = ' '.join(columns)
        for row in rows[:20]:  # Sample first 20 rows
            all_text += ' ' + ' '.join(str(v) for v in row.values() if v)
        
        # Detect language
        lang_code, lang_name, lang_confidence = LanguageDetector.detect(all_text)
        
        # Classify data type
        data_type, type_confidence = DataClassifier.classify(columns, rows)
        
        # Extract factors
        factors = self._extract_factors(columns, rows, data_type)
        
        # Find patterns
        patterns = self._find_patterns(rows, data_type)
        
        # Detect anomalies
        anomalies = self._detect_anomalies(rows, data_type)
        
        # Calculate risk score
        risk_score = self._calculate_risk_score(factors, patterns, anomalies)
        
        # Generate summary
        summary = self._generate_summary(lang_code, data_type, len(rows), factors, risk_score)
        
        # Extract key metrics
        key_metrics = self._extract_key_metrics(rows, columns, data_type)
        
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
        
        # Generate sections based on data type
        sections = self._generate_sections(analysis, lang)
        
        # Generate charts
        charts = self._generate_charts(analysis)
        
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
                'processing_time_ms': analysis.processing_time_ms
            }
        )
        
        self.reports[report_id] = report
        
        # Auto-save for persistence
        self.save_data()
        
        return report
    
    def _generate_sections(self, analysis: AnalysisResult, lang: str) -> List[ReportSection]:
        """Generate report sections"""
        sections = []
        
        # Executive Summary
        sections.append(ReportSection(
            title='תקציר מנהלים' if lang == 'hebrew' else 'Executive Summary',
            content=analysis.summary,
            order=1
        ))
        
        # Key Metrics
        metrics_content = '\n'.join([f"• {k}: {v}" for k, v in list(analysis.key_metrics.items())[:10]])
        sections.append(ReportSection(
            title='מדדים עיקריים' if lang == 'hebrew' else 'Key Metrics',
            content=metrics_content,
            data_table=analysis.key_metrics,
            order=2
        ))
        
        # Factors Analysis
        if analysis.extracted_factors:
            factors_content = '\n'.join([
                f"• {f.name}: {f.value} (חשיבות: {f.importance:.0%})" if lang == 'hebrew' 
                else f"• {f.name}: {f.value} (Importance: {f.importance:.0%})"
                for f in analysis.extracted_factors
            ])
            sections.append(ReportSection(
                title='ניתוח גורמים' if lang == 'hebrew' else 'Factors Analysis',
                content=factors_content,
                order=3
            ))
        
        # Patterns Found
        if analysis.patterns_found:
            patterns_content = '\n'.join([
                f"• {p.description} (משמעות: {p.significance:.0%})" if lang == 'hebrew'
                else f"• {p.description} (Significance: {p.significance:.0%})"
                for p in analysis.patterns_found
            ])
            sections.append(ReportSection(
                title='דפוסים שזוהו' if lang == 'hebrew' else 'Patterns Found',
                content=patterns_content,
                order=4
            ))
        
        # Anomalies
        if analysis.anomalies:
            anomalies_content = '\n'.join([
                f"• [{a.severity.value.upper()}] {a.description}"
                for a in analysis.anomalies
            ])
            sections.append(ReportSection(
                title='חריגות וסיכונים' if lang == 'hebrew' else 'Anomalies & Risks',
                content=anomalies_content,
                order=5
            ))
        
        # Risk Assessment
        risk_level = 'נמוך' if analysis.risk_score < 30 else ('בינוני' if analysis.risk_score < 60 else 'גבוה')
        risk_level_en = 'Low' if analysis.risk_score < 30 else ('Medium' if analysis.risk_score < 60 else 'High')
        
        sections.append(ReportSection(
            title='הערכת סיכון כוללת' if lang == 'hebrew' else 'Overall Risk Assessment',
            content=f"ציון סיכון: {analysis.risk_score:.1f}/100 - רמה: {risk_level}" if lang == 'hebrew'
                    else f"Risk Score: {analysis.risk_score:.1f}/100 - Level: {risk_level_en}",
            order=6
        ))
        
        return sections
    
    def _generate_charts(self, analysis: AnalysisResult) -> List[ChartConfig]:
        """Generate chart configurations"""
        charts = []
        
        # Risk Score Gauge
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
        
        # Factors Importance Bar Chart
        if analysis.extracted_factors:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='Factors Importance',
                data={
                    'labels': [f.name for f in analysis.extracted_factors[:8]],
                    'values': [f.importance * 100 for f in analysis.extracted_factors[:8]]
                },
                options={'horizontal': True}
            ))
        
        # Data Distribution Pie Chart
        if analysis.key_metrics:
            numeric_metrics = {k: v for k, v in analysis.key_metrics.items() 
                             if isinstance(v, (int, float)) and k.endswith('_total')}
            if numeric_metrics:
                charts.append(ChartConfig(
                    type=ChartType.PIE,
                    title='Data Distribution',
                    data={
                        'labels': list(numeric_metrics.keys())[:6],
                        'values': list(numeric_metrics.values())[:6]
                    }
                ))
        
        # Anomalies by Severity
        if analysis.anomalies:
            severity_counts = {}
            for a in analysis.anomalies:
                severity_counts[a.severity.value] = severity_counts.get(a.severity.value, 0) + 1
            
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='Anomalies by Severity',
                data={
                    'labels': list(severity_counts.keys()),
                    'values': list(severity_counts.values())
                },
                options={'colors': ['#4caf50', '#ffeb3b', '#ff9800', '#f44336']}
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
