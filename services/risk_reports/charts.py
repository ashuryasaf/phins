"""Risk Reports chart configs (B9).

Charts are *data configurations* (labels, values, thresholds) rendered by the
dashboard in the browser; the service never rasterises anything. Building them
is a few hundred microseconds on the pension fixture (measured in
``tests/test_risk_reports_package.py``), so they are produced eagerly with the
report rather than lazily on view.
"""

from typing import Any, Dict, List, Optional
from services.risk_reports.models import AnalysisResult, ChartConfig, ChartType


class ChartsMixin:
    """Chart configuration builders."""

    def _build_savings_cover_id_charts(
        self,
        summary: Optional[Dict[str, Any]],
        lang_code: str
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
                data={
                    'labels': ['חיסכון' if is_hebrew else 'Savings', 'כיסוי' if is_hebrew else 'Cover'],
                    'values': [total_savings, total_cover]
                },
                options={
                    'colors': ['#10b981', '#1a237e'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))

        if records_analyzed > 0:
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
            charts.extend(self._build_savings_cover_id_charts(savings_cover_id_summary, analysis.language))
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
        
        # 1. Cumulative Savings by Provider (Bar Chart)
        provider_totals = {}
        for acct in accounts:
            provider = acct.get('provider', 'לא ידוע' if is_hebrew else 'Unknown')
            balance = acct.get('total_balance', 0) or acct.get('savings_balance', 0) or 0
            if provider and balance > 0:
                provider_totals[provider] = provider_totals.get(provider, 0) + balance
        
        if provider_totals:
            charts.append(ChartConfig(
                type=ChartType.BAR,
                title='צבירה לפי יצרן' if is_hebrew else 'Savings by Provider',
                data={
                    'labels': list(provider_totals.keys()),
                    'values': list(provider_totals.values())
                },
                options={
                    'horizontal': False,
                    'colors': ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 2. Savings vs Severance Breakdown (Doughnut Chart)
        total_savings = totals.get('total_savings_balance', 0)
        total_severance = totals.get('total_severance_balance', 0)
        
        if not total_savings and not total_severance:
            # Calculate from accounts
            total_savings = sum(a.get('savings_balance', 0) or 0 for a in accounts)
            total_severance = sum(a.get('severance_balance', 0) or 0 for a in accounts)
        
        if total_savings > 0 or total_severance > 0:
            labels = ['תגמולים', 'פיצויים'] if is_hebrew else ['Savings', 'Severance']
            charts.append(ChartConfig(
                type=ChartType.DOUGHNUT,
                title='תגמולים מול פיצויים' if is_hebrew else 'Savings vs Severance',
                data={
                    'labels': labels,
                    'values': [total_savings, total_severance]
                },
                options={
                    'colors': ['#4CAF50', '#FF9800'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 3. Insurance Coverage Breakdown (Pie Chart)
        coverage_totals = {}
        for acct in accounts:
            death_coverage = acct.get('death_coverage', 0) or 0
            disability_coverage = acct.get('disability_coverage', 0) or 0
            
            if death_coverage > 0:
                label = 'ביטוח חיים' if is_hebrew else 'Life Insurance'
                coverage_totals[label] = coverage_totals.get(label, 0) + death_coverage
            if disability_coverage > 0:
                label = 'אובדן כושר' if is_hebrew else 'Disability'
                coverage_totals[label] = coverage_totals.get(label, 0) + disability_coverage
        
        if coverage_totals:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='כיסויים ביטוחיים' if is_hebrew else 'Insurance Coverage',
                data={
                    'labels': list(coverage_totals.keys()),
                    'values': list(coverage_totals.values())
                },
                options={
                    'colors': ['#E91E63', '#3F51B5'],
                    'currency': True,
                    'currency_symbol': '₪'
                }
            ))
        
        # 4. Product Type Distribution (Pie Chart)
        product_balances = {}
        for acct in accounts:
            product_type = acct.get('product_type_name', '') or acct.get('product_type', '')
            if not product_type:
                product_type = 'לא מוגדר' if is_hebrew else 'Undefined'
            balance = acct.get('total_balance', 0) or acct.get('savings_balance', 0) or 0
            if balance > 0:
                product_balances[product_type] = product_balances.get(product_type, 0) + balance
        
        if product_balances and len(product_balances) > 1:
            charts.append(ChartConfig(
                type=ChartType.PIE,
                title='צבירה לפי סוג מוצר' if is_hebrew else 'Savings by Product Type',
                data={
                    'labels': list(product_balances.keys()),
                    'values': list(product_balances.values())
                },
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

