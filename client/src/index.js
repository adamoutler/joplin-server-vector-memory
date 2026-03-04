const express = require('express');
const cors = require('cors');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { JoplinSyncClient } = require('./sync');

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '../../data');
const CONFIG_PATH = path.join(DATA_DIR, 'config.json');

// Ensure data dir exists
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

let syncStatus = 'ready'; // ready, syncing, error
let syncClient = null;

app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Joplin Server Token Access & Dashboard</title>
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
        <h1>Joplin Server Dashboard</h1>
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
          <button type="submit">Save & Validate</button>
          <div id="auth-msg" class="messages"></div>
        </form>

        <h2 style="margin-top: 2rem;">Local Access Token</h2>
        <p>Copy this token into your <code>.gemini/settings.json</code> file.</p>
        <div class="token-group">
          <input type="text" id="token" readonly>
          <button id="rotate-btn">Rotate Token</button>
        </div>
        <div id="token-msg" class="messages"></div>
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
               document.getElementById('serverUrl').value = data.config.joplinServerUrl || '';
               document.getElementById('username').value = data.config.joplinUsername || '';
               // don't populate password
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
          const msgEl = document.getElementById('auth-msg');
          msgEl.innerText = 'Validating...';
          msgEl.className = 'messages';
          
          try {
            const res = await fetch('/auth', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ serverUrl, username, password, masterPassword })
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
  const { serverUrl, username, password, masterPassword, rotate } = req.body;
  
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
