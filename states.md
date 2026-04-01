## Overview
The container starts with a default "setup" username and password. On login, the user enters a server, username, password, and optional E2E encryption password.  The container is then married and begins normal operation. 

The normal opertaion is the The container syncs from Joplin Server to a local database. The local database is then turned into a vector database. During normal operation the database is synced and indexes are updated. 

## States:
States combine the happy path and the unhappy path. The primary numbered items contain the happy path. The bullets are exceptions and cause the system to start over from the beginning

### Sync
**Startup Flow**
Unmarried -> Waiting for credentials -> Sync -> Ready (Trigger Index)

**States**
1. Unmarried - the container has not been locked to a user - progression = a lock file exists.
2. Waiting For Credentials - the container is locked to a particular user - progression = a user logs in and credentials are gained
3. Sync - the sync routine has begun - progression = sync is completed
4. Sync Ready -> start **Index**
**Sync Exceptions**
* Database write error - wipe and restart
* At login lock file does not exist but a database does - wipe and restart
* error during sync - restart container
* Invalid credentials provided - ignore and wait


### Index
**Index Flow**
Not Available -> Indexing -> Ready

**Index**
1. Not Available - the system has never been indexed or has not been checked - progression = a valid vector db exists
2. Indexing - the system is currently being indexed - progression = indexing routine has completed all synced files
3. Ready - The system is ready for operation - progression = restart index flow due to sync or error. 
**Index Exceptions**
* Cannot write to VectorDB - blow it away and create a new one
* Cannot read VectorDB - blow it away and create a new one
* VectorDB returns bad data - blow it away and create a new one


### Settings
**Sync**
* A change occurred - remove entire db and resync
**Index**
* A change occurred - remove entire vectordb and resync


## Credentials Contract

This contract defines exactly what is persisted to disk vs. what lives in volatile memory only.
Violating this contract is a security regression. See `code-logic.md` item #13 and #15.

| Field | Storage | Notes |
|---|---|---|
| `joplinUsername` (email) | `config.json` (disk) | Acts as the marriage lock. Persists across all restarts. Cannot be changed without a factory wipe. |
| `joplinServerUrl` | `config.json` (disk) | Required to know where to relay credentials for validation on restart. |
| `joplinPassword` | `globalCredentials` (RAM only) | **NEVER written to disk.** Discarded on container restart. |
| `joplinMasterPassword` | `globalCredentials` (RAM only) | **NEVER written to disk.** Discarded on container restart. |
| `api_keys` | `config.json` (disk) | Bearer tokens for the MCP interface. No password material. |

### What Happens on Container Restart

1. Container starts. `globalCredentials` is empty (volatile memory is cleared).
2. `config.json` is read. If `joplinPassword` or `joplinMasterPassword` fields are found (legacy), they are immediately scrubbed and the file is rewritten.
3. Because `joplinUsername` exists in `config.json`, the system enters **"Waiting for credentials"** state. Sync does **not** auto-start.
4. User opens the dashboard. Browser prompts for Basic Auth (`WWW-Authenticate: Basic realm=...`).
5. User enters their Joplin Server username and password.
6. Auth middleware checks: username matches the marriage lock. Password is relayed to Joplin Server (`/api/sessions`) for real-time validation.
7. On success: password is stored in `globalCredentials` (RAM). `onAuthSuccess()` fires and auto-starts sync.
8. Container is now in normal operation. Steps 1-3 repeat on next restart.