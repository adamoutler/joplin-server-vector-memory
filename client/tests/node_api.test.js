const os = require('os');
const path = require('path');
const request = require('supertest');

// Configure test environment variables before requiring modules
process.env.TEST_MODE_ALLOW_ALL_IPS = 'true';
process.env.NODE_ENV = 'test';

const testDataDir = path.join(os.tmpdir(), `node-api-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
process.env.DATA_DIR = testDataDir;
const CONFIG_PATH = path.join(testDataDir, 'config.json');

// Mock @joplin/lib/models/Resource
jest.mock('@joplin/lib/models/Resource', () => ({
  default: {
    load: jest.fn(),
    fullPath: jest.fn()
  }
}));

// Mock sync client
const mockDb = {
  selectAll: jest.fn()
};

const mockSyncClientInstance = {
  on: jest.fn(),
  init: jest.fn().mockResolvedValue(),
  sync: jest.fn().mockResolvedValue(),
  decrypt: jest.fn().mockResolvedValue(),
  generateEmbeddings: jest.fn().mockResolvedValue(),
  db: mockDb
};

jest.mock('../src/sync', () => ({
  JoplinSyncClient: jest.fn().mockImplementation(() => mockSyncClientInstance)
}));

// Mock network validateJoplinSession for relay auth
jest.mock('../src/network', () => {
  const actualNetwork = jest.requireActual('../src/network');
  return {
    ...actualNetwork,
    validateJoplinSession: jest.fn(),
    fetchWithTimeout: jest.fn()
  };
});

describe('node_api & index endpoints', () => {
  let app;
  let fsw;
  let Resource;
  let validateJoplinSession;
  let exitSpy;

  const activeTimers = new Set();
  const realSetTimeout = global.setTimeout;
  const realClearTimeout = global.clearTimeout;
  const realSetInterval = global.setInterval;
  const realClearInterval = global.clearInterval;

  beforeAll(() => {
    fsw = require('../src/fsw');
    if (!fsw.existsSync(testDataDir)) {
      fsw.mkdirSync(testDataDir, { recursive: true });
    }

    // Intercept timers so all are unref'd, tracked, and safely cancelled to guarantee 0 leaks
    jest.spyOn(global, 'setTimeout').mockImplementation((cb, ms, ...args) => {
      const timer = realSetTimeout((...cbArgs) => {
        activeTimers.delete(timer);
        cb(...cbArgs);
      }, ms, ...args);
      if (timer && typeof timer.unref === 'function') {
        timer.unref();
      }
      activeTimers.add(timer);
      return timer;
    });

    jest.spyOn(global, 'setInterval').mockImplementation((cb, ms, ...args) => {
      const timer = realSetInterval((...cbArgs) => {
        cb(...cbArgs);
      }, ms, ...args);
      if (timer && typeof timer.unref === 'function') {
        timer.unref();
      }
      activeTimers.add(timer);
      return timer;
    });

    // Mock process.exit so tests do not terminate Jest
    exitSpy = jest.spyOn(process, 'exit').mockImplementation(() => {});

    Resource = require('@joplin/lib/models/Resource').default;
    validateJoplinSession = require('../src/network').validateJoplinSession;

    app = require('../src/index');
  });

  afterEach(() => {
    // Clear all active timers to avoid leaks
    for (const timer of activeTimers) {
      realClearTimeout(timer);
      realClearInterval(timer);
    }
    activeTimers.clear();
  });

  afterAll(() => {
    // Cleanup temporary test directory
    try {
      if (fsw && fsw.existsSync(testDataDir)) {
        fsw.rmSync(testDataDir, { recursive: true, force: true });
      }
    } catch (_e) {
      // ignore cleanup errors
    }

    if (exitSpy) exitSpy.mockRestore();
    jest.restoreAllMocks();
  });

  describe('1. Uninitialized syncClient endpoints (503 status)', () => {
    it('GET /node-api/resources/:id returns 503 when syncClient is not initialized', async () => {
      const res = await request(app).get('/node-api/resources/res_uninit');
      expect(res.status).toBe(503);
      expect(res.body).toEqual({ error: 'Sync client not initialized' });
    });

    it('GET /node-api/notes/:id/resources returns 503 when syncClient is not initialized', async () => {
      const res = await request(app).get('/node-api/notes/note_uninit/resources');
      expect(res.status).toBe(503);
      expect(res.body).toEqual({ error: 'Sync client not initialized' });
    });
  });

  describe('2. Relay Auth when password not in memory (lines 346-363)', () => {
    beforeAll(() => {
      // Configure config.json with username and server URL but no password
      fsw.writeFileSync(CONFIG_PATH, JSON.stringify({
        joplinServerUrl: 'http://testserver:22300',
        joplinUsername: 'relayuser'
      }, null, 2));
    });

    it('returns 401 when Joplin Server rejects credentials (lines 354-360)', async () => {
      validateJoplinSession.mockResolvedValueOnce({
        ok: false,
        status: 403,
        text: async () => 'Invalid credentials'
      });

      const authHeader = 'Basic ' + Buffer.from('relayuser:rejected_pass').toString('base64');
      const res = await request(app)
        .get('/status')
        .set('Authorization', authHeader);

      expect(res.status).toBe(401);
      expect(res.text).toBe('Authentication required.');
      expect(validateJoplinSession).toHaveBeenCalledWith('http://testserver:22300', 'relayuser', 'rejected_pass');
    });

    it('returns 401 when Joplin Server is unreachable (lines 361-364)', async () => {
      validateJoplinSession.mockRejectedValueOnce(new Error('connect ECONNREFUSED 127.0.0.1:22300'));

      const authHeader = 'Basic ' + Buffer.from('relayuser:unreachable_pass').toString('base64');
      const res = await request(app)
        .get('/status')
        .set('Authorization', authHeader);

      expect(res.status).toBe(401);
      expect(res.text).toBe('Authentication required.');
      expect(validateJoplinSession).toHaveBeenCalledWith('http://testserver:22300', 'relayuser', 'unreachable_pass');
    });

    it('succeeds, caches credentials in memory, and triggers onAuthSuccess (lines 351-353)', async () => {
      validateJoplinSession.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ id: 'session_valid_token' })
      });

      const authHeader = 'Basic ' + Buffer.from('relayuser:valid_relay_pass').toString('base64');
      const res = await request(app)
        .get('/status')
        .set('Authorization', authHeader);

      expect(res.status).toBe(200);
      expect(res.body.hasCredentials).toBe(true);
      expect(validateJoplinSession).toHaveBeenCalledWith('http://testserver:22300', 'relayuser', 'valid_relay_pass');
    });
  });

  describe('3. Error cases on /status (corrupt config) and /sync (unconfigured)', () => {
    it('GET /status returns config error when config.json is corrupted (lines 580-582)', async () => {
      fsw.writeFileSync(CONFIG_PATH, '{ corrupted json: true, ');

      const authHeader = 'Basic ' + Buffer.from('setup:1-mcp-server').toString('base64');
      const res = await request(app)
        .get('/status')
        .set('Authorization', authHeader);

      expect(res.status).toBe(200);
      expect(res.body.config).toEqual({ error: 'Configuration file is corrupted.' });
    });

    it('POST /sync returns 400 when unconfigured (lines 605-607)', async () => {
      fsw.writeFileSync(CONFIG_PATH, JSON.stringify({}));

      const authHeader = 'Basic ' + Buffer.from('setup:1-mcp-server').toString('base64');
      const res = await request(app)
        .post('/sync')
        .set('Authorization', authHeader);

      expect(res.status).toBe(400);
      expect(res.body.error).toBe('System not fully configured yet.');
    });
  });

  describe('4. Initialized syncClient endpoints (/node-api/resources/:id and /node-api/notes/:id/resources)', () => {
    let testFilePath;

    beforeAll(async () => {
      // Re-write valid config and initialize syncClient via runSyncCycle
      fsw.writeFileSync(CONFIG_PATH, JSON.stringify({
        joplinServerUrl: 'http://testserver:22300',
        joplinUsername: 'relayuser'
      }, null, 2));

      await app.runSyncCycle({
        joplinServerUrl: 'http://testserver:22300',
        joplinUsername: 'relayuser'
      });

      testFilePath = path.join(testDataDir, 'existing_resource.txt');
      fsw.writeFileSync(testFilePath, 'Resource file binary mock data', 'utf8');
    });

    it('GET /node-api/resources/:id returns 404 when resource not found (line 382)', async () => {
      Resource.load.mockResolvedValueOnce(null);

      const res = await request(app).get('/node-api/resources/res_not_found');
      expect(res.status).toBe(404);
      expect(res.body.error).toBe('Resource not found');
    });

    it('GET /node-api/resources/:id returns 404 when file not downloaded yet (line 387)', async () => {
      Resource.load.mockResolvedValueOnce({ id: 'res_missing_file', mime: 'image/png' });
      Resource.fullPath.mockReturnValueOnce(path.join(testDataDir, 'nonexistent_file.png'));

      const res = await request(app).get('/node-api/resources/res_missing_file');
      expect(res.status).toBe(404);
      expect(res.body.error).toBe('Resource file not downloaded yet');
    });

    it('GET /node-api/resources/:id returns 200 with file content when downloaded (lines 389-390)', async () => {
      Resource.load.mockResolvedValueOnce({ id: 'res_existing', mime: 'text/plain' });
      Resource.fullPath.mockReturnValueOnce(testFilePath);

      const res = await request(app).get('/node-api/resources/res_existing');
      expect(res.status).toBe(200);
      expect(res.text).toBe('Resource file binary mock data');
      expect(res.headers['content-type']).toContain('text/plain');
    });

    it('GET /node-api/resources/:id returns 500 when Resource.load throws (lines 393-394)', async () => {
      Resource.load.mockRejectedValueOnce(new Error('Corrupt resource record'));

      const res = await request(app).get('/node-api/resources/res_err');
      expect(res.status).toBe(500);
      expect(res.body.error).toBe('Corrupt resource record');
    });

    it('GET /node-api/notes/:id/resources returns resource array (lines 402-409)', async () => {
      const mockResources = [
        { id: 'r1', title: 'diagram.png', mime: 'image/png', file_extension: 'png' },
        { id: 'r2', title: 'spec.pdf', mime: 'application/pdf', file_extension: 'pdf' }
      ];
      mockDb.selectAll.mockResolvedValueOnce(mockResources);

      const res = await request(app).get('/node-api/notes/note_123/resources');
      expect(res.status).toBe(200);
      expect(res.body).toEqual(mockResources);
      expect(mockDb.selectAll).toHaveBeenCalledWith(expect.stringContaining('FROM resources r'), ['note_123']);
    });

    it('GET /node-api/notes/:id/resources returns 500 on db query error (lines 411-413)', async () => {
      mockDb.selectAll.mockRejectedValueOnce(new Error('SQLite table locked'));

      const res = await request(app).get('/node-api/notes/note_err/resources');
      expect(res.status).toBe(500);
      expect(res.body.error).toBe('SQLite table locked');
    });
  });

  describe('5. API Keys management (/auth/keys, /auth/keys/create, /auth/keys/delete) (lines 792-850)', () => {
    let validAuthHeader;
    let createdKeyString;

    beforeAll(() => {
      fsw.writeFileSync(CONFIG_PATH, JSON.stringify({
        joplinServerUrl: 'http://testserver:22300',
        joplinUsername: 'relayuser',
        api_keys: []
      }, null, 2));

      validAuthHeader = 'Basic ' + Buffer.from('relayuser:valid_relay_pass').toString('base64');
    });

    it('GET /auth/keys returns empty api_keys list initially (lines 792-800)', async () => {
      const res = await request(app)
        .get('/auth/keys')
        .set('Authorization', validAuthHeader);

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ api_keys: [] });
    });

    it('POST /auth/keys/create creates a key with custom annotation and expiration (lines 802-825)', async () => {
      const res = await request(app)
        .post('/auth/keys/create')
        .set('Authorization', validAuthHeader)
        .send({ annotation: 'Agent CI Key', expires_at: '2026-12-31T23:59:59Z' });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.key.annotation).toBe('Agent CI Key');
      expect(res.body.key.expires_at).toBe('2026-12-31T23:59:59Z');
      expect(res.body.key.key).toMatch(/^JMS_[a-f0-9]+$/);
      createdKeyString = res.body.key.key;
    });

    it('POST /auth/keys/create uses default annotation when omitted (lines 814-815)', async () => {
      const res = await request(app)
        .post('/auth/keys/create')
        .set('Authorization', validAuthHeader)
        .send({});

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.key.annotation).toBe('Unnamed Key');
      expect(res.body.key.expires_at).toBeNull();
    });

    it('GET /auth/keys returns all registered api keys', async () => {
      const res = await request(app)
        .get('/auth/keys')
        .set('Authorization', validAuthHeader);

      expect(res.status).toBe(200);
      expect(res.body.api_keys.length).toBe(2);
      expect(res.body.api_keys.some(k => k.key === createdKeyString)).toBe(true);
    });

    it('POST /auth/keys/delete deletes a key (lines 830-845)', async () => {
      const res = await request(app)
        .post('/auth/keys/delete')
        .set('Authorization', validAuthHeader)
        .send({ key: createdKeyString });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);

      const checkRes = await request(app)
        .get('/auth/keys')
        .set('Authorization', validAuthHeader);
      expect(checkRes.body.api_keys.some(k => k.key === createdKeyString)).toBe(false);
    });

    it('POST /auth/keys/delete handles case where api_keys array is missing (lines 848-850)', async () => {
      fsw.writeFileSync(CONFIG_PATH, JSON.stringify({
        joplinServerUrl: 'http://testserver:22300',
        joplinUsername: 'relayuser'
      }, null, 2));

      const res = await request(app)
        .post('/auth/keys/delete')
        .set('Authorization', validAuthHeader)
        .send({ key: 'nonexistent_key' });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
    });

    it('POST /auth/keys/create returns 500 when saving fails (lines 825-827)', async () => {
      const spy = jest.spyOn(fsw, 'writeFileSync').mockImplementationOnce(() => {
        throw new Error('EACCES: permission denied');
      });

      const res = await request(app)
        .post('/auth/keys/create')
        .set('Authorization', validAuthHeader)
        .send({ annotation: 'Fail Key' });

      expect(res.status).toBe(500);
      expect(res.body.error).toBe('Failed to save new key');
      spy.mockRestore();
    });

    it('POST /auth/keys/delete returns 500 when saving fails (lines 845-847)', async () => {
      fsw.writeFileSync(CONFIG_PATH, JSON.stringify({
        joplinServerUrl: 'http://testserver:22300',
        joplinUsername: 'relayuser',
        api_keys: [{ key: 'JMS_error_key', annotation: 'Will fail' }]
      }, null, 2));

      const spy = jest.spyOn(fsw, 'writeFileSync').mockImplementationOnce(() => {
        throw new Error('EACCES: permission denied');
      });

      const res = await request(app)
        .post('/auth/keys/delete')
        .set('Authorization', validAuthHeader)
        .send({ key: 'JMS_error_key' });

      expect(res.status).toBe(500);
      expect(res.body.error).toBe('Failed to delete key');
      spy.mockRestore();
    });
  });

  describe('6. Restart daemon (/node-api/restart) (lines 858-861)', () => {
    it('POST /node-api/restart responds with message and triggers process.exit(0)', async () => {
      const res = await request(app).post('/node-api/restart');
      expect(res.status).toBe(200);
      expect(res.body).toEqual({ message: 'Restarting sync daemon...' });

      // Wait 550ms for the 500ms setTimeout to fire
      await new Promise(resolve => realSetTimeout(resolve, 550));
      expect(exitSpy).toHaveBeenCalledWith(0);
      exitSpy.mockClear();
    });
  });

  describe('7. System wipe (/auth/wipe) (lines 863-896)', () => {
    let validAuthHeader;

    beforeEach(() => {
      validAuthHeader = 'Basic ' + Buffer.from('relayuser:valid_relay_pass').toString('base64');
    });

    it('POST /auth/wipe nukes DATA_DIR, clears sync loop, responds, and schedules restart (lines 863-892)', async () => {
      // Put dummy files into testDataDir
      fsw.writeFileSync(path.join(testDataDir, 'test.db'), 'database content');
      fsw.writeFileSync(path.join(testDataDir, 'dummy.json'), '{}');

      const res = await request(app)
        .post('/auth/wipe')
        .set('Authorization', validAuthHeader);

      expect(res.status).toBe(200);
      expect(res.body).toEqual({
        success: true,
        message: 'System completely reset. Rebooting...'
      });

      // Verify directory was emptied
      const remainingFiles = fsw.readdirSync(testDataDir);
      expect(remainingFiles.length).toBe(0);

      // Verify reboot trigger
      await new Promise(resolve => realSetTimeout(resolve, 550));
      expect(exitSpy).toHaveBeenCalledWith(0);
      exitSpy.mockClear();
    });

    it('POST /auth/wipe returns 500 when readdirSync throws an error (lines 893-896)', async () => {
      const readdirSpy = jest.spyOn(fsw, 'readdirSync').mockImplementationOnce(() => {
        throw new Error('EPERM: operation not permitted');
      });

      const res = await request(app)
        .post('/auth/wipe')
        .set('Authorization', validAuthHeader);

      expect(res.status).toBe(500);
      expect(res.body.error).toContain('Failed to wipe system: EPERM: operation not permitted');
      readdirSpy.mockRestore();
    });
  });

  describe('8. Auth Middleware edge cases', () => {
    it('returns WWW-Authenticate header when accessing root / without auth (lines 248-250)', async () => {
      const res = await request(app).get('/');
      expect(res.status).toBe(401);
      expect(res.headers['www-authenticate']).toContain('Basic realm="Joplin Sync Client"');
    });

    it('returns 401 when Authorization header format is invalid (lines 260-261)', async () => {
      const res = await request(app)
        .get('/status')
        .set('Authorization', 'Bearer some-random-bearer-token');
      expect(res.status).toBe(401);
      expect(res.text).toBe('Authentication required.');
    });

    it('returns 401 when user does not match married container username (lines 294-297)', async () => {
      const badUserAuth = 'Basic ' + Buffer.from('wronguser:anypassword').toString('base64');
      const res = await request(app)
        .get('/status')
        .set('Authorization', badUserAuth);
      expect(res.status).toBe(401);
      expect(res.text).toBe('Authentication required.');
    });
  });
});
