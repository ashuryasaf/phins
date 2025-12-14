#!/bin/bash
#
# Master Test Runner for PHINS
#
# Runs all test suites and generates comprehensive report
#

set -e  # Exit on error (but we'll handle test failures)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Banner
echo -e "${BLUE}"
cat << "EOF"
    ____  __  ___   _______   _______
   / __ \/ / / / | / / ___/  / ____(_)
  / /_/ / /_/ /  |/ /\__ \  / /_  / / 
 / ____/ __  / /|  /___/ / / __/ / /  
/_/   /_/ /_/_/ |_//____/ /_/   /_/   
                                       
Master Test Runner - All Pipelines
EOF
echo -e "${NC}"

echo "=========================================="
echo "  PHINS Comprehensive Test Suite"
echo "=========================================="
echo ""

# Check if pytest is available
if ! python3 -m pytest --version &> /dev/null; then
    echo -e "${RED}✗ pytest not found. Installing...${NC}"
    pip3 install pytest requests
fi

# Test results tracking
TOTAL_PASSED=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0
TEST_SUITES=()
SUITE_RESULTS=()

# Function to run a test suite
run_test_suite() {
    local suite_name=$1
    local test_file=$2
    local description=$3
    
    echo ""
    echo -e "${CYAN}======================================${NC}"
    echo -e "${CYAN}$suite_name${NC}"
    echo -e "${CYAN}$description${NC}"
    echo -e "${CYAN}======================================${NC}"
    
    if [ ! -f "$test_file" ]; then
        echo -e "${YELLOW}⚠ Test file not found: $test_file${NC}"
        SUITE_RESULTS+=("SKIP")
        return
    fi
    
    # Run tests and capture results
    if python3 -m pytest "$test_file" -v --tb=short 2>&1 | tee /tmp/pytest_output.txt; then
        echo -e "${GREEN}✓ $suite_name PASSED${NC}"
        SUITE_RESULTS+=("PASS")
        
        # Parse results
        passed=$(grep -oP '\d+(?= passed)' /tmp/pytest_output.txt | tail -1 || echo "0")
        TOTAL_PASSED=$((TOTAL_PASSED + passed))
    else
        echo -e "${RED}✗ $suite_name FAILED${NC}"
        SUITE_RESULTS+=("FAIL")
        
        # Parse results even on failure
        passed=$(grep -oP '\d+(?= passed)' /tmp/pytest_output.txt | tail -1 || echo "0")
        failed=$(grep -oP '\d+(?= failed)' /tmp/pytest_output.txt | tail -1 || echo "0")
        TOTAL_PASSED=$((TOTAL_PASSED + passed))
        TOTAL_FAILED=$((TOTAL_FAILED + failed))
    fi
    
    TEST_SUITES+=("$suite_name")
}

# Start time
START_TIME=$(date +%s)

echo -e "${BLUE}Starting comprehensive test run...${NC}"
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Run all test suites
run_test_suite \
    "Smoke Tests" \
    "tests/test_smoke_critical_paths.py" \
    "Quick validation of critical paths"

run_test_suite \
    "E2E Insurance Pipeline" \
    "tests/test_e2e_insurance_pipeline.py" \
    "Complete customer journey tests"

run_test_suite \
    "API Integration" \
    "tests/test_api_integration.py" \
    "All API endpoint tests"

run_test_suite \
    "Security & Performance" \
    "tests/test_security_performance.py" \
    "Security validation and performance tests"

run_test_suite \
    "Data Persistence" \
    "tests/test_data_persistence.py" \
    "Data persistence validation"

# End time
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Generate summary report
echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}TEST SUMMARY${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Individual suite results
echo "Suite Results:"
for i in "${!TEST_SUITES[@]}"; do
    suite="${TEST_SUITES[$i]}"
    result="${SUITE_RESULTS[$i]}"
    
    if [ "$result" == "PASS" ]; then
        echo -e "  ${GREEN}✓${NC} $suite"
    elif [ "$result" == "FAIL" ]; then
        echo -e "  ${RED}✗${NC} $suite"
    else
        echo -e "  ${YELLOW}⊘${NC} $suite (skipped)"
    fi
done

echo ""
echo "Overall Results:"
echo -e "  ${GREEN}Passed:${NC}  $TOTAL_PASSED"
if [ $TOTAL_FAILED -gt 0 ]; then
    echo -e "  ${RED}Failed:${NC}  $TOTAL_FAILED"
fi
if [ $TOTAL_SKIPPED -gt 0 ]; then
    echo -e "  ${YELLOW}Skipped:${NC} $TOTAL_SKIPPED"
fi

echo ""
echo "Duration: ${DURATION}s"
echo "End time: $(date '+%Y-%m-%d %H:%M:%S')"

echo ""
echo -e "${BLUE}======================================${NC}"

# Calculate success rate
TOTAL_TESTS=$((TOTAL_PASSED + TOTAL_FAILED))
if [ $TOTAL_TESTS -gt 0 ]; then
    SUCCESS_RATE=$((TOTAL_PASSED * 100 / TOTAL_TESTS))
    echo "Success Rate: ${SUCCESS_RATE}%"
    
    if [ $SUCCESS_RATE -eq 100 ]; then
        echo -e "${GREEN}✅ ALL TESTS PASSED!${NC}"
    elif [ $SUCCESS_RATE -ge 80 ]; then
        echo -e "${YELLOW}⚠️  MOSTLY PASSING (${SUCCESS_RATE}%)${NC}"
    else
        echo -e "${RED}❌ CRITICAL FAILURES (${SUCCESS_RATE}%)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  NO TESTS RUN${NC}"
fi

echo -e "${BLUE}======================================${NC}"
echo ""

# Additional checks
echo "Additional Checks:"

# Check if server file exists
if [ -f "web_portal/server.py" ]; then
    echo -e "  ${GREEN}✓${NC} Server file exists"
else
    echo -e "  ${RED}✗${NC} Server file missing"
fi

# Check if config files exist
if [ -f "railway.json" ]; then
    echo -e "  ${GREEN}✓${NC} railway.json exists"
else
    echo -e "  ${YELLOW}⚠${NC} railway.json missing"
fi

if [ -f "Dockerfile" ]; then
    echo -e "  ${GREEN}✓${NC} Dockerfile exists"
else
    echo -e "  ${YELLOW}⚠${NC} Dockerfile missing"
fi

if [ -f "requirements.txt" ]; then
    echo -e "  ${GREEN}✓${NC} requirements.txt exists"
else
    echo -e "  ${RED}✗${NC} requirements.txt missing"
fi

echo ""
echo "=========================================="
echo "  Test Run Complete"
echo "=========================================="
echo ""

# Recommendations
if [ $TOTAL_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ Ready for deployment!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run config validation: ${CYAN}python3 validate_railway_config.py${NC}"
    echo "  2. Deploy to Railway: ${CYAN}./deploy_railway_verified.sh${NC}"
    echo "  3. Run health check: ${CYAN}python3 railway_health_check.py <URL>${NC}"
else
    echo -e "${RED}❌ Please fix failing tests before deployment${NC}"
    echo ""
    echo "To see detailed failures, run:"
    echo "  ${CYAN}python3 -m pytest tests/ -v --tb=short${NC}"
fi

echo ""

# Exit with appropriate code
if [ $TOTAL_FAILED -eq 0 ]; then
    exit 0
else
    exit 1
fi
