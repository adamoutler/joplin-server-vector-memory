import os
with open('tests/test_live_api_e2e.py', 'r') as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if line.startswith('@pytest.fixture(scope="module")'):
        skip = True
    if skip and line.startswith('@pytest.mark.enable_socket'):
        skip = False
    
    if not skip:
        if line.startswith('def test_api_server_live_endpoints(setup_live_container):'):
            new_lines.append('def test_api_server_live_endpoints():\n')
        else:
            new_lines.append(line)

with open('tests/test_live_api_e2e.py', 'w') as f:
    f.writelines(new_lines)
