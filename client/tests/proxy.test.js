const request = require('supertest');
const express = require('express');

// We will test the app by mocking http-proxy-middleware
jest.mock('http-proxy-middleware', () => {
  return {
    createProxyMiddleware: jest.fn(() => {
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
    '/api/some-endpoint',
    '/mcp-server/sse',
    '/mcp-server-http/mcp',
    '/mcp/http/api-key/mcp/sse'
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
});
