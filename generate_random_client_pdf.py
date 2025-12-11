#!/usr/bin/env python3
"""Generate a PDF report with randomized client information (demo).

This is a self-contained script that uses ReportLab to render a PDF
containing client contact info, policies, bills and claims with
randomized values for demo or testing purposes.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import mm
from datetime import datetime, timedelta
import random
import uuid

OUTPUT = "random_client_report.pdf"


def currency(v: float) -> str:
    return f"${v:,.2f}"


def random_name():
    first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Jamie", "Dana", "Cameron"]
    last_names = ["Smith", "Johnson", "Lee", "Garcia", "Brown", "Davis", "Martinez", "Lopez", "Wilson", "Clark"]
    return f"{random.choice(first_names)} {random.choice(last_names)}"


def make_client():
    cid = f"CUST-{uuid.uuid4().hex[:8].upper()}"
    name = random_name()
    email = f"{name.split()[0].lower()}.{name.split()[1].lower()}@example.com"
    phone = f"+1-{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}"
    addr = f"{random.randint(10,999)} {random.choice(['Main St','Oak Ave','Maple Rd','Pine Ln','Elm St'])}, {random.choice(['Springfield','Riverview','Lakeside','Fairview'])}"
    return {
        'customer_id': cid,
        'name': name,
        'email': email,
        'phone': phone,
        'address': addr,
    }


def make_policies(customer_id, count=2):
    policies = []
    today = datetime.today().date()
    for i in range(count):
        pid = f"POL-{uuid.uuid4().hex[:6].upper()}"
        start = today - timedelta(days=random.randint(0, 400))
        end = start + timedelta(days=365)
        premium = round(random.uniform(200.0, 5000.0), 2)
        coverage = round(random.uniform(10000.0, 1000000.0), 2)
        policies.append({
            'policy_id': pid,
            'policy_type': random.choice(['AUTO','HOME','LIFE','HEALTH','LIABILITY']),
            'start_date': start,
            'end_date': end,
            'premium': premium,
            'coverage': coverage,
        })
    return policies


def make_bills(policies, months=3):
    bills = []
    for p in policies:
        for m in range(months):
            bill_date = p['start_date'] + timedelta(days=30 * m)
            amount = round(p['premium'] / 12.0 if random.random() < 0.5 else p['premium'], 2)
            due = bill_date + timedelta(days=30)
            status = random.choice(['OUTSTANDING','PAID','PARTIAL'])
            bills.append({
                'bill_id': f"BILL-{uuid.uuid4().hex[:6].upper()}",
                'policy_id': p['policy_id'],
                'bill_date': bill_date,
                'due_date': due,
                'amount': amount,
                'status': status,
            })
    return bills


def make_claims(policies, max_claims=2):
    claims = []
    for p in policies:
        for _ in range(random.randint(0, max_claims)):
            inc_date = p['start_date'] + timedelta(days=random.randint(1, 300))
            amt = round(random.uniform(500.0, p['coverage'] * 0.2), 2)
            status = random.choice(['PENDING','UNDER_REVIEW','APPROVED','PAID','REJECTED'])
            claims.append({
                'claim_id': f"CLM-{uuid.uuid4().hex[:6].upper()}",
                'policy_id': p['policy_id'],
                'incident_date': inc_date,
                'claim_amount': amt,
                'status': status,
            })
    return claims


def build_pdf(client, policies, bills, claims, output=OUTPUT):
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("PHINS - Random Client Report", styles['Title']))
    story.append(Spacer(1, 8))

    # Client block
    story.append(Paragraph(f"<b>Client:</b> {client['name']}", styles['Heading3']))
    story.append(Paragraph(f"<b>Customer ID:</b> {client['customer_id']}", styles['Normal']))
    story.append(Paragraph(f"<b>Email:</b> {client['email']}", styles['Normal']))
    story.append(Paragraph(f"<b>Phone:</b> {client['phone']}", styles['Normal']))
    story.append(Paragraph(f"<b>Address:</b> {client['address']}", styles['Normal']))
    story.append(Spacer(1, 10))

    # Policies table
    story.append(Paragraph("<b>Policies</b>", styles['Heading2']))
    data = [["Policy ID", "Type", "Start", "End", "Premium", "Coverage"]]
    for p in policies:
        data.append([
            p['policy_id'],
            p['policy_type'],
            p['start_date'].isoformat(),
            p['end_date'].isoformat(),
            currency(p['premium']),
            currency(p['coverage'])
        ])

    t = Table(data, hAlign='LEFT', colWidths=[50*mm, 25*mm, 28*mm, 28*mm, 30*mm, 35*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (4, 0), (5, -1), 'RIGHT'),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Bills table
    story.append(Paragraph("<b>Bills (Recent)</b>", styles['Heading2']))
    data = [["Bill ID", "Policy", "Bill Date", "Due Date", "Amount", "Status"]]
    for b in sorted(bills, key=lambda x: x['bill_date'], reverse=True)[:10]:
        data.append([
            b['bill_id'],
            b['policy_id'],
            b['bill_date'].isoformat(),
            b['due_date'].isoformat(),
            currency(b['amount']),
            b['status']
        ])

    t = Table(data, hAlign='LEFT', colWidths=[50*mm, 35*mm, 30*mm, 30*mm, 30*mm, 25*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Claims table
    story.append(Paragraph("<b>Claims (Recent)</b>", styles['Heading2']))
    data = [["Claim ID", "Policy", "Incident", "Amount", "Status"]]
    for c in sorted(claims, key=lambda x: x['incident_date'], reverse=True)[:10]:
        data.append([
            c['claim_id'],
            c['policy_id'],
            c['incident_date'].isoformat(),
            currency(c['claim_amount']),
            c['status']
        ])

    t = Table(data, hAlign='LEFT', colWidths=[60*mm, 45*mm, 35*mm, 30*mm, 30*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Summary
    story.append(Paragraph("<b>Summary</b>", styles['Heading2']))
    total_prem = sum(p['premium'] for p in policies)
    total_billed = sum(b['amount'] for b in bills)
    total_claims = sum(c['claim_amount'] for c in claims)
    story.append(Paragraph(f"Total Policies: <b>{len(policies)}</b>", styles['Normal']))
    story.append(Paragraph(f"Estimated Annual Premium (sum): <b>{currency(total_prem)}</b>", styles['Normal']))
    story.append(Paragraph(f"Recent Billed Amount (sum): <b>{currency(total_billed)}</b>", styles['Normal']))
    story.append(Paragraph(f"Recent Claim Amount (sum): <b>{currency(total_claims)}</b>", styles['Normal']))
    story.append(Spacer(1, 12))

    story.append(Paragraph("This report contains randomized demo data for testing and presentation purposes.", styles['Italic']))

    doc.build(story)
    return output


def main():
    client = make_client()
    policies = make_policies(client['customer_id'], count=random.randint(1, 3))
    bills = make_bills(policies, months=3)
    claims = make_claims(policies, max_claims=2)

    out = build_pdf(client, policies, bills, claims)
    print(f"Generated: {out} (Client: {client['customer_id']} - {client['name']})")


if __name__ == '__main__':
    main()
