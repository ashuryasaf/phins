"""
Underwriting Bot — evidence intake and feature extraction (B1 split).

Path validation for uploaded evidence and the per-modality analyzers
(photo, medical report, official document, audio, video). Each analyzer is a
pure function of ``(metadata, bytes[, transcription])`` returning a result
dict; the service caches results by file SHA-256 through
``services.evidence_facts.FeatureCache``.
"""

from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple

import uuid
import re
import os
import struct
import tempfile
import logging

from services.underwriting_bot.report import UnderwritingMetadata

_logger = logging.getLogger('phins.underwriting_bot')



# ============================================================================
# SECURITY - Path Validation
# ============================================================================

# Allowed base directories for file uploads (configurable via environment)
ALLOWED_UPLOAD_DIRS = [
    '/workspace/uploads',
    os.path.join(tempfile.gettempdir(), 'phins_uploads'),
    os.environ.get('PHINS_UPLOAD_DIR', '/workspace/uploads')
]

def validate_file_path(file_path: str, file_name: str) -> Tuple[bool, str, str]:
    """
    Validate file path to prevent path traversal attacks.
    
    Args:
        file_path: The file path to validate
        file_name: The original file name
        
    Returns:
        Tuple of (is_valid, sanitized_path, error_message)
    """
    if not file_path:
        return True, "", ""  # Empty path is OK (file content may be provided directly)
    
    # Check for path traversal attempts
    dangerous_patterns = ['../', '..\\', '%2e%2e', '%252e', '/etc/', '/proc/', '/sys/']
    file_path_lower = file_path.lower()
    for pattern in dangerous_patterns:
        if pattern in file_path_lower:
            return False, "", f"Security error: Path traversal attempt detected ({pattern})"
    
    # Normalize the path
    try:
        normalized = os.path.normpath(file_path)
        abs_path = os.path.abspath(normalized)
    except Exception as e:
        return False, "", f"Invalid path: {e}"
    
    # Check if path is within allowed directories
    is_allowed = False
    for allowed_dir in ALLOWED_UPLOAD_DIRS:
        if allowed_dir and abs_path.startswith(os.path.abspath(allowed_dir)):
            is_allowed = True
            break
    
    if not is_allowed:
        # If not in allowed dir, generate a safe path
        safe_dir = os.environ.get('PHINS_UPLOAD_DIR', '/workspace/uploads')
        # Sanitize filename - remove any path components and dangerous chars
        safe_name = os.path.basename(file_name) if file_name else 'unnamed'
        safe_name = re.sub(r'[^\w\-_\.]', '_', safe_name)
        abs_path = os.path.join(safe_dir, safe_name)
    
    return True, abs_path, ""


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent security issues."""
    if not filename:
        return f"file_{uuid.uuid4().hex[:8]}"
    
    # Get just the filename, not any path
    filename = os.path.basename(filename)
    
    # Remove/replace dangerous characters
    safe_name = re.sub(r'[^\w\-_\.]', '_', filename)
    
    # Ensure it doesn't start with a dot (hidden file)
    if safe_name.startswith('.'):
        safe_name = '_' + safe_name[1:]
    
    # Limit length
    if len(safe_name) > 255:
        name, ext = os.path.splitext(safe_name)
        safe_name = name[:250] + ext
    
    return safe_name or f"file_{uuid.uuid4().hex[:8]}"



# ============================================================================
# METADATA ANALYZERS
# ============================================================================

class PhotoAnalyzer:
    """Analyzes photos for identity verification and health indicators"""
    
    def __init__(self):
        self.supported_formats = ['image/jpeg', 'image/png', 'image/webp']

    @staticmethod
    def _detect_image_format(data: bytes) -> Tuple[Optional[str], bool]:
        """Detect image format from magic bytes. Returns (format_name, format_ok)."""
        if not data or len(data) < 12:
            return None, False
        if data[:3] == b'\xff\xd8\xff':
            return 'jpeg', True
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'png', True
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'webp', True
        return None, False

    @staticmethod
    def _quality_from_size(file_size: int) -> float:
        """Simple size-based quality heuristic, clamped to [0, 1]."""
        if file_size < 5 * 1024:
            # Low quality / likely too small for useful analysis
            q = file_size / (5 * 1024) * 0.4
        elif file_size <= 50 * 1024:
            # Medium band: 0.4 .. 0.7
            q = 0.4 + ((file_size - 5 * 1024) / (45 * 1024)) * 0.3
        else:
            # Higher: 0.7 .. 1.0 (plateau near 500KB)
            q = 0.7 + min((file_size - 50 * 1024) / (450 * 1024), 1.0) * 0.3
        return max(0.0, min(1.0, q))

    @staticmethod
    def _read_png_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
        """Read width/height from PNG IHDR chunk."""
        # Signature (8) + length(4) + 'IHDR'(4) + width(4) + height(4)
        if len(data) < 24:
            return None
        if data[12:16] != b'IHDR':
            return None
        try:
            width, height = struct.unpack('>II', data[16:24])
            if width > 0 and height > 0:
                return int(width), int(height)
        except struct.error:
            return None
        return None

    @staticmethod
    def _read_jpeg_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
        """Scan JPEG for SOF0/SOF2 marker and read dimensions."""
        i = 2  # skip SOI
        n = len(data)
        while i < n - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            # skip fill bytes
            while i < n and data[i] == 0xFF:
                i += 1
            if i >= n:
                break
            marker = data[i]
            i += 1
            # Standalone markers without length
            if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
                continue
            if i + 2 > n:
                break
            seg_len = struct.unpack('>H', data[i:i + 2])[0]
            if seg_len < 2:
                break
            # SOF0 / SOF1 / SOF2
            if marker in (0xC0, 0xC1, 0xC2) and i + 7 <= n:
                try:
                    height, width = struct.unpack('>HH', data[i + 3:i + 7])
                    if width > 0 and height > 0:
                        return int(width), int(height)
                except struct.error:
                    return None
            i += seg_len
        return None
        
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None) -> Dict[str, Any]:
        """
        Analyze a photo using byte-level heuristics (no CV model):
        - Format magic-byte validation
        - Size-based quality estimate
        - Dimension / portrait-shape hint (not face detection)
        """
        result = {
            'analysis_type': 'photo',
            'features': [],
            'scores': {},
            'flags': []
        }

        if not file_content:
            result['flags'].append('MISSING_CONTENT')
            result['features'].extend([
                {'name': 'portrait_shape_hint', 'value': False, 'confidence': 0.0},
                {'name': 'image_quality', 'value': None, 'confidence': 0.0},
                {'name': 'detected_format', 'value': None, 'confidence': 0.0},
            ])
            result['scores'] = {
                'identity_confidence': 0.0,
                'quality_score': 0.0,
                'usability_score': 0.0,
            }
            result['processing_success'] = False
            return result

        file_size = len(file_content)
        fmt_name, format_ok = self._detect_image_format(file_content)
        image_quality = self._quality_from_size(file_size)

        width = height = None
        if fmt_name == 'png':
            dims = self._read_png_dimensions(file_content)
            if dims:
                width, height = dims
        elif fmt_name == 'jpeg':
            dims = self._read_jpeg_dimensions(file_content)
            if dims:
                width, height = dims

        # Portrait aspect + reasonable size → weak hint only (no face CV model)
        portrait_shape_hint = False
        portrait_confidence = 0.0
        if (
            width is not None and height is not None
            and height > width
            and file_size >= 5 * 1024
            and width >= 64 and height >= 64
        ):
            portrait_shape_hint = True
            portrait_confidence = 0.4

        result['features'].append({
            'name': 'detected_format',
            'value': fmt_name,
            'confidence': 1.0 if format_ok else 0.0
        })
        result['features'].append({
            'name': 'format_ok',
            'value': format_ok,
            'confidence': 1.0 if format_ok else 0.0
        })
        result['features'].append({
            'name': 'file_size',
            'value': file_size,
            'confidence': 1.0
        })
        if width is not None and height is not None:
            result['features'].append({
                'name': 'dimensions',
                'value': {'width': width, 'height': height},
                'confidence': 1.0
            })
        result['features'].append({
            'name': 'portrait_shape_hint',
            'value': portrait_shape_hint,
            'confidence': portrait_confidence
        })
        result['features'].append({
            'name': 'image_quality',
            'value': image_quality,
            'confidence': 0.5  # heuristic only
        })

        # Identity confidence is low without a real face model; use portrait hint only
        identity_confidence = portrait_confidence if portrait_shape_hint else 0.0
        usability = 0.0
        if format_ok:
            usability = image_quality * (0.6 + 0.4 * (portrait_confidence if portrait_shape_hint else 0.0))

        result['scores'] = {
            'identity_confidence': identity_confidence,
            'quality_score': image_quality,
            'usability_score': max(0.0, min(1.0, usability)),
        }

        if not format_ok:
            result['flags'].append('UNKNOWN_OR_INVALID_IMAGE_FORMAT')
        if image_quality < 0.5:
            result['flags'].append('LOW_IMAGE_QUALITY')
        if not portrait_shape_hint:
            result['flags'].append('NO_PORTRAIT_SHAPE_HINT')
        # Explicit: no CV face detection available
        result['flags'].append('NO_FACE_CV_MODEL')

        result['processing_success'] = format_ok
        return result


class MedicalReportAnalyzer:
    """Analyzes medical reports for health risk assessment"""
    
    # Common medical conditions and their risk impact
    CONDITION_RISK_MAPPING = {
        'diabetes': {'category': 'chronic', 'base_risk': 0.6, 'multiplier': 1.3},
        'hypertension': {'category': 'chronic', 'base_risk': 0.5, 'multiplier': 1.2},
        'heart_disease': {'category': 'critical', 'base_risk': 0.8, 'multiplier': 1.5},
        'cancer': {'category': 'critical', 'base_risk': 0.85, 'multiplier': 1.8},
        'asthma': {'category': 'manageable', 'base_risk': 0.3, 'multiplier': 1.1},
        'obesity': {'category': 'lifestyle', 'base_risk': 0.4, 'multiplier': 1.2},
        'depression': {'category': 'mental', 'base_risk': 0.35, 'multiplier': 1.15},
        'anxiety': {'category': 'mental', 'base_risk': 0.3, 'multiplier': 1.1},
        'arthritis': {'category': 'chronic', 'base_risk': 0.35, 'multiplier': 1.1},
        'copd': {'category': 'chronic', 'base_risk': 0.6, 'multiplier': 1.4},
    }

    # Medications only reported when the name literally appears in source text
    KNOWN_MEDICATIONS = {
        'metformin': {'purpose': 'diabetes', 'risk_modifier': 0.1},
        'insulin': {'purpose': 'diabetes', 'risk_modifier': 0.15},
        'lisinopril': {'purpose': 'blood_pressure', 'risk_modifier': 0.1},
        'amlodipine': {'purpose': 'blood_pressure', 'risk_modifier': 0.1},
        'atenolol': {'purpose': 'blood_pressure', 'risk_modifier': 0.1},
        'atorvastatin': {'purpose': 'cholesterol', 'risk_modifier': 0.08},
        'simvastatin': {'purpose': 'cholesterol', 'risk_modifier': 0.08},
        'aspirin': {'purpose': 'cardiovascular', 'risk_modifier': 0.05},
        'warfarin': {'purpose': 'anticoagulant', 'risk_modifier': 0.2},
        'albuterol': {'purpose': 'asthma', 'risk_modifier': 0.08},
        'salbutamol': {'purpose': 'asthma', 'risk_modifier': 0.08},
        'sertraline': {'purpose': 'depression', 'risk_modifier': 0.1},
        'fluoxetine': {'purpose': 'depression', 'risk_modifier': 0.1},
        'ibuprofen': {'purpose': 'pain', 'risk_modifier': 0.05},
        'prednisone': {'purpose': 'anti_inflammatory', 'risk_modifier': 0.12},
    }
    
    def __init__(self):
        self.supported_formats = ['application/pdf', 'image/jpeg', 'image/png', 'text/plain']

    @staticmethod
    def _decode_text_content(file_content: bytes = None) -> str:
        if not file_content:
            return ""
        for encoding in ('utf-8', 'latin-1'):
            try:
                return file_content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return ""

    def _condition_variants(self, condition_key: str) -> List[str]:
        """Accept underscore/space and common phrasing variants."""
        spaced = condition_key.replace('_', ' ')
        underscored = condition_key.replace(' ', '_')
        variants = {condition_key.lower(), spaced.lower(), underscored.lower()}
        if condition_key == 'heart_disease':
            variants.update({'heart disease', 'cardiac disease', 'coronary disease'})
        if condition_key == 'hypertension':
            variants.update({'high blood pressure', 'high bp'})
        if condition_key == 'copd':
            variants.update({'chronic obstructive pulmonary disease'})
        return list(variants)
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None,
                extracted_text: str = "") -> Dict[str, Any]:
        """
        Analyze medical report for:
        - Pre-existing conditions (from extracted/decoded text only)
        - Current medications (only names present in text)
        - Risk indicators derived from found conditions
        """
        result = {
            'analysis_type': 'medical_report',
            'conditions_found': [],
            'medications': [],
            'lab_results': [],
            'risk_indicators': [],
            'scores': {},
            'flags': []
        }

        text = (extracted_text or "").strip()
        if not text and file_content:
            text = self._decode_text_content(file_content).strip()

        if not text:
            result['flags'].append('NO_TEXT_CONTENT')
            result['scores'] = {
                'medical_risk_score': 0.0,
                'conditions_severity': 0.0,
                'medication_impact': 0.0,
                'confidence_note': 'low_confidence_no_text',
            }
            result['processing_success'] = True
            return result

        text_lower = text.lower()

        for condition, cond_data in self.CONDITION_RISK_MAPPING.items():
            matched_variant = None
            for variant in self._condition_variants(condition):
                # Word-boundary-ish match; allow spaces/underscores already normalized in variants
                pattern = r'(?<!\w)' + re.escape(variant) + r'(?!\w)'
                if re.search(pattern, text_lower):
                    matched_variant = variant
                    break
            if matched_variant:
                result['conditions_found'].append({
                    'condition': condition,
                    'category': cond_data['category'],
                    'risk_impact': cond_data['base_risk'],
                    'confidence': 0.7,  # keyword match, not clinical NLP
                    'matched_text': matched_variant,
                })

        for med_name, med_data in self.KNOWN_MEDICATIONS.items():
            pattern = r'(?<!\w)' + re.escape(med_name) + r'(?!\w)'
            if re.search(pattern, text_lower):
                result['medications'].append({
                    'name': med_name.title() if med_name != 'insulin' else 'Insulin',
                    'purpose': med_data['purpose'],
                    'risk_modifier': med_data['risk_modifier'],
                })

        # Scores based only on conditions/meds actually found
        base_risk = 0.0
        for cond in result['conditions_found']:
            base_risk += cond['risk_impact'] * 0.3
        for med in result['medications']:
            base_risk += med.get('risk_modifier', 0.0) * 0.1
        base_risk = min(base_risk, 1.0)

        result['scores'] = {
            'medical_risk_score': base_risk,
            'conditions_severity': min(len(result['conditions_found']) * 0.15, 1.0),
            'medication_impact': min(len(result['medications']) * 0.05, 1.0),
        }

        if not result['conditions_found'] and not result['medications']:
            result['flags'].append('NO_CONDITIONS_OR_MEDS_FOUND')
        if base_risk > 0.7:
            result['flags'].append('HIGH_MEDICAL_RISK')
        if any(c['category'] == 'critical' for c in result['conditions_found']):
            result['flags'].append('CRITICAL_CONDITION_PRESENT')

        result['processing_success'] = True
        return result


class OfficialDocumentAnalyzer:
    """Analyzes official documents (passport, driving licence, NI, disability cert)"""
    
    DOCUMENT_FIELDS = {
        'passport': ['full_name', 'date_of_birth', 'nationality', 'passport_number', 
                     'issue_date', 'expiry_date', 'place_of_birth', 'gender'],
        'driving_licence': ['full_name', 'date_of_birth', 'licence_number', 'categories',
                            'issue_date', 'expiry_date', 'address', 'restrictions'],
        'national_insurance': ['full_name', 'ni_number', 'date_of_birth'],
        'disability_certificate': ['full_name', 'date_of_birth', 'disability_type',
                                   'disability_level', 'issue_date', 'valid_until',
                                   'issuing_authority', 'benefits_entitled']
    }
    
    def __init__(self):
        self.supported_formats = ['application/pdf', 'image/jpeg', 'image/png']

    @staticmethod
    def _decode_text_content(file_content: bytes = None) -> str:
        if not file_content:
            return ""
        for encoding in ('utf-8', 'latin-1'):
            try:
                return file_content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return ""

    @staticmethod
    def _normalize_date(raw: str) -> Optional[str]:
        """Normalize YYYY-MM-DD or DD/MM/YYYY to ISO YYYY-MM-DD."""
        raw = raw.strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _extract_fields_from_text(self, text: str, doc_type: str) -> Dict[str, Any]:
        """Regex field extraction from available document text only."""
        fields: Dict[str, Any] = {}
        if not text:
            return fields

        name_match = re.search(
            r'(?:full\s*)?name\s*[:\-]\s*([A-Za-z][A-Za-z \'\-\.]{1,80})',
            text, re.IGNORECASE
        )
        if name_match:
            fields['full_name'] = name_match.group(1).strip()

        dob_match = re.search(
            r'(?:date\s*of\s*birth|dob|d\.?o\.?b\.?)\s*[:\-]?\s*'
            r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})',
            text, re.IGNORECASE
        )
        if dob_match:
            normalized = self._normalize_date(dob_match.group(1))
            if normalized:
                fields['date_of_birth'] = normalized

        expiry_match = re.search(
            r'(?:expiry\s*date|expiration\s*date|expires?(?:\s*on)?|valid\s*until|valid\s*thru)\s*[:\-]?\s*'
            r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})',
            text, re.IGNORECASE
        )
        if expiry_match:
            normalized = self._normalize_date(expiry_match.group(1))
            if normalized:
                # Use valid_until for disability certificates when that wording appears
                label = expiry_match.group(0).lower()
                if 'valid until' in label or 'valid thru' in label or doc_type == 'disability_certificate':
                    fields['valid_until'] = normalized
                else:
                    fields['expiry_date'] = normalized

        issue_match = re.search(
            r'(?:issue\s*date|date\s*of\s*issue|issued(?:\s*on)?)\s*[:\-]?\s*'
            r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})',
            text, re.IGNORECASE
        )
        if issue_match:
            normalized = self._normalize_date(issue_match.group(1))
            if normalized:
                fields['issue_date'] = normalized

        passport_match = re.search(
            r'(?:passport\s*(?:no\.?|number|#)?\s*[:\-]?\s*)'
            r'([A-Z0-9]{6,12})',
            text, re.IGNORECASE
        )
        if not passport_match:
            # Generic passport-like alphanumerics near "passport"
            passport_match = re.search(
                r'passport[^A-Z0-9]{0,20}([A-Z]{1,2}\d{6,9})',
                text, re.IGNORECASE
            )
        if passport_match and doc_type in ('passport', 'other_document', ''):
            fields['passport_number'] = passport_match.group(1).upper()

        licence_match = re.search(
            r'(?:licence|license)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9]{5,20})',
            text, re.IGNORECASE
        )
        if licence_match and doc_type in ('driving_licence', 'other_document', ''):
            fields['licence_number'] = licence_match.group(1).upper()

        ni_match = re.search(
            r'(?:ni\s*(?:no\.?|number)?|national\s*insurance(?:\s*number)?)\s*[:\-]?\s*'
            r'([A-Z]{2}\s?\d{6}\s?[A-Z])',
            text, re.IGNORECASE
        )
        if ni_match:
            fields['ni_number'] = re.sub(r'\s+', '', ni_match.group(1).upper())

        nationality_match = re.search(
            r'nationality\s*[:\-]\s*([A-Za-z ]{2,40})',
            text, re.IGNORECASE
        )
        if nationality_match:
            fields['nationality'] = nationality_match.group(1).strip()

        gender_match = re.search(
            r'(?:gender|sex)\s*[:\-]\s*([MF]|Male|Female|Other|X)\b',
            text, re.IGNORECASE
        )
        if gender_match:
            fields['gender'] = gender_match.group(1).strip()

        if doc_type == 'disability_certificate' or re.search(r'disability', text, re.IGNORECASE):
            dtype = re.search(
                r'disability\s*type\s*[:\-]\s*([A-Za-z \-]{2,40})',
                text, re.IGNORECASE
            )
            if dtype:
                fields['disability_type'] = dtype.group(1).strip()
            dlevel = re.search(
                r'disability\s*level\s*[:\-]\s*([A-Za-z \-]{2,40})',
                text, re.IGNORECASE
            )
            if dlevel:
                fields['disability_level'] = dlevel.group(1).strip()
            authority = re.search(
                r'(?:issuing\s*authority|issued\s*by)\s*[:\-]\s*([A-Za-z0-9 \-\.]{2,60})',
                text, re.IGNORECASE
            )
            if authority:
                fields['issuing_authority'] = authority.group(1).strip()

        return fields
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None,
                document_type: str = "", extracted_text: str = "") -> Dict[str, Any]:
        """
        Analyze official document for:
        - Field extraction from provided/decoded text (regex)
        - Content-checkable authenticity signals only (expiry presence/status)
        - No invented applicant data or authenticity scores
        """
        doc_type = document_type or metadata.metadata_type.value
        
        result = {
            'analysis_type': 'official_document',
            'document_type': doc_type,
            'extracted_fields': {},
            'authenticity': {},
            'scores': {},
            'flags': []
        }

        text = (extracted_text or "").strip()
        if not text and file_content:
            text = self._decode_text_content(file_content).strip()

        if not text:
            result['extracted_fields'] = {}
            result['flags'].append('NO_CONTENT')
            result['authenticity'] = {
                'verified': None,
                'method': 'none',
            }
            result['scores'] = {
                'authenticity_score': None,
                'completeness_score': 0.0,
                'validity_score': None,
                'has_expiry_date': False,
                'appears_expired': None,
            }
            result['processing_success'] = False
            return result

        fields = self._extract_fields_from_text(text, doc_type)
        result['extracted_fields'] = fields

        expiry_str = fields.get('expiry_date') or fields.get('valid_until')
        has_expiry_date = bool(expiry_str)
        appears_expired = None
        if expiry_str:
            try:
                expiry = datetime.strptime(expiry_str, '%Y-%m-%d').date()
                days_to_expiry = (expiry - date.today()).days
                fields['days_to_expiry'] = days_to_expiry
                appears_expired = days_to_expiry < 0
                if appears_expired:
                    result['flags'].append('DOCUMENT_EXPIRED')
                elif days_to_expiry < 90:
                    result['flags'].append('DOCUMENT_EXPIRING_SOON')
            except ValueError:
                result['flags'].append('UNPARSEABLE_EXPIRY_DATE')

        if doc_type == 'disability_certificate' and (
            fields.get('disability_type') or re.search(r'disability', text, re.IGNORECASE)
        ):
            result['flags'].append('DISABILITY_DECLARED')

        expected = self.DOCUMENT_FIELDS.get(doc_type, [])
        found_expected = sum(1 for f in expected if f in fields)
        completeness = (found_expected / len(expected)) if expected else (
            min(len(fields) / 8.0, 1.0)
        )

        # Authenticity: only report what content can support; never invent a high score
        result['authenticity'] = {
            'verified': None,  # unknown without cryptographic/issuer verification
            'method': 'content_checks',
            'has_expiry_date': has_expiry_date,
            'appears_expired': appears_expired,
            'fields_extracted': len(fields),
        }

        validity_score = None
        if appears_expired is True:
            validity_score = 0.0
        elif appears_expired is False:
            validity_score = 1.0

        result['scores'] = {
            'authenticity_score': None,  # cannot claim authenticity without evidence
            'completeness_score': completeness,
            'validity_score': validity_score,
            'has_expiry_date': has_expiry_date,
            'appears_expired': appears_expired,
        }

        if not fields:
            result['flags'].append('NO_FIELDS_EXTRACTED')

        result['processing_success'] = True
        return result


class AudioAnalyzer:
    """Analyzes audio recordings for underwriting assessment"""
    
    def __init__(self, transcription_provider=None):
        self.supported_formats = ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm']
        # Injected for tests; otherwise resolved per call from the environment
        # (``PHINS_TRANSCRIPTION_PROVIDER``) so a deployment that enables STT
        # later does not need a restart of long-lived analyzer instances.
        self._transcription_provider = transcription_provider

    def _transcribe(self, metadata: UnderwritingMetadata, file_content: bytes,
                    result: Dict[str, Any]) -> str:
        """Run the platform STT provider over ``file_content``.

        Returns the transcript ('' when none). Flags on ``result`` record why
        no transcript was produced: ``NO_STT_AVAILABLE`` only when the provider
        is disabled, ``STT_FAILED`` when a configured provider errored.
        """
        try:
            from services.transcription_providers import (
                TranscriptionUnavailableError, get_transcription_provider,
            )
            provider = self._transcription_provider or get_transcription_provider()
        except Exception as exc:
            _logger.warning("transcription provider unavailable: %s", exc)
            result['flags'].append('NO_STT_AVAILABLE')
            return ''
        try:
            payload = provider.transcribe(
                file_content,
                file_name=metadata.file_name or 'audio.mp3',
                mime_type=metadata.mime_type or 'audio/mpeg',
                context={'customer_id': metadata.customer_id,
                         'underwriting_id': metadata.underwriting_id,
                         'metadata_id': metadata.id},
            )
        except TranscriptionUnavailableError:
            result['flags'].append('NO_STT_AVAILABLE')
            return ''
        except Exception as exc:
            _logger.warning("transcription failed for %s: %s", metadata.id, exc)
            result['flags'].append('STT_FAILED')
            return ''
        text = str((payload or {}).get('text') or '').strip()
        describe = getattr(provider, 'describe', None)
        info = describe() if callable(describe) else {}
        result['stt'] = {
            'provider': (info or {}).get('provider') or type(provider).__name__,
            'model': (payload or {}).get('model') or (info or {}).get('model'),
            'language': (payload or {}).get('language'),
            'duration_seconds': (payload or {}).get('duration_seconds'),
            'segments': len((payload or {}).get('segments') or []),
        }
        if not text:
            result['flags'].append('STT_EMPTY_TRANSCRIPT')
        return text

    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None,
                transcription: str = "") -> Dict[str, Any]:
        """
        Analyze audio. A caller-supplied transcription wins; otherwise the
        platform speech-to-text provider is used when one is configured.
        Without a sentiment model only the transcript and unknown/empty
        signals are reported — nothing is invented.
        """
        result = {
            'analysis_type': 'audio',
            'transcription': '',
            'sentiment': {},
            'health_indicators': [],
            'scores': {},
            'flags': []
        }

        provided = (transcription or "").strip()
        if not provided and file_content:
            provided = self._transcribe(metadata, file_content, result)
        result['transcription'] = provided

        if not provided:
            if 'NO_STT_AVAILABLE' not in result['flags'] and 'STT_FAILED' not in result['flags'] \
                    and 'STT_EMPTY_TRANSCRIPT' not in result['flags']:
                result['flags'].append('NO_STT_AVAILABLE')
            if not file_content:
                result['flags'].append('MISSING_CONTENT')
            else:
                result['flags'].append('ANALYSIS_LIMITED_NO_STT')
            result['sentiment'] = {
                'overall': 'unknown',
                'confidence': 0.0,
                'emotions_detected': [],
                'stress_level': None,
            }
            result['health_indicators'] = []
            result['scores'] = {
                'stress_score': None,
                'clarity_score': None,
                'authenticity_score': None,
            }
            # Bytes present can be accepted; analysis remains limited without STT
            result['processing_success'] = bool(file_content)
            return result

        # Transcription provided by caller — still no sentiment model
        result['sentiment'] = {
            'overall': 'unknown',
            'confidence': 0.0,
            'emotions_detected': [],
            'stress_level': None,
        }
        result['flags'].append('NO_SENTIMENT_MODEL')
        result['scores'] = {
            'stress_score': None,
            'clarity_score': None,
            'authenticity_score': None,
            'transcription_length': len(provided),
        }
        result['processing_success'] = True
        return result


class VideoAnalyzer:
    """Analyzes video recordings for identity verification and assessment"""
    
    def __init__(self):
        self.supported_formats = ['video/mp4', 'video/webm', 'video/quicktime']

    @staticmethod
    def _detect_video_container(data: bytes) -> Optional[str]:
        if not data or len(data) < 12:
            return None
        # ISO BMFF (mp4/mov): bytes 4-8 often 'ftyp'
        if len(data) >= 8 and data[4:8] == b'ftyp':
            return 'mp4'
        # WebM / Matroska EBML header
        if data[:4] == b'\x1a\x45\xdf\xa3':
            return 'webm'
        return None
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None) -> Dict[str, Any]:
        """
        Analyze video. Without CV/liveness models, only report byte-level
        container hints and unknown identity/liveness — do not invent matches.
        """
        result = {
            'analysis_type': 'video',
            'identity_verification': {},
            'liveness': {},
            'behavioral': [],
            'scores': {},
            'flags': []
        }

        if not file_content:
            result['flags'].append('MISSING_CONTENT')
            result['identity_verification'] = {
                'face_detected': None,
                'face_match_score': None,
                'multiple_faces': None,
                'face_consistent_throughout': None,
            }
            result['liveness'] = {
                'is_live': None,
                'confidence': None,
                'spoof_detection': 'unknown',
                'eye_blink_detected': None,
                'head_movement_detected': None,
            }
            result['behavioral'] = []
            result['scores'] = {
                'identity_confidence': 0.0,
                'liveness_score': None,
                'behavioral_score': None,
            }
            result['processing_success'] = False
            return result

        container = self._detect_video_container(file_content)
        file_size = len(file_content)

        result['identity_verification'] = {
            'face_detected': None,  # no CV model
            'face_match_score': None,
            'multiple_faces': None,
            'face_consistent_throughout': None,
            'container_hint': container,
            'file_size': file_size,
        }
        result['liveness'] = {
            'is_live': None,
            'confidence': None,
            'spoof_detection': 'unknown',
            'eye_blink_detected': None,
            'head_movement_detected': None,
        }
        result['behavioral'] = []
        result['scores'] = {
            'identity_confidence': 0.0,
            'liveness_score': None,
            'behavioral_score': None,
        }
        result['flags'].append('NO_VIDEO_CV_MODEL')
        if not container:
            result['flags'].append('UNKNOWN_VIDEO_CONTAINER')
        result['processing_success'] = True
        return result

