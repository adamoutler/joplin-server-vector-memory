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

---

# Ticket 3: Security Audit: Internal Node API Auth Bypass (79b430a0-656f-4c3a-8b4f-987173015ade)

## Objective
Perform a detailed security inspection and audit of the internal-only routes (`/node-api/*`) and the authentication bypass mechanisms in `client/src/index.js` to ensure they are not vulnerable to exploitation. Implement hardening measures to strictly prevent external access.

## Implementation Strategy
* Identify path-matching bypass vulnerabilities related to Express.js normalization and case-sensitivity.
* Implement an Express.js router-level middleware `app.use('/node-api', ...)` prior to Basic Auth evaluation.
* Strictly enforce that `req.socket.remoteAddress` is a local loopback IP (`127.0.0.1`, `::1`, etc.).
* Block unauthorized requests with a `403 Forbidden` response.
* Document the security findings and mitigations in `docs/security_audit_internal_api.md`.

## Acceptance Criteria
- [x] Security audit completed and documented in `docs/security_audit_internal_api.md`.
- [x] Path normalization bypasses fixed via robust `app.use('/node-api')` routing.
- [x] Only traffic originating from `localhost` is permitted to access `/node-api/*`.
- [x] Test execution passes, and QA artifacts (screenshots and `test-results.json`) are provided.
- [x] Commits pushed to the repository.

---

# Ticket JOPLINMEM-176: Optimize MCP Help Response Structure and Terminology (c3de5d47-142b-451d-b73e-cd0593d97ed6)

## Objective
Optimize the MCP `help` response that returns project metadata to improve parsing efficiency and reduce token overhead.

## Implementation Strategy
1. **Collapse JSON into relevant units:** Group `states` and `labels` directly inside their respective `project` object.
2. **Don't pretty print:** Send minified JSON to the `llmContent` stream.
3. **Remove conversational filler:** Eliminate descriptive/chatty messages from the payload.
4. **Convert display output:** Format the terminal output as `[PROJECT_SLUG] - [Description]`.
5. **Proper terminology:** Change `identifier` to `project_slug`.

## Definition of Done
- [x] JSON response is strictly minified.
- [x] `states` and `labels` are appropriately nested within the `project` object.
- [x] Output is purely parsable JSON with absolutely zero conversational filler.
- [x] The key uses `"project_slug"` instead of `"identifier"`.
- [x] QA artifacts verifying this output are generated and stored in `docs/qa/JOPLINMEM-176-proof.json`.
