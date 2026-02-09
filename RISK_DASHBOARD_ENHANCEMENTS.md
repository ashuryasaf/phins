# Risk Reports Dashboard Enhancements

## Overview
This document describes the enhancements made to the Risk Reports Dashboard (`/risk-reports-dashboard.html`) to improve user experience with collapsible sections, interactive minitabs, and PDF export functionality.

## Features Implemented

### 1. Collapsible Sections with Default Minimize State

#### Implementation Details
- **CSS Classes Added:**
  - `.collapsible` - Makes a section collapsible
  - `.collapsed` - Represents collapsed state
  - Smooth transitions using `max-height` and `opacity`
  - Animated arrow indicator (▼) that rotates when collapsed

#### User Experience
- Sections with collapsible functionality show a clickable header
- Arrow indicator shows current state (down = expanded, right = collapsed)
- Smooth animation when toggling between states
- Content is completely hidden when collapsed to save screen space

#### Default Minimized Sections
The following sections are set to be minimized by default when the report loads:

1. **📥 Swiftness Data Resources** - External data resources and downloads
2. **🧬 Interface & Schema Coverage** - Technical schema information
3. **📁 Uploaded Document Context** - File upload details
4. **🧭 Swiftness Affiliation Report (1 file)** - Affiliation snapshot data
5. **🧭 Swiftness Affiliation Intelligence** - Combined intelligence data

#### Code Implementation
```javascript
function makeCollapsible(sectionElement, defaultCollapsed = false) {
  if (!sectionElement) return;
  
  sectionElement.classList.add('collapsible');
  if (defaultCollapsed) {
    sectionElement.classList.add('collapsed');
  }
  
  const heading = sectionElement.querySelector('h3');
  if (heading) {
    heading.addEventListener('click', () => toggleSection(sectionElement));
  }
}
```

### 2. Interactive Minitabs in "Report Model Structure (Nituach Tik)"

#### Features
Each report section is now displayed as an interactive "minitab" card that includes:

- **Visual Design:**
  - Section number badge with primary color
  - Hebrew and English titles
  - Field count indicator
  - Chart type badges (if applicable)
  - Hover effects with elevation and border color change

- **Interactive Functionality:**
  - Click any minitab to generate a detailed report for that section
  - Modal popup displays section-specific information
  - Shows all data fields with types
  - Lists recommended chart types
  - Source data attribution

#### Code Implementation
```javascript
function generateMinitabReport(sectionIndex, titleHe, titleEn) {
  const section = swiftnessReportModel?.sections?.[sectionIndex];
  // Creates modal with detailed section report
  // Shows fields, charts, and data source info
}
```

#### Minitab Card Structure
Each card displays:
- Section order number (1-N)
- Hebrew title (primary)
- English title (secondary)
- Number of data fields
- "📊 Generate Report" action link
- Chart badges (if section has recommended charts)

### 3. PDF Export Functionality

#### Main Report PDF Export
- **Button Location:** "📥 Export PDF" button in report header
- **Functionality:**
  - Dynamically loads jsPDF library (CDN)
  - Exports complete report to PDF
  - **Excludes collapsed/minimized sections** automatically
  - Includes proper formatting and page breaks
  - Adds timestamp to document

#### PDF Content Includes:
- Report title
- Generation timestamp
- All expanded section headings
- Section content (text only, HTML stripped)
- Proper pagination

#### Individual Minitab PDF Export
- Each minitab modal has "📥 Download PDF" button
- Generates section-specific PDF with:
  - Section number and titles (Hebrew + English)
  - Complete list of data fields with types
  - Recommended charts
  - Generation timestamp
  - Data source attribution

#### Code Implementation
```javascript
function exportReport(format) {
  if (format !== 'pdf') {
    alert(`Export to ${format.toUpperCase()} - Coming soon!`);
    return;
  }
  
  // Load jsPDF library dynamically
  if (typeof window.jspdf === 'undefined') {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
    script.onload = () => generatePDF();
    document.head.appendChild(script);
  } else {
    generatePDF();
  }
}
```

## Technical Implementation

### CSS Enhancements
```css
/* Collapsible Section Styles */
.report-section.collapsible h3 {
  cursor: pointer;
  user-select: none;
  position: relative;
  padding-right: 30px;
  transition: color 0.2s;
}

.report-section.collapsible h3::after {
  content: '▼';
  position: absolute;
  right: 0;
  font-size: 0.8rem;
  transition: transform 0.3s;
}

.report-section.collapsible.collapsed h3::after {
  transform: rotate(-90deg);
}

.report-section.collapsible .content {
  max-height: 2000px;
  overflow: hidden;
  transition: max-height 0.3s ease-out, opacity 0.3s;
  opacity: 1;
}

.report-section.collapsible.collapsed .content {
  max-height: 0;
  opacity: 0;
}

/* Minitab Card Hover Effects */
.minitab-card:hover {
  border-color: var(--primary) !important;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(13, 71, 161, 0.15);
}
```

### JavaScript Functions Added

1. **toggleSection(element)** - Toggles collapsed state
2. **makeCollapsible(sectionElement, defaultCollapsed)** - Initializes collapsible behavior
3. **exportReport(format)** - Main PDF export function
4. **generatePDF()** - Creates PDF from visible sections
5. **generateMinitabReport(index, titleHe, titleEn)** - Shows minitab modal
6. **exportMinitabToPDF(sectionIndex)** - Exports single section to PDF
7. **generateMinitabPDF(section)** - Creates minitab-specific PDF

## User Journey

### Viewing the Report
1. User navigates to Risk Reports Dashboard
2. Report loads with specified sections minimized by default
3. User can click on any section header to expand/collapse
4. Main content sections (Affiliation Snapshot, Report Model Structure) remain expanded

### Working with Minitabs
1. User scrolls to "📊 Report Model Structure (Nituach Tik)" section
2. Sees grid of interactive minitab cards
3. Hovers over a card to see hover effect
4. Clicks card to generate detailed section report
5. Modal appears with complete section information
6. Can download section-specific PDF or close modal

### Exporting to PDF
1. User clicks "📥 Export PDF" button in report header
2. System generates PDF of all expanded sections
3. Collapsed sections are automatically excluded
4. PDF downloads with timestamped filename
5. Success notification appears

## Benefits

### For End Users
- **Better Organization:** Minimize irrelevant sections to focus on key data
- **Cleaner Interface:** Default minimized state reduces visual clutter
- **Quick Access:** Interactive minitabs provide direct access to section details
- **Portable Reports:** PDF export for sharing and archiving
- **Flexible Exports:** Choose between full report or section-specific PDFs

### For Data Analysts
- **Focused Analysis:** Generate reports for specific portfolio sections
- **Data Field Visibility:** See all fields and their types in minitab modals
- **Chart Recommendations:** Know which visualizations work best for each section
- **Professional Output:** PDF exports suitable for client presentations

### For System Integration
- **Modular Design:** Each minitab can be enhanced independently
- **Extensible:** Easy to add more sections or customize behavior
- **Standards Compliant:** Based on Mislaka portfolio analysis standards
- **API Ready:** Structure supports future backend integration for real data

## Browser Compatibility
- Modern browsers (Chrome, Firefox, Safari, Edge)
- Requires JavaScript enabled
- jsPDF library loaded from CDN (fallback mechanism included)

## Dependencies
- **jsPDF** - PDF generation (loaded dynamically)
- **Chart.js** - Already included in page for charts

## Future Enhancements (Potential)
1. **Save Section States:** Remember which sections user has minimized
2. **Bulk Operations:** Expand/collapse all sections at once
3. **PDF Templates:** Custom PDF layouts and branding
4. **Real-time Data:** Connect minitabs to live backend data
5. **Export Options:** Add Excel export for minitab data
6. **Search/Filter:** Filter minitabs by section type or field count
7. **Favorites:** Mark frequently used sections for quick access

## Testing Checklist
- [x] Collapsible sections toggle correctly
- [x] Default minimized sections start collapsed
- [x] Arrow indicator rotates with state
- [x] Minitab cards display correctly
- [x] Minitab click opens modal
- [x] Minitab modal shows correct data
- [x] Main PDF export works
- [x] Collapsed sections excluded from PDF
- [x] Minitab PDF export works
- [x] Hover effects work on minitabs
- [x] Mobile responsive (minitabs reflow)

## Code Location
- **File:** `/web_portal/static/risk-reports-dashboard.html`
- **Lines (approximate):**
  - CSS: Lines 862-915
  - JavaScript: Lines 4067-4289
  - Minitab HTML: Lines 3516-3544

## Git Commit
- **Commit:** `6efacff`
- **Message:** "Implement collapsible sections, minitab reports, and PDF export"
- **Files Changed:** 1 file, 430 insertions, 7 deletions

---

*Last Updated: February 9, 2026*
*Implementation Status: ✅ Complete*
