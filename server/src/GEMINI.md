# Server Source Code (`server/src/`)

## How it works
This directory contains the operational logic of the Python MCP Server.
- `main.py` initializes the FastMCP server (`joplin_notes`), configures the FastAPI application, sets up middleware (e.g., for authentication and JSON acceptance), and defines the canonical MCP tools (`joplin_notes_search`, `joplin_notes_get`, `joplin_notes_create`, `joplin_notes_update`, `joplin_notes_request_deletion`, `joplin_notes_execute_deletion`, `joplin_notes_resource_get`, `joplin_notes_resource_upload`).
- `db.py` provides connection pooling and utilities for interacting with the SQLite database populated by the Node.js client.

## Dependencies
- FastMCP, FastAPI
- SQLite native libraries (`sqlite3`) and `sqlite_vec` for FTS/KNN queries.
- SentenceTransformers (for local embedding generation).

## What depends on it
- The `server/tests/` module depends on this source code to run unit and integration tests.
- The `client/src/sync.js` relies on `main.py`'s embedding endpoint to convert text to vectors.