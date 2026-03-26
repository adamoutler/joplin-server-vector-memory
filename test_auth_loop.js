const express = require('express');
const fs = require('fs');

// Create mock Joplin Server
const joplinApp = express();
joplinApp.use(express.json());
joplinApp.post('/api/sessions', (req, res) => {
    if (req.body.email === 'admin' && req.body.password === 'pass') {
        res.json({ id: "123", user_id: "456" });
    } else {
        res.status(403).json({ error: "Invalid username or password" });
    }
});
const joplinServer = joplinApp.listen(22300, () => console.log('Mock Joplin on 22300'));

// Create mock config.json
if (!fs.existsSync('data')) fs.mkdirSync('data');
fs.writeFileSync('data/config.json', JSON.stringify({
    joplinServerUrl: 'http://localhost:22300',
    joplinUsername: 'admin'
}));

// Run the proxy client
process.env.DATA_DIR = 'data';
const proxyApp = require('./client/src/index.js');
// The app is exported, but listen is already called if require.main === module.
// So we just spin it up using HTTP server.
const http = require('http');
const server = http.createServer(proxyApp);
server.listen(3000, async () => {
    console.log('Proxy on 3000');
    
    // Simulate curl with correct password
    const b64 = Buffer.from('admin:pass').toString('base64');
    console.log("Making request to proxy with correct credentials...");
    let res = await fetch('http://localhost:3000/status', {
        headers: { 'Authorization': `Basic ${b64}` }
    });
    console.log(`Attempt 1 Status: ${res.status}`);
    
    // Simulate a restart of the server but wait... the script is running. 
    // We can't restart easily, but we can clear globalCredentials since it's global.
    // However, the proxyApp doesn't export globalCredentials.
    // Let's just make the request.
    
    process.exit(0);
});
