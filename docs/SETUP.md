# Setup Guide

This guide walks you through setting up the Joplin Server Vector Memory MCP, connecting it to your Joplin Server, and configuring an AI agent to use it.

## Prerequisites

- **Joplin Server**: An active Joplin Server instance with your notes (optionally E2EE enabled).
- **Docker & Docker Compose**: To run the memory server components.
- **Ollama**: Running locally or remotely, with the `all-minilm` model pulled.

## 1. Quick Start Installation

1. Clone the repository to your local machine.
2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
3. Edit the `.env` file to match your setup (e.g., pointing `OLLAMA_URL` to your Ollama instance).
4. Start the services using Docker Compose:
   ```bash
   docker compose up -d
   ```

### Optional: Redis Credential Caching
If you want the system to automatically resume syncing across container or host reboots without requiring you to log back in, you can enable the optional Redis profile. This securely caches your Joplin passwords in an internal Redis container.
Instead of the standard `docker compose up -d`, start the stack with:
```bash
docker compose --profile redis up -d
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

## 5. Reverse Proxy Configuration (Nginx & Nginx Proxy Manager)

When exposing Joplin Server Vector Memory to external AI clients (like Google Gemini Spark, Cursor, or Claude) behind a reverse proxy such as Nginx or Nginx Proxy Manager (NPM), the system operates across two internal services:
- **Port 3000 (Node.js)**: Web Dashboard UI, OAuth 2.0 Authorization Server, RFC 8414 Discovery (`/.well-known/*`), and Consent Page (`/authorize.html`).
- **Port 8000 (Python FastMCP)**: Semantic search, MCP protocol endpoints (`/mcp`, `/http-api/*`), and tools.

### Nginx Proxy Manager (NPM) Configuration Guide

#### 1. "Details" Tab
* **Domain Names**: `joplin.yourdomain.com` (or dedicated subdomain like `memory.yourdomain.com`)
* **Scheme**: `http`
* **Forward Hostname / IP**: `127.0.0.1` (or your Docker container hostname/IP)
* **Forward Port**: `3000` *(Default forwards dashboard and OAuth to Node.js)*
* **Websockets Support**: **ON**
* **Block Common Exploits**: **ON**

#### 2. "Custom Locations" Tab
Add the following 3 custom locations to route MCP traffic and protect internal APIs:

1. **Location: `/mcp`**
   * **Scheme**: `http`
   * **Forward Hostname / IP**: `127.0.0.1`
   * **Forward Port**: `8000`
   * Click the **Gear icon** (custom config) and paste:
     ```nginx
     proxy_http_version 1.1;
     proxy_set_header Connection '';
     proxy_buffering off;
     proxy_cache off;
     chunked_transfer_encoding off;
     proxy_read_timeout 86400s;
     proxy_send_timeout 86400s;
     ```

2. **Location: `/http-api/`**
   * **Scheme**: `http`
   * **Forward Hostname / IP**: `127.0.0.1`
   * **Forward Port**: `8000`
   * Click the **Gear icon** and paste:
     ```nginx
     proxy_http_version 1.1;
     proxy_set_header Connection '';
     proxy_buffering off;
     proxy_cache off;
     chunked_transfer_encoding off;
     proxy_read_timeout 86400s;
     proxy_send_timeout 86400s;
     ```

3. **Location: `/node-api/`** *(Security Block)*
   * **Scheme**: `http`
   * **Forward Hostname / IP**: `127.0.0.1`
   * **Forward Port**: `3000`
   * Click the **Gear icon** and paste:
     ```nginx
     deny all;
     return 403;
     ```

#### 3. "Advanced" Tab
In the **Advanced** tab of the Proxy Host, paste the standard proxy headers so OAuth 2.0 discovery dynamically resolves the public HTTPS domain as its issuer:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

> [!IMPORTANT]
> - **Perimeter Authentication Warning**: If you configure HTTP Basic Auth or an Access List in Nginx Proxy Manager across the entire domain, external AI clients connecting with `Authorization: Bearer <token>` will be rejected by Nginx with HTTP 401 before reaching the server. The `/mcp`, `/http-api/`, and `/.well-known/` routes must be exempt from perimeter Basic Auth.
> - **Dedicated Subdomain Recommendation**: If `joplin.yourdomain.com` is already hosting your official Joplin Server (note sync server on port 22300), Joplin Server occupies the root `/` and `/api/`. Point a dedicated subdomain (such as `memory.yourdomain.com` or `mcp.yourdomain.com`) to this container to prevent route collisions.

