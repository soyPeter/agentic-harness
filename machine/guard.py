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
# In block mode, a shell command in an unenrolled repository runs only if it enrolls it: a shell can write in too many
# ways (redirections, wrappers, substitutions, tools with delete flags) for an allowlist to be safe. Reads work through
# the agents' file tools.


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


def patch_paths(command):
    import re
    return re.findall(r"(?m)^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", command or "")


def targets(data, base):
    """The paths a tool call writes (Bash: its working directory). Relative paths resolve against the session's cwd."""
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    paths = []
    if tool in ("Write", "Edit", "MultiEdit") and tool_input.get("file_path"):
        paths = [tool_input["file_path"]]
    elif tool == "apply_patch":
        paths = [a or b for a, b in patch_paths(tool_input.get("command") or tool_input.get("patch"))]
    elif tool == "Bash":
        paths = [tool_input.get("workdir") or base]
    return [Path(p) if os.path.isabs(p) else Path(base) / p for p in paths if p]


def nearest_dir(path):
    path = path.resolve()
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return str(path)


def enrolls(command):
    """True only for a single, plain `.../enroll.sh <args>` command (no operators, redirections or substitutions)."""
    import re
    import shlex
    if re.search(r"[;&|<>`$()\n]", command or ""):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return bool(words) and words[0].endswith("enroll.sh")


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
    base = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    unenrolled = []
    for target in targets(data, base):
        root = repo_root(nearest_dir(target))
        if (root is None or not inside(root, settings.get("roots") or []) or inside(root, settings.get("exempt") or [])
                or (root / HARNESS_FILE).is_file()):
            continue
        if root not in unenrolled:
            unenrolled.append(root)
    if not unenrolled:
        sys.stdout.write(quiet)
        return 0
    root = unenrolled[0]
    message = ("%s is not enrolled in the agentic harness, so no spec, review or judge gates apply here. Enroll it "
               "first: <agentic-harness>/enroll.sh %s" % (root, root))
    writes = data.get("tool_name") in EDIT_TOOLS or (
        data.get("tool_name") == "Bash" and not enrolls((data.get("tool_input") or {}).get("command") or ""))
    if settings.get("mode") == "block" and writes:
        sys.stderr.write("Harness machine guard: refused this %s. %s\n" % (
            "command" if data.get("tool_name") == "Bash" else "edit", message))
        return 2
    if warned_once(root, data.get("session_id")):
        sys.stdout.write(quiet)
        return 0
    if source == "codex":
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                            "additionalContext": "harness: " + message}}) + "\n")
    else:
        sys.stdout.write(json.dumps({"systemMessage": "harness: " + message}) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # never block on the guard's own failure
        sys.exit(0)
