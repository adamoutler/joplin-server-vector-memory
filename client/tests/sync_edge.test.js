const sqlite3 = require('sqlite3');
const sqliteVec = require('sqlite-vec');
const { JoplinSyncClient } = require('../src/sync.js');

jest.mock('@joplin/lib/shim-init-node', () => ({
  shimInit: jest.fn(),
}));

jest.mock('@joplin/lib/models/Setting', () => ({
  default: {
    setConstant: jest.fn(),
    setValue: jest.fn(),
    value: jest.fn().mockReturnValue(9),
    load: jest.fn().mockResolvedValue(),
    setKeychainService: jest.fn(),
  },
}));

describe('sync.js edge coverage', () => {
  let client;
  let vectorDb;

  beforeEach((done) => {
    client = new JoplinSyncClient({
      serverUrl: 'http://test',
      username: 'user',
      password: 'pass',
      profileDir: '/tmp/test-profile'
    });

    vectorDb = new sqlite3.Database(':memory:', (err) => {
      if (err) return done(err);
      sqliteVec.load(vectorDb);
      vectorDb.serialize(() => {
        vectorDb.run(`CREATE TABLE IF NOT EXISTS note_metadata (
          rowid INTEGER PRIMARY KEY,
          note_id TEXT UNIQUE,
          title TEXT,
          content TEXT,
          parent_id TEXT,
          folder_path TEXT,
          updated_time INTEGER DEFAULT 0
        )`);
        vectorDb.run(`CREATE TABLE IF NOT EXISTS folders (
          id TEXT PRIMARY KEY,
          title TEXT,
          parent_id TEXT
        )`);
        vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
          title,
          content,
          content="note_metadata",
          content_rowid="rowid"
        )`);
        vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[3])`, done);
      });
    });

    client.vectorDb = vectorDb;
    client._vecNotesCreated = true;
  });

  afterEach((done) => {
    if (vectorDb) {
      vectorDb.close(done);
    } else {
      done();
    }
  });

  it('buildFolderPathLookup resolves nested folder paths and handles caching', () => {
    const folders = [
      { id: 'f1', title: 'Work', parent_id: '' },
      { id: 'f2', title: 'Projects', parent_id: 'f1' },
      { id: 'f3', title: 'MCP', parent_id: 'f2' },
      { id: 'f4', title: 'Standalone', parent_id: null }
    ];

    const lookup = client.buildFolderPathLookup(folders);
    expect(lookup.get('f1')).toBe('Work');
    expect(lookup.get('f2')).toBe('Work/Projects');
    expect(lookup.get('f3')).toBe('Work/Projects/MCP');
    expect(lookup.get('f4')).toBe('Standalone');
  });

  it('upsertVector inserts a new note then updates existing note', async () => {
    const embedding = [0.1, 0.2, 0.3];

    // 1. Insert new
    await client.upsertVector('note_1', 'Note One', 'Content 1', embedding, 1000, 'f1', 'Work');

    const row = await new Promise((resolve, reject) => {
      vectorDb.get('SELECT * FROM note_metadata WHERE note_id = ?', ['note_1'], (err, r) => {
        if (err) reject(err); else resolve(r);
      });
    });
    expect(row).toBeDefined();
    expect(row.title).toBe('Note One');
    expect(row.folder_path).toBe('Work');

    // 2. Update existing
    await client.upsertVector('note_1', 'Note One Updated', 'Content 1 Updated', embedding, 2000, 'f1', 'Work');

    const updatedRow = await new Promise((resolve, reject) => {
      vectorDb.get('SELECT * FROM note_metadata WHERE note_id = ?', ['note_1'], (err, r) => {
        if (err) reject(err); else resolve(r);
      });
    });
    expect(updatedRow.title).toBe('Note One Updated');
    expect(updatedRow.updated_time).toBe(2000);
  });

  it('bulkUpsertVectors returns immediately on empty notes array', async () => {
    await expect(client.bulkUpsertVectors([], [])).resolves.toBeUndefined();
  });

  it('bulkUpsertVectors inserts and updates batches of notes', async () => {
    const notes = [
      { id: 'b_note_1', title: 'Batch Note 1', body: 'Body 1', updated_time: 100, parent_id: 'f1', folder_path: 'Work' },
      { id: 'b_note_2', title: 'Batch Note 2', body: 'Body 2', updated_time: 200, parent_id: 'f2', folder_path: 'Work/Projects' }
    ];
    const embeddings = [
      [0.1, 0.2, 0.3],
      [0.4, 0.5, 0.6]
    ];

    // 1. Initial batch insert
    await client.bulkUpsertVectors(notes, embeddings);

    let rows = await new Promise((resolve, reject) => {
      vectorDb.all('SELECT * FROM note_metadata WHERE note_id IN (?, ?) ORDER BY note_id', ['b_note_1', 'b_note_2'], (err, r) => {
        if (err) reject(err); else resolve(r);
      });
    });
    expect(rows).toHaveLength(2);
    expect(rows[0].title).toBe('Batch Note 1');
    expect(rows[1].title).toBe('Batch Note 2');

    // 2. Batch update existing
    notes[0].title = 'Batch Note 1 Modified';
    notes[0].updated_time = 300;
    await client.bulkUpsertVectors(notes, embeddings);

    rows = await new Promise((resolve, reject) => {
      vectorDb.all('SELECT * FROM note_metadata WHERE note_id IN (?, ?) ORDER BY note_id', ['b_note_1', 'b_note_2'], (err, r) => {
        if (err) reject(err); else resolve(r);
      });
    });
    expect(rows[0].title).toBe('Batch Note 1 Modified');
    expect(rows[0].updated_time).toBe(300);
  });

  it('decrypt emits decryptComplete when no master keys found', async () => {
    client.masterPassword = 'secret_password';
    
    // Mock MasterKey.all to return empty array
    jest.mock('@joplin/lib/models/MasterKey', () => ({
      default: {
        all: jest.fn().mockResolvedValue([])
      }
    }), { virtual: true });

    const decryptCompleteSpy = jest.fn();
    client.on('decryptComplete', decryptCompleteSpy);

    await client.decrypt();
    expect(decryptCompleteSpy).toHaveBeenCalled();
  });

  it('generateEmbeddings handles proactive deletion and empty changedNoteIds', async () => {
    // Insert a note to delete
    await client.upsertVector('del_note', 'Delete Me', 'Content', [0.1, 0.2, 0.3], 500, '', '');

    client.db = {
      selectAll: jest.fn().mockResolvedValue([])
    };

    // Call generateEmbeddings with deletedNoteIds = ['del_note'] and changedNoteIds = []
    await client.generateEmbeddings([], ['del_note']);

    const checkRow = await new Promise((resolve, reject) => {
      vectorDb.get('SELECT * FROM note_metadata WHERE note_id = ?', ['del_note'], (err, r) => {
        if (err) reject(err); else resolve(r);
      });
    });
    expect(checkRow).toBeUndefined();
  });
});
