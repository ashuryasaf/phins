#!/usr/bin/env python3
"""
PHINS External Services Validation Script

This script validates that all external services are properly configured
before deployment. Run this before deploying to production.

Usage:
    python validate_external_services.py

Exit codes:
    0 - All validations passed
    1 - Some validations failed (check output for details)
"""

import os
import sys
import json
from datetime import datetime


class ValidationResult:
    """Results of a validation check"""
    def __init__(self, name: str, passed: bool, message: str = "", details: dict = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or {}


class ServiceValidator:
    """Validates external service configurations"""
    
    def __init__(self):
        self.results = []
        
    def add_result(self, result: ValidationResult):
        self.results.append(result)
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"{status}: {result.name}")
        if result.message:
            print(f"       {result.message}")
        
    def validate_all(self):
        """Run all validations"""
        print("=" * 60)
        print("PHINS External Services Validation")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("=" * 60)
        print()
        
        # Core validations
        print("--- Environment Configuration ---")
        self.validate_environment()
        print()
        
        print("--- Database Connection ---")
        self.validate_database()
        print()
        
        print("--- Email Service ---")
        self.validate_email()
        print()
        
        print("--- SMS Service ---")
        self.validate_sms()
        print()
        
        print("--- CAPTCHA Service ---")
        self.validate_captcha()
        print()
        
        print("--- Payment Gateways ---")
        self.validate_payments()
        print()
        
        print("--- Security Configuration ---")
        self.validate_security()
        print()
        
        # Summary
        self.print_summary()
        
        # Return exit code
        return 0 if all(r.passed for r in self.results) else 1
    
    def validate_environment(self):
        """Validate basic environment configuration"""
        # Check PHINS_ENV
        env = os.environ.get('PHINS_ENV', 'development')
        self.add_result(ValidationResult(
            "PHINS_ENV set",
            env in ['development', 'staging', 'production'],
            f"Current: {env}"
        ))
        
        # Check USE_DATABASE
        use_db = os.environ.get('USE_DATABASE', '0')
        self.add_result(ValidationResult(
            "USE_DATABASE enabled",
            use_db == '1',
            f"Current: {use_db} (should be 1 for production)"
        ))
    
    def validate_database(self):
        """Validate database configuration and connection"""
        db_url = os.environ.get('DATABASE_URL', '')
        use_sqlite = os.environ.get('USE_SQLITE', '0') == '1'
        
        if use_sqlite:
            self.add_result(ValidationResult(
                "Database configuration",
                True,
                "Using SQLite (development mode)"
            ))
        elif db_url:
            # Check PostgreSQL URL format
            is_postgres = db_url.startswith('postgresql://')
            self.add_result(ValidationResult(
                "PostgreSQL URL configured",
                is_postgres,
                "URL format valid" if is_postgres else "URL should start with postgresql://"
            ))
            
            # Try to connect
            if is_postgres:
                try:
                    from sqlalchemy import create_engine
                    engine = create_engine(db_url, pool_pre_ping=True)
                    with engine.connect() as conn:
                        conn.execute("SELECT 1")
                    self.add_result(ValidationResult(
                        "Database connection",
                        True,
                        "Successfully connected to PostgreSQL"
                    ))
                except Exception as e:
                    self.add_result(ValidationResult(
                        "Database connection",
                        False,
                        f"Connection failed: {str(e)[:100]}"
                    ))
        else:
            self.add_result(ValidationResult(
                "Database configuration",
                False,
                "DATABASE_URL not set and USE_SQLITE not enabled"
            ))
    
    def validate_email(self):
        """Validate email service configuration"""
        provider_aliases = {
            'send-grid': 'sendgrid',
            'send_grid': 'sendgrid',
            'sg': 'sendgrid',
            'aws_ses': 'ses',
            'aws-ses': 'ses',
            'amazon_ses': 'ses',
            'amazon-ses': 'ses',
            'mail-gun': 'mailgun',
            'mail_gun': 'mailgun',
            'resend_api': 'resend',
            'resend-api': 'resend',
        }
        provider_raw = str(os.environ.get('EMAIL_PROVIDER', 'smtp') or 'smtp').strip().lower()
        provider = provider_aliases.get(provider_raw, provider_raw or 'smtp')

        from_addr = (
            os.environ.get('NOTIFICATION_FROM_ADDRESS')
            or os.environ.get('DEFAULT_FROM_EMAIL')
            or os.environ.get('MAIL_FROM')
            or os.environ.get('MAIL_FROM_ADDRESS')
            or os.environ.get('EMAIL_FROM_ADDRESS')
            or ''
        ).strip()
        if not from_addr:
            if provider == 'sendgrid':
                from_addr = (
                    os.environ.get('SENDGRID_FROM_ADDRESS')
                    or os.environ.get('SENDGRID_FROM_EMAIL')
                    or os.environ.get('SENDGRID_SENDER_EMAIL')
                    or ''
                ).strip()
            elif provider == 'mailgun':
                from_addr = (
                    os.environ.get('MAILGUN_FROM_ADDRESS')
                    or os.environ.get('MAILGUN_FROM_EMAIL')
                    or ''
                ).strip()
            elif provider == 'ses':
                from_addr = (
                    os.environ.get('SES_FROM_ADDRESS')
                    or os.environ.get('AWS_SES_FROM_ADDRESS')
                    or os.environ.get('AWS_SES_FROM_EMAIL')
                    or ''
                ).strip()
            elif provider == 'resend':
                from_addr = (
                    os.environ.get('RESEND_FROM_ADDRESS')
                    or os.environ.get('RESEND_FROM_EMAIL')
                    or ''
                ).strip()
        
        self.add_result(ValidationResult(
            "Email provider configured",
            provider in ['smtp', 'sendgrid', 'ses', 'mailgun', 'resend'],
            f"Provider: {provider}"
        ))
        
        self.add_result(ValidationResult(
            "Email FROM address set",
            bool(from_addr) and '@' in from_addr,
            f"Address: {from_addr}" if from_addr else "Not configured"
        ))

        otp_from_addr = (
            os.environ.get('PHINS_OTP_FROM_ADDRESS')
            or os.environ.get('OTP_FROM_ADDRESS')
            or from_addr
        ).strip()
        self.add_result(ValidationResult(
            "OTP sender address set",
            bool(otp_from_addr) and '@' in otp_from_addr,
            f"OTP sender: {otp_from_addr}" if otp_from_addr else "Not configured"
        ))
        
        # Provider-specific checks
        if provider == 'smtp':
            smtp_host = os.environ.get('SMTP_HOST', '')
            smtp_user = os.environ.get('SMTP_USERNAME', '')
            self.add_result(ValidationResult(
                "SMTP credentials",
                bool(smtp_host),
                f"Host: {smtp_host}" if smtp_host else "SMTP_HOST not set"
            ))
        elif provider == 'sendgrid':
            api_key = os.environ.get('SENDGRID_API_KEY', '')
            self.add_result(ValidationResult(
                "SendGrid API key",
                bool(api_key) and api_key.startswith('SG.'),
                "API key configured" if api_key else "SENDGRID_API_KEY not set"
            ))
        elif provider == 'ses':
            aws_key = os.environ.get('AWS_ACCESS_KEY_ID', '')
            aws_region = os.environ.get('AWS_SES_REGION', '')
            self.add_result(ValidationResult(
                "AWS SES credentials",
                bool(aws_key) and bool(aws_region),
                f"Region: {aws_region}" if aws_region else "AWS credentials not fully configured"
            ))
        elif provider == 'resend':
            api_key = os.environ.get('RESEND_API_KEY', '')
            self.add_result(ValidationResult(
                "Resend API key",
                bool(api_key),
                "API key configured" if api_key else "RESEND_API_KEY not set"
            ))
    
    def validate_sms(self):
        """Validate SMS service configuration"""
        provider = os.environ.get('SMS_PROVIDER', 'twilio')
        
        self.add_result(ValidationResult(
            "SMS provider configured",
            provider in ['twilio', 'sns', 'vonage', 'messagebird'],
            f"Provider: {provider}"
        ))
        
        if provider == 'twilio':
            sid = os.environ.get('TWILIO_ACCOUNT_SID', '')
            token = os.environ.get('TWILIO_AUTH_TOKEN', '')
            from_num = os.environ.get('TWILIO_FROM_NUMBER', '')
            
            has_creds = bool(sid) and bool(token)
            self.add_result(ValidationResult(
                "Twilio credentials",
                has_creds,
                "Credentials configured" if has_creds else "Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN"
            ))
            
            self.add_result(ValidationResult(
                "Twilio FROM number",
                bool(from_num) and from_num.startswith('+'),
                f"Number: {from_num}" if from_num else "TWILIO_FROM_NUMBER not set"
            ))
        elif provider == 'sns':
            aws_key = os.environ.get('AWS_ACCESS_KEY_ID', '')
            self.add_result(ValidationResult(
                "AWS SNS credentials",
                bool(aws_key),
                "AWS credentials configured" if aws_key else "AWS credentials not set"
            ))
        elif provider == 'vonage':
            api_key = os.environ.get('VONAGE_API_KEY', '')
            self.add_result(ValidationResult(
                "Vonage credentials",
                bool(api_key),
                "Credentials configured" if api_key else "VONAGE_API_KEY not set"
            ))
    
    def validate_captcha(self):
        """Validate CAPTCHA configuration"""
        enabled = os.environ.get('CAPTCHA_ENABLED', 'true').lower() == 'true'
        captcha_type = os.environ.get('CAPTCHA_TYPE', 'simple')
        
        self.add_result(ValidationResult(
            "CAPTCHA enabled",
            enabled,
            "CAPTCHA is enabled" if enabled else "CAPTCHA is disabled (not recommended)"
        ))
        
        self.add_result(ValidationResult(
            "CAPTCHA type configured",
            captcha_type in ['simple', 'hcaptcha', 'recaptcha'],
            f"Type: {captcha_type}"
        ))
        
        if captcha_type == 'hcaptcha':
            secret = os.environ.get('HCAPTCHA_SECRET', '')
            site_key = os.environ.get('HCAPTCHA_SITE_KEY', '')
            self.add_result(ValidationResult(
                "hCaptcha credentials",
                bool(secret) and bool(site_key),
                "Credentials configured" if (secret and site_key) else "Missing hCaptcha keys"
            ))
        elif captcha_type == 'recaptcha':
            secret = os.environ.get('RECAPTCHA_SECRET', '')
            site_key = os.environ.get('RECAPTCHA_SITE_KEY', '')
            self.add_result(ValidationResult(
                "reCAPTCHA credentials",
                bool(secret) and bool(site_key),
                "Credentials configured" if (secret and site_key) else "Missing reCAPTCHA keys"
            ))
    
    def validate_payments(self):
        """Validate payment gateway configuration"""
        # Stripe
        stripe_key = os.environ.get('STRIPE_API_KEY', '')
        if stripe_key:
            is_live = stripe_key.startswith('sk_live_')
            is_test = stripe_key.startswith('sk_test_')
            self.add_result(ValidationResult(
                "Stripe configured",
                is_live or is_test,
                f"Mode: {'LIVE' if is_live else 'TEST' if is_test else 'Invalid key'}"
            ))
        else:
            self.add_result(ValidationResult(
                "Stripe configured",
                False,
                "STRIPE_API_KEY not set (payments will fail)"
            ))
        
        # PayPal
        paypal_id = os.environ.get('PAYPAL_CLIENT_ID', '')
        paypal_sandbox = os.environ.get('PAYPAL_SANDBOX', 'true').lower()
        if paypal_id:
            self.add_result(ValidationResult(
                "PayPal configured",
                True,
                f"Mode: {'SANDBOX' if paypal_sandbox == 'true' else 'LIVE'}"
            ))
        else:
            self.add_result(ValidationResult(
                "PayPal configured",
                False,
                "PAYPAL_CLIENT_ID not set (PayPal payments will fail)"
            ))
    
    def validate_security(self):
        """Validate security configuration"""
        # Secret key
        secret_key = os.environ.get('SECRET_KEY', '')
        self.add_result(ValidationResult(
            "SECRET_KEY configured",
            len(secret_key) >= 32,
            f"Length: {len(secret_key)} chars" if secret_key else "Not set (CRITICAL)"
        ))
        
        # Vault key
        vault_key = os.environ.get('VAULT_KEY', '')
        self.add_result(ValidationResult(
            "VAULT_KEY configured",
            len(vault_key) >= 16,
            f"Length: {len(vault_key)} chars" if vault_key else "Not set (actuarial encryption disabled)"
        ))
        
        # Encryption key
        enc_key = os.environ.get('PHINS_ENCRYPTION_KEY', '')
        self.add_result(ValidationResult(
            "PHINS_ENCRYPTION_KEY configured",
            bool(enc_key),
            "Configured" if enc_key else "Not set (some features may not work)"
        ))
        
        # Rate limiting
        rate_limit = os.environ.get('RATE_LIMIT_ENABLED', 'true').lower() == 'true'
        self.add_result(ValidationResult(
            "Rate limiting enabled",
            rate_limit,
            "Enabled" if rate_limit else "Disabled (not recommended for production)"
        ))
    
    def print_summary(self):
        """Print validation summary"""
        print("=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        
        print(f"Total checks: {len(self.results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print()
        
        if failed > 0:
            print("⚠️  FAILED CHECKS:")
            for r in self.results:
                if not r.passed:
                    print(f"   - {r.name}: {r.message}")
            print()
            print("❌ DO NOT DEPLOY - Fix the issues above first")
        else:
            print("✅ ALL CHECKS PASSED - Ready for deployment")
        
        print("=" * 60)


def main():
    """Main entry point"""
    validator = ServiceValidator()
    exit_code = validator.validate_all()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
