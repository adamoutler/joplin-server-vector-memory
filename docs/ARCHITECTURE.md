# Architecture Overview

Joplin Server Vector Memory MCP is an AI-native semantic search engine designed to interface between an End-to-End Encrypted (E2EE) Joplin Server ecosystem and an AI client via the Model Context Protocol (MCP).

## Core Components

The system is split into several primary components:

### 1. Sync Client (Node.js)
The Sync Client resides in the `client/` directory and acts as a headless daemon.
- **Responsibilities:**
  - Authenticates with the Joplin Server.
  - Synchronizes and decrypts E2EE notes using `@joplin/lib`.
  - Triggers embedding generation for the notes.
  - Serves a dashboard GUI for setup and token generation (running on port 3000 by default).
  - Proxies traffic to the backend MCP server.

### 2. MCP Server (Python)
The MCP Server is implemented using `FastMCP` and `FastAPI` in the `server/` directory.
- **Responsibilities:**
  - Exposes the MCP protocol to various AI clients over multiple transport layers:
    - Stateless HTTP (e.g., for Gemini CLI)
    - Streamable HTTP (e.g., for Cline, Claude)
    - Server-Sent Events (SSE) (e.g., for Cursor)
  - Provides a standard REST HTTP API under `/http-api/`.
  - Performs semantic searches and Note operations (`get`, `remember`, `delete`).

### 3. Database Layer (SQLite)
A local embedded database using `sqlite3` enhanced with extensions:
- **`sqlite-vec`**: Provides extremely fast local vector distance calculations for embeddings.
- **`FTS5` (Full-Text Search)**: Maintains a traditional keyword-based search index.
- Data is stored across multiple tables (e.g., `note_metadata` for raw content, `vec_notes` for vectors, and `notes_fts` for text search) kept in sync via triggers.

### 4. Embeddings (Ollama)
By default, the system relies on a local Ollama container.
- **Model:** Uses `nomic-embed-text` to map text into 768-dimensional vectors.
- Used both during the sync process (embedding notes) and during search queries.

## Data Flow

### Syncing
1. The Sync Client polls the Joplin Server.
2. Encrypted note items are downloaded and decrypted locally.
3. The plain text content is sent to Ollama to generate vector embeddings.
4. Note metadata and embeddings are persisted in the SQLite database.

### Searching (Reciprocal Rank Fusion)
1. An AI Agent sends a search query via MCP or the HTTP API.
2. The MCP Server asks Ollama to generate an embedding for the query.
3. The server runs two searches in parallel:
   - A `sqlite-vec` k-nearest neighbors vector search.
   - An `FTS5` keyword-based BM25 search.
4. The system merges the results using **Reciprocal Rank Fusion (RRF)** to ensure highly relevant semantic and keyword matches are prioritized.
5. The top notes are returned as a result to the AI Agent.
