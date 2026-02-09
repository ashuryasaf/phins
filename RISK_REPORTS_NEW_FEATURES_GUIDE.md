# User Guide: Risk Reports Dashboard New Features

## 🎯 What's New?

The Risk Reports Dashboard (risk-reports-dashboard.html) now includes three powerful features to improve your workflow:

1. **Collapsible Sections** - Hide/show report sections to focus on what matters
2. **Interactive Minitabs** - Generate detailed reports for specific portfolio sections
3. **PDF Export** - Download professional reports with smart filtering

---

## 📋 Using Collapsible Sections

### Which Sections Are Collapsible?

These sections start **minimized** when you load the page:
- 📥 Swiftness Data Resources
- 🧬 Interface & Schema Coverage
- 📁 Uploaded Document Context
- 🧭 Swiftness Affiliation Report (1 file)
- 🧭 Swiftness Affiliation Intelligence

### How to Use

**To Expand a Section:**
1. Look for the ▶ arrow next to the section title
2. Click the section heading
3. Section content appears with smooth animation

**To Collapse a Section:**
1. Click the expanded section heading (shows ▼ arrow)
2. Section content hides
3. Screen space is freed up

**Tip:** You can expand/collapse sections as many times as needed!

---

## 📊 Using Interactive Minitabs

### What Are Minitabs?

In the "📊 Report Model Structure (Nituach Tik)" section, each portfolio section is now an interactive card called a "minitab."

### How to Generate a Minitab Report

1. **Scroll** to the "Report Model Structure" section
2. **Find** the section you want to analyze (e.g., "Client Details", "Portfolio Summary")
3. **Hover** over the minitab card - it will highlight blue and lift up
4. **Click** the card anywhere
5. **Wait** for the modal to load (about 1 second)
6. **Review** the detailed information:
   - All data fields in that section
   - Field types (currency, text, date, etc.)
   - Recommended charts for visualization
   - Data source information

### What You See in the Modal

```
┌─────────────────────────────────────┐
│ Section Number & Titles (He + En)   │
│ ─────────────────────────────────── │
│ 📊 Section Details                  │
│                                      │
│ 📋 Data Fields:                     │
│   • Field 1 with type               │
│   • Field 2 with type               │
│   • ... all fields listed           │
│                                      │
│ 📈 Recommended Charts               │
│                                      │
│ [📥 Download PDF]  [Close]          │
└─────────────────────────────────────┘
```

### Downloading a Minitab PDF

1. Open the minitab modal (click any minitab card)
2. Review the section details
3. Click "📥 Download PDF" button
4. PDF downloads with the section's complete information
5. Success notification appears

**PDF Filename Format:** `phins_minitab_section{number}_{timestamp}.pdf`

---

## 📥 Exporting to PDF

### Main Report Export

**What Gets Exported:**
- Report title and timestamp
- All **expanded** sections (visible content)
- Proper formatting and page breaks

**What Gets Excluded:**
- Any **collapsed/minimized** sections
- HTML styling (converted to plain text)

### How to Export

1. **Prepare Your Report:**
   - Expand sections you want in the PDF
   - Minimize sections you want to exclude

2. **Click Export:**
   - Find "📥 Export PDF" button at the top of the report
   - Click the button

3. **Wait:**
   - System loads PDF library (first time only)
   - Generates PDF from visible content
   - Takes 1-3 seconds depending on content size

4. **Download:**
   - PDF downloads automatically
   - Success notification appears
   - Check your Downloads folder

**PDF Filename Format:** `phins_risk_report_{timestamp}.pdf`

---

## 💡 Pro Tips

### Workflow Optimization

**For Quick Review:**
1. Keep technical sections minimized (Data Resources, Schema Coverage)
2. Focus on business sections (Affiliation Snapshot, Report Model)
3. Export PDF of just the key sections

**For Detailed Analysis:**
1. Expand all sections
2. Review each minitab individually
3. Download minitab PDFs for specific areas
4. Export full report at the end

**For Client Presentations:**
1. Minimize all technical/internal sections
2. Keep only client-facing sections expanded
3. Export clean PDF without technical details
4. Sections excluded from PDF don't clutter the report

### Keyboard Navigation

- **Tab:** Move between clickable elements
- **Enter:** Activate buttons and toggle sections
- **Esc:** Close minitab modals (if supported)

### Mobile Use

- All features work on mobile devices
- Minitabs stack in single column on small screens
- Tap sections to expand/collapse
- PDF export works the same way

---

## ❓ Troubleshooting

### Section Won't Expand/Collapse
- **Solution:** Refresh the page and try again
- Make sure JavaScript is enabled

### Minitab Modal Won't Open
- **Solution:** Wait for page to fully load
- Check if you're clicking the card (not just the text)

### PDF Won't Download
- **Solution:** Allow pop-ups for the site
- Check browser download permissions
- Try with a different browser
- Make sure you have internet connection (for jsPDF library)

### PDF is Empty or Incomplete
- **Solution:** Expand the sections you want to include
- Wait for all content to load before exporting
- Sections that are collapsed are intentionally excluded

---

## 📞 Support

Need help? Check these resources:
- Full Technical Guide: `RISK_DASHBOARD_ENHANCEMENTS.md`
- Visual UI Guide: `RISK_DASHBOARD_UI_GUIDE.md`
- Contact: support@phins.ai

---

## 🔄 Feature Summary

| Feature | Action | Result |
|---------|--------|--------|
| Collapse Section | Click section heading | Content hides, arrow rotates |
| Expand Section | Click collapsed heading | Content shows smoothly |
| View Minitab | Click minitab card | Modal with section details |
| Export Minitab | Click PDF in modal | Download section-specific PDF |
| Export Report | Click Export PDF button | Download full report (visible sections only) |

---

## 🎨 Visual Indicators

| Symbol | Meaning |
|--------|---------|
| ▼ | Section is expanded |
| ▶ | Section is collapsed |
| 📊 | Generate Report |
| 📥 | Download/Export |
| ✕ | Close modal |

---

**Page:** https://phins-portal-production.up.railway.app/risk-reports-dashboard.html  
**Last Updated:** February 9, 2026  
**Version:** 1.0  
**Status:** Production Ready ✅
