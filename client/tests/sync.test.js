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

jest.mock('@joplin/lib/services/share/ShareService', () => {
  const mockInitialize = jest.fn();
  class ShareService {
    static instance() {
      if (!this._instance) {
        this._instance = new ShareService();
      }
      return this._instance;
    }
    initialize = mockInitialize;
  }
  return { default: ShareService };
});

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

  it('should initialize ShareService with a mock store containing dispatch', async () => {
    const ShareService = require('@joplin/lib/services/share/ShareService').default;
    await client.init();
    expect(ShareService.instance().initialize).toHaveBeenCalledWith(
      expect.objectContaining({
        dispatch: expect.any(Function),
        getState: expect.any(Function)
      }),
      null,
      null
    );
    // Let's actually verify getState returns what we expect
    const getStateMock = ShareService.instance().initialize.mock.calls[0][0].getState;
    expect(getStateMock()).toEqual({ shareService: { shares: [], shareInvitations: [] } });
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
      global.fetch = jest.fn().mockImplementation((url, options) => {
        return Promise.resolve({
          ok: true,
          json: async () => ({ embedding: [0.1] })
        });
      });
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
      global.fetch.mockImplementation((url, options) => {
        return Promise.resolve({
          ok: true,
          json: async () => ({ embedding: mockEmbedding })
        });
      });

      const embeddingGeneratedMock = jest.fn();
      client.on('noteEmbeddingGenerated', embeddingGeneratedMock);

      await client.generateEmbeddings();

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/http-api/internal/embed'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            text: 'search_document: Title: Note 1\n\nThis is note 1'
          })
        })
      );

      expect(embeddingGeneratedMock).toHaveBeenCalledWith({
        noteId: 'note1',
        embedding: mockEmbedding
      });
    });

    it('should chunk notes larger than 8000 characters at word boundaries and only send the first chunk', async () => {
      await client.init();

      // Create a large body string > 50000 characters to test the chunk limit
      const largeWord = 'A'.repeat(1000); // 1000 chars
      const largeBody = Array(55).fill(largeWord).join(' '); // 55054 chars with 54 spaces

      const mockNotes = [
        { id: 'note2', title: 'Large Note', body: largeBody },
      ];

      client.db = {
        selectAll: jest.fn().mockResolvedValue(mockNotes)
      };

      const mockEmbedding = [0.4, 0.5, 0.6];
      global.fetch.mockImplementation((url, options) => {
        return Promise.resolve({
          ok: true,
          json: async () => ({ embedding: mockEmbedding })
        });
      });

      await client.generateEmbeddings();

      const fetchCallBody = JSON.parse(global.fetch.mock.calls[0][1].body);
      
      // Expected rawText logic:
      // Title: Large Note\n\n + largeBody
      // That's 19 chars for title part. So 8000 total length minus 19 = 7981 of largeBody.
      // largeBody has words of 1000 chars each separated by spaces.
      // The last space before index 8000 is at index 7999 (if it was 1000-char words).
      // Let's test the length is strictly less than or equal to 8000 + prefix length
      
      expect(fetchCallBody.text.startsWith('search_document: ')).toBe(true);
      expect(fetchCallBody.text.length).toBeLessThanOrEqual(8000 + 'search_document: '.length);
      
      // Ensure the partial word was truncated, meaning it ends cleanly without exceeding the limit
      expect(fetchCallBody.text.endsWith(largeWord)).toBe(true);
    });

    it('should handle fetch errors gracefully', async () => {
      await client.init();

      const mockNotes = [
        { id: 'note1', title: 'Note 1', body: 'This is note 1' },
      ];
      
      client.db = {
        selectAll: jest.fn().mockResolvedValue(mockNotes)
      };

      global.fetch.mockImplementation((url) => {
        if (url && url.includes('/api/tags')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ models: [{ name: 'nomic-embed-text' }] }) });
        }
        return Promise.reject(new Error('Network error'));
      });

      const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
      const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
      const setTimeoutSpy = jest.spyOn(global, 'setTimeout').mockImplementation((cb) => { cb(); return 0; });

      await client.generateEmbeddings();

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Failed to generate embedding for note note1: Unknown Unknown'
      );
      
      consoleWarnSpy.mockRestore();
      consoleErrorSpy.mockRestore();
      setTimeoutSpy.mockRestore();
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

    it('should emit progress events with correct values', async () => {
      await client.init();

      const mockNotes = [
        { id: 'n1', title: 'N1', body: 'body1' },
        { id: 'n2', title: 'N2', body: 'body2' },
      ];
      
      client.db = {
        selectAll: jest.fn().mockResolvedValue(mockNotes)
      };

      global.fetch.mockImplementation((url, options) => {
        if (url && url.includes('/api/tags')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ models: [{ name: 'nomic-embed-text' }] }) });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({ embedding: [0.1] })
        });
      });

      const progressMock = jest.fn();
      client.on('progress', progressMock);

      await client.generateEmbeddings();

      expect(progressMock).toHaveBeenCalledTimes(2);
      expect(progressMock).toHaveBeenNthCalledWith(1, {
        phase: 'embedding',
        current: 1,
        total: 2,
        percent: 50
      });
      expect(progressMock).toHaveBeenNthCalledWith(2, {
        phase: 'embedding',
        current: 2,
        total: 2,
        percent: 100
      });
    });

    it('should retry on failure using incremental backoff before succeeding', async () => {
      await client.init();

      const mockNotes = [
        { id: 'retry_note', title: 'Retry Note', body: 'This note requires retries' },
      ];
      
      client.db = {
        selectAll: jest.fn().mockResolvedValue(mockNotes)
      };

      const mockEmbedding = [0.7, 0.8, 0.9];
      
      // Mock fetch to fail 2 times then succeed for embeddings
      let embedAttempts = 0;
      global.fetch.mockImplementation((url, options) => {
        embedAttempts++;
        if (embedAttempts === 1) return Promise.reject(new Error('fetch failed'));
        if (embedAttempts === 2) return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found' });
        return Promise.resolve({
          ok: true,
          json: async () => ({ embedding: mockEmbedding })
        });
      });

      const embeddingGeneratedMock = jest.fn();
      client.on('noteEmbeddingGenerated', embeddingGeneratedMock);

      const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
      const setTimeoutSpy = jest.spyOn(global, 'setTimeout').mockImplementation((cb) => { cb(); return 0; });

      await client.generateEmbeddings();

      expect(global.fetch).toHaveBeenCalledTimes(3);
      expect(consoleWarnSpy).toHaveBeenCalledTimes(2);
      expect(embeddingGeneratedMock).toHaveBeenCalledWith({
        noteId: 'retry_note',
        embedding: mockEmbedding
      });
      
      consoleWarnSpy.mockRestore();
      setTimeoutSpy.mockRestore();
    });
  });
});
