"""
PHINS API Extensions for Community Foundations and OTP Security

This module provides API handlers for:
- Community Foundation management
- OTP Security (CAPTCHA, login verification)
- Device trust management
- Foundation billing integration for customer dashboard

Integration with server.py:
  Import and call these handlers from do_GET/do_POST based on path matching.

Data Persistence:
  Foundation data is automatically persisted to disk and survives server restarts.
  Backups are created before critical operations.
  Foundation deposits are integrated with customer billing for dashboard visibility.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

# Import services
try:
    from services.foundation_service import (
        get_foundation_service,
        init_foundation_service,
        FoundationCreateRequest,
    )
    FOUNDATION_SERVICE_AVAILABLE = True
except ImportError:
    FOUNDATION_SERVICE_AVAILABLE = False
    print("Warning: Foundation service not available")

# Import billing integration
try:
    from services.foundation_billing_integration import (
        get_billing_integration,
        FoundationBillingIntegration
    )
    BILLING_INTEGRATION_AVAILABLE = True
except ImportError:
    BILLING_INTEGRATION_AVAILABLE = False
    print("Warning: Foundation billing integration not available")

# Import persistence service
try:
    from services.foundation_persistence_service import (
        get_persistence_service
    )
    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False
    print("Warning: Foundation persistence not available")

# Import backup service
try:
    from services.ledger_backup_service import (
        get_backup_service
    )
    BACKUP_AVAILABLE = True
except ImportError:
    BACKUP_AVAILABLE = False
    print("Warning: Ledger backup service not available")

try:
    from services.otp_security_service import (
        get_otp_security_service,
        OTPPurpose,
    )
    OTP_SERVICE_AVAILABLE = True
except ImportError:
    OTP_SERVICE_AVAILABLE = False
    print("Warning: OTP security service not available")

# Import contribution payment service for enhanced payment processing
try:
    from services.contribution_payment_service import (
        get_payment_service,
        init_payment_service,
        ContributionPaymentService,
        PaymentMethod,
        PaymentStatus,
        MAX_UPLOAD_SIZE,
        SUPPORTED_DOCUMENT_TYPES
    )
    PAYMENT_SERVICE_AVAILABLE = True
except ImportError:
    PAYMENT_SERVICE_AVAILABLE = False
    print("Warning: Contribution payment service not available")

# Shared data stores for cross-dashboard integration
_contribution_ledger: Dict = {}
_admin_dashboard_data: Dict = {}
_accounting_dashboard_data: Dict = {}


# ============================================================================
# CAPTCHA & OTP SECURITY ENDPOINTS
# ============================================================================

def handle_captcha_create(client_ip: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/security/captcha - Create CAPTCHA challenge"""
    if not OTP_SERVICE_AVAILABLE:
        return 503, {"error": "OTP security service not available"}
    
    service = get_otp_security_service()
    action = body_data.get('action', 'login')
    
    result = service.create_captcha_challenge(
        action=action,
        ip_address=client_ip
    )
    
    return 200 if result.success else 400, result.to_dict()


def handle_captcha_verify(client_ip: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/security/captcha/verify - Verify CAPTCHA response"""
    if not OTP_SERVICE_AVAILABLE:
        return 503, {"error": "OTP security service not available"}
    
    service = get_otp_security_service()
    challenge_id = body_data.get('challenge_id')
    response = body_data.get('response', '')
    
    if not challenge_id:
        return 400, {"success": False, "error": "Missing challenge_id"}
    
    result = service.verify_captcha(
        challenge_id=challenge_id,
        response=response,
        ip_address=client_ip
    )
    
    return 200 if result.success else 400, result.to_dict()


def handle_otp_request(client_ip: str, body_data: Dict, user_agent: str = "") -> Tuple[int, Dict]:
    """POST /api/security/otp/request - Request OTP for verification"""
    if not OTP_SERVICE_AVAILABLE:
        return 503, {"error": "OTP security service not available"}
    
    service = get_otp_security_service()
    
    email = body_data.get('email')
    purpose = body_data.get('purpose', 'login')
    user_type = body_data.get('user_type', 'customer')
    user_id = body_data.get('user_id', email)  # Use email as user_id if not provided
    device_fingerprint = body_data.get('device_fingerprint')
    
    if not email:
        return 400, {"success": False, "error": "Email is required"}
    
    # Convert purpose string to enum
    try:
        purpose_enum = OTPPurpose(purpose)
    except ValueError:
        purpose_enum = OTPPurpose.LOGIN
    
    result = service.create_otp_verification(
        user_type=user_type,
        user_id=user_id,
        email=email,
        purpose=purpose_enum,
        ip_address=client_ip,
        user_agent=user_agent,
        device_fingerprint=device_fingerprint
    )
    
    # In development/demo mode, include OTP in response
    # In production, this would be sent via email
    response_data = result.to_dict()
    if result.success and result.data:
        response_data['verification_id'] = result.data.get('verification_id')
        response_data['masked_email'] = result.data.get('masked_email')
        response_data['expires_in_seconds'] = result.data.get('expires_in_seconds', 300)
        # For demo purposes, include the OTP code
        # REMOVE THIS IN PRODUCTION
        if result.data.get('otp_code'):
            response_data['demo_otp_code'] = result.data.get('otp_code')
            print(f"[DEMO] OTP Code for {email}: {result.data.get('otp_code')}")
    
    return 200 if result.success else 400, response_data


def handle_otp_verify(client_ip: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/security/otp/verify - Verify OTP code"""
    if not OTP_SERVICE_AVAILABLE:
        return 503, {"error": "OTP security service not available"}
    
    service = get_otp_security_service()
    
    verification_id = body_data.get('verification_id')
    otp_code = body_data.get('otp_code')
    trust_device = body_data.get('trust_device', False)
    
    if not verification_id or not otp_code:
        return 400, {"success": False, "error": "verification_id and otp_code required"}
    
    result = service.verify_otp(
        verification_id=verification_id,
        otp_code=otp_code,
        ip_address=client_ip,
        trust_device=trust_device
    )
    
    return 200 if result.success else 400, result.to_dict()


def handle_otp_resend(client_ip: str, body_data: Dict, user_agent: str = "") -> Tuple[int, Dict]:
    """POST /api/security/otp/resend - Resend OTP code"""
    if not OTP_SERVICE_AVAILABLE:
        return 503, {"error": "OTP security service not available"}
    
    # For now, require a new OTP request
    # A more sophisticated implementation would reuse verification data
    return 400, {
        "success": False, 
        "message": "Please request a new OTP code"
    }


def handle_login_check(client_ip: str, body_data: Dict, user_agent: str = "") -> Tuple[int, Dict]:
    """POST /api/security/login/check - Check login security requirements"""
    if not OTP_SERVICE_AVAILABLE:
        return 200, {
            "success": True,
            "requires_otp": False,
            "requires_captcha": True,
            "data": {"is_trusted_device": False}
        }
    
    service = get_otp_security_service()
    
    user_type = body_data.get('user_type', 'customer')
    user_id = body_data.get('user_id', '')
    email = body_data.get('email', '')
    device_fingerprint = body_data.get('device_fingerprint')
    
    result = service.check_login_requirements(
        user_type=user_type,
        user_id=user_id,
        email=email,
        ip_address=client_ip,
        user_agent=user_agent,
        device_fingerprint=device_fingerprint
    )
    
    return 200, result.to_dict()


# ============================================================================
# FOUNDATION ENDPOINTS
# ============================================================================

def handle_foundations_list(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations - List user's foundations"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    
    # Get user's foundations
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    foundations = service.get_user_foundations(user_id)
    
    return 200, {
        "items": foundations,
        "total": len(foundations)
    }


def handle_foundation_create(session: Dict, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations - Create new foundation"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    request = FoundationCreateRequest(
        name=body_data.get('name', ''),
        foundation_type=body_data.get('foundation_type', 'custom'),
        description=body_data.get('description', ''),
        founder_id=user_id,
        founder_type='customer' if customer_id else 'staff',
        max_members=int(body_data.get('max_members')) if body_data.get('max_members') else None
    )
    
    result = service.create_foundation(request)
    
    return 201 if result.success else 400, result.to_dict()


def handle_foundation_get(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """GET /api/foundations/{id} - Get foundation details"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    foundation = service.get_foundation(foundation_id)
    
    if not foundation:
        return 404, {"error": "Foundation not found"}
    
    return 200, foundation


def handle_foundation_activate(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/activate - Activate draft foundation"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.activate_foundation(foundation_id, user_id)
    
    return 200 if result.success else 400, result.to_dict()


def handle_foundation_contribute(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/contribute - Make contribution"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Get first fund for the foundation
    funds = service.get_foundation_funds(foundation_id)
    if not funds:
        return 400, {"error": "No funds available for contribution"}
    
    fund_id = body_data.get('fund_id') or funds[0]['id']
    amount = float(body_data.get('amount', 0))
    
    if amount <= 0:
        return 400, {"error": "Amount must be positive"}
    
    result = service.make_contribution(
        foundation_id=foundation_id,
        fund_id=fund_id,
        member_id=user_id,
        amount=amount,
        notes=body_data.get('notes', '')
    )
    
    return 200 if result.get('success') else 400, result


def handle_foundation_invite(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/invite - Create invitation"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.create_invitation(
        foundation_id=foundation_id,
        invited_by=user_id,
        invited_email=body_data.get('email'),
        max_uses=body_data.get('max_uses', 1),
        expires_days=body_data.get('expires_days', 7)
    )
    
    return 200 if result.get('success') else 400, result


# ============================================================================
# FOUNDATION MEMBER ENDPOINTS
# ============================================================================

def handle_foundation_members_list(session: Dict, foundation_id: str, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/members - List foundation members"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    include_pending = query_params.get('include_pending', ['false'])[0].lower() == 'true'
    
    # Only founders/admins can see pending members
    if include_pending and member['role'] not in ['founder', 'admin']:
        include_pending = False
    
    members = service.get_foundation_members(foundation_id, include_pending=include_pending)
    
    return 200, {
        "items": members,
        "total": len(members),
        "foundation_id": foundation_id,
        "user_role": member['role']
    }


def handle_foundation_member_approve(session: Dict, foundation_id: str, member_id: str) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/members/{member_id}/approve - Approve pending member"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.approve_member(foundation_id, member_id, user_id)
    
    if result.success:
        return 200, {"success": True, "message": "Member approved", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_foundation_member_reject(session: Dict, foundation_id: str, member_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/members/{member_id}/reject - Reject pending member"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    reason = body_data.get('reason', '')
    result = service.reject_member(foundation_id, member_id, user_id, reason)
    
    if result.success:
        return 200, {"success": True, "message": "Member rejected", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_foundation_member_remove(session: Dict, foundation_id: str, member_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/members/{member_id}/remove - Remove active member"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    reason = body_data.get('reason', '')
    result = service.remove_member(foundation_id, member_id, user_id, reason)
    
    if result.success:
        return 200, {"success": True, "message": "Member removed", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_foundation_member_role(session: Dict, foundation_id: str, member_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/members/{member_id}/role - Update member role"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    new_role = body_data.get('role', '')
    result = service.update_member_role(foundation_id, member_id, new_role, user_id)
    
    if result.success:
        return 200, {"success": True, "message": f"Role updated to {new_role}", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


# ============================================================================
# FOUNDATION VOTING ENDPOINTS
# ============================================================================

def handle_foundation_votes_list(session: Dict, foundation_id: str, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/votes - List foundation votes"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    status = query_params.get('status', [None])[0]
    limit = int(query_params.get('limit', ['50'])[0])
    
    if status == 'active':
        votes = service.get_active_votes(foundation_id)
    else:
        votes = service.get_all_votes(foundation_id, status=status, limit=limit)
    
    # Add user's vote status to each vote
    for vote in votes:
        vote_status = service.get_member_vote_status(vote['id'], user_id)
        vote['user_vote'] = vote_status
    
    return 200, {
        "items": votes,
        "total": len(votes),
        "foundation_id": foundation_id
    }


def handle_foundation_vote_get(session: Dict, foundation_id: str, vote_id: str) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/votes/{vote_id} - Get vote details"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    vote = service.get_vote(vote_id)
    if not vote or vote['foundation_id'] != foundation_id:
        return 404, {"error": "Vote not found"}
    
    # Add user's vote status
    vote['user_vote'] = service.get_member_vote_status(vote_id, user_id)
    
    # Get vote casts if admin or founder
    if member['role'] in ['founder', 'admin']:
        vote['casts'] = service.get_vote_casts(vote_id)
    
    return 200, vote


def handle_foundation_vote_create(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/votes - Create a new vote"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.create_vote(
        foundation_id=foundation_id,
        created_by=user_id,
        proposal_type=body_data.get('proposal_type', 'general'),
        title=body_data.get('title', ''),
        description=body_data.get('description', ''),
        threshold=float(body_data.get('threshold', 0.50)),
        duration_days=int(body_data.get('duration_days', 7)),
        subject=body_data.get('subject', ''),
        summary=body_data.get('summary', ''),
        outlines=body_data.get('outlines'),
        voting_mechanism=body_data.get('voting_mechanism', 'simple_majority'),
        options=body_data.get('options')
    )
    
    return 201 if result.get('success') else 400, result


def handle_foundation_vote_cast(session: Dict, foundation_id: str, vote_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/votes/{vote_id}/cast - Cast a vote"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.cast_vote(
        vote_id=vote_id,
        member_id=user_id,
        choice=body_data.get('choice', ''),
        reason=body_data.get('reason', ''),
        ranked_choices=body_data.get('ranked_choices')
    )
    
    return 200 if result.get('success') else 400, result


def handle_foundation_vote_close(session: Dict, foundation_id: str, vote_id: str) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/votes/{vote_id}/close - Close a vote early"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.close_vote(vote_id, user_id)
    
    return 200 if result.get('success') else 400, result


def handle_foundation_vote_approve(session: Dict, foundation_id: str, vote_id: str) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/votes/{vote_id}/approve - Approve a pending vote proposal"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.approve_vote(vote_id, user_id)
    
    return 200 if result.get('success') else 400, result


# ============================================================================
# FOUNDATION CLAIMS ENDPOINTS
# ============================================================================

def handle_foundation_claims_list(session: Dict, foundation_id: str, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/claims - List foundation claims"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    status = query_params.get('status', [None])[0]
    claims = service.get_foundation_claims(foundation_id, status=status)
    
    return 200, {
        "items": claims,
        "total": len(claims),
        "foundation_id": foundation_id
    }


def handle_foundation_claim_submit(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/claims - Submit a claim"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    result = service.submit_claim(
        foundation_id=foundation_id,
        fund_id=body_data.get('fund_id', ''),
        claimant_id=user_id,
        claim_type=body_data.get('claim_type', 'general'),
        amount=float(body_data.get('amount', 0)),
        description=body_data.get('description', ''),
        supporting_docs=body_data.get('supporting_docs')
    )
    
    return 201 if result.get('success') else 400, result


def handle_foundation_claim_approve(session: Dict, foundation_id: str, claim_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/{id}/claims/{claim_id}/approve - Approve a claim"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    approved_amount = body_data.get('approved_amount')
    if approved_amount:
        approved_amount = float(approved_amount)
    
    result = service.approve_claim(
        claim_id=claim_id,
        approver_id=user_id,
        approved_amount=approved_amount,
        notes=body_data.get('notes', '')
    )
    
    return 200 if result.get('success') else 400, result


# ============================================================================
# FOUNDATION BILLING & REPORTS ENDPOINTS
# ============================================================================

def handle_foundation_billing(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/billing - Get billing summary"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    billing = service.get_foundation_billing_summary(foundation_id)
    
    if 'error' in billing:
        return 404, billing
    
    return 200, billing


def handle_foundation_member_billing(session: Dict, foundation_id: str, member_user_id: str) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/members/{member_id}/billing - Get member billing history"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation and has rights to view
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    # Can only view own billing unless admin/founder
    if member_user_id != user_id and member['role'] not in ['founder', 'admin']:
        return 403, {"error": "You can only view your own billing history"}
    
    billing = service.get_member_billing_history(foundation_id, member_user_id)
    
    if 'error' in billing:
        return 404, billing
    
    return 200, billing


def handle_foundation_report(session: Dict, foundation_id: str, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/report - Get foundation report"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    report_type = query_params.get('type', ['summary'])[0]
    report = service.get_foundation_report(foundation_id, report_type)
    
    if 'error' in report:
        return 404, report
    
    return 200, report


# ============================================================================
# COMPREHENSIVE NFT LEDGER ENDPOINTS
# ============================================================================

def handle_comprehensive_ledger(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundation-ledger/comprehensive - Get comprehensive NFT ledger with all transactions"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"transactions": [], "statistics": {}, "total_count": 0}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    foundation_id = query_params.get('foundation_id', [None])[0]
    limit = int(query_params.get('limit', ['100'])[0])
    
    ledger = service.get_comprehensive_ledger(
        user_id=user_id,
        foundation_id=foundation_id,
        limit=limit
    )
    
    return 200, ledger


def handle_vote_statistics(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundation-votes/statistics - Get comprehensive voting statistics"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"summary": {}, "type_breakdown": {}, "recent_votes": []}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    foundation_id = query_params.get('foundation_id', [None])[0]
    
    stats = service.get_vote_statistics(
        foundation_id=foundation_id,
        user_id=user_id if not foundation_id else None
    )
    
    return 200, stats


def handle_foundation_csv_report(session: Dict, foundation_id: str, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/export/csv - Export foundation data as CSV"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    # Only founders and admins can export data
    if member['role'] not in ['founder', 'admin']:
        return 403, {"error": "Only founders and admins can export data"}
    
    report_type = query_params.get('type', ['transactions'])[0]
    
    csv_data = service.generate_csv_report(foundation_id, report_type)
    
    foundation = service.get_foundation(foundation_id)
    filename = f"{foundation['name'].replace(' ', '_')}_{report_type}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    
    return 200, {
        "success": True,
        "data": csv_data,
        "filename": filename,
        "content_type": "text/csv"
    }


# ============================================================================
# WALLET & PAYMENT ENDPOINTS
# ============================================================================

def handle_wallet_balance(session: Dict) -> Tuple[int, Dict]:
    """GET /api/foundation-wallet/balance - Get customer wallet balance"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"wallet_balance": 0, "currency": "USD"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    wallet = service.get_customer_wallet_balance(user_id)
    return 200, wallet


def handle_wallet_deposit(session: Dict, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundation-wallet/deposit - Deposit funds to wallet"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    amount = float(body_data.get('amount', 0))
    payment_method = body_data.get('payment_method', 'credit_card')
    payment_reference = body_data.get('payment_reference', '')
    
    if amount <= 0:
        return 400, {"error": "Amount must be positive"}
    
    result = service.deposit_to_wallet(
        customer_id=user_id,
        amount=amount,
        payment_method=payment_method,
        payment_reference=payment_reference
    )
    
    return 200 if result.get('success') else 400, result


def handle_contribution_with_billing(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """
    POST /api/foundations/{id}/contribute-billing - Make contribution with full billing integration
    
    Enhanced version with:
    - Credit card payment processing with validation
    - Bank transfer support
    - Wallet payment support
    - Document upload support (up to 500MB)
    - AI assessment and recommendations
    - Ledger recording
    - Dashboard integration (admin, accounting)
    """
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Get foundation info
    foundation = service.get_foundation(foundation_id)
    if not foundation:
        return 404, {"error": "Foundation not found"}
    
    # Get fund_id
    funds = service.get_foundation_funds(foundation_id)
    if not funds:
        return 400, {"error": "No funds available for contribution"}
    
    fund_id = body_data.get('fund_id') or funds[0]['id']
    fund = next((f for f in funds if f['id'] == fund_id), funds[0])
    
    amount = float(body_data.get('amount', 0))
    payment_method = body_data.get('payment_method', 'wallet')
    notes = body_data.get('notes', '')
    documents = body_data.get('documents', [])  # List of document uploads
    
    if amount <= 0:
        return 400, {"error": "Amount must be positive"}
    
    # Use enhanced payment service if available
    if PAYMENT_SERVICE_AVAILABLE:
        payment_service = get_payment_service(
            ledger=_contribution_ledger,
            admin_dashboard=_admin_dashboard_data,
            accounting_dashboard=_accounting_dashboard_data
        )
        
        # Process based on payment method
        if payment_method == 'credit_card':
            # Credit card payment with validation
            card_number = body_data.get('card_number', '')
            exp_month = int(body_data.get('exp_month', 0))
            exp_year = int(body_data.get('exp_year', 0))
            cvv = body_data.get('cvv', '')
            cardholder_name = body_data.get('cardholder_name', '')
            billing_zip = body_data.get('billing_zip', '')
            
            if not all([card_number, exp_month, exp_year, cvv, cardholder_name]):
                return 400, {"error": "Missing credit card information. Required: card_number, exp_month, exp_year, cvv, cardholder_name"}
            
            result = payment_service.process_credit_card_payment(
                customer_id=user_id,
                foundation_id=foundation_id,
                foundation_name=foundation['name'],
                fund_id=fund_id,
                fund_name=fund['name'],
                amount=amount,
                card_number=card_number,
                exp_month=exp_month,
                exp_year=exp_year,
                cvv=cvv,
                cardholder_name=cardholder_name,
                billing_zip=billing_zip,
                notes=notes,
                documents=documents
            )
            
            if result.get('success'):
                # Also record to foundation service for fund balance update
                service.make_contribution_with_billing(
                    foundation_id=foundation_id,
                    fund_id=fund_id,
                    member_id=user_id,
                    amount=amount,
                    payment_method=payment_method,
                    payment_reference=result.get('transaction_id', ''),
                    notes=notes
                )
            
            return 200 if result.get('success') else 400, result
        
        elif payment_method == 'bank_transfer':
            # Bank transfer
            bank_name = body_data.get('bank_name', '')
            account_last4 = body_data.get('account_last4', '')
            routing_number = body_data.get('routing_number', '')
            
            result = payment_service.process_bank_transfer(
                customer_id=user_id,
                foundation_id=foundation_id,
                foundation_name=foundation['name'],
                fund_id=fund_id,
                fund_name=fund['name'],
                amount=amount,
                bank_name=bank_name,
                account_last4=account_last4,
                routing_number=routing_number,
                notes=notes,
                documents=documents
            )
            
            if result.get('success'):
                service.make_contribution_with_billing(
                    foundation_id=foundation_id,
                    fund_id=fund_id,
                    member_id=user_id,
                    amount=amount,
                    payment_method=payment_method,
                    payment_reference=result.get('transaction_id', ''),
                    notes=notes
                )
            
            return 200 if result.get('success') else 400, result
        
        elif payment_method == 'wallet':
            # Wallet payment
            wallet = service.get_customer_wallet_balance(user_id)
            wallet_balance = wallet.get('wallet_balance', 0)
            
            result = payment_service.process_wallet_payment(
                customer_id=user_id,
                foundation_id=foundation_id,
                foundation_name=foundation['name'],
                fund_id=fund_id,
                fund_name=fund['name'],
                amount=amount,
                wallet_balance=wallet_balance,
                notes=notes,
                documents=documents
            )
            
            if result.get('success'):
                service.make_contribution_with_billing(
                    foundation_id=foundation_id,
                    fund_id=fund_id,
                    member_id=user_id,
                    amount=amount,
                    payment_method=payment_method,
                    payment_reference=result.get('transaction_id', ''),
                    notes=notes
                )
            
            return 200 if result.get('success') else 400, result
    
    # Fallback to original implementation if payment service not available
    payment_reference = body_data.get('payment_reference', '')
    wallet_id = body_data.get('wallet_id', '')
    
    # If using wallet, verify sufficient balance
    if payment_method == 'wallet':
        wallet = service.get_customer_wallet_balance(user_id)
        if wallet['wallet_balance'] < amount:
            return 400, {
                "error": "Insufficient wallet balance",
                "wallet_balance": wallet['wallet_balance'],
                "required_amount": amount
            }
    
    result = service.make_contribution_with_billing(
        foundation_id=foundation_id,
        fund_id=fund_id,
        member_id=user_id,
        amount=amount,
        payment_method=payment_method,
        payment_reference=payment_reference,
        wallet_id=wallet_id,
        notes=notes
    )
    
    return 200 if result.get('success') else 400, result


def handle_contribution_document_upload(session: Dict, body_data: Dict) -> Tuple[int, Dict]:
    """
    POST /api/contribution-documents/upload - Upload document for a contribution
    
    Supports large file uploads up to 500MB including videos, PDFs, images, etc.
    """
    if not PAYMENT_SERVICE_AVAILABLE:
        return 503, {"error": "Document upload service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    transaction_id = body_data.get('transaction_id', '')
    file_name = body_data.get('file_name', '')
    file_data = body_data.get('file_data', '')  # Base64 encoded
    file_type = body_data.get('file_type', '')
    description = body_data.get('description', '')
    
    if not all([transaction_id, file_name, file_data, file_type]):
        return 400, {"error": "Missing required fields: transaction_id, file_name, file_data, file_type"}
    
    # Validate file type
    if file_type not in SUPPORTED_DOCUMENT_TYPES:
        return 400, {
            "error": f"Unsupported file type: {file_type}",
            "supported_types": SUPPORTED_DOCUMENT_TYPES
        }
    
    # Validate file size (base64 is ~33% larger than binary)
    estimated_size = len(file_data) * 3 // 4
    if estimated_size > MAX_UPLOAD_SIZE:
        return 400, {
            "error": f"File too large. Maximum size is {MAX_UPLOAD_SIZE / (1024*1024):.0f}MB",
            "estimated_size_mb": estimated_size / (1024*1024)
        }
    
    payment_service = get_payment_service(
        ledger=_contribution_ledger,
        admin_dashboard=_admin_dashboard_data,
        accounting_dashboard=_accounting_dashboard_data
    )
    
    result = payment_service.upload_document_for_contribution(
        transaction_id=transaction_id,
        file_name=file_name,
        file_data_base64=file_data,
        file_type=file_type,
        uploaded_by=user_id,
        description=description
    )
    
    return 200 if result.get('success') else 400, result


def handle_contribution_ai_assessment(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """
    GET /api/contribution-assessment - Get AI assessment for contributions
    
    Returns AI-powered insights, recommendations, and summaries for the user's contributions.
    """
    if not PAYMENT_SERVICE_AVAILABLE:
        return 200, {
            "available": False,
            "message": "AI assessment service not available"
        }
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    payment_service = get_payment_service(
        ledger=_contribution_ledger,
        admin_dashboard=_admin_dashboard_data,
        accounting_dashboard=_accounting_dashboard_data
    )
    
    # Get user's recent transactions
    transactions = payment_service.get_customer_transactions(user_id, limit=20)
    
    if not transactions:
        return 200, {
            "available": True,
            "customer_id": user_id,
            "message": "No contribution history found",
            "recommendations": [
                {
                    "type": "getting_started",
                    "title": "Welcome to Foundation Contributions",
                    "content": "Make your first contribution to join the community safety net. Start small and build up over time."
                }
            ]
        }
    
    # Aggregate assessment data
    total_contributed = sum(tx.get('amount', 0) for tx in transactions)
    avg_contribution = total_contributed / len(transactions)
    
    # Get the most recent AI assessment
    latest_assessment = None
    for tx in transactions:
        if tx.get('ai_assessment'):
            latest_assessment = tx['ai_assessment']
            break
    
    return 200, {
        "available": True,
        "customer_id": user_id,
        "summary": {
            "total_contributions": len(transactions),
            "total_amount": total_contributed,
            "average_amount": round(avg_contribution, 2),
            "last_contribution": transactions[0].get('created_at') if transactions else None
        },
        "latest_assessment": latest_assessment,
        "recommendations": latest_assessment.get('recommendations', []) if latest_assessment else [],
        "advice": latest_assessment.get('advice', []) if latest_assessment else []
    }


def handle_admin_contribution_dashboard(session: Dict) -> Tuple[int, Dict]:
    """
    GET /api/admin/contribution-dashboard - Get admin contribution dashboard data
    
    Returns aggregated contribution data for admin monitoring.
    """
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    dashboard_data = {
        "contributions": _admin_dashboard_data.get('contributions', {
            'total_amount': 0,
            'total_count': 0,
            'by_method': {},
            'recent': []
        }),
        "ledger_stats": {
            "total_entries": len(_contribution_ledger),
            "verified_entries": sum(1 for e in _contribution_ledger.values() if e.get('verified'))
        },
        "last_updated": _admin_dashboard_data.get('last_updated', datetime.now(timezone.utc).isoformat())
    }
    
    return 200, dashboard_data


def handle_accounting_contribution_dashboard(session: Dict) -> Tuple[int, Dict]:
    """
    GET /api/accounting/contribution-dashboard - Get accounting contribution dashboard data
    
    Returns financial data for accounting/reporting purposes.
    """
    if not session:
        return 401, {"error": "Authentication required"}
    
    role = session.get('role', '')
    if role not in ['admin', 'accountant', 'actuary']:
        return 403, {"error": "Access denied. Required role: admin, accountant, or actuary"}
    
    accounting_data = {
        "transactions": _accounting_dashboard_data.get('transactions', {
            'total_revenue': 0,
            'total_fees': 0,
            'net_revenue': 0,
            'by_foundation': {},
            'recent': []
        }),
        "summary": {
            "total_processed": _accounting_dashboard_data.get('transactions', {}).get('total_revenue', 0),
            "total_fees_collected": _accounting_dashboard_data.get('transactions', {}).get('total_fees', 0),
            "net_to_foundations": _accounting_dashboard_data.get('transactions', {}).get('net_revenue', 0)
        },
        "last_updated": _accounting_dashboard_data.get('last_updated', datetime.now(timezone.utc).isoformat())
    }
    
    return 200, accounting_data


def handle_contribution_ledger(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """
    GET /api/contribution-ledger - Get contribution ledger entries
    
    Returns verified ledger entries for contributions with cryptographic hashes.
    """
    if not session:
        return 401, {"error": "Authentication required"}
    
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    is_admin = session.get('role') == 'admin'
    
    # Filter by customer if not admin
    if is_admin:
        entries = list(_contribution_ledger.values())
    else:
        entries = [e for e in _contribution_ledger.values() if e.get('customer_id') == user_id]
    
    # Sort by timestamp
    entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Apply limit
    limit = int(query_params.get('limit', ['50'])[0])
    entries = entries[:limit]
    
    return 200, {
        "items": entries,
        "total": len(entries),
        "verified_count": sum(1 for e in entries if e.get('verified'))
    }


def handle_foundation_activities(session: Dict, foundation_id: str, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/{id}/activities - Get foundation activities"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Check if user is member of this foundation
    member = service._get_member_by_user(foundation_id, user_id)
    if not member:
        return 403, {"error": "You are not a member of this foundation"}
    
    limit = int(query_params.get('limit', ['50'])[0])
    activities = service.get_foundation_activities(foundation_id, limit=limit)
    
    return 200, {
        "items": activities,
        "total": len(activities),
        "foundation_id": foundation_id
    }


def handle_foundation_ledger(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundation-ledger - Get user's foundation ledger entries (activities)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"items": [], "total": 0}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Get all foundations user is a member of
    foundations = service.get_user_foundations(user_id)
    
    all_activities = []
    for foundation in foundations:
        activities = service.get_foundation_activities(foundation['id'], limit=20)
        for activity in activities:
            activity['foundation_name'] = foundation['name']
        all_activities.extend(activities)
    
    # Sort by timestamp, most recent first
    all_activities.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Limit to 50 most recent
    limit = int(query_params.get('limit', ['50'])[0])
    all_activities = all_activities[:limit]
    
    return 200, {
        "items": all_activities,
        "total": len(all_activities)
    }


def handle_foundation_billing_dashboard(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """
    GET /api/foundation-billing-dashboard - Get foundation billing data for customer dashboard
    
    This endpoint returns billing data that should appear on the customer's main dashboard,
    showing their foundation deposits, contributions, and payouts.
    """
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {
            "customer_id": "",
            "foundation_billing": {
                "summary": {
                    "total_contributed": 0,
                    "total_received": 0,
                    "net_position": 0,
                    "active_foundations": 0
                },
                "recent_transactions": [],
                "transaction_count": 0
            }
        }
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    # Get billing dashboard data
    dashboard_data = service.get_billing_dashboard_data(user_id)
    
    return 200, dashboard_data


def handle_foundation_create_backup(session: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/backup - Create a manual backup of foundation data (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    backup_id = service.create_backup(label="manual_backup")
    
    if backup_id:
        return 200, {"success": True, "backup_id": backup_id, "message": "Backup created successfully"}
    else:
        return 500, {"success": False, "error": "Backup creation failed"}


def handle_foundation_persistence_status(session: Dict) -> Tuple[int, Dict]:
    """GET /api/foundations/persistence-status - Get persistence service status (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    
    status = {
        "persistence_enabled": service._persistence_enabled,
        "backup_enabled": service._backup_enabled,
        "billing_integration_enabled": service._billing_enabled,
        "foundations_count": len(service._foundations),
        "members_count": len(service._members),
        "contributions_count": len(service._contributions),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    # Add backup list if available
    if BACKUP_AVAILABLE:
        try:
            backup_service = get_backup_service()
            status["recent_backups"] = backup_service.list_backups(backup_type="foundation", limit=5)
        except Exception as e:
            status["backup_list_error"] = str(e)
    
    return 200, status


def handle_foundation_activity_log(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/foundation-activity - Get user's foundation activity log"""
    return handle_foundation_ledger(session, query_params)


def handle_foundation_join(session: Dict, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/foundations/join - Join foundation via invitation code"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    customer_id = session.get('customer_id')
    user_id = customer_id or session.get('username')
    
    code = body_data.get('code', '')
    display_name = body_data.get('display_name')
    
    result = service.join_foundation(
        code=code,
        member_id=user_id,
        member_type='customer' if customer_id else 'staff',
        display_name=display_name
    )
    
    return 200 if result.success else 400, result.to_dict()


def handle_foundation_invitations_list(session: Dict) -> Tuple[int, Dict]:
    """GET /api/foundation-invitations - List pending invitations for user"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session:
        return 401, {"error": "Authentication required"}
    
    service = get_foundation_service()
    
    # Get user email from session
    email = session.get('email', '')
    if not email:
        # Try to get from customer record
        customer_id = session.get('customer_id')
        if customer_id:
            # Would need to look up customer email here
            email = ''
    
    invitations = service.get_pending_invitations(email) if email else []
    
    return 200, {
        "items": invitations,
        "total": len(invitations)
    }


def handle_invitation_validate(code: str) -> Tuple[int, Dict]:
    """
    GET /api/foundation-invitations/validate?code=XXX - Validate invitation code
    GET /api/foundation-invitations/validate/{code} - Validate invitation code (path param)
    
    Returns foundation details if code is valid, for the frontend to display preview.
    """
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"valid": False, "error": "Foundation service is temporarily unavailable. Please try again later."}
    
    if not code or len(code) < 4:
        return 200, {"valid": False, "error": "Invalid invitation code format. Please enter a valid code."}
    
    service = get_foundation_service()
    result = service.validate_invitation(code)
    
    # If valid, enhance the response with full foundation details for frontend preview
    if result.get("valid") and result.get("foundation_id"):
        foundation = service.get_foundation(result["foundation_id"])
        if foundation:
            # Get foundation settings/rules for display
            settings = foundation.get('settings', {})
            rules = {
                "contribution_frequency": settings.get('contribution_rules', {}).get('frequency', 'monthly'),
                "min_contribution": settings.get('contribution_rules', {}).get('min_amount', 50),
                "vote_threshold": int(settings.get('voting_rules', {}).get('majority_threshold', 0.5) * 100),
                "waiting_period": settings.get('claim_rules', {}).get('waiting_period_days', 30),
                "auto_approve_threshold": settings.get('claim_rules', {}).get('auto_approve_threshold', 500)
            }
            
            result["foundation"] = {
                "id": foundation.get("id"),
                "name": foundation.get("name"),
                "foundation_type": foundation.get("foundation_type"),
                "description": foundation.get("description", ""),
                "status": foundation.get("status"),
                "current_members": foundation.get("current_members", 0),
                "max_members": foundation.get("max_members", 0),
                "is_unlimited": foundation.get("is_unlimited", False),
                "total_fund_balance": foundation.get("total_fund_balance", 0),
                "rules": rules,
                "created_at": foundation.get("created_at")
            }
            # Add invited role from invitation if available
            result["invited_role"] = "member"  # Default role for invitees
        else:
            # Foundation exists in invitation but not in storage (e.g., server restarted)
            return 200, {
                "valid": False,
                "error": "The foundation associated with this invitation no longer exists. Please request a new invitation."
            }
    
    return 200, result


# ============================================================================
# ADMIN FOUNDATION ENDPOINTS
# ============================================================================

def handle_admin_foundations_list(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/admin/foundations - List all foundations (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    
    status = query_params.get('status', [None])[0]
    foundations = service.list_foundations(status=status, limit=100)
    
    return 200, {
        "items": foundations,
        "total": len(foundations)
    }


def handle_admin_foundations_stats(session: Dict) -> Tuple[int, Dict]:
    """GET /api/admin/foundations/stats - Get foundation statistics (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {
            "total_foundations": 0,
            "total_members": 0,
            "total_funds": 0,
            "active_votes": 0
        }
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    foundations = service.list_foundations(limit=1000)
    
    total_members = sum(f.get('current_members', 0) for f in foundations)
    total_funds = sum(f.get('total_fund_balance', 0) for f in foundations)
    
    return 200, {
        "total_foundations": len(foundations),
        "total_members": total_members,
        "total_funds": total_funds,
        "active_votes": 0  # Would need to aggregate from votes
    }


def handle_admin_foundation_get(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """GET /api/admin/foundations/{id} - Get foundation details (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    foundation = service.get_foundation(foundation_id)
    
    if not foundation:
        return 404, {"error": "Foundation not found"}
    
    return 200, foundation


def handle_admin_foundation_activity(session: Dict) -> Tuple[int, Dict]:
    """GET /api/admin/foundations/activity - Get recent activity (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"items": [], "total": 0}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    # Would need to aggregate activities from all foundations
    # For now, return empty list
    return 200, {"items": [], "total": 0}


def handle_admin_foundation_suspend(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """POST /api/admin/foundations/{id}/suspend - Suspend foundation (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    foundation = service.get_foundation(foundation_id)
    
    if not foundation:
        return 404, {"error": "Foundation not found"}
    
    # Use pipeline processing for suspend
    admin_id = session.get('username', 'admin')
    result = service.process_pipeline(foundation_id, admin_id, 'suspended', 'Suspended by admin')
    
    if result.success:
        return 200, {"success": True, "message": "Foundation suspended", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_admin_foundation_reject(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/admin/foundations/{id}/reject - Reject foundation (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    admin_id = session.get('username', 'admin')
    reason = body_data.get('reason', '')
    
    result = service.reject_foundation(foundation_id, admin_id, reason)
    
    if result.success:
        return 200, {"success": True, "message": "Foundation rejected", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_admin_foundation_activate(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """POST /api/admin/foundations/{id}/activate - Activate foundation (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    admin_id = session.get('username', 'admin')
    
    result = service.activate_foundation(foundation_id, admin_id, is_admin=True)
    
    if result.success:
        return 200, {"success": True, "message": "Foundation activated", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_admin_foundation_process_pipeline(session: Dict, foundation_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/admin/foundations/{id}/process-pipeline - Process foundation through pipeline (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    admin_id = session.get('username', 'admin')
    target_stage = body_data.get('target_stage', '')
    notes = body_data.get('notes', '')
    
    if not target_stage:
        return 400, {"error": "target_stage is required"}
    
    result = service.process_pipeline(foundation_id, admin_id, target_stage, notes)
    
    if result.success:
        return 200, {"success": True, "message": f"Foundation processed to {target_stage}", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_admin_foundation_members(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """GET /api/admin/foundations/{id}/members - Get foundation members (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    foundation = service.get_foundation(foundation_id)
    
    if not foundation:
        return 404, {"error": "Foundation not found"}
    
    members = service.get_foundation_members(foundation_id, include_pending=True)
    
    return 200, {
        "items": members,
        "total": len(members),
        "foundation_id": foundation_id,
        "foundation_name": foundation.get('name')
    }


def handle_admin_foundation_member_update(session: Dict, foundation_id: str, member_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """PUT /api/admin/foundations/{foundation_id}/members/{member_id} - Update member details (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    admin_id = session.get('username', 'admin')
    
    result = service.update_member_details(
        foundation_id=foundation_id,
        member_record_id=member_id,
        actor_id=admin_id,
        display_name=body_data.get('display_name'),
        email=body_data.get('email'),
        phone=body_data.get('phone'),
        photo_url=body_data.get('photo_url')
    )
    
    if result.success:
        return 200, {"success": True, "message": "Member updated", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_admin_foundation_member_photo(session: Dict, foundation_id: str, member_id: str, body_data: Dict) -> Tuple[int, Dict]:
    """POST /api/admin/foundations/{foundation_id}/members/{member_id}/photo - Update member photo (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    admin_id = session.get('username', 'admin')
    photo_url = body_data.get('photo_url', '')
    
    if not photo_url:
        return 400, {"error": "photo_url is required"}
    
    result = service.update_member_photo(
        foundation_id=foundation_id,
        member_record_id=member_id,
        photo_url=photo_url,
        actor_id=admin_id
    )
    
    if result.success:
        return 200, {"success": True, "message": "Member photo updated", "data": result.data}
    else:
        return 400, {"success": False, "error": result.error_message}


def handle_admin_foundation_activities(session: Dict, foundation_id: str) -> Tuple[int, Dict]:
    """GET /api/admin/foundations/{id}/activities - Get foundation activities (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 503, {"error": "Foundation service not available"}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    foundation = service.get_foundation(foundation_id)
    
    if not foundation:
        return 404, {"error": "Foundation not found"}
    
    activities = service.get_foundation_activities(foundation_id, limit=100)
    
    # Add foundation name to each activity
    for activity in activities:
        activity['foundation_name'] = foundation.get('name')
    
    return 200, {
        "items": activities,
        "total": len(activities),
        "foundation_id": foundation_id,
        "foundation_name": foundation.get('name')
    }


def handle_admin_all_activities(session: Dict, query_params: Dict) -> Tuple[int, Dict]:
    """GET /api/admin/foundations/all-activities - Get all recent activities (admin only)"""
    if not FOUNDATION_SERVICE_AVAILABLE:
        return 200, {"items": [], "total": 0}
    
    if not session or session.get('role') != 'admin':
        return 403, {"error": "Admin access required"}
    
    service = get_foundation_service()
    foundations = service.list_foundations(limit=1000)
    
    all_activities = []
    for foundation in foundations:
        activities = service.get_foundation_activities(foundation['id'], limit=20)
        for activity in activities:
            activity['foundation_name'] = foundation.get('name')
        all_activities.extend(activities)
    
    # Sort by timestamp, most recent first
    all_activities.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Limit to 50 most recent
    limit = int(query_params.get('limit', ['50'])[0])
    all_activities = all_activities[:limit]
    
    return 200, {
        "items": all_activities,
        "total": len(all_activities)
    }


# ============================================================================
# ROUTE DISPATCHER
# ============================================================================

def dispatch_get(path: str, session: Dict, query_params: Dict, client_ip: str) -> Optional[Tuple[int, Dict]]:
    """
    Dispatch GET requests to appropriate handlers.
    Returns (status_code, response_dict) or None if path not handled.
    """
    # Foundation invitations validation (public)
    # Support both query param (?code=XXX) and path param (/validate/XXX) formats
    if path == '/api/invitations/validate' or path == '/api/foundation-invitations/validate':
        code = query_params.get('code', [''])[0]
        return handle_invitation_validate(code)
    
    # Handle path parameter format: /api/foundation-invitations/validate/{code}
    if path.startswith('/api/foundation-invitations/validate/'):
        code = path.split('/')[-1]
        return handle_invitation_validate(code)
    
    # Foundation list
    if path == '/api/foundations':
        return handle_foundations_list(session, query_params)
    
    # Foundation invitations for user
    if path == '/api/foundation-invitations':
        return handle_foundation_invitations_list(session)
    
    # Foundation ledger (NFT ledger for user)
    if path == '/api/foundation-ledger':
        return handle_foundation_ledger(session, query_params)
    
    # Comprehensive NFT ledger with all transaction types
    if path == '/api/foundation-ledger/comprehensive':
        return handle_comprehensive_ledger(session, query_params)
    
    # Vote statistics
    if path == '/api/foundation-votes/statistics':
        return handle_vote_statistics(session, query_params)
    
    # Wallet balance
    if path == '/api/foundation-wallet/balance':
        return handle_wallet_balance(session)
    
    # Foundation activity log
    if path == '/api/foundation-activity':
        return handle_foundation_activity_log(session, query_params)
    
    # Foundation billing dashboard - for customer dashboard integration
    if path == '/api/foundation-billing-dashboard':
        return handle_foundation_billing_dashboard(session, query_params)
    
    # Foundation persistence status (admin only)
    if path == '/api/foundations/persistence-status':
        return handle_foundation_persistence_status(session)
    
    # Contribution AI assessment
    if path == '/api/contribution-assessment':
        return handle_contribution_ai_assessment(session, query_params)
    
    # Contribution ledger (payment transactions)
    if path == '/api/contribution-ledger':
        return handle_contribution_ledger(session, query_params)
    
    # Admin: Contribution dashboard
    if path == '/api/admin/contribution-dashboard':
        return handle_admin_contribution_dashboard(session)
    
    # Accounting: Contribution dashboard
    if path == '/api/accounting/contribution-dashboard':
        return handle_accounting_contribution_dashboard(session)
    
    # Foundation-specific endpoints
    if path.startswith('/api/foundations/') and not path.startswith('/api/foundations/join'):
        parts = path.split('/')
        
        # /api/foundations/{id}
        if len(parts) == 4:
            foundation_id = parts[3]
            return handle_foundation_get(session, foundation_id)
        
        # /api/foundations/{id}/{resource}
        if len(parts) == 5:
            foundation_id = parts[3]
            resource = parts[4]
            
            if resource == 'members':
                return handle_foundation_members_list(session, foundation_id, query_params)
            elif resource == 'votes':
                return handle_foundation_votes_list(session, foundation_id, query_params)
            elif resource == 'claims':
                return handle_foundation_claims_list(session, foundation_id, query_params)
            elif resource == 'billing':
                return handle_foundation_billing(session, foundation_id)
            elif resource == 'report':
                return handle_foundation_report(session, foundation_id, query_params)
            elif resource == 'activities':
                return handle_foundation_activities(session, foundation_id, query_params)
        
        # /api/foundations/{id}/export/{format}
        if len(parts) == 6 and parts[4] == 'export':
            foundation_id = parts[3]
            export_format = parts[5]
            
            if export_format == 'csv':
                return handle_foundation_csv_report(session, foundation_id, query_params)
        
        # /api/foundations/{id}/votes/{vote_id}
        if len(parts) == 6 and parts[4] == 'votes':
            foundation_id = parts[3]
            vote_id = parts[5]
            return handle_foundation_vote_get(session, foundation_id, vote_id)
        
        # /api/foundations/{id}/members/{member_id}/billing
        if len(parts) == 7 and parts[4] == 'members' and parts[6] == 'billing':
            foundation_id = parts[3]
            member_user_id = parts[5]
            return handle_foundation_member_billing(session, foundation_id, member_user_id)
    
    # Admin: Foundation stats
    if path == '/api/admin/foundations/stats':
        return handle_admin_foundations_stats(session)
    
    # Admin: Foundation activity (legacy endpoint)
    if path == '/api/admin/foundations/activity':
        return handle_admin_all_activities(session, query_params)
    
    # Admin: All activities
    if path == '/api/admin/foundations/all-activities':
        return handle_admin_all_activities(session, query_params)
    
    # Admin: Foundation list
    if path == '/api/admin/foundations':
        return handle_admin_foundations_list(session, query_params)
    
    # Admin: Foundation specific activities
    if '/activities' in path and path.startswith('/api/admin/foundations/'):
        parts = path.split('/')
        # /api/admin/foundations/{id}/activities
        if len(parts) == 6 and parts[5] == 'activities':
            foundation_id = parts[4]
            return handle_admin_foundation_activities(session, foundation_id)
    
    # Admin: Foundation members
    if '/members' in path and path.startswith('/api/admin/foundations/'):
        parts = path.split('/')
        # /api/admin/foundations/{id}/members
        if len(parts) == 6 and parts[5] == 'members':
            foundation_id = parts[4]
            return handle_admin_foundation_members(session, foundation_id)
    
    # Admin: Foundation details
    if path.startswith('/api/admin/foundations/') and path.count('/') == 4:
        foundation_id = path.split('/')[-1]
        return handle_admin_foundation_get(session, foundation_id)
    
    return None


def dispatch_post(path: str, session: Dict, body_data: Dict, client_ip: str, user_agent: str = "") -> Optional[Tuple[int, Dict]]:
    """
    Dispatch POST requests to appropriate handlers.
    Returns (status_code, response_dict) or None if path not handled.
    """
    # Security: CAPTCHA
    if path == '/api/security/captcha':
        return handle_captcha_create(client_ip, body_data)
    
    if path == '/api/security/captcha/verify':
        return handle_captcha_verify(client_ip, body_data)
    
    # Security: OTP
    if path == '/api/security/otp/request':
        return handle_otp_request(client_ip, body_data, user_agent)
    
    if path == '/api/security/otp/verify':
        return handle_otp_verify(client_ip, body_data)
    
    if path == '/api/security/otp/resend':
        return handle_otp_resend(client_ip, body_data, user_agent)
    
    # Security: Login check
    if path == '/api/security/login/check':
        return handle_login_check(client_ip, body_data, user_agent)
    
    # Foundation: Create
    if path == '/api/foundations':
        return handle_foundation_create(session, body_data)
    
    # Foundation: Join
    if path == '/api/foundations/join':
        return handle_foundation_join(session, body_data)
    
    # Foundation: Create backup (admin only)
    if path == '/api/foundations/backup':
        return handle_foundation_create_backup(session)
    
    # Wallet: Deposit
    if path == '/api/foundation-wallet/deposit':
        return handle_wallet_deposit(session, body_data)
    
    # Contribution document upload (supports up to 500MB)
    if path == '/api/contribution-documents/upload':
        return handle_contribution_document_upload(session, body_data)
    
    # Foundation-specific POST endpoints
    if path.startswith('/api/foundations/') and not path.startswith('/api/admin/'):
        parts = path.split('/')
        
        # /api/foundations/{id}/{action}
        if len(parts) == 5:
            foundation_id = parts[3]
            action = parts[4]
            
            if action == 'activate':
                return handle_foundation_activate(session, foundation_id)
            elif action == 'contribute':
                return handle_foundation_contribute(session, foundation_id, body_data)
            elif action == 'contribute-billing':
                return handle_contribution_with_billing(session, foundation_id, body_data)
            elif action == 'invite':
                return handle_foundation_invite(session, foundation_id, body_data)
            elif action == 'votes':
                return handle_foundation_vote_create(session, foundation_id, body_data)
            elif action == 'claims':
                return handle_foundation_claim_submit(session, foundation_id, body_data)
        
        # /api/foundations/{id}/members/{member_id}/{action}
        if len(parts) == 7 and parts[4] == 'members':
            foundation_id = parts[3]
            member_id = parts[5]
            action = parts[6]
            
            if action == 'approve':
                return handle_foundation_member_approve(session, foundation_id, member_id)
            elif action == 'reject':
                return handle_foundation_member_reject(session, foundation_id, member_id, body_data)
            elif action == 'remove':
                return handle_foundation_member_remove(session, foundation_id, member_id, body_data)
            elif action == 'role':
                return handle_foundation_member_role(session, foundation_id, member_id, body_data)
        
        # /api/foundations/{id}/votes/{vote_id}/{action}
        if len(parts) == 7 and parts[4] == 'votes':
            foundation_id = parts[3]
            vote_id = parts[5]
            action = parts[6]
            
            if action == 'cast':
                return handle_foundation_vote_cast(session, foundation_id, vote_id, body_data)
            elif action == 'close':
                return handle_foundation_vote_close(session, foundation_id, vote_id)
            elif action == 'approve':
                return handle_foundation_vote_approve(session, foundation_id, vote_id)
        
        # /api/foundations/{id}/claims/{claim_id}/{action}
        if len(parts) == 7 and parts[4] == 'claims':
            foundation_id = parts[3]
            claim_id = parts[5]
            action = parts[6]
            
            if action == 'approve':
                return handle_foundation_claim_approve(session, foundation_id, claim_id, body_data)
    
    # Admin: Suspend foundation
    if path.endswith('/suspend') and path.startswith('/api/admin/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_admin_foundation_suspend(session, foundation_id)
    
    # Admin: Reject foundation
    if path.endswith('/reject') and path.startswith('/api/admin/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_admin_foundation_reject(session, foundation_id, body_data)
    
    # Admin: Activate foundation
    if path.endswith('/activate') and path.startswith('/api/admin/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_admin_foundation_activate(session, foundation_id)
    
    # Admin: Process pipeline
    if path.endswith('/process-pipeline') and path.startswith('/api/admin/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_admin_foundation_process_pipeline(session, foundation_id, body_data)
    
    # Admin: Update member photo
    if '/members/' in path and path.endswith('/photo') and path.startswith('/api/admin/foundations/'):
        parts = path.split('/')
        # /api/admin/foundations/{fid}/members/{mid}/photo
        if len(parts) == 8 and parts[5] == 'members' and parts[7] == 'photo':
            foundation_id = parts[4]
            member_id = parts[6]
            return handle_admin_foundation_member_photo(session, foundation_id, member_id, body_data)
    
    return None


def dispatch_put(path: str, session: Dict, body_data: Dict, client_ip: str, user_agent: str = "") -> Optional[Tuple[int, Dict]]:
    """
    Dispatch PUT requests to appropriate handlers.
    Returns (status_code, response_dict) or None if path not handled.
    """
    # Admin: Update member details
    if '/members/' in path and path.startswith('/api/admin/foundations/'):
        parts = path.split('/')
        # /api/admin/foundations/{fid}/members/{mid}
        if len(parts) == 7 and parts[5] == 'members':
            foundation_id = parts[4]
            member_id = parts[6]
            return handle_admin_foundation_member_update(session, foundation_id, member_id, body_data)
    
    return None
