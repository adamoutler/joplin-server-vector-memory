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

app.use(createProxyMiddleware({ pathFilter: '/docs', target: BACKEND_URL, changeOrigin: true }));
app.use(createProxyMiddleware({ pathFilter: '/openapi.json', target: BACKEND_URL, changeOrigin: true }));
app.use('/http-api/mcp', (req, res, next) => {
  if (!req.headers.accept || req.headers.accept === '*/*') {
    req.headers.accept = 'application/json';
  }
  next();
});
app.use(createProxyMiddleware({
  pathFilter: '/http-api',
  target: BACKEND_URL,
  changeOrigin: true,
  pathRewrite: { '^/http-api': '' }
}));

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

app.use(async (req, res, next) => {
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

  if (!joplinUrl) {
    return next();
  }

  const authHeader = req.headers.authorization;
  if (!authHeader) {
    res.setHeader('WWW-Authenticate', 'Basic');
    return res.status(401).send('Authentication required.');
  }

  const match = authHeader.match(/^Basic\s+(.*)$/i);
  if (!match) {
    res.setHeader('WWW-Authenticate', 'Basic');
    return res.status(401).send('Authentication required.');
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

  // Check local config first
  if (proxyConfig && proxyConfig.joplinUsername && proxyConfig.joplinPassword) {
    if (reqUser === proxyConfig.joplinUsername && reqPass === proxyConfig.joplinPassword) {
      authCache.set(base64Credentials, now);
      return next();
    } else {
      authCache.delete(base64Credentials);
      res.setHeader('WWW-Authenticate', 'Basic');
      return res.status(401).send('Authentication required.');
    }
  }

  try {
    const response = await fetch(`${joplinUrl}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: reqUser, password: reqPass })
    });

    if (response.ok) {
      authCache.set(base64Credentials, now);
      return next();
    } else {
      authCache.delete(base64Credentials);
      res.setHeader('WWW-Authenticate', 'Basic');
      return res.status(401).send('Authentication required.');
    }
  } catch (err) {
    console.error('Joplin Server unreachable:', err);
    process.exit(1);
  }
});

let syncStatus = 'ready'; // ready, syncing, error
let syncClient = null;

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
  res.json({ status: syncStatus, config });
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
  config = { 
    ...config, 
    joplinServerUrl: serverUrl, 
    joplinUsername: username, 
    joplinPassword: password, 
    joplinMasterPassword: masterPassword,
    memoryServerAddress,
    token 
  };
  
  try {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
  } catch (err) {
    console.error('Failed to write config.json:', err);
  }
  
  // Re-init sync client in background
  startSync(config);

  res.json({ success: true, token });
});

async function startSync(config) {
  if (syncStatus === 'syncing') return;
  syncStatus = 'syncing';
  try {
    syncClient = new JoplinSyncClient({
      serverUrl: config.joplinServerUrl,
      username: config.joplinUsername,
      password: config.joplinPassword,
      masterPassword: config.joplinMasterPassword,
      profileDir: process.env.JOPLIN_PROFILE_DIR || path.join(DATA_DIR, 'joplin-profile'),
    });
    
    syncClient.on('syncStart', () => { syncStatus = 'syncing'; console.log('Sync started...'); });
    syncClient.on('syncComplete', () => { console.log('Sync completed.'); });
    syncClient.on('decryptStart', () => console.log('Decryption started...'));
    syncClient.on('decryptComplete', () => console.log('Decryption completed.'));
    syncClient.on('embeddingStart', () => { console.log('Embedding generation started...'); });
    syncClient.on('embeddingComplete', () => { console.log('Embedding generation completed.'); });
    
    await syncClient.init();
    await syncClient.sync();
    await syncClient.decrypt();
    await syncClient.generateEmbeddings();
    
    syncStatus = 'ready';
  } catch (err) {
    console.error('Sync error:', err);
    syncStatus = 'error';
  }
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
