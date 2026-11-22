#!/usr/bin/env python3
"""Agentic harness: thin-mode launcher (ADR-001).

Every plugin hook, and every harness command in a thin project, goes through here:

    launcher.py hook <event> [--from codex|opencode]     (hook input on stdin)
    launcher.py <harness.py arguments>

The project pins the engine in backbone/.harness-lock.json ({"mode": "thin", "version", "commit"}). The launcher runs
that release from ~/.agentic-harness/engines/<version>/ (HARNESS_ENGINES), fetching tag v<version> from the harness
repository (HARNESS_ENGINE_SOURCE) the first time, and refuses one whose commit isn't the pinned one.

A repository without the harness is left alone, and a full install keeps its own hooks. When a thin project's engine
can't be run, hooks fail closed: reads go through, everything else is refused with the reason.

`hook machine-guard` is the machine guard's check (machine/guard.py, settings in ~/.agentic-harness/machine.json from
machine.sh install --plugin): in a repository under its roots that isn't enrolled, an agent's edits get a reminder, or
are refused in block mode. A CLI that runs the guard hook machine.sh installed (Codex: once the user has trusted it in
/hooks, as it is now) gets the check from that hook only, as long as the copy it runs is this release's. Like the guard,
it lets a call through when it fails.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_SOURCE = "https://github.com/soyPeter/agentic-harness.git"
ENGINE_SCRIPT = Path("payload/owned/scripts/harness/lib/harness.py")
VENDORED_SCRIPT = Path("scripts/harness/lib/harness.py")
READ_TOOLS = ("Read", "Grep", "Glob", "LS", "TodoWrite")
# Below the CLIs' hook timeouts (15s for session start, 30s for tool hooks): a hook the CLI kills lets the call through.
FETCH_SECONDS = {"session-start": 10, "subagent-start": 10}
FETCH_DEFAULT_SECONDS = 20


class EngineUnavailable(Exception):
    pass


def git(*args, timeout=10):
    try:
        result = subprocess.run(["git"] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def project_root():
    start = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    top = git("-C", start, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def read_lock(root):
    """The lock, or None when the repository has none. A lock that exists but can't be read raises: treating it as
    absent would turn every gate off, which a merge conflict in the pin would otherwise do."""
    try:
        text = (root / "backbone" / ".harness-lock.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EngineUnavailable("backbone/.harness-lock.json can't be read (%s)" % exc.strerror)
    try:
        data = json.loads(text)
    except ValueError:
        raise EngineUnavailable("backbone/.harness-lock.json is not valid JSON (an unresolved merge conflict?)")
    if not isinstance(data, dict):
        raise EngineUnavailable("backbone/.harness-lock.json is not a JSON object")
    return data


def engines_dir():
    return Path(os.environ.get("HARNESS_ENGINES") or os.path.expanduser("~/.agentic-harness/engines"))


def checked(engine, commit):
    head = git("-C", str(engine), "rev-parse", "HEAD")
    if head != commit:
        raise EngineUnavailable("the cached engine %s is at commit %s, not the pinned %s; delete it to fetch it again"
                                % (engine, head or "(unreadable)", commit))
    if not (engine / ENGINE_SCRIPT).is_file():
        raise EngineUnavailable("the cached engine %s has no %s" % (engine, ENGINE_SCRIPT))
    changes = git("-C", str(engine), "status", "--porcelain", "--untracked-files=all")
    if changes is None or changes:
        raise EngineUnavailable("the cached engine %s has local changes, so it is not the pinned release; delete it "
                                "to fetch it again" % engine)
    return engine / ENGINE_SCRIPT


def fetch(engine, version, commit, seconds):
    source = os.environ.get("HARNESS_ENGINE_SOURCE") or DEFAULT_SOURCE
    engine.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".fetch-%s-" % version, dir=str(engine.parent)))
    try:
        if git("clone", "--quiet", "--depth", "1", "--branch", "v" + version, source, str(tmp / "engine"),
               timeout=seconds) is None:
            raise EngineUnavailable("could not fetch v%s from %s (offline, or no such release)" % (version, source))
        head = git("-C", str(tmp / "engine"), "rev-parse", "HEAD")
        if head != commit:
            raise EngineUnavailable("release v%s in %s is commit %s, but the project pins %s; the tag moved or the pin "
                                    "is wrong" % (version, source, head, commit))
        try:
            os.rename(str(tmp / "engine"), str(engine))
        except OSError:
            if not engine.is_dir():   # otherwise another session fetched it first
                raise
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def engine_script(lock, event):
    version, commit = str(lock.get("version") or ""), str(lock.get("commit") or "")
    if not re.match(r"^[0-9A-Za-z][0-9A-Za-z._-]*$", version):
        raise EngineUnavailable("backbone/.harness-lock.json pins no valid version")
    if not re.match(r"^[0-9a-f]{40}$", commit):
        raise EngineUnavailable("backbone/.harness-lock.json pins version %s without its commit" % version)
    engine = engines_dir() / version
    if not engine.is_dir():
        fetch(engine, version, commit, FETCH_SECONDS.get(event, FETCH_DEFAULT_SECONDS))
    return checked(engine, commit)


def refuse(event, reason):
    message = ("Agentic harness: the engine this project pins can't be run: %s.\n"
               "Changes are refused until it can (reads still work). The user can fix the pin in "
               "backbone/.harness-lock.json, or restore network access so it can be fetched." % reason)
    if event is None:
        sys.stderr.write(message + "\n")
        return 1
    if event == "session-start":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}))
        return 0
    if event == "agent-guard":
        sys.stderr.write(message + "\n")
        return 2
    if event == "pre-tool-use":
        try:
            data = json.load(sys.stdin)
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("tool_name") in READ_TOOLS:
            return 0
        sys.stderr.write(message + "\n")
        return 2
    return 0


def plugin_module(name):
    path = Path(__file__).resolve().parents[1] / name
    spec = importlib.util.spec_from_file_location("agentic_harness_" + path.stem, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def machine_guard(source):
    sys.dont_write_bytecode = True   # no __pycache__ in the plugin's folders
    try:
        if not plugin_module("tools/machine.py").hooked(source):
            return plugin_module("machine/guard.py").main(["launcher.py", "--from", source])
    except Exception:
        pass
    sys.stdout.write("{}\n" if source == "codex" else "")
    return 0


def main(argv):
    args = argv[1:]
    if args[:1] == ["pin"] or (args[:1] == ["init"] and "--thin" in args[1:]):
        installer = Path(__file__).resolve().parents[1] / "tools/thin.py"
        if not installer.is_file():
            sys.stderr.write("Agentic harness: thin-mode installer is missing from the plugin.\n")
            return 2
        return subprocess.run([sys.executable, "-I", str(installer)] + args).returncode
    event = args[1] if len(args) >= 2 and args[0] == "hook" else None
    if event == "machine-guard":
        return machine_guard(args[args.index("--from") + 1] if "--from" in args[:-1] else "claude")
    root = project_root()
    if root is None:
        return 0 if event else refuse(None, "not inside a git repository")
    vendored = root / VENDORED_SCRIPT
    if vendored.is_file():
        if event and event not in ("agent-guard", "grill-stop", "judge-stop", "tester-stop", "debug-stop",
                                   "review-stop", "deliver-stop"):
            return 0
        os.execv(sys.executable, [sys.executable, "-I", str(vendored)] + args)
    try:
        lock = read_lock(root)
    except EngineUnavailable as exc:
        return refuse(event, str(exc))
    if not lock or lock.get("mode") != "thin":
        if event:
            return 0
        sys.stderr.write("Agentic harness: %s has no harness installed.\n" % root)
        return 1
    try:
        script = engine_script(lock, event)
    except EngineUnavailable as exc:
        return refuse(event, str(exc))
    env = dict(os.environ, HARNESS_ROOT=str(root), HARNESS_ENGINES=str(engines_dir()),
               HARNESS_PLUGIN_ROOT=str(Path(__file__).resolve().parents[1]))
    os.execve(sys.executable, [sys.executable, "-I", str(script)] + args, env)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
