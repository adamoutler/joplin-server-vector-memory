# API Documentation

The Joplin Server Vector Memory exposes an extensive API primarily via the Model Context Protocol (MCP) as well as a standardized REST-style HTTP API. 

## Base URLs and Authentication

- **Proxy URL (Sync Client)**: `http://<HOST>:3000` (provides dashboard, `/docs` Swagger UI, `/openapi.json`, `/llms.txt`)
- **Backend API Server**: `http://<HOST>:8000` (or the port explicitly set)
- **Authentication**: Most API interactions require a Bearer token generated from the sync client dashboard.
  - Header: `Authorization: Bearer <API_TOKEN>`

## Model Context Protocol (MCP) Capabilities

The primary way AI agents interact with the Joplin Memory Server is via MCP. The application provides multiple MCP transports to support different agents.

### Available MCP Endpoints

1. **Stateless HTTP** (e.g., Gemini CLI)
   - URL: `http://<HOST>:<BACKEND_PORT>/http-api/mcp`
2. **Streamable HTTP** (e.g., Cline, Claude, Windsurf)
   - URL: `http://<HOST>:<BACKEND_PORT>/http-api/mcp/stream`
3. **Server-Sent Events (SSE)** (e.g., Cursor)
   - URL: `http://<HOST>:<BACKEND_PORT>/http-api/mcp/sse`

### MCP Tools

When an AI agent connects via MCP, it gains access to the primary `joplin_notes_*` tools (and backward-compatible `notes_*` and `resources_*` aliases):

- **`joplin_notes_search(query: str, limit: int = 5)`** (alias: `notes_search`)
  - **Description**: Search Joplin notes semantically using natural language queries. Returns top notes with ID, Title, and relevant excerpt. Utilizes Reciprocal Rank Fusion combining sqlite-vec semantic search and FTS5 BM25 keyword matching.
- **`joplin_notes_get(note_id: str)`** (alias: `notes_get`)
  - **Description**: Get full text content, metadata, parent folder, and timestamps of a specific Joplin note by ID.
- **`joplin_notes_create(title: str, content: str, folder: Optional[str] = None)`** (aliases: `joplin_notes_remember`, `notes_remember`)
  - **Description**: Create, add, save, or remember a new note in Joplin. Relays to Joplin Server and immediately synchronizes to local vector storage.
- **`joplin_notes_update(note_id: str, content: str, update_mode: str = 'full note replacement', ...)`** (alias: `notes_update`)
  - **Description**: Update an existing Joplin note using optimistic concurrency control. Supports full replacement, partial replacement, append, and prepend modes.
- **`joplin_notes_request_deletion(note_id: str, reason: str)`** (alias: `notes_request_deletion`)
  - **Description**: Request deletion of a note (Step 1 of 2). Returns a short-lived `deletion_token` and confirmation title.
- **`joplin_notes_execute_deletion(deletion_token: str, confirm_title: str, safety_attestation: dict)`** (alias: `notes_execute_deletion`)
  - **Description**: Permanently delete a Joplin note (Step 2 of 2). Validates token, exact title, and safety attestation.
- **`joplin_notes_resource_get(resource_id: str)`** (alias: `resources_get`)
  - **Description**: Retrieve attachment/resource file metadata and content by ID.
- **`joplin_notes_resource_upload(title: str, data: str, mime_type: str = "application/octet-stream")`** (alias: `resources_upload`)
  - **Description**: Upload a new binary/text attachment to Joplin and receive a resource ID to embed in markdown notes (`[:/RESOURCE_ID]`).

---

## REST HTTP API

In addition to MCP, a RESTful JSON API is exposed under `/http-api`.

### Search Notes

- **Endpoint**: `POST /http-api/search`
- **Body Request**:
  ```json
  {
    "query": "how to cook pasta"
  }
  ```
- **Response**: Array of notes matching the query.
  ```json
  [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "title": "Pasta Recipe",
      "blurb": "Boil water, add pasta...",
      "distance": 0.123
    }
  ]
  ```

### Get Note

- **Endpoint**: `POST /http-api/get`
- **Body Request**:
  ```json
  {
    "note_id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```
- **Response**: Full note content.

### Create / Remember Note

- **Endpoint**: `POST /http-api/create` (or `POST /http-api/remember`)
- **Body Request**:
  ```json
  {
    "title": "New Recipe",
    "content": "# New Recipe\n\nIngredients..."
  }
  ```
- **Response**: Success status with new note ID.

### Update Note

- **Endpoint**: `POST /http-api/update`
- **Body Request (Partial Replacement)**:
  ```json
  {
    "note_id": "123e4567-e89b-12d3-a456-426614174000",
    "content": "boy who",
    "search_text": "computer who",
    "update_mode": "full note replacement",
    "last_modified_timestamp": 1728000000000,
    "summary_of_changes": "Replace computer who with boy who"
  }
  ```
- **Response**:
  ```json
  {
    "status": "success",
    "id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```

### Request Deletion

- **Endpoint**: `POST /http-api/request-deletion`
- **Body Request**:
  ```json
  {
    "note_id": "123e4567-e89b-12d3-a456-426614174000",
    "reason": "Note no longer needed"
  }
  ```
- **Response**: Returns a `deletion_token` and `confirm_title` needed for the next step.

### Execute Deletion

- **Endpoint**: `POST /http-api/execute-deletion`
- **Body Request**:
  ```json
  {
    "deletion_token": "token_from_request_deletion",
    "confirm_title": "Exact Note Title",
    "safety_attestation": {
      "content_hash": "sha256:...",
      "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
  }
  ```
- **Response**: Success status confirming deletion.
