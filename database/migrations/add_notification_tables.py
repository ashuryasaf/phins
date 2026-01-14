"""
Database Migration: Add Notification Service Tables

This migration creates tables for the enterprise notification service:
- notification_templates: Template storage
- notification_queue: Async delivery queue
- notification_history: Delivery history
- otp_codes: OTP storage (hashed)
- client_verifications: Verification workflows
- rate_limit_records: Rate limiting
- email_suppression_list: Bounced/unsubscribed emails
- sms_suppression_list: Invalid phone numbers
- notification_preferences: Customer preferences
- notification_audit_log: Security audit trail

Run with: python3 database/migrations/add_notification_tables.py
"""

import os
import sys

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, inspect
from database.models import Base
from database.notification_models import (
    NotificationTemplate,
    NotificationQueue,
    NotificationHistory,
    OTPCode,
    ClientVerification,
    RateLimitRecord,
    EmailSuppressionList,
    SMSSuppressionList,
    NotificationPreference,
    NotificationAuditLog,
)


def get_database_url():
    """Get database URL from environment or default to SQLite"""
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # Handle Railway's postgres:// URL format
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        return db_url
    
    # Default to SQLite for development
    sqlite_path = os.environ.get('SQLITE_PATH', 'phins.db')
    return f'sqlite:///{sqlite_path}'


def run_migration():
    """Run the migration to create notification tables"""
    print("=" * 60)
    print("PHINS Notification Service Database Migration")
    print("=" * 60)
    print()
    
    db_url = get_database_url()
    print(f"Database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print()
    
    # Create engine
    engine = create_engine(db_url, echo=False)
    inspector = inspect(engine)
    
    # List of notification tables
    notification_tables = [
        'notification_templates',
        'notification_queue',
        'notification_history',
        'otp_codes',
        'client_verifications',
        'rate_limit_records',
        'email_suppression_list',
        'sms_suppression_list',
        'notification_preferences',
        'notification_audit_log',
    ]
    
    # Check existing tables
    existing_tables = inspector.get_table_names()
    
    print("Checking existing tables...")
    new_tables = []
    skip_tables = []
    
    for table in notification_tables:
        if table in existing_tables:
            skip_tables.append(table)
            print(f"  ✓ {table} (already exists)")
        else:
            new_tables.append(table)
            print(f"  ○ {table} (will create)")
    
    print()
    
    if not new_tables:
        print("All notification tables already exist. No migration needed.")
        return True
    
    print(f"Creating {len(new_tables)} new tables...")
    print()
    
    try:
        # Create only notification tables (not all Base tables)
        notification_models = [
            NotificationTemplate,
            NotificationQueue,
            NotificationHistory,
            OTPCode,
            ClientVerification,
            RateLimitRecord,
            EmailSuppressionList,
            SMSSuppressionList,
            NotificationPreference,
            NotificationAuditLog,
        ]
        
        # Create tables
        for model in notification_models:
            if model.__tablename__ in new_tables:
                model.__table__.create(engine, checkfirst=True)
                print(f"  ✓ Created: {model.__tablename__}")
        
        print()
        print("=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)
        
        # Verify
        print()
        print("Verifying tables...")
        inspector = inspect(engine)
        final_tables = inspector.get_table_names()
        
        all_created = True
        for table in notification_tables:
            if table in final_tables:
                print(f"  ✓ {table}")
            else:
                print(f"  ✗ {table} (MISSING)")
                all_created = False
        
        return all_created
        
    except Exception as e:
        print(f"Migration failed: {str(e)}")
        return False


def seed_default_templates(engine):
    """Seed default notification templates"""
    from sqlalchemy.orm import Session
    from datetime import datetime
    import uuid
    
    session = Session(engine)
    
    try:
        # Check if templates already exist
        existing = session.query(NotificationTemplate).count()
        if existing > 0:
            print(f"Templates already seeded ({existing} templates)")
            return
        
        default_templates = [
            {
                'id': f'TPL_{uuid.uuid4().hex[:8]}',
                'name': 'otp_email',
                'channel': 'email',
                'category': 'otp',
                'subject': 'Your PHINS Verification Code: {{ code }}',
                'body_template': 'Your verification code is: {{ code }}. Valid for {{ expiry_minutes }} minutes.',
                'language': 'en',
                'priority': 'critical',
                'active': True,
            },
            {
                'id': f'TPL_{uuid.uuid4().hex[:8]}',
                'name': 'otp_sms',
                'channel': 'sms',
                'category': 'otp',
                'body_template': 'PHINS code: {{ code }}. Expires in {{ expiry_minutes }} min.',
                'language': 'en',
                'priority': 'critical',
                'active': True,
            },
            {
                'id': f'TPL_{uuid.uuid4().hex[:8]}',
                'name': 'welcome_email',
                'channel': 'email',
                'category': 'transactional',
                'subject': 'Welcome to PHINS Insurance',
                'body_template': 'Hello {{ name }}, welcome to PHINS Insurance!',
                'language': 'en',
                'priority': 'normal',
                'active': True,
            },
            {
                'id': f'TPL_{uuid.uuid4().hex[:8]}',
                'name': 'password_reset',
                'channel': 'email',
                'category': 'security',
                'subject': 'PHINS Password Reset Request',
                'body_template': 'Click here to reset your password: {{ reset_link }}',
                'language': 'en',
                'priority': 'high',
                'active': True,
            },
        ]
        
        for template_data in default_templates:
            template = NotificationTemplate(**template_data)
            session.add(template)
        
        session.commit()
        print(f"Seeded {len(default_templates)} default templates")
        
    except Exception as e:
        session.rollback()
        print(f"Failed to seed templates: {str(e)}")
    finally:
        session.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Run notification service database migration')
    parser.add_argument('--seed-templates', action='store_true', help='Seed default templates')
    args = parser.parse_args()
    
    success = run_migration()
    
    if success and args.seed_templates:
        print()
        print("Seeding default templates...")
        db_url = get_database_url()
        engine = create_engine(db_url)
        seed_default_templates(engine)
    
    sys.exit(0 if success else 1)
