const express = require('express');
const cors = require('cors');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { JoplinSyncClient } = require('./sync');

const app = express();
app.use(cors());

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

const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '../data');
const CONFIG_PATH = path.join(DATA_DIR, 'config.json');

// Ensure data dir exists
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
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
- \`search_notes\`: Search notes semantically using a query.
- \`get_note\`: Fetch full note content by ID.
- \`remember\`: Save a new note into the memory bank.
- \`delete_note\`: Delete a note by ID.
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

  let joplinUrl = process.env.JOPLIN_SERVER_URL;
  let proxyConfig = null;

  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const data = await fs.promises.readFile(CONFIG_PATH, 'utf8');
      proxyConfig = JSON.parse(data);
      if (!joplinUrl && proxyConfig.joplinServerUrl) {
        joplinUrl = proxyConfig.joplinServerUrl;
      }
    } catch(e) {
      // ignore parse errors
    }
  }

  const send401 = () => {
    if (req.path === '/' || req.path === '/index.html') {
      res.setHeader('WWW-Authenticate', 'Basic realm="Joplin Sync Client"');
    }
    return res.status(401).send('Authentication required.');
  };

  const authHeader = req.headers.authorization;
  if (!authHeader) {
    return send401();
  }

  const match = authHeader.match(/^Basic\s+(.*)$/i);
  if (!match) {
    return send401();
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
  
  if (isSetupMode) {
      if (reqUser === 'setup' && reqPass === '1-mcp-server') {
          authCache.set(base64Credentials, now);
          return next();
      } else {
          return send401();
      }
  }

  // Enforce username lock: if we have a configured username, reject any other username immediately
  if (reqUser !== proxyConfig.joplinUsername) {
      authCache.delete(base64Credentials);
      return send401();
  }

  const onAuthSuccess = () => {
      authCache.set(base64Credentials, now);
      globalCredentials.password = reqPass;
      
      // Optimistically assume master password is the sync password if not set
      if (!globalCredentials.masterPassword) {
          globalCredentials.masterPassword = reqPass; 
      }
      
      // Auto-unlock: If we have a proxy config but sync isn't running or errored, try to start it
      if (proxyConfig && proxyConfig.joplinServerUrl && proxyConfig.joplinUsername) {
        if (!isProcessing && (!syncState || syncState.status === 'ready' || syncState.status === 'offline' || syncState.status === 'error' || syncState.error?.includes('credentials'))) {
             // Only auto-start if it seems like we need to (e.g. boot up state)
             // We use a small timeout to avoid blocking the auth request itself
             setTimeout(() => {
                 if (!isProcessing && (!syncState || syncState.status === 'ready' || syncState.status === 'offline' || syncState.status === 'error' || syncState.error?.includes('credentials'))) {
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
      return send401();
    }
  }

  try {
    const response = await fetch(`${joplinUrl}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: reqUser, password: reqPass })
    });

    if (response.ok) {
      return onAuthSuccess();
    } else {
      authCache.delete(base64Credentials);
      return send401();
    }
  } catch (err) {
    console.error('Joplin Server unreachable:', err);
    process.exit(1);
  }
});

let isProcessing = false;
let syncState = { status: 'ready', progress: null, error: null };
let embeddingState = { status: 'ready', progress: null, error: null };
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
    
    res.json({ id: newNote.id, status: 'success' });
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

app.use(express.static(path.join(__dirname, '../public')));
app.get('/', (req, res) => {
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
    } catch(e) {}
  }
  res.json({ syncState, embeddingState, config });
});

app.post('/auth', async (req, res) => {
  const { serverUrl, username, password, masterPassword, memoryServerAddress, rotate } = req.body;
  
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const data = await fs.promises.readFile(CONFIG_PATH, 'utf8');
      config = JSON.parse(data);
    } catch(e) {}
  }

  if (rotate) {
    const newToken = crypto.randomUUID();
    config.token = newToken;
    try {
      fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
    } catch (err) {
      console.error('Failed to write config.json:', err);
      return res.status(500).json({ error: 'Failed to save new token' });
    }
    return res.json({ token: newToken });
  }

  if (!serverUrl || !username || !password) {
    return res.status(400).json({ error: 'Missing credentials' });
  }

  if (config.joplinUsername && config.joplinUsername !== username) {
      return res.status(403).json({ error: 'System is already locked to a different username.' });
  }

  // Ping or SSL validation
  try {
    const fetchWithTimeout = async (url) => {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await fetch(url, { signal: controller.signal });
        clearTimeout(id);
        return response;
      } catch (err) {
        clearTimeout(id);
        throw err;
      }
    };
    
    // Attempt a basic check against the server
    const checkRes = await fetchWithTimeout(`${serverUrl}/api/ping`).catch(() => fetchWithTimeout(`${serverUrl}/login`)).catch(() => fetchWithTimeout(serverUrl));
    
    if (!checkRes || !checkRes.ok) {
      if (checkRes && checkRes.status !== 404 && checkRes.status !== 401 && checkRes.status !== 403) {
        // Many APIs might return 404/401/403 for unauthorized paths but it proves the server is up
        console.warn('Server responded with status:', checkRes.status);
      }
    }
  } catch (err) {
    return res.status(400).json({ error: 'Failed to validate server: ' + err.message });
  }

  const token = config.token || crypto.randomUUID();
  const isMarriage = !config.joplinUsername;

  globalCredentials.password = password;
  globalCredentials.masterPassword = masterPassword;
  
  config = { 
    ...config, 
    joplinServerUrl: serverUrl, 
    joplinUsername: username, 
    memoryServerAddress,
    token 
  };
  delete config.joplinPassword;
  delete config.joplinMasterPassword;
  
  try {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
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

  // Re-init sync client in background
  startSync(config);

  res.json({ success: true, token });
});

app.post('/auth/wipe', async (req, res) => {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      fs.unlinkSync(CONFIG_PATH);
    }
    
    // Stop the background sync loop
    if (syncIntervalId) {
      clearInterval(syncIntervalId);
      syncIntervalId = null;
    }
    
    // Nuke the database and profile
    const profileDir = process.env.JOPLIN_PROFILE_DIR || path.join(DATA_DIR, 'joplin-profile');
    if (fs.existsSync(profileDir)) {
      fs.rmSync(profileDir, { recursive: true, force: true });
    }
    
    const dbPath = process.env.SQLITE_DB_PATH || path.join(DATA_DIR, 'vector_memory.sqlite');
    if (fs.existsSync(dbPath)) {
      fs.unlinkSync(dbPath);
    }

    // Reset memory state
    syncClient = null;
    isProcessing = false;
    syncState = { status: 'ready', progress: null, error: null };
    embeddingState = { status: 'ready', progress: null, error: null };
    globalCredentials = { password: null, masterPassword: null };
    authCache.clear();

    res.json({ success: true, message: 'System completely reset.' });
    
    // Force exit to ensure clean slate (Docker will restart it)
    setTimeout(() => process.exit(0), 500);
  } catch (err) {
    console.error('Failed to wipe system:', err);
    res.status(500).json({ error: 'Failed to wipe system: ' + err.message });
  }
});

let syncIntervalId = null;

async function runSyncCycle(config) {
  if (isProcessing) return;
  isProcessing = true;
  try {
    if (!syncClient) {
      syncClient = new JoplinSyncClient({
        serverUrl: config.joplinServerUrl,
        username: config.joplinUsername,
        password: config.joplinPassword,
        masterPassword: config.joplinMasterPassword,
        profileDir: process.env.JOPLIN_PROFILE_DIR || path.join(DATA_DIR, 'joplin-profile'),
      });
      
      syncClient.on('syncStart', () => { syncState.status = 'syncing'; syncState.progress = null; syncState.error = null; console.log('Sync started...'); });
      syncClient.on('syncComplete', () => { syncState.status = 'ready'; console.log('Sync completed.'); });
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
    
    await syncClient.sync();
    await syncClient.decrypt();
    await syncClient.generateEmbeddings();
    
  } catch (err) {
    console.error('Cycle top-level error:', err);
    if (syncState.status === 'syncing') {
      syncState.status = 'error';
      syncState.error = err.message;
    } else if (embeddingState.status === 'embedding') {
      embeddingState.status = 'error';
      embeddingState.error = err.message;
    } else {
      syncState.status = 'error';
      syncState.error = 'Initialization or cycle failed: ' + err.message;
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
     fs.writeFileSync(CONFIG_PATH, JSON.stringify(initialConfig, null, 2));
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
