#!/usr/bin/env python3
"""
Database Initialization Script for PHINS
Runs on first startup to set up the database and populate demo data.

This script:
1. Checks if database is empty
2. Creates all necessary tables with proper foreign keys
3. Runs populate_demo_data.py to create realistic demo data
4. Seeds default admin users
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def init_database(force: bool = False):
    """
    Initialize the database schema and optionally populate with demo data.
    
    Args:
        force: If True, drop existing tables and recreate (USE WITH CAUTION)
    """
    print("=" * 60)
    print("PHINS Database Initialization")
    print("=" * 60)
    
    try:
        # Import database modules
        from database import init_database as create_tables
        from database import check_database_connection, get_database_info
        from database.seeds import seed_default_users
        from database.manager import DatabaseManager
        
        # Check database connection
        print("\n1. Checking database connection...")
        if not check_database_connection():
            print("   ✗ Database connection failed!")
            print("   Please check your DATABASE_URL or database configuration.")
            return False
        print("   ✓ Database connection successful")
        
        # Get database info
        db_info = get_database_info()
        print(f"\n2. Database Information:")
        print(f"   Type: {db_info.get('database_type', 'Unknown')}")
        print(f"   Connection: OK" if db_info.get('connection_ok') else "   Connection: FAILED")
        
        # Check if database is empty
        print("\n3. Checking if database needs initialization...")
        is_empty = False
        try:
            with DatabaseManager() as db:
                # Try to count users - if table doesn't exist or is empty, we need to initialize
                user_count = db.users.count()
                customer_count = db.customers.count()
                policy_count = db.policies.count()
                
                if user_count == 0 and customer_count == 0 and policy_count == 0:
                    is_empty = True
                    print(f"   Database is empty - initialization required")
                else:
                    print(f"   Database already initialized:")
                    print(f"   - Users: {user_count}")
                    print(f"   - Customers: {customer_count}")
                    print(f"   - Policies: {policy_count}")
        except Exception as e:
            # If we get an error, likely tables don't exist
            is_empty = True
            print(f"   Database needs initialization (tables may not exist)")
        
        # Create tables if needed
        if is_empty or force:
            print("\n4. Creating database tables...")
            create_tables(drop_existing=force)
            print("   ✓ Database tables created successfully")
            
            # Seed default users
            print("\n5. Creating default admin users...")
            seed_default_users()
            print("   ✓ Default users created")
            print("   Default admin login: admin / admin123")
            
            # Populate demo data
            print("\n6. Checking if demo data should be populated...")
            populate_demo = os.environ.get('POPULATE_DEMO_DATA', 'true').lower() in ('true', '1', 'yes')
            
            if populate_demo:
                print("   Populating demo data (this may take a moment)...")
                try:
                    from populate_demo_data import main as populate_data
                    populate_data()
                    print("   ✓ Demo data populated successfully")
                except Exception as e:
                    print(f"   ⚠ Warning: Could not populate demo data: {e}")
                    print("   You can run 'python populate_demo_data.py' manually later")
            else:
                print("   Skipping demo data (POPULATE_DEMO_DATA=false)")
        else:
            print("\n4. Database already initialized - skipping creation")
        
        print("\n" + "=" * 60)
        print("✓ Database initialization complete!")
        print("=" * 60)
        print("\nYou can now start the server:")
        print("  python web_portal/server.py")
        print("\nOr access the admin portal at: http://localhost:8000/admin-portal.html")
        print("  Login: admin / admin123")
        print("\n")
        
        return True
        
    except ImportError as e:
        print(f"\n✗ Error: Required module not found: {e}")
        print("   Make sure you have installed all dependencies:")
        print("   pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"\n✗ Error during initialization: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Initialize PHINS database')
    parser.add_argument('--force', action='store_true',
                       help='Drop existing tables and recreate (WARNING: destroys data)')
    parser.add_argument('--no-demo', action='store_true',
                       help='Skip demo data population')
    
    args = parser.parse_args()
    
    # Set environment variable based on --no-demo flag
    if args.no_demo:
        os.environ['POPULATE_DEMO_DATA'] = 'false'
    
    # Warn if forcing
    if args.force:
        print("\n⚠️  WARNING: --force will DELETE ALL EXISTING DATA")
        response = input("Are you sure? Type 'yes' to continue: ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return
    
    # Run initialization
    success = init_database(force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
