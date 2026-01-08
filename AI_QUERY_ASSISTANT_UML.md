# 🤖 PHINS AI Query Assistant - Architecture & Design

## Executive Summary

The AI Query Assistant is an intelligent, voice-enabled natural language interface that allows customers to interact with their PHINS dashboard using conversational queries. It processes text and voice input, understands user intent, executes actions, and generates custom reports—all while maintaining data integrity with the PHINS pipeline.

---

## 1. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           PHINS AI QUERY ASSISTANT                               │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│    ┌──────────────┐         ┌──────────────────────────────────────┐            │
│    │   Customer   │◄───────►│      🎤 AI Query Interface           │            │
│    │   (Voice/    │         │  ┌────────────────────────────────┐  │            │
│    │    Text)     │         │  │  Natural Language Input        │  │            │
│    └──────────────┘         │  │  Voice Recognition (Web API)   │  │            │
│                             │  │  Intent Classification         │  │            │
│                             │  └────────────────────────────────┘  │            │
│                             └──────────────────────────────────────┘            │
│                                           │                                      │
│                                           ▼                                      │
│    ┌──────────────────────────────────────────────────────────────────┐         │
│    │                    🧠 AI Processing Engine                        │         │
│    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │         │
│    │  │   Intent    │  │   Entity    │  │   Action    │              │         │
│    │  │  Classifier │  │  Extractor  │  │   Router    │              │         │
│    │  └─────────────┘  └─────────────┘  └─────────────┘              │         │
│    └──────────────────────────────────────────────────────────────────┘         │
│                                           │                                      │
│         ┌─────────────────────────────────┼─────────────────────────────┐       │
│         │                                 │                             │       │
│         ▼                                 ▼                             ▼       │
│  ┌──────────────┐              ┌──────────────┐              ┌──────────────┐  │
│  │   📊 Report  │              │   💳 Action  │              │   📈 BI      │  │
│  │   Generator  │              │   Executor   │              │  Calculator  │  │
│  └──────────────┘              └──────────────┘              └──────────────┘  │
│         │                                 │                             │       │
│         └─────────────────────────────────┼─────────────────────────────┘       │
│                                           ▼                                      │
│    ┌──────────────────────────────────────────────────────────────────┐         │
│    │                    🔗 PHINS Data Pipeline                          │         │
│    │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐│         │
│    │  │Customer │  │ Policy  │  │ Billing │  │ Savings │  │ Claims  ││         │
│    │  │  Data   │  │  Data   │  │  Data   │  │  Data   │  │  Data   ││         │
│    │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘│         │
│    └──────────────────────────────────────────────────────────────────┘         │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Query Classification Taxonomy

```
                            ┌─────────────────────┐
                            │    User Query       │
                            │  (Text or Voice)    │
                            └──────────┬──────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
        ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
        │  📊 REPORT        │ │  ❓ INFORMATION   │ │  ⚡ ACTION        │
        │     QUERIES       │ │     QUERIES       │ │     QUERIES       │
        └───────────────────┘ └───────────────────┘ └───────────────────┘
                │                      │                      │
    ┌───────────┼───────────┐          │          ┌───────────┼───────────┐
    │           │           │          │          │           │           │
    ▼           ▼           ▼          ▼          ▼           ▼           ▼
┌───────┐ ┌───────┐ ┌───────┐ ┌───────────┐ ┌───────┐ ┌───────┐ ┌───────┐
│Billing│ │Personal│ │Policy │ │Monthly    │ │Apply  │ │Pay    │ │Save/  │
│Report │ │Data   │ │Summary│ │Costs/     │ │Policy │ │Bills  │ │Invest │
│       │ │Report │ │       │ │Savings    │ │       │ │       │ │       │
└───────┘ └───────┘ └───────┘ └───────────┘ └───────┘ └───────┘ └───────┘
                              │
                    ┌─────────┼─────────┐
                    │         │         │
                    ▼         ▼         ▼
              ┌─────────┐ ┌─────────┐ ┌─────────┐
              │Coverage │ │Savings  │ │Future   │
              │Amount   │ │Balance  │ │Projec-  │
              │         │ │         │ │tions    │
              └─────────┘ └─────────┘ └─────────┘
```

---

## 3. Intent Classification Engine

### 3.1 Supported Intents

| Intent ID | Category | Example Queries | Action |
|-----------|----------|-----------------|--------|
| `REPORT_BILLING` | Report | "Show me all my billings", "billing report" | Generate billing report |
| `REPORT_PERSONAL` | Report | "My personal data", "profile report" | Generate personal data report |
| `REPORT_POLICY` | Report | "Policy summary", "coverage report" | Generate policy summary |
| `REPORT_SAVINGS` | Report | "Savings report", "investment summary" | Generate savings/investment report |
| `REPORT_CLAIMS` | Report | "Claims history", "my claims report" | Generate claims report |
| `INFO_MONTHLY_COST` | Info | "How much do I pay monthly?" | Show monthly premium |
| `INFO_MONTHLY_SAVINGS` | Info | "How much do I save monthly?" | Show monthly savings |
| `INFO_COVERAGE` | Info | "What's my coverage?", "risk cover amount" | Show coverage details |
| `INFO_BALANCE` | Info | "What's my balance?", "savings balance" | Show current balances |
| `CALC_PROJECTION` | Calc | "Savings in 5 years", "future value" | Calculate projections |
| `ACTION_APPLY` | Action | "Apply for new policy", "get insurance" | Navigate to application |
| `ACTION_PAY` | Action | "Pay my bills", "make payment" | Navigate to payment |
| `ACTION_SAVE` | Action | "Save $10,000", "invest money" | Navigate to savings |
| `ACTION_CLAIM` | Action | "File a claim", "submit claim" | Navigate to claims |
| `ACTION_UPDATE` | Action | "Update my info", "change address" | Navigate to settings |

### 3.2 Entity Extraction

```
┌────────────────────────────────────────────────────────────────┐
│                     ENTITY EXTRACTOR                            │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Input: "How much savings will I have in 5.5 years if I        │
│          save $500 monthly?"                                    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Extracted Entities:                                      │   │
│  │                                                          │   │
│  │  📅 TIME_PERIOD: 5.5 years (66 months)                  │   │
│  │  💰 AMOUNT: $500                                        │   │
│  │  🔄 FREQUENCY: monthly                                  │   │
│  │  📊 CALCULATION_TYPE: future_value                      │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Output: {                                                      │
│    intent: "CALC_PROJECTION",                                   │
│    entities: {                                                  │
│      time_period: { value: 5.5, unit: "years", months: 66 },   │
│      amount: { value: 500, currency: "USD" },                  │
│      frequency: "monthly",                                      │
│      calculation: "future_value"                               │
│    }                                                            │
│  }                                                              │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. Voice Recognition Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    VOICE RECOGNITION PIPELINE                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │   🎤     │    │   📝     │    │   🧠     │    │   ⚡     │      │
│  │  Voice   │───►│  Speech  │───►│  Intent  │───►│  Action  │      │
│  │  Input   │    │  to Text │    │  Parse   │    │  Execute │      │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘      │
│       │                │                │                │          │
│       │                │                │                │          │
│       ▼                ▼                ▼                ▼          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │ Web      │    │ Clean &  │    │ Classify │    │ Generate │      │
│  │ Speech   │    │ Normalize│    │ Intent + │    │ Response │      │
│  │ API      │    │ Text     │    │ Extract  │    │ or       │      │
│  │          │    │          │    │ Entities │    │ Report   │      │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘      │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    SUPPORTED LANGUAGES                       │    │
│  │  🇺🇸 English  🇮🇱 Hebrew  🇪🇸 Spanish  🇫🇷 French  🇩🇪 German   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. Report Generation Engine

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CUSTOM REPORT GENERATOR                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Input: { intent: "REPORT_BILLING", customer_id: "CUST-123" }       │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                     DATA AGGREGATION                           │  │
│  │                                                                │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐       │  │
│  │  │ Billing     │    │ Payment     │    │ Policy      │       │  │
│  │  │ History     │    │ Schedule    │    │ Premium     │       │  │
│  │  │ API         │    │ API         │    │ API         │       │  │
│  │  └─────────────┘    └─────────────┘    └─────────────┘       │  │
│  │         │                  │                  │               │  │
│  │         └──────────────────┼──────────────────┘               │  │
│  │                            ▼                                  │  │
│  │                   ┌─────────────────┐                        │  │
│  │                   │   Data Merger   │                        │  │
│  │                   │   & Enrichment  │                        │  │
│  │                   └─────────────────┘                        │  │
│  │                            │                                  │  │
│  └────────────────────────────┼──────────────────────────────────┘  │
│                               ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                     REPORT TEMPLATES                           │  │
│  │                                                                │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐          │  │
│  │  │ Summary │  │ Detail  │  │ Chart   │  │ Export  │          │  │
│  │  │ View    │  │ Table   │  │ Visual  │  │ PDF/CSV │          │  │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘          │  │
│  │                                                                │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  Output: Interactive report with download options                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. BI Calculation Engine

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BI CALCULATION ENGINE                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  PROJECTION CALCULATOR                                               │
│  ─────────────────────                                               │
│                                                                      │
│  Query: "How much savings will I have in 5.5 years?"                │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                                                                │  │
│  │  Current Savings:      $12,500                                │  │
│  │  Monthly Contribution: $500                                   │  │
│  │  Expected Return:      7.2% annual                            │  │
│  │  Time Period:          5.5 years (66 months)                  │  │
│  │                                                                │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │              COMPOUND GROWTH FORMULA                     │  │  │
│  │  │                                                          │  │  │
│  │  │  FV = PV(1+r)^n + PMT × [((1+r)^n - 1) / r]            │  │  │
│  │  │                                                          │  │  │
│  │  │  Where:                                                  │  │  │
│  │  │    PV  = Present Value ($12,500)                        │  │  │
│  │  │    r   = Monthly rate (7.2%/12 = 0.006)                 │  │  │
│  │  │    n   = Number of months (66)                          │  │  │
│  │  │    PMT = Monthly payment ($500)                         │  │  │
│  │  │                                                          │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                │  │
│  │  RESULT:                                                      │  │
│  │  ════════                                                     │  │
│  │  📊 Future Value:           $59,847.32                       │  │
│  │  💰 Total Contributions:    $33,000.00                       │  │
│  │  📈 Investment Growth:      $14,347.32                       │  │
│  │  🎯 Effective Return:       27.09%                           │  │
│  │                                                                │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Action Router Sequence Diagram

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│ Customer│     │AI Query │     │ Intent  │     │ Action  │     │ Pipeline│
│         │     │Interface│     │Classifier│    │ Router  │     │   API   │
└────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘
     │               │               │               │               │
     │  "Pay my bills"               │               │               │
     │──────────────►│               │               │               │
     │               │               │               │               │
     │               │ Classify      │               │               │
     │               │──────────────►│               │               │
     │               │               │               │               │
     │               │ Intent:       │               │               │
     │               │ ACTION_PAY    │               │               │
     │               │◄──────────────│               │               │
     │               │               │               │               │
     │               │ Route Action  │               │               │
     │               │──────────────────────────────►│               │
     │               │               │               │               │
     │               │               │               │ Fetch billing │
     │               │               │               │ data          │
     │               │               │               │──────────────►│
     │               │               │               │               │
     │               │               │               │ Outstanding   │
     │               │               │               │ balance: $450 │
     │               │               │               │◄──────────────│
     │               │               │               │               │
     │               │ Show payment  │               │               │
     │               │ options +     │               │               │
     │               │ quick pay     │               │               │
     │◄──────────────────────────────────────────────│               │
     │               │               │               │               │
     │ [Confirm]     │               │               │               │
     │──────────────►│               │               │               │
     │               │               │               │               │
     │               │               │               │ Process       │
     │               │               │               │ payment       │
     │               │               │               │──────────────►│
     │               │               │               │               │
     │               │               │               │ Success ✓     │
     │               │               │               │◄──────────────│
     │               │               │               │               │
     │  Payment      │               │               │               │
     │  confirmed!   │               │               │               │
     │◄──────────────────────────────────────────────│               │
     │               │               │               │               │
```

---

## 8. UI Component Design

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  🤖 PHINS AI Assistant                                         [?] [×] │  │
│  ├────────────────────────────────────────────────────────────────────────┤  │
│  │                                                                         │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │  │
│  │  │  💬 How can I help you today?                                   │   │  │
│  │  │                                                                  │   │  │
│  │  │  Try asking:                                                     │   │  │
│  │  │  • "Show me my billing report"                                  │   │  │
│  │  │  • "How much do I pay monthly?"                                 │   │  │
│  │  │  • "Calculate my savings in 5 years"                            │   │  │
│  │  │  • "I want to apply for a new policy"                           │   │  │
│  │  │                                                                  │   │  │
│  │  └─────────────────────────────────────────────────────────────────┘   │  │
│  │                                                                         │  │
│  │  ┌─────────────────────────────────────────────────────────┬───────┐   │  │
│  │  │  Ask me anything...                                      │  🎤  │   │  │
│  │  └─────────────────────────────────────────────────────────┴───────┘   │  │
│  │                                                                         │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │  │
│  │  │  ⚡ Quick Actions:                                               │   │  │
│  │  │                                                                  │   │  │
│  │  │  [📊 Billing Report] [💰 Savings Calc] [📋 My Policies]         │   │  │
│  │  │  [💳 Pay Bills] [📈 Investment Report] [🆘 File Claim]          │   │  │
│  │  │                                                                  │   │  │
│  │  └─────────────────────────────────────────────────────────────────┘   │  │
│  │                                                                         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  📊 AI RESPONSE AREA                                                   │  │
│  │  ─────────────────────────────────────────────────────────────────     │  │
│  │                                                                         │  │
│  │  [Dynamic content appears here based on query]                         │  │
│  │                                                                         │  │
│  │  • Reports render with charts and tables                               │  │
│  │  • Calculations show with visual breakdowns                            │  │
│  │  • Actions show confirmation dialogs                                   │  │
│  │  • Export buttons for PDF/CSV downloads                                │  │
│  │                                                                         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Data Integrity Protection

```
┌─────────────────────────────────────────────────────────────────────┐
│                  DATA INTEGRITY RULES                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  🔒 READ-ONLY ACCESS                                                │
│  ─────────────────────                                               │
│  • Customer personal data                                            │
│  • Policy terms and conditions                                       │
│  • Historical transactions                                           │
│  • Claims history                                                    │
│                                                                      │
│  ✍️ WRITE ACTIONS (With Confirmation)                               │
│  ──────────────────────────────────────                              │
│  • New policy applications → Pipeline validation                    │
│  • Payment processing → Gateway verification                        │
│  • Savings deposits → Balance verification                          │
│  • Claim submissions → Document validation                          │
│                                                                      │
│  🛡️ SECURITY MEASURES                                               │
│  ─────────────────────                                               │
│  • All queries logged with audit trail                              │
│  • Sensitive data masked in responses                               │
│  • Action confirmation required for transactions                    │
│  • Session-based authentication                                     │
│  • Rate limiting on API calls                                       │
│                                                                      │
│  📊 PIPELINE VALIDATION                                             │
│  ───────────────────────                                             │
│  • All reports generated from live pipeline data                    │
│  • Real-time balance verification                                   │
│  • Cross-reference with source systems                              │
│  • Automatic data freshness indicators                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. Implementation Recommendations

### 10.1 Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Voice Input | Web Speech API | Native browser support, no external dependencies |
| Intent Classification | Rule-based + Fuzzy matching | Fast, reliable, no ML training needed |
| Entity Extraction | Regex + NLP patterns | Extract numbers, dates, currencies |
| Report Generation | Client-side HTML/CSS | Fast rendering, PDF export via html2pdf |
| BI Calculations | JavaScript math | Real-time calculations |
| Data Pipeline | REST API | Existing PHINS infrastructure |

### 10.2 Implementation Phases

```
Phase 1 (Core)           Phase 2 (Enhanced)        Phase 3 (Advanced)
─────────────────        ──────────────────        ─────────────────────
✓ Text input             ✓ Voice input             ✓ Multi-language
✓ Basic intents          ✓ Complex queries         ✓ Predictive suggestions
✓ Simple reports         ✓ Custom reports          ✓ Conversational context
✓ Quick actions          ✓ BI calculations         ✓ Smart recommendations
                         ✓ PDF export              ✓ Scheduled reports
```

### 10.3 Sample Query Processing

```javascript
// Example: "How much savings will I have in 5.5 years if I save $500/month?"

{
  "raw_query": "How much savings will I have in 5.5 years if I save $500/month?",
  "intent": {
    "type": "CALC_PROJECTION",
    "confidence": 0.95
  },
  "entities": {
    "time_period": { "value": 5.5, "unit": "years", "months": 66 },
    "amount": { "value": 500, "currency": "USD" },
    "frequency": "monthly",
    "calculation": "future_value"
  },
  "action": {
    "type": "calculate",
    "handler": "savingsProjection",
    "params": {
      "current_balance": "$12,500",  // From customer data
      "monthly_contribution": "$500",
      "expected_return": "7.2%",
      "period_months": 66
    }
  },
  "response": {
    "type": "projection_report",
    "data": {
      "future_value": "$59,847.32",
      "total_contributions": "$33,000",
      "investment_growth": "$14,347.32",
      "effective_return": "27.09%"
    }
  }
}
```

---

## 11. Best Practices & Recommendations

### ✅ DO:
1. **Start simple** - Implement core intents first, then expand
2. **Use fuzzy matching** - Users don't type perfectly
3. **Provide feedback** - Show processing state, confidence levels
4. **Confirm actions** - Never execute transactions without confirmation
5. **Cache reports** - Reduce API calls for frequently requested data
6. **Log everything** - Audit trail for all queries and actions

### ❌ DON'T:
1. **Don't rely solely on ML** - Rule-based is faster and more predictable
2. **Don't expose sensitive data** - Mask account numbers, etc.
3. **Don't skip validation** - Verify all calculations
4. **Don't forget mobile** - Voice is especially useful on mobile
5. **Don't ignore errors** - Graceful fallbacks for misunderstood queries

---

## 12. Conclusion

The PHINS AI Query Assistant will transform the customer experience by:

1. **Reducing friction** - Natural language instead of navigation
2. **Enabling voice** - Accessibility and convenience
3. **Instant insights** - Custom reports in seconds
4. **Quick actions** - Pay bills, apply policies, invest—all from one interface
5. **Maintaining integrity** - Secure, audited, pipeline-validated

**Ready for implementation!** 🚀
