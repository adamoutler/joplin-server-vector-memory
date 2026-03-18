const { shimInit } = require('@joplin/lib/shim-init-node');
const Setting = require('@joplin/lib/models/Setting').default;
const JoplinDatabase = require('@joplin/lib/JoplinDatabase').default;
const SyncTargetRegistry = require('@joplin/lib/SyncTargetRegistry').default;
const sqlite3 = require('sqlite3');
const sqliteVec = require('sqlite-vec');
const path = require('path');
const fs = require('fs');
const EventEmitter = require('events');

class JoplinSyncClient extends EventEmitter {
  constructor(options = {}) {
    super();
    this.profileDir = options.profileDir || '/tmp/joplin-client';
    this.serverUrl = options.serverUrl || process.env.JOPLIN_SERVER_URL;
    if (this.serverUrl) this.serverUrl = this.serverUrl.replace(/\/+$/, '');
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
    const vectorDbPath = process.env.SQLITE_DB_PATH || path.join(this.profileDir, 'vector.sqlite');
    this.vectorDb = new sqlite3.Database(vectorDbPath);
    sqliteVec.load(this.vectorDb);

    // Create tables in vector db
    await new Promise((resolve, reject) => {
      this.vectorDb.serialize(() => {
        this.vectorDb.run(`CREATE TABLE IF NOT EXISTS note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, title TEXT, content TEXT, updated_time INTEGER DEFAULT 0)`, err => {
          if (err) return reject(err);
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
      async setPassword(service, account, password) {}
      async password(service, account) { return null; }
      async deletePassword(service, account) {}
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

  async sync() {
    if (!this.synchronizer) {
      throw new Error('Synchronizer not initialized');
    }
    this._lastSyncErrors = [];
    
    // Hard-patch console to catch EVERYTHING Joplin outputs during this sync cycle
    const origConsoleError = console.error;
    const origConsoleWarn = console.warn;
    const origConsoleLog = console.log;
    const origConsoleInfo = console.info;
    
    const interceptLog = (...args) => {
        const msg = args.map(a => typeof a === 'object' && a instanceof Error ? (a.stack || a.message) : String(a)).join(' ');
        if (msg.includes('Forbidden') || msg.includes('403') || msg.includes('JoplinError') || msg.includes('errors:')) {
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
        throw new Error(`Sync failed: ${this._lastSyncErrors[0]}`);
      }
    } catch (err) {
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
  upsertVector(noteId, title, content, embedding, updatedTime) {
    return new Promise((resolve, reject) => {
      this.vectorDb.serialize(() => {
        if (!this._vecNotesCreated) {
            this.vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[${embedding.length}])`);
            this._vecNotesCreated = true;
        }
        this.vectorDb.run('BEGIN IMMEDIATE TRANSACTION', (err) => {
          if (err) return reject(err);
          this.vectorDb.get(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [noteId], (err, row) => {
            if (err) { this.vectorDb.run('ROLLBACK'); return reject(err); }
            const eStr = new Float32Array(embedding);
            
            if (row) {
              const rowid = row.rowid;
              this.vectorDb.run(`UPDATE note_metadata SET title = ?, content = ?, updated_time = ? WHERE rowid = ?`, [title, content, updatedTime, rowid], (err) => {
                if (err) { this.vectorDb.run('ROLLBACK'); return reject(err); }
                this.vectorDb.run(`DELETE FROM vec_notes WHERE rowid = ?`, [rowid], (err) => {
                  if (err) { this.vectorDb.run('ROLLBACK'); return reject(err); }
                  this.vectorDb.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr], (err) => {
                    if (err) { this.vectorDb.run('ROLLBACK'); return reject(err); }
                    this.vectorDb.run('COMMIT', resolve);
                  });
                });
              });
            } else {
              const vectorDb = this.vectorDb;
              vectorDb.run(`INSERT INTO note_metadata (note_id, title, content, updated_time) VALUES (?, ?, ?, ?)`, [noteId, title, content, updatedTime], function(err) {
                if (err) { vectorDb.run('ROLLBACK'); return reject(err); }
                const rowid = this.lastID;
                vectorDb.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr], (err) => {
                  if (err) { vectorDb.run('ROLLBACK'); return reject(err); }
                  vectorDb.run('COMMIT', resolve);
                });
              });
            }
          });
        });
      });
    });
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
      embeddingModel: config.embeddingModel || config.EMBEDDING_MODEL || process.env.EMBEDDING_MODEL || 'nomic-embed-text'
    };
  }

  async generateEmbeddings() {
    this.emit('embeddingStart');
    
    try {
      // 1. Fetch current decrypted notes from Joplin DB
      const notes = await this.db.selectAll('SELECT id, title, body, updated_time FROM notes WHERE encryption_applied = 0');
      
      // 2. Fetch existing metadata from Vector DB
      const vectorMeta = await new Promise((resolve, reject) => {
        this.vectorDb.all(`SELECT note_id, updated_time FROM note_metadata`, (err, rows) => {
          if (err) return reject(err);
          resolve(rows || []);
        });
      });
      
      const vectorIdToTime = new Map();
      vectorMeta.forEach(row => vectorIdToTime.set(row.note_id, row.updated_time || 0));
      
      const currentNoteIds = new Set(notes.map(n => n.id));
      
      // 3. Delete removed notes
      for (const vId of vectorIdToTime.keys()) {
        if (!currentNoteIds.has(vId)) {
          console.log(`Note ${vId} was deleted, removing from vector DB...`);
          await new Promise((resolve, reject) => {
            this.vectorDb.get(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [vId], (err, row) => {
              if (err || !row) return resolve();
              this.vectorDb.run(`DELETE FROM vec_notes WHERE rowid = ?`, [row.rowid], () => {
                this.vectorDb.run(`DELETE FROM note_metadata WHERE rowid = ?`, [row.rowid], resolve);
              });
            });
          });
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
      
      let i = 0;
      for (const note of notesToProcess) {
        i++;
        this.emit('progress', { phase: 'embedding', current: i, total: notesToProcess.length, percent: Math.round((i / notesToProcess.length) * 100) });
        if (!note.body) continue;
        
        try {
          // Truncate from the start to avoid 500 context length errors on Ollama side if applicable.
          let rawText = `Title: ${note.title}\n\n${note.body}`;
          
          const CHUNK_LIMIT = 8000;
          if (rawText.length > CHUNK_LIMIT) {
              let chunk = rawText.substring(0, CHUNK_LIMIT);
              let lastSpace = Math.max(chunk.lastIndexOf(' '), chunk.lastIndexOf('\n'), chunk.lastIndexOf('\t'));
              if (lastSpace > 0) {
                  rawText = chunk.substring(0, lastSpace);
              } else {
                  rawText = chunk;
              }
          }
          let promptBody = `search_document: ${rawText}`;

          let response;
          let retries = 0;
          const maxRetries = 5;
          let backoff = 1000;
          
          while (retries < maxRetries) {
            try {
              console.log(`Fetching from: ${internalApiUrl}/http-api/internal/embed`);
              response = await fetch(`${internalApiUrl}/http-api/internal/embed`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  text: promptBody
                })
              });

              if (response.ok) {
                break;
              }

              console.warn(`Internal embed API error (${response.status}) for note ${note.id}. Retrying in ${backoff}ms...`);
            } catch (err) {
              console.warn(`Network error (${err.message}) for note ${note.id}. Retrying in ${backoff}ms...`);
              await new Promise(resolve => setTimeout(resolve, backoff));
              retries++;
              backoff *= 2;
              continue;
            }
            await new Promise(resolve => setTimeout(resolve, backoff));
            retries++;
            backoff *= 2;
          }          
          if (!response || !response.ok) {
            const status = response ? response.status : 'Unknown';
            const statusText = response ? response.statusText : 'Unknown';
            let errBody = '';
            try { errBody = await response.text(); } catch(e) { /* ignore */ }
            throw new Error(`Failed to generate embedding for note ${note.id}: HTTP ${status} ${statusText}. ${errBody}`);
          }
          
          const data = await response.json();
          
          await this.upsertVector(note.id, note.title, note.body, data.embedding, note.updated_time);
          
          this.emit('noteEmbeddingGenerated', {
            noteId: note.id,
            embedding: data.embedding
          });
        } catch (error) {
          console.error(`Catastrophic error generating embedding for note ${note.id}:`, error);
          
          if (error.message && error.message.includes('Dimension mismatch')) {
            console.warn('Vector dimension mismatch detected. The underlying embedding model has changed but the DB schema is stale.');
            console.warn('Treating the vector database as ephemeral: Wiping the vector DB and forcing a container restart to rebuild schema from scratch.');
            
            const fs = require('fs');
            const path = require('path');
            const vectorDbPath = process.env.SQLITE_DB_PATH || path.join(this.profileDir, '../vector_memory.sqlite');
            
            try {
              if (this.vectorDb) {
                this.vectorDb.close();
              }
              if (fs.existsSync(vectorDbPath)) {
                fs.unlinkSync(vectorDbPath);
                console.log('Stale vector database deleted successfully.');
              }
            } catch (e) {
              console.error('Failed to wipe stale vector database:', e);
            }
            
            // Force Docker to restart the node process to re-init with correct dimensions
            setTimeout(() => process.exit(0), 1000);
            
            throw new Error(`Self-healing triggered: Vector database schema was stale and has been wiped. System is automatically restarting to reconstruct the database with correct vector dimensions. Please refresh in a moment.`);
          }

          throw new Error(`Embedding process failed critically on note ${note.id}: ${error.message}`, { cause: error });
        }
      }
      this.emit('embeddingComplete');
    } catch (err) {
      console.error('Error in generateEmbeddings:', err);
      this.emit('embeddingError', err);
      throw err;
    }
  }
}

module.exports = { JoplinSyncClient };
