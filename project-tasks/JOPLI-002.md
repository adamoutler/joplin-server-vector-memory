**Context/Reason:** To improve maintainability and adherence to separation of concerns, the hardcoded HTML template in the root route of the Express server needs to be extracted.

Currently, in `client/src/index.js`, the `app.get('/')` route handler responds with a massive, inline ES6 template literal containing HTML, CSS, and client-side JavaScript. This makes the backend code difficult to read, lint, and maintain. 

**CRITICAL INSTRUCTIONS:**
- DO NOT edit code outside the scope of this ticket.
- DO NOT run any unit tests. Wait for the `quality_control_agent` to handle testing execution according to the orchestration pipeline.

**Files to modify:**
* `client/src/index.js`:
  - Remove the inline HTML string from `app.get('/')`.
  - Configure Express to serve static files from a new directory (e.g., `client/public` or `client/views`).
  - Send the newly created file when the user visits the root route.
* `client/public/index.html` (New File):
  - Move the extracted HTML/CSS/JS content here. Ensure all references remain intact so frontend functionality (status fetching, auth rotation) works perfectly.

### Test Recommendations
* Add an integration test in `client/tests/dashboard.test.js` or equivalent to assert that `GET /` returns the correct HTML content with `Content-Type: text/html`.

### Definition of Done
* The Express root route (`/`) serves the HTML from an external file rather than an inline string.
* All existing frontend functionality (status polling, form submission, token rotation) continues to work without regressions.
* `curl http://localhost:3000/` successfully returns the HTML document.
