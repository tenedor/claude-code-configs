# Permission Prompt Notification Hook

This hook plays an audible sound whenever Claude Code displays a permission prompt, ensuring you don't miss requests that need your approval.

The script uses macOS's `afplay` command to play the Glass system sound in the background. This works reliably from background processes, unlike `tput bel` which requires an active terminal. The hook also logs each notification to `/tmp/claude-notification-hook-debug.log` for debugging.

To customize the sound, edit `run.sh` and replace `Glass.aiff` with any sound from `/System/Library/Sounds/` (Ping, Purr, Sosumi, etc.) or provide a path to your own audio file.
