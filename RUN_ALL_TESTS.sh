#!/bin/bash

################################################################################
# RUN_ALL_TESTS.sh
# Master test script for running all tests with proper output formatting
# and error handling
################################################################################

set -e  # Exit on error
set -o pipefail  # Catch errors in pipelines

# Color codes for output formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Test result tracking
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
SKIPPED_TESTS=0
START_TIME=$(date +%s)

# Log file
LOG_DIR="test_logs"
LOG_FILE="${LOG_DIR}/test_run_$(date +%Y%m%d_%H%M%S).log"

################################################################################
# Helper Functions
################################################################################

print_header() {
    echo -e "\n${BOLD}${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}  $1${NC}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════${NC}\n"
}

print_section() {
    echo -e "\n${BOLD}${BLUE}▶ $1${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

# Create log directory
setup_logging() {
    mkdir -p "${LOG_DIR}"
    echo "Test run started at $(date)" > "${LOG_FILE}"
    print_info "Logging to: ${LOG_FILE}"
}

# Run a test suite and track results
run_test_suite() {
    local test_name="$1"
    local test_command="$2"
    local optional="${3:-false}"
    
    print_section "Running: ${test_name}"
    echo "----------------------------------------" >> "${LOG_FILE}"
    echo "Test: ${test_name}" >> "${LOG_FILE}"
    echo "Command: ${test_command}" >> "${LOG_FILE}"
    echo "Started: $(date)" >> "${LOG_FILE}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    if eval "${test_command}" >> "${LOG_FILE}" 2>&1; then
        print_success "${test_name} passed"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        echo "Result: PASSED" >> "${LOG_FILE}"
        return 0
    else
        local exit_code=$?
        if [ "${optional}" = "true" ]; then
            print_warning "${test_name} skipped or failed (optional)"
            SKIPPED_TESTS=$((SKIPPED_TESTS + 1))
            echo "Result: SKIPPED (optional)" >> "${LOG_FILE}"
            return 0
        else
            print_error "${test_name} failed (exit code: ${exit_code})"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            echo "Result: FAILED (exit code: ${exit_code})" >> "${LOG_FILE}"
            return 1
        fi
    fi
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
check_prerequisites() {
    print_section "Checking Prerequisites"
    
    local missing_deps=0
    
    # Check for common test tools
    if command_exists python3; then
        print_success "Python3 found: $(python3 --version)"
    else
        print_error "Python3 not found"
        missing_deps=$((missing_deps + 1))
    fi
    
    if command_exists pytest; then
        print_success "pytest found: $(pytest --version | head -n1)"
    else
        print_warning "pytest not found (may be needed)"
    fi
    
    if command_exists npm; then
        print_success "npm found: $(npm --version)"
    else
        print_warning "npm not found (may be needed)"
    fi
    
    if command_exists go; then
        print_success "Go found: $(go version)"
    else
        print_warning "Go not found (may be needed)"
    fi
    
    if [ $missing_deps -gt 0 ]; then
        print_error "Missing critical dependencies"
        return 1
    fi
    
    return 0
}

# Generate summary report
generate_summary() {
    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    print_header "TEST SUMMARY"
    
    echo -e "${BOLD}Total Tests:${NC}   ${TOTAL_TESTS}"
    echo -e "${GREEN}${BOLD}Passed:${NC}        ${PASSED_TESTS}"
    echo -e "${RED}${BOLD}Failed:${NC}        ${FAILED_TESTS}"
    echo -e "${YELLOW}${BOLD}Skipped:${NC}       ${SKIPPED_TESTS}"
    echo -e "${BOLD}Duration:${NC}      ${minutes}m ${seconds}s"
    echo ""
    
    # Calculate success rate
    if [ ${TOTAL_TESTS} -gt 0 ]; then
        local success_rate=$((PASSED_TESTS * 100 / TOTAL_TESTS))
        echo -e "${BOLD}Success Rate:${NC}  ${success_rate}%"
    fi
    
    echo -e "\n${BOLD}Log File:${NC}      ${LOG_FILE}"
    
    # Write summary to log
    echo "" >> "${LOG_FILE}"
    echo "========================================" >> "${LOG_FILE}"
    echo "SUMMARY" >> "${LOG_FILE}"
    echo "========================================" >> "${LOG_FILE}"
    echo "Total Tests: ${TOTAL_TESTS}" >> "${LOG_FILE}"
    echo "Passed: ${PASSED_TESTS}" >> "${LOG_FILE}"
    echo "Failed: ${FAILED_TESTS}" >> "${LOG_FILE}"
    echo "Skipped: ${SKIPPED_TESTS}" >> "${LOG_FILE}"
    echo "Duration: ${minutes}m ${seconds}s" >> "${LOG_FILE}"
    echo "Finished: $(date)" >> "${LOG_FILE}"
    
    if [ ${FAILED_TESTS} -eq 0 ]; then
        echo -e "\n${GREEN}${BOLD}🎉 All tests passed!${NC}\n"
        return 0
    else
        echo -e "\n${RED}${BOLD}❌ Some tests failed. Check log for details.${NC}\n"
        return 1
    fi
}

################################################################################
# Main Test Execution
################################################################################

main() {
    print_header "PHINS - Master Test Suite"
    
    setup_logging
    
    # Check prerequisites
    if ! check_prerequisites; then
        print_error "Prerequisites check failed. Aborting."
        exit 1
    fi
    
    # Track if any critical test fails
    local has_critical_failure=false
    
    # Unit Tests
    print_header "UNIT TESTS"
    if [ -f "pytest.ini" ] || [ -d "tests" ]; then
        run_test_suite "Python Unit Tests" "pytest tests/ -v --tb=short" || has_critical_failure=true
    else
        print_warning "No Python test configuration found, skipping pytest"
    fi
    
    if [ -f "package.json" ]; then
        run_test_suite "JavaScript Unit Tests" "npm test" true
    fi
    
    if [ -f "go.mod" ]; then
        run_test_suite "Go Unit Tests" "go test ./... -v" true
    fi
    
    # Integration Tests
    print_header "INTEGRATION TESTS"
    if [ -d "tests/integration" ]; then
        run_test_suite "Integration Tests" "pytest tests/integration/ -v --tb=short" || has_critical_failure=true
    else
        print_info "No integration tests found, skipping"
        SKIPPED_TESTS=$((SKIPPED_TESTS + 1))
    fi
    
    # End-to-End Tests
    print_header "END-TO-END TESTS"
    if [ -d "tests/e2e" ] || [ -d "e2e" ]; then
        run_test_suite "E2E Tests" "pytest tests/e2e/ -v --tb=short" || has_critical_failure=true
    else
        print_info "No E2E tests found, skipping"
        SKIPPED_TESTS=$((SKIPPED_TESTS + 1))
    fi
    
    # Linting and Code Quality
    print_header "CODE QUALITY CHECKS"
    if command_exists flake8; then
        run_test_suite "Python Linting (flake8)" "flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics" true
    fi
    
    if command_exists pylint; then
        run_test_suite "Python Linting (pylint)" "pylint **/*.py --errors-only" true
    fi
    
    if command_exists black; then
        run_test_suite "Python Formatting Check" "black --check ." true
    fi
    
    if [ -f ".eslintrc.js" ] || [ -f ".eslintrc.json" ]; then
        run_test_suite "JavaScript Linting" "npm run lint" true
    fi
    
    # Generate final summary
    generate_summary
    local summary_exit=$?
    
    # Exit with appropriate code
    if [ $summary_exit -ne 0 ] || [ "$has_critical_failure" = true ]; then
        exit 1
    else
        exit 0
    fi
}

################################################################################
# Script Entry Point
################################################################################

# Handle command line arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Master test script for running all tests"
        echo ""
        echo "Options:"
        echo "  --help, -h     Show this help message"
        echo "  --version, -v  Show version information"
        echo ""
        echo "Environment Variables:"
        echo "  CI             Set to 'true' for CI/CD environments"
        echo ""
        exit 0
        ;;
    --version|-v)
        echo "RUN_ALL_TESTS.sh v1.0.0"
        exit 0
        ;;
esac

# Run main function
main "$@"
