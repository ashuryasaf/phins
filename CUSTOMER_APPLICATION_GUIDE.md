# PHINS Customer Application System - Complete Guide

## Overview

The PHINS Customer Application System provides a business-oriented, user-friendly interface for customers to apply for insurance policies online. This mirrors the admin policy creation process but is optimized for self-service with progressive disclosure, visual design, and clear explanations.

## System Architecture

### Customer Journey Flow

```
Homepage (index.html)
    ↓ [Apply Now Button]
Customer Application (apply.html)
    ↓ [4-Step Wizard]
    1. Personal Information
    2. Coverage Selection
    3. Health Assessment
    4. Review & Submit
    ↓ [Submit Application]
Backend API (/api/policies/create)
    ↓ [Creates Policy Record]
Admin Underwriting Queue
    ↓ [Underwriter Reviews]
Customer Dashboard
    ↓ [Track Application Status]
```

### Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `apply.html` | Customer application form with 4-step wizard | 450+ |
| `apply-styles.css` | Responsive styling, policy cards, progress bar | 700+ |
| `apply.js` | Form logic, validation, premium calculation, API integration | 500+ |
| `dashboard.html` | Customer dashboard with "Apply for New Policy" action | Updated |
| `styles.css` | Added action card styling for dashboard | Updated |

## Features

### 1. Multi-Step Application Wizard

**Step 1: Personal Information**
- Full name
- Date of birth (age validation)
- Email address
- Phone number
- Full address (street, city, state, ZIP)
- Occupation

**Step 2: Coverage Selection**
- Visual policy cards:
  - **Basic Life**: $100K-$500K coverage, $50-$250/month
  - **Standard Life**: $250K-$1M coverage, $150-$600/month
  - **Premium Life**: $500K-$5M coverage, $300-$2,500/month
- Interactive coverage slider
- Real-time premium estimation

**Step 3: Health Assessment**
- Tobacco use (yes/no)
- Medical conditions (checkboxes for 8 common conditions)
- Recent surgeries (yes/no with details)
- Hazardous activities (checkboxes for 5 activities)
- Family medical history (yes/no with details)
- BMI Calculator:
  - Height input (feet + inches)
  - Weight input (pounds)
  - Auto-calculation with color-coded categories
  - Categories: Underweight, Normal, Overweight, Obese

**Step 4: Review & Submit**
- Comprehensive summary of all entered data
- Edit buttons for each section
- Terms & conditions checkboxes:
  - Accuracy acknowledgment
  - Terms of service agreement
- Submit button with loading state

### 2. Real-Time Premium Calculation

The premium calculation matches the admin backend formula exactly:

```javascript
// Base rates per policy type
const baseRates = {
    'basic_life': 50,
    'standard_life': 150,
    'premium_life': 300
};

// Coverage-based multiplier
const coverageMultiplier = selectedCoverage / 100000;

// Age-based factor (2% per year over 25)
const ageFactor = age > 25 ? 1 + ((age - 25) * 0.02) : 1;

// Risk score multiplier
const riskMultipliers = {
    low: 0.8,
    medium: 1.0,
    high: 1.3,
    very_high: 1.6
};

// Final calculation
annualPremium = baseRate * coverageMultiplier * ageFactor * riskMultiplier;
monthlyPremium = annualPremium / 12;
```

### 3. Risk Assessment Algorithm

**Risk Points Calculation:**
- Tobacco use: +2 points
- Medical conditions: +1 point per condition
- Recent surgeries: +2 points
- Hazardous activities: +1 point per activity
- Family medical history: +1 point
- BMI categories:
  - Underweight: +1 point
  - Normal: 0 points
  - Overweight: +1 point
  - Obese: +2 points

**Risk Level Classification:**
- 0-2 points: Low Risk
- 3-5 points: Medium Risk
- 6-8 points: High Risk
- 9+ points: Very High Risk

### 4. BMI Calculator

**Formula:**
```
BMI = (weight in pounds × 703) / (height in inches)²
```

**Categories:**
- < 18.5: Underweight
- 18.5 - 24.9: Normal
- 25.0 - 29.9: Overweight
- ≥ 30.0: Obese

### 5. Form Validation

**Step-by-Step Validation:**
- Step 1: All personal info fields required
- Step 2: Policy type and coverage amount required
- Step 3: All health questions required
- Step 4: Both checkboxes must be checked

**Real-Time Validation:**
- Email format checking
- Phone number format
- Date of birth (must be 18-85 years old)
- Coverage limits per policy type

## API Integration

### Endpoint: POST /api/policies/create

**Request Payload:**
```json
{
    "customer_name": "John Doe",
    "email": "john@example.com",
    "phone": "555-1234",
    "date_of_birth": "1985-03-15",
    "address": "123 Main St",
    "city": "Springfield",
    "state": "IL",
    "zip": "62701",
    "occupation": "Software Engineer",
    "policy_type": "standard_life",
    "coverage_amount": 500000,
    "annual_premium": 2400.00,
    "payment_frequency": "monthly",
    "monthly_premium": 200.00,
    "health_questions": {
        "tobacco_use": false,
        "medical_conditions": ["diabetes"],
        "surgeries": "Appendectomy in 2020",
        "hazardous_activities": [],
        "family_history": "Father had heart disease",
        "height_feet": 5,
        "height_inches": 10,
        "weight": 180,
        "bmi": 25.8,
        "bmi_category": "Overweight"
    },
    "risk_score": 3,
    "risk_level": "medium",
    "underwriting_status": "pending"
}
```

**Response:**
```json
{
    "success": true,
    "policy_id": "POL-000456",
    "message": "Application submitted successfully",
    "next_steps": "An underwriter will review your application within 2-3 business days"
}
```

## User Interface Design

### Design Principles
1. **Progressive Disclosure**: Show only relevant information at each step
2. **Visual Hierarchy**: Use cards, icons, and colors to guide attention
3. **Immediate Feedback**: Real-time validation and premium updates
4. **Mobile-First**: Responsive design works on all devices
5. **Accessibility**: Clear labels, proper contrast, keyboard navigation

### Color Scheme
- Primary Brand: `#005b96` (PHINS Blue)
- Success: `#28a745` (Green)
- Warning: `#ffc107` (Amber)
- Error: `#dc3545` (Red)
- Neutral: `#6c757d` (Gray)

### Typography
- Headings: System UI font, bold weight
- Body: System UI font, regular weight
- Emphasis: 600 weight for important text

## Customer Experience Flow

### From Homepage
1. Customer lands on homepage
2. Sees hero section with "Apply Now" button
3. Clicks "Apply Now"
4. Redirected to application form

### From Dashboard
1. Customer logs into dashboard
2. Sees "Apply for New Policy" action card
3. Clicks action card
4. Redirected to application form

### Application Process
1. **Step 1 (30-60 seconds)**: Enter personal details
2. **Step 2 (15-30 seconds)**: Select policy and coverage
3. **Step 3 (60-90 seconds)**: Complete health assessment with BMI
4. **Step 4 (15-30 seconds)**: Review and submit
5. **Total Time**: 2-4 minutes for complete application

### Post-Submission
1. Success modal appears with application ID
2. Customer can view status in dashboard
3. Email confirmation sent (future feature)
4. Underwriter reviews in admin portal
5. Customer notified of decision (future feature)

## Admin Integration

### How Applications Enter Admin System

When a customer submits an application via `apply.html`:

1. **API Call**: POST to `/api/policies/create`
2. **Backend Processing**:
   ```python
   # Generate policy ID
   policy_id = generate_policy_id()
   
   # Calculate risk score from health questions
   risk_score = calculate_risk_score(health_data)
   
   # Set initial status
   status = "Active"
   underwriting_status = "Pending"
   
   # Store in POLICIES dictionary
   POLICIES[policy_id] = policy_data
   
   # Also create underwriting record
   UNDERWRITING_APPLICATIONS[policy_id] = {
       "policy_id": policy_id,
       "risk_assessment": risk_level,
       "health_questions": health_questions,
       "status": "Pending"
   }
   ```

3. **Admin Portal Access**:
   - Underwriter logs into admin portal
   - Navigates to "Underwriting" section
   - Sees new application in pending queue
   - Reviews health questionnaire data
   - Approves/Rejects/Refers application

### Data Consistency

**Customer Application → Admin System:**
- Same field names and data types
- Same premium calculation formula
- Same risk assessment algorithm
- Same validation rules

**Benefits:**
- No data transformation needed
- Seamless workflow
- Consistent business rules
- Real-time updates

## Technical Implementation Details

### JavaScript Architecture

**Main Functions in apply.js:**

```javascript
// Navigation
nextStep()       // Advance to next step with validation
previousStep()   // Go back to previous step
goToStep(n)     // Jump to specific step

// Policy Selection
selectPolicy(type, minCoverage, maxCoverage, basePrice)

// Calculations
calculatePremium()     // Real-time premium based on inputs
calculateBMI()         // BMI from height/weight
calculateRiskScore()   // Risk points from health data

// Submission
handleSubmit()         // Validate and send to API
```

### CSS Architecture

**Key Classes in apply-styles.css:**

```css
.application-container  // Main wrapper
.progress-bar          // Step indicator
.step-content          // Individual step container
.policy-card           // Visual policy selection cards
.form-group            // Form field wrapper
.summary-section       // Review page sections
.modal                 // Success modal overlay
```

### Form State Management

**Global State Object:**
```javascript
const formData = {
    // Step 1
    full_name: '',
    date_of_birth: '',
    email: '',
    phone: '',
    address: '',
    city: '',
    state: '',
    zip: '',
    occupation: '',
    
    // Step 2
    policy_type: '',
    coverage_amount: 0,
    annual_premium: 0,
    monthly_premium: 0,
    
    // Step 3
    tobacco_use: false,
    medical_conditions: [],
    surgeries: '',
    hazardous_activities: [],
    family_history: '',
    height_feet: 0,
    height_inches: 0,
    weight: 0,
    bmi: 0,
    bmi_category: '',
    
    // Calculated
    risk_score: 0,
    risk_level: ''
};
```

## Testing Scenarios

### Happy Path
1. Fill all required fields with valid data
2. Select Standard Life policy with $500K coverage
3. Check no tobacco, no conditions
4. Enter normal BMI values
5. Accept terms and submit
6. **Expected**: Low/Medium risk, application created successfully

### High-Risk Profile
1. Age: 55 years old
2. Tobacco use: Yes
3. Medical conditions: Diabetes, High Blood Pressure, Heart Disease
4. Recent surgery: Yes
5. Hazardous activities: Scuba Diving, Rock Climbing
6. BMI: Obese category
7. **Expected**: Very High risk, higher premium, application flagged for review

### Edge Cases
1. **Minimum Age (18)**: Should calculate lowest age factor
2. **Maximum Age (85)**: Should show warning, highest age factor
3. **Minimum Coverage**: $100K for Basic Life
4. **Maximum Coverage**: $5M for Premium Life
5. **Zero Height/Weight**: Should prevent BMI calculation
6. **Missing Required Fields**: Should block progression

### Mobile Responsiveness
1. Test on iPhone (375px width)
2. Test on iPad (768px width)
3. Test on desktop (1200px+ width)
4. **Expected**: All elements readable, buttons accessible, forms usable

## Future Enhancements

### Phase 1 (Short-term)
- [ ] Email confirmation after submission
- [ ] SMS notifications for status updates
- [ ] Document upload capability (driver's license, medical records)
- [ ] Save & resume application feature
- [ ] Application status tracking in dashboard

### Phase 2 (Medium-term)
- [ ] E-signature integration
- [ ] Payment method setup during application
- [ ] Beneficiary designation
- [ ] Medical exam scheduling
- [ ] Real-time chat support

### Phase 3 (Long-term)
- [ ] AI-powered risk assessment
- [ ] Instant underwriting for low-risk applicants
- [ ] Dynamic questionnaire (conditional questions)
- [ ] Integration with medical records APIs
- [ ] Video consultation booking

## Security Considerations

### Current Implementation
- Client-side validation (basic)
- API endpoint authentication (token-based)
- Data transmitted via HTTP (development)

### Production Requirements
- [ ] HTTPS/TLS encryption mandatory
- [ ] Input sanitization on backend
- [ ] Rate limiting on API endpoints
- [ ] CAPTCHA for bot prevention
- [ ] PII encryption at rest
- [ ] HIPAA compliance for health data
- [ ] Session timeout (15 minutes)
- [ ] Audit logging for all submissions

## Monitoring & Analytics

### Key Metrics to Track
1. **Application Funnel**:
   - Started applications
   - Completed step 1, 2, 3, 4
   - Submitted applications
   - Conversion rate

2. **User Behavior**:
   - Time spent per step
   - Fields with most errors
   - Abandonment points
   - Device/browser distribution

3. **Risk Distribution**:
   - Low/Medium/High/Very High percentages
   - Average premium by risk level
   - Most common medical conditions
   - BMI distribution

4. **Business Outcomes**:
   - Applications submitted per day
   - Approval rate
   - Average time to underwriting decision
   - Revenue per application

## Troubleshooting

### Common Issues

**Problem**: Premium not updating
- **Cause**: Missing policy type or coverage amount
- **Fix**: Select policy card and ensure coverage slider has value

**Problem**: Can't proceed to next step
- **Cause**: Required fields not filled
- **Fix**: Look for red border around fields, fill all required

**Problem**: BMI not calculating
- **Cause**: Height or weight is 0
- **Fix**: Enter valid height (feet + inches) and weight (pounds)

**Problem**: Submit button disabled
- **Cause**: Terms checkboxes not checked
- **Fix**: Check both checkboxes at bottom of Step 4

**Problem**: API error on submission
- **Cause**: Server not running or invalid data
- **Fix**: Check server.py is running, verify all fields valid

## Access Points

### URLs
- **Homepage**: http://localhost:8000/
- **Application Form**: http://localhost:8000/apply.html
- **Customer Dashboard**: http://localhost:8000/dashboard.html
- **Admin Portal**: http://localhost:8000/admin-portal.html

### From Homepage
- Click "Apply Now" button in hero section
- Click "Get Started" in CTA section

### From Dashboard
- Click "Apply for New Policy" action card (top of page)

## Support Documentation

### User Guide (Customer-Facing)
Create a help section explaining:
- How to choose the right policy type
- What information you'll need (SSN, medical history, etc.)
- How coverage amounts work
- What happens after submission
- Expected timeline for approval

### Admin Guide (Internal)
Reference existing `ADMIN_PORTAL_GUIDE.md` for:
- How customer applications appear in underwriting queue
- What data is collected
- How to review applications
- Approval/rejection workflows

## Conclusion

The PHINS Customer Application System provides a complete, business-oriented mirror of the admin policy creation process. It's designed for:

1. **Ease of Use**: Simple 4-step wizard, clear instructions
2. **Transparency**: Real-time premium calculation, risk explanation
3. **Completeness**: Collects all necessary underwriting data
4. **Integration**: Seamlessly feeds into admin workflow
5. **Scalability**: Ready for future enhancements

Customers can now apply for policies in 2-4 minutes with a modern, professional experience that matches the quality of the admin portal.
