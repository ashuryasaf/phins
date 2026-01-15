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
| Web Server | Flask-based (`web_portal/server.py`) |
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
│   ├── server.py            # Main Flask server (large file)
│   └── static/              # Frontend HTML, JS, CSS
├── services/                # Business service modules
│   ├── underwriting_service.py
│   ├── claims_service.py
│   ├── billing_service.py
│   ├── policy_service.py
│   └── ...                  # 27 service modules
├── database/                # Database models and repositories
├── tests/                   # pytest test files (25 tests)
├── security/                # Security utilities (vault, password migration)
├── src/                     # AL language source for Business Central
└── docs/uml/                # Architecture diagrams
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `phins_system.py` | Core domain entities (Company, Customer, Policy, Claim, etc.) |
| `web_portal/server.py` | REST API endpoints and web server |
| `services/*.py` | Business logic services |
| `database/models.py` | SQLAlchemy ORM models |
| `tests/conftest.py` | pytest fixtures and configuration |
| `requirements.txt` | Python dependencies |

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
```

### Test Categories

- **Unit tests**: Individual service and module tests
- **Integration tests**: End-to-end workflow tests
- **API tests**: REST endpoint verification
- **Security tests**: Authentication and authorization checks

### Key Test Files

| Test File | Coverage |
|-----------|----------|
| `test_database.py` | Database operations |
| `test_e2e_insurance_pipeline.py` | Full insurance workflows |
| `test_api_integration.py` | REST API endpoints |
| `test_security_performance.py` | Security checks |
| `test_underwriting_bot.py` | AI automation |

## Running the Server

```bash
# Development mode (in-memory)
python3 web_portal/server.py

# With SQLite database
export USE_DATABASE=1
export USE_SQLITE=1
python3 web_portal/server.py

# With PostgreSQL (production)
export USE_DATABASE=1
export DATABASE_URL="postgresql://..."
python3 web_portal/server.py
```

The server runs on port 5000 by default.

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
2. Create migration if using Alembic
3. Update affected services
4. Update affected tests

### Adding Frontend Pages
1. Create HTML file in `web_portal/static/`
2. Add corresponding JS file if needed
3. Update `styles.css` for styling
4. Link from appropriate navigation

## Do's and Don'ts

### Do
- Run tests before committing changes
- Use existing services and patterns
- Add type hints to new functions
- Handle errors gracefully with appropriate error messages
- Use the audit service for important operations
- Follow the existing code organization

### Don't
- Modify `phins_system.py` core entities without careful consideration
- Skip input validation on API endpoints
- Hardcode credentials or sensitive data
- Break existing API contracts
- Ignore test failures

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
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `USE_DATABASE` | Enable database mode | 0 (disabled) |
| `USE_SQLITE` | Use SQLite instead of PostgreSQL | 0 |
| `DATABASE_URL` | PostgreSQL connection string | None |
| `SECRET_KEY` | Session encryption key | Auto-generated |
| `PORT` | Server port | 5000 |

## Debugging Tips

1. **Server not starting**: Check if port 5000 is in use
2. **Database errors**: Ensure `USE_DATABASE=1` is set
3. **Import errors**: Run `pip install -r requirements.txt`
4. **Test failures**: Check `tests/conftest.py` for fixture issues

## Related Documentation

- `README.md` - Project overview and features
- `AI_ARCHITECTURE.md` - AI automation documentation
- `SECURITY.md` - Security implementation details
- `DATABASE_IMPLEMENTATION_SUMMARY.md` - Database architecture
- `.github/copilot-instructions.md` - Additional AI guidance (AL-focused)

---

*Last Updated: January 2026*
