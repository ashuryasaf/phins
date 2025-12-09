"""
PHINS File Management System - Demonstration
Shows file upload, download, and management across all divisions
"""

from phins_system import (
    PHINSInsuranceSystem,
    FileType, DocumentDivision, FileStatus,
    FileManagement
)
from datetime import datetime


def print_header(title: str):
    """Print a section header"""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def demo_sales_division_files(system: PHINSInsuranceSystem):
    """Demonstrate file management in Sales Division"""
    print_header("SALES DIVISION - POLICY DOCUMENTS")

    # Create sample policy documents
    doc1 = system.upload_document(
        file_name="Auto_Insurance_Policy_POL001.pdf",
        file_type=FileType.POLICY_DOCUMENT,
        division=DocumentDivision.SALES,
        related_entity_id="POL001",
        related_entity_type="Policy",
        file_size=2500000,  # 2.5 MB
        file_path="/documents/sales/policies/POL001_auto_policy.pdf",
        uploaded_by="sales_agent_01",
        description="Comprehensive Auto Insurance Policy Document"
    )

    print(f"✓ Uploaded Policy Document: {doc1.file_name}")
    print(f"  File Type: {doc1.file_type.value}")
    print(f"  Size: {doc1.file_size_mb} MB")
    print(f"  Division: {doc1.division.value}")
    print(f"  Status: {doc1.status.value}\n")

    # Upload insurance card
    doc2 = system.upload_document(
        file_name="Insurance_Card_POL001.jpg",
        file_type=FileType.INSURANCE_CARD,
        division=DocumentDivision.SALES,
        related_entity_id="POL001",
        related_entity_type="Policy",
        file_size=850000,  # 0.85 MB
        file_path="/documents/sales/cards/POL001_insurance_card.jpg",
        uploaded_by="sales_agent_01",
        description="Digital copy of insurance card"
    )

    print(f"✓ Uploaded Insurance Card: {doc2.file_name}")
    print(f"  File Type: {doc2.file_type.value}")
    print(f"  Size: {doc2.file_size_mb} MB\n")

    # Verify documents
    system.verify_document(doc1.document_id, "manager_sales")
    system.verify_document(doc2.document_id, "manager_sales")
    
    print(f"✓ Documents Verified by: manager_sales")
    print(f"  Doc1 Status: {system.get_document(doc1.document_id).status.value}")
    print(f"  Doc2 Status: {system.get_document(doc2.document_id).status.value}\n")


def demo_underwriting_division_files(system: PHINSInsuranceSystem):
    """Demonstrate file management in Underwriting Division"""
    print_header("UNDERWRITING DIVISION - MEDICAL & DOCUMENTATION")

    # Medical report upload
    doc3 = system.upload_document(
        file_name="Medical_Report_CUST001.pdf",
        file_type=FileType.MEDICAL_REPORT,
        division=DocumentDivision.UNDERWRITING,
        related_entity_id="CUST001",
        related_entity_type="Customer",
        file_size=3200000,  # 3.2 MB
        file_path="/documents/underwriting/medical/CUST001_medical_report.pdf",
        uploaded_by="underwriter_01",
        description="Medical examination report for risk assessment"
    )

    # ID document upload
    doc4 = system.upload_document(
        file_name="ID_Document_CUST001.pdf",
        file_type=FileType.ID_DOCUMENT,
        division=DocumentDivision.UNDERWRITING,
        related_entity_id="CUST001",
        related_entity_type="Customer",
        file_size=1500000,  # 1.5 MB
        file_path="/documents/underwriting/id/CUST001_id_document.pdf",
        uploaded_by="underwriter_01",
        description="Identification document for verification"
    )

    print(f"✓ Uploaded Medical Report: {doc3.file_name}")
    print(f"  File Type: {doc3.file_type.value}")
    print(f"  Size: {doc3.file_size_mb} MB")
    print(f"  Division: {doc3.division.value}\n")

    print(f"✓ Uploaded ID Document: {doc4.file_name}")
    print(f"  File Type: {doc4.file_type.value}")
    print(f"  Size: {doc4.file_size_mb} MB\n")

    # Verify medical report, reject ID document
    system.verify_document(doc3.document_id, "underwriting_mgr")
    system.reject_document(doc4.document_id, "underwriting_mgr", "Poor image quality, please resubmit")

    print(f"✓ Medical Report Verified")
    print(f"  Status: {system.get_document(doc3.document_id).status.value}\n")

    print(f"✓ ID Document Rejected")
    doc4_rejected = system.get_document(doc4.document_id)
    print(f"  Status: {doc4_rejected.status.value}")
    print(f"  Rejection Reason: {doc4_rejected.rejection_reason}\n")


def demo_claims_division_files(system: PHINSInsuranceSystem):
    """Demonstrate file management in Claims Division"""
    print_header("CLAIMS DIVISION - CLAIM DOCUMENTATION")

    # Claim form upload
    doc5 = system.upload_document(
        file_name="Claim_Form_CLM001.pdf",
        file_type=FileType.CLAIM_FORM,
        division=DocumentDivision.CLAIMS,
        related_entity_id="CLM001",
        related_entity_type="Claim",
        file_size=1800000,  # 1.8 MB
        file_path="/documents/claims/forms/CLM001_claim_form.pdf",
        uploaded_by="customer_portal",
        description="Claim submission form with customer information"
    )

    # Proof of loss upload
    doc6 = system.upload_document(
        file_name="Proof_of_Loss_CLM001.pdf",
        file_type=FileType.PROOF_OF_LOSS,
        division=DocumentDivision.CLAIMS,
        related_entity_id="CLM001",
        related_entity_type="Claim",
        file_size=4500000,  # 4.5 MB
        file_path="/documents/claims/proof/CLM001_proof_of_loss.pdf",
        uploaded_by="customer_portal",
        description="Supporting documents for loss verification"
    )

    print(f"✓ Uploaded Claim Form: {doc5.file_name}")
    print(f"  File Type: {doc5.file_type.value}")
    print(f"  Size: {doc5.file_size_mb} MB\n")

    print(f"✓ Uploaded Proof of Loss: {doc6.file_name}")
    print(f"  File Type: {doc6.file_type.value}")
    print(f"  Size: {doc6.file_size_mb} MB\n")

    # Verify both documents
    system.verify_document(doc5.document_id, "claims_adjuster_01")
    system.verify_document(doc6.document_id, "claims_adjuster_01")

    print(f"✓ All Claim Documents Verified by: claims_adjuster_01\n")


def demo_accounting_division_files(system: PHINSInsuranceSystem):
    """Demonstrate file management in Accounting Division"""
    print_header("ACCOUNTING DIVISION - INVOICES & RECEIPTS")

    # Invoice upload
    doc7 = system.upload_document(
        file_name="Invoice_BILL001.pdf",
        file_type=FileType.INVOICE,
        division=DocumentDivision.ACCOUNTING,
        related_entity_id="BILL001",
        related_entity_type="Bill",
        file_size=850000,  # 0.85 MB
        file_path="/documents/accounting/invoices/BILL001_invoice.pdf",
        uploaded_by="accounting_system",
        description="Premium billing invoice"
    )

    # Payment receipt
    doc8 = system.upload_document(
        file_name="Payment_Receipt_BILL001.pdf",
        file_type=FileType.PAYMENT_RECEIPT,
        division=DocumentDivision.ACCOUNTING,
        related_entity_id="BILL001",
        related_entity_type="Bill",
        file_size=650000,  # 0.65 MB
        file_path="/documents/accounting/receipts/BILL001_receipt.pdf",
        uploaded_by="payment_processor",
        description="Payment confirmation and receipt"
    )

    print(f"✓ Uploaded Invoice: {doc7.file_name}")
    print(f"  File Type: {doc7.file_type.value}")
    print(f"  Size: {doc7.file_size_mb} MB\n")

    print(f"✓ Uploaded Payment Receipt: {doc8.file_name}")
    print(f"  File Type: {doc8.file_type.value}")
    print(f"  Size: {doc8.file_size_mb} MB\n")

    # Verify both
    system.verify_document(doc7.document_id, "accounting_manager")
    system.verify_document(doc8.document_id, "accounting_manager")

    print(f"✓ All Accounting Documents Verified\n")


def demo_customer_portal_files(system: PHINSInsuranceSystem):
    """Demonstrate file management in Customer Portal"""
    print_header("CUSTOMER PORTAL - PERSONAL DOCUMENT ACCESS")

    # Customer uploaded document
    doc9 = system.upload_document(
        file_name="Customer_Statement_Request_CUST001.pdf",
        file_type=FileType.OTHER,
        division=DocumentDivision.CUSTOMER_PORTAL,
        related_entity_id="CUST001",
        related_entity_type="Customer",
        file_size=500000,  # 0.5 MB
        file_path="/documents/portal/CUST001_statement_request.pdf",
        uploaded_by="CUST001",
        description="Customer statement request"
    )

    print(f"✓ Customer Document Uploaded: {doc9.file_name}")
    print(f"  Uploaded by: {doc9.uploaded_by}")
    print(f"  Size: {doc9.file_size_mb} MB")
    print(f"  Status: {doc9.status.value}\n")

    # Verify customer document
    system.verify_document(doc9.document_id, "portal_admin")
    print(f"✓ Document Verified by Portal Admin\n")


def demo_file_retrieval_and_organization(system: PHINSInsuranceSystem):
    """Demonstrate file retrieval and organization features"""
    print_header("FILE RETRIEVAL & ORGANIZATION")

    # Get documents by division
    print("1. DOCUMENTS BY DIVISION:")
    print("-" * 80)
    
    sales_docs = system.get_division_documents(DocumentDivision.SALES)
    print(f"   Sales Division: {len(sales_docs)} documents")
    for doc in sales_docs:
        print(f"     • {doc.file_name} ({doc.file_size_mb} MB)")

    underwriting_docs = system.get_division_documents(DocumentDivision.UNDERWRITING)
    print(f"\n   Underwriting Division: {len(underwriting_docs)} documents")
    for doc in underwriting_docs:
        print(f"     • {doc.file_name} ({doc.file_size_mb} MB)")

    claims_docs = system.get_division_documents(DocumentDivision.CLAIMS)
    print(f"\n   Claims Division: {len(claims_docs)} documents")
    for doc in claims_docs:
        print(f"     • {doc.file_name} ({doc.file_size_mb} MB)\n")

    # Get documents by type
    print("2. DOCUMENTS BY TYPE:")
    print("-" * 80)
    
    policy_docs = system.get_documents_by_type(FileType.POLICY_DOCUMENT)
    print(f"   Policy Documents: {len(policy_docs)}")
    for doc in policy_docs:
        print(f"     • {doc.file_name} ({doc.status.value})")

    medical_docs = system.get_documents_by_type(FileType.MEDICAL_REPORT)
    print(f"\n   Medical Reports: {len(medical_docs)}")
    for doc in medical_docs:
        print(f"     • {doc.file_name} ({doc.status.value})\n")

    # Get documents by status
    print("3. DOCUMENTS BY STATUS:")
    print("-" * 80)
    
    pending = system.get_pending_documents()
    print(f"   Pending Verification: {len(pending)}")
    for doc in pending:
        print(f"     • {doc.file_name} (uploaded by {doc.uploaded_by})")

    verified = system.get_verified_documents()
    print(f"\n   Verified Documents: {len(verified)}")
    for doc in verified:
        print(f"     • {doc.file_name} (verified by {doc.verified_by})")

    rejected = system.get_rejected_documents()
    print(f"\n   Rejected Documents: {len(rejected)}")
    for doc in rejected:
        print(f"     • {doc.file_name}")
        print(f"       Reason: {doc.rejection_reason}\n")

    # Get documents for specific entity
    print("4. DOCUMENTS FOR SPECIFIC ENTITY (Policy POL001):")
    print("-" * 80)
    entity_docs = system.get_entity_documents("POL001")
    print(f"   Total: {len(entity_docs)} documents")
    for doc in entity_docs:
        print(f"     • {doc.file_name} ({doc.file_type.value}, {doc.file_size_mb} MB)\n")


def demo_document_storage_analytics(system: PHINSInsuranceSystem):
    """Demonstrate document storage and analytics"""
    print_header("DOCUMENT STORAGE & ANALYTICS")

    stats = system.get_document_storage_stats()
    
    print(f"Total Documents in System: {stats['total_files']}")
    print(f"Total Storage: {stats['total_gb']} GB ({stats['total_mb']} MB)")
    print(f"\nDocument Status Breakdown:")
    print(f"  ✓ Verified Documents: {stats['verified']}")
    print(f"  ⏳ Pending Verification: {stats['pending']}")
    print(f"  ✗ Rejected Documents: {stats['rejected']}")
    print()


def demo_file_download_scenario(system: PHINSInsuranceSystem):
    """Demonstrate file download functionality"""
    print_header("FILE DOWNLOAD - CUSTOMER ACCESSING DOCUMENTS")

    # Customer downloads their policy document
    print("Customer CUST001 downloads documents:\n")
    
    documents = system.get_entity_documents("POL001")
    
    for doc in documents[:2]:  # Show first 2 documents
        retrieved = system.download_document(doc.document_id)
        if retrieved:
            print(f"✓ Downloaded: {retrieved.file_name}")
            print(f"  Type: {retrieved.file_type.value}")
            print(f"  Size: {retrieved.file_size_mb} MB")
            print(f"  Location: {retrieved.file_path}")
            print(f"  Status: {retrieved.status.value}\n")


def demo_archive_management(system: PHINSInsuranceSystem):
    """Demonstrate document archival"""
    print_header("DOCUMENT ARCHIVAL & RETENTION")

    # Archive old documents
    pending = system.get_pending_documents()
    if pending:
        doc_to_archive = pending[0]
        system.archive_document(doc_to_archive.document_id)
        archived_doc = system.get_document(doc_to_archive.document_id)
        
        print(f"✓ Document Archived: {archived_doc.file_name}")
        print(f"  Previous Status: {FileStatus.UPLOADED.value}")
        print(f"  Current Status: {archived_doc.status.value}")
        print(f"  Archive Date: {archived_doc.last_modified.strftime('%Y-%m-%d %H:%M:%S')}\n")


def main():
    """Run complete file management demonstration"""
    print("\n")
    print(" " * 15 + "PHINS FILE MANAGEMENT SYSTEM")
    print(" " * 20 + "File Operations Demonstration")
    print(" " * 15 + "=" * 50)
    
    # Initialize system
    system = PHINSInsuranceSystem()
    
    # Run all demonstrations
    demo_sales_division_files(system)
    demo_underwriting_division_files(system)
    demo_claims_division_files(system)
    demo_accounting_division_files(system)
    demo_customer_portal_files(system)
    demo_file_retrieval_and_organization(system)
    demo_document_storage_analytics(system)
    demo_file_download_scenario(system)
    demo_archive_management(system)
    
    print("\n" + "=" * 80)
    print("  File Management Demonstration Complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
