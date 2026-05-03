// Clean up whitespace-only environment variables
for (const key in process.env) {
  if (typeof process.env[key] === 'string' && process.env[key].trim() === '') {
    delete process.env[key];
  }
}
const { shimInit } = require('@joplin/lib/shim-init-node');
const Setting = require('@joplin/lib/models/Setting').default;
const JoplinDatabase = require('@joplin/lib/JoplinDatabase').default;
const SyncTargetRegistry = require('@joplin/lib/SyncTargetRegistry').default;
const sqlite3 = require('sqlite3');
const sqliteVec = require('sqlite-vec');
const path = require('path');
const fs = require('fs');
const EventEmitter = require('events');
const { triggerInternalEmbedding } = require('./network');

class JoplinSyncClient extends EventEmitter {
  constructor(options = {}) {
    super();
    this.profileDir = options.profileDir || '/tmp/joplin-client';
    this.serverUrl = options.serverUrl || process.env.JOPLIN_SERVER_URL;
    if (this.serverUrl) this.serverUrl = this.serverUrl.replace(/\/$/, '');
    this.username = options.username || process.env.JOPLIN_USERNAME;
    this.password = options.password || process.env.JOPLIN_PASSWORD;
    this.masterPassword = options.masterPassword || process.env.JOPLIN_MASTER_PASSWORD;
    this.db = null;
    this.sqliteDb = null;
    this.vectorDb = null;
    this.synchronizer = null;
  }

  async init() {
    shimInit({ nodeSqlite: sqlite3 });

    if (!fs.existsSync(this.profileDir)) {
      fs.mkdirSync(this.profileDir, { recursive: true });
    }

    const dbPath = path.join(this.profileDir, 'database.sqlite');
    
    // In Joplin's Database class, you must pass a driver. 
    // Usually it's DatabaseDriverNode, but since we are stubbing basic init,
    // let's see if Database needs a specific driver or if raw sqlite3 throws errors later.
    // If it fails on this.db.open(), we'll need to instantiate DatabaseDriverNode.
    const { DatabaseDriverNode } = require('@joplin/lib/database-driver-node');
    const driver = new DatabaseDriverNode();
    this.db = new JoplinDatabase(driver);
    const dbLogger = { 
        debug: () => {}, 
        info: () => {}, 
        warn: () => {}, 
        error: (...args) => {
            console.error(...args);
            if (!this._lastSyncErrors) this._lastSyncErrors = [];
            this._lastSyncErrors.push(args.join(' '));
        }, 
        setLevel: () => {} 
    };
    this.db.setLogger(dbLogger);
    await this.db.open({ name: dbPath });
    
    const BaseModel = require('@joplin/lib/BaseModel').default;
    BaseModel.setDb(this.db);

    // Initialize vector db
    const vectorDbPath = process.env.SQLITE_DB_PATH || path.join(this.profileDir, '../vector_memory.sqlite');
    this.vectorDb = new sqlite3.Database(vectorDbPath);
    sqliteVec.load(this.vectorDb);

    // Create tables in vector db
    await new Promise((resolve, reject) => {
      this.vectorDb.serialize(() => {
        this.vectorDb.run(`CREATE TABLE IF NOT EXISTS note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, title TEXT, content TEXT, parent_id TEXT, folder_path TEXT, updated_time INTEGER DEFAULT 0)`, err => {
          if (err) return reject(err);
          this.vectorDb.run(`CREATE TABLE IF NOT EXISTS folders (id TEXT PRIMARY KEY, title TEXT, parent_id TEXT)`, err => err && reject(err));
          this.vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, content, content="note_metadata", content_rowid="rowid")`, err => err && reject(err));
          this.vectorDb.run(`CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON note_metadata BEGIN INSERT INTO notes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content); END;`, err => err && reject(err));
          this.vectorDb.run(`CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON note_metadata BEGIN INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.rowid, old.title, old.content); END;`, err => err && reject(err));
          this.vectorDb.run(`CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON note_metadata BEGIN INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.rowid, old.title, old.content); INSERT INTO notes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content); END;`, err => {
            if (err) reject(err); else resolve();
          });
        });
      });
    });

    Setting.setConstant('profileDir', this.profileDir);
    Setting.setConstant('resourceDir', path.join(this.profileDir, 'resources'));
    Setting.setConstant('env', 'prod');
    Setting.setConstant('appId', 'net.cozic.joplin-cli');
    Setting.setConstant('appType', 'cli');
    
    const Logger = require('@joplin/utils/Logger').default;
    const logger = new Logger();
    logger.addTarget('console');
    logger.setLevel(Logger.LEVEL_WARN);
    
    const originalError = logger.error.bind(logger);
    const originalWarn = logger.warn.bind(logger);
    const originalInfo = logger.info.bind(logger);
    
    const trapError = (args) => {
        const msg = args.map(a => typeof a === 'object' && a instanceof Error ? a.message : String(a)).join(' ');
        if (msg.includes('Forbidden') || msg.includes('403') || msg.includes('JoplinError')) {
             if (!this._lastSyncErrors) this._lastSyncErrors = [];
             this._lastSyncErrors.push(msg);
        }
    };

    logger.error = (...args) => { originalError(...args); trapError(args); };
    logger.warn = (...args) => { originalWarn(...args); trapError(args); };
    logger.info = (...args) => { originalInfo(...args); trapError(args); };
    
    Logger.initializeGlobalLogger(logger);

    const dummyLogger = {
        debug: () => {},
        info: () => {},
        warn: () => {},
        error: (...args) => {
            console.error(...args);
            if (!this._lastSyncErrors) this._lastSyncErrors = [];
            this._lastSyncErrors.push(args.join(' '));
        },
        setLevel: () => {}
    };

    const BaseService = require('@joplin/lib/services/BaseService').default;
    BaseService.logger_ = dummyLogger;

    const ShareService = require('@joplin/lib/services/share/ShareService').default;
    ShareService.instance().initialize({ getState: () => ({ shareService: { shares: [], shareInvitations: [] } }), dispatch: () => {} }, null, null);

    const KeychainService = require('@joplin/lib/services/keychain/KeychainService').default;
    const keychainService = new KeychainService();
    
    class CustomDummyDriver {
      get name() { return 'dummy'; }
      get appId() { return 'joplin'; }
      get clientId() { return 'joplin-client'; }
      async supported() { return true; }
  
  
      async setPassword(_service, __account, __password) { console.debug("setPassword", _service); }
  
      async password(__service, __account) { return null; }
  
      async deletePassword(_service, __account) { console.debug("deletePassword", _service); }
      async detectIfMacOsKeychainBug() { return false; }
    }
    
    keychainService.initialize([new CustomDummyDriver()]);
    Setting.setKeychainService(keychainService);
    
    await Setting.load();

    const BaseItem = require('@joplin/lib/models/BaseItem').default;
    BaseItem.loadClass('Note', require('@joplin/lib/models/Note').default);
    BaseItem.loadClass('Folder', require('@joplin/lib/models/Folder').default);
    BaseItem.loadClass('Resource', require('@joplin/lib/models/Resource').default);
    BaseItem.loadClass('Tag', require('@joplin/lib/models/Tag').default);
    BaseItem.loadClass('NoteTag', require('@joplin/lib/models/NoteTag').default);
    BaseItem.loadClass('MasterKey', require('@joplin/lib/models/MasterKey').default);
    BaseItem.loadClass('Revision', require('@joplin/lib/models/Revision').default);

    const RevisionService = require('@joplin/lib/services/RevisionService').default;
    BaseItem.revisionService_ = RevisionService.instance();
    
    // Monkey-patch revisionService getter to ensure it's never "not set" 
    // due to Node module caching edge cases or Joplin internals.
          const _originalRevisionService = BaseItem.revisionService;
    BaseItem.revisionService = function() {
        if (!this.revisionService_) {
            this.revisionService_ = require('@joplin/lib/services/RevisionService').default.instance();
        }
        return this.revisionService_;
    };

    const SyncTargetJoplinServer = require('@joplin/lib/SyncTargetJoplinServer').default;
    SyncTargetRegistry.addClass(SyncTargetJoplinServer);
    const SyncTargetWebDAV = require('@joplin/lib/SyncTargetWebDAV');
    SyncTargetRegistry.addClass(SyncTargetWebDAV);

    // Configure sync to Joplin Server (target = 9)
    await Setting.setValue('sync.target', 9);
    await Setting.setValue('sync.9.path', this.serverUrl);
    await Setting.setValue('sync.9.userContentPath', this.serverUrl);
    await Setting.setValue('sync.9.username', this.username);
    await Setting.setValue('sync.9.password', this.password);
    
    // Ensure resources are downloaded locally
    await Setting.setValue('sync.resourceDownloadMode', 'always');

    // Initialize sync target
    const syncTargetId = Setting.value('sync.target');
    const SyncTargetClass = SyncTargetRegistry.classById(syncTargetId);
    const syncTarget = new SyncTargetClass(this.db);
    this.synchronizer = await syncTarget.synchronizer();

    this.synchronizer.dispatch = (action) => {
      if (action.type === 'SYNC_STARTED') this.emit('syncStart');
      if (action.type === 'SYNC_COMPLETED') this.emit('syncComplete');
      if (action.type === 'SYNC_REPORT_UPDATE') {
        this.emit('progress', { phase: 'download', report: action.report });
      }
    };

    return this.db;
  }

    /**
   * Executes the synchronization process with the Joplin Server.
   * Pulls remote changes into the local database and handles database migrations.
   *
   * @throws {Error} Throws if the synchronizer is not initialized or a fatal sync error occurs.
   */
  async sync() {
    if (!this.synchronizer) {
      throw new Error('Synchronizer not initialized');
    }

    try {
      // Defensive initialization: ensure services are present before deep sync operations 
      // where Joplin models might try to use them and fail.
      const BaseItem = require('@joplin/lib/models/BaseItem').default;
      if (!BaseItem.revisionService_) {
          BaseItem.revisionService_ = require('@joplin/lib/services/RevisionService').default.instance();
      }

      const existingSyncItems = await this.db.selectOne('SELECT count(*) as c FROM sync_items');
      const isFullSync = !existingSyncItems || existingSyncItems.c === 0;

      if (isFullSync && this.vectorDb) {
          console.log('Full sync detected. Wiping existing vector DB tables...');
          await new Promise((resolve) => {
              this.vectorDb.serialize(() => {
                  this.vectorDb.run(`DROP TABLE IF EXISTS vec_notes`, () => {});
                  this.vectorDb.run(`DROP TABLE IF EXISTS notes_fts`, () => {});
                  this.vectorDb.run(`DROP TABLE IF EXISTS note_metadata`, () => resolve());
              });
          });
          
          await new Promise((resolve, reject) => {
            this.vectorDb.serialize(() => {
              this.vectorDb.run(`CREATE TABLE IF NOT EXISTS note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, title TEXT, content TEXT, parent_id TEXT, folder_path TEXT, updated_time INTEGER DEFAULT 0)`, err => {
                if (err) return reject(err);
                this.vectorDb.run(`CREATE TABLE IF NOT EXISTS folders (id TEXT PRIMARY KEY, title TEXT, parent_id TEXT)`, err => err && reject(err));
                this.vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, content, content="note_metadata", content_rowid="rowid")`, err => err && reject(err));
                this.vectorDb.run(`CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON note_metadata BEGIN INSERT INTO notes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content); END;`, err => err && reject(err));
                this.vectorDb.run(`CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON note_metadata BEGIN INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.rowid, old.title, old.content); END;`, err => err && reject(err));
                this.vectorDb.run(`CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON note_metadata BEGIN INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.rowid, old.title, old.content); INSERT INTO notes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content); END;`, err => {
                  if (err) reject(err); else resolve();
                });
              });
            });
          });
      }
    } catch (e) {
      console.error('Failed to check or wipe vector db on full sync:', e);
    }

    this._lastSyncErrors = [];
    
    // Hard-patch console to catch EVERYTHING Joplin outputs during this sync cycle
    const origConsoleError = console.error;
    const origConsoleWarn = console.warn;
    const origConsoleLog = console.log;
    const origConsoleInfo = console.info;
    
    const interceptLog = (...args) => {
        const msg = args.map(a => typeof a === 'object' && a instanceof Error ? (a.stack || a.message) : String(a)).join(' ');
        if (msg.includes('Forbidden') || msg.includes('403') || msg.includes('JoplinError') || msg.toLowerCase().includes('error')) {
            this._lastSyncErrors.push(msg);
        }
    };
    
    console.error = (...args) => { origConsoleError(...args); interceptLog(...args); };
    console.warn = (...args) => { origConsoleWarn(...args); interceptLog(...args); };
    console.log = (...args) => { origConsoleLog(...args); interceptLog(...args); };
    console.info = (...args) => { origConsoleInfo(...args); interceptLog(...args); };

    try {
      await this.synchronizer.start();
      
      if (this._lastSyncErrors && this._lastSyncErrors.length > 0) {
        throw new Error(`Sync failed:\n${this._lastSyncErrors.join('\n')}`);
      }
    } catch (err) {
      const errMsg = err.message || String(err);
      if (errMsg.includes('SQLITE_CORRUPT') || errMsg.includes('SQLITE_FULL') || errMsg.includes('SQLITE_IOERR') || errMsg.includes('database disk image is malformed')) {
        console.error('Fatal database error during sync. Wiping databases and restarting...', err);
        const fs = require('fs');
        const path = require('path');
        try {
            if (fs.existsSync(this.profileDir)) fs.rmSync(this.profileDir, { recursive: true, force: true });
            const vectorDbPath = process.env.SQLITE_DB_PATH || path.join(this.profileDir, '../vector_memory.sqlite');
            if (fs.existsSync(vectorDbPath)) fs.unlinkSync(vectorDbPath);
        } catch(e) {
            console.error('Failed to wipe databases:', e);
        }
        process.exit(1);
      }
      this.emit('syncError', err);
      throw err;
    } finally {
      // Restore console
      console.error = origConsoleError;
      console.warn = origConsoleWarn;
      console.log = origConsoleLog;
      console.info = origConsoleInfo;
    }
  }

  async decrypt() {
    if (!this.masterPassword) {
      console.warn('No master password provided, skipping decryption.');
      return;
    }

    this.emit('decryptStart');
    try {
        const MasterKey = require('@joplin/lib/models/MasterKey').default;
        const EncryptionService = require('@joplin/lib/services/e2ee/EncryptionService').default;
        const service = EncryptionService.instance();

        const masterKeys = await MasterKey.all();
        if (!masterKeys || masterKeys.length === 0) {
            // Note: Not everyone uses encryption, so it is perfectly normal for some users to not have any master keys here.
            console.warn('No E2EE master keys found in database. Skipping decryption.');
            this.emit('decryptComplete');
            return;
        }

        let loadedCount = 0;
        for (const key of masterKeys) {
            try {
                await service.loadMasterKey(key, this.masterPassword, true);
                loadedCount++;
            } catch (e) {
                console.warn(`Failed to unlock master key ${key.id} (may be normal if password differs):`, e.message);
            }
        }

        if (loadedCount > 0) {
            console.log(`Successfully unlocked ${loadedCount} master keys.`);
            // In a full implementation we would invoke the DecryptionWorker here.
            // For now, Joplin's read endpoints might handle it transparently if the key is loaded in the service.
        }
    } catch (err) {
        console.error('Error during decryption setup:', err);
    }
    this.emit('decryptComplete');
  }

  buildFolderPathLookup(folders) {
    const folderMap = new Map();
    for (const folder of folders) {
      folderMap.set(folder.id, folder);
    }
    const pathCache = new Map();
    const getPath = (id) => {
      if (!id) return '';
      if (pathCache.has(id)) return pathCache.get(id);
      const folder = folderMap.get(id);
      if (!folder) return '';
      let p;
      if (folder.parent_id) {
        const parentPath = getPath(folder.parent_id);
        p = parentPath ? `${parentPath}/${folder.title}` : folder.title;
      } else {
        p = folder.title;
      }
      pathCache.set(id, p);
      return p;
    };
    for (const folder of folders) {
      getPath(folder.id);
    }
    return pathCache;
  }

  async bulkUpsertVectors(notes, embeddings) {
    const runAsync = (query, params) => new Promise((resolve, reject) => {
      this.vectorDb.run(query, params, function(err) {
        if (err) reject(err);
        else resolve(this);
      });
    });
    const getAsync = (query, params) => new Promise((resolve, reject) => {
      this.vectorDb.get(query, params, (err, row) => {
        if (err) reject(err);
        else resolve(row);
      });
    });

    if (notes.length === 0) return;

    if (!this._vecNotesCreated) {
        await runAsync(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[${embeddings[0].length}])`, []);
        this._vecNotesCreated = true;
    }

    try {
      await runAsync('BEGIN IMMEDIATE TRANSACTION', []);
      
      for (let i = 0; i < notes.length; i++) {
        const note = notes[i];
        const embedding = embeddings[i];
        const eStr = Buffer.from(new Float32Array(embedding).buffer);
        
        const row = await getAsync(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [note.id]);
        
        if (row) {
          const rowid = row.rowid;
          await runAsync(`UPDATE note_metadata SET title = ?, content = ?, updated_time = ?, parent_id = ?, folder_path = ? WHERE rowid = ?`, [note.title, note.body, note.updated_time, note.parent_id, note.folder_path, rowid]);
          await runAsync(`DELETE FROM vec_notes WHERE rowid = ?`, [rowid]);
          await runAsync(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr]);
        } else {
          const result = await runAsync(`INSERT INTO note_metadata (note_id, title, content, updated_time, parent_id, folder_path) VALUES (?, ?, ?, ?, ?, ?)`, [note.id, note.title, note.body, note.updated_time, note.parent_id, note.folder_path]);
          const rowid = result.lastID;
          await runAsync(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr]);
        }
      }
      
      await runAsync('COMMIT', []);
    } catch (err) {
      try {
        await runAsync('ROLLBACK', []);
      } catch (rollbackErr) {
        console.error('Failed to rollback transaction:', rollbackErr);
      }
      this._handleVectorDbFatalError(err);
      throw err;
    }
  }

  async upsertVector(noteId, title, content, embedding, updatedTime, parentId, folderPath) {
    const runAsync = (query, params) => new Promise((resolve, reject) => {
      this.vectorDb.run(query, params, function(err) {
        if (err) reject(err);
        else resolve(this);
      });
    });
    const getAsync = (query, params) => new Promise((resolve, reject) => {
      this.vectorDb.get(query, params, (err, row) => {
        if (err) reject(err);
        else resolve(row);
      });
    });

    if (!this._vecNotesCreated) {
        await runAsync(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[${embedding.length}])`, []);
        this._vecNotesCreated = true;
    }

    try {
      await runAsync('BEGIN IMMEDIATE TRANSACTION', []);
      const row = await getAsync(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [noteId]);
      const eStr = Buffer.from(new Float32Array(embedding).buffer);

      if (row) {
        const rowid = row.rowid;
        await runAsync(`UPDATE note_metadata SET title = ?, content = ?, updated_time = ?, parent_id = ?, folder_path = ? WHERE rowid = ?`, [title, content, updatedTime, parentId, folderPath, rowid]);
        await runAsync(`DELETE FROM vec_notes WHERE rowid = ?`, [rowid]);
        await runAsync(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr]);
      } else {
        const result = await runAsync(`INSERT INTO note_metadata (note_id, title, content, updated_time, parent_id, folder_path) VALUES (?, ?, ?, ?, ?, ?)`, [noteId, title, content, updatedTime, parentId, folderPath]);
        const rowid = result.lastID;
        await runAsync(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr]);
      }
      await runAsync('COMMIT', []);
    } catch (err) {
      try {
        await runAsync('ROLLBACK', []);
      } catch (rollbackErr) {
        console.error('Failed to rollback transaction:', rollbackErr);
      }
      this._handleVectorDbFatalError(err);
      throw err;
    }
  }

  async getConfig() {
    let config = {};
    const configPath = process.env.CONFIG_PATH || '/app/data/config.json';
    try {
      if (fs.existsSync(configPath)) {
        const data = await fs.promises.readFile(configPath, 'utf8');
        config = JSON.parse(data);
      }
    } catch (e) {
      console.error('Error reading config.json:', e);
    }
    return {
      ollamaUrl: config.ollamaUrl || config.OLLAMA_URL || process.env.OLLAMA_URL || 'http://localhost:11434',
      embeddingModel: config.embeddingModel || config.EMBEDDING_MODEL || process.env.EMBEDDING_MODEL || 'nomic-embed-text',
      chunkSize: config.chunkSize || 1000,
      chunkOverlap: config.chunkOverlap || 200
    };
  }

  _handleVectorDbFatalError(error) {
      console.warn('Fatal database state detected. Treating vector database as ephemeral: Wiping DB and forcing restart.', error);
      const fs = require('fs');
      const path = require('path');
      const vectorDbPath = process.env.SQLITE_DB_PATH || path.join(this.profileDir, '../vector_memory.sqlite');
      try {
          if (this.vectorDb) this.vectorDb.close();
          if (fs.existsSync(vectorDbPath)) fs.unlinkSync(vectorDbPath);
      } catch (_e) { /* ignore cleanup error */ }
      setTimeout(() => process.exit(1), 1000);
      throw new Error(`Self-healing triggered: Vector database connection was poisoned or corrupted.`, { cause: error });
  }

  async generateEmbeddings(changedNoteIds = null, deletedNoteIds = null) {
    this.emit('embeddingStart');

    const config = await this.getConfig();

    try {
      // 1. Sync folders first to enable recursive scoping
      const joplinFolders = await this.db.selectAll('SELECT id, title, parent_id FROM folders');
      await new Promise((resolve, reject) => {
          this.vectorDb.serialize(() => {
              this.vectorDb.run('BEGIN TRANSACTION');
              this.vectorDb.run('DELETE FROM folders');
              const stmt = this.vectorDb.prepare('INSERT INTO folders (id, title, parent_id) VALUES (?, ?, ?)');
              for (const f of joplinFolders) {
                  stmt.run([f.id, f.title, f.parent_id]);
              }
              stmt.finalize();
              this.vectorDb.run('COMMIT', (err) => err ? reject(err) : resolve());
          });
      });

      const folderPathCache = this.buildFolderPathLookup(joplinFolders);

      // Proactively delete notes if provided
      if (deletedNoteIds && deletedNoteIds.length > 0) {
        console.log(`Proactively deleting ${deletedNoteIds.length} notes from vector DB...`);
        for (const vId of deletedNoteIds) {
          await new Promise((resolve, reject) => {
            this.vectorDb.get(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [vId], (err, row) => {
              if (err) return reject(err);
              if (!row) return resolve();
              this.vectorDb.run(`DELETE FROM vec_notes WHERE rowid = ?`, [row.rowid], (err2) => {
                if (err2) return reject(err2);
                this.vectorDb.run(`DELETE FROM note_metadata WHERE rowid = ?`, [row.rowid], (err3) => {
                  if (err3) return reject(err3);
                  resolve();
                });
              });
            });
          }).catch(err => this._handleVectorDbFatalError(err));
        }
      }

      // 2. Fetch current decrypted notes from Joplin DB
      let notesQuery = 'SELECT id, title, body, updated_time, parent_id FROM notes WHERE encryption_applied = 0';
      let notes = [];
      if (changedNoteIds && changedNoteIds.length > 0) {
          const placeholders = changedNoteIds.map(() => '?').join(',');
          notesQuery += ` AND id IN (${placeholders})`;
          notes = await this.db.selectAll(notesQuery, changedNoteIds);
      } else if (changedNoteIds && changedNoteIds.length === 0) {
          // Empty array passed, skip fetching
          notes = [];
      } else {
          notes = await this.db.selectAll(notesQuery);
      }
      
      // 3. Fetch existing metadata from Vector DB
      const vectorMeta = await new Promise((resolve, reject) => {
        this.vectorDb.all(`SELECT note_id, updated_time FROM note_metadata`, (err, rows) => {
          if (err) return reject(err);
          resolve(rows || []);
        });
      }).catch(err => this._handleVectorDbFatalError(err));
      
      const vectorIdToTime = new Map();
      vectorMeta.forEach(row => vectorIdToTime.set(row.note_id, row.updated_time || 0));
      
      const currentNoteIds = new Set(notes.map(n => n.id));
      
      // Delete removed notes (only on full scan)
      if (changedNoteIds === null) {
          for (const vId of vectorIdToTime.keys()) {
            if (!currentNoteIds.has(vId)) {
              console.log(`Note ${vId} was deleted, removing from vector DB...`);
              await new Promise((resolve, reject) => {
                this.vectorDb.get(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [vId], (err, row) => {
                  if (err) return reject(err);
                  if (!row) return resolve();
                  this.vectorDb.run(`DELETE FROM vec_notes WHERE rowid = ?`, [row.rowid], (err2) => {
                    if (err2) return reject(err2);
                    this.vectorDb.run(`DELETE FROM note_metadata WHERE rowid = ?`, [row.rowid], (err3) => {
                      if (err3) return reject(err3);
                      resolve();
                    });
                  });
                });
              }).catch(err => this._handleVectorDbFatalError(err));
            }
          }
      }
      
      // 4. Filter notes that need updating
      const notesToProcess = notes.filter(n => {
        const vTime = vectorIdToTime.get(n.id);
        return vTime === undefined || n.updated_time > vTime;
      });
      
      if (notesToProcess.length === 0) {
        console.log('No changed notes to embed.');
        this.emit('embeddingComplete');
        return;
      }
      
      console.log(`Found ${notesToProcess.length} new or updated notes to embed.`);
      
      // Instead of polling Ollama directly, we just call our Python server.
      // The Python server will handle whether it uses local SentenceTransformers or an external Ollama server.
      const internalApiUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

      const BATCH_SIZE = 72;
      let processedCount = 0;      let dbWriteQueue = Promise.resolve();

      for (let i = 0; i < notesToProcess.length; i += BATCH_SIZE) {
        const batch = notesToProcess.slice(i, i + BATCH_SIZE);
        const validNotes = [];
        const prompts = [];

        for (const note of batch) {
          if (!note.body) continue;
          const folderPath = folderPathCache.get(note.parent_id) || '';
          note.folder_path = folderPath;
          let rawText = `Folder: ${folderPath}\nTitle: ${note.title}\n\n${note.body}`;
          const CHUNK_LIMIT = config.chunkSize ? config.chunkSize * 4 : 4000;
          if (rawText.length > CHUNK_LIMIT) {
              let chunk = rawText.substring(0, CHUNK_LIMIT);
              let lastSpace = Math.max(chunk.lastIndexOf(' '), chunk.lastIndexOf('\n'), chunk.lastIndexOf('\t'));
              if (lastSpace > 0) {
                  rawText = chunk.substring(0, lastSpace);
              } else {
                  rawText = chunk;
              }
          }
          prompts.push(`search_document: ${rawText}`);
          validNotes.push(note);
        }

        if (prompts.length === 0) {
          processedCount += batch.length;
          this.emit('progress', { phase: 'embedding', current: processedCount, total: notesToProcess.length, percent: Math.round((processedCount / notesToProcess.length) * 100) });
          continue;
        }

        let response;
        let retries = 0;
        const maxRetries = 5;
        let backoff = 1000;

        while (retries < maxRetries) {
          try {
            response = await triggerInternalEmbedding(internalApiUrl, { texts: prompts });
            if (response.ok) break;
            console.warn(`Internal embed API error (${response.status}) for batch. Retrying in ${backoff}ms...`);
          } catch (err) {
            console.warn(`Network error (${err.message}) for batch. Retrying in ${backoff}ms...`);
          }
          await new Promise(resolve => setTimeout(resolve, backoff));
          retries++;
          backoff *= 2;
        }          
        if (!response || !response.ok) {
          const status = response ? response.status : 'Unknown';
          const statusText = response ? response.statusText : 'Unknown';
          let errBody = '';
          try { errBody = await response.text(); } catch(_e) { /* ignore */ }
          throw new Error(`Failed to generate embeddings for batch: HTTP ${status} ${statusText}. ${errBody}`);
        }

        const data = await response.json();
        const embeddings = data.embeddings;

        // Pipeline the DB write: chain it to the queue without awaiting it here
        // so the next iteration can immediately start fetching the next batch!
        dbWriteQueue = dbWriteQueue.then(async () => {
           try {
              await this.bulkUpsertVectors(validNotes, embeddings);
              for (let j = 0; j < validNotes.length; j++) {
                this.emit('noteEmbeddingGenerated', {
                  noteId: validNotes[j].id,
                  embedding: embeddings[j]
                });
              }
           } catch (error) {
              this._handleVectorDbFatalError(error);
           } finally {
              processedCount += batch.length; // use batch.length so empty notes are counted
              this.emit('progress', { phase: 'embedding', current: processedCount, total: notesToProcess.length, percent: Math.round((processedCount / notesToProcess.length) * 100) });
           }
        });
      }

      // Await the very last DB write before emitting complete
      await dbWriteQueue;
      this.emit('embeddingComplete');
    } catch (err) {
      console.error('Error in generateEmbeddings:', err);
      this.emit('embeddingError', err);
      throw err;
    }
  }
}

module.exports = { JoplinSyncClient };
