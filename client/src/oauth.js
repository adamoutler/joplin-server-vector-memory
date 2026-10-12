const crypto = require('node:crypto');
const fs = require('./fsw');
const express = require('express');

/**
 * Creates and configures the OAuth 2.0 / 2.1 router.
 *
 * @param {Object} options
 * @param {string} options.configPath Path to config.json
 * @param {Function} options.getGlobalCredentials Function returning current in-memory Joplin credentials
 * @returns {express.Router} Configured OAuth router
 */
function createOAuthRouter({ configPath, getGlobalCredentials }) {
  const router = express.Router();

  // In-memory store for pending authorization requests (TTL: 180s)
  const pendingRequests = new Map();
  // In-memory store for single-use authorization codes (TTL: 60s)
  const authCodes = new Map();

  // Helper to load config safely
  function loadConfig() {
    if (!fs.existsSync(configPath)) {
      return {};
    }
    try {
      return JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (_e) {
      return {};
    }
  }

  // Helper to save config atomically
  function saveConfig(config) {
    fs.writeFileSync(configPath + '.tmp', JSON.stringify(config, null, 2));
    fs.renameSync(configPath + '.tmp', configPath);
  }

  // Cleanup expired items
  function cleanup() {
    const now = Date.now();
    for (const [id, req] of pendingRequests.entries()) {
      if (req.expires_at < now) {
        pendingRequests.delete(id);
      }
    }
    for (const [code, item] of authCodes.entries()) {
      if (item.expires_at < now) {
        authCodes.delete(code);
      }
    }
  }

  // Periodic cleanup without keeping node event loop active
  const cleanupTimer = setInterval(cleanup, 30000);
  if (cleanupTimer.unref) {
    cleanupTimer.unref();
  }

  // Helper for timing-safe hash comparison
  function timingSafeHashMatch(plaintext, storedHash) {
    if (!plaintext || !storedHash) return false;
    const computedHash = 'sha256:' + crypto.createHash('sha256').update(plaintext).digest('hex');
    const bufA = Buffer.from(computedHash);
    const bufB = Buffer.from(storedHash);
    if (bufA.length !== bufB.length) return false;
    return crypto.timingSafeEqual(bufA, bufB);
  }

  // Verify submitted password/secret against:
  // 1. in-memory Joplin master password / password
  // 2. registered client secret
  // 3. active api_keys
  function verifySecret(secret, clientId, config) {
    if (!secret) return false;

    const creds = getGlobalCredentials ? getGlobalCredentials() : {};
    if (creds.password && secret === creds.password) return true;
    if (creds.masterPassword && secret === creds.masterPassword) return true;

    // Check registered OAuth clients
    const clients = config.oauth_clients || [];
    const client = clients.find(c => c.client_id === clientId);
    if (client && client.client_secret_hash) {
      if (timingSafeHashMatch(secret, client.client_secret_hash)) return true;
    }

    // Check API keys
    const apiKeys = config.api_keys || [];
    if (apiKeys.some(k => k.key === secret)) return true;

    return false;
  }

  // -------------------------------------------------------------
  // 1. RFC 8414 Authorization Server Metadata
  // -------------------------------------------------------------
  router.get('/.well-known/oauth-authorization-server', (req, res) => {
    const proto = req.headers['x-forwarded-proto'] || req.protocol || 'http';
    const host = req.headers['x-forwarded-host'] || req.get('host') || '127.0.0.1:3000';
    const issuer = `${proto}://${host}`;

    res.json({
      issuer,
      authorization_endpoint: `${issuer}/oauth/authorize`,
      token_endpoint: `${issuer}/oauth/token`,
      response_types_supported: ['code'],
      grant_types_supported: ['authorization_code'],
      code_challenge_methods_supported: ['S256'],
      token_endpoint_auth_methods_supported: ['client_secret_basic', 'client_secret_post', 'none']
    });
  });

  // -------------------------------------------------------------
  // 2. GET /oauth/authorize - Request consent
  // -------------------------------------------------------------
  router.get('/oauth/authorize', (req, res) => {
    cleanup();
    const {
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: responseType,
      state,
      code_challenge: codeChallenge,
      code_challenge_method: codeChallengeMethod,
      scope
    } = req.query;

    if (!clientId || !redirectUri) {
      return res.status(400).send('Missing client_id or redirect_uri.');
    }

    if (responseType !== 'code') {
      return res.status(400).send('Unsupported response_type. Must be "code".');
    }

    // Enforce PKCE S256 per RFC 7636
    if (!codeChallenge || codeChallengeMethod !== 'S256') {
      return res.status(400).send('PKCE code_challenge with code_challenge_method=S256 is required.');
    }

    const config = loadConfig();
    const registeredClient = (config.oauth_clients || []).find(c => c.client_id === clientId);

    // If client is pre-registered, strictly enforce redirect_uri whitelist
    if (registeredClient && Array.isArray(registeredClient.redirect_uris) && registeredClient.redirect_uris.length > 0) {
      if (!registeredClient.redirect_uris.includes(redirectUri)) {
        return res.status(400).send('Unauthorized redirect_uri for this client.');
      }
    }

    const requestId = 'req_' + crypto.randomBytes(16).toString('hex');
    const userCode = 'JMS-' + crypto.randomInt(100, 999);

    const pendingItem = {
      id: requestId,
      user_code: userCode,
      client_id: clientId,
      client_name: registeredClient?.name || clientId,
      redirect_uri: redirectUri,
      state: state || '',
      code_challenge: codeChallenge,
      code_challenge_method: codeChallengeMethod,
      scope: scope || 'mcp',
      status: 'pending',
      redirect_url: null,
      created_at: Date.now(),
      expires_at: Date.now() + 180 * 1000 // 3 minutes TTL
    };

    pendingRequests.set(requestId, pendingItem);

    // Render accessible consent page
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Authorize Application &bull; Joplin Vector Memory</title>
  <style>
    :root {
      --bg: #f8f9fa; --card-bg: #ffffff; --border: #d0d7de; --text: #1f2328; --muted: #57606a;
      --primary: #0056b3; --success: #198754; --danger: #dc3545; --code-bg: #eaeef2;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0d1117; --card-bg: #161b22; --border: #30363d; --text: #f0f6fc; --muted: #8b949e;
        --primary: #388bfd; --success: #238636; --danger: #f85149; --code-bg: #21262d;
      }
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; width: 100%; max-width: 480px; padding: 2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .header { text-align: center; margin-bottom: 1.5rem; }
    .brand { font-size: 2.5rem; margin-bottom: 0.5rem; display: block; }
    h1 { font-size: 1.4rem; color: var(--primary); }
    .app-box { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin: 1.25rem 0; }
    .user-code { font-size: 1.2rem; font-weight: bold; letter-spacing: 0.1em; color: var(--primary); }
    .scopes { list-style: none; margin: 1rem 0; font-size: 0.9rem; }
    .scopes li { margin: 0.4rem 0; display: flex; align-items: center; gap: 0.5rem; }
    .form-group { margin: 1.25rem 0; }
    label { display: block; font-weight: 600; margin-bottom: 0.5rem; font-size: 0.9rem; }
    input[type="password"] { width: 100%; padding: 0.75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--card-bg); color: var(--text); font-size: 1rem; }
    .actions { display: grid; grid-template-columns: 1fr 1.5fr; gap: 0.75rem; margin-top: 1.5rem; }
    button { padding: 0.75rem 1rem; border-radius: 6px; font-weight: 600; font-size: 1rem; cursor: pointer; border: none; }
    .btn-deny { background: transparent; border: 1px solid var(--border); color: var(--muted); }
    .btn-deny:hover { border-color: var(--danger); color: var(--danger); }
    .btn-approve { background: var(--success); color: #fff; }
    .btn-approve:hover { opacity: 0.9; }
    .notice { font-size: 0.8rem; color: var(--muted); text-align: center; margin-top: 1.25rem; }
  </style>
</head>
<body>
  <main class="card" role="main">
    <div class="header">
      <span class="brand" aria-hidden="true">🧠</span>
      <h1>Authorization Request</h1>
      <p style="color: var(--muted); font-size: 0.9rem;">Joplin Server Vector Memory</p>
    </div>

    <div class="app-box">
      <div><strong>Application:</strong> ${escapeHtml(pendingItem.client_name)}</div>
      <div style="font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem;">Client ID: <code>${escapeHtml(clientId)}</code></div>
      <div style="margin-top: 0.5rem;">Verification Code: <span class="user-code">${userCode}</span></div>
    </div>

    <ul class="scopes">
      <li><span>🔍</span> Search &amp; retrieve notes</li>
      <li><span>🧠</span> Record memories and context</li>
    </ul>

    <form method="POST" action="/oauth/authorize">
      <input type="hidden" name="request_id" value="${requestId}">
      
      <div class="form-group">
        <label for="shared-secret">Owner Confirmation Password / Secret:</label>
        <input type="password" id="shared-secret" name="shared_secret" placeholder="Joplin Password or Client Secret" required autocomplete="current-password">
        <p style="font-size: 0.8rem; color: var(--muted); margin-top: 0.3rem;">
          Or approve this request from your Admin Dashboard under "Pending Approvals".
        </p>
      </div>

      <div class="actions">
        <button type="submit" name="action" value="deny" class="btn-deny">Deny</button>
        <button type="submit" name="action" value="approve" class="btn-approve">Approve Access</button>
      </div>
    </form>

    <p class="notice">This page automatically redirects once approved.</p>
  </main>

  <script>
    // Poll for out-of-band admin dashboard approval
    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch('/oauth/requests/${requestId}/status');
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'approved' && data.redirect_url) {
            clearInterval(pollInterval);
            window.location.href = data.redirect_url;
          } else if (data.status === 'rejected' && data.redirect_url) {
            clearInterval(pollInterval);
            window.location.href = data.redirect_url;
          }
        }
      } catch (_e) {}
    }, 2000);
  </script>
</body>
</html>`;

    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.send(html);
  });

  // -------------------------------------------------------------
  // 3. POST /oauth/authorize - On-page form submit
  // -------------------------------------------------------------
  router.post('/oauth/authorize', express.urlencoded({ extended: false }), (req, res) => {
    cleanup();
    const { request_id: requestId, action, shared_secret: sharedSecret } = req.body;
    const pendingItem = pendingRequests.get(requestId);

    if (!pendingItem) {
      return res.status(400).send('Authorization request expired or invalid.');
    }

    if (action === 'deny') {
      pendingRequests.delete(requestId);
      const target = new URL(pendingItem.redirect_uri);
      target.searchParams.set('error', 'access_denied');
      if (pendingItem.state) target.searchParams.set('state', pendingItem.state);
      return res.redirect(target.toString());
    }

    const config = loadConfig();
    const isValid = verifySecret(sharedSecret, pendingItem.client_id, config);
    if (!isValid) {
      return res.status(401).send('Invalid password or shared secret. Please try again.');
    }

    // Issue authorization code
    const code = 'jms_code_' + crypto.randomBytes(24).toString('base64url');
    authCodes.set(code, {
      code,
      client_id: pendingItem.client_id,
      redirect_uri: pendingItem.redirect_uri,
      code_challenge: pendingItem.code_challenge,
      code_challenge_method: pendingItem.code_challenge_method,
      scope: pendingItem.scope,
      expires_at: Date.now() + 60 * 1000 // 60s TTL
    });

    const target = new URL(pendingItem.redirect_uri);
    target.searchParams.set('code', code);
    if (pendingItem.state) target.searchParams.set('state', pendingItem.state);

    pendingItem.status = 'approved';
    pendingItem.redirect_url = target.toString();

    // Redirect user
    res.redirect(target.toString());
  });

  // -------------------------------------------------------------
  // 4. GET /oauth/requests/:id/status - Status polling for waiting page
  // -------------------------------------------------------------
  router.get('/oauth/requests/:id/status', (req, res) => {
    cleanup();
    const item = pendingRequests.get(req.params.id);
    if (!item) {
      return res.json({ status: 'expired' });
    }
    res.json({
      status: item.status,
      redirect_url: item.redirect_url
    });
  });

  // -------------------------------------------------------------
  // 5. POST /oauth/token - Token exchange
  // -------------------------------------------------------------
  router.post('/oauth/token', express.urlencoded({ extended: false }), express.json(), (req, res) => {
    cleanup();
    const grantType = req.body.grant_type;

    if (grantType !== 'authorization_code') {
      return res.status(400).json({
        error: 'unsupported_grant_type',
        error_description: 'Only authorization_code grant is supported.'
      });
    }

    const {
      code,
      redirect_uri: redirectUri,
      code_verifier: codeVerifier
    } = req.body;

    let clientId = req.body.client_id;
    let clientSecret = req.body.client_secret;

    // Support HTTP Basic Auth for client credentials
    const authHeader = req.headers.authorization;
    if (authHeader && authHeader.startsWith('Basic ')) {
      try {
        const decoded = Buffer.from(authHeader.slice(6), 'base64').toString('utf8');
        const [u, ...p] = decoded.split(':');
        clientId = decodeURIComponent(u);
        clientSecret = decodeURIComponent(p.join(':'));
      } catch (err) {
        console.debug('Failed to decode Basic auth credentials in token exchange', err);
      }
    }

    if (!code) {
      return res.status(400).json({ error: 'invalid_request', error_description: 'Missing code.' });
    }

    const storedCode = authCodes.get(code);
    if (!storedCode) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'Invalid or expired authorization code.' });
    }

    // Burn code immediately (single-use)
    authCodes.delete(code);

    // Validate redirect_uri and client_id
    if (storedCode.redirect_uri !== redirectUri) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'redirect_uri mismatch.' });
    }

    if (clientId && storedCode.client_id !== clientId) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'client_id mismatch.' });
    }

    // PKCE verification
    if (!codeVerifier) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'code_verifier required.' });
    }

    const calculatedChallenge = crypto.createHash('sha256').update(codeVerifier).digest('base64url');
    const bufA = Buffer.from(calculatedChallenge);
    const bufB = Buffer.from(storedCode.code_challenge);

    if (bufA.length !== bufB.length || !crypto.timingSafeEqual(bufA, bufB)) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'PKCE verification failed.' });
    }

    // If client is registered with secret, verify secret
    const config = loadConfig();
    const registeredClient = (config.oauth_clients || []).find(c => c.client_id === storedCode.client_id);
    if (registeredClient?.client_secret_hash) {
      if (!clientSecret || !timingSafeHashMatch(clientSecret, registeredClient.client_secret_hash)) {
        return res.status(401).json({ error: 'invalid_client', error_description: 'Client authentication failed.' });
      }
    }

    // Issue Bearer access token
    const token = 'JMS_' + crypto.randomUUID().replaceAll('-', '');
    if (!config.api_keys) config.api_keys = [];
    config.api_keys.push({
      key: token,
      annotation: `OAuth: ${storedCode.client_id}`,
      expires_at: null
    });

    saveConfig(config);

    res.json({
      access_token: token,
      token_type: 'Bearer',
      expires_in: 31536000,
      scope: storedCode.scope || 'mcp'
    });
  });

  // -------------------------------------------------------------
  // 6. Admin API Endpoints (Protected by Admin Auth in index.js)
  // -------------------------------------------------------------

  // List registered OAuth clients
  router.get('/auth/oauth/clients', (_req, res) => {
    const config = loadConfig();
    const clients = (config.oauth_clients || []).map(c => ({
      client_id: c.client_id,
      name: c.name,
      redirect_uris: c.redirect_uris || [],
      created_at: c.created_at
    }));
    res.json({ clients });
  });

  // Create new OAuth client
  router.post('/auth/oauth/clients/create', express.json(), (req, res) => {
    const { name, client_id: customId, redirect_uri: redirectUri } = req.body;
    const config = loadConfig();
    if (!config.oauth_clients) config.oauth_clients = [];

    const clientId = customId?.trim() || ('client_' + crypto.randomBytes(6).toString('hex'));
    if (config.oauth_clients.some(c => c.client_id === clientId)) {
      return res.status(400).json({ error: 'Client ID already exists.' });
    }

    const plainSecret = 'secret_' + crypto.randomBytes(24).toString('hex');
    const secretHash = 'sha256:' + crypto.createHash('sha256').update(plainSecret).digest('hex');

    const newClient = {
      client_id: clientId,
      name: name || clientId,
      client_secret_hash: secretHash,
      redirect_uris: redirectUri ? [redirectUri.trim()] : [],
      created_at: new Date().toISOString()
    };

    config.oauth_clients.push(newClient);
    saveConfig(config);

    res.json({
      success: true,
      client: {
        client_id: clientId,
        client_secret: plainSecret, // Plaintext displayed ONCE on creation
        name: newClient.name,
        redirect_uris: newClient.redirect_uris
      }
    });
  });

  // Delete OAuth client
  router.post('/auth/oauth/clients/delete', express.json(), (req, res) => {
    const { client_id: clientId } = req.body;
    const config = loadConfig();
    if (config.oauth_clients) {
      config.oauth_clients = config.oauth_clients.filter(c => c.client_id !== clientId);
      saveConfig(config);
    }
    res.json({ success: true });
  });

  // List active pending authorization requests
  router.get('/auth/oauth/pending', (_req, res) => {
    cleanup();
    const list = [];
    for (const reqItem of pendingRequests.values()) {
      if (reqItem.status === 'pending') {
        list.push({
          id: reqItem.id,
          user_code: reqItem.user_code,
          client_id: reqItem.client_id,
          client_name: reqItem.client_name,
          redirect_uri: reqItem.redirect_uri,
          scope: reqItem.scope,
          created_at: reqItem.created_at
        });
      }
    }
    res.json({ pending: list });
  });

  // Approve a pending request from the Admin Dashboard
  router.post('/auth/oauth/pending/:id/approve', (_req, res) => {
    cleanup();
    const pendingItem = pendingRequests.get(_req.params.id);
    if (!pendingItem || pendingItem.status !== 'pending') {
      return res.status(404).json({ error: 'Pending request not found or expired.' });
    }

    const code = 'jms_code_' + crypto.randomBytes(24).toString('base64url');
    authCodes.set(code, {
      code,
      client_id: pendingItem.client_id,
      redirect_uri: pendingItem.redirect_uri,
      code_challenge: pendingItem.code_challenge,
      code_challenge_method: pendingItem.code_challenge_method,
      scope: pendingItem.scope,
      expires_at: Date.now() + 60 * 1000
    });

    const target = new URL(pendingItem.redirect_uri);
    target.searchParams.set('code', code);
    if (pendingItem.state) target.searchParams.set('state', pendingItem.state);

    pendingItem.status = 'approved';
    pendingItem.redirect_url = target.toString();

    res.json({ success: true, redirect_url: target.toString() });
  });

  // Deny a pending request from the Admin Dashboard
  router.post('/auth/oauth/pending/:id/deny', (_req, res) => {
    cleanup();
    const pendingItem = pendingRequests.get(_req.params.id);
    if (!pendingItem || pendingItem.status !== 'pending') {
      return res.status(404).json({ error: 'Pending request not found or expired.' });
    }

    const target = new URL(pendingItem.redirect_uri);
    target.searchParams.set('error', 'access_denied');
    if (pendingItem.state) target.searchParams.set('state', pendingItem.state);

    pendingItem.status = 'rejected';
    pendingItem.redirect_url = target.toString();

    res.json({ success: true, redirect_url: target.toString() });
  });

  return router;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

module.exports = {
  createOAuthRouter
};
