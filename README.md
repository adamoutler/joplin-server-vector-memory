# Joplin Server Vector Memory MCP

An AI-native semantic search engine and memory bridge for personal notes. It acts as a secure, local bridge between an End-to-End Encrypted (E2EE) Joplin Server ecosystem and an MCP (Model Context Protocol) client.

## Components
*   **Sync Client (`client/`)**: A Node.js headless daemon that synchronizes and decrypts notes using `@joplin/lib`.
*   **MCP Server (`server/`)**: A Python FastMCP server that exposes semantic search and note management tools to AI clients.
*   **Database (`database/`)**: Local SQLite database with `sqlite-vec` for extremely fast, embedded vector distance calculations.
*   **Embeddings**: By default, uses an embedded Ollama container with `nomic-embed-text` to generate vector embeddings of your notes.

## Quick Start
1. Configure your `.env` file (copy from `.env.example`).
2. Run `docker-compose up -d`.
3. Configure your Gemini CLI `.gemini/settings.json` to point to the local FastMCP server on port 8000.
