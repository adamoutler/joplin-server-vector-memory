import sys
import os
import json

os.environ['CONFIG_PATH'] = '/tmp/test_config.json'
with open('/tmp/test_config.json', 'w') as f:
    json.dump({
        "embedding": {
            "provider": "ollama",
            "baseUrl": "http://192.168.1.101:11434",
            "model": "gemma" # wait, user said 'embeddinggemma'? let's try that or print available models
        }
    }, f)

import ollama
try:
    client = ollama.Client(host="http://192.168.1.101:11434")
    print("Ollama models:")
    print([m['name'] for m in client.list()['models']])
except Exception as e:
    print("Ollama error:", e)

