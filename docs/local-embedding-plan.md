# Local Embeddings & Ollama Independence

## Objective
The system must be fully self-contained by default. Relying on an external or composed Ollama container should be strictly optional. The `app` container should generate embeddings using a lightweight, in-process local Python library by default, but allow users to supply an `OLLAMA_URL` (like `http://192.168.1.101:11434`) if they want to offload embeddings.

## Architectural Changes

### 1. Python Server (`server/src/main.py`)
- **Dependencies**: Add `sentence-transformers` and `torch` (or a lighter ONNX runtime) to `server/requirements.txt` to run embeddings directly in Python.
- **Unified Embedding Logic**: Update `get_embedding(text)` in `main.py`:
  - If `OLLAMA_URL` is set, use the existing Ollama client logic.
  - If `OLLAMA_URL` is NOT set, use `sentence-transformers` (e.g., `all-MiniLM-L6-v2`) to generate the embedding natively.
- **Internal API**: Expose a new route `POST /http-api/internal/embed` so the Node.js daemon can ask the Python server for embeddings without knowing the underlying provider.

### 2. Node.js Daemon (`client/src/sync.js`)
- Remove all Ollama-specific logic (e.g., checking `/api/tags`, specific Ollama error handling).
- Update the `fetch()` call in `generateEmbeddings()` to query the local Python backend at `http://127.0.0.1:8000/http-api/internal/embed`.
- This makes the Node.js client entirely agnostic to the embedding provider.

### 3. Docker & Configuration
- **`docker-compose.yml`**: Remove the `ollama` service entirely. Remove the `depends_on: ollama` from the `app` service. The default deployment is now just the single `app` container.
- **`tests/docker-compose.test.yml`**: Keep or adjust the `ollama` container specifically for testing external provider behavior, or drop it to speed up tests by relying on the internal CPU embedder.