**Context/Reason:** To prevent blocking the main Node.js event loop and enhance server performance, synchronous file I/O operations must be converted to asynchronous equivalents.

In `client/src/index.js`, the Express middleware that validates incoming basic authentication reads the configuration file synchronously using `fs.readFileSync(CONFIG_PATH, 'utf8')`. This blocks the thread for every request checking authorization credentials. A similar synchronous read occurs in the `/status` route and inside the `startSync` logic. These need to be refactored to use `fs.promises.readFile` or `fs.readFile` with callbacks.

**CRITICAL INSTRUCTIONS:**
- DO NOT edit code outside the scope of this ticket.
- DO NOT run any unit tests. Wait for the `quality_control_agent` to handle testing execution according to the orchestration pipeline.

**Files to modify:**
* `client/src/index.js`:
  - Locate `fs.readFileSync(CONFIG_PATH, 'utf8')` within the `app.use` auth proxy middleware.
  - Refactor to use `fs.promises.readFile` in a `try...catch` block.
  - Apply similar asynchronous refactoring to `app.get('/status')`.
  - Refactor the auth cache or loading logic to either cache the config intelligently in-memory or read it asynchronously.

### Test Recommendations
* Modify or add tests in `client/tests/proxy.test.js` or `client/tests/dashboard.test.js` to perform concurrent requests to ensure the event loop is not blocked during configuration reads and that authorization resolves correctly.

### Definition of Done
* No instances of `fs.readFileSync` exist within Express request handling flows (`app.use` middleware or route handlers).
* The application continues to start correctly.
* The API correctly parses the asynchronous config for authentication without throwing `UnhandledPromiseRejection` warnings.
