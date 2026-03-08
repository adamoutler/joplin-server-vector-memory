# Joplin Server Vector Memory MCP

The **Joplin Server Vector Memory MCP** creates an AI-native semantic search engine for your personal notes. It operates as a secure, local bridge connecting an End-to-End Encrypted (E2EE) Joplin Server ecosystem with an AI assistant via the Model Context Protocol (MCP) and localized vector storage.

This system bypasses the limitations of the traditional Joplin Web Clipper API by establishing an independent, "headless" sync target dedicated entirely to AI memory and vector retrieval.

## Documentation Index

- [Architecture Overview](ARCHITECTURE.md): Detailed breakdown of the system components and data flow.
- [Setup Guide](SETUP.md): Step-by-step instructions for installation, configuration, and connecting AI agents.
- [API Documentation](API.md): Comprehensive reference for the MCP capabilities and REST HTTP API.

## How It Works

The architecture relies on a hybrid stack to manage synchronization, embedding, and AI interaction efficiently without breaking encryption guarantees.

### 1. Headless Synchronization (Node.js)
The system utilizes a headless daemon powered by the official `@joplin/lib` package. 
* It authenticates securely with your central Joplin Server.
* It downloads the encrypted blobs and decrypts them entirely on your local machine using your Master Password.
* By hooking into Joplin's internal `ResourceService` and `Synchronizer` event emitters, it intercepts fully synced and decrypted notes in real-time.

### 2. Local Embedding Generation
Once a note is intercepted and decrypted, the Markdown text is passed through an embedding model (such as `nomic-embed-text` running locally via Ollama). This translates the textual content into a high-dimensional vector array representing the semantic meaning of the note.

### 3. Fast Vector Storage (SQLite + sqlite-vec)
Instead of relying on heavy external vector databases (like Milvus or dedicated MySQL vector extensions), the system leverages `sqlite-vec`—an embedded SQLite extension optimized for extremely fast vector similarity search.
* The system mirrors the decrypted text, metadata, and generated vector embeddings into a local `vector_memory.sqlite` database.
* Because the database runs embedded alongside the application, there is zero external infrastructure overhead, enabling instantaneous vector distance calculations for personal note collections.

### 4. AI Integration via FastMCP (Python)
A custom MCP server, built with FastMCP in Python, connects to the local SQLite database. 
* It loads the `sqlite-vec` extension and exposes custom tools to AI clients (like Gemini or Claude).
* **Semantic Search:** When the AI searches for a concept, the MCP server generates an embedding for the query and executes an accelerated SQLite vector search. It quickly returns the most semantically relevant notes based on distance calculations, providing the AI with deep context from your personal knowledge base.

## Security & Encryption Integrity

A core feature of this architecture is its adherence to Joplin's strict security model:
* **E2EE Preservation:** Your notes remain fully encrypted while resting on the central Joplin Server and while transmitting over the network.
* **Local-Only Decryption:** Decryption, vector generation, and vector storage occur strictly within the trusted boundary of your local network where the headless client is running. The central server is completely unaware of the AI indexing.

By running this system as a companion to your standard Joplin clients, you gain robust semantic search and AI interactivity without compromising the privacy of your personal data.
