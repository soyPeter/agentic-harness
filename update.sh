#!/bin/sh
# Update the agentic harness in a repository: ./update.sh <target> [--dry-run] [--force]
#   ./update.sh status <target>   what is outdated or edited locally
#   ./update.sh catalog           list the stack packs projects can adopt after a stack ADR
#   ./update.sh --to-thin <target> [--version V]   switch a full install to thin mode (README, "Thin mode")
#   ./update.sh --to-full <target>                 switch a thin-mode project back to a full install
case "$1" in
  status|catalog)
    cmd="$1"; shift
    exec python3 "$(dirname "$0")/tools/installer.py" "$cmd" "$@" ;;
esac
for arg; do
  case "$arg" in
    --to-thin|--to-full) exec python3 "$(dirname "$0")/tools/convert.py" "$@" ;;
  esac
done
exec python3 "$(dirname "$0")/tools/installer.py" update "$@"
