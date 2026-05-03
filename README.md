# 🧠 Joplin Server Vector Memory MCP: Your Universal AI Brain

[![SafeSkill](https://safeskill.dev/api/badge/adamoutler-joplin-server-vector-memory)](https://safeskill.dev/scan/adamoutler-joplin-server-vector-memory)
[![CI Pipeline](https://github.com/adamoutler/joplin-server-vector-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/adamoutler/joplin-server-vector-memory/actions/workflows/ci.yml)
[![NPM Version](https://img.shields.io/github/package-json/v/adamoutler/joplin-server-vector-memory.svg)](https://github.com/adamoutler/joplin-server-vector-memory)
[![License](https://img.shields.io/github/license/adamoutler/joplin-server-vector-memory.svg)](https://github.com/adamoutler/joplin-server-vector-memory/blob/main/LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Commitizen friendly](https://img.shields.io/badge/commitizen-friendly-brightgreen.svg)](http://commitizen.github.io/cz-cli/)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/adamoutler/joplin-server-vector-memory/badge)](https://securityscorecards.dev/viewer/?uri=github.com/adamoutler/joplin-server-vector-memory)
[![Docker Image Size](https://img.shields.io/docker/image-size/adamoutler/joplin-server-vector-memory-dev/latest?label=Docker%20Size)](https://github.com/adamoutler/joplin-server-vector-memory/pkgs/container/joplin-server-vector-memory-dev)

In an era where cognitive labor is increasingly augmented by a rotating cast of AI assistants, your intellectual capital shouldn't be trapped in isolated digital silos. **Joplin Server Vector Memory MCP** transforms your personal notes into a universal **"AI Brain"**—a secure, centralized, and delightfully interoperable memory engine designed for the multi-agent future. Think of it as the ultimate VIP lounge where all your AI tools can securely access your best ideas! ✨

An AI-native semantic search engine and memory bridge, this system acts as a secure, local connection between your End-to-End Encrypted (E2EE) Joplin Server ecosystem and any MCP (Model Context Protocol) client.

---

## 🚀 Quick Start Guide

Ready to supercharge your AI assistants? Let's get started:

### Option 1: Docker Run

```bash
docker pull ghcr.io/adamoutler/joplin-server-vector-memory-dev:latest
docker run -p 127.0.0.1:3000:3000 -p 127.0.0.1:8000:8000 -v data:/app/data ghcr.io/adamoutler/joplin-server-vector-memory-dev:latest
```

### Option 2: Docker Compose

1. Download one of our provided docker-compose files:
    *   **[docker-compose.yml](docs/docker-compose.yml)** (Stable)
    *   **[docker-compose-dev.yml](docs/docker-compose-dev.yml)** (Latest Dev)
2. Run the following command in the directory containing the downloaded file:
    ```bash
    docker compose up -d
    ```
3. **Monitor Progress:** Open `http://localhost:3000` in your browser. Log in with `setup` / `1-mcp-server` to enter your Joplin details. Watch your synchronization and embedding progress in real-time!
4. **Connect Your AI:** Configure your favorite AI client (e.g., Gemini CLI via `.gemini/settings.json`, Claude Desktop, etc.) to point to the local FastMCP server running on port `8000`.

---

## 🎯 Core Philosophy & Architecture

Our primary architectural mandate is **Interoperability and Record/Convey**. By default, most AI platforms hoard your project context and learned skills within their proprietary agent memories. This system breaks that paradigm. Whether you are coding with GitHub Copilot, analyzing data with Claude Code, brainstorming via Gemini CLI, or automating with GPT Codex, this bridge allows *any* AI to interface seamlessly with your complete Joplin knowledge base. 🤝

### 🕊️ Transferrable Knowledge (Zero Vendor Lock-in)
Guarantee the sovereignty of your data. Export and utilize your notes across any AI platform, ensuring your personal memory is always an open highway, never a walled garden. Record insights once, and empower any AI agent to recall and build upon them instantly.

### 🛡️ Safe Agentic UX via Friction Architecture
Designing APIs and MCP tools for AI agents requires a different paradigm than designing for humans. Instead of optimizing for visual UX, we optimize for **Agentic UX**. We've implemented a pioneering API design that manages AI behavior through a "sliding scale of friction" (Levels -1 to 3). This framework intentionally guides AIs toward safe behaviors and safeguards your data against destructive hallucinations—employing measures up to "Extreme Friction," which requires multi-turn cryptographic proof for permanent note deletions. Not today, rogue agents! 🛑
*(Read more in our [AI Friction Architecture Guide](docs/AI_FRICTION_ARCHITECTURE.md))*

---

## 🧩 System Components

The architecture is split into robust, specialized components to keep your data moving fast and securely:

*   🔄 **Sync Client (`client/`)**: A Node.js headless daemon that synchronizes and decrypts your notes using `@joplin/lib`. It features a snazzy web dashboard at `http://localhost:3000` providing distinct "Sync Status" and "Embedding Status" indicators for transparent, real-time feedback while your brain gets indexed.
*   🚀 **MCP Server (`server/`)**: A high-performance Python FastMCP server exposing robust semantic search and note management tools directly to your AI clients.
*   🗄️ **Vector Database (`database/`)**: Built on a trusty local SQLite database utilizing `sqlite-vec` for embedded vector distance calculations so fast, if you blink, you'll miss them. ⚡
*   🪄 **Adaptive Embeddings**: Powered by Ollama (`nomic-embed-text`) for high-performance vector embeddings by default. Don't have Ollama running? No worries! The system features a **zero-configuration local fallback** using an embedded CPU model (`all-MiniLM-L6-v2`) ensuring seamless, out-of-the-box operation.

---

## 🔒 Security & Authentication

Your privacy is paramount. We've built the system so that your credentials stay yours alone.

*   **Initial Boot (Setup Mode):** On first run (if no credentials are provided via `.env`), the system boots into Setup Mode. The background sync daemon is paused. You must access the dashboard at `http://localhost:3000` using the default setup credentials (`Username: setup`, `Password: 1-mcp-server`).
*   **In-Memory Credentials:** The system is designed so that neither the Joplin Server password nor the E2EE Master Password is ever saved to the Docker volume by default. Passwords live strictly in volatile RAM.
*   **Optional Redis Caching:** For users who want persistent logins across container or host reboots without storing passwords in plaintext files, you can enable the optional Redis profile (`docker compose --profile redis up -d`). This securely caches your credentials in Redis, allowing the system to automatically resume syncing after a restart.
*   **Auto-Unlock via Browser:** The system intercepts your browser's native Basic Auth login to acquire the passwords securely.
*   **User Lock & Factory Reset:** Upon entering your real Joplin Server credentials into the dashboard, the system permanently binds exclusively to that username. It forces a logout of the `setup` account, requiring you to log back in using your *real* Joplin username and password. It cannot be hijacked by other accounts. To switch users, the authenticated owner must access the "Danger Zone" in the dashboard to perform a Factory Reset, which wipes the local databases and relinquishes the lock.

---

## 📚 What's Next? Further Resources

### Usage & Setup
*   **[Setup Guide](docs/SETUP.md)**: Detailed instructions for advanced configurations.
*   **[Environment Variables](docs/ENVIRONMENT.md)**: A comprehensive reference for all headless configuration options.
*   **[API Documentation](docs/API.md)**: Deep dive into the available MCP tools and endpoints.

### Architecture & Design
*   **[System Architecture](docs/ARCHITECTURE.md)**: Understand the data flow and component interactions.
*   **[AI Friction Architecture](docs/AI_FRICTION_ARCHITECTURE.md)**: Learn how we design safe Agentic UX.
*   **[Local Embedding Plan](docs/local-embedding-plan.md)**: Details on our zero-configuration local AI fallback strategy.

### Development & Contributing
*   **[Kanban Tickets](docs/kanban_tickets.md)**: Current roadmap, planned features, and bug fixes.
*   **[CI/CD AI Feedback Loop](docs/CI_CD_AI_FEEDBACK_LOOP.md)**: How our autonomous AI agents handle testing and deployment.

*Welcome to the future of personal knowledge management. Your AI brain is ready!* 🧠✨