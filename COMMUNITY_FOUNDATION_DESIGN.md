# Community Foundation System - Architecture Design

## Executive Summary

The **Community Foundation** feature enables customers and suppliers to create and manage mutual aid groups with shared insurance coverage, collective savings, and configurable governance rules. This document provides a comprehensive analysis, UML models, and implementation plan for review.

---

## 1. Requirements Analysis

### 1.1 Foundation Types (User-Selectable Categories)
| Type | Description | Typical Size | Example Use Cases |
|------|-------------|--------------|-------------------|
| `family` | Family-based mutual support | 2-15 | Shared health coverage, emergency fund |
| `work` | Workplace/company groups | 10-100 | Employee benefits, workplace injury coverage |
| `neighborhood` | Location-based communities | 20-50 | Local emergency mutual aid |
| `friends` | Social circle groups | 5-35 | Peer support network, shared risk |
| `entrepreneurs` | Business founders network | 10-50 | Startup risk hedging, health pool |
| `business_venture` | Joint business partnerships | 2-20 | Partnership liability, key-person coverage |
| `professional` | Industry/profession groups | 50-unlimited | Professional liability pool |
| `customer_club` | Open membership clubs | Unlimited | Loyalty programs, discount pools |
| `custom` | User-defined category | Configurable | Any custom use case |

### 1.2 Core Features

#### A. Foundation Creation
- **Who can create**: Customers OR Suppliers
- **Creator becomes**: Founder with administrative rights
- **Initial setup**: Name, type, description, member limits, rules

#### B. Membership Model
| Role | Rights | Duties |
|------|--------|--------|
| `founder` | Full admin rights, rule creation, dissolution | Oversight, dispute resolution |
| `admin` | Member management, fund management | Support founder |
| `member` | Voting rights, fund access, claims | Contributions, rule compliance |
| `observer` | View-only access | None (invited guests) |

#### C. Mutual Rights (Shared Benefits)
1. **Collective Insurance Pool**
   - Group policy discounts (10-30% reduction)
   - Shared deductible funds
   - Cross-coverage for life events

2. **Mutual Savings Account**
   - Pooled emergency fund
   - Investment returns distributed proportionally
   - Withdrawal rules (voting/approval required)

3. **Risk Sharing**
   - Life and disability coverage
   - Medical expense sharing
   - Business interruption funds

#### D. Mutual Duties (Responsibilities)
1. **Contribution Requirements**
   - Monthly/quarterly dues
   - Percentage-based or fixed amounts
   - Grace periods and penalties

2. **Fund Risk Limits**
   - Maximum claim as % of total fund
   - Per-member withdrawal caps
   - Reserve requirements (min 20%)

3. **Decision Making**
   - Majority vote (>50%)
   - Supermajority (>66%) for rule changes
   - Founder veto (optional, configurable)

### 1.3 Governance Rules (Configurable)

```
BASE RULES (immutable after creation):
├── Foundation Type
├── Maximum Members
├── Founder Veto Rights (yes/no)
└── Dissolution Requirements

ADJUSTABLE RULES (modifiable by vote):
├── Contribution Amount
├── Contribution Frequency
├── Claim Approval Threshold
├── Fund Risk Percentage (max claim %)
├── Voting Threshold (majority %)
├── New Member Approval Process
├── Waiting Period for Claims
└── Dispute Resolution Method
```

### 1.4 Privacy & Security Requirements

| Requirement | Implementation |
|-------------|----------------|
| Invitation-only joining | Private invitation codes with expiry |
| No sensitive data exposure | Masked member details, aggregate-only displays |
| Audit trail | All actions logged with timestamps |
| Data isolation | Foundation data separate from individual profiles |
| Consent management | Explicit opt-in for shared data visibility |

---

## 2. UML Class Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         COMMUNITY FOUNDATION DATA MODEL                         │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐       ┌──────────────────────────┐
│     Foundation           │       │    FoundationMember      │
├──────────────────────────┤       ├──────────────────────────┤
│ + id: String (PK)        │1    * │ + id: String (PK)        │
│ + name: String           │───────│ + foundation_id: String  │
│ + type: FoundationType   │       │ + member_id: String      │
│ + description: Text      │       │ + member_type: Enum      │
│ + founder_id: String     │       │   (customer|supplier)    │
│ + founder_type: Enum     │       │ + role: MemberRole       │
│   (customer|supplier)    │       │ + status: MemberStatus   │
│ + status: FoundationStat │       │ + contribution_amount:Fl │
│ + created_at: DateTime   │       │ + total_contributed: Fl  │
│ + max_members: Integer   │       │ + joined_at: DateTime    │
│ + is_unlimited: Boolean  │       │ + last_contribution: DT  │
│ + current_members: Int   │       │ + voting_weight: Float   │
│ + total_fund_balance: Fl │       │ + display_name: String   │
│ + reserve_percentage: Fl │       │ + is_visible: Boolean    │
│ + settings: JSON         │       └──────────────────────────┘
└──────────────────────────┘                   │
         │                                     │ member_id
         │                                     ▼
         │                     ┌───────────────────────────────┐
         │                     │  Customer / Supplier Tables   │
         │                     │  (existing - no modification) │
         │                     └───────────────────────────────┘
         │
         │1
         │
         │*
┌──────────────────────────┐       ┌──────────────────────────┐
│   FoundationRule         │       │  FoundationInvitation    │
├──────────────────────────┤       ├──────────────────────────┤
│ + id: String (PK)        │       │ + id: String (PK)        │
│ + foundation_id: String  │       │ + foundation_id: String  │
│ + rule_type: RuleType    │       │ + code: String (unique)  │
│ + rule_key: String       │       │ + invited_email: String  │
│ + rule_value: JSON       │       │ + invited_by: String     │
│ + is_base_rule: Boolean  │       │ + status: InviteStatus   │
│ + requires_vote: Boolean │       │ + created_at: DateTime   │
│ + vote_threshold: Float  │       │ + expires_at: DateTime   │
│ + created_at: DateTime   │       │ + used_at: DateTime      │
│ + last_modified: DateTime│       │ + max_uses: Integer      │
│ + modified_by: String    │       │ + used_count: Integer    │
│ + version: Integer       │       │ + notes: Text            │
└──────────────────────────┘       └──────────────────────────┘

┌──────────────────────────┐       ┌──────────────────────────┐
│   FoundationFund         │       │  FoundationContribution  │
├──────────────────────────┤       ├──────────────────────────┤
│ + id: String (PK)        │1    * │ + id: String (PK)        │
│ + foundation_id: String  │───────│ + fund_id: String        │
│ + fund_type: FundType    │       │ + member_id: String      │
│   (insurance|savings|    │       │ + amount: Float          │
│    emergency|custom)     │       │ + contribution_type:Enum │
│ + name: String           │       │   (monthly|quarterly|    │
│ + balance: Float         │       │    annual|one_time)      │
│ + currency: String       │       │ + status: ContribStatus  │
│ + min_reserve: Float     │       │ + due_date: DateTime     │
│ + max_claim_pct: Float   │       │ + paid_date: DateTime    │
│ + status: FundStatus     │       │ + transaction_ref: Str   │
│ + created_at: DateTime   │       │ + notes: Text            │
│ + last_activity: DateTime│       └──────────────────────────┘
└──────────────────────────┘
         │
         │1
         │
         │*
┌──────────────────────────┐       ┌──────────────────────────┐
│   FoundationClaim        │       │    FoundationVote        │
├──────────────────────────┤       ├──────────────────────────┤
│ + id: String (PK)        │       │ + id: String (PK)        │
│ + foundation_id: String  │       │ + foundation_id: String  │
│ + fund_id: String        │       │ + proposal_id: String    │
│ + claimant_id: String    │       │ + proposal_type: Enum    │
│ + claim_type: ClaimType  │       │   (rule_change|claim|    │
│   (medical|disability|   │       │    membership|withdrawal)│
│    emergency|business)   │       │ + title: String          │
│ + amount_requested: Fl   │       │ + description: Text      │
│ + amount_approved: Float │       │ + status: VoteStatus     │
│ + status: FClaimStatus   │       │ + threshold: Float       │
│ + description: Text      │       │ + votes_for: Integer     │
│ + supporting_docs: JSON  │       │ + votes_against: Integer │
│ + submitted_at: DateTime │       │ + votes_abstain: Integer │
│ + reviewed_at: DateTime  │       │ + created_at: DateTime   │
│ + reviewed_by: String    │       │ + closes_at: DateTime    │
│ + vote_id: String (FK)   │       │ + result: String         │
│ + payout_date: DateTime  │       │ + created_by: String     │
│ + payout_method: String  │       └──────────────────────────┘
└──────────────────────────┘
                                   ┌──────────────────────────┐
                                   │   FoundationVoteCast     │
                                   ├──────────────────────────┤
                                   │ + id: String (PK)        │
                                   │ + vote_id: String (FK)   │
                                   │ + member_id: String      │
                                   │ + vote_choice: Enum      │
                                   │   (for|against|abstain)  │
                                   │ + weight: Float          │
                                   │ + cast_at: DateTime      │
                                   │ + reason: Text (optional)│
                                   └──────────────────────────┘

┌──────────────────────────┐
│   FoundationActivity     │
├──────────────────────────┤
│ + id: String (PK)        │
│ + foundation_id: String  │
│ + activity_type: Enum    │
│ + actor_id: String       │
│ + details: JSON          │
│ + timestamp: DateTime    │
│ + ip_address: String     │
└──────────────────────────┘
```

---

## 3. State Machine Diagrams

### 3.1 Foundation Lifecycle

```
                    ┌─────────┐
                    │ DRAFT   │ (initial creation)
                    └────┬────┘
                         │ activate()
                         ▼
                    ┌─────────┐
          ┌─────────│ ACTIVE  │─────────┐
          │         └────┬────┘         │
    suspend()            │         dissolve()
          │         no members          │
          ▼              │              ▼
    ┌───────────┐        │       ┌───────────┐
    │ SUSPENDED │        │       │ DISSOLVED │
    └─────┬─────┘        │       └───────────┘
          │              │
    reactivate()         │
          │              ▼
          └────────►┌─────────┐
                    │ INACTIVE│ (auto after 1 year)
                    └─────────┘
```

### 3.2 Membership Lifecycle

```
    ┌──────────┐    accept()     ┌─────────┐
    │ INVITED  │────────────────►│ PENDING │ (awaiting approval)
    └──────────┘                 └────┬────┘
         │                            │
    decline()                   approve() │ reject()
         │                            │        │
         ▼                            ▼        ▼
    ┌──────────┐                ┌────────┐  ┌──────────┐
    │ DECLINED │                │ ACTIVE │  │ REJECTED │
    └──────────┘                └────┬───┘  └──────────┘
                                     │
                           leave() / remove()
                                     │
                                     ▼
                               ┌───────────┐
                               │  REMOVED  │
                               └───────────┘
```

### 3.3 Foundation Claim Process

```
    ┌───────────┐
    │ SUBMITTED │
    └─────┬─────┘
          │
    ┌─────▼─────┐     requires_vote = true
    │ REVIEWING │─────────────────────────┐
    └─────┬─────┘                         │
          │                               ▼
          │ auto_approve          ┌─────────────┐
          │ (small claims)        │ VOTE_OPEN   │
          │                       └──────┬──────┘
          ▼                              │
    ┌───────────┐                  vote_passed │ vote_failed
    │ APPROVED  │◄─────────────────────────────┤
    └─────┬─────┘                              │
          │                                    ▼
          │                            ┌───────────┐
    process_payout()                   │ REJECTED  │
          │                            └───────────┘
          ▼
    ┌──────────┐
    │  PAID    │
    └──────────┘
```

---

## 4. Sequence Diagrams

### 4.1 Foundation Creation Flow

```
┌────────┐     ┌─────────┐     ┌───────────────┐     ┌──────────┐
│Customer│     │Dashboard│     │FoundationSvc  │     │ Database │
└───┬────┘     └────┬────┘     └───────┬───────┘     └────┬─────┘
    │               │                  │                   │
    │ Click "Create │                  │                   │
    │ Foundation"   │                  │                   │
    │──────────────►│                  │                   │
    │               │                  │                   │
    │               │ POST /api/       │                   │
    │               │ foundations      │                   │
    │               │─────────────────►│                   │
    │               │                  │                   │
    │               │                  │ Validate input    │
    │               │                  │──────────────────►│
    │               │                  │                   │
    │               │                  │ Create foundation │
    │               │                  │──────────────────►│
    │               │                  │                   │
    │               │                  │ Create default    │
    │               │                  │ rules             │
    │               │                  │──────────────────►│
    │               │                  │                   │
    │               │                  │ Add founder as    │
    │               │                  │ member            │
    │               │                  │──────────────────►│
    │               │                  │                   │
    │               │                  │ Create initial    │
    │               │                  │ fund accounts     │
    │               │                  │──────────────────►│
    │               │                  │                   │
    │               │ Return           │                   │
    │               │ foundation_id    │                   │
    │               │◄─────────────────│                   │
    │               │                  │                   │
    │ Show success  │                  │                   │
    │ + dashboard   │                  │                   │
    │◄──────────────│                  │                   │
    │               │                  │                   │
```

### 4.2 Invitation & Join Flow

```
┌────────┐    ┌────────┐    ┌─────────┐    ┌───────────────┐    ┌──────────┐
│Founder │    │Invitee │    │Dashboard│    │FoundationSvc  │    │ Database │
└───┬────┘    └───┬────┘    └────┬────┘    └───────┬───────┘    └────┬─────┘
    │             │              │                  │                  │
    │ Send invite │              │                  │                  │
    │────────────────────────────►                  │                  │
    │             │              │ POST /api/       │                  │
    │             │              │ invitations      │                  │
    │             │              │─────────────────►│                  │
    │             │              │                  │ Generate code    │
    │             │              │                  │─────────────────►│
    │             │              │                  │                  │
    │             │ Email/Link   │                  │                  │
    │             │◄─────────────────────────────────                  │
    │             │              │                  │                  │
    │             │ Click link   │                  │                  │
    │             │──────────────►                  │                  │
    │             │              │                  │                  │
    │             │              │ Validate code    │                  │
    │             │              │─────────────────►│                  │
    │             │              │                  │ Verify code      │
    │             │              │                  │─────────────────►│
    │             │              │                  │                  │
    │             │              │ Show foundation  │                  │
    │             │◄─────────────│ info + join form │                  │
    │             │              │                  │                  │
    │             │ Accept &     │                  │                  │
    │             │ submit       │                  │                  │
    │             │──────────────►                  │                  │
    │             │              │ POST /api/       │                  │
    │             │              │ foundations/join │                  │
    │             │              │─────────────────►│                  │
    │             │              │                  │                  │
    │             │              │                  │ If auto_approve: │
    │             │              │                  │ add as member    │
    │             │              │                  │─────────────────►│
    │             │              │                  │                  │
    │             │              │                  │ Else: create     │
    │             │              │                  │ pending member   │
    │             │              │                  │─────────────────►│
    │             │              │                  │                  │
    │             │ Confirmation │                  │                  │
    │             │◄─────────────────────────────────                  │
    │             │              │                  │                  │
```

### 4.3 Claim Submission & Voting Flow

```
┌────────┐    ┌─────────┐    ┌───────────────┐    ┌──────────┐
│Member  │    │Dashboard│    │FoundationSvc  │    │ Database │
└───┬────┘    └────┬────┘    └───────┬───────┘    └────┬─────┘
    │              │                 │                  │
    │ Submit claim │                 │                  │
    │─────────────►│                 │                  │
    │              │ POST /api/      │                  │
    │              │ foundation-     │                  │
    │              │ claims          │                  │
    │              │────────────────►│                  │
    │              │                 │ Validate amount  │
    │              │                 │ vs fund balance  │
    │              │                 │─────────────────►│
    │              │                 │                  │
    │              │                 │ Check if vote    │
    │              │                 │ required         │
    │              │                 │                  │
    │              │                 │ [if amount >     │
    │              │                 │  auto_threshold] │
    │              │                 │                  │
    │              │                 │ Create vote      │
    │              │                 │ proposal         │
    │              │                 │─────────────────►│
    │              │                 │                  │
    │              │                 │ Notify all       │
    │              │                 │ members          │
    │              │                 │                  │
    │              │ Claim pending   │                  │
    │              │ vote            │                  │
    │◄─────────────│                 │                  │
    │              │                 │                  │
```

---

## 5. API Endpoints Design

### 5.1 Foundation Management

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/foundations` | Create new foundation | Customer/Supplier |
| `GET` | `/api/foundations` | List user's foundations | Customer/Supplier |
| `GET` | `/api/foundations/{id}` | Get foundation details | Member |
| `PUT` | `/api/foundations/{id}` | Update foundation | Founder/Admin |
| `DELETE` | `/api/foundations/{id}` | Dissolve foundation | Founder |
| `POST` | `/api/foundations/{id}/activate` | Activate draft foundation | Founder |

### 5.2 Membership

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/foundations/{id}/invite` | Send invitation | Founder/Admin |
| `POST` | `/api/foundations/join` | Join via invitation code | Customer/Supplier |
| `GET` | `/api/foundations/{id}/members` | List members | Member |
| `PUT` | `/api/foundations/{id}/members/{mid}` | Update member role | Founder/Admin |
| `DELETE` | `/api/foundations/{id}/members/{mid}` | Remove member | Founder/Admin |
| `POST` | `/api/foundations/{id}/leave` | Leave foundation | Member |

### 5.3 Funds & Contributions

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/foundations/{id}/funds` | List funds | Member |
| `POST` | `/api/foundations/{id}/funds` | Create new fund | Founder/Admin |
| `POST` | `/api/foundations/{id}/contribute` | Make contribution | Member |
| `GET` | `/api/foundations/{id}/contributions` | View contribution history | Member |

### 5.4 Claims

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/foundation-claims` | Submit claim | Member |
| `GET` | `/api/foundation-claims` | List claims | Member |
| `GET` | `/api/foundation-claims/{id}` | Get claim details | Member |
| `PUT` | `/api/foundation-claims/{id}/review` | Review claim | Founder/Admin |

### 5.5 Voting

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/foundations/{id}/votes` | List active votes | Member |
| `POST` | `/api/foundations/{id}/votes` | Create vote proposal | Founder/Admin |
| `POST` | `/api/foundations/{id}/votes/{vid}/cast` | Cast vote | Member |
| `GET` | `/api/foundations/{id}/votes/{vid}/results` | View results | Member |

### 5.6 Invitations

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/foundation-invitations` | List pending invitations | User |
| `GET` | `/api/foundation-invitations/validate/{code}` | Validate code | Public |
| `POST` | `/api/foundation-invitations/{code}/accept` | Accept invitation | User |
| `POST` | `/api/foundation-invitations/{code}/decline` | Decline invitation | User |

---

## 6. Dashboard Features

### 6.1 Customer Dashboard - Foundation Section

```
┌─────────────────────────────────────────────────────────────────┐
│  PHINS Dashboard                                    [John Doe ▼]│
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─── My Foundations ──────────────────────────────────────┐   │
│  │                                                          │   │
│  │  ┌──────────────────┐  ┌──────────────────┐             │   │
│  │  │ 👨‍👩‍👧‍👦 Family Fund    │  │ 💼 Startup Group  │  [+Create] │   │
│  │  │ ──────────────── │  │ ──────────────── │             │   │
│  │  │ Members: 4/10    │  │ Members: 8/35    │             │   │
│  │  │ Balance: $12,500 │  │ Balance: $45,200 │             │   │
│  │  │ Your role: Founder│ │ Your role: Member│             │   │
│  │  │                  │  │                  │             │   │
│  │  │ [View] [Manage]  │  │ [View] [Leave]   │             │   │
│  │  └──────────────────┘  └──────────────────┘             │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── Pending Invitations ──────────────────────────────────┐   │
│  │                                                          │   │
│  │  🔔 Neighborhood Watch Fund - invited by Sarah M.        │   │
│  │     Type: neighborhood | Members: 23 | Min contrib: $50  │   │
│  │     [Accept] [Decline] [View Details]                    │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Foundation Detail View

```
┌─────────────────────────────────────────────────────────────────┐
│  ◄ Back to Dashboard                    Family Emergency Fund   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─── Fund Overview ────────────────────────────────────────┐   │
│  │  Total Balance: $12,500.00          Reserve: $2,500 (20%)│   │
│  │  Available:     $10,000.00          Members: 4/10        │   │
│  │                                                          │   │
│  │  [Contribute] [Request Claim] [Invite Member]            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── Members ──────────────────────────────────────────────┐   │
│  │  Name          │ Role    │ Contributed │ Status          │   │
│  │  ─────────────────────────────────────────────────────── │   │
│  │  John D.       │ Founder │ $4,500      │ Active          │   │
│  │  Mary D.       │ Admin   │ $3,200      │ Active          │   │
│  │  Mike D.       │ Member  │ $2,800      │ Active          │   │
│  │  Anna D.       │ Member  │ $2,000      │ Active          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── Active Votes ─────────────────────────────────────────┐   │
│  │  📊 Increase monthly contribution to $200                │   │
│  │     Votes: 2 for / 1 against / 1 pending                 │   │
│  │     Ends: Jan 25, 2026                                   │   │
│  │     [Cast Your Vote]                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── Recent Claims ────────────────────────────────────────┐   │
│  │  #CLM-001 │ Medical │ $1,200 │ Mike D. │ ✅ Approved     │   │
│  │  #CLM-002 │ Emergency│ $500  │ Anna D. │ 🗳️ Voting      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 Foundation Creation Wizard

```
┌─────────────────────────────────────────────────────────────────┐
│  Create New Foundation                              Step 1 of 4 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Choose Your Foundation Type:                                   │
│                                                                 │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ 👨‍👩‍👧‍👦 Family      │  │ 💼 Work        │  │ 🏘️ Neighborhood │    │
│  │ Mutual support │  │ Employee group │  │ Local community│    │
│  │ for family     │  │ benefits pool  │  │ emergency fund │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
│                                                                 │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ 👥 Friends      │  │ 🚀 Entrepreneurs│ │ 🏢 Business    │    │
│  │ Peer support   │  │ Startup risk   │  │ Joint venture  │    │
│  │ network        │  │ hedging        │  │ coverage       │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
│                                                                 │
│  ┌────────────────┐  ┌────────────────┐                        │
│  │ 🎯 Customer    │  │ ⚙️ Custom       │                        │
│  │ Club (open)    │  │ Define your    │                        │
│  │ Unlimited      │  │ own type       │                        │
│  └────────────────┘  └────────────────┘                        │
│                                                                 │
│                                            [Cancel] [Next →]    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Enumerations & Constants

```python
class FoundationType(str, Enum):
    FAMILY = "family"
    WORK = "work"
    NEIGHBORHOOD = "neighborhood"
    FRIENDS = "friends"
    ENTREPRENEURS = "entrepreneurs"
    BUSINESS_VENTURE = "business_venture"
    PROFESSIONAL = "professional"
    CUSTOMER_CLUB = "customer_club"
    CUSTOM = "custom"

class FoundationStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    DISSOLVED = "dissolved"

class MemberRole(str, Enum):
    FOUNDER = "founder"
    ADMIN = "admin"
    MEMBER = "member"
    OBSERVER = "observer"

class MemberStatus(str, Enum):
    INVITED = "invited"
    PENDING = "pending"  # Awaiting approval
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"
    DECLINED = "declined"

class FundType(str, Enum):
    COLLECTIVE_INSURANCE = "insurance"
    MUTUAL_SAVINGS = "savings"
    EMERGENCY = "emergency"
    CUSTOM = "custom"

class ClaimType(str, Enum):
    MEDICAL = "medical"
    DISABILITY = "disability"
    EMERGENCY = "emergency"
    BUSINESS_INTERRUPTION = "business"
    CUSTOM = "custom"

class ClaimStatus(str, Enum):
    SUBMITTED = "submitted"
    REVIEWING = "reviewing"
    VOTE_OPEN = "vote_open"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"

class VoteStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"

class ContributionStatus(str, Enum):
    SCHEDULED = "scheduled"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"

class RuleType(str, Enum):
    CONTRIBUTION = "contribution"
    CLAIM_APPROVAL = "claim_approval"
    MEMBERSHIP = "membership"
    VOTING = "voting"
    FUND_LIMITS = "fund_limits"
    GOVERNANCE = "governance"
```

---

## 8. Default Rules Configuration

```json
{
  "base_rules": {
    "foundation_type": "family",
    "max_members": 35,
    "founder_veto": true,
    "dissolution_threshold": 0.75,
    "min_members_to_operate": 2
  },
  "contribution_rules": {
    "frequency": "monthly",
    "min_amount": 50.00,
    "max_amount": null,
    "grace_period_days": 7,
    "late_fee_percentage": 5.0
  },
  "claim_rules": {
    "waiting_period_days": 30,
    "auto_approve_threshold": 500.00,
    "max_claim_percentage": 25.0,
    "requires_documentation": true,
    "vote_threshold": 0.50
  },
  "fund_rules": {
    "min_reserve_percentage": 20.0,
    "max_single_payout_percentage": 25.0,
    "investment_allowed": false
  },
  "voting_rules": {
    "majority_threshold": 0.50,
    "supermajority_threshold": 0.66,
    "vote_duration_days": 7,
    "quorum_percentage": 0.50
  },
  "membership_rules": {
    "auto_approve_members": false,
    "require_invitation": true,
    "new_member_vote_required": false,
    "removal_vote_threshold": 0.66
  }
}
```

---

## 9. Security Considerations

### 9.1 Data Privacy

| Data Type | Visibility | Protection |
|-----------|------------|------------|
| Member real names | Founder/Admin only | Display names used publicly |
| Email addresses | Never exposed | Hash for matching only |
| Contribution amounts | Aggregate only | Individual amounts hidden |
| Claim details | Anonymized for voting | Claimant sees full details |
| Fund balance | All members | No individual breakdown |

### 9.2 Access Control Matrix

| Action | Founder | Admin | Member | Observer |
|--------|---------|-------|--------|----------|
| View foundation | ✅ | ✅ | ✅ | ✅ |
| Edit foundation | ✅ | ✅ | ❌ | ❌ |
| Invite members | ✅ | ✅ | ❌ | ❌ |
| Remove members | ✅ | ✅* | ❌ | ❌ |
| Create funds | ✅ | ✅ | ❌ | ❌ |
| Make contribution | ✅ | ✅ | ✅ | ❌ |
| Submit claim | ✅ | ✅ | ✅ | ❌ |
| Cast vote | ✅ | ✅ | ✅ | ❌ |
| Create vote | ✅ | ✅ | ❌ | ❌ |
| Dissolve foundation | ✅ | ❌ | ❌ | ❌ |
| View audit log | ✅ | ✅ | ❌ | ❌ |

*Admin cannot remove Founder or other Admins

---

## 10. Implementation Phases

### Phase 1: Core Foundation (MVP)
- [ ] Database models
- [ ] Foundation CRUD API
- [ ] Membership management
- [ ] Basic invitation system
- [ ] Dashboard UI

### Phase 2: Funds & Contributions
- [ ] Fund management
- [ ] Contribution tracking
- [ ] Wallet integration
- [ ] Payment processing

### Phase 3: Claims & Voting
- [ ] Claim submission
- [ ] Voting system
- [ ] Auto-approval logic
- [ ] Payout processing

### Phase 4: Advanced Features
- [ ] Rule customization UI
- [ ] Analytics dashboard
- [ ] Notifications
- [ ] Mobile optimization

---

## 11. Confirmation Checklist

Please confirm or modify the following features:

### Core Features
- [ ] **Foundation Types**: Family, Work, Neighborhood, Friends, Entrepreneurs, Business Venture, Professional, Customer Club, Custom
- [ ] **Creator Types**: Both Customers AND Suppliers can create foundations
- [ ] **Member Limits**: Configurable (default 35) OR unlimited for clubs
- [ ] **Founder Powers**: Admin rights + optional veto power

### Financial Features
- [ ] **Collective Insurance Pool**: Shared risk coverage with group discounts
- [ ] **Mutual Savings Account**: Pooled funds with proportional distribution
- [ ] **Fund Risk Limits**: Adjustable as % (default 25% max claim)
- [ ] **Reserve Requirement**: Minimum 20% kept in reserve

### Governance Features
- [ ] **Decision Making**: Majority vote (>50%) for standard decisions
- [ ] **Rule Changes**: Supermajority (>66%) required
- [ ] **Founder Veto**: Optional, configurable at creation
- [ ] **Claim Auto-Approval**: Small claims auto-approved below threshold

### Privacy Features
- [ ] **Invitation-Only**: Private codes required to join
- [ ] **Display Names**: Real names hidden, display names used
- [ ] **Aggregate Data**: Individual contributions not shown to other members
- [ ] **Audit Trail**: All actions logged for compliance

---

## 12. Questions for Clarification

1. **Integration with existing PHINS policies**: Should foundation insurance pools link to actual PHINS policy products, or operate as standalone funds?

2. **Supplier foundation creation**: When a supplier (e.g., business owner) creates a foundation for employees, should they have special reporting access?

3. **Cross-foundation membership**: Can a customer/supplier be a member of multiple foundations simultaneously?

4. **Currency support**: Should funds support multiple currencies, or USD only?

5. **Investment options**: Should mutual savings funds have optional investment allocation (like the existing savings portfolio)?

---

*Document Version: 1.0*
*Created: January 19, 2026*
*Status: Awaiting Confirmation*
