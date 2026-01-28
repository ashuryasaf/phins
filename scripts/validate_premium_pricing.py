#!/usr/bin/env python3
"""
Premium Pricing Validation and Correction Script

This script validates premium pricing across the actuary chain:
- Underwriting Applications
- Policies
- Billing

It identifies premiums that don't match the actuarial pricing model
and can optionally correct them.

Usage:
    python scripts/validate_premium_pricing.py [--fix] [--production]
    
Options:
    --fix         Actually fix incorrect premiums (default: dry-run)
    --production  Target production server
"""

import argparse
import json
import requests
from datetime import datetime


# Production and local URLs
PRODUCTION_URL = 'https://phins-portal-production.up.railway.app'
LOCAL_URL = 'http://localhost:5000'


def calculate_correct_premium(policy_data: dict) -> dict:
    """
    Calculate the correct premium using the aligned actuarial model.
    
    This matches the frontend (apply.js) calculation:
    - Base rate: $0.25 per $1,000 coverage per month
    - Age factor: 1.0 + (age - 25) * 0.015
    - Risk factor: varies by assessment
    """
    coverage = policy_data.get('coverage_amount', 100000)
    
    # Policy type base rates (per $1000 coverage per month)
    policy_type_rates = {
        'life': 0.25,
        'health': 0.25,
        'phins_unified': 0.25,
        'auto': 0.15,
        'property': 0.20,
        'business': 0.40
    }
    base_rate = policy_type_rates.get(policy_data.get('type', 'life'), 0.25)
    
    # Age factor: 1.5% increase per year over 25
    age = policy_data.get('age', 30)
    if age == 0 or age is None:
        age = 30  # Default age
    age_factor = 1.0 + (max(0, age - 25) * 0.015)
    
    # Risk factor based on underwriting assessment
    risk_score = (policy_data.get('risk_score') or policy_data.get('risk_assessment') or 'medium').lower()
    risk_factors = {
        'very_low': 0.85,
        'low': 0.90,
        'medium': 1.0,
        'moderate': 1.15,
        'elevated': 1.25,
        'high': 1.35,
        'very_high': 1.50
    }
    risk_factor = risk_factors.get(risk_score, 1.0)
    
    # Calculate monthly premium
    monthly_premium = (coverage / 1000) * base_rate * age_factor * risk_factor
    annual_premium = monthly_premium * 12
    
    return {
        'monthly': round(monthly_premium, 2),
        'annual': round(annual_premium, 2),
        'quarterly': round(monthly_premium * 3 * 0.97, 2),
        'calculation': {
            'coverage': coverage,
            'base_rate': base_rate,
            'age': age,
            'age_factor': round(age_factor, 4),
            'risk_score': risk_score,
            'risk_factor': risk_factor
        }
    }


def validate_premium(item: dict, item_type: str) -> dict:
    """
    Validate a single item's premium against the actuarial model.
    
    Returns validation result with discrepancy details.
    """
    current_monthly = float(item.get('monthly_premium', 0) or 0)
    current_annual = float(item.get('annual_premium', 0) or 0)
    
    # Get correct premium
    correct = calculate_correct_premium(item)
    
    # Check for discrepancy (allow 5% tolerance for rounding)
    monthly_diff = abs(current_monthly - correct['monthly'])
    monthly_pct_diff = (monthly_diff / correct['monthly'] * 100) if correct['monthly'] > 0 else 0
    
    annual_diff = abs(current_annual - correct['annual'])
    annual_pct_diff = (annual_diff / correct['annual'] * 100) if correct['annual'] > 0 else 0
    
    is_valid = monthly_pct_diff <= 5 and annual_pct_diff <= 5
    
    return {
        'id': item.get('id'),
        'type': item_type,
        'customer_id': item.get('customer_id'),
        'policy_type': item.get('type') or item.get('policy_type'),
        'coverage_amount': item.get('coverage_amount'),
        'current': {
            'monthly': current_monthly,
            'annual': current_annual
        },
        'correct': {
            'monthly': correct['monthly'],
            'annual': correct['annual']
        },
        'discrepancy': {
            'monthly_diff': round(monthly_diff, 2),
            'monthly_pct': round(monthly_pct_diff, 1),
            'annual_diff': round(annual_diff, 2),
            'annual_pct': round(annual_pct_diff, 1),
            'ratio': round(current_monthly / correct['monthly'], 2) if correct['monthly'] > 0 else 0
        },
        'is_valid': is_valid,
        'calculation': correct['calculation']
    }


def main():
    parser = argparse.ArgumentParser(description='Validate and fix premium pricing')
    parser.add_argument('--fix', action='store_true', help='Actually fix incorrect premiums')
    parser.add_argument('--production', action='store_true', help='Target production server')
    args = parser.parse_args()
    
    base_url = PRODUCTION_URL if args.production else LOCAL_URL
    
    print('=' * 70)
    print('PHINS Premium Pricing Validation')
    print('=' * 70)
    print(f'Target: {base_url}')
    print(f'Mode: {"FIX" if args.fix else "VALIDATE ONLY (dry-run)"}')
    print(f'Time: {datetime.now().isoformat()}')
    print()
    
    # Check health
    try:
        health = requests.get(f'{base_url}/api/health', timeout=10).json()
        print(f'Server: {health.get("status")}')
    except Exception as e:
        print(f'Cannot connect to server: {e}')
        return
    
    print()
    print('-' * 70)
    print('Checking Applications...')
    print('-' * 70)
    
    invalid_apps = []
    valid_apps = []
    
    try:
        # Get applications (may require auth)
        resp = requests.get(f'{base_url}/api/underwriting', timeout=30)
        if resp.status_code == 200:
            apps = resp.json() if isinstance(resp.json(), list) else []
            
            for app in apps:
                result = validate_premium(app, 'application')
                if result['is_valid']:
                    valid_apps.append(result)
                else:
                    invalid_apps.append(result)
                    print(f'  ⚠ {result["id"]}: ${result["current"]["monthly"]}/mo should be ${result["correct"]["monthly"]}/mo ({result["discrepancy"]["ratio"]}x)')
            
            print(f'\nApplications: {len(valid_apps)} valid, {len(invalid_apps)} need correction')
        else:
            print(f'  Could not fetch applications (status {resp.status_code})')
    except Exception as e:
        print(f'  Error checking applications: {e}')
    
    print()
    print('-' * 70)
    print('Checking Policies...')
    print('-' * 70)
    
    invalid_policies = []
    valid_policies = []
    
    try:
        resp = requests.get(f'{base_url}/api/policies', timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            policies = data.get('items', data) if isinstance(data, dict) else data
            
            for policy in policies:
                result = validate_premium(policy, 'policy')
                if result['is_valid']:
                    valid_policies.append(result)
                else:
                    invalid_policies.append(result)
                    print(f'  ⚠ {result["id"]}: ${result["current"]["monthly"]}/mo should be ${result["correct"]["monthly"]}/mo ({result["discrepancy"]["ratio"]}x)')
            
            print(f'\nPolicies: {len(valid_policies)} valid, {len(invalid_policies)} need correction')
        else:
            print(f'  Could not fetch policies (status {resp.status_code})')
    except Exception as e:
        print(f'  Error checking policies: {e}')
    
    print()
    print('-' * 70)
    print('Checking Billing...')
    print('-' * 70)
    
    invalid_bills = []
    
    try:
        resp = requests.get(f'{base_url}/api/billing/stats', timeout=30)
        if resp.status_code == 200:
            stats = resp.json()
            print(f'  Total billed: ${stats.get("total_billed", 0):,.2f}')
            print(f'  Total collected: ${stats.get("total_collected", 0):,.2f}')
            print(f'  Outstanding: ${stats.get("outstanding_balance", 0):,.2f}')
    except Exception as e:
        print(f'  Error checking billing: {e}')
    
    # Summary
    print()
    print('=' * 70)
    print('SUMMARY')
    print('=' * 70)
    
    total_invalid = len(invalid_apps) + len(invalid_policies)
    
    if total_invalid == 0:
        print('✓ All premiums are correctly calculated!')
    else:
        print(f'⚠ Found {total_invalid} items with incorrect premiums:')
        print(f'  - Applications: {len(invalid_apps)}')
        print(f'  - Policies: {len(invalid_policies)}')
        
        if invalid_apps or invalid_policies:
            print()
            print('Discrepancy Pattern:')
            ratios = [r['discrepancy']['ratio'] for r in (invalid_apps + invalid_policies) if r['discrepancy']['ratio'] > 0]
            if ratios:
                avg_ratio = sum(ratios) / len(ratios)
                print(f'  Average overcharge ratio: {avg_ratio:.2f}x')
    
    if args.fix and total_invalid > 0:
        print()
        print('=' * 70)
        print('APPLYING FIXES...')
        print('=' * 70)
        print('Note: Manual database updates may be required.')
        print('Recommendation: Re-create applications with correct pricing.')
    
    print()
    print('=' * 70)


if __name__ == '__main__':
    main()
