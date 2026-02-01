#!/bin/bash

# Test script to verify the restore solution
# This doesn't actually restore, just validates the tools work

echo "════════════════════════════════════════════════════"
echo "  Testing PHINS Platform Restore Solution"
echo "════════════════════════════════════════════════════"
echo ""

TESTS_PASSED=0
TESTS_FAILED=0

# Test 1: Check if scripts exist and are executable
echo "Test 1: Checking script files..."
if [ -x restore_platform.sh ]; then
    echo "  ✓ restore_platform.sh exists and is executable"
    ((TESTS_PASSED++))
else
    echo "  ✗ restore_platform.sh missing or not executable"
    ((TESTS_FAILED++))
fi

if [ -x preview_restore.sh ]; then
    echo "  ✓ preview_restore.sh exists and is executable"
    ((TESTS_PASSED++))
else
    echo "  ✗ preview_restore.sh missing or not executable"
    ((TESTS_FAILED++))
fi

# Test 2: Check if documentation exists
echo ""
echo "Test 2: Checking documentation files..."
if [ -f RESTORE_GUIDE.md ]; then
    echo "  ✓ RESTORE_GUIDE.md exists"
    ((TESTS_PASSED++))
else
    echo "  ✗ RESTORE_GUIDE.md missing"
    ((TESTS_FAILED++))
fi

if [ -f HOW_TO_RESTORE.md ]; then
    echo "  ✓ HOW_TO_RESTORE.md exists"
    ((TESTS_PASSED++))
else
    echo "  ✗ HOW_TO_RESTORE.md missing"
    ((TESTS_FAILED++))
fi

# Test 3: Verify target commit exists
echo ""
echo "Test 3: Verifying target commit exists..."
TARGET_COMMIT="337d9aab5340184e499598f3174452db5f99fd93"
if git rev-parse --verify "$TARGET_COMMIT^{commit}" &>/dev/null; then
    echo "  ✓ Target commit $TARGET_COMMIT exists"
    ((TESTS_PASSED++))
else
    echo "  ✗ Target commit $TARGET_COMMIT not found"
    ((TESTS_FAILED++))
fi

# Test 4: Verify commit date
echo ""
echo "Test 4: Verifying commit date..."
COMMIT_DATE=$(git log -1 --format="%ai" "$TARGET_COMMIT" 2>/dev/null)
if [[ "$COMMIT_DATE" == "2026-01-30 12:51:47"* ]]; then
    echo "  ✓ Commit date is correct: $COMMIT_DATE"
    ((TESTS_PASSED++))
else
    echo "  ✗ Commit date unexpected: $COMMIT_DATE"
    ((TESTS_FAILED++))
fi

# Test 5: Check git repository status
echo ""
echo "Test 5: Checking git repository..."
if git status &>/dev/null; then
    echo "  ✓ Git repository is valid"
    ((TESTS_PASSED++))
else
    echo "  ✗ Git repository is invalid"
    ((TESTS_FAILED++))
fi

# Test 6: Verify preview script runs without errors
echo ""
echo "Test 6: Testing preview script..."
if ./preview_restore.sh >/dev/null 2>&1; then
    echo "  ✓ Preview script runs without errors"
    ((TESTS_PASSED++))
else
    echo "  ✗ Preview script has errors"
    ((TESTS_FAILED++))
fi

# Test 7: Check backup directory
echo ""
echo "Test 7: Checking backup directory..."
if [ -d backups ]; then
    BACKUP_COUNT=$(ls -1 backups/ | wc -l)
    echo "  ✓ Backup directory exists with $BACKUP_COUNT backup(s)"
    ((TESTS_PASSED++))
else
    echo "  ✗ Backup directory missing"
    ((TESTS_FAILED++))
fi

# Test 8: Verify commit message content
echo ""
echo "Test 8: Verifying commit message..."
COMMIT_MSG=$(git log -1 --format="%s" "$TARGET_COMMIT")
if [[ "$COMMIT_MSG" == *"customer login"* ]]; then
    echo "  ✓ Commit message matches: '$COMMIT_MSG'"
    ((TESTS_PASSED++))
else
    echo "  ✗ Commit message unexpected: '$COMMIT_MSG'"
    ((TESTS_FAILED++))
fi

# Summary
echo ""
echo "════════════════════════════════════════════════════"
echo "  Test Results"
echo "════════════════════════════════════════════════════"
echo ""
echo "Tests Passed: $TESTS_PASSED"
echo "Tests Failed: $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo "✓ All tests passed! The restore solution is ready."
    echo ""
    echo "To restore the platform to January 30, 2026 at 13:00, run:"
    echo "  ./restore_platform.sh"
    echo ""
    echo "To preview first, run:"
    echo "  ./preview_restore.sh"
    exit 0
else
    echo "✗ Some tests failed. Please check the issues above."
    exit 1
fi
