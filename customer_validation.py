"""
PHINS Customer Validation Module
Comprehensive customer and family member validation for underwriting
Supports health assessment, personal information, and family member management
Zero external dependencies - Pure Python stdlib
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, date
import re
from abc import ABC, abstractmethod


# ============================================================================
# ENUMS - Customer Validation Types
# ============================================================================

class Gender(Enum):
    """Gender classification"""
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    PREFER_NOT_TO_SAY = "Prefer Not to Say"


class SmokingStatus(Enum):
    """Smoking status"""
    SMOKER = "Smoker"
    NON_SMOKER = "Non-Smoker"
    FORMER_SMOKER = "Former Smoker"
    OCCASIONAL = "Occasional"


class PersonalStatus(Enum):
    """Personal/Marital status"""
    SINGLE = "Single"
    MARRIED = "Married"
    DIVORCED = "Divorced"
    WIDOWED = "Widowed"
    DOMESTIC_PARTNERSHIP = "Domestic Partnership"
    SEPARATED = "Separated"


class DocumentType(Enum):
    """ID document types"""
    PASSPORT = "Passport"
    NATIONAL_ID = "National ID"
    DRIVER_LICENSE = "Driver License"
    VISA = "Visa"
    TRAVEL_DOCUMENT = "Travel Document"
    OTHER = "Other"


class FamilyRelationship(Enum):
    """Relationship types for family members"""
    SPOUSE = "Spouse"
    CHILD = "Child"
    PARENT = "Parent"
    SIBLING = "Sibling"
    GRANDPARENT = "Grandparent"
    GRANDCHILD = "Grandchild"
    GUARDIAN = "Guardian"
    DEPENDENT = "Dependent"
    OTHER = "Other"


class HealthConditionLevel(Enum):
    """Health condition severity ranking (1-10 scale)"""
    EXCELLENT = 1
    VERY_GOOD = 2
    GOOD = 3
    GOOD_WITH_MINOR_ISSUES = 4
    FAIR = 5
    FAIR_WITH_MODERATE_ISSUES = 6
    POOR = 7
    POOR_WITH_SIGNIFICANT_ISSUES = 8
    VERY_POOR = 9
    CRITICAL = 10


# ============================================================================
# VALIDATION RULES
# ============================================================================

class ValidationRules:
    """Validation rules for customer data"""
    
    # Name validation
    MIN_NAME_LENGTH = 2
    MAX_NAME_LENGTH = 100
    NAME_PATTERN = r"^[a-zA-Z\s\-']{2,100}$"  # Letters, spaces, hyphens, apostrophes
    
    # Phone validation
    # Allow international phone formats with optional leading + and common
    # separators. Increase maximum to support longer international numbers
    # (e.g. +972-5050505, +1 (555) 012-3456, or longer extensions).
    PHONE_PATTERN = r"^\+?[\d\s\-\(\)\.]{7,30}$"
    # Minimum digits (without separators) and maximum digits allowed
    MIN_PHONE_LENGTH = 7
    MAX_PHONE_LENGTH = 30
    
    # Email validation
    EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    
    # Address validation
    MIN_ADDRESS_LENGTH = 5
    MAX_ADDRESS_LENGTH = 255
    
    # Passport/ID validation
    MIN_ID_LENGTH = 6
    MAX_ID_LENGTH = 50
    
    # Age requirements
    MIN_AGE_YEARS = 18
    MAX_AGE_YEARS = 120
    
    # Health condition range
    MIN_HEALTH_CONDITION = 1
    MAX_HEALTH_CONDITION = 10


class Validator:
    """Core validation utility class"""
    
    @staticmethod
    def is_valid_name(name: str) -> bool:
        """Validate name format"""
        if not name or len(name) < ValidationRules.MIN_NAME_LENGTH:
            return False
        if len(name) > ValidationRules.MAX_NAME_LENGTH:
            return False
        return re.match(ValidationRules.NAME_PATTERN, name) is not None
    
    @staticmethod
    def is_valid_email(email: str) -> bool:
        """Validate email format"""
        if not email or len(email) > 255:
            return False
        return re.match(ValidationRules.EMAIL_PATTERN, email) is not None
    
    @staticmethod
    def is_valid_phone(phone: str) -> bool:
        """Validate phone format"""
        if not phone:
            return False
        # Remove common formatting characters
        cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace("+", "")
        if len(cleaned) < ValidationRules.MIN_PHONE_LENGTH:
            return False
        if len(cleaned) > ValidationRules.MAX_PHONE_LENGTH:
            return False
        return re.match(ValidationRules.PHONE_PATTERN, phone) is not None
    
    @staticmethod
    def is_valid_address(address: str) -> bool:
        """Validate address format"""
        if not address:
            return False
        if len(address) < ValidationRules.MIN_ADDRESS_LENGTH:
            return False
        if len(address) > ValidationRules.MAX_ADDRESS_LENGTH:
            return False
        return True
    
    @staticmethod
    def is_valid_document_id(doc_id: str) -> bool:
        """Validate passport/ID format"""
        if not doc_id:
            return False
        doc_id = doc_id.strip()
        if len(doc_id) < ValidationRules.MIN_ID_LENGTH:
            return False
        if len(doc_id) > ValidationRules.MAX_ID_LENGTH:
            return False
        return doc_id.replace(" ", "").replace("-", "").isalnum()
    
    @staticmethod
    def is_valid_birthdate(birthdate: date, min_age: int = ValidationRules.MIN_AGE_YEARS) -> tuple[bool, str]:
        """Validate birthdate and calculate age"""
        if not birthdate:
            return False, "Birthdate is required"
        
        if not isinstance(birthdate, date):
            return False, "Birthdate must be a date object"
        
        today = date.today()
        if birthdate > today:
            return False, "Birthdate cannot be in the future"
        
        # Calculate age
        age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        
        if age < min_age:
            return False, f"Minimum age required: {min_age} years (current age: {age} years)"
        
        if age > ValidationRules.MAX_AGE_YEARS:
            return False, f"Invalid age: {age} years"
        
        return True, f"Valid age: {age} years"
    
    @staticmethod
    def is_valid_health_condition(level: int) -> bool:
        """Validate health condition level"""
        return ValidationRules.MIN_HEALTH_CONDITION <= level <= ValidationRules.MAX_HEALTH_CONDITION
    
    @staticmethod
    def validate_all_required_fields(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate all required customer fields"""
        errors = []
        
        required_fields = [
            "first_name", "last_name", "gender", "birthdate",
            "document_type", "document_id", "smoking_status",
            "personal_status", "address", "phone", "email", "health_condition"
        ]
        
        for field in required_fields:
            if field not in data or data[field] is None:
                errors.append(f"Missing required field: {field}")
        
        return len(errors) == 0, errors


# ============================================================================
# DATA CLASSES - Customer Information
# ============================================================================

@dataclass
class IdentificationDocument:
    """Customer identification document"""
    document_type: DocumentType
    document_id: str
    issue_date: date
    expiry_date: Optional[date] = None
    issuing_country: str = "USA"
    
    def __post_init__(self):
        """Validate document on creation"""
        if not Validator.is_valid_document_id(self.document_id):
            raise ValueError(f"Invalid document ID format: {self.document_id}")
        
        if self.expiry_date and self.expiry_date < date.today():
            raise ValueError(f"Document expired on {self.expiry_date}")
    
    def is_valid(self) -> bool:
        """Check if document is currently valid"""
        if self.expiry_date and self.expiry_date < date.today():
            return False
        return True
    
    def days_to_expiry(self) -> Optional[int]:
        """Days until document expiry"""
        if not self.expiry_date:
            return None
        delta = self.expiry_date - date.today()
        return delta.days


@dataclass
class HealthAssessment:
    """Health condition assessment for underwriting"""
    condition_level: int  # 1-10 scale
    assessment_date: datetime
    notes: str = ""
    medical_conditions: List[str] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    current_medications: List[str] = field(default_factory=list)
    last_medical_checkup: Optional[date] = None
    
    def __post_init__(self):
        """Validate health assessment"""
        if not Validator.is_valid_health_condition(self.condition_level):
            raise ValueError(f"Health condition must be 1-10, got {self.condition_level}")
    
    def get_condition_description(self) -> str:
        """Get human-readable health condition description"""
        level_map = {
            1: "Excellent",
            2: "Very Good",
            3: "Good",
            4: "Good with Minor Issues",
            5: "Fair",
            6: "Fair with Moderate Issues",
            7: "Poor",
            8: "Poor with Significant Issues",
            9: "Very Poor",
            10: "Critical"
        }
        return level_map.get(self.condition_level, "Unknown")
    
    def requires_medical_review(self) -> bool:
        """Determine if medical review is required"""
        # Medical review needed for conditions >= 6 or with serious conditions
        return self.condition_level >= 6 or len(self.medical_conditions) > 0
    
    def health_risk_score(self) -> float:
        """Calculate health risk score (0-1.0)"""
        # Base score from condition level
        base_score = (self.condition_level - 1) / 9.0
        
        # Increase score for medical conditions
        if self.medical_conditions:
            base_score += 0.1
        
        return min(base_score, 1.0)


@dataclass
class Customer:
    """Core customer information for underwriting"""
    
    # Personal Information
    first_name: str
    last_name: str
    gender: Gender
    birthdate: date
    
    # Identification
    identification: IdentificationDocument
    
    # Lifestyle
    smoking_status: SmokingStatus
    personal_status: PersonalStatus
    
    # Contact Information
    address: str
    city: str
    state_province: str
    postal_code: str
    
    # Health Assessment
    health_assessment: HealthAssessment
    
    # Optional fields with defaults
    country: str = "USA"
    phone: str = ""
    email: str = ""
    customer_id: Optional[str] = None
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)
    notes: str = ""
    
    def __post_init__(self):
        """Validate customer data"""
        if not Validator.is_valid_name(self.first_name):
            raise ValueError(f"Invalid first name: {self.first_name}")
        
        if not Validator.is_valid_name(self.last_name):
            raise ValueError(f"Invalid last name: {self.last_name}")
        
        is_valid_date, msg = Validator.is_valid_birthdate(self.birthdate)
        if not is_valid_date:
            raise ValueError(f"Invalid birthdate: {msg}")
        
        if self.phone and not Validator.is_valid_phone(self.phone):
            raise ValueError(f"Invalid phone format: {self.phone}")
        
        if self.email and not Validator.is_valid_email(self.email):
            raise ValueError(f"Invalid email format: {self.email}")
        
        if not Validator.is_valid_address(self.address):
            raise ValueError(f"Invalid address: {self.address}")
    
    @property
    def full_name(self) -> str:
        """Get full customer name"""
        return f"{self.first_name} {self.last_name}"
    
    @property
    def age(self) -> int:
        """Calculate customer age"""
        today = date.today()
        return today.year - self.birthdate.year - ((today.month, today.day) < (self.birthdate.month, self.birthdate.day))
    
    def get_summary(self) -> Dict[str, Any]:
        """Get customer summary for quick review"""
        return {
            "customer_id": self.customer_id,
            "full_name": self.full_name,
            "age": self.age,
            "gender": self.gender.value,
            "smoking_status": self.smoking_status.value,
            "personal_status": self.personal_status.value,
            "health_condition": self.health_assessment.condition_level,
            "health_description": self.health_assessment.get_condition_description(),
            "document_id": self.identification.document_id,
            "document_valid": self.identification.is_valid(),
            "contact": {
                "email": self.email,
                "phone": self.phone,
                "address": f"{self.address}, {self.city}, {self.state_province} {self.postal_code}"
            },
            "requires_medical_review": self.health_assessment.requires_medical_review(),
            "health_risk_score": self.health_assessment.health_risk_score()
        }


@dataclass
class FamilyMember:
    """Family member information for multi-generational policies"""
    
    # Same core information as Customer
    first_name: str
    last_name: str
    gender: Gender
    birthdate: date
    relationship: FamilyRelationship
    
    # Identification
    identification: IdentificationDocument
    
    # Lifestyle
    smoking_status: SmokingStatus
    personal_status: PersonalStatus
    
    # Contact Information (can be same as primary customer)
    phone: Optional[str] = None
    email: Optional[str] = None
    health_assessment: Optional[HealthAssessment] = None
    
    # Metadata
    member_id: Optional[str] = None
    created_date: datetime = field(default_factory=datetime.now)
    notes: str = ""
    
    def __post_init__(self):
        """Validate family member data"""
        if not Validator.is_valid_name(self.first_name):
            raise ValueError(f"Invalid first name: {self.first_name}")
        
        if not Validator.is_valid_name(self.last_name):
            raise ValueError(f"Invalid last name: {self.last_name}")
        
        # Family members can be any age (including minors)
        if self.birthdate > date.today():
            raise ValueError("Birthdate cannot be in the future")
        
        if self.phone and not Validator.is_valid_phone(self.phone):
            raise ValueError(f"Invalid phone format: {self.phone}")
        
        if self.email and not Validator.is_valid_email(self.email):
            raise ValueError(f"Invalid email format: {self.email}")
    
    @property
    def full_name(self) -> str:
        """Get full family member name"""
        return f"{self.first_name} {self.last_name}"
    
    @property
    def age(self) -> int:
        """Calculate family member age"""
        today = date.today()
        return today.year - self.birthdate.year - ((today.month, today.day) < (self.birthdate.month, self.birthdate.day))
    
    def get_summary(self) -> Dict[str, Any]:
        """Get family member summary"""
        health_info = None
        if self.health_assessment:
            health_info = {
                "condition_level": self.health_assessment.condition_level,
                "description": self.health_assessment.get_condition_description(),
                "requires_medical_review": self.health_assessment.requires_medical_review()
            }
        
        return {
            "member_id": self.member_id,
            "full_name": self.full_name,
            "relationship": self.relationship.value,
            "age": self.age,
            "gender": self.gender.value,
            "smoking_status": self.smoking_status.value,
            "personal_status": self.personal_status.value,
            "health": health_info,
            "document_id": self.identification.document_id,
            "document_valid": self.identification.is_valid(),
            "contact": {
                "email": self.email,
                "phone": self.phone
            }
        }


# ============================================================================
# CUSTOMER HOUSEHOLD MANAGEMENT
# ============================================================================

@dataclass
class CustomerHousehold:
    """Household containing primary customer and family members"""
    
    primary_customer: Customer
    family_members: List[FamilyMember] = field(default_factory=list)
    household_id: Optional[str] = None
    created_date: datetime = field(default_factory=datetime.now)
    
    def add_family_member(self, member: FamilyMember) -> bool:
        """Add a family member to the household"""
        # Validate member
        if not member:
            raise ValueError("Family member cannot be None")
        
        # Ensure unique member ID
        if member.member_id is None:
            member.member_id = f"FM_{len(self.family_members) + 1}_{self.primary_customer.customer_id or 'NEW'}"
        
        self.family_members.append(member)
        self.last_modified = datetime.now()
        return True
    
    def remove_family_member(self, member_id: str) -> bool:
        """Remove a family member from household"""
        self.family_members = [m for m in self.family_members if m.member_id != member_id]
        self.last_modified = datetime.now()
        return True
    
    def get_family_member(self, member_id: str) -> Optional[FamilyMember]:
        """Retrieve specific family member"""
        for member in self.family_members:
            if member.member_id == member_id:
                return member
        return None
    
    def get_all_members_summary(self) -> Dict[str, Any]:
        """Get summary of all household members"""
        return {
            "household_id": self.household_id,
            "primary_customer": self.primary_customer.get_summary(),
            "family_members_count": len(self.family_members),
            "family_members": [m.get_summary() for m in self.family_members],
            "total_members": 1 + len(self.family_members),
            "household_health_risk": self._calculate_household_health_risk()
        }
    
    def _calculate_household_health_risk(self) -> float:
        """Calculate overall household health risk"""
        if not self.family_members:
            return self.primary_customer.health_assessment.health_risk_score()
        
        all_members = [self.primary_customer] + [
            m for m in self.family_members if m.health_assessment
        ]
        
        if not all_members:
            return 0.0
        
        total_risk = sum(
            m.health_assessment.health_risk_score() if hasattr(m, 'health_assessment') else 0
            for m in all_members
        )
        return total_risk / len(all_members)
    
    def requires_household_medical_review(self) -> bool:
        """Check if any household member needs medical review"""
        if self.primary_customer.health_assessment.requires_medical_review():
            return True
        
        return any(
            m.health_assessment and m.health_assessment.requires_medical_review()
            for m in self.family_members
        )


# ============================================================================
# CUSTOMER VALIDATION SERVICE
# ============================================================================

class CustomerValidationService:
    """Service for managing customer validation and household"""
    
    def __init__(self):
        self.customers: Dict[str, Customer] = {}
        self.households: Dict[str, CustomerHousehold] = {}
    
    def create_customer(self, customer_data: Dict[str, Any]) -> Customer:
        """Create and validate customer"""
        try:
            # Validate required fields
            is_valid, errors = Validator.validate_all_required_fields(customer_data)
            if not errors:
                # Create identification document
                identification = IdentificationDocument(
                    document_type=customer_data["document_type"],
                    document_id=customer_data["document_id"],
                    issue_date=customer_data.get("issue_date", date.today()),
                    expiry_date=customer_data.get("expiry_date"),
                    issuing_country=customer_data.get("issuing_country", "USA")
                )
                
                # Create health assessment
                health_assessment = HealthAssessment(
                    condition_level=customer_data["health_condition"],
                    assessment_date=customer_data.get("assessment_date", datetime.now()),
                    notes=customer_data.get("health_notes", ""),
                    medical_conditions=customer_data.get("medical_conditions", []),
                    allergies=customer_data.get("allergies", []),
                    current_medications=customer_data.get("medications", []),
                    last_medical_checkup=customer_data.get("last_checkup")
                )
                
                # Create customer
                customer = Customer(
                    first_name=customer_data["first_name"],
                    last_name=customer_data["last_name"],
                    gender=customer_data["gender"],
                    birthdate=customer_data["birthdate"],
                    identification=identification,
                    smoking_status=customer_data["smoking_status"],
                    personal_status=customer_data["personal_status"],
                    address=customer_data["address"],
                    city=customer_data.get("city", ""),
                    state_province=customer_data.get("state", ""),
                    postal_code=customer_data.get("postal_code", ""),
                    country=customer_data.get("country", "USA"),
                    phone=customer_data.get("phone", ""),
                    email=customer_data.get("email", ""),
                    health_assessment=health_assessment,
                    notes=customer_data.get("notes", "")
                )
                
                # Generate customer ID if not provided
                if not customer.customer_id:
                    customer.customer_id = f"CUST_{len(self.customers) + 1000}"
                
                # Store customer
                self.customers[customer.customer_id] = customer
                return customer
        except ValueError as e:
            raise ValueError(f"Customer validation failed: {str(e)}")
    
    def create_household(self, customer: Customer) -> CustomerHousehold:
        """Create household for customer"""
        household = CustomerHousehold(primary_customer=customer)
        household.household_id = f"HH_{customer.customer_id}"
        self.households[household.household_id] = household
        return household
    
    def add_family_member_to_household(
        self, 
        household_id: str, 
        member_data: Dict[str, Any]
    ) -> FamilyMember:
        """Add family member to household"""
        if household_id not in self.households:
            raise ValueError(f"Household {household_id} not found")
        
        household = self.households[household_id]
        
        try:
            # Create identification document
            identification = IdentificationDocument(
                document_type=member_data["document_type"],
                document_id=member_data["document_id"],
                issue_date=member_data.get("issue_date", date.today()),
                expiry_date=member_data.get("expiry_date"),
                issuing_country=member_data.get("issuing_country", "USA")
            )
            
            # Create health assessment if provided
            health_assessment = None
            if "health_condition" in member_data:
                health_assessment = HealthAssessment(
                    condition_level=member_data["health_condition"],
                    assessment_date=member_data.get("assessment_date", datetime.now()),
                    notes=member_data.get("health_notes", ""),
                    medical_conditions=member_data.get("medical_conditions", []),
                    allergies=member_data.get("allergies", []),
                    current_medications=member_data.get("medications", []),
                    last_medical_checkup=member_data.get("last_checkup")
                )
            
            # Create family member
            member = FamilyMember(
                first_name=member_data["first_name"],
                last_name=member_data["last_name"],
                gender=member_data["gender"],
                birthdate=member_data["birthdate"],
                relationship=member_data["relationship"],
                identification=identification,
                smoking_status=member_data["smoking_status"],
                personal_status=member_data["personal_status"],
                phone=member_data.get("phone"),
                email=member_data.get("email"),
                health_assessment=health_assessment,
                notes=member_data.get("notes", "")
            )
            
            # Add to household
            household.add_family_member(member)
            return member
        except ValueError as e:
            raise ValueError(f"Family member validation failed: {str(e)}")
    
    def get_customer_by_id(self, customer_id: str) -> Optional[Customer]:
        """Retrieve customer by ID"""
        return self.customers.get(customer_id)
    
    def get_household_by_id(self, household_id: str) -> Optional[CustomerHousehold]:
        """Retrieve household by ID"""
        return self.households.get(household_id)
    
    def validate_customer_for_underwriting(self, customer_id: str) -> Dict[str, Any]:
        """Comprehensive validation for underwriting decision"""
        customer = self.get_customer_by_id(customer_id)
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")
        
        household = self.households.get(f"HH_{customer_id}")
        
        return {
            "customer_id": customer_id,
            "validation_timestamp": datetime.now().isoformat(),
            "primary_customer": customer.get_summary(),
            "household": household.get_all_members_summary() if household else None,
            "requires_medical_review": (
                household.requires_household_medical_review() if household 
                else customer.health_assessment.requires_medical_review()
            ),
            "overall_health_risk": (
                household._calculate_household_health_risk() if household
                else customer.health_assessment.health_risk_score()
            ),
            "document_validity": customer.identification.is_valid(),
            "all_documents_valid": (
                customer.identification.is_valid() and
                all(m.identification.is_valid() for m in (household.family_members if household else []))
            ),
            "ready_for_underwriting": True
        }
