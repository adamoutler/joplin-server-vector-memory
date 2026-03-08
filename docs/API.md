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

When an AI agent connects via MCP, it gains access to the following tools:

- **`search_notes(query: str)`**
  - **Description**: Search notes semantically using the provided query. Returns the top 5 notes with their ID, Title, and a Blurb. It utilizes Reciprocal Rank Fusion of vector and FTS matching.
- **`get_note(note_id: str)`**
  - **Description**: Get the full text content of a specific note by ID.
- **`remember(title: str, content: str)`**
  - **Description**: Save a new note into the memory bank. (Currently mocks relaying to Joplin Server by directly inserting into local SQLite).
- **`delete_note(note_id: str)`**
  - **Description**: Delete a note by its ID.

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

### Remember Note

- **Endpoint**: `POST /http-api/remember`
- **Body Request**:
  ```json
  {
    "title": "New Recipe",
    "content": "# New Recipe\n\nIngredients..."
  }
  ```
- **Response**: Success status with new note ID.

### Delete Note

- **Endpoint**: `POST /http-api/delete`
- **Body Request**:
  ```json
  {
    "note_id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```
- **Response**: Success status confirming deletion.
