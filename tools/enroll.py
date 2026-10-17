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
# The automation's precheck, which Orca runs itself before the agent, starts the backlog in its own Orca terminal
# (`harness.py orca-nightly`; agents may not start coordinators). The agent only reports the digest of the last run.
AUTOMATION_PRECHECK = "python3 scripts/harness/lib/harness.py orca-nightly"
AUTOMATION_PROMPT = ("Run `python3 scripts/harness/lib/harness.py orca-digest` in this repository and report its output "
                     "as the digest of the agentic harness's last backlog run: each task's outcome and the open "
                     "escalations, which wait for the user. Don't edit files, answer escalations or approve permission "
                     "prompts.")


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
    if result.returncode != 0 and not result.stdout.strip():
        return False, (result.stderr.strip() or "orca exited with %d" % result.returncode)[:300]
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return False, (result.stderr or result.stdout).strip()[:300] or "orca printed no JSON"
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
        return 0
    result = run(["bash", str(script)], cwd=target)
    issues = [line for line in (result.stdout + result.stderr).splitlines() if re.match(r"(?i)^(error|warn)\b", line)]
    errors = sum(1 for i in issues if i.lower().startswith("error"))
    say("doctor", "%d error(s), %d warning(s)" % (errors, len(issues) - errors))
    for line in issues:
        say("", line)
    return 1 if errors or result.returncode != 0 else 0


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


def automation_name(target, project):
    """The automation's identity: the project name plus a hash of the checkout's path, so two projects that share a
    name (client-a/api, client-b/api) get one each, and the same checkout always maps to the same automation."""
    import hashlib
    return "harness-%s-%s" % (project, hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:8])


def automation(target, project, schedule, dry_run):
    name = automation_name(target, project)
    ok, listed = orca("automations", "list")
    if not ok:
        raise SystemExit("enroll: can't list Orca automations (%s); not creating one, so none is duplicated" % listed)
    rows = listed if isinstance(listed, list) else (listed.get("automations") if isinstance(listed, dict) else None) or []
    workspace = "path:%s" % target
    same = [a for a in rows if isinstance(a, dict) and (a.get("name") == name or
                                                         str(a.get("workspace") or "").rstrip("/") == workspace)]
    if same:
        say("automation", "%s exists already for this checkout; not creating another" % (same[0].get("name") or name))
        return
    if dry_run:
        say("automation", "would create %s (%s)" % (name, schedule))
        return
    ok, result = orca("automations", "create", "--name", name, "--trigger", schedule, "--prompt", AUTOMATION_PROMPT,
                      "--precheck", AUTOMATION_PRECHECK, "--provider", "claude", "--workspace", workspace,
                      "--workspace-mode", "existing")
    if not ok:
        raise SystemExit("enroll: orca automations create: %s" % result)
    say("automation", "created %s (%s): its precheck starts harness.py orca --merge --trust in its own Orca "
                      "terminal; the agent reports the last run's digest" % (name, schedule))
    conf = (target / CONF).read_text(encoding="utf-8") if (target / CONF).exists() else ""
    if not re.search(r'(?m)^HARNESS_AUTONOMY="autonomous"', conf):
        say("", "note: harness.py orca refuses until you set HARNESS_AUTONOMY=\"autonomous\" in %s" % CONF)


def protect(target, dry_run):
    remote = run(["git", "-C", str(target), "remote", "get-url", "origin"]).stdout.strip()
    if "github.com" not in remote:
        say("protect", "skipped: no GitHub remote")
        return 0
    if not shutil.which("gh"):
        say("protect", "skipped: gh is not installed")
        return 0
    # ci-protect finds the default branch itself and keeps the branch's existing checks and rules.
    argv = ["python3", str(target / "scripts/harness/lib/harness.py"), "ci-protect"] + (["--dry-run"] if dry_run else [])
    result = run(argv, cwd=target)
    say("protect", (result.stdout.strip().splitlines() or ["done"])[-1] if result.returncode == 0
        else "failed: %s" % (result.stdout + result.stderr).strip()[:300])
    return 0 if result.returncode == 0 else 1


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
    health = doctor(target, dry_run)
    if "--orca" in args:
        register_in_orca(target, dry_run)
        if value("--automation"):
            automation(target, project, value("--automation"), dry_run)
    protected = protect(target, dry_run) if "--protect" in args else 0
    if code == 1:
        print("Resolve the conflicts above (update.sh), then enroll again.")
    if health:
        print("Fix the doctor's errors above; the gates may not hold until then.")
    if protected:
        print("Branch protection was requested and failed; see above.")
    return 1 if code or health or protected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
