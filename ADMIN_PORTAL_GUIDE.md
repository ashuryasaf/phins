# PHINS Admin Portal - Complete Policy Management System

## 🚀 System Overview

The PHINS Admin Portal is now a comprehensive insurance policy management system with:

1. **Admin Authentication** - Multi-role access control
2. **Policy Creation** - Complete underwriting questionnaire workflow
3. **Underwriting Management** - Approve/reject applications with risk assessment
4. **Claims Management** - File, approve, and pay claims
5. **Payment Processing** - Full claim payment mechanism
6. **Business Intelligence Dashboards** - Three levels of analytics

## 📍 Access URLs

- **Main Portal**: http://localhost:8000/admin-portal.html
- **Alternative Admin Page**: http://localhost:8000/admin.html
- **Customer Portal**: http://localhost:8000/

## 🔐 Login Credentials

| Username | Password | Role | Access |
|----------|----------|------|--------|
| admin | admin123 | Administrator | Full access to all features |
| underwriter | under123 | Underwriter | Policy review and approval |
| claims_adjuster | claims123 | Claims Adjuster | Claims management |
| accountant | acct123 | Accountant | Financial reporting |

## 🎯 Features Implemented

### 1. Policy Creation Process

**Flow**: Admin → Create Policy → Underwriting Questionnaire → Risk Assessment → Submit

**Questionnaire includes:**
- Tobacco/smoking status
- Pre-existing medical conditions
- Surgery history
- Hazardous activities
- Family medical history
- Current medications
- Height and weight (BMI calculation)
- Risk score assessment
- Medical examination requirement flag

**Premium Calculation:**
- Base premium by policy type (Life, Health, Auto, Property, Business)
- Age factor adjustment
- Coverage amount scaling
- Risk score multiplier

### 2. Underwriting Management

**Workflow:**
1. Application submitted with questionnaire
2. Underwriter reviews risk assessment
3. Decision options:
   - **Approve**: Activates policy, calculates final premium
   - **Reject**: Provides rejection reason
   - **Refer**: Request additional information/medical exam

**Features:**
- Filter by status (Pending, Approved, Rejected)
- View complete questionnaire responses
- Risk assessment visualization
- Medical exam requirements tracking

### 3. Claims Management

**Complete Claims Lifecycle:**

```
File Claim → Under Review → Approve/Reject → Payment → Closed
```

**Claim Types:**
- Medical claims
- Accident claims
- Death benefit
- Disability claims
- Property damage
- Liability claims

**Claims Processing:**
1. **File Claim**: Customer or adjuster files claim with policy ID
2. **Review**: Claims adjuster reviews claim details
3. **Approve**: Set approved amount (can differ from claimed amount)
4. **Pay**: Process payment with method selection
5. **Track**: Payment reference and completion date

**Payment Methods:**
- Bank transfer
- Check
- Direct deposit

### 4. Business Intelligence Dashboards

#### A. Actuary Level BI

**Metrics:**
- Total exposure across all policies
- Average premium per policy
- Claims ratio (claims per policy)
- Loss ratio (claims paid vs premiums collected)
- Risk distribution visualization
- Policy type breakdown

**Use Cases:**
- Risk portfolio analysis
- Pricing strategy evaluation
- Reinsurance needs assessment

#### B. Underwriting Level BI

**Metrics:**
- Pending applications count
- Approved applications this month
- Rejection rate percentage
- Average processing time
- Risk assessment distribution
- Medical exams required count

**Use Cases:**
- Underwriting efficiency tracking
- Risk acceptance patterns
- Processing bottleneck identification

#### C. Accounting Level BI

**Metrics:**
- Total revenue (premiums collected)
- Total claims paid
- Net income calculation
- Profit margin percentage
- Outstanding premiums
- Pending claims liability

**Visualizations:**
- 12-month revenue vs claims trend
- Cash flow analysis
- Financial health indicators

**Use Cases:**
- Financial performance monitoring
- Cash flow forecasting
- Profitability analysis

## 🔌 API Endpoints

### Authentication
- `POST /api/login` - User authentication

### Policy Management
- `GET /api/policies` - List all policies
- `GET /api/policies?id={policy_id}` - Get specific policy
- `POST /api/policies/create` - Create new policy with underwriting

### Underwriting
- `GET /api/underwriting` - List all applications
- `GET /api/underwriting?id={app_id}` - Get specific application
- `POST /api/underwriting/approve` - Approve application
- `POST /api/underwriting/reject` - Reject application

### Claims
- `GET /api/claims` - List all claims
- `GET /api/claims?status={status}` - Filter claims by status
- `POST /api/claims/create` - File new claim
- `POST /api/claims/approve` - Approve claim with amount
- `POST /api/claims/reject` - Reject claim
- `POST /api/claims/pay` - Process claim payment

### Business Intelligence
- `GET /api/bi/actuary` - Actuary level metrics
- `GET /api/bi/underwriting` - Underwriting level metrics
- `GET /api/bi/accounting` - Accounting level metrics

### Customers
- `GET /api/customers` - List all customers
- `GET /api/customers?id={customer_id}` - Get specific customer

## 📊 Data Model

### Policy Object
```json
{
  "id": "POL-20251211-1234",
  "customer_id": "CUST-12345",
  "type": "life",
  "coverage_amount": 100000,
  "annual_premium": 1200,
  "monthly_premium": 100,
  "status": "active",
  "underwriting_id": "UW-20251211-5678",
  "risk_score": "medium",
  "start_date": "2025-12-11T...",
  "end_date": "2026-12-11T...",
  "created_date": "2025-12-11T..."
}
```

### Underwriting Application
```json
{
  "id": "UW-20251211-5678",
  "policy_id": "POL-20251211-1234",
  "customer_id": "CUST-12345",
  "status": "approved",
  "questionnaire_responses": {...},
  "risk_assessment": "medium",
  "medical_exam_required": false,
  "submitted_date": "2025-12-11T...",
  "decision_date": "2025-12-12T...",
  "approved_by": "John Underwriter"
}
```

### Claim Object
```json
{
  "id": "CLM-20251211-9012",
  "policy_id": "POL-20251211-1234",
  "customer_id": "CUST-12345",
  "type": "medical",
  "description": "Hospital stay for surgery",
  "claimed_amount": 5000,
  "approved_amount": 4500,
  "status": "paid",
  "filed_date": "2025-12-11T...",
  "approval_date": "2025-12-12T...",
  "payment_date": "2025-12-13T...",
  "payment_method": "bank_transfer",
  "payment_reference": "PAY-20251213-3456"
}
```

## 🎨 User Interface Features

### Dashboard
- Real-time statistics cards
- Policy count
- Pending applications
- Active claims
- Total revenue

### Navigation
- Sidebar menu with icons
- Role-based access indicators
- Active page highlighting

### Forms
- Multi-section layout
- Inline validation
- Dynamic risk calculation
- Radio button groups for questionnaires
- Success/error messaging

### Tables
- Sortable columns
- Status badges with color coding
- Action buttons per row
- Filtering capabilities

### Charts
- Bar charts for distributions
- Time series for trends
- Visual comparisons
- Interactive tooltips

## 🔄 Workflow Examples

### Example 1: Creating a New Life Insurance Policy

1. Login as `admin` / `admin123`
2. Navigate to "➕ Create Policy"
3. Fill customer information:
   - Name: John Doe
   - Email: john@example.com
   - DOB: 1980-05-15
4. Select policy type: Life Insurance
5. Set coverage: $250,000
6. Complete underwriting questionnaire
7. Set risk score based on responses
8. Submit → Policy created with ID and sent to underwriting

### Example 2: Underwriting Review

1. Login as `underwriter` / `under123`
2. Navigate to "✍️ Underwriting"
3. View pending applications
4. Review questionnaire responses
5. Click "Approve" button
6. Policy automatically activates
7. Customer can now pay premiums

### Example 3: Claims Processing

1. Login as `claims_adjuster` / `claims123`
2. Navigate to "💰 Claims"
3. Click "+ File New Claim"
4. Enter policy ID and claim details
5. Submit claim
6. Review claim in list
7. Click "Approve" and set approved amount
8. Click "Pay" and select payment method
9. Payment reference generated

### Example 4: Financial Analysis

1. Login as `accountant` / acct123`
2. Navigate to "💹 BI - Accounting"
3. View key metrics:
   - Revenue, Claims Paid, Net Income, Profit Margin
4. Analyze 12-month trend chart
5. Review outstanding premiums and liabilities
6. Export data for reporting

## 🛠️ Technical Stack

**Backend:**
- Python 3 with http.server
- In-memory data storage (demo mode)
- REST API endpoints
- Session-based authentication

**Frontend:**
- Pure HTML5/CSS3/JavaScript
- Responsive design (mobile-friendly)
- No external dependencies
- Modern browser features

## 🔒 Security Features

- Token-based authentication
- Session management with localStorage
- Protected API endpoints (Authorization header)
- Role-based access control ready
- Input validation on forms

## 📈 Next Steps / Enhancements

Potential production improvements:

1. **Database Integration**: Replace in-memory storage with PostgreSQL/MongoDB
2. **Real Authentication**: Implement JWT with proper password hashing
3. **File Upload**: Support document attachments for claims
4. **Email Notifications**: Send updates on policy/claim status changes
5. **Advanced BI**: Add more complex analytics and data visualization
6. **Integration**: Connect to existing underwriting_assistant.py and accounting_engine.py
7. **Audit Trail**: Log all user actions for compliance
8. **Export Features**: PDF generation for policies and claims
9. **Payment Gateway**: Real payment processing integration
10. **Mobile App**: Native mobile app for field agents

## 🎯 Quick Start

```bash
# Server is already running!
# Access the admin portal:
open http://localhost:8000/admin-portal.html

# Or from command line:
curl http://localhost:8000/api/policies
```

## 📞 Support

For issues or questions about the system:
- Check browser console for JavaScript errors
- Verify server is running on port 8000
- Review API endpoint responses
- Check authentication token in localStorage

---

**System Status**: ✅ Online and Ready
**Server URL**: http://localhost:8000
**Admin Portal**: http://localhost:8000/admin-portal.html
