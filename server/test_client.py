import requests

# Test SSE root
r1 = requests.get("http://localhost:8000/http-api/mcp/sse/")
print("SSE root:", r1.status_code)

# Test SSE messages
r2 = requests.post("http://localhost:8000/http-api/mcp/sse/messages")
print("SSE messages:", r2.status_code)

# Test Stream root
r3 = requests.post("http://localhost:8000/http-api/mcp/stream/")
print("Stream root:", r3.status_code)

# Test Stateless root
r4 = requests.post("http://localhost:8000/http-api/mcp/stateless/")
print("Stateless root:", r4.status_code)

