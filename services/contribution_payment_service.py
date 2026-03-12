"""
PHINS Contribution Payment Service
==================================
Comprehensive payment processing for foundation contributions.

Features:
- Credit card payment processing with validation
- Bank transfer handling
- Wallet transactions
- Payment verification and security
- Transaction logging
- Dashboard integration (admin, accounting)
- Large document upload support
- AI assessment for contribution analysis

Pipeline:
  Payment → Validation → Processing → Ledger → Dashboards → AI Analysis
"""

import json
import hashlib
import re
import logging
import os
import uuid
import base64
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum

logger = logging.getLogger('phins.contribution_payment')


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class PaymentMethod(str, Enum):
    """Supported payment methods"""
    WALLET = "wallet"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    ACH = "ach"
    WIRE = "wire"
    CRYPTO = "crypto"


class PaymentStatus(str, Enum):
    """Payment processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class CardBrand(str, Enum):
    """Credit card brands"""
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    UNKNOWN = "unknown"


# Maximum upload size (500MB in bytes)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB

# Supported document types
SUPPORTED_DOCUMENT_TYPES = [
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/gif',
    'video/mp4',
    'video/quicktime',
    'video/webm',
    'video/avi',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
    'audio/mpeg',
    'audio/wav',
    'audio/mp3'
]


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CreditCardInfo:
    """Credit card information for processing"""
    card_number_last4: str
    brand: str
    exp_month: int
    exp_year: int
    cardholder_name: str
    billing_zip: str = ""
    token: str = ""  # Tokenized card for security
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PaymentTransaction:
    """Payment transaction record"""
    id: str
    customer_id: str
    foundation_id: str
    foundation_name: str
    fund_id: str
    fund_name: str
    amount: float
    currency: str = "USD"
    payment_method: str = "credit_card"
    payment_status: str = "pending"
    
    # Card details (if applicable)
    card_last4: str = ""
    card_brand: str = ""
    card_exp: str = ""
    
    # Processing details
    processor_reference: str = ""
    authorization_code: str = ""
    settlement_date: str = ""
    
    # Timestamps
    created_at: str = ""
    processed_at: str = ""
    completed_at: str = ""
    
    # Fees and adjustments
    processing_fee: float = 0.0
    net_amount: float = 0.0
    
    # Documents attached
    documents: List[Dict] = field(default_factory=list)
    
    # AI assessment
    ai_assessment: Dict = field(default_factory=dict)
    
    # Error info
    error_code: str = ""
    error_message: str = ""
    
    # Ledger hash for integrity
    ledger_hash: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ContributionDocument:
    """Document attached to a contribution"""
    id: str
    contribution_id: str
    file_name: str
    file_type: str  # MIME type
    file_size: int  # bytes
    file_path: str  # Storage path
    description: str = ""
    uploaded_at: str = ""
    uploaded_by: str = ""
    checksum: str = ""  # MD5/SHA256 for integrity
    ai_analysis: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# PAYMENT VALIDATION
# ============================================================================

class PaymentValidator:
    """Validates payment information"""
    
    @staticmethod
    def validate_credit_card(card_number: str) -> Tuple[bool, str, str]:
        """
        Validate credit card number using Luhn algorithm and detect brand.
        
        Returns: (is_valid, brand, error_message)
        """
        # Remove spaces and dashes
        card_number = re.sub(r'[\s-]', '', card_number)
        
        # Check if numeric
        if not card_number.isdigit():
            return False, "", "Card number must contain only digits"
        
        # Check length
        if len(card_number) < 13 or len(card_number) > 19:
            return False, "", "Invalid card number length"
        
        # Detect brand
        brand = PaymentValidator._detect_card_brand(card_number)
        
        # Luhn algorithm check
        if not PaymentValidator._luhn_check(card_number):
            return False, brand, "Invalid card number (checksum failed)"
        
        return True, brand, ""
    
    @staticmethod
    def _detect_card_brand(card_number: str) -> str:
        """Detect credit card brand from number"""
        if card_number.startswith('4'):
            return CardBrand.VISA.value
        elif card_number.startswith(('51', '52', '53', '54', '55')) or \
             (2221 <= int(card_number[:4]) <= 2720 if len(card_number) >= 4 else False):
            return CardBrand.MASTERCARD.value
        elif card_number.startswith(('34', '37')):
            return CardBrand.AMEX.value
        elif card_number.startswith(('6011', '644', '645', '646', '647', '648', '649', '65')):
            return CardBrand.DISCOVER.value
        return CardBrand.UNKNOWN.value
    
    @staticmethod
    def _luhn_check(card_number: str) -> bool:
        """Verify card number using Luhn algorithm"""
        digits = [int(d) for d in card_number]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        
        total = sum(odd_digits)
        for d in even_digits:
            d *= 2
            if d > 9:
                d -= 9
            total += d
        
        return total % 10 == 0
    
    @staticmethod
    def validate_expiry(exp_month: int, exp_year: int) -> Tuple[bool, str]:
        """Validate card expiry date"""
        now = datetime.now()
        
        if exp_month < 1 or exp_month > 12:
            return False, "Invalid expiry month"
        
        # Handle 2-digit year
        if exp_year < 100:
            exp_year += 2000
        
        if exp_year < now.year:
            return False, "Card has expired"
        
        if exp_year == now.year and exp_month < now.month:
            return False, "Card has expired"
        
        return True, ""
    
    @staticmethod
    def validate_cvv(cvv: str, brand: str) -> Tuple[bool, str]:
        """Validate CVV/CVC"""
        if not cvv.isdigit():
            return False, "CVV must contain only digits"
        
        if brand == CardBrand.AMEX.value:
            if len(cvv) != 4:
                return False, "AMEX CVV must be 4 digits"
        else:
            if len(cvv) != 3:
                return False, "CVV must be 3 digits"
        
        return True, ""
    
    @staticmethod
    def validate_amount(amount: float, min_amount: float = 1.0, max_amount: float = 1000000.0) -> Tuple[bool, str]:
        """Validate payment amount"""
        if amount <= 0:
            return False, "Amount must be positive"
        if amount < min_amount:
            return False, f"Minimum amount is ${min_amount}"
        if amount > max_amount:
            return False, f"Maximum amount is ${max_amount:,.2f}"
        return True, ""


# ============================================================================
# DOCUMENT HANDLER
# ============================================================================

class DocumentUploadHandler:
    """Handles large document uploads for contributions"""
    
    def __init__(self, upload_dir: str = None):
        if upload_dir is None:
            upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'contributions')
        self.upload_dir = upload_dir
        try:
            os.makedirs(upload_dir, exist_ok=True)
        except PermissionError:
            import tempfile
            self.upload_dir = os.path.join(tempfile.gettempdir(), 'phins_uploads', 'contributions')
            os.makedirs(self.upload_dir, exist_ok=True)
    
    def validate_file(self, file_name: str, file_size: int, file_type: str) -> Tuple[bool, str]:
        """Validate file before upload"""
        # Check size
        if file_size > MAX_UPLOAD_SIZE:
            return False, f"File too large. Maximum size is {MAX_UPLOAD_SIZE / (1024*1024):.0f}MB"
        
        if file_size <= 0:
            return False, "File is empty"
        
        # Check type
        if file_type not in SUPPORTED_DOCUMENT_TYPES:
            return False, f"Unsupported file type: {file_type}"
        
        # Check name
        if not file_name or len(file_name) > 255:
            return False, "Invalid file name"
        
        # Check for dangerous extensions
        dangerous_extensions = ['.exe', '.bat', '.cmd', '.sh', '.ps1', '.vbs', '.js']
        if any(file_name.lower().endswith(ext) for ext in dangerous_extensions):
            return False, "File type not allowed for security reasons"
        
        return True, ""
    
    def process_upload(
        self,
        contribution_id: str,
        file_name: str,
        file_data: bytes,
        file_type: str,
        uploaded_by: str,
        description: str = ""
    ) -> Optional[ContributionDocument]:
        """
        Process and store an uploaded document.
        
        Args:
            contribution_id: ID of the contribution
            file_name: Original file name
            file_data: File content as bytes
            file_type: MIME type
            uploaded_by: User ID who uploaded
            description: Optional description
            
        Returns:
            ContributionDocument or None if failed
        """
        file_size = len(file_data)
        
        # Validate
        valid, error = self.validate_file(file_name, file_size, file_type)
        if not valid:
            logger.error(f"File validation failed: {error}")
            return None
        
        # Generate unique ID and path
        doc_id = f"DOC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        
        # Create subdirectory for contribution
        contrib_dir = os.path.join(self.upload_dir, contribution_id)
        os.makedirs(contrib_dir, exist_ok=True)
        
        # Sanitize filename
        safe_name = re.sub(r'[^\w\-_\.]', '_', file_name)
        file_path = os.path.join(contrib_dir, f"{doc_id}_{safe_name}")
        
        try:
            # Write file
            with open(file_path, 'wb') as f:
                f.write(file_data)
            
            # Calculate checksum
            checksum = hashlib.sha256(file_data).hexdigest()
            
            # Create document record
            document = ContributionDocument(
                id=doc_id,
                contribution_id=contribution_id,
                file_name=file_name,
                file_type=file_type,
                file_size=file_size,
                file_path=file_path,
                description=description,
                uploaded_at=datetime.now(timezone.utc).isoformat(),
                uploaded_by=uploaded_by,
                checksum=checksum
            )
            
            logger.info(f"Document uploaded: {doc_id} ({file_size / (1024*1024):.2f}MB)")
            return document
            
        except Exception as e:
            logger.error(f"Failed to save document: {e}")
            return None
    
    def process_base64_upload(
        self,
        contribution_id: str,
        file_name: str,
        file_data_base64: str,
        file_type: str,
        uploaded_by: str,
        description: str = ""
    ) -> Optional[ContributionDocument]:
        """Process a base64-encoded file upload"""
        try:
            file_data = base64.b64decode(file_data_base64)
            return self.process_upload(
                contribution_id=contribution_id,
                file_name=file_name,
                file_data=file_data,
                file_type=file_type,
                uploaded_by=uploaded_by,
                description=description
            )
        except Exception as e:
            logger.error(f"Failed to decode base64 file: {e}")
            return None
    
    def get_document(self, doc_id: str, contribution_id: str) -> Optional[bytes]:
        """Retrieve a document's contents"""
        contrib_dir = os.path.join(self.upload_dir, contribution_id)
        
        # Find the file
        if not os.path.exists(contrib_dir):
            return None
        
        for filename in os.listdir(contrib_dir):
            if filename.startswith(doc_id):
                file_path = os.path.join(contrib_dir, filename)
                with open(file_path, 'rb') as f:
                    return f.read()
        
        return None


# ============================================================================
# AI ASSESSMENT SERVICE
# ============================================================================

class ContributionAIAssessment:
    """
    AI-powered assessment for contributions.
    
    Provides:
    - Contribution pattern analysis
    - Risk assessment
    - Recommendations
    - Summary generation
    - Anomaly detection
    """
    
    def __init__(self):
        self.assessment_history: Dict[str, Dict] = {}
    
    def analyze_contribution(
        self,
        contribution: PaymentTransaction,
        member_history: List[Dict],
        foundation_stats: Dict
    ) -> Dict[str, Any]:
        """
        Analyze a contribution and provide AI assessment.
        
        Args:
            contribution: The contribution being made
            member_history: Past contributions by this member
            foundation_stats: Foundation financial statistics
            
        Returns:
            AI assessment with insights and recommendations
        """
        now = datetime.now(timezone.utc)
        
        # Calculate metrics
        total_historical = sum(h.get('amount', 0) for h in member_history)
        avg_contribution = total_historical / len(member_history) if member_history else 0
        contribution_count = len(member_history)
        
        # Analyze patterns
        is_first_contribution = contribution_count == 0
        is_above_average = contribution.amount > avg_contribution * 1.2 if avg_contribution > 0 else False
        is_below_average = contribution.amount < avg_contribution * 0.8 if avg_contribution > 0 else False
        is_large_contribution = contribution.amount > 1000
        
        # Calculate contribution frequency (if history exists)
        frequency_days = 0
        if len(member_history) >= 2:
            dates = sorted([
                datetime.fromisoformat(h['created_at'].replace('Z', '+00:00'))
                for h in member_history if h.get('created_at')
            ])
            if len(dates) >= 2:
                total_days = (dates[-1] - dates[0]).days
                frequency_days = total_days / (len(dates) - 1) if len(dates) > 1 else 0
        
        # Foundation health check
        fund_balance = foundation_stats.get('total_fund_balance', 0)
        member_count = foundation_stats.get('current_members', 1)
        balance_per_member = fund_balance / member_count if member_count > 0 else 0
        
        # Risk assessment
        risk_level = "low"
        risk_factors = []
        
        if is_first_contribution and contribution.amount > 5000:
            risk_level = "medium"
            risk_factors.append("Large first-time contribution")
        
        if contribution.amount > 10000:
            risk_level = "medium"
            risk_factors.append("High-value transaction")
        
        if is_above_average and contribution.amount > avg_contribution * 3:
            risk_factors.append("Significantly above historical average")
        
        # Generate recommendations
        recommendations = []
        
        if is_first_contribution:
            recommendations.append("Welcome to the foundation! Consider setting up recurring contributions for consistent fund growth.")
        
        if balance_per_member < 500:
            recommendations.append("The foundation's per-member balance is below optimal. Regular contributions help build a stronger safety net.")
        
        if frequency_days > 45 and contribution_count > 2:
            recommendations.append("Your contribution frequency has decreased. Consider maintaining regular monthly contributions.")
        
        if is_large_contribution:
            recommendations.append("Thank you for this significant contribution! This will meaningfully impact the foundation's capabilities.")
        
        # Generate summary
        summary = self._generate_summary(
            contribution=contribution,
            is_first=is_first_contribution,
            total_historical=total_historical,
            avg_contribution=avg_contribution,
            foundation_name=contribution.foundation_name
        )
        
        # Financial advice
        advice = self._generate_advice(
            contribution=contribution,
            member_history=member_history,
            foundation_stats=foundation_stats
        )
        
        assessment = {
            'assessment_id': f"AI-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
            'contribution_id': contribution.id,
            'generated_at': now.isoformat(),
            
            # Metrics
            'metrics': {
                'contribution_amount': contribution.amount,
                'historical_total': total_historical,
                'average_contribution': round(avg_contribution, 2),
                'contribution_count': contribution_count,
                'frequency_days': round(frequency_days, 1) if frequency_days else None,
                'is_first_contribution': is_first_contribution,
                'is_above_average': is_above_average,
                'is_below_average': is_below_average
            },
            
            # Risk assessment
            'risk_assessment': {
                'level': risk_level,
                'factors': risk_factors,
                'score': self._calculate_risk_score(risk_factors)
            },
            
            # Insights
            'insights': {
                'pattern': 'regular' if frequency_days and 25 <= frequency_days <= 35 else 'irregular' if frequency_days else 'new',
                'engagement_level': 'high' if contribution_count > 10 else 'medium' if contribution_count > 3 else 'new',
                'contribution_trend': 'increasing' if is_above_average else 'decreasing' if is_below_average else 'stable'
            },
            
            # Recommendations and advice
            'recommendations': recommendations,
            'advice': advice,
            
            # Summary
            'summary': summary,
            
            # Confidence score
            'confidence': 0.85 if contribution_count > 5 else 0.70 if contribution_count > 0 else 0.60
        }
        
        # Store assessment
        self.assessment_history[contribution.id] = assessment
        
        return assessment
    
    def _generate_summary(
        self,
        contribution: PaymentTransaction,
        is_first: bool,
        total_historical: float,
        avg_contribution: float,
        foundation_name: str
    ) -> str:
        """Generate a human-readable summary"""
        if is_first:
            return (
                f"This is your first contribution to {foundation_name}. "
                f"Your ${contribution.amount:,.2f} contribution establishes your membership "
                f"and begins building your contribution history with the community."
            )
        
        new_total = total_historical + contribution.amount
        return (
            f"Your ${contribution.amount:,.2f} contribution to {foundation_name} "
            f"brings your total contributions to ${new_total:,.2f}. "
            f"Your historical average is ${avg_contribution:,.2f}. "
            f"{'This contribution is above your typical amount, showing increased engagement.' if contribution.amount > avg_contribution else 'This maintains your consistent contribution pattern.'}"
        )
    
    def _generate_advice(
        self,
        contribution: PaymentTransaction,
        member_history: List[Dict],
        foundation_stats: Dict
    ) -> List[Dict]:
        """Generate financial advice based on contribution patterns"""
        advice = []
        
        # Tax deduction advice
        total = sum(h.get('amount', 0) for h in member_history) + contribution.amount
        if total > 250:
            advice.append({
                'type': 'tax',
                'title': 'Tax Deduction Reminder',
                'content': f'Your total contributions of ${total:,.2f} may qualify for tax deductions. Keep records of all foundation contributions for tax purposes.',
                'priority': 'medium'
            })
        
        # Savings optimization
        if contribution.amount >= 500:
            advice.append({
                'type': 'optimization',
                'title': 'Contribution Optimization',
                'content': 'Consider splitting large contributions into monthly payments to better manage cash flow while maintaining consistent support.',
                'priority': 'low'
            })
        
        # Community growth
        member_count = foundation_stats.get('current_members', 1)
        if member_count < 10:
            advice.append({
                'type': 'community',
                'title': 'Community Growth',
                'content': 'Your foundation is still growing. Inviting more members can reduce individual contribution burden while strengthening the collective safety net.',
                'priority': 'medium'
            })
        
        # Diversification
        advice.append({
            'type': 'diversification',
            'title': 'Risk Diversification',
            'content': 'Consider contributing to multiple foundation funds (emergency, healthcare, education) to build comprehensive coverage.',
            'priority': 'low'
        })
        
        return advice
    
    def _calculate_risk_score(self, risk_factors: List[str]) -> int:
        """Calculate numeric risk score (0-100)"""
        base_score = 10
        factor_weights = {
            "Large first-time contribution": 25,
            "High-value transaction": 20,
            "Significantly above historical average": 15
        }
        
        for factor in risk_factors:
            base_score += factor_weights.get(factor, 10)
        
        return min(100, base_score)
    
    def analyze_documents(
        self,
        documents: List[ContributionDocument]
    ) -> Dict[str, Any]:
        """
        Analyze uploaded documents for the contribution.
        
        Returns analysis and recommendations.
        """
        now = datetime.now(timezone.utc)
        
        total_size = sum(doc.file_size for doc in documents)
        doc_types = [doc.file_type for doc in documents]
        
        # Categorize documents
        has_images = any('image' in t for t in doc_types)
        has_videos = any('video' in t for t in doc_types)
        has_pdfs = any('pdf' in t for t in doc_types)
        has_audio = any('audio' in t for t in doc_types)
        
        analysis = {
            'analysis_id': f"DOC-AI-{now.strftime('%Y%m%d%H%M%S')}",
            'generated_at': now.isoformat(),
            'document_count': len(documents),
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            
            'document_types': {
                'images': has_images,
                'videos': has_videos,
                'pdfs': has_pdfs,
                'audio': has_audio
            },
            
            'recommendations': [],
            'completeness_score': 0
        }
        
        # Generate recommendations based on document types
        if has_videos:
            analysis['recommendations'].append({
                'type': 'video_processing',
                'content': 'Video content detected. Processing may take additional time for analysis.'
            })
        
        if not has_pdfs and total_size > 10 * 1024 * 1024:  # >10MB
            analysis['recommendations'].append({
                'type': 'format',
                'content': 'Consider compressing large files or converting to PDF for easier archival.'
            })
        
        # Calculate completeness (basic heuristic)
        completeness = 50  # Base score
        if has_images:
            completeness += 15
        if has_pdfs:
            completeness += 20
        if len(documents) >= 2:
            completeness += 15
        
        analysis['completeness_score'] = min(100, completeness)
        
        return analysis


# ============================================================================
# MAIN PAYMENT SERVICE
# ============================================================================

class ContributionPaymentService:
    """
    Main service for processing contribution payments.
    
    Handles:
    - Payment validation and processing
    - Document uploads
    - AI assessment
    - Ledger recording
    - Dashboard integration
    """
    
    def __init__(
        self,
        ledger: Dict = None,
        admin_dashboard: Dict = None,
        accounting_dashboard: Dict = None
    ):
        self.validator = PaymentValidator()
        self.document_handler = DocumentUploadHandler()
        self.ai_assessment = ContributionAIAssessment()
        
        # Data stores
        self.transactions: Dict[str, Dict] = {}
        self.ledger = ledger if ledger is not None else {}
        self.admin_dashboard = admin_dashboard if admin_dashboard is not None else {}
        self.accounting_dashboard = accounting_dashboard if accounting_dashboard is not None else {}
        
        # Processing fee configuration
        self.fee_rates = {
            PaymentMethod.CREDIT_CARD.value: 0.029,  # 2.9%
            PaymentMethod.DEBIT_CARD.value: 0.015,   # 1.5%
            PaymentMethod.BANK_TRANSFER.value: 0.005,  # 0.5%
            PaymentMethod.ACH.value: 0.005,
            PaymentMethod.WALLET.value: 0.0,  # No fee for wallet
            PaymentMethod.WIRE.value: 0.01
        }
        
        self.flat_fees = {
            PaymentMethod.CREDIT_CARD.value: 0.30,
            PaymentMethod.DEBIT_CARD.value: 0.22,
            PaymentMethod.BANK_TRANSFER.value: 0.0,
            PaymentMethod.ACH.value: 0.25,
            PaymentMethod.WALLET.value: 0.0,
            PaymentMethod.WIRE.value: 15.00
        }
        
        logger.info("ContributionPaymentService initialized")
    
    def process_credit_card_payment(
        self,
        customer_id: str,
        foundation_id: str,
        foundation_name: str,
        fund_id: str,
        fund_name: str,
        amount: float,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        cardholder_name: str,
        billing_zip: str = "",
        notes: str = "",
        documents: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process a credit card payment for a foundation contribution.
        
        This method:
        1. Validates card information
        2. Validates amount
        3. Processes payment (simulated)
        4. Creates transaction record
        5. Records to ledger
        6. Updates dashboards
        7. Runs AI assessment
        8. Handles document uploads
        
        Returns:
            Processing result with transaction details
        """
        now = datetime.now(timezone.utc)
        transaction_id = f"TX-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        
        # Step 1: Validate card
        card_valid, brand, card_error = self.validator.validate_credit_card(card_number)
        if not card_valid:
            return {
                "success": False,
                "error_code": "INVALID_CARD",
                "error": card_error,
                "transaction_id": transaction_id
            }
        
        # Step 2: Validate expiry
        exp_valid, exp_error = self.validator.validate_expiry(exp_month, exp_year)
        if not exp_valid:
            return {
                "success": False,
                "error_code": "INVALID_EXPIRY",
                "error": exp_error,
                "transaction_id": transaction_id
            }
        
        # Step 3: Validate CVV
        cvv_valid, cvv_error = self.validator.validate_cvv(cvv, brand)
        if not cvv_valid:
            return {
                "success": False,
                "error_code": "INVALID_CVV",
                "error": cvv_error,
                "transaction_id": transaction_id
            }
        
        # Step 4: Validate amount
        amount_valid, amount_error = self.validator.validate_amount(amount)
        if not amount_valid:
            return {
                "success": False,
                "error_code": "INVALID_AMOUNT",
                "error": amount_error,
                "transaction_id": transaction_id
            }
        
        # Step 5: Calculate fees
        processing_fee = self._calculate_fee(amount, PaymentMethod.CREDIT_CARD.value)
        net_amount = amount - processing_fee
        
        # Step 6: Process payment (simulated - in production, integrate with Stripe/etc.)
        auth_code = self._simulate_payment_processing(amount, brand)
        
        # Step 7: Create transaction record
        transaction = PaymentTransaction(
            id=transaction_id,
            customer_id=customer_id,
            foundation_id=foundation_id,
            foundation_name=foundation_name,
            fund_id=fund_id,
            fund_name=fund_name,
            amount=amount,
            currency="USD",
            payment_method=PaymentMethod.CREDIT_CARD.value,
            payment_status=PaymentStatus.COMPLETED.value,
            card_last4=card_number[-4:],
            card_brand=brand,
            card_exp=f"{exp_month:02d}/{exp_year % 100:02d}",
            processor_reference=f"PROC-{uuid.uuid4().hex[:12].upper()}",
            authorization_code=auth_code,
            created_at=now.isoformat(),
            processed_at=now.isoformat(),
            completed_at=now.isoformat(),
            processing_fee=processing_fee,
            net_amount=net_amount
        )
        
        # Step 8: Handle document uploads
        uploaded_docs = []
        if documents:
            for doc_data in documents:
                doc = self.document_handler.process_base64_upload(
                    contribution_id=transaction_id,
                    file_name=doc_data.get('file_name', 'document'),
                    file_data_base64=doc_data.get('data', ''),
                    file_type=doc_data.get('file_type', 'application/octet-stream'),
                    uploaded_by=customer_id,
                    description=doc_data.get('description', '')
                )
                if doc:
                    uploaded_docs.append(doc.to_dict())
                    transaction.documents.append(doc.to_dict())
        
        # Step 9: Generate ledger hash
        transaction.ledger_hash = self._generate_ledger_hash(transaction)
        
        # Step 10: Store transaction
        self.transactions[transaction_id] = transaction.to_dict()
        
        # Step 11: Record to ledger
        self._record_to_ledger(transaction)
        
        # Step 12: Update dashboards
        self._update_admin_dashboard(transaction)
        self._update_accounting_dashboard(transaction)
        
        # Step 13: Run AI assessment
        member_history = self._get_member_history(customer_id, foundation_id)
        foundation_stats = self._get_foundation_stats(foundation_id)
        ai_assessment = self.ai_assessment.analyze_contribution(
            contribution=transaction,
            member_history=member_history,
            foundation_stats=foundation_stats
        )
        transaction.ai_assessment = ai_assessment
        
        # Update stored transaction with AI assessment
        self.transactions[transaction_id] = transaction.to_dict()
        
        logger.info(f"Credit card payment processed: {transaction_id} - ${amount} ({brand})")
        
        return {
            "success": True,
            "transaction_id": transaction_id,
            "amount": amount,
            "processing_fee": processing_fee,
            "net_amount": net_amount,
            "payment_method": PaymentMethod.CREDIT_CARD.value,
            "card_brand": brand,
            "card_last4": card_number[-4:],
            "authorization_code": auth_code,
            "status": PaymentStatus.COMPLETED.value,
            "ledger_hash": transaction.ledger_hash,
            "recorded_to_ledger": True,
            "ai_assessment": ai_assessment,
            "documents_uploaded": len(uploaded_docs),
            "timestamp": now.isoformat()
        }
    
    def process_wallet_payment(
        self,
        customer_id: str,
        foundation_id: str,
        foundation_name: str,
        fund_id: str,
        fund_name: str,
        amount: float,
        wallet_balance: float,
        notes: str = "",
        documents: List[Dict] = None
    ) -> Dict[str, Any]:
        """Process a wallet payment for contribution"""
        now = datetime.now(timezone.utc)
        transaction_id = f"TX-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        
        # Validate amount
        amount_valid, amount_error = self.validator.validate_amount(amount)
        if not amount_valid:
            return {
                "success": False,
                "error_code": "INVALID_AMOUNT",
                "error": amount_error,
                "transaction_id": transaction_id
            }
        
        # Check wallet balance
        if wallet_balance < amount:
            return {
                "success": False,
                "error_code": "INSUFFICIENT_BALANCE",
                "error": f"Insufficient wallet balance. Available: ${wallet_balance:.2f}, Required: ${amount:.2f}",
                "transaction_id": transaction_id
            }
        
        # Create transaction
        transaction = PaymentTransaction(
            id=transaction_id,
            customer_id=customer_id,
            foundation_id=foundation_id,
            foundation_name=foundation_name,
            fund_id=fund_id,
            fund_name=fund_name,
            amount=amount,
            currency="USD",
            payment_method=PaymentMethod.WALLET.value,
            payment_status=PaymentStatus.COMPLETED.value,
            created_at=now.isoformat(),
            processed_at=now.isoformat(),
            completed_at=now.isoformat(),
            processing_fee=0,
            net_amount=amount
        )
        
        # Handle document uploads
        uploaded_docs = []
        if documents:
            for doc_data in documents:
                doc = self.document_handler.process_base64_upload(
                    contribution_id=transaction_id,
                    file_name=doc_data.get('file_name', 'document'),
                    file_data_base64=doc_data.get('data', ''),
                    file_type=doc_data.get('file_type', 'application/octet-stream'),
                    uploaded_by=customer_id,
                    description=doc_data.get('description', '')
                )
                if doc:
                    uploaded_docs.append(doc.to_dict())
                    transaction.documents.append(doc.to_dict())
        
        # Generate ledger hash
        transaction.ledger_hash = self._generate_ledger_hash(transaction)
        
        # Store and record
        self.transactions[transaction_id] = transaction.to_dict()
        self._record_to_ledger(transaction)
        self._update_admin_dashboard(transaction)
        self._update_accounting_dashboard(transaction)
        
        # AI assessment
        member_history = self._get_member_history(customer_id, foundation_id)
        foundation_stats = self._get_foundation_stats(foundation_id)
        ai_assessment = self.ai_assessment.analyze_contribution(
            contribution=transaction,
            member_history=member_history,
            foundation_stats=foundation_stats
        )
        transaction.ai_assessment = ai_assessment
        self.transactions[transaction_id] = transaction.to_dict()
        
        logger.info(f"Wallet payment processed: {transaction_id} - ${amount}")
        
        return {
            "success": True,
            "transaction_id": transaction_id,
            "amount": amount,
            "processing_fee": 0,
            "net_amount": amount,
            "payment_method": PaymentMethod.WALLET.value,
            "status": PaymentStatus.COMPLETED.value,
            "ledger_hash": transaction.ledger_hash,
            "recorded_to_ledger": True,
            "ai_assessment": ai_assessment,
            "documents_uploaded": len(uploaded_docs),
            "timestamp": now.isoformat()
        }
    
    def process_bank_transfer(
        self,
        customer_id: str,
        foundation_id: str,
        foundation_name: str,
        fund_id: str,
        fund_name: str,
        amount: float,
        bank_name: str = "",
        account_last4: str = "",
        routing_number: str = "",
        notes: str = "",
        documents: List[Dict] = None
    ) -> Dict[str, Any]:
        """Process a bank transfer payment"""
        now = datetime.now(timezone.utc)
        transaction_id = f"TX-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        
        # Validate amount
        amount_valid, amount_error = self.validator.validate_amount(amount)
        if not amount_valid:
            return {
                "success": False,
                "error_code": "INVALID_AMOUNT",
                "error": amount_error,
                "transaction_id": transaction_id
            }
        
        # Calculate fees
        processing_fee = self._calculate_fee(amount, PaymentMethod.BANK_TRANSFER.value)
        net_amount = amount - processing_fee
        
        # Create transaction (bank transfers are pending until cleared)
        transaction = PaymentTransaction(
            id=transaction_id,
            customer_id=customer_id,
            foundation_id=foundation_id,
            foundation_name=foundation_name,
            fund_id=fund_id,
            fund_name=fund_name,
            amount=amount,
            currency="USD",
            payment_method=PaymentMethod.BANK_TRANSFER.value,
            payment_status=PaymentStatus.PROCESSING.value,  # Bank transfers take time
            processor_reference=f"ACH-{uuid.uuid4().hex[:12].upper()}",
            created_at=now.isoformat(),
            processed_at=now.isoformat(),
            processing_fee=processing_fee,
            net_amount=net_amount
        )
        
        # Handle documents
        uploaded_docs = []
        if documents:
            for doc_data in documents:
                doc = self.document_handler.process_base64_upload(
                    contribution_id=transaction_id,
                    file_name=doc_data.get('file_name', 'document'),
                    file_data_base64=doc_data.get('data', ''),
                    file_type=doc_data.get('file_type', 'application/octet-stream'),
                    uploaded_by=customer_id,
                    description=doc_data.get('description', '')
                )
                if doc:
                    uploaded_docs.append(doc.to_dict())
                    transaction.documents.append(doc.to_dict())
        
        # Generate ledger hash
        transaction.ledger_hash = self._generate_ledger_hash(transaction)
        
        # Store and record
        self.transactions[transaction_id] = transaction.to_dict()
        self._record_to_ledger(transaction)
        self._update_admin_dashboard(transaction)
        self._update_accounting_dashboard(transaction)
        
        logger.info(f"Bank transfer initiated: {transaction_id} - ${amount}")
        
        return {
            "success": True,
            "transaction_id": transaction_id,
            "amount": amount,
            "processing_fee": processing_fee,
            "net_amount": net_amount,
            "payment_method": PaymentMethod.BANK_TRANSFER.value,
            "status": PaymentStatus.PROCESSING.value,
            "expected_settlement": (now + timedelta(days=3)).strftime('%Y-%m-%d'),
            "ledger_hash": transaction.ledger_hash,
            "recorded_to_ledger": True,
            "documents_uploaded": len(uploaded_docs),
            "timestamp": now.isoformat(),
            "message": "Bank transfer initiated. Funds will be available in 2-3 business days."
        }
    
    def _calculate_fee(self, amount: float, payment_method: str) -> float:
        """Calculate processing fee for payment"""
        rate = self.fee_rates.get(payment_method, 0)
        flat = self.flat_fees.get(payment_method, 0)
        return round(amount * rate + flat, 2)
    
    def _simulate_payment_processing(self, amount: float, brand: str) -> str:
        """Simulate payment processing (replace with real processor in production)"""
        # In production, this would integrate with Stripe, Square, etc.
        return f"AUTH-{uuid.uuid4().hex[:8].upper()}"
    
    def _generate_ledger_hash(self, transaction: PaymentTransaction) -> str:
        """Generate cryptographic hash for ledger entry"""
        data = f"{transaction.id}{transaction.customer_id}{transaction.amount}{transaction.created_at}"
        return hashlib.sha256(data.encode()).hexdigest()[:32].upper()
    
    def _record_to_ledger(self, transaction: PaymentTransaction) -> None:
        """Record transaction to the main ledger"""
        ledger_entry = {
            'id': f"LEDGER-{transaction.id}",
            'transaction_id': transaction.id,
            'type': 'contribution_payment',
            'customer_id': transaction.customer_id,
            'foundation_id': transaction.foundation_id,
            'foundation_name': transaction.foundation_name,
            'fund_id': transaction.fund_id,
            'fund_name': transaction.fund_name,
            'amount': transaction.amount,
            'net_amount': transaction.net_amount,
            'processing_fee': transaction.processing_fee,
            'payment_method': transaction.payment_method,
            'status': transaction.payment_status,
            'hash': transaction.ledger_hash,
            'timestamp': transaction.created_at,
            'verified': True
        }
        self.ledger[ledger_entry['id']] = ledger_entry
    
    def _update_admin_dashboard(self, transaction: PaymentTransaction) -> None:
        """Update admin dashboard with transaction data"""
        if 'contributions' not in self.admin_dashboard:
            self.admin_dashboard['contributions'] = {
                'total_amount': 0,
                'total_count': 0,
                'by_method': {},
                'recent': []
            }
        
        contrib = self.admin_dashboard['contributions']
        contrib['total_amount'] += transaction.amount
        contrib['total_count'] += 1
        
        method = transaction.payment_method
        if method not in contrib['by_method']:
            contrib['by_method'][method] = {'amount': 0, 'count': 0}
        contrib['by_method'][method]['amount'] += transaction.amount
        contrib['by_method'][method]['count'] += 1
        
        # Add to recent (keep last 50)
        contrib['recent'].insert(0, {
            'id': transaction.id,
            'customer_id': transaction.customer_id,
            'foundation_name': transaction.foundation_name,
            'amount': transaction.amount,
            'method': method,
            'status': transaction.payment_status,
            'timestamp': transaction.created_at
        })
        contrib['recent'] = contrib['recent'][:50]
        
        self.admin_dashboard['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    def _update_accounting_dashboard(self, transaction: PaymentTransaction) -> None:
        """Update accounting dashboard with transaction data"""
        if 'transactions' not in self.accounting_dashboard:
            self.accounting_dashboard['transactions'] = {
                'total_revenue': 0,
                'total_fees': 0,
                'net_revenue': 0,
                'by_foundation': {},
                'recent': []
            }
        
        acct = self.accounting_dashboard['transactions']
        acct['total_revenue'] += transaction.amount
        acct['total_fees'] += transaction.processing_fee
        acct['net_revenue'] += transaction.net_amount
        
        fnd_id = transaction.foundation_id
        if fnd_id not in acct['by_foundation']:
            acct['by_foundation'][fnd_id] = {
                'name': transaction.foundation_name,
                'total': 0,
                'fees': 0,
                'count': 0
            }
        acct['by_foundation'][fnd_id]['total'] += transaction.amount
        acct['by_foundation'][fnd_id]['fees'] += transaction.processing_fee
        acct['by_foundation'][fnd_id]['count'] += 1
        
        # Add to recent
        acct['recent'].insert(0, {
            'id': transaction.id,
            'amount': transaction.amount,
            'fee': transaction.processing_fee,
            'net': transaction.net_amount,
            'foundation': transaction.foundation_name,
            'method': transaction.payment_method,
            'timestamp': transaction.created_at
        })
        acct['recent'] = acct['recent'][:100]
        
        self.accounting_dashboard['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    def _get_member_history(self, customer_id: str, foundation_id: str) -> List[Dict]:
        """Get member's contribution history"""
        history = []
        for tx in self.transactions.values():
            if tx.get('customer_id') == customer_id and tx.get('foundation_id') == foundation_id:
                history.append(tx)
        return sorted(history, key=lambda x: x.get('created_at', ''), reverse=True)
    
    def _get_foundation_stats(self, foundation_id: str) -> Dict:
        """Get foundation statistics"""
        total = 0
        count = 0
        for tx in self.transactions.values():
            if tx.get('foundation_id') == foundation_id:
                total += tx.get('amount', 0)
                count += 1
        return {
            'foundation_id': foundation_id,
            'total_contributions': total,
            'contribution_count': count,
            'total_fund_balance': total,
            'current_members': max(1, count // 3)  # Estimate
        }
    
    def get_transaction(self, transaction_id: str) -> Optional[Dict]:
        """Get transaction by ID"""
        return self.transactions.get(transaction_id)
    
    def get_customer_transactions(self, customer_id: str, limit: int = 50) -> List[Dict]:
        """Get customer's transactions"""
        transactions = [
            tx for tx in self.transactions.values()
            if tx.get('customer_id') == customer_id
        ]
        return sorted(transactions, key=lambda x: x.get('created_at', ''), reverse=True)[:limit]
    
    def upload_document_for_contribution(
        self,
        transaction_id: str,
        file_name: str,
        file_data_base64: str,
        file_type: str,
        uploaded_by: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """Upload a document for an existing contribution"""
        # Check transaction exists
        if transaction_id not in self.transactions:
            return {
                "success": False,
                "error": "Transaction not found"
            }
        
        # Process upload
        doc = self.document_handler.process_base64_upload(
            contribution_id=transaction_id,
            file_name=file_name,
            file_data_base64=file_data_base64,
            file_type=file_type,
            uploaded_by=uploaded_by,
            description=description
        )
        
        if not doc:
            return {
                "success": False,
                "error": "Failed to upload document"
            }
        
        # Add to transaction
        transaction = self.transactions[transaction_id]
        if 'documents' not in transaction:
            transaction['documents'] = []
        transaction['documents'].append(doc.to_dict())
        
        # Run AI analysis on documents
        all_docs = [ContributionDocument(**d) for d in transaction['documents']]
        doc_analysis = self.ai_assessment.analyze_documents(all_docs)
        
        return {
            "success": True,
            "document_id": doc.id,
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "checksum": doc.checksum,
            "ai_analysis": doc_analysis
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_payment_service: Optional[ContributionPaymentService] = None


def get_payment_service(
    ledger: Dict = None,
    admin_dashboard: Dict = None,
    accounting_dashboard: Dict = None
) -> ContributionPaymentService:
    """Get or create the payment service singleton"""
    global _payment_service
    if _payment_service is None:
        _payment_service = ContributionPaymentService(
            ledger=ledger,
            admin_dashboard=admin_dashboard,
            accounting_dashboard=accounting_dashboard
        )
    return _payment_service


def init_payment_service(
    ledger: Dict = None,
    admin_dashboard: Dict = None,
    accounting_dashboard: Dict = None
) -> ContributionPaymentService:
    """Initialize or reinitialize the payment service"""
    global _payment_service
    _payment_service = ContributionPaymentService(
        ledger=ledger,
        admin_dashboard=admin_dashboard,
        accounting_dashboard=accounting_dashboard
    )
    return _payment_service
