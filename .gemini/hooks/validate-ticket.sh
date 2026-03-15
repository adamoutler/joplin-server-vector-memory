#!/bin/bash
input=$(cat)
state=$(echo "$input" | jq -r '.tool_input.state')

# Replace the state IDs below with your Plane instance's UUIDs for 'Done' state
if [[ "$state" == "ae56a905-81b7-4f9a-a2e5-7a842d66b8f4" ]] || [[ "$state" == "05ce5001-f07a-4126-838c-b9ebea9725ab" ]]; then
    jq -n '{
        error: "GUARDRAIL TRIGGERED: You are strictly forbidden from manually transitioning tickets to Done using update_work_item. Tickets must be closed by the QA gate via a valid `git commit`."
    }'
    exit 0
fi

echo '{"decision": "allow"}'
