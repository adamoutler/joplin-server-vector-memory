#!/bin/bash
# Read input from Gemini CLI
INPUT=$(cat)

tool_name=$(echo "$INPUT" | jq -r '.tool_name')

if [[ "$tool_name" =~ run_shell_command|Bash|shell ]]; then
    command=$(echo "$INPUT" | jq -r '.tool_input.command')

    if [[ "$command" =~ git[[:space:]]+push ]]; then
        echo "Detected git push. Waiting 20 seconds for GitHub Actions to register the build..." >&2
        sleep 20

        CURRENT_COMMIT=$(git rev-parse HEAD)
        RUN_ID=$(gh run list --commit "$CURRENT_COMMIT" --json databaseId -q '.[0].databaseId')

        if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ]; then
            echo "Found workflow run $RUN_ID. Watching for completion..." >&2

            # Watch the run and stream output to stderr so the user sees it without breaking JSON hook protocol

            gh run watch "$RUN_ID" >&2

            STATUS=$(gh run view "$RUN_ID" --json conclusion -q '.conclusion')

            if [ "$STATUS" != "success" ]; then
                MSG="Run $RUN_ID status: $STATUS. You must continue troubleshooting and fixing the code until the build succeeds."
            else
                MSG="Run $RUN_ID finished with status: $STATUS."
            fi

            jq -n -c --arg result "$MSG" \
              '{"decision": "allow", "hookSpecificOutput": {"additionalContext": $result}}'
            exit 0
        else
            jq -n -c '{decision: "allow", "hookSpecificOutput": {"additionalContext": "Could not find a GitHub Actions run for the pushed commit."}}'
            exit 0
        fi
    fi
fi

# Proceed normally
echo '{"decision": "allow"}'
