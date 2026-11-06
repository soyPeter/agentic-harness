"""update.sh --to-thin and --to-full (ADR-001): a project switches between the full install and thin mode.

Every test works in throwaway repositories. A local repository tagged like the harness's releases stands in for the
harness repository (HARNESS_ENGINE_SOURCE), so the conversions fetch and check a release as they do online.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
except ImportError:
    given = None


ROOT = Path(__file__).resolve().parents[1]
UPDATE = ROOT / "update.sh"
LAUNCHER = ROOT / "plugin/launcher.py"
VERSION = (ROOT / "VERSION").read_text().strip()
LOCK = "backbone/.harness-lock.json"
WORKFLOW = ".github/workflows/harness-verify.yml"
SHIM = ".githooks/pre-commit"
PLUGIN = "agentic-harness@agentic-harness"
FULL_HOOKS = "scripts/harness/git-hooks"
USER_SETTINGS = {"model": "opus", "permissions": {"deny": ["Read(./.env)"]},
                 "hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [{"type": "command",
                                                                         "command": "echo custom-hook"}]}]}}
ADR = """# ADR-002: Containers

## Status
Accepted

## Date
2026-11-01

## Context
The service ships as an image.

## Decision
Podman images. Catalog packs: container.

## Alternatives considered
- Docker: not chosen.

## Consequences
- Agents load the container skills.
"""


def environment(source, work):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com",
               HARNESS_ENGINE_SOURCE=str(source), HARNESS_ENGINES=str(work / "cache"),
               CODEX_HOME=str(work / "codex"), OPENCODE_CONFIG_DIR=str(work / "opencode"),
               XDG_CONFIG_HOME=str(work / "xdg"), HARNESS_REVIEW="off", HARNESS_DELIVER="off",
               PYTHONDONTWRITEBYTECODE="1")
    for name in ("HARNESS_ROOT", "CLAUDE_PROJECT_DIR", "HARNESS_PLUGIN_ROOT", "HARNESS_VERIFY", "HARNESS_AUTONOMY",
                 "HARNESS_BUILD_CMD"):
        env.pop(name, None)
    return env


def content(path):
    return path.read_bytes() if path.is_file() else None


def run(cwd, env, *args, check=True, input=None):
    result = subprocess.run([str(a) for a in args], cwd=str(cwd), env=env, capture_output=True, text=True,
                            input=input, stdin=subprocess.DEVNULL if input is None else None)
    if check and result.returncode:
        raise AssertionError("%s failed (%d):\n%s%s" % (" ".join(map(str, args)), result.returncode, result.stdout,
                                                         result.stderr))
    return result


def set_release_version(source, version):
    (source / "VERSION").write_text(version + "\n")
    for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "package.json"):
        data = json.loads((source / name).read_text())
        data["version"] = version
        (source / name).write_text(json.dumps(data, indent=2) + "\n")


def build_source(source, env):
    """Releases v0.26.1 (before thin mode), v<VERSION> (this checkout) and v99.0.0 (a later one)."""
    source.mkdir()
    run(source, env, "git", "init", "-q", "-b", "main")
    shutil.copytree(ROOT / "payload", source / "payload")
    (source / "VERSION").write_text("0.26.1\n")
    run(source, env, "git", "add", "-A")
    run(source, env, "git", "commit", "-qm", "legacy engine")
    run(source, env, "git", "tag", "v0.26.1")
    names = run(ROOT, env, "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    for name in filter(None, names.split("\0")):
        if (ROOT / name).is_file():
            (source / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(ROOT / name), str(source / name))
    run(source, env, "git", "add", "-A")
    run(source, env, "git", "commit", "-qm", "release")
    run(source, env, "git", "tag", "v" + VERSION)
    set_release_version(source, "99.0.0")
    for name in ("payload/owned/AGENTS.md", "plugin/pre-commit"):
        with open(str(source / name), "a") as handle:
            handle.write("# 99.0.0\n")
    fragment = json.loads((source / "payload/settings.fragment.json").read_text())
    fragment["permissions"]["allow"].append("Bash(make test)")
    (source / "payload/settings.fragment.json").write_text(json.dumps(fragment, indent=2) + "\n")
    run(source, env, "git", "commit", "-qam", "later release")
    run(source, env, "git", "tag", "v99.0.0")


def install_full(project, env):
    project.mkdir()
    run(project, env, "git", "init", "-q", "-b", "main")
    (project / ".claude").mkdir()
    (project / ".claude/settings.json").write_text(json.dumps(USER_SETTINGS, indent=2) + "\n")
    run(project, env, ROOT / "bootstrap.sh", project, "--name", "demo")
    run(project, env, "git", "add", "-A")
    run(project, env, "git", "commit", "-qm", "chore: adopt agentic harness")


class Fixture(unittest.TestCase):
    """A committed full install of this checkout (the release v<VERSION>) in self.project."""

    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix="thin convert ")
        base = Path(cls.shared.name).resolve()
        cls.source = base / "source"
        env = environment(cls.source, base)
        build_source(cls.source, env)
        cls.template = base / "full"
        install_full(cls.template, env)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="thin convert ")
        self.addCleanup(scratch.cleanup)
        self.work = Path(scratch.name).resolve()
        self.env = environment(self.source, self.work)
        self.project = self.copy_of(self.template, "project")

    def copy_of(self, template, name):
        project = self.work / name
        shutil.copytree(str(template), str(project), symlinks=True)
        return project

    def run_at(self, cwd, *args, env=None, check=True, input=None):
        return run(cwd, env or self.env, *args, check=check, input=input)

    def git(self, *args, check=True, project=None):
        return self.run_at(project or self.project, "git", *args, check=check)

    def update(self, *args, check=True, project=None):
        return self.run_at(project or self.project, UPDATE, *args, check=check)

    def commit(self, message, hooks=True, project=None):
        """Commit everything; without hooks for a fixture, which may also change nothing."""
        self.git("add", "-A", project=project)
        self.git("commit", "-qm", message, *([] if hooks else ["--no-verify", "--allow-empty"]), project=project)
        return self.git("rev-parse", "HEAD", project=project).stdout.strip()

    def hooks_path(self, project=None):
        return self.git("config", "--get", "core.hooksPath", check=False, project=project).stdout.strip()

    def release(self, name, version=VERSION):
        return subprocess.run(["git", "show", "v%s:%s" % (version, name)], cwd=str(self.source), env=self.env,
                              capture_output=True, check=True).stdout

    def tag_commit(self, version):
        return self.run_at(self.source, "git", "rev-parse", "v%s^{commit}" % version).stdout.strip()

    def lock(self, project=None):
        return json.loads(((project or self.project) / LOCK).read_text())

    def snapshot(self, project=None):
        """Everything a conversion could change: the files and folders outside .git, core.hooksPath and HEAD."""
        project = project or self.project
        files = {}
        for item in sorted(project.rglob("*")):
            name = item.relative_to(project).as_posix()
            if name == ".git" or name.startswith(".git/"):
                continue
            files[name] = None if item.is_dir() else (item.read_bytes(), os.access(str(item), os.X_OK))
        head = self.git("rev-parse", "-q", "--verify", "HEAD", check=False, project=project).stdout.strip()
        return files, self.hooks_path(project), head

    def empty_folders(self, project=None):
        project = project or self.project
        return sorted(item.relative_to(project).as_posix() for item in project.rglob("*")
                      if item.is_dir() and ".git" not in item.relative_to(project).parts and not any(item.iterdir()))


class Conversion(Fixture):
    def test_switching_to_thin_and_back_gives_back_the_full_install(self):
        installed = self.git("rev-parse", "HEAD").stdout.strip()
        result = self.update("--to-thin", self.project)
        self.assertIn("thin mode", result.stdout)
        for name in ("AGENTS.md", "scripts/harness", ".claude/agents", ".claude/skills", ".codex", ".opencode",
                     ".devcontainer"):
            self.assertFalse((self.project / name).exists(), name)
        self.assertEqual(self.lock(), {"mode": "thin", "version": VERSION, "commit": self.tag_commit(VERSION)})
        self.assertEqual((self.project / SHIM).read_bytes(), self.release("plugin/pre-commit"))
        self.assertTrue(os.access(str(self.project / SHIM), os.X_OK))
        self.assertEqual(self.hooks_path(), ".githooks")
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        self.assertTrue(settings["enabledPlugins"][PLUGIN])
        self.assertEqual(settings["extraKnownMarketplaces"]["agentic-harness"]["source"]["ref"], "v" + VERSION)
        self.assertNotIn("scripts/harness/", json.dumps(settings["hooks"]))
        self.assertIn("echo custom-hook", json.dumps(settings["hooks"]))
        self.assertEqual((settings["model"], settings["permissions"]["deny"]), ("opus", ["Read(./.env)"]))
        self.assertEqual(self.git("status", "--porcelain", "--", "backbone", "CLAUDE.md", ".github").stdout,
                         " M %s\n" % LOCK)
        self.assertEqual(self.empty_folders(), [])
        doctor = self.run_at(self.project, "python3", "-B", LAUNCHER, "doctor")
        self.assertNotIn("ERROR", doctor.stdout)
        self.commit("chore: switch the agentic harness to thin mode")

        result = self.update("--to-full", self.project)
        self.assertIn("full install", result.stdout)
        self.git("add", "-A")
        self.assertEqual(self.git("diff", "--cached", "--stat", installed, "--", ".", ":(exclude)" + LOCK).stdout, "")
        restored, original = self.lock(), json.loads(self.git("show", "%s:%s" % (installed, LOCK)).stdout)
        for lock in (restored, original):
            lock.pop("installed")
            lock.pop("updated")
        self.assertEqual(restored, original)
        self.assertEqual(self.hooks_path(), FULL_HOOKS)
        self.assertFalse((self.project / ".githooks").exists())
        self.assertEqual(self.empty_folders(), [])
        self.git("commit", "-qm", "chore: switch the agentic harness back to a full install")
        status = self.update("status", self.project).stdout
        for state in ("missing", "edited locally", "update available", "new upstream"):
            self.assertNotIn(state, status)
        self.run_at(self.project, self.project / "scripts/harness/doctor.sh")
        self.update(self.project)

    def test_the_switch_passes_ci_only_with_the_harness_change_label(self):
        full = self.git("rev-parse", "HEAD").stdout.strip()
        self.update("--to-thin", self.project)
        thin = self.commit("chore: switch the agentic harness to thin mode")
        self.assert_ci_needs_the_label(full)
        self.update("--to-full", self.project)
        self.commit("chore: switch the agentic harness back to a full install")
        self.assert_ci_needs_the_label(thin)

    def assert_ci_needs_the_label(self, base):
        refused = self.ci_verify(base)
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("the harness itself changes", refused.stdout)
        approved = self.ci_verify(base, "--allow-user-changes")
        self.assertEqual(approved.returncode, 0, approved.stdout + approved.stderr)

    def ci_verify(self, base, *flags):
        """harness-verify on the pull request base..HEAD: its first step picks the verifier the base branch names (its
        vendored engine, or the engine its pin names), the second runs verify --range with it."""
        self.git("update-ref", "refs/remotes/origin/review-base", base)
        workflow = (self.project / WORKFLOW).read_text()
        step = workflow.split("      - name: Take the verifier from the base branch\n", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0])
        script = script.replace("https://github.com/soyPeter/agentic-harness.git", str(self.source))
        runner = Path(tempfile.mkdtemp(prefix="runner ", dir=str(self.work)))
        env = dict(self.env, BASE="review-base", RUNNER_TEMP=str(runner), GITHUB_ENV=str(runner / "github-env"))
        self.run_at(self.project, "bash", "-e", "-o", "pipefail", "-c", script, env=env)
        engine = (runner / "github-env").read_text().strip().split("=", 1)[1]
        return self.run_at(self.project, "python3", "-B", engine, "verify", "--range", "origin/review-base..HEAD",
                           *flags, env=dict(self.env, HARNESS_ROOT=str(self.project)), check=False)

    def test_edited_harness_files_are_kept_as_backups(self):
        edits = ("AGENTS.md", ".claude/agents/judge.md", ".claude/skills/security/SKILL.md", ".codex/agents/judge.toml",
                 ".opencode/plugins/harness.js", "scripts/harness/guardrails.core.conf",
                 ".devcontainer/harness-agent/Dockerfile")
        for name in edits + (WORKFLOW, "backbone/8-WORKFLOW.md"):
            with open(str(self.project / name), "a") as handle:
                handle.write("# local edit\n")
        edited = {name: (self.project / name).read_bytes() for name in edits + (WORKFLOW, "backbone/8-WORKFLOW.md")}
        self.commit("chore: local harness edits", hooks=False)
        result = self.update("--to-thin", self.project)
        for name in edits:
            with self.subTest(name=name):
                self.assertFalse((self.project / name).exists())
                self.assertEqual((self.project / (name + ".harness-bak")).read_bytes(), edited[name])
                self.assertIn(name + ".harness-bak", result.stdout)
        self.assertFalse((self.project / ".claude/skills/security/checklist.md").exists())
        self.assertFalse((self.project / ".claude/agents/griller.md").exists())
        self.assertEqual((self.project / WORKFLOW).read_bytes(), self.release("payload/owned/" + WORKFLOW))
        self.assertEqual((self.project / (WORKFLOW + ".harness-bak")).read_bytes(), edited[WORKFLOW])
        self.assertEqual((self.project / "backbone/8-WORKFLOW.md").read_bytes(), edited["backbone/8-WORKFLOW.md"])
        self.assertFalse((self.project / "backbone/8-WORKFLOW.md.harness-bak").exists())
        self.commit("chore: switch the agentic harness to thin mode")

        result = self.update("--to-full", self.project, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CONFLICT  backbone/8-WORKFLOW.md", result.stdout)
        self.assertEqual((self.project / "backbone/8-WORKFLOW.md").read_bytes(), edited["backbone/8-WORKFLOW.md"])
        self.assertEqual((self.project / "backbone/8-WORKFLOW.md.harness-new").read_bytes(),
                         self.release("payload/owned/backbone/8-WORKFLOW.md"))
        for name in edits + (WORKFLOW,):
            with self.subTest(name=name):
                self.assertEqual((self.project / name).read_bytes(), self.release("payload/owned/" + name))
                self.assertEqual((self.project / (name + ".harness-bak")).read_bytes(), edited[name])
        self.assertEqual(self.lock()["harness_version"], VERSION)

    def test_running_a_conversion_again_changes_nothing(self):
        self.update("--to-thin", self.project)
        converted = self.snapshot()
        again = self.update("--to-thin", self.project)
        self.assertIn("already in thin mode", again.stdout)
        self.assertEqual(self.snapshot(), converted)
        self.commit("chore: switch the agentic harness to thin mode")
        self.update("--to-full", self.project)
        converted = self.snapshot()
        again = self.update("--to-full", self.project)
        self.assertIn("already a full install", again.stdout)
        self.assertEqual(self.snapshot(), converted)

    def test_a_dry_run_shows_the_plan_and_changes_nothing(self):
        before = self.snapshot()
        result = self.update("--to-thin", self.project, "--dry-run")
        self.assertIn("remove    AGENTS.md", result.stdout)
        self.assertIn("add       " + SHIM, result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_a_project_installed_in_thin_mode_switches_to_full(self):
        project = self.work / "thin"
        project.mkdir()
        self.git("init", "-q", "-b", "main", project=project)
        self.run_at(project, "python3", "-B", LAUNCHER, "init", "--thin", "--name", "demo")
        self.commit("chore: adopt agentic harness", project=project)
        result = self.update("--to-full", project, project=project)
        self.assertIn("full install", result.stdout)
        lock = self.lock(project)
        self.assertNotIn("mode", lock)
        self.assertEqual(lock["harness_version"], VERSION)
        self.assertEqual(self.hooks_path(project), FULL_HOOKS)
        self.assertFalse((project / ".githooks").exists())
        settings = json.loads((project / ".claude/settings.json").read_text())
        self.assertNotIn("enabledPlugins", settings)
        self.assertNotIn("extraKnownMarketplaces", settings)
        self.assertIn("scripts/harness/lib/harness.py", json.dumps(settings["hooks"]))
        self.assertTrue((project / ".github/workflows/harness-judge.yml").is_file())
        self.assertIn("CLAUDE.md", result.stdout)
        self.commit("chore: switch the agentic harness to a full install", project=project)
        self.run_at(project, project / "scripts/harness/doctor.sh")
        status = self.update("status", project, project=project).stdout
        for state in ("missing", "edited locally", "update available", "new upstream"):
            self.assertNotIn(state, status)

    def test_adopted_packs_stay_in_the_project(self):
        (self.project / "backbone/adr/ADR-002-containers.md").write_text(ADR)
        self.run_at(self.project, "python3", "-B", "scripts/harness/lib/harness.py", "adopt", "container", "--adr",
                    "ADR-002", "--with", "podman")
        installed = self.commit("chore: adopt the container pack", hooks=False)
        packed = [name for name in self.lock()["adopted"]["container"]["files"]]
        self.assertTrue(packed)
        self.update("--to-thin", self.project)
        for name in packed:
            self.assertTrue((self.project / name).is_file(), name)
        self.assertEqual(self.lock()["adopted"], json.loads(self.git("show", "%s:%s" % (installed, LOCK)).stdout)[
            "adopted"])
        doctor = self.run_at(self.project, "python3", "-B", LAUNCHER, "doctor")
        self.assertIn("container via ADR-002", doctor.stdout)
        self.commit("chore: switch the agentic harness to thin mode")
        self.update("--to-full", self.project)
        self.git("add", "-A")
        self.assertEqual(self.git("diff", "--cached", "--stat", installed, "--", ".", ":(exclude)" + LOCK).stdout, "")
        self.assertEqual(sorted(self.lock()["files"]),
                         sorted(json.loads(self.git("show", "%s:%s" % (installed, LOCK)).stdout)["files"]))

    def test_another_release_can_be_pinned_while_switching(self):
        self.update("--to-thin", self.project, "--version", "99.0.0")
        self.assertEqual(self.lock(), {"mode": "thin", "version": "99.0.0", "commit": self.tag_commit("99.0.0")})
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        self.assertEqual(settings["extraKnownMarketplaces"]["agentic-harness"]["source"]["ref"], "v99.0.0")
        self.assertEqual((self.project / SHIM).read_bytes(), self.release("plugin/pre-commit", "99.0.0"))
        self.commit("chore: switch the agentic harness to thin mode")
        self.update("--to-full", self.project)
        self.assertEqual(self.lock()["harness_version"], "99.0.0")
        self.assertEqual((self.project / "AGENTS.md").read_bytes(), self.release("payload/owned/AGENTS.md", "99.0.0"))
        self.assertIn("Bash(make test)", json.loads((self.project / ".claude/settings.json").read_text())[
            "permissions"]["allow"])
        self.assertFalse((self.project / ".githooks").exists())

    def test_thin_commands_on_a_full_install_point_at_the_switch(self):
        before = self.snapshot()
        for command in (("init", "--thin"), ("pin", VERSION)):
            with self.subTest(command=command):
                result = self.run_at(self.project, "python3", "-B", LAUNCHER, *command, check=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("update.sh --to-thin", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_force_hooks_path_replaces_another_hook_manager(self):
        self.git("config", "core.hooksPath", ".husky/_")
        self.update("--to-thin", self.project, "--force-hooks-path")
        self.assertEqual(self.hooks_path(), ".githooks")

    def test_hooks_of_the_projects_own_keep_running_after_the_switch_back(self):
        self.update("--to-thin", self.project)
        (self.project / ".githooks/post-checkout").write_text("#!/bin/sh\necho checked out\n")
        self.commit("chore: switch the agentic harness to thin mode")
        result = self.update("--to-full", self.project)
        self.assertEqual(self.hooks_path(), ".githooks")
        self.assertIn("core.hooksPath", result.stdout)
        self.assertIn("--force-hooks-path", result.stdout)
        self.assertFalse((self.project / SHIM).exists())
        self.assertTrue((self.project / ".githooks/post-checkout").is_file())

    def test_force_takes_the_release_version_and_keeps_a_backup(self):
        self.update("--to-thin", self.project)
        workflow = self.project / "backbone/8-WORKFLOW.md"
        workflow.write_text(workflow.read_text() + "local edit\n")
        edited = workflow.read_bytes()
        self.commit("chore: switch the agentic harness to thin mode")
        self.update("--to-full", self.project, "--force")
        self.assertEqual(workflow.read_bytes(), self.release("payload/owned/backbone/8-WORKFLOW.md"))
        self.assertEqual((self.project / "backbone/8-WORKFLOW.md.harness-bak").read_bytes(), edited)
        self.assertFalse((self.project / "backbone/8-WORKFLOW.md.harness-new").exists())


class Refusals(Fixture):
    """Each row breaks one thing a conversion needs. The conversion must refuse before writing anything."""

    def test_switching_to_thin_refuses_and_changes_nothing(self):
        def edit(name, text="# local edit\n"):
            def apply(project):
                with open(str(project / name), "a") as handle:
                    handle.write(text)
            return apply

        def commit_after(*steps):
            def apply(project):
                for step in steps:
                    step(project)
                self.commit("chore: fixture", hooks=False, project=project)
            return apply

        def cache_with_local_changes(project):
            cache = self.work / "cache" / VERSION
            self.run_at(self.work, "git", "clone", "-q", "--branch", "v" + VERSION, self.source, cache)
            (cache / "plugin/pre-commit").write_text("modified cache\n")

        def no_harness(project):
            shutil.rmtree(str(project))
            project.mkdir()
            self.git("init", "-q", "-b", "main", project=project)

        def lock_files(change):
            def apply(project):
                lock = self.lock(project)
                change(lock["files"])
                (project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
            return apply

        cases = (
            ("a change not committed", edit("backbone/1-PRD.md"), (), "uncommitted changes"),
            ("an untracked file", edit("notes.txt"), (), "uncommitted changes"),
            ("a release that was not published", None, ("--version", "9.9.9"), "release v9.9.9 was not found"),
            ("a release from before thin mode", None, ("--version", "0.26.1"), "does not support thin mode"),
            ("a backup already there", commit_after(edit("AGENTS.md"), edit("AGENTS.md.harness-bak")), (),
             "AGENTS.md.harness-bak already exists"),
            ("a pre-commit hook of the project's own", commit_after(self.own_pre_commit), (),
             SHIM + " already exists with different content"),
            ("another hook manager", lambda project: self.git("config", "core.hooksPath", ".husky/_", project=project),
             (), "core.hooksPath is .husky/_"),
            ("settings that are not JSON", commit_after(edit(".claude/settings.json", "{")), (),
             ".claude/settings.json"),
            ("a corrupt lock", commit_after(edit(LOCK, "<<<<<<< HEAD\n")), (), LOCK),
            ("a lock that doesn't list the engine",
             commit_after(lock_files(lambda files: files.pop("scripts/harness/lib/harness.py"))), (),
             "scripts/harness/lib/harness.py isn't listed"),
            ("a lock naming a file outside the project",
             commit_after(lock_files(lambda files: files.update({"../outside.txt": "0" * 64}))), (),
             "outside the project"),
            ("an engine cache with local changes", cache_with_local_changes, (), "local changes"),
            ("no harness", no_harness, (), "no harness"),
        )
        for name, prepare, flags, says in cases:
            with self.subTest(case=name):
                project = self.copy_of(self.template, "to-thin " + name)
                shutil.rmtree(str(self.work / "cache"), ignore_errors=True)
                if prepare:
                    prepare(project)
                self.assert_refused(project, ("--to-thin", project) + flags, says)
        project = self.copy_of(self.template, "subfolder")
        self.assert_refused(project, ("--to-thin", project / "backbone"), "repository root")

    def own_pre_commit(self, project):
        (project / ".githooks").mkdir()
        (project / SHIM).write_text("#!/bin/sh\nnpm test\n")

    def test_switching_to_full_refuses_and_changes_nothing(self):
        thin = self.work / "thin template"
        shutil.copytree(str(self.template), str(thin), symlinks=True)
        self.update("--to-thin", thin, project=thin)
        self.commit("chore: switch the agentic harness to thin mode", project=thin)

        def commit_after(step):
            def apply(project):
                step(project)
                self.commit("chore: fixture", hooks=False, project=project)
            return apply

        def pin(**fields):
            def apply(project):
                lock = self.lock(project)
                lock.update(fields)
                (project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
            return apply

        def edited_shim_with_backup(project):
            with open(str(project / SHIM), "a") as handle:
                handle.write("# local edit\n")
            (project / (SHIM + ".harness-bak")).write_text("an older backup\n")

        def edited_doc_with_backup(project):
            with open(str(project / "backbone/8-WORKFLOW.md"), "a") as handle:
                handle.write("local edit\n")
            (project / "backbone/8-WORKFLOW.md.harness-bak").write_text("an older backup\n")

        def uncommitted(project):
            (project / "notes.txt").write_text("notes\n")

        cases = (
            ("a change not committed", uncommitted, (), "uncommitted changes"),
            ("a pin whose commit is not the release's", commit_after(pin(commit="0" * 40)), (), "the project pins"),
            ("a pin with no valid version", commit_after(pin(version="../x")), (), "no valid version"),
            ("a pin with no valid commit", commit_after(pin(commit="v" + VERSION)), (), "without a valid commit"),
            ("settings that are not JSON",
             commit_after(lambda project: (project / ".claude/settings.json").write_text("{")), (),
             ".claude/settings.json"),
            ("an edited shim whose backup is taken", commit_after(edited_shim_with_backup), (),
             SHIM + ".harness-bak already exists"),
            ("--force over a backup", commit_after(edited_doc_with_backup), ("--force",),
             "backbone/8-WORKFLOW.md.harness-bak already exists"),
        )
        for name, prepare, flags, says in cases:
            with self.subTest(case=name):
                project = self.copy_of(thin, "to-full " + name)
                shutil.rmtree(str(self.work / "cache"), ignore_errors=True)
                prepare(project)
                self.assert_refused(project, ("--to-full", project) + flags, says)

    def assert_refused(self, project, args, says):
        before = self.snapshot(project)
        result = self.update(*args, check=False, project=project)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(says, result.stderr)
        self.assertEqual(self.snapshot(project), before)


class Properties(Fixture):
    """For any set of harness files the user edited: the switch to thin mode keeps exactly those, as backups, and
    removes the rest, but leaves backbone/ as it is; the switch back restores every harness file and keeps the
    backups, and only edited backbone documents conflict."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owned = sorted(json.loads((cls.template / LOCK).read_text())["files"])

    if given is None:
        def test_edited_files_are_backed_up_and_restored(self):
            self.skipTest("needs hypothesis (pip install -r tests/requirements.txt)")
    else:
        @settings(max_examples=8, deadline=None, database=None, suppress_health_check=list(HealthCheck))
        @given(data=st.data())
        def test_edited_files_are_backed_up_and_restored(self, data):
            edits = data.draw(st.sets(st.sampled_from(self.owned), max_size=6), label="edited")
            project = self.copy_of(self.template, "example")
            try:
                self.check_round_trip(project, edits)
            finally:
                shutil.rmtree(str(project), ignore_errors=True)

    def check_round_trip(self, project, edits):
        original = {name: (project / name).read_bytes() for name in self.owned}
        for name in edits:
            with open(str(project / name), "a") as handle:
                handle.write("# local edit\n")
        edited = {name: (project / name).read_bytes() for name in edits}
        self.commit("chore: local harness edits", hooks=False, project=project)
        self.update("--to-thin", project, project=project)
        for name in self.owned:
            if name.startswith("backbone/"):
                expected, backup = edited.get(name, original[name]), None
            elif name == WORKFLOW:
                expected, backup = original[name], edited.get(name)
            else:
                expected, backup = None, edited.get(name)
            self.assertEqual(content(project / name), expected, name)
            self.assertEqual(content(project / (name + ".harness-bak")), backup, name)
        self.assertEqual(self.empty_folders(project), [])
        converted = self.snapshot(project)
        self.update("--to-thin", project, project=project)
        self.assertEqual(self.snapshot(project), converted)
        self.commit("chore: switch the agentic harness to thin mode", project=project)

        conflicts = {name for name in edits if name.startswith("backbone/")}
        result = self.update("--to-full", project, check=False, project=project)
        self.assertEqual(result.returncode, 1 if conflicts else 0, result.stdout + result.stderr)
        for name in self.owned:
            in_conflict = name in conflicts
            self.assertEqual(content(project / name), edited[name] if in_conflict else original[name], name)
            self.assertEqual(content(project / (name + ".harness-new")), original[name] if in_conflict else None, name)
            self.assertEqual(content(project / (name + ".harness-bak")),
                             None if name.startswith("backbone/") else edited.get(name), name)
        self.assertEqual(self.hooks_path(project), FULL_HOOKS)


if __name__ == "__main__":
    unittest.main()
