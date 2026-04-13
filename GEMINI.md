# Joplin Server Vector Memory MCP - Gemini Methodology

This document outlines the methodology and guidelines for future AI incarnations (specifically Gemini CLI agents) working on this codebase.

## 1. Code Discovery & Context Gathering
- **Use Dedicated Tools:** Always use `glob`, `list_directory`, and `grep_search` rather than shelling out to `ls`, `find`, or `grep`. This reduces context bloat and ensures fast, targeted discovery.
- **Read Documentation First:** Before making any architectural changes, read the `1-GEMINI.md` files located in each major directory (`/client`, `/server`, `/client/src`, etc.). They define the boundaries, dependencies, and responsibilities of each module.

## 2. Refactoring & Code Quality
- **Legibility is Paramount:** Prioritize human readability. Use descriptive variable names, extract complex logic into smaller, well-named functions, and ensure consistent formatting.
- **Docstrings & JSDoc:** Any new functions or major changes to existing ones should be documented using standard Python docstrings or JSDoc comments to describe parameters, return types, and potential exceptions.
- **Behavior Preservation:** Refactoring should never alter external API contracts or break the E2EE encryption/decryption flows.

## 3. Execution & Testing
- **Validation:** Never assume a change works just by looking at it. Always run the test suites before claiming success.
  - For the Node.js client: `cd client && npm ci && npm test`
  - For the Python server: Ensure the `venv` is active, install requirements, and run `pytest`.
- **Iterative Commits:** Commit logical chunks of work with clear, descriptive commit messages.

## 4. Architectural Rules
- **No Passwords on Disk:** Remember that `joplinPassword` and `joplinMasterPassword` are strictly ephemeral. Never write them to `config.json`.
- **Vector DB Resilience:** The `sqlite-vec` database is treated as ephemeral. If corrupted, it should be wiped and rebuilt from the source notes.
- **Zero-Trust E2EE:** Do not expose decrypted note contents outside the local host environment except via the authenticated MCP interface.
