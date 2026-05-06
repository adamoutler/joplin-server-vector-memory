# Environment Variables Configuration

The Joplin Server Vector Memory MCP system can be configured either via the interactive Web Dashboard (Setup Mode) or completely headless via environment variables.

If the core Joplin credentials (`JOPLIN_SERVER_URL`, `JOPLIN_USERNAME`, `JOPLIN_PASSWORD`) are provided via environment variables, the system will bypass Setup Mode on its first run and automatically initialize the configuration and begin synchronization.

## Core Joplin Credentials

*   **`JOPLIN_SERVER_URL`**
    *   *Description:* The base URL of your target Joplin Server instance.
    *   *Example:* `https://joplin.example.com`
*   **`JOPLIN_USERNAME`**
    *   *Description:* The email address or username used to log in to the Joplin Server.
    *   *Example:* `admin@example.com`
*   **`JOPLIN_PASSWORD`**
    *   *Description:* The password for the Joplin Server account.
*   **`JOPLIN_MASTER_PASSWORD`**
    *   *Description:* The master password used for End-to-End Encryption (E2EE) to decrypt notes. This must be the master password that was used to encrypt the notes on the server. If omitted, the system will attempt to use `JOPLIN_PASSWORD` as a fallback.

## AI Embedding Configuration

*   **`OLLAMA_URL`**
    *   *Description:* If you wish to use Ollama for high-performance vector generation, set this to the URL of your Ollama instance. If left blank, the system automatically falls back to an embedded CPU model (`all-MiniLM-L6-v2`).
    *   *Example:* `http://192.168.1.100:11434`
*   **`EMBEDDING_MODEL`**
    *   *Description:* The name of the Ollama model to use for embeddings if `OLLAMA_URL` is set.
    *   *Default:* `all-minilm`

## Security & API Access

*   **`API_TOKEN`**
    *   *Description:* When using environment variables to bypass Setup Mode, this variable allows you to manually define the exact API key the Python backend will accept for `/api/` and `/http-api/` requests. If not provided, a random UUID is generated during the initial boot.

## Network & Port Configuration

*   **`FRONTEND_PORT`**
    *   *Description:* Used in the provided `docker-compose.yml` to map the external port for the Node.js dashboard.
    *   *Default:* `3000`
*   **`PORT`**
    *   *Description:* The internal port the Node.js Express server binds to.
    *   *Default:* `3000`
*   **`BACKEND_URL`**
    *   *Description:* The URL the Node.js proxy uses to communicate with the Python FastMCP server.
    *   *Default:* `http://127.0.0.1:8000`
*   **`NODE_PROXY_URL`**
    *   *Description:* The URL the Python FastMCP server uses to communicate back to the Node.js proxy (for syncing or retrieving resources).
    *   *Default:* `http://127.0.0.1:3000`

## System Paths & Internals

*   **`DATA_DIR`**
    *   *Description:* The base directory for persistent data storage.
    *   *Default:* `/app/data` (when run via Docker)
*   **`SQLITE_DB_PATH`**
    *   *Description:* The explicit path to the SQLite vector database.
    *   *Default:* `${DATA_DIR}/vector_memory.sqlite`
*   **`JOPLIN_PROFILE_DIR`**
    *   *Description:* The temporary directory where the `@joplin/lib` sync client stores its encrypted state.
    *   *Default:* `${DATA_DIR}/joplin-profile`
*   **`CONFIG_PATH`**
    *   *Description:* The path to the generated `config.json` that stores runtime state and API keys.
    *   *Default:* `/app/data/config.json`
*   **`SYNC_INTERVAL_MS`**
    *   *Description:* The polling interval in milliseconds for the background sync daemon.
    *   *Default:* `60000` (60 seconds)