---
name: joplin-mcp-architecture
description: Architectural flow and state machine for Joplin MCP Server
---

# Joplin MCP Server Architecture

## Boot Up and State Machine

1. **Cold-Boot/Unmarried State:**
   - Hard-coded username/password: `setup` / `1-mcp-server`.
   - The server is "unmarried" (default state).

2. **Login and Setup:**
   - When users log in for the first time, they enter their Joplin Server URL, username, and password.
   - The server checks these credentials against the Joplin server.
   - If successful, the server stores these credentials and becomes "married" to this user. Their data alone resides on it.
   - The server restarts.

3. **Waiting for Credentials State:**
   - Every boot up, the server comes up into a waiting-for-credentials state.
   - The user logs in using the Basic Auth realm text box.
   - The server checks these credentials against Joplin. If successful, the user logs in and the credentials are used to initiate the sync.

4. **Sync and Embedding Flow:**
   - **Syncing:** Sync is in-progress.
   - **Check Vector DB:** Upon sync completion, the vector database is checked for needed updates.
   - **Embedding:** The server sync status becomes `ready`. Embedding is in-progress.
   - **Ready:** Upon embedding completion, the embedding status becomes `ready`.

## Expected Behaviors and Error Handling

Every boot up, the server should wait for credentials, then initialize the Joplin sync with them. 

### Sync vs Embedding Errors
- **Sync Problems:** Handled by Joplin (assuming our side is correct) -> **Retry**.
- **Embedding Problems:** Handled by blowing away the vector DB and **Reindexing**.

### Things We Cannot Handle (Return Error)
- Read/write errors -> Sync/embedding error.
- Network issues -> Sync/embedding error.
- Credentials changed -> Sync error.
- Hardware failure -> Unpredictable random error.

### Expected Things We Must Handle
- **Index is complete, but a new note was synced:** Update the index.
- **Index is complete, but a note was deleted:** Update the index.
- **Missing embedding database:** Create the index.
- **Missing credentials for sync:** Wait for credentials.
- **No credentials (no sync) but request made using API key:** Serve the response (stateless processing allowed).
- **Change of chunking strategy or model (Save & Validate):** Wipe index and Reindex.

## Developer Rules
- `reindex` should NOT trigger changes to sync logic. It should strictly affect the vector database/embeddings.
- `Save & Validate` (updating configurations, credentials, models) should wipe the index to ensure consistency.