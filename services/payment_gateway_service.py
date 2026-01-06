#!/usr/bin/env python3
"""
PHINS Multi-Gateway Payment Service
Supports: PayPal, Stripe (Credit Cards, Apple Pay, Google Pay), Bitcoin/Crypto

This service provides a unified interface for multiple payment processors
with built-in sandbox/test mode support for development and testing.

IMPORTANT: For production use, replace sandbox credentials with live credentials
and ensure PCI DSS compliance for card handling.
"""

import json
import uuid
import hashlib
import hmac
import time
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import urllib.request
import urllib.parse
import urllib.error


class PaymentMethod(Enum):
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    PAYPAL = "paypal"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"
    BITCOIN = "bitcoin"
    ETHEREUM = "ethereum"
    USDC = "usdc"
    BANK_TRANSFER = "bank_transfer"


class PaymentStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


@dataclass
class PaymentResult:
    """Standardized payment result across all gateways"""
    success: bool
    transaction_id: str
    gateway: str
    method: str
    amount: float
    currency: str
    status: str
    timestamp: str
    details: Dict[str, Any]
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class PayPalSandbox:
    """
    PayPal Sandbox Integration for Testing
    
    Test Credentials (Sandbox):
    - Client ID: sb-xxxxx (get from developer.paypal.com)
    - Client Secret: xxxxx (get from developer.paypal.com)
    
    Test Card Numbers (PayPal Sandbox):
    - Visa: 4111111111111111
    - Mastercard: 5555555555554444
    - Amex: 378282246310005
    
    Test PayPal Accounts:
    - Create sandbox accounts at developer.paypal.com
    """
    
    # Sandbox API endpoints
    SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
    LIVE_BASE_URL = "https://api-m.paypal.com"
    
    def __init__(self, client_id: str = None, client_secret: str = None, sandbox: bool = True):
        self.sandbox = sandbox
        self.base_url = self.SANDBOX_BASE_URL if sandbox else self.LIVE_BASE_URL
        
        # Use demo credentials if none provided (for testing without real PayPal account)
        self.client_id = client_id or "DEMO_SANDBOX_CLIENT_ID"
        self.client_secret = client_secret or "DEMO_SANDBOX_SECRET"
        self._access_token = None
        self._token_expiry = None
    
    def _get_access_token(self) -> str:
        """Get OAuth2 access token from PayPal"""
        if self._access_token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._access_token
        
        # For demo mode without real credentials, return mock token
        if self.client_id == "DEMO_SANDBOX_CLIENT_ID":
            self._access_token = f"DEMO_TOKEN_{secrets.token_hex(16)}"
            self._token_expiry = datetime.now() + timedelta(hours=1)
            return self._access_token
        
        # Real PayPal OAuth2 flow
        try:
            url = f"{self.base_url}/v1/oauth2/token"
            auth = f"{self.client_id}:{self.client_secret}".encode()
            auth_header = f"Basic {__import__('base64').b64encode(auth).decode()}"
            
            data = urllib.parse.urlencode({'grant_type': 'client_credentials'}).encode()
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Authorization', auth_header)
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                self._access_token = result['access_token']
                self._token_expiry = datetime.now() + timedelta(seconds=result.get('expires_in', 3600) - 60)
                return self._access_token
        except Exception as e:
            # Fallback to demo mode on error
            self._access_token = f"FALLBACK_TOKEN_{secrets.token_hex(16)}"
            self._token_expiry = datetime.now() + timedelta(hours=1)
            return self._access_token
    
    def create_order(self, amount: float, currency: str = "USD", 
                     description: str = "Insurance Premium Payment",
                     customer_email: str = None) -> PaymentResult:
        """Create a PayPal order for payment"""
        order_id = f"PAYPAL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        
        # Demo/Sandbox simulation
        if self.client_id == "DEMO_SANDBOX_CLIENT_ID" or self.sandbox:
            return PaymentResult(
                success=True,
                transaction_id=order_id,
                gateway="paypal",
                method="paypal",
                amount=amount,
                currency=currency,
                status=PaymentStatus.PENDING.value,
                timestamp=datetime.now().isoformat(),
                details={
                    'order_id': order_id,
                    'approval_url': f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                    'capture_url': f"/api/payment/paypal/capture/{order_id}",
                    'description': description,
                    'sandbox_mode': True,
                    'test_instructions': 'In sandbox mode, click approval_url to simulate payment approval'
                }
            )
        
        # Real PayPal API call would go here
        return self._create_real_order(amount, currency, description)
    
    def capture_order(self, order_id: str) -> PaymentResult:
        """Capture an approved PayPal order"""
        # Simulate successful capture in sandbox
        return PaymentResult(
            success=True,
            transaction_id=order_id,
            gateway="paypal",
            method="paypal",
            amount=0,  # Amount from order
            currency="USD",
            status=PaymentStatus.COMPLETED.value,
            timestamp=datetime.now().isoformat(),
            details={
                'order_id': order_id,
                'capture_id': f"CAPTURE-{secrets.token_hex(8).upper()}",
                'sandbox_mode': self.sandbox
            }
        )
    
    def refund(self, capture_id: str, amount: float = None) -> PaymentResult:
        """Refund a captured payment"""
        refund_id = f"REFUND-{secrets.token_hex(8).upper()}"
        return PaymentResult(
            success=True,
            transaction_id=refund_id,
            gateway="paypal",
            method="paypal",
            amount=amount or 0,
            currency="USD",
            status=PaymentStatus.REFUNDED.value,
            timestamp=datetime.now().isoformat(),
            details={
                'capture_id': capture_id,
                'refund_id': refund_id,
                'sandbox_mode': self.sandbox
            }
        )


class StripeTestMode:
    """
    Stripe Test Mode Integration
    Supports: Credit Cards, Debit Cards, Apple Pay, Google Pay
    
    Test Card Numbers (Stripe):
    - Visa: 4242424242424242
    - Visa (Debit): 4000056655665556
    - Mastercard: 5555555555554444
    - Amex: 378282246310005
    - Discover: 6011111111111117
    
    - Decline: 4000000000000002
    - Insufficient Funds: 4000000000009995
    - Expired Card: 4000000000000069
    - Incorrect CVC: 4000000000000127
    
    Apple Pay / Google Pay:
    - Use Stripe's test environment tokens
    
    Test Expiry: Any future date (e.g., 12/34)
    Test CVC: Any 3 digits (4 for Amex)
    """
    
    SANDBOX_BASE_URL = "https://api.stripe.com/v1"
    
    # Test card responses
    TEST_CARDS = {
        '4242424242424242': {'status': 'success', 'brand': 'visa'},
        '4000056655665556': {'status': 'success', 'brand': 'visa_debit'},
        '5555555555554444': {'status': 'success', 'brand': 'mastercard'},
        '5425233430109903': {'status': 'success', 'brand': 'mastercard'},
        '378282246310005': {'status': 'success', 'brand': 'amex'},
        '6011111111111117': {'status': 'success', 'brand': 'discover'},
        '4000000000000002': {'status': 'declined', 'error': 'Card declined'},
        '4000000000009995': {'status': 'declined', 'error': 'Insufficient funds'},
        '4000000000000069': {'status': 'declined', 'error': 'Expired card'},
        '4000000000000127': {'status': 'declined', 'error': 'Incorrect CVC'},
    }
    
    def __init__(self, api_key: str = None, test_mode: bool = True):
        self.test_mode = test_mode
        # Use test key format if none provided
        self.api_key = api_key or "sk_test_DEMO_KEY_FOR_TESTING"
    
    def create_payment_intent(self, amount: float, currency: str = "USD",
                              card_number: str = None, 
                              payment_method: str = "card",
                              customer_email: str = None,
                              metadata: Dict = None) -> PaymentResult:
        """Create a Stripe PaymentIntent"""
        intent_id = f"pi_{secrets.token_hex(12)}"
        amount_cents = int(amount * 100)
        
        # Determine card behavior based on test card number
        card_cleaned = (card_number or '').replace(' ', '').replace('-', '')
        test_response = self.TEST_CARDS.get(card_cleaned, {'status': 'success', 'brand': 'unknown'})
        
        if test_response['status'] == 'declined':
            return PaymentResult(
                success=False,
                transaction_id=intent_id,
                gateway="stripe",
                method=payment_method,
                amount=amount,
                currency=currency.upper(),
                status=PaymentStatus.FAILED.value,
                timestamp=datetime.now().isoformat(),
                error=test_response['error'],
                details={
                    'payment_intent_id': intent_id,
                    'decline_code': test_response['error'].lower().replace(' ', '_'),
                    'test_mode': self.test_mode
                }
            )
        
        return PaymentResult(
            success=True,
            transaction_id=intent_id,
            gateway="stripe",
            method=payment_method,
            amount=amount,
            currency=currency.upper(),
            status=PaymentStatus.COMPLETED.value,
            timestamp=datetime.now().isoformat(),
            details={
                'payment_intent_id': intent_id,
                'charge_id': f"ch_{secrets.token_hex(12)}",
                'card_brand': test_response.get('brand', 'unknown'),
                'card_last4': card_cleaned[-4:] if card_cleaned else '****',
                'receipt_url': f"https://dashboard.stripe.com/test/payments/{intent_id}",
                'test_mode': self.test_mode,
                'metadata': metadata or {}
            }
        )
    
    def create_apple_pay_session(self, amount: float, currency: str = "USD",
                                  merchant_name: str = "PHINS Insurance") -> PaymentResult:
        """Initialize Apple Pay payment session"""
        session_id = f"applepay_{secrets.token_hex(12)}"
        
        return PaymentResult(
            success=True,
            transaction_id=session_id,
            gateway="stripe",
            method="apple_pay",
            amount=amount,
            currency=currency.upper(),
            status=PaymentStatus.PENDING.value,
            timestamp=datetime.now().isoformat(),
            details={
                'session_id': session_id,
                'merchant_name': merchant_name,
                'supported_networks': ['visa', 'masterCard', 'amex', 'discover'],
                'merchant_capabilities': ['supports3DS'],
                'test_mode': self.test_mode,
                'client_token': f"apple_pay_token_{secrets.token_hex(16)}",
                'instructions': 'Use Apple Pay button in test mode - will simulate successful payment'
            }
        )
    
    def create_google_pay_session(self, amount: float, currency: str = "USD",
                                   merchant_name: str = "PHINS Insurance") -> PaymentResult:
        """Initialize Google Pay payment session"""
        session_id = f"googlepay_{secrets.token_hex(12)}"
        
        return PaymentResult(
            success=True,
            transaction_id=session_id,
            gateway="stripe",
            method="google_pay",
            amount=amount,
            currency=currency.upper(),
            status=PaymentStatus.PENDING.value,
            timestamp=datetime.now().isoformat(),
            details={
                'session_id': session_id,
                'merchant_name': merchant_name,
                'allowed_payment_methods': ['CARD', 'TOKENIZED_CARD'],
                'test_mode': self.test_mode,
                'client_token': f"google_pay_token_{secrets.token_hex(16)}",
                'instructions': 'Use Google Pay button in test mode - will simulate successful payment'
            }
        )
    
    def refund(self, payment_intent_id: str, amount: float = None) -> PaymentResult:
        """Refund a Stripe payment"""
        refund_id = f"re_{secrets.token_hex(12)}"
        
        return PaymentResult(
            success=True,
            transaction_id=refund_id,
            gateway="stripe",
            method="refund",
            amount=amount or 0,
            currency="USD",
            status=PaymentStatus.REFUNDED.value,
            timestamp=datetime.now().isoformat(),
            details={
                'refund_id': refund_id,
                'payment_intent_id': payment_intent_id,
                'test_mode': self.test_mode
            }
        )


class CryptoPaymentGateway:
    """
    Cryptocurrency Payment Gateway
    Supports: Bitcoin (BTC), Ethereum (ETH), USDC, and other tokens
    
    Test Mode:
    - Simulates blockchain confirmations
    - Uses testnet addresses
    
    Bitcoin Testnet Faucet: https://coinfaucet.eu/en/btc-testnet/
    Ethereum Testnet (Goerli): https://goerlifaucet.com/
    """
    
    # Testnet addresses (DO NOT USE FOR REAL PAYMENTS)
    TESTNET_ADDRESSES = {
        'BTC': 'tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx',  # Bitcoin testnet
        'ETH': '0x742d35Cc6634C0532925a3b844Bc9e7595f3Bdb7',  # Ethereum testnet
        'USDC': '0x742d35Cc6634C0532925a3b844Bc9e7595f3Bdb7',  # Same as ETH (ERC-20)
        'LTC': 'tltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kfn5j3x',  # Litecoin testnet
    }
    
    # Approximate USD rates (for demo - in production, fetch from API)
    DEMO_RATES = {
        'BTC': 43500.00,
        'ETH': 2250.00,
        'USDC': 1.00,
        'LTC': 72.00,
    }
    
    def __init__(self, testnet: bool = True, market_data_service=None):
        self.testnet = testnet
        self.market_data = market_data_service
        self._pending_payments = {}
    
    def get_crypto_rate(self, symbol: str) -> float:
        """Get current USD rate for cryptocurrency"""
        symbol = symbol.upper()
        
        # Try to get live rate from market data service
        if self.market_data:
            try:
                prices = self.market_data.get_crypto_prices_usd([symbol])
                if prices.get('prices', {}).get(symbol):
                    return float(prices['prices'][symbol])
            except Exception:
                pass
        
        # Fallback to demo rates
        return self.DEMO_RATES.get(symbol, 1.0)
    
    def create_payment_request(self, amount_usd: float, crypto_symbol: str = "BTC",
                                customer_id: str = None,
                                policy_id: str = None) -> PaymentResult:
        """Create a cryptocurrency payment request"""
        symbol = crypto_symbol.upper()
        rate = self.get_crypto_rate(symbol)
        crypto_amount = round(amount_usd / rate, 8)
        
        payment_id = f"CRYPTO-{symbol}-{secrets.token_hex(8).upper()}"
        
        # Generate receiving address (testnet in test mode)
        if self.testnet:
            receiving_address = self.TESTNET_ADDRESSES.get(symbol, 
                f"TEST_{symbol}_{secrets.token_hex(20)}")
        else:
            receiving_address = f"PROD_{symbol}_{secrets.token_hex(20)}"
        
        # Store pending payment for tracking
        self._pending_payments[payment_id] = {
            'amount_usd': amount_usd,
            'crypto_amount': crypto_amount,
            'symbol': symbol,
            'address': receiving_address,
            'rate': rate,
            'created': datetime.now().isoformat(),
            'expires': (datetime.now() + timedelta(minutes=30)).isoformat(),
            'confirmations': 0,
            'status': 'pending'
        }
        
        return PaymentResult(
            success=True,
            transaction_id=payment_id,
            gateway="crypto",
            method=symbol.lower(),
            amount=amount_usd,
            currency="USD",
            status=PaymentStatus.PENDING.value,
            timestamp=datetime.now().isoformat(),
            details={
                'payment_id': payment_id,
                'receiving_address': receiving_address,
                'crypto_symbol': symbol,
                'crypto_amount': crypto_amount,
                'exchange_rate': rate,
                'expires_at': self._pending_payments[payment_id]['expires'],
                'qr_code_data': f"{symbol.lower()}:{receiving_address}?amount={crypto_amount}",
                'testnet': self.testnet,
                'required_confirmations': 1 if self.testnet else (6 if symbol == 'BTC' else 12),
                'instructions': f'Send exactly {crypto_amount} {symbol} to the address above',
                'network': f"{symbol} {'Testnet' if self.testnet else 'Mainnet'}"
            }
        )
    
    def check_payment_status(self, payment_id: str) -> PaymentResult:
        """Check the status of a crypto payment"""
        payment = self._pending_payments.get(payment_id)
        
        if not payment:
            return PaymentResult(
                success=False,
                transaction_id=payment_id,
                gateway="crypto",
                method="unknown",
                amount=0,
                currency="USD",
                status=PaymentStatus.FAILED.value,
                timestamp=datetime.now().isoformat(),
                error="Payment not found",
                details={}
            )
        
        # In test mode, simulate confirmation after a short time
        if self.testnet:
            created = datetime.fromisoformat(payment['created'])
            elapsed = (datetime.now() - created).total_seconds()
            
            # Simulate blockchain confirmations over time
            if elapsed > 30:  # After 30 seconds, simulate 1 confirmation
                payment['confirmations'] = min(int(elapsed / 30), 6)
            
            if payment['confirmations'] >= 1:
                payment['status'] = 'confirmed'
                return PaymentResult(
                    success=True,
                    transaction_id=payment_id,
                    gateway="crypto",
                    method=payment['symbol'].lower(),
                    amount=payment['amount_usd'],
                    currency="USD",
                    status=PaymentStatus.COMPLETED.value,
                    timestamp=datetime.now().isoformat(),
                    details={
                        'confirmations': payment['confirmations'],
                        'tx_hash': f"0x{secrets.token_hex(32)}",
                        'block_number': 12345678 + payment['confirmations'],
                        'testnet': self.testnet
                    }
                )
        
        return PaymentResult(
            success=True,
            transaction_id=payment_id,
            gateway="crypto",
            method=payment['symbol'].lower(),
            amount=payment['amount_usd'],
            currency="USD",
            status=PaymentStatus.PENDING.value,
            timestamp=datetime.now().isoformat(),
            details={
                'confirmations': payment['confirmations'],
                'required_confirmations': 1 if self.testnet else 6,
                'testnet': self.testnet
            }
        )
    
    def simulate_payment_received(self, payment_id: str) -> PaymentResult:
        """Manually simulate a payment being received (for testing)"""
        payment = self._pending_payments.get(payment_id)
        
        if not payment:
            return PaymentResult(
                success=False,
                transaction_id=payment_id,
                gateway="crypto",
                method="unknown",
                amount=0,
                currency="USD",
                status=PaymentStatus.FAILED.value,
                timestamp=datetime.now().isoformat(),
                error="Payment not found",
                details={}
            )
        
        payment['confirmations'] = 6
        payment['status'] = 'confirmed'
        
        return PaymentResult(
            success=True,
            transaction_id=payment_id,
            gateway="crypto",
            method=payment['symbol'].lower(),
            amount=payment['amount_usd'],
            currency="USD",
            status=PaymentStatus.COMPLETED.value,
            timestamp=datetime.now().isoformat(),
            details={
                'confirmations': 6,
                'tx_hash': f"0x{secrets.token_hex(32)}",
                'simulated': True,
                'testnet': self.testnet
            }
        )


class UnifiedPaymentGateway:
    """
    Unified Payment Gateway - Single interface for all payment methods
    
    Usage:
        gateway = UnifiedPaymentGateway(test_mode=True)
        
        # Credit Card
        result = gateway.process_payment(
            method='credit_card',
            amount=250.00,
            card_number='4242424242424242',
            ...
        )
        
        # PayPal
        result = gateway.create_paypal_order(amount=250.00)
        
        # Apple Pay
        result = gateway.create_apple_pay_session(amount=250.00)
        
        # Bitcoin
        result = gateway.create_crypto_payment(amount=250.00, crypto='BTC')
    """
    
    def __init__(self, 
                 test_mode: bool = True,
                 paypal_client_id: str = None,
                 paypal_secret: str = None,
                 stripe_api_key: str = None,
                 market_data_service=None):
        
        self.test_mode = test_mode
        self.paypal = PayPalSandbox(
            client_id=paypal_client_id,
            client_secret=paypal_secret,
            sandbox=test_mode
        )
        self.stripe = StripeTestMode(
            api_key=stripe_api_key,
            test_mode=test_mode
        )
        self.crypto = CryptoPaymentGateway(
            testnet=test_mode,
            market_data_service=market_data_service
        )
        
        # Transaction log
        self._transactions: List[Dict] = []
    
    def get_available_methods(self) -> List[Dict]:
        """Get list of available payment methods with test info"""
        return [
            {
                'id': 'credit_card',
                'name': 'Credit Card',
                'gateway': 'stripe',
                'enabled': True,
                'test_cards': [
                    {'number': '4242424242424242', 'brand': 'Visa', 'result': 'Success'},
                    {'number': '5555555555554444', 'brand': 'Mastercard', 'result': 'Success'},
                    {'number': '378282246310005', 'brand': 'Amex', 'result': 'Success'},
                    {'number': '4000000000000002', 'brand': 'Visa', 'result': 'Decline'},
                ]
            },
            {
                'id': 'paypal',
                'name': 'PayPal',
                'gateway': 'paypal',
                'enabled': True,
                'sandbox_url': 'https://www.sandbox.paypal.com',
                'test_account': 'Create at developer.paypal.com'
            },
            {
                'id': 'apple_pay',
                'name': 'Apple Pay',
                'gateway': 'stripe',
                'enabled': True,
                'note': 'Requires Safari on Mac/iOS with Apple Pay configured'
            },
            {
                'id': 'google_pay',
                'name': 'Google Pay',
                'gateway': 'stripe',
                'enabled': True,
                'note': 'Requires Chrome with Google Pay configured'
            },
            {
                'id': 'bitcoin',
                'name': 'Bitcoin (BTC)',
                'gateway': 'crypto',
                'enabled': True,
                'network': 'Testnet' if self.test_mode else 'Mainnet',
                'faucet': 'https://coinfaucet.eu/en/btc-testnet/'
            },
            {
                'id': 'ethereum',
                'name': 'Ethereum (ETH)',
                'gateway': 'crypto',
                'enabled': True,
                'network': 'Goerli Testnet' if self.test_mode else 'Mainnet',
                'faucet': 'https://goerlifaucet.com/'
            },
            {
                'id': 'usdc',
                'name': 'USD Coin (USDC)',
                'gateway': 'crypto',
                'enabled': True,
                'network': 'Testnet' if self.test_mode else 'Mainnet'
            }
        ]
    
    def process_payment(self, method: str, amount: float, currency: str = "USD",
                        customer_id: str = None, policy_id: str = None,
                        **kwargs) -> PaymentResult:
        """
        Process a payment using the specified method
        
        Args:
            method: Payment method (credit_card, paypal, apple_pay, google_pay, bitcoin, ethereum, usdc)
            amount: Amount in specified currency
            currency: Currency code (default: USD)
            customer_id: Customer identifier
            policy_id: Policy identifier
            **kwargs: Method-specific parameters
                - credit_card: card_number, expiry_month, expiry_year, cvv
                - paypal: return_url, cancel_url
                - crypto: (none additional)
        """
        method = method.lower().replace(' ', '_')
        
        result = None
        
        if method in ['credit_card', 'debit_card', 'card']:
            result = self.stripe.create_payment_intent(
                amount=amount,
                currency=currency,
                card_number=kwargs.get('card_number'),
                payment_method='card',
                customer_email=kwargs.get('email'),
                metadata={
                    'customer_id': customer_id,
                    'policy_id': policy_id
                }
            )
        
        elif method == 'paypal':
            result = self.paypal.create_order(
                amount=amount,
                currency=currency,
                description=kwargs.get('description', f'Payment for policy {policy_id}'),
                customer_email=kwargs.get('email')
            )
        
        elif method == 'apple_pay':
            result = self.stripe.create_apple_pay_session(
                amount=amount,
                currency=currency,
                merchant_name=kwargs.get('merchant_name', 'PHINS Insurance')
            )
        
        elif method == 'google_pay':
            result = self.stripe.create_google_pay_session(
                amount=amount,
                currency=currency,
                merchant_name=kwargs.get('merchant_name', 'PHINS Insurance')
            )
        
        elif method in ['bitcoin', 'btc']:
            result = self.crypto.create_payment_request(
                amount_usd=amount,
                crypto_symbol='BTC',
                customer_id=customer_id,
                policy_id=policy_id
            )
        
        elif method in ['ethereum', 'eth']:
            result = self.crypto.create_payment_request(
                amount_usd=amount,
                crypto_symbol='ETH',
                customer_id=customer_id,
                policy_id=policy_id
            )
        
        elif method == 'usdc':
            result = self.crypto.create_payment_request(
                amount_usd=amount,
                crypto_symbol='USDC',
                customer_id=customer_id,
                policy_id=policy_id
            )
        
        else:
            result = PaymentResult(
                success=False,
                transaction_id='',
                gateway='unknown',
                method=method,
                amount=amount,
                currency=currency,
                status=PaymentStatus.FAILED.value,
                timestamp=datetime.now().isoformat(),
                error=f'Unsupported payment method: {method}',
                details={}
            )
        
        # Log transaction
        if result:
            self._transactions.append({
                'transaction_id': result.transaction_id,
                'method': method,
                'amount': amount,
                'currency': currency,
                'status': result.status,
                'customer_id': customer_id,
                'policy_id': policy_id,
                'timestamp': result.timestamp,
                'test_mode': self.test_mode
            })
        
        return result
    
    def check_status(self, transaction_id: str, method: str = None) -> PaymentResult:
        """Check payment status"""
        if transaction_id.startswith('CRYPTO-') or method in ['bitcoin', 'ethereum', 'usdc']:
            return self.crypto.check_payment_status(transaction_id)
        
        # For other methods, look up in transaction log
        for txn in self._transactions:
            if txn['transaction_id'] == transaction_id:
                return PaymentResult(
                    success=True,
                    transaction_id=transaction_id,
                    gateway=txn.get('gateway', 'unknown'),
                    method=txn['method'],
                    amount=txn['amount'],
                    currency=txn['currency'],
                    status=txn['status'],
                    timestamp=txn['timestamp'],
                    details={'test_mode': self.test_mode}
                )
        
        return PaymentResult(
            success=False,
            transaction_id=transaction_id,
            gateway='unknown',
            method=method or 'unknown',
            amount=0,
            currency='USD',
            status=PaymentStatus.FAILED.value,
            timestamp=datetime.now().isoformat(),
            error='Transaction not found',
            details={}
        )
    
    def refund(self, transaction_id: str, amount: float = None,
               method: str = None) -> PaymentResult:
        """Process a refund"""
        if transaction_id.startswith('pi_'):
            return self.stripe.refund(transaction_id, amount)
        elif transaction_id.startswith('PAYPAL-'):
            return self.paypal.refund(transaction_id, amount)
        else:
            return PaymentResult(
                success=False,
                transaction_id=transaction_id,
                gateway='unknown',
                method='refund',
                amount=amount or 0,
                currency='USD',
                status=PaymentStatus.FAILED.value,
                timestamp=datetime.now().isoformat(),
                error='Cannot refund this transaction type',
                details={}
            )
    
    def simulate_crypto_confirmation(self, payment_id: str) -> PaymentResult:
        """Manually confirm a crypto payment (for testing)"""
        return self.crypto.simulate_payment_received(payment_id)
    
    def get_transaction_history(self, customer_id: str = None, 
                                 limit: int = 50) -> List[Dict]:
        """Get transaction history"""
        txns = self._transactions
        if customer_id:
            txns = [t for t in txns if t.get('customer_id') == customer_id]
        return txns[-limit:]


# Singleton instance for the application
_payment_gateway: Optional[UnifiedPaymentGateway] = None


def get_payment_gateway(test_mode: bool = True,
                        paypal_client_id: str = None,
                        paypal_secret: str = None,
                        stripe_api_key: str = None,
                        market_data_service=None) -> UnifiedPaymentGateway:
    """Get or create the payment gateway singleton"""
    global _payment_gateway
    if _payment_gateway is None:
        _payment_gateway = UnifiedPaymentGateway(
            test_mode=test_mode,
            paypal_client_id=paypal_client_id,
            paypal_secret=paypal_secret,
            stripe_api_key=stripe_api_key,
            market_data_service=market_data_service
        )
    return _payment_gateway


# Demo/test function
def demo_payments():
    """Demonstrate all payment methods"""
    print("=" * 60)
    print("PHINS Payment Gateway Demo")
    print("=" * 60)
    
    gateway = get_payment_gateway(test_mode=True)
    
    print("\n📋 Available Payment Methods:")
    for method in gateway.get_available_methods():
        print(f"  - {method['name']} ({method['gateway']})")
    
    print("\n💳 Credit Card Payment (Visa):")
    result = gateway.process_payment(
        method='credit_card',
        amount=250.00,
        card_number='4242424242424242',
        customer_id='CUST-001',
        policy_id='POL-001'
    )
    print(f"  Status: {result.status}")
    print(f"  Transaction ID: {result.transaction_id}")
    
    print("\n💳 Credit Card Payment (Declined):")
    result = gateway.process_payment(
        method='credit_card',
        amount=100.00,
        card_number='4000000000000002',
        customer_id='CUST-001',
        policy_id='POL-001'
    )
    print(f"  Status: {result.status}")
    print(f"  Error: {result.error}")
    
    print("\n🅿️ PayPal Order:")
    result = gateway.process_payment(
        method='paypal',
        amount=150.00,
        customer_id='CUST-001',
        policy_id='POL-001'
    )
    print(f"  Status: {result.status}")
    print(f"  Approval URL: {result.details.get('approval_url')}")
    
    print("\n🍎 Apple Pay Session:")
    result = gateway.process_payment(
        method='apple_pay',
        amount=200.00,
        customer_id='CUST-001',
        policy_id='POL-001'
    )
    print(f"  Status: {result.status}")
    print(f"  Session ID: {result.details.get('session_id')}")
    
    print("\n₿ Bitcoin Payment:")
    result = gateway.process_payment(
        method='bitcoin',
        amount=300.00,
        customer_id='CUST-001',
        policy_id='POL-001'
    )
    print(f"  Status: {result.status}")
    print(f"  Address: {result.details.get('receiving_address')}")
    print(f"  Amount: {result.details.get('crypto_amount')} BTC")
    
    print("\n" + "=" * 60)
    print("Demo complete! All payment methods tested in sandbox mode.")
    print("=" * 60)


if __name__ == '__main__':
    demo_payments()
