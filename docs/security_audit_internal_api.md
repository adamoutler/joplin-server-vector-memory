# Security Audit: Internal Node API Auth Bypass

## Findings

During the security audit of the internal Node API routes (`/node-api/*`) and authentication bypass mechanisms in the Joplin Server Vector Memory MCP project, the following issues were identified:

1. **Missing Source IP Validation**: The initial implementation bypassed Basic Authentication solely based on the URL path (`req.path.startsWith('/node-api/')`). This allowed any external client reaching the Node.js port (3000) to access internal endpoints without authentication.
2. **Path Normalization and Case Sensitivity Bypass**: After an initial fix added `isLocalhost` checks based on `req.path.startsWith('/node-api/')`, a secondary vulnerability was identified. Express.js route handlers are case-insensitive and normalize slashes by default (e.g., `//node-api`, `/NODE-API/`). A malicious external actor could supply `/NODE-API/some-action` in the URI. This would fail the strict `startsWith('/node-api/')` string check (thus falling through to the Basic Auth prompt), but if they supplied valid (or intercepted/guessed) Basic Auth credentials, they would proceed to the route handler which *does* match `/NODE-API/` case-insensitively, bypassing the localhost restriction entirely.

## Hardening Measures Implemented

To remediate these issues, the codebase was hardened with the following measures in `client/src/index.js`:

1. **Express Router-Level Middleware**: The manual `req.path.startsWith()` check was replaced with an Express router-level middleware `app.use('/node-api', ...)` placed *before* the general authentication middleware. This delegates path normalization and case-insensitive matching to the robust Express routing engine.
2. **Strict IP Whitelisting**: Inside the `/node-api` middleware, `req.socket.remoteAddress` is strictly validated. The connection is forcibly rejected with a `403 Forbidden` if it does not originate from a local loopback address (`127.0.0.1`, `::1`, or `::ffff:127.0.0.1`).
3. **Internal Flagging**: If the IP check passes, the request is flagged with `req.isInternalApi = true`. The subsequent Basic Authentication middleware simply checks this flag to safely bypass the auth challenge for internal Python MCP server traffic.

## Conclusion

The `/node-api/*` endpoints are now securely restricted to internal loopback traffic. External requests, regardless of whether they provide valid Basic Auth credentials or attempt path spoofing techniques, will be accurately intercepted and blocked.
