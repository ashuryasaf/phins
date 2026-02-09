# Visual Guide: Risk Reports Dashboard UI Enhancements

## Feature 1: Collapsible Sections

### Before Enhancement
```
┌─────────────────────────────────────────────────┐
│ 📥 Swiftness Data Resources                    │
│ ─────────────────────────────────────────────── │
│ [Always expanded content taking up space]       │
│ • Files, links, schemas...                      │
│ • Multiple lines of data...                     │
│ • More information...                           │
└─────────────────────────────────────────────────┘
```

### After Enhancement
```
┌─────────────────────────────────────────────────┐
│ 📥 Swiftness Data Resources              ▶     │ ← Click to expand
└─────────────────────────────────────────────────┘
    (Minimized by default, content hidden)

┌─────────────────────────────────────────────────┐
│ 📥 Swiftness Data Resources              ▼     │ ← Click to collapse
│ ─────────────────────────────────────────────── │
│ [Content visible when expanded]                 │
│ • Files, links, schemas...                      │
│ • Multiple lines of data...                     │
│ • More information...                           │
└─────────────────────────────────────────────────┘
```

### Sections Set to Minimize by Default
✓ 📥 Swiftness Data Resources
✓ 🧬 Interface & Schema Coverage
✓ 📁 Uploaded Document Context
✓ 🧭 Swiftness Affiliation Report (1 file)
✓ 🧭 Swiftness Affiliation Intelligence

---

## Feature 2: Interactive Minitabs

### Report Model Structure Section - Enhanced View

```
┌───────────────────────────────────────────────────────────────────┐
│ 📊 Report Model Structure (Nituach Tik)                    ▼     │
│ ─────────────────────────────────────────────────────────────────│
│ Professional portfolio analysis report with 12 sections           │
│                                                                    │
│ ╔═══════════════════════════╗ ╔═══════════════════════════╗     │
│ ║  ┌──┐                      ║ ║  ┌──┐                      ║     │
│ ║  │1 │ פרטי לקוח            ║ ║  │2 │ פרטי פוליסה          ║     │
│ ║  └──┘ Client Details       ║ ║  └──┘ Policy Details      ║     │
│ ║  ┌─────────────────────┐   ║ ║  ┌─────────────────────┐   ║     │
│ ║  │ 8 fields            │   ║ ║  │ 12 fields           │   ║     │
│ ║  └─────────────────────┘   ║ ║  └─────────────────────┘   ║     │
│ ║      📊 Generate Report    ║ ║      📊 Generate Report    ║     │
│ ╚═══════════════════════════╝ ╚═══════════════════════════╝     │
│      (Hover: border turns blue, card lifts)                      │
│                                                                    │
│ ╔═══════════════════════════╗ ╔═══════════════════════════╗     │
│ ║  ┌──┐                      ║ ║  ┌──┐                      ║     │
│ ║  │3 │ סיכום תיק            ║ ║  │4 │ ניתוח השקעות         ║     │
│ ║  └──┘ Portfolio Summary    ║ ║  └──┘ Investment Analysis ║     │
│ ║  ┌─────────────────────┐   ║ ║  ┌─────────────────────┐   ║     │
│ ║  │ 15 fields           │   ║ ║  │ 20 fields           │   ║     │
│ ║  │ 📈 Bar Chart        │   ║ ║  │ 📈 Line Chart       │   ║     │
│ ║  │ 📈 Pie Chart        │   ║ ║  │ 📈 Bar Chart        │   ║     │
│ ║  └─────────────────────┘   ║ ║  └─────────────────────┘   ║     │
│ ║      📊 Generate Report    ║ ║      📊 Generate Report    ║     │
│ ╚═══════════════════════════╝ ╚═══════════════════════════╝     │
│                                                                    │
│ ┌────────────────────────────────────────────────────────────┐   │
│ │ 💡 Interactive Minitabs: Click any section card above to   │   │
│ │    generate a specific report for that section based on    │   │
│ │    its affiliated source data.                             │   │
│ └────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### When User Clicks a Minitab

```
           ┌─────────────────────────────────────────────┐
           │  ╔════════════════════════════════════════╗ │
           │  ║  ┌──┐                           ✕     ║ │
           │  ║  │3 │                                  ║ │
           │  ║  └──┘                                  ║ │
           │  ║  סיכום תיק                             ║ │
           │  ║  Portfolio Summary                     ║ │
           │  ╠════════════════════════════════════════╣ │
           │  ║                                        ║ │
           │  ║  📊 Section 3 - Detailed Report       ║ │
           │  ║  Generated from Swiftness Mislaka      ║ │
           │  ║  standards with 15 data fields         ║ │
           │  ║                                        ║ │
           │  ║  📋 Data Fields                        ║ │
           │  ║  ┌────────────────────────────────┐   ║ │
           │  ║  │ יתרה כוללת (Total Balance)     │   ║ │
           │  ║  │ Total Balance • currency       │   ║ │
           │  ║  └────────────────────────────────┘   ║ │
           │  ║  ┌────────────────────────────────┐   ║ │
           │  ║  │ הפקדות חודשיות (Monthly Dep.)  │   ║ │
           │  ║  │ Monthly Deposits • currency    │   ║ │
           │  ║  └────────────────────────────────┘   ║ │
           │  ║  ... (13 more fields)                 ║ │
           │  ║                                        ║ │
           │  ║  📈 Recommended Charts                 ║ │
           │  ║  Bar Chart   Pie Chart   Line Chart   ║ │
           │  ║                                        ║ │
           │  ║  ✅ Data Source: 15 affiliated fields ║ │
           │  ║     following Mislaka standards       ║ │
           │  ║                                        ║ │
           │  ║  [📥 Download PDF]  [Close]           ║ │
           │  ╚════════════════════════════════════════╝ │
           └─────────────────────────────────────────────┘
                     Modal Popup (Click outside or X to close)
```

---

## Feature 3: PDF Export

### Main Report Export Button

```
┌────────────────────────────────────────────────────┐
│ 🧭 Swiftness Affiliation Report (1 file)          │
│ ───────────────────────────────────────────────────│
│ [📥 Export PDF]  [📊 Export Excel]                 │
│                                                     │
│ [Report content...]                                │
└────────────────────────────────────────────────────┘
              ↓ Click "Export PDF"
┌────────────────────────────────────────────────────┐
│ 📥 Generating PDF...                               │
│                                                     │
│ • Collecting visible sections                      │
│ • Excluding minimized sections                     │
│ • Formatting content                               │
│ • Creating pages with breaks                       │
└────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────┐
│ ✅ PDF Downloaded Successfully!                    │
│                                                     │
│ phins_risk_report_1739134589234.pdf               │
└────────────────────────────────────────────────────┘
```

### PDF Output Structure

```
╔════════════════════════════════════════════════════╗
║  PHINS Risk Analysis Report                        ║
║                                                    ║
║  Generated: February 9, 2026 8:33 PM              ║
║                                                    ║
║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ║
║                                                    ║
║  🧭 Affiliation Snapshot                          ║
║  Generated from Swiftness + Mislaka Research Hub  ║
║  Snapshot Timestamp: Feb 9, 2026                  ║
║  • Entity Types: 45                               ║
║  • Product Types: 23                              ║
║  • Status Codes: 12                               ║
║  • ID Types: 8                                    ║
║                                                    ║
║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ║
║                                                    ║
║  [📥 Swiftness Data Resources - EXCLUDED]         ║
║  [🧬 Interface & Schema Coverage - EXCLUDED]      ║
║  [📁 Uploaded Document Context - EXCLUDED]        ║
║  (Sections were minimized, excluded from PDF)     ║
║                                                    ║
║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ║
║                                                    ║
║  📊 Report Model Structure (Nituach Tik)          ║
║  Professional portfolio analysis with 12 sections ║
║  1. Client Details (8 fields)                     ║
║  2. Policy Details (12 fields)                    ║
║  ... (all sections listed)                        ║
║                                                    ║
╚════════════════════════════════════════════════════╝
```

### Minitab-Specific PDF Export

```
╔════════════════════════════════════════════════════╗
║  Section 3: Portfolio Summary                      ║
║  סיכום תיק                                         ║
║                                                    ║
║  Generated: February 9, 2026 8:35 PM              ║
║                                                    ║
║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ║
║                                                    ║
║  Data Fields:                                      ║
║  1. Total Balance (currency)                      ║
║  2. Monthly Deposits (currency)                   ║
║  3. Investment Returns (percentage)               ║
║  4. Management Fees (currency)                    ║
║  5. Account Status (text)                         ║
║  ... (15 fields total)                            ║
║                                                    ║
║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ║
║                                                    ║
║  Recommended Charts:                              ║
║  1. Bar Chart                                     ║
║  2. Pie Chart                                     ║
║  3. Line Chart                                    ║
║                                                    ║
╚════════════════════════════════════════════════════╝
```

---

## User Interactions Summary

### 1. Section Collapse/Expand
```
Action: Click section heading
Before: ▼ Section Title (expanded)
After:  ▶ Section Title (collapsed, content hidden)
```

### 2. Minitab Hover
```
State: Normal
┌─────────────┐
│ Section 1   │  Border: #e2e8f0 (gray)
│ 8 fields    │  Position: normal
└─────────────┘

State: Hover
┌─────────────┐
│ Section 1   │  Border: #0d47a1 (blue)
│ 8 fields    │  Position: lifted (-2px)
└─────────────┘  Shadow: increased
```

### 3. Minitab Click
```
Click → Loading (0.8s) → Modal Opens
   ↓
┌─────────────┐
│ 📊          │
│ Generating  │
│ Report...   │
└─────────────┘
```

### 4. PDF Export Flow
```
Click Export → Load Library → Generate → Download → Success
    ↓              ↓             ↓          ↓         ↓
  Button      jsPDF CDN    Format PDF   Browser   Notification
```

---

## Responsive Design

### Desktop (1400px+)
- Minitabs: 4 columns
- Full modal width: 800px
- All features visible

### Tablet (768px - 1400px)
- Minitabs: 2-3 columns
- Modal width: 90%
- Sections stack appropriately

### Mobile (< 768px)
- Minitabs: 1 column
- Modal width: 95%
- Touch-friendly tap targets
- Scrollable modal content

---

## Color Scheme

### Primary Colors
- Primary Blue: #0d47a1
- Primary Light: #1976d2
- Success Green: #10b981
- Text Dark: #1a1a2e
- Text Muted: #64748b

### State Colors
- Hover: Primary with 15% transparency
- Active: Slightly darker primary
- Disabled: 60% opacity

### Section-Specific
- Swiftness Resources: Green gradient (#f0fdf4 to #dcfce7)
- Report Model: Blue gradient (#eff6ff to #dbeafe)
- Minitab badges: Light blue (#e0f2fe)
- Chart badges: Amber (#fef3c7)

---

## Accessibility Features

✓ Keyboard Navigation: Tab through sections and buttons
✓ Screen Reader Support: Proper ARIA labels
✓ High Contrast: Clear visual indicators
✓ Focus States: Visible focus rings
✓ Click Targets: Minimum 44x44px touch targets
✓ Animations: Respectful of prefers-reduced-motion

---

## Performance Metrics

- Section Toggle: < 300ms animation
- Minitab Click: 800ms loading + instant modal
- PDF Generation: 1-3 seconds (depends on content)
- Page Load: No blocking, progressive enhancement

---

*This visual guide demonstrates the UI enhancements without requiring screenshots.*
*All features are implemented and ready for testing in production environment.*
