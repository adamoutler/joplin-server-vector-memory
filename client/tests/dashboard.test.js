const request = require('supertest');
const fs = require('fs');
const path = require('path');

process.env.JOPLIN_SERVER_URL = 'http://testserver';
const authHeader = 'Basic ' + Buffer.from('admin:password123').toString('base64');

jest.mock('fs', () => {
  const actualFs = jest.requireActual('fs');
  return {
    ...actualFs,
    existsSync: jest.fn(actualFs.existsSync),
    readFileSync: jest.fn(actualFs.readFileSync),
    writeFileSync: jest.fn(),
    mkdirSync: jest.fn()
  };
});

jest.mock('../src/sync', () => {
  return {
    JoplinSyncClient: jest.fn().mockImplementation(() => ({
      on: jest.fn(),
      init: jest.fn().mockResolvedValue(),
      sync: jest.fn().mockResolvedValue(),
      decrypt: jest.fn().mockResolvedValue(),
      generateEmbeddings: jest.fn().mockResolvedValue()
    }))
  };
});

describe('Dashboard Endpoints', () => {
  let app;

  beforeEach(() => {
    jest.clearAllMocks();
    fs.existsSync.mockReturnValue(false);
    fs.readFileSync.mockReturnValue('{}');
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
    expect(response.body).toHaveProperty('status');
  });

  test('GET /status uses cached authentication if Joplin Server fails subsequently', async () => {
    fs.existsSync.mockReturnValue(false); 
    
    // First request should succeed and cache the credentials
    let response = await request(app).get('/status').set('Authorization', authHeader);
    expect(response.status).toBe(200);

    // Now mock the fetch to throw an error (or return 500)
    global.fetch.mockImplementationOnce(async (url, options) => {
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
    fs.readFileSync.mockReturnValue(JSON.stringify({
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
    fs.readFileSync.mockReturnValue(JSON.stringify({
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
    const response = await request(app)
      .post('/auth')
      .set('Authorization', authHeader)
      .send({
        serverUrl: 'http://testserver',
        username: 'testuser',
        password: 'testpassword',
        memoryServerAddress: 'http://localhost:8000'
      });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('success', true);
    expect(response.body).toHaveProperty('token');
    
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

  test('POST /auth handles rotate token request', async () => {
    fs.existsSync.mockReturnValue(true);
    fs.readFileSync.mockReturnValue('{"joplinServerUrl":"test"}');

    const response = await request(app)
      .post('/auth')
      .set('Authorization', authHeader)
      .send({
        rotate: true
      });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('token');
    expect(fs.writeFileSync).toHaveBeenCalled();
  });
});