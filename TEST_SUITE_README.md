# PHINS PR #4 - Comprehensive Test Suite Documentation

## Overview

This test suite validates all 6 core features implemented in PR #4:

1. **Landing Page & Routing** - Tests that all pages load correctly and routing works
2. **Role-Based Access Control (RBAC)** - Tests authentication and authorization for different user roles
3. **Password Management** - Tests password change, reset, and validation
4. **Form Data Persistence** - Tests quote and policy application submissions
5. **AI Automation Controller** - Tests automated quote generation, underwriting, claims processing, and fraud detection
6. **Database Operations** - Tests database initialization, user seeding, and data consistency

## Files

- **`test_pr_complete.py`** - Main test suite (30+ test cases)
- **`ai_automation_controller.py`** - AI automation module with business logic
- **`test_report.html`** - Generated HTML test report (after running tests)
- **`test_results.json`** - Generated JSON test results (after running tests)

## Prerequisites

### Required Dependencies

```bash
pip install requests
```

### Optional Dependencies

For database tests (if available):
```bash
pip install sqlalchemy psycopg2-binary alembic
```

### Server Setup

The test suite requires the PHINS web portal server to be running:

```bash
# Start the server (in a separate terminal)
python web_portal/server.py
```

The server should be running at `http://localhost:8000` (default).

## Running Tests

### Run All Tests

```bash
python test_pr_complete.py
```

### Run Specific Category

```bash
# Run only RBAC tests
python test_pr_complete.py --category rbac

# Run only AI tests
python test_pr_complete.py --category ai

# Run only form tests
python test_pr_complete.py --category forms
```

Available categories: `routing`, `rbac`, `password`, `forms`, `ai`, `database`, `integration`, `api`

### Run Without Server (AI & Database Tests Only)

```bash
python test_pr_complete.py --no-server-tests
```

### Verbose Mode

```bash
python test_pr_complete.py -v
```

### Custom Server URL

```bash
TEST_BASE_URL=http://example.com:8080 python test_pr_complete.py
```

## Test Results

### Console Output

The test suite provides real-time console output with pass/fail indicators:

```
🧪 PHINS SYSTEM INTEGRATION TEST SUITE
======================================================================
Testing against: http://localhost:8000
======================================================================
  ✅ Landing Page Loads
  ✅ Login Page Routing
  ✅ Admin Login
  ✅ Underwriter Login
  ...

======================================================================
📊 TEST RESULTS SUMMARY
======================================================================
Total Tests: 30
Passed: ✅ 27
Failed: ❌ 0
Skipped: ⏭️  3

Pass Rate: 100.0%
Execution Time: 0.28 seconds
======================================================================
```

### HTML Report

After running tests, open `test_report.html` in a browser to see a detailed, color-coded report with:

- Overall statistics (total, passed, failed, skipped)
- Pass rate percentage
- Results grouped by category
- Execution time for each test
- Error messages and stack traces for failures

### JSON Report

The `test_results.json` file contains machine-readable test results suitable for CI/CD integration:

```json
{
  "timestamp": "2025-12-16T19:55:37.235121",
  "total_tests": 30,
  "passed": 27,
  "failed": 0,
  "skipped": 3,
  "execution_time": "0.28s",
  "tests": [...]
}
```

## Test Categories Details

### 1. Landing Page & Routing Tests (2 tests)

- Verifies landing page loads with CTAs (Get Quote, New Policy, Login buttons)
- Checks login page has username and password fields
- Validates CSRF protection presence

### 2. Role-Based Access Control Tests (5 tests)

Tests login and authorization for:
- **Admin** (username: `admin`, password: `admin123`)
- **Underwriter** (username: `underwriter`, password: `under123`)
- **Accountant** (username: `accountant`, password: `acct123`)
- **Claims Adjuster** (username: `claims_adjuster`, password: `claims123`)
- RBAC enforcement (unauthorized access blocked)

### 3. Password Management Tests (3 tests)

- Password change endpoint functionality
- Password reset request handling
- Password strength validation (weak passwords rejected)

### 4. Form Data Persistence Tests (3 tests)

- Quote form submission and data storage
- Policy application submission
- Form validation (invalid data rejected)

### 5. AI Automation Controller Tests (5 tests)

- **Auto Quote Generation** - Calculates premiums based on age, coverage, health score
- **Automated Underwriting** - Risk assessment with AUTO_APPROVE/AUTO_REJECT/MANUAL_REVIEW decisions
- **Smart Claims Processing** - Auto-approves small claims (<$1000), requires review for large claims
- **Fraud Detection** - Identifies suspicious patterns (multiple applications, unrealistic claims)

### 6. Database Tests (3 tests)

- Database initialization and schema creation
- Default admin users creation and password hashing
- Data consistency and relationship integrity

### 7. Integration Tests (3 tests)

- Complete quote-to-policy journey
- Complete claims submission and processing
- Session management (login, token validation, logout)

### 8. API Endpoint Tests (3 tests)

- Authentication endpoints (`/api/login`, `/api/register`)
- Quote endpoints (`/api/submit-quote`)
- Application endpoints (`/api/policies/create`, `/api/policies/create_simple`)

## AI Automation Controller

The `ai_automation_controller.py` module provides automated business logic:

### Auto Quote Function

```python
from ai_automation_controller import auto_quote

result = auto_quote({
    'age': 30,
    'coverage_type': 'health',
    'coverage_amount': 100000,
    'health_score': 8
})
# Returns: quote_amount, confidence_score, risk_factors
```

### Auto Underwriting Function

```python
from ai_automation_controller import auto_underwrite

result = auto_underwrite({
    'age': 30,
    'smoker': False,
    'health_score': 9,
    'bmi': 22
})
# Returns: decision (AUTO_APPROVE/AUTO_REJECT/MANUAL_REVIEW), risk_score, risk_level
```

### Auto Claims Processing

```python
from ai_automation_controller import auto_process_claim

result = auto_process_claim({
    'amount': 500,
    'has_documents': True,
    'claim_type': 'medical',
    'policy_active': True
})
# Returns: decision, approved_amount, confidence
```

### Fraud Detection

```python
from ai_automation_controller import detect_fraud

result = detect_fraud({
    'multiple_applications': 6,
    'claim_amount': 50000,
    'policy_age_days': 15
})
# Returns: fraud_risk_level (LOW/MEDIUM/HIGH/CRITICAL), fraud_score, flags
```

## Troubleshooting

### Tests Failing Due to Rate Limiting

If tests fail with "Too many requests" or 429 errors:

1. Restart the server to clear rate limits:
   ```bash
   # Stop the server (Ctrl+C)
   python web_portal/server.py
   ```

2. Run tests again

### Database Tests Skipped

This is normal if the database module is not configured. The tests will show as "skipped" rather than "failed".

To enable database tests:
1. Set up PostgreSQL or use SQLite
2. Configure `DATABASE_URL` environment variable
3. Install database dependencies: `pip install sqlalchemy psycopg2-binary`

### Server Not Running

If you get connection errors:

```
Error: Connection refused
```

Make sure the server is running:
```bash
python web_portal/server.py
```

### Import Errors

If you get import errors for `ai_automation_controller`:

```bash
# Ensure you're in the project root directory
cd /path/to/phins
python test_pr_complete.py
```

## Success Criteria

✅ **All Tests Passing**: 27/27 tests pass (3 database tests may be skipped)
✅ **100% Pass Rate**: No failed tests
✅ **Reports Generated**: Both HTML and JSON reports created
✅ **Execution Time**: Complete in under 2 minutes (typically ~0.3 seconds)
✅ **No Errors**: Clean execution with proper error handling

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Run PHINS Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.12
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Start server
        run: python web_portal/server.py &
      - name: Wait for server
        run: sleep 5
      - name: Run tests
        run: python test_pr_complete.py
      - name: Upload test reports
        uses: actions/upload-artifact@v2
        with:
          name: test-reports
          path: |
            test_report.html
            test_results.json
```

## License

Part of the PHINS Insurance Management System.

---

**Questions or Issues?**

If you encounter any problems with the test suite, please:
1. Check this README for troubleshooting steps
2. Verify the server is running and accessible
3. Check that all dependencies are installed
4. Review the generated test reports for detailed error messages
