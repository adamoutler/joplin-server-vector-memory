const request = require('supertest');
const _fs = require('fs');

jest.mock('fs', () => {
  const actualFs = jest.requireActual('fs');
  return {
    ...actualFs,
    existsSync: jest.fn(() => true),
    promises: {
      readFile: jest.fn(async () => JSON.stringify({
        joplinServerUrl: 'http://testserver',
        joplinUsername: 'admin',
        joplinPassword: 'password123'
      }))
    },
    readFileSync: jest.fn(() => '{}'),
    writeFileSync: jest.fn(),
    renameSync: jest.fn(),
    mkdirSync: jest.fn(),
    readdirSync: jest.fn(() => []),
    rmSync: jest.fn()
  };
});

jest.mock('../src/sync', () => {
  return {
    JoplinSyncClient: jest.fn().mockImplementation(() => ({
      on: jest.fn(),
      init: jest.fn().mockResolvedValue(),
      sync: jest.fn().mockRejectedValue(new Error('Fatal database corruption SQLITE_CORRUPT')),
      decrypt: jest.fn().mockResolvedValue(),
      generateEmbeddings: jest.fn().mockResolvedValue()
    }))
  };
});

describe('index.js runSyncCycle error handling', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    globalThis.fetch = jest.fn(async () => ({ ok: true, status: 200, json: async () => ({ id: 'token' }) }));
  });

  afterAll(() => {
    jest.restoreAllMocks();
  });

  test('process.exit is called on fatal sync error', async () => {
    const exitSpy = jest.spyOn(process, 'exit').mockImplementation(() => {});
    const app = require('../src/index');

    const adminAuthHeader = 'Basic ' + Buffer.from('admin:password123').toString('base64');
    
    // Auth correctly
    await request(app).get('/status').set('Authorization', adminAuthHeader);

    // Trigger sync cycle which will instantiate our mocked JoplinSyncClient
    await request(app)
      .post('/sync')
      .set('Authorization', adminAuthHeader);

    // Give the async runSyncCycle time to fail and call setTimeout for exit
    await new Promise(resolve => setTimeout(resolve, 1500));

    expect(exitSpy).toHaveBeenCalledWith(1);
    
    exitSpy.mockRestore();
  });
});
