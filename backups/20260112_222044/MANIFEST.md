# PHINS Platform Backup

## Backup Contents

| File | Description |
|------|-------------|
| balance_sheet.json | PHINS General Reserves ($3.5M claims reserve) |
| customers.json | All registered customers |
| policies.json | Insurance policies |
| claims.json | Claims data |
| underwriting.json | Underwriting applications |
| billing.json | Billing records |
| bi_dashboard.json | Business intelligence data |
| platform_analytics.json | Platform analytics |
| git_commits.txt | Recent git commits |
| current_commit.txt | Current deployed commit |

## Restore Instructions

1. Deploy the commit in `current_commit.txt`
2. Use `/api/admin/seed-data` to reinitialize database
3. Import data using admin APIs if needed

## Platform URL
https://phins-portal-production.up.railway.app/

