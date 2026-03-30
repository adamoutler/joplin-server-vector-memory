#!/bin/bash
PROJECT=joplin-server-vector-memory
PAYLOAD=$(cat -)

TOOL_NAME=$(echo "$PAYLOAD" | jq -r '.tool_name // empty')
TICKET_ID=$(echo "$PAYLOAD" | jq -r '.tool_input.ticket_id // empty')

if [ -z "$TICKET_ID" ]; then
    echo '{"decision": "allow"}'
    exit 0
fi

# Determine intended state
if [[ "$TOOL_NAME" == "mcp_kanban_complete_work" ]]; then
    INTENDED_STATE="Done"
elif [[ "$TOOL_NAME" == "mcp_kanban_transition_ticket" ]]; then
    INTENDED_STATE=$(echo "$PAYLOAD" | jq -r '.tool_input.state_name // empty')
else
    # Not a state change tool we care about
    echo '{"decision": "allow"}'
    exit 0
fi

# Only gate transitions to Done
if [[ "$INTENDED_STATE" != "Done" ]]; then
    echo '{"decision": "allow"}'
    exit 0
fi

# Rate limit check: Ensure at least 30s between calls
CURRENT_TIME=$(date +%s)
if [ -f /tmp/qa_gate_last_run ]; then
    LAST_RUN=$(cat /tmp/qa_gate_last_run)
    DIFF=$((CURRENT_TIME - LAST_RUN))
    if [ "$DIFF" -lt 30 ]; then
        jq -c -n --arg reason "Rate limit exceeded. Please wait 30 seconds between calls to mcp update ticket." '{"decision": "deny", "reason": $reason}'
        exit 0
    fi
fi
echo "$CURRENT_TIME" > /tmp/qa_gate_last_run

# Resolve IDs
PROJECT_IDENTIFIER=$(echo "$TICKET_ID" | cut -d'-' -f1)
ISSUE_SEQUENCE_ID=$(echo "$TICKET_ID" | cut -d'-' -f2)

PROJECT_JSON=$(curl -s -X GET "https://kanban.hackedyour.info/api/v1/workspaces/${PROJECT}/projects/" -H "x-api-key: $KANBAN_API_KEY" -H "Content-Type: application/json")
PROJECT_ID=$(echo "$PROJECT_JSON" | jq -r --arg ident "$PROJECT_IDENTIFIER" '.results[] | select(.identifier == $ident) | .id')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "null" ]; then
   jq -c -n --arg reason "Could not resolve project ID for $PROJECT_IDENTIFIER. The hook script needs updating or the API failed." '{"decision": "deny", "reason": $reason}'
   exit 0
fi

ISSUE_JSON=$(curl -s -X GET "https://kanban.hackedyour.info/api/v1/workspaces/${PROJECT}/projects/${PROJECT_ID}/issues/?sequence_id=${ISSUE_SEQUENCE_ID}" -H "x-api-key: $KANBAN_API_KEY" -H "Content-Type: application/json")
WORK_ITEM_ID=$(echo "$ISSUE_JSON" | jq -r --arg seq "$ISSUE_SEQUENCE_ID" '.results[] | select(.sequence_id == ($seq|tonumber)) | .id')

if [ -z "$WORK_ITEM_ID" ] || [ "$WORK_ITEM_ID" == "null" ]; then
   jq -c -n --arg reason "Could not resolve work item ID for $TICKET_ID. The hook script needs updating or the API failed." '{"decision": "deny", "reason": $reason}'
   exit 0
fi

# Pre-flight QA checks
if [[ -n $(git status --porcelain) ]]; then
  jq -c -n --arg reason "please commit all project files and delete non-project files - if there are any uncommitted files." '{"decision": "deny", "reason": $reason}'
  exit 0
fi

if git status -sb | grep -q 'ahead'; then
  jq -c -n --arg reason "Git repository has unpushed commits. Please push changes before QA to ensure we match the main repo." '{"decision": "deny", "reason": $reason}'
  exit 0
fi

# Check GitHub Actions build status before invoking AI
CURRENT_COMMIT=$(git rev-parse HEAD)
RUN_JSON=$(gh run list --commit "$CURRENT_COMMIT" --json databaseId,conclusion -q '.[0]')
RUN_ID=$(echo "$RUN_JSON" | jq -r '.databaseId // empty')
CONCLUSION=$(echo "$RUN_JSON" | jq -r '.conclusion // empty')

if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
  jq -c -n --arg reason "No GitHub Actions run found for the current commit $CURRENT_COMMIT. Please push your changes and wait for checks to pass." '{"decision": "deny", "reason": $reason}'
  exit 0
fi

if [[ "$CONCLUSION" != "success" ]]; then
  jq -c -n --arg reason "GitHub Actions run $RUN_ID did not succeed (status: $CONCLUSION). Please fix the build before transitioning to Done." '{"decision": "deny", "reason": $reason}'
  exit 0
fi

GH_RUN_VIEW=$(gh run view "$RUN_ID")

# Retrieve the ticket
TICKET_JSON=$(curl -s -X GET "https://kanban.hackedyour.info/api/v1/workspaces/${PROJECT}/projects/$PROJECT_ID/issues/$WORK_ITEM_ID/" \
  -H "x-api-key: $KANBAN_API_KEY" \
  -H "Content-Type: application/json")

# Retrieve the ticket comments and format them to reduce context size
TICKET_COMMENTS=$(curl -s -X GET "https://kanban.hackedyour.info/api/v1/workspaces/${PROJECT}/projects/$PROJECT_ID/issues/$WORK_ITEM_ID/comments/" \
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

RESULT=$(cat "$TICKET_FILE" | gemini -p " @reality-checker Please use the provided context and \`read_file(path)\` tool to determine if work item $WORK_ITEM_ID is completed. If it is not complete, please respond with what is required and NEEDS WORK. An automated system will flag this as incomplete if you state NEEDS WORK." 2>&1)
GEMINI_EXIT_CODE=$?

if [ $GEMINI_EXIT_CODE -ne 0 ]; then
  jq -c -n --arg reason "No quality control available. Gemini command exited with $GEMINI_EXIT_CODE. Output: $RESULT" '{"decision": "deny", "reason": $reason}'
  exit 0
fi

# Strip Gemini CLI boilerplate
CLEAN_RESULT=$(echo "$RESULT" | awk '
  /# Integration Agent|The `reality-checker`/ {found=1}
  found {print}
')

if [[ -z "$CLEAN_RESULT" ]]; then
  CLEAN_RESULT="$RESULT"
fi

COMMENT_PAYLOAD=$(jq -n --arg html "$CLEAN_RESULT" '{"comment_html": $html}')
curl -s -X POST "https://kanban.hackedyour.info/api/v1/workspaces/${PROJECT}/projects/$PROJECT_ID/issues/$WORK_ITEM_ID/comments/" \
  -H "x-api-key: $KANBAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$COMMENT_PAYLOAD" > /dev/null

if echo "$RESULT" | grep -qE "NEEDS WORK"; then
  jq -c -n --arg reason "Reality checker blocked the transition to Done. Please review the ticket comments for details." '{"decision": "deny", "reason": $reason}'
  exit 0
else
  echo '{"decision": "allow"}'
  exit 0
fi
