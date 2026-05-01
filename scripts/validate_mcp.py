#!/usr/bin/env python3
import sys
import os
import asyncio

# Add the server directory to PYTHONPATH so we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../server')))

try:
    from src.main import mcp
except ImportError as e:
    print(f"Error importing MCP server: {e}")
    sys.exit(1)


async def main():
    try:
        tools = await mcp.list_tools()
    except Exception as e:
        print(f"Error listing MCP tools: {e}")
        sys.exit(1)

    if not tools:
        print("Error: No MCP tools found.")
        sys.exit(1)

    errors = []
    for tool in tools:
        if not tool.name:
            errors.append("Tool is missing a name.")

        if not hasattr(tool, "description") or not tool.description:
            errors.append(f"Tool '{tool.name}' is missing a description.")

        # In MCP standard Python SDKs, the field is often `inputSchema`, but FastMCP uses `parameters`.
        schema = getattr(tool, "parameters", getattr(tool, "inputSchema", None))

        if schema is None or not isinstance(schema, dict):
            errors.append(f"Tool '{tool.name}' has invalid or missing schema definition (parameters/inputSchema): {type(schema)}")

    if errors:
        print("MCP Schema Validation Failed:")
        for err in errors:
            print(f" - {err}")
        sys.exit(1)

    print(f"MCP Schema Validation Passed! Found {len(tools)} tools.")
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
