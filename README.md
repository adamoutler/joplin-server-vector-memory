# 🧠 Joplin Server Vector Memory MCP: Your Universal AI Brain

In an era where cognitive labor is increasingly augmented by a rotating cast of AI assistants, your intellectual capital shouldn't be trapped in isolated digital silos. **Joplin Server Vector Memory MCP** transforms your personal notes into a universal **"AI Brain"**—a secure, centralized, and delightfully interoperable memory engine designed for the multi-agent future. Think of it as the ultimate VIP lounge where all your AI tools can securely access your best ideas! ✨

An AI-native semantic search engine and memory bridge, this system acts as a secure, local connection between your End-to-End Encrypted (E2EE) Joplin Server ecosystem and any MCP (Model Context Protocol) client.

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
*   **In-Memory Credentials:** The system is designed so that neither the Joplin Server password nor the E2EE Master Password is ever saved to the Docker volume. Passwords live strictly in volatile RAM.
*   **Auto-Unlock via Browser:** The system intercepts your browser's native Basic Auth login to acquire the passwords securely.
*   **User Lock & Factory Reset:** Upon entering your real Joplin Server credentials into the dashboard, the system permanently binds exclusively to that username. It forces a logout of the `setup` account, requiring you to log back in using your *real* Joplin username and password. It cannot be hijacked by other accounts. To switch users, the authenticated owner must access the "Danger Zone" in the dashboard to perform a Factory Reset, which wipes the local databases and relinquishes the lock.

---

## 🤖 Automated CI/CD & Versioning

This project uses GitHub Actions for continuous integration to ensure high reliability.

*   **Auto-Versioning:** Every local commit automatically triggers a `post-commit` hook that generates and tags a semver version (e.g., `v0.1.X`) based on the commit depth.
*   **Deployment:** Pushing to the `main` branch triggers the CI pipeline. If all tests pass, the container is automatically built and deployed to the GitHub Container Registry (`ghcr.io`) with the new version tag.
*   **AI Feedback Loop:** The Gemini CLI is configured with a post-tool hook that intercepts `git push` commands. The AI will automatically wait for the GitHub Actions workflow to complete and read the CI results, ensuring rigorous QA without manual intervention.

---

## 🚀 Quick Start Guide

Ready to supercharge your AI assistants? Let's get started:

1.  **Configure Environment:** Copy the example config file to set up your environment.
    ```bash
    cp .env.example .env
    ```
    *(Optionally edit `.env` to add your credentials, or leave it blank to use the secure Setup Mode UI.)*
2.  **Spin Up the Infrastructure:**
    ```bash
    docker-compose up -d
    ```
3.  **Monitor Progress:** Open `http://localhost:3000` in your browser. If you didn't provide credentials in `.env`, log in with `setup` / `1-mcp-server` to enter your Joplin details. Watch your synchronization and embedding progress in real-time!
4.  **Connect Your AI:** Configure your favorite AI client (e.g., Gemini CLI via `.gemini/settings.json`, Claude Desktop, etc.) to point to the local FastMCP server running on port `8000`.

---

## 📚 What's Next? Further Resources

*   **[API Documentation](docs/API.md)**: Deep dive into the available MCP tools and endpoints.
*   **[System Architecture](docs/ARCHITECTURE.md)**: Understand the data flow and component interactions.
*   **[Setup Guide](docs/SETUP.md)**: Detailed instructions for advanced configurations.
*   **[AI Friction Architecture](docs/AI_FRICTION_ARCHITECTURE.md)**: Learn how we design safe Agentic UX.

*Welcome to the future of personal knowledge management. Your AI brain is ready!* 🧠✨
