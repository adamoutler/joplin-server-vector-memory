#!/bin/bash

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "[git-p] Error: gh CLI is not installed. Please install it."
    exit 1
fi

# Check if gh is authenticated
if ! gh auth status &> /dev/null; then
    echo "[git-p] Error: gh CLI is not authenticated. Please run 'gh auth login'."
    exit 1
fi

echo "[git-p] Pushing..."
export GIT_P_RUNNING=1
if ! git push --follow-tags "$@"; then
    echo "[git-p] Error: git push failed."
    exit 1
fi

echo "[git-p] Waiting for GitHub Actions CI run to be triggered..."
COMMIT_SHA=$(git rev-parse HEAD)

for i in {1..15}; do
    RUN_ID=$(gh run list --commit "$COMMIT_SHA" --json databaseId -q ".[0].databaseId" 2>/dev/null)
    if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ]; then
        break
    fi
    sleep 3
done

if [ -z "$RUN_ID" ] || [ "$RUN_ID" == "null" ]; then
    echo "[git-p] No CI run found for commit $COMMIT_SHA after waiting."
    exit 0
fi

echo "[git-p] Tracking Run #$RUN_ID..."

# Wait with a timeout (e.g. 10 minutes)
TIMEOUT=600
INTERVAL=10
ELAPSED=0

while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(gh run view "$RUN_ID" --json status,conclusion -q "{status: .status, conclusion: .conclusion}" 2>/dev/null)
    RUN_STATUS=$(echo "$STATUS" | jq -r .status 2>/dev/null)
    RUN_CONCLUSION=$(echo "$STATUS" | jq -r .conclusion 2>/dev/null)

    if [ "$RUN_STATUS" == "completed" ]; then
        if [ "$RUN_CONCLUSION" == "success" ]; then
            echo "[git-p] CI Run #$RUN_ID completed successfully!"
            exit 0
        else
            echo "[git-p] CI Run #$RUN_ID failed (conclusion: $RUN_CONCLUSION). Extracting logs..."
            gh run view "$RUN_ID" --log-failed | tail -n 200
            exit 1
        fi
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo "[git-p] Timeout reached ($TIMEOUT seconds) waiting for CI run #$RUN_ID to complete. Check back later."
exit 1
