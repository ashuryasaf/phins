"""
Test suite for the Contribution Payment Service

Tests:
- Credit card validation
- Payment processing
- Document upload handling
- AI assessment
- Ledger recording
- Dashboard integration
"""

import pytest
import json
import base64
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.contribution_payment_service import (
    ContributionPaymentService,
    PaymentValidator,
    DocumentUploadHandler,
    ContributionAIAssessment,
    get_payment_service,
    init_payment_service,
    PaymentMethod,
    PaymentStatus,
    CreditCardInfo,
    PaymentTransaction,
    MAX_UPLOAD_SIZE,
    SUPPORTED_DOCUMENT_TYPES
)


class TestPaymentValidator:
    """Test payment validation functions"""
    
    def test_valid_visa_card(self):
        """Test valid Visa card validation"""
        validator = PaymentValidator()
        valid, brand, error = validator.validate_credit_card("4111111111111111")
        assert valid is True
        assert brand == "visa"
        assert error == ""
    
    def test_valid_mastercard(self):
        """Test valid Mastercard validation"""
        validator = PaymentValidator()
        valid, brand, error = validator.validate_credit_card("5500000000000004")
        assert valid is True
        assert brand == "mastercard"
        assert error == ""
    
    def test_valid_amex(self):
        """Test valid American Express validation"""
        validator = PaymentValidator()
        valid, brand, error = validator.validate_credit_card("378282246310005")
        assert valid is True
        assert brand == "amex"
        assert error == ""
    
    def test_invalid_card_number(self):
        """Test invalid card number"""
        validator = PaymentValidator()
        valid, brand, error = validator.validate_credit_card("1234567890123456")
        assert valid is False
        assert "checksum" in error.lower() or "invalid" in error.lower()
    
    def test_card_with_spaces(self):
        """Test card number with spaces"""
        validator = PaymentValidator()
        valid, brand, error = validator.validate_credit_card("4111 1111 1111 1111")
        assert valid is True
        assert brand == "visa"
    
    def test_valid_expiry(self):
        """Test valid expiry date"""
        validator = PaymentValidator()
        future_year = datetime.now().year + 2
        valid, error = validator.validate_expiry(12, future_year)
        assert valid is True
        assert error == ""
    
    def test_expired_card(self):
        """Test expired card"""
        validator = PaymentValidator()
        past_year = datetime.now().year - 1
        valid, error = validator.validate_expiry(1, past_year)
        assert valid is False
        assert "expired" in error.lower()
    
    def test_invalid_month(self):
        """Test invalid month"""
        validator = PaymentValidator()
        valid, error = validator.validate_expiry(13, 2030)
        assert valid is False
        assert "month" in error.lower()
    
    def test_valid_cvv(self):
        """Test valid CVV"""
        validator = PaymentValidator()
        valid, error = validator.validate_cvv("123", "visa")
        assert valid is True
        
        # AMEX has 4-digit CVV
        valid, error = validator.validate_cvv("1234", "amex")
        assert valid is True
    
    def test_invalid_cvv(self):
        """Test invalid CVV"""
        validator = PaymentValidator()
        valid, error = validator.validate_cvv("12", "visa")
        assert valid is False
    
    def test_valid_amount(self):
        """Test valid amount"""
        validator = PaymentValidator()
        valid, error = validator.validate_amount(100.00)
        assert valid is True
    
    def test_invalid_amount(self):
        """Test invalid amount"""
        validator = PaymentValidator()
        
        # Zero amount
        valid, error = validator.validate_amount(0)
        assert valid is False
        
        # Negative amount
        valid, error = validator.validate_amount(-50)
        assert valid is False


class TestDocumentUploadHandler:
    """Test document upload handling"""
    
    def test_validate_file_success(self):
        """Test successful file validation"""
        handler = DocumentUploadHandler()
        valid, error = handler.validate_file("test.pdf", 1024 * 1024, "application/pdf")
        assert valid is True
        assert error == ""
    
    def test_validate_file_too_large(self):
        """Test file too large"""
        handler = DocumentUploadHandler()
        valid, error = handler.validate_file("large.mp4", MAX_UPLOAD_SIZE + 1, "video/mp4")
        assert valid is False
        assert "large" in error.lower()
    
    def test_validate_file_unsupported_type(self):
        """Test unsupported file type"""
        handler = DocumentUploadHandler()
        valid, error = handler.validate_file("script.exe", 1024, "application/x-executable")
        assert valid is False
    
    def test_validate_empty_file(self):
        """Test empty file"""
        handler = DocumentUploadHandler()
        valid, error = handler.validate_file("empty.txt", 0, "text/plain")
        assert valid is False
        assert "empty" in error.lower()
    
    def test_process_upload(self):
        """Test document upload processing"""
        import tempfile
        temp_dir = tempfile.mkdtemp()
        handler = DocumentUploadHandler(upload_dir=temp_dir)
        
        test_content = b"Test document content"
        doc = handler.process_upload(
            contribution_id="TEST-001",
            file_name="test.txt",
            file_data=test_content,
            file_type="text/plain",
            uploaded_by="test_user",
            description="Test document"
        )
        
        assert doc is not None
        assert doc.file_name == "test.txt"
        assert doc.file_size == len(test_content)
        assert doc.uploaded_by == "test_user"
        assert doc.checksum is not None
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)
    
    def test_process_base64_upload(self):
        """Test base64 document upload"""
        import tempfile
        temp_dir = tempfile.mkdtemp()
        handler = DocumentUploadHandler(upload_dir=temp_dir)
        
        test_content = b"Test document content"
        base64_data = base64.b64encode(test_content).decode('utf-8')
        
        doc = handler.process_base64_upload(
            contribution_id="TEST-002",
            file_name="test.txt",
            file_data_base64=base64_data,
            file_type="text/plain",
            uploaded_by="test_user"
        )
        
        assert doc is not None
        assert doc.file_size == len(test_content)
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)


class TestContributionAIAssessment:
    """Test AI assessment functionality"""
    
    def test_analyze_first_contribution(self):
        """Test AI analysis of first contribution"""
        ai = ContributionAIAssessment()
        
        transaction = PaymentTransaction(
            id="TX-001",
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=500.0,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        assessment = ai.analyze_contribution(
            contribution=transaction,
            member_history=[],  # Empty history = first contribution
            foundation_stats={"total_fund_balance": 1000, "current_members": 5}
        )
        
        assert assessment is not None
        assert "assessment_id" in assessment
        assert assessment["metrics"]["is_first_contribution"] is True
        assert "summary" in assessment
        assert "recommendations" in assessment
    
    def test_analyze_regular_contribution(self):
        """Test AI analysis with contribution history"""
        ai = ContributionAIAssessment()
        
        transaction = PaymentTransaction(
            id="TX-002",
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=150.0,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        # Create mock history
        member_history = [
            {"amount": 100.0, "created_at": "2026-01-01T00:00:00+00:00"},
            {"amount": 100.0, "created_at": "2026-01-15T00:00:00+00:00"},
            {"amount": 100.0, "created_at": "2026-01-20T00:00:00+00:00"}
        ]
        
        assessment = ai.analyze_contribution(
            contribution=transaction,
            member_history=member_history,
            foundation_stats={"total_fund_balance": 5000, "current_members": 10}
        )
        
        assert assessment is not None
        assert assessment["metrics"]["is_first_contribution"] is False
        assert assessment["metrics"]["contribution_count"] == 3
        assert "risk_assessment" in assessment
        assert assessment["risk_assessment"]["level"] in ["low", "medium", "high"]
    
    def test_analyze_documents(self):
        """Test document analysis"""
        from services.contribution_payment_service import ContributionDocument
        
        ai = ContributionAIAssessment()
        
        documents = [
            ContributionDocument(
                id="DOC001",
                contribution_id="TX-001",
                file_name="receipt.pdf",
                file_type="application/pdf",
                file_size=1024 * 1024,
                file_path="/test/receipt.pdf"
            ),
            ContributionDocument(
                id="DOC002",
                contribution_id="TX-001",
                file_name="photo.jpg",
                file_type="image/jpeg",
                file_size=2 * 1024 * 1024,
                file_path="/test/photo.jpg"
            )
        ]
        
        analysis = ai.analyze_documents(documents)
        
        assert analysis is not None
        assert analysis["document_count"] == 2
        assert analysis["document_types"]["images"] is True
        assert analysis["document_types"]["pdfs"] is True
        assert "completeness_score" in analysis


class TestContributionPaymentService:
    """Test the main payment service"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.ledger = {}
        self.admin_dashboard = {}
        self.accounting_dashboard = {}
        self.service = ContributionPaymentService(
            ledger=self.ledger,
            admin_dashboard=self.admin_dashboard,
            accounting_dashboard=self.accounting_dashboard
        )
    
    def test_process_credit_card_payment_success(self):
        """Test successful credit card payment"""
        result = self.service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=100.00,
            card_number="4111111111111111",
            exp_month=12,
            exp_year=2030,
            cvv="123",
            cardholder_name="John Doe",
            billing_zip="12345"
        )
        
        assert result["success"] is True
        assert result["amount"] == 100.00
        assert result["card_brand"] == "visa"
        assert result["card_last4"] == "1111"
        assert result["status"] == PaymentStatus.COMPLETED.value
        assert "transaction_id" in result
        assert "ledger_hash" in result
        assert result["recorded_to_ledger"] is True
        assert "ai_assessment" in result
    
    def test_process_credit_card_payment_invalid_card(self):
        """Test credit card payment with invalid card"""
        result = self.service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=100.00,
            card_number="1234567890123456",
            exp_month=12,
            exp_year=2030,
            cvv="123",
            cardholder_name="John Doe"
        )
        
        assert result["success"] is False
        assert result["error_code"] == "INVALID_CARD"
    
    def test_process_credit_card_payment_expired(self):
        """Test credit card payment with expired card"""
        result = self.service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=100.00,
            card_number="4111111111111111",
            exp_month=1,
            exp_year=2020,
            cvv="123",
            cardholder_name="John Doe"
        )
        
        assert result["success"] is False
        assert result["error_code"] == "INVALID_EXPIRY"
    
    def test_process_wallet_payment_success(self):
        """Test successful wallet payment"""
        result = self.service.process_wallet_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=50.00,
            wallet_balance=100.00
        )
        
        assert result["success"] is True
        assert result["amount"] == 50.00
        assert result["processing_fee"] == 0
        assert result["net_amount"] == 50.00
    
    def test_process_wallet_payment_insufficient_balance(self):
        """Test wallet payment with insufficient balance"""
        result = self.service.process_wallet_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=150.00,
            wallet_balance=100.00
        )
        
        assert result["success"] is False
        assert result["error_code"] == "INSUFFICIENT_BALANCE"
    
    def test_process_bank_transfer(self):
        """Test bank transfer payment"""
        result = self.service.process_bank_transfer(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=500.00,
            bank_name="Test Bank",
            account_last4="1234"
        )
        
        assert result["success"] is True
        assert result["amount"] == 500.00
        assert result["status"] == PaymentStatus.PROCESSING.value  # Bank transfers are pending
        assert "expected_settlement" in result
    
    def test_ledger_recording(self):
        """Test that transactions are recorded to ledger"""
        result = self.service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=75.00,
            card_number="4111111111111111",
            exp_month=12,
            exp_year=2030,
            cvv="123",
            cardholder_name="John Doe"
        )
        
        assert result["success"] is True
        assert len(self.ledger) == 1
        
        ledger_entry = list(self.ledger.values())[0]
        assert ledger_entry["amount"] == 75.00
        assert ledger_entry["verified"] is True
    
    def test_admin_dashboard_update(self):
        """Test that admin dashboard is updated"""
        result = self.service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=200.00,
            card_number="4111111111111111",
            exp_month=12,
            exp_year=2030,
            cvv="123",
            cardholder_name="John Doe"
        )
        
        assert result["success"] is True
        assert "contributions" in self.admin_dashboard
        assert self.admin_dashboard["contributions"]["total_amount"] == 200.00
        assert self.admin_dashboard["contributions"]["total_count"] == 1
    
    def test_accounting_dashboard_update(self):
        """Test that accounting dashboard is updated"""
        result = self.service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=300.00,
            card_number="4111111111111111",
            exp_month=12,
            exp_year=2030,
            cvv="123",
            cardholder_name="John Doe"
        )
        
        assert result["success"] is True
        assert "transactions" in self.accounting_dashboard
        assert self.accounting_dashboard["transactions"]["total_revenue"] == 300.00
        assert self.accounting_dashboard["transactions"]["total_fees"] > 0  # Credit card has fees
    
    def test_get_customer_transactions(self):
        """Test retrieving customer transactions"""
        # Make a few transactions
        for i in range(3):
            self.service.process_wallet_payment(
                customer_id="CUST001",
                foundation_id="FND001",
                foundation_name="Test Foundation",
                fund_id="FUND001",
                fund_name="Main Fund",
                amount=50.00 + i * 10,
                wallet_balance=1000.00
            )
        
        transactions = self.service.get_customer_transactions("CUST001")
        assert len(transactions) == 3
    
    def test_document_upload_for_contribution(self):
        """Test uploading document to existing contribution"""
        # First create a contribution
        result = self.service.process_wallet_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Test Foundation",
            fund_id="FUND001",
            fund_name="Main Fund",
            amount=100.00,
            wallet_balance=1000.00
        )
        
        tx_id = result["transaction_id"]
        
        # Upload a document
        test_content = base64.b64encode(b"Test document").decode('utf-8')
        upload_result = self.service.upload_document_for_contribution(
            transaction_id=tx_id,
            file_name="receipt.txt",
            file_data_base64=test_content,
            file_type="text/plain",
            uploaded_by="CUST001",
            description="Payment receipt"
        )
        
        assert upload_result["success"] is True
        assert "document_id" in upload_result


class TestServiceIntegration:
    """Integration tests for the full contribution pipeline"""
    
    def test_full_contribution_pipeline(self):
        """Test the complete contribution pipeline"""
        # Initialize service
        ledger = {}
        admin = {}
        accounting = {}
        service = init_payment_service(ledger, admin, accounting)
        
        # Step 1: Make a credit card contribution
        result = service.process_credit_card_payment(
            customer_id="CUST001",
            foundation_id="FND001",
            foundation_name="Community Fund",
            fund_id="FUND001",
            fund_name="Emergency Fund",
            amount=250.00,
            card_number="4111111111111111",
            exp_month=12,
            exp_year=2030,
            cvv="123",
            cardholder_name="Jane Smith",
            billing_zip="90210"
        )
        
        assert result["success"] is True
        tx_id = result["transaction_id"]
        
        # Step 2: Verify ledger entry
        assert len(ledger) == 1
        ledger_entry = list(ledger.values())[0]
        assert ledger_entry["verified"] is True
        
        # Step 3: Verify AI assessment
        assert result["ai_assessment"] is not None
        assert "summary" in result["ai_assessment"]
        
        # Step 4: Verify admin dashboard
        assert admin["contributions"]["total_amount"] == 250.00
        
        # Step 5: Verify accounting dashboard
        assert accounting["transactions"]["total_revenue"] == 250.00
        assert accounting["transactions"]["net_revenue"] > 0
        
        # Step 6: Upload document
        doc_data = base64.b64encode(b"Receipt contents").decode('utf-8')
        doc_result = service.upload_document_for_contribution(
            transaction_id=tx_id,
            file_name="receipt.pdf",
            file_data_base64=doc_data,
            file_type="application/pdf",
            uploaded_by="CUST001"
        )
        
        assert doc_result["success"] is True
        
        # Step 7: Verify transaction was stored with document
        transaction = service.get_transaction(tx_id)
        assert transaction is not None
        assert len(transaction.get("documents", [])) == 1


class TestWalletDeposit:
    """Test wallet deposit functionality in foundation service"""
    
    def test_wallet_deposit_success(self):
        """Test successful wallet deposit"""
        import sys
        sys.path.insert(0, '/workspace')
        from services.foundation_service import FoundationService
        
        service = FoundationService(
            enable_persistence=False,
            enable_backup=False,
            enable_billing_integration=False
        )
        
        result = service.deposit_to_wallet(
            customer_id="CUST001",
            amount=100.00,
            payment_method="credit_card",
            card_last4="1234",
            card_brand="visa"
        )
        
        assert result["success"] is True
        assert result["amount"] == 100.00
        assert result["new_balance"] == 100.00
        assert "deposit_id" in result
        assert "ledger_hash" in result
        assert result["nft_verified"] is True
    
    def test_wallet_deposit_minimum(self):
        """Test wallet deposit minimum amount"""
        import sys
        sys.path.insert(0, '/workspace')
        from services.foundation_service import FoundationService
        
        service = FoundationService(
            enable_persistence=False,
            enable_backup=False,
            enable_billing_integration=False
        )
        
        result = service.deposit_to_wallet(
            customer_id="CUST001",
            amount=5.00,  # Below minimum
            payment_method="credit_card"
        )
        
        assert result["success"] is False
        assert "Minimum" in result.get("error", "")
    
    def test_wallet_deposit_balance_accumulation(self):
        """Test that multiple deposits accumulate correctly"""
        import sys
        sys.path.insert(0, '/workspace')
        from services.foundation_service import FoundationService
        
        service = FoundationService(
            enable_persistence=False,
            enable_backup=False,
            enable_billing_integration=False
        )
        
        # First deposit
        result1 = service.deposit_to_wallet(
            customer_id="CUST002",
            amount=50.00,
            payment_method="credit_card"
        )
        assert result1["success"] is True
        assert result1["new_balance"] == 50.00
        
        # Second deposit
        result2 = service.deposit_to_wallet(
            customer_id="CUST002",
            amount=75.00,
            payment_method="credit_card"
        )
        assert result2["success"] is True
        assert result2["new_balance"] == 125.00  # 50 + 75
    
    def test_wallet_transactions_history(self):
        """Test wallet transaction history"""
        import sys
        sys.path.insert(0, '/workspace')
        from services.foundation_service import FoundationService
        
        service = FoundationService(
            enable_persistence=False,
            enable_backup=False,
            enable_billing_integration=False
        )
        
        # Make a few deposits
        for i in range(3):
            service.deposit_to_wallet(
                customer_id="CUST003",
                amount=50.00 + i * 10,
                payment_method="credit_card"
            )
        
        # Get transaction history
        transactions = service.get_wallet_transactions("CUST003")
        
        assert len(transactions) == 3
        # Most recent should be first (sorted descending)
        assert transactions[0]["amount"] == 70.00
        assert transactions[1]["amount"] == 60.00
        assert transactions[2]["amount"] == 50.00


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
