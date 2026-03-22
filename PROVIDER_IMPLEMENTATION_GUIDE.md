# PHINS Provider Implementation Guide

This guide provides code templates for implementing additional email and SMS providers in the PHINS notification system.

## Table of Contents

1. [Email Provider Implementations](#1-email-provider-implementations)
2. [SMS Provider Implementations](#2-sms-provider-implementations)
3. [CAPTCHA Integration](#3-captcha-integration)
4. [Testing Providers](#4-testing-providers)

---

## 1. Email Provider Implementations

All email providers inherit from `EmailProvider` in `services/notification_service.py`.

### 1.1 SendGrid Provider

Add this class to `services/notification_service.py`:

```python
class SendGridEmailProvider(EmailProvider):
    """SendGrid email provider"""
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via SendGrid API"""
        try:
            import urllib.request
            import urllib.error
            
            api_key = NotificationConfig.SENDGRID_API_KEY
            if not api_key:
                logger.warning("SendGrid API key not configured, falling back to mock")
                return MockEmailProvider().send(to, subject, body, html_body, from_address, from_name)
            
            from_addr = from_address or NotificationConfig.EMAIL_FROM_ADDRESS
            from_display = from_name or NotificationConfig.EMAIL_FROM_NAME
            
            # Build SendGrid API payload
            payload = {
                "personalizations": [{
                    "to": [{"email": to}]
                }],
                "from": {
                    "email": from_addr,
                    "name": from_display
                },
                "subject": subject,
                "content": []
            }
            
            # Add text content
            payload["content"].append({
                "type": "text/plain",
                "value": body
            })
            
            # Add HTML content if provided
            if html_body:
                payload["content"].append({
                    "type": "text/html",
                    "value": html_body
                })
            
            # Add reply-to if provided
            if reply_to:
                payload["reply_to"] = {"email": reply_to}
            
            # Make API request
            url = "https://api.sendgrid.com/v3/mail/send"
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Authorization', f'Bearer {api_key}')
            req.add_header('Content-Type', 'application/json')
            
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    # SendGrid returns 202 Accepted on success
                    if response.status in [200, 202]:
                        # Extract message ID from headers
                        message_id = response.headers.get('X-Message-Id', generate_id('SG'))
                        return True, message_id, None
                    return False, None, f"Unexpected status: {response.status}"
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"SendGrid API error: {e.code} - {error_body}")
                return False, None, f"SendGrid error: {e.code}"
                
        except Exception as e:
            logger.error(f"SendGrid send error: {str(e)}")
            return False, None, str(e)
```

### 1.2 AWS SES Provider

Add this class to `services/notification_service.py`:

```python
class AWSSESEmailProvider(EmailProvider):
    """AWS Simple Email Service provider"""
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via AWS SES"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            region = NotificationConfig.AWS_SES_REGION
            
            # Create SES client
            ses = boto3.client('ses', region_name=region)
            
            from_addr = from_address or NotificationConfig.EMAIL_FROM_ADDRESS
            from_display = from_name or NotificationConfig.EMAIL_FROM_NAME
            
            # Build message
            message = {
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': body, 'Charset': 'UTF-8'}
                }
            }
            
            if html_body:
                message['Body']['Html'] = {'Data': html_body, 'Charset': 'UTF-8'}
            
            # Build destination
            destination = {'ToAddresses': [to]}
            
            # Build source
            source = f"{from_display} <{from_addr}>" if from_display else from_addr
            
            # Send email
            kwargs = {
                'Source': source,
                'Destination': destination,
                'Message': message
            }
            
            if reply_to:
                kwargs['ReplyToAddresses'] = [reply_to]
            
            response = ses.send_email(**kwargs)
            message_id = response.get('MessageId', generate_id('SES'))
            
            return True, message_id, None
            
        except ClientError as e:
            error = e.response['Error']
            logger.error(f"AWS SES error: {error['Code']} - {error['Message']}")
            return False, None, f"SES error: {error['Message']}"
        except Exception as e:
            logger.error(f"AWS SES send error: {str(e)}")
            return False, None, str(e)
```

### 1.3 Mailgun Provider

```python
class MailgunEmailProvider(EmailProvider):
    """Mailgun email provider"""
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via Mailgun API"""
        try:
            import urllib.request
            import urllib.parse
            import base64
            
            api_key = NotificationConfig.MAILGUN_API_KEY
            domain = NotificationConfig.MAILGUN_DOMAIN
            
            if not api_key or not domain:
                logger.warning("Mailgun not configured, falling back to mock")
                return MockEmailProvider().send(to, subject, body, html_body, from_address, from_name)
            
            from_addr = from_address or NotificationConfig.EMAIL_FROM_ADDRESS
            from_display = from_name or NotificationConfig.EMAIL_FROM_NAME
            
            # Build form data
            data = {
                'from': f"{from_display} <{from_addr}>" if from_display else from_addr,
                'to': to,
                'subject': subject,
                'text': body
            }
            
            if html_body:
                data['html'] = html_body
            
            if reply_to:
                data['h:Reply-To'] = reply_to
            
            # Make API request
            url = f"https://api.mailgun.net/v3/{domain}/messages"
            encoded_data = urllib.parse.urlencode(data).encode('utf-8')
            
            auth = base64.b64encode(f"api:{api_key}".encode()).decode()
            
            req = urllib.request.Request(url, data=encoded_data, method='POST')
            req.add_header('Authorization', f'Basic {auth}')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                message_id = result.get('id', generate_id('MG'))
                return True, message_id, None
                
        except Exception as e:
            logger.error(f"Mailgun send error: {str(e)}")
            return False, None, str(e)
```

---

## 2. SMS Provider Implementations

All SMS providers inherit from `SMSProvider` in `services/notification_service.py`.

### 2.1 AWS SNS Provider

```python
class AWSSNSProvider(SMSProvider):
    """AWS SNS SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via AWS SNS"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            region = NotificationConfig.AWS_SNS_REGION
            
            # Create SNS client
            sns = boto3.client('sns', region_name=region)
            
            # Normalize phone number
            phone = normalize_phone(to)
            
            # Send SMS
            response = sns.publish(
                PhoneNumber=phone,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'  # OTP messages should be transactional
                    }
                }
            )
            
            message_id = response.get('MessageId', generate_id('SNS'))
            return True, message_id, None
            
        except ClientError as e:
            error = e.response['Error']
            logger.error(f"AWS SNS error: {error['Code']} - {error['Message']}")
            return False, None, f"SNS error: {error['Message']}"
        except Exception as e:
            logger.error(f"AWS SNS send error: {str(e)}")
            return False, None, str(e)
```

### 2.2 Vonage (Nexmo) Provider

```python
class VonageSMSProvider(SMSProvider):
    """Vonage (Nexmo) SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via Vonage API"""
        try:
            import urllib.request
            import urllib.parse
            
            api_key = NotificationConfig.VONAGE_API_KEY
            api_secret = NotificationConfig.VONAGE_API_SECRET
            
            if not api_key or not api_secret:
                logger.warning("Vonage not configured, falling back to mock")
                return MockSMSProvider().send(to, message, from_number)
            
            # Normalize phone number
            phone = normalize_phone(to)
            
            # Build request
            url = "https://rest.nexmo.com/sms/json"
            data = {
                'api_key': api_key,
                'api_secret': api_secret,
                'to': phone,
                'from': from_number or 'PHINS',
                'text': message
            }
            
            encoded_data = urllib.parse.urlencode(data).encode('utf-8')
            
            req = urllib.request.Request(url, data=encoded_data, method='POST')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                
                if result.get('messages'):
                    msg = result['messages'][0]
                    if msg.get('status') == '0':
                        return True, msg.get('message-id', generate_id('VNG')), None
                    else:
                        return False, None, f"Vonage error: {msg.get('error-text', 'Unknown')}"
                
                return False, None, "No response from Vonage"
                
        except Exception as e:
            logger.error(f"Vonage send error: {str(e)}")
            return False, None, str(e)
```

### 2.3 MessageBird Provider

```python
class MessageBirdSMSProvider(SMSProvider):
    """MessageBird SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via MessageBird API"""
        try:
            import urllib.request
            
            api_key = NotificationConfig.MESSAGEBIRD_API_KEY
            
            if not api_key:
                logger.warning("MessageBird not configured, falling back to mock")
                return MockSMSProvider().send(to, message, from_number)
            
            # Normalize phone number
            phone = normalize_phone(to)
            
            # Build request
            url = "https://rest.messagebird.com/messages"
            payload = {
                'recipients': [phone],
                'originator': from_number or 'PHINS',
                'body': message
            }
            
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Authorization', f'AccessKey {api_key}')
            req.add_header('Content-Type', 'application/json')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                message_id = result.get('id', generate_id('MB'))
                return True, message_id, None
                
        except Exception as e:
            logger.error(f"MessageBird send error: {str(e)}")
            return False, None, str(e)
```

---

## 3. CAPTCHA Integration

### 3.1 Frontend Integration for hCaptcha

Add to your login/registration HTML:

```html
<!-- Add in <head> -->
<script src="https://js.hcaptcha.com/1/api.js" async defer></script>

<!-- Add in form -->
<div class="h-captcha" data-sitekey="YOUR_SITE_KEY"></div>

<!-- Form submission -->
<script>
document.querySelector('form').addEventListener('submit', function(e) {
    const captchaResponse = hcaptcha.getResponse();
    if (!captchaResponse) {
        e.preventDefault();
        alert('Please complete the CAPTCHA');
        return;
    }
    // Include captchaResponse in your API call
});
</script>
```

### 3.2 Frontend Integration for reCAPTCHA v2

```html
<!-- Add in <head> -->
<script src="https://www.google.com/recaptcha/api.js" async defer></script>

<!-- Add in form -->
<div class="g-recaptcha" data-sitekey="YOUR_SITE_KEY"></div>

<!-- Form submission -->
<script>
document.querySelector('form').addEventListener('submit', function(e) {
    const captchaResponse = grecaptcha.getResponse();
    if (!captchaResponse) {
        e.preventDefault();
        alert('Please complete the CAPTCHA');
        return;
    }
    // Include captchaResponse in your API call
});
</script>
```

---

## 4. Testing Providers

### 4.1 Test Email Sending

```python
#!/usr/bin/env python3
"""Test email provider"""

import os
os.environ['EMAIL_PROVIDER'] = 'smtp'  # or sendgrid, ses
os.environ['SMTP_HOST'] = 'smtp.gmail.com'
os.environ['SMTP_PORT'] = '587'
os.environ['SMTP_USERNAME'] = 'your-email@gmail.com'
os.environ['SMTP_PASSWORD'] = 'your-app-password'
os.environ['EMAIL_FROM_ADDRESS'] = 'your-email@gmail.com'

from services.notification_service import create_notification_service, NotificationRequest, NotificationChannel

service = create_notification_service(use_mock=False)

result = service.send(NotificationRequest(
    channel=NotificationChannel.EMAIL,
    recipient="test@example.com",
    subject="Test Email from PHINS",
    content="This is a test email to verify the provider is working."
))

print(f"Success: {result.success}")
print(f"Message ID: {result.provider_message_id}")
if result.error_message:
    print(f"Error: {result.error_message}")
```

### 4.2 Test SMS Sending

```python
#!/usr/bin/env python3
"""Test SMS provider"""

import os
os.environ['SMS_PROVIDER'] = 'twilio'
os.environ['TWILIO_ACCOUNT_SID'] = 'your-sid'
os.environ['TWILIO_AUTH_TOKEN'] = 'your-token'
os.environ['TWILIO_FROM_NUMBER'] = '+1234567890'

from services.notification_service import create_notification_service, NotificationRequest, NotificationChannel

service = create_notification_service(use_mock=False)

result = service.send(NotificationRequest(
    channel=NotificationChannel.SMS,
    recipient="+1234567890",
    content="Test SMS from PHINS"
))

print(f"Success: {result.success}")
print(f"Message ID: {result.provider_message_id}")
if result.error_message:
    print(f"Error: {result.error_message}")
```

### 4.3 Test OTP Flow

```python
#!/usr/bin/env python3
"""Test OTP verification flow"""

from services.notification_service import (
    create_notification_service,
    OTPRequest,
    NotificationChannel,
    VerificationType
)

# Create service (use_mock=True for testing without real providers)
service = create_notification_service(use_mock=True)

# Send OTP
otp_result = service.send_otp(OTPRequest(
    identifier="test@example.com",
    channel=NotificationChannel.EMAIL,
    verification_type=VerificationType.EMAIL_VERIFICATION,
    customer_id="TEST001"
))

print(f"OTP Sent: {otp_result.success}")
print(f"OTP ID: {otp_result.otp_id}")
print(f"Expires: {otp_result.expires_at}")

# In real usage, user would receive OTP via email/SMS
# For testing with mock, check the mock provider's sent_emails list
if hasattr(service._email_provider, 'sent_emails'):
    last_email = service._email_provider.sent_emails[-1]
    print(f"Email sent to: {last_email['to']}")
    print(f"Subject: {last_email['subject']}")

# Verify OTP (in real usage, user provides the code they received)
# For this test, we need to extract the code - in mock mode it's visible
verify_result = service.verify_otp(
    identifier="test@example.com",
    code="123456",  # This would be the actual code received
    verification_type=VerificationType.EMAIL_VERIFICATION
)

print(f"Verification: {verify_result.success}")
```

---

## 5. Provider Factory Update

Update the `create_notification_service` function to support new providers:

```python
def create_notification_service(
    use_mock: bool = True,
    email_provider: Optional[EmailProvider] = None,
    sms_provider: Optional[SMSProvider] = None
) -> NotificationService:
    """
    Factory function to create NotificationService with appropriate providers.
    """
    if use_mock:
        email = MockEmailProvider()
        sms = MockSMSProvider()
    else:
        # Email provider selection
        if email_provider:
            email = email_provider
        else:
            provider_type = NotificationConfig.EMAIL_PROVIDER.lower()
            if provider_type == 'sendgrid':
                email = SendGridEmailProvider()
            elif provider_type == 'ses':
                email = AWSSESEmailProvider()
            elif provider_type == 'mailgun':
                email = MailgunEmailProvider()
            else:  # default to SMTP
                email = SMTPEmailProvider()
        
        # SMS provider selection
        if sms_provider:
            sms = sms_provider
        else:
            provider_type = NotificationConfig.SMS_PROVIDER.lower()
            if provider_type == 'sns':
                sms = AWSSNSProvider()
            elif provider_type == 'vonage':
                sms = VonageSMSProvider()
            elif provider_type == 'messagebird':
                sms = MessageBirdSMSProvider()
            else:  # default to Twilio
                sms = TwilioSMSProvider()
    
    return NotificationService(
        email_provider=email,
        sms_provider=sms
    )
```

---

## Quick Reference: Environment Variables per Provider

| Provider | Required Variables |
|----------|-------------------|
| **SMTP** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` |
| **SendGrid** | `SENDGRID_API_KEY` |
| **AWS SES** | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SES_REGION` |
| **Mailgun** | `MAILGUN_API_KEY`, `MAILGUN_DOMAIN` |
| **Twilio** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` |
| **AWS SNS** | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SNS_REGION` |
| **Vonage** | `VONAGE_API_KEY`, `VONAGE_API_SECRET` |
| **MessageBird** | `MESSAGEBIRD_API_KEY` |
| **hCaptcha** | `HCAPTCHA_SECRET`, `HCAPTCHA_SITE_KEY` |
| **reCAPTCHA** | `RECAPTCHA_SECRET`, `RECAPTCHA_SITE_KEY` |
| **Gemini / Veo** | `GEMINI_API_KEY` |
| **Kling** | `KLING_API_KEY` |

---

**Document Version**: 1.0  
**Created**: January 28, 2026
