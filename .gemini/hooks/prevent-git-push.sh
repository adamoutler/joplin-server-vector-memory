#!/usr/bin/env bash

# This script is meant to be run as a git pre-push hook.
# It prevents standard 'git push' for specific users to enforce the use of 'git p'.

# If we are running via git-p.sh (which exports GIT_P_RUNNING=1), allow the push.
if [ "$GIT_P_RUNNING" = "1" ]; then
  exit 0
fi

# Determine the git user email and name.
USER_EMAIL=$(git config user.email)
USER_NAME=$(git config user.name)

# Only block pushes if the user config matches Adam Outler / AI.
# Ensure open-source contributors are allowed to use standard git push without encountering the block.
if [[ "$USER_EMAIL" == *"adamoutler"* || "$USER_NAME" == *"Adam Outler"* || "$USER_NAME" == *"AI"* ]]; then
  echo "====================================================================="
  echo "                           PUSH BLOCKED                              "
  echo "====================================================================="
  echo "Standard 'git push' is blocked for your user profile:"
  echo "  Name:  $USER_NAME"
  echo "  Email: $USER_EMAIL"
  echo ""
  echo "Please use 'git p' instead (which pushes and monitors CI status)."
  echo "To bypass manually, export GIT_P_RUNNING=1 before pushing."
  echo "====================================================================="
  exit 1
fi

# Allow push for all other users
exit 0