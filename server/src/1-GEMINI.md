# Server Source Code (`server/src/`)

## How it works
This directory contains the operational logic of the Python MCP Server.
- `main.py` initializes the FastMCP server, configures the FastAPI application, sets up middleware (e.g., for authentication and JSON acceptance), and defines the core MCP tools (`notes_search`, `notes_get`, `notes_remember`, `notes_request_deletion`, `notes_execute_deletion`).
- `db.py` provides connection pooling and utilities for interacting with the SQLite database populated by the Node.js client.

## Dependencies
- FastMCP, FastAPI
- SQLite native libraries (`sqlite3`) and `sqlite_vec` for FTS/KNN queries.
- SentenceTransformers (for local embedding generation).

## What depends on it
- The `server/tests/` module depends on this source code to run unit and integration tests.
- The `client/src/sync.js` relies on `main.py`'s embedding endpoint to convert text to vectors.