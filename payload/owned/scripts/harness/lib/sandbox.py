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

EVIDENCE_FIELDS = ("backend", "isolation_class", "base_image_digest", "allowlist_hash", "region", "control_plane",
                   "credential_mode")
ISOLATION_CLASSES = ("none", "container", "userspace-kernel", "microVM", "dedicated-VM")
CREDENTIAL_VARIABLES = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
PINNED = re.compile(r"@(sha256:[0-9a-f]{64})$")
NOT_ISOLATED = {"isolation_class": "none", "base_image_digest": "none", "allowlist_hash": "none", "region": "local",
                "control_plane": "none", "credential_mode": "host"}
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")
PROC_STATUS = "/proc/self/status"
# linux/capability.h. The agent's container drops NET_ADMIN and NET_RAW and has no sudo.
CAPABILITY_BITS = {"NET_ADMIN": 12, "NET_RAW": 13, "SYS_ADMIN": 21}
# devcontainer.json is JSON with comments and trailing commas. A string's contents are never read as either.
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)
JSONC_COMMA = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')
# The egress container's published list, in the agent's container (docker-compose.yml). Only this path counts.
ALLOWLIST_PATH = "/run/harness-egress/allowlist"


class Sandbox(object):
    """One sandbox: the workspace its sessions run in, as the sandbox sees it."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)


class SandboxBackend(object):
    """What every backend provides. `name` is the HARNESS_SANDBOX_BACKEND value that selects it."""
    name = None

    def create(self, workspace):
        """A Sandbox for the task's workspace."""
        raise NotImplementedError

    def exec(self, sandbox, command, stdin=None, log=None, timeout=None):
        """Run a shell command in the sandbox's workspace with stdin as its input and its output (stdout and stderr) to
        the log file. The exit code, or None once the timeout stopped it."""
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
        """The sandbox evidence: one value per EVIDENCE_FIELDS name, and isolation_reason."""
        raise NotImplementedError


class Devcontainer(SandboxBackend):
    """The local .devcontainer/harness-agent/ sandbox. The runner runs where its sessions run: inside the container when
    the user started it there, otherwise on the host. So this backend starts and destroys nothing. HARNESS_SANDBOX_IMAGE
    is set by the image's environment, which a host can set too, so the container is claimed only when the process
    shows the container's restrictions and the egress container's list (isolation)."""
    name = "devcontainer"

    def create(self, workspace):
        return Sandbox(workspace)

    def exec(self, sandbox, command, stdin=None, log=None, timeout=None):
        try:
            return subprocess.run(command, shell=True, cwd=str(sandbox.workspace), input=stdin, stdout=log,
                                  stderr=subprocess.STDOUT, text=True, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return None

    def copy_in(self, sandbox, host_path, sandbox_path):
        shutil.copy2(str(host_path), str(sandbox_path))

    def copy_out(self, sandbox, sandbox_path, host_path):
        shutil.copy2(str(sandbox_path), str(host_path))

    def egress_policy(self):
        if isolation()[0] != "container":
            return None
        return published_hosts(ALLOWLIST_PATH)

    def teardown(self, sandbox):
        pass

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
                "isolation_reason": reason}


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


def backend(name):
    return BACKENDS[name]()


def evidence(name):
    """The evidence for the sandbox this process runs in, as the named backend sees it."""
    if name not in BACKENDS:
        return dict({field: "unknown" for field in EVIDENCE_FIELDS}, backend=name)
    return backend(name).identity()
