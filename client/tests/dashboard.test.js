const request = require('supertest');
const fs = require('fs');
const path = require('path');

process.env.DASHBOARD_USER = 'admin';
process.env.DASHBOARD_PASSWORD = 'password123';
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

  test('GET /status returns status ready or offline', async () => {
    fs.existsSync.mockReturnValue(false); 
    
    const response = await request(app).get('/status').set('Authorization', authHeader);
    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('status');
  });

  test('POST /auth validates and saves credentials', async () => {
    global.fetch = jest.fn(() => 
      Promise.resolve({
        ok: true,
        status: 200
      })
    );

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