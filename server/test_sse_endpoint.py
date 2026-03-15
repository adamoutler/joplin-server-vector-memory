import asyncio
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import json

async def run():
    url = "http://127.0.0.1:8000/http-api/mcp/sse"
    async with sse_client(url) as (read, write):
        # We don't need to initialize, just checking what the write endpoint is
        print("Write endpoint URL:", write._session_id, getattr(write, 'post_url', 'unknown'))

asyncio.run(run())
