# Client Source Code (`client/src/`)

## How it works
This directory contains the core logic for the Node.js Sync Client. 
- `index.js` sets up the Express server, manages rate limiting, proxies requests to the Python backend, handles authentication and session state, and exposes endpoints for note and resource management.
- `sync.js` defines the `JoplinSyncClient` class, which uses the official `@joplin/lib` to perform synchronization, decryption, and embedding generation (which it outsources to the Python server via an internal API). It writes the final decrypted text and embeddings into the local SQLite database.

## Dependencies
- Express, CORS, HTTP Proxy Middleware
- `@joplin/lib` components (SyncTarget, Decryption, BaseModel, etc.)
- SQLite native bindings

## What depends on it
- The `client/tests/` module depends on this source code to execute tests.
- The compiled/running `client` container executes `index.js` as its entrypoint.