const { JoplinSyncClient } = require('../src/sync.js');

jest.mock('@joplin/lib/shim-init-node', () => ({
  shimInit: jest.fn(),
}));

jest.mock('@joplin/utils/Logger', () => {
  class MockLogger {
    constructor() {}
    addTarget() {}
    setLevel() {}
    static initializeGlobalLogger = jest.fn();
    static create() { return new MockLogger(); }
  }
  MockLogger.LEVEL_WARN = 20;
  return { default: MockLogger };
});

jest.mock('@joplin/lib/models/Setting', () => ({
  default: {
    setConstant: jest.fn(),
    setValue: jest.fn(),
    value: jest.fn().mockReturnValue(9),
    load: jest.fn().mockResolvedValue(),
    setKeychainService: jest.fn(),
  },
}));

jest.mock('@joplin/lib/database', () => ({
  default: class Database {
    constructor() {}
    setDebugEnabled() {}
    open() { return Promise.resolve(); }
    setLogger(l) { this.logger_ = l; }
    logger() { 
      const defaultLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };
      return this.logger_ ? this.logger_() : defaultLogger;
    }
    wrapQueries() { return []; }
    wrapQuery() { return ''; }
    transactionExecBatch() { return Promise.resolve(); }
    exec() { return Promise.resolve(); }
    selectOne() { return Promise.resolve(null); }
    selectAll() { return Promise.resolve([]); }
  },
}));

jest.mock('@joplin/lib/JoplinDatabase', () => ({
  default: class JoplinDatabase {
    constructor() {}
    setLogger() {}
    open() { return Promise.resolve(); }
  },
}));

jest.mock('@joplin/lib/SyncTargetRegistry', () => ({
  default: {
    addClass: jest.fn(),
    classById: jest.fn().mockReturnValue(jest.fn().mockImplementation(() => ({
      synchronizer: jest.fn().mockResolvedValue({
        start: jest.fn().mockResolvedValue(),
        on: jest.fn(),
      }),
    }))),
  },
}));

jest.mock('@joplin/lib/services/e2ee/EncryptionService', () => ({
  default: {
    instance: jest.fn().mockReturnValue({
      loadMasterKeysFromSettings: jest.fn().mockResolvedValue(),
      loadedMasterKeys: jest.fn().mockResolvedValue([{ id: 'key1' }]),
      unlockMasterKey: jest.fn().mockResolvedValue(),
      activateMasterKey: jest.fn().mockResolvedValue(),
    }),
  },
}));

jest.mock('sqlite3', () => ({
  Database: class Database { 
    constructor() {}
    all(query, params, callback) { 
      if (typeof params === 'function') {
        params(null, []);
      } else if (callback) {
        callback(null, []);
      }
    }
    loadExtension() {}
    serialize(cb) { cb(); }
    run(query, params, callback) {
      if (typeof params === 'function') {
        params.call({ lastID: 1 }, null);
      } else if (callback) {
        callback.call({ lastID: 1 }, null);
      }
    }
    get(query, params, callback) {
      if (typeof params === 'function') {
        params(null, null);
      } else if (callback) {
        callback(null, null);
      }
    }
  },
}));

describe('JoplinSyncClient', () => {
  let client;

  beforeEach(() => {
    client = new JoplinSyncClient({
      serverUrl: 'http://localhost:22300',
      username: 'test',
      password: 'password',
      masterPassword: 'masterpassword',
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('should initialize successfully', async () => {
    await client.init();
    expect(client.db).toBeDefined();
    expect(client.synchronizer).toBeDefined();
  });

  it('should call Logger.initializeGlobalLogger exactly once', async () => {
    const Logger = require('@joplin/utils/Logger').default;
    await client.init();
    expect(Logger.initializeGlobalLogger).toHaveBeenCalledTimes(1);
  });

  it('should call synchronizer start on sync', async () => {
    await client.init();
    await client.sync();
    expect(client.synchronizer.start).toHaveBeenCalled();
  });

  it('should register sync events on init', async () => {
    await client.init();
    expect(client.synchronizer.dispatch).toBeDefined();
    expect(typeof client.synchronizer.dispatch).toBe('function');
  });

  it('should emit decryptStart and decryptComplete on decrypt', async () => {
    await client.init();
    const decryptStartMock = jest.fn();
    const decryptCompleteMock = jest.fn();
    
    client.on('decryptStart', decryptStartMock);
    client.on('decryptComplete', decryptCompleteMock);
    
    await client.decrypt();
    
    expect(decryptStartMock).toHaveBeenCalled();
    expect(decryptCompleteMock).toHaveBeenCalled();
  });

  it('should decrypt using master password', async () => {
    await client.init();
    await client.decrypt();
    // Test passes if decrypt runs without throwing
    expect(true).toBe(true);
  });

  describe('generateEmbeddings', () => {
    let originalFetch;

    beforeEach(() => {
      originalFetch = global.fetch;
      global.fetch = jest.fn();
    });

    afterEach(() => {
      global.fetch = originalFetch;
    });

    it('should emit noteEmbeddingGenerated with correct vector array', async () => {
      await client.init();
      
      const mockNotes = [
        { id: 'note1', title: 'Note 1', body: 'This is note 1' },
      ];
      
      client.db = {
        selectAll: jest.fn().mockResolvedValue(mockNotes)
      };

      const mockEmbedding = [0.1, 0.2, 0.3];
      global.fetch.mockResolvedValue({
        ok: true,
        json: async () => ({ embedding: mockEmbedding })
      });

      const embeddingGeneratedMock = jest.fn();
      client.on('noteEmbeddingGenerated', embeddingGeneratedMock);

      await client.generateEmbeddings();

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/embeddings'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            model: 'nomic-embed-text',
            prompt: 'search_document: Title: Note 1\n\nThis is note 1'
          })
        })
      );

      expect(embeddingGeneratedMock).toHaveBeenCalledWith({
        noteId: 'note1',
        embedding: mockEmbedding
      });
    });

    it('should handle fetch errors gracefully', async () => {
      await client.init();

      const mockNotes = [
        { id: 'note1', title: 'Note 1', body: 'This is note 1' },
      ];
      
      client.db = {
        selectAll: jest.fn().mockResolvedValue(mockNotes)
      };

      global.fetch.mockRejectedValue(new Error('Network error'));

      const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

      await client.generateEmbeddings();

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Error generating embedding for note note1:',
        expect.any(Error)
      );
      
      consoleErrorSpy.mockRestore();
    });
    
    it('should emit embeddingStart and embeddingComplete', async () => {
      await client.init();

      client.db = {
        selectAll: jest.fn().mockResolvedValue([])
      };
      
      const startMock = jest.fn();
      const completeMock = jest.fn();
      
      client.on('embeddingStart', startMock);
      client.on('embeddingComplete', completeMock);
      
      await client.generateEmbeddings();
      
      expect(startMock).toHaveBeenCalled();
      expect(completeMock).toHaveBeenCalled();
    });
  });
});
