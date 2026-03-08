# Setup Guide

This guide walks you through setting up the Joplin Server Vector Memory MCP, connecting it to your Joplin Server, and configuring an AI agent to use it.

## Prerequisites

- **Joplin Server**: An active Joplin Server instance with your notes (optionally E2EE enabled).
- **Docker & Docker Compose**: To run the memory server components.
- **Ollama**: Running locally or remotely, with the `nomic-embed-text` model pulled.

## 1. Quick Start Installation

1. Clone the repository to your local machine.
2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
3. Edit the `.env` file to match your setup (e.g., pointing `OLLAMA_URL` to your Ollama instance).
4. Start the services using Docker Compose:
   ```bash
   docker-compose up -d
   ```

## 2. Configuration & Sync

Once the services are running, you need to authenticate with your Joplin Server.

1. Open your web browser and navigate to the Sync Client dashboard at `http://localhost:3000`.
2. Fill out the configuration form:
   - **Joplin Server URL**: e.g., `https://joplin.yourdomain.com`
   - **Username**: Your Joplin Server email address.
   - **Password**: Your Joplin Server password.
   - **Master Password**: (Optional) Required if you use End-to-End Encryption (E2EE) to decrypt your notes locally.
   - **Memory Server Address**: Default is usually `http://localhost:3000`.
3. Click **Save & Validate**.
4. The server will begin synchronizing your notes. You can monitor the sync status at the top of the dashboard. During sync, notes are downloaded, decrypted (if E2EE), and embedded using Ollama.
5. Copy the **Local Access Token** displayed on the dashboard. You will need this to authenticate your AI agents.

## 3. Connecting AI Agents

The Joplin Memory Server supports multiple Model Context Protocol (MCP) clients. Refer to the dashboard or `/llms.txt` on the server for live copy-paste configuration snippets.

> **CRITICAL**: Do NOT use port `3000` (the Sync Client proxy) for MCP connection in the client configuration. The actual MCP backend runs on port `8000`. Ensure your MCP client configuration points to the Backend API Port (usually `8000`).

### Example: Stateless HTTP (e.g., Gemini CLI)

Update your `settings.json` (e.g., `.gemini/settings.json`) with the following:

```json
{
  "mcpServers": {
    "joplin_memory": {
      "url": "http://localhost:8000/http-api/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_LOCAL_ACCESS_TOKEN>"
      }
    }
  }
}
```

### Example: Streamable HTTP (e.g., Cline, Claude Desktop, Windsurf)

```json
{
  "mcpServers": {
    "joplin_memory": {
      "url": "http://localhost:8000/http-api/mcp/stream",
      "headers": {
        "Authorization": "Bearer <YOUR_LOCAL_ACCESS_TOKEN>"
      }
    }
  }
}
```

### Example: Server-Sent Events (SSE) (e.g., Cursor)

```json
{
  "mcpServers": {
    "joplin_memory": {
      "url": "http://localhost:8000/http-api/mcp/sse",
      "headers": {
        "Authorization": "Bearer <YOUR_LOCAL_ACCESS_TOKEN>"
      }
    }
  }
}
```

## 4. Testing the Setup

You can view the interactive Swagger API documentation by navigating to `http://localhost:3000/docs`. From there, you can authorize using your Bearer token and test out endpoints such as `POST /http-api/search` manually to verify embeddings are working correctly.
