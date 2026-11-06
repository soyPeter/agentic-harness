#!/usr/bin/env python3
"""Machine-level enforcement of the agentic harness, for every project on this machine.

  machine.sh install [--roots DIR ...] [--mode warn|block] [--plugin]   user level: no root needed
  machine.sh status
  machine.sh remove
  machine.sh managed --out DIR [--roots DIR ...] [--mode warn|block]   admin files to review and install yourself

install copies the guard (machine/guard.py) to ~/.agentic-harness/ and adds it as a user-level PreToolUse hook to
Claude Code (~/.claude/settings.json) and Codex (~/.codex/hooks.json). In a git repository under one of --roots that
isn't enrolled (neither a full install nor a thin one), the guard reminds (warn) or refuses file edits (block) until
the repository is enrolled; enrolled repositories are left to their own hooks. The harness source repository is
exempt. Existing hooks (Orca's, yours) are kept; remove deletes only the guard's entries.

The agentic-harness plugin runs the same check from its own hooks, with the same settings
(~/.agentic-harness/machine.json), except in a CLI where the guard hook is installed: there the guard alone answers.
With the plugin, install --plugin is enough: it writes the settings only, and takes out a guard hook installed earlier.

User-level hooks can be removed by the user. For a guard nobody on the machine can switch off, `managed` writes
Claude Code's managed-settings.json and Codex's requirements.toml with the same hook (Codex trusts managed hooks by
policy). They are written to --out for you to review; installing them in /Library or /etc needs sudo, and this tool
never does that.
"""
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
MARK = "--harness-machine-guard"   # the token that identifies the guard's own hook entries
HOOK_FILES = {"claude": (".claude", "settings.json"), "codex": (".codex", "hooks.json")}


def home(*parts):
    return Path(os.path.expanduser("~")).joinpath(*parts)


def guard_command(source, guard_path, config=None):
    prefix = "HARNESS_MACHINE_CONFIG=%s " % shlex.quote(str(config)) if config else ""
    return "%spython3 %s --from %s %s" % (prefix, shlex.quote(str(guard_path)), source, MARK)


def hook_group(source, guard_path, config=None):
    matcher = "Write|Edit|MultiEdit|Bash" if source == "claude" else "apply_patch|Bash"
    return {"matcher": matcher, "hooks": [{"type": "command", "command": guard_command(source, guard_path, config),
                                           "timeout": 10}]}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        raise SystemExit("machine: %s is not valid JSON; not touching it" % path)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".harness-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


LEGACY = re.compile(r'^python3 "[^"]*/\.agentic-harness/guard\.py" --from (claude|codex)$')   # 0.14.0-dev commands


def owned(command):
    command = str(command or "").strip()
    return MARK in command.split() or bool(LEGACY.match(command))


def without_guard(groups):
    kept = []
    for group in groups or []:
        hooks = [h for h in group.get("hooks", []) if not owned(h.get("command"))]
        if hooks:
            kept.append(dict(group, hooks=hooks))
    return kept


def has_guard(data):
    groups = (data.get("hooks") or {}).get("PreToolUse") or []
    return any(owned(hook.get("command")) for group in groups for hook in group.get("hooks", []))


def hooked(source):
    """Whether the guard is a hook in the user's settings of the CLI (claude or codex). The plugin's launcher leaves
    the check to it there, so a tool call isn't reminded or refused twice."""
    try:
        return has_guard(json.loads(home(*HOOK_FILES[source]).read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def set_hook(path, source, guard_path, install):
    data = read_json(path)
    hooks = data.setdefault("hooks", {})
    groups = without_guard(hooks.get("PreToolUse"))
    if install:
        groups.append(hook_group(source, guard_path))
    if groups:
        hooks["PreToolUse"] = groups
    else:
        hooks.pop("PreToolUse", None)
    write_json(path, data)


def parse(argv):
    roots, mode, out, key = [], "warn", None, None
    for arg in argv:
        if arg in ("--roots", "--mode", "--out", "--platform"):
            key = arg
        elif arg == "--plugin":
            key = None
        elif key == "--roots":
            roots.append(arg)
        elif key == "--mode":
            mode, key = arg, None
        elif key == "--out":
            out, key = arg, None
        elif key == "--platform":
            key = None
    if mode not in ("warn", "block"):
        raise SystemExit("machine: --mode is warn or block")
    return roots or ["~/Work/repos"], mode, out


def install(argv):
    roots, mode, _ = parse(argv)
    guard = home(".agentic-harness", "guard.py")
    guard.parent.mkdir(parents=True, exist_ok=True)
    settings = home(".agentic-harness", "machine.json")
    write_json(settings, {"roots": roots, "mode": mode, "exempt": [str(HARNESS)],
                          "enroll": str((HARNESS / "enroll.sh").resolve())})
    if "--plugin" in argv:
        print("  install    settings %s (mode %s, roots %s; exempt: %s)" % (settings, mode, ", ".join(roots), HARNESS))
        print("  plugin     the agentic-harness plugin's hooks check with them, in each CLI the plugin is installed in")
        for source, (folder, name) in HOOK_FILES.items():
            if hooked(source):
                set_hook(home(folder, name), source, guard, False)
                print("  %-10s guard hook removed from ~/%s/%s" % (source, folder, name))
        if guard.exists():
            guard.unlink()
        return 0
    shutil.copyfile(str(HARNESS / "machine" / "guard.py"), str(guard))
    set_hook(home(".claude", "settings.json"), "claude", guard, True)
    print("  install    guard %s (mode %s, roots %s; exempt: %s)" % (guard, mode, ", ".join(roots), HARNESS))
    print("  claude     PreToolUse hook in ~/.claude/settings.json (applies to new sessions)")
    if home(".codex").is_dir():
        set_hook(home(".codex", "hooks.json"), "codex", guard, True)
        print("  codex      PreToolUse hook in ~/.codex/hooks.json. Codex runs a new user hook only after you trust "
              "it once: open Codex, run /hooks and trust the agentic-harness guard.")
    else:
        print("  codex      skipped (no ~/.codex)")
    return 0


def remove(_argv):
    guard = home(".agentic-harness", "guard.py")
    for path, source in ((home(".claude", "settings.json"), "claude"), (home(".codex", "hooks.json"), "codex")):
        if path.exists():
            set_hook(path, source, guard, False)
            print("  removed    the guard hook from %s" % path)
    for name in ("guard.py", "machine.json"):
        if home(".agentic-harness", name).exists():
            home(".agentic-harness", name).unlink()
    print("  removed    %s" % home(".agentic-harness"))
    return 0


def status(_argv):
    conf = home(".agentic-harness", "machine.json")
    try:
        shown = json.dumps(json.loads(conf.read_text(encoding="utf-8"))) if conf.exists() else "not installed"
    except ValueError:
        shown = "%s is not valid JSON (the guard and the plugin then check nothing): run install again" % conf
    print("  config     %s" % shown)
    for source, (folder, name) in HOOK_FILES.items():
        path = home(folder, name)
        found = path.exists() and has_guard(read_json(path))
        print("  %-10s %s" % (source, "guard hook present" if found else
                              "no guard hook (the agentic-harness plugin checks, where installed)" if conf.exists()
                              else "no guard hook"))
    return 0


PLATFORMS = {
    "macos": {"claude_dir": "/Library/Application Support/AgenticHarness",
              "claude_settings": "/Library/Application Support/ClaudeCode/managed-settings.json"},
    "linux": {"claude_dir": "/etc/claude-code/agentic-harness",
              "claude_settings": "/etc/claude-code/managed-settings.json"},
}
CODEX_DIR = "/etc/codex/agentic-harness"


def managed(argv):
    roots, mode, out = parse(argv)
    if not out:
        raise SystemExit("machine: managed needs --out DIR")
    platform = argv[argv.index("--platform") + 1] if "--platform" in argv and argv.index("--platform") + 1 < len(argv) \
        else ("macos" if sys.platform == "darwin" else "linux")
    if platform not in PLATFORMS:
        raise SystemExit("machine: --platform is macos or linux")
    paths = PLATFORMS[platform]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(HARNESS / "machine" / "guard.py"), str(out / "guard.py"))
    write_json(out / "machine.json", {"roots": roots, "mode": mode, "exempt": [str(HARNESS)],
                                      "enroll": str((HARNESS / "enroll.sh").resolve())})
    claude_dir = paths["claude_dir"]
    write_json(out / "managed-settings.json", {
        "hooks": {"PreToolUse": [hook_group("claude", claude_dir + "/guard.py", claude_dir + "/machine.json")]},
        "permissions": {"disableBypassPermissionsMode": "disable"},
    })
    codex_command = guard_command("codex", CODEX_DIR + "/guard.py", CODEX_DIR + "/machine.json")
    (out / "requirements.toml").write_text("""# Agentic harness: Codex managed requirements (review, then install as /etc/codex/requirements.toml).
# Managed hooks are trusted by policy and can't be switched off from a user or project config.
# Don't set allow_managed_hooks_only: it would also skip each project's own harness hooks.
[features]
hooks = true

[[hooks.PreToolUse]]
matcher = "apply_patch|Bash"
[[hooks.PreToolUse.hooks]]
type = "command"
command = %s
timeout = 10
""" % json.dumps(codex_command), encoding="utf-8")
    (out / "INSTALL.md").write_text("""# Installing the managed guard (%(platform)s, needs admin rights)

Review every file here first. Then:

    sudo mkdir -p "%(claude_dir)s" %(codex_dir)s
    sudo cp guard.py machine.json "%(claude_dir)s/"
    sudo cp guard.py machine.json %(codex_dir)s/
    sudo cp managed-settings.json "%(claude_settings)s"
    sudo cp requirements.toml /etc/codex/requirements.toml

Claude Code's managed-settings.json replaces any existing one: merge by hand if you already have one. Both hooks read
the managed machine.json next to their guard, so users can't widen it. It also disables bypassPermissions mode.

Limits: the guard needs python3 and git on the PATH. If its own lookup fails (no git, a broken config), it lets the call
through rather than stop every agent on the machine; the repositories' own hooks and CI stay the enforcement.
""" % {"platform": platform, "claude_dir": claude_dir, "codex_dir": CODEX_DIR,
       "claude_settings": paths["claude_settings"]}, encoding="utf-8")
    for name in ("guard.py", "machine.json", "managed-settings.json", "requirements.toml", "INSTALL.md"):
        print("  wrote      %s" % (out / name))
    print("Review them, then follow INSTALL.md (sudo). Nothing was installed.")
    return 0


def main(argv):
    commands = {"install": install, "remove": remove, "status": status, "managed": managed}
    if len(argv) < 2 or argv[1] not in commands:
        sys.stderr.write(__doc__)
        return 64
    return commands[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
