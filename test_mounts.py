from fastapi import FastAPI
import fastmcp
from fastmcp import FastMCP

mcp = FastMCP("test")

fastmcp.settings.sse_path = "/http-api/mcp/sse"
fastmcp.settings.message_path = "/http-api/mcp/sse/messages"
fastmcp.settings.streamable_http_path = "/http-api/mcp/stream"

fastmcp_app = mcp.http_app(transport='sse')
stateless_app = mcp.http_app(transport='http', stateless_http=True, path="/http-api/mcp/stateless", json_response=True)
streamable_app = mcp.http_app(transport='streamable-http')

app = FastAPI()
for route in fastmcp_app.routes:
    app.routes.append(route)
for route in stateless_app.routes:
    app.routes.append(route)
for route in streamable_app.routes:
    app.routes.append(route)

for route in app.routes:
    print(getattr(route, "path", route))
