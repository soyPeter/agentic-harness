#!/usr/bin/env python3
"""Agentic harness (harness-owned): in the sandbox, make a thin project's pinned engine the Claude Code plugin.

A thin project runs the release its backbone/.harness-lock.json pins, and its hooks come from the agentic-harness
plugin (ADR-001). On the host the user installs that plugin. In here this script fetches the pinned release into
~/.agentic-harness/engines/<version>/, where the launcher looks for it, refuses it unless it is the pinned commit with
no local changes, and links it into ~/.agentic-harness/plugins/, the folder CLAUDE_CODE_PLUGIN_DIRS names
(docker-compose.yml), so every Claude Code session in the sandbox loads it. The launcher would fetch the release itself,
but it ships inside that release. A full install needs nothing: its hooks are in the project.

HARNESS_ENGINE_SOURCE names another repository to fetch from, as for the launcher; inside the sandbox it must be
reachable from here (an allowlisted host, or a path under the workspace).
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_SOURCE = "https://github.com/soyPeter/agentic-harness.git"
HOME = Path(os.path.expanduser("~/.agentic-harness"))
LINK = HOME / "plugins" / "agentic-harness"


def git(*args):
    result = subprocess.run(["git"] + list(args), capture_output=True, text=True, timeout=300)
    return result.stdout.strip() if result.returncode == 0 else None


def pinned_engine(lock):
    version, commit = str(lock.get("version") or ""), str(lock.get("commit") or "")
    if not re.match(r"^[0-9A-Za-z][0-9A-Za-z._-]*$", version) or not re.match(r"^[0-9a-f]{40}$", commit):
        raise RuntimeError("backbone/.harness-lock.json pins no valid version and commit")
    engine = Path(os.environ.get("HARNESS_ENGINES") or HOME / "engines") / version
    if not engine.is_dir():
        source = os.environ.get("HARNESS_ENGINE_SOURCE") or DEFAULT_SOURCE
        engine.parent.mkdir(parents=True, exist_ok=True)
        fetched = Path(tempfile.mkdtemp(prefix=".fetch-%s-" % version, dir=str(engine.parent)))
        try:
            cloned = git("clone", "--quiet", "--depth", "1", "--branch", "v" + version, source, str(fetched / "engine"))
            if cloned is None:
                raise RuntimeError("could not fetch v%s from %s" % (version, source))
            os.rename(str(fetched / "engine"), str(engine))
        finally:
            shutil.rmtree(str(fetched), ignore_errors=True)
    head = git("-C", str(engine), "rev-parse", "HEAD")
    if head != commit:
        raise RuntimeError("%s is commit %s, not the pinned %s; delete it to fetch it again" % (engine, head, commit))
    if git("-C", str(engine), "status", "--porcelain", "--untracked-files=all") != "":
        raise RuntimeError("%s has local changes, so it is not the pinned release; delete it to fetch it again"
                           % engine)
    return version, engine


def main(workspace):
    if os.path.islink(str(LINK)):
        LINK.unlink()
    try:
        lock = json.loads((Path(workspace) / "backbone/.harness-lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lock = None
    if not isinstance(lock, dict) or lock.get("mode") != "thin":
        return 0
    try:
        version, engine = pinned_engine(lock)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write("thin-engine: the pinned engine can't be used, so no Claude Code session in this sandbox gets "
                         "the harness hooks: %s\n" % exc)
        return 1
    LINK.parent.mkdir(parents=True, exist_ok=True)
    LINK.symlink_to(engine)
    print("thin-engine: the agentic-harness plugin here is the pinned engine v%s. Run the harness with: python3 "
          "%s/plugin/launcher.py <command>" % (version, LINK))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
