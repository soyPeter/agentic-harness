#!/bin/sh
# Put a project under the agentic harness for every agent and, optionally, in Orca:
#   ./enroll.sh <target> [--name NAME] [--orca] [--automation SCHEDULE] [--agents "default=claude judge=codex"]
#               [--protect] [--dry-run]
exec python3 "$(dirname "$0")/tools/enroll.py" "$@"
