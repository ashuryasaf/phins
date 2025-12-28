"""
PHINS Insurance Marketplace Service
====================================
Comprehensive services and products marketplace with:
- Location-based healthcare services
- Imported health products (medications, prosthetics, medical devices)
- NFT token integration for transaction integrity
- Full insurance pipeline integration
- External API connectivity

This is part of the world's most advanced AI-driven BI insurance system.
"""

import uuid
import hashlib
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import re


class ServiceCategory(Enum):
    """Service and product categories"""
    # Healthcare Services
    CONSULTATION = "consultation"
    TELEHEALTH = "telehealth"
    PHYSICAL_THERAPY = "physical_therapy"
    MENTAL_HEALTH = "mental_health"
    HOME_CARE = "home_care"
    EMERGENCY = "emergency"
    LABORATORY = "laboratory"
    IMAGING = "imaging"
    
    # Medical Products
    MEDICATION = "medication"
    PROSTHETICS = "prosthetics"
    MOBILITY_DEVICES = "mobility_devices"
    MONITORING_DEVICES = "monitoring_devices"
    DAILY_SUPPLIES = "daily_supplies"
    WOUND_CARE = "wound_care"
    RESPIRATORY = "respiratory"
    
    # Location Services
    TRANSPORTATION = "transportation"
    PHARMACY_DELIVERY = "pharmacy_delivery"
    NURSING_HOME = "nursing_home"
    REHABILITATION_CENTER = "rehabilitation_center"


class PaymentType(Enum):
    """Payment types for claims"""
    LUMP_SUM = "lump_sum"
    RISK_COVER = "risk_cover"
    SERVICE_PAYMENT = "service_payment"
    PRODUCT_PURCHASE = "product_purchase"
    RECURRING_BENEFIT = "recurring_benefit"


class TransactionStatus(Enum):
    """Transaction status"""
    PENDING = "pending"
    APPROVED = "approved"
    PROCESSING = "processing"
    COMPLETED = "completed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass
class NFTToken:
    """NFT Token for transaction integrity and provenance tracking"""
    token_id: str = ""
    chain_type: str = "PHINS-CHAIN"  # Internal blockchain-like ledger
    transaction_hash: str = ""
    owner_id: str = ""
    owner_type: str = "customer"  # customer, provider, insurance
    asset_type: str = ""  # service, product, claim, policy
    asset_id: str = ""
    metadata: Dict = field(default_factory=dict)
    created_at: str = ""
    transferred_at: Optional[str] = None
    previous_owners: List[str] = field(default_factory=list)
    smart_contract_ref: str = ""
    verification_hash: str = ""
    
    def __post_init__(self):
        if not self.token_id:
            self.token_id = f"NFT-{uuid.uuid4().hex[:12].upper()}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.transaction_hash:
            self.transaction_hash = self._generate_hash()
        if not self.verification_hash:
            self.verification_hash = self._generate_verification()
    
    def _generate_hash(self) -> str:
        """Generate transaction hash"""
        data = f"{self.token_id}{self.owner_id}{self.asset_id}{self.created_at}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def _generate_verification(self) -> str:
        """Generate verification hash for integrity"""
        data = json.dumps({
            'token_id': self.token_id,
            'owner_id': self.owner_id,
            'asset_type': self.asset_type,
            'asset_id': self.asset_id,
            'metadata': self.metadata
        }, sort_keys=True)
        return hashlib.sha3_256(data.encode()).hexdigest()
    
    def transfer(self, new_owner_id: str, new_owner_type: str = "customer") -> 'NFTToken':
        """Transfer token to new owner"""
        self.previous_owners.append(self.owner_id)
        self.owner_id = new_owner_id
        self.owner_type = new_owner_type
        self.transferred_at = datetime.now().isoformat()
        self.verification_hash = self._generate_verification()
        return self
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ServiceProvider:
    """Healthcare service provider"""
    provider_id: str
    name: str
    category: str
    specializations: List[str] = field(default_factory=list)
    location: Dict = field(default_factory=dict)  # lat, lng, address, city, country
    rating: float = 4.5
    reviews_count: int = 0
    insurance_accepted: List[str] = field(default_factory=list)
    operating_hours: Dict = field(default_factory=dict)
    certifications: List[str] = field(default_factory=list)
    contact: Dict = field(default_factory=dict)
    services_offered: List[str] = field(default_factory=list)
    pricing_tier: str = "standard"  # budget, standard, premium
    distance_km: float = 0.0
    availability: str = "available"
    nft_verified: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class HealthProduct:
    """Health product catalog item"""
    product_id: str
    name: str
    category: str
    subcategory: str = ""
    description: str = ""
    manufacturer: str = ""
    country_of_origin: str = ""
    price: float = 0.0
    currency: str = "USD"
    insurance_coverage_pct: float = 0.0  # Percentage covered by insurance
    requires_prescription: bool = False
    requires_approval: bool = False
    stock_status: str = "in_stock"
    delivery_days: int = 3
    specifications: Dict = field(default_factory=dict)
    certifications: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    nft_authenticity_token: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass 
class ServiceTransaction:
    """Transaction record for service/product purchase"""
    transaction_id: str
    customer_id: str
    policy_id: Optional[str] = None
    claim_id: Optional[str] = None
    transaction_type: str = "purchase"  # purchase, claim_payment, refund
    category: str = ""
    item_type: str = ""  # service or product
    item_id: str = ""
    item_name: str = ""
    provider_id: Optional[str] = None
    quantity: int = 1
    unit_price: float = 0.0
    total_amount: float = 0.0
    insurance_covered: float = 0.0
    wallet_deduction: float = 0.0
    out_of_pocket: float = 0.0
    payment_type: str = "wallet"
    status: str = "pending"
    nft_token_id: str = ""
    location: Dict = field(default_factory=dict)
    delivery_address: Optional[str] = None
    scheduled_date: Optional[str] = None
    completed_date: Optional[str] = None
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.transaction_id:
            self.transaction_id = f"TXN-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ExternalAPIConnector:
    """
    External API connector for location-based services and imported products.
    Simulates connections to real healthcare APIs.
    """
    
    def __init__(self):
        self.api_endpoints = {
            'location_services': 'https://api.healthservices.io/v2',
            'pharmacy_network': 'https://api.pharmacynetwork.com/v1',
            'medical_devices': 'https://api.meddevices.global/v3',
            'prosthetics': 'https://api.prosthetics-worldwide.com/v2',
            'laboratory': 'https://api.labservices.io/v1',
            'transportation': 'https://api.medtransport.io/v1',
            'telemedicine': 'https://api.telehealth.global/v2'
        }
        self.api_keys = {}  # Would store actual API keys
    
    def search_providers_by_location(
        self, 
        lat: float, 
        lng: float, 
        category: str,
        radius_km: float = 25.0,
        limit: int = 20
    ) -> List[ServiceProvider]:
        """
        Search healthcare providers by location.
        In production, this would call external APIs.
        """
        # Simulated providers with realistic data
        providers = self._get_simulated_providers(category, lat, lng, radius_km)
        return providers[:limit]
    
    def get_imported_products(
        self,
        category: str,
        subcategory: Optional[str] = None,
        country_filter: Optional[str] = None
    ) -> List[HealthProduct]:
        """
        Get imported health products from global suppliers.
        """
        products = self._get_simulated_products(category, subcategory)
        if country_filter:
            products = [p for p in products if p.country_of_origin == country_filter]
        return products
    
    def check_pharmacy_availability(
        self,
        medication_id: str,
        location: Dict
    ) -> Dict:
        """Check medication availability at nearby pharmacies"""
        return {
            'available': True,
            'pharmacies': [
                {'name': 'CVS Pharmacy', 'distance_km': 2.3, 'price': 45.99, 'in_stock': True},
                {'name': 'Walgreens', 'distance_km': 3.1, 'price': 47.50, 'in_stock': True},
                {'name': 'Local Pharmacy Plus', 'distance_km': 0.8, 'price': 42.00, 'in_stock': True}
            ],
            'delivery_available': True,
            'estimated_delivery': '2-4 hours'
        }
    
    def schedule_transportation(
        self,
        pickup_location: Dict,
        destination: Dict,
        patient_needs: Dict
    ) -> Dict:
        """Schedule medical transportation"""
        return {
            'booking_id': f"TRANS-{uuid.uuid4().hex[:8].upper()}",
            'status': 'confirmed',
            'vehicle_type': patient_needs.get('wheelchair_accessible', False) and 'wheelchair_van' or 'sedan',
            'driver_assigned': True,
            'estimated_pickup': (datetime.now() + timedelta(minutes=30)).isoformat(),
            'estimated_cost': 45.00,
            'insurance_covered': 35.00
        }
    
    def _get_simulated_providers(
        self, 
        category: str, 
        lat: float, 
        lng: float,
        radius_km: float
    ) -> List[ServiceProvider]:
        """Generate simulated providers for demo"""
        
        provider_templates = {
            'consultation': [
                ('Dr. Sarah Mitchell, MD', ['General Practice', 'Family Medicine'], 'premium'),
                ('Community Health Center', ['Primary Care', 'Preventive'], 'budget'),
                ('Metropolitan Medical Group', ['Internal Medicine', 'Geriatrics'], 'standard'),
                ('Dr. James Chen, MD', ['Cardiology', 'Internal Medicine'], 'premium'),
                ('Sunrise Family Clinic', ['Family Medicine', 'Pediatrics'], 'standard'),
            ],
            'physical_therapy': [
                ('PhysioWorks Rehabilitation', ['Sports Rehab', 'Post-Surgery'], 'premium'),
                ('Community PT Center', ['Mobility', 'Strength Training'], 'budget'),
                ('Advanced Movement Therapy', ['Neurological', 'Orthopedic'], 'standard'),
                ('Elite Sports Medicine', ['Athletic Injuries', 'Performance'], 'premium'),
            ],
            'mental_health': [
                ('Mindful Wellness Center', ['Anxiety', 'Depression', 'PTSD'], 'standard'),
                ('Dr. Emily Brooks, PsyD', ['Cognitive Therapy', 'Trauma'], 'premium'),
                ('Community Counseling Services', ['General Counseling', 'Group Therapy'], 'budget'),
            ],
            'laboratory': [
                ('LabCorp Diagnostics', ['Blood Tests', 'Genetic Testing'], 'standard'),
                ('Quest Diagnostics', ['Comprehensive Panels', 'Specialty Tests'], 'standard'),
                ('Local Clinical Laboratory', ['Basic Tests', 'Urgent Results'], 'budget'),
            ],
            'home_care': [
                ('Comfort Home Health', ['Personal Care', 'Nursing'], 'standard'),
                ('Elite Home Healthcare', ['Skilled Nursing', 'Therapy'], 'premium'),
                ('Community Care Aides', ['Basic Assistance', 'Companionship'], 'budget'),
            ],
            'pharmacy_delivery': [
                ('QuickMeds Delivery', ['Same-Day', 'Prescription'], 'standard'),
                ('MedExpress Pharmacy', ['Next-Day', 'Specialty Drugs'], 'standard'),
                ('24/7 Pharmacy Services', ['Emergency', 'After Hours'], 'premium'),
            ],
        }
        
        templates = provider_templates.get(category, provider_templates['consultation'])
        providers = []
        
        for i, (name, specs, tier) in enumerate(templates):
            distance = round(random.uniform(0.5, radius_km), 1)
            providers.append(ServiceProvider(
                provider_id=f"PROV-{category[:3].upper()}-{i+1:04d}",
                name=name,
                category=category,
                specializations=specs,
                location={
                    'lat': lat + random.uniform(-0.05, 0.05),
                    'lng': lng + random.uniform(-0.05, 0.05),
                    'address': f"{random.randint(100, 9999)} Healthcare Blvd",
                    'city': 'Metropolitan Area',
                    'country': 'US'
                },
                rating=round(random.uniform(3.8, 5.0), 1),
                reviews_count=random.randint(50, 500),
                insurance_accepted=['PHINS', 'BlueCross', 'Aetna', 'United'],
                operating_hours={
                    'monday': '8:00-18:00',
                    'tuesday': '8:00-18:00',
                    'wednesday': '8:00-18:00',
                    'thursday': '8:00-18:00',
                    'friday': '8:00-17:00',
                    'saturday': '9:00-13:00' if tier != 'budget' else 'closed',
                    'sunday': 'closed'
                },
                certifications=['State Licensed', 'HIPAA Compliant', 'PHINS Verified'],
                contact={
                    'phone': f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
                    'email': f"contact@{name.lower().replace(' ', '').replace(',', '').replace('.', '')[:15]}.com"
                },
                services_offered=specs,
                pricing_tier=tier,
                distance_km=distance,
                availability='available' if random.random() > 0.2 else 'limited',
                nft_verified=True
            ))
        
        return sorted(providers, key=lambda x: x.distance_km)
    
    def _get_simulated_products(
        self,
        category: str,
        subcategory: Optional[str] = None
    ) -> List[HealthProduct]:
        """Generate simulated products catalog"""
        
        product_catalog = {
            'prosthetics': [
                HealthProduct(
                    product_id='PROS-001',
                    name='Advanced Myoelectric Prosthetic Arm',
                    category='prosthetics',
                    subcategory='upper_limb',
                    description='State-of-the-art myoelectric prosthetic with multi-grip patterns and sensory feedback',
                    manufacturer='OttoBock',
                    country_of_origin='Germany',
                    price=45000.00,
                    insurance_coverage_pct=80.0,
                    requires_prescription=True,
                    requires_approval=True,
                    delivery_days=14,
                    specifications={
                        'grip_patterns': 24,
                        'battery_life_hours': 16,
                        'weight_kg': 0.45,
                        'material': 'Carbon Fiber'
                    },
                    certifications=['FDA Approved', 'CE Marked', 'ISO 13485'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='PROS-002',
                    name='Bionic Leg Prosthesis C-Leg 4',
                    category='prosthetics',
                    subcategory='lower_limb',
                    description='Microprocessor-controlled knee joint for above-knee amputees',
                    manufacturer='OttoBock',
                    country_of_origin='Germany',
                    price=70000.00,
                    insurance_coverage_pct=85.0,
                    requires_prescription=True,
                    requires_approval=True,
                    delivery_days=21,
                    specifications={
                        'gait_modes': 8,
                        'battery_life_hours': 48,
                        'max_weight_capacity_kg': 136
                    },
                    certifications=['FDA Approved', 'CE Marked'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='PROS-003',
                    name='Silicone Cosmetic Hand Prosthesis',
                    category='prosthetics',
                    subcategory='cosmetic',
                    description='Custom-made realistic silicone hand prosthesis',
                    manufacturer='Naked Prosthetics',
                    country_of_origin='USA',
                    price=8500.00,
                    insurance_coverage_pct=70.0,
                    requires_prescription=True,
                    requires_approval=False,
                    delivery_days=30,
                    specifications={
                        'custom_fit': True,
                        'skin_tone_matching': True,
                        'waterproof': True
                    },
                    certifications=['FDA Registered'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
            'medication': [
                HealthProduct(
                    product_id='MED-001',
                    name='Metformin 500mg (Generic)',
                    category='medication',
                    subcategory='diabetes',
                    description='Blood sugar control medication for Type 2 Diabetes',
                    manufacturer='Teva Pharmaceuticals',
                    country_of_origin='Israel',
                    price=15.00,
                    insurance_coverage_pct=90.0,
                    requires_prescription=True,
                    delivery_days=1,
                    specifications={'dosage': '500mg', 'quantity': 60, 'form': 'tablet'},
                    certifications=['FDA Approved'],
                    warnings=['Take with meals', 'Monitor kidney function'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='MED-002',
                    name='Insulin Glargine (Lantus)',
                    category='medication',
                    subcategory='diabetes',
                    description='Long-acting insulin for diabetes management',
                    manufacturer='Sanofi',
                    country_of_origin='France',
                    price=285.00,
                    insurance_coverage_pct=80.0,
                    requires_prescription=True,
                    requires_approval=False,
                    delivery_days=1,
                    specifications={'dosage': '100 units/mL', 'quantity': '10mL vial'},
                    certifications=['FDA Approved'],
                    warnings=['Refrigerate', 'Do not freeze'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='MED-003',
                    name='Lisinopril 10mg',
                    category='medication',
                    subcategory='cardiovascular',
                    description='ACE inhibitor for blood pressure control',
                    manufacturer='Lupin Pharmaceuticals',
                    country_of_origin='India',
                    price=12.00,
                    insurance_coverage_pct=95.0,
                    requires_prescription=True,
                    delivery_days=1,
                    specifications={'dosage': '10mg', 'quantity': 30, 'form': 'tablet'},
                    certifications=['FDA Approved'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
            'mobility_devices': [
                HealthProduct(
                    product_id='MOB-001',
                    name='Lightweight Power Wheelchair',
                    category='mobility_devices',
                    subcategory='wheelchairs',
                    description='Foldable electric wheelchair with joystick control',
                    manufacturer='Pride Mobility',
                    country_of_origin='USA',
                    price=3500.00,
                    insurance_coverage_pct=75.0,
                    requires_prescription=True,
                    requires_approval=True,
                    delivery_days=7,
                    specifications={
                        'weight_kg': 25,
                        'max_speed_mph': 5,
                        'range_miles': 15,
                        'foldable': True
                    },
                    certifications=['FDA Registered', 'Medicare Approved'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='MOB-002',
                    name='Rollator Walker with Seat',
                    category='mobility_devices',
                    subcategory='walkers',
                    description='Four-wheel rollator with padded seat and storage',
                    manufacturer='Drive Medical',
                    country_of_origin='USA',
                    price=150.00,
                    insurance_coverage_pct=80.0,
                    requires_prescription=False,
                    delivery_days=3,
                    specifications={
                        'weight_capacity_kg': 136,
                        'seat_height_inches': 20,
                        'foldable': True
                    },
                    certifications=['FDA Registered'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='MOB-003',
                    name='Stairlift System',
                    category='mobility_devices',
                    subcategory='home_modifications',
                    description='Indoor straight stairlift with safety sensors',
                    manufacturer='Stannah',
                    country_of_origin='UK',
                    price=4500.00,
                    insurance_coverage_pct=60.0,
                    requires_prescription=False,
                    requires_approval=True,
                    delivery_days=14,
                    specifications={
                        'max_weight_kg': 160,
                        'track_length_ft': 15,
                        'installation_included': True
                    },
                    certifications=['CE Marked', 'UL Listed'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
            'monitoring_devices': [
                HealthProduct(
                    product_id='MON-001',
                    name='Continuous Glucose Monitor System',
                    category='monitoring_devices',
                    subcategory='diabetes',
                    description='14-day CGM with smartphone connectivity',
                    manufacturer='Abbott',
                    country_of_origin='USA',
                    price=120.00,
                    insurance_coverage_pct=85.0,
                    requires_prescription=True,
                    delivery_days=2,
                    specifications={
                        'sensor_life_days': 14,
                        'bluetooth': True,
                        'app_compatible': True
                    },
                    certifications=['FDA Approved'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='MON-002',
                    name='Smart Blood Pressure Monitor',
                    category='monitoring_devices',
                    subcategory='cardiovascular',
                    description='Wireless BP monitor with irregular heartbeat detection',
                    manufacturer='Omron',
                    country_of_origin='Japan',
                    price=89.99,
                    insurance_coverage_pct=70.0,
                    requires_prescription=False,
                    delivery_days=2,
                    specifications={
                        'bluetooth': True,
                        'memory_readings': 200,
                        'cuff_sizes': ['S', 'M', 'L']
                    },
                    certifications=['FDA Cleared'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='MON-003',
                    name='Pulse Oximeter Pro',
                    category='monitoring_devices',
                    subcategory='respiratory',
                    description='Medical-grade fingertip pulse oximeter',
                    manufacturer='Masimo',
                    country_of_origin='USA',
                    price=299.00,
                    insurance_coverage_pct=75.0,
                    requires_prescription=False,
                    delivery_days=2,
                    specifications={
                        'accuracy': '±2%',
                        'display': 'OLED',
                        'battery_life_hours': 40
                    },
                    certifications=['FDA 510(k) Cleared'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
            'daily_supplies': [
                HealthProduct(
                    product_id='SUP-001',
                    name='Premium Adult Diapers (Case of 80)',
                    category='daily_supplies',
                    subcategory='incontinence',
                    description='Maximum absorbency briefs with odor protection',
                    manufacturer='TENA',
                    country_of_origin='Sweden',
                    price=65.00,
                    insurance_coverage_pct=60.0,
                    requires_prescription=False,
                    delivery_days=2,
                    specifications={'quantity': 80, 'sizes': ['M', 'L', 'XL'], 'absorbency': 'Maximum'},
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='SUP-002',
                    name='Disposable Bed Pads (100 count)',
                    category='daily_supplies',
                    subcategory='incontinence',
                    description='High-absorbency underpads for bed protection',
                    manufacturer='McKesson',
                    country_of_origin='USA',
                    price=45.00,
                    insurance_coverage_pct=50.0,
                    requires_prescription=False,
                    delivery_days=2,
                    specifications={'quantity': 100, 'size': '23x36 inches'},
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
            'wound_care': [
                HealthProduct(
                    product_id='WND-001',
                    name='Advanced Wound Dressing Kit',
                    category='wound_care',
                    subcategory='dressings',
                    description='Complete wound care kit with silver dressings',
                    manufacturer='Smith & Nephew',
                    country_of_origin='UK',
                    price=125.00,
                    insurance_coverage_pct=75.0,
                    requires_prescription=False,
                    delivery_days=2,
                    specifications={'components': 50, 'types': ['foam', 'hydrocolloid', 'silver']},
                    certifications=['FDA Cleared'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
            'respiratory': [
                HealthProduct(
                    product_id='RESP-001',
                    name='Portable Oxygen Concentrator',
                    category='respiratory',
                    subcategory='oxygen_therapy',
                    description='Lightweight portable oxygen concentrator',
                    manufacturer='Inogen',
                    country_of_origin='USA',
                    price=2500.00,
                    insurance_coverage_pct=80.0,
                    requires_prescription=True,
                    requires_approval=True,
                    delivery_days=5,
                    specifications={
                        'weight_kg': 2.2,
                        'battery_life_hours': 8,
                        'flow_settings': 5,
                        'faa_approved': True
                    },
                    certifications=['FDA Cleared', 'FAA Approved'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
                HealthProduct(
                    product_id='RESP-002',
                    name='CPAP Machine with Heated Humidifier',
                    category='respiratory',
                    subcategory='sleep_apnea',
                    description='Auto-adjusting CPAP with integrated humidifier',
                    manufacturer='ResMed',
                    country_of_origin='Australia',
                    price=850.00,
                    insurance_coverage_pct=80.0,
                    requires_prescription=True,
                    delivery_days=3,
                    specifications={
                        'auto_adjusting': True,
                        'humidifier': True,
                        'app_tracking': True
                    },
                    certifications=['FDA Cleared'],
                    nft_authenticity_token=f"NFT-AUTH-{uuid.uuid4().hex[:8].upper()}"
                ),
            ],
        }
        
        products = product_catalog.get(category, [])
        if subcategory:
            products = [p for p in products if p.subcategory == subcategory]
        return products


class MarketplaceService:
    """
    Main marketplace service for managing services, products, and transactions.
    Integrates with the insurance pipeline for claims and payments.
    """
    
    def __init__(self):
        self.external_api = ExternalAPIConnector()
        self.transactions: Dict[str, ServiceTransaction] = {}
        self.nft_registry: Dict[str, NFTToken] = {}
        self.wallet_balances: Dict[str, float] = {}  # customer_id -> balance
        self.pending_approvals: Dict[str, Dict] = {}
    
    # ==================== Wallet Management ====================
    
    def get_wallet_balance(self, customer_id: str) -> float:
        """Get customer's health wallet balance"""
        return self.wallet_balances.get(customer_id, 0.0)
    
    def add_funds_to_wallet(
        self,
        customer_id: str,
        amount: float,
        source: str = "card_payment",
        policy_id: Optional[str] = None
    ) -> Dict:
        """Add funds to customer's health wallet"""
        if amount <= 0:
            return {'success': False, 'error': 'Invalid amount'}
        
        current = self.wallet_balances.get(customer_id, 0.0)
        self.wallet_balances[customer_id] = current + amount
        
        # Create NFT for the transaction
        nft = NFTToken(
            owner_id=customer_id,
            asset_type='wallet_deposit',
            asset_id=f"DEP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            metadata={
                'amount': amount,
                'source': source,
                'policy_id': policy_id,
                'previous_balance': current,
                'new_balance': current + amount
            }
        )
        self.nft_registry[nft.token_id] = nft
        
        return {
            'success': True,
            'new_balance': self.wallet_balances[customer_id],
            'deposit_amount': amount,
            'nft_token': nft.to_dict()
        }
    
    def credit_wallet_from_claim(
        self,
        customer_id: str,
        claim_id: str,
        amount: float,
        payment_type: PaymentType
    ) -> Dict:
        """Credit wallet from approved insurance claim"""
        result = self.add_funds_to_wallet(
            customer_id,
            amount,
            source=f"claim_payment_{payment_type.value}",
            policy_id=None
        )
        
        if result['success']:
            result['claim_id'] = claim_id
            result['payment_type'] = payment_type.value
        
        return result
    
    # ==================== Provider Search ====================
    
    def search_providers(
        self,
        category: str,
        latitude: float,
        longitude: float,
        radius_km: float = 25.0,
        limit: int = 20
    ) -> List[Dict]:
        """Search for healthcare providers by location"""
        providers = self.external_api.search_providers_by_location(
            lat=latitude,
            lng=longitude,
            category=category,
            radius_km=radius_km,
            limit=limit
        )
        return [p.to_dict() for p in providers]
    
    # ==================== Product Catalog ====================
    
    def get_products(
        self,
        category: str,
        subcategory: Optional[str] = None,
        country_of_origin: Optional[str] = None
    ) -> List[Dict]:
        """Get products from catalog"""
        products = self.external_api.get_imported_products(
            category=category,
            subcategory=subcategory,
            country_filter=country_of_origin
        )
        return [p.to_dict() for p in products]
    
    def get_all_categories(self) -> Dict:
        """Get all available categories"""
        return {
            'services': [
                {'id': 'consultation', 'name': '🩺 Medical Consultations', 'icon': '🩺'},
                {'id': 'telehealth', 'name': '📱 Telehealth Services', 'icon': '📱'},
                {'id': 'physical_therapy', 'name': '🏃 Physical Therapy', 'icon': '🏃'},
                {'id': 'mental_health', 'name': '🧠 Mental Health', 'icon': '🧠'},
                {'id': 'home_care', 'name': '🏠 Home Care Services', 'icon': '🏠'},
                {'id': 'laboratory', 'name': '🔬 Laboratory Tests', 'icon': '🔬'},
                {'id': 'imaging', 'name': '📷 Medical Imaging', 'icon': '📷'},
                {'id': 'transportation', 'name': '🚗 Medical Transportation', 'icon': '🚗'},
            ],
            'products': [
                {'id': 'medication', 'name': '💊 Medications', 'icon': '💊'},
                {'id': 'prosthetics', 'name': '🦿 Prosthetics', 'icon': '🦿'},
                {'id': 'mobility_devices', 'name': '🦽 Mobility Devices', 'icon': '🦽'},
                {'id': 'monitoring_devices', 'name': '📟 Monitoring Devices', 'icon': '📟'},
                {'id': 'daily_supplies', 'name': '🧴 Daily Care Supplies', 'icon': '🧴'},
                {'id': 'wound_care', 'name': '🩹 Wound Care', 'icon': '🩹'},
                {'id': 'respiratory', 'name': '💨 Respiratory Equipment', 'icon': '💨'},
            ]
        }
    
    # ==================== Purchases & Transactions ====================
    
    def purchase_service(
        self,
        customer_id: str,
        provider_id: str,
        service_type: str,
        service_details: Dict,
        policy_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        scheduled_date: Optional[str] = None,
        location: Optional[Dict] = None
    ) -> Dict:
        """Purchase a healthcare service"""
        
        price = service_details.get('price', 0)
        insurance_coverage_pct = service_details.get('insurance_coverage_pct', 0)
        
        insurance_covered = price * (insurance_coverage_pct / 100)
        wallet_balance = self.get_wallet_balance(customer_id)
        
        # Calculate payment breakdown
        remaining = price - insurance_covered
        wallet_deduction = min(remaining, wallet_balance)
        out_of_pocket = remaining - wallet_deduction
        
        # Create transaction
        transaction = ServiceTransaction(
            transaction_id="",  # Will be auto-generated
            customer_id=customer_id,
            policy_id=policy_id,
            claim_id=claim_id,
            transaction_type='service_purchase',
            category=service_type,
            item_type='service',
            item_id=service_details.get('id', ''),
            item_name=service_details.get('name', ''),
            provider_id=provider_id,
            unit_price=price,
            total_amount=price,
            insurance_covered=insurance_covered,
            wallet_deduction=wallet_deduction,
            out_of_pocket=out_of_pocket,
            payment_type='mixed' if insurance_covered > 0 else 'wallet',
            status='pending',
            location=location or {},
            scheduled_date=scheduled_date
        )
        
        # Deduct from wallet
        if wallet_deduction > 0:
            self.wallet_balances[customer_id] = wallet_balance - wallet_deduction
        
        # Create NFT token for the transaction
        nft = NFTToken(
            owner_id=customer_id,
            asset_type='service_purchase',
            asset_id=transaction.transaction_id,
            metadata={
                'service_type': service_type,
                'provider_id': provider_id,
                'amount': price,
                'insurance_covered': insurance_covered,
                'policy_id': policy_id,
                'claim_id': claim_id
            }
        )
        
        transaction.nft_token_id = nft.token_id
        self.nft_registry[nft.token_id] = nft
        self.transactions[transaction.transaction_id] = transaction
        
        # If requires approval, add to pending
        if service_details.get('requires_approval'):
            transaction.status = 'pending_approval'
            self.pending_approvals[transaction.transaction_id] = {
                'transaction': transaction.to_dict(),
                'nft': nft.to_dict(),
                'approval_type': 'service'
            }
        else:
            transaction.status = 'approved'
        
        return {
            'success': True,
            'transaction': transaction.to_dict(),
            'nft_token': nft.to_dict(),
            'payment_breakdown': {
                'total': price,
                'insurance_covered': insurance_covered,
                'wallet_deduction': wallet_deduction,
                'out_of_pocket': out_of_pocket,
                'new_wallet_balance': self.get_wallet_balance(customer_id)
            }
        }
    
    def purchase_product(
        self,
        customer_id: str,
        product_id: str,
        product_details: Dict,
        quantity: int = 1,
        policy_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        delivery_address: Optional[str] = None
    ) -> Dict:
        """Purchase a health product"""
        
        unit_price = product_details.get('price', 0)
        total_price = unit_price * quantity
        insurance_coverage_pct = product_details.get('insurance_coverage_pct', 0)
        
        insurance_covered = total_price * (insurance_coverage_pct / 100)
        wallet_balance = self.get_wallet_balance(customer_id)
        
        remaining = total_price - insurance_covered
        wallet_deduction = min(remaining, wallet_balance)
        out_of_pocket = remaining - wallet_deduction
        
        transaction = ServiceTransaction(
            transaction_id="",
            customer_id=customer_id,
            policy_id=policy_id,
            claim_id=claim_id,
            transaction_type='product_purchase',
            category=product_details.get('category', ''),
            item_type='product',
            item_id=product_id,
            item_name=product_details.get('name', ''),
            quantity=quantity,
            unit_price=unit_price,
            total_amount=total_price,
            insurance_covered=insurance_covered,
            wallet_deduction=wallet_deduction,
            out_of_pocket=out_of_pocket,
            payment_type='mixed' if insurance_covered > 0 else 'wallet',
            status='pending',
            delivery_address=delivery_address
        )
        
        if wallet_deduction > 0:
            self.wallet_balances[customer_id] = wallet_balance - wallet_deduction
        
        nft = NFTToken(
            owner_id=customer_id,
            asset_type='product_purchase',
            asset_id=transaction.transaction_id,
            metadata={
                'product_id': product_id,
                'product_name': product_details.get('name'),
                'quantity': quantity,
                'amount': total_price,
                'insurance_covered': insurance_covered,
                'manufacturer': product_details.get('manufacturer'),
                'country_of_origin': product_details.get('country_of_origin'),
                'authenticity_token': product_details.get('nft_authenticity_token')
            }
        )
        
        transaction.nft_token_id = nft.token_id
        self.nft_registry[nft.token_id] = nft
        self.transactions[transaction.transaction_id] = transaction
        
        if product_details.get('requires_approval') or product_details.get('requires_prescription'):
            transaction.status = 'pending_approval'
            self.pending_approvals[transaction.transaction_id] = {
                'transaction': transaction.to_dict(),
                'nft': nft.to_dict(),
                'approval_type': 'product',
                'requires_prescription': product_details.get('requires_prescription', False)
            }
        else:
            transaction.status = 'processing'
        
        return {
            'success': True,
            'transaction': transaction.to_dict(),
            'nft_token': nft.to_dict(),
            'payment_breakdown': {
                'total': total_price,
                'insurance_covered': insurance_covered,
                'wallet_deduction': wallet_deduction,
                'out_of_pocket': out_of_pocket,
                'new_wallet_balance': self.get_wallet_balance(customer_id)
            },
            'estimated_delivery_days': product_details.get('delivery_days', 3)
        }
    
    # ==================== Transaction Management ====================
    
    def get_customer_transactions(
        self,
        customer_id: str,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get customer's transactions"""
        transactions = [
            t for t in self.transactions.values()
            if t.customer_id == customer_id
        ]
        
        if status:
            transactions = [t for t in transactions if t.status == status]
        if category:
            transactions = [t for t in transactions if t.category == category]
        
        transactions.sort(key=lambda x: x.created_at, reverse=True)
        return [t.to_dict() for t in transactions[:limit]]
    
    def get_all_transactions(
        self,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get all transactions (admin view)"""
        transactions = list(self.transactions.values())
        if status:
            transactions = [t for t in transactions if t.status == status]
        transactions.sort(key=lambda x: x.created_at, reverse=True)
        return [t.to_dict() for t in transactions[:limit]]
    
    def update_transaction_status(
        self,
        transaction_id: str,
        new_status: str,
        notes: Optional[str] = None
    ) -> Dict:
        """Update transaction status"""
        if transaction_id not in self.transactions:
            return {'success': False, 'error': 'Transaction not found'}
        
        transaction = self.transactions[transaction_id]
        transaction.status = new_status
        transaction.updated_at = datetime.now().isoformat()
        if notes:
            transaction.notes = notes
        
        if new_status == 'completed' and not transaction.completed_date:
            transaction.completed_date = datetime.now().isoformat()
        
        return {
            'success': True,
            'transaction': transaction.to_dict()
        }
    
    # ==================== Approval Workflow ====================
    
    def get_pending_approvals(self) -> List[Dict]:
        """Get all pending approvals (admin view)"""
        return list(self.pending_approvals.values())
    
    def approve_transaction(
        self,
        transaction_id: str,
        approver_id: str,
        approval_notes: Optional[str] = None
    ) -> Dict:
        """Approve a pending transaction"""
        if transaction_id not in self.pending_approvals:
            return {'success': False, 'error': 'No pending approval found'}
        
        approval = self.pending_approvals.pop(transaction_id)
        result = self.update_transaction_status(
            transaction_id,
            'approved',
            f"Approved by {approver_id}. {approval_notes or ''}"
        )
        
        if result['success']:
            # Update NFT with approval
            nft_id = self.transactions[transaction_id].nft_token_id
            if nft_id in self.nft_registry:
                self.nft_registry[nft_id].metadata['approved_by'] = approver_id
                self.nft_registry[nft_id].metadata['approval_date'] = datetime.now().isoformat()
        
        return result
    
    def reject_transaction(
        self,
        transaction_id: str,
        rejector_id: str,
        rejection_reason: str
    ) -> Dict:
        """Reject a pending transaction"""
        if transaction_id in self.pending_approvals:
            self.pending_approvals.pop(transaction_id)
        
        if transaction_id in self.transactions:
            transaction = self.transactions[transaction_id]
            
            # Refund wallet if applicable
            if transaction.wallet_deduction > 0:
                current = self.wallet_balances.get(transaction.customer_id, 0)
                self.wallet_balances[transaction.customer_id] = current + transaction.wallet_deduction
        
        return self.update_transaction_status(
            transaction_id,
            'rejected',
            f"Rejected by {rejector_id}: {rejection_reason}"
        )
    
    # ==================== NFT Operations ====================
    
    def get_nft_token(self, token_id: str) -> Optional[Dict]:
        """Get NFT token details"""
        nft = self.nft_registry.get(token_id)
        return nft.to_dict() if nft else None
    
    def verify_nft_authenticity(self, token_id: str) -> Dict:
        """Verify NFT token authenticity"""
        nft = self.nft_registry.get(token_id)
        if not nft:
            return {'valid': False, 'error': 'Token not found'}
        
        # Regenerate verification hash and compare
        expected_hash = nft._generate_verification()
        is_valid = expected_hash == nft.verification_hash
        
        return {
            'valid': is_valid,
            'token_id': token_id,
            'owner_id': nft.owner_id,
            'asset_type': nft.asset_type,
            'created_at': nft.created_at,
            'chain_type': nft.chain_type,
            'verification_hash': nft.verification_hash
        }
    
    def get_customer_nfts(self, customer_id: str) -> List[Dict]:
        """Get all NFTs owned by a customer"""
        nfts = [
            nft.to_dict() for nft in self.nft_registry.values()
            if nft.owner_id == customer_id
        ]
        return nfts
    
    # ==================== Insurance Pipeline Integration ====================
    
    def process_claim_payment(
        self,
        claim_id: str,
        customer_id: str,
        policy_id: str,
        approved_amount: float,
        payment_type: PaymentType,
        payment_destination: str = "wallet"  # wallet, direct_deposit, service_provider, product_vendor
    ) -> Dict:
        """
        Process payment for an approved claim.
        Integrates with the insurance pipeline.
        """
        
        if payment_destination == "wallet":
            # Credit to health wallet
            result = self.credit_wallet_from_claim(
                customer_id=customer_id,
                claim_id=claim_id,
                amount=approved_amount,
                payment_type=payment_type
            )
        else:
            # Create payment transaction
            transaction = ServiceTransaction(
                transaction_id="",
                customer_id=customer_id,
                policy_id=policy_id,
                claim_id=claim_id,
                transaction_type='claim_payment',
                category=payment_type.value,
                item_type='claim_disbursement',
                item_name=f"Claim Payment - {payment_type.value}",
                total_amount=approved_amount,
                insurance_covered=approved_amount,
                payment_type=payment_destination,
                status='processing'
            )
            
            nft = NFTToken(
                owner_id=customer_id,
                asset_type='claim_payment',
                asset_id=transaction.transaction_id,
                metadata={
                    'claim_id': claim_id,
                    'policy_id': policy_id,
                    'amount': approved_amount,
                    'payment_type': payment_type.value,
                    'destination': payment_destination
                }
            )
            
            transaction.nft_token_id = nft.token_id
            self.nft_registry[nft.token_id] = nft
            self.transactions[transaction.transaction_id] = transaction
            
            result = {
                'success': True,
                'transaction': transaction.to_dict(),
                'nft_token': nft.to_dict(),
                'payment_type': payment_type.value,
                'amount': approved_amount
            }
        
        return result
    
    def link_purchase_to_claim(
        self,
        transaction_id: str,
        claim_id: str
    ) -> Dict:
        """Link a service/product purchase to an insurance claim"""
        if transaction_id not in self.transactions:
            return {'success': False, 'error': 'Transaction not found'}
        
        transaction = self.transactions[transaction_id]
        transaction.claim_id = claim_id
        
        # Update NFT metadata
        nft_id = transaction.nft_token_id
        if nft_id in self.nft_registry:
            self.nft_registry[nft_id].metadata['claim_id'] = claim_id
            self.nft_registry[nft_id].metadata['linked_at'] = datetime.now().isoformat()
        
        return {
            'success': True,
            'transaction': transaction.to_dict()
        }
    
    # ==================== Statistics & Reports ====================
    
    def get_marketplace_stats(self) -> Dict:
        """Get marketplace statistics for BI dashboard"""
        all_transactions = list(self.transactions.values())
        
        total_volume = sum(t.total_amount for t in all_transactions)
        insurance_covered = sum(t.insurance_covered for t in all_transactions)
        wallet_volume = sum(t.wallet_deduction for t in all_transactions)
        
        by_category = {}
        for t in all_transactions:
            cat = t.category or 'other'
            if cat not in by_category:
                by_category[cat] = {'count': 0, 'volume': 0}
            by_category[cat]['count'] += 1
            by_category[cat]['volume'] += t.total_amount
        
        by_status = {}
        for t in all_transactions:
            status = t.status
            by_status[status] = by_status.get(status, 0) + 1
        
        return {
            'total_transactions': len(all_transactions),
            'total_volume': total_volume,
            'insurance_covered_total': insurance_covered,
            'wallet_volume': wallet_volume,
            'pending_approvals': len(self.pending_approvals),
            'total_nfts_issued': len(self.nft_registry),
            'active_wallets': len(self.wallet_balances),
            'total_wallet_balances': sum(self.wallet_balances.values()),
            'by_category': by_category,
            'by_status': by_status
        }


# Global instance
marketplace_service = MarketplaceService()


def get_marketplace_service() -> MarketplaceService:
    """Get the marketplace service instance"""
    return marketplace_service
