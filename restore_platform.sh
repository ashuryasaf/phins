#!/bin/bash

# PHINS Platform Restore Script
# Restores platform to a specific git commit or date/time
# Usage: ./restore_platform.sh [COMMIT_HASH or DATE]
#
# Examples:
#   ./restore_platform.sh 337d9aab5340184e499598f3174452db5f99fd93
#   ./restore_platform.sh "2026-01-30 13:00"
#   ./restore_platform.sh (uses default: 2026-01-30 13:00)

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default restore point: January 30, 2026, 13:00 UTC
DEFAULT_RESTORE_POINT="2026-01-30 13:00:00"
DEFAULT_COMMIT="337d9aab5340184e499598f3174452db5f99fd93"

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   PHINS Platform Restore Utility${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

# Function to check if a string is a valid commit hash
is_commit_hash() {
    git rev-parse --verify "$1^{commit}" &>/dev/null
    return $?
}

# Function to find commit by date
find_commit_by_date() {
    local date_str="$1"
    local commit=$(git log --all --format="%H" --until="$date_str" -1)
    if [ -z "$commit" ]; then
        echo -e "${RED}Error: No commit found before date: $date_str${NC}"
        exit 1
    fi
    echo "$commit"
}

# Determine target commit
TARGET_COMMIT=""
RESTORE_REASON=""

if [ $# -eq 0 ]; then
    # No argument provided, use default
    echo -e "${YELLOW}No restore point specified. Using default:${NC}"
    echo -e "${YELLOW}  Date: $DEFAULT_RESTORE_POINT UTC${NC}"
    echo -e "${YELLOW}  Commit: $DEFAULT_COMMIT${NC}"
    TARGET_COMMIT="$DEFAULT_COMMIT"
    RESTORE_REASON="Default restore point (January 30, 2026 at 13:00 UTC)"
elif is_commit_hash "$1"; then
    # Argument is a commit hash
    TARGET_COMMIT="$1"
    RESTORE_REASON="Specified commit hash"
else
    # Argument is a date/time string
    echo -e "${BLUE}Searching for commit valid at: $1${NC}"
    TARGET_COMMIT=$(find_commit_by_date "$1")
    RESTORE_REASON="Last commit before $1"
fi

# Display commit information
echo ""
echo -e "${GREEN}Target Commit Information:${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
git log -1 --format="%H%nAuthor: %an <%ae>%nDate:   %ai%nSubject: %s%n" "$TARGET_COMMIT"
echo -e "${GREEN}Reason: $RESTORE_REASON${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}Warning: You have uncommitted changes.${NC}"
    echo -e "${YELLOW}These changes will be lost if you proceed.${NC}"
    echo ""
    git status --short
    echo ""
    read -p "Do you want to stash your changes? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Stashing uncommitted changes...${NC}"
        git stash push -u -m "Auto-stash before restore to $TARGET_COMMIT"
        echo -e "${GREEN}✓ Changes stashed${NC}"
    else
        read -p "Proceed without stashing? (y/n) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${RED}Restore cancelled.${NC}"
            exit 0
        fi
    fi
fi

# Final confirmation
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  ⚠️  WARNING: This will reset your repository${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
read -p "Are you sure you want to restore to commit $TARGET_COMMIT? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}Restore cancelled.${NC}"
    exit 0
fi

# Perform the restore
echo ""
echo -e "${BLUE}Restoring platform to commit: $TARGET_COMMIT${NC}"
echo ""

# Checkout the target commit
git checkout "$TARGET_COMMIT"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}   ✓ Platform Successfully Restored${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}Platform is now at commit: $TARGET_COMMIT${NC}"
echo -e "${GREEN}Date: $(git log -1 --format='%ai' $TARGET_COMMIT)${NC}"
echo -e "${GREEN}Message: $(git log -1 --format='%s' $TARGET_COMMIT)${NC}"
echo ""
echo -e "${YELLOW}Note: You are now in a 'detached HEAD' state.${NC}"
echo ""
echo -e "${YELLOW}To continue working from this point:${NC}"
echo -e "  1. Create a new branch: ${BLUE}git checkout -b restore-$(date +%Y%m%d)${NC}"
echo -e "  2. Or return to main: ${BLUE}git checkout main${NC}"
echo ""
echo -e "${YELLOW}To restore your previous work (if stashed):${NC}"
echo -e "  ${BLUE}git stash list${NC}   # View stashes"
echo -e "  ${BLUE}git stash pop${NC}    # Apply most recent stash"
echo ""
