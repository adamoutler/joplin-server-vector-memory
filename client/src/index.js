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

app.use(createProxyMiddleware({ pathFilter: '/docs', target: BACKEND_URL, changeOrigin: true, pathRewrite: { '^/docs': '/internal-docs' } }));
app.use(createProxyMiddleware({ pathFilter: '/openapi.json', target: BACKEND_URL, changeOrigin: true, pathRewrite: { '^/openapi.json': '/internal-openapi.json' } }));
app.use(createProxyMiddleware({ pathFilter: '/mcp-server', target: BACKEND_URL, changeOrigin: true }));
app.use(createProxyMiddleware({ pathFilter: '/mcp-server-http', target: BACKEND_URL, changeOrigin: true }));
app.use(createProxyMiddleware({ pathFilter: '/mcp', target: BACKEND_URL, changeOrigin: true }));
app.use(createProxyMiddleware({ pathFilter: '/api', target: BACKEND_URL, changeOrigin: true }));

app.use(express.json());

const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '../../data');
const CONFIG_PATH = path.join(DATA_DIR, 'config.json');

// Ensure data dir exists
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

const authCache = new Map();
const AUTH_CACHE_TTL = 15 * 60 * 1000; // 15 minutes

app.use(async (req, res, next) => {
  const joplinUrl = process.env.JOPLIN_SERVER_URL;
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
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
      if (config.joplinUsername && config.joplinPassword) {
        if (reqUser === config.joplinUsername && reqPass === config.joplinPassword) {
          authCache.set(base64Credentials, now);
          return next();
        } else {
          authCache.delete(base64Credentials);
          res.setHeader('WWW-Authenticate', 'Basic');
          return res.status(401).send('Authentication required.');
        }
      }
    } catch(e) {
      // ignore parse errors and fallback
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

app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Joplin Memory Server Dashboard</title>
      <style>
        body { font-family: sans-serif; margin: 2rem; max-width: 600px; background: #f9f9f9; color: #333; }
        .container { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        h1, h2 { color: #0056b3; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-weight: bold; }
        input[type="text"], input[type="password"] { width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        button { padding: 0.75rem 1.5rem; background: #0056b3; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }
        button:hover { background: #004494; }
        .status { margin-bottom: 2rem; padding: 1rem; background: #e9ecef; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; }
        .status h2 { margin: 0; font-size: 1.25rem; color: #333; }
        #status-text { font-weight: bold; text-transform: uppercase; }
        .status-ready { color: green; }
        .status-syncing { color: orange; }
        .status-error { color: red; }
        .status-offline { color: gray; }
        .token-group { display: flex; gap: 1rem; align-items: center; }
        #token { flex-grow: 1; font-family: monospace; background: #f4f4f4; cursor: text; }
        .messages { margin-top: 1rem; font-weight: bold; }
        .error { color: red; }
        .success { color: green; }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Joplin Memory Server Dashboard</h1>
        <div class="status">
          <h2>Sync Status: <span id="status-text" class="status-offline">Offline</span></h2>
        </div>
        
        <h2>Configuration</h2>
        <form id="auth-form">
          <div class="form-group">
            <label>Joplin Server URL</label>
            <input type="text" id="serverUrl" placeholder="https://joplin.yourdomain.com" required>
          </div>
          <div class="form-group">
            <label>Username (Email)</label>
            <input type="text" id="username" placeholder="user@example.com" required>
          </div>
          <div class="form-group">
            <label>Password</label>
            <input type="password" id="password" required>
          </div>
          <div class="form-group">
            <label>Master Password (Optional, for E2EE)</label>
            <input type="password" id="masterPassword">
          </div>
          <div class="form-group">
            <label>Memory Server Address</label>
            <input type="text" id="memoryServerAddress" placeholder="http://localhost:3000" required>
          </div>
          <button type="submit">Save & Validate</button>
          <div id="auth-msg" class="messages"></div>
        </form>

        <h2 style="margin-top: 2rem;">Local Access Token</h2>
        <p>Use this token for your MCP client configuration.</p>
        <div class="token-group">
          <input type="text" id="token" readonly>
          <button id="rotate-btn">Rotate Token</button>
        </div>
        <div id="token-msg" class="messages"></div>

        <h2 style="margin-top: 2rem;">API Documentation</h2>
        <div style="background: #f4f4f4; padding: 1rem; border-radius: 4px;">
          <ul>
            <li><a href="/docs" target="_blank" id="docs-link">Interactive API Docs (Swagger UI)</a></li>
            <li><a href="/openapi.json" target="_blank" id="openapi-link">OpenAPI Schema</a></li>
          </ul>
        </div>

        <h2 style="margin-top: 2rem;">MCP Server Examples</h2>
        <div id="mcp-examples" style="display: none; background: #f4f4f4; padding: 1rem; border-radius: 4px;">
          <h3>HTTP API Address</h3>
          <pre><code id="example-http"></code></pre>
          <h3>MCP API Address</h3>
          <pre><code id="example-mcp"></code></pre>
          <h3>MCP Client Configuration Example</h3>
          <pre><code id="example-cli"></code></pre>
        </div>
      </div>

      <script>
        async function fetchStatus() {
          try {
            const res = await fetch('/status');
            const data = await res.json();
            const el = document.getElementById('status-text');
            el.innerText = data.status;
            el.className = 'status-' + data.status;
            if (data.config && data.config.token) {
               const tokenEl = document.getElementById('token');
               if (!tokenEl.value) {
                 tokenEl.value = data.config.token;
               }
               const updateIfInactive = (id, val) => {
                 const el = document.getElementById(id);
                 if (document.activeElement !== el && el.value === '') {
                   el.value = val;
                 } else if (document.activeElement !== el && el.value !== val) {
                   el.value = val;
                 }
               };
               
               updateIfInactive('serverUrl', data.config.joplinServerUrl || '');
               updateIfInactive('username', data.config.joplinUsername || '');
               updateIfInactive('memoryServerAddress', data.config.memoryServerAddress || '');
               // don't populate password
               
               const memAddr = window.location.origin;
               document.getElementById('mcp-examples').style.display = 'block';
               document.getElementById('example-http').innerText = memAddr;
               document.getElementById('example-mcp').innerText = memAddr + '/mcp/http/api-key/mcp/sse';
               document.getElementById('example-cli').innerText = JSON.stringify({
                 "mcpServers": {
                   "joplin_memory": {
                     "url": memAddr + "/mcp/http/api-key/mcp/sse",
                     "headers": {
                       "Authorization": "Bearer " + data.config.token
                     }
                   }
                 }
               }, null, 2);
            }
          } catch(e) {
            const el = document.getElementById('status-text');
            el.innerText = 'offline';
            el.className = 'status-offline';
          }
        }
        setInterval(fetchStatus, 5000);
        fetchStatus();

        document.getElementById('auth-form').addEventListener('submit', async (e) => {
          e.preventDefault();
          const serverUrl = document.getElementById('serverUrl').value;
          const username = document.getElementById('username').value;
          const password = document.getElementById('password').value;
          const masterPassword = document.getElementById('masterPassword').value;
          const memoryServerAddress = document.getElementById('memoryServerAddress').value;
          const msgEl = document.getElementById('auth-msg');
          msgEl.innerText = 'Validating...';
          msgEl.className = 'messages';
          
          try {
            const res = await fetch('/auth', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ serverUrl, username, password, masterPassword, memoryServerAddress })
            });
            const data = await res.json();
            if (res.ok) {
              msgEl.innerText = 'Saved successfully!';
              msgEl.className = 'messages success';
              document.getElementById('token').value = data.token;
              fetchStatus(); // refresh status which might be syncing now
            } else {
              msgEl.innerText = 'Error: ' + data.error;
              msgEl.className = 'messages error';
            }
          } catch(err) {
            msgEl.innerText = 'Network error: ' + err.message;
            msgEl.className = 'messages error';
          }
        });

        document.getElementById('rotate-btn').addEventListener('click', async () => {
          const msgEl = document.getElementById('token-msg');
          try {
            const res = await fetch('/auth', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ rotate: true })
            });
            const data = await res.json();
            if (res.ok) {
              document.getElementById('token').value = data.token;
              msgEl.innerText = 'Token rotated successfully.';
              msgEl.className = 'messages success';
              setTimeout(() => msgEl.innerText = '', 3000);
            } else {
              msgEl.innerText = 'Error: ' + data.error;
              msgEl.className = 'messages error';
            }
          } catch(err) {
            msgEl.innerText = 'Network error: ' + err.message;
            msgEl.className = 'messages error';
          }
        });
      </script>
    </body>
    </html>
  `);
});

app.get('/status', (req, res) => {
  let config = {};
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
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
      config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    } catch(e) {}
  }

  if (rotate) {
    const newToken = crypto.randomUUID();
    config.token = newToken;
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
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
  
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
  
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
  try {
    const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    if (config.joplinServerUrl && config.joplinUsername && config.joplinPassword) {
      // Use setImmediate to let the server start first
      setImmediate(() => startSync(config));
    }
  } catch(e) {
    console.error('Failed to parse config on boot:', e);
  }
} else if (process.env.JOPLIN_SERVER_URL && process.env.JOPLIN_USERNAME && process.env.JOPLIN_PASSWORD) {
   // Fallback to env vars for initial config
   const initialConfig = {
     joplinServerUrl: process.env.JOPLIN_SERVER_URL,
     joplinUsername: process.env.JOPLIN_USERNAME,
     joplinPassword: process.env.JOPLIN_PASSWORD,
     joplinMasterPassword: process.env.JOPLIN_MASTER_PASSWORD,
     token: process.env.API_TOKEN || crypto.randomUUID()
   };
   fs.writeFileSync(CONFIG_PATH, JSON.stringify(initialConfig, null, 2));
   setImmediate(() => startSync(initialConfig));
}

if (require.main === module) {
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server is running on port ${PORT}`);
  });
}

module.exports = app;
