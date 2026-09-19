"""Risk Reports analysis layer (B9).

Language detection, Hebrew document field extraction, data classification and
the statistical/inductive analysis methods of ``AIRiskReportsService``
(column profiling, correlations, factors, patterns, anomalies, risk score,
summary and key metrics). Pure functions of the parsed rows: nothing here
touches the stores.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple
from services.risk_reports.models import Anomaly, DataType, Factor, Pattern, Severity


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
            r'ת\.?\s*ז\.?[\s:]*([0-9]{8,9})',
            r'תעודת זהות[\s:]*([0-9]{8,9})',
            r'מספר זהות[\s:]*([0-9]{8,9})',
            r'מספר\s*ת\.?\s*ז\.?[\s:]*([0-9]{8,9})',
            r'ת["״]ז[\s.:]*([0-9]{8,9})',
        ],
        'total_accumulation': [
            r'סה["״]כ\s*צבירה[\s:]*[₪$]?\s*([0-9,.]+)',
            r'סך\s*(?:הכל\s*)?צבירה[\s:]*[₪$]?\s*([0-9,.]+)',
            r'צבירה כוללת[\s:]*[₪$]?\s*([0-9,.]+)',
        ],
        'severance': [
            r'יתרת\s*פיצויים[\s:]*[₪$]?\s*([0-9,.]+)',
            r'סה["״]כ\s*פיצויים[\s:]*[₪$]?\s*([0-9,.]+)',
            r'פיצויים[\s:]*[₪$]?\s*([0-9,.]+)',
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
                    if field_name in ['premium', 'cover_amount', 'total_accumulation', 'severance']:
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



class AnalysisMixin:
    """Statistical / inductive analysis over parsed rows."""

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

