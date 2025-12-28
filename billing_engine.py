#!/usr/bin/env python3
"""
PHINS Secure Billing Engine
Handles payment processing, transaction logging, and fraud detection
"""
import json
import uuid
import hashlib
import hmac
import secrets
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any


class SecurityValidator:
    """Security validation utilities for payment processing - PCI DSS Compliant"""
    
    # Card type identification patterns (IIN/BIN ranges)
    CARD_PATTERNS = {
        'visa': {
            'prefixes': ['4'],
            'lengths': [13, 16, 19],
            'cvv_length': 3
        },
        'mastercard': {
            'prefixes': ['51', '52', '53', '54', '55'] + [str(i) for i in range(2221, 2721)],
            'lengths': [16],  # Mastercard is ALWAYS 16 digits
            'cvv_length': 3
        },
        'amex': {
            'prefixes': ['34', '37'],
            'lengths': [15],
            'cvv_length': 4
        },
        'discover': {
            'prefixes': ['6011', '644', '645', '646', '647', '648', '649', '65'],
            'lengths': [16, 19],
            'cvv_length': 3
        },
        'diners': {
            'prefixes': ['300', '301', '302', '303', '304', '305', '36', '38'],
            'lengths': [14, 16],
            'cvv_length': 3
        },
        'jcb': {
            'prefixes': ['3528', '3529'] + [str(i) for i in range(3530, 3590)],
            'lengths': [16, 19],
            'cvv_length': 3
        }
    }
    
    @staticmethod
    def hash_sensitive_data(data: str, salt: str = None) -> Tuple[str, str]:
        """Hash sensitive data with salt - PCI DSS compliant"""
        if salt is None:
            salt = secrets.token_hex(32)  # 256-bit salt
        # Use PBKDF2 with SHA-256, 310,000 iterations (OWASP 2023 recommendation)
        hashed = hashlib.pbkdf2_hmac('sha256', data.encode(), salt.encode(), 310000)
        return hashed.hex(), salt
    
    @staticmethod
    def verify_hash(data: str, hashed: str, salt: str) -> bool:
        """Verify hashed data using constant-time comparison"""
        new_hash, _ = SecurityValidator.hash_sensitive_data(data, salt)
        return hmac.compare_digest(new_hash, hashed)
    
    @staticmethod
    def detect_card_type(card_number: str) -> Optional[str]:
        """Detect card type from card number (IIN/BIN identification)"""
        card_number = card_number.replace(' ', '').replace('-', '')
        if not card_number.isdigit():
            return None
        
        for card_type, rules in SecurityValidator.CARD_PATTERNS.items():
            for prefix in rules['prefixes']:
                if card_number.startswith(prefix):
                    if len(card_number) in rules['lengths']:
                        return card_type
        return None
    
    @staticmethod
    def validate_card_number(card_number: str, expected_type: str = None) -> Dict[str, Any]:
        """
        Comprehensive card number validation with:
        - Format cleaning
        - Length validation by card type
        - IIN/BIN prefix validation
        - Luhn algorithm checksum
        
        Returns dict with validation details for insurance-grade accuracy.
        """
        # Clean the card number
        original = card_number
        card_number = card_number.replace(' ', '').replace('-', '').replace('.', '')
        
        result = {
            'valid': False,
            'card_number_masked': SecurityValidator.mask_card_number(card_number),
            'card_type': None,
            'errors': [],
            'warnings': []
        }
        
        # Basic format check
        if not card_number.isdigit():
            result['errors'].append('Card number must contain only digits')
            return result
        
        # Length check
        length = len(card_number)
        if length < 13:
            result['errors'].append(f'Card number too short ({length} digits, minimum 13)')
            return result
        if length > 19:
            result['errors'].append(f'Card number too long ({length} digits, maximum 19)')
            return result
        
        # Detect card type
        detected_type = SecurityValidator.detect_card_type(card_number)
        result['card_type'] = detected_type
        
        # Validate against expected type if provided
        if expected_type and detected_type:
            if expected_type.lower() != detected_type:
                result['warnings'].append(f'Card appears to be {detected_type}, not {expected_type}')
        
        # Card-type specific validation
        if detected_type:
            rules = SecurityValidator.CARD_PATTERNS[detected_type]
            if length not in rules['lengths']:
                result['errors'].append(
                    f'{detected_type.title()} cards must be {" or ".join(map(str, rules["lengths"]))} digits (got {length})'
                )
                return result
        else:
            result['warnings'].append('Unknown card type - proceeding with basic validation')
        
        # Mastercard specific: MUST be exactly 16 digits
        if detected_type == 'mastercard' and length != 16:
            result['errors'].append('Mastercard must be exactly 16 digits')
            return result
        
        # Luhn algorithm checksum
        def luhn_checksum(card: str) -> bool:
            digits = [int(d) for d in card]
            odd_digits = digits[-1::-2]
            even_digits = digits[-2::-2]
            checksum = sum(odd_digits)
            for d in even_digits:
                doubled = d * 2
                checksum += doubled if doubled < 10 else doubled - 9
            return checksum % 10 == 0
        
        if not luhn_checksum(card_number):
            result['errors'].append('Card number failed checksum validation (invalid card)')
            return result
        
        # All validations passed
        result['valid'] = True
        return result
    
    @staticmethod
    def validate_cvv(cvv: str, card_type: str = None) -> Dict[str, Any]:
        """
        Validate CVV/CVC/CID with card-type specific rules.
        - Visa/Mastercard/Discover/JCB: 3 digits
        - Amex: 4 digits (CID)
        """
        result = {
            'valid': False,
            'errors': []
        }
        
        if not cvv:
            result['errors'].append('CVV is required')
            return result
        
        cvv = cvv.strip()
        
        if not cvv.isdigit():
            result['errors'].append('CVV must contain only digits')
            return result
        
        # Determine expected length
        if card_type and card_type.lower() == 'amex':
            expected_length = 4
            cvv_name = 'CID'
        else:
            expected_length = 3
            cvv_name = 'CVV'
        
        if len(cvv) != expected_length:
            result['errors'].append(f'{cvv_name} must be exactly {expected_length} digits')
            return result
        
        result['valid'] = True
        return result
    
    @staticmethod
    def validate_expiry(expiry_month: int, expiry_year: int) -> Dict[str, Any]:
        """
        Validate card expiry date with detailed feedback.
        """
        result = {
            'valid': False,
            'errors': [],
            'warnings': []
        }
        
        now = datetime.now()
        
        # Validate month range
        if expiry_month < 1 or expiry_month > 12:
            result['errors'].append('Invalid expiry month (must be 1-12)')
            return result
        
        # Handle 2-digit year
        if expiry_year < 100:
            expiry_year = 2000 + expiry_year
        
        # Check if expired
        if expiry_year < now.year:
            result['errors'].append('Card has expired')
            return result
        
        if expiry_year == now.year and expiry_month < now.month:
            result['errors'].append('Card has expired')
            return result
        
        # Warning for cards expiring soon
        months_until_expiry = (expiry_year - now.year) * 12 + (expiry_month - now.month)
        if months_until_expiry <= 2:
            result['warnings'].append(f'Card expires in {months_until_expiry} month(s)')
        
        result['valid'] = True
        result['expiry_formatted'] = f"{expiry_month:02d}/{expiry_year}"
        return result
    
    @staticmethod
    def mask_card_number(card_number: str) -> str:
        """
        PCI DSS compliant card masking - show only last 4 digits.
        Never store or log full card numbers.
        """
        card_number = card_number.replace(' ', '').replace('-', '')
        if len(card_number) < 4:
            return '****'
        # PCI DSS allows showing first 6 and last 4, but we show only last 4 for extra security
        return f"****-****-****-{card_number[-4:]}"
    
    @staticmethod
    def detect_suspicious_activity(transaction_history: List[Dict]) -> Dict:
        """Detect suspicious payment patterns"""
        if not transaction_history:
            return {'suspicious': False, 'reason': None}
        
        recent_transactions = [t for t in transaction_history 
                              if (datetime.now() - datetime.fromisoformat(t['timestamp'])).total_seconds() < 3600]
        
        # Multiple failed attempts
        failed_count = sum(1 for t in recent_transactions if t['status'] == 'failed')
        if failed_count >= 3:
            return {'suspicious': True, 'reason': 'Multiple failed payment attempts', 'severity': 'high'}
        
        # Rapid consecutive transactions
        if len(recent_transactions) >= 5:
            return {'suspicious': True, 'reason': 'Unusual transaction frequency', 'severity': 'medium'}
        
        # Large amount detection
        recent_amounts = [t['amount'] for t in recent_transactions if t['status'] == 'success']
        if recent_amounts and max(recent_amounts) > 10000:
            return {'suspicious': True, 'reason': 'Large transaction amount', 'severity': 'medium'}
        
        return {'suspicious': False, 'reason': None}


class BillingEngine:
    """Main billing engine for payment processing"""
    
    def __init__(self):
        self.transactions = {}
        self.payment_methods = {}
        self.billing_history = {}
        self.fraud_alerts = []
        self.security = SecurityValidator()
    
    def add_payment_method(self, customer_id: str, payment_data: Dict) -> Dict:
        """
        Add payment method (tokenized)
        In production, use proper payment gateway tokenization (Stripe, Square, etc.)
        NEVER store full card numbers - PCI DSS compliance
        """
        try:
            # Validate card number with enhanced validation
            card_validation = self.security.validate_card_number(payment_data['card_number'])
            if not card_validation['valid']:
                error_msg = card_validation['errors'][0] if card_validation['errors'] else 'Invalid card number'
                return {'success': False, 'error': error_msg}
            
            # Get detected card type for proper CVV validation
            detected_card_type = card_validation.get('card_type', payment_data.get('card_type'))
            
            # Validate CVV with card-type awareness
            cvv_validation = self.security.validate_cvv(payment_data['cvv'], detected_card_type)
            if not cvv_validation['valid']:
                error_msg = cvv_validation['errors'][0] if cvv_validation['errors'] else 'Invalid CVV'
                return {'success': False, 'error': error_msg}
            
            # Validate expiry date
            expiry_validation = self.security.validate_expiry(
                int(payment_data['expiry_month']), 
                int(payment_data['expiry_year'])
            )
            if not expiry_validation['valid']:
                error_msg = expiry_validation['errors'][0] if expiry_validation['errors'] else 'Card expired'
                return {'success': False, 'error': error_msg}
            
            # Create payment token (simulate tokenization)
            # In production: use Stripe/Square/Braintree tokenization
            token = f"pm_{secrets.token_hex(16)}"
            
            # Store masked card info only (PCI DSS compliance - NEVER store full card numbers)
            if customer_id not in self.payment_methods:
                self.payment_methods[customer_id] = []
            
            self.payment_methods[customer_id].append({
                'token': token,
                'masked_card': self.security.mask_card_number(payment_data['card_number']),
                'card_type': detected_card_type or payment_data.get('card_type', 'unknown'),
                'expiry': f"{payment_data['expiry_month']}/{payment_data['expiry_year']}",
                'cardholder_name': payment_data.get('cardholder_name', ''),
                'billing_address': payment_data.get('billing_address', {}),
                'is_default': len(self.payment_methods[customer_id]) == 0,
                'created_date': datetime.now().isoformat()
            })
            
            return {
                'success': True,
                'token': token,
                'masked_card': self.security.mask_card_number(payment_data['card_number']),
                'card_type': detected_card_type
            }
        
        except Exception as e:
            return {'success': False, 'error': f'Payment method validation failed: {str(e)}'}
    
    def process_payment(self, customer_id: str, amount: float, policy_id: str,
                        payment_token: str = None, metadata: Dict = None,
                        currency: str = 'USD', fx_rate_to_usd: float = None) -> Dict:
        """
        Process payment with fraud detection and security checks
        """
        transaction_id = f"TXN-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(8)}"
        
        try:
            # Amount validation
            if amount <= 0:
                raise ValueError("Amount must be positive")
            
            if amount > 50000:  # Configurable limit
                raise ValueError("Amount exceeds single transaction limit")
            
            # Check for suspicious activity
            customer_transactions = self.get_customer_transactions(customer_id)
            fraud_check = self.security.detect_suspicious_activity(customer_transactions)
            
            if fraud_check['suspicious']:
                self.fraud_alerts.append({
                    'customer_id': customer_id,
                    'transaction_id': transaction_id,
                    'reason': fraud_check['reason'],
                    'severity': fraud_check['severity'],
                    'timestamp': datetime.now().isoformat(),
                    'status': 'flagged'
                })
                
                return {
                    'success': False,
                    'transaction_id': transaction_id,
                    'error': 'Transaction flagged for review',
                    'requires_verification': True
                }
            
            # Get payment method
            payment_method = None
            if payment_token:
                customer_methods = self.payment_methods.get(customer_id, [])
                payment_method = next((pm for pm in customer_methods if pm['token'] == payment_token), None)
                
                if not payment_method:
                    raise ValueError("Invalid payment method")
            
            # Simulate payment processing (in production: call payment gateway API)
            # For demo: 95% success rate
            processing_success = random.random() < 0.95
            
            transaction = {
                'transaction_id': transaction_id,
                'customer_id': customer_id,
                'policy_id': policy_id,
                'amount': amount,
                'currency': currency,
                'status': 'success' if processing_success else 'failed',
                'payment_method': payment_method['masked_card'] if payment_method else 'N/A',
                'payment_token': payment_token,
                'metadata': {
                    **(metadata or {}),
                    **({'fx_rate_to_usd': fx_rate_to_usd} if fx_rate_to_usd is not None else {})
                },
                'timestamp': datetime.now().isoformat(),
                'processed_date': datetime.now().isoformat(),
                'failure_reason': None if processing_success else 'Card declined',
                'receipt_url': f"/receipts/{transaction_id}" if processing_success else None
            }
            
            self.transactions[transaction_id] = transaction
            
            # Update billing history
            if customer_id not in self.billing_history:
                self.billing_history[customer_id] = []
            self.billing_history[customer_id].append(transaction)
            
            return {
                'success': processing_success,
                'transaction_id': transaction_id,
                'amount': amount,
                'status': transaction['status'],
                'receipt_url': transaction['receipt_url'],
                'error': transaction['failure_reason']
            }
        
        except Exception as e:
            error_transaction = {
                'transaction_id': transaction_id,
                'customer_id': customer_id,
                'policy_id': policy_id,
                'amount': amount,
                'status': 'error',
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
            self.transactions[transaction_id] = error_transaction
            
            return {
                'success': False,
                'transaction_id': transaction_id,
                'error': str(e)
            }
    
    def refund_payment(self, transaction_id: str, amount: float = None, reason: str = None) -> Dict:
        """Process refund for a transaction"""
        transaction = self.transactions.get(transaction_id)
        
        if not transaction:
            return {'success': False, 'error': 'Transaction not found'}
        
        if transaction['status'] != 'success':
            return {'success': False, 'error': 'Cannot refund non-successful transaction'}
        
        refund_amount = amount or transaction['amount']
        
        if refund_amount > transaction['amount']:
            return {'success': False, 'error': 'Refund amount exceeds original transaction'}
        
        refund_id = f"RFD-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(8)}"
        
        refund = {
            'refund_id': refund_id,
            'original_transaction_id': transaction_id,
            'customer_id': transaction['customer_id'],
            'amount': refund_amount,
            'reason': reason or 'Customer request',
            'status': 'completed',
            'timestamp': datetime.now().isoformat()
        }
        
        self.transactions[refund_id] = refund
        transaction['refund_id'] = refund_id
        transaction['refund_amount'] = refund_amount
        
        return {
            'success': True,
            'refund_id': refund_id,
            'amount': refund_amount,
            'status': 'completed'
        }
    
    def get_customer_transactions(self, customer_id: str) -> List[Dict]:
        """Get all transactions for a customer"""
        return self.billing_history.get(customer_id, [])
    
    def get_transaction(self, transaction_id: str) -> Optional[Dict]:
        """Get specific transaction"""
        return self.transactions.get(transaction_id)
    
    def get_billing_statement(self, customer_id: str, start_date: str = None, end_date: str = None) -> Dict:
        """Generate billing statement"""
        transactions = self.get_customer_transactions(customer_id)
        
        if start_date:
            transactions = [t for t in transactions 
                          if t['timestamp'] >= start_date]
        if end_date:
            transactions = [t for t in transactions 
                          if t['timestamp'] <= end_date]
        
        successful = [t for t in transactions if t['status'] == 'success']
        failed = [t for t in transactions if t['status'] == 'failed']
        
        return {
            'customer_id': customer_id,
            'period': {
                'start': start_date or 'All time',
                'end': end_date or 'Present'
            },
            'summary': {
                'total_transactions': len(transactions),
                'successful_payments': len(successful),
                'failed_payments': len(failed),
                'total_amount_paid': sum(t['amount'] for t in successful),
                'total_amount_failed': sum(t['amount'] for t in failed)
            },
            'transactions': sorted(transactions, key=lambda x: x['timestamp'], reverse=True)
        }
    
    def get_fraud_alerts(self, severity: str = None, status: str = None) -> List[Dict]:
        """Get fraud alerts with optional filtering"""
        alerts = self.fraud_alerts
        
        if severity:
            alerts = [a for a in alerts if a.get('severity') == severity]
        if status:
            alerts = [a for a in alerts if a.get('status') == status]
        
        return sorted(alerts, key=lambda x: x['timestamp'], reverse=True)
    
    def resolve_fraud_alert(self, alert_index: int, resolution: str) -> Dict:
        """Resolve a fraud alert"""
        if alert_index >= len(self.fraud_alerts):
            return {'success': False, 'error': 'Alert not found'}
        
        self.fraud_alerts[alert_index]['status'] = 'resolved'
        self.fraud_alerts[alert_index]['resolution'] = resolution
        self.fraud_alerts[alert_index]['resolved_date'] = datetime.now().isoformat()
        
        return {'success': True, 'alert': self.fraud_alerts[alert_index]}
    
    def get_payment_methods(self, customer_id: str) -> List[Dict]:
        """Get customer's saved payment methods"""
        return self.payment_methods.get(customer_id, [])
    
    def remove_payment_method(self, customer_id: str, payment_token: str) -> Dict:
        """Remove a payment method"""
        methods = self.payment_methods.get(customer_id, [])
        original_count = len(methods)
        
        self.payment_methods[customer_id] = [m for m in methods if m['token'] != payment_token]
        
        if len(self.payment_methods[customer_id]) < original_count:
            return {'success': True, 'message': 'Payment method removed'}
        return {'success': False, 'error': 'Payment method not found'}


# Global billing engine instance
billing_engine = BillingEngine()


if __name__ == '__main__':
    import random
    
    print("=== PHINS Billing Engine Test ===\n")
    
    # Test 1: Add payment method
    print("1. Adding payment method...")
    result = billing_engine.add_payment_method('CUST-12345', {
        'card_number': '4532015112830366',  # Valid test Visa
        'cvv': '123',
        'expiry_month': '12',
        'expiry_year': '2026',
        'card_type': 'visa',
        'billing_address': {
            'street': '123 Main St',
            'city': 'Boston',
            'state': 'MA',
            'zip': '02101'
        }
    })
    print(f"   Result: {result}\n")
    
    # Test 2: Process payment
    print("2. Processing payment...")
    payment_result = billing_engine.process_payment(
        customer_id='CUST-12345',
        amount=250.00,
        policy_id='POL-20251212-1234',
        payment_token=result.get('token'),
        metadata={'type': 'monthly_premium', 'month': 'December'}
    )
    print(f"   Result: {payment_result}\n")
    
    # Test 3: Get billing statement
    print("3. Getting billing statement...")
    statement = billing_engine.get_billing_statement('CUST-12345')
    print(f"   Transactions: {statement['summary']['total_transactions']}")
    print(f"   Total paid: ${statement['summary']['total_amount_paid']}\n")
    
    # Test 4: Fraud detection
    print("4. Testing fraud detection (multiple rapid transactions)...")
    for i in range(5):
        billing_engine.process_payment('CUST-67890', 100.0, 'POL-TEST', metadata={'test': True})
    
    alerts = billing_engine.get_fraud_alerts()
    print(f"   Fraud alerts: {len(alerts)}")
    if alerts:
        print(f"   Latest alert: {alerts[0]['reason']}\n")
    
    print("=== Tests Complete ===")
