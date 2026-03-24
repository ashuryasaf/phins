# PHINS AI Assistant Post-Deploy Verification Checklist

Use this checklist immediately after merging and deploying PR #204 to production.

## 1) Prerequisites
- [ ] Production deployment completed successfully
- [ ] `https://www.phins.ai` reachable
- [ ] Have valid credentials for:
  - [ ] admin
  - [ ] customer user

## 2) Automated HTTP smoke checks
- [ ] Run:

```bash
bash scripts/post_deploy_verify_ai_assistant.sh --base-url https://www.phins.ai
```

- [ ] Script exits successfully (0) and prints `Post-deploy verification passed`

## 3) Manual UI checks — Admin
- [ ] Sign in as admin and open `https://www.phins.ai/admin.html`
- [ ] Confirm panel title: **PHINS admin AI Assistant**
- [ ] Click minimize (`➖`) and verify:
  - [ ] Query row remains visible
  - [ ] Minimized toggle shows `🎤➕`
- [ ] Click expand and verify:
  - [ ] Toggle returns to `➖`
- [ ] Voice input starts/stops without UI errors
- [ ] Floating assistant appears at lower-right
- [ ] Floating assistant admin quick actions are present

## 4) Manual UI checks — Customer
- [ ] Sign in as customer and open `https://www.phins.ai/dashboard.html`
- [ ] Confirm panel title: **PHINS AI Assistant**
- [ ] Click minimize (`➖`) and verify:
  - [ ] Query row remains visible
  - [ ] Minimized toggle shows `🎤➕`
- [ ] Click expand and verify:
  - [ ] Toggle returns to `➖`
- [ ] Voice input starts/stops without UI errors
- [ ] Floating assistant appears at lower-right

## 5) Admin hierarchy command checks (floating assistant)
- [ ] Test voice/text command: `open actuary dashboard`
- [ ] Test voice/text command: `run portfolio simulation`
- [ ] Test voice/text command: `logout`
- [ ] Confirm command routing executes expected navigation/actions with existing confirmations

## 6) Data integrity guardrail checks
- [ ] High-impact actions still show confirmation prompts
- [ ] No unauthorized action appears for non-admin context
- [ ] No browser console errors during assistant usage

## 7) Sign-off
- [ ] Release owner sign-off
- [ ] Product owner sign-off
- [ ] Support/ops informed rollout complete
