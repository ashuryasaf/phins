"""Risk Reports rendering layer (B9).

Report sections (data content, pension, affiliated savings/cover/ID,
Swiftness resources, Hebrew insurance), affiliation metadata and
recommendations. Text-only; charts live in :mod:`services.risk_reports.charts`.
"""

import re
from typing import Any, Dict, List, Optional
from services.risk_reports.models import (
    AnalysisResult, DataType, Factor, Priority, Recommendation, ReportSection, Severity,
)


class RenderMixin:
    """Section and recommendation builders."""

    def _generate_sections(self, analysis: AnalysisResult, lang: str, 
                          doc_data: Dict[str, Any] = None,
                          pension_data: Dict[str, Any] = None,
                          pension_report: str = None,
                          savings_cover_id_summary: Dict[str, Any] = None) -> List[ReportSection]:
        """Generate comprehensive report sections with AI/BI insights and actual data content"""
        sections = []
        is_hebrew = lang == 'hebrew'
        
        # 1. Executive Summary
        sections.append(ReportSection(
            title='תקציר מנהלים' if is_hebrew else 'Executive Summary',
            content=analysis.summary,
            order=1
        ))
        
        # 2. PENSION DATA SECTION - Display pension report from PensionDataAgent
        if pension_data or pension_report:
            pension_section = self._generate_pension_section(pension_data, pension_report, is_hebrew)
            if pension_section:
                sections.append(ReportSection(
                    title='דו״ח ניתוח פנסיה וביטוח' if is_hebrew else 'Pension & Insurance Analysis Report',
                    content=pension_section,
                    order=2
                ))
            sections.extend(self._build_pension_affiliated_sections(pension_data, is_hebrew))
        
        # 3. ACTUAL DATA CONTENT SECTION - Show extracted data from the files
        if doc_data:
            data_content_section = self._generate_data_content_section(doc_data, analysis, is_hebrew)
            if data_content_section:
                sections.append(ReportSection(
                    title='תוכן הנתונים שהועלו' if is_hebrew else 'Uploaded Data Content',
                    content=data_content_section,
                    order=3
                ))

        # 3.5 Savings/Cover/ID affiliation section (table-oriented summary)
        if savings_cover_id_summary is None:
            savings_cover_id_summary = self._extract_savings_cover_id_summary(doc_data, pension_data)
        affiliated_summary_section = self._build_savings_cover_id_section(
            savings_cover_id_summary,
            is_hebrew,
            assessment_only=bool(pension_data or pension_report),
        )
        if affiliated_summary_section:
            sections.append(affiliated_summary_section)
        
        # 3. Hebrew Insurance Details (if extracted)
        hebrew_factors = [f for f in analysis.extracted_factors if f.category == 'hebrew_insurance']
        if hebrew_factors:
            hebrew_content = self._generate_hebrew_insurance_section(hebrew_factors, is_hebrew)
            sections.append(ReportSection(
                title='פרטי פוליסת ביטוח' if is_hebrew else 'Insurance Policy Details',
                content=hebrew_content,
                order=3
            ))
        
        is_pension_assessment = bool(pension_data or pension_report)
        completeness = analysis.key_metrics.get('data_completeness', 100)

        # Statistical filler (Data Profile, correlations, patterns, generic
        # key-metrics) is not the Mislaka assessment itself. Skip it so the
        # report — and the downloadable PDF — stay on identity, accounts,
        # סה״כ צבירה and פיצויים.
        if not is_pension_assessment:
            # 4. Data Profile Overview
            total_records = analysis.key_metrics.get('total_records', 0)
            numeric_cols = analysis.key_metrics.get('numeric_columns', 0)
            cat_cols = analysis.key_metrics.get('categorical_columns', 0)

            if is_hebrew:
                profile_content = f"""📊 פרופיל הנתונים:

• סה"כ רשומות: {total_records}
• שדות מספריים: {numeric_cols}
• שדות קטגוריים: {cat_cols}
• שלמות נתונים: {completeness}%
• סוג נתונים: {analysis.data_classification.value}
• שפה: {analysis.language_name}
• רמת ביטחון: {analysis.confidence:.0%}"""
            else:
                profile_content = f"""📊 Data Profile:

• Total Records: {total_records}
• Numeric Fields: {numeric_cols}
• Categorical Fields: {cat_cols}
• Data Completeness: {completeness}%
• Data Type: {analysis.data_classification.value}
• Language: {analysis.language_name}
• Confidence Level: {analysis.confidence:.0%}"""

            sections.append(ReportSection(
                title='פרופיל נתונים' if is_hebrew else 'Data Profile',
                content=profile_content,
                order=2
            ))

        # 3. Statistical Analysis (BI Metrics)
        # SKIP for pension data - the pension report already shows meaningful data clearly
        # Statistical analysis of IDs/policy numbers is meaningless
        if not is_pension_assessment:  # Only show statistical analysis for non-pension data
            stat_factors = [f for f in analysis.extracted_factors if f.category == 'statistical']
            if stat_factors:
                if is_hebrew:
                    stats_lines = ['📈 ניתוח סטטיסטי מפורט:\n']
                    for f in stat_factors[:8]:
                        if isinstance(f.value, dict):
                            stats_lines.append(f"🔹 {f.name}:")
                            stats_lines.append(f"   • ממוצע: {f.value.get('mean', 'N/A')}")
                            stats_lines.append(f"   • חציון: {f.value.get('median', 'N/A')}")
                            stats_lines.append(f"   • טווח: {f.value.get('range', 'N/A')}")
                            stats_lines.append(f"   • סטיית תקן: {f.value.get('std_dev', 'N/A')}")
                            stats_lines.append(f"   • התפלגות: {f.value.get('distribution', 'N/A')}")
                            stats_lines.append("")
                else:
                    stats_lines = ['📈 Detailed Statistical Analysis:\n']
                    for f in stat_factors[:8]:
                        if isinstance(f.value, dict):
                            stats_lines.append(f"🔹 {f.name}:")
                            stats_lines.append(f"   • Mean: {f.value.get('mean', 'N/A')}")
                            stats_lines.append(f"   • Median: {f.value.get('median', 'N/A')}")
                            stats_lines.append(f"   • Range: {f.value.get('range', 'N/A')}")
                            stats_lines.append(f"   • Std Dev: {f.value.get('std_dev', 'N/A')}")
                            stats_lines.append(f"   • Distribution: {f.value.get('distribution', 'N/A')}")
                            stats_lines.append("")
                
                sections.append(ReportSection(
                    title='ניתוח סטטיסטי' if is_hebrew else 'Statistical Analysis',
                    content='\n'.join(stats_lines),
                    order=3
                ))
        
        # 4. Correlation Insights — skip for Mislaka (not assessment data)
        top_corr = analysis.key_metrics.get('top_correlation')
        if top_corr and not is_pension_assessment:
            if is_hebrew:
                corr_content = f"""🔗 מתאמים שזוהו:

• הקשר החזק ביותר: {top_corr.get('fields', '')}
• עוצמת המתאם: {top_corr.get('strength', 0)}

💡 משמעות: מתאמים אלו מצביעים על קשרים פוטנציאליים בין משתנים שיש לקחת בחשבון בניתוח."""
            else:
                corr_content = f"""🔗 Correlations Discovered:

• Strongest Relationship: {top_corr.get('fields', '')}
• Correlation Strength: {top_corr.get('strength', 0)}

💡 Significance: These correlations indicate potential relationships between variables that should be considered in the analysis."""
            
            sections.append(ReportSection(
                title='ניתוח מתאמים' if is_hebrew else 'Correlation Analysis',
                content=corr_content,
                order=4
            ))
        
        # 5. Patterns & Trends — skip for Mislaka (not assessment data)
        if analysis.patterns_found and not is_pension_assessment:
            if is_hebrew:
                patterns_lines = ['🔍 דפוסים ומגמות שזוהו:\n']
                for i, p in enumerate(analysis.patterns_found, 1):
                    patterns_lines.append(f"{i}. [{p.type}] {p.description}")
                    patterns_lines.append(f"   משמעות: {p.significance:.0%}")
                    patterns_lines.append("")
            else:
                patterns_lines = ['🔍 Identified Patterns & Trends:\n']
                for i, p in enumerate(analysis.patterns_found, 1):
                    patterns_lines.append(f"{i}. [{p.type}] {p.description}")
                    patterns_lines.append(f"   Significance: {p.significance:.0%}")
                    patterns_lines.append("")
            
            sections.append(ReportSection(
                title='דפוסים ומגמות' if is_hebrew else 'Patterns & Trends',
                content='\n'.join(patterns_lines),
                order=5
            ))
        
        # 6. Anomalies & Warnings
        if analysis.anomalies:
            if is_hebrew:
                anomaly_lines = ['⚠️ חריגות ואזהרות:\n']
                severity_map = {'critical': '🔴 קריטי', 'high': '🟠 גבוה', 'medium': '🟡 בינוני', 'low': '🟢 נמוך'}
                for a in analysis.anomalies:
                    sev_label = severity_map.get(a.severity.value, a.severity.value)
                    anomaly_lines.append(f"• {sev_label}: {a.description}")
                    anomaly_lines.append(f"  📋 המלצה: {a.recommendation}")
                    anomaly_lines.append("")
            else:
                anomaly_lines = ['⚠️ Anomalies & Warnings:\n']
                severity_map = {'critical': '🔴 Critical', 'high': '🟠 High', 'medium': '🟡 Medium', 'low': '🟢 Low'}
                for a in analysis.anomalies:
                    sev_label = severity_map.get(a.severity.value, a.severity.value)
                    anomaly_lines.append(f"• {sev_label}: {a.description}")
                    anomaly_lines.append(f"  📋 Recommendation: {a.recommendation}")
                    anomaly_lines.append("")
            
            sections.append(ReportSection(
                title='חריגות ואזהרות' if is_hebrew else 'Anomalies & Warnings',
                content='\n'.join(anomaly_lines),
                order=6
            ))
        
        # 7. Risk Assessment / Key Metrics — statistical scores, not the
        # Mislaka assessment. Keep anomalies (identity / integrity).
        if is_pension_assessment:
            return sections

        # 7. Risk Assessment
        risk_score = analysis.risk_score
        if risk_score < 30:
            risk_level = 'נמוך' if is_hebrew else 'Low'
            risk_color = '🟢'
            risk_desc = 'הנתונים מצביעים על רמת סיכון נמוכה' if is_hebrew else 'Data indicates low risk level'
        elif risk_score < 60:
            risk_level = 'בינוני' if is_hebrew else 'Medium'
            risk_color = '🟡'
            risk_desc = 'יש לשים לב לגורמי סיכון מסוימים' if is_hebrew else 'Some risk factors require attention'
        else:
            risk_level = 'גבוה' if is_hebrew else 'High'
            risk_color = '🔴'
            risk_desc = 'נדרשת בדיקה מעמיקה של גורמי הסיכון' if is_hebrew else 'In-depth review of risk factors required'
        
        if is_hebrew:
            risk_content = f"""🎯 הערכת סיכון כוללת:

{risk_color} ציון סיכון: {risk_score:.0f}/100
📊 רמת סיכון: {risk_level}

{risk_desc}

גורמים המשפיעים על הציון:
• מספר חריגות: {len(analysis.anomalies)}
• דפוסים חריגים: {len([p for p in analysis.patterns_found if p.significance > 0.5])}
• שלמות נתונים: {completeness}%"""
        else:
            risk_content = f"""🎯 Overall Risk Assessment:

{risk_color} Risk Score: {risk_score:.0f}/100
📊 Risk Level: {risk_level}

{risk_desc}

Factors Affecting Score:
• Number of anomalies: {len(analysis.anomalies)}
• Unusual patterns: {len([p for p in analysis.patterns_found if p.significance > 0.5])}
• Data completeness: {completeness}%"""
        
        sections.append(ReportSection(
            title='הערכת סיכון' if is_hebrew else 'Risk Assessment',
            content=risk_content,
            order=7
        ))
        
        # 8. Key Metrics Table
        metrics_items = []
        for k, v in list(analysis.key_metrics.items())[:15]:
            if not k.startswith('domain_') and k != 'top_correlation':
                if isinstance(v, float):
                    metrics_items.append(f"• {k}: {v:.2f}")
                else:
                    metrics_items.append(f"• {k}: {v}")
        
        sections.append(ReportSection(
            title='מדדים מרכזיים' if is_hebrew else 'Key Metrics',
            content='\n'.join(metrics_items),
            data_table=analysis.key_metrics,
            order=8
        ))

        # 9. Affiliation Snapshot (Mislaka schema codes)
        affiliation_section = self._build_affiliation_mapping_section(is_hebrew)
        if affiliation_section:
            sections.append(affiliation_section)
        
        return sections

    def _build_affiliation_snapshot_metadata(self) -> Dict[str, Any]:
        """Build compact affiliation metadata without mutating source mappings."""
        try:
            from services.pension_data_agent import MislakaSchemaMapping

            return {
                'interface_codes': len(MislakaSchemaMapping.INTERFACE_CODES),
                'product_types': len(MislakaSchemaMapping.PRODUCT_TYPE_CODES),
                'entity_types': len(MislakaSchemaMapping.ENTITY_TYPE_CODES),
                'status_codes': len(MislakaSchemaMapping.STATUS_CODES),
                'id_types': len(MislakaSchemaMapping.ID_TYPE_CODES),
                'environment_codes': len(MislakaSchemaMapping.ENVIRONMENT_CODES),
            }
        except Exception:
            return {}

    def _get_report_model_metadata(self) -> Optional[Dict[str, Any]]:
        """Include the Swiftness report model section keys for frontend structuring."""
        try:
            from services.swiftness_data_service import get_swiftness_data_service
            svc = get_swiftness_data_service()
            model = svc.get_report_model()
            return {
                'section_keys': [s['key'] for s in model.get('sections', [])],
                'model_version': model.get('metadata', {}).get('model_version'),
                'total_sections': model.get('metadata', {}).get('total_sections'),
            }
        except Exception:
            return None

    def _build_pension_affiliated_sections(self, pension_data: Dict[str, Any], is_hebrew: bool) -> List[ReportSection]:
        """Build table-oriented sections aligned with the Nituach Tik report model."""
        sections: List[ReportSection] = []
        if not pension_data:
            return sections

        accounts = pension_data.get('accounts', []) or []
        contributions = pension_data.get('contributions', []) or []
        totals = pension_data.get('totals', {}) or {}
        employers = pension_data.get('employers', []) or []
        client = pension_data.get('client', {}) or {}
        if isinstance(client, list):
            client = client[0] if client else {}
        if isinstance(client, dict) and client:
            client = self._normalize_client_profile_fields(client)
            profile_rows = [{
                'שם מלא' if is_hebrew else 'Full Name': client.get('full_name', client.get('client_name', '')),
                'מזהה לקוח' if is_hebrew else 'Customer ID': client.get('id_number', ''),
                'תאריך לידה' if is_hebrew else 'Birth Date': client.get('birth_date', ''),
                'פורמט גולמי' if is_hebrew else 'Birth Date Raw': client.get('birth_date_raw', ''),
                'אימות מזהה' if is_hebrew else 'ID Validation': (
                    'תקין' if client.get('id_israeli_valid') else 'דורש בדיקה'
                ) if is_hebrew else (
                    'Valid' if client.get('id_israeli_valid') else 'Needs review'
                ),
            }]
            sections.append(ReportSection(
                title='פרופיל לקוח (שיוך)' if is_hebrew else 'Customer Profile (Affiliated)',
                content='פרטי לקוח מאומתים מתוך קבצים מסונפים.' if is_hebrew else 'Customer identity fields validated from affiliated files.',
                data_table={
                    'columns': list(profile_rows[0].keys()),
                    'rows': profile_rows
                },
                order=2
            ))

        if accounts:
            status_rows = []
            for acct in accounts[:80]:
                status_rows.append({
                    'מספר פוליסה' if is_hebrew else 'Policy Number': acct.get('policy_number', ''),
                    'יצרן' if is_hebrew else 'Provider': acct.get('provider', ''),
                    'סוג מוצר' if is_hebrew else 'Product Type': acct.get('product_type_name', acct.get('product_type', '')),
                    'סטטוס' if is_hebrew else 'Status': acct.get('status', acct.get('status_en', '')),
                    'יתרה כוללת' if is_hebrew else 'Total Balance': acct.get('total_balance', 0),
                    'פיצויים' if is_hebrew else 'Severance': acct.get('severance_balance', 0),
                    'מעסיק' if is_hebrew else 'Employer': acct.get('employer_name', ''),
                    'סעיף 14' if is_hebrew else 'Section 14': ('כן' if acct.get('section14') else 'לא') if is_hebrew else ('Yes' if acct.get('section14') else 'No'),
                })

            sections.append(ReportSection(
                title='סטטוס פוליסות (טבלת שיוכים)' if is_hebrew else 'Policy Status (Affiliation Table)',
                content='מבט טבלאי על פוליסות לפי שיוכי מסלקה.' if is_hebrew else 'Table view of policies by Mislaka affiliation mappings.',
                data_table={
                    'columns': list(status_rows[0].keys()) if status_rows else [],
                    'rows': status_rows
                },
                order=3
            ))

            plan_rows = []
            for acct in accounts[:80]:
                plan_rows.append({
                    'מספר פוליסה' if is_hebrew else 'Policy Number': acct.get('policy_number', ''),
                    'תאריך תחילה' if is_hebrew else 'Start Date': acct.get('start_date', ''),
                    'דמי ניהול מצבירה %' if is_hebrew else 'Mgmt Fee Savings %': acct.get('management_fee_savings', 0),
                    'דמי ניהול מהפקדה %' if is_hebrew else 'Mgmt Fee Deposits %': acct.get('management_fee_deposits', 0),
                    'כיסוי חיים' if is_hebrew else 'Life Coverage': acct.get('death_coverage', 0),
                    'כיסוי אכ"ע' if is_hebrew else 'Disability Coverage': acct.get('disability_coverage', 0),
                    'תגמולים' if is_hebrew else 'Savings': acct.get('savings_balance', 0),
                    'פיצויים' if is_hebrew else 'Severance': acct.get('severance_balance', 0),
                })

            sections.append(ReportSection(
                title='רשימת תוכניות (פירוט טבלאי)' if is_hebrew else 'Plan Details (Tabular)',
                content='פירוט תוכניות לפי מודל הדוח המסונף.' if is_hebrew else 'Detailed plan view aligned with the affiliated report model.',
                data_table={
                    'columns': list(plan_rows[0].keys()) if plan_rows else [],
                    'rows': plan_rows
                },
                order=4
            ))

        if contributions:
            contribution_rows = []
            for contrib in contributions[:120]:
                contribution_rows.append({
                    'תקופה' if is_hebrew else 'Period': contrib.get('period', ''),
                    'מעסיק' if is_hebrew else 'Employer': contrib.get('employer_name', ''),
                    'הפקדת עובד' if is_hebrew else 'Employee Amount': contrib.get('employee_amount', 0),
                    'הפקדת מעסיק' if is_hebrew else 'Employer Amount': contrib.get('employer_amount', 0),
                    'פיצויים' if is_hebrew else 'Severance': contrib.get('severance_amount', 0),
                    'סה״כ' if is_hebrew else 'Total': contrib.get('total_amount', 0),
                })

            sections.append(ReportSection(
                title='פירוט הפקדות וחובות' if is_hebrew else 'Contribution Details',
                content='רצף הפקדות לפי תקופה לצורכי בקרה ותאימות.' if is_hebrew else 'Period-level contribution trail for control and reconciliation.',
                data_table={
                    'columns': list(contribution_rows[0].keys()) if contribution_rows else [],
                    'rows': contribution_rows
                },
                order=5
            ))

        if employers or accounts:
            employer_values = []
            seen = set()
            for acct in accounts:
                emp_name = (acct.get('employer_name') or '').strip()
                if emp_name and emp_name not in seen:
                    seen.add(emp_name)
                    employer_values.append({
                        'שם מעסיק' if is_hebrew else 'Employer Name': emp_name,
                        'מספר מעסיק' if is_hebrew else 'Employer ID': acct.get('employer_id', ''),
                        'סעיף 14' if is_hebrew else 'Section 14': ('כן' if acct.get('section14') else 'לא') if is_hebrew else ('Yes' if acct.get('section14') else 'No'),
                    })
            for emp in employers:
                emp_name = (emp.get('name') or '').strip() if isinstance(emp, dict) else str(emp).strip()
                if emp_name and emp_name not in seen:
                    seen.add(emp_name)
                    employer_values.append({
                        'שם מעסיק' if is_hebrew else 'Employer Name': emp_name,
                        'מספר מעסיק' if is_hebrew else 'Employer ID': emp.get('id', '') if isinstance(emp, dict) else '',
                        'סעיף 14' if is_hebrew else 'Section 14': '',
                    })

            if employer_values:
                sections.append(ReportSection(
                    title='פרטי מעסיקים' if is_hebrew else 'Employer Information',
                    content='שיוך מעסיקים לחשבונות ולזכויות.' if is_hebrew else 'Employer affiliation to accounts and severance rights.',
                    data_table={
                        'columns': list(employer_values[0].keys()),
                        'rows': employer_values[:80]
                    },
                    order=6
                ))

        if totals:
            totals_rows = [{
                'שדה' if is_hebrew else 'Metric': 'סה״כ צבירה' if is_hebrew else 'Total Balance',
                'ערך' if is_hebrew else 'Value': totals.get('total_balance', 0)
            }, {
                'שדה' if is_hebrew else 'Metric': 'סה״כ חסכונות' if is_hebrew else 'Total Savings',
                'ערך' if is_hebrew else 'Value': totals.get('total_savings', totals.get('total_savings_balance', 0))
            }, {
                'שדה' if is_hebrew else 'Metric': 'סה״כ פיצויים' if is_hebrew else 'Total Severance',
                'ערך' if is_hebrew else 'Value': totals.get('total_severance', totals.get('total_severance_balance', 0))
            }, {
                'שדה' if is_hebrew else 'Metric': 'מספר פוליסות' if is_hebrew else 'Policy Count',
                'ערך' if is_hebrew else 'Value': totals.get('account_count', len(accounts))
            }]

            sections.append(ReportSection(
                title='סיכום כספי (מודל דוח)' if is_hebrew else 'Financial Summary (Model-Aligned)',
                content='תקציר כספי לצורך השוואה מול מודל הדוח המסונף.' if is_hebrew else 'Financial summary aligned with the affiliated report model.',
                data_table={
                    'columns': list(totals_rows[0].keys()),
                    'rows': totals_rows
                },
                order=7
            ))

        return sections

    def _build_affiliation_mapping_section(self, is_hebrew: bool) -> Optional[ReportSection]:
        """Build a compact affiliations map section from authoritative schema constants."""
        try:
            from services.pension_data_agent import MislakaSchemaMapping
        except Exception:
            return None

        rows: List[Dict[str, Any]] = []

        for code, info in sorted(MislakaSchemaMapping.INTERFACE_CODES.items(), key=lambda item: int(item[0]))[:20]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'ממשק' if is_hebrew else 'Interface',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', info.get('name', '')),
                'שיוך' if is_hebrew else 'Affiliation': info.get('schema', info.get('name', ''))
            })

        for code, info in sorted(MislakaSchemaMapping.PRODUCT_TYPE_CODES.items(), key=lambda item: str(item[0]))[:20]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'מוצר' if is_hebrew else 'Product',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', info.get('name', '')),
                'שיוך' if is_hebrew else 'Affiliation': info.get('en', '')
            })

        for code, info in sorted(MislakaSchemaMapping.STATUS_CODES.items(), key=lambda item: str(item[0]))[:10]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'סטטוס' if is_hebrew else 'Status',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', info.get('name', '')),
                'שיוך' if is_hebrew else 'Affiliation': info.get('en', '')
            })

        for code, info in sorted(MislakaSchemaMapping.ID_TYPE_CODES.items(), key=lambda item: str(item[0]))[:10]:
            rows.append({
                'קבוצה' if is_hebrew else 'Group': 'זיהוי' if is_hebrew else 'ID Type',
                'קוד' if is_hebrew else 'Code': code,
                'שם' if is_hebrew else 'Name': info.get('he', ''),
                'שיוך' if is_hebrew else 'Affiliation': info.get('en', '')
            })

        return ReportSection(
            title='מפת שיוכים (Affiliations)' if is_hebrew else 'Affiliation Mapping Snapshot',
            content='טבלת שיוכים לפי מסלקה: ממשקים, מוצרים, סטטוסים וסוגי זיהוי.' if is_hebrew
            else 'Affiliation map by Mislaka schema: interfaces, products, statuses, and ID types.',
            data_table={
                'columns': list(rows[0].keys()) if rows else [],
                'rows': rows
            },
            order=9
        )

    @staticmethod
    def _to_float_amount(value: Any) -> float:
        """Best-effort numeric conversion for monetary/coverage fields."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)

        text_value = str(value).strip()
        if not text_value:
            return 0.0

        cleaned = (
            text_value
            .replace(',', '')
            .replace('₪', '')
            .replace('$', '')
            .replace('€', '')
            .replace('%', '')
        )
        cleaned = re.sub(r'[^0-9\.\-]', '', cleaned)
        if cleaned in ['', '-', '.', '-.']:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def _mask_identifier(identifier: Any) -> str:
        """Mask identifiers for privacy in report tables."""
        identifier_str = str(identifier or '').strip()
        if len(identifier_str) <= 4:
            return identifier_str
        return f"{identifier_str[:2]}****{identifier_str[-2:]}"

    @staticmethod
    def _column_matches(column_name: str, tokens: List[str]) -> bool:
        column_lower = (column_name or '').lower()
        return any(token in column_lower for token in tokens)

    def _extract_savings_cover_id_summary(
        self,
        doc_data: Optional[Dict[str, Any]],
        pension_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extract affiliated summary metrics focused on savings, cover and ID dimensions.
        The output is intentionally source-agnostic (no credentials or external links).
        """
        rows = []
        columns = []
        if isinstance(doc_data, dict):
            rows = doc_data.get('rows', []) or []
            columns = doc_data.get('columns', []) or []

        id_tokens = [
            'id', 'identity', 'id_number', 'customer_id', 'policyholder_id',
            'ת.ז', 'ת"ז', 'ת״ז', 'תז', 'תעודת זהות', 'מספר זהות', 'מספר ת.ז'
        ]
        savings_tokens = [
            'saving', 'savings', 'balance', 'accumulated', 'total_balance',
            'יתרה', 'צבירה', 'חיסכון', 'תגמולים', 'סה"כ', 'סה״כ'
        ]
        severance_tokens = [
            'severance', 'pitzuim', 'פיצויים', 'יתרת פיצויים'
        ]
        cover_tokens = [
            'cover', 'coverage', 'insured_amount', 'sum_insured',
            'death_coverage', 'disability_coverage', 'כיסוי', 'סכום ביטוח'
        ]

        id_columns = [c for c in columns if self._column_matches(str(c), id_tokens)]
        savings_columns = [c for c in columns if self._column_matches(str(c), savings_tokens)]
        cover_columns = [c for c in columns if self._column_matches(str(c), cover_tokens)]
        severance_columns = [c for c in columns if self._column_matches(str(c), severance_tokens)]

        total_savings = 0.0
        total_cover = 0.0
        total_severance = 0.0
        records_with_savings = 0
        records_with_cover = 0
        id_values: List[str] = []
        sample_rows: List[Dict[str, Any]] = []

        # Prefer pension structured data when available (Mislaka-aligned source).
        if isinstance(pension_data, dict) and pension_data.get('accounts'):
            accounts = pension_data.get('accounts', []) or []
            client_data = pension_data.get('client', {})
            if isinstance(client_data, list):
                client_data = client_data[0] if client_data else {}
            shared_client_id = ''
            if isinstance(client_data, dict):
                shared_client_id = str(client_data.get('id_number', '') or '').strip()

            for account in accounts[:500]:
                account_id = str(account.get('id_number') or shared_client_id or account.get('policy_number') or '').strip()
                savings_value = (
                    self._to_float_amount(account.get('total_balance'))
                    or self._to_float_amount(account.get('savings_balance'))
                )
                severance_value = self._to_float_amount(account.get('severance_balance'))
                cover_value = (
                    self._to_float_amount(account.get('death_coverage'))
                    + self._to_float_amount(account.get('disability_coverage'))
                )

                if account_id:
                    id_values.append(account_id)
                if savings_value > 0:
                    total_savings += savings_value
                    records_with_savings += 1
                if severance_value > 0:
                    total_severance += severance_value
                if cover_value > 0:
                    total_cover += cover_value
                    records_with_cover += 1

                if account_id or savings_value > 0 or cover_value > 0:
                    sample_rows.append({
                        'id': self._mask_identifier(account_id) if account_id else '',
                        'savings': round(savings_value, 2),
                        'cover': round(cover_value, 2),
                        'reference': str(account.get('policy_number', '') or '')
                    })
        else:
            for row in rows[:500]:
                if not isinstance(row, dict):
                    continue

                id_value = ''
                for col in id_columns:
                    candidate = str(row.get(col, '') or '').strip()
                    if candidate:
                        id_value = candidate
                        break

                savings_value = sum(self._to_float_amount(row.get(col)) for col in savings_columns)
                cover_value = sum(self._to_float_amount(row.get(col)) for col in cover_columns)
                total_severance += sum(self._to_float_amount(row.get(col)) for col in severance_columns)

                if id_value:
                    id_values.append(id_value)
                if savings_value > 0:
                    total_savings += savings_value
                    records_with_savings += 1
                if cover_value > 0:
                    total_cover += cover_value
                    records_with_cover += 1

                if id_value or savings_value > 0 or cover_value > 0:
                    sample_rows.append({
                        'id': self._mask_identifier(id_value) if id_value else '',
                        'savings': round(savings_value, 2),
                        'cover': round(cover_value, 2),
                        'reference': ''
                    })

        unique_ids = sorted({v for v in id_values if v})
        customer_id = ''
        customer_id_valid = None
        customer_birth_date = ''
        customer_birth_date_raw = ''
        integrity_issues: List[str] = []

        client_data = {}
        if isinstance(pension_data, dict):
            client_data = pension_data.get('client', {}) or {}
            if isinstance(client_data, list):
                client_data = client_data[0] if client_data else {}
            if not isinstance(client_data, dict):
                client_data = {}
        client_data = self._normalize_client_profile_fields(client_data)
        if client_data.get('id_number'):
            customer_id = str(client_data.get('id_number') or '').strip()
        elif unique_ids:
            customer_id = self._normalize_customer_identifier(unique_ids[0])

        if customer_id and customer_id.isdigit() and len(customer_id) == 9:
            customer_id_valid = self._is_valid_israeli_id(customer_id)
            if not customer_id_valid:
                integrity_issues.append('Customer ID failed Israeli checksum validation')
        elif customer_id:
            customer_id_valid = False
            integrity_issues.append('Customer ID is not a 9-digit value')

        customer_birth_date = str(client_data.get('birth_date') or '').strip()
        customer_birth_date_raw = str(client_data.get('birth_date_raw') or '').strip()

        if not customer_birth_date:
            birth_tokens = ['birth', 'birth_date', 'date_of_birth', 'dob', 'תאריך לידה', 'לידה']
            birth_columns = [c for c in columns if self._column_matches(str(c), birth_tokens)]
            for row in rows[:500]:
                if not isinstance(row, dict):
                    continue
                found_raw = ''
                for birth_col in birth_columns:
                    candidate = str(row.get(birth_col, '') or '').strip()
                    if candidate:
                        found_raw = candidate
                        break
                if found_raw:
                    birth_raw, birth_display = self._normalize_birth_date(found_raw)
                    customer_birth_date_raw = birth_raw or customer_birth_date_raw
                    customer_birth_date = birth_display or customer_birth_date
                    if customer_birth_date:
                        break

        if isinstance(pension_data, dict):
            totals = pension_data.get('totals') or {}
            if not total_savings and totals.get('total_balance'):
                total_savings = self._to_float_amount(totals.get('total_balance'))
            if not total_severance and totals.get('total_severance'):
                total_severance = self._to_float_amount(totals.get('total_severance'))

        if customer_birth_date_raw and not customer_birth_date:
            integrity_issues.append('Birth date could not be normalized to DD/MM/YYYY')

        records_analyzed = max(len(rows), len(sample_rows), 0)
        id_rows_count = len([entry for entry in sample_rows if entry.get('id')])

        return {
            'records_analyzed': records_analyzed,
            'id_columns': id_columns,
            'savings_columns': savings_columns,
            'cover_columns': cover_columns,
            'ids_with_values': len(id_values),
            'unique_id_count': len(unique_ids),
            'id_row_coverage': id_rows_count,
            'total_savings': round(total_savings, 2),
            'total_severance': round(total_severance, 2),
            'average_savings': round(total_savings / records_with_savings, 2) if records_with_savings else 0.0,
            'total_cover': round(total_cover, 2),
            'average_cover': round(total_cover / records_with_cover, 2) if records_with_cover else 0.0,
            'coverage_to_savings_ratio': round(total_cover / total_savings, 2) if total_savings > 0 else None,
            'sample_rows': sample_rows[:120],
            'customer_id': customer_id,
            'customer_id_masked': self._mask_identifier(customer_id) if customer_id else '',
            'customer_id_valid': customer_id_valid,
            'birth_date': customer_birth_date,
            'birth_date_raw': customer_birth_date_raw,
            'integrity_issues': integrity_issues,
        }

    def _build_savings_cover_id_section(
        self,
        summary: Optional[Dict[str, Any]],
        is_hebrew: bool,
        assessment_only: bool = False,
    ) -> Optional[ReportSection]:
        """Build a compact affiliated section for savings/cover/ID analysis."""
        if not summary:
            return None

        records_analyzed = int(summary.get('records_analyzed', 0) or 0)
        total_savings = float(summary.get('total_savings', 0) or 0)
        total_cover = float(summary.get('total_cover', 0) or 0)
        unique_id_count = int(summary.get('unique_id_count', 0) or 0)
        if records_analyzed <= 0 and total_savings <= 0 and total_cover <= 0 and unique_id_count <= 0:
            return None

        if is_hebrew:
            if assessment_only:
                content = (
                    "סיכום הערכת מסלקה (נתוני הלקוח מהקבצים המסונפים):\n\n"
                    f"• תעודת זהות: {summary.get('customer_id', 'לא זמין')}\n"
                    f"• תאריך לידה: {summary.get('birth_date', 'לא זמין')}"
                    + (f" (מקור: {summary.get('birth_date_raw')})" if summary.get('birth_date_raw') else "")
                    + "\n"
                    f"• סה״כ צבירה: ₪{total_savings:,.2f}\n"
                    f"• סה״כ פיצויים: ₪{float(summary.get('total_severance', 0) or 0):,.2f}\n"
                    f"• סך כיסוי: ₪{total_cover:,.2f}\n"
                    f"• תקינות מזהה: {'✓ תקין' if summary.get('customer_id_valid') else '⚠ דורש בדיקה'}"
                )
            else:
                content = (
                    "סיכום מסונף לחיסכון וביטוח (על בסיס שיוכי מסלקה):\n\n"
                    f"• מזהה לקוח: {summary.get('customer_id', 'לא זמין')}\n"
                    f"• תאריך לידה: {summary.get('birth_date', 'לא זמין')}"
                    + (f" (מקור: {summary.get('birth_date_raw')})" if summary.get('birth_date_raw') else "")
                    + "\n"
                    f"• רשומות שנותחו: {records_analyzed}\n"
                    f"• סך חיסכון: ₪{total_savings:,.2f}\n"
                    f"• סה״כ פיצויים: ₪{float(summary.get('total_severance', 0) or 0):,.2f}\n"
                    f"• סך כיסוי: ₪{total_cover:,.2f}\n"
                    f"• מזהים ייחודיים: {unique_id_count}\n"
                    f"• יחס כיסוי/חיסכון: {summary.get('coverage_to_savings_ratio', 'N/A')}\n"
                    f"• תקינות מזהה: {'✓ תקין' if summary.get('customer_id_valid') else '⚠ דורש בדיקה'}"
                )
            title = 'סיכום מסונף - חיסכון, כיסוי וזיהוי'
            columns = ['מזהה לקוח', 'תאריך לידה', 'מזהה (מוסתר)', 'חיסכון', 'כיסוי', 'אסמכתא']
            data_rows = [{
                'מזהה לקוח': summary.get('customer_id', ''),
                'תאריך לידה': summary.get('birth_date', ''),
                'מזהה (מוסתר)': row.get('id', ''),
                'חיסכון': row.get('savings', 0),
                'כיסוי': row.get('cover', 0),
                'אסמכתא': row.get('reference', ''),
            } for row in summary.get('sample_rows', [])[:60]]
        else:
            if assessment_only:
                content = (
                    "Mislaka assessment snapshot (from affiliated source files):\n\n"
                    f"• National ID: {summary.get('customer_id', 'N/A')}\n"
                    f"• Birth Date: {summary.get('birth_date', 'N/A')}"
                    + (f" (source: {summary.get('birth_date_raw')})" if summary.get('birth_date_raw') else "")
                    + "\n"
                    f"• Total accumulation: ₪{total_savings:,.2f}\n"
                    f"• Total severance: ₪{float(summary.get('total_severance', 0) or 0):,.2f}\n"
                    f"• Total cover: ₪{total_cover:,.2f}\n"
                    f"• ID validation: {'Valid' if summary.get('customer_id_valid') else 'Needs review'}"
                )
            else:
                content = (
                    "Affiliated savings and insurance snapshot (Mislaka-aligned):\n\n"
                    f"• Customer ID: {summary.get('customer_id', 'N/A')}\n"
                    f"• Birth Date: {summary.get('birth_date', 'N/A')}"
                    + (f" (source: {summary.get('birth_date_raw')})" if summary.get('birth_date_raw') else "")
                    + "\n"
                    f"• Records analyzed: {records_analyzed}\n"
                    f"• Total savings: ₪{total_savings:,.2f}\n"
                    f"• Total severance: ₪{float(summary.get('total_severance', 0) or 0):,.2f}\n"
                    f"• Total cover: ₪{total_cover:,.2f}\n"
                    f"• Unique IDs: {unique_id_count}\n"
                    f"• Cover/Savings ratio: {summary.get('coverage_to_savings_ratio', 'N/A')}\n"
                    f"• ID validation: {'Valid' if summary.get('customer_id_valid') else 'Needs review'}"
                )
            title = 'Affiliated Summary - Savings, Cover & ID'
            columns = ['Customer ID', 'Birth Date', 'Masked ID', 'Savings', 'Cover', 'Reference']
            data_rows = [{
                'Customer ID': summary.get('customer_id', ''),
                'Birth Date': summary.get('birth_date', ''),
                'Masked ID': row.get('id', ''),
                'Savings': row.get('savings', 0),
                'Cover': row.get('cover', 0),
                'Reference': row.get('reference', ''),
            } for row in summary.get('sample_rows', [])[:60]]

        # Fall back to metric table when we don't have row-level samples.
        if not data_rows:
            metric_key = 'מדד' if is_hebrew else 'Metric'
            value_key = 'ערך' if is_hebrew else 'Value'
            metrics_rows = [
                {metric_key: 'Records', value_key: records_analyzed},
                {metric_key: 'Total Savings', value_key: total_savings},
                {metric_key: 'Total Cover', value_key: total_cover},
                {metric_key: 'Unique IDs', value_key: unique_id_count},
                {metric_key: 'Cover/Savings Ratio', value_key: summary.get('coverage_to_savings_ratio', 'N/A')},
            ]
            return ReportSection(
                title=title,
                content=content,
                data_table={'columns': [metric_key, value_key], 'rows': metrics_rows},
                order=4
            )

        return ReportSection(
            title=title,
            content=content,
            data_table={'columns': columns, 'rows': data_rows},
            order=4
        )


    def _generate_swiftness_resources_section(self, is_hebrew: bool) -> str:
        """Generate a report section with Swiftness affiliated links and resources."""
        try:
            from services.swiftness_data_service import get_swiftness_data_service
            svc = get_swiftness_data_service()
            catalog = svc.get_resource_catalog()
            model = svc.get_report_model()
        except Exception:
            return ''
        
        lines = []
        meta = catalog.get('metadata', {})
        
        if is_hebrew:
            lines.append('📥 משאבי נתונים מ-Swiftness לעבודה מול המסלקה:\n')
            lines.append(f'סה"כ משאבים: {meta.get("total_resources", 0)}')
            lines.append(f'ממשקים: {", ".join(meta.get("interfaces", []))}')
            lines.append(f'סוגי קבצים: {", ".join(t.upper() for t in meta.get("file_types", []))}')
            lines.append('')
            lines.append('🔗 קישורים ישירים:')
            for link in catalog.get('quick_links', []):
                lines.append(f'  • {link.get("label_he", link["label"])}: {link["url"]}')
            lines.append('')
            lines.append('📋 כללי מערכת (סכימות וטבלאות קודים):')
            for res in catalog.get('system_general', [])[:6]:
                lines.append(f'  • {res["name"]} ({res.get("file_type", "").upper()}'
                             f'{" v" + res["version"] if res.get("version") else ""})')
            lines.append('')
            lines.append('📂 קבצים עדכניים לעבודה מול המסלקה:')
            for res in catalog.get('mislaka_work_files', [])[:6]:
                lines.append(f'  • {res["name"]} ({res.get("file_type", "").upper()})')
            
            # Report model summary
            model_meta = model.get('metadata', {})
            sections_count = len(model.get('sections', []))
            lines.append('')
            lines.append(f'📊 מודל דוח מקיף: {sections_count} חלקים')
            for sec in model.get('sections', []):
                fields_count = len(sec.get('data_fields', []))
                lines.append(f'  {sec["order"]}. {sec["title_he"]} ({fields_count} שדות)')
            
            # Data integrity
            rules = model_meta.get('data_integrity_rules', [])
            if rules:
                lines.append('')
                lines.append('🛡️ כללי שלמות נתונים:')
                for rule in rules:
                    lines.append(f'  ✓ {rule}')
        else:
            lines.append('📥 Swiftness Data Resources for Mislaka Integration:\n')
            lines.append(f'Total Resources: {meta.get("total_resources", 0)}')
            lines.append(f'Interfaces: {", ".join(meta.get("interfaces", []))}')
            lines.append(f'File Types: {", ".join(t.upper() for t in meta.get("file_types", []))}')
            lines.append('')
            lines.append('🔗 Direct Links:')
            for link in catalog.get('quick_links', []):
                lines.append(f'  • {link["label"]}: {link["url"]}')
            lines.append('')
            lines.append('📋 System General (Schemas & Code Tables):')
            for res in catalog.get('system_general', [])[:6]:
                lines.append(f'  • {res.get("name_en", res["name"])} ({res.get("file_type", "").upper()}'
                             f'{" v" + res["version"] if res.get("version") else ""})')
            lines.append('')
            lines.append('📂 Latest Mislaka Work Files:')
            for res in catalog.get('mislaka_work_files', [])[:6]:
                lines.append(f'  • {res.get("name_en", res["name"])} ({res.get("file_type", "").upper()})')
            
            # Report model summary
            model_meta = model.get('metadata', {})
            sections_count = len(model.get('sections', []))
            lines.append('')
            lines.append(f'📊 Comprehensive Report Model: {sections_count} sections')
            for sec in model.get('sections', []):
                fields_count = len(sec.get('data_fields', []))
                lines.append(f'  {sec["order"]}. {sec["title_en"]} ({fields_count} fields)')
            
            # Data integrity
            rules = model_meta.get('data_integrity_rules', [])
            if rules:
                lines.append('')
                lines.append('🛡️ Data Integrity Rules:')
                for rule in rules:
                    lines.append(f'  ✓ {rule}')
        
        return '\n'.join(lines)
    
    def _generate_data_content_section(self, doc_data: Dict[str, Any], 
                                        analysis: AnalysisResult, is_hebrew: bool) -> str:
        """
        Generate a section showing actual data content from uploaded files.
        This displays the real values from CSV/ZIP files, not just statistics.
        """
        content_lines = []
        
        columns = doc_data.get('columns', [])
        rows = doc_data.get('rows', [])
        files = doc_data.get('files', [])
        
        # If from ZIP, show file list
        if files:
            if is_hebrew:
                content_lines.append("📁 קבצים שנותחו מתוך ה-ZIP:")
            else:
                content_lines.append("📁 Files analyzed from ZIP:")
            
            for f in files:
                content_lines.append(f"  • {f.get('name', 'Unknown')} ({f.get('row_count', 0)} שורות)" if is_hebrew else f"  • {f.get('name', 'Unknown')} ({f.get('row_count', 0)} rows)")
            content_lines.append("")
        
        # Show column headers
        if columns:
            if is_hebrew:
                content_lines.append(f"📋 עמודות הנתונים ({len(columns)}):")
            else:
                content_lines.append(f"📋 Data Columns ({len(columns)}):")
            
            # Display columns in a formatted way
            col_display = []
            for col in columns[:20]:  # Limit to 20 columns
                col_display.append(f"  • {col}")
            content_lines.extend(col_display)
            if len(columns) > 20:
                content_lines.append(f"  ... ועוד {len(columns) - 20} עמודות" if is_hebrew else f"  ... and {len(columns) - 20} more columns")
            content_lines.append("")
        
        # Show sample data rows as table
        if rows:
            if is_hebrew:
                content_lines.append(f"📊 נתונים שחולצו ({len(rows)} רשומות):")
                content_lines.append("=" * 50)
            else:
                content_lines.append(f"📊 Extracted Data ({len(rows)} records):")
                content_lines.append("=" * 50)
            
            # Display first 10 rows with all their values
            for i, row in enumerate(rows[:15], 1):
                if is_hebrew:
                    content_lines.append(f"\n🔹 רשומה {i}:")
                else:
                    content_lines.append(f"\n🔹 Record {i}:")
                
                for key, value in row.items():
                    if value and str(value).strip():
                        # Clean and format the value
                        val_str = str(value).strip()
                        # Detect if it's a numeric value
                        try:
                            num_val = float(val_str.replace(',', '').replace('₪', '').replace('$', ''))
                            if num_val > 1000:
                                val_str = f"₪{num_val:,.0f}" if any(x in key.lower() for x in ['premium', 'cover', 'amount', 'סכום', 'פרמיה', 'כיסוי']) else f"{num_val:,.0f}"
                        except ValueError:
                            pass
                        content_lines.append(f"    {key}: {val_str}")
            
            if len(rows) > 15:
                content_lines.append(f"\n... ועוד {len(rows) - 15} רשומות" if is_hebrew else f"\n... and {len(rows) - 15} more records")
        
        # Extract and highlight key insurance/financial fields
        key_fields = self._extract_key_fields_from_data(rows, is_hebrew)
        if key_fields:
            content_lines.append("")
            if is_hebrew:
                content_lines.append("🎯 שדות מרכזיים שזוהו:")
            else:
                content_lines.append("🎯 Key Fields Identified:")
            
            for field_name, field_value in key_fields.items():
                content_lines.append(f"  • {field_name}: {field_value}")
        
        return '\n'.join(content_lines) if content_lines else ""
    
    def _generate_pension_section(self, pension_data: Dict[str, Any], 
                                   pension_report: str, is_hebrew: bool) -> str:
        """
        Generate a comprehensive pension and insurance report section.
        Uses data from the enhanced PensionDataAgent for Mislaka XML files.
        
        Supports the full Mislaka interface standards:
        - Holdings Interface (v9.7.7)
        - Severance Interface (v5.9.38)
        - Event Interface (v7.6.30)
        - Transference Interface (v3.7.2)
        
        This displays:
        - Professional Mislaka report generated by PensionDataAgent
        - Account summaries with balances by provider/product type
        - Section 14 status and severance details
        - Health score and AI recommendations
        - Contribution analysis and trends
        """
        content_lines = []
        
        # If we have the pre-generated Mislaka pension report, include it
        if pension_report:
            content_lines.append(pension_report)
            content_lines.append("")
            content_lines.append("─" * 50)
            content_lines.append("")
        
        # If we have structured pension data, add detailed breakdown
        if pension_data:
            # Support both 'totals' (new) and 'summary' (legacy) keys
            totals = pension_data.get('totals', pension_data.get('summary', {}))
            accounts = pension_data.get('accounts', [])
            clients = pension_data.get('client', {})
            if isinstance(clients, list) and clients:
                clients = clients[0]
            header = pension_data.get('header', {})
            contributions = pension_data.get('contributions', [])
            severance = pension_data.get('severance', [])
            
            if is_hebrew:
                # Financial summary section with health score
                health_score = totals.get('health_score', {})
                if health_score:
                    content_lines.append("🎯 ציון בריאות פיננסית:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• ציון כולל: {health_score.get('overall', 0)}/100 ({health_score.get('rating_he', 'לא ידוע')})")
                    content_lines.append(f"• ציון חסכונות: {health_score.get('savings', 0)}/100")
                    content_lines.append(f"• ציון פיזור: {health_score.get('diversification', 0)}/100")
                    content_lines.append(f"• ציון סעיף 14: {health_score.get('section14', 0)}/100")
                    content_lines.append("")
                
                # Financial summary section
                content_lines.append("💰 סיכום כספי מפורט:")
                content_lines.append("=" * 40)
                content_lines.append(f"• סה״כ יתרה בחשבונות: {totals.get('total_balance_formatted', '₪0')}")
                content_lines.append(f"• סה״כ חסכונות: {totals.get('total_savings_formatted', '₪0')}")
                content_lines.append(f"• סה״כ פיצויים צבורים: {totals.get('total_severance_formatted', '₪0')}")
                content_lines.append(f"• מספר חשבונות/פוליסות: {totals.get('account_count', 0)}")
                content_lines.append(f"• מספר יצרנים/חברות: {totals.get('provider_count', 0)}")
                
                # Providers
                providers = totals.get('providers', [])
                if providers:
                    content_lines.append(f"• יצרנים: {', '.join(providers)}")
                content_lines.append("")
                
                # Section 14 status
                content_lines.append("📌 סעיף 14 (פיצויים):")
                if totals.get('section14_coverage'):
                    content_lines.append("• סטטוס: ✅ מכוסה")
                    content_lines.append("• ✅ הלקוח מכוסה תחת סעיף 14 - פיצויים מובטחים")
                    content_lines.append(f"• מספר חשבונות עם סעיף 14: {totals.get('section14_accounts', 0)}")
                else:
                    content_lines.append("• סטטוס: ⚠️ לא מכוסה")
                    content_lines.append("• ⚠️ אין כיסוי סעיף 14 - יש לבדוק עם המעסיק")
                content_lines.append("")
                
                # Contribution summary
                contrib_totals = totals.get('contributions', {})
                if contrib_totals:
                    content_lines.append("📈 סיכום הפקדות:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• הפקדות עובד: ₪{contrib_totals.get('employee_total', 0):,.2f}")
                    content_lines.append(f"• הפקדות מעסיק: ₪{contrib_totals.get('employer_total', 0):,.2f}")
                    content_lines.append(f"• הפקדות פיצויים: ₪{contrib_totals.get('severance_total', 0):,.2f}")
                    content_lines.append(f"• סה״כ הפקדות: ₪{contrib_totals.get('grand_total', 0):,.2f}")
                    content_lines.append(f"• תקופות: {contrib_totals.get('periods_count', 0)}")
                    content_lines.append("")
                
                # Contribution trend
                trend = totals.get('contribution_trend')
                if trend:
                    trend_he = totals.get('contribution_trend_he', trend)
                    content_lines.append("📈 מגמת הפקדות:")
                    content_lines.append(f"• מגמה: {trend_he}")
                    content_lines.append("")
                
                # Missing months warning
                missing = totals.get('missing_contribution_months', [])
                if missing:
                    content_lines.append("⚠️ אזהרה - חודשים חסרים:")
                    content_lines.append(f"• נמצאו {len(missing)} חודשים ללא הפקדות")
                    content_lines.append(f"• חודשים: {', '.join(missing[:6])}{'...' if len(missing) > 6 else ''}")
                    content_lines.append("")
                
                # Account details
                if accounts:
                    content_lines.append("📁 פירוט חשבונות:")
                    content_lines.append("-" * 40)
                    total_balance = totals.get('total_balance', 1)
                    for i, acct in enumerate(accounts[:10], 1):
                        balance = acct.get('total_balance', acct.get('balance', 0))
                        pct = (balance / total_balance * 100) if total_balance > 0 else 0
                        content_lines.append(f"\n🔹 חשבון {i}:")
                        content_lines.append(f"   • מספר פוליסה: {acct.get('policy_number', 'לא ידוע')}")
                        if acct.get('provider'):
                            content_lines.append(f"   • יצרן: {acct.get('provider')}")
                        if acct.get('product_type_name') or acct.get('product_name') or acct.get('product_type'):
                            content_lines.append(f"   • סוג מוצר: {acct.get('product_type_name', acct.get('product_name', acct.get('product_type', 'לא ידוע')))}")
                        if acct.get('status'):
                            content_lines.append(f"   • סטטוס: {acct.get('status')}")
                        content_lines.append(f"   • יתרה: ₪{balance:,.2f} ({pct:.1f}% מהכולל)")
                        if acct.get('savings_balance', 0) > 0:
                            content_lines.append(f"   • חיסכון: ₪{acct.get('savings_balance', 0):,.2f}")
                        if acct.get('severance_balance', 0) > 0:
                            content_lines.append(f"   • פיצויים: ₪{acct.get('severance_balance', 0):,.2f}")
                        if acct.get('section14'):
                            content_lines.append(f"   • סעיף 14: ✅ מכוסה")
                        if acct.get('management_fee_savings', 0) > 0:
                            content_lines.append(f"   • דמי ניהול: {acct.get('management_fee_savings', 0):.2f}%")
                        if acct.get('employer_name'):
                            content_lines.append(f"   • מעסיק: {acct.get('employer_name')}")
                    
                    if len(accounts) > 10:
                        content_lines.append(f"\n   ... ועוד {len(accounts) - 10} חשבונות")
                    content_lines.append("")
            
            else:
                # English version
                health_score = totals.get('health_score', {})
                if health_score:
                    content_lines.append("🎯 Financial Health Score:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• Overall Score: {health_score.get('overall', 0)}/100 ({health_score.get('rating', 'unknown')})")
                    content_lines.append(f"• Savings Score: {health_score.get('savings', 0)}/100")
                    content_lines.append(f"• Diversification Score: {health_score.get('diversification', 0)}/100")
                    content_lines.append(f"• Section 14 Score: {health_score.get('section14', 0)}/100")
                    content_lines.append("")
                
                content_lines.append("💰 Detailed Financial Summary:")
                content_lines.append("=" * 40)
                content_lines.append(f"• Total Account Balance: {totals.get('total_balance_formatted', '₪0')}")
                content_lines.append(f"• Total Savings: {totals.get('total_savings_formatted', '₪0')}")
                content_lines.append(f"• Total Severance Accrued: {totals.get('total_severance_formatted', '₪0')}")
                content_lines.append(f"• Number of Accounts/Policies: {totals.get('account_count', 0)}")
                content_lines.append(f"• Number of Providers: {totals.get('provider_count', 0)}")
                
                providers = totals.get('providers', [])
                if providers:
                    content_lines.append(f"• Providers: {', '.join(providers)}")
                content_lines.append("")
                
                # Section 14 status
                content_lines.append("📌 Section 14 (Severance):")
                content_lines.append(f"• Covered: {'Yes' if totals.get('section14_coverage') else 'No'}")
                if totals.get('section14_coverage'):
                    content_lines.append("• ✅ Client is covered under Section 14 - severance is secured")
                    content_lines.append(f"• Accounts with Section 14: {totals.get('section14_accounts', 0)}")
                else:
                    content_lines.append("• ⚠️ No Section 14 coverage - verify with employer")
                content_lines.append("")
                
                # Contribution summary
                contrib_totals = totals.get('contributions', {})
                if contrib_totals:
                    content_lines.append("📈 Contribution Summary:")
                    content_lines.append("=" * 40)
                    content_lines.append(f"• Employee Contributions: ₪{contrib_totals.get('employee_total', 0):,.2f}")
                    content_lines.append(f"• Employer Contributions: ₪{contrib_totals.get('employer_total', 0):,.2f}")
                    content_lines.append(f"• Severance Contributions: ₪{contrib_totals.get('severance_total', 0):,.2f}")
                    content_lines.append(f"• Total Contributions: ₪{contrib_totals.get('grand_total', 0):,.2f}")
                    content_lines.append(f"• Periods: {contrib_totals.get('periods_count', 0)}")
                    content_lines.append("")
                
                # Contribution trend
                trend = totals.get('contribution_trend')
                if trend:
                    content_lines.append("📈 Contribution Trend:")
                    content_lines.append(f"• Trend: {trend.capitalize()}")
                    content_lines.append("")
                
                # Missing months warning
                missing = totals.get('missing_contribution_months', [])
                if missing:
                    content_lines.append("⚠️ Warning - Missing Months:")
                    content_lines.append(f"• Found {len(missing)} months without contributions")
                    content_lines.append(f"• Months: {', '.join(missing[:6])}{'...' if len(missing) > 6 else ''}")
                    content_lines.append("")
                
                # Account details
                if accounts:
                    content_lines.append("📁 Account Details:")
                    content_lines.append("-" * 40)
                    total_balance = totals.get('total_balance', 1)
                    for i, acct in enumerate(accounts[:10], 1):
                        balance = acct.get('total_balance', acct.get('balance', 0))
                        pct = (balance / total_balance * 100) if total_balance > 0 else 0
                        content_lines.append(f"\n🔹 Account {i}:")
                        content_lines.append(f"   • Policy Number: {acct.get('policy_number', 'Unknown')}")
                        content_lines.append(f"   • Balance: ₪{balance:,.2f} ({pct:.1f}% of total)")
                        if acct.get('provider'):
                            content_lines.append(f"   • Provider: {acct.get('provider')}")
                        if acct.get('product_name') or acct.get('product_type'):
                            content_lines.append(f"   • Product: {acct.get('product_name', acct.get('product_type', 'Unknown'))}")
                        if acct.get('status'):
                            content_lines.append(f"   • Status: {acct.get('status')}")
                        content_lines.append(f"   • Balance: ₪{acct.get('balance', 0):,.2f}")
                        if acct.get('severance_balance', 0) > 0:
                            content_lines.append(f"   • Severance: ₪{acct.get('severance_balance', 0):,.2f}")
                        if acct.get('employer'):
                            emp = acct['employer']
                            if isinstance(emp, dict):
                                content_lines.append(f"   • Employer: {emp.get('name', '')}")
                    
                    if len(accounts) > 10:
                        content_lines.append(f"\n   ... and {len(accounts) - 10} more accounts")
                    content_lines.append("")
        
        return '\n'.join(content_lines) if content_lines else ""
    
    def _extract_key_fields_from_data(self, rows: List[Dict], is_hebrew: bool) -> Dict[str, Any]:
        """
        Extract key financial/insurance fields from the actual data rows.
        """
        key_fields = {}
        
        # Keywords to look for
        important_keys = {
            'policy': ['policy', 'פוליסה', 'מספר פוליסה', 'policy_number'],
            'premium': ['premium', 'פרמיה', 'תשלום', 'payment', 'חודשי'],
            'cover': ['cover', 'כיסוי', 'סכום ביטוח', 'סכום', 'coverage', 'amount'],
            'date': ['date', 'תאריך', 'start', 'תחילה', 'end', 'סיום'],
            'id': ['id', 'ת.ז', 'תעודת זהות', 'מספר זהות', 'identity'],
            'name': ['name', 'שם', 'מבוטח', 'insured'],
            'type': ['type', 'סוג', 'תוכנית', 'plan', 'מסלול'],
            'pension': ['pension', 'פנסיה', 'גמל', 'קרן'],
            'beneficiary': ['beneficiary', 'מוטב', 'מוטבים'],
        }
        
        for row in rows[:20]:  # Check first 20 rows
            for col_name, value in row.items():
                if not value or not str(value).strip():
                    continue
                
                col_lower = col_name.lower()
                value_str = str(value).strip()
                
                for field_type, keywords in important_keys.items():
                    if any(kw in col_lower for kw in keywords):
                        label_map = {
                            'policy': 'מספר פוליסה' if is_hebrew else 'Policy Number',
                            'premium': 'פרמיה' if is_hebrew else 'Premium',
                            'cover': 'סכום כיסוי' if is_hebrew else 'Cover Amount',
                            'date': col_name,
                            'id': 'מספר זהות' if is_hebrew else 'ID Number',
                            'name': 'שם' if is_hebrew else 'Name',
                            'type': 'סוג' if is_hebrew else 'Type',
                            'pension': 'פנסיה' if is_hebrew else 'Pension',
                            'beneficiary': 'מוטב' if is_hebrew else 'Beneficiary',
                        }
                        
                        label = label_map.get(field_type, col_name)
                        
                        # Format numeric values
                        if field_type in ['premium', 'cover']:
                            try:
                                num_val = float(value_str.replace(',', '').replace('₪', '').replace('$', ''))
                                value_str = f"₪{num_val:,.0f}"
                            except ValueError:
                                pass
                        
                        # Mask ID numbers for privacy
                        if field_type == 'id' and len(value_str) >= 6:
                            value_str = value_str[:2] + '****' + value_str[-2:]
                        
                        if label not in key_fields:
                            key_fields[label] = value_str
                        break
        
        return key_fields
    
    def _generate_hebrew_insurance_section(self, hebrew_factors: List[Factor], 
                                            is_hebrew: bool) -> str:
        """
        Generate a detailed section showing extracted Hebrew insurance policy details.
        """
        content_lines = []
        
        if is_hebrew:
            content_lines.append("📋 פרטי הפוליסה שחולצו מהמסמכים:\n")
        else:
            content_lines.append("📋 Policy Details Extracted from Documents:\n")
        
        for factor in hebrew_factors:
            # Add factor name as header
            content_lines.append(f"▸ {factor.name}:")
            
            if isinstance(factor.value, dict):
                for key, val in factor.value.items():
                    content_lines.append(f"    • {key}: {val}")
            else:
                content_lines.append(f"    {factor.value}")
            
            content_lines.append("")
        
        # Add importance rating
        if hebrew_factors:
            avg_importance = sum(f.importance for f in hebrew_factors) / len(hebrew_factors)
            if is_hebrew:
                content_lines.append(f"📈 רמת חשיבות ממוצעת: {avg_importance:.0%}")
            else:
                content_lines.append(f"📈 Average Importance: {avg_importance:.0%}")
        
        return '\n'.join(content_lines)


    def _generate_recommendations(self, analysis: AnalysisResult, lang: str) -> List[Recommendation]:
        """Generate actionable recommendations"""
        recommendations = []
        rec_id = 1
        
        # High risk score recommendation
        if analysis.risk_score > 70:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='risk',
                priority=Priority.URGENT,
                title='סקירת סיכונים דחופה' if lang == 'hebrew' else 'Urgent Risk Review Required',
                description='ציון הסיכון הכולל גבוה ומצריך התייחסות מיידית' if lang == 'hebrew' 
                           else 'The overall risk score is high and requires immediate attention',
                action_items=[
                    'סקור את כל החריגות שזוהו' if lang == 'hebrew' else 'Review all identified anomalies',
                    'בדוק את הנתונים החריגים' if lang == 'hebrew' else 'Verify outlier data points',
                    'עדכן את הערכת הסיכון' if lang == 'hebrew' else 'Update risk assessment'
                ],
                expected_impact='הפחתת רמת הסיכון ב-20-30%' if lang == 'hebrew' else 'Risk level reduction of 20-30%'
            ))
            rec_id += 1
        
        # Missing data recommendation
        missing_patterns = [p for p in analysis.patterns_found if p.type == 'missing_data']
        if missing_patterns:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='data_quality',
                priority=Priority.HIGH,
                title='השלמת נתונים חסרים' if lang == 'hebrew' else 'Complete Missing Data',
                description='זוהו שדות עם נתונים חסרים המשפיעים על איכות הניתוח' if lang == 'hebrew'
                           else 'Fields with missing data detected affecting analysis quality',
                action_items=[
                    'אסוף את הנתונים החסרים' if lang == 'hebrew' else 'Collect missing data',
                    'עדכן את המערכת' if lang == 'hebrew' else 'Update the system',
                    'הרץ ניתוח מחדש' if lang == 'hebrew' else 'Re-run analysis'
                ],
                expected_impact='שיפור דיוק הניתוח ב-15-25%' if lang == 'hebrew' else 'Analysis accuracy improvement of 15-25%'
            ))
            rec_id += 1
        
        # Anomalies recommendation
        if analysis.anomalies:
            high_severity = [a for a in analysis.anomalies if a.severity in [Severity.HIGH, Severity.CRITICAL]]
            if high_severity:
                recommendations.append(Recommendation(
                    id=f"REC-{rec_id}",
                    category='anomalies',
                    priority=Priority.HIGH,
                    title='טיפול בחריגות קריטיות' if lang == 'hebrew' else 'Address Critical Anomalies',
                    description=f'זוהו {len(high_severity)} חריגות ברמה גבוהה או קריטית' if lang == 'hebrew'
                               else f'{len(high_severity)} high or critical anomalies detected',
                    action_items=[a.recommendation for a in high_severity[:3]],
                    expected_impact='הפחתת סיכון והגברת אמינות הנתונים' if lang == 'hebrew' 
                                   else 'Risk reduction and improved data reliability'
                ))
                rec_id += 1
        
        # Data type specific recommendations
        if analysis.data_classification == DataType.INSURANCE:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='insurance',
                priority=Priority.MEDIUM,
                title='סקירת כיסויים ביטוחיים' if lang == 'hebrew' else 'Review Insurance Coverage',
                description='מומלץ לבדוק התאמת הכיסויים לצרכים' if lang == 'hebrew'
                           else 'Review coverage adequacy against needs',
                action_items=[
                    'השווה כיסויים לסיכונים' if lang == 'hebrew' else 'Compare coverage to risks',
                    'בדוק חפיפות בפוליסות' if lang == 'hebrew' else 'Check for policy overlaps',
                    'עדכן סכומי ביטוח' if lang == 'hebrew' else 'Update coverage amounts'
                ],
                expected_impact='אופטימיזציה של הוצאות ביטוח' if lang == 'hebrew' else 'Insurance expense optimization'
            ))
            rec_id += 1
        elif analysis.data_classification == DataType.INVESTMENT:
            recommendations.append(Recommendation(
                id=f"REC-{rec_id}",
                category='investment',
                priority=Priority.MEDIUM,
                title='איזון תיק השקעות' if lang == 'hebrew' else 'Portfolio Rebalancing',
                description='בדוק את פיזור התיק ואיזון הסיכון' if lang == 'hebrew'
                           else 'Review portfolio diversification and risk balance',
                action_items=[
                    'נתח פיזור נכסים' if lang == 'hebrew' else 'Analyze asset allocation',
                    'בדוק התאמה לפרופיל סיכון' if lang == 'hebrew' else 'Check risk profile alignment',
                    'שקול איזון מחדש' if lang == 'hebrew' else 'Consider rebalancing'
                ],
                expected_impact='שיפור יחס תשואה/סיכון' if lang == 'hebrew' else 'Improved return/risk ratio'
            ))
            rec_id += 1
        
        return recommendations

