#!/bin/sh
# Machine-level enforcement of the agentic harness for every project on this machine:
#   ./machine.sh install [--roots DIR ...] [--mode warn|block] | status | remove | managed --out DIR
exec python3 "$(dirname "$0")/tools/machine.py" "$@"
