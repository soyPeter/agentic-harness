"""The harness-agent sandbox end to end, in a real container (ADR-003). Opt-in: HARNESS_E2E=1, with docker running and
the devcontainer CLI on the PATH (npm install -g @devcontainers/cli). It builds the image, so a first run takes a few
minutes and needs the network.

Each class bootstraps a throwaway project, brings its .devcontainer/harness-agent/ up with `devcontainer up` and checks
from inside, as the agent:
- a host off the allowlist can't be reached, and an allowlisted one can;
- the agent's container holds neither NET_ADMIN nor NET_RAW, and nothing the agent runs changes the rules in force or
  the allowlist the evidence is taken from;
- a judge pass recorded inside records that sandbox, and the receipt shows it on the host.
The containers, images and volumes a class created are removed afterwards. The harness-agent-claude-config volume,
which every project's sandbox shares, is left alone.
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
DEVCONTAINER = shutil.which("devcontainer")
SHARED_VOLUME = "harness-agent-claude-config"
CAPABILITIES = {"NET_ADMIN": 12, "NET_RAW": 13, "SYS_ADMIN": 21}   # linux/capability.h
DEFAULT_HOSTS = ["api.anthropic.com", "api.github.com", "codeload.github.com", "github.com",
                 "objects.githubusercontent.com", "statsig.anthropic.com"]
DEFAULT_ALLOWLIST_HASH = "sha256:0e8bb6fbde0f567902ea181ebaaabe69c10a830267e395f64a2c4d0e649d5f41"
BLOCKED = "https://example.com"
ALLOWED = "https://api.github.com/zen"

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


def stop_input(agent, report):
    return json.dumps({"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                       "last_assistant_message": "Done.\n\n```json\n%s\n```" % json.dumps(report)})


def docker(*args):
    return subprocess.run(("docker",) + args, capture_output=True, text=True)


@unittest.skipUnless(os.environ.get("HARNESS_E2E") == "1" and shutil.which("docker") and DEVCONTAINER,
                     "real container: set HARNESS_E2E=1 (needs docker running and the devcontainer CLI)")
class Sandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="sandbox-e2e-")
        cls.addClassCleanup(temp.cleanup)
        cls.project = Path(temp.name).resolve() / ("p%s" % cls.__name__.lower())
        cls.project.mkdir()
        cls.config = cls.project / ".devcontainer/harness-agent/devcontainer.json"
        cls.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test",
                       GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                       GIT_COMMITTER_EMAIL="test@example.com", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true",
                       HARNESS_REVIEW="off", HARNESS_DELIVER="off", PYTHONDONTWRITEBYTECODE="1",
                       CLAUDE_PROJECT_DIR=str(cls.project))
        for key in ("HARNESS_ROOT", "HARNESS_AUTONOMY", "HARNESS_PROFILE", "HARNESS_ROLE", "HARNESS_SANDBOX_BACKEND",
                    "HARNESS_SANDBOX_IMAGE", "HARNESS_EGRESS_ALLOWLIST", "CLAUDE_CODE_OAUTH_TOKEN",
                    "ANTHROPIC_API_KEY"):
            cls.env.pop(key, None)
        cls.host("git", "init", "-q", "-b", "main")
        cls.host(str(ROOT / "bootstrap.sh"), str(cls.project), "--name", "sandbox")
        cls.host("git", "add", "-A")
        cls.host("git", "commit", "-qm", "chore: adopt agentic harness")
        cls.addClassCleanup(cls.remove_sandbox)
        up = cls.host(DEVCONTAINER, "up", "--workspace-folder", str(cls.project), "--config", str(cls.config),
                      timeout=1800)
        cls.container = json.loads(up.stdout.strip().splitlines()[-1])["containerId"]

    @classmethod
    def host(cls, *args, input=None, timeout=300):
        result = subprocess.run(args, cwd=cls.project, env=cls.env, input=input, capture_output=True, text=True,
                                timeout=timeout)
        if result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    @classmethod
    def remove_sandbox(cls):
        """Everything this class's `devcontainer up` created: its containers, their images and the project's volumes,
        never the shared one."""
        found = docker("ps", "-aq", "--filter", "label=devcontainer.local_folder=%s" % cls.project).stdout.split()
        projects = {docker("inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}', c).stdout.strip()
                    for c in found} - {"", "<no value>"}
        for name in projects:
            found += docker("ps", "-aq", "--filter", "label=com.docker.compose.project=%s" % name).stdout.split()
        images = {docker("inspect", "-f", "{{.Image}}", c).stdout.strip() for c in set(found)} - {""}
        if found:
            docker("rm", "-f", *set(found))
        for image in images:
            docker("rmi", "-f", image)
        for name in projects:
            volumes = docker("volume", "ls", "-q", "--filter", "label=com.docker.compose.project=%s" % name)
            for volume in set(volumes.stdout.split()) - {SHARED_VOLUME}:
                docker("volume", "rm", volume)

    def inside(self, script, input=None):
        """script run by bash in the agent's container, as the agent, in /workspace."""
        return subprocess.run([DEVCONTAINER, "exec", "--workspace-folder", str(self.project), "--config",
                               str(self.config), "bash", "-c", script], cwd=self.project, env=self.env, input=input,
                              capture_output=True, text=True, timeout=300)

    def reachable(self, url):
        return self.inside("curl -sS -o /dev/null --max-time 8 %s" % url).returncode == 0

    def published_hosts(self):
        listed = self.inside('cat "$HARNESS_EGRESS_ALLOWLIST"')
        return sorted(listed.stdout.split()) if listed.returncode == 0 else None


class Allowlist(Sandbox):
    def test_a_host_off_the_allowlist_is_unreachable(self):
        self.assertFalse(self.reachable(BLOCKED))

    def test_an_allowlisted_host_is_reachable(self):
        self.assertTrue(self.reachable(ALLOWED))

    def test_the_agent_container_holds_no_network_admin_capability(self):
        status = self.inside("grep '^CapBnd:' /proc/self/status")
        bounding = int(status.stdout.split()[1], 16)

        for name, bit in CAPABILITIES.items():
            with self.subTest(capability=name):
                self.assertFalse(bounding >> bit & 1, "CAP_%s is in the agent's bounding set" % name)

    def test_the_agent_process_runs_with_no_new_privileges_and_no_network_or_system_capability(self):
        status = self.inside("cat /proc/self/status").stdout
        fields = {key.strip(): value.strip() for key, value in
                  (line.split(":", 1) for line in status.splitlines() if ":" in line)}
        effective = int(fields["CapEff"], 16)

        self.assertEqual(fields["NoNewPrivs"], "1")
        for name, bit in CAPABILITIES.items():
            with self.subTest(capability=name):
                self.assertFalse(effective >> bit & 1, "CAP_%s is in the agent's effective set" % name)
        self.assertEqual(self.inside("test -e /.dockerenv && echo yes").stdout.strip(), "yes")

    def test_a_judge_pass_inside_records_the_sandbox_and_the_receipt_on_the_host_shows_it(self):
        (self.project / "backbone/specs").mkdir(parents=True, exist_ok=True)
        spec = self.project / "backbone/specs/7.1.md"
        spec.write_text(SPEC)
        tasks = self.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n")
        self.host("git", "add", "-A")
        self.host("git", "commit", "-qm", "docs: spec for task 7.1")
        harness = ("python3", "-B", str(self.project / "scripts/harness/lib/harness.py"))
        self.host(*harness, "hook", "grill-stop",
                  input=stop_input("griller", {"verdict": "pass", "task": "7.1", "questions": [], "summary": "s"}))
        spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 7.1", "- [WIP] **Task 7.1"))
        (self.project / "src").mkdir(exist_ok=True)
        (self.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (self.project / "tests").mkdir(exist_ok=True)
        (self.project / "tests/test_search.py").write_text("def test_contains():  # AC-7.1-1\n    assert True\n")
        pinned = re.search(r"(?m)^ARG HARNESS_SANDBOX_IMAGE=\S+@(sha256:[0-9a-f]{64})$",
                           (self.project / ".devcontainer/harness-agent/Dockerfile").read_text())

        judged = self.inside("CLAUDE_PROJECT_DIR=/workspace HARNESS_TEST_CMD=true "
                             "python3 -B scripts/harness/lib/harness.py hook judge-stop",
                             input=stop_input("judge", JUDGE_PASS))
        receipt = json.loads(self.host(*harness, "receipt", "7.1", "--json").stdout)

        self.assertEqual(judged.returncode, 0, judged.stdout + judged.stderr)
        self.assertTrue(pinned, "the Dockerfile pins its base image by digest")
        self.assertEqual({key: receipt["sandbox"][key] for key in ("backend", "isolation_class", "base_image_digest",
                                                                   "allowlist_hash", "region", "control_plane",
                                                                   "credential_mode")}, {
            "backend": "devcontainer", "isolation_class": "container", "base_image_digest": pinned.group(1),
            "allowlist_hash": DEFAULT_ALLOWLIST_HASH, "region": "local", "control_plane": "local",
            "credential_mode": "login"})
        self.assertIn("in a container", receipt["sandbox"]["isolation_reason"])


class Tamper(Sandbox):
    def test_nothing_the_agent_runs_changes_the_rules_in_force_or_the_published_allowlist(self):
        self.inside('HARNESS_FIREWALL_ALLOW="example.com" sudo -n /usr/local/bin/init-firewall.sh; '
                    "sudo -n iptables -P OUTPUT ACCEPT; iptables -P OUTPUT ACCEPT; ip6tables -P OUTPUT ACCEPT; "
                    'echo example.com >> "$HARNESS_EGRESS_ALLOWLIST"; true')

        self.assertFalse(self.reachable(BLOCKED))
        self.assertTrue(self.reachable(ALLOWED))
        self.assertEqual(self.published_hosts(), DEFAULT_HOSTS)


if __name__ == "__main__":
    unittest.main()
