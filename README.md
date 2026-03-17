# Joplin Server Vector Memory MCP

An AI-native semantic search engine and memory bridge for personal notes. It acts as a secure, local bridge between an End-to-End Encrypted (E2EE) Joplin Server ecosystem and an MCP (Model Context Protocol) client.

## Components
*   **Sync Client (`client/`)**: A Node.js headless daemon that synchronizes and decrypts notes using `@joplin/lib`. Includes a web dashboard UI at `http://localhost:3000` providing distinct "Sync Status" and "Embedding Status" indicators for clear feedback during the indexing phases.
*   **MCP Server (`server/`)**: A Python FastMCP server that exposes semantic search and note management tools to AI clients.
*   **Database (`database/`)**: Local SQLite database with `sqlite-vec` for extremely fast, embedded vector distance calculations.
*   **Embeddings**: Supports Ollama (`nomic-embed-text` by default) for high-performance vector embeddings. If Ollama is not configured or unavailable, the system features a **zero-configuration local fallback** using an embedded CPU model (`all-MiniLM-L6-v2`), ensuring a seamless, out-of-the-box experience.

## Security & Authentication
* **Initial Boot (Setup Mode):** On first run (if no credentials are provided via `.env`), the system boots into Setup Mode. The background sync daemon is paused. You must access the dashboard at `http://localhost:3000` using the default setup credentials:
  * **Username:** `setup`
  * **Password:** `1-mcp-server`
* **In-Memory Credentials:** The system is designed so that neither the Joplin Server password nor the E2EE Master Password is saved to the Docker volume. Passwords live strictly in volatile RAM.
* **Auto-Unlock via Browser:** The system intercepts your browser's native Basic Auth login to acquire the passwords securely. 
* **User Lock & Factory Reset:** Upon entering your real Joplin Server credentials into the dashboard, the system permanently binds exclusively to that username. It forces a logout of the `setup` account, requiring you to log back in using your *real* Joplin username and password. It cannot be hijacked by other accounts. To switch users, the authenticated owner must access the "Danger Zone" in the dashboard to perform a Factory Reset, which wipes the local databases and relinquishes the lock.

## AI-Feedback Loop (Git P Alias)
To ensure AI agents receive immediate feedback from GitHub Actions when committing code, this project utilizes a custom `git p` command wrapper.

If you are a developer or an AI agent working on this repository, you should configure the `git p` alias:
```bash
git config alias.p '!bash scripts/git-p.sh'
```
Once configured, use `git p` instead of `git push`. The script will automatically push your commits and wait for the corresponding CI run to complete, outputting any failure logs directly to your terminal. There is a pre-push hook installed (for specific users) that will block standard `git push` to enforce this workflow.

## Quick Start
1. Configure your `.env` file (copy from `.env.example`).
2. Run `docker-compose up -d`.
3. Open `http://localhost:3000` to monitor synchronization and embedding progress in real-time.
4. Configure your AI client (e.g., Gemini CLI via `.gemini/settings.json`) to point to the local FastMCP server on port 8000.
