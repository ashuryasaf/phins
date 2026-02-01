#!/bin/bash

# PHINS Platform Restore Preview
# Shows what would be restored without making changes
# Usage: ./preview_restore.sh [COMMIT_HASH or DATE]

set -e

# Default restore point: January 30, 2026, 13:00 UTC
DEFAULT_RESTORE_POINT="2026-01-30 13:00:00"
DEFAULT_COMMIT="337d9aab5340184e499598f3174452db5f99fd93"

echo "═══════════════════════════════════════════════"
echo "   PHINS Platform Restore Preview"
echo "═══════════════════════════════════════════════"
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
        echo "Error: No commit found before date: $date_str"
        exit 1
    fi
    echo "$commit"
}

# Determine target commit
TARGET_COMMIT=""
RESTORE_REASON=""

if [ $# -eq 0 ]; then
    echo "No restore point specified. Using default:"
    echo "  Date: $DEFAULT_RESTORE_POINT UTC"
    echo "  Commit: $DEFAULT_COMMIT"
    TARGET_COMMIT="$DEFAULT_COMMIT"
    RESTORE_REASON="Default restore point (January 30, 2026 at 13:00 UTC)"
elif is_commit_hash "$1"; then
    TARGET_COMMIT="$1"
    RESTORE_REASON="Specified commit hash"
else
    echo "Searching for commit valid at: $1"
    TARGET_COMMIT=$(find_commit_by_date "$1")
    RESTORE_REASON="Last commit before $1"
fi

# Display commit information
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Target Commit Details:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
git log -1 --format="%H%nAuthor:  %an <%ae>%nDate:    %ai%nSubject: %s%n" "$TARGET_COMMIT"
echo "Reason: $RESTORE_REASON"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show full commit message
echo "Full Commit Message:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
git log -1 --format="%B" "$TARGET_COMMIT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show files that would be changed
echo "Files Changed in This Commit:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
git diff-tree --no-commit-id --name-status -r "$TARGET_COMMIT" | head -20
FILE_COUNT=$(git diff-tree --no-commit-id --name-only -r "$TARGET_COMMIT" | wc -l)
if [ "$FILE_COUNT" -gt 20 ]; then
    echo "... and $(($FILE_COUNT - 20)) more files"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show commits between current and target
CURRENT_COMMIT=$(git rev-parse HEAD)
if [ "$CURRENT_COMMIT" != "$TARGET_COMMIT" ]; then
    echo "Commits That Will Be Undone:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    COMMIT_DIFF=$(git rev-list --count "$TARGET_COMMIT..$CURRENT_COMMIT" 2>/dev/null || echo "0")
    if [ "$COMMIT_DIFF" -gt 0 ]; then
        echo "You will go back $COMMIT_DIFF commit(s):"
        echo ""
        git log --oneline --decorate "$TARGET_COMMIT..$CURRENT_COMMIT" | head -10
        if [ "$COMMIT_DIFF" -gt 10 ]; then
            echo "... and $(($COMMIT_DIFF - 10)) more commits"
        fi
    else
        echo "Target commit is ahead of current HEAD."
        FORWARD_COMMIT_DIFF=$(git rev-list --count "$CURRENT_COMMIT..$TARGET_COMMIT" 2>/dev/null || echo "0")
        if [ "$FORWARD_COMMIT_DIFF" -gt 0 ]; then
            echo "You will go forward $FORWARD_COMMIT_DIFF commit(s):"
            echo ""
            git log --oneline --decorate "$CURRENT_COMMIT..$TARGET_COMMIT" | head -10
        fi
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
fi

# Show current state
echo "Current Repository State:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Current branch: $(git rev-parse --abbrev-ref HEAD)"
echo "Current commit: $CURRENT_COMMIT"
git log -1 --format="Date: %ai%nMessage: %s" HEAD
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show next steps
echo "═══════════════════════════════════════════════"
echo "   Next Steps"
echo "═══════════════════════════════════════════════"
echo ""
echo "To restore to this commit, run:"
echo "  ./restore_platform.sh $TARGET_COMMIT"
echo ""
echo "Or restore by date:"
echo "  ./restore_platform.sh \"$DEFAULT_RESTORE_POINT\""
echo ""
echo "For more information, see: RESTORE_GUIDE.md"
echo ""
