#!/usr/bin/env python3
"""
Email Sender for PHINS Platform Architecture UML PDF

This script sends the architecture PDF document via email.

USAGE:
------
1. Set your email credentials (choose one method):

   Method A - Environment Variables (Recommended):
   $ export EMAIL_SENDER="your-email@gmail.com"
   $ export EMAIL_PASSWORD="your-app-password"
   $ export EMAIL_RECIPIENT="recipient@example.com"
   $ python3 send_architecture_pdf.py

   Method B - Edit the CONFIG section below directly

2. For Gmail users:
   - Enable 2-Factor Authentication on your Google account
   - Generate an App Password: https://myaccount.google.com/apppasswords
   - Use the App Password (not your regular password)

3. Run the script:
   $ python3 send_architecture_pdf.py

SUPPORTED PROVIDERS:
-------------------
- Gmail (smtp.gmail.com)
- Outlook/Hotmail (smtp-mail.outlook.com)
- Yahoo (smtp.mail.yahoo.com)
- SendGrid (smtp.sendgrid.net)
- Custom SMTP server
"""

import smtplib
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

# ============================================================================
# CONFIGURATION - Edit these values OR use environment variables
# ============================================================================

CONFIG = {
    # Email Provider: 'gmail', 'outlook', 'yahoo', 'sendgrid', or 'custom'
    'provider': 'gmail',
    
    # Your email address (sender)
    'sender_email': os.environ.get('EMAIL_SENDER', 'your-email@gmail.com'),
    
    # Your email password or app password
    'sender_password': os.environ.get('EMAIL_PASSWORD', 'your-app-password'),
    
    # Recipient email address
    'recipient_email': os.environ.get('EMAIL_RECIPIENT', 'recipient@example.com'),
    
    # Custom SMTP settings (only if provider='custom')
    'custom_smtp_server': os.environ.get('SMTP_SERVER', 'smtp.example.com'),
    'custom_smtp_port': int(os.environ.get('SMTP_PORT', '587')),
}

# PDF file to send
PDF_FILE = '/workspace/PLATFORM_ARCHITECTURE_UML.pdf'

# ============================================================================
# SMTP Server Settings
# ============================================================================

SMTP_SETTINGS = {
    'gmail': {
        'server': 'smtp.gmail.com',
        'port': 587,
        'use_tls': True,
    },
    'outlook': {
        'server': 'smtp-mail.outlook.com',
        'port': 587,
        'use_tls': True,
    },
    'yahoo': {
        'server': 'smtp.mail.yahoo.com',
        'port': 587,
        'use_tls': True,
    },
    'sendgrid': {
        'server': 'smtp.sendgrid.net',
        'port': 587,
        'use_tls': True,
    },
    'custom': {
        'server': CONFIG['custom_smtp_server'],
        'port': CONFIG['custom_smtp_port'],
        'use_tls': True,
    },
}

# ============================================================================
# Email Content
# ============================================================================

def create_email_content():
    """Create the email subject and body."""
    subject = "PHINS Platform - Database Architecture UML Document"
    
    body_html = """
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #1a5276;">PHINS Insurance Platform - Architecture Documentation</h2>
        
        <p>Please find attached the <strong>Database Architecture UML Document</strong> for the PHINS Insurance Platform.</p>
        
        <h3 style="color: #2874a6;">Document Contents:</h3>
        <ul>
            <li>Entity-Relationship Diagram (ERD)</li>
            <li>Table Relationships Summary</li>
            <li>System Layer Architecture (3-Tier Component Diagram)</li>
            <li>Data Flow Diagram - Policy Lifecycle</li>
            <li>Class Diagram (ORM Models)</li>
            <li>Database Index Strategy</li>
            <li>Sequence Diagram - New Policy Application</li>
            <li>Deployment Architecture</li>
            <li>Security Model (Authentication, Encryption, RBAC)</li>
        </ul>
        
        <h3 style="color: #2874a6;">Platform Summary:</h3>
        <table style="border-collapse: collapse; margin: 10px 0;">
            <tr>
                <td style="padding: 5px 15px; border: 1px solid #ddd;"><strong>Database Tables</strong></td>
                <td style="padding: 5px 15px; border: 1px solid #ddd;">10</td>
            </tr>
            <tr>
                <td style="padding: 5px 15px; border: 1px solid #ddd;"><strong>ORM Models</strong></td>
                <td style="padding: 5px 15px; border: 1px solid #ddd;">10</td>
            </tr>
            <tr>
                <td style="padding: 5px 15px; border: 1px solid #ddd;"><strong>Repositories</strong></td>
                <td style="padding: 5px 15px; border: 1px solid #ddd;">10</td>
            </tr>
            <tr>
                <td style="padding: 5px 15px; border: 1px solid #ddd;"><strong>Services</strong></td>
                <td style="padding: 5px 15px; border: 1px solid #ddd;">7</td>
            </tr>
            <tr>
                <td style="padding: 5px 15px; border: 1px solid #ddd;"><strong>Architecture</strong></td>
                <td style="padding: 5px 15px; border: 1px solid #ddd;">3-Tier (Presentation → Application → Data)</td>
            </tr>
        </table>
        
        <p style="margin-top: 20px; padding: 10px; background-color: #f8f9fa; border-left: 4px solid #1a5276;">
            <em>Generated: {date}</em>
        </p>
        
        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
        <p style="color: #666; font-size: 12px;">
            This is an automated email from the PHINS Insurance Platform documentation system.
        </p>
    </body>
    </html>
    """.format(date=datetime.now().strftime('%B %d, %Y'))
    
    body_text = """
PHINS Insurance Platform - Architecture Documentation

Please find attached the Database Architecture UML Document for the PHINS Insurance Platform.

Document Contents:
- Entity-Relationship Diagram (ERD)
- Table Relationships Summary
- System Layer Architecture (3-Tier Component Diagram)
- Data Flow Diagram - Policy Lifecycle
- Class Diagram (ORM Models)
- Database Index Strategy
- Sequence Diagram - New Policy Application
- Deployment Architecture
- Security Model (Authentication, Encryption, RBAC)

Generated: {date}
    """.format(date=datetime.now().strftime('%B %d, %Y'))
    
    return subject, body_text, body_html


def send_email():
    """Send the email with the PDF attachment."""
    
    # Validate configuration
    if CONFIG['sender_email'] == 'your-email@gmail.com':
        print("=" * 60)
        print("ERROR: Please configure your email settings!")
        print("=" * 60)
        print("\nEdit the CONFIG section in this script or set environment variables:")
        print("\n  export EMAIL_SENDER='your-email@gmail.com'")
        print("  export EMAIL_PASSWORD='your-app-password'")
        print("  export EMAIL_RECIPIENT='recipient@example.com'")
        print("\nThen run: python3 send_architecture_pdf.py")
        print("=" * 60)
        return False
    
    # Check if PDF exists
    if not os.path.exists(PDF_FILE):
        print(f"ERROR: PDF file not found: {PDF_FILE}")
        return False
    
    # Get SMTP settings
    provider = CONFIG['provider']
    if provider not in SMTP_SETTINGS:
        print(f"ERROR: Unknown provider '{provider}'")
        return False
    
    smtp_config = SMTP_SETTINGS[provider]
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['From'] = CONFIG['sender_email']
    msg['To'] = CONFIG['recipient_email']
    
    subject, body_text, body_html = create_email_content()
    msg['Subject'] = subject
    
    # Attach text and HTML versions
    msg.attach(MIMEText(body_text, 'plain'))
    msg.attach(MIMEText(body_html, 'html'))
    
    # Attach PDF
    with open(PDF_FILE, 'rb') as f:
        pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
        pdf_attachment.add_header(
            'Content-Disposition', 
            'attachment', 
            filename='PLATFORM_ARCHITECTURE_UML.pdf'
        )
        msg.attach(pdf_attachment)
    
    # Send email
    print(f"Connecting to {smtp_config['server']}:{smtp_config['port']}...")
    
    try:
        server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
        server.ehlo()
        
        if smtp_config['use_tls']:
            server.starttls()
            server.ehlo()
        
        print("Authenticating...")
        server.login(CONFIG['sender_email'], CONFIG['sender_password'])
        
        print(f"Sending email to {CONFIG['recipient_email']}...")
        server.sendmail(
            CONFIG['sender_email'],
            CONFIG['recipient_email'],
            msg.as_string()
        )
        
        server.quit()
        
        print("=" * 60)
        print("✅ EMAIL SENT SUCCESSFULLY!")
        print("=" * 60)
        print(f"  From: {CONFIG['sender_email']}")
        print(f"  To:   {CONFIG['recipient_email']}")
        print(f"  Attachment: PLATFORM_ARCHITECTURE_UML.pdf")
        print("=" * 60)
        return True
        
    except smtplib.SMTPAuthenticationError:
        print("=" * 60)
        print("❌ AUTHENTICATION FAILED!")
        print("=" * 60)
        print("\nFor Gmail users:")
        print("1. Enable 2-Factor Authentication")
        print("2. Generate an App Password at:")
        print("   https://myaccount.google.com/apppasswords")
        print("3. Use the App Password (not your regular password)")
        print("=" * 60)
        return False
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return False


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  PHINS Platform - Architecture PDF Email Sender")
    print("=" * 60 + "\n")
    
    success = send_email()
    sys.exit(0 if success else 1)
