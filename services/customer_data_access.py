"""
PHINS Customer Data Access Control Service
==========================================
Enforces data isolation for customers, ensuring each customer can only access their own data.

This service provides:
1. Customer authentication validation
2. Data access authorization checks
3. Automatic customer_id resolution from session
4. Audit logging for data access attempts

CRITICAL SECURITY RULES:
- Standard customers (role='customer') can ONLY access their own data
- Admin/staff can access any customer's data for operational purposes
- All unauthorized access attempts are logged
- Customer ID must match session's customer_id for customer role
"""

from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
import hashlib
import random


class CustomerDataAccessService:
    """
    Central service for enforcing customer data isolation.
    
    Usage:
        access = CustomerDataAccessService(audit_log, customers)
        
        # Check if user can access customer data
        authorized, customer_id, error = access.authorize_customer_access(
            session=session,
            requested_customer_id='CUST-TEST-100',
            resource_type='savings'
        )
        
        if not authorized:
            return {'error': error}, 403
    """
    
    # Roles that can access any customer's data
    ADMIN_ROLES = ['admin', 'underwriter', 'claims', 'claims_adjuster', 'accountant']
    
    # Standard customer role
    CUSTOMER_ROLE = 'customer'
    
    def __init__(self, audit_log: List = None, customers: Dict = None, policies: Dict = None):
        """
        Initialize with audit log and customer data store.
        
        Args:
            audit_log: List to append audit entries to
            customers: CUSTOMERS dictionary for customer validation
            policies: POLICIES dictionary for policy ownership validation
        """
        self.audit_log = audit_log if audit_log is not None else []
        self.customers = customers if customers is not None else {}
        self.policies = policies if policies is not None else {}
        
        # Track access violations for security monitoring
        self.access_violations: List[Dict] = []
        
    def authorize_customer_access(self, 
                                    session: Optional[Dict],
                                    requested_customer_id: Optional[str],
                                    resource_type: str = 'data',
                                    require_auth: bool = True) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Authorize access to customer data.
        
        Args:
            session: User session dict with 'customer_id', 'role', 'username'
            requested_customer_id: The customer_id being requested
            resource_type: Type of resource being accessed (savings, policies, claims, etc.)
            require_auth: If True, require authentication (return False if no session)
            
        Returns:
            Tuple of (authorized: bool, resolved_customer_id: str or None, error: str or None)
            
        Examples:
            # Customer trying to access their own data
            authorize_customer_access(session={'customer_id': 'CUST-100', 'role': 'customer'}, 
                                      requested_customer_id='CUST-100')
            -> (True, 'CUST-100', None)
            
            # Customer trying to access another customer's data (DENIED)
            authorize_customer_access(session={'customer_id': 'CUST-100', 'role': 'customer'}, 
                                      requested_customer_id='CUST-200')
            -> (False, None, 'Access denied - cannot access other customer data')
            
            # Admin accessing any customer's data
            authorize_customer_access(session={'role': 'admin'}, 
                                      requested_customer_id='CUST-200')
            -> (True, 'CUST-200', None)
        """
        # No session and auth required
        if not session and require_auth:
            self._log_violation(None, requested_customer_id, resource_type, 'no_session')
            return False, None, 'Authentication required'
        
        # If no session and auth not required (public endpoints), allow with requested ID
        if not session:
            return True, requested_customer_id, None
        
        # Get user info from session
        user_role = (session.get('role') or '').lower()
        session_customer_id = session.get('customer_id')
        username = session.get('username', 'unknown')
        
        # Admin/staff roles can access any customer's data
        if user_role in self.ADMIN_ROLES:
            resolved_id = requested_customer_id or session_customer_id
            self._log_access(username, resolved_id, resource_type, 'admin_access')
            return True, resolved_id, None
        
        # For customer role, enforce strict data isolation
        if user_role == self.CUSTOMER_ROLE:
            # Customer must have a customer_id in their session
            if not session_customer_id:
                self._log_violation(username, requested_customer_id, resource_type, 'no_customer_id_in_session')
                return False, None, 'Customer session invalid - no customer_id'
            
            # If no specific ID requested, use session's customer_id
            if not requested_customer_id:
                self._log_access(username, session_customer_id, resource_type, 'own_data')
                return True, session_customer_id, None
            
            # If specific ID requested, it MUST match session's customer_id
            if requested_customer_id != session_customer_id:
                self._log_violation(username, requested_customer_id, resource_type, 'unauthorized_access_attempt',
                                   session_customer_id=session_customer_id)
                return False, None, f'Access denied - you can only access your own {resource_type}'
            
            # Authorized - accessing own data
            self._log_access(username, session_customer_id, resource_type, 'own_data')
            return True, session_customer_id, None
        
        # Unknown role - default deny
        self._log_violation(username, requested_customer_id, resource_type, 'unknown_role', role=user_role)
        return False, None, 'Access denied - invalid role'
    
    def get_authorized_customer_id(self, session: Optional[Dict], 
                                    requested_customer_id: Optional[str] = None) -> Optional[str]:
        """
        Get the authorized customer_id for the current session.
        
        For customers: Returns their own customer_id (ignores requested_customer_id)
        For admin/staff: Returns requested_customer_id if provided, else session's customer_id
        
        Args:
            session: User session
            requested_customer_id: Optional requested customer_id
            
        Returns:
            Authorized customer_id or None
        """
        authorized, customer_id, _ = self.authorize_customer_access(
            session, requested_customer_id, 'data', require_auth=True
        )
        return customer_id if authorized else None
    
    def validate_resource_ownership(self, session: Optional[Dict],
                                     resource: Dict,
                                     resource_type: str = 'resource') -> Tuple[bool, Optional[str]]:
        """
        Validate that a user can access a specific resource.
        
        Args:
            session: User session
            resource: Resource dict with 'customer_id' field
            resource_type: Type of resource (policy, claim, etc.)
            
        Returns:
            Tuple of (authorized: bool, error: str or None)
        """
        if not session:
            return False, 'Authentication required'
        
        resource_customer_id = resource.get('customer_id')
        
        # Resolve ownership through the related policy when the resource does not
        # carry a direct customer_id (common for claims/bills/attachments).
        if not resource_customer_id and resource.get('policy_id'):
            policy = self.policies.get(resource.get('policy_id')) or {}
            resource_customer_id = policy.get('customer_id')

        if not resource_customer_id:
            username = (session or {}).get('username', 'unknown')
            user_role = ((session or {}).get('role') or '').lower()
            if user_role in self.ADMIN_ROLES:
                return True, None

            requested_owner_ref = (
                resource.get('customer_id')
                or resource.get('policy_id')
                or resource.get('id')
            )
            self._log_violation(
                username,
                requested_owner_ref,
                resource_type,
                'resource_owner_unresolved',
            )
            return False, 'Access denied - unable to verify resource ownership'
        
        authorized, _, error = self.authorize_customer_access(
            session, resource_customer_id, resource_type
        )
        
        return authorized, error
    
    def filter_resources_for_customer(self, session: Optional[Dict],
                                        resources: List[Dict],
                                        customer_id_field: str = 'customer_id') -> List[Dict]:
        """
        Filter a list of resources to only include those the user can access.
        
        Args:
            session: User session
            resources: List of resource dicts
            customer_id_field: Field name containing customer_id
            
        Returns:
            Filtered list of resources
        """
        if not session:
            return []
        
        user_role = (session.get('role') or '').lower()
        session_customer_id = session.get('customer_id')
        
        # Admin/staff can see all
        if user_role in self.ADMIN_ROLES:
            return resources
        
        # Customers can only see their own
        if user_role == self.CUSTOMER_ROLE and session_customer_id:
            return [r for r in resources if r.get(customer_id_field) == session_customer_id]
        
        # Default: return nothing
        return []
    
    def _log_access(self, username: str, customer_id: str, resource_type: str, access_type: str):
        """Log successful data access"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'data_access',
            'username': username,
            'customer_id': customer_id,
            'resource_type': resource_type,
            'access_type': access_type
        }
        self.audit_log.append(entry)
    
    def _log_violation(self, username: Optional[str], requested_customer_id: Optional[str],
                       resource_type: str, violation_type: str, **extra):
        """Log access violation"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'access_violation',
            'violation_type': violation_type,
            'username': username,
            'requested_customer_id': requested_customer_id,
            'resource_type': resource_type,
            **extra
        }
        self.access_violations.append(entry)
        self.audit_log.append(entry)
        
        # Print warning for monitoring
        print(f"⚠️ ACCESS VIOLATION: {violation_type} - User '{username}' attempted to access "
              f"{resource_type} for customer '{requested_customer_id}'")
    
    def get_access_violations(self, limit: int = 100) -> List[Dict]:
        """Get recent access violations for security monitoring"""
        return sorted(self.access_violations, key=lambda x: x['timestamp'], reverse=True)[:limit]


# Singleton instance
_customer_access_service: CustomerDataAccessService = None


def get_customer_access_service(**kwargs) -> CustomerDataAccessService:
    """Get or create the customer access service singleton"""
    global _customer_access_service
    if _customer_access_service is None:
        _customer_access_service = CustomerDataAccessService(**kwargs)
    return _customer_access_service


def init_customer_access_service(audit_log: List = None,
                                 customers: Dict = None,
                                 policies: Dict = None) -> CustomerDataAccessService:
    """Initialize the customer access service with dependencies"""
    global _customer_access_service
    _customer_access_service = CustomerDataAccessService(
        audit_log=audit_log,
        customers=customers,
        policies=policies,
    )
    return _customer_access_service


# Convenience functions for direct use in server.py

def authorize_customer_data_access(session: Optional[Dict],
                                    requested_customer_id: Optional[str],
                                    resource_type: str = 'data') -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Convenience function to authorize customer data access.
    
    Use in server.py like:
        authorized, customer_id, error = authorize_customer_data_access(
            session, qs.get('customer_id', [''])[0], 'savings'
        )
        if not authorized:
            self._set_json_headers(403)
            self.wfile.write(json.dumps({'error': error}).encode('utf-8'))
            return
    """
    service = get_customer_access_service()
    return service.authorize_customer_access(session, requested_customer_id, resource_type)


def get_safe_customer_id(session: Optional[Dict], 
                         requested_customer_id: Optional[str] = None) -> Optional[str]:
    """
    Safely resolve customer_id, ensuring customers can only access their own data.
    
    Use in server.py like:
        customer_id = get_safe_customer_id(session, qs.get('customer_id', [''])[0])
        if not customer_id:
            self._set_json_headers(403)
            self.wfile.write(json.dumps({'error': 'Access denied'}).encode('utf-8'))
            return
    """
    service = get_customer_access_service()
    return service.get_authorized_customer_id(session, requested_customer_id)
