**Context/Reason:** To secure the proxy middleware, a bug that can bypass authentication when the environment variable `JOPLIN_SERVER_URL` is undefined must be fixed.

In `client/src/index.js`, the Express proxy middleware starts with:
```javascript
app.use(async (req, res, next) => {
  const joplinUrl = process.env.JOPLIN_SERVER_URL;
  if (!joplinUrl) {
    return next();
  }
...
```
If a user configures their Joplin Server URL through the web dashboard, the value is saved to `config.json` and `process.env.JOPLIN_SERVER_URL` may remain undefined. In this state, the authentication middleware returns `next()` immediately without validating any Authorization headers, leaving the MCP backend fully exposed and bypassing the intended security.

**CRITICAL INSTRUCTIONS:**
- DO NOT edit code outside the scope of this ticket.
- DO NOT run any unit tests. Wait for the `quality_control_agent` to handle testing execution according to the orchestration pipeline.

**Files to modify:**
* `client/src/index.js`:
  - Modify the authentication middleware to resolve the `joplinUrl` from the persistent `config.json` file if `process.env.JOPLIN_SERVER_URL` is undefined.
  - Only call `return next()` without authenticating if *neither* the environment variable nor the config file have a Joplin Server URL defined (which should technically be an invalid state for operation).

### Test Recommendations
* Add a test in `client/tests/proxy.test.js` where `process.env.JOPLIN_SERVER_URL` is explicitly unset, but the config file is populated, to verify that requests lacking an Authorization header correctly receive an HTTP 401 response instead of bypassing to the backend.

### Definition of Done
* The proxy middleware enforces authentication even when `JOPLIN_SERVER_URL` is solely defined in `config.json`.
* An automated test verifies this security edge case.
