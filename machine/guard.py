#!/usr/bin/env python3
"""Agentic harness: machine guard (installed by machine.sh into ~/.agentic-harness/guard.py).

A user-level (or managed) PreToolUse hook for Claude Code and Codex. It runs in every project and does one thing:
in a git repository under one of your work folders that has no agentic harness, it warns (mode "warn") or refuses
file edits (mode "block") until the repository is enrolled (enroll.sh <path>). In an enrolled repository it does
nothing, because the repository's own hooks enforce the gates.

Config: ~/.agentic-harness/machine.json (or HARNESS_MACHINE_CONFIG): {"roots": [...], "mode": "warn"|"block",
"exempt": [...]}. A guard error never blocks: the repository's own hooks are the enforcement; this only enrolls.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "apply_patch")
HARNESS_FILE = "scripts/harness/lib/harness.py"


def config():
    path = Path(os.environ.get("HARNESS_MACHINE_CONFIG") or os.path.expanduser("~/.agentic-harness/machine.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def repo_root(start):
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 and out.stdout.strip() else None


def inside(path, folders):
    for folder in folders:
        base = Path(os.path.expanduser(folder)).resolve()
        if path == base or base in path.parents:
            return True
    return False


def warned_once(root, session):
    """True if this session was already reminded about root (one reminder per session and repository)."""
    marker = Path(os.path.expanduser("~/.agentic-harness/warned")) / ("%s-%s" % (session or "session",
                                                                             str(root).strip("/").replace("/", "_")))
    if marker.exists():
        return True
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    except OSError:
        pass
    return False


def main(argv):
    source = argv[argv.index("--from") + 1] if "--from" in argv and argv.index("--from") + 1 < len(argv) else "claude"
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    settings = config()
    quiet = "{}\n" if source == "codex" else ""
    if not settings or not isinstance(data, dict):
        sys.stdout.write(quiet)
        return 0
    start = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    root = repo_root(start)
    if (root is None or not inside(root, settings.get("roots") or []) or inside(root, settings.get("exempt") or [])
            or (root / HARNESS_FILE).is_file()):
        sys.stdout.write(quiet)
        return 0
    message = ("%s is not enrolled in the agentic harness, so no spec, review or judge gates apply here. Enroll it "
               "first: <agentic-harness>/enroll.sh %s" % (root, root))
    if settings.get("mode") == "block" and data.get("tool_name") in EDIT_TOOLS:
        sys.stderr.write("Harness machine guard: refused this edit. %s\n" % message)
        return 2
    if source == "codex" or warned_once(root, data.get("session_id")):
        sys.stdout.write(quiet)
        return 0
    sys.stdout.write(json.dumps({"systemMessage": "harness: " + message}) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # never block on the guard's own failure
        sys.exit(0)
