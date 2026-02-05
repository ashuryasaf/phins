"""
Mislaka API Integration Service
================================
Integrates with the Israeli Insurance & Pension Clearinghouse (מסלקה)
API at https://mislaka-api.co.il/api

This service provides access to:
- Insurance policy information
- Pension fund data
- Provident fund (קופות גמל) details
- Life insurance policies
- Health insurance data

Author: PHINS Platform
"""

import json
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import base64
import os

# Try to import requests, handle if not available
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class MislakaProductType(Enum):
    """Types of financial products available through Mislaka"""
    PENSION = "pension"  # קרן פנסיה
    PROVIDENT = "provident"  # קופת גמל
    EDUCATION_FUND = "education_fund"  # קרן השתלמות
    LIFE_INSURANCE = "life_insurance"  # ביטוח חיים
    HEALTH_INSURANCE = "health_insurance"  # ביטוח בריאות
    MANAGERS_INSURANCE = "managers_insurance"  # ביטוח מנהלים
    SAVINGS = "savings"  # חיסכון
    ALL = "all"


class MislakaStatus(Enum):
    """Status codes for Mislaka API responses"""
    SUCCESS = "success"
    PENDING = "pending"
    ERROR = "error"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"


@dataclass
class MislakaPolicy:
    """Represents an insurance/pension policy from Mislaka"""
    policy_id: str
    policy_number: str
    product_type: str
    company_name: str
    company_code: str
    start_date: str
    status: str
    premium_monthly: float = 0.0
    cover_amount: float = 0.0
    accumulated_value: float = 0.0
    management_fee_percent: float = 0.0
    investment_track: str = ""
    beneficiaries: List[str] = None
    last_update: str = ""
    
    def __post_init__(self):
        if self.beneficiaries is None:
            self.beneficiaries = []


@dataclass
class MislakaPerson:
    """Represents a person's identity for Mislaka queries"""
    id_number: str  # תעודת זהות
    first_name: str = ""
    last_name: str = ""
    birth_date: str = ""
    phone: str = ""
    email: str = ""


@dataclass 
class MislakaQueryResult:
    """Result of a Mislaka API query"""
    request_id: str
    status: MislakaStatus
    timestamp: str
    person: MislakaPerson
    policies: List[MislakaPolicy]
    total_policies: int
    total_accumulated: float
    total_monthly_premium: float
    error_message: str = ""
    raw_response: Dict = None


class MislakaAPIService:
    """
    Service for integrating with the Mislaka API.
    
    The Mislaka (מסלקה) is Israel's insurance and pension information
    clearinghouse, providing centralized access to policy data.
    """
    
    BASE_URL = "https://mislaka-api.co.il/api"
    
    # API Endpoints
    ENDPOINTS = {
        'auth': '/auth/token',
        'policies': '/policies',
        'policy_details': '/policies/{policy_id}',
        'person_policies': '/person/{id_number}/policies',
        'pension': '/pension',
        'provident': '/provident',
        'insurance': '/insurance',
        'summary': '/person/{id_number}/summary',
        'companies': '/companies',
        'products': '/products',
    }
    
    # Israeli Insurance Company Codes
    COMPANY_CODES = {
        '01': 'מגדל',
        '02': 'הראל',
        '03': 'כלל',
        '04': 'הפניקס',
        '05': 'מנורה מבטחים',
        '06': 'איילון',
        '07': 'הכשרה',
        '08': 'שלמה',
        '09': 'אלטשולר שחם',
        '10': 'מיטב דש',
        '11': 'אנליסט',
        '12': 'פסגות',
        '13': 'מור',
        '14': 'ילין לפידות',
    }
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """
        Initialize the Mislaka API service.
        
        Args:
            api_key: API key for authentication (or from env MISLAKA_API_KEY)
            api_secret: API secret for signing requests (or from env MISLAKA_API_SECRET)
        """
        self.api_key = api_key or os.environ.get('MISLAKA_API_KEY', '')
        self.api_secret = api_secret or os.environ.get('MISLAKA_API_SECRET', '')
        self.access_token = None
        self.token_expires = None
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes cache
    
    def is_configured(self) -> bool:
        """Check if API credentials are configured"""
        return bool(self.api_key and self.api_secret)
    
    def _get_headers(self, include_auth: bool = True) -> Dict[str, str]:
        """Get request headers"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': 'PHINS-Platform/1.0',
        }
        
        if include_auth and self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        
        return headers
    
    def _sign_request(self, payload: Dict) -> str:
        """Create HMAC signature for request"""
        if not self.api_secret:
            return ""
        
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            payload_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _make_request(self, method: str, endpoint: str, 
                      data: Dict = None, params: Dict = None) -> Tuple[bool, Dict]:
        """
        Make HTTP request to Mislaka API.
        
        Returns: (success, response_data)
        """
        if not REQUESTS_AVAILABLE:
            return False, {'error': 'requests library not available'}
        
        url = f"{self.BASE_URL}{endpoint}"
        headers = self._get_headers()
        
        if data:
            headers['X-Signature'] = self._sign_request(data)
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            else:
                return False, {'error': f'Unsupported method: {method}'}
            
            if response.status_code == 200:
                return True, response.json()
            elif response.status_code == 401:
                return False, {'error': 'Unauthorized - check API credentials', 'status': 'unauthorized'}
            elif response.status_code == 404:
                return False, {'error': 'Resource not found', 'status': 'not_found'}
            elif response.status_code == 429:
                return False, {'error': 'Rate limited - try again later', 'status': 'rate_limited'}
            else:
                return False, {'error': f'API error: {response.status_code}', 'body': response.text}
                
        except requests.exceptions.Timeout:
            return False, {'error': 'Request timeout'}
        except requests.exceptions.ConnectionError:
            return False, {'error': 'Connection error - check network'}
        except Exception as e:
            return False, {'error': str(e)}
    
    def authenticate(self) -> bool:
        """
        Authenticate with Mislaka API and obtain access token.
        
        Returns: True if successful
        """
        if not self.is_configured():
            print("[MISLAKA] API credentials not configured")
            return False
        
        payload = {
            'api_key': self.api_key,
            'timestamp': datetime.now().isoformat(),
        }
        
        success, response = self._make_request('POST', self.ENDPOINTS['auth'], data=payload)
        
        if success and 'access_token' in response:
            self.access_token = response['access_token']
            expires_in = response.get('expires_in', 3600)
            self.token_expires = datetime.now() + timedelta(seconds=expires_in)
            print(f"[MISLAKA] Authenticated successfully, token expires in {expires_in}s")
            return True
        
        print(f"[MISLAKA] Authentication failed: {response.get('error', 'Unknown error')}")
        return False
    
    def get_person_policies(self, id_number: str, 
                           product_type: MislakaProductType = MislakaProductType.ALL) -> MislakaQueryResult:
        """
        Get all policies for a person by ID number.
        
        Args:
            id_number: Israeli ID number (תעודת זהות)
            product_type: Filter by product type
            
        Returns: MislakaQueryResult with policies
        """
        request_id = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id_number[-4:]}"
        
        # Check cache
        cache_key = f"policies_{id_number}_{product_type.value}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached['expires'] > datetime.now():
                print(f"[MISLAKA] Returning cached result for {cache_key}")
                return cached['data']
        
        # Build request
        endpoint = self.ENDPOINTS['person_policies'].format(id_number=id_number)
        params = {}
        if product_type != MislakaProductType.ALL:
            params['product_type'] = product_type.value
        
        success, response = self._make_request('GET', endpoint, params=params)
        
        if not success:
            return MislakaQueryResult(
                request_id=request_id,
                status=MislakaStatus.ERROR,
                timestamp=datetime.now().isoformat(),
                person=MislakaPerson(id_number=id_number),
                policies=[],
                total_policies=0,
                total_accumulated=0,
                total_monthly_premium=0,
                error_message=response.get('error', 'Unknown error'),
                raw_response=response
            )
        
        # Parse policies
        policies = []
        for p in response.get('policies', []):
            policy = MislakaPolicy(
                policy_id=p.get('id', ''),
                policy_number=p.get('policy_number', ''),
                product_type=p.get('product_type', ''),
                company_name=p.get('company_name', self.COMPANY_CODES.get(p.get('company_code', ''), '')),
                company_code=p.get('company_code', ''),
                start_date=p.get('start_date', ''),
                status=p.get('status', 'active'),
                premium_monthly=float(p.get('premium_monthly', 0)),
                cover_amount=float(p.get('cover_amount', 0)),
                accumulated_value=float(p.get('accumulated_value', 0)),
                management_fee_percent=float(p.get('management_fee', 0)),
                investment_track=p.get('investment_track', ''),
                beneficiaries=p.get('beneficiaries', []),
                last_update=p.get('last_update', '')
            )
            policies.append(policy)
        
        # Build result
        result = MislakaQueryResult(
            request_id=request_id,
            status=MislakaStatus.SUCCESS,
            timestamp=datetime.now().isoformat(),
            person=MislakaPerson(
                id_number=id_number,
                first_name=response.get('person', {}).get('first_name', ''),
                last_name=response.get('person', {}).get('last_name', ''),
            ),
            policies=policies,
            total_policies=len(policies),
            total_accumulated=sum(p.accumulated_value for p in policies),
            total_monthly_premium=sum(p.premium_monthly for p in policies),
            raw_response=response
        )
        
        # Cache result
        self._cache[cache_key] = {
            'data': result,
            'expires': datetime.now() + timedelta(seconds=self._cache_ttl)
        }
        
        return result
    
    def get_policy_details(self, policy_id: str) -> Optional[MislakaPolicy]:
        """
        Get detailed information about a specific policy.
        
        Args:
            policy_id: Unique policy identifier
            
        Returns: MislakaPolicy or None if not found
        """
        endpoint = self.ENDPOINTS['policy_details'].format(policy_id=policy_id)
        success, response = self._make_request('GET', endpoint)
        
        if not success:
            return None
        
        p = response.get('policy', response)
        return MislakaPolicy(
            policy_id=p.get('id', policy_id),
            policy_number=p.get('policy_number', ''),
            product_type=p.get('product_type', ''),
            company_name=p.get('company_name', ''),
            company_code=p.get('company_code', ''),
            start_date=p.get('start_date', ''),
            status=p.get('status', 'active'),
            premium_monthly=float(p.get('premium_monthly', 0)),
            cover_amount=float(p.get('cover_amount', 0)),
            accumulated_value=float(p.get('accumulated_value', 0)),
            management_fee_percent=float(p.get('management_fee', 0)),
            investment_track=p.get('investment_track', ''),
            beneficiaries=p.get('beneficiaries', []),
            last_update=p.get('last_update', '')
        )
    
    def get_pension_funds(self, id_number: str) -> List[MislakaPolicy]:
        """Get pension fund policies for a person"""
        result = self.get_person_policies(id_number, MislakaProductType.PENSION)
        return result.policies
    
    def get_provident_funds(self, id_number: str) -> List[MislakaPolicy]:
        """Get provident fund (קופת גמל) policies for a person"""
        result = self.get_person_policies(id_number, MislakaProductType.PROVIDENT)
        return result.policies
    
    def get_life_insurance(self, id_number: str) -> List[MislakaPolicy]:
        """Get life insurance policies for a person"""
        result = self.get_person_policies(id_number, MislakaProductType.LIFE_INSURANCE)
        return result.policies
    
    def get_insurance_companies(self) -> List[Dict[str, str]]:
        """Get list of insurance companies"""
        success, response = self._make_request('GET', self.ENDPOINTS['companies'])
        
        if success:
            return response.get('companies', [])
        
        # Return static list if API fails
        return [{'code': k, 'name': v} for k, v in self.COMPANY_CODES.items()]
    
    def get_person_summary(self, id_number: str) -> Dict[str, Any]:
        """
        Get summary of all financial products for a person.
        
        Returns aggregated data including:
        - Total number of policies
        - Total accumulated value
        - Total monthly premiums
        - Breakdown by product type
        """
        endpoint = self.ENDPOINTS['summary'].format(id_number=id_number)
        success, response = self._make_request('GET', endpoint)
        
        if success:
            return response
        
        # If API fails, try to build summary from policies
        result = self.get_person_policies(id_number)
        
        summary = {
            'id_number': id_number,
            'total_policies': result.total_policies,
            'total_accumulated': result.total_accumulated,
            'total_monthly_premium': result.total_monthly_premium,
            'by_product_type': {},
            'by_company': {},
        }
        
        for policy in result.policies:
            # By product type
            ptype = policy.product_type
            if ptype not in summary['by_product_type']:
                summary['by_product_type'][ptype] = {
                    'count': 0,
                    'accumulated': 0,
                    'premium': 0
                }
            summary['by_product_type'][ptype]['count'] += 1
            summary['by_product_type'][ptype]['accumulated'] += policy.accumulated_value
            summary['by_product_type'][ptype]['premium'] += policy.premium_monthly
            
            # By company
            company = policy.company_name
            if company not in summary['by_company']:
                summary['by_company'][company] = {
                    'count': 0,
                    'accumulated': 0,
                    'premium': 0
                }
            summary['by_company'][company]['count'] += 1
            summary['by_company'][company]['accumulated'] += policy.accumulated_value
            summary['by_company'][company]['premium'] += policy.premium_monthly
        
        return summary
    
    def to_dict(self, obj) -> Dict:
        """Convert dataclass objects to dictionaries"""
        if hasattr(obj, '__dataclass_fields__'):
            return asdict(obj)
        elif isinstance(obj, list):
            return [self.to_dict(item) for item in obj]
        elif isinstance(obj, Enum):
            return obj.value
        return obj


# Singleton instance
_mislaka_service = None


def get_mislaka_service() -> MislakaAPIService:
    """Get or create Mislaka API service singleton"""
    global _mislaka_service
    if _mislaka_service is None:
        _mislaka_service = MislakaAPIService()
    return _mislaka_service


def init_mislaka_service(api_key: str = None, api_secret: str = None) -> MislakaAPIService:
    """Initialize Mislaka API service with credentials"""
    global _mislaka_service
    _mislaka_service = MislakaAPIService(api_key, api_secret)
    return _mislaka_service
