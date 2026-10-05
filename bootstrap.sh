#!/bin/sh
# Install the agentic harness into a repository (stack-neutral; the stack is decided in the design phase):
#   ./bootstrap.sh <target> [--name NAME] [--git-init] [--dry-run]
exec python3 "$(dirname "$0")/tools/installer.py" install "$@"
