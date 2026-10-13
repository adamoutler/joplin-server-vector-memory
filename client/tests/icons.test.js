const request = require('supertest');

describe('Static Icon and App Assets', () => {
  let app;

  beforeAll(() => {
    // Require the main app from src/index.js
    // Prevent listen port conflict if index.js binds to PORT
    process.env.NODE_ENV = 'test';
    app = require('../src/index.js');
  });

  afterAll((done) => {
    if (app && app.close) {
      app.close(done);
    } else {
      done();
    }
  });

  test('GET /favicon.ico returns 200 without authentication', async () => {
    const res = await request(app).get('/favicon.ico');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toMatch(/image\/(x-icon|vnd\.microsoft\.icon)/);
    expect(res.body.length).toBeGreaterThan(0);
  });

  test('GET /icon.png returns 200 with image/png without authentication', async () => {
    const res = await request(app).get('/icon.png');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('image/png');
    expect(res.body.length).toBeGreaterThan(0);
  });

  test('GET /icon.svg returns 200 with image/svg+xml without authentication', async () => {
    const res = await request(app).get('/icon.svg');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('image/svg+xml');
    const svgText = res.text || res.body.toString('utf8');
    expect(svgText).toContain('<svg');
    expect(svgText).toContain('SERVER');
  });

  test('GET /icon-128.png and /icon-192.png return 200 without authentication', async () => {
    const res128 = await request(app).get('/icon-128.png');
    expect(res128.status).toBe(200);
    expect(res128.headers['content-type']).toContain('image/png');

    const res192 = await request(app).get('/icon-192.png');
    expect(res192.status).toBe(200);
    expect(res192.headers['content-type']).toContain('image/png');
  });

  test('GET /apple-touch-icon.png returns 200 without authentication', async () => {
    const res = await request(app).get('/apple-touch-icon.png');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('image/png');
  });

  test('GET /manifest.json returns valid web app manifest with custom icons', async () => {
    const res = await request(app).get('/manifest.json');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('application/json');
    expect(res.body.name).toBe('Joplin Server Vector Memory');
    expect(Array.isArray(res.body.icons)).toBe(true);
    expect(res.body.icons.length).toBeGreaterThanOrEqual(2);
    expect(res.body.icons.some(i => i.src === '/icon-192.png')).toBe(true);
    expect(res.body.icons.some(i => i.src === '/icon-512.png')).toBe(true);
  });
});
