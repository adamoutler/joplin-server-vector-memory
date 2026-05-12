# Client Tests (`client/tests/`)

## How it works
This module contains the automated test suites for the Node.js Sync Client. It verifies the functionality of the Express server (`index.js`), the synchronization client (`sync.js`), and their various edge cases (like authentication flows, chunking, proxy behavior, and backoff logic).

## Dependencies
- Jest (or similar JavaScript testing framework)
- Supertest (for API testing)
- Mocked `@joplin/lib` dependencies

## What depends on it
- The CI/CD pipeline (Root module) depends on these tests passing before allowing merges or releases.