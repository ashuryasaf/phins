"""
Translation Validation System for PHINS
Enforces that all user-facing content is properly translated across all 20 languages
"""

import re
import ast
from typing import List, Dict, Set, Tuple
from pathlib import Path
from i18n import Language, TranslationManager

class TranslationValidator:
    """Validates that all strings are properly internationalized"""
    
    # Patterns that indicate hardcoded user-facing strings
    HARDCODED_PATTERNS = [
        r'print\(["\']([A-Z][^"\']{10,})["\']',  # Print statements with sentences
        r'return\s*["\']([A-Z][a-z]{3,}\s+[a-z]+.*?)["\']',  # Return strings
        r'"message":\s*["\']([^"\']+)["\']',  # Message fields in dicts
        r'"title":\s*["\']([^"\']+)["\']',  # Title fields
        r'"error":\s*["\']([^"\']+)["\']',  # Error fields
        r'"label":\s*["\']([^"\']+)["\']',  # Label fields
        r'<h[1-6]>([^<]+)</h[1-6]>',  # HTML headings
        r'<p>([^<]{20,})</p>',  # HTML paragraphs with substantial content
        r'<button[^>]*>([^<]+)</button>',  # Button text
        r'<title>([^<]+)</title>',  # Page titles
        r'placeholder=["\']([^"\']+)["\']',  # Form placeholders
    ]
    
    # Files/folders to exclude from validation
    EXCLUDED_PATHS = [
        '__pycache__',
        '.pytest_cache',
        '.git',
        'tests/',
        'conftest.py',
        'translation_validator.py',  # Self
        '.venv/',
        'venv/',
        '.mypy_cache',
        'node_modules/',
        'demo',  # Demo files can have hardcoded examples
    ]
    
    # Allowed exceptions (technical terms, variable names, etc.)
    ALLOWED_EXCEPTIONS = {
        'PHINS', 'PHI', 'API', 'URL', 'ID', 'UUID', 'JSON', 'XML', 'HTTP', 'HTTPS',
        'GET', 'POST', 'PUT', 'DELETE', 'PATCH',
        'True', 'False', 'None', 'OK', 'Error',
    }
    
    def __init__(self, project_root: str = "/workspaces/phins"):
        self.project_root = Path(project_root)
        self.translator = TranslationManager()
        self.violations: List[Dict] = []
        self.missing_translations: List[Dict] = []
        
    def validate_project(self) -> Dict:
        """Validate entire project for translation compliance"""
        print("🌍 PHINS Translation Validation System")
        print("=" * 80)
        
        # Validate Python files
        print("\n📝 Validating Python files...")
        self._validate_python_files()
        
        # Validate HTML files
        print("\n🌐 Validating HTML files...")
        self._validate_html_files()
        
        # Validate translation completeness
        print("\n✅ Validating translation dictionary completeness...")
        self._validate_translation_completeness()
        
        # Generate report
        return self._generate_report()
    
    def _should_skip(self, path: Path) -> bool:
        """Check if path should be skipped"""
        path_str = str(path)
        return any(excluded in path_str for excluded in self.EXCLUDED_PATHS)
    
    def _validate_python_files(self):
        """Scan Python files for hardcoded strings"""
        python_files = list(self.project_root.glob('**/*.py'))
        
        for py_file in python_files:
            if self._should_skip(py_file):
                continue
                
            try:
                content = py_file.read_text(encoding='utf-8')
                self._scan_python_content(py_file, content)
            except Exception as e:
                print(f"  ⚠️  Could not read {py_file}: {e}")
    
    def _scan_python_content(self, file_path: Path, content: str):
        """Scan Python file content for hardcoded strings"""
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Skip comments and docstrings
            if line.strip().startswith('#') or '"""' in line or "'''" in line:
                continue
            
            # Skip if line contains translation calls
            if any(call in line for call in ['translate(', 't(', 'i18n.', 'TranslationManager']):
                continue
            
            # Check for hardcoded patterns
            for pattern in self.HARDCODED_PATTERNS[:6]:  # Python-specific patterns
                matches = re.finditer(pattern, line)
                for match in matches:
                    string_content = match.group(1)
                    
                    # Skip if it's an allowed exception
                    if self._is_allowed_exception(string_content):
                        continue
                    
                    # Skip if it's likely a variable/technical term
                    if self._is_technical_string(string_content):
                        continue
                    
                    self.violations.append({
                        'file': str(file_path.relative_to(self.project_root)),
                        'line': line_num,
                        'type': 'hardcoded_string',
                        'content': string_content,
                        'context': line.strip()
                    })
    
    def _validate_html_files(self):
        """Scan HTML files for hardcoded strings"""
        html_files = list(self.project_root.glob('**/*.html'))
        
        for html_file in html_files:
            if self._should_skip(html_file):
                continue
                
            try:
                content = html_file.read_text(encoding='utf-8')
                self._scan_html_content(html_file, content)
            except Exception as e:
                print(f"  ⚠️  Could not read {html_file}: {e}")
    
    def _scan_html_content(self, file_path: Path, content: str):
        """Scan HTML content for hardcoded strings"""
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Skip if line has data-i18n or similar attributes
            if 'data-i18n' in line or 'data-translate' in line:
                continue
            
            # Skip if JavaScript translation function is used
            if 'translate(' in line or 't(' in line:
                continue
            
            # Check HTML-specific patterns
            for pattern in self.HARDCODED_PATTERNS[6:]:  # HTML-specific patterns
                matches = re.finditer(pattern, line, re.IGNORECASE)
                for match in matches:
                    string_content = match.group(1).strip()
                    
                    # Skip short strings or technical terms
                    if len(string_content) < 5 or self._is_allowed_exception(string_content):
                        continue
                    
                    self.violations.append({
                        'file': str(file_path.relative_to(self.project_root)),
                        'line': line_num,
                        'type': 'hardcoded_html',
                        'content': string_content,
                        'context': line.strip()[:100]
                    })
    
    def _validate_translation_completeness(self):
        """Verify all translation keys have all 20 languages"""
        translations = TranslationManager.TRANSLATIONS
        all_languages = {lang.value for lang in Language}
        
        for key, trans_dict in translations.items():
            provided_langs = set(trans_dict.keys())
            missing = all_languages - provided_langs
            
            if missing:
                self.missing_translations.append({
                    'key': key,
                    'missing_languages': sorted(missing),
                    'provided_count': len(provided_langs)
                })
    
    def _is_allowed_exception(self, string: str) -> bool:
        """Check if string is an allowed exception"""
        return string in self.ALLOWED_EXCEPTIONS or len(string) < 3
    
    def _is_technical_string(self, string: str) -> bool:
        """Check if string appears to be technical/non-user-facing"""
        # Check for code-like patterns
        if re.match(r'^[A-Z_]+$', string):  # ALL_CAPS constants
            return True
        if re.match(r'^[a-z_]+$', string):  # snake_case
            return True
        if '/' in string or '\\' in string:  # Paths
            return True
        if '@' in string:  # Email-like
            return True
        if string.startswith('http'):  # URLs
            return True
        if len(string.split()) == 1 and string.istitle():  # Single word title case (might be name)
            return True
        
        return False
    
    def _generate_report(self) -> Dict:
        """Generate validation report"""
        print("\n" + "=" * 80)
        print("📊 VALIDATION REPORT")
        print("=" * 80)
        
        # Summary
        total_violations = len(self.violations)
        total_missing = len(self.missing_translations)
        
        print(f"\n🔍 Found {total_violations} hardcoded string violations")
        print(f"⚠️  Found {total_missing} incomplete translation keys")
        
        # Show top violations
        if self.violations:
            print("\n❌ Top 10 Hardcoded String Violations:")
            print("-" * 80)
            for i, violation in enumerate(self.violations[:10], 1):
                print(f"\n{i}. {violation['file']}:{violation['line']}")
                print(f"   Type: {violation['type']}")
                print(f"   Content: \"{violation['content'][:60]}...\"" if len(violation['content']) > 60 else f"   Content: \"{violation['content']}\"")
        
        # Show missing translations
        if self.missing_translations:
            print("\n⚠️  Incomplete Translation Keys:")
            print("-" * 80)
            for missing in self.missing_translations[:5]:
                print(f"\n  Key: {missing['key']}")
                print(f"  Missing languages: {', '.join(missing['missing_languages'])}")
                print(f"  Coverage: {missing['provided_count']}/20 languages")
        
        # Overall status
        print("\n" + "=" * 80)
        if total_violations == 0 and total_missing == 0:
            print("✅ PASSED: All content is properly internationalized!")
        else:
            print(f"❌ FAILED: {total_violations + total_missing} issues found")
            print("\n💡 Recommendations:")
            if total_violations > 0:
                print("   1. Replace hardcoded strings with t('translation_key') calls")
                print("   2. Add missing keys to i18n.py TRANSLATIONS dictionary")
                print("   3. For HTML, use data-i18n attributes or JavaScript translation")
            if total_missing > 0:
                print("   4. Complete all 20 language translations for existing keys")
        print("=" * 80)
        
        return {
            'total_violations': total_violations,
            'total_missing_translations': total_missing,
            'violations': self.violations,
            'missing_translations': self.missing_translations,
            'status': 'PASSED' if (total_violations == 0 and total_missing == 0) else 'FAILED'
        }
    
    def export_violations_csv(self, output_path: str = "translation_violations.csv"):
        """Export violations to CSV for tracking"""
        import csv
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['file', 'line', 'type', 'content', 'status'])
            writer.writeheader()
            
            for violation in self.violations:
                writer.writerow({
                    'file': violation['file'],
                    'line': violation['line'],
                    'type': violation['type'],
                    'content': violation['content'],
                    'status': 'TO_FIX'
                })
        
        print(f"\n📄 Violations exported to {output_path}")


class TranslationEnforcer:
    """Runtime enforcement of translation usage"""
    
    @staticmethod
    def enforce_translation(func):
        """Decorator to enforce that function uses translation"""
        def wrapper(*args, **kwargs):
            # Get function source
            import inspect
            source = inspect.getsource(func)
            
            # Check if translation functions are used
            if not any(call in source for call in ['translate(', 't(', 'i18n.']):
                print(f"⚠️  WARNING: Function {func.__name__} may contain hardcoded strings!")
            
            return func(*args, **kwargs)
        return wrapper
    
    @staticmethod
    def validate_string(string: str, context: str = ""):
        """Validate a string at runtime to ensure it should be translated"""
        # If it looks like user-facing content, warn
        if len(string) > 15 and ' ' in string and string[0].isupper():
            print(f"⚠️  Possible untranslated string in {context}: \"{string[:50]}...\"")


def main():
    """Run translation validation"""
    validator = TranslationValidator()
    report = validator.validate_project()
    
    # Export violations
    if report['total_violations'] > 0:
        validator.export_violations_csv()
    
    return report


if __name__ == '__main__':
    main()
