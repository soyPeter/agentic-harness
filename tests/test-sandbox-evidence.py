"""Sandbox evidence in the change receipt, and the sandbox backend the runner starts its sessions with (ADR-003).

The judge-stop hook records, with each judge verdict, the sandbox it ran in: where the judge's evidence, the harness's
own test run included, was produced. `receipt` shows the evidence of the judge pass it relies on. Inside the
harness-agent container the environment says so: the image bakes the base image it was built from
(HARNESS_SANDBOX_IMAGE) and HARNESS_EGRESS_ALLOWLIST names the allowlist the egress container publishes. These checks
give the hooks that environment; tests/test-sandbox-egress.py brings up the real container (HARNESS_E2E=1).
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SANDBOX_ENVIRONMENT = ("HARNESS_SANDBOX_IMAGE", "HARNESS_EGRESS_ALLOWLIST", "HARNESS_SANDBOX_BACKEND",
                       "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
# The allowlist init-firewall.sh enforces with an empty HARNESS_FIREWALL_ALLOW, as the egress container may write it:
# in any order and case, with repeats.
PUBLISHED_ALLOWLIST = ("statsig.anthropic.com\nGitHub.com\napi.anthropic.com\ngithub.com\napi.github.com\n"
                       "codeload.github.com\nobjects.githubusercontent.com\n")
# sha256 of the sorted, deduplicated, lower-case host names, one per line.
DEFAULT_ALLOWLIST_HASH = "sha256:0e8bb6fbde0f567902ea181ebaaabe69c10a830267e395f64a2c4d0e649d5f41"
ON_THE_HOST = {"backend": "devcontainer", "isolation_class": "none", "image_digest": "none", "allowlist_hash": "none",
               "region": "local", "control_plane": "none", "credential_mode": "host"}

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

        self.assertEqual(data["sandbox"], ON_THE_HOST)
        self.assertIn("SANDBOX (where the judge pass was recorded)", text)
        for key, value in ON_THE_HOST.items():
            self.assertIn("  - %s: %s" % (key, value), text)
        self.assertIn("outside the harness-agent container", text)

    def test_a_judge_pass_in_the_harness_agent_container_records_its_image_and_allowlist(self):
        image = self.harness_agent_image()

        text, data = self.judged(HARNESS_SANDBOX_IMAGE=image, HARNESS_EGRESS_ALLOWLIST=self.published_allowlist(),
                                 CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-test-token")

        self.assertEqual(data["sandbox"], {
            "backend": "devcontainer", "isolation_class": "container", "image_digest": image.split("@", 1)[1],
            "allowlist_hash": DEFAULT_ALLOWLIST_HASH, "region": "local", "control_plane": "local",
            "credential_mode": "env"})
        self.assertIn("  - isolation_class: container", text)
        self.assertIn("  - allowlist_hash: %s" % DEFAULT_ALLOWLIST_HASH, text)
        self.assertNotIn("outside the harness-agent container", text)

    def test_the_evidence_names_how_credentials_arrive_never_the_credential(self):
        self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(), ANTHROPIC_API_KEY="sk-ant-api03-secret-key")

        verdicts = (self.project / "backbone/.verdicts/7.1.judge.json").read_text()

        self.assertEqual(json.loads(verdicts)["history"][-1]["sandbox"]["credential_mode"], "env")
        self.assertNotIn("sk-ant-api03-secret-key", verdicts)

    def test_without_a_credential_in_its_environment_the_agent_uses_the_login_stored_in_the_container(self):
        _, data = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(), CLAUDE_CODE_OAUTH_TOKEN="",
                              ANTHROPIC_API_KEY="")

        self.assertEqual(data["sandbox"]["credential_mode"], "login")

    def test_an_image_built_from_a_tag_is_not_pinned(self):
        _, data = self.judged(HARNESS_SANDBOX_IMAGE="node:22-bookworm")

        self.assertEqual(data["sandbox"]["isolation_class"], "container")
        self.assertEqual(data["sandbox"]["image_digest"], "unpinned")

    def test_an_allowlist_the_egress_side_has_not_published_is_not_vouched_for(self):
        _, data = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                              HARNESS_EGRESS_ALLOWLIST=str(self.work / "never-written"))

        self.assertEqual(data["sandbox"]["allowlist_hash"], "none")

    def test_the_hash_follows_the_hosts_not_how_they_are_written(self):
        _, wider = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                               HARNESS_EGRESS_ALLOWLIST=self.published_allowlist(PUBLISHED_ALLOWLIST + "pypi.org\n"))
        _, reordered = self.judged(HARNESS_SANDBOX_IMAGE=self.harness_agent_image(),
                                   HARNESS_EGRESS_ALLOWLIST=self.published_allowlist(
                                       "\n".join(reversed(PUBLISHED_ALLOWLIST.upper().split())) + "\n"))

        self.assertNotEqual(wider["sandbox"]["allowlist_hash"], DEFAULT_ALLOWLIST_HASH)
        self.assertEqual(reordered["sandbox"]["allowlist_hash"], DEFAULT_ALLOWLIST_HASH)

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

    def test_the_ci_floor_never_consults_the_backend(self):
        verify = self.harness("verify", check=False, HARNESS_VERIFY="block", HARNESS_SANDBOX_BACKEND="e2b")

        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("verify: ok", verify.stdout)


class SandboxFiles(Project):
    def test_the_image_is_built_from_a_base_pinned_by_digest(self):
        self.assertRegex(self.harness_agent_image(), r"^[a-z0-9./_-]+(:[\w.-]+)?@sha256:[0-9a-f]{64}$")
        self.assertIn("FROM ${HARNESS_SANDBOX_IMAGE}",
                      (self.project / ".devcontainer/harness-agent/Dockerfile").read_text())

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
