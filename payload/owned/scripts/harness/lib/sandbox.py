"""Agentic harness (harness-owned): sandbox backends and sandbox evidence (ADR-003 in the harness repository).

A backend is where harness.py run starts its agent sessions, and the evidence is what a judge verdict records about
the sandbox it ran in. The engine stays standard-library only: a backend for a hosted sandbox talks to it through its
CLI or its REST API, never through a vendor SDK.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

EVIDENCE_FIELDS = ("backend", "isolation_class", "base_image_digest", "allowlist_hash", "region", "control_plane",
                   "credential_mode")
ISOLATION_CLASSES = ("none", "container", "userspace-kernel", "microVM", "dedicated-VM")
CREDENTIAL_VARIABLES = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
PINNED = re.compile(r"@(sha256:[0-9a-f]{64})$")
NOT_ISOLATED = {"isolation_class": "none", "base_image_digest": "none", "allowlist_hash": "none", "region": "local",
                "control_plane": "none", "credential_mode": "host", "egress_denials": None}
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")
PROC_STATUS = "/proc/self/status"
# linux/capability.h. The agent's container drops NET_ADMIN and NET_RAW and has no sudo.
CAPABILITY_BITS = {"NET_ADMIN": 12, "NET_RAW": 13, "SYS_ADMIN": 21}
# devcontainer.json is JSON with comments and trailing commas. A string's contents are never read as either.
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)
JSONC_COMMA = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')
# The egress container's published list, in the agent's container (docker-compose.yml). Only this path counts.
ALLOWLIST_PATH = "/run/harness-egress/allowlist"
# What the egress container denied (egress.py), on the same read-only volume.
DENIALS_PATH = "/run/harness-egress/denials.jsonl"
DENIALS_CITED = 10
# The sandbox a project carries, relative to its root; HARNESS_SANDBOX_START brings it up with the devcontainer CLI.
DEVCONTAINER_CONFIG = ".devcontainer/harness-agent/devcontainer.json"
# A build on a cold cache installs the agent CLI; a session's own timeout is enforced inside the container too.
UP_SECONDS = 1800
EXEC_GRACE_SECONDS = 60


class SandboxError(Exception):
    """The sandbox can't be used, and no session may run."""


class Sandbox(object):
    """One sandbox: the workspace its sessions run in, as the sandbox sees it. A sandbox the backend brought up has
    its container, the workspace inside it and the agent command it defines."""

    def __init__(self, workspace, container=None, remote_workspace=None, agent_command=None):
        self.workspace = Path(workspace)
        self.container, self.remote_workspace, self.agent_command = container, remote_workspace, agent_command


class SandboxBackend(object):
    """What every backend provides. `name` is the HARNESS_SANDBOX_BACKEND value that selects it."""
    name = None

    def create(self, workspace, env=None):
        """A Sandbox for the task's workspace; env is the harness settings a check inside it gets. Raises SandboxError
        when the sandbox can't be used."""
        raise NotImplementedError

    def exec(self, sandbox, command, stdin=None, log=None, timeout=None, env=None):
        """Run a shell command in the sandbox's workspace with stdin as its input, env added to its environment and its
        output (stdout and stderr) to the log file. The exit code, or None once the timeout stopped it."""
        raise NotImplementedError

    def copy_in(self, sandbox, host_path, sandbox_path):
        raise NotImplementedError

    def copy_out(self, sandbox, sandbox_path, host_path):
        raise NotImplementedError

    def egress_policy(self):
        """The allowlisted host names in force, lower-case and sorted, or None when nothing restricts egress."""
        raise NotImplementedError

    def teardown(self, sandbox):
        """Destroy the sandbox; the runner calls it after every session, a timed-out one too."""
        raise NotImplementedError

    def identity(self):
        """The sandbox evidence: one value per EVIDENCE_FIELDS name, isolation_reason, and egress_denials (a summary of
        what the sandbox's egress control denied, or None when nothing logged it)."""
        raise NotImplementedError


class Devcontainer(SandboxBackend):
    """The local .devcontainer/harness-agent/ sandbox. By default sessions run where the runner runs: inside the
    container when the user started it there, otherwise on the host, and this backend starts and destroys nothing.
    With start (HARNESS_SANDBOX_START=on) a runner on the host brings the project's sandbox up with the devcontainer
    CLI, has the harness inside check it (harness: its command there) and runs each session in it, with the agent
    command the sandbox defines, then stops the containers it started. HARNESS_SANDBOX_IMAGE is set by the image's
    environment, which a host can set too, so the container is claimed only when the process shows the container's
    restrictions and the egress container's list (isolation)."""
    name = "devcontainer"

    def __init__(self, start=False, harness=None, reference=None):
        self.start, self.harness, self.reference = start, harness, reference
        self.compose_project = None

    def starts_sandbox(self):
        return self.start and isolation()[0] != "container"

    def create(self, workspace, env=None):
        if not self.starts_sandbox():
            return Sandbox(workspace)
        problem = start_problem(workspace, self.reference)
        if problem:
            raise SandboxError(problem)
        running = self.containers(workspace, running=True)
        try:
            up = subprocess.run(self.cli(workspace, "up"), capture_output=True, text=True, timeout=UP_SECONDS)
        except subprocess.TimeoutExpired:
            raise SandboxError("devcontainer up did not finish in %d seconds" % UP_SECONDS)
        result = last_json(up.stdout)
        if up.returncode != 0 or result.get("outcome") != "success":
            raise SandboxError("devcontainer up failed: %s" % (result.get("message") or up.stderr.strip()[-600:]
                                                                or "exit %d" % up.returncode))
        if not running:
            self.compose_project = result.get("composeProjectName")
        box = Sandbox(workspace, result.get("containerId"), result.get("remoteWorkspaceFolder") or "/workspace")
        isolated, reason = self.probe(box)
        if isolated != "container":
            self.teardown(box)
            raise SandboxError("the sandbox devcontainer up brought up doesn't isolate its sessions: isolation_class %s "
                               "(%s)" % (isolated, reason))
        checked = self.inside(box, "%s doctor" % self.harness, env)
        if checked.returncode != 0:
            self.teardown(box)
            raise SandboxError("the harness inside the sandbox refuses it:\n%s" % checked.stdout.strip()[-1500:])
        box.agent_command = self.inside(box, 'printf %s "$HARNESS_AGENT_CMD"').stdout.strip()
        if not box.agent_command:
            self.teardown(box)
            raise SandboxError("the sandbox sets no HARNESS_AGENT_CMD (the agent service in docker-compose.yml)")
        return box

    def exec(self, sandbox, command, stdin=None, log=None, timeout=None, env=None):
        if sandbox.container is None:
            try:
                return subprocess.run(command, shell=True, cwd=str(sandbox.workspace), input=stdin, stdout=log,
                                      stderr=subprocess.STDOUT, text=True, timeout=timeout,
                                      env=dict(os.environ, **(env or {}))).returncode
            except subprocess.TimeoutExpired:
                return None
        # Stopping `devcontainer exec` on the host would leave the session running inside, so the timeout is enforced
        # there; the host's own limit is only a backstop.
        bounded = ["timeout", "-k", "10", str(timeout), "sh", "-c", command] if timeout else ["sh", "-c", command]
        started = time.time()
        try:
            code = subprocess.run(self.in_workspace(sandbox, bounded, env), input=stdin, stdout=log,
                                  stderr=subprocess.STDOUT, text=True,
                                  timeout=timeout + EXEC_GRACE_SECONDS if timeout else None).returncode
        except subprocess.TimeoutExpired:
            return None
        if timeout and code in (124, 137) and time.time() - started >= timeout:
            return None
        return code

    def cli(self, workspace, command):
        return ["devcontainer", command, "--workspace-folder", str(workspace),
                "--config", str(Path(workspace) / DEVCONTAINER_CONFIG)]

    def in_workspace(self, sandbox, argv, env=None):
        remote_env = [arg for key, value in sorted((env or {}).items())
                      for arg in ("--remote-env", "%s=%s" % (key, value))]
        return (self.cli(sandbox.workspace, "exec") + remote_env +
                ["sh", "-c", 'cd "$1" && shift && exec "$@"', "sh", sandbox.remote_workspace] + argv)

    def inside(self, sandbox, script, env=None):
        return subprocess.run(self.in_workspace(sandbox, ["sh", "-c", script], env), capture_output=True, text=True,
                              timeout=600)

    def probe(self, sandbox):
        """(isolation_class, reason) of a process in the sandbox, worked out by this module's own code, not by the
        harness inside, which the workspace holds."""
        source = Path(__file__).read_text(encoding="utf-8") + "\nprint(json.dumps(isolation()))\n"
        try:
            found = subprocess.run(self.in_workspace(sandbox, ["python3", "-B", "-"]), input=source,
                                   capture_output=True, text=True, timeout=120)
            return tuple(last_json_value(found.stdout))
        except (subprocess.TimeoutExpired, TypeError, ValueError):
            return "unknown", "the isolation check didn't answer"

    def containers(self, workspace, running=False):
        """The ids of the agent's container docker knows for the workspace."""
        found = subprocess.run(["docker", "ps", "-q"] + ([] if running else ["-a"]) +
                               ["--filter", "label=devcontainer.local_folder=%s" % workspace],
                               capture_output=True, text=True)
        return found.stdout.split()

    def copy_in(self, sandbox, host_path, sandbox_path):
        shutil.copy2(str(host_path), str(sandbox_path))

    def copy_out(self, sandbox, sandbox_path, host_path):
        shutil.copy2(str(sandbox_path), str(host_path))

    def egress_policy(self):
        if isolation()[0] != "container":
            return None
        return published_hosts(ALLOWLIST_PATH)

    def teardown(self, sandbox):
        """Stops the containers this backend started, which ends whatever a session left running; a sandbox that was
        already up stays as it was."""
        if sandbox.container is None or not self.compose_project:
            return
        project = subprocess.run(["docker", "ps", "-q", "--filter",
                                  "label=com.docker.compose.project=%s" % self.compose_project],
                                 capture_output=True, text=True).stdout.split()
        if project:
            subprocess.run(["docker", "stop"] + project, capture_output=True, text=True)

    def identity(self):
        isolation_class, reason = isolation()
        if isolation_class != "container":
            return dict(NOT_ISOLATED, backend=self.name, isolation_reason=reason)
        pinned = PINNED.search(os.environ["HARNESS_SANDBOX_IMAGE"])
        hosts = self.egress_policy()
        return {"backend": self.name, "isolation_class": isolation_class,
                "base_image_digest": pinned.group(1) if pinned else "unpinned",
                "allowlist_hash": allowlist_hash(hosts) if hosts is not None else "none",
                "region": "local", "control_plane": "local",
                "credential_mode": "env" if any(os.environ.get(v) for v in CREDENTIAL_VARIABLES) else "login",
                "isolation_reason": reason, "egress_denials": egress_denials(DENIALS_PATH)}


BACKENDS = {Devcontainer.name: Devcontainer}


def isolation():
    """(isolation_class, reason): the boundary this process runs behind. Only a Linux process in a container, with the
    restrictions the agent's container is started with (no-new-privileges, no network or system capabilities), and
    with the egress container's allowlist published at ALLOWLIST_PATH, is a container. Anything else is none, and the
    reason says which check failed."""
    if not os.environ.get("HARNESS_SANDBOX_IMAGE"):
        return "none", "not in the harness-agent image (HARNESS_SANDBOX_IMAGE is unset)"
    unverified = "HARNESS_SANDBOX_IMAGE is set, but "
    if sys.platform != "linux":
        return "none", unverified + "this is not Linux, so no container boundary can be checked"
    if not any(os.path.exists(marker) for marker in CONTAINER_MARKERS):
        return "none", unverified + "this process is not in a container (no /.dockerenv or /run/.containerenv)"
    fields = proc_status()
    if fields is None or "CapEff" not in fields or "CapBnd" not in fields:
        return "none", unverified + "CapEff and CapBnd can't be read from /proc/self/status"
    if fields.get("NoNewPrivs") != "1":
        return "none", unverified + "NoNewPrivs is not set, so the process could gain privileges"
    # CapEff is empty for a non-root user even when a capability was added, so the bounding set counts too.
    reachable = int(fields["CapEff"], 16) | int(fields["CapBnd"], 16)
    held = sorted(name for name, bit in CAPABILITY_BITS.items() if reachable >> bit & 1)
    if held:
        return "none", unverified + "the process has %s in its effective or bounding set, which the agent's container " \
            "must drop" % ", ".join(held)
    if os.environ.get("HARNESS_EGRESS_ALLOWLIST") != ALLOWLIST_PATH:
        return "none", unverified + "HARNESS_EGRESS_ALLOWLIST is not %s, so no egress container is known to limit " \
            "this process" % ALLOWLIST_PATH
    if published_hosts(ALLOWLIST_PATH) is None:
        return "none", unverified + "%s can't be read, so no egress container is known to limit this process" \
            % ALLOWLIST_PATH
    return "container", "in a container with NoNewPrivs set, no NET_ADMIN, NET_RAW or SYS_ADMIN, and the egress " \
        "allowlist published at %s" % ALLOWLIST_PATH


def proc_status():
    try:
        text = Path(PROC_STATUS).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    pairs = (line.split(":", 1) for line in text.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def published_hosts(path):
    """The host names in an egress allowlist file, lower-case and sorted, or None when it can't be read or is empty."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return sorted({line.strip().lower() for line in text.splitlines() if line.strip()}) or None


def egress_denials(path):
    """A summary of the egress container's denial log: since when it logs, how many packets it denied, the targets
    denied most, and the log's sha256, so the receipt can cite it. None when there is no log to read."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    started, truncated, counts = None, False, {}
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        started = started or record.get("started")
        truncated = truncated or record.get("truncated") is True
        if isinstance(record.get("kind"), str) and isinstance(record.get("target"), str):
            key = (record["kind"], record["target"])
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:DENIALS_CITED]
    return {"log": str(path), "log_sha256": "sha256:" + hashlib.sha256(data).hexdigest(), "since": started,
            "count": sum(counts.values()), "truncated": truncated,
            "top": [{"kind": kind, "target": target, "count": count} for (kind, target), count in ranked]}


def start_problem(workspace, reference=None):
    """Why a runner here can't bring the workspace's sandbox up (HARNESS_SANDBOX_START=on), or None. reference: the
    engine's own copy of the definition, when an agent in the sandbox can't write it."""
    if isolation()[0] == "container":
        return None
    if not (Path(workspace) / DEVCONTAINER_CONFIG).is_file():
        return ("HARNESS_SANDBOX_START is on, but %s is missing, so run has no sandbox to bring up (update.sh or pin "
                "installs it)" % DEVCONTAINER_CONFIG)
    missing = [tool for tool in ("devcontainer", "docker") if not shutil.which(tool)]
    if missing:
        return ("HARNESS_SANDBOX_START is on, but %s isn't on the PATH, so run can't bring the sandbox up (the "
                "devcontainer CLI: npm install -g @devcontainers/cli; docker: Docker Desktop, OrbStack or Docker "
                "Engine)" % " and ".join(missing))
    folder = Path(workspace) / DEVCONTAINER_CONFIG.rsplit("/", 1)[0]
    digest = definition_digest(folder)
    if reference is not None and definition_digest(reference) == digest:
        return None
    if approved_definitions().get(os.path.realpath(str(workspace))) == digest:
        return None
    return ("HARNESS_SANDBOX_START is on, but this machine doesn't trust the sandbox's definition (%s/, %s): it isn't "
            "the harness's own copy, and you haven't approved it. devcontainer up runs parts of it on this host, and an "
            "agent in the sandbox can write the workspace, so run brings up only a definition you approved. Review the "
            "folder, then run harness.py sandbox-approve in your own terminal"
            % (DEVCONTAINER_CONFIG.rsplit("/", 1)[0], digest))


def definition_files(folder):
    """[(path relative to folder, sha256 of its content or of a symlink's target)] for every file in the sandbox's
    folder, sorted."""
    found = []
    for path in sorted(Path(folder).rglob("*")):
        if path.is_symlink():
            found.append((path.relative_to(folder).as_posix(),
                          "symlink:" + hashlib.sha256(os.readlink(str(path)).encode("utf-8")).hexdigest()))
        elif path.is_file():
            found.append((path.relative_to(folder).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return found


def definition_digest(folder):
    """sha256 over the sandbox's folder: every file's path and content, so an added, changed or removed file changes
    it."""
    listing = "".join("%s %s\n" % (digest, name) for name, digest in definition_files(folder))
    return "sha256:" + hashlib.sha256(listing.encode("utf-8")).hexdigest()


def definition_differences(folder, reference):
    """The files of folder that are missing from reference or differ from it, and reference's files folder lacks."""
    ours, theirs = dict(definition_files(folder)), dict(definition_files(reference))
    return sorted(name for name in set(ours) | set(theirs) if ours.get(name) != theirs.get(name))


def approvals_file():
    """Where this machine's user records the sandbox definitions they approved: outside every project, so no agent in a
    sandbox can reach it."""
    return Path(os.path.expanduser("~/.agentic-harness/sandbox-approvals.json"))


def approved_definitions():
    try:
        data = json.loads(approvals_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    projects = data.get("projects") if isinstance(data, dict) else None
    return projects if isinstance(projects, dict) else {}


def approve_definition(workspace, digest):
    projects = approved_definitions()
    projects[os.path.realpath(str(workspace))] = digest
    approvals_file().parent.mkdir(parents=True, exist_ok=True)
    approvals_file().write_text(json.dumps({"projects": projects}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def last_json(text):
    """The JSON object on the last line of text that holds one, or {}."""
    value = last_json_value(text, dict)
    return value if value is not None else {}


def last_json_value(text, kind=list):
    """The JSON value of kind on the last line of text that holds one, or None."""
    for line in reversed(text.strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, kind):
            return value
    return None


def unpublished_allowlist():
    """Why the harness-agent image has no readable egress allowlist at ALLOWLIST_PATH, or None. The image is the one the
    Dockerfile builds when HARNESS_SANDBOX_IMAGE is set, and then the egress container must have published the list."""
    if not os.environ.get("HARNESS_SANDBOX_IMAGE"):
        return None
    if os.environ.get("HARNESS_EGRESS_ALLOWLIST") == ALLOWLIST_PATH and published_hosts(ALLOWLIST_PATH) is not None:
        return None
    return ("HARNESS_SANDBOX_IMAGE is set (the harness-agent image), but the egress allowlist isn't published at %s with "
            "HARNESS_EGRESS_ALLOWLIST naming it, so the egress container isn't limiting this sandbox's network. Start the "
            "sandbox from .devcontainer/harness-agent/ (docker-compose.yml), or unset HARNESS_SANDBOX_IMAGE (ADR-003)"
            % ALLOWLIST_PATH)


def jsonc_loads(text):
    """The JSON value of devcontainer.json's text. Raises ValueError when it isn't one."""
    without_comments = JSONC_TOKEN.sub(lambda m: m.group(0) if m.group(0)[0] == '"' else "", text)
    return json.loads(JSONC_COMMA.sub(lambda m: m.group(0) if m.group(0)[0] == '"' else "", without_comments))


def allowlist_hash(hosts):
    """sha256 over the host names, one per line: the same policy gives the same hash, whoever wrote the list."""
    return "sha256:" + hashlib.sha256("".join(host + "\n" for host in hosts).encode("utf-8")).hexdigest()


def normalized(recorded):
    """A recorded sandbox with the base image digest under its current name: a judge pass recorded before the rename
    says image_digest."""
    if not recorded or "image_digest" not in recorded or "base_image_digest" in recorded:
        return recorded
    renamed = dict(recorded)
    renamed["base_image_digest"] = renamed.pop("image_digest")
    return renamed


def required_isolation(setting, change_class, ladder):
    """(the isolation class work of change_class needs, None) under HARNESS_SANDBOX_REQUIRE, or (None, why the setting
    can't be read). The setting is space-separated <class>=<isolation class> pairs; a pair holds for its class and every
    class above it on the ladder, so work never needs less isolation than the work below it."""
    named = {}
    known = {name.lower(): name for name in ISOLATION_CLASSES}
    for entry in setting.split():
        cls, sep, level = entry.lower().partition("=")
        if not sep or cls not in ladder or level not in known:
            return None, ("'%s' is not <class>=<isolation class>, with a class among %s and an isolation class among %s"
                          % (entry, ", ".join(ladder), ", ".join(ISOLATION_CLASSES)))
        if cls in named:
            return None, "%s is named twice" % cls
        named[cls] = known[level]
    reach = ladder[:ladder.index(change_class) + 1]
    return max((named.get(cls, "none") for cls in reach), key=ISOLATION_CLASSES.index), None


def shortfall(evidence, required):
    """Why the sandbox evidence doesn't reach the required isolation class, or None. Missing evidence, and a class this
    harness doesn't know, reach nothing above none."""
    if required == "none":
        return None
    if not evidence:
        return "recorded no sandbox (the judge pass predates sandbox evidence)"
    recorded = evidence.get("isolation_class")
    if recorded not in ISOLATION_CLASSES:
        return "has isolation_class %s, which this harness doesn't know" % recorded
    if ISOLATION_CLASSES.index(recorded) >= ISOLATION_CLASSES.index(required):
        return None
    reason = evidence.get("isolation_reason")
    return "has isolation_class %s%s" % (recorded, " (%s)" % reason if reason else "")


def problem(name):
    """Why HARNESS_SANDBOX_BACKEND can't be used, or None."""
    if name in BACKENDS:
        return None
    return ("HARNESS_SANDBOX_BACKEND is %s, but this harness has only these sandbox backends: %s (ADR-003)"
            % (name or "empty", ", ".join(sorted(BACKENDS))))


def backend(name, **options):
    return BACKENDS[name](**options)


def session_isolation(name):
    """The isolation_class and isolation_reason of the sandbox this process runs in, as the named backend sees it: what
    the gates compare, without the rest of the evidence."""
    if name not in BACKENDS:
        return {"isolation_class": "unknown", "isolation_reason": "HARNESS_SANDBOX_BACKEND %s is unknown" % name}
    isolation_class, reason = isolation()
    return {"isolation_class": isolation_class, "isolation_reason": reason}


def evidence(name):
    """The evidence for the sandbox this process runs in, as the named backend sees it."""
    if name not in BACKENDS:
        return dict({field: "unknown" for field in EVIDENCE_FIELDS}, backend=name)
    return backend(name).identity()
