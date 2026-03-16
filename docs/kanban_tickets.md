# Ticket 1: Add Unified Resource Retrieval to MCP Server

## Objective
The server should be capable of fetching *any* attached file/resource on demand from the Joplin API (e.g., images, scripts, markdown, PDFs). Rather than having file-type specific tools, the MCP server will utilize a single unified retrieval method that dynamically maps the file to the appropriate native MCP content block based on its MIME type. 

## Pattern Recommendation: Unified MIME-Type Dispatching
By dynamically mapping Joplin resource MIME types to standard MCP `TextContent`, `ImageContent`, and `EmbeddedResource` blocks, AI agents will seamlessly pack, pass, and read markdown files, executable scripts, images, and documents between each other using a single retrieval mechanism.
* **Context Efficiency:** Resources are fetched strictly on-demand, preventing database bloat.
* **Network Restraints:** Prevents AI egress failures by returning raw or encoded data directly into context rather than a local URL.

## Implementation Strategy

### Task 1: Create a `list_note_resources` Tool
* **Goal:** Allow the AI to inspect which resources are attached to a given note.
* **Implementation:** Add a new `@mcp.tool()` that calls `GET /notes/{note_id}/resources` on the Joplin API.
* **Output:** A JSON array of resource metadata (IDs, titles, file extensions, and mime types).

### Task 2: Create a Unified `get_resource` Tool
* **Goal:** Allow the AI to retrieve a specific file by its resource ID.
* **Implementation:** 
  1. Add a new `@mcp.tool()` taking `resource_id`.
  2. Call `GET /resources/{resource_id}` on the Joplin API to fetch metadata (specifically the mime type).
  3. Call `GET /resources/{resource_id}/file` to fetch the raw file data.
  4. Implement a dynamic dispatch router based on MIME type:
      * **Text & Scripts (`text/*`, `application/json`, `.sh`, `.md`):** Read as UTF-8 string and return an MCP `TextContent` block.
      * **Images (`image/jpeg`, `image/png`):** Read as binary, base64 encode, and return an MCP `ImageContent` block.
      * **PDFs & Binaries (`application/pdf`, etc):** Read as binary, base64 encode, and return an MCP `EmbeddedResource` block strictly containing the raw binary data.

### Task 3: API Authentication Plumbing
* **Goal:** Authenticate the requests properly with the upstream Joplin Server.
* **Implementation:** Extend the existing config caching logic inside `main.py` so the new tools can seamlessly retrieve `joplinServerUrl` and `joplinToken` required to hit the `GET /resources` API endpoints.

---

# Ticket 2: Implement Event-Based Polling Synchronization

## Background
Currently, the synchronization process (`startSync` in `index.js`) executes a full `@joplin/lib` sync (`syncClient.sync()`), followed by `decrypt()`, and then calls `generateEmbeddings()`. The current `generateEmbeddings()` method queries *all* decrypted notes and blindly pushes them to Ollama to generate embeddings. Running this on an interval is extremely heavyweight and resource-intensive. 

We need to transition to a lightweight polling architecture using the Joplin Server `/events` endpoint.

## Architectural Plan

### 1. Cursor State Management
- **Storage:** Persist the `cursor` returned by the `/events` endpoint so it survives restarts. This can be added to `config.json` or a new metadata table in the local `vector.sqlite` database.
- **Initial Bootstrap:** 
  - On the very first run (when no cursor exists), execute the existing full sync, decrypt, and full embedding generation.
  - Immediately after the initial sync completes, call `GET <JOPLIN_SERVER_URL>/api/events` (without a cursor) to fetch the latest `cursor` and store it.

### 2. Implement the Polling Loop
- In `client/src/index.js`, introduce a `setInterval` loop that fires every 30–60 seconds.
- The loop will make an authenticated request to `GET <JOPLIN_SERVER_URL>/api/events?cursor=<stored_cursor>`.
- **Pagination handling:** If the response includes `"has_more": true`, loop to fetch the next page of events immediately using the new cursor.

### 3. Delta Processing & Targeted Sync
When the `/events` endpoint returns items, filter them for `item_type === 1` (Notes):
- **If no note events exist:** Update the stored cursor and do nothing else.
- **If note events exist:**
  1. Trigger `syncClient.sync()` and `syncClient.decrypt()` to pull down the updated encrypted notes and decrypt them locally.
  2. Parse the events to categorize the affected `item_id`s:
     - **Created (`type: 1`) & Updated (`type: 2`):** Pass these specific `item_id`s to a newly optimized embedding function.
     - **Deleted (`type: 3`):** Remove these notes directly from the Vector DB (`DELETE FROM note_metadata WHERE note_id = ?`).

### 4. Refactor `generateEmbeddings()`
- **Current state:** `SELECT id, title, body FROM notes WHERE encryption_applied = 0` (processes all notes).
- **Required Change:** Modify `generateEmbeddings(noteIds = null)` to optionally accept an array of IDs. 
- If `noteIds` is provided, alter the query to target only the changed notes (e.g., `WHERE encryption_applied = 0 AND id IN (...)`). This stops the client from re-embedding the entire vault on every change.

## Acceptance Criteria
- [ ] `last_event_cursor` is persistently stored and read on boot.
- [ ] A polling mechanism checks the `/events` endpoint every 30s-60s.
- [ ] `generateEmbeddings` is refactored to support targeted updates for specific note IDs.
- [ ] Sync and embedding generation are skipped entirely if no Note-related events are found during a poll.
- [ ] Deletion events properly remove records from the SQLite vector database.