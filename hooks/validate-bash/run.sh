#!/bin/bash
# Wrapper script for Python-based bash command validation hook

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Execute the Python script with stdin passed through
exec python3 "$SCRIPT_DIR/run.py"
