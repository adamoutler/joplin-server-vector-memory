# Joplin Server Vector Memory MCP

An AI-native semantic search engine and memory bridge for personal notes. It acts as a secure, local bridge between an End-to-End Encrypted (E2EE) Joplin Server ecosystem and an MCP (Model Context Protocol) client.

## Components
*   **Sync Client (`client/`)**: A Node.js headless daemon that synchronizes and decrypts notes using `@joplin/lib`. Includes a web dashboard UI at `http://localhost:3000` providing distinct "Sync Status" and "Embedding Status" indicators for clear feedback during the indexing phases.
*   **MCP Server (`server/`)**: A Python FastMCP server that exposes semantic search and note management tools to AI clients.
*   **Database (`database/`)**: Local SQLite database with `sqlite-vec` for extremely fast, embedded vector distance calculations.
*   **Embeddings**: Supports Ollama (`nomic-embed-text` by default) for high-performance vector embeddings. If Ollama is not configured or unavailable, the system features a **zero-configuration local fallback** using an embedded CPU model (`all-MiniLM-L6-v2`), ensuring a seamless, out-of-the-box experience.

## Quick Start
1. Configure your `.env` file (copy from `.env.example`).
2. Run `docker-compose up -d`.
3. Open `http://localhost:3000` to monitor synchronization and embedding progress in real-time.
4. Configure your AI client (e.g., Gemini CLI via `.gemini/settings.json`) to point to the local FastMCP server on port 8000.
