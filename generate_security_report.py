#!/usr/bin/env python3
"""
Security Report Generator for PHINS Portal
Generates detailed security reports including threat logs, blocked IPs, and statistics
"""

import json
import requests
from datetime import datetime
from collections import Counter

BASE_URL = 'http://localhost:8000'

def generate_security_report(admin_token=None):
    """Generate comprehensive security report"""
    
    print("=" * 80)
    print("PHINS SECURITY REPORT")
    print("=" * 80)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if not admin_token:
        print("⚠️  No admin token provided - attempting to fetch limited data")
        print("   For full report, provide admin authentication token")
        print()
    
    try:
        # Fetch security data
        headers = {}
        if admin_token:
            headers['Authorization'] = f'Bearer {admin_token}'
        
        response = requests.get(f'{BASE_URL}/api/security/threats', 
                               headers=headers, 
                               timeout=10)
        
        if response.status_code != 200:
            print(f"✗ Failed to fetch security data: {response.status_code}")
            if response.status_code == 403:
                print("  Access denied - admin credentials required")
            return False
        
        data = response.json()
        
        # Display statistics
        print("SECURITY STATISTICS")
        print("-" * 80)
        stats = data.get('statistics', {})
        print(f"Total Malicious Attempts: {stats.get('total_malicious_attempts', 0):,}")
        print(f"Blocked IP Addresses:     {stats.get('total_blocked_ips', 0):,}")
        print(f"Permanent Blocks:         {stats.get('permanent_blocks', 0):,}")
        print(f"Active Lockouts:          {stats.get('active_lockouts', 0):,}")
        print()
        
        # Analyze malicious attempts
        attempts = data.get('malicious_attempts', [])
        if attempts:
            print("THREAT ANALYSIS")
            print("-" * 80)
            
            # Count by threat type
            threat_types = Counter(a.get('threat_type', 'unknown') for a in attempts)
            print("\nThreats by Type:")
            for threat_type, count in threat_types.most_common():
                print(f"  {threat_type:25} {count:5,} attempts")
            
            # Count by IP
            print("\nTop 10 Attacking IPs:")
            ips = Counter(a.get('ip', 'unknown') for a in attempts)
            for ip, count in ips.most_common(10):
                print(f"  {ip:20} {count:5,} attempts")
            
            # Recent attempts (last 10)
            print("\nRecent Malicious Attempts:")
            for attempt in attempts[-10:]:
                timestamp = attempt.get('timestamp', '')
                ip = attempt.get('ip', 'unknown')
                threat = attempt.get('threat_type', 'unknown')
                endpoint = attempt.get('endpoint', 'unknown')
                print(f"  [{timestamp}] {ip:15} {threat:20} → {endpoint}")
        else:
            print("✓ No malicious attempts recorded")
        
        print()
        
        # Display blocked IPs
        blocked_ips = data.get('blocked_ips', {})
        if blocked_ips:
            print("BLOCKED IP ADDRESSES")
            print("-" * 80)
            print(f"{'IP Address':20} {'Block Type':15} {'Reason':30} {'Timestamp':20}")
            print("-" * 80)
            for ip, info in list(blocked_ips.items())[-20:]:  # Last 20
                block_type = 'PERMANENT' if info.get('permanent') else 'TEMPORARY'
                reason = info.get('reason', 'Unknown')[:28]
                timestamp = info.get('timestamp', '')[:19]
                print(f"{ip:20} {block_type:15} {reason:30} {timestamp:20}")
        else:
            print("✓ No IP addresses currently blocked")
        
        print()
        
        # Display failed logins
        failed_logins = data.get('failed_logins', {})
        if failed_logins:
            print("FAILED LOGIN ATTEMPTS")
            print("-" * 80)
            print(f"{'IP Address':20} {'Attempts':10} {'Lockout Until':20}")
            print("-" * 80)
            for ip, info in list(failed_logins.items())[-15:]:  # Last 15
                attempts = info.get('attempts', 0)
                lockout = info.get('lockout_until', 0)
                if lockout > datetime.now().timestamp():
                    lockout_str = datetime.fromtimestamp(lockout).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"{ip:20} {attempts:10} {lockout_str:20}")
        
        print()
        print("=" * 80)
        
        # Save to file
        filename = f"security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"✓ Full report saved to: {filename}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("✗ Failed to connect to server")
        print(f"  Is the server running on {BASE_URL}?")
        return False
    except Exception as e:
        print(f"✗ Error generating report: {str(e)}")
        return False

def main():
    """Main entry point"""
    import sys
    
    admin_token = None
    if len(sys.argv) > 1:
        admin_token = sys.argv[1]
    
    if not admin_token:
        print("Usage: python generate_security_report.py [admin_token]")
        print()
    
    success = generate_security_report(admin_token)
    exit(0 if success else 1)

if __name__ == '__main__':
    main()
