"""Risk Reports chart configs (B9).

Charts are *data configurations* (labels, values, thresholds) rendered by the
dashboard in the browser; the service never rasterises anything. Building them
is a few hundred microseconds on the pension fixture (measured in
``tests/test_risk_reports_package.py``), so they are produced eagerly with the
report rather than lazily on view.
"""

from typing import Any, Dict, List, Optional
from services.risk_reports.models import AnalysisResult, ChartConfig, ChartType
from services.risk_reports.pdf_export import classify_cover_type


def _currency_payload(labels, values) -> Dict[str, Any]:
    """Slice labels plus their sum, so the dashboard can show the affiliated total."""
    amounts = [round(float(value or 0), 2) for value in values]
    return {
        'labels': list(labels),
        'values': amounts,
        'total': round(sum(amounts), 2),
    }


def _reconciled_breakdown(stored: Any, expected: float) -> Optional[Dict[str, float]]:
    """Use the assessment's own concentration when its slices already sum to צבירה."""
    if not isinstance(stored, dict) or not stored:
        return None
    cleaned = {
        str(name): round(float(amount or 0), 2)
        for name, amount in stored.items()
        if float(amount or 0) > 0
    }
    if not cleaned or expected <= 0:
        return None
    if abs(sum(cleaned.values()) - float(expected)) < 0.05:
        return cleaned
    return None


class ChartsMixin:
    """Chart configuration builders."""

    def _build_savings_cover_id_charts(
        self,
        summary: Optional[Dict[str, Any]],
        lang_code: str,
        include_id_coverage: bool = True,
    ) -> List[ChartConfig]:
        """Generate supplementary charts focused on savings, cover and ID availability."""
        if not summary:
            return []

        charts: List[ChartConfig] = []
        is_hebrew = lang_code == 'hebrew'
        total_savings = float(summary.get('total_savings', 0) or 0)
        total_cover = float(summary.get('total_cover', 0) or 0)
        records_analyzed = int(summary.get('records_analyzed', 0) or 0)
        id_rows = int(summary.get('id_row_coverage', 0) or 0)

        if total_savings > 0 or total_cover > 0:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='חיסכון מול כיסוי' if is_hebrew else 'Savings vs Cover',
                data=_currency_payload(
                    ['חיסכון' if is_hebrew else 'Savings', 'כיסוי' if is_hebrew else 'Cover'],
                    [total_savings, total_cover],
                ),
                options={
                    'colors': ['#10b981', '#1a237e'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))

        if include_id_coverage and records_analyzed > 0:
            missing_ids = max(records_analyzed - id_rows, 0)
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='כיסוי שדות זיהוי' if is_hebrew else 'ID Field Coverage',
                data={
                    'labels': ['כולל מזהה' if is_hebrew else 'With ID', 'ללא מזהה' if is_hebrew else 'Without ID'],
                    'values': [id_rows, missing_ids]
                },
                options={'colors': ['#3b82f6', '#cbd5e1']}
            ))

        return charts


    def _generate_charts(
        self,
        analysis: AnalysisResult,
        pension_data: Dict = None,
        doc_data: Dict[str, Any] = None,
        savings_cover_id_summary: Dict[str, Any] = None
    ) -> List[ChartConfig]:
        """
        Generate chart configurations.
        
        For pension data, generates meaningful financial charts:
        - Cumulative savings by provider
        - Savings vs Severance breakdown
        - Insurance coverage breakdown
        """
        charts = []
        
        if savings_cover_id_summary is None:
            savings_cover_id_summary = self._extract_savings_cover_id_summary(doc_data, pension_data)

        # Check if we have pension data for specialized charts
        if pension_data:
            charts.extend(self._generate_pension_charts(pension_data, analysis.language))
            # Savings vs cover is assessment data; skip the ID-coverage doughnut
            # (that is a statistical completeness view, not the assessment).
            charts.extend(self._build_savings_cover_id_charts(
                savings_cover_id_summary, analysis.language, include_id_coverage=False
            ))
            return charts
        
        # Risk Score Gauge (for non-pension data)
        charts.append(ChartConfig(
            type=ChartType.GAUGE,
            title='Risk Score',
            data={
                'value': analysis.risk_score,
                'min': 0,
                'max': 100,
                'thresholds': [30, 60, 80]
            },
            options={'colors': ['#4caf50', '#ffeb3b', '#ff9800', '#f44336']}
        ))
        
        # Factors Importance Bar Chart - only for meaningful factors
        meaningful_factors = [f for f in analysis.extracted_factors[:8] 
                            if f.category in ['domain', 'currency', 'financial']]
        if meaningful_factors:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='Factors Importance',
                data={
                    'labels': [f.name for f in meaningful_factors],
                    'values': [f.importance * 100 for f in meaningful_factors]
                },
                options={'horizontal': True}
            ))
        
        # Data Distribution Pie Chart - only meaningful totals
        if analysis.key_metrics:
            # Filter to only financial totals, not counts
            financial_metrics = {k: v for k, v in analysis.key_metrics.items() 
                               if isinstance(v, (int, float)) and 
                               (k.endswith('_total') or 'balance' in k.lower() or 
                                'savings' in k.lower() or 'coverage' in k.lower()) and
                               v > 0}
            if financial_metrics:
                charts.append(ChartConfig(
                    type=ChartType.PIE,
                    title='Data Distribution',
                    data={
                        'labels': list(financial_metrics.keys())[:6],
                        'values': list(financial_metrics.values())[:6]
                    }
                ))

        charts.extend(self._build_savings_cover_id_charts(savings_cover_id_summary, analysis.language))
        
        return charts
    
    def _generate_pension_charts(self, pension_data: Dict, lang_code: str) -> List[ChartConfig]:
        """
        Generate specialized charts for pension/Mislaka data.
        
        Creates meaningful visualizations:
        1. Cumulative savings by provider (bar chart)
        2. Savings vs Severance breakdown (doughnut)
        3. Insurance coverage breakdown (pie chart)
        """
        charts = []
        is_hebrew = lang_code == 'hebrew'
        
        totals = pension_data.get('totals', {})
        accounts = pension_data.get('accounts', [])
        
        from services.pension.schema import (
            account_accumulation,
            accumulation_by_product,
            accumulation_by_provider,
            death_lump_sum,
            deduped_sum,
            money_close,
            parse_money,
            severance_sum,
            tagmulim_amount,
        )

        tzvira = float((totals or {}).get('total_balance') or 0)
        if tzvira <= 0:
            tzvira = deduped_sum(accounts, account_accumulation)

        # 1. צבירה לפי יצרן. Prefer the assessment breakdown when it sums to צבירה.
        provider_totals = _reconciled_breakdown((totals or {}).get('by_provider'), tzvira)
        if not provider_totals:
            provider_totals = accumulation_by_provider(accounts)
        
        if provider_totals:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='צבירה לפי יצרן' if is_hebrew else 'Savings by Provider',
                data=_currency_payload(list(provider_totals.keys()), list(provider_totals.values())),
                options={
                    'horizontal': False,
                    'colors': ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 2. תגמולים מול פיצויים. פיצויים includes affiliated pitzuim pots.
        # An explicit תגמולים column is kept. Otherwise a savings figure that
        # is the whole צבירה is not relabelled as תגמולים; the slice is
        # צבירה minus the פיצויים already inside it.
        explicit_tagmulim = deduped_sum(accounts, lambda account: account.get('tagmulim_balance'))
        inferred_tagmulim = deduped_sum(accounts, tagmulim_amount)
        account_severance = severance_sum(accounts)
        stored_severance = float((totals or {}).get('total_severance') or (totals or {}).get('total_severance_balance') or 0)
        total_severance = stored_severance if stored_severance > account_severance + 0.02 else account_severance
        if explicit_tagmulim > 0:
            total_tagmulim = explicit_tagmulim
        elif inferred_tagmulim > 0 and tzvira > 0 and inferred_tagmulim < tzvira - 0.02 and not money_close(inferred_tagmulim, tzvira):
            total_tagmulim = inferred_tagmulim
        elif account_severance > 0 and tzvira + 0.02 >= account_severance:
            total_tagmulim = round(tzvira - account_severance, 2)
        else:
            total_tagmulim = 0.0
        
        if total_tagmulim > 0 or total_severance > 0:
            labels = ['תגמולים', 'פיצויים'] if is_hebrew else ['Savings', 'Severance']
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='תגמולים מול פיצויים' if is_hebrew else 'Savings vs Severance',
                data=_currency_payload(labels, [total_tagmulim, total_severance]),
                options={
                    'colors': ['#4CAF50', '#FF9800'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 3. Insurance Coverage Breakdown (Pie Chart)
        coverage_totals = {}
        cost_totals = {}
        cover_fields = (
            ('death_coverage', 'death_premium', 'ביטוח למקרה מוות', 'Death Cover', 'life'),
            ('disability_coverage', 'disability_premium', 'אבדן כושר עבודה', 'Loss of Work Capacity', 'disability_work'),
            ('work_disability_coverage', 'work_disability_premium', 'אבדן כושר עבודה', 'Loss of Work Capacity', 'disability_work'),
            ('invalidity_coverage', 'invalidity_premium', 'נכות', 'Disability', 'invalidity'),
            ('waiver_coverage', 'waiver_premium', 'שחרור', 'Premium Waiver', 'waiver'),
            ('survivors_coverage', 'survivors_premium', 'שארים', 'Survivors', 'survivors'),
            ('ltc_coverage', 'ltc_premium', 'סיעוד', 'Long-Term Care', 'ltc'),
        )
        seen_cover_amounts = set()
        seen_cover_costs = set()
        life_label = 'ביטוח למקרה מוות' if is_hebrew else 'Death Cover'
        for acct in accounts:
            policy = str(acct.get('policy_number') or '')
            lump = death_lump_sum(acct)
            if lump > 0:
                amount_key = (policy, life_label, round(lump, 2))
                if amount_key not in seen_cover_amounts:
                    seen_cover_amounts.add(amount_key)
                    coverage_totals[life_label] = coverage_totals.get(life_label, 0) + lump
            death_cost = parse_money(acct.get('death_premium'))
            if death_cost > 0:
                cost_key = (policy, life_label, round(death_cost, 2))
                if cost_key not in seen_cover_costs:
                    seen_cover_costs.add(cost_key)
                    cost_totals[life_label] = cost_totals.get(life_label, 0) + death_cost
            nested_types = set()
            for item in (acct.get('risk_covers') or []):
                if not isinstance(item, dict):
                    continue
                type_key, title_he, title_en = classify_cover_type(item.get('code'), item.get('name'))
                if type_key == 'life':
                    # Nested סכום ביטוח כולל can be צבירה + כיסוי. The life
                    # slice is the סכום חד פעמי already taken above.
                    nested_types.add(type_key)
                    continue
                nested_types.add(type_key)
                amount = float(item.get('amount') or 0)
                cost = float(item.get('cost') or 0)
                label = title_he if is_hebrew else title_en
                amount_key = (policy, label, round(amount, 2))
                cost_key = (policy, label, round(cost, 2))
                if amount > 0 and amount_key not in seen_cover_amounts:
                    seen_cover_amounts.add(amount_key)
                    coverage_totals[label] = coverage_totals.get(label, 0) + amount
                if cost > 0 and cost_key not in seen_cover_costs:
                    seen_cover_costs.add(cost_key)
                    cost_totals[label] = cost_totals.get(label, 0) + cost
            for amount_field, cost_field, he_label, en_label, type_key in cover_fields:
                if type_key == 'life' or type_key in nested_types:
                    continue
                amount = float(acct.get(amount_field) or 0)
                cost = float(acct.get(cost_field) or 0)
                label = he_label if is_hebrew else en_label
                amount_key = (policy, label, round(amount, 2))
                cost_key = (policy, label, round(cost, 2))
                if amount > 0 and amount_key not in seen_cover_amounts:
                    seen_cover_amounts.add(amount_key)
                    coverage_totals[label] = coverage_totals.get(label, 0) + amount
                if cost > 0 and cost_key not in seen_cover_costs:
                    seen_cover_costs.add(cost_key)
                    cost_totals[label] = cost_totals.get(label, 0) + cost
        
        if coverage_totals:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='כיסויים ביטוחיים' if is_hebrew else 'Insurance Coverage',
                data=_currency_payload(list(coverage_totals.keys()), list(coverage_totals.values())),
                options={
                    'colors': ['#E91E63', '#3F51B5', '#009688', '#795548', '#607D8B', '#FF5722'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        if cost_totals:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='עלות הכיסויים' if is_hebrew else 'Cover Costs',
                data=_currency_payload(list(cost_totals.keys()), list(cost_totals.values())),
                options={
                    'colors': ['#c9a04e', '#0e2f63'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 4. Official Mislaka product-family concentration (always, even one type)
        product_balances = _reconciled_breakdown((totals or {}).get('by_product'), tzvira)
        if not product_balances:
            product_balances = accumulation_by_product(accounts)

        if product_balances:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='ריכוז סכומי הצבירה לפי סוגי המוצרים' if is_hebrew else 'Accumulation by Product Type',
                data=_currency_payload(list(product_balances.keys()), list(product_balances.values())),
                options={
                    'colors': ['#009688', '#795548', '#607D8B', '#FF5722', '#673AB7'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 5. Total Summary Gauge (if we have total balance)
        total_balance = totals.get('total_balance', 0)
        if not total_balance:
            total_balance = sum(a.get('total_balance', 0) or 0 for a in accounts)
        
        if total_balance > 0:
            charts.append(ChartConfig(
                type=ChartType.GAUGE,
                title='סה״כ חיסכון' if is_hebrew else 'Total Savings',
                data={
                    'value': total_balance,
                    'display_value': f'₪{total_balance:,.0f}',
                    'min': 0,
                    'max': total_balance * 1.2,  # 20% headroom
                    'thresholds': [total_balance * 0.25, total_balance * 0.5, total_balance * 0.75]
                },
                options={
                    'colors': ['#ffeb3b', '#8BC34A', '#4CAF50', '#2196F3'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        return charts

