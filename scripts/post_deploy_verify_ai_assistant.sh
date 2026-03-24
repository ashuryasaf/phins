#!/usr/bin/env bash

set -euo pipefail

BASE_URL="https://www.phins.ai"
TIMEOUT_SECONDS=20

usage() {
  cat <<'EOF'
Post-deploy verification for PHINS AI assistant changes.

Usage:
  bash scripts/post_deploy_verify_ai_assistant.sh [--base-url URL] [--timeout SECONDS]

Options:
  --base-url URL      Base URL to verify (default: https://www.phins.ai)
  --timeout SECONDS   curl timeout in seconds (default: 20)
  -h, --help          Show this help message

Examples:
  bash scripts/post_deploy_verify_ai_assistant.sh
  bash scripts/post_deploy_verify_ai_assistant.sh --base-url https://staging.phins.ai --timeout 30
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="${2:-}"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 2
      ;;
  esac
done

BASE_URL="${BASE_URL%/}"

if [[ -z "$BASE_URL" ]]; then
  echo "ERROR: base URL cannot be empty"
  exit 2
fi

declare -i PASSED=0
declare -i FAILED=0

pass() {
  PASSED=$((PASSED + 1))
  echo "✅ $1"
}

fail() {
  FAILED=$((FAILED + 1))
  echo "❌ $1"
}

fetch_path() {
  local path="$1"
  curl -fsSL --max-time "$TIMEOUT_SECONDS" "${BASE_URL}${path}"
}

assert_contains() {
  local path="$1"
  local needle="$2"
  local label="$3"
  local content
  if ! content="$(fetch_path "$path")"; then
    fail "${label} (could not fetch ${path})"
    return
  fi

  if [[ "$content" == *"$needle"* ]]; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_script_injection_once() {
  local path="$1"
  local label="$2"
  local content
  if ! content="$(fetch_path "$path")"; then
    fail "${label} (could not fetch ${path})"
    return
  fi

  local count
  count="$(python3 - "$content" <<'PY'
import sys
payload = sys.argv[1]
print(payload.count('<script src="/ui-clarity.js"></script>'))
PY
)"

  if [[ "$count" == "1" ]]; then
    pass "$label"
  else
    fail "$label (found ${count} injections)"
  fi
}

echo "🔎 PHINS AI assistant post-deploy verification"
echo "🌐 Base URL: ${BASE_URL}"
echo

assert_contains "/dashboard.html" 'id="ai-assistant-panel"' "Customer assistant panel present"
assert_contains "/dashboard.html" 'id="ai-panel-minimize-btn"' "Customer assistant minimize control present"
assert_contains "/dashboard.html" "toggleButton.textContent = '🎤➕';" "Customer minimize state shows voice icon"
assert_contains "/dashboard.html" 'id="ai-query-row"' "Customer minimized query row wiring present"

assert_contains "/admin.html" 'id="admin-ai-assistant-panel"' "Admin assistant panel present"
assert_contains "/admin.html" 'id="admin-ai-panel-minimize-btn"' "Admin assistant minimize control present"
assert_contains "/admin.html" "toggleButton.textContent = '🎤➕';" "Admin minimize state shows voice icon"
assert_contains "/admin.html" 'id="admin-ai-query-row"' "Admin minimized query row wiring present"

assert_script_injection_once "/dashboard.html" "ui-clarity injected once on customer dashboard"
assert_script_injection_once "/admin.html" "ui-clarity injected once on admin dashboard"
assert_script_injection_once "/login.html" "ui-clarity injected once on login page"

assert_contains "/ui-clarity.js" 'const FLOATING_BAR_ID = "phins-vqa-bar";' "Floating bar bootstrap constant present"
assert_contains "/ui-clarity.js" "PHINS admin AI Assistant" "Admin floating assistant branding present"
assert_contains "/ui-clarity.js" "startFloatingVoiceInput" "Floating voice start handler present"
assert_contains "/ui-clarity.js" "run_actuary_portfolio_simulation" "Deferred actuary simulation action present"
assert_contains "/ui-clarity.js" 'id: "admin_logout"' "Admin logout command mapping present"

echo
echo "📊 Verification summary: ${PASSED} passed, ${FAILED} failed"

if [[ $FAILED -gt 0 ]]; then
  echo "❗ Post-deploy verification failed."
  exit 1
fi

echo "✅ Post-deploy verification passed."
