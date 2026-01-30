# AGENTS.md - AI Agent Instructions for PHINS

This document provides guidance for AI agents working on the PHINS Insurance Management System codebase.

## Project Overview

**PHINS** (Professional Insurance Management System) is a production-grade insurance management platform with:
- Multi-language support (20 languages)
- Enterprise scalability (1M+ concurrent users)
- Web portal with REST API
- Database persistence (SQLite/PostgreSQL)
- AI-powered automation for underwriting, claims, and quotes

**Live URL**: [www.phins.ai](https://www.phins.ai)

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.8+ |
| Web Server | Flask-style HTTP server (`web_portal/server.py`) |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| ORM | SQLAlchemy 2.0+ |
| Testing | pytest |
| Reports | ReportLab (PDF generation) |
| AL Source | Microsoft Dynamics 365 Business Central (AL language) |

## Directory Structure

```
/workspace/
├── phins_system.py          # Core business entities and logic
├── web_portal/
│   ├── server.py            # Main HTTP server (large file ~28k lines)
│   ├── api_extensions.py    # API extension modules
│   ├── connectors.py        # External service connectors
│   └── static/              # Frontend HTML, JS, CSS (45+ files)
├── services/                # Business service modules (41 services)
│   ├── underwriting_service.py
│   ├── claims_service.py
│   ├── billing_service.py
│   ├── policy_service.py
│   ├── actuarial_service.py
│   ├── foundation_service.py
│   ├── algo_trading_service.py
│   └── ...                  # 34 more service modules
├── database/                # Database models and repositories
│   ├── models.py            # SQLAlchemy ORM models
│   ├── config.py            # Database configuration
│   ├── manager.py           # Database manager
│   ├── seeds.py             # Data seeding
│   └── repositories/        # Repository pattern (12 repositories)
├── tests/                   # pytest test files (35 tests)
├── security/                # Security utilities (vault, password migration)
├── scripts/                 # Utility scripts
├── src/                     # AL language source for Business Central
├── docs/                    # Documentation and UML diagrams
└── backups/                 # Backup files
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `phins_system.py` | Core domain entities (Company, Customer, Policy, Claim, etc.) |
| `web_portal/server.py` | REST API endpoints and web server (~28k lines) |
| `services/*.py` | Business logic services (41 modules) |
| `database/models.py` | SQLAlchemy ORM models |
| `database/repositories/*.py` | Data access layer (repository pattern) |
| `tests/conftest.py` | pytest fixtures and configuration |
| `requirements.txt` | Python dependencies |

## Services Overview

The platform includes 41 service modules organized by domain:

### Core Insurance Services
- `underwriting_service.py` - Underwriting workflow and decisions
- `claims_service.py` - Claims processing and management
- `billing_service.py` - Billing and invoicing
- `policy_service.py` - Policy lifecycle management
- `reinsurance_service.py` - Reinsurance arrangements

### Financial Services
- `actuarial_service.py` - Actuarial calculations and pricing
- `billing_credit_service.py` - Credit management
- `financial_reporting_service.py` - Financial reports
- `payment_gateway_service.py` - Payment processing
- `unified_balance_service.py` - Balance calculations

### AI/Automation Services
- `underwriting_bot_service.py` - AI-powered underwriting
- `claims_bot_service.py` - AI-powered claims processing
- `algo_trading_service.py` - Algorithmic trading

### Investment & Portfolio
- `investment_portfolio_service.py` - Portfolio management
- `portfolio_tracker_service.py` - Portfolio tracking
- `savings_pipeline_service.py` - Savings automation
- `market_data_service.py` - Market data feeds
- `advanced_market_data.py` - Advanced market analytics

### Foundation & Community
- `foundation_service.py` - Foundation management
- `foundation_persistence_service.py` - Foundation data persistence
- `foundation_billing_integration.py` - Foundation billing
- `contribution_payment_service.py` - Contribution tracking

### Supply Chain & Suppliers
- `supply_chain_ecosystem_service.py` - Supply chain management
- `supplier_management_service.py` - Supplier operations
- `marketplace_service.py` - Marketplace features

### Infrastructure Services
- `audit_service.py` - Audit logging
- `notification_service.py` - Notifications
- `data_integrity_service.py` - Data validation
- `pipeline_integrity_service.py` - Pipeline health
- `metrics_service.py` - Performance metrics

## Database Repository Pattern

The `database/repositories/` folder implements the repository pattern:

| Repository | Purpose |
|------------|---------|
| `customer_repository.py` | Customer CRUD operations |
| `policy_repository.py` | Policy data access |
| `claim_repository.py` | Claims data access |
| `billing_repository.py` | Billing operations |
| `underwriting_repository.py` | Underwriting data |
| `user_repository.py` | User management |
| `session_repository.py` | Session handling |
| `audit_repository.py` | Audit log storage |
| `actuarial_repository.py` | Actuarial data |
| `token_repository.py` | Token management |

## Development Guidelines

### Code Style

- **Python**: Use PEP 8 conventions
- **Variables**: snake_case for variables and functions
- **Classes**: PascalCase for class names
- **Constants**: UPPERCASE_WITH_UNDERSCORES
- **Type hints**: Preferred for function signatures

### Business Domain Conventions

| Entity | ID Prefix | Example |
|--------|-----------|---------|
| Company | COM | COM001 |
| Customer | CUST | CUST001 |
| Policy | POL | POL001 |
| Claim | CLM | CLM001 |
| Bill | BILL | BILL001 |

### Status Enumerations

- **PolicyStatus**: ACTIVE, INACTIVE, CANCELLED, LAPSED, SUSPENDED
- **UnderwritingStatus**: PENDING, APPROVED, REJECTED, REFERRED, APPROVED_CONDITIONAL
- **ClaimStatus**: PENDING, UNDER_REVIEW, APPROVED, REJECTED, PAID, CLOSED
- **BillStatus**: OUTSTANDING, PARTIAL, PAID, OVERDUE, CANCELLED

### Data Integrity Helpers

The server includes helper functions for safe data handling:

```python
# Case-insensitive status comparison
status_eq(item, 'approved', 'paid')  # True if status matches any

# Safe numeric conversion (prevents TypeErrors)
safe_float(val, default=0.0)  # Handles None, strings, invalid types
safe_int(val, default=0)
```

## Testing

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_database.py

# Run with verbose output
pytest -v tests/

# Run specific test function
pytest tests/test_database.py::test_function_name

# Run tests matching a pattern
pytest -k "billing" tests/
```

### Test Categories

- **Unit tests**: Individual service and module tests
- **Integration tests**: End-to-end workflow tests
- **API tests**: REST endpoint verification
- **Security tests**: Authentication and authorization checks
- **Data integrity tests**: Dashboard and pipeline validation

### Key Test Files

| Test File | Coverage |
|-----------|----------|
| `test_database.py` | Database operations |
| `test_e2e_insurance_pipeline.py` | Full insurance workflows |
| `test_api_integration.py` | REST API endpoints |
| `test_security_performance.py` | Security checks |
| `test_underwriting_bot.py` | AI automation |
| `test_dashboard_data_integrity.py` | Dashboard calculations |
| `test_billing_engine.py` | Billing operations |
| `test_algo_trading.py` | Trading algorithms |
| `test_foundation_pipeline_integrity.py` | Foundation workflows |
| `test_customer_data_isolation.py` | Data security |

## Running the Server

```bash
# Development mode (in-memory) - runs on port 8000
python3 web_portal/server.py

# With SQLite database
export USE_DATABASE=1
export USE_SQLITE=1
python3 web_portal/server.py

# With PostgreSQL (production)
export USE_DATABASE=1
export DATABASE_URL="postgresql://..."
python3 web_portal/server.py

# Run quick tests
python3 web_portal/server.py --test
```

The server runs on port **8000** by default (configurable via `PORT` environment variable).

## Important Workflows

### 1. Policy Creation Flow
```
Customer Registration → Policy Creation → Underwriting Assessment → 
Approval/Rejection → Bill Generation → Payment Recording
```

### 2. Claims Processing Flow
```
Claim Submission → Validation → Adjuster Review → 
Approval/Rejection → Payment Processing
```

### 3. Automated Underwriting (AI)
```
Application Submission → Risk Assessment → Fraud Detection →
Auto-Decision (if threshold met) or Human Review
```

### 4. Foundation Contribution Flow
```
Foundation Setup → Member Registration → Contribution Scheduling →
Payment Processing → Benefit Distribution
```

### 5. Supplier Ecosystem Flow
```
Supplier Registration → Product Catalog → Order Processing →
Fulfillment → Settlement
```

## Database Schema

Core tables (auto-created on startup):
- `customers` - Customer profiles
- `policies` - Insurance policies
- `claims` - Claims records
- `underwriting_applications` - Underwriting workflow
- `bills` - Billing and invoices
- `users` - Staff accounts
- `sessions` - User sessions
- `audit_logs` - Complete audit trail
- `notifications` - Notification queue

## API Patterns

### Authentication
- Session-based authentication via `/api/login`
- Default users seeded: admin, underwriter, claims_adjuster, accountant

### Response Format
```json
{
  "items": [...],
  "page": 1,
  "page_size": 50,
  "total": 123
}
```

### Common Endpoints
- `POST /api/login` - Authentication
- `GET /api/policies` - List policies (paginated)
- `GET /api/claims` - List claims (paginated)
- `POST /api/customer/register` - Register customer
- `POST /api/underwrite` - Submit underwriting
- `GET /api/dashboard/stats` - Dashboard statistics
- `GET /api/billing/summary` - Billing summary

### Error Response Format
```json
{
  "error": "Error message description"
}
```

## Common Tasks for Agents

### Adding a New Service
1. Create service file in `services/`
2. Import and register in `web_portal/server.py`
3. Add relevant tests in `tests/`
4. Update documentation if needed

### Adding a New API Endpoint
1. Add route handler in `web_portal/server.py`
2. Implement business logic (use existing services when possible)
3. Add input validation
4. Add appropriate tests
5. Update API documentation

### Modifying Database Schema
1. Update models in `database/models.py`
2. Create migration if using Alembic (or in `database/migrations/`)
3. Update affected repositories in `database/repositories/`
4. Update affected services
5. Update affected tests

### Adding Frontend Pages
1. Create HTML file in `web_portal/static/`
2. Add corresponding JS file if needed
3. Update `styles.css` for styling
4. Link from appropriate navigation

### Adding a New Repository
1. Create repository file in `database/repositories/`
2. Extend `BaseRepository` from `database/repositories/base.py`
3. Implement CRUD methods following existing patterns
4. Update `database/repositories/__init__.py`

## Do's and Don'ts

### Do
- Run tests before committing changes
- Use existing services and patterns
- Add type hints to new functions
- Handle errors gracefully with appropriate error messages
- Use the audit service for important operations
- Follow the existing code organization
- Use `safe_float()` and `safe_int()` for numeric conversions
- Use `status_eq()` for case-insensitive status comparisons

### Don't
- Modify `phins_system.py` core entities without careful consideration
- Skip input validation on API endpoints
- Hardcode credentials or sensitive data
- Break existing API contracts
- Ignore test failures
- Add external dependencies without necessity

## Helpful Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Type checking
mypy phins_system.py

# Run specific service demo
python3 demo.py
python3 demo_global.py

# Generate test report
python3 generate_uw_assessment_report.py

# Validate system
python3 validate_system.py

# Check database connection
python3 check_database_connection.py
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `USE_DATABASE` | Enable database mode | 0 (disabled) |
| `USE_SQLITE` | Use SQLite instead of PostgreSQL | 0 |
| `DATABASE_URL` | PostgreSQL connection string | None |
| `SECRET_KEY` | Session encryption key | Auto-generated |
| `PORT` | Server port | 8000 |

## Debugging Tips

1. **Server not starting**: Check if port 8000 is in use
2. **Database errors**: Ensure `USE_DATABASE=1` is set
3. **Import errors**: Run `pip install -r requirements.txt`
4. **Test failures**: Check `tests/conftest.py` for fixture issues
5. **Data integrity issues**: Use `safe_float()`/`safe_int()` for conversions
6. **Status comparison issues**: Use `status_eq()` for case-insensitive checks

## Related Documentation

- `README.md` - Project overview and features
- `AI_ARCHITECTURE.md` - AI automation documentation
- `SECURITY.md` - Security implementation details
- `DATABASE_IMPLEMENTATION_SUMMARY.md` - Database architecture
- `DEPLOYMENT.md` - Deployment instructions
- `RAILWAY_DEPLOYMENT.md` - Railway-specific deployment
- `.github/copilot-instructions.md` - AL language guidance (Business Central)
- `UNDERWRITING_BOT_IMPLEMENTATION.md` - AI underwriting details
- `COMMUNITY_FOUNDATION_DESIGN.md` - Foundation feature design
- `SUPPLY_CHAIN_ARCHITECTURE.md` - Supply chain documentation

## Frontend Pages (web_portal/static/)

| Page | Purpose |
|------|---------|
| `index.html` | Landing page |
| `login.html` | User authentication |
| `dashboard.html` | Main dashboard |
| `admin-portal.html` | Admin management |
| `underwriter-dashboard.html` | Underwriting workflow |
| `claims-adjuster-dashboard.html` | Claims processing |
| `accountant-dashboard.html` | Financial operations |
| `actuary-dashboard.html` | Actuarial tools |
| `client-portal.html` | Customer self-service |
| `foundation-dashboard.html` | Foundation management |
| `supplier-dashboard.html` | Supplier operations |
| `algo-trading.html` | Trading interface |

---

*Last Updated: January 2026*
