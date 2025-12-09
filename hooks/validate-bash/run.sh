#!/bin/bash
# General bash command validation to prevent dangerous execution patterns
# and restrict file access to the project directory

set -euo pipefail

# Read hook input from stdin
input=$(cat)

# DEBUG: Log input to file
echo "=== Hook called at $(date) ===" >> /tmp/claude-hook-debug.log
echo "$input" >> /tmp/claude-hook-debug.log
echo "" >> /tmp/claude-hook-debug.log

# Extract tool name and command
tool_name=$(echo "$input" | jq -r '.tool_name // ""')
command=$(echo "$input" | jq -r '.tool_input.command // ""')

# Only validate Bash commands
if [[ "$tool_name" != "Bash" ]]; then
  exit 0
fi

# Function to send permission response
send_permission_response() {
  local decision="$1"
  local reason="$2"

  # DEBUG: Log decision
  echo "DECISION: $decision - $reason" >> /tmp/claude-hook-debug.log
  echo "COMMAND WAS: $command" >> /tmp/claude-hook-debug.log
  echo "" >> /tmp/claude-hook-debug.log

  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "$decision",
    "permissionDecisionReason": "$reason"
  }
}
EOF
  exit 0
}

# Function to pass on making a permissioning decision, deferring to other rules
defer_permission_decision() {
  echo "DECISION: defer" >> /tmp/claude-hook-debug.log
  echo "COMMAND WAS: $command" >> /tmp/claude-hook-debug.log
  echo "" >> /tmp/claude-hook-debug.log

  exit 0
}

# Function to grant permission
allow_command() {
  send_permission_response "allow" "$1"
}

# Function to require user permission
require_user_permission() {
  send_permission_response "ask" "$1"
}

# Function to deny command
deny_command() {
  send_permission_response "deny" "$1"
}

# 1. Block any command containing dangerous shell metacharacters
# These enable command chaining, substitution, redirection, and other unsafe operations
if [[ "$command" =~ [\&\$\|\>\<\;\`] ]]; then
  require_user_permission "contains dangerous shell metacharacters (&, \$, |, >, <, ;, or \`)"
fi

# 2. Block absolute paths (anything starting with /)
# This prevents access to system directories and files outside the project
if [[ "$command" =~ (^|[[:space:]])/ ]]; then
  require_user_permission "contains absolute path (starts with /). Use relative paths only."
fi

# 3. Block parent directory access (..)
# This prevents escaping the project directory
if [[ "$command" =~ \.\. ]]; then
  require_user_permission "contains parent directory reference (..). Stay within project directory."
fi

# 4. Block tilde expansion (~ for home directory)
# This could allow access outside the project scope
if [[ "$command" =~ \~ ]]; then
  require_user_permission "contains tilde (~) for home directory expansion. Use relative paths only."
fi

# 5. Block commands with newlines (multiline execution)
# Check for both literal newlines and JSON-escaped newlines (\n)
if [[ "$command" =~ $'\n' ]] || [[ "$command" =~ \\n ]]; then
  require_user_permission "contains newline characters (multiline command)"
fi

# 6. Block null bytes and suspicious control characters
if [[ "$command" =~ $'\x00' ]] || [[ "$command" =~ $'\x1b' ]]; then
  require_user_permission "contains suspicious control characters"
fi

# If all checks pass, allow the command
defer_permission_decision
