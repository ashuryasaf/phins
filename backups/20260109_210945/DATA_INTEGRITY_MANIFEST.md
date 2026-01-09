# PHINS Platform Data Integrity Manifest
## Backup Date: January 9, 2026 - 21:09:45 UTC

---

## 📦 BACKUP CONTENTS

| File | Description | Size |
|------|-------------|------|
| `phins_repo_full.bundle` | Complete Git repository bundle | ~5.5MB |
| `seeds_backup.py` | Database seed data (users, customers) | ~42KB |
| `config_backup.py` | Database configuration | ~5KB |
| `server_config_snapshot.py` | Server configuration (first 300 lines) | ~12KB |
| `static_files_list.txt` | List of all static web files | ~3KB |
| `recent_commits.txt` | Last 20 git commits | ~1KB |

---

## 👥 USER ACCOUNTS (Preserved)

### System/Staff Accounts
| Username | Role | Access |
|----------|------|--------|
| `admin` | admin | Full platform access |
| `media_ad` | media | Media Dashboard only |
| `underwriter` | underwriter | Underwriting Dashboard |
| `claims_adjuster` | claims | Claims Dashboard |
| `accountant` | accountant | Accountant Dashboard |
| `actuary` | actuary | Actuary Dashboard |
| `supplier` | supplier | Supplier Dashboard |
| `asaf@phins.ai` | admin | Full platform access |

### Customer Accounts
| Username | Customer ID | Status |
|----------|-------------|--------|
| `asaf@assurance.co.il` | CUST-ASAF-001 | Active |
| `efrat@phins.ai` | CUST-EFRAT-001 | Active |
| `asi@phins.ai` | CUST-ASI-001 | Active |
| `shosh@phins.ai` | CUST-SHOSH-001 | Active |

---

## 🗄️ DATA STORAGE LAYERS

### 1. Database (SQLite/PostgreSQL)
- Users table
- Customers table
- Policies table
- Claims table
- Underwriting applications
- Sessions table
- Audit logs

### 2. In-Memory + Persistence (Ledger File v1.6)
- HEALTH_WALLETS
- MEDICAL_PURCHASES
- NFT_LEDGER
- CUSTOMER_ALLOCATIONS
- INVESTMENT_ACCOUNTS
- TRANSACTION_LEDGER
- BILLING
- POLICIES
- CUSTOMERS
- UNDERWRITING_APPLICATIONS
- CLAIMS
- CLAIM_FILES
- UNDERWRITING_FILES
- MEDIA_ASSETS
- DESIGN_SETTINGS
- PHINS_BALANCE_SHEET

### 3. Design Settings
- hero_video_id
- hero_background_id
- video_poster_id
- promo_banner_id
- tagline
- primary_color
- accent_color
- show_video
- show_contact

---

## 🔐 ROLE-BASED ACCESS CONTROL

| Role | Dashboards | API Access |
|------|------------|------------|
| admin | All | All endpoints |
| media | admin-media.html | /api/media, /api/design/settings |
| underwriter | underwriter-dashboard.html | /api/underwriting, /api/policies |
| claims | claims-adjuster-dashboard.html | /api/claims |
| accountant | accountant-dashboard.html | /api/billing, /api/reports |
| actuary | actuary-dashboard.html | /api/actuarial |
| supplier | supplier-dashboard.html | /api/suppliers |
| customer | dashboard.html, client-portal.html | Customer-specific data only |

---

## 📊 PIPELINE COMPONENTS

### Underwriting Pipeline
1. Customer submits application (`/api/policies/create`)
2. Documents uploaded and stored
3. Risk assessment generated
4. Underwriter reviews
5. Approve/Reject decision
6. Policy created on approval

### Claims Pipeline
1. Customer files claim (`/api/claims/create`)
2. Documents attached
3. Claims Bot AI analysis
4. Risk/Fraud assessment
5. Claims adjuster review
6. Approve/Reject/Pay decision

### Billing Pipeline
1. Monthly premium calculations
2. Invoice generation
3. Payment processing
4. Transaction ledger updates
5. Balance sheet updates

---

## 🔄 HOW TO RESTORE

### Restore Git Repository
```bash
git clone phins_repo_full.bundle phins-restored
cd phins-restored
git checkout main
```

### Restore Database Seeds
```bash
cp seeds_backup.py database/seeds.py
python -c "from database.seeds import seed_default_users; seed_default_users()"
```

### Verify Data Integrity
1. Check user accounts exist
2. Verify customer data
3. Test API endpoints
4. Confirm role-based access

---

## ✅ DATA INTEGRITY CHECKLIST

- [x] All user accounts preserved
- [x] Customer data maintained
- [x] Role definitions intact
- [x] API endpoints functional
- [x] Persistence layer (v1.6) active
- [x] Media assets storage ready
- [x] Design settings preserved
- [x] Pipeline workflows operational

---

## 📞 RECOVERY CONTACT

For data recovery assistance, this manifest contains all necessary information to restore the platform to its current state.

**Backup Created By**: AI Assistant
**Platform Version**: PHINS v1.6
**Git Commit**: See recent_commits.txt
