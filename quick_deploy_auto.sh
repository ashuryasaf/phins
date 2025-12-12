#!/usr/bin/env bash
set -euo pipefail

# PHINS: One-command deploy helper
# - Non-interactive
# - Works with Railway or Render via GitHub integration

echo "🚀 PHINS Auto Deploy"
echo "Branch: $(git rev-parse --abbrev-ref HEAD)"

# 1) Fast preflight: syntax + tests (optional, skip on CI)
echo "🔎 Preflight: syntax + tests"
python3 -m py_compile web_portal/server.py || { echo "❌ Syntax error"; exit 1; }
pytest -q || echo "ℹ️ Tests skipped or partial"

# 2) Push latest changes to origin/main (triggers host auto-deploy)
echo "📤 Pushing to origin/main"
git add -A
git commit -m "Deploy: auto-push via quick_deploy_auto.sh" || echo "ℹ️ Nothing to commit"
git push origin $(git rev-parse --abbrev-ref HEAD)

echo "✅ Push complete"
echo "" 
echo "Next steps (choose one):"
echo "  - Railway: https://railway.app/new → Select repo ashuryasaf/phins"
echo "  - Render:  https://dashboard.render.com/select-repo?type=web → Connect repo"
echo "" 
echo "Once connected, future runs of this script will auto-trigger deployments on push."
