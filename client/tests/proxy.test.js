const request = require('supertest');
const express = require('express');
const fs = require('fs');

jest.mock('fs', () => {
  const actualFs = jest.requireActual('fs');
  return {
    ...actualFs,
    existsSync: jest.fn(() => false),
    promises: {
      readFile: jest.fn(async () => '{}')
    },
    mkdirSync: jest.fn(),
    readdirSync: jest.fn(() => []),
    rmSync: jest.fn()
  };
});

// We will test the app by mocking http-proxy-middleware
jest.mock('http-proxy-middleware', () => {
  return {
    createProxyMiddleware: jest.fn((options) => {
      return (req, res, next) => {
        res.status(200).json({ proxied: true, path: req.path });
      };
    })
  };
});

// Mock sync client to avoid startSync running background tasks during tests
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

describe('Proxy Routes', () => {
  let app;
  
  beforeAll(() => {
    // Requires the index file so it initializes the app with the mocked middleware
    app = require('../src/index');
  });

  afterAll(() => {
    jest.resetModules();
  });

  const proxyRoutes = [
    '/openapi.json',
    '/http-api/some-endpoint',
    '/http-api/mcp',
    '/http-api/mcp/sse'
  ];

  test.each(proxyRoutes)('should proxy route %s', async (route) => {
    const response = await request(app).get(route);
    // Since our mock proxy middleware just returns 200 with { proxied: true },
    // we can check if it hit the middleware.
    expect(response.status).toBe(200);
    expect(response.body.proxied).toBe(true);
  });

  test('should proxy route /docs/', async () => {
    const response = await request(app).get('/docs/');
    expect(response.status).toBe(200);
    expect(response.body.proxied).toBe(true);
  });

  test('should enforce auth if JOPLIN_SERVER_URL is in config but missing from env', async () => {
    const originalEnv = process.env.JOPLIN_SERVER_URL;
    delete process.env.JOPLIN_SERVER_URL;
    
    // Make fs.existsSync return true
    fs.existsSync.mockReturnValue(true);
    // Return a fake config
    fs.promises.readFile.mockResolvedValue(JSON.stringify({ joplinServerUrl: 'http://test.joplin' }));
    
    // Send request without auth header
    const response = await request(app).get('/status');
    expect(response.status).toBe(401);
    expect(response.text).toContain('Authentication required');
    
    if (originalEnv !== undefined) {
      process.env.JOPLIN_SERVER_URL = originalEnv;
    }
  });
});
