const { JoplinSyncClient } = require('../src/sync');

describe('Incremental Backoff for Ollama Initialization', () => {
  let client;

  beforeEach(() => {
    client = new JoplinSyncClient();
    // Mock DB methods to return a single note
    client.db = {
      selectAll: jest.fn().mockResolvedValue([
        { id: 'note1', title: 'Test Note', body: 'Test Body', encryption_applied: 0 }
      ])
    };
    // Mock config
    client.getConfig = jest.fn().mockResolvedValue({
      ollamaUrl: 'http://localhost:11434',
      embeddingModel: 'test-model'
    });
    // Mock upsert method so we don't need real sqlite
    client.upsertVector = jest.fn().mockResolvedValue();
    
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
      if (url.includes('/api/tags')) {
        callCount++;
        if (callCount <= 3) {
          // Initially return 404 Model not found
          return { ok: false, status: 404, json: async () => ({ error: 'Model not found' }) };
        } else {
          // On 4th call, return 200 with the model available
          return { ok: true, status: 200, json: async () => ({ models: [{ name: 'test-model' }] }) };
        }
      }
      if (url.includes('/api/embeddings')) {
        embedCount++;
        return { ok: true, status: 200, json: async () => ({ embedding: [0.1, 0.2, 0.3] }) };
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
    expect(client.upsertVector).toHaveBeenCalledWith('note1', 'Test Note', 'Test Body', [0.1, 0.2, 0.3]);
    
    console.log(`Test passed. Total fetch calls for tags: ${callCount}. Duration: ${duration}ms`);
  }, 10000);
});
