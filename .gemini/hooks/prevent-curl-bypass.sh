#!/bin/bash
PAYLOAD=$(cat -)
COMMAND=$(echo "$PAYLOAD" | jq -r '.tool_input.command // empty')

if [[ "$COMMAND" == *"curl "* || "$COMMAND" == *"gh "* || "$COMMAND" == *"plane "* ]]; then
  if [[ "$COMMAND" == *"status"* || "$COMMAND" == *"state"* ]] && [[ "$COMMAND" == *"Done"* ]]; then
    echo '{"decision": "deny", "reason": "Bypass detected. You are strictly forbidden from closing Kanban tickets via CLI tools. Please follow the verification pipeline."}'
    exit 0
  fi
fi

echo '{"decision": "allow"}'
