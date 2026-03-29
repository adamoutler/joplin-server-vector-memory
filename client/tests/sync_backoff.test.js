const { JoplinSyncClient } = require('../src/sync');

describe('Incremental Backoff for Ollama Initialization', () => {
  let client;

  beforeEach(() => {
    client = new JoplinSyncClient();
    // Mock DB methods to return a single note
    client.db = {
      selectAll: jest.fn().mockResolvedValue([
        { id: 'note1', title: 'Test Note', body: 'Test Body', encryption_applied: 0, updated_time: 12345 }
      ])
    };
    // Mock config
    client.getConfig = jest.fn().mockResolvedValue({
      ollamaUrl: 'http://localhost:11434',
      embeddingModel: 'test-model'
    });
    // Mock vectorDb
    client.vectorDb = { 
      all: (q, cb) => cb(null, []), 
      run: function(q, p, cb) { 
        if (cb) cb.call({ lastID: 1 }, null); 
        else if (typeof p === 'function') p.call({ lastID: 1 }, null);
      }, 
      get: (q, p, cb) => cb(null, null),
      serialize: (cb) => cb(),
      prepare: function() {
        return {
          run: function(p, cb) {
            if (cb) cb.call({ lastID: 1 }, null);
          },
          finalize: function() {}
        };
      }
    };
    
    // Mock upsert method so we don't need real sqlite
    client.bulkUpsertVectors = jest.fn().mockResolvedValue();
    
    // Mock global fetch
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('should retry on 404 and eventually succeed when models are loaded', async () => {
    let callCount = 0;
    let embedCount = 0;
    
    global.fetch.mockImplementation(async (url, options) => {
      if (url.includes('/http-api/internal/embed')) {
        callCount++;
        if (callCount <= 3) {
          // Initially return 503 or 404
          return { ok: false, status: 503, statusText: 'Service Unavailable' };
        } else {
          // On 4th call, return 200 with the embedding
          embedCount++;
          return { ok: true, status: 200, json: async () => ({ embeddings: [ [0.1, 0.2, 0.3] ] }) };
        }
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });

    const startTime = Date.now();
    
    // Make the test faster by mocking global.setTimeout temporarily
    const originalSetTimeout = global.setTimeout;
    global.setTimeout = (cb, ms) => originalSetTimeout(cb, 10); // execute with only 10ms delay for fast test

    try {
        await client.generateEmbeddings();
    } finally {
        global.setTimeout = originalSetTimeout;
    }
    
    const duration = Date.now() - startTime;

    // Check that it backed off and fetched multiple times
    expect(callCount).toBe(4);
    
    // Check that it eventually generated the embedding
    expect(embedCount).toBe(1);
    expect(client.bulkUpsertVectors).toHaveBeenCalledWith(
      [{ id: 'note1', title: 'Test Note', body: 'Test Body', updated_time: 12345, encryption_applied: 0 }],
      [[0.1, 0.2, 0.3]]
    );
    
    console.log(`Test passed. Total fetch calls for tags: ${callCount}. Duration: ${duration}ms`);
  }, 10000);
});
