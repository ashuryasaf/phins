# Database Setup Guide

This guide explains how to set up and use the PostgreSQL database support in PHINS.

## Overview

PHINS now supports two storage modes:

1. **In-Memory Mode (Default)**: Data stored in memory, lost on restart (original behavior)
2. **Database Mode**: Persistent storage using SQLite (dev) or PostgreSQL (production)

## Quick Start

### Local Development with SQLite

```bash
# Enable database mode with SQLite
export USE_DATABASE=1
export USE_SQLITE=1
export SQLITE_PATH=phins.db

# Run the server
python3 web_portal/server.py
```

### Local Development with PostgreSQL

```bash
# Install PostgreSQL locally (Ubuntu/Debian)
sudo apt-get install postgresql postgresql-contrib

# Create database
sudo -u postgres createdb phins
sudo -u postgres createuser phins_user
sudo -u postgres psql -c "ALTER USER phins_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE phins TO phins_user;"

# Set environment variables
export USE_DATABASE=1
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=phins
export DB_USER=phins_user
export DB_PASSWORD=your_password

# Run the server
python3 web_portal/server.py
```

## Railway Deployment

### Step 1: Add PostgreSQL Plugin

1. Go to your Railway project dashboard
2. Click "New" → "Database" → "PostgreSQL"
3. Railway will automatically provision a PostgreSQL database
4. The `DATABASE_URL` environment variable will be automatically set

### Step 2: Configure Environment Variables

In your Railway service settings, add:

```
USE_DATABASE=1
```

That's it! Railway automatically provides the `DATABASE_URL` variable.

### Step 3: Deploy

```bash
# Push to GitHub
git push origin main

# Railway will automatically deploy with database support
```

## Environment Variables

### Database Mode Control

- `USE_DATABASE`: Set to `1`, `true`, or `yes` to enable database mode
- `USE_SQLITE`: Set to `1`, `true`, or `yes` to force SQLite (for local dev)

### SQLite Configuration

- `SQLITE_PATH`: Path to SQLite database file (default: `phins.db`)

### PostgreSQL Configuration

Option 1 - Full URL (recommended for Railway, Heroku, etc.):
- `DATABASE_URL`: Full PostgreSQL connection string
  - Format: `postgresql://user:password@host:port/database`
  - Railway provides this automatically

Option 2 - Individual variables:
- `DB_HOST`: PostgreSQL host (default: none)
- `DB_PORT`: PostgreSQL port (default: 5432)
- `DB_NAME`: Database name (default: phins)
- `DB_USER`: Database user (default: postgres)
- `DB_PASSWORD`: Database password (required)

## Database Schema

The database automatically creates these tables:

- `customers`: Customer information
- `policies`: Insurance policies
- `claims`: Insurance claims
- `underwriting_applications`: Underwriting workflow
- `bills`: Billing and invoices
- `users`: System users (staff accounts)
- `sessions`: User sessions
- `audit_logs`: Audit trail

## Default Users

When database mode is enabled, the following users are automatically created:

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | admin |
| underwriter | under123 | underwriter |
| claims_adjuster | claims123 | claims |
| accountant | acct123 | accountant |

**⚠️ IMPORTANT**: Change these passwords in production!

## Data Migration

To migrate existing in-memory data to database:

```python
from database.migrate_data import migrate_all_data
from web_portal.server import CUSTOMERS, POLICIES, CLAIMS, UNDERWRITING_APPLICATIONS

# Migrate all data
migrate_all_data(CUSTOMERS, POLICIES, CLAIMS, UNDERWRITING_APPLICATIONS)
```

## Manual Database Operations

### Initialize Database Schema

```python
from database import init_database

# Create all tables
init_database()

# Drop and recreate (WARNING: deletes all data)
init_database(drop_existing=True)
```

### Seed Default Data

```python
from database.seeds import seed_database

# Seed users only
seed_database(include_sample_data=False)

# Seed users and sample data
seed_database(include_sample_data=True)
```

### Check Database Connection

```python
from database import check_database_connection, get_database_info

# Test connection
if check_database_connection():
    print("Database connected!")
    
# Get configuration info
info = get_database_info()
print(f"Database type: {info['database_type']}")
print(f"Connection OK: {info['connection_ok']}")
```

## Repository Pattern Usage

For custom operations, use the repository pattern:

```python
from database.manager import DatabaseManager

# Using context manager (recommended)
with DatabaseManager() as db:
    # Create a customer
    customer = db.customers.create(
        id='CUST-12345',
        name='John Doe',
        email='john@example.com'
    )
    
    # Query customers
    customers = db.customers.get_all()
    customer = db.customers.get_by_id('CUST-12345')
    customer = db.customers.get_by_email('john@example.com')
    
    # Create a policy
    policy = db.policies.create(
        id='POL-001',
        customer_id='CUST-12345',
        type='life',
        coverage_amount=100000.0,
        annual_premium=1200.0
    )
    
    # Query policies
    policies = db.policies.get_by_customer('CUST-12345')
    active_policies = db.policies.get_active_policies()
```

## Troubleshooting

### "Module not found" errors

```bash
# Install required packages
pip install sqlalchemy psycopg2-binary
```

### SQLite database locked

```bash
# This can happen with multiple processes
# Use PostgreSQL for production or ensure only one process accesses SQLite
```

### PostgreSQL connection refused

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Check firewall allows port 5432
sudo ufw allow 5432/tcp
```

### Database tables not created

```python
# Manually initialize
from database import init_database
init_database()
```

## Performance Tuning

### Connection Pooling

Connection pool settings in `database/config.py`:

```python
POOL_SIZE = 20          # Number of connections to maintain
MAX_OVERFLOW = 10       # Additional connections when pool is full
POOL_TIMEOUT = 30       # Seconds to wait for available connection
POOL_RECYCLE = 3600     # Recycle connections after 1 hour
```

### Query Optimization

- Indexes are automatically created on foreign keys and frequently queried fields
- Use `get_by_id()` for single record lookups (fastest)
- Use `filter_by()` for simple filters
- Batch operations when creating multiple records

## Security Best Practices

1. **Change default passwords** immediately in production
2. **Use environment variables** for sensitive configuration
3. **Enable SSL** for PostgreSQL connections in production
4. **Restrict database user privileges** to minimum required
5. **Regular backups** of production database
6. **Audit logs** are automatically recorded in `audit_logs` table

## Backup and Restore

### SQLite Backup

```bash
# Backup
cp phins.db phins.db.backup

# Restore
cp phins.db.backup phins.db
```

### PostgreSQL Backup

```bash
# Backup
pg_dump -h localhost -U phins_user phins > backup.sql

# Restore
psql -h localhost -U phins_user phins < backup.sql
```

### Railway PostgreSQL Backup

Railway automatically creates daily backups. To manually backup:

1. Go to your PostgreSQL database in Railway dashboard
2. Click "Backups" tab
3. Click "Create Backup"

## Monitoring

The server logs all database operations at INFO level:

```
INFO:database:Initializing database: PostgreSQL
INFO:database.repositories.base:Created Customer: CUST-12345
INFO:database.repositories.base:Updated Policy: POL-001
```

To enable SQL query logging:

```python
# In database/config.py
ECHO_SQL = True  # Will log all SQL queries
```

## Support

For issues or questions:
1. Check server logs for error messages
2. Verify environment variables are set correctly
3. Test database connection separately
4. Check Railway logs if deployed there
