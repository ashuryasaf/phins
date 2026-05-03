"""PHINS Security Package.

Provides layered defence modules:

- ``auth_tokens`` — HMAC-signed bearer tokens (v2)
- ``headers`` — HTTP security headers
- ``vault`` — Fernet encryption helpers
- ``secrets_policy`` — startup secret audit
- ``network`` — outbound URL validation
- ``firewall`` — IP-layer firewall with adaptive threat scoring
- ``file_scanner`` — file upload virus/malware scanning
- ``request_sanitizer`` — deep request body sanitisation and CSRF
- ``intrusion_detector`` — security event bus and correlation engine
"""
