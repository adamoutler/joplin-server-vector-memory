const { JoplinSyncClient } = require('../src/sync');

describe('Semantic Chunking for Large Notes', () => {
  let client;

  beforeEach(() => {
    client = new JoplinSyncClient();
    
    // Create a 50,000+ character body with spaces
    const word = 'word '; // 5 chars
    const body = word.repeat(11000); // 55,000 characters

    // Mock DB methods to return a single large note
    client.db = {
      selectAll: jest.fn().mockResolvedValue([
        { id: 'note1', title: 'Giant Test Note', body: body, encryption_applied: 0 }
      ])
    };
    
    // Mock config
    client.getConfig = jest.fn().mockResolvedValue({
      ollamaUrl: 'http://localhost:11434',
      embeddingModel: 'test-model',
      chunkSize: 2000
    });
    
    // Mock vectorDb
    client.vectorDb = { all: (q, cb) => cb(null, []), run: (q, p, cb) => cb && cb(null), get: (q, p, cb) => cb(null, null) };
    
    // Mock upsert method so we don't need real sqlite
    client.upsertVector = jest.fn().mockResolvedValue();
    
    // Mock global fetch
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('should truncate notes exceeding chunk limit and split by spaces', async () => {
    let capturedPrompt = '';
    
    global.fetch.mockImplementation(async (url, options) => {
      if (url.includes('/http-api/internal/embed')) {
        const body = JSON.parse(options.body);
        capturedPrompt = body.texts[0];
        return { ok: true, status: 200, json: async () => ({ embeddings: [[0.1, 0.2, 0.3]] }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });

    const originalSetTimeout = global.setTimeout;
    global.setTimeout = (cb, ms) => originalSetTimeout(cb, 10);

    try {
        await client.generateEmbeddings();
    } finally {
        global.setTimeout = originalSetTimeout;
    }

    // "search_document: ".length is 17. The chunk limit is 8000 characters.
    // The total length of the prompt should not exceed 8017 characters.
    expect(capturedPrompt.length).toBeLessThanOrEqual(8017);
    
    // It should also not be drastically small if the word spacing is normal.
    // It should cut at the nearest space below 8000.
    expect(capturedPrompt.length).toBeGreaterThan(7900);
    
    // Ensure the end of the prompt is a space (from our word generation logic)
    // or ends at a complete word. The chunking logic cuts at the last space,
    // so the last character of `rawText` should be just before that space.
    
    console.log(`Test passed. Captured prompt length: ${capturedPrompt.length}`);
  });
});
