# Client Module (`client/`)

## How it works
The `client` module is a Node.js application that acts as a headless Sync Client. It connects to an End-to-End Encrypted (E2EE) Joplin Server, downloads encrypted notes, and decrypts them locally using the user's Master Password. It also serves a dashboard UI and acts as a proxy for certain API requests to the Python backend.

## Dependencies
- Node.js
- `@joplin/lib` (for Joplin synchronization and decryption protocols)
- Express (for the dashboard and proxy server)
- `sqlite3` and `sqlite-vec` (for database and vector operations)

## What depends on it
- The Root module (`/`) depends on it for building the `client` Docker image.
- The `server/` module implicitly depends on the `client/` module to fetch, decrypt, and populate the local SQLite database that the Python server reads from.