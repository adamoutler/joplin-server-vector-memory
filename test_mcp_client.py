import asyncio
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

async def run():
    print("Testing port 8000...")
    try:
        async with streamable_http_client("http://localhost:8000/http-api/mcp/stream") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Port 8000 initialized successfully.")
    except Exception as e:
        print(f"Port 8000 failed: {e}")

    print("Testing port 3000...")
    try:
        async with streamable_http_client("http://localhost:3000/http-api/mcp/stream") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Port 3000 initialized successfully.")
    except Exception as e:
        print(f"Port 3000 failed: {e}")

asyncio.run(run())
