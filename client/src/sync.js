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
    this.db.setLogger({ debug: () => {}, info: () => {}, warn: () => {}, error: console.error, setLevel: () => {} });
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
        this.vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[768])`, err => err && reject(err));
        this.vectorDb.run(`CREATE TABLE IF NOT EXISTS note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, title TEXT, content TEXT)`, err => {
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
    Setting.setConstant('env', 'prod');
    Setting.setConstant('appId', 'net.cozic.joplin-cli');
    Setting.setConstant('appType', 'cli');
    
    const Logger = require('@joplin/utils/Logger').default;
    const logger = new Logger();
    logger.addTarget('console');
    logger.setLevel(Logger.LEVEL_WARN);
    Logger.initializeGlobalLogger(logger);

    const dummyLogger = {
        debug: () => {},
        info: () => {},
        warn: () => {},
        error: console.error,
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

    // Initialize sync target
    const syncTargetId = Setting.value('sync.target');
    const SyncTargetClass = SyncTargetRegistry.classById(syncTargetId);
    const syncTarget = new SyncTargetClass(this.db);
    this.synchronizer = await syncTarget.synchronizer();

    this.synchronizer.dispatch = (action) => {
      if (action.type === 'SYNC_STARTED') this.emit('syncStart');
      if (action.type === 'SYNC_COMPLETED') this.emit('syncComplete');
    };

    return this.db;
  }

  async sync() {
    if (!this.synchronizer) {
      throw new Error('Synchronizer not initialized');
    }
    await this.synchronizer.start();
  }

  async decrypt() {
    if (!this.masterPassword) {
      console.warn('No master password provided, skipping decryption.');
      return;
    }
    
    this.emit('decryptStart');
    const EncryptionService = require('@joplin/lib/services/e2ee/EncryptionService').default;
    const service = EncryptionService.instance();
    await service.loadMasterKeysFromSettings();
    
    const masterKeys = await service.loadedMasterKeys();
    for (const key of masterKeys) {
      await service.unlockMasterKey(key, this.masterPassword);
      await service.activateMasterKey(key.id);
    }
    this.emit('decryptComplete');
  }

  upsertVector(noteId, title, content, embedding) {
    return new Promise((resolve, reject) => {
      this.vectorDb.serialize(() => {
        this.vectorDb.get(`SELECT rowid FROM note_metadata WHERE note_id = ?`, [noteId], (err, row) => {
          if (err) return reject(err);
          const eStr = new Float32Array(embedding);
          
          if (row) {
            const rowid = row.rowid;
            this.vectorDb.run(`UPDATE note_metadata SET title = ?, content = ? WHERE rowid = ?`, [title, content, rowid], (err) => {
              if (err) return reject(err);
              this.vectorDb.run(`DELETE FROM vec_notes WHERE rowid = ?`, [rowid], (err) => {
                if (err) return reject(err);
                this.vectorDb.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr], (err) => {
                  if (err) return reject(err);
                  resolve();
                });
              });
            });
          } else {
            const vectorDb = this.vectorDb;
            vectorDb.run(`INSERT INTO note_metadata (note_id, title, content) VALUES (?, ?, ?)`, [noteId, title, content], function(err) {
              if (err) return reject(err);
              const rowid = this.lastID;
              vectorDb.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr], (err) => {
                if (err) return reject(err);
                resolve();
              });
            });
          }
        });
      });
    });
  }

  getConfig() {
    let config = {};
    const configPath = process.env.CONFIG_PATH || '/app/data/config.json';
    try {
      if (fs.existsSync(configPath)) {
        config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
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
      const notes = await this.db.selectAll('SELECT id, title, body FROM notes WHERE encryption_applied = 0');
      
      const config = this.getConfig();
      const ollamaUrl = config.ollamaUrl;
      const model = config.embeddingModel;
      
      for (const note of notes || []) {
        if (!note.body) continue;
        
        try {
          // Truncate from the start to avoid 500 context length errors on Ollama side.
          // Nomic-embed-text has a strict context limit. 25000 characters is a safer 
          // upper bound to ensure we don't blow past the token limit for dense markdown.
          // ALSO: nomic-embed-text requires the `search_document: ` prefix for documents.
          // We MUST include the title in the body so the embedding contains contextual meaning.
          let rawText = `Title: ${note.title}\n\n${note.body}`;
          if (rawText.length > 25000) {
              let truncated = rawText.substring(0, 25000);
              let lastSpace = Math.max(truncated.lastIndexOf(' '), truncated.lastIndexOf('\n'), truncated.lastIndexOf('\t'));
              if (lastSpace > 0) {
                  rawText = truncated.substring(0, lastSpace);
              } else {
                  rawText = truncated;
              }
          }
          let promptBody = `search_document: ${rawText}`;

          const response = await fetch(`${ollamaUrl}/api/embeddings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: model,
              prompt: promptBody,
              options: {
                num_ctx: 8192
              }
            })
          });
          
          if (!response.ok) {
            console.error(`Failed to generate embedding for note ${note.id}: ${response.status} ${response.statusText}`);
            continue;
          }
          
          const data = await response.json();
          
          await this.upsertVector(note.id, note.title, note.body, data.embedding);
          
          this.emit('noteEmbeddingGenerated', {
            noteId: note.id,
            embedding: data.embedding
          });
        } catch (error) {
          console.error(`Error generating embedding for note ${note.id}:`, error);
        }
      }
      this.emit('embeddingComplete');
    } catch (err) {
      console.error('Error fetching notes from DB:', err);
      throw err;
    }
  }
}

module.exports = { JoplinSyncClient };
