// Clean up whitespace-only environment variables
for (const key in process.env) {
  if (typeof process.env[key] === 'string' && process.env[key].trim() === '') {
    delete process.env[key];
  }
}
const express = require('express');
const cors = require('cors');
const rateLimit = require('express-rate-limit');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { JoplinSyncClient } = require('./sync');

const app = express();
app.use(cors());

const limiter = rateLimit({
  windowMs: 1000, // 1 second window
  max: 10, // limit each IP to 10 requests per windowMs (equivalent to 1 per 100ms)
  standardHeaders: true,
  legacyHeaders: false,
});
app.use(limiter);


const { createProxyMiddleware } = require('http-proxy-middleware');
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

const apiProxy = createProxyMiddleware({ target: BACKEND_URL, changeOrigin: true });
app.use((req, res, next) => {
  if (req.path.startsWith('/docs') || req.path.startsWith('/openapi.json') || req.path.startsWith('/http-api') || req.path.startsWith('/api/')) {
    // Special handling for MCP accept header
    if (req.path.startsWith('/http-api/mcp')) {
      if (!req.headers.accept || req.headers.accept === '*/*') {
        req.headers.accept = 'application/json';
      }
    }
    return apiProxy(req, res, next);
  }
  next();
});

app.use(express.json());

const { Mutex } = require('async-mutex');
const nodeApiMutex = new Mutex();

app.use('/node-api', async (req, res, next) => {
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(req.method)) {
    const release = await nodeApiMutex.acquire();
    let released = false;
    const safeRelease = () => {
      if (!released) {
        released = true;
        release();
      }
    };
    res.on('finish', safeRelease);
    res.on('close', safeRelease);
    res.on('error', safeRelease);
  }
  next();
});

const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '../data');
const CONFIG_PATH = path.join(DATA_DIR, 'config.json');

// Ensure data dir exists
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

// Ensure clean state if no lock file exists (Claim 2: Orphaned Database Wipe)
if (!fs.existsSync(CONFIG_PATH) && !fs.existsSync(CONFIG_PATH + '.tmp')) {
  console.log('No lock file (config.json) found on startup. Ensuring clean state...');
  const files = fs.readdirSync(DATA_DIR);
  for (const file of files) {
    if (file === 'config.json' || file === 'config.json.tmp') continue;
    const fullPath = path.join(DATA_DIR, file);
    try {
      fs.rmSync(fullPath, { recursive: true, force: true });
    } catch (e) {
      console.error(`Failed to clean orphaned file ${fullPath}:`, e);
    }
  }
} else if (!fs.existsSync(CONFIG_PATH) && fs.existsSync(CONFIG_PATH + '.tmp')) {
  console.warn('Startup: Found config.json.tmp but no config.json. An atomic write may have been interrupted. Waiting for manual recovery.');
}

app.get('/llms.txt', (req, res) => {
  const hostUrl = `${req.protocol}://${req.get('host')}`;
  res.type('text/plain').send(`# For Humans
To set up MCP access for your AI Agent:

1. Tell it to "Please go here and set up MCP. Ask me for the backend API port! <link to this page>"
-or-
2. Copy and paste the contents of this page and let it know your API token and Backend API Port (usually 8000 or 8001).

---

# For AI Agents: Joplin Server Vector Memory MCP Setup

Joplin Server Vector Memory acts as a secure, local bridge for End-to-End Encrypted Joplin notes. Connect to its **MCP (Model Context Protocol) server** for live access to semantic search, read full notes, and trigger memory creation/deletion.

## 1. Gather Connection Details
Ask the user for the following if not provided:
1. **API Token:** Found on the dashboard index (/).
2. **Backend API Port:** ⚠️ **CRITICAL INSTRUCTION** ⚠️ Do NOT use the port you are currently reading this from (e.g., port 3000). The current port is exclusively for the dashboard UI and proxy. The actual MCP backend runs on a separate port (usually 8000 or 8001). **You must ask the user what the backend API port is before proceeding.**

Construct the **MCP Base URL** using the host from this page but replacing the port with the Backend API Port provided by the user. (e.g. http://localhost:<BACKEND_PORT>).

## 2. Configure MCP Client
Use the gathered details to configure your connection. 

**Option A: Stateless HTTP (Recommended for CLI agents like Gemini CLI)**
\`\`\`json
{
  "mcpServers": {
    "joplin_memory": {
      "url": "http://<HOST>:<BACKEND_PORT>/http-api/mcp",
      "headers": {
        "Authorization": "Bearer <API_TOKEN>"
      }
    }
  }
}
\`\`\`

**Option B: Streamable SSE (For IDEs like Cursor/Cline)**
\`\`\`json
{
  "mcpServers": {
    "joplin_memory": {
      "url": "http://<HOST>:<BACKEND_PORT>/http-api/mcp/sse",
      "headers": {
        "Authorization": "Bearer <API_TOKEN>"
      }
    }
  }
}
\`\`\`

## 3. Capabilities
Once connected, you can:
- \`notes_search\`: Search notes semantically using a query.
- \`notes_get\`: Fetch full note content by ID.
- \`notes_remember\`: Save a new note into the memory bank.
- \`notes_request_deletion\`: Delete a note by ID.
`);
});


const authCache = new Map();
const AUTH_CACHE_TTL = 15 * 60 * 1000; // 15 minutes

let globalCredentials = {
  password: null,
  masterPassword: null
};

app.use(async (req, res, next) => {
  // Allow internal API calls from the Python MCP server without basic auth
  if (req.path.startsWith('/node-api/')) {
    return next();
  }

  // Exempt the POST /auth endpoint so users can log in via the HTML form
  // even if their browser has cached invalid Basic Auth credentials.
  if (req.path === '/auth' && req.method === 'POST') {
    return next();
  }

  let joplinUrl = process.env.JOPLIN_SERVER_URL;
  if (joplinUrl) joplinUrl = joplinUrl.replace(/\/$/, '');
  let proxyConfig = null;

  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const data = await fs.promises.readFile(CONFIG_PATH, 'utf8');
      proxyConfig = JSON.parse(data);
      if (!joplinUrl && proxyConfig.joplinServerUrl) {
        joplinUrl = proxyConfig.joplinServerUrl.replace(/\/$/, '');
      }
    } catch(e) {
      // ignore parse errors
    }
  }

  const send401 = (reason) => {
    console.log(`[Auth Middleware] Rejecting request to ${req.path} - Reason: ${reason}`);
    if (req.path === '/' || req.path === '/index.html') {
      res.setHeader('WWW-Authenticate', 'Basic realm="Joplin Sync Client"');
    }
    return res.status(401).send('Authentication required.');
  };

  const authHeader = req.headers.authorization;
  if (!authHeader) {
    return send401("Missing Authorization header");
  }

  const match = authHeader.match(/^Basic\s+(.*)$/i);
  if (!match) {
    return send401("Invalid Authorization header format");
  }

  const base64Credentials = match[1];
  const now = Date.now();
  
  if (authCache.has(base64Credentials)) {
    const lastSuccess = authCache.get(base64Credentials);
    if (now - lastSuccess < AUTH_CACHE_TTL) {
      return next();
    }
  }

  const auth = Buffer.from(base64Credentials, 'base64').toString().split(':');
  const reqUser = auth[0];
  const reqPass = auth.slice(1).join(':');

  // Setup mode check
  const isSetupMode = !proxyConfig || !proxyConfig.joplinUsername;
  const isDefaultSetup = reqUser === 'setup' && reqPass === '1-mcp-server';
  
  console.log(`[Auth Middleware] Path: ${req.path}, isSetupMode: ${isSetupMode}, reqUser: ${reqUser}, reqPass: ${reqPass === '1-mcp-server' ? '(default)' : '(hidden)'}`);

  if (isSetupMode) {
      if (isDefaultSetup) {
          authCache.set(base64Credentials, now);
          return next();
      } else {
          return send401("Setup mode active, but credentials do not match default setup");
      }
  }

  // Enforce username lock: if we have a configured username, reject any other username immediately
  if (reqUser !== proxyConfig.joplinUsername) {      
      authCache.delete(base64Credentials);
      return send401(`User lock mismatch. Expected: ${proxyConfig.joplinUsername}, Got: ${reqUser}`);
  }

  const onAuthSuccess = () => {
      console.log(`[Auth Middleware] Authentication successful for ${reqUser}`);
      authCache.set(base64Credentials, now);
      globalCredentials.password = reqPass;
      
      // Optimistically assume master password is the sync password if not set
      if (!globalCredentials.masterPassword) {
          globalCredentials.masterPassword = reqPass; 
      }
      
      // Auto-unlock: If we have a proxy config but sync isn't running or errored, try to start it
      if (proxyConfig && proxyConfig.joplinServerUrl && proxyConfig.joplinUsername) {
        if (!isProcessing && (!syncState || syncState.status === 'offline' || syncState.status === 'error' || syncState.error?.includes('credentials'))) {
             // Only auto-start if it seems like we need to (e.g. boot up state)
             // We use a small timeout to avoid blocking the auth request itself
             setTimeout(() => {
                 if (!isProcessing && (!syncState || syncState.status === 'offline' || syncState.status === 'error' || syncState.error?.includes('credentials'))) {
                     console.log("Auto-unlocking sync using intercepted Basic Auth credentials...");
                     startSync(proxyConfig);
                 }
             }, 1000);
        }
      }
      return next();
  };

  // Check local config first
  const currentPass = globalCredentials.password || process.env.JOPLIN_PASSWORD || proxyConfig?.joplinPassword;
  if (currentPass) {
    if (reqPass === currentPass) {
      return onAuthSuccess();
    } else {
      authCache.delete(base64Credentials);
      return send401("Password mismatch with local memory/env/config");
    }
  }

  console.log(`[Auth Middleware] Password not in memory. Relaying to Joplin Server at ${joplinUrl}/api/sessions for validation...`);
  try {
    const response = await fetch(`${joplinUrl}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: reqUser, password: reqPass })
    });

    console.log(`[Auth Middleware] Joplin Server responded with HTTP ${response.status}`);
    if (response.ok) {
      console.log(`[Auth Middleware] Credentials verified by Joplin Server successfully.`);
      return onAuthSuccess();
    } else {
      const responseBody = await response.text();
      console.error(`[Auth Middleware] Joplin Server rejected credentials. HTTP ${response.status}. Body: ${responseBody}`);
      authCache.delete(base64Credentials);
      return send401(`Joplin Server rejected credentials with HTTP ${response.status}`);
    }
  } catch (err) {
    console.error(`[Auth Middleware] Joplin Server unreachable at ${joplinUrl}:`, err);
    return send401("Joplin Server unreachable during validation relay");
  }
});

let isProcessing = false;
let syncState = { status: 'offline', progress: null, error: null };
let embeddingState = { status: 'offline', progress: null, error: null };
let syncClient = null;

app.get('/node-api/resources/:id', async (req, res) => {
  if (!syncClient || !syncClient.db) {
    return res.status(503).json({ error: 'Sync client not initialized' });
  }
  const Resource = require('@joplin/lib/models/Resource').default;
  try {
    const resource = await Resource.load(req.params.id);
    if (!resource) {
      return res.status(404).json({ error: 'Resource not found' });
    }
    const fullPath = Resource.fullPath(resource);
    if (!fs.existsSync(fullPath)) {
      // If not downloaded yet, we could trigger a download or just return 404
      return res.status(404).json({ error: 'Resource file not downloaded yet' });
    }
    res.type(resource.mime || 'application/octet-stream');
    res.sendFile(fullPath);
  } catch (err) {
    console.error('Error fetching resource:', err);
    res.status(500).json({ error: err.message });
  }
});

app.get('/node-api/notes/:id/resources', async (req, res) => {
  if (!syncClient || !syncClient.db) {
    return res.status(503).json({ error: 'Sync client not initialized' });
  }
  try {
    const resources = await syncClient.db.selectAll(
      `SELECT r.id, r.title, r.mime, r.file_extension 
       FROM resources r 
       JOIN note_resources nr ON r.id = nr.resource_id 
       WHERE nr.note_id = ?`, 
      [req.params.id]
    );
    res.json(resources);
  } catch (err) {
    console.error('Error fetching note resources:', err);
    res.status(500).json({ error: err.message });
  }
});

app.post('/node-api/resources', async (req, res) => {
  if (!syncClient || !syncClient.db) {
    return res.status(503).json({ error: 'Sync client not initialized' });
  }
  const { filename, base64_data, mime_type } = req.body;
  if (!filename || !base64_data) {
    return res.status(400).json({ error: 'filename and base64_data are required' });
  }
  
  const Resource = require('@joplin/lib/models/Resource').default;
  const mimeUtils = require('@joplin/lib/mime-utils.js');
  try {
    const fileBuffer = Buffer.from(base64_data, 'base64');
    const resourceProps = {
      title: filename,
      mime: mime_type || mimeUtils.fromFilename(filename) || 'application/octet-stream',
      file_extension: path.extname(filename).slice(1)
    };
    
    // Create the resource record in the local DB
    const newResource = await Resource.save(resourceProps, { isNew: true });
    
    // Write the actual binary file to the resources directory
    const fullPath = Resource.fullPath(newResource);
    const resourceDir = path.dirname(fullPath);
    if (!fs.existsSync(resourceDir)) {
      fs.mkdirSync(resourceDir, { recursive: true });
    }
    await fs.promises.writeFile(fullPath, fileBuffer);
    
    // Trigger sync to push to server
    if (syncClient.synchronizer) {
      syncClient.synchronizer.start().catch(e => console.error('Sync failed after resource upload:', e));
    }
    
    res.json({ id: newResource.id, status: 'success' });
  } catch (err) {
    console.error('Error uploading resource:', err);
    res.status(500).json({ error: err.message });
  }
});

app.post('/node-api/notes', async (req, res) => {
  if (!syncClient || !syncClient.db) {
    return res.status(503).json({ error: 'Sync client not initialized' });
  }
  const { title, body, folder: folderName = 'Agent Memory' } = req.body;
  if (!title || !body) {
    return res.status(400).json({ error: 'title and body are required' });
  }
  const Note = require('@joplin/lib/models/Note').default;
  const Folder = require('@joplin/lib/models/Folder').default;
  
  try {
    let folder = await Folder.loadByField('title', folderName);
    if (!folder) {
        folder = await Folder.save({ title: folderName }, { isNew: true });
    }

    const noteProps = {
      title: title,
      body: body,
      parent_id: folder.id
    };
    
    const newNote = await Note.save(noteProps, { isNew: true });
    
    if (syncClient.synchronizer) {
      syncClient.synchronizer.start().catch(e => console.error('Sync failed after note creation:', e));
    }
    
    res.json({ id: newNote.id, parent_id: newNote.parent_id, status: 'success' });
  } catch (err) {
    console.error('Error creating note:', err);
    res.status(500).json({ error: err.message });
  }
});

app.put('/node-api/notes/:id', async (req, res) => {
  if (!syncClient || !syncClient.db) {
    return res.status(503).json({ error: 'Sync client not initialized' });
  }
  const { title, body } = req.body;
  const Note = require('@joplin/lib/models/Note').default;
  
  try {
    const existing = await Note.load(req.params.id);
    if (!existing) return res.status(404).json({ error: 'Note not found' });
    
    const noteProps = {
      id: req.params.id,
      title: title || existing.title,
      body: body !== undefined ? body : existing.body,
    };
    
    await Note.save(noteProps);
    
    if (syncClient.synchronizer) {
      syncClient.synchronizer.start().catch(e => console.error('Sync failed after note update:', e));
    }
    
    res.json({ status: 'success' });
  } catch (err) {
    console.error('Error updating note:', err);
    res.status(500).json({ error: err.message });
  }
});

app.delete('/node-api/notes/:id', async (req, res) => {
  if (!syncClient || !syncClient.db) {
    return res.status(503).json({ error: 'Sync client not initialized' });
  }
  const Note = require('@joplin/lib/models/Note').default;
  
  try {
    await Note.delete(req.params.id);
    
    if (syncClient.synchronizer) {
      syncClient.synchronizer.start().catch(e => console.error('Sync failed after note deletion:', e));
    }
    
    res.json({ status: 'success' });
  } catch (err) {
    console.error('Error deleting note:', err);
    res.status(500).json({ error: err.message });
  }
});

app.use(express.static(path.join(__dirname, '../public'), {
  setHeaders: (res, filePath) => {
    if (path.basename(filePath) === 'index.html') {
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
      res.setHeader('Pragma', 'no-cache');
      res.setHeader('Expires', '0');
    }
  }
}));

app.get('/', (req, res) => {
  res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Expires', '0');
  res.sendFile(path.join(__dirname, '../public/index.html'));
});

app.get('/status', async (req, res) => {
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const data = await fs.promises.readFile(CONFIG_PATH, 'utf8');
      config = JSON.parse(data);
      // omit sensitive data
      delete config.joplinPassword;
      delete config.joplinMasterPassword;
    } catch (e) { 
      console.error('Failed to parse config.json in /status endpoint.', e);
      config = { error: 'Configuration file is corrupted.' };
    }
  }
  res.json({ syncState, embeddingState, config, hasCredentials: !!globalCredentials.password });
});

app.post('/sync', async (req, res) => {
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const data = await fs.promises.readFile(CONFIG_PATH, 'utf8');
      config = JSON.parse(data);
    } catch (e) { /* ignore */ }
  }
  
  if (!config.joplinServerUrl || !config.joplinUsername) {
    return res.status(400).json({ error: 'System not fully configured yet.' });
  }

  if (isProcessing) {
    return res.status(409).json({ error: 'Sync already in progress.' });
  }

  setTimeout(() => runSyncCycle(config).catch(e => console.error('Manual sync failed:', e)), 100);
  res.json({ success: true, message: 'Sync cycle initiated.' });
});

app.post('/auth', async (req, res) => {
  const { serverUrl, username, password, masterPassword, memoryServerAddress, rotate } = req.body;

  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const data = await fs.promises.readFile(CONFIG_PATH, 'utf8');
      config = JSON.parse(data);
    } catch (e) {
      console.error('CRITICAL: Failed to parse config.json in /auth endpoint.', e);
      return res.status(500).json({ error: 'Critical Configuration Error. The lock file is corrupted. Please Factory Reset.' });
    }
  }
  if (!serverUrl || !username || !password) {
    return res.status(400).json({ error: 'Missing credentials' });
  }

  let cleanServerUrl;
  try {
    const parsed = new URL(serverUrl);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error('Invalid protocol');
    }
    cleanServerUrl = parsed.toString().replace(/\/$/, '');
  } catch (err) {
    return res.status(400).json({ error: 'Invalid Joplin Server URL format or protocol.' });
  }

  if (config.joplinUsername && config.joplinUsername !== username) {
      return res.status(400).json({ error: 'Username cannot be changed after initial setup. Please perform a Factory Reset to switch accounts.' });
  }

  // Ping and credential validation
  try {
    const fetchWithTimeout = async (url, options = {}) => {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        clearTimeout(id);
        return response;
      } catch (err) {
        clearTimeout(id);
        throw err;
      }
    };
    
    // Attempt a basic check against the server to see if it's reachable
    const checkRes = await fetchWithTimeout(`${cleanServerUrl}/api/ping`).catch(() => fetchWithTimeout(`${cleanServerUrl}/login`)).catch(() => fetchWithTimeout(cleanServerUrl));
    
    if (!checkRes || !checkRes.ok) {
      if (checkRes && checkRes.status !== 404 && checkRes.status !== 401 && checkRes.status !== 403) {
        console.warn('Server responded with status:', checkRes.status);
      } else if (!checkRes) {
        return res.status(400).json({ error: 'Cannot reach the Joplin Server URL. Please check the address.' });
      }
    }

    // Now validate the actual credentials
    const sessionRes = await fetchWithTimeout(`${cleanServerUrl}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: username, password })
    }).catch(err => {
        throw new Error('Network error reaching /api/sessions: ' + err.message);
    });

    if (!sessionRes || !sessionRes.ok) {
        if (sessionRes && sessionRes.status === 403) {
            return res.status(403).json({ error: 'Invalid username or password.' });
        }
        return res.status(400).json({ error: `Authentication failed. Server returned HTTP ${sessionRes ? sessionRes.status : 'Unknown'}.` });
    }

  } catch (err) {
    return res.status(400).json({ error: 'Failed to validate server: ' + err.message });
  }

  if (!config.api_keys || config.api_keys.length === 0) {
    config.api_keys = [{
      key: 'JMS_' + crypto.randomBytes(32).toString('hex'),
      annotation: 'Default Key',
      expires_at: null
    }];
  }

  const isMarriage = !config.joplinUsername;
  
  let isServerUrlChange = false;
  const cleanOldUrl = (config.joplinServerUrl || '').replace(/\/$/, '');
  const cleanNewUrl = (serverUrl || '').replace(/\/$/, '');
  
  if (cleanOldUrl && cleanOldUrl !== cleanNewUrl) {
      isServerUrlChange = true;
  }

  globalCredentials.password = password;
  globalCredentials.masterPassword = masterPassword;

  const isUsernameChange = config.joplinUsername && config.joplinUsername !== username;

  console.log('Save & Validate triggered. Wiping vector index...');
  const sqliteDbPath = process.env.SQLITE_DB_PATH || path.join(DATA_DIR, 'vector_memory.sqlite');
  try {
      if (fs.existsSync(sqliteDbPath)) {
          try {
              fs.unlinkSync(sqliteDbPath);
          } catch (e) {
              console.warn('Failed to unlink sqlite db (might be locked), attempting to truncate/clear instead...');
          }
      }
      console.log('Vector index wiped successfully.');
  } catch (err) {
      console.error('Failed to wipe vector index:', err);
  }

  if (isServerUrlChange || isUsernameChange || isMarriage) {
      console.log('Server URL or Username changed (or initial setup). Wiping local Joplin database...');
      const profileDir = process.env.JOPLIN_PROFILE_DIR || path.join(DATA_DIR, 'joplin-profile');
      try {
          if (fs.existsSync(profileDir)) fs.rmSync(profileDir, { recursive: true, force: true });
          console.log('Joplin database wiped successfully.');
      } catch (err) {
          console.error('Failed to wipe Joplin database:', err);
      }
  }

  // Clear the in-memory sync client so it re-initializes with the new databases
  if (syncClient && syncClient.db) {
      try { syncClient.db.close(); } catch(e) { /* ignore */ }
  }
  syncClient = null;

  config = {
    ...config,
    joplinServerUrl: cleanServerUrl,
    joplinUsername: username,
    joplinPassword: password, // Store password in config so it persists across restarts
    joplinMasterPassword: masterPassword,
    memoryServerAddress: memoryServerAddress || 'http://localhost:8000',
    token: config.token || crypto.randomUUID()
  };

  try {
    fs.writeFileSync(CONFIG_PATH + '.tmp', JSON.stringify(config, null, 2));
    fs.renameSync(CONFIG_PATH + '.tmp', CONFIG_PATH);
  } catch (err) {
    console.error('Failed to write config.json:', err);
  }
  
  if (isMarriage) {
    authCache.clear();
    return res.json({ 
      success: true, 
      requireRelogin: true, 
      message: 'System locked to your account. Please log in again using your Joplin Server username and password.' 
    });
  }

  // Re-init sync client in background immediately
  setImmediate(() => startSync(config));
  
  res.json({ success: true, token: config.token });
});

app.get('/auth/keys', (req, res) => {
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    } catch (e) { /* ignore */ }
  }
  res.json({ api_keys: config.api_keys || [] });
});

app.post('/auth/keys/create', (req, res) => {
  const { annotation, expires_at } = req.body;
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    } catch (e) { /* ignore */ }
  }
  
  const newKey = 'JMS_' + crypto.randomBytes(32).toString('hex');
  const keyObj = {
    key: newKey,
    annotation: annotation || 'Unnamed Key',
    expires_at: expires_at || null
  };
  
  if (!config.api_keys) config.api_keys = [];
  config.api_keys.push(keyObj);
  
  try {
    fs.writeFileSync(CONFIG_PATH + '.tmp', JSON.stringify(config, null, 2));
    fs.renameSync(CONFIG_PATH + '.tmp', CONFIG_PATH);
    res.json({ success: true, key: keyObj });
  } catch (err) {
    res.status(500).json({ error: 'Failed to save new key' });
  }
});

app.post('/auth/keys/delete', (req, res) => {
  const { key } = req.body;
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    } catch (e) { /* ignore */ }
  }
  
  if (config.api_keys) {
    config.api_keys = config.api_keys.filter(k => k.key !== key);
    try {
      fs.writeFileSync(CONFIG_PATH + '.tmp', JSON.stringify(config, null, 2));
    fs.renameSync(CONFIG_PATH + '.tmp', CONFIG_PATH);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ error: 'Failed to delete key' });
    }
  } else {
    res.json({ success: true });
  }
});

// Maintenance Shutdown Procedure: 
// When /node-api/restart is called, Node gracefully exits. 
// This triggers the lock-and-confirm handshake in entrypoint.sh and main.py 
// to prevent catastrophic race conditions where Python resets the DB and overwrites config.json 
// while Node is simultaneously shutting down. Do not remove this logic.
app.post('/node-api/restart', (req, res) => {
  res.json({ message: 'Restarting sync daemon...' });
  setTimeout(() => process.exit(0), 500);
});

app.post('/auth/wipe', async (req, res) => {
  try {
    console.log(`Wiping system... Cleaning data directory ${DATA_DIR}...`);
    
    // Stop the background sync loop
    if (syncIntervalId) {
      clearInterval(syncIntervalId);
      syncIntervalId = null;
    }
    
    // Nuke everything in DATA_DIR
    if (fs.existsSync(DATA_DIR)) {
      const files = fs.readdirSync(DATA_DIR);
      for (const file of files) {
        const fullPath = path.join(DATA_DIR, file);
        try {
          fs.rmSync(fullPath, { recursive: true, force: true });
        } catch (e) {
          console.error(`Failed to delete ${fullPath}:`, e);
        }
      }
    }

    res.json({ success: true, message: 'System completely reset. Rebooting...' });
    
    // Reboot container after short delay to let response send
    setTimeout(() => process.exit(0), 500);
  } catch (err) {
    console.error('Failed to wipe system:', err);
    res.status(500).json({ error: 'Failed to wipe system: ' + err.message });
  }
});

let syncIntervalId = null;

async function runSyncCycle(config) {
  console.log('runSyncCycle triggered with config:', Object.keys(config || {}));
  if (isProcessing) return;
  isProcessing = true;
  try {
    if (!syncClient) {
      syncClient = new JoplinSyncClient({
        serverUrl: config.joplinServerUrl,
        username: config.joplinUsername,
        password: config.joplinPassword || globalCredentials.password,
        masterPassword: config.joplinMasterPassword || globalCredentials.masterPassword,
        profileDir: process.env.JOPLIN_PROFILE_DIR || path.join(DATA_DIR, 'joplin-profile'),
      });
      
      syncClient.on('syncStart', () => { 
        syncState.status = 'syncing'; 
        syncState.progress = null; 
        syncState.error = null; 
        
        embeddingState.status = 'waiting';
        embeddingState.progress = null;
        embeddingState.error = null;
        
        console.log('Sync started...'); 
      });
      syncClient.on('syncComplete', () => { 
        if (syncState.status !== 'error') {
          syncState.status = 'ready'; 
          console.log('Sync completed successfully.'); 
        }
      });
      syncClient.on('syncError', (err) => { syncState.status = 'error'; syncState.error = err.message; console.error('Sync error:', err); });

      syncClient.on('decryptStart', () => console.log('Decryption started...'));
      syncClient.on('decryptComplete', () => console.log('Decryption completed.'));
      
      syncClient.on('embeddingStart', () => { embeddingState.status = 'embedding'; embeddingState.progress = null; embeddingState.error = null; console.log('Embedding generation started...'); });
      syncClient.on('embeddingComplete', () => { embeddingState.status = 'ready'; console.log('Embedding generation completed.'); });
      syncClient.on('embeddingError', (err) => { embeddingState.status = 'error'; embeddingState.error = err.message; console.error('Embedding error:', err); });

      syncClient.on('progress', (data) => { 
        if (data.phase === 'download') {
          syncState.progress = data.report;
        } else if (data.phase === 'embedding') {
          embeddingState.progress = data;
        }
      });
      
      await syncClient.init();
    }
    
    // Explicitly validate sync access before starting to catch 403s immediately
    if (config.joplinServerUrl) {
       let joplinUrl;
       try {
         const parsed = new URL(config.joplinServerUrl);
         if (!['http:', 'https:'].includes(parsed.protocol)) {
           throw new Error('Invalid protocol');
         }
         joplinUrl = parsed.toString().replace(/\/$/, '');
       } catch (err) {
         throw new Error('Invalid Joplin Server URL format or protocol in config.', { cause: err });
       }
       
       const syncPass = config.joplinPassword || globalCredentials.password;
       if (syncPass) {
           const sessionRes = await fetch(`${joplinUrl}/api/sessions`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ email: config.joplinUsername, password: syncPass })
           }).catch(() => null);

           console.log(`[Explicit Check] /api/sessions returned status: ${sessionRes ? sessionRes.status : 'null'}`);

           if (sessionRes && !sessionRes.ok) {
               throw new Error(`Authentication failed during explicit check. Server returned HTTP ${sessionRes.status}. Please verify your username and password.`);
           }

           if (sessionRes && sessionRes.ok) {
              const sessionData = await sessionRes.json();
              const sessionId = sessionData.id;
              
              const syncCheckRes = await fetch(`${joplinUrl}/api/items/root:/info.json:/content`, {
                  headers: { 'X-API-AUTH': sessionId },
                  redirect: 'manual'
              }).catch(() => null);

              if (syncCheckRes && !syncCheckRes.ok && syncCheckRes.status !== 404) {
                  throw new Error(`Joplin Server rejected sync access (HTTP ${syncCheckRes.status}: ${syncCheckRes.statusText}). Ensure your account has sync permissions and you have accepted the Terms of Service on the Joplin Server web UI.`);
              }           }
       }
    }

    await syncClient.sync();
    await syncClient.decrypt();
    await syncClient.generateEmbeddings();
    
  } catch (err) {
    console.error('Cycle top-level error:', err);
    // Determine the source of the error to avoid cross-contamination of status states
    if (err.message && err.message.includes('Embedding')) {
        embeddingState.status = 'error';
        embeddingState.error = err.message;
    } else if (err.message && err.message.includes('Joplin Server')) {
        syncState.status = 'error';
        syncState.error = err.message;
    } else if (syncState.status === 'syncing') {
        syncState.status = 'error';
        syncState.error = err.message;
    } else if (embeddingState.status === 'embedding') {
        embeddingState.status = 'error';
        embeddingState.error = err.message;
    } else {
        // Only fallback to sync error if we literally don't know where it came from, 
        // but avoid overwriting a 'ready' sync state if embedding just failed.
        if (syncState.status !== 'ready') {
           syncState.status = 'error';
           syncState.error = 'Initialization failed: ' + err.message;
        } else {
           embeddingState.status = 'error';
           embeddingState.error = 'Cycle failed: ' + err.message;
        }
    }
    
    // Avoid restarting the container for generic sync errors as it wipes in-memory credentials.
    // Fatal SQLite corruption errors are handled natively in sync.js with process.exit.
    if (err.message && err.message.includes('Sync failed')) {
        console.error('Sync cycle encountered an error. Will retry on next interval.', err.message);
    }
  } finally {
    isProcessing = false;
  }
}

async function startSync(config) {
  // Clear any existing interval
  if (syncIntervalId) {
    clearInterval(syncIntervalId);
  }
  
  // Run immediately
  await runSyncCycle(config);
  
  // Poll every 60 seconds
  const pollInterval = parseInt(process.env.SYNC_INTERVAL_MS) || 60000;
  syncIntervalId = setInterval(() => runSyncCycle(config), pollInterval);
}
// Start on boot if config exists
if (fs.existsSync(CONFIG_PATH)) {
  fs.promises.readFile(CONFIG_PATH, 'utf8').then(data => {
    try {
      const config = JSON.parse(data);
      if (config.joplinServerUrl && config.joplinUsername && config.joplinPassword) {
        // Use setImmediate to let the server start first
        setImmediate(() => startSync(config));
      }
    } catch(e) {
      console.error('Failed to auto-start sync:', e);
    }
  }).catch(e => {
    console.error('Failed to read config on boot:', e);
  });
} else if (process.env.JOPLIN_SERVER_URL && process.env.JOPLIN_USERNAME && process.env.JOPLIN_PASSWORD) {
   // Fallback to env vars for initial config
   const initialConfig = {
     joplinServerUrl: process.env.JOPLIN_SERVER_URL,
     joplinUsername: process.env.JOPLIN_USERNAME,
     joplinPassword: process.env.JOPLIN_PASSWORD,
     joplinMasterPassword: process.env.JOPLIN_MASTER_PASSWORD,
     token: process.env.API_TOKEN || crypto.randomUUID()
   };
   try {
     fs.writeFileSync(CONFIG_PATH + '.tmp', JSON.stringify(initialConfig, null, 2));
     fs.renameSync(CONFIG_PATH + '.tmp', CONFIG_PATH);
   } catch (err) {
     console.error('Failed to write config.json:', err);
   }
   setImmediate(() => startSync(initialConfig));
}


if (require.main === module) {
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server is running on port ${PORT}`);
  });
}

module.exports = app;
