import os

with open('tests/conftest.py', 'r') as f:
    content = f.read()

# Remove ephemeral_docker_cluster from tests/conftest.py
import re
new_content = re.sub(r'@pytest\.fixture\(scope="session", autouse=True\)\ndef ephemeral_docker_cluster\(\):.*?(?=@pytest\.fixture|\Z)', '', content, flags=re.DOTALL)

with open('tests/conftest.py', 'w') as f:
    f.write(new_content)
