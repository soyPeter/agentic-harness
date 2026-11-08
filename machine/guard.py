#!/usr/bin/env python3
"""Agentic harness: machine guard (installed by machine.sh into ~/.agentic-harness/guard.py).

A user-level (or managed) PreToolUse hook for Claude Code and Codex. It runs in every project and does one thing:
in a git repository under one of your work folders that has no agentic harness, it warns (mode "warn") or refuses
file edits (mode "block") until the repository is enrolled (enroll.sh <path>). A repository is enrolled when it has
a full install (its own engine in scripts/harness/) or a thin one (a "thin" pin in backbone/.harness-lock.json, run
by the agentic-harness plugin); there it does nothing, because the repository's own hooks or the plugin's enforce
the gates.

Config: ~/.agentic-harness/machine.json (or HARNESS_MACHINE_CONFIG): {"roots": [...], "mode": "warn"|"block",
"exempt": [...]}, where roots and exempt are lists of folders; settings that aren't count as none. A guard error never
blocks: the repository's own hooks are the enforcement; this only enrolls.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "apply_patch")
HARNESS_FILE = "scripts/harness/lib/harness.py"
LOCK_FILE = "backbone/.harness-lock.json"
# In block mode, a shell command in an unenrolled repository runs only if it enrolls it: a shell can write in too many
# ways (redirections, wrappers, substitutions, tools with delete flags) for an allowlist to be safe. Reads work through
# the agents' file tools.


def config():
    path = Path(os.environ.get("HARNESS_MACHINE_CONFIG") or os.path.expanduser("~/.agentic-harness/machine.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if problem(data) is None else None


def problem(settings):
    """Why these settings can't be used, or None. A string in place of a list of folders would be read character by
    character, and "/" holds every path."""
    if not isinstance(settings, dict):
        return "the settings are not a JSON object"
    for name in ("roots", "exempt"):
        value = settings.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return '"%s" must be a list of folders' % name
    return None


def repo_root(start):
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 and out.stdout.strip() else None


def enrolled(root):
    """A full install, or a thin pin. A lock that exists but can't be read (a merge conflict in the pin) counts too, as
    a valid pin does, whether or not the CLI has the plugin: the guard judges the repository, not what the CLI has
    installed. Run as its own hook, the guard can't tell whether the plugin is there; where it is, the plugin's launcher
    refuses a session's changes in that repository until the lock is fixed, and a "not enrolled" answer would
    contradict that."""
    if (root / HARNESS_FILE).is_file():
        return True
    try:
        lock = json.loads((root / LOCK_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    return not isinstance(lock, dict) or lock.get("mode") == "thin"


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
        workdir = tool_input.get("workdir") or base
        return [Path(workdir)] + shell_paths(tool_input.get("command"), workdir)
    return [Path(p) if os.path.isabs(p) else Path(base) / p for p in paths if p]


def nearest_dir(path):
    path = path.resolve()
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return str(path)


def enrolls(command, base, enroll_path):
    """True only for a single, plain run of the harness's own enroll.sh (the path machine.sh install recorded),
    with no operators, redirections or substitutions. A script that merely has the same name doesn't count."""
    import re
    import shlex
    if not enroll_path or re.search(r"[;&|<>`$()\n]", command or ""):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words:
        return False
    program = Path(os.path.expanduser(words[0]))
    program = program if program.is_absolute() else Path(base) / program
    try:
        return program.resolve() == Path(enroll_path).resolve()
    except OSError:
        return False


def shell_paths(command, base):
    """Best effort: the paths a shell command names, so a command run from one repository that writes into another
    is judged by that other one. Tokens come from a shell-aware split (redirections become their own tokens, quoted
    paths keep their spaces); a token that is a path, a cd target, or code containing a literal absolute path counts.
    Paths built at run time (variables, computed strings) aren't visible."""
    import re
    import shlex
    try:
        lexer = shlex.shlex(command or "", posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = (command or "").split()
    found = []
    for i, token in enumerate(tokens):
        if re.match(r"^(~|\.\.?)?/|^\.\.$", token) or (i > 0 and tokens[i - 1] == "cd"):
            found.append(token)
        else:
            # Code passed to an interpreter (python3 -c "...", node -e '...'): quoted literal paths, spaces and all,
            # then unquoted absolute paths.
            quoted = re.findall(r"""(['"])((?:~|/)[^'"\n]*)\1""", token)
            found += [path for _, path in quoted]
            found += re.findall(r"(?:^|[\s=(:,])(/[^\s'\"<>|;&()`$,]+)", token)
    paths = []
    for item in found:
        item = os.path.expanduser(item)
        paths.append(Path(item) if os.path.isabs(item) else Path(base) / item)
    return paths


def warned_once(root, session):
    """True if this session was already reminded about root (one reminder per session and repository). The CLIs run
    hooks, and a session's tool calls, at the same time, so only the hook that creates the marker reminds."""
    marker = Path(os.path.expanduser("~/.agentic-harness/warned")) / ("%s-%s" % (session or "session",
                                                                             str(root).strip("/").replace("/", "_")))
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return True
    except OSError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(time.strftime("%Y-%m-%dT%H:%M:%S"))
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
                or enrolled(root)):
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
        data.get("tool_name") == "Bash" and not enrolls((data.get("tool_input") or {}).get("command") or "",
                                                        (data.get("tool_input") or {}).get("workdir") or base,
                                                        settings.get("enroll")))
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
