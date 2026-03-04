const { shimInit } = require('@joplin/lib/shim-init-node');
const Setting = require('@joplin/lib/models/Setting').default;
const Database = require('@joplin/lib/database').default;
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
    shimInit();

    if (!fs.existsSync(this.profileDir)) {
      fs.mkdirSync(this.profileDir, { recursive: true });
    }

    const dbPath = path.join(this.profileDir, 'database.sqlite');
    this.sqliteDb = new sqlite3.Database(dbPath);
    this.db = new Database(this.sqliteDb);
    this.db.setDebugEnabled(false);
    await this.db.open();

    // Initialize vector db
    const vectorDbPath = process.env.SQLITE_DB_PATH || path.join(this.profileDir, 'vector.sqlite');
    this.vectorDb = new sqlite3.Database(vectorDbPath);
    sqliteVec.load(this.vectorDb);

    // Create tables in vector db
    await new Promise((resolve, reject) => {
      this.vectorDb.serialize(() => {
        this.vectorDb.run(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[768])`, err => err && reject(err));
        this.vectorDb.run(`CREATE TABLE IF NOT EXISTS note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, title TEXT, content TEXT)`, err => {
          if (err) reject(err); else resolve();
        });
      });
    });

    Setting.setConstant('profileDir', this.profileDir);
    await Setting.load();

    // Configure sync to Joplin Server (target = 9)
    await Setting.setValue('sync.target', 9);
    await Setting.setValue('sync.9.path', this.serverUrl);
    await Setting.setValue('sync.9.userContentPath', this.serverUrl);
    await Setting.setValue('sync.9.username', this.username);
    await Setting.setValue('sync.9.password', this.password);

    // Initialize sync target
    const syncTargetId = Setting.value('sync.target');
    const syncTarget = SyncTargetRegistry.classById(syncTargetId).newSyncTarget(this.db);
    this.synchronizer = await syncTarget.synchronizer();

    this.synchronizer.on('syncStart', () => this.emit('syncStart'));
    this.synchronizer.on('syncComplete', () => this.emit('syncComplete'));

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
          const eStr = JSON.stringify(embedding);
          
          if (row) {
            const rowid = row.rowid;
            this.vectorDb.run(`UPDATE note_metadata SET title = ?, content = ? WHERE rowid = ?`, [title, content, rowid], (err) => {
              if (err) return reject(err);
              this.vectorDb.run(`UPDATE vec_notes SET embedding = ? WHERE rowid = ?`, [eStr, rowid], (err) => {
                if (err) return reject(err);
                resolve();
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
    
    return new Promise((resolve, reject) => {
      this.sqliteDb.all('SELECT id, title, body FROM notes WHERE encryption_applied = 0', async (err, notes) => {
        if (err) {
          console.error('Error fetching notes from DB:', err);
          return reject(err);
        }
        
        const config = this.getConfig();
        const ollamaUrl = config.ollamaUrl;
        const model = config.embeddingModel;
        
        for (const note of notes || []) {
          if (!note.body) continue;
          
          try {
            const response = await fetch(`${ollamaUrl}/api/embeddings`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                model: model,
                prompt: note.body
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
        resolve();
      });
    });
  }
}

module.exports = { JoplinSyncClient };
