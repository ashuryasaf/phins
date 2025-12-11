PHINS PDF Generation & Visual Testing

This file documents how to generate client PDF reports, run tests, and configure CI for visual testing.

Quick local usage

1. Create and activate venv (optional):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

2. Generate a demo PDF (B2B/B2C friendly branding):

```bash
# demo mode (creates demo allocations)
python generate_client_pdf.py --customer CUST-EXAMPLE --output sample_report.pdf

# use real allocations if available
python generate_client_pdf.py --customer REAL_CUST_ID --no-demo --output sample_report_real.pdf
```

Branding

- The script reads the following env vars to override branding (useful for B2B white-label or regional instances):
  - `PHINS_COMPANY_NAME` (default: "PHINS Insurance")
  - `PHINS_COMPANY_ADDRESS`
  - `PHINS_COMPANY_CONTACT`

Visual testing / upload

- Use `visual_upload.py` to upload generated PDFs to a visual-testing target or S3.

Examples:

```bash
python visual_upload.py -f sample_report.pdf -b transfer
python visual_upload.py -f sample_report.pdf -b fileio
# S3 (requires AWS creds in env)
python - <<'PY'
from visual_upload import upload_s3
from pathlib import Path
print(upload_s3(Path('sample_report.pdf'), bucket='my-test-bucket', key='reports/sample_report.pdf'))
PY
```

CI

- `.github/workflows/visual_test.yml` runs on PR and push to `main`.
- Set these GitHub secrets to enable S3 upload in CI: `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `VISUAL_TEST_BUCKET`.

Notes

- For PDF → image conversion the workflow installs `poppler-utils`. If you run locally, install `poppler` for your OS.
- Tests use `pytest`; run `python -m pytest -q`.
- For secure production usage, replace demo allocations with your business data source and add proper access controls for generated reports.
