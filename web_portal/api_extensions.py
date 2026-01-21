"""
PHINS API Extensions for Community Foundations and OTP Security

This module provides API handlers for:
- Community Foundation management
- OTP Security (CAPTCHA, login verification)
- Device trust management

Integration with server.py:
  Import and call these handlers from do_GET/do_POST based on path matching.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

# Import services
try:
    from services.foundation_service import (
        get_foundation_service,
        FoundationCreateRequest,
    )
    FOUNDATION_SERVICE_AVAILABLE = True
except ImportError:
    FOUNDATION_SERVICE_AVAILABLE = False
    print("Warning: Foundation service not available")

try:
    from services.otp_security_service import (
        get_otp_security_service,
        OTPPurpose,
    )
    OTP_SERVICE_AVAILABLE = True
except ImportError:
    OTP_SERVICE_AVAILABLE = False
    print("Warning: OTP security service not available")


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
    
    # Foundation details
    if path.startswith('/api/foundations/') and path.count('/') == 3:
        foundation_id = path.split('/')[-1]
        return handle_foundation_get(session, foundation_id)
    
    # Foundation invitations for user
    if path == '/api/foundation-invitations':
        return handle_foundation_invitations_list(session)
    
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
    
    # Foundation: Activate
    if path.endswith('/activate') and path.startswith('/api/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_foundation_activate(session, foundation_id)
    
    # Foundation: Contribute
    if path.endswith('/contribute') and path.startswith('/api/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_foundation_contribute(session, foundation_id, body_data)
    
    # Foundation: Invite
    if path.endswith('/invite') and path.startswith('/api/foundations/'):
        foundation_id = path.split('/')[-2]
        return handle_foundation_invite(session, foundation_id, body_data)
    
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
