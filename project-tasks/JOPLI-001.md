**Context/Reason:** To improve API performance and reduce unnecessary disk I/O, the configuration reading logic must be optimized.

Currently, in `server/src/main.py`, the `get_config()` function reads `/app/data/config.json` synchronously from disk on every invocation. Since `get_config()` is called by `get_embedding()`, which in turn is called during `search_notes()` and `remember()`, every single search or insert operation forces a disk read. Additionally, `verify_token()` also reads the same config file from disk for every authenticated request. This introduces significant latency and blocks the thread.

**CRITICAL INSTRUCTIONS:**
- DO NOT edit code outside the scope of this ticket.
- DO NOT run any unit tests. Wait for the `quality_control_agent` to handle testing execution according to the orchestration pipeline.

**Files to modify:**
* `server/src/main.py`:
  - Implement a caching mechanism (e.g., using `@lru_cache`, or a global module-level config dictionary) for `get_config()`.
  - Refactor `verify_token()` to use the cached configuration instead of reading the file on every request.
  - Ensure there is a way to invalidate or reload the cache if the file changes, or at least document the cache TTL behavior.

### Test Recommendations
* Add a test case in `server/tests/test_server.py` or equivalent to assert that `config.json` is only read once during multiple consecutive API calls.

### Definition of Done
* `get_config()` uses a cached configuration mechanism.
* `verify_token()` uses a cached configuration mechanism.
* A performance or unit test verifies the reduced file system reads.
* Application starts successfully and `search_notes` runs without errors.
