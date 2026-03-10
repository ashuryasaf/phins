"""
Supplier Management Service for PHINS Platform

Handles all supplier-related business logic including:
- Supplier registration and onboarding
- Approval workflow with AI risk assessment
- Supplier offer management
- Order processing and fulfillment
- Wallet integration for payments
- Performance metrics and analytics

Author: PHINS Engineering Team
Version: 1.0
"""

import json
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
import random


class SupplierManagementService:
    """
    Comprehensive service for managing B2B supplier ecosystem.
    
    Features:
    - Supplier registration with AI-powered risk assessment
    - Approval workflow (auto-approve, manual review, auto-reject)
    - Offer management (services and products)
    - Order processing with wallet integration
    - Performance analytics and BI insights
    """
    
    def __init__(self, suppliers_store: Dict = None, offers_store: Dict = None, 
                 orders_store: Dict = None, documents_store: Dict = None):
        """
        Initialize the supplier management service.
        
        Args:
            suppliers_store: In-memory or DB-backed supplier storage
            offers_store: In-memory or DB-backed offers storage
            orders_store: In-memory or DB-backed orders storage
            documents_store: In-memory or DB-backed documents storage
        """
        self.suppliers = suppliers_store if suppliers_store is not None else {}
        self.offers = offers_store if offers_store is not None else {}
        self.orders = orders_store if orders_store is not None else {}
        self.documents = documents_store if documents_store is not None else {}
        
        # Supplier types with their categories
        self.supplier_types = {
            'healthcare_provider': {
                'category': 'medical',
                'sub_categories': ['hospital', 'clinic', 'doctor', 'specialist', 'therapist', 'home_care'],
                'wallet_types': ['health'],
                'risk_weight': 0.8  # Healthcare requires high scrutiny
            },
            'pharmacy': {
                'category': 'medical',
                'sub_categories': ['retail', 'online', 'specialty', 'compounding'],
                'wallet_types': ['health'],
                'risk_weight': 0.9  # Pharmacies require very high scrutiny
            },
            'legal_service': {
                'category': 'legal',
                'sub_categories': ['insurance_law', 'personal_injury', 'medical_malpractice', 'estate_planning'],
                'wallet_types': ['health', 'general'],
                'risk_weight': 0.7
            },
            'delivery': {
                'category': 'logistics',
                'sub_categories': ['medical_equipment', 'prescription', 'document', 'emergency_transport'],
                'wallet_types': ['health', 'general'],
                'risk_weight': 0.5
            },
            'investment_firm': {
                'category': 'financial',
                'sub_categories': ['asset_management', 'pension_funds', 'index_funds', 'crypto_assets'],
                'wallet_types': ['investment'],
                'risk_weight': 0.95  # Financial services require highest scrutiny
            },
            'equipment_supplier': {
                'category': 'medical',
                'sub_categories': ['wheelchairs', 'cpap', 'home_devices', 'rehabilitation'],
                'wallet_types': ['health'],
                'risk_weight': 0.6
            },
            'tech_provider': {
                'category': 'tech',
                'sub_categories': ['telemedicine', 'health_apps', 'insurance_tech', 'ai_services'],
                'wallet_types': ['health', 'investment', 'general'],
                'risk_weight': 0.5
            },
            'laboratory': {
                'category': 'medical',
                'sub_categories': ['diagnostic', 'imaging', 'pathology', 'genetic_testing'],
                'wallet_types': ['health'],
                'risk_weight': 0.8
            },
            'wellness': {
                'category': 'health',
                'sub_categories': ['wellness_programs', 'rehabilitation', 'fitness', 'nutrition'],
                'wallet_types': ['health'],
                'risk_weight': 0.4
            },
            'other': {
                'category': 'other',
                'sub_categories': ['other'],
                'wallet_types': ['general'],
                'risk_weight': 0.6
            }
        }
        
        # Commission rates by supplier type
        self.commission_rates = {
            'healthcare_provider': 0.05,  # 5%
            'pharmacy': 0.08,  # 8%
            'legal_service': 0.10,  # 10%
            'delivery': 0.12,  # 12%
            'investment_firm': 0.02,  # 2%
            'equipment_supplier': 0.10,  # 10%
            'tech_provider': 0.15,  # 15%
            'laboratory': 0.07,  # 7%
            'wellness': 0.12,  # 12%
            'other': 0.10  # 10%
        }
    
    # =========================================================================
    # SUPPLIER REGISTRATION
    # =========================================================================
    
    def generate_supplier_id(self) -> str:
        """Generate a unique supplier ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"SUP-{timestamp}-{random_part}"
    
    def generate_offer_id(self) -> str:
        """Generate a unique offer ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"OFF-{timestamp}-{random_part}"
    
    def generate_order_id(self) -> str:
        """Generate a unique order ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"ORD-{timestamp}-{random_part}"
    
    def generate_document_id(self) -> str:
        """Generate a unique document ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"DOC-{timestamp}-{random_part}"
    
    def hash_password(self, password: str) -> Tuple[str, str]:
        """
        Hash a password with a random salt.
        
        Returns:
            Tuple of (password_hash, salt)
        """
        salt = secrets.token_hex(32)
        password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        return password_hash, salt
    
    def verify_password(self, password: str, password_hash: str, salt: str) -> bool:
        """Verify a password against its hash and salt."""
        computed_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        return computed_hash == password_hash
    
    def register_supplier(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new supplier application.
        
        Args:
            data: Supplier registration data including:
                - company_name (required)
                - contact_email (required)
                - contact_name (required)
                - supplier_type (required)
                - password (required)
                - Other optional fields
        
        Returns:
            Created supplier record with AI assessment
        """
        # Validate required fields
        required_fields = ['company_name', 'contact_email', 'contact_name', 'supplier_type', 'password']
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
        # Check for duplicate email
        for supplier in self.suppliers.values():
            if supplier.get('contact_email', '').lower() == data['contact_email'].lower():
                raise ValueError(f"Email {data['contact_email']} is already registered")
        
        # Validate supplier type
        supplier_type = data['supplier_type']
        if supplier_type not in self.supplier_types:
            raise ValueError(f"Invalid supplier type. Must be one of: {', '.join(self.supplier_types.keys())}")
        
        # Generate ID and hash password
        supplier_id = self.generate_supplier_id()
        password_hash, salt = self.hash_password(data['password'])
        
        # Get type configuration
        type_config = self.supplier_types[supplier_type]
        
        # Build supplier record
        now = datetime.now(timezone.utc)
        supplier = {
            'id': supplier_id,
            'company_name': data['company_name'].strip(),
            'business_registration_number': data.get('business_registration_number', '').strip() or None,
            'tax_id': data.get('tax_id', '').strip() or None,
            'supplier_type': supplier_type,
            'category': type_config['category'],
            'sub_category': data.get('sub_category', '').strip() or None,
            'description': data.get('description', '').strip() or None,
            'services_offered': json.dumps(data.get('services_offered', [])),
            'products_offered': json.dumps(data.get('products_offered', [])),
            'service_areas': json.dumps(data.get('service_areas', [])),
            
            # Contact info
            'contact_name': data['contact_name'].strip(),
            'contact_email': data['contact_email'].strip().lower(),
            'contact_phone': data.get('contact_phone', '').strip() or None,
            'website': data.get('website', '').strip() or None,
            'address': data.get('address', '').strip() or None,
            'city': data.get('city', '').strip() or None,
            'state': data.get('state', '').strip() or None,
            'country': data.get('country', 'United States').strip(),
            'postal_code': data.get('postal_code', '').strip() or None,
            
            # Authentication
            'password_hash': password_hash,
            'password_salt': salt,
            'portal_active': False,  # Activated after approval
            'last_login': None,
            
            # Status
            'status': 'pending',
            'application_date': now.isoformat(),
            'review_date': None,
            'approval_date': None,
            'approved_by': None,
            'rejection_reason': None,
            'suspension_reason': None,
            
            # AI Assessment (performed during registration)
            'ai_risk_score': None,
            'ai_trust_score': None,
            'ai_recommendation': None,
            'ai_assessment_date': None,
            'ai_assessment_notes': None,
            
            # Verification
            'verification_status': 'pending',
            'documents_verified': False,
            'documents_metadata': json.dumps([]),
            'license_number': data.get('license_number', '').strip() or None,
            'license_expiry': data.get('license_expiry'),
            'insurance_certificate': data.get('insurance_certificate'),
            'insurance_expiry': data.get('insurance_expiry'),
            
            # Wallet Configuration
            'wallet_types_supported': json.dumps(type_config['wallet_types']),
            'payment_methods': json.dumps(data.get('payment_methods', ['wallet'])),
            'bank_details': json.dumps(data.get('bank_details', {})) if data.get('bank_details') else None,
            'crypto_wallet': data.get('crypto_wallet'),
            'commission_rate': self.commission_rates.get(supplier_type, 0.10),
            'settlement_frequency': data.get('settlement_frequency', 'weekly'),
            
            # Performance (initialized)
            'total_orders': 0,
            'total_revenue': 0.0,
            'average_rating': 0.0,
            'total_reviews': 0,
            'dispute_count': 0,
            'dispute_resolution_rate': 1.0,
            
            # Timestamps
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        
        # Perform AI risk assessment
        ai_assessment = self.assess_supplier_risk(supplier)
        supplier['ai_risk_score'] = ai_assessment['risk_score']
        supplier['ai_trust_score'] = ai_assessment['trust_score']
        supplier['ai_recommendation'] = ai_assessment['recommendation']
        supplier['ai_assessment_date'] = now.isoformat()
        supplier['ai_assessment_notes'] = json.dumps(ai_assessment['notes'])
        
        # Store supplier
        self.suppliers[supplier_id] = supplier
        
        return {
            'success': True,
            'supplier_id': supplier_id,
            'status': supplier['status'],
            'ai_recommendation': ai_assessment['recommendation'],
            'message': f"Application submitted successfully. ID: {supplier_id}"
        }
    
    # =========================================================================
    # AI RISK ASSESSMENT
    # =========================================================================
    
    def assess_supplier_risk(self, supplier: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform AI-powered risk assessment for a supplier.
        
        This simulates an AI model that evaluates:
        - Business completeness (all required info provided)
        - Document verification status
        - Industry risk factors
        - Geographic risk factors
        - Historical patterns (for existing suppliers)
        
        Returns:
            Risk assessment with recommendation
        """
        risk_factors = []
        trust_factors = []
        
        # Base scores
        base_risk = 0.3
        base_trust = 0.7
        
        supplier_type = supplier.get('supplier_type', 'other')
        type_config = self.supplier_types.get(supplier_type, self.supplier_types['other'])
        
        # 1. Business Information Completeness
        info_fields = ['company_name', 'contact_name', 'contact_email', 'address', 
                       'city', 'state', 'country', 'postal_code']
        filled_fields = sum(1 for f in info_fields if supplier.get(f))
        completeness = filled_fields / len(info_fields)
        
        if completeness >= 0.9:
            trust_factors.append({'factor': 'complete_business_info', 'impact': 0.1})
            base_trust += 0.1
        elif completeness < 0.7:
            risk_factors.append({'factor': 'incomplete_business_info', 'impact': 0.15})
            base_risk += 0.15
        
        # 2. Business Registration & Tax ID
        if supplier.get('business_registration_number'):
            trust_factors.append({'factor': 'business_registered', 'impact': 0.08})
            base_trust += 0.08
        else:
            risk_factors.append({'factor': 'no_business_registration', 'impact': 0.1})
            base_risk += 0.1
        
        if supplier.get('tax_id'):
            trust_factors.append({'factor': 'tax_id_provided', 'impact': 0.05})
            base_trust += 0.05
        
        # 3. Industry Risk Weight
        industry_risk = type_config.get('risk_weight', 0.5)
        if industry_risk > 0.8:
            risk_factors.append({'factor': f'high_risk_industry_{supplier_type}', 'impact': 0.15})
            base_risk += 0.15
        elif industry_risk < 0.5:
            trust_factors.append({'factor': f'low_risk_industry_{supplier_type}', 'impact': 0.05})
            base_trust += 0.05
        
        # 4. Contact Information Quality
        if supplier.get('contact_phone') and supplier.get('website'):
            trust_factors.append({'factor': 'complete_contact_info', 'impact': 0.05})
            base_trust += 0.05
        
        # 5. License and Insurance
        if supplier.get('license_number'):
            trust_factors.append({'factor': 'license_provided', 'impact': 0.1})
            base_trust += 0.1
        elif supplier_type in ['healthcare_provider', 'pharmacy', 'legal_service']:
            risk_factors.append({'factor': 'missing_required_license', 'impact': 0.2})
            base_risk += 0.2
        
        # 6. Services/Products Offered
        services = json.loads(supplier.get('services_offered', '[]'))
        products = json.loads(supplier.get('products_offered', '[]'))
        if len(services) + len(products) > 0:
            trust_factors.append({'factor': 'offerings_specified', 'impact': 0.05})
            base_trust += 0.05
        
        # Calculate final scores (clamped to 0-1)
        risk_score = min(max(base_risk, 0.0), 1.0)
        trust_score = min(max(base_trust, 0.0), 1.0)
        
        # Normalize so risk + trust don't exceed certain threshold
        combined = risk_score + trust_score
        if combined > 1.5:
            adjustment = (combined - 1.5) / 2
            risk_score = max(risk_score - adjustment, 0.0)
            trust_score = max(trust_score - adjustment, 0.0)
        
        # Determine recommendation
        if trust_score >= 0.8 and risk_score <= 0.3:
            recommendation = 'approve'
        elif risk_score >= 0.7 or trust_score <= 0.4:
            recommendation = 'reject'
        else:
            recommendation = 'review'
        
        return {
            'risk_score': round(risk_score, 3),
            'trust_score': round(trust_score, 3),
            'recommendation': recommendation,
            'notes': {
                'risk_factors': risk_factors,
                'trust_factors': trust_factors,
                'industry_risk_weight': industry_risk,
                'info_completeness': completeness,
                'assessment_version': '1.0'
            }
        }
    
    # =========================================================================
    # APPROVAL WORKFLOW
    # =========================================================================
    
    def get_pending_suppliers(self, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Get list of pending supplier applications."""
        pending = [s for s in self.suppliers.values() if s.get('status') == 'pending']
        
        # Sort by application date (newest first)
        pending.sort(key=lambda x: x.get('application_date', ''), reverse=True)
        
        # Paginate
        total = len(pending)
        start = (page - 1) * page_size
        end = start + page_size
        items = pending[start:end]
        
        return {
            'items': items,
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': (total + page_size - 1) // page_size
        }
    
    def approve_supplier(self, supplier_id: str, approved_by: str, notes: str = None) -> Dict[str, Any]:
        """
        Approve a supplier application.
        
        Args:
            supplier_id: ID of supplier to approve
            approved_by: Username of admin approving
            notes: Optional approval notes
        
        Returns:
            Updated supplier record
        """
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        supplier = self.suppliers[supplier_id]
        
        if supplier['status'] not in ['pending', 'under_review']:
            raise ValueError(f"Supplier is already {supplier['status']}")
        
        now = datetime.now(timezone.utc)
        supplier['status'] = 'approved'
        supplier['approval_date'] = now.isoformat()
        supplier['approved_by'] = approved_by
        supplier['portal_active'] = True
        supplier['updated_date'] = now.isoformat()
        
        if notes:
            current_notes = json.loads(supplier.get('ai_assessment_notes', '{}'))
            current_notes['approval_notes'] = notes
            supplier['ai_assessment_notes'] = json.dumps(current_notes)
        
        return {
            'success': True,
            'supplier_id': supplier_id,
            'status': 'approved',
            'message': f"Supplier {supplier['company_name']} approved successfully"
        }
    
    def reject_supplier(self, supplier_id: str, rejected_by: str, reason: str) -> Dict[str, Any]:
        """
        Reject a supplier application.
        
        Args:
            supplier_id: ID of supplier to reject
            rejected_by: Username of admin rejecting
            reason: Reason for rejection (required)
        
        Returns:
            Updated supplier record
        """
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        if not reason:
            raise ValueError("Rejection reason is required")
        
        supplier = self.suppliers[supplier_id]
        
        if supplier['status'] not in ['pending', 'under_review']:
            raise ValueError(f"Supplier is already {supplier['status']}")
        
        now = datetime.now(timezone.utc)
        supplier['status'] = 'rejected'
        supplier['rejection_reason'] = reason
        supplier['review_date'] = now.isoformat()
        supplier['portal_active'] = False
        supplier['updated_date'] = now.isoformat()
        
        return {
            'success': True,
            'supplier_id': supplier_id,
            'status': 'rejected',
            'message': f"Supplier {supplier['company_name']} rejected"
        }
    
    def suspend_supplier(self, supplier_id: str, suspended_by: str, reason: str) -> Dict[str, Any]:
        """Suspend an active supplier."""
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        if not reason:
            raise ValueError("Suspension reason is required")
        
        supplier = self.suppliers[supplier_id]
        
        if supplier['status'] != 'approved':
            raise ValueError(f"Can only suspend approved suppliers")
        
        now = datetime.now(timezone.utc)
        supplier['status'] = 'suspended'
        supplier['suspension_reason'] = reason
        supplier['portal_active'] = False
        supplier['updated_date'] = now.isoformat()
        
        return {
            'success': True,
            'supplier_id': supplier_id,
            'status': 'suspended',
            'message': f"Supplier {supplier['company_name']} suspended"
        }
    
    def reactivate_supplier(self, supplier_id: str, reactivated_by: str) -> Dict[str, Any]:
        """Reactivate a suspended supplier."""
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        supplier = self.suppliers[supplier_id]
        
        if supplier['status'] != 'suspended':
            raise ValueError(f"Can only reactivate suspended suppliers")
        
        now = datetime.now(timezone.utc)
        supplier['status'] = 'approved'
        supplier['suspension_reason'] = None
        supplier['portal_active'] = True
        supplier['updated_date'] = now.isoformat()
        
        return {
            'success': True,
            'supplier_id': supplier_id,
            'status': 'approved',
            'message': f"Supplier {supplier['company_name']} reactivated"
        }
    
    # =========================================================================
    # SUPPLIER AUTHENTICATION
    # =========================================================================
    
    # Accounts created before this date bypass OTP and are granted
    # credential auto-provisioning on first login.
    LEGACY_ACCOUNT_CUTOFF = datetime(2026, 3, 9, 0, 0, 0, tzinfo=timezone.utc)

    def authenticate_supplier(self, email: str, password: str) -> Dict[str, Any]:
        """
        Authenticate a supplier login.
        
        Returns:
            Supplier info if authenticated, raises ValueError otherwise
        """
        # Find supplier by email
        supplier = None
        for s in self.suppliers.values():
            if s.get('contact_email', '').lower() == email.lower():
                supplier = s
                break
        
        if not supplier:
            raise ValueError("Invalid email or password")
        
        # Check password – with legacy credential migration for pre-cutoff accounts
        has_credentials = bool(supplier.get('password_hash') and supplier.get('password_salt'))

        if has_credentials:
            if not self.verify_password(password, supplier['password_hash'],
                                        supplier['password_salt']):
                raise ValueError("Invalid email or password")
        else:
            created_raw = supplier.get('created_date') or supplier.get('application_date') or ''
            try:
                created = datetime.fromisoformat(created_raw).replace(tzinfo=timezone.utc) if created_raw else None
            except Exception:
                created = None
            is_legacy = (created is not None and created < self.LEGACY_ACCOUNT_CUTOFF)
            if not is_legacy:
                raise ValueError("Invalid email or password")
            pw_hash, pw_salt = self.hash_password(password)
            supplier['password_hash'] = pw_hash
            supplier['password_salt'] = pw_salt
            print(f"[SUPPLIER-AUTH] Legacy credential migration for supplier '{email}' (created {created_raw})")
        
        # Check status – legacy approved suppliers retain access
        if supplier['status'] != 'approved':
            raise ValueError(f"Account not active. Status: {supplier['status']}")
        
        if not supplier.get('portal_active'):
            # Auto-activate portal for legacy approved suppliers
            created_raw = supplier.get('created_date') or supplier.get('application_date') or ''
            try:
                created = datetime.fromisoformat(created_raw).replace(tzinfo=timezone.utc) if created_raw else None
            except Exception:
                created = None
            is_legacy = (created is not None and created < self.LEGACY_ACCOUNT_CUTOFF)
            if is_legacy:
                supplier['portal_active'] = True
                print(f"[SUPPLIER-AUTH] Auto-activated portal for legacy supplier '{email}'")
            else:
                raise ValueError("Portal access is disabled")
        
        # Update last login
        now = datetime.now(timezone.utc)
        supplier['last_login'] = now.isoformat()
        
        return {
            'id': supplier['id'],
            'company_name': supplier['company_name'],
            'contact_email': supplier['contact_email'],
            'supplier_type': supplier['supplier_type'],
            'role': 'supplier'
        }
    
    # =========================================================================
    # OFFER MANAGEMENT
    # =========================================================================
    
    def create_offer(self, supplier_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new supplier offer."""
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        supplier = self.suppliers[supplier_id]
        if supplier['status'] != 'approved':
            raise ValueError("Only approved suppliers can create offers")
        
        # Validate required fields
        required_fields = ['name', 'item_type', 'category', 'price']
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
        offer_id = data.get('id') or self.generate_offer_id()
        now = datetime.now(timezone.utc)
        
        # Get wallet types from supplier
        wallet_types = json.loads(supplier.get('wallet_types_supported', '["general"]'))
        
        offer = {
            'id': offer_id,
            'supplier_id': supplier_id,
            'name': data['name'].strip(),
            'description': data.get('description', '').strip() or None,
            'item_type': data['item_type'],  # service or product
            'category': data['category'],
            'sub_category': data.get('sub_category'),
            'price': float(data['price']),
            'currency': data.get('currency', 'USD'),
            'unit': data.get('unit', 'per_item'),
            'min_quantity': int(data.get('min_quantity', 1)),
            'max_quantity': int(data['max_quantity']) if data.get('max_quantity') else None,
            'wallet_compatible': json.dumps(data.get('wallet_compatible', wallet_types)),
            'active': data.get('active', True),
            'featured': data.get('featured', False),
            'image_url': data.get('image_url'),
            'availability': json.dumps(data.get('availability', {})) if data.get('availability') else None,
            'requires_appointment': data.get('requires_appointment', False),
            'lead_time_hours': int(data.get('lead_time_hours', 0)),
            'total_orders': 0,
            'total_revenue': 0.0,
            'average_rating': 0.0,
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        
        self.offers[offer_id] = offer
        
        return {
            'success': True,
            'offer_id': offer_id,
            'message': f"Offer '{data['name']}' created successfully"
        }
    
    def update_offer(self, offer_id: str, supplier_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing offer."""
        if offer_id not in self.offers:
            raise ValueError(f"Offer {offer_id} not found")
        
        offer = self.offers[offer_id]
        if offer['supplier_id'] != supplier_id:
            raise ValueError("Not authorized to update this offer")
        
        # Update allowed fields
        allowed_fields = ['name', 'description', 'price', 'currency', 'unit', 
                          'min_quantity', 'max_quantity', 'active', 'featured',
                          'image_url', 'availability', 'requires_appointment', 
                          'lead_time_hours', 'wallet_compatible']
        
        for field in allowed_fields:
            if field in data:
                if field in ['availability', 'wallet_compatible']:
                    offer[field] = json.dumps(data[field]) if data[field] else None
                else:
                    offer[field] = data[field]
        
        offer['updated_date'] = datetime.now(timezone.utc).isoformat()
        
        return {
            'success': True,
            'offer_id': offer_id,
            'message': "Offer updated successfully"
        }
    
    def delete_offer(self, offer_id: str, supplier_id: str) -> Dict[str, Any]:
        """Delete/deactivate an offer."""
        if offer_id not in self.offers:
            raise ValueError(f"Offer {offer_id} not found")
        
        offer = self.offers[offer_id]
        if offer['supplier_id'] != supplier_id:
            raise ValueError("Not authorized to delete this offer")
        
        # Soft delete (deactivate)
        offer['active'] = False
        offer['updated_date'] = datetime.now(timezone.utc).isoformat()
        
        return {
            'success': True,
            'offer_id': offer_id,
            'message': "Offer deactivated successfully"
        }
    
    def get_offers(self, supplier_id: str = None, category: str = None, 
                   active_only: bool = True, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Get offers with optional filtering."""
        offers = list(self.offers.values())
        
        # Filter by supplier
        if supplier_id:
            offers = [o for o in offers if o.get('supplier_id') == supplier_id]
        
        # Filter by category
        if category:
            offers = [o for o in offers if o.get('category') == category]
        
        # Filter active only
        if active_only:
            offers = [o for o in offers if o.get('active', True)]
        
        # Sort by created date (newest first)
        offers.sort(key=lambda x: x.get('created_date', ''), reverse=True)
        
        # Paginate
        total = len(offers)
        start = (page - 1) * page_size
        end = start + page_size
        items = offers[start:end]
        
        return {
            'items': items,
            'page': page,
            'page_size': page_size,
            'total': total
        }
    
    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================
    
    def create_order(self, customer_id: str, offer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new order from a customer to a supplier.
        
        Args:
            customer_id: Customer placing the order
            offer_id: Offer being ordered
            data: Order details (quantity, payment_method, delivery_address, etc.)
        
        Returns:
            Created order record
        """
        if offer_id not in self.offers:
            raise ValueError(f"Offer {offer_id} not found")
        
        offer = self.offers[offer_id]
        if not offer.get('active', True):
            raise ValueError("This offer is no longer available")
        
        supplier_id = offer['supplier_id']
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier not found")
        
        supplier = self.suppliers[supplier_id]
        if supplier['status'] != 'approved':
            raise ValueError("Supplier is not active")
        
        # Calculate amounts
        quantity = int(data.get('quantity', 1))
        unit_price = float(offer['price'])
        total_amount = unit_price * quantity
        commission_rate = supplier.get('commission_rate', 0.10)
        platform_fee = round(total_amount * commission_rate, 2)
        supplier_payout = round(total_amount - platform_fee, 2)
        
        order_id = self.generate_order_id()
        now = datetime.now(timezone.utc)
        
        order = {
            'id': order_id,
            'supplier_id': supplier_id,
            'customer_id': customer_id,
            'offer_id': offer_id,
            'order_type': offer.get('item_type', 'service'),
            'item_name': offer['name'],
            'item_description': offer.get('description'),
            'quantity': quantity,
            'unit_price': unit_price,
            'total_amount': total_amount,
            'platform_fee': platform_fee,
            'supplier_payout': supplier_payout,
            'payment_method': data.get('payment_method', 'health_wallet'),
            'wallet_transaction_id': None,
            'payment_status': 'pending',
            'payment_date': None,
            'status': 'pending',
            'delivery_address': data.get('delivery_address'),
            'delivery_notes': data.get('delivery_notes'),
            'scheduled_date': data.get('scheduled_date'),
            'estimated_delivery': None,
            'actual_delivery': None,
            'completed_date': None,
            'tracking_number': None,
            'tracking_url': None,
            'rating': None,
            'review': None,
            'review_date': None,
            'dispute_reason': None,
            'dispute_date': None,
            'dispute_resolution': None,
            'dispute_resolved_date': None,
            'cancelled_by': None,
            'cancellation_reason': None,
            'cancelled_date': None,
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        
        self.orders[order_id] = order
        
        return {
            'success': True,
            'order_id': order_id,
            'total_amount': total_amount,
            'payment_method': order['payment_method'],
            'message': f"Order created. Please complete payment."
        }
    
    def update_order_status(self, order_id: str, status: str, 
                           actor: str = None, notes: Dict = None) -> Dict[str, Any]:
        """Update order status."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        
        valid_statuses = ['pending', 'confirmed', 'processing', 'shipped', 
                         'in_progress', 'delivered', 'completed', 'cancelled', 
                         'refunded', 'disputed']
        if status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        
        order = self.orders[order_id]
        now = datetime.now(timezone.utc)
        
        order['status'] = status
        order['updated_date'] = now.isoformat()
        
        # Update related fields based on status
        if status == 'completed':
            order['completed_date'] = now.isoformat()
            # Update supplier metrics
            self._update_supplier_metrics(order['supplier_id'], order)
        elif status == 'delivered':
            order['actual_delivery'] = now.isoformat()
        elif status == 'cancelled':
            order['cancelled_date'] = now.isoformat()
            order['cancelled_by'] = actor
            if notes:
                order['cancellation_reason'] = notes.get('reason')
        elif status == 'disputed':
            order['dispute_date'] = now.isoformat()
            if notes:
                order['dispute_reason'] = notes.get('reason')
        
        return {
            'success': True,
            'order_id': order_id,
            'status': status,
            'message': f"Order status updated to {status}"
        }
    
    def _update_supplier_metrics(self, supplier_id: str, order: Dict[str, Any]):
        """Update supplier performance metrics after order completion."""
        if supplier_id not in self.suppliers:
            return
        
        supplier = self.suppliers[supplier_id]
        supplier['total_orders'] = int(supplier.get('total_orders', 0)) + 1
        supplier['total_revenue'] = float(supplier.get('total_revenue', 0)) + float(order.get('supplier_payout', 0))
        supplier['updated_date'] = datetime.now(timezone.utc).isoformat()
    
    def get_orders(self, supplier_id: str = None, customer_id: str = None,
                   status: str = None, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Get orders with optional filtering."""
        orders = list(self.orders.values())
        
        if supplier_id:
            orders = [o for o in orders if o.get('supplier_id') == supplier_id]
        
        if customer_id:
            orders = [o for o in orders if o.get('customer_id') == customer_id]
        
        if status:
            orders = [o for o in orders if o.get('status') == status]
        
        # Sort by created date (newest first)
        orders.sort(key=lambda x: x.get('created_date', ''), reverse=True)
        
        # Paginate
        total = len(orders)
        start = (page - 1) * page_size
        end = start + page_size
        items = orders[start:end]
        
        return {
            'items': items,
            'page': page,
            'page_size': page_size,
            'total': total
        }
    
    # =========================================================================
    # ANALYTICS & BI
    # =========================================================================
    
    def get_supplier_analytics(self, supplier_id: str = None) -> Dict[str, Any]:
        """
        Get supplier analytics for BI dashboard.
        
        If supplier_id provided, returns that supplier's analytics.
        Otherwise returns platform-wide supplier analytics.
        """
        if supplier_id:
            # Single supplier analytics
            if supplier_id not in self.suppliers:
                raise ValueError(f"Supplier {supplier_id} not found")
            
            supplier = self.suppliers[supplier_id]
            supplier_orders = [o for o in self.orders.values() if o.get('supplier_id') == supplier_id]
            supplier_offers = [o for o in self.offers.values() if o.get('supplier_id') == supplier_id]
            
            return {
                'supplier_id': supplier_id,
                'company_name': supplier['company_name'],
                'total_orders': len(supplier_orders),
                'total_revenue': sum(float(o.get('supplier_payout', 0)) for o in supplier_orders),
                'active_offers': len([o for o in supplier_offers if o.get('active', True)]),
                'average_rating': supplier.get('average_rating', 0.0),
                'orders_by_status': self._count_by_status(supplier_orders),
                'revenue_by_month': self._revenue_by_month(supplier_orders),
                'top_offers': self._top_offers(supplier_offers, supplier_orders)
            }
        else:
            # Platform-wide analytics
            suppliers = list(self.suppliers.values())
            orders = list(self.orders.values())
            offers = list(self.offers.values())
            
            return {
                'total_suppliers': len(suppliers),
                'active_suppliers': len([s for s in suppliers if s.get('status') == 'approved']),
                'pending_applications': len([s for s in suppliers if s.get('status') == 'pending']),
                'suppliers_by_type': self._count_by_field(suppliers, 'supplier_type'),
                'suppliers_by_status': self._count_by_field(suppliers, 'status'),
                'total_orders': len(orders),
                'total_revenue': sum(float(o.get('total_amount', 0)) for o in orders),
                'total_platform_fees': sum(float(o.get('platform_fee', 0)) for o in orders),
                'orders_by_status': self._count_by_status(orders),
                'total_offers': len(offers),
                'active_offers': len([o for o in offers if o.get('active', True)]),
                'ai_recommendations': {
                    'approve': len([s for s in suppliers if s.get('ai_recommendation') == 'approve']),
                    'review': len([s for s in suppliers if s.get('ai_recommendation') == 'review']),
                    'reject': len([s for s in suppliers if s.get('ai_recommendation') == 'reject'])
                }
            }
    
    def _count_by_status(self, items: List[Dict]) -> Dict[str, int]:
        """Count items by status."""
        counts = {}
        for item in items:
            status = item.get('status', 'unknown')
            counts[status] = counts.get(status, 0) + 1
        return counts
    
    def _count_by_field(self, items: List[Dict], field: str) -> Dict[str, int]:
        """Count items by a specific field."""
        counts = {}
        for item in items:
            value = item.get(field, 'unknown')
            counts[value] = counts.get(value, 0) + 1
        return counts
    
    def _revenue_by_month(self, orders: List[Dict]) -> Dict[str, float]:
        """Calculate revenue by month."""
        revenue = {}
        for order in orders:
            if order.get('status') in ['completed', 'delivered']:
                date_str = order.get('created_date', '')[:7]  # YYYY-MM
                if date_str:
                    revenue[date_str] = revenue.get(date_str, 0) + float(order.get('supplier_payout', 0))
        return revenue
    
    def _top_offers(self, offers: List[Dict], orders: List[Dict]) -> List[Dict]:
        """Get top performing offers."""
        offer_stats = {}
        for offer in offers:
            offer_id = offer['id']
            offer_orders = [o for o in orders if o.get('offer_id') == offer_id]
            offer_stats[offer_id] = {
                'id': offer_id,
                'name': offer['name'],
                'total_orders': len(offer_orders),
                'total_revenue': sum(float(o.get('supplier_payout', 0)) for o in offer_orders)
            }
        
        sorted_offers = sorted(offer_stats.values(), key=lambda x: x['total_revenue'], reverse=True)
        return sorted_offers[:10]
    
    def get_ai_insights(self) -> Dict[str, Any]:
        """
        Get AI-powered insights for the platform.
        
        Returns actionable insights for admin dashboard.
        """
        suppliers = list(self.suppliers.values())
        orders = list(self.orders.values())
        
        insights = {
            'risk_alerts': [],
            'recommendations': [],
            'performance_alerts': []
        }
        
        # Check for high-risk suppliers
        for supplier in suppliers:
            if supplier.get('status') == 'approved':
                risk_score = supplier.get('ai_risk_score', 0.5)
                if risk_score > 0.7:
                    insights['risk_alerts'].append({
                        'supplier_id': supplier['id'],
                        'company_name': supplier['company_name'],
                        'risk_score': risk_score,
                        'message': f"High risk supplier ({risk_score:.2f}) requires monitoring"
                    })
                
                # Check for declining ratings
                if supplier.get('total_reviews', 0) >= 5 and supplier.get('average_rating', 5) < 3.5:
                    insights['performance_alerts'].append({
                        'supplier_id': supplier['id'],
                        'company_name': supplier['company_name'],
                        'average_rating': supplier.get('average_rating'),
                        'message': f"Supplier rating declining ({supplier.get('average_rating'):.1f}/5.0)"
                    })
                
                # Check for high dispute rate
                if supplier.get('total_orders', 0) >= 10:
                    dispute_rate = supplier.get('dispute_count', 0) / supplier.get('total_orders', 1)
                    if dispute_rate > 0.1:
                        insights['risk_alerts'].append({
                            'supplier_id': supplier['id'],
                            'company_name': supplier['company_name'],
                            'dispute_rate': dispute_rate,
                            'message': f"High dispute rate ({dispute_rate:.1%})"
                        })
        
        # Identify underserved categories
        supplier_by_type = self._count_by_field(
            [s for s in suppliers if s.get('status') == 'approved'], 
            'supplier_type'
        )
        for stype, count in supplier_by_type.items():
            if count < 3:
                insights['recommendations'].append({
                    'category': stype,
                    'current_count': count,
                    'message': f"Consider recruiting more {stype.replace('_', ' ')} suppliers"
                })
        
        return insights


# Create singleton instance for import
_supplier_service_instance = None

def get_supplier_service(suppliers: Dict = None, offers: Dict = None, 
                         orders: Dict = None, documents: Dict = None) -> SupplierManagementService:
    """Get or create the supplier management service singleton."""
    global _supplier_service_instance
    if _supplier_service_instance is None:
        _supplier_service_instance = SupplierManagementService(
            suppliers_store=suppliers,
            offers_store=offers,
            orders_store=orders,
            documents_store=documents
        )
    return _supplier_service_instance
