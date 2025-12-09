# Copilot Instructions for PHINS Insurance Management System

## Project Overview

**PHINS** is a comprehensive insurance contract and policy management system built on Microsoft Dynamics 365 Business Central using AL language. It implements a complete insurance business platform with multiple operational divisions: Sales, Underwriting, Accounting, Claims, Legal, and Reinsurance, plus a customer portal for self-service access.

**Publisher ID**: PHI (use for all custom object IDs)

## Architecture & Core Components

### Data Model - Master Tables (src/Tables/)

**Customer-Centric Core:**
- `CustomerMaster` (ID: 50101): Individual/Business/Corporate customers with portal access flags
- `CompanyMaster` (ID: 50100): Insurance company master data, licenses, registration

**Insurance Operations:**
- `InsurancePolicyMaster` (ID: 50102): Policies with lifecycle (Active→Cancelled) and underwriting status
- `ClaimsMaster` (ID: 50103): Claims with approval workflow (Pending→Review→Approved→Paid)
- `BillingMaster` (ID: 50104): Invoices, payments, late fees, multiple payment methods
- `UnderwritingMaster` (ID: 50106): Risk assessment, medical requirements, premium adjustments
- `ReinsuranceMaster` (ID: 50105): Partner arrangements (Proportional/Non-Proportional/Excess-of-Loss types)

**Key Relationships:**
- Policy → Customer (customer has multiple policies)
- Claim → Policy → Customer (claims are policy-specific)
- Bill → Policy → Customer (billing for policy premiums)
- Underwriting → Policy (one underwriting per policy submission)

### Division-Specific Pages (src/Pages/)

| Page | Division | Purpose |
|------|----------|---------|
| `PoliciesListPage` (50101) | Sales | Policy CRUD, premium management, renewals |
| `UnderwritingListPage` (50104) | Underwriting | Risk assessment, approval/rejection/referral workflows |
| `BillingListPage` (50103) | Accounting | Invoice creation, payment recording, late fee application |
| `ClaimsListPage` (50102) | Claims | Claim submission, approval, payment processing |
| `ReinsuranceListPage` (50105) | Reinsurance | Partner mgmt, ceded amounts, commission rates |
| `CustomerPortalPage` (50106) | Portal | Self-service: view policies, claims, billing |
| `CustomerDashboardPage` (50107) | Portal | Role center with CUEs for metrics |

### Business Logic - Codeunits (src/Codeunits/)

**PolicyManagement** (50102):
- `CreatePolicy()`: Initialize policy with customer, premium, coverage
- `RenewPolicy()`: Extend dates, reset underwriting status
- `CancelPolicy()` / `SuspendPolicy()` / `ReactivatePolicy()`: State management

**ClaimsManagement** (50100):
- `CreateClaim()`: File new claim for active policy
- `ApproveClaim()`: Set approved amount and status
- `ProcessClaimPayment()`: Mark as paid with payment date
- `GetClaimStatus()`: Query current status

**BillingManagement** (50101):
- `CreateBill()`: Generate invoice for policy premium
- `RecordPayment()`: Update Amount Paid, adjust status (Outstanding→Partial→Paid)
- `ApplyLateFee()`: Add percentage-based fee for overdue bills
- `GetBillingStatement()`: Summarize customer's total due and overdue count

**UnderwritingEngine** (50103):
- `InitiateUnderwriting()`: Create assessment record for new policy
- `AssessRisk()`: Set risk level (Low/Medium/High/Very High), flag medical/doc requirements
- `ApproveUnderwriting()`: Apply premium adjustment, finalize decision
- `RequestAdditionalInfo()`: Refer decision, flag document requirements

## Key Business Workflows

### 1. Policy Sales → Underwriting → Billing
```
Create Customer → Create Policy (status: Active, UW: Pending) 
  → Initiate Underwriting 
  → Underwriter: AssessRisk/ApproveUnderwriting 
  → Create Bill (first premium) 
  → RecordPayment (activate/lock policy)
```

### 2. Claims Processing
```
Customer Files Claim (status: Pending) 
  → Claims Adjuster Reviews 
  → ApproveClaim (set approved amount) 
  → ProcessClaimPayment (move to Paid) 
  → Customer sees in portal
```

### 3. Billing & Collections
```
CreateBill (due 30 days) 
  → Send Reminder (if due) 
  → RecordPayment (tracks partial payments) 
  → ApplyLateFee (if overdue)
```

### 4. Reinsurance Protection
```
Identify high-value policies 
  → Create Reinsurance arrangement with partner 
  → Track ceded amounts and commissions
```

## Naming Conventions & Patterns

### Object IDs & Prefixes
- **Format**: PHI + 2-digit category + 4-digit number
- Tables: 501xx (50100-50199)
- Pages: 501xx (matching table)
- Codeunits: 501xx (50100-50199)

### Code Style
- **Objects & Procedures**: PascalCase (e.g., `InsurancePolicyMaster`, `ApproveClaim`)
- **Variables**: camelCase (e.g., `claimAmount`, `approvedStatus`)
- **Fields in tables**: Quoted PascalCase in AL source (e.g., `"Customer ID"`)
- **Constants**: UPPERCASE_WITH_UNDERSCORES

### Regions & Organization
Use `#region` for logical sections in large files:
```al
#region [Division Name] Operations
  procedure ...
#endregion
```

### DateTime Fields
All master tables include:
- `Created Date` (DateTime, non-editable, auto-set on insert)
- `Last Modified` (DateTime, auto-updated on modify) — *implement via triggers*

## Architecture Decisions

### Why Separate Codeunits by Division?
Each division's logic is encapsulated in its own codeunit, enabling:
- Independent testing and deployment
- Clear ownership (Sales team owns PolicyManagement, Claims owns ClaimsManagement)
- Easy extension for new divisions

### Why Portal Pages?
- `CustomerPortalPage` (Card): View-only profile + action buttons
- `CustomerDashboardPage` (RoleCenter): CUEs showing counts/metrics

Portal logic filters records by logged-in customer ID (implement via security context in future UI integration).

### Status Field Patterns
- **Policy Status**: Active, Inactive, Cancelled, Lapsed, Suspended
- **Underwriting Status**: Pending, Approved, Rejected, Referred, Approved-Conditional
- **Claim Status**: Pending, Under Review, Approved, Rejected, Paid, Closed
- **Bill Status**: Outstanding, Partial, Paid, Overdue, Cancelled

## Integration Points

### Future Integrations (API-Ready)
- **Payment Gateways**: Webhook receiver for online payments → `RecordPayment`
- **Email Service**: Trigger notifications on status changes (approval, payment due, claim status)
- **Document Storage**: Link to external document mgmt for policy/claim files
- **Medical Providers**: API for underwriting medical exam orders

### External Data
- `Reinsurance Partner` field is free-text (connect to external partner DB later)
- `Assigned To` fields (underwriter, adjuster) reference employee codes

## File Structure

```
src/
├── Tables/
│   ├── CompanyMaster.al
│   ├── CustomerMaster.al
│   ├── InsurancePolicyMaster.al
│   ├── ClaimsMaster.al
│   ├── BillingMaster.al
│   ├── ReinsuranceMaster.al
│   └── UnderwritingMaster.al
├── Pages/
│   ├── CompanyListPage.al
│   ├── PoliciesListPage.al
│   ├── ClaimsListPage.al
│   ├── BillingListPage.al
│   ├── UnderwritingListPage.al
│   ├── ReinsuranceListPage.al
│   ├── CustomerPortalPage.al
│   └── CustomerDashboardPage.al
└── Codeunits/
    ├── PolicyManagement.al
    ├── ClaimsManagement.al
    ├── BillingManagement.al
    └── UnderwritingEngine.al
```

## Development Workflow

### Before Starting
1. Run `AL: Download symbols` → Select Business Central 24.0
2. Check `app.json` version matches target BC instance
3. Verify `.vscode/launch.json` has server URL & auth config

### Adding a Feature
1. **Add table** if new data entity needed (mirror existing field patterns)
2. **Add page** for CRUD operations (use existing pages as templates)
3. **Add codeunit procedures** for business logic
4. **Compile**: Ctrl+Shift+B (checks all symbols resolve)
5. **Run**: F5 (deploys to BC sandbox, launches debugger)

### Testing Division Features
- Open corresponding page (e.g., ClaimsListPage for Claims division)
- Use action buttons to exercise codeunit procedures
- Check Problems panel (Ctrl+Shift+M) for compilation errors

## Common Patterns

### Creating Records with Auto-ID
```al
local procedure GetNextPolicyID(): Integer
var
    Policy: Record "PHINS Insurance Policy";
begin
    if Policy.FindLast() then
        exit(StrToInt(CopyStr(Policy."Policy ID", 4)) + 1)
    else
        exit(1);
end;
```

### Status Transition Validation
```al
if Rec.Status <> Rec.Status::Approved then begin
    Rec.Status := Rec.Status::Approved;
    Rec.Modify();
end;
```

### Related Record Lookup
```al
if Policy.Get(PolicyID) then begin
    // ... update policy fields
end;
```

## Quick Reference

| Task | Shortcut |
|------|----------|
| Build | Ctrl+Shift+B |
| Debug (F5) | F5 |
| Run test | Ctrl+F5 |
| Problems panel | Ctrl+Shift+M |
| Format | Shift+Alt+F |
| Go to definition | F12 |
| Compile & view errors | Ctrl+Shift+B |
