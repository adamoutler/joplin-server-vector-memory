---
name: skillsafe-scanner
description: Run the skillsafe scan on the adamoutler/joplin-server-vector-memory package, then operate and improve/complete all issues identified. Use this when asked to scan or fix skillsafe issues.
---

# Skillsafe Scanner

This skill provides a comprehensive workflow to run the `npx skillsafe scan` command and automatically analyze, fix, and verify any issues identified in the `adamoutler/joplin-server-vector-memory` package.

## Workflow

1. Run the `skillsafe` scan command:
   ```bash
   npx skillsafe scan adamoutler/joplin-server-vector-memory
   ```
2. Wait for the command to complete and analyze its output for any identified issues.
3. For each issue identified in the scan:
   - Investigate the codebase using search tools (`grep_search`, `glob`) to understand the root cause of the issue.
   - Propose a fix for the issue.
   - Implement the fix using appropriate file editing tools.
   - Run project tests (e.g., `npm run test` in the client directory, or `pytest` in the server directory) to verify the fix did not break existing functionality.
4. Rerun the scan to verify the issue is resolved.
5. Provide a summary of the issues fixed and their resolutions to the user.
