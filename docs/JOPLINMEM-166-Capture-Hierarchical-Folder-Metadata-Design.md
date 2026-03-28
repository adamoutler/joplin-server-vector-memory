# Design Document: JOPLINMEM-166 - Capture Hierarchical Folder Metadata

## Status: Draft
## Date: 2026-05-20

## 1. Problem Statement
Joplin stores folder structures in a flat `folders` table with `parent_id` references. Currently, the `note_metadata` table in the vector memory store does not capture the full hierarchical path of a note's folder. Capturing this data as `folder_path` (e.g., `Work/Projects/2026`) and `parent_id` is essential for:
1. Providing better context for semantic search.
2. Supporting scoped searches (already partially implemented via `folders` table in server).
3. Displaying the note's location in search results.

## 2. Proposed Architecture

### 2.1 Database Schema Changes
The `note_metadata` table in both `client/src/sync.js` and `server/src/db.py` will be updated.

**Updated `note_metadata` Schema:**
```sql
CREATE TABLE IF NOT EXISTS note_metadata (
    rowid INTEGER PRIMARY KEY,
    note_id TEXT UNIQUE,
    title TEXT,
    content TEXT,
    parent_id TEXT,
    folder_path TEXT,
    updated_time INTEGER DEFAULT 0
)
```

**Migration Strategy:**
- In `server/src/db.py`, use `ALTER TABLE note_metadata ADD COLUMN ...` if the columns don't exist.
- In `client/src/sync.js`, the table is wiped during full syncs. For incremental syncs, we will add similar migration logic or rely on the next full sync to populate it if preferred (though migration is better for reliability).

### 2.2 Folder Path Resolution Algorithm
A performant in-memory resolution algorithm will be implemented in `client/src/sync.js` within the `generateEmbeddings` loop.

**Algorithm Detail:**
1. **Fetch all folders** from the Joplin SQLite database: `SELECT id, title, parent_id FROM folders`.
2. **Build an ID-to-Folder map**: `folderMap: Map<id, {title, parent_id}>`.
3. **Build a Path Cache**: `pathCache: Map<id, string>` (memoization).
4. **Resolution Function**:
   - For a given `folder_id`, recursively (or iteratively) build the path.
   - Use the `pathCache` to avoid redundant computations.
   - Example: `getFolderPath('folder_3')` -> resolves `folder_1/folder_2/folder_3`.

**Performance:**
- Thousands of notes can be processed efficiently as each unique folder path is computed exactly once.
- Time Complexity: $O(F)$ where $F$ is the number of folders.
- Space Complexity: $O(F)$ to store the map and cache.

### 2.3 Data Synchronization Flow
1. **`sync()` method**: Continues to sync raw data from Joplin Server to local `database.sqlite`.
2. **`generateEmbeddings()` method**:
   - Fetches folders and builds the path map.
   - Syncs folders to `vector_memory.sqlite` (to support recursive CTE searches in the server).
   - Fetches notes with `parent_id`.
   - Resolves `folder_path` for each note.
   - Includes `parent_id` and `folder_path` in the `validNotes` batch.
3. **`bulkUpsertVectors()` method**:
   - Updates `note_metadata` with the new fields.

## 3. Implementation Details

### 3.1 `client/src/sync.js` Changes
- Update `init()` table creation.
- Update `sync()` full-sync wipe and recreate.
- Update `generateEmbeddings()` to fetch folders and resolve paths.
- Update `bulkUpsertVectors()` and `upsertVector()` signatures and SQL.

### 3.2 `server/src/db.py` Changes
- Update `init_db()` schema and migration logic.

### 3.3 Example Resolution Logic (JS)
```javascript
const folders = await this.db.selectAll('SELECT id, title, parent_id FROM folders');
const folderMap = new Map(folders.map(f => [f.id, f]));
const pathCache = new Map();

function getFolderPath(folderId) {
    if (!folderId || folderId === '0' || folderId === '') return '';
    if (pathCache.has(folderId)) return pathCache.get(folderId);

    const folder = folderMap.get(folderId);
    if (!folder) return '';

    const parentPath = getFolderPath(folder.parent_id);
    const fullPath = parentPath ? `${parentPath}/${folder.title}` : folder.title;
    
    pathCache.set(folderId, fullPath);
    return fullPath;
}
```

## 4. Verification Plan

### 4.1 Automated Tests
1. **Unit Test (JS)**: Verify `getFolderPath` correctly resolves paths for various depths.
2. **Integration Test (JS)**: Verify `generateEmbeddings` populates `folder_path` in `note_metadata`.
3. **Migration Test (Python)**: Verify `server/src/db.py` correctly adds the new column to an existing database.

### 4.2 Manual Verification
- Run a sync on a profile with multiple folder levels.
- Query `note_metadata` manually to ensure `folder_path` is accurate.
- Perform a search using the MCP tool and verify `folder_id` (and potentially `folder_path` in the blurb/meta) is correct.
