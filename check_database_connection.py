#!/usr/bin/env python3
"""
PHINS Database Connection Diagnostic
=====================================
Run this script to diagnose database connection issues on Railway.

Usage:
    python3 check_database_connection.py

Environment Variables Required:
    - DATABASE_URL (preferred) or DATABASE_PUBLIC_URL
"""

import os
import sys
import re

def mask_password(url):
    """Mask password in connection string for display"""
    if not url:
        return "NOT SET"
    # Match the password between :password@ pattern
    return re.sub(r':([^:@]+)@', r':****@', url)

def check_connection():
    """Check database connection and provide diagnostic info"""
    print("=" * 70)
    print("PHINS Database Connection Diagnostic")
    print("=" * 70)
    
    # Check environment variables
    print("\n1. CHECKING ENVIRONMENT VARIABLES")
    print("-" * 40)
    
    database_url = os.environ.get('DATABASE_URL')
    database_public_url = os.environ.get('DATABASE_PUBLIC_URL')
    use_database = os.environ.get('USE_DATABASE', 'not set')
    
    print(f"   DATABASE_URL:        {mask_password(database_url)}")
    print(f"   DATABASE_PUBLIC_URL: {mask_password(database_public_url)}")
    print(f"   USE_DATABASE:        {use_database}")
    
    # Determine which URL to use
    url_to_use = database_url or database_public_url
    url_source = 'DATABASE_URL' if database_url else 'DATABASE_PUBLIC_URL' if database_public_url else None
    
    if not url_to_use:
        print("\n   ⚠️  ERROR: No database URL found!")
        print("   Please set DATABASE_URL in Railway variables.")
        print("\n   SOLUTION:")
        print("   1. Go to Railway Dashboard")
        print("   2. Click on your PostgreSQL service (Postgres-AyKP)")
        print("   3. Go to 'Variables' tab")
        print("   4. Copy DATABASE_URL value")
        print("   5. Add it to your web service's variables")
        return False
    
    print(f"\n   Using: {url_source}")
    
    # Parse connection string
    print("\n2. PARSING CONNECTION STRING")
    print("-" * 40)
    
    # Handle postgres:// vs postgresql://
    if url_to_use.startswith('postgres://'):
        url_to_use = url_to_use.replace('postgres://', 'postgresql://', 1)
        print("   Converted postgres:// to postgresql:// for SQLAlchemy")
    
    # Parse URL components
    try:
        # Pattern: postgresql://user:password@host:port/database
        pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
        match = re.match(pattern, url_to_use)
        
        if match:
            user, password, host, port, database = match.groups()
            print(f"   Username: {user}")
            print(f"   Password: {'*' * len(password)} ({len(password)} chars)")
            print(f"   Host:     {host}")
            print(f"   Port:     {port}")
            print(f"   Database: {database}")
        else:
            print("   ⚠️  Could not parse URL - format might be incorrect")
            print(f"   Expected: postgresql://user:password@host:port/database")
    except Exception as e:
        print(f"   ⚠️  Error parsing URL: {e}")
    
    # Test actual connection
    print("\n3. TESTING DATABASE CONNECTION")
    print("-" * 40)
    
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError
        
        engine = create_engine(
            url_to_use,
            pool_pre_ping=True,
            connect_args={'connect_timeout': 10}
        )
        
        with engine.connect() as conn:
            # Test basic connection
            result = conn.execute(text("SELECT 1"))
            print("   ✓ Basic connection: SUCCESS")
            
            # Get PostgreSQL version
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"   ✓ PostgreSQL version: {version[:50]}...")
            
            # Check current database
            result = conn.execute(text("SELECT current_database()"))
            db_name = result.scalar()
            print(f"   ✓ Current database: {db_name}")
            
            # List tables
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name
            """))
            tables = [row[0] for row in result]
            
            if tables:
                print(f"   ✓ Tables found: {len(tables)}")
                for table in tables[:10]:  # Show first 10
                    print(f"      - {table}")
                if len(tables) > 10:
                    print(f"      ... and {len(tables) - 10} more")
            else:
                print("   ⚠️  No tables found - database may need initialization")
                print("   Run: python3 init_database.py")
        
        print("\n   ✅ DATABASE CONNECTION SUCCESSFUL!")
        return True
        
    except ImportError:
        print("   ⚠️  SQLAlchemy not installed")
        print("   Run: pip3 install sqlalchemy psycopg2-binary")
        return False
        
    except OperationalError as e:
        print(f"   ❌ Connection failed: {e}")
        print("\n   POSSIBLE CAUSES:")
        print("   - Wrong host/port in connection string")
        print("   - Database service not running")
        print("   - Network connectivity issues")
        print("   - Firewall blocking connection")
        print("\n   SOLUTION:")
        print("   1. Go to Railway Dashboard")
        print("   2. Check PostgreSQL service is running")
        print("   3. Copy fresh DATABASE_URL from PostgreSQL > Variables")
        return False
        
    except Exception as e:
        print(f"   ❌ Unexpected error: {type(e).__name__}: {e}")
        return False

def show_railway_instructions():
    """Show instructions for getting correct DATABASE_URL from Railway"""
    print("\n" + "=" * 70)
    print("HOW TO GET CORRECT DATABASE_URL FROM RAILWAY")
    print("=" * 70)
    print("""
1. Go to Railway Dashboard: https://railway.app/dashboard

2. Open your project

3. Click on the PostgreSQL service (Postgres-AyKP)

4. Go to the "Variables" tab

5. Find and copy one of these URLs:
   
   OPTION A (Recommended - Internal URL):
   ├── Variable: DATABASE_URL
   └── Use when your web service is ALSO on Railway
   
   OPTION B (Public URL):
   ├── Variable: DATABASE_PUBLIC_URL  
   └── Use when connecting from OUTSIDE Railway

6. Go to your WEB SERVICE (not the database)

7. Click "Variables" tab

8. Add/Update the variable:
   ├── Name:  DATABASE_URL
   └── Value: <paste the URL you copied>

9. Also ensure these are set:
   ├── USE_DATABASE = true
   └── ENABLE_LEDGER_PERSISTENCE = true

10. Trigger a new deployment

IMPORTANT: Make sure you're copying from the PostgreSQL service,
not from an old/different database instance!
""")

def verify_data_integrity():
    """Verify data integrity after connection"""
    print("\n4. DATA INTEGRITY CHECK")
    print("-" * 40)
    
    database_url = os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_PUBLIC_URL')
    if not database_url:
        print("   Skipped - no database URL")
        return
    
    try:
        from sqlalchemy import MetaData, Table, create_engine, func, inspect, select
        
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        engine = create_engine(database_url, pool_pre_ping=True)
        
        with engine.connect() as conn:
            # Check for key tables
            key_tables = ['customers', 'policies', 'claims', 'billing', 'users']
            inspector = inspect(engine)
            metadata = MetaData()
            
            for table in key_tables:
                try:
                    if table not in inspector.get_table_names():
                        print(f"   {table}: table not found")
                        continue

                    reflected_table = Table(table, metadata, autoload_with=engine)
                    result = conn.execute(select(func.count()).select_from(reflected_table))
                    count = result.scalar()
                    print(f"   {table}: {count} records")
                except Exception:
                    print(f"   {table}: table not found")
            
            print("\n   ✓ Data integrity check complete")
            
    except Exception as e:
        print(f"   ⚠️  Could not verify data: {e}")

if __name__ == '__main__':
    success = check_connection()
    
    if success:
        verify_data_integrity()
    else:
        show_railway_instructions()
    
    print("\n" + "=" * 70)
    sys.exit(0 if success else 1)
