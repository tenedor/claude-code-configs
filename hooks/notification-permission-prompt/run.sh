#!/bin/bash

# Play a system sound when Claude Code shows a permission prompt
# The & runs it in the background so the hook doesn't block
afplay /System/Library/Sounds/Glass.aiff &

echo "" >> /tmp/claude-notification-hook-debug.log
echo "notification permission prompt triggered at $(date)" >> /tmp/claude-notification-hook-debug.log
