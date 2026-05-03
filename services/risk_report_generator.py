"""
PHINS Risk Report Generator
===========================
Generates comprehensive, downloadable risk assessment reports for underwriting applications.
Produces executive-level AI analysis with detailed recommendations.

Features:
- Full risk assessment breakdown
- Medical condition analysis
- Document verification summary
- AI-powered recommendations
- Executive summary
- PDF/HTML report generation
- Pipeline-ready structured output

Author: PHINS Platform
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import json
import hashlib
import uuid
import html  # Security: HTML escaping for XSS prevention


class ReportFormat(Enum):
    """Output formats for reports"""
    HTML = "html"
    JSON = "json"
    TEXT = "text"
    PDF_READY = "pdf_ready"


class RiskCategory(Enum):
    """Risk categorization"""
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"
    VERY_HIGH = "very_high"


class RecommendationType(Enum):
    """AI recommendation types"""
    AUTO_APPROVE = "auto_approve"
    APPROVE_STANDARD = "approve_standard"
    APPROVE_WITH_EXCLUSIONS = "approve_with_exclusions"
    APPROVE_WITH_LOADING = "approve_with_loading"
    REFER_MEDICAL = "refer_medical"
    REFER_SENIOR_UW = "refer_senior_underwriter"
    DECLINE = "decline"
    DEFER = "defer"


@dataclass
class MedicalCondition:
    """Medical condition assessment"""
    condition_name: str
    icd_code: str
    severity: str  # mild, moderate, severe
    diagnosed_date: Optional[str]
    current_status: str  # active, controlled, in_remission
    treatment: str
    risk_impact: float  # 0.0 to 1.0
    exclusion_recommended: bool
    loading_percentage: float  # Premium loading recommendation
    notes: str


@dataclass
class DocumentVerification:
    """Document verification result"""
    document_type: str
    document_id: str
    verified: bool
    authenticity_score: float
    expiry_status: str  # valid, expiring_soon, expired
    extracted_data: Dict[str, Any]
    flags: List[str]
    verification_date: datetime


@dataclass
class RiskFactor:
    """Individual risk factor"""
    category: str
    factor_name: str
    factor_value: Any
    impact_score: float
    impact_direction: str  # increases, decreases, neutral
    weight: float
    explanation: str
    data_source: str


@dataclass
class ExecutiveRecommendation:
    """AI Executive recommendation"""
    recommendation_type: RecommendationType
    confidence_level: float
    primary_rationale: str
    supporting_factors: List[str]
    risk_mitigations: List[str]
    conditions: List[str]
    premium_adjustment: float
    exclusions: List[str]
    monitoring_requirements: List[str]
    review_period_months: int


@dataclass
class ComprehensiveRiskReport:
    """Full risk assessment report"""
    # Header
    report_id: str
    application_id: str
    customer_id: str
    policy_type: str
    coverage_amount: float
    
    # Applicant Profile
    applicant_name: str
    applicant_age: int
    applicant_gender: str
    applicant_occupation: str
    applicant_location: str
    
    # Risk Scores
    overall_risk_score: float
    risk_category: RiskCategory
    identity_score: float
    medical_score: float
    lifestyle_score: float
    financial_score: float
    fraud_score: float
    
    # Medical Assessment
    medical_conditions: List[MedicalCondition]
    disability_percentage: float
    disability_type: str
    bmi_category: str
    smoking_status: str
    
    # Document Verification
    documents_verified: List[DocumentVerification]
    identity_verified: bool
    
    # Risk Factors
    risk_factors: List[RiskFactor]
    
    # AI Recommendation
    recommendation: ExecutiveRecommendation
    
    # Metadata
    assessment_date: datetime
    assessor_id: str
    processing_time_seconds: float
    model_version: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'report_id': self.report_id,
            'application_id': self.application_id,
            'customer_id': self.customer_id,
            'policy_type': self.policy_type,
            'coverage_amount': self.coverage_amount,
            'applicant': {
                'name': self.applicant_name,
                'age': self.applicant_age,
                'gender': self.applicant_gender,
                'occupation': self.applicant_occupation,
                'location': self.applicant_location
            },
            'risk_scores': {
                'overall': self.overall_risk_score,
                'category': self.risk_category.value,
                'identity': self.identity_score,
                'medical': self.medical_score,
                'lifestyle': self.lifestyle_score,
                'financial': self.financial_score,
                'fraud': self.fraud_score
            },
            'medical_assessment': {
                'conditions': [self._condition_to_dict(c) for c in self.medical_conditions],
                'disability_percentage': self.disability_percentage,
                'disability_type': self.disability_type,
                'bmi_category': self.bmi_category,
                'smoking_status': self.smoking_status
            },
            'documents': [self._doc_to_dict(d) for d in self.documents_verified],
            'identity_verified': self.identity_verified,
            'risk_factors': [self._factor_to_dict(f) for f in self.risk_factors],
            'recommendation': self._recommendation_to_dict(self.recommendation),
            'metadata': {
                'assessment_date': self.assessment_date.isoformat(),
                'assessor_id': self.assessor_id,
                'processing_time_seconds': self.processing_time_seconds,
                'model_version': self.model_version
            }
        }
    
    def _condition_to_dict(self, c: MedicalCondition) -> Dict:
        return {
            'condition': c.condition_name,
            'icd_code': c.icd_code,
            'severity': c.severity,
            'diagnosed_date': c.diagnosed_date,
            'status': c.current_status,
            'treatment': c.treatment,
            'risk_impact': c.risk_impact,
            'exclusion_recommended': c.exclusion_recommended,
            'loading_percentage': c.loading_percentage,
            'notes': c.notes
        }
    
    def _doc_to_dict(self, d: DocumentVerification) -> Dict:
        return {
            'type': d.document_type,
            'id': d.document_id,
            'verified': d.verified,
            'authenticity_score': d.authenticity_score,
            'expiry_status': d.expiry_status,
            'extracted_data': d.extracted_data,
            'flags': d.flags
        }
    
    def _factor_to_dict(self, f: RiskFactor) -> Dict:
        return {
            'category': f.category,
            'name': f.factor_name,
            'value': str(f.factor_value),
            'impact': f.impact_score,
            'direction': f.impact_direction,
            'weight': f.weight,
            'explanation': f.explanation,
            'source': f.data_source
        }
    
    def _recommendation_to_dict(self, r: ExecutiveRecommendation) -> Dict:
        return {
            'type': r.recommendation_type.value,
            'confidence': r.confidence_level,
            'rationale': r.primary_rationale,
            'supporting_factors': r.supporting_factors,
            'risk_mitigations': r.risk_mitigations,
            'conditions': r.conditions,
            'premium_adjustment': r.premium_adjustment,
            'exclusions': r.exclusions,
            'monitoring': r.monitoring_requirements,
            'review_period_months': r.review_period_months
        }


class RiskReportGenerator:
    """
    Generates comprehensive risk assessment reports.
    """
    
    # BMI categories
    BMI_CATEGORIES = {
        (0, 18.5): 'Underweight',
        (18.5, 25): 'Normal',
        (25, 30): 'Overweight',
        (30, 35): 'Obese Class I',
        (35, 40): 'Obese Class II',
        (40, 100): 'Obese Class III (Severe)'
    }
    
    # Occupation risk ratings
    OCCUPATION_RISK = {
        'office_worker': 0.1,
        'teacher': 0.1,
        'nurse': 0.2,
        'doctor': 0.15,
        'construction_worker': 0.5,
        'police_officer': 0.4,
        'firefighter': 0.5,
        'pilot': 0.3,
        'miner': 0.6,
        'software_engineer': 0.1,
        'accountant': 0.1,
        'retail_worker': 0.15,
        'driver': 0.3,
        'chef': 0.2,
        'default': 0.2
    }
    
    def __init__(self):
        self.generator_id = f"RRG-{uuid.uuid4().hex[:8]}"
        self.model_version = "1.0.0"
    
    def generate_report(self,
                       application_id: str,
                       customer_data: Dict[str, Any],
                       medical_data: Dict[str, Any],
                       documents: List[Dict[str, Any]],
                       policy_data: Dict[str, Any]) -> ComprehensiveRiskReport:
        """
        Generate a comprehensive risk assessment report.
        """
        start_time = datetime.now()
        
        # Extract applicant info
        applicant_name = customer_data.get('name', 'Unknown')
        applicant_age = customer_data.get('age', 0)
        applicant_gender = customer_data.get('gender', 'unknown')
        applicant_occupation = customer_data.get('occupation', 'unknown')
        applicant_location = customer_data.get('location', customer_data.get('city', 'Unknown'))
        
        # Process medical conditions
        medical_conditions = self._process_medical_conditions(medical_data)
        
        # Process documents
        doc_verifications = self._process_documents(documents)
        
        # Calculate risk scores
        scores = self._calculate_risk_scores(
            applicant_age=applicant_age,
            medical_conditions=medical_conditions,
            medical_data=medical_data,
            occupation=applicant_occupation,
            documents=doc_verifications
        )
        
        # Identify risk factors
        risk_factors = self._identify_risk_factors(
            applicant_age=applicant_age,
            medical_conditions=medical_conditions,
            medical_data=medical_data,
            occupation=applicant_occupation,
            scores=scores
        )
        
        # Generate AI recommendation
        recommendation = self._generate_recommendation(
            scores=scores,
            risk_factors=risk_factors,
            medical_conditions=medical_conditions,
            medical_data=medical_data,
            applicant_age=applicant_age
        )
        
        # Determine risk category
        risk_category = self._determine_risk_category(scores['overall'])
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        report = ComprehensiveRiskReport(
            report_id=f"RR-{application_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            application_id=application_id,
            customer_id=customer_data.get('id', 'unknown'),
            policy_type=policy_data.get('type', 'life'),
            coverage_amount=policy_data.get('coverage_amount', 0),
            applicant_name=applicant_name,
            applicant_age=applicant_age,
            applicant_gender=applicant_gender,
            applicant_occupation=applicant_occupation,
            applicant_location=applicant_location,
            overall_risk_score=scores['overall'],
            risk_category=risk_category,
            identity_score=scores['identity'],
            medical_score=scores['medical'],
            lifestyle_score=scores['lifestyle'],
            financial_score=scores['financial'],
            fraud_score=scores['fraud'],
            medical_conditions=medical_conditions,
            disability_percentage=medical_data.get('disability_percentage', 0),
            disability_type=medical_data.get('disability_type', 'none'),
            bmi_category=medical_data.get('bmi_category', 'Normal'),
            smoking_status=medical_data.get('smoking_status', 'non_smoker'),
            documents_verified=doc_verifications,
            identity_verified=all(d.verified for d in doc_verifications if d.document_type in ['passport', 'driving_licence']),
            risk_factors=risk_factors,
            recommendation=recommendation,
            assessment_date=datetime.now(),
            assessor_id=self.generator_id,
            processing_time_seconds=processing_time,
            model_version=self.model_version
        )
        
        return report
    
    def _process_medical_conditions(self, medical_data: Dict) -> List[MedicalCondition]:
        """Process medical conditions from data"""
        conditions = []
        
        raw_conditions = medical_data.get('conditions', [])
        
        for cond in raw_conditions:
            conditions.append(MedicalCondition(
                condition_name=cond.get('name', 'Unknown'),
                icd_code=cond.get('icd_code', ''),
                severity=cond.get('severity', 'moderate'),
                diagnosed_date=cond.get('diagnosed_date'),
                current_status=cond.get('status', 'active'),
                treatment=cond.get('treatment', 'Unknown'),
                risk_impact=cond.get('risk_impact', 0.3),
                exclusion_recommended=cond.get('exclusion_recommended', False),
                loading_percentage=cond.get('loading_percentage', 0),
                notes=cond.get('notes', '')
            ))
        
        return conditions
    
    def _process_documents(self, documents: List[Dict]) -> List[DocumentVerification]:
        """Process document verifications"""
        verifications = []
        
        for doc in documents:
            verifications.append(DocumentVerification(
                document_type=doc.get('type', 'unknown'),
                document_id=doc.get('id', ''),
                verified=doc.get('verified', True),
                authenticity_score=doc.get('authenticity_score', 0.9),
                expiry_status=doc.get('expiry_status', 'valid'),
                extracted_data=doc.get('extracted_data', {}),
                flags=doc.get('flags', []),
                verification_date=datetime.now()
            ))
        
        return verifications
    
    def _calculate_risk_scores(self,
                               applicant_age: int,
                               medical_conditions: List[MedicalCondition],
                               medical_data: Dict,
                               occupation: str,
                               documents: List[DocumentVerification]) -> Dict[str, float]:
        """Calculate all risk scores"""
        
        # Identity score (based on document verification)
        if documents:
            identity_score = sum(d.authenticity_score for d in documents if d.verified) / len(documents)
        else:
            identity_score = 0.5
        
        # Medical score (higher = more risk)
        base_medical = 0.1
        
        # Age factor
        if applicant_age < 30:
            age_factor = 0.05
        elif applicant_age < 45:
            age_factor = 0.1
        elif applicant_age < 55:
            age_factor = 0.2
        elif applicant_age < 65:
            age_factor = 0.35
        else:
            age_factor = 0.5
        
        # Condition factor
        condition_factor = sum(c.risk_impact for c in medical_conditions) * 0.5
        
        # Disability factor
        disability_pct = medical_data.get('disability_percentage', 0)
        disability_factor = disability_pct / 100 * 0.4
        
        # BMI factor
        bmi_category = medical_data.get('bmi_category', 'Normal')
        bmi_factors = {
            'Underweight': 0.15,
            'Normal': 0.0,
            'Overweight': 0.1,
            'Obese Class I': 0.2,
            'Obese Class II': 0.35,
            'Obese Class III (Severe)': 0.5
        }
        bmi_factor = bmi_factors.get(bmi_category, 0.1)
        
        # Smoking factor
        smoking_status = medical_data.get('smoking_status', 'non_smoker')
        smoking_factors = {
            'non_smoker': 0.0,
            'former_smoker': 0.1,
            'occasional': 0.15,
            'smoker': 0.3
        }
        smoking_factor = smoking_factors.get(smoking_status, 0.1)
        
        medical_score = min(base_medical + age_factor + condition_factor + disability_factor + bmi_factor + smoking_factor, 1.0)
        
        # Lifestyle score (lower = better)
        occ_risk = self.OCCUPATION_RISK.get(occupation.lower().replace(' ', '_'), 
                                            self.OCCUPATION_RISK['default'])
        lifestyle_score = 1.0 - (occ_risk + smoking_factor * 0.5)
        
        # Financial score (assumed good for now)
        financial_score = 0.85
        
        # Fraud score (based on documents)
        fraud_indicators = sum(1 for d in documents for f in d.flags if 'suspicious' in f.lower() or 'fraud' in f.lower())
        fraud_score = min(fraud_indicators * 0.2, 0.8)
        
        # Overall risk score
        overall = (
            (1 - identity_score) * 0.15 +
            medical_score * 0.40 +
            (1 - lifestyle_score) * 0.15 +
            (1 - financial_score) * 0.10 +
            fraud_score * 0.20
        )
        
        return {
            'overall': min(overall, 1.0),
            'identity': identity_score,
            'medical': medical_score,
            'lifestyle': lifestyle_score,
            'financial': financial_score,
            'fraud': fraud_score
        }
    
    def _identify_risk_factors(self,
                               applicant_age: int,
                               medical_conditions: List[MedicalCondition],
                               medical_data: Dict,
                               occupation: str,
                               scores: Dict[str, float]) -> List[RiskFactor]:
        """Identify all risk factors"""
        factors = []
        
        # Age factor
        if applicant_age >= 45:
            impact = 0.1 if applicant_age < 55 else (0.2 if applicant_age < 65 else 0.35)
            factors.append(RiskFactor(
                category='demographic',
                factor_name='Age',
                factor_value=applicant_age,
                impact_score=impact,
                impact_direction='increases',
                weight=0.15,
                explanation=f'Applicant age of {applicant_age} years increases mortality risk',
                data_source='application'
            ))
        
        # Disability factor
        disability_pct = medical_data.get('disability_percentage', 0)
        if disability_pct > 0:
            impact = disability_pct / 100 * 0.6
            factors.append(RiskFactor(
                category='medical',
                factor_name='Disability',
                factor_value=f'{disability_pct}%',
                impact_score=impact,
                impact_direction='increases',
                weight=0.25,
                explanation=f'{disability_pct}% disability rating impacts risk assessment',
                data_source='disability_certificate'
            ))
        
        # Medical conditions
        for condition in medical_conditions:
            factors.append(RiskFactor(
                category='medical',
                factor_name=condition.condition_name,
                factor_value=condition.severity,
                impact_score=condition.risk_impact,
                impact_direction='increases',
                weight=0.20,
                explanation=f'{condition.condition_name} ({condition.severity}) - {condition.current_status}',
                data_source='medical_report'
            ))
        
        # BMI factor
        bmi_category = medical_data.get('bmi_category', 'Normal')
        if bmi_category not in ['Normal', 'Overweight']:
            impact = 0.2 if 'Obese' in bmi_category else 0.1
            factors.append(RiskFactor(
                category='lifestyle',
                factor_name='BMI Category',
                factor_value=bmi_category,
                impact_score=impact,
                impact_direction='increases',
                weight=0.15,
                explanation=f'BMI category ({bmi_category}) indicates elevated health risk',
                data_source='medical_report'
            ))
        
        # Smoking
        smoking_status = medical_data.get('smoking_status', 'non_smoker')
        if smoking_status != 'non_smoker':
            impact = 0.3 if smoking_status == 'smoker' else 0.15
            factors.append(RiskFactor(
                category='lifestyle',
                factor_name='Smoking Status',
                factor_value=smoking_status,
                impact_score=impact,
                impact_direction='increases',
                weight=0.15,
                explanation=f'Smoking status ({smoking_status}) significantly impacts mortality risk',
                data_source='questionnaire'
            ))
        
        # Occupation
        occ_risk = self.OCCUPATION_RISK.get(occupation.lower().replace(' ', '_'), 
                                            self.OCCUPATION_RISK['default'])
        if occ_risk > 0.2:
            factors.append(RiskFactor(
                category='occupational',
                factor_name='Occupation Risk',
                factor_value=occupation,
                impact_score=occ_risk,
                impact_direction='increases',
                weight=0.10,
                explanation=f'Occupation ({occupation}) has elevated risk profile',
                data_source='application'
            ))
        
        return factors
    
    def _determine_risk_category(self, overall_score: float) -> RiskCategory:
        """Determine risk category from score"""
        if overall_score < 0.15:
            return RiskCategory.VERY_LOW
        elif overall_score < 0.25:
            return RiskCategory.LOW
        elif overall_score < 0.40:
            return RiskCategory.MODERATE
        elif overall_score < 0.55:
            return RiskCategory.ELEVATED
        elif overall_score < 0.70:
            return RiskCategory.HIGH
        else:
            return RiskCategory.VERY_HIGH
    
    def _generate_recommendation(self,
                                 scores: Dict[str, float],
                                 risk_factors: List[RiskFactor],
                                 medical_conditions: List[MedicalCondition],
                                 medical_data: Dict,
                                 applicant_age: int) -> ExecutiveRecommendation:
        """Generate AI executive recommendation"""
        
        overall_risk = scores['overall']
        medical_risk = scores['medical']
        
        # Determine base recommendation
        if overall_risk < 0.15:
            rec_type = RecommendationType.AUTO_APPROVE
            rationale = "Risk profile within auto-approval parameters. All verification checks passed with excellent scores."
            confidence = 0.95
            premium_adj = 0.0
        elif overall_risk < 0.25:
            rec_type = RecommendationType.APPROVE_STANDARD
            rationale = "Risk profile acceptable for standard terms. Minor risk factors identified but within acceptable range."
            confidence = 0.90
            premium_adj = 0.0
        elif overall_risk < 0.40:
            rec_type = RecommendationType.APPROVE_WITH_LOADING
            rationale = "Moderate risk factors identified. Recommend approval with appropriate premium loading."
            confidence = 0.85
            premium_adj = self._calculate_premium_loading(scores, medical_conditions, medical_data)
        elif overall_risk < 0.55:
            rec_type = RecommendationType.APPROVE_WITH_EXCLUSIONS
            rationale = "Elevated risk profile requires exclusions or significant loading. Consider specific condition exclusions."
            confidence = 0.80
            premium_adj = self._calculate_premium_loading(scores, medical_conditions, medical_data)
        elif overall_risk < 0.70:
            rec_type = RecommendationType.REFER_MEDICAL
            rationale = "High risk medical profile requires Chief Medical Officer review before decision."
            confidence = 0.75
            premium_adj = 0.0
        else:
            rec_type = RecommendationType.REFER_SENIOR_UW
            rationale = "Very high risk profile. Senior underwriter review required for final decision."
            confidence = 0.70
            premium_adj = 0.0
        
        # Supporting factors
        supporting = []
        for factor in sorted(risk_factors, key=lambda x: x.impact_score, reverse=True)[:5]:
            supporting.append(f"{factor.factor_name}: {factor.factor_value} ({factor.impact_direction} risk by {factor.impact_score:.1%})")
        
        # Risk mitigations
        mitigations = []
        if medical_data.get('disability_percentage', 0) > 0:
            mitigations.append("Consider disability-specific exclusion clause")
        if any('Obese' in c.condition_name or medical_data.get('bmi_category', '').startswith('Obese') for c in medical_conditions):
            mitigations.append("Recommend annual BMI monitoring requirement")
        if medical_risk > 0.3:
            mitigations.append("Require updated medical examination annually")
        if applicant_age > 55:
            mitigations.append("Consider reduced coverage term or stepped benefits")
        
        # Conditions
        conditions = []
        if premium_adj > 0:
            conditions.append(f"Premium loading of {premium_adj:.0%} applied")
        if medical_risk > 0.4:
            conditions.append("Annual medical review required")
        if applicant_age > 60:
            conditions.append("Maximum coverage term limited to 10 years")
        
        # Exclusions
        exclusions = []
        for cond in medical_conditions:
            if cond.exclusion_recommended:
                exclusions.append(f"Pre-existing condition exclusion: {cond.condition_name}")
        if medical_data.get('disability_percentage', 0) >= 50:
            exclusions.append("Disability-related claims exclusion for first 24 months")
        
        # Monitoring
        monitoring = []
        if medical_risk > 0.3:
            monitoring.append("Annual health declaration required")
        if any('Obese' in str(c.condition_name) for c in medical_conditions) or 'Obese' in medical_data.get('bmi_category', ''):
            monitoring.append("Bi-annual BMI assessment")
        if medical_data.get('disability_percentage', 0) > 0:
            monitoring.append("Annual disability status update")
        monitoring.append("Claims monitoring for adverse patterns")
        
        # Review period
        if overall_risk < 0.25:
            review_period = 36
        elif overall_risk < 0.40:
            review_period = 24
        elif overall_risk < 0.55:
            review_period = 12
        else:
            review_period = 6
        
        return ExecutiveRecommendation(
            recommendation_type=rec_type,
            confidence_level=confidence,
            primary_rationale=rationale,
            supporting_factors=supporting,
            risk_mitigations=mitigations,
            conditions=conditions,
            premium_adjustment=premium_adj,
            exclusions=exclusions,
            monitoring_requirements=monitoring,
            review_period_months=review_period
        )
    
    def _calculate_premium_loading(self,
                                   scores: Dict[str, float],
                                   medical_conditions: List[MedicalCondition],
                                   medical_data: Dict) -> float:
        """Calculate recommended premium loading percentage"""
        base_loading = 0.0
        
        # Medical conditions loading
        for cond in medical_conditions:
            base_loading += cond.loading_percentage / 100
        
        # BMI loading
        bmi_cat = medical_data.get('bmi_category', 'Normal')
        bmi_loadings = {
            'Obese Class I': 0.15,
            'Obese Class II': 0.30,
            'Obese Class III (Severe)': 0.50
        }
        base_loading += bmi_loadings.get(bmi_cat, 0)
        
        # Disability loading
        disability_pct = medical_data.get('disability_percentage', 0)
        if disability_pct > 0:
            base_loading += disability_pct / 100 * 0.5
        
        # Smoking loading
        if medical_data.get('smoking_status') == 'smoker':
            base_loading += 0.25
        elif medical_data.get('smoking_status') == 'former_smoker':
            base_loading += 0.10
        
        return min(base_loading, 1.0)  # Cap at 100%
    
    def _escape_html(self, value: Any) -> str:
        """
        Safely escape a value for HTML output to prevent XSS attacks.
        
        Args:
            value: Any value to be rendered in HTML
            
        Returns:
            HTML-escaped string
        """
        if value is None:
            return ''
        return html.escape(str(value))
    
    def generate_html_report(self, report: ComprehensiveRiskReport) -> str:
        """Generate HTML formatted report with XSS protection"""
        
        # SECURITY: Escape all user-provided data
        esc = self._escape_html
        
        # Risk category colors
        category_colors = {
            RiskCategory.VERY_LOW: '#28a745',
            RiskCategory.LOW: '#5cb85c',
            RiskCategory.MODERATE: '#f0ad4e',
            RiskCategory.ELEVATED: '#fd7e14',
            RiskCategory.HIGH: '#dc3545',
            RiskCategory.VERY_HIGH: '#721c24'
        }
        
        rec_colors = {
            RecommendationType.AUTO_APPROVE: '#28a745',
            RecommendationType.APPROVE_STANDARD: '#5cb85c',
            RecommendationType.APPROVE_WITH_LOADING: '#17a2b8',
            RecommendationType.APPROVE_WITH_EXCLUSIONS: '#f0ad4e',
            RecommendationType.REFER_MEDICAL: '#fd7e14',
            RecommendationType.REFER_SENIOR_UW: '#dc3545',
            RecommendationType.DECLINE: '#721c24',
            RecommendationType.DEFER: '#6c757d'
        }
        
        risk_color = category_colors.get(report.risk_category, '#6c757d')
        rec_color = rec_colors.get(report.recommendation.recommendation_type, '#6c757d')
        
        html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PHINS - Safe Assurance</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; background: #f5f5f5; }}
        .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
        .report {{ background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #1a237e 0%, #0d47a1 100%); color: white; padding: 30px; }}
        .header h1 {{ font-size: 24px; margin-bottom: 10px; }}
        .header .subtitle {{ opacity: 0.9; font-size: 14px; }}
        .header .report-id {{ font-family: monospace; background: rgba(255,255,255,0.1); padding: 5px 10px; border-radius: 4px; display: inline-block; margin-top: 10px; }}
        .section {{ padding: 25px 30px; border-bottom: 1px solid #eee; }}
        .section:last-child {{ border-bottom: none; }}
        .section-title {{ font-size: 18px; font-weight: 600; color: #1a237e; margin-bottom: 20px; display: flex; align-items: center; }}
        .section-title::before {{ content: ''; width: 4px; height: 24px; background: #1a237e; margin-right: 10px; border-radius: 2px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
        .card {{ background: #f8f9fa; border-radius: 8px; padding: 15px; }}
        .card-label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
        .card-value {{ font-size: 18px; font-weight: 600; color: #333; margin-top: 5px; }}
        .risk-score {{ text-align: center; padding: 30px; }}
        .risk-gauge {{ width: 200px; height: 200px; border-radius: 50%; background: conic-gradient({risk_color} 0% {report.overall_risk_score*100}%, #e0e0e0 {report.overall_risk_score*100}% 100%); margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; }}
        .risk-gauge-inner {{ width: 160px; height: 160px; border-radius: 50%; background: white; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .risk-gauge-value {{ font-size: 36px; font-weight: 700; color: {risk_color}; }}
        .risk-gauge-label {{ font-size: 12px; color: #666; }}
        .risk-category {{ display: inline-block; padding: 8px 20px; background: {risk_color}; color: white; border-radius: 20px; font-weight: 600; font-size: 14px; }}
        .score-bar {{ height: 8px; background: #e0e0e0; border-radius: 4px; margin: 8px 0; overflow: hidden; }}
        .score-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s ease; }}
        .recommendation-box {{ background: {rec_color}; color: white; padding: 25px; border-radius: 8px; margin-bottom: 20px; }}
        .recommendation-type {{ font-size: 20px; font-weight: 700; margin-bottom: 10px; }}
        .recommendation-confidence {{ opacity: 0.9; font-size: 14px; }}
        .rationale {{ background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid {rec_color}; }}
        .condition-card {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 15px; margin-bottom: 10px; }}
        .condition-severe {{ background: #f8d7da; border-color: #dc3545; }}
        .condition-moderate {{ background: #fff3cd; border-color: #ffc107; }}
        .condition-mild {{ background: #d4edda; border-color: #28a745; }}
        .factor-list {{ list-style: none; }}
        .factor-item {{ padding: 12px 15px; background: #f8f9fa; border-radius: 6px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }}
        .factor-impact {{ padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
        .factor-impact.high {{ background: #f8d7da; color: #721c24; }}
        .factor-impact.medium {{ background: #fff3cd; color: #856404; }}
        .factor-impact.low {{ background: #d4edda; color: #155724; }}
        .exclusion-list {{ background: #f8d7da; border-radius: 8px; padding: 15px; }}
        .exclusion-item {{ padding: 8px 0; border-bottom: 1px solid rgba(0,0,0,0.1); }}
        .exclusion-item:last-child {{ border-bottom: none; }}
        .monitoring-list {{ background: #d1ecf1; border-radius: 8px; padding: 15px; }}
        .premium-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; }}
        .premium-value {{ font-size: 32px; font-weight: 700; }}
        .document-status {{ display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
        .document-verified {{ background: #d4edda; color: #155724; }}
        .document-pending {{ background: #fff3cd; color: #856404; }}
        .document-failed {{ background: #f8d7da; color: #721c24; }}
        .footer {{ background: #f8f9fa; padding: 20px 30px; text-align: center; font-size: 12px; color: #666; }}
        .phins-footer {{ text-align: center; padding: 15px 0 10px; font-size: 10px; color: #888; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; color: #333; }}
        @page {{ size: auto; margin: 0; }}
        @media print {{
            .container {{ max-width: 100%; padding: 0; }}
            .report {{ box-shadow: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="report">
            <!-- Header -->
            <div class="header">
                <h1>🔒 UNDERWRITING RISK ASSESSMENT REPORT</h1>
                <div class="subtitle">AI-Powered Comprehensive Risk Analysis</div>
                <div class="report-id">Report ID: {esc(report.report_id)}</div>
            </div>
            
            <!-- Application Info -->
            <div class="section">
                <div class="section-title">Application Details</div>
                <div class="grid">
                    <div class="card">
                        <div class="card-label">Application ID</div>
                        <div class="card-value">{esc(report.application_id)}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Policy Type</div>
                        <div class="card-value">{esc(report.policy_type.title())}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Coverage Amount</div>
                        <div class="card-value">£{report.coverage_amount:,.0f}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Assessment Date</div>
                        <div class="card-value">{report.assessment_date.strftime('%d %b %Y')}</div>
                    </div>
                </div>
            </div>
            
            <!-- Applicant Profile -->
            <div class="section">
                <div class="section-title">Applicant Profile</div>
                <div class="grid">
                    <div class="card">
                        <div class="card-label">Full Name</div>
                        <div class="card-value">{esc(report.applicant_name)}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Age</div>
                        <div class="card-value">{esc(report.applicant_age)} years</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Gender</div>
                        <div class="card-value">{esc(report.applicant_gender.title())}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Occupation</div>
                        <div class="card-value">{esc(report.applicant_occupation)}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Location</div>
                        <div class="card-value">{esc(report.applicant_location)}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Identity Verified</div>
                        <div class="card-value">{'✅ Verified' if report.identity_verified else '⚠️ Pending'}</div>
                    </div>
                </div>
            </div>
            
            <!-- Overall Risk Score -->
            <div class="section">
                <div class="section-title">Overall Risk Assessment</div>
                <div class="risk-score">
                    <div class="risk-gauge">
                        <div class="risk-gauge-inner">
                            <div class="risk-gauge-value">{report.overall_risk_score:.1%}</div>
                            <div class="risk-gauge-label">Risk Score</div>
                        </div>
                    </div>
                    <div class="risk-category">{report.risk_category.value.replace('_', ' ').upper()}</div>
                </div>
                
                <div class="grid" style="margin-top: 30px;">
                    <div class="card">
                        <div class="card-label">Identity Score</div>
                        <div class="card-value">{report.identity_score:.1%}</div>
                        <div class="score-bar"><div class="score-bar-fill" style="width: {report.identity_score*100}%; background: #28a745;"></div></div>
                    </div>
                    <div class="card">
                        <div class="card-label">Medical Risk</div>
                        <div class="card-value">{report.medical_score:.1%}</div>
                        <div class="score-bar"><div class="score-bar-fill" style="width: {report.medical_score*100}%; background: {'#dc3545' if report.medical_score > 0.5 else '#f0ad4e' if report.medical_score > 0.3 else '#28a745'};"></div></div>
                    </div>
                    <div class="card">
                        <div class="card-label">Lifestyle Score</div>
                        <div class="card-value">{report.lifestyle_score:.1%}</div>
                        <div class="score-bar"><div class="score-bar-fill" style="width: {report.lifestyle_score*100}%; background: #28a745;"></div></div>
                    </div>
                    <div class="card">
                        <div class="card-label">Financial Score</div>
                        <div class="card-value">{report.financial_score:.1%}</div>
                        <div class="score-bar"><div class="score-bar-fill" style="width: {report.financial_score*100}%; background: #28a745;"></div></div>
                    </div>
                    <div class="card">
                        <div class="card-label">Fraud Score</div>
                        <div class="card-value">{report.fraud_score:.1%}</div>
                        <div class="score-bar"><div class="score-bar-fill" style="width: {report.fraud_score*100}%; background: {'#dc3545' if report.fraud_score > 0.3 else '#28a745'};"></div></div>
                    </div>
                </div>
            </div>
            
            <!-- Medical Assessment -->
            <div class="section">
                <div class="section-title">Medical Assessment</div>
                <div class="grid" style="margin-bottom: 20px;">
                    <div class="card">
                        <div class="card-label">Disability Status</div>
                        <div class="card-value">{esc(report.disability_percentage)}% ({esc(report.disability_type)})</div>
                    </div>
                    <div class="card">
                        <div class="card-label">BMI Category</div>
                        <div class="card-value">{esc(report.bmi_category)}</div>
                    </div>
                    <div class="card">
                        <div class="card-label">Smoking Status</div>
                        <div class="card-value">{esc(report.smoking_status.replace('_', ' ').title())}</div>
                    </div>
                </div>
                
                <h4 style="margin: 20px 0 15px; color: #333;">Medical Conditions Identified</h4>
                {''.join([f"""
                <div class="condition-card condition-{esc(c.severity)}">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>{esc(c.condition_name)}</strong> <span style="opacity: 0.7;">({esc(c.icd_code)})</span>
                        </div>
                        <span style="background: rgba(0,0,0,0.1); padding: 4px 12px; border-radius: 12px; font-size: 12px;">{esc(c.severity.upper())}</span>
                    </div>
                    <div style="margin-top: 10px; font-size: 14px;">
                        <div><strong>Status:</strong> {esc(c.current_status.replace('_', ' ').title())}</div>
                        <div><strong>Treatment:</strong> {esc(c.treatment)}</div>
                        <div><strong>Risk Impact:</strong> {c.risk_impact:.1%}</div>
                        {'<div style="color: #dc3545; margin-top: 5px;">⚠️ Exclusion Recommended</div>' if c.exclusion_recommended else ''}
                        {f'<div><strong>Loading:</strong> +{c.loading_percentage:.0f}%</div>' if c.loading_percentage > 0 else ''}
                        {f'<div style="margin-top: 5px; font-style: italic; opacity: 0.8;">{esc(c.notes)}</div>' if c.notes else ''}
                    </div>
                </div>
                """ for c in report.medical_conditions]) if report.medical_conditions else '<p style="color: #666;">No significant medical conditions identified.</p>'}
            </div>
            
            <!-- Risk Factors -->
            <div class="section">
                <div class="section-title">Risk Factors Analysis</div>
                <ul class="factor-list">
                    {''.join([f"""
                    <li class="factor-item">
                        <div>
                            <strong>{esc(f.factor_name)}</strong>
                            <div style="font-size: 13px; color: #666;">{esc(f.explanation)}</div>
                        </div>
                        <span class="factor-impact {'high' if f.impact_score > 0.3 else 'medium' if f.impact_score > 0.15 else 'low'}">{esc(f.impact_direction.upper())} {f.impact_score:.1%}</span>
                    </li>
                    """ for f in report.risk_factors])}
                </ul>
            </div>
            
            <!-- Document Verification -->
            <div class="section">
                <div class="section-title">Document Verification</div>
                <table>
                    <thead>
                        <tr>
                            <th>Document Type</th>
                            <th>Status</th>
                            <th>Authenticity</th>
                            <th>Expiry</th>
                            <th>Flags</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"""
                        <tr>
                            <td>{esc(d.document_type.replace('_', ' ').title())}</td>
                            <td><span class="document-status {'document-verified' if d.verified else 'document-failed'}">{'✓ Verified' if d.verified else '✗ Failed'}</span></td>
                            <td>{d.authenticity_score:.1%}</td>
                            <td>{esc(d.expiry_status.replace('_', ' ').title())}</td>
                            <td>{esc(', '.join(d.flags)) if d.flags else '-'}</td>
                        </tr>
                        """ for d in report.documents_verified])}
                    </tbody>
                </table>
            </div>
            
            <!-- AI Recommendation -->
            <div class="section">
                <div class="section-title">🤖 AI Executive Recommendation</div>
                
                <div class="recommendation-box">
                    <div class="recommendation-type">{report.recommendation.recommendation_type.value.replace('_', ' ').upper()}</div>
                    <div class="recommendation-confidence">Confidence Level: {report.recommendation.confidence_level:.1%}</div>
                </div>
                
                <div class="rationale">
                    <strong>Primary Rationale:</strong>
                    <p style="margin-top: 10px;">{esc(report.recommendation.primary_rationale)}</p>
                </div>
                
                {f"""
                <div class="premium-box" style="margin-top: 20px;">
                    <div style="font-size: 14px; opacity: 0.9;">Recommended Premium Loading</div>
                    <div class="premium-value">+{report.recommendation.premium_adjustment:.0%}</div>
                </div>
                """ if report.recommendation.premium_adjustment > 0 else ''}
                
                <div class="grid" style="margin-top: 20px;">
                    <div>
                        <h4 style="margin-bottom: 15px;">Supporting Factors</h4>
                        <ul style="padding-left: 20px;">
                            {''.join([f'<li style="margin-bottom: 8px;">{esc(f)}</li>' for f in report.recommendation.supporting_factors])}
                        </ul>
                    </div>
                    <div>
                        <h4 style="margin-bottom: 15px;">Risk Mitigations</h4>
                        <ul style="padding-left: 20px;">
                            {''.join([f'<li style="margin-bottom: 8px;">{esc(m)}</li>' for m in report.recommendation.risk_mitigations]) if report.recommendation.risk_mitigations else '<li>No specific mitigations required</li>'}
                        </ul>
                    </div>
                </div>
                
                {f"""
                <div class="exclusion-list" style="margin-top: 20px;">
                    <h4 style="margin-bottom: 15px; color: #721c24;">⚠️ Recommended Exclusions</h4>
                    {''.join([f'<div class="exclusion-item">{esc(e)}</div>' for e in report.recommendation.exclusions])}
                </div>
                """ if report.recommendation.exclusions else ''}
                
                <div class="monitoring-list" style="margin-top: 20px;">
                    <h4 style="margin-bottom: 15px; color: #0c5460;">📋 Monitoring Requirements</h4>
                    {''.join([f'<div style="padding: 8px 0; border-bottom: 1px solid rgba(0,0,0,0.1);">{esc(m)}</div>' for m in report.recommendation.monitoring_requirements])}
                </div>
                
                {f"""
                <div style="margin-top: 20px; background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-bottom: 10px;">Conditions of Approval</h4>
                    <ul style="padding-left: 20px;">
                        {''.join([f'<li style="margin-bottom: 5px;">{esc(c)}</li>' for c in report.recommendation.conditions])}
                    </ul>
                </div>
                """ if report.recommendation.conditions else ''}
                
                <div style="margin-top: 20px; text-align: center; padding: 15px; background: #e9ecef; border-radius: 8px;">
                    <strong>Review Period:</strong> {report.recommendation.review_period_months} months
                </div>
            </div>
            
            <!-- Footer -->
            <div class="footer">
                <p>Generated by PHINS AI Underwriting Bot v{esc(report.model_version)}</p>
                <p>Report Generated: {report.assessment_date.strftime('%d %B %Y at %H:%M:%S')}</p>
                <p>Processing Time: {report.processing_time_seconds:.2f} seconds | Assessor ID: {esc(report.assessor_id)}</p>
                <p style="margin-top: 15px; font-size: 10px; opacity: 0.7;">This report is generated by an AI system and should be reviewed by a qualified underwriter before final decision.</p>
            </div>
            <div class="phins-footer">PHINS - Safe Assurance</div>
        </div>
    </div>
</body>
</html>'''
        
        return html_content
    
    def generate_text_report(self, report: ComprehensiveRiskReport) -> str:
        """Generate plain text report"""
        lines = []
        
        lines.append("=" * 80)
        lines.append("           UNDERWRITING RISK ASSESSMENT REPORT")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Report ID:      {report.report_id}")
        lines.append(f"Application ID: {report.application_id}")
        lines.append(f"Generated:      {report.assessment_date.strftime('%d %B %Y at %H:%M:%S')}")
        lines.append("")
        
        lines.append("-" * 80)
        lines.append("APPLICANT PROFILE")
        lines.append("-" * 80)
        lines.append(f"Name:           {report.applicant_name}")
        lines.append(f"Age:            {report.applicant_age} years")
        lines.append(f"Gender:         {report.applicant_gender.title()}")
        lines.append(f"Occupation:     {report.applicant_occupation}")
        lines.append(f"Location:       {report.applicant_location}")
        lines.append(f"Identity:       {'VERIFIED' if report.identity_verified else 'NOT VERIFIED'}")
        lines.append("")
        
        lines.append("-" * 80)
        lines.append("POLICY DETAILS")
        lines.append("-" * 80)
        lines.append(f"Policy Type:    {report.policy_type.title()}")
        lines.append(f"Coverage:       £{report.coverage_amount:,.0f}")
        lines.append("")
        
        lines.append("-" * 80)
        lines.append("RISK ASSESSMENT SCORES")
        lines.append("-" * 80)
        lines.append(f"Overall Risk:   {report.overall_risk_score:.1%} ({report.risk_category.value.replace('_', ' ').upper()})")
        lines.append(f"Identity:       {report.identity_score:.1%}")
        lines.append(f"Medical Risk:   {report.medical_score:.1%}")
        lines.append(f"Lifestyle:      {report.lifestyle_score:.1%}")
        lines.append(f"Financial:      {report.financial_score:.1%}")
        lines.append(f"Fraud Risk:     {report.fraud_score:.1%}")
        lines.append("")
        
        lines.append("-" * 80)
        lines.append("MEDICAL ASSESSMENT")
        lines.append("-" * 80)
        lines.append(f"Disability:     {report.disability_percentage}% ({report.disability_type})")
        lines.append(f"BMI Category:   {report.bmi_category}")
        lines.append(f"Smoking:        {report.smoking_status.replace('_', ' ').title()}")
        lines.append("")
        
        if report.medical_conditions:
            lines.append("Medical Conditions:")
            for i, c in enumerate(report.medical_conditions, 1):
                lines.append(f"  {i}. {c.condition_name} ({c.icd_code})")
                lines.append(f"     Severity: {c.severity} | Status: {c.current_status}")
                lines.append(f"     Treatment: {c.treatment}")
                lines.append(f"     Risk Impact: {c.risk_impact:.1%}")
                if c.exclusion_recommended:
                    lines.append(f"     ⚠ EXCLUSION RECOMMENDED")
                if c.loading_percentage > 0:
                    lines.append(f"     Loading: +{c.loading_percentage:.0f}%")
        lines.append("")
        
        lines.append("-" * 80)
        lines.append("RISK FACTORS")
        lines.append("-" * 80)
        for f in report.risk_factors:
            lines.append(f"• {f.factor_name}: {f.factor_value}")
            lines.append(f"  Impact: {f.impact_score:.1%} ({f.impact_direction})")
            lines.append(f"  {f.explanation}")
            lines.append("")
        
        lines.append("=" * 80)
        lines.append("AI EXECUTIVE RECOMMENDATION")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"DECISION: {report.recommendation.recommendation_type.value.replace('_', ' ').upper()}")
        lines.append(f"Confidence: {report.recommendation.confidence_level:.1%}")
        lines.append("")
        lines.append("Rationale:")
        lines.append(f"  {report.recommendation.primary_rationale}")
        lines.append("")
        
        if report.recommendation.premium_adjustment > 0:
            lines.append(f"PREMIUM LOADING: +{report.recommendation.premium_adjustment:.0%}")
            lines.append("")
        
        lines.append("Supporting Factors:")
        for f in report.recommendation.supporting_factors:
            lines.append(f"  • {f}")
        lines.append("")
        
        if report.recommendation.exclusions:
            lines.append("Recommended Exclusions:")
            for e in report.recommendation.exclusions:
                lines.append(f"  ⚠ {e}")
            lines.append("")
        
        if report.recommendation.conditions:
            lines.append("Conditions of Approval:")
            for c in report.recommendation.conditions:
                lines.append(f"  • {c}")
            lines.append("")
        
        lines.append("Monitoring Requirements:")
        for m in report.recommendation.monitoring_requirements:
            lines.append(f"  • {m}")
        lines.append("")
        
        lines.append(f"Review Period: {report.recommendation.review_period_months} months")
        lines.append("")
        
        lines.append("=" * 80)
        lines.append(f"Generated by PHINS AI Underwriting Bot v{report.model_version}")
        lines.append(f"Processing Time: {report.processing_time_seconds:.2f} seconds")
        lines.append("=" * 80)
        
        return "\n".join(lines)


# Factory function
def create_risk_report_generator() -> RiskReportGenerator:
    """Create a new risk report generator instance"""
    return RiskReportGenerator()
