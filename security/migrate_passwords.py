#!/usr/bin/env python3
"""
PHINS Security: Password Migration Script
==========================================
Migrates plain-text passwords in dynamic_customers.json to hashed format.

This script:
1. Reads the existing dynamic_customers.json file
2. For each entry with a plain-text 'password' field, hashes it
3. Stores the hash and salt, removing the plain-text password
4. Preserves all other data

Usage:
    python3 security/migrate_passwords.py
    
IMPORTANT: This is a one-way migration. Make a backup before running.
"""

import json
import hashlib
import secrets
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def hash_password(password: str) -> dict:
    """Hash password using PBKDF2"""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}


def migrate_passwords():
    """Migrate plain-text passwords to hashed format"""
    
    seeds_file = os.path.join(os.path.dirname(__file__), '..', 'database', 'dynamic_customers.json')
    backup_file = seeds_file + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    
    print("=" * 70)
    print("PHINS Password Migration Script")
    print("=" * 70)
    print(f"\nSource file: {seeds_file}")
    
    if not os.path.exists(seeds_file):
        print("\n❌ Error: dynamic_customers.json not found")
        return False
    
    # Load existing data
    with open(seeds_file, 'r') as f:
        customers = json.load(f)
    
    print(f"Found {len(customers)} customer entries")
    
    # Create backup
    with open(backup_file, 'w') as f:
        json.dump(customers, f, indent=2)
    print(f"✓ Backup created: {backup_file}")
    
    # Migrate passwords
    migrated_count = 0
    already_hashed = 0
    
    for customer in customers:
        if 'password_hash' in customer and 'password_salt' in customer:
            # Already migrated
            already_hashed += 1
            # Remove legacy 'password' field if present
            if 'password' in customer:
                del customer['password']
        elif 'password' in customer:
            # Has plain-text password - migrate it
            plain_password = customer['password']
            pwd_hash = hash_password(plain_password)
            
            # Store hashed version
            customer['password_hash'] = pwd_hash['hash']
            customer['password_salt'] = pwd_hash['salt']
            
            # Remove plain-text password
            del customer['password']
            
            migrated_count += 1
            print(f"  ✓ Migrated: {customer.get('email', customer.get('username', 'unknown'))}")
        else:
            # No password field - generate unusable random password
            pwd_hash = hash_password(secrets.token_urlsafe(32))
            customer['password_hash'] = pwd_hash['hash']
            customer['password_salt'] = pwd_hash['salt']
            migrated_count += 1
    
    # Save migrated data
    with open(seeds_file, 'w') as f:
        json.dump(customers, f, indent=2)
    
    print("\n" + "=" * 70)
    print("Migration Summary")
    print("=" * 70)
    print(f"  Total entries: {len(customers)}")
    print(f"  Already hashed: {already_hashed}")
    print(f"  Migrated: {migrated_count}")
    print(f"  Backup: {backup_file}")
    print("\n✅ Migration complete!")
    print("\n⚠️  IMPORTANT: Plain-text passwords have been removed.")
    print("    Users will use the passwords they registered with.")
    print("    To reset a password, remove the user entry and have them re-register.")
    
    return True


if __name__ == '__main__':
    success = migrate_passwords()
    sys.exit(0 if success else 1)
