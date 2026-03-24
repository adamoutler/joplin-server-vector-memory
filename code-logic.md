# Code Logic Validation

1. **setup user default. hard code username/password. Accept it only if the storage lock file isn't present.**
   - **Validation:** FALSE
   - **Details:** The system currently allows the `setup` user to bypass the lock even after `config.json` is created, as a fallback mechanism. A Kanban ticket has been created to fix this.

2. **when lock file is created, it cannot be recreated. changing username in setup causes a failure to save.**
   - **Validation:** FALSE
   - **Details:** Currently, submitting a new username through the setup UI does not fail to save; instead, it triggers a wipe of the local data and updates the config to the new username. A Kanban ticket has been created to block username modifications after the initial lock.

3. **there is only one method used to set the username and it becomes inactive (unable to set the username) after the lock file is created**
   - **Validation:** FALSE
   - **Details:** The `/auth` endpoint remains active and currently allows changing the username (by wiping data). A Kanban ticket has been created to enforce this claim.

4. **the lock file has the user's name in it (or email address) after container is paired to a username.**
   - **Validation:** TRUE
   - **Details:** `config.json` stores the paired user's email/username under the `joplinUsername` key.

5. **logging in checks if there is a lock file. and requries that specific username, and only that specific username in the lock file is allowed.**
   - **Validation:** FALSE
   - **Details:** While the middleware checks if `joplinUsername` matches the provided username, it currently contains a loophole for the `setup` user. Ticket created to enforce strict lock.

6. **that user name is required forever until the container is wiped (NOTE THIS IS DIFFERENT FROM REINDEX).**
   - **Validation:** TRUE
   - **Details:** The username restriction persists across reindexing (which only drops DB tables) and requires a full wipe (`/auth/wipe`) or a username change (which currently triggers a wipe) to clear.

7. **When the container is wiped the entire volume is cleared. nothing remains. The container is rebooted to clear states.**
   - **Validation:** FALSE
   - **Details:** The `/auth/wipe` endpoint only deletes specific files (`config.json`, the DB, and profile dir), not the entire volume, and it does not reboot the container. A Kanban ticket has been created to address this.

8. **When the user is logged in they may choose any option leading to a reindex, which requires them to type REINDEX, and deletes everything stored, relating to the vector db.**
   - **Validation:** TRUE
   - **Details:** Updating critical RAG settings or restoring defaults prompts a modal requiring the user to type "REINDEX". The backend then runs `reset_database`, dropping all vector DB tables.

9. **Any option which changes settings that lead to a reindex uses an entirely separate API from the sync settings. Sync is an entirely separate api.**
   - **Validation:** TRUE
   - **Details:** Reindex settings (`embedding`, `chunkSize`, `chunkOverlap`) are managed via `/api/reindex` utilizing `ReindexRequest`, while general sync settings are managed via `/api/settings`. The NodeJS proxy handles the sync engine directly.

10. **After sync, the indexing must occur always, if for some reason a full sync occurs and the vector db exists, the vector db must be deleted and recreated.**
    - **Validation:** FALSE
    - **Details:** The system currently performs incremental embedding updates based on `updated_time`, even if a "full sync" fetch is performed, and does not explicitly delete/recreate the vector db just because a full sync occurs. A Kanban ticket has been created to address this logic.

11. **Any user not specified in the lock file is denied access, unless a lock file does not exist and then setup is used.**
    - **Validation:** FALSE
    - **Details:** Setup is currently allowed even when the lock file exists. Addressed by the ticket for Claim 1.

12. **While user is specified in a lock file, the user's password is not stored on the system, instead it is verified in real time with the joplin server, in order to grant access to the status page.**
    - **Validation:** TRUE
    - **Details:** The password is stored only in volatile memory (`globalCredentials`) and is explicitly omitted from `config.json`. If missing from RAM, it relies on real-time `/api/sessions` validation against the Joplin Server.

13. **Accessing the status page should trigger a sync, and retain the user's password from the login operation to use for syncing to joplin server.**
    - **Validation:** FALSE
    - **Details:** While the user's password IS retained in memory after login, accessing the status page (`/status` endpoint) is purely passive and does not proactively trigger a sync. A Kanban ticket has been created to implement explicit sync triggering upon UI access.