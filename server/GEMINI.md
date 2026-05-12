# Server Module (`server/`)

## How it works
The `server` module is a Python application that hosts the FastMCP (Model Context Protocol) server. It provides AI assistants with a secure, local bridge to the Joplin personal knowledge base. It handles incoming MCP requests (via SSE, stateless HTTP, or stdio) to perform semantic searches, fetch full notes, and execute note creations or deletions.

## Dependencies
- Python 3.10+
- FastAPI, Uvicorn
- FastMCP
- `sentence-transformers`, `ollama` (for embedding generation)
- `sqlite-vec` (for vector search operations)

## What depends on it
- The Root module (`/`) depends on it for building the `server` Docker image.
- The `client/` module depends on the internal `/http-api/internal/embed` endpoint exposed by this server to generate vector embeddings during the sync process.
- AI Agents (like Cursor, Cline, or Gemini CLI) depend on this server via the MCP protocol.