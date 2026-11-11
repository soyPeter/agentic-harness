"""Sandbox evidence in the change receipt, and the sandbox backend the runner starts its sessions with (ADR-003).

The judge-stop hook records, with each judge verdict, the sandbox it ran in: where the judge's evidence, the harness's
own test run included, was produced. `receipt` shows the evidence of the judge pass it relies on. A process counts as
inside the harness-agent container only when its own status shows the container's restrictions, which a host run never
has: so these checks cover what a host can see, and the container itself is checked by tests/test-sandbox-egress.py
(HARNESS_E2E=1).
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER_REL = ".devcontainer/harness-agent/devcontainer.json"
# Where the egress container publishes its allowlist, read-only, in the agent's container (docker-compose.yml).
EGRESS_ALLOWLIST = "/run/harness-egress/allowlist"
SANDBOX_ENVIRONMENT = ("HARNESS_SANDBOX_IMAGE", "HARNESS_EGRESS_ALLOWLIST", "HARNESS_SANDBOX_BACKEND",
                       "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
# The allowlist init-firewall.sh enforces with an empty HARNESS_FIREWALL_ALLOW, as the egress container may write it:
# in any order and case, with repeats.
PUBLISHED_ALLOWLIST = ("statsig.anthropic.com\nGitHub.com\napi.anthropic.com\ngithub.com\napi.github.com\n"
                       "codeload.github.com\nobjects.githubusercontent.com\n")
# sha256 of the sorted, deduplicated, lower-case host names, one per line.
DEFAULT_ALLOWLIST_HASH = "sha256:0e8bb6fbde0f567902ea181ebaaabe69c10a830267e395f64a2c4d0e649d5f41"
ON_THE_HOST = {"backend": "devcontainer", "isolation_class": "none", "base_image_digest": "none",
               "allowlist_hash": "none", "region": "local", "control_plane": "none", "credential_mode": "host"}
RECORDED_IN_CONTAINER = {"backend": "devcontainer", "isolation_class": "container", "allowlist_hash": DEFAULT_ALLOWLIST_HASH,
                         "region": "local", "control_plane": "local", "credential_mode": "login"}
# A devcontainer.json as installed before the egress container: one container that runs its own firewall.
STALE_DEVCONTAINER = """// An earlier harness release: one container, the firewall inside it.
{
  "name": "harness-agent",
  "build": {"dockerfile": "Dockerfile"},
  "runArgs": ["--cap-add=NET_ADMIN", "--cap-add=NET_RAW"],
  "remoteUser": "agent",
  "postStartCommand": "sudo /usr/local/bin/init-firewall.sh"
}
"""
# The same file as edited by hand: JSONC comments, trailing commas, and a string that holds a comment marker.
JSONC_STALE_DEVCONTAINER = """// An earlier harness release, edited by hand.
{
  "name": "harness-agent", // the container's name
  "build": {"dockerfile": "Dockerfile", "args": {"NOTE": "see https://example.com/a,}"},},
  "runArgs": ["--cap-add=NET_ADMIN", "--cap-add=NET_RAW",], /* before the firewall */
  "remoteUser": "agent",
  "postStartCommand": "sudo /usr/local/bin/init-firewall.sh",
}
"""

SPEC = """# Spec 7.1: Customer search

Task: 7.1
PRD: none

## Context
Support needs to find customers by name.

## Requirements
- REQ-7.1-1: The system shall return customers whose name contains the query, ignoring case.

## Acceptance criteria
- AC-7.1-1 (REQ-7.1-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.

## Non-functional requirements
- none

## Architecture
ADRs: ADR-001
Tech requirements:
- The search lives in src/search.py.

## Skills
- code-quality: all code

## Out of scope
- Fuzzy matching.

## Assumptions
- none

## Open questions
- none

## Approval
"""
JUDGE_PASS = {"verdict": "pass", "task": "7.1", "summary": "s", "findings": [],
              "criteria": [{"id": "AC-7.1-1", "met": True, "evidence": "src/search.py:2", "tests": ["test_contains"]}],
              "tests": {"command": "true", "result": "passed"}}


def final_message(report):
    return "Done.\n\n```json\n%s\n```" % json.dumps(report)


def devcontainer_config(project):
    """The installed .devcontainer/harness-agent/devcontainer.json, its // comment lines dropped (JSONC)."""
    text = (project / ".devcontainer/harness-agent/devcontainer.json").read_text()
    return json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))


class Project(unittest.TestCase):
    """A project whose task 7.1 is approved, [WIP] and implemented, so a judge pass makes `receipt 7.1` answer."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="sandbox evidence ")
        cls.work = Path(cls.temp.name).resolve()
        cls.project = cls.work / "project"
        cls.project.mkdir()
        cls.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test",
                       GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                       GIT_COMMITTER_EMAIL="test@example.com", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true",
                       HARNESS_REVIEW="off", HARNESS_DELIVER="off", PYTHONDONTWRITEBYTECODE="1",
                       CLAUDE_PROJECT_DIR=str(cls.project), HOME=str(cls.work / "home"))
        for key in ("HARNESS_ROOT", "HARNESS_AUTONOMY", "HARNESS_PROFILE", "HARNESS_ROLE") + SANDBOX_ENVIRONMENT:
            cls.env.pop(key, None)
        cls.command("git", "init", "-q", "-b", "main")
        cls.command(str(ROOT / "bootstrap.sh"), str(cls.project), "--name", "sandbox")
        cls.commit("chore: adopt agentic harness")
        (cls.project / "backbone/specs").mkdir(parents=True, exist_ok=True)
        (cls.project / "backbone/specs/7.1.md").write_text(SPEC)
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n")
        cls.commit("docs: spec for task 7.1")
        cls.hook("grill-stop", "griller", {"verdict": "pass", "task": "7.1", "questions": [], "summary": "s"})
        spec = cls.project / "backbone/specs/7.1.md"
        spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 7.1", "- [WIP] **Task 7.1"))
        (cls.project / "src").mkdir(exist_ok=True)
        (cls.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (cls.project / "tests").mkdir(exist_ok=True)
        (cls.project / "tests/test_search.py").write_text("def test_contains():  # AC-7.1-1\n    assert True\n")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def command(cls, *args, input=None, check=True, env=None):
        result = subprocess.run(args, cwd=cls.project, env=env or cls.env, input=input, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    @classmethod
    def commit(cls, message):
        cls.command("git", "add", "-A")
        cls.command("git", "commit", "-qm", message)

    @classmethod
    def harness(cls, *args, input=None, check=True, **environment):
        return cls.command("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"), *args, input=input,
                           check=check, env=dict(cls.env, **environment))

    @classmethod
    def hook(cls, event, agent, report, **environment):
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": final_message(report)}
        cls.harness("hook", event, input=json.dumps(stop), **environment)

    def judged(self, **environment):
        """The receipt (text, JSON) after a judge pass recorded in the given environment."""
        self.hook("judge-stop", "judge", JUDGE_PASS, **environment)
        return self.harness("receipt", "7.1").stdout, json.loads(self.harness("receipt", "7.1", "--json").stdout)

    def recorded(self, sandbox):
        """The receipt (text, JSON) after the latest judge pass's sandbox is replaced by the given record."""
        self.judged()
        verdicts = self.project / "backbone/.verdicts/7.1.judge.json"
        record = json.loads(verdicts.read_text())
        record["history"][-1]["sandbox"] = sandbox
        verdicts.write_text(json.dumps(record, indent=2) + "\n")
        return self.harness("receipt", "7.1").stdout, json.loads(self.harness("receipt", "7.1", "--json").stdout)

    def harness_agent_image(self):
        """The image reference the installed Dockerfile builds from, as the image bakes it into its environment."""
        found = re.findall(r"(?m)^ARG HARNESS_SANDBOX_IMAGE=(\S+)$",
                           (self.project / ".devcontainer/harness-agent/Dockerfile").read_text())
        self.assertEqual(len(found), 1, "the Dockerfile names the image it builds from once, in an ARG")
        return found[0]

    def published_allowlist(self, text=PUBLISHED_ALLOWLIST):
        path = self.work / "egress" / "allowlist"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        return str(path)


class Evidence(Project):
    def test_a_judge_pass_on_the_host_records_that_nothing_isolated_it(self):
        text, data = self.judged()

        self.assertEqual({key: data["sandbox"][key] for key in ON_THE_HOST}, ON_THE_HOST)
        self.assertTrue(data["sandbox"]["isolation_reason"])
        self.assertIn("SANDBOX (where the judge pass was recorded)", text)
        for key, value in ON_THE_HOST.items():
            self.assertIn("  - %s: %s" % (key, value), text)
        self.assertIn("nothing isolated the session from the host", text)

    def test_the_harness_image_variable_and_an_allowlist_alone_do_not_make_a_container(self):
        text, data = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                                 HARNESS_EGRESS_ALLOWLIST="/etc/hosts",
                                 CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-test-token")

        self.assertEqual({key: data["sandbox"][key] for key in ON_THE_HOST}, ON_THE_HOST)
        self.assertIn("nothing isolated the session from the host", text)

    @unittest.skipUnless(os.environ.get("HARNESS_SANDBOX_IMAGE") and os.path.isfile(EGRESS_ALLOWLIST),
                         "runs inside the harness-agent sandbox, where the egress container publishes its allowlist")
    def test_inside_the_harness_agent_sandbox_a_judge_pass_is_a_container(self):
        _, data = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                              HARNESS_EGRESS_ALLOWLIST=EGRESS_ALLOWLIST)

        self.assertEqual(data["sandbox"]["isolation_class"], "container", data["sandbox"]["isolation_reason"])
        self.assertEqual(data["sandbox"]["allowlist_hash"], DEFAULT_ALLOWLIST_HASH)
        self.assertIn("in a container", data["sandbox"]["isolation_reason"])

    def test_the_evidence_never_holds_a_credential(self):
        self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(), ANTHROPIC_API_KEY="sk-ant-api03-secret-key")

        verdicts = (self.project / "backbone/.verdicts/7.1.judge.json").read_text()

        self.assertNotIn("sk-ant-api03-secret-key", verdicts)

    def test_an_allowlist_the_egress_side_has_not_published_is_not_vouched_for(self):
        _, data = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                              HARNESS_EGRESS_ALLOWLIST=str(self.work / "never-written"))

        self.assertEqual(data["sandbox"]["allowlist_hash"], "none")

    def test_a_judge_pass_recorded_before_sandbox_evidence_says_so(self):
        self.judged()
        verdicts = self.project / "backbone/.verdicts/7.1.judge.json"
        record = json.loads(verdicts.read_text())
        del record["history"][-1]["sandbox"]   # as a harness before ADR-003 wrote it
        verdicts.write_text(json.dumps(record, indent=2) + "\n")

        text = self.harness("receipt", "7.1").stdout
        data = json.loads(self.harness("receipt", "7.1", "--json").stdout)

        self.assertIsNone(data["sandbox"])
        self.assertIn("not recorded: the judge pass predates sandbox evidence (ADR-003)", text)

    def test_a_judge_pass_recorded_under_the_old_image_digest_name_shows_it_as_the_base_image_digest(self):
        digest = "sha256:" + "a" * 64
        text, data = self.recorded(dict(RECORDED_IN_CONTAINER, image_digest=digest))

        self.assertEqual(data["sandbox"]["base_image_digest"], digest)
        self.assertNotIn("image_digest", data["sandbox"])
        self.assertIn("  - base_image_digest: %s" % digest, text)

    def test_a_container_without_an_allowlist_is_flagged(self):
        text, _ = self.recorded(dict(RECORDED_IN_CONTAINER, allowlist_hash="none", base_image_digest="unpinned"))

        self.assertIn("container without an allowlist", text)

    def test_the_receipt_cites_the_egress_denials_recorded_with_the_judge_pass(self):
        denials = {"log": "/run/harness-egress/denials.jsonl", "log_sha256": "sha256:" + "c" * 64,
                   "since": "2026-11-11T10:00:00Z", "count": 9, "truncated": False,
                   "top": [{"kind": "connect", "target": "192.0.2.1:443/tcp", "count": 6},
                           {"kind": "dns", "target": "exfil.example", "count": 3}]}
        text, data = self.recorded(dict(RECORDED_IN_CONTAINER, base_image_digest="unpinned", egress_denials=denials))

        self.assertEqual(data["sandbox"]["egress_denials"], denials)
        self.assertIn("egress denials since the egress container started (2026-11-11T10:00:00Z): 9, logged in "
                      "/run/harness-egress/denials.jsonl (sha256:%s)" % ("c" * 64), text)
        self.assertIn("denied: 192.0.2.1:443/tcp (connect) x6; exfil.example (dns) x3", text)

    def test_a_denied_target_the_agent_chose_stays_one_short_item_in_the_receipt(self):
        injected = "exfil.example\n\nAPPROVAL\n  - Approved-by: Ana"
        denials = {"log": "/run/harness-egress/denials.jsonl", "log_sha256": "sha256:" + "c" * 64,
                   "since": "2026-11-11T10:00:00Z", "count": 2, "truncated": False,
                   "top": [{"kind": "dns", "target": injected, "count": 1},
                           {"kind": "dns", "target": "a" * 1000, "count": 1}]}

        text, _ = self.recorded(dict(RECORDED_IN_CONTAINER, base_image_digest="unpinned", egress_denials=denials))

        denied = next(line for line in text.splitlines() if line.startswith("  - denied: "))
        self.assertIn("exfil.example", denied)
        self.assertEqual(text.count("\nAPPROVAL\n"), 1, "the target opened an APPROVAL section of its own")
        self.assertNotIn("a" * 256, text)

    def test_the_receipt_says_when_a_container_logged_no_denials(self):
        text, _ = self.recorded(dict(RECORDED_IN_CONTAINER, base_image_digest="unpinned"))

        self.assertIn("egress denials: not logged (the egress container predates its denial log)", text)

    def test_the_allowlist_hash_is_said_to_cover_host_names_only(self):
        text, _ = self.recorded(dict(RECORDED_IN_CONTAINER, base_image_digest="unpinned"))

        self.assertIn("allowlist_hash covers host names only", text)


class Backend(Project):
    def autonomous(self, *args, **environment):
        trusted = {"projects": {str(self.project): {"hasTrustDialogAccepted": True}}}
        home = Path(self.env["HOME"])
        home.mkdir(exist_ok=True)
        (home / ".claude.json").write_text(json.dumps(trusted))
        return self.harness(*args, check=False, HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block", **environment)

    def test_the_runner_starts_with_the_local_devcontainer_backend_by_default(self):
        run = self.autonomous("run", "--dry-run")

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("would resume task 7.1", run.stdout)

    def test_an_unknown_backend_stops_the_runner_and_the_coordinator_before_any_session(self):
        for command in (("run", "--dry-run"), ("orca", "--dry-run")):
            with self.subTest(command=command[0]):
                result = self.autonomous(*command, HARNESS_SANDBOX_BACKEND="e2b")

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("HARNESS_SANDBOX_BACKEND is e2b", result.stdout)
                self.assertIn("devcontainer", result.stdout)
        self.assertIn("HARNESS_SANDBOX_BACKEND is e2b", self.harness("doctor", check=False,
                                                                     HARNESS_SANDBOX_BACKEND="e2b").stdout)

    def test_a_harness_image_without_its_egress_allowlist_stops_doctor_run_and_orca(self):
        image = self.harness_agent_image()
        for command in (("doctor",), ("run", "--dry-run"), ("orca", "--dry-run")):
            with self.subTest(command=command[0]):
                result = self.autonomous(*command, HARNESS_SANDBOX_IMAGE=image, HARNESS_EGRESS_ALLOWLIST="")

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("HARNESS_EGRESS_ALLOWLIST", result.stdout)

    def test_a_harness_image_whose_allowlist_is_not_the_egress_volumes_is_a_doctor_error(self):
        result = self.harness("doctor", check=False, HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                              HARNESS_EGRESS_ALLOWLIST=self.published_allowlist())

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(EGRESS_ALLOWLIST, result.stdout)

    def test_the_ci_floor_never_consults_the_backend(self):
        verify = self.harness("verify", check=False, HARNESS_VERIFY="block", HARNESS_SANDBOX_BACKEND="e2b")

        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("verify: ok", verify.stdout)


class Start(Project):
    """HARNESS_SANDBOX_START=on: run on the host brings the project's sandbox up with the devcontainer CLI and runs each
    session in it. The container itself is checked by HostRun in tests/test-sandbox-egress.py (HARNESS_E2E=1); these
    checks cover what decides whether run may start at all.

      HARNESS_SANDBOX_START  sandbox files  devcontainer and docker on the PATH  doctor  run
      off                    any            any                                   ok      sessions run where run runs
      on                     missing        any                                   error   refuses
      on                     present        either missing                        error   refuses
      on                     not trusted    both                                  error   refuses, nothing started
      on                     trusted        both                                  ok      starts the sandbox

    devcontainer up runs parts of the sandbox's definition on the host (initializeCommand, the Compose file's mounts
    and privileges), and an agent in the sandbox can write the workspace. So run trusts the definition only when it is
    the running engine's own copy, kept outside the project, or one the user approved on this machine
    (harness.py sandbox-approve), and agents may not change either.
    """

    def tools(self, *names, failing=False, unisolated=False):
        """A PATH with git, python3 and sh, and executables standing in for names: they succeed, or fail like a sandbox
        that can't come up. unisolated: devcontainer brings up a "sandbox" that runs everything right here, on the
        host."""
        folder = Path(tempfile.mkdtemp(prefix="tools ", dir=str(self.work)))
        for tool in ("git", "python3", "sh"):
            (folder / tool).symlink_to(shutil.which(tool))
        for name in names:
            script = folder / name
            if unisolated and name == "devcontainer":
                script.write_text(UNISOLATED_DEVCONTAINER % str(folder / "calls"))
            else:
                script.write_text("#!/bin/sh\necho \"${0##*/} $*\" >> '%s/calls'\n%s\n" % (
                    folder, 'echo \'{"outcome":"error","message":"the build failed"}\'; exit 1' if failing
                    else "exit 0"))
            script.chmod(0o755)
        return str(folder)

    def approve(self):
        approvals = Path(self.env["HOME"]) / ".agentic-harness/sandbox-approvals.json"
        self.addCleanup(lambda: approvals.unlink() if approvals.exists() else None)
        approved = self.harness("sandbox-approve", check=False)
        self.assertEqual(approved.returncode, 0, approved.stdout + approved.stderr)
        return approved.stdout

    def autonomous(self, *args, **environment):
        trusted = {"projects": {str(self.project): {"hasTrustDialogAccepted": True}}}
        home = Path(self.env["HOME"])
        home.mkdir(exist_ok=True)
        (home / ".claude.json").write_text(json.dumps(trusted))
        return self.harness(*args, check=False, HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block", **environment)

    def test_doctor_needs_the_sandbox_files_and_both_tools_to_start_the_sandbox(self):
        cases = ((self.tools(), "devcontainer"), (self.tools("devcontainer"), "docker"),
                 (self.tools("docker"), "devcontainer"))
        for path, missing in cases:
            with self.subTest(missing=missing, path=path):
                doctor = self.harness("doctor", check=False, HARNESS_SANDBOX_START="on", PATH=path)

                self.assertEqual(doctor.returncode, 1, doctor.stdout)
                self.assertIn("HARNESS_SANDBOX_START is on", doctor.stdout)
                self.assertIn(missing, doctor.stdout)
        self.approve()
        self.assertNotIn("HARNESS_SANDBOX_START", self.harness("doctor", check=False, HARNESS_SANDBOX_START="on",
                                                               PATH=self.tools("devcontainer", "docker")).stdout)
        self.assertNotIn("HARNESS_SANDBOX_START", self.harness("doctor", check=False, PATH=self.tools()).stdout)

    def test_doctor_needs_the_sandbox_files_to_start_the_sandbox(self):
        config = self.project / DEVCONTAINER_REL
        kept = config.read_bytes()
        config.unlink()
        self.addCleanup(config.write_bytes, kept)

        doctor = self.harness("doctor", check=False, HARNESS_SANDBOX_START="on", PATH=self.tools("devcontainer", "docker"))

        self.assertEqual(doctor.returncode, 1, doctor.stdout)
        self.assertIn(DEVCONTAINER_REL, doctor.stdout)

    def test_a_start_value_that_is_neither_on_nor_off_is_a_doctor_error(self):
        doctor = self.harness("doctor", check=False, HARNESS_SANDBOX_START="yes")

        self.assertEqual(doctor.returncode, 1, doctor.stdout)
        self.assertIn("HARNESS_SANDBOX_START must be on or off", doctor.stdout)

    def test_run_refuses_without_the_tools_to_start_the_sandbox(self):
        run = self.autonomous("run", "--dry-run", HARNESS_SANDBOX_START="on", PATH=self.tools())

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("devcontainer", run.stdout)

    def test_a_dry_run_says_it_would_start_the_sandbox(self):
        self.approve()
        run = self.autonomous("run", "--dry-run", HARNESS_SANDBOX_START="on", PATH=self.tools("devcontainer", "docker"))

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("would bring up .devcontainer/harness-agent/ with the devcontainer CLI", run.stdout)
        self.assertIn("would resume task 7.1", run.stdout)

    def test_run_refuses_to_run_worktrees_in_the_sandbox(self):
        self.approve()
        path = self.tools("devcontainer", "docker")

        run = self.autonomous("run", "--worktree", HARNESS_SANDBOX_START="on", PATH=path)

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("--worktree", run.stdout)
        self.assertFalse((Path(path) / "calls").exists(), "nothing was started")
        self.assertNotIn("harness/task-", self.command("git", "branch", "--list").stdout)

    def test_run_stops_before_any_session_when_the_sandbox_does_not_come_up(self):
        self.approve()
        path = self.tools("devcontainer", "docker", failing=True)

        run = self.autonomous("run", "--only", "7.1", HARNESS_SANDBOX_START="on", PATH=path)

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("the sandbox could not start", run.stdout)
        self.assertIn("the build failed", run.stdout)
        calls = (Path(path) / "calls").read_text()
        self.assertIn("devcontainer up --workspace-folder %s" % self.project, calls)
        self.assertNotIn("devcontainer exec", calls)


    def test_a_sandbox_definition_this_machine_has_not_approved_starts_nothing(self):
        path = self.tools("devcontainer", "docker")

        doctor = self.harness("doctor", check=False, HARNESS_SANDBOX_START="on", PATH=path)
        run = self.autonomous("run", "--only", "7.1", HARNESS_SANDBOX_START="on", PATH=path)

        self.assertEqual(doctor.returncode, 1, doctor.stdout)
        self.assertIn("harness.py sandbox-approve", doctor.stdout)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertFalse((Path(path) / "calls").exists(), "devcontainer ran for an unapproved definition")

    def test_a_definition_changed_after_its_approval_starts_nothing(self):
        self.approve()
        config = self.project / DEVCONTAINER_REL
        kept = config.read_text()
        self.addCleanup(config.write_text, kept)
        for change in ('"initializeCommand": "touch /tmp/escaped",\n  "name"', '"name"'):
            with self.subTest(change=change):
                config.write_text(kept.replace('"name"', change, 1) + ("\n" if change == '"name"' else ""))
                path = self.tools("devcontainer", "docker")

                run = self.autonomous("run", "--only", "7.1", HARNESS_SANDBOX_START="on", PATH=path)

                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn("sandbox-approve", run.stdout)
                self.assertFalse((Path(path) / "calls").exists(), "devcontainer ran for a changed definition")

    def test_a_file_added_to_the_sandbox_folder_needs_approval_too(self):
        self.approve()
        extra = self.project / ".devcontainer/harness-agent/.env"
        extra.write_text("COMPOSE_FILE=elsewhere.yml\n")
        self.addCleanup(extra.unlink)

        doctor = self.harness("doctor", check=False, HARNESS_SANDBOX_START="on", PATH=self.tools("devcontainer", "docker"))

        self.assertEqual(doctor.returncode, 1, doctor.stdout)
        self.assertIn("sandbox-approve", doctor.stdout)

    def test_approving_names_the_definition_it_trusts(self):
        out = self.approve()

        self.assertIn(".devcontainer/harness-agent/", out)
        self.assertRegex(out, r"sha256:[0-9a-f]{64}")
        self.assertIn("devcontainer.json", out)

    def test_run_refuses_a_sandbox_that_does_not_isolate_the_session(self):
        self.approve()
        path = self.tools("devcontainer", "docker", unisolated=True)

        run = self.autonomous("run", "--only", "7.1", HARNESS_SANDBOX_START="on", PATH=path)

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("isolation_class none", run.stdout)
        self.assertNotIn("attempt 1", run.stdout)

    def test_agents_cannot_change_the_sandbox_definition_or_approve_it(self):
        config = self.project / DEVCONTAINER_REL
        approvals = Path(self.env["HOME"]) / ".agentic-harness/sandbox-approvals.json"
        writes = {
            "relative": {"tool_name": "Write", "tool_input": {"file_path": DEVCONTAINER_REL, "content": "{}"}},
            "absolute": {"tool_name": "Edit", "tool_input": {"file_path": str(config), "old_string": '"name"',
                                                             "new_string": '"initializeCommand": "id", "name"'}},
            "the approvals": {"tool_name": "Write", "tool_input": {"file_path": str(approvals), "content": "{}"}},
            "shell": {"tool_name": "Bash", "tool_input": {"command": "echo '{}' > %s" % DEVCONTAINER_REL}},
            "compose": {"tool_name": "Bash", "tool_input": {
                "command": "sed -i 's/cap_drop/cap_add/' .devcontainer/harness-agent/docker-compose.yml"}},
            "a script": {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"open('.devcontainer/"
                                                                        "harness-agent/Dockerfile', 'a').write('x')\""}},
            "approve": {"tool_name": "Bash", "tool_input": {
                "command": "python3 scripts/harness/lib/harness.py sandbox-approve"}},
        }
        for name, call in writes.items():
            with self.subTest(write=name):
                hook = self.harness("hook", "pre-tool-use", input=json.dumps(dict(call, agent_id="a1")), check=False)

                self.assertEqual(hook.returncode, 2, hook.stdout + hook.stderr)


UNISOLATED_DEVCONTAINER = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(%r, "a") as calls:
    calls.write(" ".join(["devcontainer"] + args) + "\\n")
if args[0] == "up":
    print(json.dumps({"outcome": "success", "containerId": "here", "composeProjectName": "here",
                      "remoteWorkspaceFolder": args[args.index("--workspace-folder") + 1]}))
    sys.exit(0)
rest = args[1:]
while rest and rest[0].startswith("--"):
    rest = rest[2:]
os.execvp(rest[0], rest)
"""


class Upgrade(Project):
    def keep_stale_devcontainer(self, text=STALE_DEVCONTAINER):
        (self.project / DEVCONTAINER_REL).write_text(text)

    def test_doctor_warns_about_a_devcontainer_json_that_predates_the_egress_container(self):
        self.keep_stale_devcontainer()

        result = self.harness("doctor", check=False)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("predates the two-container sandbox", result.stdout)

    def test_doctor_reads_a_stale_devcontainer_json_with_inline_comments_and_trailing_commas(self):
        self.keep_stale_devcontainer(JSONC_STALE_DEVCONTAINER)

        result = self.harness("doctor", check=False)

        self.assertIn("predates the two-container sandbox", result.stdout)

    def test_doctor_says_when_devcontainer_json_cannot_be_parsed(self):
        self.keep_stale_devcontainer('{\n  "name": "harness-agent",\n  "runArgs": [\n}\n')

        result = self.harness("doctor", check=False)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("devcontainer.json can't be parsed", result.stdout)

    def test_update_says_what_to_merge_when_it_keeps_an_edited_devcontainer_json_from_before_the_egress_container(self):
        self.keep_stale_devcontainer()
        lock = self.project / "backbone/.harness-lock.json"
        record = json.loads(lock.read_text())
        # Installed from an earlier release, then edited: the upstream file has changed since.
        record["files"][DEVCONTAINER_REL] = hashlib.sha256((STALE_DEVCONTAINER + "// older\n").encode()).hexdigest()
        lock.write_text(json.dumps(record, indent=2) + "\n")

        result = self.command(str(ROOT / "update.sh"), str(self.project), check=False)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.project / (DEVCONTAINER_REL + ".harness-new")).is_file())
        self.assertIn("WARN", result.stdout)
        self.assertIn("dockerComposeFile", result.stdout)


class SandboxFiles(Project):
    def test_the_image_is_built_from_a_base_pinned_by_digest(self):
        self.assertRegex(self.harness_agent_image(), r"^[a-z0-9./_-]+(:[\w.-]+)?@sha256:[0-9a-f]{64}$")
        self.assertIn("FROM ${HARNESS_SANDBOX_IMAGE}",
                      (self.project / ".devcontainer/harness-agent/Dockerfile").read_text())

    def test_doctor_does_not_call_the_installed_devcontainer_json_stale_or_unreadable(self):
        result = self.harness("doctor", check=False)

        self.assertNotIn("predates the two-container sandbox", result.stdout)
        self.assertNotIn("can't be parsed", result.stdout)

    def test_the_agent_container_gets_no_network_admin_capability(self):
        config = devcontainer_config(self.project)

        self.assertFalse([arg for arg in config.get("runArgs", []) if "cap-add" in arg or "privileged" in arg])
        self.assertFalse(set(config.get("capAdd", [])) & {"NET_ADMIN", "NET_RAW"})
        self.assertFalse(config.get("privileged"))

    @unittest.skipUnless(shutil.which("docker"), "reads the compose file with docker compose config")
    def test_the_agent_shares_a_network_whose_rules_only_the_egress_container_can_change(self):
        config = devcontainer_config(self.project)
        folder = self.project / ".devcontainer/harness-agent"
        # The user's own HOME: docker finds its compose plugin there.
        compose = json.loads(self.command("docker", "compose", "-f", str(folder / config["dockerComposeFile"]),
                                          "config", "--format", "json", env=os.environ).stdout)["services"]
        agent = compose[config["service"]]
        owner = re.match(r"^service:(\S+)$", agent.get("network_mode", ""))

        self.assertFalse(set(agent.get("cap_add", [])) & {"NET_ADMIN", "NET_RAW"})
        self.assertLessEqual({"NET_ADMIN", "NET_RAW"}, set(agent.get("cap_drop", [])))
        self.assertIn("no-new-privileges:true", agent.get("security_opt", []))
        self.assertFalse(agent.get("privileged"))
        self.assertTrue(owner, "the agent joins another service's network namespace")
        self.assertIn("NET_ADMIN", compose[owner.group(1)].get("cap_add", []))
        self.assertIn(owner.group(1), config.get("runServices", [owner.group(1)]))


if __name__ == "__main__":
    unittest.main()
