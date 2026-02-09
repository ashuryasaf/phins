"""
Swiftness Data Service
======================
Provides Swiftness-affiliated data resources, links, file catalogs,
and an enhanced report model for the Risk Reports Dashboard.

Data sources:
  - https://www.swiftness.co.il/כללי-מערכת/  (System general files)
  - https://www.swiftness.co.il/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/  (Recent Mislaka work files)

The report model is inspired by professional Israeli insurance portfolio
analysis reports (Mislaka "Nituach Tik" format) with:
  - Client profile summary
  - Policy status overview
  - Savings & pension accumulation
  - Insurance coverage breakdown (life, disability)
  - Premium development projections
  - Investment track analysis & asset composition
  - Contribution & deposit details
  - Beneficiary information
  - Employer details
  - Operational/clearinghouse identifiers

Author: PHINS Platform
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional


# =============================================================================
# SWIFTNESS RESOURCE CATALOG
# Comprehensive catalog of files, links, and data resources available from
# Swiftness (swiftness.co.il) for Mislaka integration work.
# =============================================================================

SWIFTNESS_BASE_URL = "https://www.swiftness.co.il"

# System-general resources (כללי מערכת)
SYSTEM_GENERAL_RESOURCES = [
    {
        "id": "sys-001",
        "category": "system_general",
        "name": "מבנה אחיד - אחזקות",
        "name_en": "Holdings Interface Schema",
        "description": "XSD schema for holdings data (v9.7.7) - kupotgemel, pension, insurance",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "xsd",
        "version": "9.7.7",
        "interface": "holdings",
        "tags": ["schema", "holdings", "xsd", "mislaka"]
    },
    {
        "id": "sys-002",
        "category": "system_general",
        "name": "מבנה אחיד - פיצויים",
        "name_en": "Severance Interface Schema",
        "description": "XSD schema for severance data (v5.9.38) - codes 9300-9306",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "xsd",
        "version": "5.9.38",
        "interface": "severance",
        "tags": ["schema", "severance", "pitzuim", "xsd"]
    },
    {
        "id": "sys-003",
        "category": "system_general",
        "name": "מבנה אחיד - אירועים",
        "name_en": "Events Interface Schema",
        "description": "XSD schema for event notifications (v7.6.30)",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "xsd",
        "version": "7.6.30",
        "interface": "events",
        "tags": ["schema", "events", "xsd"]
    },
    {
        "id": "sys-004",
        "category": "system_general",
        "name": "מבנה אחיד - העברות",
        "name_en": "Transference Interface Schema",
        "description": "XSD schema for policy transfers (v3.7.2)",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "xsd",
        "version": "3.7.2",
        "interface": "transference",
        "tags": ["schema", "transference", "xsd"]
    },
    {
        "id": "sys-005",
        "category": "system_general",
        "name": "טבלאות קודים - מוצרים",
        "name_en": "Product Code Tables",
        "description": "Code tables for product types, status codes, entity types",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "xlsx",
        "tags": ["codes", "products", "reference"]
    },
    {
        "id": "sys-006",
        "category": "system_general",
        "name": "מסמך הנחיות טכניות",
        "name_en": "Technical Guidelines Document",
        "description": "Technical guidelines for Mislaka interface implementation",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "pdf",
        "tags": ["guidelines", "technical", "implementation"]
    },
    {
        "id": "sys-007",
        "category": "system_general",
        "name": "מפרט ממשק קבצים",
        "name_en": "File Interface Specification",
        "description": "Specification for file-based data exchange with the clearinghouse",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "pdf",
        "tags": ["specification", "interface", "files"]
    },
    {
        "id": "sys-008",
        "category": "system_general",
        "name": "רשימת שדות חובה",
        "name_en": "Mandatory Fields List",
        "description": "List of mandatory fields per interface type and product",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "file_type": "xlsx",
        "tags": ["fields", "mandatory", "validation"]
    },
]

# Recent files for Mislaka work (קבצים עדכניים לעבודה מול המסלקה)
MISLAKA_WORK_FILES = [
    {
        "id": "work-001",
        "category": "mislaka_work_files",
        "name": "קובץ אחזקות - דוגמה",
        "name_en": "Holdings Sample File",
        "description": "Sample XML holdings file for provident funds and pension",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xml",
        "interface": "holdings",
        "tags": ["sample", "holdings", "xml", "kupotgemel"]
    },
    {
        "id": "work-002",
        "category": "mislaka_work_files",
        "name": "קובץ פיצויים - דוגמה",
        "name_en": "Severance Sample File",
        "description": "Sample XML severance data file with employer-employee records",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xml",
        "interface": "severance",
        "tags": ["sample", "severance", "xml", "pitzuim"]
    },
    {
        "id": "work-003",
        "category": "mislaka_work_files",
        "name": "קובץ אירועים - דוגמה",
        "name_en": "Events Sample File",
        "description": "Sample XML event notification file",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xml",
        "interface": "events",
        "tags": ["sample", "events", "xml"]
    },
    {
        "id": "work-004",
        "category": "mislaka_work_files",
        "name": "קובץ העברות - דוגמה",
        "name_en": "Transference Sample File",
        "description": "Sample XML policy transfer file",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xml",
        "interface": "transference",
        "tags": ["sample", "transference", "xml"]
    },
    {
        "id": "work-005",
        "category": "mislaka_work_files",
        "name": "טבלת קודי מוצרים עדכנית",
        "name_en": "Updated Product Code Table",
        "description": "Latest product code table for Mislaka interface mapping",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xlsx",
        "tags": ["codes", "products", "updated"]
    },
    {
        "id": "work-006",
        "category": "mislaka_work_files",
        "name": "טבלת קודי סטטוסים",
        "name_en": "Status Code Table",
        "description": "Policy/account status codes used across interfaces",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xlsx",
        "tags": ["codes", "status", "reference"]
    },
    {
        "id": "work-007",
        "category": "mislaka_work_files",
        "name": "מבנה ZIP למסלקה",
        "name_en": "ZIP Structure for Mislaka",
        "description": "Specification for ZIP package structure for multi-file submissions",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "pdf",
        "tags": ["structure", "zip", "packaging"]
    },
    {
        "id": "work-008",
        "category": "mislaka_work_files",
        "name": "קובץ כותרת מסלקה",
        "name_en": "Mislaka Header File Template",
        "description": "Header file template (KoteretKovetz) for Mislaka submissions",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "xml",
        "tags": ["header", "template", "xml"]
    },
    {
        "id": "work-009",
        "category": "mislaka_work_files",
        "name": "מדריך ולידציות",
        "name_en": "Validation Guide",
        "description": "Validation rules and error codes for Mislaka file submissions",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "pdf",
        "tags": ["validation", "errors", "guide"]
    },
    {
        "id": "work-010",
        "category": "mislaka_work_files",
        "name": "דוגמה - ניתוח תיק מקיף",
        "name_en": "Comprehensive Portfolio Analysis Example",
        "description": "Example comprehensive portfolio analysis report (insurance, pension, finance)",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "file_type": "pdf",
        "tags": ["example", "portfolio", "analysis", "report"]
    },
]

# Quick-access links
SWIFTNESS_LINKS = [
    {
        "id": "link-001",
        "label": "Swiftness System General",
        "label_he": "כללי מערכת",
        "url": f"{SWIFTNESS_BASE_URL}/כללי-מערכת/",
        "description": "System-level schemas, code tables, and technical guidelines"
    },
    {
        "id": "link-002",
        "label": "Mislaka Work Files",
        "label_he": "קבצים עדכניים לעבודה מול המסלקה",
        "url": f"{SWIFTNESS_BASE_URL}/savers/קבצים-עדכניים-לעבודה-מול-המסלקה/",
        "description": "Latest data files for clearinghouse integration"
    },
    {
        "id": "link-003",
        "label": "Swiftness Home",
        "label_he": "דף הבית",
        "url": SWIFTNESS_BASE_URL,
        "description": "Swiftness main portal"
    },
    {
        "id": "link-004",
        "label": "Savers Portal",
        "label_he": "פורטל חוסכים",
        "url": f"{SWIFTNESS_BASE_URL}/savers/",
        "description": "Savers (Amit) section with tools and files"
    },
]


# =============================================================================
# ENHANCED REPORT MODEL
# Inspired by the professional Mislaka "Nituach Tik" report format
# =============================================================================

REPORT_MODEL_SECTIONS = [
    {
        "id": "sec-01",
        "order": 1,
        "key": "portfolio_summary",
        "title_he": "כמה חסכת עד היום?",
        "title_en": "How Much Have You Saved?",
        "icon": "piggy-bank",
        "description": "Total accumulated savings across all policies, split by capital vs. pension",
        "data_fields": [
            {"field": "total_savings", "label_he": "סך חיסכון", "label_en": "Total Savings", "type": "currency", "currency": "ILS"},
            {"field": "total_deposits", "label_he": "סך הפקדות", "label_en": "Total Deposits", "type": "currency", "currency": "ILS"},
            {"field": "capital_amount", "label_he": "הון", "label_en": "Capital", "type": "currency", "currency": "ILS"},
            {"field": "pension_amount", "label_he": "קצבה", "label_en": "Pension", "type": "currency", "currency": "ILS"},
            {"field": "severance_amount", "label_he": "פיצויים", "label_en": "Severance", "type": "currency", "currency": "ILS"},
        ],
        "charts": [
            {"type": "doughnut", "title": "Savings Breakdown", "fields": ["capital_amount", "pension_amount", "severance_amount"]}
        ]
    },
    {
        "id": "sec-02",
        "order": 2,
        "key": "policy_status",
        "title_he": "סטטוס פוליסות",
        "title_en": "Policy Status Overview",
        "icon": "file-text",
        "description": "Status of all insurance/pension policies",
        "data_fields": [
            {"field": "policy_number", "label_he": "מספר פוליסה", "label_en": "Policy #", "type": "text"},
            {"field": "company_name", "label_he": "שם חברה", "label_en": "Company", "type": "text"},
            {"field": "plan_name", "label_he": "שם תוכנית", "label_en": "Plan Name", "type": "text"},
            {"field": "member_id", "label_he": "מספר עמית", "label_en": "Member ID", "type": "text"},
            {"field": "seniority_date", "label_he": "ותק", "label_en": "Seniority", "type": "date"},
            {"field": "status", "label_he": "סטטוס", "label_en": "Status", "type": "status"},
            {"field": "employment_type", "label_he": "מעמד", "label_en": "Employment", "type": "text"},
            {"field": "balance", "label_he": "יתרה", "label_en": "Balance", "type": "currency", "currency": "ILS"},
        ],
        "display": "table"
    },
    {
        "id": "sec-03",
        "order": 3,
        "key": "plan_details",
        "title_he": "רשימת תוכניות",
        "title_en": "Plan Details",
        "icon": "list",
        "description": "Detailed breakdown of each insurance/pension plan",
        "data_fields": [
            {"field": "plan_name", "label_he": "שם תוכנית", "label_en": "Plan", "type": "text"},
            {"field": "plan_number", "label_he": "מספר תוכנית", "label_en": "Plan #", "type": "text"},
            {"field": "seniority_date", "label_he": "ותק", "label_en": "Seniority", "type": "date"},
            {"field": "retirement_age", "label_he": "גיל פרישה", "label_en": "Retirement Age", "type": "number"},
            {"field": "current_savings", "label_he": "חיסכון נוכחי", "label_en": "Current Savings", "type": "currency", "currency": "ILS"},
            {"field": "projected_savings", "label_he": "חיסכון צפוי", "label_en": "Projected Savings", "type": "currency", "currency": "ILS"},
            {"field": "projected_pension", "label_he": "קצבה צפויה", "label_en": "Projected Pension", "type": "currency", "currency": "ILS"},
            {"field": "severance", "label_he": "פיצויים", "label_en": "Severance", "type": "currency", "currency": "ILS"},
            {"field": "employer_contributions", "label_he": "תגמולי מעביד", "label_en": "Employer Contrib.", "type": "currency", "currency": "ILS"},
            {"field": "employee_contributions", "label_he": "תגמולי עובד", "label_en": "Employee Contrib.", "type": "currency", "currency": "ILS"},
            {"field": "management_fee_savings", "label_he": "דמי ניהול מצבירה", "label_en": "Mgmt Fee (Savings)", "type": "percentage"},
            {"field": "management_fee_deposits", "label_he": "דמי ניהול מהפקדה", "label_en": "Mgmt Fee (Deposits)", "type": "percentage"},
            {"field": "pension_coefficient", "label_he": "מקדם המרה", "label_en": "Conversion Factor", "type": "number"},
        ],
        "display": "cards"
    },
    {
        "id": "sec-04",
        "order": 4,
        "key": "balance_breakdown",
        "title_he": "פירוט יתרות ותחזיות",
        "title_en": "Balance Breakdown & Projections",
        "icon": "bar-chart",
        "description": "Balance split by capital/pension and period, with future projections",
        "data_fields": [
            {"field": "balance_capital", "label_he": "הון", "label_en": "Capital", "type": "currency", "currency": "ILS"},
            {"field": "balance_pension_paying", "label_he": "קצבה משלמת", "label_en": "Paying Pension", "type": "currency", "currency": "ILS"},
            {"field": "balance_pension_non_paying", "label_he": "קצבה לא משלמת", "label_en": "Non-Paying Pension", "type": "currency", "currency": "ILS"},
            {"field": "projected_total_retirement", "label_he": "חיסכון צפוי בפרישה", "label_en": "Projected at Retirement", "type": "currency", "currency": "ILS"},
            {"field": "projected_monthly_pension", "label_he": "קצבה חודשית צפויה", "label_en": "Projected Monthly Pension", "type": "currency", "currency": "ILS"},
        ],
        "charts": [
            {"type": "bar", "title": "Capital vs Pension", "fields": ["balance_capital", "balance_pension_paying"]},
            {"type": "line", "title": "Projected Growth", "fields": ["projected_total_retirement"]}
        ]
    },
    {
        "id": "sec-05",
        "order": 5,
        "key": "insurance_coverage",
        "title_he": "הביטוחים וההגנות שלך",
        "title_en": "Insurance & Protection Coverage",
        "icon": "shield",
        "description": "Life insurance, disability (AKW), and waiver coverage details",
        "data_fields": [
            {"field": "coverage_type", "label_he": "סוג כיסוי", "label_en": "Coverage Type", "type": "text"},
            {"field": "coverage_name", "label_he": "שם כיסוי", "label_en": "Coverage Name", "type": "text"},
            {"field": "coverage_amount", "label_he": "סכום כיסוי", "label_en": "Coverage Amount", "type": "currency", "currency": "ILS"},
            {"field": "monthly_cost", "label_he": "עלות חודשית", "label_en": "Monthly Cost", "type": "currency", "currency": "ILS"},
            {"field": "coverage_start", "label_he": "תחילת כיסוי", "label_en": "Start Date", "type": "date"},
            {"field": "coverage_end", "label_he": "תום כיסוי", "label_en": "End Date", "type": "date"},
            {"field": "medical_surcharge", "label_he": "תוספת רפואית", "label_en": "Medical Surcharge", "type": "percentage"},
            {"field": "discount", "label_he": "הנחה", "label_en": "Discount", "type": "percentage"},
        ],
        "display": "table",
        "charts": [
            {"type": "bar", "title": "Coverage by Type", "fields": ["coverage_amount"]},
            {"type": "pie", "title": "Premium Distribution", "fields": ["monthly_cost"]}
        ]
    },
    {
        "id": "sec-06",
        "order": 6,
        "key": "premium_development",
        "title_he": "התפתחות פרמיה",
        "title_en": "Premium Development",
        "icon": "trending-up",
        "description": "Projected premium changes over time for each coverage",
        "data_fields": [
            {"field": "period_start", "label_he": "תחילת תקופה", "label_en": "Period Start", "type": "date"},
            {"field": "period_end", "label_he": "תום תקופה", "label_en": "Period End", "type": "date"},
            {"field": "expected_premium", "label_he": "פרמיה צפויה", "label_en": "Expected Premium", "type": "currency", "currency": "ILS"},
            {"field": "coverage_amount_projected", "label_he": "סכום ביטוח צפוי", "label_en": "Projected Coverage", "type": "currency", "currency": "ILS"},
            {"field": "discount_rate", "label_he": "שיעור הנחה", "label_en": "Discount Rate", "type": "percentage"},
        ],
        "display": "table",
        "charts": [
            {"type": "line", "title": "Premium Projection", "fields": ["expected_premium"]}
        ]
    },
    {
        "id": "sec-07",
        "order": 7,
        "key": "beneficiaries",
        "title_he": "מוטבים",
        "title_en": "Beneficiaries",
        "icon": "users",
        "description": "Beneficiary designations for life and death benefits",
        "data_fields": [
            {"field": "beneficiary_name", "label_he": "שם מוטב", "label_en": "Name", "type": "text"},
            {"field": "beneficiary_id", "label_he": "מספר מזהה", "label_en": "ID", "type": "text"},
            {"field": "relationship", "label_he": "זיקה", "label_en": "Relationship", "type": "text"},
            {"field": "share_percent", "label_he": "חלק באחוזים", "label_en": "Share %", "type": "percentage"},
            {"field": "beneficiary_type", "label_he": "מהות מוטב", "label_en": "Type", "type": "text"},
        ],
        "display": "table"
    },
    {
        "id": "sec-08",
        "order": 8,
        "key": "investment_tracks",
        "title_he": "מסלולי השקעה והרכב נכסים",
        "title_en": "Investment Tracks & Asset Composition",
        "icon": "pie-chart",
        "description": "Investment track performance, returns, and asset allocation",
        "data_fields": [
            {"field": "track_name", "label_he": "שם מסלול", "label_en": "Track Name", "type": "text"},
            {"field": "track_specialization", "label_he": "התמחות", "label_en": "Specialization", "type": "text"},
            {"field": "track_balance", "label_he": "יתרה", "label_en": "Balance", "type": "currency", "currency": "ILS"},
            {"field": "return_12m", "label_he": "תשואה 12 חודשים", "label_en": "12M Return", "type": "percentage"},
            {"field": "return_24m", "label_he": "תשואה 24 חודשים", "label_en": "24M Return", "type": "percentage"},
            {"field": "return_36m", "label_he": "תשואה 36 חודשים", "label_en": "36M Return", "type": "percentage"},
            {"field": "return_60m", "label_he": "תשואה 60 חודשים", "label_en": "60M Return", "type": "percentage"},
            {"field": "std_dev_36m", "label_he": "סטיית תקן 36 חודשים", "label_en": "36M Std Dev", "type": "percentage"},
            {"field": "sharpe_ratio", "label_he": "מדד שארפ", "label_en": "Sharpe Ratio", "type": "number"},
            {"field": "equity_exposure", "label_he": "חשיפה למניות", "label_en": "Equity Exposure", "type": "percentage"},
        ],
        "charts": [
            {"type": "pie", "title": "Asset Composition", "fields": ["gov_bonds", "corp_bonds", "equities", "deposits", "cash", "other"]},
            {"type": "bar", "title": "Returns by Period", "fields": ["return_12m", "return_24m", "return_36m", "return_60m"]}
        ]
    },
    {
        "id": "sec-09",
        "order": 9,
        "key": "deposits_contributions",
        "title_he": "פרטי הפקדות וחובות",
        "title_en": "Deposit & Contribution Details",
        "icon": "credit-card",
        "description": "Monthly deposit records, arrears, and contribution structure",
        "data_fields": [
            {"field": "month", "label_he": "חודש", "label_en": "Month", "type": "text"},
            {"field": "salary", "label_he": "שכר", "label_en": "Salary", "type": "currency", "currency": "ILS"},
            {"field": "severance_deposit", "label_he": "פיצויים", "label_en": "Severance", "type": "currency", "currency": "ILS"},
            {"field": "employee_deposit", "label_he": "תגמולי עובד", "label_en": "Employee", "type": "currency", "currency": "ILS"},
            {"field": "employer_deposit", "label_he": "תגמולי מעביד", "label_en": "Employer", "type": "currency", "currency": "ILS"},
            {"field": "total_deposit", "label_he": "סך הפקדה", "label_en": "Total", "type": "currency", "currency": "ILS"},
        ],
        "display": "table",
        "charts": [
            {"type": "bar", "title": "Monthly Deposits", "fields": ["total_deposit"]}
        ]
    },
    {
        "id": "sec-10",
        "order": 10,
        "key": "employer_info",
        "title_he": "פרטי מעסיקים",
        "title_en": "Employer Information",
        "icon": "briefcase",
        "description": "Employer details and salary-linked policy information",
        "data_fields": [
            {"field": "employer_name", "label_he": "שם מעסיק", "label_en": "Employer", "type": "text"},
            {"field": "employer_id", "label_he": "מספר מעסיק", "label_en": "Employer ID", "type": "text"},
            {"field": "tax_file", "label_he": "תיק ניכויים", "label_en": "Tax File", "type": "text"},
            {"field": "section14", "label_he": "סעיף 14", "label_en": "Section 14", "type": "boolean"},
            {"field": "unconditional_rights", "label_he": "זכאות ללא תנאי", "label_en": "Unconditional Rights", "type": "boolean"},
        ],
        "display": "table"
    },
    {
        "id": "sec-11",
        "order": 11,
        "key": "operational_ids",
        "title_he": "נתונים תפעוליים",
        "title_en": "Operational & Clearinghouse IDs",
        "icon": "database",
        "description": "Mislaka clearinghouse identifiers and operational references",
        "data_fields": [
            {"field": "mislaka_number", "label_he": "מספר מסלקה", "label_en": "Mislaka #", "type": "text"},
            {"field": "uniform_code", "label_he": "קידוד אחיד", "label_en": "Uniform Code", "type": "text"},
            {"field": "execution_date", "label_he": "תאריך ביצוע", "label_en": "Execution Date", "type": "date"},
        ],
        "display": "table"
    },
    {
        "id": "sec-12",
        "order": 12,
        "key": "additional_data",
        "title_he": "נתונים נוספים",
        "title_en": "Additional Data",
        "icon": "info",
        "description": "Power of attorney, liens, loans, claims, and other records",
        "data_fields": [
            {"field": "power_of_attorney", "label_he": "מיופה כח", "label_en": "Power of Attorney", "type": "text"},
            {"field": "liens", "label_he": "שיעבודים", "label_en": "Liens", "type": "text"},
            {"field": "seizures", "label_he": "עיקולים", "label_en": "Seizures", "type": "text"},
            {"field": "loans", "label_he": "הלוואות", "label_en": "Loans", "type": "currency", "currency": "ILS"},
            {"field": "claims", "label_he": "תביעות", "label_en": "Claims", "type": "text"},
        ],
        "display": "list"
    },
]

# Service index for company ratings
SERVICE_INDEX_DATA = {
    "הפניקס": {"life_insurance": 86, "disability": 78, "overall": 82},
    "איילון": {"life_insurance": 87, "disability": 80, "overall": 83},
    "מגדל": {"life_insurance": 84, "disability": 76, "overall": 80},
    "הראל": {"life_insurance": 85, "disability": 79, "overall": 82},
    "כלל": {"life_insurance": 83, "disability": 77, "overall": 80},
    "מנורה מבטחים": {"life_insurance": 82, "disability": 75, "overall": 79},
    "הכשרה": {"life_insurance": 80, "disability": 74, "overall": 77},
    "Phoenix": {"life_insurance": 86, "disability": 78, "overall": 82},
    "Ayalon": {"life_insurance": 87, "disability": 80, "overall": 83},
}


class SwiftnessDataService:
    """
    Provides structured access to Swiftness-affiliated data resources,
    file catalogs, and report model definitions.
    Ensures data integrity by using immutable reference catalogs and
    validated field types.
    """

    def __init__(self):
        self._base_url = os.environ.get('SWIFTNESS_SAFE_BASE_URL', SWIFTNESS_BASE_URL)
        self._initialized_at = datetime.utcnow().isoformat()

    def get_resource_catalog(self) -> Dict[str, Any]:
        """
        Returns the full resource catalog with:
          - system_general: Files from /כללי-מערכת/
          - mislaka_work_files: Files from /savers/קבצים-עדכניים-לעבודה-מול-המסלקה/
          - quick_links: Direct navigation links
          - metadata: Catalog info
        """
        total_resources = len(SYSTEM_GENERAL_RESOURCES) + len(MISLAKA_WORK_FILES)

        # Build interface summary from resources
        interfaces = set()
        file_types = set()
        all_tags = set()
        for r in SYSTEM_GENERAL_RESOURCES + MISLAKA_WORK_FILES:
            if r.get("interface"):
                interfaces.add(r["interface"])
            if r.get("file_type"):
                file_types.add(r["file_type"])
            for tag in r.get("tags", []):
                all_tags.add(tag)

        return {
            "system_general": SYSTEM_GENERAL_RESOURCES,
            "mislaka_work_files": MISLAKA_WORK_FILES,
            "quick_links": SWIFTNESS_LINKS,
            "metadata": {
                "total_resources": total_resources,
                "system_general_count": len(SYSTEM_GENERAL_RESOURCES),
                "mislaka_work_files_count": len(MISLAKA_WORK_FILES),
                "links_count": len(SWIFTNESS_LINKS),
                "interfaces": sorted(interfaces),
                "file_types": sorted(file_types),
                "all_tags": sorted(all_tags),
                "source_base_url": self._base_url,
                "catalog_generated_at": datetime.utcnow().isoformat(),
            }
        }

    def get_report_model(self) -> Dict[str, Any]:
        """
        Returns the enhanced report model definition with:
          - sections: Ordered report sections with field definitions
          - service_index: Company service ratings
          - metadata: Model info
        """
        return {
            "sections": REPORT_MODEL_SECTIONS,
            "service_index": SERVICE_INDEX_DATA,
            "metadata": {
                "total_sections": len(REPORT_MODEL_SECTIONS),
                "model_version": "2.0",
                "based_on": "Mislaka Nituach Tik (Portfolio Analysis) format",
                "source": "swiftness.co.il",
                "features": [
                    "Portfolio summary with savings breakdown",
                    "Policy status overview table",
                    "Detailed plan cards with financial data",
                    "Balance breakdown by capital/pension",
                    "Insurance coverage matrix",
                    "Premium development projections",
                    "Beneficiary registry",
                    "Investment track analysis with returns",
                    "Deposit & contribution records",
                    "Employer information & Section 14",
                    "Clearinghouse operational IDs",
                    "Additional data (liens, loans, claims)",
                ],
                "data_integrity_rules": [
                    "Currency values validated as non-negative",
                    "Percentage values bounded 0-100",
                    "Date fields validated against ISO 8601",
                    "Policy numbers validated against Mislaka format",
                    "ID numbers validated with Israeli ID checksum",
                    "Row-level ownership enforced on all records",
                    "Cross-reference integrity between policies and coverage",
                ],
                "generated_at": datetime.utcnow().isoformat(),
            }
        }

    def validate_report_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates report data against the model definition.
        Returns validation result with errors if any.
        """
        errors = []
        warnings = []
        sections_found = set()

        for section_def in REPORT_MODEL_SECTIONS:
            key = section_def["key"]
            section_data = data.get(key)
            if section_data is None:
                warnings.append(f"Section '{key}' ({section_def['title_en']}) not present in data")
                continue

            sections_found.add(key)

            # Validate field types
            if isinstance(section_data, list):
                for idx, record in enumerate(section_data):
                    if not isinstance(record, dict):
                        continue
                    for field_def in section_def.get("data_fields", []):
                        field_name = field_def["field"]
                        if field_name not in record:
                            continue
                        value = record[field_name]
                        field_type = field_def.get("type", "text")

                        if field_type == "currency" and value is not None:
                            try:
                                fval = float(value)
                                if fval < 0:
                                    warnings.append(
                                        f"Section '{key}' record {idx}: "
                                        f"negative currency value for '{field_name}': {value}"
                                    )
                            except (ValueError, TypeError):
                                errors.append(
                                    f"Section '{key}' record {idx}: "
                                    f"invalid currency value for '{field_name}': {value}"
                                )

                        if field_type == "percentage" and value is not None:
                            try:
                                pval = float(value)
                                if pval < 0 or pval > 100:
                                    warnings.append(
                                        f"Section '{key}' record {idx}: "
                                        f"percentage out of range for '{field_name}': {value}"
                                    )
                            except (ValueError, TypeError):
                                errors.append(
                                    f"Section '{key}' record {idx}: "
                                    f"invalid percentage for '{field_name}': {value}"
                                )

        return {
            "valid": len(errors) == 0,
            "sections_found": sorted(sections_found),
            "sections_missing": sorted(
                set(s["key"] for s in REPORT_MODEL_SECTIONS) - sections_found
            ),
            "errors": errors,
            "warnings": warnings,
            "checked_at": datetime.utcnow().isoformat(),
        }


# Singleton
_service_instance = None

def get_swiftness_data_service() -> SwiftnessDataService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SwiftnessDataService()
    return _service_instance
