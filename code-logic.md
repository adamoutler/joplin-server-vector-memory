# Code Logic Validation

1. **setup user default. hard code username/password. Accept it only if the storage lock file isn't present.**
   - **Validation:** TRUE
   - **Details:** Verified in `client/src/index.js`. The `isSetupMode` boolean strictly ensures the 'setup' user is only allowed if `config.json` doesn't contain a `joplinUsername`. 

2. **when lock file is created, it cannot be recreated. changing username in setup causes a failure to save.**
   - **Validation:** TRUE
   - **Details:** Verified. The `/auth` endpoint enforces a strict check against `proxyConfig.joplinUsername`. If an existing lock exists, the endpoint returns a 400 Bad Request, preventing modification.

3. **there is only one method used to set the username and it becomes inactive (unable to set the username) after the lock file is created**
   - **Validation:** TRUE
   - **Details:** Verified. `/auth` is the only setup endpoint. Once married, it rejects requests that attempt to change the username.

4. **the lock file has the user's name in it (or email address) after container is paired to a username.**
   - **Validation:** TRUE
   - **Details:** Verified. The `config.json` file securely stores the user's email/username under the `joplinUsername` key upon successful setup.

5. **logging in checks if there is a lock file. and requries that specific username, and only that specific username in the lock file is allowed.**
   - **Validation:** TRUE
   - **Details:** Verified. Authentication middleware in the proxy blocks any `reqUser` that does not perfectly match `proxyConfig.joplinUsername`.

6. **that user name is required forever until the container is wiped (NOTE THIS IS DIFFERENT FROM REINDEX).**
   - **Validation:** TRUE
   - **Details:** Verified. The requirement persists indefinitely. A full wipe via `/auth/wipe` is the only mechanism to clear the configuration.

7. **When the container is wiped the entire volume is cleared. nothing remains. The container is rebooted to clear states.**
   - **Validation:** TRUE
   - **Details:** Verified. `/auth/wipe` performs an exhaustive recursive deletion of all contents inside `DATA_DIR` and then executes `process.exit(0)`, relying on the Docker orchestration to reboot a clean container.

8. **When the user is logged in they may choose any option leading to a reindex, which requires them to type REINDEX, and deletes everything stored, relating to the vector db.**
   - **Validation:** TRUE
   - **Details:** Verified. The UI enforces the `REINDEX` textual confirmation, and the backend explicitly drops `vec_notes`, `notes_fts`, and `note_metadata` tables.

9. **Any option which changes settings that lead to a reindex uses an entirely separate API from the sync settings. Sync is an entirely separate api.**
   - **Validation:** TRUE
   - **Details:** Verified. Reindex triggers through `/api/reindex` (handled by Python), whereas sync properties navigate through `/api/settings` and trigger the isolated `sync.js` engine.

10. **After sync, the indexing must occur always, if for some reason a full sync occurs and the vector db exists, the vector db must be deleted and recreated.**
    - **Validation:** TRUE
    - **Details:** Verified. `client/src/sync.js` explicitly checks `isFullSync` and drops the vector and metadata tables prior to pulling the full payload.

11. **Any user not specified in the lock file is denied access, unless a lock file does not exist and then setup is used.**
    - **Validation:** TRUE
    - **Details:** Verified. Covered by the middleware proxy checks that enforce `isSetupMode` exclusivity.

12. **While user is specified in a lock file, login requires the correct user and correct password.**
    - **Validation:** TRUE
    - **Details:** Verified. The credentials intercepted by Basic Auth are securely relayed to the remote Joplin Server to validate the session for every request.k file, the user's password is not stored on the system, instead it is verified in real time with the joplin server, in order to grant access to the status page.**
    - **Validation:** TRUE
    - **Details:** The password is stored only in volatile memory (`globalCredentials`) and is explicitly omitted from `config.json`. If missing from RAM, it relies on real-time `/api/sessions` validation against the Joplin Server.

13. **Accessing the status page should trigger a sync, and retain the user's password from the login operation to use for syncing to joplin server.**
    - **Validation:** FALSE
    - **Details:** While the user's password IS retained in memory after login, accessing the status page (`/status` endpoint) is purely passive and does not proactively trigger a sync. A Kanban ticket has been created to implement explicit sync triggering upon UI access.