const request = require('supertest');
const express = require('express');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { createOAuthRouter } = require('../src/oauth');

describe('OAuth 2.0 / 2.1 Server', () => {
  let app;
  let testDir;
  let configPath;
  let globalCreds;

  beforeEach(() => {
    testDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oauth-test-'));
    configPath = path.join(testDir, 'config.json');
    globalCreds = { password: 'test-joplin-password', masterPassword: 'test-master-password' };

    fs.writeFileSync(configPath, JSON.stringify({
      joplinUsername: 'admin',
      api_keys: [
        { key: 'JMS_existing_token_123', annotation: 'Existing Key', expires_at: null }
      ],
      oauth_clients: []
    }));

    app = express();
    app.use(express.json());
    app.use(express.urlencoded({ extended: false }));

    const oauthRouter = createOAuthRouter({
      configPath,
      getGlobalCredentials: () => globalCreds
    });
    app.use(oauthRouter);
  });

  afterEach(() => {
    try {
      fs.rmSync(testDir, { recursive: true, force: true });
    } catch (_e) {
      // ignore cleanup errors
    }
  });

  function generatePKCE() {
    const verifier = crypto.randomBytes(32).toString('base64url');
    const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
    return { verifier, challenge };
  }

  describe('RFC 8414 Metadata Discovery', () => {
    test('returns authorization server metadata', async () => {
      const res = await request(app).get('/.well-known/oauth-authorization-server');
      expect(res.status).toBe(200);
      expect(res.body.issuer).toBeDefined();
      expect(res.body.authorization_endpoint).toContain('/oauth/authorize');
      expect(res.body.token_endpoint).toContain('/oauth/token');
      expect(res.body.logo_uri).toContain('/icon.png');
      expect(res.body.response_types_supported).toEqual(['code']);
      expect(res.body.grant_types_supported).toEqual(['authorization_code']);
      expect(res.body.code_challenge_methods_supported).toEqual(['S256']);
    });
  });

  describe('Client Management Endpoints', () => {
    test('creates and lists registered OAuth clients', async () => {
      const createRes = await request(app)
        .post('/auth/oauth/clients/create')
        .send({
          name: 'Gemini Spark',
          client_id: 'gemini-spark-test',
          redirect_uri: 'http://localhost:9099/callback'
        });

      expect(createRes.status).toBe(200);
      expect(createRes.body.success).toBe(true);
      expect(createRes.body.client.client_id).toBe('gemini-spark-test');
      expect(createRes.body.client.client_secret).toBeDefined();
      expect(createRes.body.client.redirect_uris).toEqual(['http://localhost:9099/callback']);

      // List clients - secret should not be exposed
      const listRes = await request(app).get('/auth/oauth/clients');
      expect(listRes.status).toBe(200);
      expect(listRes.body.clients.length).toBe(1);
      expect(listRes.body.clients[0].client_id).toBe('gemini-spark-test');
      expect(listRes.body.clients[0].client_secret).toBeUndefined();
    });

    test('rejects duplicate client_id creation', async () => {
      await request(app)
        .post('/auth/oauth/clients/create')
        .send({ client_id: 'dup-id', name: 'App 1' });

      const res = await request(app)
        .post('/auth/oauth/clients/create')
        .send({ client_id: 'dup-id', name: 'App 2' });

      expect(res.status).toBe(400);
      expect(res.body.error).toContain('already exists');
    });

    test('deletes registered OAuth client', async () => {
      await request(app)
        .post('/auth/oauth/clients/create')
        .send({ client_id: 'to-delete', name: 'Temp' });

      const delRes = await request(app)
        .post('/auth/oauth/clients/delete')
        .send({ client_id: 'to-delete' });

      expect(delRes.status).toBe(200);
      const listRes = await request(app).get('/auth/oauth/clients');
      expect(listRes.body.clients.find(c => c.client_id === 'to-delete')).toBeUndefined();
    });
  });

  describe('Authorization Flow (GET /oauth/authorize)', () => {
    test('validates required parameters', async () => {
      const { challenge } = generatePKCE();

      // Missing client_id or redirect_uri
      let res = await request(app).get('/oauth/authorize');
      expect(res.status).toBe(400);

      // Invalid response_type
      res = await request(app).get('/oauth/authorize?client_id=app&redirect_uri=http://cb&response_type=token');
      expect(res.status).toBe(400);
      expect(res.body.error).toBe('unsupported_response_type');

      // Missing PKCE
      res = await request(app).get('/oauth/authorize?client_id=app&redirect_uri=http://cb&response_type=code');
      expect(res.status).toBe(400);
      expect(res.body.error_description).toContain('PKCE');

      // Missing S256 method
      res = await request(app).get(`/oauth/authorize?client_id=app&redirect_uri=http://cb&response_type=code&code_challenge=${challenge}&code_challenge_method=plain`);
      expect(res.status).toBe(400);
      expect(res.body.error_description).toContain('S256');
    });

    test('enforces redirect_uri whitelist for pre-registered client', async () => {
      const { challenge } = generatePKCE();
      await request(app)
        .post('/auth/oauth/clients/create')
        .send({
          client_id: 'strict-client',
          redirect_uri: 'https://approved.callback.com/cb'
        });

      const res = await request(app).get(
        `/oauth/authorize?client_id=strict-client&redirect_uri=https://malicious.com/cb&response_type=code&code_challenge=${challenge}&code_challenge_method=S256`
      );
      expect(res.status).toBe(400);
      expect(res.body.error_description).toContain('Unauthorized redirect_uri');
    });

    test('redirects to authorize.html for valid request and adds to pending queue', async () => {
      const { challenge } = generatePKCE();
      const res = await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=http://127.0.0.1:8080/callback&response_type=code&state=xyz123&code_challenge=${challenge}&code_challenge_method=S256`
      );

      expect(res.status).toBe(302);
      expect(res.header.location).toContain('/authorize.html?request_id=req_');

      // Check that request appeared in pending queue
      const pendingRes = await request(app).get('/auth/oauth/pending');
      expect(pendingRes.status).toBe(200);
      expect(pendingRes.body.pending.length).toBe(1);
      expect(pendingRes.body.pending[0].client_id).toBe('gemini-spark');

      // Test details endpoint for frontend
      const detailsRes = await request(app).get(`/oauth/requests/${pendingRes.body.pending[0].id}/details`);
      expect(detailsRes.status).toBe(200);
      expect(detailsRes.body.client_id).toBe('gemini-spark');
      expect(detailsRes.body.user_code).toBeDefined();

      const notFoundRes = await request(app).get('/oauth/requests/fake-id/details');
      expect(notFoundRes.status).toBe(404);
    });
  });

  describe('Direct On-Page Approval (POST /oauth/authorize)', () => {
    test('denies request when action is deny', async () => {
      const { challenge } = generatePKCE();
      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=http://127.0.0.1:8080/cb&response_type=code&state=s1&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];

      const res = await request(app)
        .post('/oauth/authorize')
        .type('form')
        .send({ request_id: pending.id, action: 'deny' });

      expect(res.status).toBe(302);
      expect(res.header.location).toContain('error=access_denied');
      expect(res.header.location).toContain('state=s1');
    });

    test('rejects approval with invalid password', async () => {
      const { challenge } = generatePKCE();
      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=http://127.0.0.1:8080/cb&response_type=code&state=s1&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];

      const res = await request(app)
        .post('/oauth/authorize')
        .type('form')
        .send({ request_id: pending.id, action: 'approve', shared_secret: 'wrong-password' });

      expect(res.status).toBe(401);
      expect(res.body.error_description || res.text).toContain('Invalid password');
    });

    test('approves request with valid Joplin password and redirects with code', async () => {
      const { challenge } = generatePKCE();
      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=http://127.0.0.1:8080/cb&response_type=code&state=s1&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];

      const res = await request(app)
        .post('/oauth/authorize')
        .type('form')
        .send({ request_id: pending.id, action: 'approve', shared_secret: 'test-joplin-password' });

      expect(res.status).toBe(302);
      const location = new URL(res.header.location);
      expect(location.origin + location.pathname).toBe('http://127.0.0.1:8080/cb');
      expect(location.searchParams.get('code')).toMatch(/^jms_code_/);
      expect(location.searchParams.get('state')).toBe('s1');
    });

    test('handles non-existent request_id gracefully', async () => {
      const res = await request(app)
        .post('/oauth/authorize')
        .type('form')
        .send({ request_id: 'non-existent', action: 'approve', shared_secret: 'any' });

      expect(res.status).toBe(400);
      expect(res.body.error_description || res.text).toContain('expired or invalid');
    });
  });

  describe('Dashboard Approval Queue & Polling', () => {
    test('admin approves pending request from dashboard, status polling detects redirect', async () => {
      const { challenge } = generatePKCE();
      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=http://127.0.0.1:8080/cb&response_type=code&state=poll-state&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];

      // Waiting page polls before approval
      let pollRes = await request(app).get(`/oauth/requests/${pending.id}/status`);
      expect(pollRes.status).toBe(200);
      expect(pollRes.body.status).toBe('pending');
      expect(pollRes.body.redirect_url).toBeNull();

      // Admin approves in dashboard
      const approveRes = await request(app).post(`/auth/oauth/pending/${pending.id}/approve`);
      expect(approveRes.status).toBe(200);
      expect(approveRes.body.success).toBe(true);

      // Waiting page polls after approval
      pollRes = await request(app).get(`/oauth/requests/${pending.id}/status`);
      expect(pollRes.status).toBe(200);
      expect(pollRes.body.status).toBe('approved');
      expect(pollRes.body.redirect_url).toContain('code=jms_code_');
      expect(pollRes.body.redirect_url).toContain('state=poll-state');
    });

    test('admin denies pending request from dashboard', async () => {
      const { challenge } = generatePKCE();
      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=http://127.0.0.1:8080/cb&response_type=code&state=deny-state&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];

      const denyRes = await request(app).post(`/auth/oauth/pending/${pending.id}/deny`);
      expect(denyRes.status).toBe(200);

      const pollRes = await request(app).get(`/oauth/requests/${pending.id}/status`);
      expect(pollRes.body.status).toBe('rejected');
      expect(pollRes.body.redirect_url).toContain('error=access_denied');
    });

    test('status polling handles expired or missing request', async () => {
      const res = await request(app).get('/oauth/requests/fake-id/status');
      expect(res.body.status).toBe('expired');
    });
  });

  describe('Token Exchange (POST /oauth/token)', () => {
    test('exchanges valid authorization code with PKCE S256 verifier for Bearer token', async () => {
      const { verifier, challenge } = generatePKCE();
      const redirectUri = 'http://127.0.0.1:8080/cb';

      // 1. Authorize
      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=${redirectUri}&response_type=code&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];
      const approveRes = await request(app).post(`/auth/oauth/pending/${pending.id}/approve`);
      const targetUrl = new URL(approveRes.body.redirect_url);
      const code = targetUrl.searchParams.get('code');

      // 2. Token exchange
      const tokenRes = await request(app)
        .post('/oauth/token')
        .type('form')
        .send({
          grant_type: 'authorization_code',
          code,
          redirect_uri: redirectUri,
          client_id: 'gemini-spark',
          code_verifier: verifier
        });

      expect(tokenRes.status).toBe(200);
      expect(tokenRes.body.access_token).toMatch(/^JMS_/);
      expect(tokenRes.body.token_type).toBe('Bearer');
      expect(tokenRes.body.expires_in).toBe(31536000);

      // Verify token persisted in config.json
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      const foundToken = config.api_keys.find(k => k.key === tokenRes.body.access_token);
      expect(foundToken).toBeDefined();
      expect(foundToken.annotation).toBe('OAuth: gemini-spark');

      // 3. Verify single-use code burning (reused code must fail)
      const reuseRes = await request(app)
        .post('/oauth/token')
        .type('form')
        .send({
          grant_type: 'authorization_code',
          code,
          redirect_uri: redirectUri,
          client_id: 'gemini-spark',
          code_verifier: verifier
        });
      expect(reuseRes.status).toBe(400);
      expect(reuseRes.body.error).toBe('invalid_grant');
    });

    test('rejects token exchange with invalid PKCE verifier', async () => {
      const { challenge } = generatePKCE();
      const redirectUri = 'http://127.0.0.1:8080/cb';

      await request(app).get(
        `/oauth/authorize?client_id=gemini-spark&redirect_uri=${redirectUri}&response_type=code&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];
      const approveRes = await request(app).post(`/auth/oauth/pending/${pending.id}/approve`);
      const code = new URL(approveRes.body.redirect_url).searchParams.get('code');

      const tokenRes = await request(app)
        .post('/oauth/token')
        .type('form')
        .send({
          grant_type: 'authorization_code',
          code,
          redirect_uri: redirectUri,
          client_id: 'gemini-spark',
          code_verifier: 'wrong-verifier'
        });

      expect(tokenRes.status).toBe(400);
      expect(tokenRes.body.error).toBe('invalid_grant');
      expect(tokenRes.body.error_description).toContain('PKCE verification failed');
    });

    test('verifies client secret via Basic Auth when client is registered with secret', async () => {
      const { verifier, challenge } = generatePKCE();
      const redirectUri = 'http://127.0.0.1:8080/cb';

      // Register confidential client
      const clientRes = await request(app)
        .post('/auth/oauth/clients/create')
        .send({
          client_id: 'secret-client',
          name: 'Confidential Client',
          redirect_uri: redirectUri
        });
      const clientSecret = clientRes.body.client.client_secret;

      // Authorize
      await request(app).get(
        `/oauth/authorize?client_id=secret-client&redirect_uri=${redirectUri}&response_type=code&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];
      const approveRes = await request(app).post(`/auth/oauth/pending/${pending.id}/approve`);
      const code = new URL(approveRes.body.redirect_url).searchParams.get('code');

      // Exchange with valid Basic Auth
      const basicAuth = Buffer.from(`secret-client:${clientSecret}`).toString('base64');
      const tokenRes = await request(app)
        .post('/oauth/token')
        .set('Authorization', `Basic ${basicAuth}`)
        .type('form')
        .send({
          grant_type: 'authorization_code',
          code,
          redirect_uri: redirectUri,
          code_verifier: verifier
        });

      expect(tokenRes.status).toBe(200);
      expect(tokenRes.body.access_token).toBeDefined();
    });

    test('rejects token exchange with invalid client secret for confidential client', async () => {
      const { verifier, challenge } = generatePKCE();
      const redirectUri = 'http://127.0.0.1:8080/cb';

      await request(app)
        .post('/auth/oauth/clients/create')
        .send({
          client_id: 'secret-client-2',
          redirect_uri: redirectUri
        });

      await request(app).get(
        `/oauth/authorize?client_id=secret-client-2&redirect_uri=${redirectUri}&response_type=code&code_challenge=${challenge}&code_challenge_method=S256`
      );
      const pending = (await request(app).get('/auth/oauth/pending')).body.pending[0];
      const approveRes = await request(app).post(`/auth/oauth/pending/${pending.id}/approve`);
      const code = new URL(approveRes.body.redirect_url).searchParams.get('code');

      const tokenRes = await request(app)
        .post('/oauth/token')
        .type('form')
        .send({
          grant_type: 'authorization_code',
          code,
          redirect_uri: redirectUri,
          client_id: 'secret-client-2',
          client_secret: 'incorrect-secret',
          code_verifier: verifier
        });

      expect(tokenRes.status).toBe(401);
      expect(tokenRes.body.error).toBe('invalid_client');
    });

    test('validates grant_type and error conditions', async () => {
      let res = await request(app)
        .post('/oauth/token')
        .send({ grant_type: 'password' });
      expect(res.status).toBe(400);
      expect(res.body.error).toBe('unsupported_grant_type');

      res = await request(app)
        .post('/oauth/token')
        .send({ grant_type: 'authorization_code' });
      expect(res.status).toBe(400);
      expect(res.body.error).toBe('invalid_request');
    });
  });
});
