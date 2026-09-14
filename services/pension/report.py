"""Enrichment, health score, Hebrew professional report and recommendations
for parsed Mislaka data.

Moved verbatim from ``services/pension_data_agent.py`` (B5) as a mixin so the
agent's method names — and every caller — are unchanged.
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple


class PensionReportMixin:
    """Derived metrics + report text. Pure functions of the parsed ``data``
    (and the clock, for the report date / age)."""

    def _enrich_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich parsed data with calculated metrics."""
        accounts = data.get('accounts', [])
        contributions = data.get('contributions', [])
        severance = data.get('severance', [])
        
        # Initialize totals if not present
        if 'totals' not in data:
            data['totals'] = {}
        
        totals = data['totals']
        
        # Calculate totals
        totals['total_balance'] = sum(float(a.get('total_balance', 0) or 0) for a in accounts)
        totals['total_savings'] = sum(float(a.get('savings_balance', 0) or 0) for a in accounts)
        totals['total_severance'] = sum(float(a.get('severance_balance', 0) or 0) for a in accounts)
        totals['total_severance'] += sum(float(s.get('total_severance', 0) or 0) for s in severance)
        totals['total_coverage'] = sum(float(a.get('coverage_amount', 0) or 0) for a in accounts)
        totals['account_count'] = len(accounts)
        totals['provider_count'] = len(set(a.get('provider', '') for a in accounts if a.get('provider')))
        totals['providers'] = list(set(a.get('provider', '') for a in accounts if a.get('provider')))
        
        # Format totals
        totals['total_balance_formatted'] = f"₪{totals['total_balance']:,.2f}"
        totals['total_savings_formatted'] = f"₪{totals['total_savings']:,.2f}"
        totals['total_severance_formatted'] = f"₪{totals['total_severance']:,.2f}"
        
        # Contribution analysis
        if contributions:
            total_employee = sum(float(c.get('employee_amount', 0) or 0) for c in contributions)
            total_employer = sum(float(c.get('employer_amount', 0) or 0) for c in contributions)
            total_sev_contrib = sum(float(c.get('severance_amount', 0) or 0) for c in contributions)
            
            totals['contributions'] = {
                'employee_total': total_employee,
                'employer_total': total_employer,
                'severance_total': total_sev_contrib,
                'grand_total': total_employee + total_employer + total_sev_contrib,
                'periods_count': len(contributions),
            }
            
            # Contribution trend
            try:
                sorted_contribs = sorted(contributions, key=lambda x: x.get('period', ''))
                if len(sorted_contribs) >= 2:
                    first = sorted_contribs[0]
                    last = sorted_contribs[-1]
                    first_total = float(first.get('employee_amount', 0) or 0) + float(first.get('employer_amount', 0) or 0)
                    last_total = float(last.get('employee_amount', 0) or 0) + float(last.get('employer_amount', 0) or 0)
                    
                    if last_total > first_total * 1.1:
                        totals['contribution_trend'] = 'increasing'
                        totals['contribution_trend_he'] = 'עולה'
                    elif last_total < first_total * 0.9:
                        totals['contribution_trend'] = 'decreasing'
                        totals['contribution_trend_he'] = 'יורד'
                    else:
                        totals['contribution_trend'] = 'stable'
                        totals['contribution_trend_he'] = 'יציב'
            except:
                pass
        
        # Section 14 status
        section14_accounts = [a for a in accounts if a.get('section14')]
        section14_severance = [s for s in severance if s.get('section14')]
        totals['section14_coverage'] = len(section14_accounts) > 0 or len(section14_severance) > 0
        totals['section14_accounts'] = len(section14_accounts)
        
        # Health score
        totals['health_score'] = self._calculate_health_score(totals)
        
        return data
    
    def _calculate_health_score(self, totals: Dict) -> Dict[str, Any]:
        """Calculate financial health score."""
        score = {
            'overall': 0,
            'savings': 0,
            'diversification': 0,
            'section14': 0,
            'rating': 'unknown',
            'rating_he': 'לא ידוע',
        }
        
        total_balance = totals.get('total_balance', 0)
        provider_count = totals.get('provider_count', 0)
        
        # Savings score
        if total_balance >= 1000000:
            score['savings'] = 100
        elif total_balance >= 500000:
            score['savings'] = 80
        elif total_balance >= 200000:
            score['savings'] = 60
        elif total_balance >= 50000:
            score['savings'] = 40
        else:
            score['savings'] = 20
        
        # Diversification score
        if provider_count >= 3:
            score['diversification'] = 70
        elif provider_count == 2:
            score['diversification'] = 90
        elif provider_count == 1:
            score['diversification'] = 70
        else:
            score['diversification'] = 50
        
        # Section 14 score
        if totals.get('section14_coverage'):
            score['section14'] = 100
        elif totals.get('total_severance', 0) > 0:
            score['section14'] = 70
        else:
            score['section14'] = 50
        
        # Overall
        score['overall'] = int(
            score['savings'] * 0.5 +
            score['diversification'] * 0.2 +
            score['section14'] * 0.3
        )
        
        if score['overall'] >= 80:
            score['rating'] = 'excellent'
            score['rating_he'] = 'מצוין'
        elif score['overall'] >= 60:
            score['rating'] = 'good'
            score['rating_he'] = 'טוב'
        elif score['overall'] >= 40:
            score['rating'] = 'fair'
            score['rating_he'] = 'סביר'
        else:
            score['rating'] = 'needs_attention'
            score['rating_he'] = 'דורש תשומת לב'
        
        return score
    
    def _generate_professional_report(self, data: Dict[str, Any]) -> str:
        """
        Generate professional Hebrew pension portfolio analysis report.
        Format modeled after professional pension analysis reports (ניתוח תיק מקיף).
        
        Sections:
        1. Cover - Client name and report date
        2. Summary - Total savings, deposits, coverage (כמה חסכתי)
        3. Policy Status Table (סטטוס פוליסות)
        4. Detailed Policy List (רשימת תוכניות) 
        5. Savings Breakdown by type (הון/קצבה)
        6. Insurance Coverage Details (הביטוחים וההגנות)
        7. Contribution Details (פירוט הפקדות)
        8. Footer
        """
        lines = []
        header = data.get('header', {})
        client = data.get('client', {})
        accounts = data.get('accounts', [])
        totals = data.get('totals', {})
        contributions = data.get('contributions', [])
        employers = data.get('employers', [])
        
        # Format report date
        report_date = header.get('report_date') or header.get('created_at') or datetime.now().strftime('%Y%m%d')
        year = datetime.now().year
        if len(str(report_date)) >= 8:
            try:
                year = str(report_date)[:4]
            except:
                pass
        
        # Get client info
        client_name = client.get('full_name') or f"{client.get('first_name', '')} {client.get('last_name', '')}".strip() or 'לא זמין'
        id_number = client.get('id_number', '') or 'לא זמין'
        birth_date = client.get('birth_date', '')
        
        # Calculate age
        age = None
        if birth_date and len(str(birth_date)) >= 8:
            try:
                birth_year = int(str(birth_date)[:4])
                age = datetime.now().year - birth_year
            except:
                pass
        
        # Calculate totals from accounts if not provided
        total_balance = totals.get('total_balance', 0)
        total_severance = totals.get('total_severance', 0)
        total_deposits = totals.get('contributions', {}).get('grand_total', 0)
        
        if total_balance == 0 and accounts:
            total_balance = sum(float(a.get('total_balance', 0) or 0) for a in accounts)
        if total_severance == 0 and accounts:
            total_severance = sum(float(a.get('severance_balance', 0) or 0) for a in accounts)
        
        # Calculate total insurance coverage
        total_death = sum(float(a.get('death_coverage', 0) or 0) for a in accounts)
        total_disability = sum(float(a.get('disability_coverage', 0) or 0) for a in accounts)
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 1: COVER PAGE
        # ═══════════════════════════════════════════════════════════════════
        lines.extend([
            "",
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
            "┃                                                                    ┃",
            f"┃                           {client_name}                            ┃",
            f"┃                        {year} ניתוח תיק                           ┃",
            "┃                      ביטוח, פנסיה ופיננסים                         ┃",
            "┃                                                                    ┃",
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            "",
            f"עבור: {client_name} ת.ז {id_number}",
            "",
        ])
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 2: MAIN SUMMARY (כמה חסכתי עד היום)
        # ═══════════════════════════════════════════════════════════════════
        lines.extend([
            "╔══════════════════════════════════════════════════════════════════════╗",
            "║                      כמה חסכתי עד היום?                              ║",
            "╠══════════════════════════════════════════════════════════════════════╣",
            f"║                         ₪{total_balance:,.0f}                        ║",
            "╚══════════════════════════════════════════════════════════════════════╝",
            "",
        ])
        
        # Summary boxes
        lines.extend([
            "┌────────────────────────────┬────────────────────────────┐",
            "│    מהן ההפקדות שלי?        │   מה סך הפיצויים שמגיע לי? │",
            f"│        ₪{total_deposits:,.0f}              │         ₪{total_severance:,.0f}            │",
            "├────────────────────────────┼────────────────────────────┤",
            "│   איזה כיסויים יש לי?      │    כיסוי אובדן כושר        │",
            f"│    ביטוח חיים: ₪{total_death:,.0f}    │      ₪{total_disability:,.0f}/חודש       │",
            "└────────────────────────────┴────────────────────────────┘",
            "",
        ])
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 3: POLICY STATUS TABLE (סטטוס פוליסות)
        # ═══════════════════════════════════════════════════════════════════
        if accounts:
            # Group by type
            savings_policies = [a for a in accounts if float(a.get('total_balance', 0) or 0) > 0]
            risk_policies = [a for a in accounts if float(a.get('total_balance', 0) or 0) == 0 and (float(a.get('death_coverage', 0) or 0) > 0 or float(a.get('disability_coverage', 0) or 0) > 0)]
            
            lines.extend([
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║                         סטטוס פוליסות                                ║",
                "╚══════════════════════════════════════════════════════════════════════╝",
                "",
            ])
            
            # Savings policies table
            if savings_policies:
                lines.extend([
                    "פוליסות ביטוח חיים משולבות חיסכון",
                    "─────────────────────────────────────────────────────────────────────",
                    "מס │ שם חברה         │ שם תוכנית           │ מס' פוליסה   │ וותק      │ סטטוס │ יתרה",
                    "───┼─────────────────┼─────────────────────┼─────────────┼───────────┼───────┼─────────────",
                ])
                
                for i, acct in enumerate(savings_policies, 1):
                    provider = acct.get('provider', '')[:15]
                    product = (acct.get('product_type_name', '') or acct.get('product_type', ''))[:18]
                    policy = str(acct.get('policy_number', ''))[:12]
                    tenure = acct.get('start_date', '')
                    if tenure and len(str(tenure)) >= 8:
                        tenure = f"{str(tenure)[6:8]}/{str(tenure)[4:6]}/{str(tenure)[:4]}"
                    else:
                        tenure = ''
                    status = acct.get('status', 'פעיל')[:6]
                    balance = float(acct.get('total_balance', 0) or 0)
                    
                    lines.append(f"{i:2} │ {provider:<15} │ {product:<19} │ {policy:<11} │ {tenure:<9} │ {status:<5} │ ₪{balance:,.0f}")
                
                lines.append("")
            
            # Risk-only policies
            if risk_policies:
                lines.extend([
                    "פוליסות סיכון טהור (ריסק מוות ו/או פוליסת אכ\"ע)",
                    "─────────────────────────────────────────────────────────────────────",
                ])
                for i, acct in enumerate(risk_policies, 1):
                    provider = acct.get('provider', '')[:15]
                    product = (acct.get('product_type_name', '') or acct.get('product_type', ''))[:18]
                    policy = str(acct.get('policy_number', ''))[:12]
                    status = acct.get('status', 'פעיל')[:6]
                    lines.append(f"{i:2} │ {provider:<15} │ {product:<19} │ {policy:<11} │ {status}")
                lines.append("")
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 4: DETAILED POLICY LIST (רשימת תוכניות)
        # ═══════════════════════════════════════════════════════════════════
        if accounts:
            lines.extend([
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║                        רשימת תוכניות                                 ║",
                "╚══════════════════════════════════════════════════════════════════════╝",
                "",
            ])
            
            for i, acct in enumerate(accounts, 1):
                provider = acct.get('provider', 'לא זמין')
                policy_num = acct.get('policy_number', '')
                product_type = acct.get('product_type_name', '') or acct.get('product_type', '')
                status = acct.get('status', 'פעיל')
                tenure = acct.get('start_date', '')
                
                balance = float(acct.get('total_balance', 0) or 0)
                savings = float(acct.get('savings_balance', 0) or 0)
                severance_bal = float(acct.get('severance_balance', 0) or 0)
                emp_savings = float(acct.get('employee_contribution', 0) or 0)
                emp_sav_employer = float(acct.get('employer_contribution', 0) or 0)
                
                mgmt_fee = float(acct.get('management_fee_savings', 0) or 0)
                mgmt_fee_deposits = float(acct.get('management_fee_deposits', 0) or 0)
                
                death_coverage = float(acct.get('death_coverage', 0) or 0)
                disability_coverage = float(acct.get('disability_coverage', 0) or 0)
                disability_cost = float(acct.get('disability_premium', 0) or 0)
                death_cost = float(acct.get('death_premium', 0) or 0)
                
                employer_name = acct.get('employer_name', '')
                
                # Format tenure
                if tenure and len(str(tenure)) >= 8:
                    tenure = f"{str(tenure)[6:8]}/{str(tenure)[4:6]}/{str(tenure)[:4]}"
                
                lines.extend([
                    f"┌──────────────────────────────────────────────────────────────────────┐",
                    f"│  {i}. פוליסה - {provider}                                            │",
                    f"├──────────────────────────────────────────────────────────────────────┤",
                    f"│  שם תוכנית: {product_type}",
                    f"│  מספר פוליסה: {policy_num}",
                ])
                
                if tenure:
                    lines.append(f"│  וותק: {tenure}")
                lines.append(f"│  סטטוס: {status}")
                
                # Financial data
                lines.append(f"│  ──────────────────────────────────────────────────────────────")
                lines.append(f"│  נתונים כספיים - נוכחיים")
                
                if balance > 0:
                    lines.append(f"│    צבירה: ₪{balance:,.0f}")
                if severance_bal > 0:
                    lines.append(f"│    פיצויים: ₪{severance_bal:,.0f}")
                if savings > 0 and savings != balance:
                    lines.append(f"│    תגמולי עובד: ₪{emp_savings:,.0f}")
                    lines.append(f"│    תגמולי מעביד: ₪{emp_sav_employer:,.0f}")
                
                # Management fees
                if mgmt_fee > 0 or mgmt_fee_deposits > 0:
                    lines.append(f"│")
                    lines.append(f"│  דמי ניהול")
                    if mgmt_fee > 0:
                        lines.append(f"│    ד.ניהול מצבירה: {mgmt_fee:.2f}%")
                    if mgmt_fee_deposits > 0:
                        lines.append(f"│    ד.ניהול מהפקדה: {mgmt_fee_deposits:.2f}%")
                
                # Insurance coverage
                if death_coverage > 0 or disability_coverage > 0:
                    lines.append(f"│  ──────────────────────────────────────────────────────────────")
                    lines.append(f"│  נתוני ביטוח")
                    if death_coverage > 0:
                        cost_str = f" עלות ₪{death_cost:.0f}" if death_cost > 0 else ""
                        lines.append(f"│    ביטוח יסודי (מוות): ₪{death_coverage:,.0f}{cost_str}")
                    if disability_coverage > 0:
                        cost_str = f" עלות ₪{disability_cost:.0f}" if disability_cost > 0 else ""
                        lines.append(f"│    אובדן כושר עבודה: ₪{disability_coverage:,.0f}/חודש{cost_str}")
                
                # Employer
                if employer_name:
                    lines.append(f"│  ──────────────────────────────────────────────────────────────")
                    lines.append(f"│  מעסיק נוכחי: {employer_name}")
                
                # Section 14
                if acct.get('section14') is not None:
                    sec14 = "קיים" if acct.get('section14') else "לא קיים"
                    lines.append(f"│  סעיף 14: {sec14}")
                
                lines.append(f"└──────────────────────────────────────────────────────────────────────┘")
                lines.append("")
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 5: SAVINGS BREAKDOWN (מהכספים שחסכתי - כמה מיועד להון וכמה לקצבה)
        # ═══════════════════════════════════════════════════════════════════
        if accounts and any(float(a.get('total_balance', 0) or 0) > 0 for a in accounts):
            lines.extend([
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║           מהכספים שחסכתי עד היום - כמה מיועד להון וכמה לקצבה?        ║",
                "╚══════════════════════════════════════════════════════════════════════╝",
                "",
                "מס │ שם חברה         │ שם תוכנית           │ קצבה         │ סה\"כ",
                "───┼─────────────────┼─────────────────────┼──────────────┼─────────────",
            ])
            
            total_pension = 0
            for i, acct in enumerate(accounts, 1):
                balance = float(acct.get('total_balance', 0) or 0)
                if balance > 0:
                    provider = acct.get('provider', '')[:15]
                    product = (acct.get('product_type_name', '') or acct.get('product_type', ''))[:18]
                    total_pension += balance
                    lines.append(f"{i:2} │ {provider:<15} │ {product:<19} │ ₪{balance:>10,.0f} │ ₪{balance:>10,.0f}")
            
            lines.append(f"───┴─────────────────┴─────────────────────┴──────────────┴─────────────")
            lines.append(f"                                         סה\"כ: ₪{total_pension:,.0f}")
            lines.append("")
            
            # Balance breakdown by type
            total_savings_comp = sum(float(a.get('savings_balance', 0) or 0) for a in accounts)
            total_sev_comp = sum(float(a.get('severance_balance', 0) or 0) for a in accounts)
            
            if total_savings_comp > 0 or total_sev_comp > 0:
                lines.extend([
                    "יתרות לפי רכיב יתרה",
                    "─────────────────────────────────────────────────────────────────────",
                ])
                if total_savings_comp > 0:
                    lines.append(f"  תגמולים עובד + תגמולים מעביד: ₪{total_savings_comp:,.0f}")
                if total_sev_comp > 0:
                    lines.append(f"  פיצויים: ₪{total_sev_comp:,.0f}")
                lines.append("")
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 6: INSURANCE COVERAGE DETAILS (הביטוחים וההגנות שלי)
        # ═══════════════════════════════════════════════════════════════════
        coverages = [(a, float(a.get('death_coverage', 0) or 0), float(a.get('disability_coverage', 0) or 0)) 
                     for a in accounts if float(a.get('death_coverage', 0) or 0) > 0 or float(a.get('disability_coverage', 0) or 0) > 0]
        
        if coverages:
            lines.extend([
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║                הביטוחים וההגנות שלי - ממה הם מורכבים?                ║",
                "╚══════════════════════════════════════════════════════════════════════╝",
                "",
            ])
            
            # Death coverage section
            death_coverages = [(a, d) for a, d, _ in coverages if d > 0]
            if death_coverages:
                lines.extend([
                    "כיסוי למקרה מוות - במקרה של פטירה הכסף ישולם למוטבים שלך",
                    "─────────────────────────────────────────────────────────────────────",
                    "מס │ תוכנית                              │ סכום כיסוי    │ עלות",
                    "───┼──────────────────────────────────────┼───────────────┼──────────",
                ])
                
                total_death_cover = 0
                total_death_cost = 0
                for i, (acct, death) in enumerate(death_coverages, 1):
                    provider = acct.get('provider', '')[:10]
                    product = (acct.get('product_type_name', '') or acct.get('product_type', ''))[:20]
                    policy = str(acct.get('policy_number', ''))[:10]
                    cost = float(acct.get('death_premium', 0) or 0)
                    desc = f"{provider} {product} {policy}"[:36]
                    
                    total_death_cover += death
                    total_death_cost += cost
                    
                    cost_str = f"₪{cost:.0f}" if cost > 0 else "-"
                    lines.append(f"{i:2} │ {desc:<36} │ ₪{death:>11,.0f} │ {cost_str}")
                
                lines.append(f"───┴──────────────────────────────────────┴───────────────┴──────────")
                lines.append(f"סה\"כ סכום ביטוח מקרה מוות: ₪{total_death_cover:,.0f}  סה\"כ דמי ביטוח: ₪{total_death_cost:.0f}")
                lines.append("")
            
            # Disability coverage section
            disability_coverages = [(a, dis) for a, _, dis in coverages if dis > 0]
            if disability_coverages:
                lines.extend([
                    "אובדן כושר עבודה - פיצוי חודשי שישולם לך במקרה שבו איבדת את היכולת לעבוד",
                    "─────────────────────────────────────────────────────────────────────",
                    "מס │ תוכנית                              │ סכום חודשי   │ עלות",
                    "───┼──────────────────────────────────────┼──────────────┼──────────",
                ])
                
                total_dis_cover = 0
                total_dis_cost = 0
                for i, (acct, dis) in enumerate(disability_coverages, 1):
                    provider = acct.get('provider', '')[:10]
                    product = (acct.get('product_type_name', '') or acct.get('product_type', ''))[:20]
                    policy = str(acct.get('policy_number', ''))[:10]
                    cost = float(acct.get('disability_premium', 0) or 0)
                    desc = f"{provider} {product} {policy}"[:36]
                    
                    total_dis_cover += dis
                    total_dis_cost += cost
                    
                    cost_str = f"₪{cost:.0f}" if cost > 0 else "-"
                    lines.append(f"{i:2} │ {desc:<36} │ ₪{dis:>10,.0f} │ {cost_str}")
                
                lines.append(f"───┴──────────────────────────────────────┴──────────────┴──────────")
                lines.append(f"סה\"כ סכום אכ\"ע: ₪{total_dis_cover:,.0f}/חודש  סה\"כ דמי ביטוח: ₪{total_dis_cost:.0f}")
                lines.append("")
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 7: CONTRIBUTION STRUCTURE (מבנה הפרשות)
        # ═══════════════════════════════════════════════════════════════════
        if accounts:
            lines.extend([
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║                          מבנה הפרשות                                 ║",
                "╚══════════════════════════════════════════════════════════════════════╝",
                "",
                "מס │ תוכנית                    │ מעסיק/שכר          │ פיצויים │ תגמולים עובד │ תגמולים מעביד",
                "───┼────────────────────────────┼────────────────────┼─────────┼──────────────┼──────────────",
            ])
            
            for i, acct in enumerate(accounts, 1):
                provider = acct.get('provider', '')[:10]
                product = (acct.get('product_type_name', '') or '')[:12]
                policy = str(acct.get('policy_number', ''))
                employer = acct.get('employer_name', '')[:18]
                
                sev_rate = acct.get('severance_rate', '')
                emp_rate = acct.get('employee_rate', '')
                empr_rate = acct.get('employer_rate', '')
                
                desc = f"{provider} {product}"[:26]
                
                sev_str = f"{sev_rate}%" if sev_rate else "-"
                emp_str = f"{emp_rate}%" if emp_rate else "-"
                empr_str = f"{empr_rate}%" if empr_rate else "-"
                
                lines.append(f"{i:2} │ {desc:<26} │ {employer:<18} │ {sev_str:>7} │ {emp_str:>12} │ {empr_str}")
            
            lines.append("")
        
        # ═══════════════════════════════════════════════════════════════════
        # SECTION 8: EMPLOYER DETAILS (פרטי מעסיקים)
        # ═══════════════════════════════════════════════════════════════════
        employer_names = list(set(a.get('employer_name', '') for a in accounts if a.get('employer_name')))
        if employer_names or employers:
            lines.extend([
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║                         פרטי מעסיקים                                 ║",
                "╚══════════════════════════════════════════════════════════════════════╝",
                "",
            ])
            
            for i, emp in enumerate(employer_names or [e.get('name', '') for e in employers], 1):
                if emp:
                    lines.append(f"  {i}. {emp}")
            
            lines.append("")
        
        # ═══════════════════════════════════════════════════════════════════
        # FOOTER
        # ═══════════════════════════════════════════════════════════════════
        lines.extend([
            "╔══════════════════════════════════════════════════════════════════════╗",
            "║                            הערות                                     ║",
            "╚══════════════════════════════════════════════════════════════════════╝",
            "",
            "ט.ל.ח. הנתונים המוצגים הינם לאחר עיבוד ממוחשב",
            "הנתונים הקובעים הנם בהתאם לנתונים הרשומים בחברות המנהלות ובהתאם לתנאי",
            "התוכניות בפועל ובכפוף להחלטת הגופים המנהלים.",
            "",
            "ככל שיש אי התאמה בין הנתונים המופיעים בדו\"ח זה לבין החברות המנהלות,",
            "האחרונים יהיו הקובעים.",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"מסמך זה הופק על ידי PHINS - פלטפורמת ניהול פנסיה וביטוח",
            f"עבור: {client_name} ת.ז {id_number}",
            f"תאריך הפקת הדו\"ח: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            f"מקור נתונים: מסלקת הביטוח והפנסיה",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ])
        
        return '\n'.join(lines)
    
    def _generate_recommendations(self, data: Dict, totals: Dict, health: Dict) -> List[Dict]:
        """Generate AI recommendations based on comprehensive data analysis."""
        recommendations = []
        
        total_balance = totals.get('total_balance', 0)
        provider_count = totals.get('provider_count', 0)
        section14 = totals.get('section14_coverage', False)
        accounts = data.get('accounts', [])
        
        # Low savings warning
        if total_balance < 100000:
            recommendations.append({
                'priority': 'high',
                'title': 'הגדלת החיסכון הפנסיוני',
                'description': 'החיסכון הנוכחי נמוך מהמומלץ. שקול להגדיל את אחוזי ההפקדה או להפקיד סכומים נוספים באופן עצמאי.'
            })
        
        # Too many providers - consolidation
        if provider_count > 3:
            recommendations.append({
                'priority': 'medium',
                'title': 'איחוד חשבונות פנסיה',
                'description': f'יש לך חשבונות ב-{provider_count} יצרנים שונים. איחוד יכול להפחית דמי ניהול ולפשט את הניהול והמעקב.'
            })
        
        # No Section 14 coverage
        if not section14 and totals.get('total_severance', 0) > 0:
            recommendations.append({
                'priority': 'high',
                'title': 'בדיקת סעיף 14',
                'description': 'מומלץ לבדוק אפשרות להסדר סעיף 14 עם המעסיק להבטחת כספי הפיצויים והגנה במקרה של עזיבה.'
            })
        
        # Check for inactive accounts
        inactive_accounts = [a for a in accounts if a.get('status_en') in ['Frozen', 'Closed', 'Transferred']]
        if inactive_accounts:
            recommendations.append({
                'priority': 'medium',
                'title': 'בדיקת חשבונות לא פעילים',
                'description': f'נמצאו {len(inactive_accounts)} חשבונות לא פעילים. מומלץ לבדוק את מצבם ולשקול העברה או איחוד.'
            })
        
        # High management fees check
        high_fee_accounts = [a for a in accounts if float(a.get('management_fee_savings', 0) or 0) > 1.0]
        if high_fee_accounts:
            recommendations.append({
                'priority': 'medium',
                'title': 'בדיקת דמי ניהול גבוהים',
                'description': f'{len(high_fee_accounts)} חשבונות עם דמי ניהול מעל 1%. מומלץ לבדוק ולהשוות מול הצעות מתחרות.'
            })
        
        # Good standing message
        if health.get('overall', 0) >= 70:
            recommendations.append({
                'priority': 'low',
                'title': 'המשך מעקב שוטף',
                'description': 'המצב הפיננסי טוב. המשך לעקוב אחר ההפקדות ובצע בדיקה שנתית של תנאי הקופות.'
            })
        
        # Always recommend annual review
        recommendations.append({
            'priority': 'low',
            'title': 'בדיקה שנתית מקיפה',
            'description': 'מומלץ לבצע בדיקה שנתית של כל הקופות, להשוות דמי ניהול ותשואות, ולעדכן מוטבים.'
        })
        
        return recommendations[:6]
    
    def _mask_id(self, id_number: str) -> str:
        """Mask ID number for privacy."""
        if not id_number or len(id_number) < 5:
            return id_number or '***'
        return id_number[:2] + '*' * (len(id_number) - 4) + id_number[-2:]
    

    def to_csv_format(self, data: Dict[str, Any]) -> Tuple[List[str], List[Dict]]:
        """Convert to CSV format for AI analysis integration."""
        columns = [
            'מספר פוליסה', 'יצרן', 'סוג מוצר', 'שם מוצר',
            'סטטוס', 'יתרה כוללת', 'חיסכון', 'פיצויים', 'מעסיק', 'סעיף 14'
        ]
        
        rows = []
        for acct in data.get('accounts', []):
            rows.append({
                'מספר פוליסה': acct.get('policy_number', ''),
                'יצרן': acct.get('provider', ''),
                'סוג מוצר': acct.get('product_type_name', acct.get('product_type', '')),
                'שם מוצר': acct.get('product_name', ''),
                'סטטוס': acct.get('status', 'פעיל'),
                'יתרה כוללת': acct.get('total_balance', 0),
                'חיסכון': acct.get('savings_balance', 0),
                'פיצויים': acct.get('severance_balance', 0),
                'מעסיק': acct.get('employer_name', ''),
                'סעיף 14': 'כן' if acct.get('section14') else 'לא'
            })
        
        # Summary row
        totals = data.get('totals', {})
        rows.append({
            'מספר פוליסה': 'סה״כ',
            'יצרן': '',
            'סוג מוצר': '',
            'שם מוצר': '',
            'סטטוס': '',
            'יתרה כוללת': totals.get('total_balance', 0),
            'חיסכון': totals.get('total_savings', 0),
            'פיצויים': totals.get('total_severance', 0),
            'מעסיק': '',
            'סעיף 14': ''
        })
        
        return columns, rows
    
    def generate_report_text(self, data: Dict[str, Any], language: str = 'hebrew') -> str:
        """Generate report text (alias for compatibility)."""
        return self._generate_professional_report(data)


__all__ = ['PensionReportMixin']
