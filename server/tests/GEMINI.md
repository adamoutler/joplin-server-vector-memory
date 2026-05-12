# Server Tests (`server/tests/`)

## How it works
This module contains the automated test suites for the Python MCP Server. It validates the FastAPI endpoints, the FastMCP tool implementations, database interactions, hybrid search capabilities (FTS + Vector), and End-to-End MCP interactions.

## Dependencies
- `pytest`
- `httpx` (for FastAPI test client)
- Pytest-asyncio

## What depends on it
- The CI/CD pipeline (Root module) depends on these tests to ensure the Python server functions correctly and securely without regressions.