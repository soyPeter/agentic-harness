"""Agentic harness (harness-owned): sandbox backends and sandbox evidence (ADR-003 in the harness repository).

A backend is where harness.py run starts its agent sessions, and the evidence is what a judge verdict records about
the sandbox it ran in. The engine stays standard-library only: a backend for a hosted sandbox talks to it through its
CLI or its REST API, never through a vendor SDK.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

EVIDENCE_FIELDS = ("backend", "isolation_class", "image_digest", "allowlist_hash", "region", "control_plane",
                   "credential_mode")
ISOLATION_CLASSES = ("none", "container", "userspace-kernel", "microVM", "dedicated-VM")
CREDENTIAL_VARIABLES = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
PINNED = re.compile(r"@(sha256:[0-9a-f]{64})$")


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
        """The sandbox evidence: one value per EVIDENCE_FIELDS name."""
        raise NotImplementedError


class Devcontainer(SandboxBackend):
    """The local .devcontainer/harness-agent/ sandbox. The runner runs where its sessions run: inside the container when
    the user started it there, otherwise on the host. So this backend starts and destroys nothing, and it vouches for
    a container only in an image built from the harness-agent Dockerfile, which bakes HARNESS_SANDBOX_IMAGE into the
    image's environment. HARNESS_EGRESS_ALLOWLIST names the host list the egress container publishes."""
    name = "devcontainer"

    def inside(self):
        return bool(os.environ.get("HARNESS_SANDBOX_IMAGE"))

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
        published = os.environ.get("HARNESS_EGRESS_ALLOWLIST")
        if not (self.inside() and published):
            return None
        try:
            text = Path(published).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return sorted({line.strip().lower() for line in text.splitlines() if line.strip()})

    def teardown(self, sandbox):
        pass

    def identity(self):
        if not self.inside():
            return {"backend": self.name, "isolation_class": "none", "image_digest": "none", "allowlist_hash": "none",
                    "region": "local", "control_plane": "none", "credential_mode": "host"}
        pinned = PINNED.search(os.environ["HARNESS_SANDBOX_IMAGE"])
        hosts = self.egress_policy()
        return {"backend": self.name, "isolation_class": "container",
                "image_digest": pinned.group(1) if pinned else "unpinned",
                "allowlist_hash": allowlist_hash(hosts) if hosts is not None else "none",
                "region": "local", "control_plane": "local",
                "credential_mode": "env" if any(os.environ.get(v) for v in CREDENTIAL_VARIABLES) else "login"}


BACKENDS = {Devcontainer.name: Devcontainer}


def allowlist_hash(hosts):
    """sha256 over the host names, one per line: the same policy gives the same hash, whoever wrote the list."""
    return "sha256:" + hashlib.sha256("".join(host + "\n" for host in hosts).encode("utf-8")).hexdigest()


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
