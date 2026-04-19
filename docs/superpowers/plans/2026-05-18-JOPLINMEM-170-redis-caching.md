# JOPLINMEM-170 Redis Credential Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Redis as an optional docker-compose service for credential caching, and integrate an E2E test that verifies the container works with Redis for sync, reboots the container, and verifies credentials are automatically retrieved without login.

**Architecture:** 
- **Docker Compose:** A `redis` service will be added to `docker-compose.yml`, `docker-compose.test.yml`, and `docker-compose.auth.yml` using the `profiles: ["redis"]` configuration so it remains optional. The `app` service will accept a `REDIS_URL` environment variable.
- **Node.js Client:** We will add `ioredis` to the Node.js client. In `client/src/index.js`, if `REDIS_URL` is set, we will connect to Redis and use it to store and retrieve `joplinPassword` and `joplinMasterPassword`.
- **E2E Testing:** A new python test `test_redis_caching.py` will explicitly spin up the `redis` profile, wait for health, configure auth, restart the `app` container, and verify the node service auto-authenticates without needing the `config.json` containing passwords on disk.

**Tech Stack:** Docker Compose, Node.js (ioredis), Python (pytest).

---

### Task 1: Update Node Dependencies

**Files:**
- Modify: `client/package.json`

- [ ] **Step 1: Install ioredis**

Run: `cd client && npm install ioredis`

- [ ] **Step 2: Commit**

```bash
git add client/package.json client/package-lock.json
git commit -m "chore: add ioredis for optional credential caching"
```

### Task 2: Modify Docker Compose Files

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.auth.yml`
- Modify: `docker-compose.test.yml`

- [ ] **Step 1: Add Redis to `docker-compose.yml`**

Add the `redis` service and update `app` environment in `docker-compose.yml`:
```yaml
services:
  app:
    environment:
      # ... existing environment ...
      - REDIS_URL=${REDIS_URL:-}
  
  redis:
    image: redis:7-alpine
    profiles: ["redis"]
    restart: unless-stopped
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis_data:
# Add redis_data to existing volumes if not present
```

- [ ] **Step 2: Update `docker-compose.auth.yml` and `docker-compose.test.yml` similarly**

Replicate the exact same block for `redis` and `REDIS_URL` in the other compose files. For `docker-compose.test.yml`, you might want `REDIS_URL=redis://redis:6379` if it's enabled.

- [ ] **Step 3: Commit**

```bash
git add docker-compose*.yml
git commit -m "feat: add optional redis profile to docker compose files"
```

### Task 3: Implement Redis Credential Caching Logic

**Files:**
- Modify: `client/src/index.js`

- [ ] **Step 1: Initialize Redis Connection in `client/src/index.js`**

Near the top of `client/src/index.js`:
```javascript
const Redis = require('ioredis');

let redisClient = null;
if (process.env.REDIS_URL) {
  try {
    redisClient = new Redis(process.env.REDIS_URL);
    redisClient.on('error', (err) => console.error('Redis client error:', err));
    console.log(`Connected to Redis at ${process.env.REDIS_URL} for optional credential caching`);
  } catch (err) {
    console.error('Failed to initialize Redis:', err);
  }
}
```

- [ ] **Step 2: Cache Credentials on Setup**

In the POST `/auth` handler, after passwords are confirmed, save them to Redis using the username as the key.
```javascript
        if (redisClient) {
          try {
            await redisClient.set(
              `joplin_creds_${reqUser}`,
              JSON.stringify({
                joplinPassword: reqPassword,
                joplinMasterPassword: req.body.masterPassword || null
              })
            );
            console.log('Credentials securely cached in Redis.');
          } catch (e) {
             console.error('Failed to cache credentials in Redis:', e);
          }
        }
```

- [ ] **Step 3: Auto-Retrieve Credentials on Startup**

In the auto-unlock logic block `if (proxyConfig && proxyConfig.joplinServerUrl && proxyConfig.joplinUsername) {`:
```javascript
      if (proxyConfig && proxyConfig.joplinServerUrl && proxyConfig.joplinUsername) {
        let restoredFromRedis = false;
        if (redisClient) {
          try {
             const cached = await redisClient.get(`joplin_creds_${proxyConfig.joplinUsername}`);
             if (cached) {
               const parsed = JSON.parse(cached);
               proxyConfig.joplinPassword = parsed.joplinPassword;
               proxyConfig.joplinMasterPassword = parsed.joplinMasterPassword;
               restoredFromRedis = true;
               console.log('Successfully restored credentials from Redis cache.');
             }
          } catch(e) {
             console.error('Failed retrieving credentials from Redis:', e);
          }
        }
        
        if (restoredFromRedis || proxyConfig.joplinPassword) {
           startSync(proxyConfig);
        } else {
           console.log('Cannot auto-unlock: No credentials provided and none found in Redis cache.');
        }
      }
```

- [ ] **Step 4: Commit**

```bash
git add client/src/index.js
git commit -m "feat: implement redis credential caching logic"
```

### Task 4: Add E2E Test for Redis Auto-Retrieval

**Files:**
- Create: `tests/test_redis_caching.py`

- [ ] **Step 1: Write the failing E2E test**

Create `tests/test_redis_caching.py`:
```python
import pytest
import requests
import subprocess
import time

@pytest.mark.enable_socket
def test_redis_credential_caching_on_restart(ephemeral_joplin):
    # Enable the redis profile and REDIS_URL for this specific test
    env = subprocess.os.environ.copy()
    env["REDIS_URL"] = "redis://redis:6379"

    # Start the test environment with redis profile
    subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "--profile", "redis", "-p", "joplin-test-env", "up", "-d"], env=env, check=True)
    time.sleep(5)  # give it time to fully initialize

    proxy_url = "http://127.0.0.1:3001"

    # Setup Auth
    setup_payload = {
        "serverUrl": "http://joplin:22300",
        "username": "admin@localhost",
        "password": "admin",
        "memoryServerAddress": "http://localhost:8000"
    }
    r = requests.post(f"{proxy_url}/auth", json=setup_payload, auth=("setup", "1-mcp-server"))
    assert r.status_code == 200, f"Setup failed: {r.text}"
    time.sleep(2)

    # Verify we can authenticate as the user
    r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"))
    assert r.status_code == 200

    # Take down the app container (simulating crash or restart)
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "stop", "app"], check=True)
    time.sleep(2)

    # Bring app container back up
    subprocess.run(["docker", "compose", "-p", "joplin-test-env", "start", "app"], check=True)

    # Wait for the node app to come back online
    for i in range(15):
        try:
            r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"), timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)

    # The user should STILL be authenticated automatically because credentials were saved in Redis
    r = requests.get(f"{proxy_url}/status", auth=("admin@localhost", "admin"))
    assert r.status_code == 200, "Failed auto-auth after restart with Redis"
    
    # Teardown the profile properly
    subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "--profile", "redis", "-p", "joplin-test-env", "down"], env=env)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_redis_caching.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_redis_caching.py
git commit -m "test: verify redis credential caching persists across app restarts"
```
