#!/bin/sh
# Update the agentic harness in a repository: ./update.sh <target> [--dry-run] [--force]
#   ./update.sh status <target>   what is outdated or edited locally
#   ./update.sh catalog           list the stack packs projects can adopt after a stack ADR
case "$1" in
  status|catalog)
    cmd="$1"; shift
    exec python3 "$(dirname "$0")/tools/installer.py" "$cmd" "$@" ;;
esac
exec python3 "$(dirname "$0")/tools/installer.py" update "$@"
