import asyncio
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession


async def main():
    async with sse_client("http://localhost:8000/http-api/mcp/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Successfully connected!")
            tools = await session.list_tools()
            print("Tools:", tools)

if __name__ == "__main__":
    asyncio.run(main())
