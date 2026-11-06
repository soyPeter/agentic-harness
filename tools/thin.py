#!/usr/bin/env python3
"""Install and pin a thin agentic harness project."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE_ROOT / "plugin"))
from launcher import EngineUnavailable, checked, engines_dir, fetch

DEFAULT_SOURCE = "https://github.com/soyPeter/agentic-harness.git"
MARKETPLACE = "agentic-harness"
LOCK = Path("backbone/.harness-lock.json")
SHIM = ".githooks/pre-commit"
# Project files copied from the pinned release; pin brings them to the new one.
RELEASE_FILES = ((SHIM, "plugin/pre-commit"),
                 (".github/workflows/harness-verify.yml", "payload/owned/.github/workflows/harness-verify.yml"))
VERSION = (SOURCE_ROOT / "VERSION").read_text().strip()


class ThinError(Exception):
    pass


def git(*args, cwd=None):
    try:
        result = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ThinError("git %s could not complete: %s" % (" ".join(args), exc))
    if result.returncode:
        raise ThinError(result.stderr.strip() or "git %s failed" % " ".join(args))
    return result.stdout.strip()


def release_commit(version):
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", version):
        raise ThinError("invalid version %r" % version)
    source = os.environ.get("HARNESS_ENGINE_SOURCE") or DEFAULT_SOURCE
    ref = "refs/tags/v" + version
    lines = git("ls-remote", "--tags", source, ref, ref + "^{}").splitlines()
    commits = {line.split("\t", 1)[1]: line.split("\t", 1)[0] for line in lines if "\t" in line}
    commit = commits.get(ref + "^{}") or commits.get(ref)
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ThinError("release v%s was not found at %s" % (version, source))
    return commit


def release_checkout(version):
    commit = release_commit(version)
    engine = engines_dir() / version
    try:
        if not engine.is_dir():
            fetch(engine, version, commit, 60)
        checked(engine, commit)
    except (EngineUnavailable, OSError) as exc:
        raise ThinError("release v%s cannot be used: %s" % (version, exc))
    required = ("VERSION", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                ".codex-plugin/plugin.json", "package.json", "plugin/launcher.py", "plugin/pre-commit",
                "tools/thin.py", "payload/seed/CLAUDE.md", "payload/owned/backbone/8-WORKFLOW.md",
                "payload/owned/.github/workflows/harness-verify.yml")
    for name in required:
        if not (engine / name).is_file():
            raise ThinError("release v%s does not support thin mode (missing %s)" % (version, name))
    if (engine / "VERSION").read_text().strip() != version:
        raise ThinError("release v%s has a different VERSION file" % version)
    for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "package.json"):
        try:
            metadata = json.loads((engine / name).read_text())
        except ValueError as exc:
            raise ThinError("release v%s has invalid %s: %s" % (version, name, exc))
        if not isinstance(metadata, dict) or metadata.get("version") != version:
            raise ThinError("release v%s has a mismatched %s version" % (version, name))
    return commit, engine


def root_dir():
    root = Path.cwd().resolve()
    top = Path(git("rev-parse", "--show-toplevel", cwd=root)).resolve()
    if root != top:
        raise ThinError("run from the repository root: %s" % top)
    return root


def settings_for(root, version):
    path = root / ".claude/settings.json"
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except ValueError as exc:
        raise ThinError(".claude/settings.json is invalid JSON: %s" % exc)
    if not isinstance(data, dict):
        raise ThinError(".claude/settings.json must be an object")
    markets = data.setdefault("extraKnownMarketplaces", {})
    plugins = data.setdefault("enabledPlugins", {})
    if not isinstance(markets, dict) or not isinstance(plugins, dict):
        raise ThinError("plugin settings in .claude/settings.json must be objects")
    markets[MARKETPLACE] = {"source": {"source": "github", "repo": "soyPeter/agentic-harness",
                                       "ref": "v" + version}}
    plugins["agentic-harness@" + MARKETPLACE] = True
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_new(root, rel, data, executable=False):
    path = root / rel
    if path.exists():
        if path.read_bytes() != data:
            raise ThinError("%s already exists with different content" % rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if executable:
        path.chmod(0o755)


def init(version, name):
    root = root_dir()
    if (root / LOCK).exists():
        raise ThinError("%s already exists" % LOCK)
    hooks_path = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=root,
                                capture_output=True, text=True).stdout.strip()
    if hooks_path and hooks_path != ".githooks":
        raise ThinError("core.hooksPath is %s; chain the harness hook before installing thin mode" % hooks_path)
    commit, release = release_checkout(version)
    settings = settings_for(root, version)
    context = {"PROJECT_NAME": name or root.name, "DATE": datetime.date.today().isoformat(),
               "HARNESS_VERSION": version}
    seeds = release / "payload/seed"
    backbone = release / "payload/owned/backbone"
    files = {}
    project_files = set()
    for base in (seeds, backbone):
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(seeds) if base == seeds else Path("backbone") / path.relative_to(backbone)
            if base == seeds and rel.parts[0] == ".github":
                continue
            if base == seeds:
                project_files.add(rel)
            content = path.read_bytes()
            if path.suffix == ".md" or path.suffix == ".conf":
                text = content.decode("utf-8")
                for key, value in context.items():
                    text = text.replace("{{%s}}" % key, value)
                if rel == Path("CLAUDE.md"):
                    text = text.replace("@AGENTS.md\n\n", "").replace(
                        "Shared agent rules belong in AGENTS.md (harness) and backbone/ (project).",
                        "Shared project rules belong in backbone/; the plugin supplies agent rules.")
                content = text.encode("utf-8")
            files[rel] = content
    workflow = Path(".github/workflows/harness-verify.yml")
    files[workflow] = (release / "payload/owned" / workflow).read_bytes()
    shim = release / "plugin/pre-commit"
    files[Path(".githooks/pre-commit")] = shim.read_bytes()
    kept = sorted(str(rel) for rel in project_files if (root / rel).exists())
    for rel, content in files.items():
        path = root / rel
        if path.exists() and rel not in project_files and path.read_bytes() != content:
            raise ThinError("%s already exists with different content" % rel)
    for rel, content in files.items():
        if rel not in project_files or not (root / rel).exists():
            write_new(root, rel, content, executable=rel == Path(".githooks/pre-commit"))
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude/settings.json").write_text(settings)
    (root / LOCK).write_text(json.dumps({"mode": "thin", "version": version, "commit": commit}, indent=2) + "\n")
    git("config", "core.hooksPath", ".githooks", cwd=root)
    print("Installed thin agentic harness v%s (%s) in %s" % (version, commit, root))
    if kept:
        print("Kept existing project files: %s" % ", ".join(kept))
    return 0


def pin(version):
    root = root_dir()
    try:
        lock = json.loads((root / LOCK).read_text())
    except (OSError, ValueError):
        raise ThinError("%s is missing or invalid" % LOCK)
    if lock.get("mode") != "thin":
        raise ThinError("%s is not a thin-mode lock" % LOCK)
    commit, release = release_checkout(version)
    settings = settings_for(root, version)
    lock.update(version=version, commit=commit)
    updated = []
    for rel, source in RELEASE_FILES:
        content = (release / source).read_bytes()
        path = root / rel
        if not path.is_file() or path.read_bytes() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            updated.append(rel)
        if rel == SHIM:
            path.chmod(0o755)
    (root / ".claude/settings.json").write_text(settings)
    (root / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
    print("Pinned thin agentic harness to v%s (%s)" % (version, commit))
    if updated:
        print("Updated from the release: %s" % ", ".join(updated))
    return 0


def main(argv):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init")
    init_parser.add_argument("--thin", action="store_true", required=True)
    init_parser.add_argument("--version", default=VERSION)
    init_parser.add_argument("--name")
    pin_parser = sub.add_parser("pin")
    pin_parser.add_argument("version")
    args = parser.parse_args(argv)
    try:
        return init(args.version, args.name) if args.command == "init" else pin(args.version)
    except ThinError as exc:
        sys.stderr.write("thin: %s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
