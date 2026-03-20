import os
import re

files_to_fix = [
    "tests/test_live_api_unhappy.py",
    "tests/test_e2e_ui_workflow.py",
    "tests/test_auth_flow.py",
    "tests/test_dashboard_auth.py",
    "tests/test_ui_api_key.py",
]

for file_path in files_to_fix:
    if not os.path.exists(file_path):
        continue
        
    with open(file_path, 'r') as f:
        lines = f.readlines()

    new_lines = []
    skip = False
    for line in lines:
        if line.startswith('@pytest.fixture(scope="module")') or line.startswith('@pytest.fixture'):
            # Only skip if it's the docker container setup fixture
            # Check the next line to see if it's the fixture we want to remove
            pass
            
        # A more robust way to remove the fixture is to match the definition and skip until 'yield' + subprocess.run 
        # But wait, some files might have multiple fixtures. We just want to remove the ones named setup_container, setup_live_container, etc.
        pass

# Actually, let's just use regex to strip out the setup fixtures entirely.
def remove_fixture(content, fixture_names):
    for fixture in fixture_names:
        # Match @pytest.fixture(scope="module")\ndef fixture_name():\n ... \n\n
        pattern = r'@pytest\.fixture(\([^\)]*\))?\ndef ' + fixture + r'\(\):.*?(?=\n@|\Z)'
        content = re.sub(pattern, '', content, flags=re.DOTALL)
        # Also remove the parameter from test definitions
        content = re.sub(r'def (test_\w+)\(([^)]*)' + fixture + r'([^)]*)\):',
                         lambda m: f"def {m.group(1)}({m.group(2)}{m.group(3)}):".replace('(, ', '(').replace(', )', ')').replace(', ,', ','),
                         content)
    return content

for file_path in files_to_fix:
    if not os.path.exists(file_path):
        continue
        
    with open(file_path, 'r') as f:
        content = f.read()
        
    fixtures = ["setup_live_container_unhappy", "setup_ui_server_advanced", "setup_container", "setup_dashboard_container", "setup_ui_server"]
    new_content = remove_fixture(content, fixtures)
    
    # Also fix ports from 3002 to 3001 and 8003 to 8002 if they exist
    new_content = new_content.replace('3002', '3001').replace('8003', '8002').replace('22301', '22300')
    
    with open(file_path, 'w') as f:
        f.write(new_content)
