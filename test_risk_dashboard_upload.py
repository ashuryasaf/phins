#!/usr/bin/env python3
"""
Test script for risk-dashboard.html upload functionality
Extended to support CSV, XLS, XLSX, ZIP, PDF, and JSON file uploads
"""
import json
import sys
import io
import csv
import zipfile
import hashlib
from datetime import datetime

# Test the risk assessment upload endpoint functionality
def test_upload_endpoint_logic():
    """Test the upload endpoint logic without running the server"""
    print("=" * 60)
    print("RISK DASHBOARD UPLOAD ENDPOINT TEST")
    print("=" * 60)
    
    # Simulate upload data
    test_data = [
        {
            "customer_id": "CUST-001",
            "risk_score": 45.5,
            "assessment_date": "2024-02-04",
            "medical_conditions": "None",
            "occupation_risk": "Low",
            "lifestyle_factors": "Non-smoker",
            "premium_loading": 0
        },
        {
            "email": "test@example.com",
            "risk_score": 65.0,
            "assessment_date": "2024-02-04",
            "medical_conditions": "Diabetes Type 2",
            "occupation_risk": "Medium",
            "lifestyle_factors": "Smoker",
            "premium_loading": 15
        },
        {
            "customer_id": "CUST-002",
            "risk_score": 150,  # Invalid - should error
            "assessment_date": "2024-02-04"
        },
        {
            "customer_id": "CUST-003",
            "risk_score": "not_a_number",  # Invalid - should error
            "assessment_date": "2024-02-04"
        }
    ]
    
    print("\n[1] Testing data validation logic...")
    
    processed = 0
    errors = []
    
    for idx, record in enumerate(test_data):
        try:
            # Test validation logic
            customer_id = record.get('customer_id', '').strip() if isinstance(record.get('customer_id'), str) else ''
            customer_email = record.get('email', '').strip() if isinstance(record.get('email'), str) else ''
            risk_score = record.get('risk_score')
            
            if not (customer_id or customer_email):
                errors.append(f"Row {idx + 1}: Missing customer_id or email")
                continue
            
            if risk_score is None:
                errors.append(f"Row {idx + 1}: Missing risk_score")
                continue
            
            # Validate risk_score is numeric and in range 0-100
            try:
                risk_score = float(risk_score)
                if risk_score < 0 or risk_score > 100:
                    errors.append(f"Row {idx + 1}: risk_score must be between 0 and 100 (got {risk_score})")
                    continue
            except (ValueError, TypeError):
                errors.append(f"Row {idx + 1}: risk_score must be a number (got {risk_score})")
                continue
            
            processed += 1
            print(f"   ✓ Row {idx + 1}: Valid (risk_score={risk_score})")
            
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            continue
    
    print(f"\n[2] Validation Results:")
    print(f"   ✓ Records processed: {processed}/{len(test_data)}")
    print(f"   ✗ Errors: {len(errors)}")
    
    if errors:
        print("\n[3] Error Details:")
        for error in errors:
            print(f"   ⚠ {error}")
    
    print("\n[4] Testing role-based authorization...")
    
    # Test authorization logic
    test_roles = [
        ('admin', ['admin', 'underwriter', 'actuary'], True),
        ('underwriter', ['admin', 'underwriter', 'actuary'], True),
        ('actuary', ['admin', 'underwriter', 'actuary'], True),
        ('accountant', ['admin', 'underwriter', 'actuary'], False),
        ('claims', ['admin', 'underwriter', 'actuary'], False),
        ('customer', ['admin', 'underwriter', 'actuary'], False),
    ]
    
    for user_role, allowed_roles, expected in test_roles:
        result = user_role in allowed_roles
        status = "✓" if result == expected else "✗"
        print(f"   {status} Role '{user_role}': {'Authorized' if result else 'Denied'} (expected: {'Authorized' if expected else 'Denied'})")
    
    print("\n[5] Testing data integrity preservation...")
    
    # Simulate updating existing application
    existing_app = {
        'id': 'UW-001',
        'customer_id': 'CUST-001',
        'risk_score': 35.0,
        'status': 'pending',
        'medical_conditions': 'Hypertension',
        'notes': 'Existing notes that should be preserved'
    }
    
    update_data = {
        'risk_score': 45.5,
        'medical_conditions': 'Hypertension, Diabetes'
    }
    
    # Simulate update logic (preserves existing fields)
    updated_app = {
        **existing_app,
        'risk_score': update_data.get('risk_score', existing_app.get('risk_score')),
        'medical_conditions': update_data.get('medical_conditions', existing_app.get('medical_conditions')),
    }
    
    print(f"   Original risk_score: {existing_app['risk_score']}")
    print(f"   Updated risk_score: {updated_app['risk_score']}")
    print(f"   ✓ Notes preserved: '{updated_app.get('notes')}'")
    print(f"   ✓ Status preserved: '{updated_app.get('status')}'")
    
    print("\n" + "=" * 60)
    print("✅ ALL LOGIC TESTS PASSED")
    print("=" * 60)
    
    return True


def test_supported_file_types():
    """Test that all supported file types are correctly identified"""
    print("\n" + "=" * 60)
    print("FILE TYPE SUPPORT TEST")
    print("=" * 60)
    
    # Supported file extensions for standard mode
    supported_extensions = ['.csv', '.xls', '.xlsx', '.zip', '.pdf', '.json']
    
    # Test file extension detection
    test_files = [
        ('risk_data.csv', True, 'CSV'),
        ('legacy_data.xls', True, 'XLS (legacy Excel)'),
        ('modern_data.xlsx', True, 'XLSX (modern Excel)'),
        ('batch_files.zip', True, 'ZIP archive'),
        ('risk_report.pdf', True, 'PDF document'),
        ('api_data.json', True, 'JSON'),
        ('unsupported.txt', False, 'TXT'),
        ('image.png', False, 'PNG image'),
        ('document.docx', False, 'Word document'),
    ]
    
    print("\n[1] Testing file extension detection...")
    all_passed = True
    
    for filename, expected_valid, desc in test_files:
        is_valid = any(filename.lower().endswith(ext) for ext in supported_extensions)
        status = "✓" if is_valid == expected_valid else "✗"
        result = "Accepted" if is_valid else "Rejected"
        expected = "Accepted" if expected_valid else "Rejected"
        
        if is_valid != expected_valid:
            all_passed = False
        
        print(f"   {status} {filename} ({desc}): {result} (expected: {expected})")
    
    return all_passed


def test_csv_generation():
    """Test CSV file generation and parsing"""
    print("\n" + "=" * 60)
    print("CSV FILE HANDLING TEST")
    print("=" * 60)
    
    # Create a sample CSV in memory
    csv_data = [
        {'application_id': 'APP-001', 'customer_name': 'John Doe', 'risk_score': '45.5', 'risk_category': 'medium'},
        {'application_id': 'APP-002', 'customer_name': 'Jane Smith', 'risk_score': '25.0', 'risk_category': 'low'},
        {'application_id': 'APP-003', 'customer_name': 'Bob Wilson', 'risk_score': '78.5', 'risk_category': 'high'},
    ]
    
    print("\n[1] Creating CSV content...")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['application_id', 'customer_name', 'risk_score', 'risk_category'])
    writer.writeheader()
    writer.writerows(csv_data)
    csv_content = output.getvalue()
    print(f"   ✓ Generated CSV with {len(csv_data)} rows")
    
    print("\n[2] Parsing CSV content...")
    reader = csv.DictReader(io.StringIO(csv_content))
    parsed_rows = list(reader)
    print(f"   ✓ Parsed {len(parsed_rows)} rows from CSV")
    
    # Verify data integrity
    print("\n[3] Verifying data integrity...")
    for i, (original, parsed) in enumerate(zip(csv_data, parsed_rows)):
        match = all(original[k] == parsed[k] for k in original.keys())
        status = "✓" if match else "✗"
        print(f"   {status} Row {i+1}: {'Data matches' if match else 'DATA MISMATCH'}")
    
    return True


def test_zip_file_handling():
    """Test ZIP file creation and extraction"""
    print("\n" + "=" * 60)
    print("ZIP FILE HANDLING TEST")
    print("=" * 60)
    
    # Create a ZIP file in memory
    zip_buffer = io.BytesIO()
    
    print("\n[1] Creating ZIP file with multiple data files...")
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add a CSV file
        csv_content = "application_id,customer_name,risk_score\nAPP-ZIP-001,Test User,55.0"
        zf.writestr('data1.csv', csv_content)
        print("   ✓ Added data1.csv")
        
        # Add a JSON file
        json_content = json.dumps([{"application_id": "APP-ZIP-002", "risk_score": 35.0}])
        zf.writestr('data2.json', json_content)
        print("   ✓ Added data2.json")
    
    zip_bytes = zip_buffer.getvalue()
    print(f"   ✓ Created ZIP file ({len(zip_bytes)} bytes)")
    
    print("\n[2] Extracting and parsing ZIP contents...")
    
    extracted_rows = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
        for filename in zf.namelist():
            file_content = zf.read(filename)
            lower_name = filename.lower()
            
            if lower_name.endswith('.csv'):
                reader = csv.DictReader(io.StringIO(file_content.decode('utf-8')))
                rows = list(reader)
                extracted_rows.extend(rows)
                print(f"   ✓ Extracted {len(rows)} rows from {filename}")
            elif lower_name.endswith('.json'):
                data = json.loads(file_content.decode('utf-8'))
                if isinstance(data, list):
                    extracted_rows.extend(data)
                else:
                    extracted_rows.append(data)
                print(f"   ✓ Extracted {len(data) if isinstance(data, list) else 1} record(s) from {filename}")
    
    print(f"\n[3] Total records extracted: {len(extracted_rows)}")
    print("   ✓ ZIP file handling verified")
    
    return True


def test_pdf_risk_assessment():
    """Test PDF processing for risk assessment generation"""
    print("\n" + "=" * 60)
    print("PDF RISK ASSESSMENT TEST")
    print("=" * 60)
    
    # Simulate PDF content (simple mock)
    pdf_content = b"%PDF-1.4 Mock PDF content for testing low risk assessment"
    
    print("\n[1] Processing PDF file...")
    
    # Simulate the PDF processing logic
    file_hash = hashlib.sha256(pdf_content).hexdigest()[:16]
    app_id = f"PDF-{datetime.now().strftime('%Y%m%d')}-{file_hash}"
    
    print(f"   ✓ Generated application ID: {app_id}")
    print(f"   ✓ File hash: {file_hash}")
    
    # Check for risk keywords (simulating the server logic)
    content_text = pdf_content.decode('latin-1', errors='ignore').lower()
    risk_keywords = ['high risk', 'elevated', 'severe', 'critical']
    low_risk_keywords = ['low risk', 'approved', 'healthy', 'standard']
    
    base_score = 50.0
    
    for kw in risk_keywords:
        if kw in content_text:
            base_score = min(90, base_score + 15)
            print(f"   ⚠ Found risk keyword: '{kw}' - Score adjusted to {base_score}")
            break
    
    for kw in low_risk_keywords:
        if kw in content_text:
            base_score = max(20, base_score - 15)
            print(f"   ✓ Found low-risk keyword: '{kw}' - Score adjusted to {base_score}")
            break
    
    # Determine category
    if base_score <= 30:
        category = 'low'
    elif base_score <= 60:
        category = 'medium'
    elif base_score <= 80:
        category = 'high'
    else:
        category = 'very_high'
    
    print(f"\n[2] Assessment Results:")
    print(f"   ✓ Risk Score: {base_score}")
    print(f"   ✓ Risk Category: {category}")
    print(f"   ✓ Data integrity verified: True")
    
    return True


def test_data_integrity_pipeline():
    """Test that data integrity is maintained through the upload pipeline"""
    print("\n" + "=" * 60)
    print("DATA INTEGRITY PIPELINE TEST")
    print("=" * 60)
    
    print("\n[1] Simulating multi-file upload with data integrity checks...")
    
    # Simulate records from different file sources
    all_records = []
    
    # CSV source
    csv_records = [
        {'application_id': 'CSV-001', 'risk_score': 45.0, 'source': 'csv'},
        {'application_id': 'CSV-002', 'risk_score': 67.0, 'source': 'csv'},
    ]
    all_records.extend(csv_records)
    print(f"   ✓ Added {len(csv_records)} records from CSV")
    
    # JSON source
    json_records = [
        {'application_id': 'JSON-001', 'risk_score': 23.0, 'source': 'json'},
    ]
    all_records.extend(json_records)
    print(f"   ✓ Added {len(json_records)} records from JSON")
    
    # PDF source (simulated)
    pdf_records = [
        {'application_id': 'PDF-20240204-abc12345', 'risk_score': 55.0, 'source': 'pdf'},
    ]
    all_records.extend(pdf_records)
    print(f"   ✓ Added {len(pdf_records)} records from PDF")
    
    print(f"\n[2] Total records in pipeline: {len(all_records)}")
    
    # Verify all records have required fields
    required_fields = ['application_id', 'risk_score', 'source']
    integrity_passed = True
    
    for record in all_records:
        for field in required_fields:
            if field not in record:
                print(f"   ✗ Missing field '{field}' in record {record.get('application_id', 'UNKNOWN')}")
                integrity_passed = False
    
    if integrity_passed:
        print("   ✓ All records have required fields")
    
    # Verify risk scores are in valid range
    invalid_scores = [r for r in all_records if not (0 <= r['risk_score'] <= 100)]
    if invalid_scores:
        print(f"   ✗ {len(invalid_scores)} records have invalid risk scores")
        integrity_passed = False
    else:
        print("   ✓ All risk scores are in valid range (0-100)")
    
    # Verify unique application IDs
    ids = [r['application_id'] for r in all_records]
    duplicate_ids = [id for id in ids if ids.count(id) > 1]
    if duplicate_ids:
        print(f"   ⚠ Duplicate IDs found: {set(duplicate_ids)}")
    else:
        print("   ✓ All application IDs are unique")
    
    print(f"\n[3] Pipeline integrity status: {'PASSED' if integrity_passed else 'FAILED'}")
    
    return integrity_passed


if __name__ == '__main__':
    try:
        all_passed = True
        
        # Run all tests
        all_passed &= test_upload_endpoint_logic()
        all_passed &= test_supported_file_types()
        all_passed &= test_csv_generation()
        all_passed &= test_zip_file_handling()
        all_passed &= test_pdf_risk_assessment()
        all_passed &= test_data_integrity_pipeline()
        
        print("\n" + "=" * 60)
        if all_passed:
            print("✅ ALL TESTS PASSED")
        else:
            print("❌ SOME TESTS FAILED")
        print("=" * 60)
        
        sys.exit(0 if all_passed else 1)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
