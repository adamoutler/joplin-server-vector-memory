#!/bin/bash
# =============================================================================
# complete_work.sh — The QA Gate for Ticket Closure
# =============================================================================
# This is the ONLY authorized way to transition a ticket to "Done".
# It enforces pre-flight checks and invokes an independent reality-checker
# agent to verify the work before allowing closure.
#
# Usage: ./scripts/complete_work.sh TICKET-123
#
# Requirements:
#   - KANBAN_API_KEY environment variable must be set
#   - gemini CLI must be installed and authenticated
#   - gh CLI must be installed and authenticated
#   - Must be run from the repository root
#
# Exit codes:
#   0 - Ticket approved and transitioned to Done
#   1 - Ticket rejected (pre-flight failure, reality-checker denial, or error)
# =============================================================================
set -euo pipefail

WORKSPACE="joplin-server-vector-memory"
API_BASE="https://kanban.hackedyour.info/api/v1/workspaces/${WORKSPACE}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"  # Optional: set env var to override model

# =============================================================================
# Argument Parsing
# =============================================================================
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 TICKET-ID (e.g., GEMWEBUI-123)"
    exit 1
fi

TICKET_ID="$1"
PREFIX="${TICKET_ID%%-*}"
NUMBER="${TICKET_ID##*-}"

if [[ -z "$PREFIX" || -z "$NUMBER" || "$PREFIX" == "$NUMBER" ]]; then
    echo "ERROR: Invalid ticket ID format. Expected PREFIX-NUMBER (e.g., GEMWEBUI-123)"
    exit 1
fi

# Validate NUMBER is numeric
if ! [[ "$NUMBER" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Invalid ticket number '$NUMBER'. Must be numeric."
    exit 1
fi

# =============================================================================
# Environment Checks
# =============================================================================
if [[ -z "${KANBAN_API_KEY:-}" ]]; then
    echo "ERROR: KANBAN_API_KEY is not set in the environment."
    exit 1
fi

if ! command -v gemini &>/dev/null; then
    echo "ERROR: gemini CLI is not installed or not in PATH."
    exit 1
fi

if ! command -v gh &>/dev/null; then
    echo "ERROR: gh CLI is not installed or not in PATH."
    exit 1
fi

# =============================================================================
# Resolve Ticket ID → Project UUID + Issue UUID
# =============================================================================
echo "=== Resolving ticket $TICKET_ID ==="

# Get project ID from identifier prefix
PROJECT_ID=$(curl -s --max-time 30 -X GET "${API_BASE}/projects/" \
    -H "x-api-key: $KANBAN_API_KEY" \
    -H "Content-Type: application/json" \
    | jq -r ".results[] | select(.identifier == \"$PREFIX\") | .id")

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "null" ]]; then
    echo "ERROR: Could not find project with identifier '$PREFIX'"
    exit 1
fi

echo "  Project: $PREFIX ($PROJECT_ID)"

# Get work item by sequence_id
WORK_ITEM_ID=$(curl -s --max-time 30 -X GET "${API_BASE}/projects/${PROJECT_ID}/issues/?search=${NUMBER}" \
    -H "x-api-key: $KANBAN_API_KEY" \
    -H "Content-Type: application/json" \
    | jq -r ".results[] | select(.sequence_id == ${NUMBER}) | .id")

if [[ -z "$WORK_ITEM_ID" || "$WORK_ITEM_ID" == "null" ]]; then
    echo "ERROR: Could not find issue ${TICKET_ID} in project ${PREFIX}"
    exit 1
fi

echo "  Issue: $TICKET_ID ($WORK_ITEM_ID)"

# Get Done state ID
DONE_STATE_ID=$(curl -s --max-time 30 -X GET "${API_BASE}/projects/${PROJECT_ID}/states/" \
    -H "x-api-key: $KANBAN_API_KEY" \
    -H "Content-Type: application/json" \
    | jq -r '.results[] | select(.name == "Done") | .id')

if [[ -z "$DONE_STATE_ID" || "$DONE_STATE_ID" == "null" ]]; then
    echo "ERROR: Could not find 'Done' state in project ${PREFIX}"
    exit 1
fi

# =============================================================================
# Pre-flight Checks
# =============================================================================
echo ""
echo "=== Pre-flight Checks ==="

# 1. Clean repository
echo -n "  [1/3] Git clean: "
PORCELAIN=$(git status --porcelain)
if [[ -n "$PORCELAIN" ]]; then
    echo "FAIL"
    echo ""
    echo "ERROR: Repository has uncommitted changes:"
    echo "$PORCELAIN"
    echo ""
    echo "Please commit all project files and delete non-project files."
    exit 1
fi
echo "PASS"

# 2. Not ahead of origin
echo -n "  [2/3] Git pushed: "
if git status -sb | grep -q 'ahead'; then
    echo "FAIL"
    echo ""
    echo "ERROR: Repository has unpushed commits. Please push changes first."
    exit 1
fi
echo "PASS"

# 3. GitHub Actions pass for current HEAD
echo "  [3/3] GitHub Actions: "
CURRENT_COMMIT=$(git rev-parse HEAD)
RUNS_JSON=$(gh run list --commit "$CURRENT_COMMIT" --json databaseId,status,conclusion)
RUN_IDS=$(echo "$RUNS_JSON" | jq -r '.[].databaseId // empty')

if [[ -z "$RUN_IDS" ]]; then
    echo "FAIL"
    echo ""
    echo "ERROR: No GitHub Actions run found for commit $CURRENT_COMMIT."
    echo "Please push your changes and wait for checks to pass."
    exit 1
fi

GH_RUN_VIEW=""
for RUN_ID in $RUN_IDS; do
    echo -n "    Checking run $RUN_ID: "
    STATUS=$(echo "$RUNS_JSON" | jq -r ".[] | select(.databaseId==$RUN_ID) | .status // empty")
    CONCLUSION=$(echo "$RUNS_JSON" | jq -r ".[] | select(.databaseId==$RUN_ID) | .conclusion // empty")
    
    if [[ "$STATUS" == "in_progress" || "$STATUS" == "queued" || "$STATUS" == "waiting" || "$STATUS" == "pending" ]]; then
        echo "WAITING"
        if ! gh run watch "$RUN_ID" --exit-status >/dev/null; then
            echo ""
            echo "ERROR: GitHub Actions run $RUN_ID failed after waiting."
            exit 1
        fi
        echo "    Run $RUN_ID: PASS"
    elif [[ "$CONCLUSION" != "success" && "$CONCLUSION" != "skipped" && "$CONCLUSION" != "neutral" ]]; then
        echo "FAIL"
        echo ""
        echo "ERROR: GitHub Actions run $RUN_ID did not succeed (conclusion: $CONCLUSION)."
        echo "Please fix the build before attempting to close the ticket."
        exit 1
    else
        echo "PASS"
    fi
    GH_RUN_VIEW="${GH_RUN_VIEW}$(gh run view "$RUN_ID")\n\n"
done

# =============================================================================
# Fetch Ticket Data
# =============================================================================
echo ""
echo "=== Fetching ticket data ==="

TICKET_JSON=$(curl -s --max-time 30 -X GET "${API_BASE}/projects/${PROJECT_ID}/issues/${WORK_ITEM_ID}/" \
    -H "x-api-key: $KANBAN_API_KEY" \
    -H "Content-Type: application/json")

TICKET_NAME=$(echo "$TICKET_JSON" | jq -r '.name // "Unknown Ticket"')
echo "  Ticket: $TICKET_NAME"

TICKET_COMMENTS=$(curl -s --max-time 30 -X GET "${API_BASE}/projects/${PROJECT_ID}/issues/${WORK_ITEM_ID}/comments/" \
    -H "x-api-key: $KANBAN_API_KEY" \
    -H "Content-Type: application/json" \
    | jq -r '
      .results[] | "User Id: \(.created_by)\nLast Updated: \(.updated_at // .created_at)\n\(.comment_html)\nAttachments: \(.attachments | tojson)\n---"
    ')

# =============================================================================
# Build Evidence File for Reality Checker
# =============================================================================
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

echo "  Evidence file: $TICKET_FILE"

# =============================================================================
# Invoke Reality Checker (Independent Judge)
# =============================================================================
echo ""
echo "=== Invoking Reality Checker ==="
echo "  Model: ${GEMINI_MODEL:-default}"
echo "  Agent: @reality-checker"
echo "  (This may take 30-60 seconds...)"
echo ""

GEMINI_CMD=(gemini)
if [[ -n "$GEMINI_MODEL" ]]; then
    GEMINI_CMD+=(-m "$GEMINI_MODEL")
fi

GEMINI_STDERR="/tmp/gemini_stderr_${WORK_ITEM_ID}.log"
RESULT=$(cat "$TICKET_FILE" | "${GEMINI_CMD[@]}" -p \
    " @reality-checker Please verify if work item $TICKET_ID is completed. The developer has provided the required documentation and proof directly in the ticket comments. Read the comments thoroughly. Your response MUST end with exactly one of these two verdicts on its own line: READY (if evidence is satisfactory) or NEEDS WORK (if not). The final line of your response must be the verdict word alone." \
    2>"$GEMINI_STDERR")
GEMINI_EXIT_CODE=$?

# --- Gate: Gemini failure = automatic rejection ---
if [ $GEMINI_EXIT_CODE -ne 0 ]; then
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  REJECTED — Reality checker unavailable (exit: $GEMINI_EXIT_CODE)"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Gemini stderr:"
    cat "$GEMINI_STDERR"
    echo ""
    echo "This may be a 429 rate limit, service outage, or auth issue."
    echo "The ticket CANNOT be closed without a successful reality check."
    rm -f "$GEMINI_STDERR"
    exit 1
fi

# --- Gate: Empty response = automatic rejection ---
if [[ -z "$RESULT" ]]; then
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  REJECTED — Reality checker returned empty response         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Gemini stderr:"
    cat "$GEMINI_STDERR"
    echo ""
    echo "The ticket CANNOT be closed without a valid reality check response."
    rm -f "$GEMINI_STDERR"
    exit 1
fi

rm -f "$GEMINI_STDERR"

# =============================================================================
# Post QA Comment to Ticket (regardless of verdict)
# =============================================================================
echo "  Posting QA results to ticket..."
COMMENT_PAYLOAD=$(jq -n --arg html "$RESULT" '{"comment_html": $html}')
curl -s --max-time 30 -X POST "${API_BASE}/projects/${PROJECT_ID}/issues/${WORK_ITEM_ID}/comments/" \
    -H "x-api-key: $KANBAN_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$COMMENT_PAYLOAD" > /dev/null

# =============================================================================
# Evaluate Verdict
# =============================================================================
# Match the pattern from .gemini/hooks/qa-gate.sh
if grep -qiE "\*\*Status\*\*: READY|^READY$" <<< "$RESULT" || echo "$RESULT" | tail -n 5 | grep -qiE "READY|confirmed.*complet|is now complete|all criteria.*met|production.ready"; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ✅ APPROVED — Reality checker verdict: READY               ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  Transitioning $TICKET_ID to Done..."

    # Transition to Done state
    HTTP_CODE=$(curl -s --max-time 30 -o /dev/null -w "%{http_code}" -X PATCH \
        "${API_BASE}/projects/${PROJECT_ID}/issues/${WORK_ITEM_ID}/" \
        -H "x-api-key: $KANBAN_API_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"state\": \"$DONE_STATE_ID\"}")

    if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 300 ]]; then
        echo "  ✅ $TICKET_ID has been transitioned to Done."
        echo ""
        echo "  Cleanup: rm -f $TICKET_FILE"
        rm -f "$TICKET_FILE"
        exit 0
    else
        echo "  ERROR: API call to transition ticket failed (HTTP $HTTP_CODE)."
        echo "  The reality checker approved, but the state transition failed."
        echo "  You may need to manually transition the ticket."
        exit 1
    fi
else
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ❌ REJECTED — Reality checker verdict: NEEDS WORK          ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  Feedback has been posted to the ticket comments."
    echo "  Address the issues below, then run this script again."
    echo ""
    echo "--- Reality Checker Feedback ---"
    echo "$RESULT"
    echo "--- End Feedback ---"
    exit 1
fi
