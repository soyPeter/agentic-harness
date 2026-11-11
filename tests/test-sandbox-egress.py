"""The harness-agent sandbox end to end, in a real container (ADR-003). Opt-in: HARNESS_E2E=1, with docker running and
the devcontainer CLI on the PATH (npm install -g @devcontainers/cli). It builds the image, so a first run takes a few
minutes and needs the network.

Each class bootstraps a throwaway project, brings its .devcontainer/harness-agent/ up with `devcontainer up` and checks
from inside, as the agent (Restrictions needs only docker):
- a host off the allowlist can't be reached, and an allowlisted one can;
- only allowlisted names resolve, whichever resolver the agent asks, and a refused name is logged;
- the agent's container holds neither NET_ADMIN nor NET_RAW, and nothing the agent runs changes the rules in force,
  the allowlist the evidence is taken from or the egress container's log of what it denied;
- a denied connection is logged by the egress container, and the receipt cites the log;
- a judge pass recorded inside records that sandbox, and the receipt shows it on the host;
- in a thin project (ThinSandbox), the container fetches the pinned engine when it starts and Claude Code loads it as
  the plugin, so the same holds through the launcher;
- with HARNESS_SANDBOX_START=on (HostRun), run on the host brings the sandbox up itself, from a checked copy of its
  definition, runs each session in it, stops a session that times out and stops the containers afterwards; it refuses
  a definition changed after the user approved it, and a sandbox someone else already brought up.
Restrictions runs the harness-agent image directly, with the agent's restrictions and each one left out: the sandbox is
recorded as a container only with all of them and the published allowlist at /run/harness-egress/allowlist. Schema work
that needs a container (HARNESS_SANDBOX_REQUIRE=schema=container) starts and is judged there and then finishes on the
host.
The containers, images and volumes a class created are removed afterwards. The harness-agent-claude-config volume,
which every project's sandbox shares, is left alone.
"""
import hashlib
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
DEFAULT_PUBLISHED = "\n".join(DEFAULT_HOSTS) + "\n"
EGRESS_ALLOWLIST = "/run/harness-egress/allowlist"
EGRESS_DENIALS = "/run/harness-egress/denials.jsonl"
UNROUTABLE = "192.0.2.1"   # TEST-NET-1: no DNS involved, and nothing answers there anyway
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


SCHEMA_SPEC = SPEC.replace("7.1", "7.2").replace("PRD: none\n", "PRD: none\nChange-Class: schema\n")
SCHEMA_JUDGE_PASS = dict(JUDGE_PASS, task="7.2", criteria=[{"id": "AC-7.2-1", "met": True, "evidence": "src/search.py:2",
                                                             "tests": ["test_contains"]}])


def stop_input(agent, report):
    return json.dumps({"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                       "last_assistant_message": "Done.\n\n```json\n%s\n```" % json.dumps(report)})


def docker(*args, input=None):
    return subprocess.run(("docker",) + args, capture_output=True, text=True, input=input)


@unittest.skipUnless(os.environ.get("HARNESS_E2E") == "1" and shutil.which("docker") and DEVCONTAINER,
                     "real container: set HARNESS_E2E=1 (needs docker running and the devcontainer CLI)")
class Sandbox(unittest.TestCase):
    UP = True   # brought up before the tests, as a user does

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
        cls.install()
        cls.addClassCleanup(cls.remove_sandbox)
        if cls.UP:
            cls.up()

    @classmethod
    def up(cls):
        up = cls.host(DEVCONTAINER, "up", "--workspace-folder", str(cls.project), "--config", str(cls.config),
                      timeout=1800)
        cls.container = json.loads(up.stdout.strip().splitlines()[-1])["containerId"]

    @classmethod
    def install(cls):
        cls.host(str(ROOT / "bootstrap.sh"), str(cls.project), "--name", "sandbox")
        cls.host("git", "add", "-A")
        cls.host("git", "commit", "-qm", "chore: adopt agentic harness")

    @classmethod
    def host(cls, *args, input=None, timeout=300, env=None):
        result = subprocess.run(args, cwd=cls.project, env=env or cls.env, input=input, capture_output=True, text=True,
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

    def resolves(self, name, *dig):
        """Whether name gets an address in the agent's container: through its resolver, or with dig and its options."""
        if not dig:
            return self.inside("getent hosts %s" % name).returncode == 0
        answer = self.inside("dig +short +time=3 +tries=1 %s %s" % (" ".join(dig), name)).stdout
        return bool(re.search(r"(?m)^\d+\.\d+\.\d+\.\d+$", answer))

    def denials(self):
        """The records of the egress container's denial log, as the agent reads them."""
        log = self.inside("cat %s" % EGRESS_DENIALS)
        self.assertEqual(log.returncode, 0, log.stderr)
        return [json.loads(line) for line in log.stdout.splitlines() if line.strip()]


class Allowlist(Sandbox):
    def test_a_host_off_the_allowlist_is_unreachable(self):
        self.assertFalse(self.reachable(BLOCKED))

    def test_an_allowlisted_host_is_reachable(self):
        self.assertTrue(self.reachable(ALLOWED))

    def test_an_allowlisted_name_resolves(self):
        self.assertTrue(self.resolves("api.github.com"))

    def test_a_name_off_the_allowlist_does_not_resolve_and_the_egress_container_logs_it(self):
        self.assertFalse(self.resolves("example.com"))

        self.assertIn({"kind": "dns", "target": "example.com"},
                      [{key: record.get(key) for key in ("kind", "target")} for record in self.denials()])

    def test_no_other_resolver_answers_the_agent(self):
        for resolver in (("@8.8.8.8",), ("@8.8.8.8", "+tcp"), ("@1.1.1.1",)):
            with self.subTest(resolver=resolver):
                self.assertFalse(self.resolves("example.com", *resolver))
        ports = self.inside("python3 -c \"import sys; print(' '.join(str(int(line.split()[1].split(':')[1], 16)) for "
                            "name in ('/proc/net/udp', '/proc/net/tcp') for line in open(name).read().splitlines()[1:] "
                            "if line.split()[1].startswith('0B00007F:')))\"").stdout.split()
        self.assertTrue(ports, "Docker's resolver listens on 127.0.0.11 in the shared network namespace")
        for port in ports:
            with self.subTest(dockers_resolver_port=port):
                self.assertFalse(self.resolves("example.com", "@127.0.0.11", "-p", port))
                self.assertFalse(self.resolves("example.com", "@127.0.0.11", "-p", port, "+tcp"))

    def test_the_egress_container_logs_a_denied_connection_with_the_agents_uid(self):
        self.assertFalse(self.reachable("http://%s/" % UNROUTABLE))
        uid = int(self.inside("id -u").stdout)

        records = [{key: record.get(key) for key in ("kind", "target", "uid")} for record in self.denials()]

        self.assertIn({"kind": "connect", "target": "%s:80/tcp" % UNROUTABLE, "uid": uid}, records)
        self.assertIn("started", self.denials()[0])

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

        self.assertFalse(self.reachable("https://%s/" % UNROUTABLE))

        judged = self.inside("CLAUDE_PROJECT_DIR=/workspace HARNESS_TEST_CMD=true "
                             "python3 -B scripts/harness/lib/harness.py hook judge-stop",
                             input=stop_input("judge", JUDGE_PASS))
        receipt = json.loads(self.host(*harness, "receipt", "7.1", "--json").stdout)
        text = self.host(*harness, "receipt", "7.1").stdout

        self.assertEqual(judged.returncode, 0, judged.stdout + judged.stderr)
        self.assertTrue(pinned, "the Dockerfile pins its base image by digest")
        self.assertEqual({key: receipt["sandbox"][key] for key in ("backend", "isolation_class", "base_image_digest",
                                                                   "allowlist_hash", "region", "control_plane",
                                                                   "credential_mode")}, {
            "backend": "devcontainer", "isolation_class": "container", "base_image_digest": pinned.group(1),
            "allowlist_hash": DEFAULT_ALLOWLIST_HASH, "region": "local", "control_plane": "local",
            "credential_mode": "login"})
        self.assertIn("in a container", receipt["sandbox"]["isolation_reason"])
        denials = receipt["sandbox"]["egress_denials"]
        self.assertGreaterEqual(denials["count"], 1)
        self.assertIn({"kind": "connect", "target": "%s:443/tcp" % UNROUTABLE},
                      [{key: entry[key] for key in ("kind", "target")} for entry in denials["top"]])
        self.assertIn("logged in %s" % EGRESS_DENIALS, text)


@unittest.skipUnless(os.environ.get("HARNESS_E2E") == "1" and shutil.which("docker"),
                     "real containers: set HARNESS_E2E=1 (needs docker running)")
class Restrictions(unittest.TestCase):
    """What a container must show to be recorded as `container` (ADR-003): the harness-agent image run with the
    restrictions the agent's container has, and with each one missing. The judge pass is recorded inside the container,
    by the harness's own hook, and the receipt on the host shows what was recorded."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="sandbox-restrictions-")
        cls.addClassCleanup(temp.cleanup)
        cls.work = Path(temp.name).resolve()
        cls.project = cls.work / "project"
        cls.project.mkdir()
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
        (cls.project / "backbone/specs").mkdir(parents=True, exist_ok=True)
        (cls.project / "backbone/specs/7.1.md").write_text(SPEC)
        (cls.project / "backbone/specs/7.2.md").write_text(SCHEMA_SPEC)
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n"
                         "- [ ] **Task 7.2: Customer table** (spec: backbone/specs/7.2.md)\n")
        cls.host("git", "add", "-A")
        cls.host("git", "commit", "-qm", "docs: specs for tasks 7.1 and 7.2")
        for task in ("7.1", "7.2"):
            cls.host("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"), "hook", "grill-stop",
                     input=stop_input("griller", {"verdict": "pass", "task": task, "questions": [], "summary": "s"}))
            spec = cls.project / ("backbone/specs/%s.md" % task)
            spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 7.1", "- [WIP] **Task 7.1"))
        (cls.project / "src").mkdir(exist_ok=True)
        (cls.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (cls.project / "tests").mkdir(exist_ok=True)
        (cls.project / "tests/test_search.py").write_text(
            "def test_contains():  # AC-7.1-1 AC-7.2-1\n    assert True\n")
        cls.image = "harness-restrictions-test:%d" % os.getpid()
        cls.addClassCleanup(docker, "rmi", "-f", cls.image)
        cls.host("docker", "build", "-q", "-t", cls.image, str(cls.project / ".devcontainer/harness-agent"),
                 timeout=1800)
        cls.egress = cls.work / "egress"
        cls.egress.mkdir()
        (cls.egress / "allowlist").write_text(DEFAULT_PUBLISHED)
        # The agent's user in the container writes the verdict into this folder, which the host's user owns.
        cls.host("chmod", "-R", "a+rwX", str(cls.project))

    @classmethod
    def host(cls, *args, input=None, timeout=300):
        result = subprocess.run(args, cwd=cls.project, env=cls.env, input=input, capture_output=True, text=True,
                                timeout=timeout)
        if result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    def run_in_container(self, flags, command, environment, input=""):
        """`docker run` of the image with the project at /workspace, with the agent's restrictions as flags."""
        env = [arg for key, value in environment.items() for arg in ("-e", "%s=%s" % (key, value))]
        return docker("run", "--rm", "-i", *flags, *env, "-e", "CLAUDE_PROJECT_DIR=/workspace",
                      "-e", "HARNESS_TEST_CMD=true", "-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory",
                      "-e", "GIT_CONFIG_VALUE_0=*", "-v", "%s:/workspace" % self.project, "-w", "/workspace",
                      self.image, "python3", "-B", "scripts/harness/lib/harness.py", *command, input=input)

    def judged_inside(self, flags, environment):
        """The sandbox a judge pass recorded inside the container with these flags, as the host's receipt shows it."""
        stop = stop_input("judge", JUDGE_PASS)
        judged = self.run_in_container(flags, ["hook", "judge-stop"], environment, input=stop)
        self.assertEqual(judged.returncode, 0, judged.stdout + judged.stderr)
        receipt = self.host("python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "receipt", "7.1",
                            "--json")
        return json.loads(receipt.stdout)["sandbox"]

    def restricted(self):
        """The flags and environment the agent's container runs with (docker-compose.yml)."""
        flags = ["--user", "agent", "--security-opt", "no-new-privileges", "--cap-drop=NET_ADMIN",
                 "--cap-drop=NET_RAW", "-v", "%s:/run/harness-egress:ro" % self.egress]
        return flags, {"HARNESS_SANDBOX_IMAGE": self.image_reference(), "HARNESS_EGRESS_ALLOWLIST": EGRESS_ALLOWLIST}

    def sandbox(self, *, drop=(), add=(), allowlist=EGRESS_ALLOWLIST, mounted=True):
        flags = ["--user", "agent", "--security-opt", "no-new-privileges"]
        flags += ["--cap-drop=%s" % cap for cap in drop] + ["--cap-add=%s" % cap for cap in add]
        if mounted:
            flags += ["-v", "%s:/run/harness-egress:ro" % self.egress]
        environment = {"HARNESS_SANDBOX_IMAGE": self.image_reference()}
        if allowlist is not None:
            environment["HARNESS_EGRESS_ALLOWLIST"] = allowlist
        return self.judged_inside(flags, environment)

    def image_reference(self):
        found = re.findall(r"(?m)^ARG HARNESS_SANDBOX_IMAGE=(\S+)$",
                           (self.project / ".devcontainer/harness-agent/Dockerfile").read_text())
        return found[0]

    def test_the_agent_as_compose_starts_it_is_a_container_with_the_published_allowlist(self):
        sandbox = self.sandbox(drop=("NET_ADMIN", "NET_RAW"))

        self.assertEqual(sandbox["isolation_class"], "container", sandbox["isolation_reason"])
        self.assertEqual(sandbox["allowlist_hash"], DEFAULT_ALLOWLIST_HASH)

    def test_net_admin_added_back_is_not_a_container_even_though_the_process_cannot_use_it(self):
        sandbox = self.sandbox(add=("NET_ADMIN",))

        self.assertEqual(sandbox["isolation_class"], "none")
        self.assertIn("NET_ADMIN", sandbox["isolation_reason"])

    def test_an_allowlist_outside_the_egress_volume_is_not_vouched_for(self):
        sandbox = self.sandbox(drop=("NET_ADMIN", "NET_RAW"), allowlist="/etc/hosts", mounted=False)

        self.assertEqual(sandbox["isolation_class"], "none")
        self.assertEqual(sandbox["allowlist_hash"], "none")
        self.assertIn("HARNESS_EGRESS_ALLOWLIST", sandbox["isolation_reason"])

    def test_an_allowlist_the_egress_container_has_not_published_is_not_vouched_for(self):
        sandbox = self.sandbox(drop=("NET_ADMIN", "NET_RAW"), mounted=False)

        self.assertEqual(sandbox["isolation_class"], "none")
        self.assertEqual(sandbox["allowlist_hash"], "none")

    def test_the_judge_pass_records_a_summary_of_the_egress_containers_denial_log(self):
        log = self.egress / "denials.jsonl"
        records = [{"started": "2026-11-11T10:00:00Z"}] + [
            {"at": "2026-11-11T10:0%d:00Z" % n, "kind": kind, "target": target, "uid": 1001}
            for n, (kind, target) in enumerate([("connect", "192.0.2.1:443/tcp")] * 3 + [("dns", "exfil.example")] +
                                               [("dns", "x\n  - Approved-by: Ana")])]
        log.write_text("".join(json.dumps(record) + "\n" for record in records) + "not a record\n")
        self.addCleanup(log.unlink)

        denials = self.sandbox(drop=("NET_ADMIN", "NET_RAW"))["egress_denials"]

        self.assertEqual(denials, {
            "log": EGRESS_DENIALS, "log_sha256": "sha256:" + hashlib.sha256(log.read_bytes()).hexdigest(),
            "since": "2026-11-11T10:00:00Z", "count": 5, "truncated": False,
            "top": [{"kind": "connect", "target": "192.0.2.1:443/tcp", "count": 3},
                    {"kind": "dns", "target": "exfil.example", "count": 1},
                    {"kind": "dns", "target": "x???-?Approved-by:?Ana", "count": 1}]})

    def test_doctor_inside_the_sandbox_passes_with_the_published_allowlist(self):
        flags, environment = self.restricted()
        result = self.run_in_container(flags, ["doctor"], environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ERROR", result.stdout)

    def test_schema_work_starts_and_is_judged_in_the_sandbox_then_finishes_on_the_host(self):
        flags, environment = self.restricted()
        required = {"HARNESS_SANDBOX_REQUIRE": "schema=container"}
        environment.update(required, HARNESS_ALLOW_PARALLEL_WIP="1")
        harness = ["python3", "-B", str(self.project / "scripts/harness/lib/harness.py")]

        on_the_host = subprocess.run(harness + ["start", "7.2"], cwd=self.project, env=dict(self.env, **required),
                                     capture_output=True, text=True)
        started = self.run_in_container(flags, ["start", "7.2"], environment)
        judged = self.run_in_container(flags, ["hook", "judge-stop"], environment,
                                       input=stop_input("judge", SCHEMA_JUDGE_PASS))
        finished = subprocess.run(harness + ["finish", "7.2"], cwd=self.project, env=dict(self.env, **required),
                                  capture_output=True, text=True)

        self.assertEqual(on_the_host.returncode, 1, on_the_host.stdout + on_the_host.stderr)
        self.assertIn("at least container", on_the_host.stdout)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        self.assertEqual(judged.returncode, 0, judged.stdout + judged.stderr)
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)


class ThinSandbox(Sandbox):
    """A thin project (ADR-001) gets the sandbox from init --thin; the release it pins is this working tree, published in
    the workspace so the container can fetch it without the network (HARNESS_ENGINE_SOURCE)."""
    LAUNCHER = "~/.agentic-harness/plugins/agentic-harness/plugin/launcher.py"

    @classmethod
    def install(cls):
        release = cls.project / ".harness-release"
        names = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout
        for name in filter(None, names.split("\0")):
            if (ROOT / name).is_file():
                (release / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(ROOT / name), str(release / name))
        cls.version = (ROOT / "VERSION").read_text().strip()
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "release"),
                     ("tag", "v" + cls.version)):
            subprocess.run(("git",) + args, cwd=release, env=cls.env, capture_output=True, check=True)
        with open(str(cls.project / ".git/info/exclude"), "a") as exclude:
            exclude.write(".harness-release/\n")
        cls.on_host = dict(cls.env, HARNESS_ENGINE_SOURCE=str(release),
                           HARNESS_ENGINES=str(cls.project.parent / "engines"))
        cls.host("python3", "-B", str(ROOT / "plugin/launcher.py"), "init", "--thin", env=cls.on_host)
        cls.host("git", "add", "-A")
        cls.host("git", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "chore: adopt agentic harness (thin)")
        cls.env["HARNESS_ENGINE_SOURCE"] = "/workspace/.harness-release"

    def test_the_container_offers_the_pinned_engine_to_claude_code_as_the_plugin(self):
        plugins = self.inside("claude plugin list")
        doctor = self.inside("python3 -B %s doctor" % self.LAUNCHER)

        self.assertEqual(plugins.returncode, 0, plugins.stdout + plugins.stderr)
        self.assertIn("agentic-harness@inline", plugins.stdout)
        self.assertIn("Version: %s" % self.version, plugins.stdout)
        self.assertIn("loaded", plugins.stdout)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertNotIn("ERROR", doctor.stdout)

    def test_a_judge_pass_inside_records_the_sandbox_and_the_receipt_on_the_host_shows_it(self):
        (self.project / "backbone/specs").mkdir(parents=True, exist_ok=True)
        spec = self.project / "backbone/specs/7.1.md"
        spec.write_text(SPEC)
        tasks = self.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n")
        self.host("git", "add", "-A")
        self.host("git", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "docs: spec for task 7.1")
        launcher = ("python3", "-B", str(ROOT / "plugin/launcher.py"))
        self.host(*launcher, "hook", "grill-stop", env=self.on_host,
                  input=stop_input("griller", {"verdict": "pass", "task": "7.1", "questions": [], "summary": "s"}))
        spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 7.1", "- [WIP] **Task 7.1"))
        (self.project / "src").mkdir(exist_ok=True)
        (self.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (self.project / "tests").mkdir(exist_ok=True)
        (self.project / "tests/test_search.py").write_text("def test_contains():  # AC-7.1-1\n    assert True\n")

        judged = self.inside("CLAUDE_PROJECT_DIR=/workspace HARNESS_TEST_CMD=true python3 -B %s hook judge-stop"
                             % self.LAUNCHER, input=stop_input("judge", JUDGE_PASS))
        receipt = json.loads(self.host(*launcher, "receipt", "7.1", "--json", env=self.on_host).stdout)

        self.assertEqual(judged.returncode, 0, judged.stdout + judged.stderr)
        self.assertEqual(receipt["sandbox"]["isolation_class"], "container", receipt["sandbox"]["isolation_reason"])
        self.assertEqual(receipt["sandbox"]["allowlist_hash"], DEFAULT_ALLOWLIST_HASH)


AGENT = """import json, os, subprocess, sys, time
prompt = sys.stdin.read()
print(open("/proc/self/status").read())
if "Task 7.2" in prompt:
    time.sleep(600)
report = %s
subprocess.run(["python3", "-B", "scripts/harness/lib/harness.py", "hook", "judge-stop"], check=True, input=json.dumps(
    {"hook_event_name": "SubagentStop", "agent_type": "judge", "stop_hook_active": False,
     "last_assistant_message": "Done.\\n\\n```json\\n%%s\\n```" %% json.dumps(report)}), text=True,
    env=dict(os.environ, CLAUDE_PROJECT_DIR="/workspace"))
""" % repr(JUDGE_PASS)


class HostRun(Sandbox):
    """HARNESS_SANDBOX_START=on (ADR-003 follow-up 5). The sandbox's agent command is a stand-in agent, so no session
    needs a model: it prints its process status and records a judge pass through the judge's hook for task 7.1, and
    for task 7.2 it outlives its timeout."""
    UP = False

    @classmethod
    def install(cls):
        super().install()
        compose = cls.project / ".devcontainer/harness-agent/docker-compose.yml"
        compose.write_text(compose.read_text().replace(
            "HARNESS_AGENT_CMD: claude -p --dangerously-skip-permissions --output-format json",
            "HARNESS_AGENT_CMD: python3 -B /workspace/agent.py"))
        (cls.project / "agent.py").write_text(AGENT)
        (cls.project / "backbone/specs").mkdir(parents=True, exist_ok=True)
        for task in ("7.1", "7.2"):
            (cls.project / ("backbone/specs/%s.md" % task)).write_text(SPEC.replace("7.1", task))
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n"
                         "- [ ] **Task 7.2: Customer list** (spec: backbone/specs/7.2.md)\n")
        cls.host("git", "add", "-A")
        cls.host("git", "commit", "-qm", "docs: specs for tasks 7.1 and 7.2")
        harness = ("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"))
        for task in ("7.1", "7.2"):
            cls.host(*harness, "hook", "grill-stop",
                     input=stop_input("griller", {"verdict": "pass", "task": task, "questions": [], "summary": "s"}))
            spec = cls.project / ("backbone/specs/%s.md" % task)
            spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task", "- [WIP] **Task"))
        (cls.project / "src").mkdir(exist_ok=True)
        (cls.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (cls.project / "tests").mkdir(exist_ok=True)
        (cls.project / "tests/test_search.py").write_text(
            "def test_contains():  # AC-7.1-1 AC-7.2-1\n    assert True\n")
        cls.host("git", "add", "-A")
        cls.host("git", "commit", "-qm", "feat: tasks 7.1 and 7.2 in progress")
        # The approval goes to a HOME of the test's own; docker keeps reading the user's configuration.
        cls.run_env = dict(cls.env, HOME=str(cls.project.parent / "home"),
                           DOCKER_CONFIG=os.environ.get("DOCKER_CONFIG") or os.path.expanduser("~/.docker"))
        cls.host("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"), "sandbox-approve",
                 env=cls.run_env)

    def run_task(self, task, **settings):
        env = dict(self.run_env, HARNESS_SANDBOX_START="on", HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block",
                   HARNESS_RUN_ATTEMPTS="1", HARNESS_ALLOW_PARALLEL_WIP="1", **settings)
        return subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "run", "--only",
                               task], cwd=self.project, env=env, capture_output=True, text=True, timeout=2400)

    def test_a_definition_changed_after_its_approval_never_reaches_the_host(self):
        config = self.project / ".devcontainer/harness-agent/devcontainer.json"
        approved = config.read_text()
        self.addCleanup(config.write_text, approved)
        escaped = self.project.parent / "escaped"
        config.write_text(approved.replace('"name"', '"initializeCommand": "touch %s",\n  "name"' % escaped, 1))

        run = self.run_task("7.1")

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("sandbox-approve", run.stdout)
        self.assertFalse(escaped.exists(), "the changed definition ran a command on the host")

    def running(self):
        return docker("ps", "-q", "--filter", "label=devcontainer.local_folder=%s" % self.project).stdout.split()

    def session_log(self, task):
        return sorted((self.project / ".git/harness/runs").glob("*/%s-1.log" % task))[-1].read_text()

    def test_a_run_brings_the_sandbox_up_runs_the_session_in_it_and_stops_it(self):
        self.assertEqual(self.running(), [], "nothing runs before the run")

        run = self.run_task("7.1")
        receipt = json.loads(self.host("python3", "-B", str(self.project / "scripts/harness/lib/harness.py"),
                                       "receipt", "7.1", "--json").stdout)

        self.assertIn("run: task 7.1 attempt 1", run.stdout, run.stdout + run.stderr)
        self.assertEqual(receipt["sandbox"]["isolation_class"], "container", receipt["sandbox"]["isolation_reason"])
        self.assertIn("NoNewPrivs:\t1", self.session_log("7.1"))
        self.assertEqual(self.running(), [], "the run stops the sandbox it started")

    def test_a_session_that_outlives_its_timeout_is_stopped_with_its_sandbox(self):
        run = self.run_task("7.2", HARNESS_RUN_TASK_TIMEOUT="5")

        self.assertIn("run: task 7.2 attempt 1", run.stdout, run.stdout + run.stderr)
        self.assertIn("exit None", run.stdout)
        self.assertEqual(self.running(), [], "the timed-out session's sandbox still runs")

    def test_run_refuses_a_sandbox_someone_else_already_brought_up(self):
        tasks = self.project / "backbone/3-TASKS.md"
        # An earlier session may have escalated the task; the user takes it back, so run has a task to start.
        tasks.write_text(re.sub(r"(?m)^(.*\*\*Task 7\.1: .*?)\s+[-\u2014]+\s+BLOCKED:.*$", r"\1", tasks.read_text()))
        self.up()
        self.addCleanup(self.stop)
        runs = self.project / ".git/harness/runs"
        before = sorted(runs.glob("*/*.log")) if runs.is_dir() else []

        run = self.run_task("7.1")

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("already up", run.stdout)
        self.assertEqual(sorted(runs.glob("*/*.log")) if runs.is_dir() else [], before, "a session ran")

    def stop(self):
        for container in self.running():
            project = docker("inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}', container)
            ids = docker("ps", "-q", "--filter", "label=com.docker.compose.project=%s" % project.stdout.strip())
            if ids.stdout.split():
                docker("stop", *ids.stdout.split())


class Tamper(Sandbox):
    def test_nothing_the_agent_runs_changes_the_rules_in_force_or_the_published_allowlist(self):
        self.inside('HARNESS_FIREWALL_ALLOW="example.com" sudo -n /usr/local/bin/init-firewall.sh; '
                    "sudo -n iptables -P OUTPUT ACCEPT; iptables -P OUTPUT ACCEPT; ip6tables -P OUTPUT ACCEPT; "
                    "iptables -t nat -F; iptables -F harness-deny; "
                    'echo example.com >> "$HARNESS_EGRESS_ALLOWLIST"; true')

        forged = self.inside('echo \'{"kind": "forged"}\' >> %s' % EGRESS_DENIALS)

        self.assertFalse(self.reachable(BLOCKED))
        self.assertTrue(self.reachable(ALLOWED))
        self.assertFalse(self.inside("getent hosts example.com").returncode == 0)
        self.assertEqual(self.published_hosts(), DEFAULT_HOSTS)
        self.assertNotEqual(forged.returncode, 0)
        self.assertNotIn("forged", [record.get("kind") for record in self.denials()])


if __name__ == "__main__":
    unittest.main()
