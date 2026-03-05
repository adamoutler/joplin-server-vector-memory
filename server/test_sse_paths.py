import os
os.environ["FASTMCP_SSE_PATH"] = "/custom/sse"
os.environ["FASTMCP_MESSAGE_PATH"] = "/custom/messages"
from fastmcp import FastMCP
mcp = FastMCP("Test")
app = mcp.http_app(transport="sse")
for route in app.routes:
    print(route.path if hasattr(route, 'path') else route)
