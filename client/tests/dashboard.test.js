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

  test('POST /auth validates and saves credentials', async () => {
    const response = await request(app)
      .post('/auth')
      .set('Authorization', authHeader)
      .send({
        serverUrl: 'http://testserver',
        username: 'testuser',
        password: 'testpassword'
      });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('success', true);
    expect(response.body).toHaveProperty('token');
    expect(fs.writeFileSync).toHaveBeenCalled();
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