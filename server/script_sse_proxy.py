from fastapi import FastAPI, Request
from fastmcp import FastMCP
import asyncio
import uvicorn

mcp = FastMCP("test")
fastmcp_app = mcp.http_app(transport='sse', path="/")

app = FastAPI()

@app.api_route("/http-api/mcp/sse", methods=["GET", "POST", "OPTIONS"])
@app.api_route("/http-api/mcp/sse/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def handle_mcp_sse(request: Request, path: str = ""):
    scope = dict(request.scope)
    scope["path"] = f"/{path}"
    return await fastmcp_app(scope, request.receive, request._send)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.0", port=8001)
