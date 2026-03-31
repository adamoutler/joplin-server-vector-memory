#!/bin/bash
PROJECT="joplin-server-vector-memory"
BASE_URL="https://kanban.hackedyour.info"
PAYLOAD=$(cat -)

echo "--- NEW RUN $(date) ---" >> /tmp/qa-gate-debug.log
echo "PAYLOAD: $PAYLOAD" >> /tmp/qa-gate-debug.log

TOOL_NAME=$(echo "$PAYLOAD" | jq -r '.tool_name // empty')
TICKET_ID=$(echo "$PAYLOAD" | jq -r '.tool_input.ticket_id // empty')

echo "TOOL_NAME: $TOOL_NAME" >> /tmp/qa-gate-debug.log
echo "TICKET_ID: $TICKET_ID" >> /tmp/qa-gate-debug.log

if [ -z "$TICKET_ID" ]; then
    echo "EXITING: Empty TICKET_ID" >> /tmp/qa-gate-debug.log
    echo '{"decision": "allow"}'
    exit 0
fi

# Determine intended state
if [[ "$TOOL_NAME" == *_complete_work ]]; then
    INTENDED_STATE="Done"
elif [[ "$TOOL_NAME" == *_transition_ticket ]]; then
    INTENDED_STATE=$(echo "$PAYLOAD" | jq -r '.tool_input.state_name // empty')
else
    # Not a state change tool we care about
    echo "EXITING: Not a state change tool ($TOOL_NAME)" >> /tmp/qa-gate-debug.log
    echo '{"decision": "allow"}'
    exit 0
fi

echo "INTENDED_STATE: $INTENDED_STATE" >> /tmp/qa-gate-debug.log

# Only gate transitions to Done
if [[ "$INTENDED_STATE" != "Done" ]]; then
    echo "EXITING: INTENDED_STATE is not Done" >> /tmp/qa-gate-debug.log
    echo '{"decision": "allow"}'
    exit 0
fi

# Rate limit check: Ensure at least 30s between calls
CURRENT_TIME=$(date +%s)
if [ -f /tmp/qa_gate_last_run ]; then
    LAST_RUN=$(cat /tmp/qa_gate_last_run)
    DIFF=$((CURRENT_TIME - LAST_RUN))
    if [ "$DIFF" -lt 30 ]; then
        echo "EXITING: Rate limit exceeded" >> /tmp/qa-gate-debug.log
        jq -c -n --arg reason "Rate limit exceeded. Please wait 30 seconds between calls to mcp update ticket." '{"decision": "deny", "reason": $reason}'
        exit 0
    fi
fi
echo "$CURRENT_TIME" > /tmp/qa_gate_last_run

# Resolve IDs
PROJECT_IDENTIFIER=$(echo "$TICKET_ID" | cut -d'-' -f1)
ISSUE_SEQUENCE_ID=$(echo "$TICKET_ID" | cut -d'-' -f2)

PROJECT_JSON=$(curl -s -X GET "${BASE_URL}/api/v1/workspaces/${PROJECT}/projects/" -H "x-api-key: $KANBAN_API_KEY" -H "Content-Type: application/json")
PROJECT_ID=$(echo "$PROJECT_JSON" | jq -r --arg ident "$PROJECT_IDENTIFIER" '.results[] | select(.identifier == $ident) | .id')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "null" ]; then
   echo "EXITING: Could not resolve project ID" >> /tmp/qa-gate-debug.log
   jq -c -n --arg reason "Could not resolve project ID for $PROJECT_IDENTIFIER. The hook script needs updating or the API failed." '{"decision": "deny", "reason": $reason}'
   exit 0
fi

ISSUE_JSON=$(curl -s -X GET "${BASE_URL}/api/v1/workspaces/${PROJECT}/projects/${PROJECT_ID}/issues/?sequence_id=${ISSUE_SEQUENCE_ID}" -H "x-api-key: $KANBAN_API_KEY" -H "Content-Type: application/json")
WORK_ITEM_ID=$(echo "$ISSUE_JSON" | jq -r --arg seq "$ISSUE_SEQUENCE_ID" '.results[] | select(.sequence_id == ($seq|tonumber)) | .id')

if [ -z "$WORK_ITEM_ID" ] || [ "$WORK_ITEM_ID" == "null" ]; then
   echo "EXITING: Could not resolve work item ID" >> /tmp/qa-gate-debug.log
   jq -c -n --arg reason "Could not resolve work item ID for $TICKET_ID. The hook script needs updating or the API failed." '{"decision": "deny", "reason": $reason}'
   exit 0
fi

echo "PROJECT_ID: $PROJECT_ID, WORK_ITEM_ID: $WORK_ITEM_ID" >> /tmp/qa-gate-debug.log

# Pre-flight QA checks bypassed for testing
# if [[ -n $(git status --porcelain) ]]; then
#   jq -c -n --arg reason "please commit all project files and delete non-project files - if there are any uncommitted files." '{"decision": "deny", "reason": $reason}'
#   exit 0
# fi

# if git status -sb | grep -q 'ahead'; then
#   jq -c -n --arg reason "Git repository has unpushed commits. Please push changes before QA to ensure we match the main repo." '{"decision": "deny", "reason": $reason}'
#   exit 0
# fi

# Check GitHub Actions build status bypassed for testing
CURRENT_COMMIT=$(git rev-parse HEAD)
GH_RUN_VIEW="Bypassed GitHub Actions check for testing."

# Retrieve the ticket
TICKET_JSON=$(curl -s -X GET "${BASE_URL}/api/v1/workspaces/${PROJECT}/projects/$PROJECT_ID/issues/$WORK_ITEM_ID/" \
  -H "x-api-key: $KANBAN_API_KEY" \
  -H "Content-Type: application/json")

# Retrieve the ticket comments and format them to reduce context size
TICKET_COMMENTS=$(curl -s -X GET "${BASE_URL}/api/v1/workspaces/${PROJECT}/projects/$PROJECT_ID/issues/$WORK_ITEM_ID/comments/" \
  -H "x-api-key: $KANBAN_API_KEY" \
  -H "Content-Type: application/json" | jq -r '
    .results[] | "User Id: \(.created_by)\nLast Updated: \(.updated_at // .created_at)\n\(.comment_html)\nAttachments: \(.attachments | tojson)\n---"
  ')

TICKET_NAME=$(echo "$TICKET_JSON" | jq -r '.name // "Unknown Ticket"')
TICKET_FILE="/tmp/ticket_${WORK_ITEM_ID}.md"

cat <<EOF > "$TICKET_FILE"
---
name: $TICKET_NAME
description: The kanban ticket to be closed. This should be evaluated as the reference source for ticket completion and the criteria for evaluation.
---
$TICKET_JSON

---
name: Kanban Ticket Comments
description: The discussion and history on the ticket including any attachments.
---
${TICKET_COMMENTS}

---
name: GitHub Actions Build Receipt
description: The build results from GitHub Actions for commit $CURRENT_COMMIT
---
$GH_RUN_VIEW
EOF

echo "Running gemini..." >> /tmp/qa-gate-debug.log

RESULT=$(cat "$TICKET_FILE" | gemini -p " @reality-checker Please use the provided context and \`read_file(path)\` tool to determine if work item $WORK_ITEM_ID is completed. If it is not complete, please respond with what is required and NEEDS WORK. An automated system will flag this as incomplete if you state NEEDS WORK." 2>&1| tee -a /tmp/a-gate-debug.log)
# comment above and uncomment below for test mode
# RESULT=$(echo "FOO BAR NEEDS WORK")
GEMINI_EXIT_CODE=$?

echo "GEMINI EXIT CODE: $GEMINI_EXIT_CODE" >> /tmp/qa-gate-debug.log

if [ $GEMINI_EXIT_CODE -ne 0 ]; then
  echo "EXITING: Gemini failed" >> /tmp/qa-gate-debug.log
  jq -c -n --arg reason "No quality control available. Gemini command exited with $GEMINI_EXIT_CODE. Output: $RESULT" '{"decision": "deny", "reason": $reason}'
  exit 0
fi

RESULT=$(echo "$RESULT" | sed -e 's/.*LocalAgentExecutor"//g')

echo "RESULT: $RESULT" >> /tmp/qa-gate-debug.log

COMMENT_PAYLOAD=$(jq -n --arg html "$RESULT" '{"comment_html": $html}')
curl -s -X POST "${BASE_URL}/api/v1/workspaces/${PROJECT}/projects/$PROJECT_ID/issues/$WORK_ITEM_ID/comments/" \
  -H "x-api-key: $KANBAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$COMMENT_PAYLOAD" > /dev/null

if echo "$RESULT" | grep -qE "NEEDS WORK|NEEDS_WORK"; then
  echo "EXITING: Denying transition" >> /tmp/qa-gate-debug.log
  jq -c -n --arg reason "Reality checker blocked the transition to Done. Output: $RESULT" '{"decision": "deny", "reason": $reason}'
  exit 0
else
  echo "EXITING: Allowing transition" >> /tmp/qa-gate-debug.log
  echo '{"decision": "allow"}'
  exit 0
fi
