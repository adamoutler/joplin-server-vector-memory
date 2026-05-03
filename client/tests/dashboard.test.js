const request = require('supertest');
const fs = require('fs');
const _path = require('path');

process.env.JOPLIN_SERVER_URL = 'http://testserver';
const authHeader = 'Basic ' + Buffer.from('setup:1-mcp-server').toString('base64');

jest.mock('fs', () => {
  const actualFs = jest.requireActual('fs');
  return {
    ...actualFs,
    existsSync: jest.fn(actualFs.existsSync),
    readFileSync: jest.fn(actualFs.readFileSync),
    promises: {
      readFile: jest.fn(async () => '{}')
    },
    writeFileSync: jest.fn(),
    renameSync: jest.fn(),
    mkdirSync: jest.fn(),
    readdirSync: jest.fn(() => []),
    rmSync: jest.fn()
  };
});

const mockHandlers = {};
const mockOn = jest.fn((event, cb) => {
  mockHandlers[event] = cb;
});
jest.mock('../src/sync', () => {
  return {
    JoplinSyncClient: jest.fn().mockImplementation(() => ({
      on: mockOn,
      init: jest.fn().mockReturnValue(new Promise(() => {})),
      sync: jest.fn().mockReturnValue(new Promise(() => {})),
      decrypt: jest.fn().mockReturnValue(new Promise(() => {})),
      generateEmbeddings: jest.fn().mockReturnValue(new Promise(() => {}))
    }))
  };
});

describe('Dashboard Endpoints', () => {
  let app;

  beforeEach(() => {
    jest.clearAllMocks();
    fs.existsSync.mockReturnValue(false);
    fs.promises.readFile.mockResolvedValue('{}');
    global.fetch = jest.fn(async (url, options) => {
      if (url.endsWith('/api/sessions')) {
        const body = options?.body ? JSON.parse(options.body) : {};
        if (body.email === 'admin' && body.password === 'password123') {
          return { ok: true, status: 200, json: async () => ({ id: 'session_token' }) };
        } else {
          return { ok: false, status: 403, json: async () => ({ error: 'Forbidden' }) };
        }
      }
      return { ok: true, status: 200 };
    });
    // Re-require app to reset state if needed
    jest.isolateModules(() => {
      app = require('../src/index');
    });
  });

  afterAll(() => {
    jest.restoreAllMocks();
  });

  test('GET / returns the correct HTML content with Content-Type: text/html', async () => {
    fs.existsSync.mockReturnValue(false);
    const response = await request(app).get('/').set('Authorization', authHeader);
    expect(response.status).toBe(200);
    expect(response.headers['content-type']).toContain('text/html');
    expect(response.text).toContain('<!DOCTYPE html>');
    expect(response.text).toContain('<html>');
  });

  test('GET / returns dashboard HTML with API Documentation links and MCP examples', async () => {
    fs.existsSync.mockReturnValue(false);
    const response = await request(app).get('/').set('Authorization', authHeader);
    expect(response.status).toBe(200);
    expect(response.text).toContain('href="/docs"');
    expect(response.text).toContain('href="/openapi.json"');
    expect(response.text).toContain('const memAddr = window.location.origin;');
    expect(response.text).toContain('/http-api/');
    expect(response.text).toContain('/http-api/mcp');
    expect(response.text).toContain('/http-api/mcp/sse');
  });

  test('GET / returns dashboard HTML with API Keys section', async () => {
    fs.existsSync.mockReturnValue(false);
    const response = await request(app).get('/').set('Authorization', authHeader);
    expect(response.status).toBe(200);
    expect(response.text).toContain('id="api-keys-list"');
    expect(response.text).toContain('id="create-key-form"');
    expect(response.text).toContain('navigator.clipboard.writeText');
  });

  test('GET /status returns 401 if unauthenticated', async () => {
    const response = await request(app).get('/status');
    expect(response.status).toBe(401);
  });

  test('GET /status returns 401 if invalid authentication', async () => {
    const invalidAuthHeader = 'Basic ' + Buffer.from('admin:wrongpassword').toString('base64');
    const response = await request(app).get('/status').set('Authorization', invalidAuthHeader);
    expect(response.status).toBe(401);
  });

  test('GET /status returns status ready or offline with valid auth', async () => {
    fs.existsSync.mockReturnValue(false); 
    
    const response = await request(app).get('/status').set('Authorization', authHeader);
    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('syncState');
    expect(response.body.syncState).toHaveProperty('status');
  });

  test('GET /status returns progress object when syncing', async () => {
    const adminAuthHeader = 'Basic ' + Buffer.from('admin:password123').toString('base64');
    fs.existsSync.mockReturnValue(true);
    fs.promises.readFile.mockResolvedValue(JSON.stringify({
      joplinUsername: 'admin',
      joplinPassword: 'password123'
    }));

    const _response = await request(app)
      .post('/auth')
      .set('Authorization', adminAuthHeader)
      .send({
        serverUrl: 'http://testserver',
        username: 'admin',
        password: 'password123',
        embedding: {
          provider: 'ollama',
          baseUrl: 'http://my-ollama:11434',
          model: 'my-model'
        }
      });      
    // trigger them using the captured mock handlers
    if (mockHandlers.syncStart) mockHandlers.syncStart();
    if (mockHandlers.progress) mockHandlers.progress({ phase: 'embedding', current: 5, total: 10, percent: 50 });

    const statusResponse = await request(app).get('/status').set('Authorization', adminAuthHeader);
    expect(statusResponse.status).toBe(200);
    expect(statusResponse.body.syncState).toHaveProperty('status', 'syncing');
    expect(statusResponse.body.embeddingState).toHaveProperty('progress');
    expect(statusResponse.body.embeddingState.progress).toEqual({ phase: 'embedding', current: 5, total: 10, percent: 50 });
  });

  test('POST /sync triggers sync if configured', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.promises.readFile.mockResolvedValue(JSON.stringify({
      joplinServerUrl: 'http://testserver',
      joplinUsername: 'admin@localhost',
      joplinPassword: 'password123'
    }));

    const adminAuthHeader = 'Basic ' + Buffer.from('admin@localhost:password123').toString('base64');
    
    // First setup global credentials memory by authenticating once
    await request(app)
      .get('/status')
      .set('Authorization', adminAuthHeader);

    const response = await request(app).post('/sync')
      .set('Authorization', adminAuthHeader);

    expect([200, 409]).toContain(response.status);
    if (response.status === 200) {
      expect(response.body.success).toBe(true);
    }
    
    // Wait slightly for setTimeout to trigger mockHandlers
    await new Promise(r => setTimeout(r, 150));
    
    expect(mockHandlers.syncStart).toBeDefined();
  });

  test('GET /status uses cached authentication if Joplin Server fails subsequently', async () => {
    fs.existsSync.mockReturnValue(false); 
    
    // First request should succeed and cache the credentials
    let response = await request(app).get('/status').set('Authorization', authHeader);
    expect(response.status).toBe(200);

    // Now mock the fetch to throw an error (or return 500)
    global.fetch.mockImplementationOnce(async (url, _options) => {
      if (url.endsWith('/api/sessions')) {
        return { ok: false, status: 500, json: async () => ({ error: 'Internal Server Error' }) };
      }
      return { ok: true, status: 200 };
    });

    // Second request should still succeed because of the cache
    response = await request(app).get('/status').set('Authorization', authHeader);
    expect(response.status).toBe(200);
  });

  test('GET /status uses local config to authenticate instantly without calling fetch', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.promises.readFile.mockResolvedValue(JSON.stringify({
      joplinUsername: 'localadmin',
      joplinPassword: 'localpassword'
    }));

    const localAuthHeader = 'Basic ' + Buffer.from('localadmin:localpassword').toString('base64');
    
    // Clear mock calls to fetch to verify it's not called
    global.fetch.mockClear();

    const response = await request(app).get('/status').set('Authorization', localAuthHeader);
    expect(response.status).toBe(200);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('GET /status fails instantly if local config credentials do not match', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.promises.readFile.mockResolvedValue(JSON.stringify({
      joplinUsername: 'localadmin',
      joplinPassword: 'localpassword'
    }));

    const wrongLocalAuthHeader = 'Basic ' + Buffer.from('localadmin:wronglocalpassword').toString('base64');
    
    global.fetch.mockClear();

    const response = await request(app).get('/status').set('Authorization', wrongLocalAuthHeader);
    expect(response.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('POST /auth validates and saves credentials', async () => {
    fs.existsSync.mockReturnValue(false);
    const response = await request(app)
      .post('/auth')
      .set('Authorization', authHeader)
      .send({
        serverUrl: 'http://testserver',
        username: 'admin',
        password: 'password123',
        memoryServerAddress: 'http://localhost:8000'
      });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('success', true);
    expect(response.body).toHaveProperty('requireRelogin', true);
    
    // Check that fs.writeFileSync was called with memoryServerAddress
    const writeCalls = fs.writeFileSync.mock.calls;
    expect(writeCalls.length).toBeGreaterThan(0);
    const savedConfig = JSON.parse(writeCalls[writeCalls.length - 1][1]);
    expect(savedConfig).toHaveProperty('memoryServerAddress', 'http://localhost:8000');
  });

  test('POST /auth handles missing credentials', async () => {
    const response = await request(app)
      .post('/auth')
      .set('Authorization', authHeader)
      .send({
        serverUrl: 'http://testserver'
      });

    expect(response.status).toBe(400);
    expect(response.body).toHaveProperty('error', 'Missing credentials');
  });

  test('POST /auth/keys/create creates a new API key', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.readFileSync.mockReturnValue('{"joplinServerUrl":"test"}');

    const response = await request(app)
      .post('/auth/keys/create')
      .set('Authorization', authHeader)
      .send({
        annotation: 'Test Key'
      });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('success', true);
    expect(response.body).toHaveProperty('key');
    expect(response.body.key.key).toMatch(/^JMS_/);
    expect(fs.writeFileSync).toHaveBeenCalled();
  });

  test('POST /auth/keys/delete removes an API key', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.readFileSync.mockReturnValue('{"joplinServerUrl":"test", "api_keys": [{"key": "JMS_TEST", "annotation": "test"}]}');

    const response = await request(app)
      .post('/auth/keys/delete')
      .set('Authorization', authHeader)
      .send({
        key: 'JMS_TEST'
      });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('success', true);
    expect(fs.writeFileSync).toHaveBeenCalled();
  });

  test('GET /llms.txt returns LLM instructions', async () => {
    const response = await request(app).get('/llms.txt');
    expect(response.status).toBe(200);
    expect(response.text).toContain('For AI Agents');
    expect(response.text).toContain('Joplin Server Vector Memory');
  });

  test('handles concurrent requests without blocking to ensure async file I/O', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.promises.readFile.mockImplementation(() => {
      // Simulate a slightly delayed read to test concurrency
      return new Promise(resolve => {
        setTimeout(() => {
          resolve(JSON.stringify({
            joplinUsername: 'localadmin',
            joplinPassword: 'localpassword'
          }));
        }, 10);
      });
    });

    const localAuthHeader = 'Basic ' + Buffer.from('localadmin:localpassword').toString('base64');
    
    // Fire 10 concurrent requests
    const requests = Array.from({ length: 10 }).map(() => 
      request(app).get('/status').set('Authorization', localAuthHeader)
    );

    const responses = await Promise.all(requests);
    
    // All 10 requests should succeed, and since they are processed concurrently, 
    // the event loop is not blocked by sync file operations.
    responses.forEach(response => {
      expect(response.status).toBe(200);
    });
  });
});