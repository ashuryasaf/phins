"""
PHINS Underwriting Assistant System - Command Line Interface
Interactive interface for underwriting operations, document management,
and division reporting.
"""

from underwriting_assistant import (
    UnderwritingAssistant, NotificationManager, DivisionalReporter,
    UnderwritingQuestion, QuestionType, DocumentType, DeliveryMethod,
    QuestionnaireLibrary, UnderwritingDecision
)
from customer_validation import (
    Customer, HealthAssessment, Gender, SmokingStatus,
    PersonalStatus, CustomerValidationService
)
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
import json


class UnderwritingCLI:
    """Command-line interface for underwriting assistant"""
    
    def __init__(self):
        self.assistant = UnderwritingAssistant("CLI_AGENT", "CLI Underwriter")
        self.notification_manager = NotificationManager()
        self.reporter = DivisionalReporter()
        self.validation_service = CustomerValidationService()
        self.current_session = None
        self.current_customer = None
    
    def print_menu(self):
        """Display main menu"""
        print(f"\n{'='*70}")
        print(f"  PHINS UNDERWRITING ASSISTANT SYSTEM")
        print(f"{'='*70}")
        print(f"\n1. NEW CUSTOMER INTAKE")
        print(f"2. START UNDERWRITING SESSION")
        print(f"3. ANSWER QUESTIONNAIRE")
        print(f"4. UPLOAD DOCUMENT")
        print(f"5. VERIFY DOCUMENT")
        print(f"6. MAKE UNDERWRITING DECISION")
        print(f"7. VIEW SESSION SUMMARY")
        print(f"8. GENERATE DIVISION REPORTS")
        print(f"9. SEND NOTIFICATIONS")
        print(f"10. VIEW ALL REPORTS")
        print(f"11. EXIT")
        print(f"\n{'-'*70}\n")
    
    def get_customer_input(self) -> Customer:
        """Get customer information from input"""
        print("\n📋 CUSTOMER INTAKE FORM")
        print(f"{'-'*70}\n")
        
        first_name = input("First Name: ").strip()
        last_name = input("Last Name: ").strip()
        
        print("\nGender: 1=Male, 2=Female, 3=Other")
        gender_choice = input("Select: ")
        gender_map = {"1": Gender.MALE, "2": Gender.FEMALE, "3": Gender.OTHER}
        gender = gender_map.get(gender_choice, Gender.MALE)
        
        birth_year = int(input("Birth Year (YYYY): "))
        birth_month = int(input("Birth Month (1-12): "))
        birth_day = int(input("Birth Day (1-31): "))
        birth_date = date(birth_year, birth_month, birth_day)
        
        email = input("Email: ").strip()
        phone = input("Phone: ").strip()
        address = input("Address: ").strip()
        
        print("\nSmoking Status: 1=Non-Smoker, 2=Smoker, 3=Former Smoker, 4=Occasional")
        smoking_choice = input("Select: ")
        smoking_map = {
            "1": SmokingStatus.NON_SMOKER,
            "2": SmokingStatus.SMOKER,
            "3": SmokingStatus.FORMER_SMOKER,
            "4": SmokingStatus.OCCASIONAL
        }
        smoking_status = smoking_map.get(smoking_choice, SmokingStatus.NON_SMOKER)
        
        print("\nPersonal Status: 1=Single, 2=Married, 3=Divorced, 4=Widowed")
        status_choice = input("Select: ")
        status_map = {
            "1": PersonalStatus.SINGLE,
            "2": PersonalStatus.MARRIED,
            "3": PersonalStatus.DIVORCED,
            "4": PersonalStatus.WIDOWED
        }
        personal_status = status_map.get(status_choice, PersonalStatus.SINGLE)
        
        health_level = int(input("\nHealth Level (1-10): "))
        medical_conditions = input("Medical Conditions (comma-separated, or blank): ").strip()
        medications = input("Medications (comma-separated, or blank): ").strip()
        allergies = input("Allergies (comma-separated, or blank): ").strip()
        
        health_assessment = HealthAssessment(
            condition_level=health_level,
            medical_conditions=[c.strip() for c in medical_conditions.split(",")] if medical_conditions else [],
            medications=[m.strip() for m in medications.split(",")] if medications else [],
            allergies=[a.strip() for a in allergies.split(",")] if allergies else []
        )
        
        customer = Customer(
            customer_id=f"CUST_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            birth_date=birth_date,
            email=email,
            phone=phone,
            address=address,
            smoking_status=smoking_status,
            personal_status=personal_status,
            health_assessment=health_assessment
        )
        
        print(f"\n✓ Customer created: {customer.full_name} (ID: {customer.customer_id})")
        return customer
    
    def start_session(self, customer: Customer, questionnaire_type: str = "complete"):
        """Start underwriting session"""
        self.current_customer = customer
        self.current_session = self.assistant.start_underwriting_session(
            customer,
            questionnaire_type=questionnaire_type
        )
        print(f"\n✓ Session started: {self.current_session.session_id}")
        print(f"  Total questions: {len(self.current_session.questions)}")
        return self.current_session
    
    def answer_question_interactive(self):
        """Interactively answer a question"""
        if not self.current_session:
            print("❌ No active session. Start a session first.")
            return
        
        unanswered = self.current_session.get_unanswered_questions()
        
        if not unanswered:
            print("✓ All required questions answered!")
            return
        
        print(f"\n📝 ANSWER QUESTIONNAIRE")
        print(f"{'='*70}")
        print(f"Questions Remaining: {len(unanswered)}\n")
        
        question = unanswered[0]
        
        print(f"Q: {question.question_text}")
        if question.question_type == QuestionType.YES_NO:
            print("   Options: Yes, No")
        elif question.question_type == QuestionType.MULTIPLE_CHOICE:
            print(f"   Options: {', '.join(question.options)}")
        elif question.question_type == QuestionType.RATING:
            print("   Scale: 1-10")
        
        answer = input("\nYour answer: ").strip()
        
        success, msg = self.assistant.process_answer(
            self.current_session.session_id,
            question.question_id,
            answer
        )
        
        if success:
            print(f"✓ {msg}")
        else:
            print(f"❌ {msg}")
    
    def upload_document_interactive(self):
        """Upload document interactively"""
        if not self.current_session:
            print("❌ No active session. Start a session first.")
            return
        
        print(f"\n📁 DOCUMENT UPLOAD")
        print(f"{'='*70}\n")
        
        print("Document Type:")
        print("  1=Passport, 2=Driver License, 3=Government ID, 4=Birth Certificate, 5=Tax ID")
        doc_choice = input("Select: ")
        doc_map = {
            "1": DocumentType.PASSPORT,
            "2": DocumentType.DRIVER_LICENSE,
            "3": DocumentType.GOVERNMENT_ID,
            "4": DocumentType.BIRTH_CERTIFICATE,
            "5": DocumentType.TAX_ID
        }
        doc_type = doc_map.get(doc_choice, DocumentType.PASSPORT)
        
        filename = input("File name: ").strip()
        file_size = int(input("File size (bytes): "))
        
        has_expiry = input("Has expiry date? (y/n): ").lower() == 'y'
        expiry_date = None
        if has_expiry:
            year = int(input("Expiry Year (YYYY): "))
            month = int(input("Expiry Month (1-12): "))
            day = int(input("Expiry Day (1-31): "))
            expiry_date = date(year, month, day)
        
        document = self.assistant.upload_document(
            self.current_session.session_id,
            doc_type,
            filename,
            file_size,
            expiry_date
        )
        
        print(f"\n✓ Document uploaded: {document.document_id}")
        print(f"  Type: {document.document_type.value}")
        print(f"  File: {document.file_name}")
        print(f"  Status: {document.verification_status.value}")
    
    def verify_document_interactive(self):
        """Verify document"""
        if not self.current_session:
            print("❌ No active session. Start a session first.")
            return
        
        if not self.current_session.documents:
            print("❌ No documents uploaded yet.")
            return
        
        print(f"\n✓ DOCUMENT VERIFICATION")
        print(f"{'='*70}\n")
        print("Documents:")
        for i, doc in enumerate(self.current_session.documents, 1):
            print(f"  {i}. {doc.document_type.value} - {doc.file_name} ({doc.verification_status.value})")
        
        choice = int(input("\nSelect document: ")) - 1
        document = self.current_session.documents[choice]
        
        notes = input("Verification notes: ").strip()
        
        is_verified = self.assistant.verify_document(
            self.current_session.session_id,
            document.document_id,
            verified_by="CLI User",
            notes=notes
        )
        
        if is_verified:
            print(f"✓ Document verified: {document.document_type.value}")
        else:
            print(f"❌ Document verification failed")
    
    def make_decision_interactive(self):
        """Make underwriting decision"""
        if not self.current_session:
            print("❌ No active session. Start a session first.")
            return
        
        print(f"\n📊 UNDERWRITING DECISION")
        print(f"{'='*70}\n")
        
        notes = input("Additional notes: ").strip()
        
        decision = self.assistant.make_underwriting_decision(
            self.current_session,
            manual_notes=notes
        )
        
        print(f"\n✓ Decision made: {decision.value}")
        print(f"  Risk Score: {self.current_session.risk_score:.1%}")
        print(f"  Notes: {self.current_session.decision_notes}")
    
    def generate_reports_interactive(self):
        """Generate all division reports"""
        if not self.current_session:
            print("❌ No active session. Start a session first.")
            return
        
        print(f"\n📋 GENERATING DIVISION REPORTS")
        print(f"{'='*70}\n")
        
        print("Generating reports...")
        
        uw_report = self.reporter.generate_underwriting_report(
            self.current_session,
            assigned_underwriter="CLI User"
        )
        print("✓ Underwriting report generated")
        
        risk_report = self.reporter.generate_risk_assessment_report(
            self.current_session,
            assigned_risk_manager="Risk Management"
        )
        print("✓ Risk assessment report generated")
        
        act_report = self.reporter.generate_actuary_report(
            self.current_session,
            assigned_actuary="Actuarial Department"
        )
        print("✓ Actuary report generated")
        
        claims_report = self.reporter.generate_claims_report(
            claim_id=f"CLM_{self.current_session.customer_id}_{datetime.now().strftime('%Y%m%d')}",
            customer_id=self.current_session.customer_id,
            claim_amount=0.00,
            claim_type="Policy Application",
            claim_description="Application intake for new policy",
            assigned_adjuster="Claims Department"
        )
        print("✓ Claims intake report generated")
        
        print(f"\n✓ All reports generated and sent to divisions")
        
        return {
            "underwriting": uw_report,
            "risk": risk_report,
            "actuary": act_report,
            "claims": claims_report
        }
    
    def send_notification_interactive(self):
        """Send notification to customer"""
        if not self.current_session:
            print("❌ No active session. Start a session first.")
            return
        
        print(f"\n📧 SEND NOTIFICATION")
        print(f"{'='*70}\n")
        
        print("Template:")
        print("  1=Approved")
        print("  2=Approved with Conditions")
        print("  3=Pending Review")
        print("  4=Claim Filed")
        template_choice = input("Select: ")
        template_map = {
            "1": "uw_approved",
            "2": "uw_conditions",
            "3": "uw_pending",
            "4": "claim_filed"
        }
        template = template_map.get(template_choice, "uw_approved")
        
        print("\nDelivery Method:")
        print("  1=Email")
        print("  2=SMS")
        print("  3=Signed Document")
        print("  4=Combined")
        method_choice = input("Select: ")
        method_map = {
            "1": DeliveryMethod.EMAIL,
            "2": DeliveryMethod.SMS,
            "3": DeliveryMethod.SIGNED_DOCUMENT,
            "4": DeliveryMethod.COMBINED
        }
        delivery_method = method_map.get(method_choice, DeliveryMethod.EMAIL)
        
        context = {
            "customer_name": self.current_customer.first_name,
            "policy_id": f"POL_{self.current_session.customer_id}",
            "effective_date": (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
        }
        
        notification = self.notification_manager.send_notification(
            customer_id=self.current_session.customer_id,
            recipient=self.current_customer.email,
            template_name=template,
            delivery_method=delivery_method,
            context=context,
            signature_required=(delivery_method == DeliveryMethod.SIGNED_DOCUMENT)
        )
        
        print(f"\n✓ Notification sent")
        print(f"  ID: {notification.delivery_id}")
        print(f"  Method: {notification.delivery_method.value}")
        print(f"  Recipient: {notification.recipient}")
    
    def view_session_summary(self):
        """Display session summary"""
        if not self.current_session:
            print("❌ No active session.")
            return
        
        summary = self.assistant.get_session_summary(self.current_session.session_id)
        
        print(f"\n📋 SESSION SUMMARY")
        print(f"{'='*70}\n")
        print(json.dumps(summary, indent=2))
    
    def view_all_reports(self):
        """Display all generated reports"""
        if not self.reporter.reports:
            print("❌ No reports generated yet.")
            return
        
        print(f"\n📊 ALL GENERATED REPORTS")
        print(f"{'='*70}\n")
        print(f"Total Reports: {len(self.reporter.reports)}\n")
        
        for i, report in enumerate(self.reporter.reports, 1):
            print(f"{i}. {report.get('report_type', 'Unknown')} (ID: {report.get('report_id', 'N/A')})")
            print(f"   Date: {report.get('report_date', 'N/A')}")
            print()
    
    def run(self):
        """Run CLI interface"""
        while True:
            self.print_menu()
            choice = input("Enter choice (1-11): ").strip()
            
            try:
                if choice == "1":
                    self.current_customer = self.get_customer_input()
                
                elif choice == "2":
                    if not self.current_customer:
                        print("❌ Please create customer first (option 1)")
                    else:
                        self.start_session(self.current_customer)
                
                elif choice == "3":
                    self.answer_question_interactive()
                
                elif choice == "4":
                    self.upload_document_interactive()
                
                elif choice == "5":
                    self.verify_document_interactive()
                
                elif choice == "6":
                    self.make_decision_interactive()
                
                elif choice == "7":
                    self.view_session_summary()
                
                elif choice == "8":
                    self.generate_reports_interactive()
                
                elif choice == "9":
                    self.send_notification_interactive()
                
                elif choice == "10":
                    self.view_all_reports()
                
                elif choice == "11":
                    print("\n✓ Exiting PHINS Underwriting Assistant")
                    break
                
                else:
                    print("❌ Invalid choice. Please try again.")
            
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                print("Please try again.")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("  PHINS UNDERWRITING ASSISTANT SYSTEM - INTERACTIVE CLI")
    print("="*70 + "\n")
    print("Loading system...")
    
    cli = UnderwritingCLI()
    cli.run()
