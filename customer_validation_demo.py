"""
PHINS Customer Validation Demo
Comprehensive demonstration of customer validation and family member management
Shows all features with practical underwriting examples
"""

from customer_validation import (
    Customer, FamilyMember, CustomerHousehold, CustomerValidationService,
    IdentificationDocument, HealthAssessment,
    Gender, SmokingStatus, PersonalStatus, DocumentType, FamilyRelationship,
    Validator
)
from datetime import date, datetime, timedelta
import json


def print_header(title: str):
    """Print formatted header"""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def demo_1_basic_customer_validation():
    """DEMO 1: Basic customer creation and validation"""
    print_header("DEMO 1: Basic Customer Validation")
    
    service = CustomerValidationService()
    
    # Create primary customer
    customer_data = {
        "first_name": "John",
        "last_name": "Smith",
        "gender": Gender.MALE,
        "birthdate": date(1980, 5, 15),
        "document_type": DocumentType.PASSPORT,
        "document_id": "PS123456789",
        "issue_date": date(2020, 1, 1),
        "expiry_date": date(2030, 1, 1),
        "smoking_status": SmokingStatus.NON_SMOKER,
        "personal_status": PersonalStatus.MARRIED,
        "address": "123 Main Street",
        "city": "New York",
        "state": "NY",
        "postal_code": "10001",
        "phone": "+1-212-555-0001",
        "email": "john.smith@example.com",
        "health_condition": 3,  # Good
        "health_notes": "Generally healthy, no major health concerns",
        "medical_conditions": [],
        "allergies": [],
        "medications": [],
    }
    
    try:
        customer = service.create_customer(customer_data)
        print(f"✅ Customer Created Successfully!")
        print(f"   Customer ID: {customer.customer_id}")
        print(f"   Name: {customer.full_name}")
        print(f"   Age: {customer.age} years")
        print(f"   Gender: {customer.gender.value}")
        print(f"   Smoking Status: {customer.smoking_status.value}")
        print(f"   Health Condition: {customer.health_assessment.get_condition_description()} ({customer.health_assessment.condition_level}/10)")
        print(f"   Document Valid: {customer.identification.is_valid()}")
        print(f"   Contact: {customer.email} | {customer.phone}")
        return customer
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def demo_2_health_assessment():
    """DEMO 2: Health assessment and medical review requirements"""
    print_header("DEMO 2: Health Assessment & Medical Review")
    
    service = CustomerValidationService()
    
    # Create customer with health conditions
    customer_data = {
        "first_name": "Jane",
        "last_name": "Johnson",
        "gender": Gender.FEMALE,
        "birthdate": date(1975, 3, 22),
        "document_type": DocumentType.NATIONAL_ID,
        "document_id": "ID-987654321",
        "issue_date": date(2022, 6, 15),
        "expiry_date": date(2032, 6, 15),
        "smoking_status": SmokingStatus.FORMER_SMOKER,
        "personal_status": PersonalStatus.DIVORCED,
        "address": "456 Oak Avenue",
        "city": "Los Angeles",
        "state": "CA",
        "postal_code": "90001",
        "phone": "+1-213-555-0002",
        "email": "jane.johnson@example.com",
        "health_condition": 7,  # Poor
        "health_notes": "Requires careful assessment",
        "medical_conditions": ["Hypertension", "Type 2 Diabetes"],
        "allergies": ["Penicillin"],
        "medications": ["Metformin", "Lisinopril"],
        "last_checkup": date(2024, 11, 1)
    }
    
    try:
        customer = service.create_customer(customer_data)
        print(f"✅ Customer with Health Conditions Created!")
        print(f"   Name: {customer.full_name}")
        print(f"   Health Condition Level: {customer.health_assessment.condition_level}/10")
        print(f"   Health Status: {customer.health_assessment.get_condition_description()}")
        print(f"   Medical Conditions: {', '.join(customer.health_assessment.medical_conditions)}")
        print(f"   Allergies: {', '.join(customer.health_assessment.allergies)}")
        print(f"   Current Medications: {', '.join(customer.health_assessment.current_medications)}")
        print(f"   Last Medical Checkup: {customer.health_assessment.last_medical_checkup}")
        print(f"\n   ⚠️  Requires Medical Review: {customer.health_assessment.requires_medical_review()}")
        print(f"   📊 Health Risk Score: {customer.health_assessment.health_risk_score():.2%}")
        return customer
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def demo_3_validation_rules():
    """DEMO 3: Validation rules in action"""
    print_header("DEMO 3: Validation Rules & Error Handling")
    
    print("Testing various validation rules...\n")
    
    # Test name validation
    test_cases = [
        ("John", True, "Valid name"),
        ("J", False, "Too short"),
        ("John123", False, "Contains numbers"),
        ("Mary-Jane", True, "Valid hyphenated name"),
    ]
    
    print("✓ Name Validation:")
    for name, expected, description in test_cases:
        result = Validator.is_valid_name(name)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{name}': {description} - {result}")
    
    # Test email validation
    print("\n✓ Email Validation:")
    email_cases = [
        ("john@example.com", True, "Valid email"),
        ("invalid.email", False, "Missing domain"),
        ("test@domain.co.uk", True, "Valid with country TLD"),
    ]
    
    for email, expected, description in email_cases:
        result = Validator.is_valid_email(email)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{email}': {description} - {result}")
    
    # Test phone validation
    print("\n✓ Phone Validation:")
    phone_cases = [
        ("+1-212-555-0001", True, "Valid with country code"),
        ("555-1234", False, "Too short"),
        ("212-555-0001", True, "Valid format"),
    ]
    
    for phone, expected, description in phone_cases:
        result = Validator.is_valid_phone(phone)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{phone}': {description} - {result}")
    
    # Test age validation
    print("\n✓ Age/Birthdate Validation:")
    age_cases = [
        (date(1980, 5, 15), True, "Adult (44 years)"),
        (date(2015, 1, 1), False, "Minor (9 years)"),
        (date(1900, 1, 1), False, "Too old (124 years)"),
    ]
    
    for birthdate, expected, description in age_cases:
        is_valid, msg = Validator.is_valid_birthdate(birthdate)
        status = "✅" if is_valid == expected else "❌"
        print(f"  {status} {birthdate}: {description} - {msg}")


def demo_4_family_members():
    """DEMO 4: Family members and household management"""
    print_header("DEMO 4: Family Members & Household Management")
    
    service = CustomerValidationService()
    
    # Create primary customer
    primary_data = {
        "first_name": "Robert",
        "last_name": "Williams",
        "gender": Gender.MALE,
        "birthdate": date(1978, 7, 10),
        "document_type": DocumentType.DRIVER_LICENSE,
        "document_id": "DL-111222333",
        "issue_date": date(2021, 3, 15),
        "expiry_date": date(2027, 3, 15),
        "smoking_status": SmokingStatus.NON_SMOKER,
        "personal_status": PersonalStatus.MARRIED,
        "address": "789 Elm Street",
        "city": "Chicago",
        "state": "IL",
        "postal_code": "60601",
        "phone": "+1-312-555-0003",
        "email": "robert.williams@example.com",
        "health_condition": 4,
    }
    
    primary = service.create_customer(primary_data)
    household = service.create_household(primary)
    
    print(f"✅ Primary Customer Created: {primary.full_name}")
    print(f"   Household ID: {household.household_id}\n")
    
    # Add spouse
    spouse_data = {
        "first_name": "Sarah",
        "last_name": "Williams",
        "gender": Gender.FEMALE,
        "birthdate": date(1980, 9, 22),
        "relationship": FamilyRelationship.SPOUSE,
        "document_type": DocumentType.NATIONAL_ID,
        "document_id": "ID-444555666",
        "issue_date": date(2022, 8, 1),
        "expiry_date": date(2032, 8, 1),
        "smoking_status": SmokingStatus.NON_SMOKER,
        "personal_status": PersonalStatus.MARRIED,
        "health_condition": 3,
    }
    
    spouse = service.add_family_member_to_household(household.household_id, spouse_data)
    print(f"✅ Spouse Added: {spouse.full_name}")
    print(f"   Member ID: {spouse.member_id}")
    print(f"   Relationship: {spouse.relationship.value}")
    print(f"   Health Condition: {spouse.health_assessment.get_condition_description()}\n")
    
    # Add child
    child_data = {
        "first_name": "Emily",
        "last_name": "Williams",
        "gender": Gender.FEMALE,
        "birthdate": date(2010, 4, 8),
        "relationship": FamilyRelationship.CHILD,
        "document_type": DocumentType.PASSPORT,
        "document_id": "PS-555666777",
        "issue_date": date(2023, 2, 1),
        "expiry_date": date(2033, 2, 1),
        "smoking_status": SmokingStatus.NON_SMOKER,
        "personal_status": PersonalStatus.SINGLE,
        "health_condition": 2,
    }
    
    child = service.add_family_member_to_household(household.household_id, child_data)
    print(f"✅ Child Added: {child.full_name}")
    print(f"   Member ID: {child.member_id}")
    print(f"   Relationship: {child.relationship.value}")
    print(f"   Age: {child.age} years")
    print(f"   Health Condition: {child.health_assessment.get_condition_description()}\n")
    
    # Display household summary
    print("📋 Household Summary:")
    summary = household.get_all_members_summary()
    print(f"   Total Members: {summary['total_members']}")
    print(f"   Primary: {summary['primary_customer']['full_name']} (Age: {summary['primary_customer']['age']})")
    print(f"   Family Members: {summary['family_members_count']}")
    for member in summary['family_members']:
        print(f"     - {member['full_name']} ({member['relationship']}, Age: {member['age']})")
    print(f"   Household Health Risk: {summary['household_health_risk']:.2%}")
    print(f"   Requires Medical Review: {household.requires_household_medical_review()}")


def demo_5_underwriting_validation():
    """DEMO 5: Complete underwriting validation"""
    print_header("DEMO 5: Complete Underwriting Validation")
    
    service = CustomerValidationService()
    
    # Create customer with complete information
    customer_data = {
        "first_name": "Michael",
        "last_name": "Brown",
        "gender": Gender.MALE,
        "birthdate": date(1985, 11, 5),
        "document_type": DocumentType.PASSPORT,
        "document_id": "PS-777888999",
        "issue_date": date(2019, 4, 10),
        "expiry_date": date(2029, 4, 10),
        "smoking_status": SmokingStatus.SMOKER,
        "personal_status": PersonalStatus.SINGLE,
        "address": "321 Pine Road",
        "city": "Houston",
        "state": "TX",
        "postal_code": "77001",
        "phone": "+1-713-555-0004",
        "email": "michael.brown@example.com",
        "health_condition": 6,
        "health_notes": "Smoker with elevated risk",
        "medical_conditions": ["Asthma"],
        "allergies": [],
        "medications": ["Albuterol"],
    }
    
    try:
        customer = service.create_customer(customer_data)
        household = service.create_household(customer)
        
        # Get underwriting validation report
        validation = service.validate_customer_for_underwriting(customer.customer_id)
        
        print(f"✅ Underwriting Validation Report")
        print(f"\n📋 Customer Information:")
        summary = validation['primary_customer']
        print(f"   Name: {summary['full_name']}")
        print(f"   Age: {summary['age']} years")
        print(f"   Gender: {summary['gender']}")
        print(f"   Smoking Status: {summary['smoking_status']}")
        print(f"   Personal Status: {summary['personal_status']}")
        
        print(f"\n🏥 Health Assessment:")
        print(f"   Condition Level: {summary['health_condition']}/10 ({summary['health_description']})")
        print(f"   Health Risk Score: {summary['health_risk_score']:.1%}")
        print(f"   Requires Medical Review: {summary['requires_medical_review']}")
        
        print(f"\n📄 Documentation:")
        print(f"   Document Type: {summary['contact']}")
        doc_validity = "✅ Valid" if validation['document_validity'] else "❌ Expired"
        print(f"   Document Status: {doc_validity}")
        print(f"   All Documents Valid: {'✅ Yes' if validation['all_documents_valid'] else '❌ No'}")
        
        print(f"\n✅ Validation Status:")
        print(f"   Ready for Underwriting: {'✅ Yes' if validation['ready_for_underwriting'] else '❌ No'}")
        print(f"   Validation Timestamp: {validation['validation_timestamp']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def demo_6_document_expiry():
    """DEMO 6: Document expiry tracking"""
    print_header("DEMO 6: Document Expiry Tracking")
    
    print("Creating customers with various document expiry statuses...\n")
    
    # Customer with soon-to-expire document
    service = CustomerValidationService()
    
    customer_data = {
        "first_name": "David",
        "last_name": "Taylor",
        "gender": Gender.MALE,
        "birthdate": date(1988, 2, 14),
        "document_type": DocumentType.PASSPORT,
        "document_id": "PS-999888777",
        "issue_date": date(2024, 3, 1),
        "expiry_date": date(2026, 3, 1),  # Expires in ~3 months
        "smoking_status": SmokingStatus.NON_SMOKER,
        "personal_status": PersonalStatus.SINGLE,
        "address": "654 Maple Drive",
        "city": "Seattle",
        "state": "WA",
        "postal_code": "98101",
        "phone": "+1-206-555-0005",
        "email": "david.taylor@example.com",
        "health_condition": 2,
    }
    
    customer = service.create_customer(customer_data)
    doc = customer.identification
    
    print(f"✅ Customer: {customer.full_name}")
    print(f"   Document Type: {doc.document_type.value}")
    print(f"   Document ID: {doc.document_id}")
    print(f"   Issue Date: {doc.issue_date}")
    print(f"   Expiry Date: {doc.expiry_date}")
    print(f"   Days to Expiry: {doc.days_to_expiry()} days")
    print(f"   Document Valid: {'✅ Yes' if doc.is_valid() else '❌ No'}")
    
    if doc.days_to_expiry() and doc.days_to_expiry() < 90:
        print(f"   ⚠️  WARNING: Document expires soon!")


def demo_7_bulk_household():
    """DEMO 7: Bulk family household creation"""
    print_header("DEMO 7: Large Household with Multiple Family Members")
    
    service = CustomerValidationService()
    
    # Create primary customer (grandparent)
    primary_data = {
        "first_name": "George",
        "last_name": "Anderson",
        "gender": Gender.MALE,
        "birthdate": date(1945, 6, 20),
        "document_type": DocumentType.PASSPORT,
        "document_id": "PS-111000111",
        "issue_date": date(2020, 7, 1),
        "expiry_date": date(2030, 7, 1),
        "smoking_status": SmokingStatus.FORMER_SMOKER,
        "personal_status": PersonalStatus.WIDOWED,
        "address": "999 Sunset Boulevard",
        "city": "Miami",
        "state": "FL",
        "postal_code": "33101",
        "phone": "+1-305-555-0006",
        "email": "george.anderson@example.com",
        "health_condition": 5,
    }
    
    primary = service.create_customer(primary_data)
    household = service.create_household(primary)
    print(f"✅ Primary Customer: {primary.full_name} (Age: {primary.age})")
    print(f"   Household ID: {household.household_id}\n")
    
    # Add multiple family members
    family_members_data = [
        {
            "first_name": "Patricia",
            "last_name": "Anderson",
            "gender": Gender.FEMALE,
            "birthdate": date(1950, 3, 15),
            "relationship": FamilyRelationship.SPOUSE,
            "document_type": DocumentType.NATIONAL_ID,
            "document_id": "ID-222111222",
            "issue_date": date(2020, 5, 1),
            "expiry_date": date(2030, 5, 1),
            "smoking_status": SmokingStatus.NON_SMOKER,
            "personal_status": PersonalStatus.MARRIED,
            "health_condition": 4,
        },
        {
            "first_name": "Thomas",
            "last_name": "Anderson",
            "gender": Gender.MALE,
            "birthdate": date(1975, 8, 22),
            "relationship": FamilyRelationship.CHILD,
            "document_type": DocumentType.DRIVER_LICENSE,
            "document_id": "DL-333222333",
            "issue_date": date(2022, 1, 15),
            "expiry_date": date(2028, 1, 15),
            "smoking_status": SmokingStatus.NON_SMOKER,
            "personal_status": PersonalStatus.MARRIED,
            "health_condition": 3,
        },
        {
            "first_name": "Rebecca",
            "last_name": "Anderson",
            "gender": Gender.FEMALE,
            "birthdate": date(2008, 11, 10),
            "relationship": FamilyRelationship.GRANDCHILD,
            "document_type": DocumentType.PASSPORT,
            "document_id": "PS-444333444",
            "issue_date": date(2024, 9, 1),
            "expiry_date": date(2034, 9, 1),
            "smoking_status": SmokingStatus.NON_SMOKER,
            "personal_status": PersonalStatus.SINGLE,
            "health_condition": 1,
        },
        {
            "first_name": "Christopher",
            "last_name": "Anderson",
            "gender": Gender.MALE,
            "birthdate": date(2012, 4, 5),
            "relationship": FamilyRelationship.GRANDCHILD,
            "document_type": DocumentType.PASSPORT,
            "document_id": "PS-555444555",
            "issue_date": date(2024, 6, 1),
            "expiry_date": date(2034, 6, 1),
            "smoking_status": SmokingStatus.NON_SMOKER,
            "personal_status": PersonalStatus.SINGLE,
            "health_condition": 1,
        },
    ]
    
    for member_data in family_members_data:
        member = service.add_family_member_to_household(household.household_id, member_data)
        print(f"✅ {member.relationship.value}: {member.full_name} (Age: {member.age})")
    
    # Display full household summary
    summary = household.get_all_members_summary()
    print(f"\n📋 Complete Household Summary:")
    print(f"   Total Members: {summary['total_members']}")
    print(f"   Family Members: {summary['family_members_count']}")
    print(f"   Household Health Risk: {summary['household_health_risk']:.1%}")
    print(f"   Requires Medical Review: {household.requires_household_medical_review()}")
    
    print(f"\n👥 Member Breakdown:")
    print(f"   Primary: {summary['primary_customer']['full_name']} ({summary['primary_customer']['age']} yrs)")
    for member in summary['family_members']:
        health = "Good" if member['health']['condition_level'] <= 4 else "Needs Review"
        print(f"   • {member['full_name']} - {member['relationship']} ({member['age']} yrs) - Health: {health}")


def run_all_demos():
    """Run all demonstrations"""
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "  🏥 PHINS CUSTOMER VALIDATION MODULE - COMPREHENSIVE DEMO".center(78) + "║")
    print("║" + "  Underwriting Assessment for Individuals & Families".center(78) + "║")
    print("║" + " " * 78 + "║")
    print("╚" + "═" * 78 + "╝")
    
    demos = [
        ("Basic Customer Validation", demo_1_basic_customer_validation),
        ("Health Assessment & Medical Review", demo_2_health_assessment),
        ("Validation Rules & Error Handling", demo_3_validation_rules),
        ("Family Members & Households", demo_4_family_members),
        ("Complete Underwriting Validation", demo_5_underwriting_validation),
        ("Document Expiry Tracking", demo_6_document_expiry),
        ("Large Household with Multiple Members", demo_7_bulk_household),
    ]
    
    for i, (title, demo_func) in enumerate(demos, 1):
        try:
            demo_func()
        except Exception as e:
            print(f"\n❌ Demo {i} Error: {e}")
            import traceback
            traceback.print_exc()
    
    print_header("✅ ALL DEMONSTRATIONS COMPLETE")
    print("""
The PHINS Customer Validation Module is now ready for use in your insurance
underwriting operations. The system provides:

✅ Comprehensive customer validation (name, email, phone, address, age)
✅ Personal identification document management (passport, ID, driver license)
✅ Health assessment with 10-point scale for risk evaluation
✅ Family member support with relationship tracking
✅ Household management for multi-generational policies
✅ Automatic validation rules and error handling
✅ Underwriting readiness reports
✅ Document expiry tracking and alerts

All validation is performed using zero external dependencies - pure Python stdlib!
    """)


if __name__ == "__main__":
    run_all_demos()
