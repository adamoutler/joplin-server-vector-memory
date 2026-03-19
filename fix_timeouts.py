import os
import glob
import re

for filepath in glob.glob('tests/*.py') + ['conftest.py']:
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        if 'requests.get(' in line or 'requests.post(' in line:
            if 'timeout=' not in line:
                # Find the end of the line, if it ends with ')', insert ', timeout=30'
                if line.rstrip().endswith(')'):
                    lines[i] = line.rstrip()[:-1] + ', timeout=30)\n'
                elif line.rstrip().endswith('})'):
                    lines[i] = line.rstrip()[:-1] + ', timeout=30)\n'
                elif line.rstrip().endswith('))'):
                    lines[i] = line.rstrip()[:-1] + ', timeout=30)\n'
                
    with open(filepath, 'w') as f:
        f.writelines(lines)
