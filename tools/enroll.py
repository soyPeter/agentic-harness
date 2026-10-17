#!/usr/bin/env python3
"""Put a project under the agentic harness for every agent and, optionally, in Orca.

  enroll.sh <target> [--name NAME] [--orca] [--automation SCHEDULE] [--agents "default=claude judge=codex"]
            [--protect] [--dry-run]

1. Installs the harness when <target> has none, otherwise updates it (bootstrap.sh / update.sh).
2. Runs the target's doctor and shows its errors and warnings.
3. --agents sets HARNESS_ORCA_AGENTS in the target's backbone/harness.conf (user-only: enroll runs as the user).
4. --orca registers the repository in Orca, so `harness.py orca` can place workers in its worktrees.
5. --automation SCHEDULE (with --orca) creates one Orca automation that runs `harness.py orca --merge --trust` in
   the repository on that schedule (an Orca preset, cron or RRULE). Enrolling again doesn't create a second one.
6. --protect requires the harness checks on the default branch (`harness.py ci-protect`), when the repository has a
   GitHub remote and `gh` is installed.

--dry-run prints every action and changes nothing. enroll never pushes and never deletes.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
LOCK = "backbone/.harness-lock.json"
CONF = "backbone/harness.conf"
# Orca 1.4 runs "repo-defined setup hooks" on each new worktree, but its CLI has no command to set one (repo set only
# changes worktree visibility; project setup-update only the setup policy). So enroll prints the step instead.
SETUP_HINT = ("Orca has no CLI to set a repository's setup hook. In Orca's settings for this repository, set the "
              "setup script to: python3 scripts/harness/lib/harness.py doctor")
# An agent session can't wait hours for a backlog, so the automation starts the coordinator in the background and
# reports the previous run's summary: one digest per run of what finished and what waits for the user.
AUTOMATION_PROMPT = ("You run the agentic harness's scheduled backlog run. Do exactly this, and don't edit files, answer "
                     "escalations or approve permission prompts yourself:\n"
                     "1. If .git/harness/orca-latest.log exists, report its last 'harness orca:' summary (each task's "
                     "outcome and the open escalations) as the digest of the previous run.\n"
                     "2. If no `harness.py orca` is running (pgrep -f 'harness.py orca'), start one in the background: "
                     "nohup python3 scripts/harness/lib/harness.py orca --merge --trust > .git/harness/orca-latest.log "
                     "2>&1 &\n"
                     "3. Report whether you started a run or one was still going.")


def say(action, detail=""):
    print("  %-10s %s" % (action, detail))


def run(argv, cwd=None):
    try:
        return subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def orca_binary():
    return os.environ.get("HARNESS_ORCA_BIN") or shutil.which("orca")


def orca(*args):
    """The orca CLI with --json: (ok, result or error message)."""
    binary = orca_binary()
    if not binary:
        return False, "orca is not installed (or set HARNESS_ORCA_BIN)"
    result = run([binary] + list(args) + ["--json"])
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return False, (result.stderr or result.stdout).strip()[:300]
    if data.get("ok") is False:
        return False, str((data.get("error") or {}).get("message") or data.get("error"))
    return True, data.get("result", data)


def install_or_update(target, name, dry_run):
    installed = (target / LOCK).exists()
    script = "update.sh" if installed else "bootstrap.sh"
    argv = [str(HARNESS / script), str(target)]
    if not installed and name:
        argv += ["--name", name]
    if dry_run:
        argv.append("--dry-run")
    result = run(argv)
    say("update" if installed else "install", "harness %s in %s%s" % (
        (HARNESS / "VERSION").read_text().strip(), target, " (dry run)" if dry_run else ""))
    for line in result.stdout.splitlines():
        if re.match(r"^\s+(CONFLICT|migrate|WARN)\b", line):
            say("", line.strip())
    if result.returncode not in (0, 1):
        raise SystemExit("enroll: %s failed:\n%s" % (script, (result.stdout + result.stderr).strip()))
    return result.returncode


def doctor(target, dry_run):
    script = target / "scripts/harness/doctor.sh"
    if dry_run or not script.exists():
        say("doctor", "skipped (dry run)" if dry_run else "skipped (no harness yet)")
        return
    result = run(["bash", str(script)], cwd=target)
    issues = [line for line in result.stdout.splitlines() if re.match(r"^(error|warn)\b", line)]
    say("doctor", "%d error(s), %d warning(s)" % (sum(1 for i in issues if i.startswith("error")),
                                                   sum(1 for i in issues if i.startswith("warn"))))
    for line in issues:
        say("", line)


def set_agents(target, agents, dry_run):
    path = target / CONF
    if not path.exists():
        say("agents", "skipped: no %s yet (dry run?)" % CONF)
        return
    text = path.read_text(encoding="utf-8")
    line = 'HARNESS_ORCA_AGENTS="%s"' % agents.replace('"', "")
    if re.search(r"(?m)^#?\s*HARNESS_ORCA_AGENTS=", text):
        new = re.sub(r"(?m)^#?\s*HARNESS_ORCA_AGENTS=.*$", line, text, count=1)
    else:
        new = text.rstrip("\n") + "\n\n# Orca coordinator: the agent per role (set by enroll).\n" + line + "\n"
    if new == text:
        say("agents", "already %s" % line)
        return
    if not dry_run:
        path.write_text(new, encoding="utf-8")
    say("agents", "%s in %s (user-only: commit it yourself, HARNESS_VERIFY=off git commit ...)" % (line, CONF))


def register_in_orca(target, dry_run):
    if dry_run:
        say("orca", "would register %s" % target)
    else:
        ok, result = orca("repo", "add", "--path", str(target))
        if not ok and not re.search(r"(?i)already|exist", str(result)):
            raise SystemExit("enroll: orca repo add: %s" % result)
        say("orca", "registered %s" % target if ok else "already registered")
    say("setup", SETUP_HINT)


def automation(target, project, schedule, dry_run):
    name = "harness-%s" % project
    ok, listed = orca("automations", "list")
    rows = listed if isinstance(listed, list) else (listed.get("automations") if isinstance(listed, dict) else None) or []
    if ok and any(isinstance(a, dict) and a.get("name") == name for a in rows):
        say("automation", "%s exists already; not creating another" % name)
        return
    if dry_run:
        say("automation", "would create %s (%s)" % (name, schedule))
        return
    ok, result = orca("automations", "create", "--name", name, "--trigger", schedule, "--prompt", AUTOMATION_PROMPT,
                      "--provider", "claude", "--workspace", "path:%s" % target, "--workspace-mode", "existing")
    if not ok:
        raise SystemExit("enroll: orca automations create: %s" % result)
    say("automation", "created %s (%s): runs harness.py orca --merge --trust" % (name, schedule))
    conf = (target / CONF).read_text(encoding="utf-8") if (target / CONF).exists() else ""
    if not re.search(r'(?m)^HARNESS_AUTONOMY="autonomous"', conf):
        say("", "note: harness.py orca refuses until you set HARNESS_AUTONOMY=\"autonomous\" in %s" % CONF)


def protect(target, dry_run):
    remote = run(["git", "-C", str(target), "remote", "get-url", "origin"]).stdout.strip()
    if "github.com" not in remote:
        say("protect", "skipped: no GitHub remote")
        return
    if not shutil.which("gh"):
        say("protect", "skipped: gh is not installed")
        return
    argv = ["python3", str(target / "scripts/harness/lib/harness.py"), "ci-protect"] + (["--dry-run"] if dry_run else [])
    result = run(argv, cwd=target)
    say("protect", (result.stdout.strip().splitlines() or ["done"])[-1] if result.returncode == 0
        else "failed: %s" % (result.stdout + result.stderr).strip()[:300])


def main(argv):
    args = argv[1:]
    if not args or args[0].startswith("-"):
        sys.stderr.write(__doc__)
        return 64
    value = lambda flag: args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None
    target = Path(args[0]).resolve()
    if not (target / ".git").exists():
        sys.stderr.write("enroll: %s is not a git repository\n" % target)
        return 2
    dry_run = "--dry-run" in args
    if value("--automation") and "--orca" not in args:
        sys.stderr.write("enroll: --automation needs --orca\n")
        return 64
    project = value("--name") or target.name
    print("Enrolling %s%s" % (target, " (dry run)" if dry_run else ""))
    code = install_or_update(target, value("--name"), dry_run)
    if value("--agents"):
        set_agents(target, value("--agents"), dry_run)
    doctor(target, dry_run)
    if "--orca" in args:
        register_in_orca(target, dry_run)
        if value("--automation"):
            automation(target, project, value("--automation"), dry_run)
    if "--protect" in args:
        protect(target, dry_run)
    if code == 1:
        print("Resolve the conflicts above (update.sh), then enroll again.")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
