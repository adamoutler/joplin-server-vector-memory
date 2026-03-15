
## 1. Project Overview
The **Joplin Server Vector Memory MCP** is a dual-component system designed to provide an AI-native semantic search engine for personal notes. It acts as a secure, local bridge between an End-to-End Encrypted (E2EE) Joplin Server ecosystem and an MCP (Model Context Protocol) client.

### Core Mission
To securely sync and decrypt Joplin notes locally, generate vector embeddings of their content, store them in a local SQLite database utilizing the `sqlite-vec` extension, and expose semantic search and bi-directional management capabilities to AI assistants via an MCP server, all while maintaining the integrity of Joplin's E2EE model.

---

## 2. Technical Architecture
The application is built using a hybrid Node.js and Python stack:

- **Sync Client (Node.js)**: A headless daemon utilizing the official `@joplin/lib` package. It authenticates with the Joplin Server, downloads encrypted blobs, and decrypts them locally using the user's Master Password.
- **Embedding Generation**: Processes decrypted Markdown text through an embedding model (e.g., `nomic-embed-text` via Ollama) to generate high-dimensional vector arrays.
- **Storage (SQLite & sqlite-vec)**: Utilizes a local SQLite database with the embedded `sqlite-vec` extension to store the decrypted text, metadata, and embeddings natively on disk with zero infrastructure overhead.
- **MCP Server (Python / FastMCP)**: Connects to the local SQLite database and exposes bi-directional tools to the AI, allowing it to perform semantic searches, read full notes, and trigger memory creation/deletion over the personal knowledge base.

---

## 3. Key Features

### Headless Synchronization
The Node.js daemon runs autonomously, hooking into Joplin’s `ResourceService` and `Synchronizer` event emitters to intercept fully synced and decrypted notes in real-time.

### E2EE Integrity
The architecture ensures notes remain fully encrypted on the central Joplin Server. Decryption and vectorization only happen within the trusted boundary of the local network.

### Embedded Vector Search
Leverages the `sqlite-vec` extension to perform rapid distance calculations for semantic querying, bypassing the need for heavy, dedicated vector databases (like MySQL or Milvus) and reducing memory overhead.

---

## 4. Environment & Deployment

### Deployment Strategy
- The system is designed to run locally or on a trusted server.
- Components (Node.js Sync Client, Python MCP Server) and bundled services (like Ollama for embeddings) are best managed via **Docker Compose** for consistent environment provisioning and networking, with SQLite running seamlessly inside the shared filesystem volume.

