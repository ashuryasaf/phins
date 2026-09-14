"""``ClientProfile`` — the aggregate of every Mislaka file in a ZIP.

Moved verbatim from ``services/pension_data_agent.py`` (B5).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class ClientProfile:
    """
    Aggregated client profile containing all data from multiple Mislaka sources.
    Used for ZIP files containing multiple XML files.
    """
    # Basic client info
    client_name: str = ""
    client_id: str = ""
    id_type: str = ""
    birth_date: str = ""
    gender: str = ""
    address: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    
    # Accounts and holdings
    accounts: List[Dict] = field(default_factory=list)
    
    # Severance details
    severance_balance: float = 0.0
    section14: bool = False
    section14_date: str = ""
    
    # Contributions/events
    contributions: List[Dict] = field(default_factory=list)
    events: List[Dict] = field(default_factory=list)
    
    # Employers
    employers: Set[str] = field(default_factory=set)
    
    # Providers
    providers: Set[str] = field(default_factory=set)
    
    # Derived metrics
    total_balance: float = 0.0
    total_savings: float = 0.0
    total_severance: float = 0.0
    total_coverage: float = 0.0
    
    # Metadata
    last_update: str = ""
    file_count: int = 0
    interface_types: Set[str] = field(default_factory=set)
    
    # Anomalies/alerts
    anomalies: List[str] = field(default_factory=list)
    
    def merge_data(self, data: Dict[str, Any]):
        """Merge data from a single parsed file into this profile."""
        # Merge client info
        client = data.get('client', {})
        if client:
            if isinstance(client, list) and client:
                client = client[0]
            
            if client.get('id_number'):
                if self.client_id and self.client_id != client['id_number']:
                    self.anomalies.append(f"ID mismatch: {self.client_id} vs {client['id_number']}")
                else:
                    self.client_id = client['id_number']
            
            if client.get('full_name'):
                self.client_name = client['full_name']
            elif client.get('first_name') or client.get('last_name'):
                self.client_name = f"{client.get('first_name', '')} {client.get('last_name', '')}".strip()
            
            if client.get('id_type'):
                self.id_type = client['id_type']
            if client.get('birth_date'):
                self.birth_date = client['birth_date']
            if client.get('phone'):
                self.phone = client['phone']
            if client.get('email'):
                self.email = client['email']
        
        # Merge accounts
        for acct in data.get('accounts', []):
            self.accounts.append(acct)
            if acct.get('provider'):
                self.providers.add(acct['provider'])
            if acct.get('employer_name'):
                self.employers.add(acct['employer_name'])
        
        # Merge contributions
        for contrib in data.get('contributions', []):
            self.contributions.append(contrib)
            if contrib.get('employer_name'):
                self.employers.add(contrib['employer_name'])
        
        # Merge severance
        for sev in data.get('severance', []):
            if sev.get('total_severance'):
                self.severance_balance += float(sev['total_severance'] or 0)
            if sev.get('section14'):
                self.section14 = True
            if sev.get('employer_name'):
                self.employers.add(sev['employer_name'])
        
        # Merge providers from providers list
        for prov in data.get('providers', []):
            if prov.get('name'):
                self.providers.add(prov['name'])
        
        # Update metadata
        header = data.get('header', {})
        if header.get('report_date') or header.get('created_at'):
            file_date = header.get('report_date') or header.get('created_at')
            if not self.last_update or file_date > self.last_update:
                self.last_update = file_date
        
        if data.get('interface_type'):
            self.interface_types.add(data['interface_type'])
        
        self.file_count += 1
    
    def finalize(self):
        """Compute derived totals after all merges."""
        self.total_balance = 0.0
        self.total_savings = 0.0
        self.total_severance = 0.0
        self.total_coverage = 0.0
        
        for acct in self.accounts:
            self.total_balance += float(acct.get('total_balance', 0) or 0)
            self.total_savings += float(acct.get('savings_balance', 0) or 0)
            self.total_severance += float(acct.get('severance_balance', 0) or 0)
            self.total_coverage += float(acct.get('coverage_amount', 0) or 0)
            
            # Check for Section 14
            if acct.get('section14'):
                self.section14 = True
        
        # Add external severance balance
        self.total_severance += self.severance_balance
        
        # Check for anomalies
        if self.total_balance < 0:
            self.anomalies.append("Total balance is negative")
        if not self.accounts:
            self.anomalies.append("No accounts found")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'client': {
                'full_name': self.client_name,
                'id_number': self.client_id,
                'id_type': self.id_type,
                'birth_date': self.birth_date,
                'phone': self.phone,
                'email': self.email,
            },
            'accounts': self.accounts,
            'contributions': self.contributions,
            'severance': [{
                'total_severance': self.total_severance,
                'section14': self.section14,
            }],
            'providers': list(self.providers),
            'employers': list(self.employers),
            'totals': {
                'total_balance': self.total_balance,
                'total_balance_formatted': f"₪{self.total_balance:,.2f}",
                'total_savings': self.total_savings,
                'total_savings_formatted': f"₪{self.total_savings:,.2f}",
                'total_severance': self.total_severance,
                'total_severance_formatted': f"₪{self.total_severance:,.2f}",
                'total_coverage': self.total_coverage,
                'account_count': len(self.accounts),
                'provider_count': len(self.providers),
                'providers': list(self.providers),
                'section14_coverage': self.section14,
            },
            'header': {
                'report_date': self.last_update,
                'file_count': self.file_count,
                'interface_types': list(self.interface_types),
            },
            'anomalies': self.anomalies,
        }


__all__ = ['ClientProfile']
