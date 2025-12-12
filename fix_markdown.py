#!/usr/bin/env python3
"""Fix common markdown lint issues"""
import re

def fix_markdown_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    original = content
    
    # Fix bare URLs in headings and text
    content = re.sub(r'www\.phins\.ai(?![)\]])', r'`www.phins.ai`', content)
    
    # Fix fenced code blocks - add blank lines around them
    lines = content.split('\n')
    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if this is a code fence
        if line.strip().startswith('```'):
            # Add blank line before if not present
            if i > 0 and fixed_lines and fixed_lines[-1].strip() != '':
                fixed_lines.append('')
            fixed_lines.append(line)
            i += 1
            
            # Copy lines until closing fence
            while i < len(lines) and not lines[i].strip().startswith('```'):
                fixed_lines.append(lines[i])
                i += 1
            
            # Add closing fence
            if i < len(lines):
                fixed_lines.append(lines[i])
                i += 1
            
            # Add blank line after if not present
            if i < len(lines) and lines[i].strip() != '':
                fixed_lines.append('')
        else:
            fixed_lines.append(line)
            i += 1
    
    content = '\n'.join(fixed_lines)
    
    # Fix lists - ensure blank lines around them
    lines = content.split('\n')
    fixed_lines = []
    for i, line in enumerate(lines):
        # Check if this line starts a list
        if line.strip() and (line.lstrip().startswith('- ') or line.lstrip().startswith('* ') or re.match(r'^\s*\d+\.', line)):
            prev_line = lines[i-1].strip() if i > 0 else ''
            # Add blank before list if previous line isn't blank or list item
            if i > 0 and prev_line and not (prev_line.startswith('-') or prev_line.startswith('*') or re.match(r'^\d+\.', prev_line)):
                if fixed_lines and fixed_lines[-1].strip() != '':
                    fixed_lines.append('')
        
        fixed_lines.append(line)
        
        # Check if next line ends a list
        next_line = lines[i+1].strip() if i+1 < len(lines) else ''
        if line.strip() and (line.lstrip().startswith('- ') or line.lstrip().startswith('* ') or re.match(r'^\s*\d+\.', line)):
            if next_line and not (next_line.startswith('-') or next_line.startswith('*') or re.match(r'^\d+\.', next_line) or next_line.startswith('`')):
                fixed_lines.append('')
    
    content = '\n'.join(fixed_lines)
    
    # Ensure file ends with single newline
    content = content.rstrip() + '\n'
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    return False

# Fix the files
files = ['ADMIN_ACCESS.md', 'RAILWAY_DEPLOYMENT.md']
for f in files:
    try:
        if fix_markdown_file(f):
            print(f'✅ Fixed {f}')
        else:
            print(f'ℹ️  {f} - no changes needed')
    except Exception as e:
        print(f'❌ Error fixing {f}: {e}')
