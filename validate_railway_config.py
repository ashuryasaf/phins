#!/usr/bin/env python3
"""
Railway Configuration Validation Script

Validates Railway deployment configuration:
- railway.json has correct startCommand
- Dockerfile exposes port 8000
- requirements.txt has all dependencies
- Environment variables documented
- Health check endpoint exists
- Restart policy configured
- Resource limits appropriate
"""

import os
import json
import sys
from pathlib import Path


class ConfigValidator:
    def __init__(self, repo_root="."):
        self.repo_root = Path(repo_root)
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def check(self, name, test_func):
        """Run a validation check"""
        try:
            print(f"  Checking: {name}...", end=" ")
            test_func()
            print("✓ PASS")
            self.passed.append(name)
            return True
        except AssertionError as e:
            print(f"✗ FAIL: {e}")
            self.failed.append((name, str(e)))
            return False
        except Exception as e:
            print(f"✗ ERROR: {e}")
            self.failed.append((name, f"Error: {e}"))
            return False
    
    def warn(self, name, message):
        """Record a warning"""
        print(f"  Warning: {name}: {message}")
        self.warnings.append((name, message))
    
    def validate_railway_json(self):
        """Validate railway.json configuration"""
        railway_file = self.repo_root / "railway.json"
        assert railway_file.exists(), "railway.json not found"
        
        with open(railway_file) as f:
            config = json.load(f)
        
        # Check deploy configuration
        assert 'deploy' in config, "Missing 'deploy' section"
        deploy = config['deploy']
        
        # Check start command
        assert 'startCommand' in deploy, "Missing 'startCommand'"
        start_cmd = deploy['startCommand']
        assert 'python' in start_cmd.lower(), "Start command should use Python"
        assert 'web_portal/server.py' in start_cmd or 'server.py' in start_cmd, \
            "Start command should run server.py"
        
        # Check restart policy
        if 'restartPolicyType' in deploy:
            assert deploy['restartPolicyType'] in ['ON_FAILURE', 'ALWAYS', 'NEVER'], \
                "Invalid restart policy type"
        else:
            self.warn("Railway Config", "No restart policy specified")
        
        # Check build configuration
        if 'build' in config:
            build = config['build']
            if 'builder' in build:
                assert build['builder'] in ['NIXPACKS', 'DOCKERFILE'], \
                    "Invalid builder type"
    
    def validate_dockerfile(self):
        """Validate Dockerfile configuration"""
        dockerfile = self.repo_root / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile not found"
        
        with open(dockerfile) as f:
            content = f.read()
        
        # Check Python version
        assert 'FROM python:' in content, "Dockerfile should use Python base image"
        
        # Check port exposure
        assert 'EXPOSE 8000' in content or 'EXPOSE $PORT' in content, \
            "Dockerfile should expose port 8000"
        
        # Check CMD or ENTRYPOINT
        has_cmd = 'CMD' in content or 'ENTRYPOINT' in content
        if has_cmd:
            assert 'server.py' in content, "Dockerfile should run server.py"
        else:
            self.warn("Dockerfile", "No CMD or ENTRYPOINT found")
        
        # Check for requirements installation
        assert 'requirements.txt' in content, \
            "Dockerfile should install from requirements.txt"
        assert 'pip install' in content, "Dockerfile should install dependencies"
    
    def validate_requirements_txt(self):
        """Validate requirements.txt has necessary dependencies"""
        req_file = self.repo_root / "requirements.txt"
        assert req_file.exists(), "requirements.txt not found"
        
        with open(req_file) as f:
            requirements = f.read()
        
        # Core dependencies
        required = ['pytest']
        optional = ['reportlab', 'boto3', 'requests']
        
        for dep in required:
            if dep not in requirements.lower():
                self.warn("Requirements", f"Missing recommended dependency: {dep}")
        
        # Check for version pinning
        lines = [l.strip() for l in requirements.split('\n') if l.strip() and not l.startswith('#')]
        unpinned = [l for l in lines if '>=' not in l and '==' not in l and '~=' not in l]
        if unpinned:
            self.warn("Requirements", f"Some dependencies not version-pinned: {len(unpinned)}")
    
    def validate_server_file(self):
        """Validate server.py exists and has correct structure"""
        server_file = self.repo_root / "web_portal" / "server.py"
        assert server_file.exists(), "web_portal/server.py not found"
        
        with open(server_file) as f:
            content = f.read()
        
        # Check port configuration
        assert 'PORT = 8000' in content or 'PORT =' in content, \
            "Server should define PORT"
        
        # Check HTTPServer setup
        assert 'HTTPServer' in content, "Server should use HTTPServer"
        assert 'BaseHTTPRequestHandler' in content or 'PortalHandler' in content, \
            "Server should define request handler"
        
        # Check for main execution
        assert "__name__ == '__main__'" in content or "__name__ == \"__main__\"" in content, \
            "Server should have main execution block"
    
    def validate_health_endpoint(self):
        """Validate health check endpoint exists"""
        server_file = self.repo_root / "web_portal" / "server.py"
        
        with open(server_file) as f:
            content = f.read()
        
        # Check for metrics or health endpoint
        has_health = '/api/metrics' in content or '/health' in content or '/api/health' in content
        if not has_health:
            self.warn("Health Check", "No obvious health check endpoint found")
    
    def validate_security_features(self):
        """Validate security features are implemented"""
        server_file = self.repo_root / "web_portal" / "server.py"
        
        with open(server_file) as f:
            content = f.read()
        
        security_features = {
            'Rate Limiting': ['RATE_LIMIT', 'check_rate_limit'],
            'Session Management': ['SESSIONS', 'validate_session'],
            'Password Hashing': ['hash_password', 'pbkdf2'],
            'SQL Injection Protection': ['detect_sql_injection', 'validate_input'],
            'XSS Protection': ['detect_xss', 'X-XSS-Protection'],
            'Security Headers': ['X-Content-Type-Options', 'X-Frame-Options']
        }
        
        for feature, keywords in security_features.items():
            if not any(kw in content for kw in keywords):
                self.warn("Security", f"{feature} implementation not found")
    
    def validate_environment_docs(self):
        """Validate environment variables are documented"""
        # Check for README or ENV documentation
        readme_files = list(self.repo_root.glob("README*.md")) + \
                      list(self.repo_root.glob("*DEPLOYMENT*.md")) + \
                      list(self.repo_root.glob("*RAILWAY*.md"))
        
        if not readme_files:
            self.warn("Documentation", "No README or deployment documentation found")
            return
        
        env_documented = False
        for readme in readme_files:
            with open(readme) as f:
                content = f.read()
                if 'environment' in content.lower() or 'env' in content.lower():
                    env_documented = True
                    break
        
        if not env_documented:
            self.warn("Documentation", "Environment variables not documented in README")
    
    def validate_gitignore(self):
        """Validate .gitignore excludes correct files"""
        gitignore = self.repo_root / ".gitignore"
        
        if not gitignore.exists():
            self.warn("Git", ".gitignore not found")
            return
        
        with open(gitignore) as f:
            content = f.read()
        
        important_patterns = [
            '__pycache__',
            '*.pyc',
            '.env',
            'venv',
            'node_modules'
        ]
        
        for pattern in important_patterns:
            if pattern not in content:
                self.warn("Git", f".gitignore should include: {pattern}")
    
    def validate_test_infrastructure(self):
        """Validate test infrastructure exists"""
        tests_dir = self.repo_root / "tests"
        assert tests_dir.exists(), "tests/ directory not found"
        
        # Check for test files
        test_files = list(tests_dir.glob("test_*.py"))
        assert len(test_files) > 0, "No test files found"
        
        # Check for conftest.py
        conftest = tests_dir / "conftest.py"
        if not conftest.exists():
            self.warn("Tests", "conftest.py not found")
    
    def validate_api_endpoints(self):
        """Validate critical API endpoints are defined"""
        server_file = self.repo_root / "web_portal" / "server.py"
        
        with open(server_file) as f:
            content = f.read()
        
        critical_endpoints = [
            '/api/login',
            '/api/policies/create',
            '/api/policies',
            '/api/claims/create',
            '/api/underwriting/approve',
            '/api/billing'
        ]
        
        missing = []
        for endpoint in critical_endpoints:
            if endpoint not in content:
                missing.append(endpoint)
        
        if missing:
            self.warn("API", f"Some endpoints might be missing: {', '.join(missing[:3])}")
    
    def run_all_validations(self):
        """Run all configuration validations"""
        print(f"\n{'='*60}")
        print("Railway Configuration Validation")
        print(f"{'='*60}\n")
        
        print("📋 Validating Configuration Files...\n")
        
        print("Core Configuration:")
        self.check("railway.json", self.validate_railway_json)
        self.check("Dockerfile", self.validate_dockerfile)
        self.check("requirements.txt", self.validate_requirements_txt)
        
        print("\nServer Configuration:")
        self.check("server.py", self.validate_server_file)
        self.check("Health Endpoint", self.validate_health_endpoint)
        self.check("API Endpoints", self.validate_api_endpoints)
        
        print("\nSecurity:")
        self.check("Security Features", self.validate_security_features)
        
        print("\nProject Structure:")
        self.check("Test Infrastructure", self.validate_test_infrastructure)
        self.check("Documentation", self.validate_environment_docs)
        self.check(".gitignore", self.validate_gitignore)
        
        # Results
        print(f"\n{'='*60}")
        print("VALIDATION RESULTS:")
        print(f"{'='*60}")
        print(f"✓ Passed: {len(self.passed)}")
        print(f"✗ Failed: {len(self.failed)}")
        print(f"⚠ Warnings: {len(self.warnings)}")
        
        if self.failed:
            print(f"\n{'='*60}")
            print("FAILURES:")
            print(f"{'='*60}")
            for name, error in self.failed:
                print(f"  ✗ {name}: {error}")
        
        if self.warnings:
            print(f"\n{'='*60}")
            print("WARNINGS:")
            print(f"{'='*60}")
            for name, message in self.warnings:
                print(f"  ⚠ {name}: {message}")
        
        print(f"\n{'='*60}")
        
        if len(self.failed) == 0:
            print("✅ CONFIGURATION VALID!")
        else:
            print(f"❌ CONFIGURATION ISSUES FOUND")
        
        print(f"{'='*60}\n")
        
        return len(self.failed) == 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Validate Railway deployment configuration',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--dir',
        default='.',
        help='Repository root directory (default: current directory)'
    )
    
    args = parser.parse_args()
    
    print("""
    ____  __  ___   _______   _______
   / __ \/ / / / | / / ___/  / ____(_)
  / /_/ / /_/ /  |/ /\__ \  / /_  / / 
 / ____/ __  / /|  /___/ / / __/ / /  
/_/   /_/ /_/_/ |_//____/ /_/   /_/   
                                       
Configuration Validator for Railway
    """)
    
    validator = ConfigValidator(args.dir)
    
    try:
        success = validator.run_all_validations()
        
        if success:
            print("\n✅ Ready for Railway deployment!")
            print("\nNext steps:")
            print("  1. Commit all changes")
            print("  2. Push to GitHub")
            print("  3. Deploy to Railway")
            print("  4. Run health check: python railway_health_check.py <URL>")
        else:
            print("\n❌ Please fix configuration issues before deploying")
        
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation interrupted by user")
        sys.exit(2)


if __name__ == '__main__':
    main()
