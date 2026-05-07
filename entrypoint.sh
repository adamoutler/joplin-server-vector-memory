#!/bin/bash
set -e

# ============================================================
# Ownership Repair: Fix volume-mounted data directory
# Docker volumes are often created as root. Our app runs as
# 'node' (UID 1000). Without this, SQLITE_READONLY errors
# will occur on any write to the Joplin profile database.
# ============================================================
if [ "$(id -u)" = "0" ]; then
    echo "Running as root. Fixing /app/data ownership for 'node' user..."
    chown -R node:node /app/data 2>/dev/null || true
    
    # Re-exec this script as the 'node' user via gosu
    exec gosu node "$0" "$@"
fi

# ============================================================
# From this point, we are running as 'node' (UID 1000)
# ============================================================

# Start the Python MCP Server in the background
echo "Starting Python Backend (FastMCP)..."
cd /app/server
uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*" &
BACKEND_PID=$!

# Start the Node.js Client Proxy/UI in the foreground
echo "Starting Node.js Proxy and Sync Client..."
cd /app/client
node src/index.js &
CLIENT_PID=$!

# Wait for both processes
wait -n $BACKEND_PID $CLIENT_PID

# Maintenance Shutdown Procedure: 
# This lock-and-confirm handshake prevents catastrophic race conditions where Python resets the DB 
# and overwrites config.json while Node is simultaneously shutting down or restarting. 
# Without this, config.json gets corrupted, permanently locking users out of the UI.
# Do not remove this logic.
LOCK_FILE="/tmp/maintenance.lock"
CONFIRM_FILE="/tmp/maintenance.confirm"

if [[ -f "$LOCK_FILE" ]]; then
    echo "Maintenance lock detected. Writing confirm file and waiting for Python to finish..."
    touch "$CONFIRM_FILE"
    
    # Wait for Python to delete the lock file (with timeout)
    WAIT_TIME=0
    while [[ -f "$LOCK_FILE" ]] && [[ $WAIT_TIME -lt 40 ]]; do
        sleep 0.5
        WAIT_TIME=$((WAIT_TIME+1))
    done
    
    if [[ -f "$LOCK_FILE" ]]; then
        echo "Maintenance timed out! Forcing restart..."
        rm -f "$LOCK_FILE"
        rm -f "$CONFIRM_FILE"
    fi
    
    echo "Maintenance complete. Restarting container..."
    exit 1
fi

# If either exits, exit the container
echo "A primary process exited. Shutting down container..."
exit 1