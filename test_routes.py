import asyncio
import httpx

async def test_endpoint():
    async with httpx.AsyncClient() as client:
        print("Testing FastMCP SSE app directly at /http-api/mcp/sse/")
        
        # Test GET to sse root
        r = await client.get("http://localhost:8000/http-api/mcp/sse/")
        print(f"GET /sse/: {r.status_code}")
        
        r = await client.post("http://localhost:8000/http-api/mcp/sse/")
        print(f"POST /sse/: {r.status_code}")
        
        r = await client.get("http://localhost:8000/http-api/mcp/sse/messages")
        print(f"GET /sse/messages: {r.status_code}")
        
        r = await client.post("http://localhost:8000/http-api/mcp/sse/messages")
        print(f"POST /sse/messages: {r.status_code}")
        
        print("Testing FastMCP Stateless app directly at /http-api/mcp/stateless/")
        r = await client.post("http://localhost:8000/http-api/mcp/stateless/")
        print(f"POST /stateless/: {r.status_code}")

if __name__ == "__main__":
    asyncio.run(test_endpoint())