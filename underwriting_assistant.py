"""
PHINS Underwriting Assistant System
Intelligent direct underwriting with document management, multi-channel delivery,
and integration with claims, actuary, and risk management divisions.

Features:
- Interactive questionnaire for validation
- Health condition assessment (1-10 scale)
- Document upload and verification
- Multi-channel delivery (SMS, Email, Signed Document)
- Assistant agent for guided underwriting
- Automatic reporting to Actuary and Risk Management
- Claims division integration
- Zero external dependencies
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime, date, timedelta
import json
from abc import ABC, abstractmethod
from customer_validation import (
    Customer, HealthAssessment, Validator, Gender,
    SmokingStatus, PersonalStatus, DocumentType
)


# ============================================================================
# ENUMS - Underwriting Assistant Types
# ============================================================================

class DocumentVerificationStatus(Enum):
    """Document verification statuses"""
    PENDING = "Pending"
    UPLOADED = "Uploaded"
    VERIFIED = "Verified"
    REJECTED = "Rejected"
    EXPIRED = "Expired"


class DeliveryMethod(Enum):
    """Delivery methods for documents and notifications"""
    EMAIL = "Email"
    SMS = "SMS"
    SIGNED_DOCUMENT = "Signed Document"
    PORTAL = "Customer Portal"
    COMBINED = "Combined (Email + SMS + Signed)"


class UnderwritingDecision(Enum):
    """Underwriting decision outcomes"""
    APPROVED = "Approved"
    APPROVED_WITH_CONDITIONS = "Approved with Conditions"
    PENDING_REVIEW = "Pending Review"
    REFERRED = "Referred to Manual Review"
    DECLINED = "Declined"


class QuestionType(Enum):
    """Types of underwriting questions"""
    MULTIPLE_CHOICE = "Multiple Choice"
    YES_NO = "Yes/No"
    TEXT_INPUT = "Text Input"
    NUMERIC = "Numeric"
    DATE = "Date"
    RATING = "Rating (1-10)"


class ReportType(Enum):
    """Types of reports"""
    UNDERWRITING_REPORT = "Underwriting Report"
    RISK_ASSESSMENT = "Risk Assessment"
    CLAIMS_REPORT = "Claims Report"
    ACTUARY_REPORT = "Actuary Report"
    SUMMARY = "Summary Report"


# ============================================================================
# DATA CLASSES - Underwriting Components
# ============================================================================

@dataclass
class UnderwritingQuestion:
    """Single underwriting question"""
    question_id: str
    question_text: str
    question_type: QuestionType
    required: bool = True
    options: List[str] = field(default_factory=list)
    category: str = ""  # Medical, Lifestyle, Financial, etc.
    weight: float = 1.0  # Importance weight for scoring
    
    def validate_answer(self, answer: Any) -> tuple[bool, str]:
        """Validate answer against question type"""
        if not answer and self.required:
            return False, f"Answer required for: {self.question_text}"
        
        if self.question_type == QuestionType.YES_NO:
            if answer not in ["Yes", "No", True, False, "yes", "no"]:
                return False, "Answer must be Yes or No"
        
        elif self.question_type == QuestionType.MULTIPLE_CHOICE:
            if answer not in self.options:
                return False, f"Answer must be one of: {', '.join(self.options)}"
        
        elif self.question_type == QuestionType.NUMERIC:
            try:
                float(answer)
            except (ValueError, TypeError):
                return False, "Answer must be numeric"
        
        elif self.question_type == QuestionType.RATING:
            try:
                rating = int(answer)
                if not (1 <= rating <= 10):
                    return False, "Rating must be between 1 and 10"
            except (ValueError, TypeError):
                return False, "Rating must be numeric (1-10)"
        
        elif self.question_type == QuestionType.DATE:
            if isinstance(answer, str):
                try:
                    datetime.strptime(answer, "%Y-%m-%d")
                except ValueError:
                    return False, "Date format must be YYYY-MM-DD"
        
        return True, "Valid"


@dataclass
class DocumentUpload:
    """Document upload record"""
    document_id: str
    customer_id: str
    document_type: DocumentType
    file_name: str
    file_size_bytes: int
    upload_date: datetime
    verification_status: DocumentVerificationStatus = DocumentVerificationStatus.UPLOADED
    verified_date: Optional[datetime] = None
    verified_by: Optional[str] = None
    verification_notes: str = ""
    expiry_date: Optional[date] = None
    is_valid: bool = True
    
    def verify_document(self, verified_by: str, notes: str = "") -> bool:
        """Mark document as verified"""
        if self.verification_status == DocumentVerificationStatus.VERIFIED:
            return True
        
        # Check expiry
        if self.expiry_date and self.expiry_date < date.today():
            self.verification_status = DocumentVerificationStatus.EXPIRED
            self.is_valid = False
            return False
        
        self.verification_status = DocumentVerificationStatus.VERIFIED
        self.verified_date = datetime.now()
        self.verified_by = verified_by
        self.verification_notes = notes
        self.is_valid = True
        return True
    
    def get_days_to_expiry(self) -> Optional[int]:
        """Get days until document expiry"""
        if not self.expiry_date:
            return None
        delta = self.expiry_date - date.today()
        return delta.days


@dataclass
class UnderwritingAnswer:
    """Answer to underwriting question"""
    question_id: str
    customer_id: str
    answer: Any
    answer_date: datetime
    answer_type: QuestionType
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "question_id": self.question_id,
            "answer": str(self.answer),
            "answer_date": self.answer_date.isoformat(),
            "notes": self.notes
        }


@dataclass
class UnderwritingSession:
    """Complete underwriting session"""
    session_id: str
    customer_id: str
    customer: Optional[Customer] = None
    questions: List[UnderwritingQuestion] = field(default_factory=list)
    answers: List[UnderwritingAnswer] = field(default_factory=list)
    documents: List[DocumentUpload] = field(default_factory=list)
    session_start: datetime = field(default_factory=datetime.now)
    session_end: Optional[datetime] = None
    is_complete: bool = False
    decision: Optional[UnderwritingDecision] = None
    decision_notes: str = ""
    risk_score: float = 0.0
    
    def add_answer(self, answer: UnderwritingAnswer) -> bool:
        """Add answer to session"""
        self.answers.append(answer)
        return True
    
    def add_document(self, document: DocumentUpload) -> bool:
        """Add document to session"""
        self.documents.append(document)
        return True
    
    def get_progress(self) -> Dict[str, Any]:
        """Get session progress"""
        total_required = sum(1 for q in self.questions if q.required)
        answered = sum(1 for a in self.answers)
        
        return {
            "total_questions": len(self.questions),
            "required_questions": total_required,
            "answered_questions": answered,
            "progress_percentage": (answered / total_required * 100) if total_required > 0 else 0,
            "documents_uploaded": len(self.documents),
            "documents_verified": sum(1 for d in self.documents if d.verification_status == DocumentVerificationStatus.VERIFIED),
            "session_started": self.session_start.isoformat(),
            "is_complete": self.is_complete,
            "current_decision": self.decision.value if self.decision else None
        }
    
    def get_unanswered_questions(self) -> List[UnderwritingQuestion]:
        """Get list of unanswered required questions"""
        answered_ids = {a.question_id for a in self.answers}
        return [q for q in self.questions if q.required and q.question_id not in answered_ids]


@dataclass
class NotificationTemplate:
    """Notification delivery template"""
    template_id: str
    template_name: str
    delivery_method: DeliveryMethod
    subject: str = ""
    body: str = ""
    signature_required: bool = False
    created_date: datetime = field(default_factory=datetime.now)
    
    def generate_content(self, context: Dict[str, Any]) -> str:
        """Generate notification content with context"""
        content = self.body
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            content = content.replace(placeholder, str(value))
        return content


@dataclass
class NotificationDelivery:
    """Notification delivery record"""
    delivery_id: str
    customer_id: str
    delivery_method: DeliveryMethod
    recipient: str
    subject: str
    message: str
    delivery_date: datetime
    delivery_status: str = "Sent"  # Sent, Pending, Failed, Read
    read_date: Optional[datetime] = None
    signature_date: Optional[datetime] = None
    signed_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# QUESTIONNAIRE MANAGEMENT
# ============================================================================

class QuestionnaireLibrary:
    """Library of standard underwriting questionnaires"""
    
    HEALTH_ASSESSMENT_QUESTIONS = [
        UnderwritingQuestion(
            question_id="health_001",
            question_text="What is your current overall health status?",
            question_type=QuestionType.RATING,
            category="Medical",
            weight=1.0
        ),
        UnderwritingQuestion(
            question_id="health_002",
            question_text="Do you have any chronic medical conditions?",
            question_type=QuestionType.YES_NO,
            category="Medical",
            weight=0.9
        ),
        UnderwritingQuestion(
            question_id="health_003",
            question_text="What medical conditions do you have?",
            question_type=QuestionType.TEXT_INPUT,
            required=False,
            category="Medical",
            weight=0.8
        ),
        UnderwritingQuestion(
            question_id="health_004",
            question_text="Are you currently taking medications?",
            question_type=QuestionType.YES_NO,
            category="Medical",
            weight=0.8
        ),
        UnderwritingQuestion(
            question_id="health_005",
            question_text="List current medications",
            question_type=QuestionType.TEXT_INPUT,
            required=False,
            category="Medical",
            weight=0.7
        ),
        UnderwritingQuestion(
            question_id="health_006",
            question_text="Do you have any known allergies?",
            question_type=QuestionType.YES_NO,
            category="Medical",
            weight=0.7
        ),
        UnderwritingQuestion(
            question_id="health_007",
            question_text="List known allergies",
            question_type=QuestionType.TEXT_INPUT,
            required=False,
            category="Medical",
            weight=0.6
        ),
    ]
    
    LIFESTYLE_QUESTIONS = [
        UnderwritingQuestion(
            question_id="lifestyle_001",
            question_text="What is your smoking status?",
            question_type=QuestionType.MULTIPLE_CHOICE,
            options=["Non-Smoker", "Smoker", "Former Smoker", "Occasional"],
            category="Lifestyle",
            weight=0.9
        ),
        UnderwritingQuestion(
            question_id="lifestyle_002",
            question_text="How many hours per week do you exercise?",
            question_type=QuestionType.NUMERIC,
            category="Lifestyle",
            weight=0.7
        ),
        UnderwritingQuestion(
            question_id="lifestyle_003",
            question_text="Do you consume alcohol?",
            question_type=QuestionType.YES_NO,
            category="Lifestyle",
            weight=0.6
        ),
        UnderwritingQuestion(
            question_id="lifestyle_004",
            question_text="How many drinks per week?",
            question_type=QuestionType.NUMERIC,
            required=False,
            category="Lifestyle",
            weight=0.6
        ),
    ]
    
    VALIDATION_QUESTIONS = [
        UnderwritingQuestion(
            question_id="validation_001",
            question_text="Is your contact information accurate?",
            question_type=QuestionType.YES_NO,
            category="Validation",
            weight=0.8
        ),
        UnderwritingQuestion(
            question_id="validation_002",
            question_text="Have you had insurance claims in the past 5 years?",
            question_type=QuestionType.YES_NO,
            category="Validation",
            weight=0.9
        ),
        UnderwritingQuestion(
            question_id="validation_003",
            question_text="Describe any insurance claims",
            question_type=QuestionType.TEXT_INPUT,
            required=False,
            category="Validation",
            weight=0.8
        ),
        UnderwritingQuestion(
            question_id="validation_004",
            question_text="Do you have any pending legal issues?",
            question_type=QuestionType.YES_NO,
            category="Validation",
            weight=0.8
        ),
    ]
    
    @staticmethod
    def get_standard_questionnaire(questionnaire_type: str) -> List[UnderwritingQuestion]:
        """Get standard questionnaire by type"""
        if questionnaire_type == "health":
            return QuestionnaireLibrary.HEALTH_ASSESSMENT_QUESTIONS
        elif questionnaire_type == "lifestyle":
            return QuestionnaireLibrary.LIFESTYLE_QUESTIONS
        elif questionnaire_type == "validation":
            return QuestionnaireLibrary.VALIDATION_QUESTIONS
        elif questionnaire_type == "complete":
            return (
                QuestionnaireLibrary.HEALTH_ASSESSMENT_QUESTIONS +
                QuestionnaireLibrary.LIFESTYLE_QUESTIONS +
                QuestionnaireLibrary.VALIDATION_QUESTIONS
            )
        return []


# ============================================================================
# UNDERWRITING ASSISTANT AGENT
# ============================================================================

class UnderwritingAssistant:
    """Intelligent underwriting assistant agent"""
    
    def __init__(self, assistant_id: str, name: str = "UW Assistant"):
        self.assistant_id = assistant_id
        self.name = name
        self.sessions: Dict[str, UnderwritingSession] = {}
        self.notification_queue: List[NotificationDelivery] = []
        self.reports: List[Dict[str, Any]] = []
    
    def start_underwriting_session(
        self,
        customer: Customer,
        questionnaire_type: str = "complete"
    ) -> UnderwritingSession:
        """Start new underwriting session"""
        session_id = f"UW_{customer.customer_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        session = UnderwritingSession(
            session_id=session_id,
            customer_id=customer.customer_id,
            customer=customer,
            questions=QuestionnaireLibrary.get_standard_questionnaire(questionnaire_type)
        )
        
        self.sessions[session_id] = session
        return session
    
    def ask_question(self, session_id: str, question: UnderwritingQuestion) -> str:
        """Present question to customer"""
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        # Build question prompt
        prompt = f"\n{question.question_text}\n"
        
        if question.question_type == QuestionType.YES_NO:
            prompt += "Options: Yes, No"
        elif question.question_type == QuestionType.MULTIPLE_CHOICE:
            prompt += f"Options: {', '.join(question.options)}"
        elif question.question_type == QuestionType.RATING:
            prompt += "Scale: 1-10 (1=Worst, 10=Best)"
        elif question.question_type == QuestionType.NUMERIC:
            prompt += "Please enter a number"
        elif question.question_type == QuestionType.DATE:
            prompt += "Format: YYYY-MM-DD"
        else:
            prompt += "Please provide your answer"
        
        return prompt
    
    def process_answer(
        self,
        session_id: str,
        question_id: str,
        answer: Any,
        notes: str = ""
    ) -> tuple[bool, str]:
        """Process and validate customer answer"""
        if session_id not in self.sessions:
            return False, f"Session {session_id} not found"
        
        session = self.sessions[session_id]
        
        # Find question
        question = None
        for q in session.questions:
            if q.question_id == question_id:
                question = q
                break
        
        if not question:
            return False, f"Question {question_id} not found"
        
        # Validate answer
        is_valid, validation_msg = question.validate_answer(answer)
        if not is_valid:
            return False, validation_msg
        
        # Add answer to session
        uw_answer = UnderwritingAnswer(
            question_id=question_id,
            customer_id=session.customer_id,
            answer=answer,
            answer_date=datetime.now(),
            answer_type=question.question_type,
            notes=notes
        )
        
        session.add_answer(uw_answer)
        return True, f"Answer recorded for: {question.question_text}"
    
    def upload_document(
        self,
        session_id: str,
        document_type: DocumentType,
        file_name: str,
        file_size_bytes: int,
        expiry_date: Optional[date] = None
    ) -> DocumentUpload:
        """Upload identification document"""
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        
        doc_id = f"DOC_{session.customer_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        document = DocumentUpload(
            document_id=doc_id,
            customer_id=session.customer_id,
            document_type=document_type,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            upload_date=datetime.now(),
            expiry_date=expiry_date
        )
        
        session.add_document(document)
        return document
    
    def verify_document(
        self,
        session_id: str,
        document_id: str,
        verified_by: str = "System",
        notes: str = ""
    ) -> bool:
        """Verify uploaded document"""
        if session_id not in self.sessions:
            return False
        
        session = self.sessions[session_id]
        
        for doc in session.documents:
            if doc.document_id == document_id:
                return doc.verify_document(verified_by, notes)
        
        return False
    
    def calculate_risk_score(self, session: UnderwritingSession) -> float:
        """Calculate underwriting risk score (0-1.0)"""
        if not session.answers or not session.customer:
            return 0.5
        
        total_weight = 0.0
        weighted_score = 0.0
        
        # Score based on answers
        for answer in session.answers:
            question = None
            for q in session.questions:
                if q.question_id == answer.question_id:
                    question = q
                    break
            
            if not question:
                continue
            
            # Convert answer to risk score
            answer_score = self._get_answer_risk_score(answer, question)
            weighted_score += answer_score * question.weight
            total_weight += question.weight
        
        # Add health assessment factor
        health_factor = session.customer.health_assessment.health_risk_score()
        weighted_score += health_factor * 2.0
        total_weight += 2.0
        
        # Document verification factor
        verified_docs = sum(1 for d in session.documents if d.verification_status == DocumentVerificationStatus.VERIFIED)
        doc_factor = 0.1 if verified_docs > 0 else 0.5
        weighted_score += doc_factor * 1.0
        total_weight += 1.0
        
        # Calculate final score
        final_score = weighted_score / total_weight if total_weight > 0 else 0.5
        return min(final_score, 1.0)  # Cap at 1.0
    
    def _get_answer_risk_score(self, answer: UnderwritingAnswer, question: UnderwritingQuestion) -> float:
        """Convert answer to risk score (0=lowest risk, 1=highest risk)"""
        answer_str = str(answer.answer).lower()
        
        # Yes/No answers
        if answer.answer_type == QuestionType.YES_NO:
            if answer_str in ["no", "false"]:
                return 0.2
            else:
                return 0.6
        
        # Rating answers
        elif answer.answer_type == QuestionType.RATING:
            try:
                rating = int(answer.answer)
                return (11 - rating) / 10.0  # Invert: 10=best (0 risk), 1=worst (1.0 risk)
            except:
                return 0.5
        
        # Smoking status
        elif "smoking" in question.question_id.lower():
            if "non-smoker" in answer_str:
                return 0.2
            elif "former" in answer_str:
                return 0.4
            else:
                return 0.7
        
        # Default
        return 0.5
    
    def make_underwriting_decision(
        self,
        session: UnderwritingSession,
        manual_notes: str = ""
    ) -> UnderwritingDecision:
        """Make automated underwriting decision"""
        # Calculate risk score
        session.risk_score = self.calculate_risk_score(session)
        
        # Check document verification
        required_docs_verified = sum(
            1 for d in session.documents
            if d.verification_status == DocumentVerificationStatus.VERIFIED
        )
        
        # Decision logic
        if session.risk_score < 0.3 and required_docs_verified > 0:
            decision = UnderwritingDecision.APPROVED
        elif session.risk_score < 0.6 and required_docs_verified > 0:
            decision = UnderwritingDecision.APPROVED_WITH_CONDITIONS
        elif session.risk_score < 0.8:
            decision = UnderwritingDecision.PENDING_REVIEW
        else:
            decision = UnderwritingDecision.REFERRED
        
        session.decision = decision
        session.decision_notes = f"Risk Score: {session.risk_score:.2%}. {manual_notes}"
        session.is_complete = True
        session.session_end = datetime.now()
        
        return decision
    
    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get underwriting session summary"""
        if session_id not in self.sessions:
            return {}
        
        session = self.sessions[session_id]
        
        return {
            "session_id": session_id,
            "customer_id": session.customer_id,
            "customer_name": session.customer.full_name if session.customer else "Unknown",
            "session_start": session.session_start.isoformat(),
            "session_end": session.session_end.isoformat() if session.session_end else None,
            "is_complete": session.is_complete,
            "questions_total": len(session.questions),
            "questions_answered": len(session.answers),
            "documents_uploaded": len(session.documents),
            "documents_verified": sum(1 for d in session.documents if d.verification_status == DocumentVerificationStatus.VERIFIED),
            "risk_score": f"{session.risk_score:.2%}",
            "decision": session.decision.value if session.decision else None,
            "decision_notes": session.decision_notes,
            "progress": session.get_progress()
        }


# ============================================================================
# NOTIFICATION AND DELIVERY MANAGEMENT
# ============================================================================

class NotificationManager:
    """Manage notifications and multi-channel delivery"""
    
    def __init__(self):
        self.templates: Dict[str, NotificationTemplate] = {}
        self.delivery_queue: List[NotificationDelivery] = []
        self._setup_default_templates()
    
    def _setup_default_templates(self):
        """Setup default notification templates"""
        self.templates["uw_approved"] = NotificationTemplate(
            template_id="tpl_uw_approved",
            template_name="Underwriting Approved",
            delivery_method=DeliveryMethod.EMAIL,
            subject="Your Insurance Application - APPROVED",
            body="Dear {{customer_name}},\n\nCongratulations! Your insurance application has been approved.\n\nPolicy Details:\n- Policy ID: {{policy_id}}\n- Effective Date: {{effective_date}}\n\nThank you for choosing us."
        )
        
        self.templates["uw_conditions"] = NotificationTemplate(
            template_id="tpl_uw_conditions",
            template_name="Underwriting Approved with Conditions",
            delivery_method=DeliveryMethod.EMAIL,
            subject="Your Insurance Application - APPROVED WITH CONDITIONS",
            body="Dear {{customer_name}},\n\nYour application has been approved with the following conditions:\n{{conditions}}\n\nPlease review and confirm acceptance.",
            signature_required=True
        )
        
        self.templates["uw_pending"] = NotificationTemplate(
            template_id="tpl_uw_pending",
            template_name="Underwriting Pending Review",
            delivery_method=DeliveryMethod.EMAIL,
            subject="Your Insurance Application - UNDER REVIEW",
            body="Dear {{customer_name}},\n\nYour application is under review. We will contact you within 3 business days with a decision."
        )
        
        self.templates["claim_filed"] = NotificationTemplate(
            template_id="tpl_claim_filed",
            template_name="Claim Filed Confirmation",
            delivery_method=DeliveryMethod.COMBINED,
            subject="Claim {{claim_id}} - RECEIVED",
            body="Your claim {{claim_id}} has been received and assigned to adjuster {{adjuster}}.\n\nClaim Amount: {{claim_amount}}\nStatus: {{claim_status}}\n\nReference: {{reference_number}}"
        )

        # Premium allocation notification template
        self.templates["premium_allocation"] = NotificationTemplate(
            template_id="tpl_premium_allocation",
            template_name="Premium Allocation Confirmation",
            delivery_method=DeliveryMethod.EMAIL,
            subject="Premium Payment Allocation Confirmation",
            body=(
                "Dear {{customer_name}},\n\n"
                "Thank you for your premium payment for Policy {{policy_id}}. "
                "The payment has been allocated as follows:\n"
                "- Total Premium: {{total_premium}}\n"
                "- Risk Coverage: {{risk_amount}}\n"
                "- Savings Account: {{savings_amount}}\n\n"
                "You can view your full statement here: {{statement_url}}\n\n"
                "Regards,\nPHINS Insurance"
            )
        )
    
    def send_notification(
        self,
        customer_id: str,
        recipient: str,
        template_name: str,
        delivery_method: DeliveryMethod,
        context: Dict[str, Any],
        signature_required: bool = False
    ) -> NotificationDelivery:
        """Send notification via specified delivery method"""
        if template_name not in self.templates:
            raise ValueError(f"Template {template_name} not found")
        
        template = self.templates[template_name]
        content = template.generate_content(context)
        
        delivery_id = f"NOTIF_{customer_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        notification = NotificationDelivery(
            delivery_id=delivery_id,
            customer_id=customer_id,
            delivery_method=delivery_method,
            recipient=recipient,
            subject=template.subject,
            message=content,
            delivery_date=datetime.now(),
            metadata={
                "template": template_name,
                "signature_required": signature_required,
                "delivery_channel": self._get_delivery_channel(delivery_method)
            }
        )
        
        self.delivery_queue.append(notification)
        return notification
    
    def _get_delivery_channel(self, method: DeliveryMethod) -> List[str]:
        """Get actual delivery channels for method"""
        if method == DeliveryMethod.EMAIL:
            return ["email"]
        elif method == DeliveryMethod.SMS:
            return ["sms"]
        elif method == DeliveryMethod.SIGNED_DOCUMENT:
            return ["signed_document"]
        elif method == DeliveryMethod.PORTAL:
            return ["portal"]
        elif method == DeliveryMethod.COMBINED:
            return ["email", "sms", "signed_document"]
        return []
    
    def mark_as_read(self, delivery_id: str) -> bool:
        """Mark notification as read"""
        for notif in self.delivery_queue:
            if notif.delivery_id == delivery_id:
                notif.delivery_status = "Read"
                notif.read_date = datetime.now()
                return True
        return False
    
    def mark_as_signed(self, delivery_id: str, signed_by: str) -> bool:
        """Mark signed document as signed"""
        for notif in self.delivery_queue:
            if notif.delivery_id == delivery_id:
                notif.delivery_status = "Signed"
                notif.signature_date = datetime.now()
                notif.signed_by = signed_by
                return True
        return False


# ============================================================================
# REPORTING TO DIVISIONS
# ============================================================================

class DivisionalReporter:
    """Generate and send reports to different divisions"""
    
    def __init__(self):
        self.reports: List[Dict[str, Any]] = []
    
    def generate_underwriting_report(
        self,
        session: UnderwritingSession,
        assigned_underwriter: str = "System"
    ) -> Dict[str, Any]:
        """Generate comprehensive underwriting report"""
        report = {
            "report_id": f"UWR_{session.session_id}_{datetime.now().strftime('%Y%m%d')}",
            "report_type": ReportType.UNDERWRITING_REPORT.value,
            "report_date": datetime.now().isoformat(),
            "customer_id": session.customer_id,
            "customer_name": session.customer.full_name if session.customer else "Unknown",
            "session_id": session.session_id,
            "assigned_underwriter": assigned_underwriter,
            "underwriting_decision": session.decision.value if session.decision else None,
            "risk_score": session.risk_score,
            "decision_notes": session.decision_notes,
            "summary": {
                "total_questions": len(session.questions),
                "answered_questions": len(session.answers),
                "documents_uploaded": len(session.documents),
                "documents_verified": sum(1 for d in session.documents if d.verification_status == DocumentVerificationStatus.VERIFIED),
                "session_duration_minutes": int((session.session_end - session.session_start).total_seconds() / 60) if session.session_end else 0,
            },
            "customer_info": {
                "age": session.customer.age if session.customer else None,
                "health_status": session.customer.health_assessment.get_condition_description() if session.customer else None,
                "health_level": session.customer.health_assessment.condition_level if session.customer else None,
                "smoking_status": session.customer.smoking_status.value if session.customer else None,
            },
            "key_findings": self._extract_key_findings(session),
            "recommendations": self._generate_recommendations(session)
        }
        
        self.reports.append(report)
        return report
    
    def generate_risk_assessment_report(
        self,
        session: UnderwritingSession,
        assigned_risk_manager: str = "Risk Management Team"
    ) -> Dict[str, Any]:
        """Generate risk assessment report for Risk Management"""
        report = {
            "report_id": f"RISK_{session.session_id}_{datetime.now().strftime('%Y%m%d')}",
            "report_type": ReportType.RISK_ASSESSMENT.value,
            "report_date": datetime.now().isoformat(),
            "customer_id": session.customer_id,
            "customer_name": session.customer.full_name if session.customer else "Unknown",
            "assigned_to": assigned_risk_manager,
            "risk_score": session.risk_score,
            "risk_level": self._get_risk_level(session.risk_score),
            "risk_factors": self._identify_risk_factors(session),
            "mitigations": self._suggest_mitigations(session),
            "monitoring_requirements": self._get_monitoring_requirements(session),
            "exclusions": self._identify_exclusions(session),
            "conditions": self._identify_conditions(session)
        }
        
        self.reports.append(report)
        return report
    
    def generate_claims_report(
        self,
        claim_id: str,
        customer_id: str,
        claim_amount: float,
        claim_type: str,
        claim_description: str,
        assigned_adjuster: str = "Claims Department"
    ) -> Dict[str, Any]:
        """Generate claims intake report"""
        report = {
            "report_id": f"CLM_{claim_id}_{datetime.now().strftime('%Y%m%d')}",
            "report_type": ReportType.CLAIMS_REPORT.value,
            "report_date": datetime.now().isoformat(),
            "claim_id": claim_id,
            "customer_id": customer_id,
            "claim_amount": claim_amount,
            "claim_type": claim_type,
            "claim_description": claim_description,
            "assigned_adjuster": assigned_adjuster,
            "status": "Received",
            "next_steps": [
                "Document review",
                "Coverage verification",
                "Initial assessment",
                "Adjuster assignment"
            ],
            "timeline": {
                "filed_date": datetime.now().isoformat(),
                "initial_review_due": (datetime.now() + timedelta(days=3)).isoformat(),
                "decision_due": (datetime.now() + timedelta(days=10)).isoformat()
            }
        }
        
        self.reports.append(report)
        return report
    
    def generate_actuary_report(
        self,
        session: UnderwritingSession,
        assigned_actuary: str = "Actuarial Department"
    ) -> Dict[str, Any]:
        """Generate premium and reserve analysis for Actuary"""
        report = {
            "report_id": f"ACT_{session.session_id}_{datetime.now().strftime('%Y%m%d')}",
            "report_type": ReportType.ACTUARY_REPORT.value,
            "report_date": datetime.now().isoformat(),
            "customer_id": session.customer_id,
            "assigned_actuary": assigned_actuary,
            "risk_score": session.risk_score,
            "base_premium_factor": self._calculate_premium_factor(session),
            "health_adjustment": self._calculate_health_adjustment(session),
            "risk_adjustment": self._calculate_risk_adjustment(session),
            "recommended_premium": self._calculate_recommended_premium(session),
            "reserve_requirements": self._calculate_reserves(session),
            "mortality_assumptions": self._get_mortality_assumptions(session),
            "loss_projections": {
                "low_scenario": self._project_losses(session, scenario="low"),
                "medium_scenario": self._project_losses(session, scenario="medium"),
                "high_scenario": self._project_losses(session, scenario="high")
            }
        }
        
        self.reports.append(report)
        return report
    
    def _extract_key_findings(self, session: UnderwritingSession) -> List[str]:
        """Extract key findings from underwriting session"""
        findings = []
        
        if session.customer:
            findings.append(f"Customer Age: {session.customer.age}")
            findings.append(f"Health Status: {session.customer.health_assessment.get_condition_description()}")
            findings.append(f"Smoking Status: {session.customer.smoking_status.value}")
        
        findings.append(f"Risk Score: {session.risk_score:.1%}")
        findings.append(f"Documents Verified: {sum(1 for d in session.documents if d.verification_status == DocumentVerificationStatus.VERIFIED)}")
        
        return findings
    
    def _generate_recommendations(self, session: UnderwritingSession) -> List[str]:
        """Generate recommendations based on underwriting"""
        recommendations = []
        
        if session.risk_score > 0.7:
            recommendations.append("Recommend manual review by senior underwriter")
            recommendations.append("Consider additional documentation requirements")
        
        if session.customer and session.customer.health_assessment.condition_level > 6:
            recommendations.append("Request recent medical records")
            recommendations.append("Consider medical exam requirement")
        
        if session.customer and session.customer.smoking_status == SmokingStatus.SMOKER:
            recommendations.append("Apply smoker rating adjustment")
        
        return recommendations
    
    def _get_risk_level(self, risk_score: float) -> str:
        """Convert risk score to risk level"""
        if risk_score < 0.25:
            return "Very Low"
        elif risk_score < 0.50:
            return "Low"
        elif risk_score < 0.70:
            return "Medium"
        elif risk_score < 0.85:
            return "High"
        else:
            return "Very High"
    
    def _identify_risk_factors(self, session: UnderwritingSession) -> List[str]:
        """Identify key risk factors"""
        factors = []
        
        if session.customer:
            if session.customer.health_assessment.condition_level > 6:
                factors.append(f"Poor health status ({session.customer.health_assessment.condition_level}/10)")
            
            if session.customer.smoking_status == SmokingStatus.SMOKER:
                factors.append("Smoking status")
            
            if session.customer.age > 65:
                factors.append(f"Advanced age ({session.customer.age} years)")
        
        if session.risk_score > 0.6:
            factors.append("Elevated overall risk score")
        
        return factors
    
    def _suggest_mitigations(self, session: UnderwritingSession) -> List[str]:
        """Suggest risk mitigations"""
        mitigations = []
        
        if session.customer and session.customer.health_assessment.condition_level > 6:
            mitigations.append("Require annual medical review")
        
        if session.customer and session.customer.smoking_status == SmokingStatus.SMOKER:
            mitigations.append("Apply smoker surcharge")
        
        mitigations.append("Regular contact and updates")
        mitigations.append("Lower coverage limits initially with option to increase")
        
        return mitigations
    
    def _get_monitoring_requirements(self, session: UnderwritingSession) -> List[str]:
        """Get ongoing monitoring requirements"""
        return [
            "Quarterly health status updates",
            "Annual document verification",
            "Claims history monitoring",
            "Annual premium review"
        ]
    
    def _identify_exclusions(self, session: UnderwritingSession) -> List[str]:
        """Identify recommended exclusions"""
        exclusions = []
        
        if session.customer and session.customer.health_assessment.condition_level > 8:
            exclusions.append("Pre-existing condition exclusion period (12 months)")
        
        return exclusions
    
    def _identify_conditions(self, session: UnderwritingSession) -> List[str]:
        """Identify approval conditions"""
        conditions = []
        
        if session.customer and session.customer.health_assessment.condition_level > 6:
            conditions.append("Medical exam required within 30 days")
        
        if not any(d.verification_status == DocumentVerificationStatus.VERIFIED for d in session.documents):
            conditions.append("Valid ID documentation required")
        
        return conditions
    
    def _calculate_premium_factor(self, session: UnderwritingSession) -> float:
        """Calculate base premium adjustment factor"""
        base_factor = 1.0
        if session.customer and session.customer.age > 60:
            base_factor *= 1.2
        return base_factor
    
    def _calculate_health_adjustment(self, session: UnderwritingSession) -> float:
        """Calculate health-based premium adjustment"""
        if not session.customer:
            return 1.0
        
        health_level = session.customer.health_assessment.condition_level
        if health_level <= 3:
            return 0.9  # 10% discount
        elif health_level <= 5:
            return 1.0  # No adjustment
        elif health_level <= 7:
            return 1.25  # 25% surcharge
        else:
            return 1.5  # 50% surcharge
    
    def _calculate_risk_adjustment(self, session: UnderwritingSession) -> float:
        """Calculate risk-based premium adjustment"""
        if session.risk_score < 0.3:
            return 0.95
        elif session.risk_score < 0.6:
            return 1.0
        elif session.risk_score < 0.8:
            return 1.15
        else:
            return 1.3
    
    def _calculate_recommended_premium(self, session: UnderwritingSession) -> float:
        """Calculate recommended annual premium"""
        base_premium = 1000.0  # Base example
        health_adj = self._calculate_health_adjustment(session)
        risk_adj = self._calculate_risk_adjustment(session)
        premium_factor = self._calculate_premium_factor(session)
        
        return base_premium * health_adj * risk_adj * premium_factor
    
    def _calculate_reserves(self, session: UnderwritingSession) -> Dict[str, float]:
        """Calculate reserve requirements"""
        recommended_premium = self._calculate_recommended_premium(session)
        
        return {
            "loss_reserve": recommended_premium * 0.6,
            "expense_reserve": recommended_premium * 0.2,
            "contingency_reserve": recommended_premium * 0.1,
            "total_reserves": recommended_premium * 0.9
        }
    
    def _get_mortality_assumptions(self, session: UnderwritingSession) -> Dict[str, Any]:
        """Get mortality and assumption data"""
        base_rate = 0.001
        
        if session.customer:
            if session.customer.age > 60:
                base_rate *= 2.0
            if session.customer.health_assessment.condition_level > 6:
                base_rate *= 1.5
        
        return {
            "base_mortality_rate": base_rate,
            "morbidity_assumptions": "Industry standard",
            "lapse_rate": 0.05,
            "interest_assumption": 0.03
        }
    
    def _project_losses(self, session: UnderwritingSession, scenario: str = "medium") -> Dict[str, float]:
        """Project losses under different scenarios"""
        annual_premium = self._calculate_recommended_premium(session)
        
        if scenario == "low":
            loss_ratio = 0.4
        elif scenario == "high":
            loss_ratio = 0.8
        else:
            loss_ratio = 0.6
        
        return {
            "year_1": annual_premium * loss_ratio,
            "year_2": annual_premium * loss_ratio * 1.05,
            "year_3": annual_premium * loss_ratio * 1.1,
            "total_3_years": annual_premium * loss_ratio * 3.15
        }
