"""update.sh --to-thin and --to-full (ADR-001): a project switches between the full install and thin mode.

Every test works in throwaway repositories. A local repository tagged like the harness's releases stands in for the
harness repository (HARNESS_ENGINE_SOURCE), so the conversions fetch and check a release as they do online.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from hypothesis_profiles import examples

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
INSTALLED = "2026-01-02"
PACK_FILE = ".claude/skills/containers/SKILL.md"
PACK_DOC = ".claude/skills/containers/image-building.md"
CATALOG_INSTALL = "scripts/harness/catalog/container/install"
LATER_SETTING = '# HARNESS_LATER_SETTING="off"'
LATER_RULE = "Bash(make test)"
DROPPED_RULE = "Bash(scripts/harness/doctor.sh)"
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
JAVA_ADR = """# ADR-003: Java

## Status
Accepted

## Date
2026-11-02

## Context
The service runs on the JVM.

## Decision
Java with Gradle. Catalog packs: java.

## Alternatives considered
- Kotlin: not chosen.

## Consequences
- Agents load the Java skills.
"""
JAVA_TEST_FILES = (".claude/skills/java-test/SKILL.md", ".claude/skills/java-test/assertj.md")
OTHER_HASH = "0" * 64


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


def plugin_entries(version):
    """What thin mode adds to .claude/settings.json for release v<version>."""
    return {"extraKnownMarketplaces": {"agentic-harness": {"source": {"source": "github",
                                                                      "repo": "soyPeter/agentic-harness",
                                                                      "ref": "v" + version}}},
            "enabledPlugins": {PLUGIN: True}, "disableAllHooks": False}


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
    """Releases v0.26.1 (before thin mode), v<VERSION> (this checkout) and v99.0.0, a later one that changes a harness
    file, a backbone document, two of the container pack's files, the shim, the settings fragment (a permission rule
    more, LATER_RULE, and one fewer, DROPPED_RULE) and harness.conf."""
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
    for name in ("payload/owned/AGENTS.md", "payload/owned/backbone/8-WORKFLOW.md", "plugin/pre-commit",
                 "catalog/container/install/" + PACK_FILE, "catalog/container/install/" + PACK_DOC):
        with open(str(source / name), "a") as handle:
            handle.write("# 99.0.0\n")
    with open(str(source / "payload/seed/backbone/harness.conf"), "a") as handle:
        handle.write('\n# A setting new in 99.0.0.\nHARNESS_LATER_SETTING="off"\n')
    fragment = json.loads((source / "payload/settings.fragment.json").read_text())
    fragment["permissions"]["allow"].remove(DROPPED_RULE)
    fragment["permissions"]["allow"].append(LATER_RULE)
    (source / "payload/settings.fragment.json").write_text(json.dumps(fragment, indent=2) + "\n")
    run(source, env, "git", "commit", "-qam", "later release")
    run(source, env, "git", "tag", "v99.0.0")


def install_full(project, env, settings=USER_SETTINGS):
    """A committed full install of this checkout over the user's settings (None: no settings file), installed on
    INSTALLED."""
    project.mkdir()
    run(project, env, "git", "init", "-q", "-b", "main")
    if settings is not None:
        (project / ".claude").mkdir()
        (project / ".claude/settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    run(project, env, ROOT / "bootstrap.sh", project, "--name", "demo")
    lock = json.loads((project / LOCK).read_text())
    lock["installed"] = INSTALLED
    (project / LOCK).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
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

    def edit(self, *names, project=None):
        """Append a local edit to each file; returns their edited contents."""
        project = project or self.project
        for name in names:
            with open(str(project / name), "a") as handle:
                handle.write("# local edit\n")
        return {name: (project / name).read_bytes() for name in names}

    def init_thin(self, name="thin"):
        """A committed project that init --thin installed."""
        project = self.work / name
        project.mkdir()
        self.git("init", "-q", "-b", "main", project=project)
        self.run_at(project, "python3", "-B", LAUNCHER, "init", "--thin", "--name", "demo")
        self.commit("chore: adopt agentic harness", project=project)
        return project

    def adopt_container(self, project=None):
        project = project or self.project
        (project / "backbone/adr/ADR-002-containers.md").write_text(ADR)
        self.run_at(project, "python3", "-B", LAUNCHER, "adopt", "container", "--adr", "ADR-002", "--with", "podman")
        return self.commit("chore: adopt the container pack", hooks=False, project=project)

    def locally_edited(self, project=None):
        """The harness files update.sh status reports as edited locally."""
        status = self.update("status", project or self.project, project=project).stdout
        return sorted(line.split()[-1] for line in status.splitlines() if line.split()[:2] == ["edited", "locally"])


class Conversion(Fixture):
    def test_switching_to_thin_and_back_gives_back_the_full_install(self):
        installed = self.git("rev-parse", "HEAD").stdout.strip()
        harness_docs = {name: digest for name, digest in self.lock()["files"].items() if name.startswith("backbone/")}
        result = self.update("--to-thin", self.project)
        self.assertIn("thin mode", result.stdout)
        for name in ("AGENTS.md", "scripts/harness", ".claude/agents", ".claude/skills", ".codex", ".opencode",
                     ".devcontainer"):
            self.assertFalse((self.project / name).exists(), name)
        self.assertEqual(self.lock(), {"mode": "thin", "version": VERSION, "commit": self.tag_commit(VERSION),
                                       "installed": INSTALLED, "kept": harness_docs})
        self.assertEqual((self.project / SHIM).read_bytes(), self.release("plugin/pre-commit"))
        self.assertTrue(os.access(str(self.project / SHIM), os.X_OK))
        self.assertEqual(self.hooks_path(), ".githooks")
        self.assertEqual(json.loads((self.project / ".claude/settings.json").read_text()),
                         dict(USER_SETTINGS, **plugin_entries(VERSION)))
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
        env = dict(self.env, BASE_REF="origin/review-base", RUNNER_TEMP=str(runner), GITHUB_ENV=str(runner / "github-env"))
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

        result = self.update("--to-full", self.project)
        self.assertIn("keep      backbone/8-WORKFLOW.md", result.stdout)
        self.assertEqual((self.project / "backbone/8-WORKFLOW.md").read_bytes(), edited["backbone/8-WORKFLOW.md"])
        self.assertFalse((self.project / "backbone/8-WORKFLOW.md.harness-new").exists())
        for name in edits + (WORKFLOW,):
            with self.subTest(name=name):
                self.assertEqual((self.project / name).read_bytes(), self.release("payload/owned/" + name))
                self.assertEqual((self.project / (name + ".harness-bak")).read_bytes(), edited[name])
        self.assertEqual(self.lock()["harness_version"], VERSION)
        self.assertEqual(self.locally_edited(), ["backbone/8-WORKFLOW.md"])

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
        project = self.init_thin()
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

    def test_a_project_installed_in_thin_mode_switches_to_full_after_the_pin_moved(self):
        project = self.init_thin()
        self.adopt_container(project)
        edited = self.edit("backbone/HOOKS.md", project=project)
        self.commit("chore: a local harness edit", hooks=False, project=project)
        self.run_at(project, "python3", "-B", LAUNCHER, "pin", "99.0.0")
        self.commit("chore: pin the agentic harness to 99.0.0", project=project)
        result = self.update("--to-full", project, project=project)
        for line in ("update    backbone/8-WORKFLOW.md", "update    " + PACK_FILE, "keep      backbone/HOOKS.md"):
            self.assertIn(line, result.stdout)
        for name, source in (("backbone/8-WORKFLOW.md", "payload/owned/backbone/8-WORKFLOW.md"),
                             (PACK_FILE, "catalog/container/install/" + PACK_FILE)):
            self.assertEqual((project / name).read_bytes(), self.release(source, "99.0.0"), name)
        self.assertEqual((project / "backbone/HOOKS.md").read_bytes(), edited["backbone/HOOKS.md"])
        self.assertEqual(self.locally_edited(project), ["backbone/HOOKS.md"])

    def test_adopted_packs_stay_in_the_project(self):
        installed = self.adopt_container()
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
        self.assertEqual({key: self.lock()[key] for key in ("mode", "version", "commit")},
                         {"mode": "thin", "version": "99.0.0", "commit": self.tag_commit("99.0.0")})
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        self.assertEqual(settings["extraKnownMarketplaces"]["agentic-harness"]["source"]["ref"], "v99.0.0")
        self.assertEqual((self.project / SHIM).read_bytes(), self.release("plugin/pre-commit", "99.0.0"))
        self.commit("chore: switch the agentic harness to thin mode")
        self.update("--to-full", self.project)
        self.assertEqual(self.lock()["harness_version"], "99.0.0")
        for name in ("AGENTS.md", "backbone/8-WORKFLOW.md"):
            self.assertEqual((self.project / name).read_bytes(), self.release("payload/owned/" + name, "99.0.0"))
        self.assertIn(LATER_RULE, json.loads((self.project / ".claude/settings.json").read_text())[
            "permissions"]["allow"])
        self.assertIn(LATER_SETTING, (self.project / "backbone/harness.conf").read_text())
        self.assertFalse((self.project / ".githooks").exists())

    def test_switching_back_after_the_pin_moved_works_like_update_sh(self):
        """Release 99.0.0 changes AGENTS.md, backbone/8-WORKFLOW.md and two of the container pack's files."""
        self.adopt_container()
        edited = self.edit(PACK_DOC, "backbone/HOOKS.md")
        self.commit("chore: local harness edits", hooks=False)
        self.update("--to-thin", self.project)
        self.commit("chore: switch the agentic harness to thin mode")
        self.run_at(self.project, "python3", "-B", LAUNCHER, "pin", "99.0.0")
        self.commit("chore: pin the agentic harness to 99.0.0")
        edited.update(self.edit(WORKFLOW))
        self.commit("chore: a local edit to the CI check", hooks=False)

        result = self.update("--to-full", self.project, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for line in ("update    backbone/8-WORKFLOW.md", "update    " + PACK_FILE, "keep      backbone/HOOKS.md",
                     "keep      " + WORKFLOW, "CONFLICT  " + PACK_DOC):
            self.assertIn(line, result.stdout)
        for name, source in (("AGENTS.md", "payload/owned/AGENTS.md"),
                             ("backbone/8-WORKFLOW.md", "payload/owned/backbone/8-WORKFLOW.md"),
                             (PACK_FILE, "catalog/container/install/" + PACK_FILE),
                             (PACK_DOC + ".harness-new", "catalog/container/install/" + PACK_DOC)):
            self.assertEqual((self.project / name).read_bytes(), self.release(source, "99.0.0"), name)
        for name, data in edited.items():
            self.assertEqual((self.project / name).read_bytes(), data, name)
        self.assertEqual(sorted(path.relative_to(self.project).as_posix()
                                for path in self.project.rglob("*.harness-new")), [PACK_DOC + ".harness-new"])
        self.assertIn(LATER_SETTING, (self.project / "backbone/harness.conf").read_text())
        self.assertEqual((self.lock()["harness_version"], self.lock()["installed"]), ("99.0.0", INSTALLED))
        self.assertEqual(self.locally_edited(), sorted(edited))

    def test_switching_there_and_back_twice_ends_where_it_started(self):
        self.edit("AGENTS.md", "backbone/8-WORKFLOW.md")
        self.commit("chore: local harness edits", hooks=False)
        states = []
        for direction in ("--to-thin", "--to-full", "--to-thin", "--to-full"):
            result = self.update(direction, self.project)
            self.assertNotIn("CONFLICT", result.stdout)
            self.commit("chore: switch the agentic harness (%s)" % direction)
            files, hooks, _ = self.snapshot()
            states.append((files, hooks, self.lock()))
        self.assertEqual(states[2], states[0])
        self.assertEqual(states[3], states[1])

    def test_the_switch_takes_out_only_what_the_harness_added_to_the_settings(self):
        project = self.work / "no settings"
        install_full(project, self.env, settings=None)
        installed = (project / ".claude/settings.json").read_bytes()
        self.update("--to-thin", project, project=project)
        self.assertEqual(json.loads((project / ".claude/settings.json").read_text()), plugin_entries(VERSION))
        self.commit("chore: switch the agentic harness to thin mode", project=project)
        self.update("--to-full", project, project=project)
        self.assertEqual((project / ".claude/settings.json").read_bytes(), installed)

    def test_switching_to_another_release_takes_out_the_installed_release_s_rules(self):
        """The installed release added DROPPED_RULE, which v99.0.0 no longer has; LATER_RULE, new in v99.0.0, is the
        user's own here."""
        own = dict(USER_SETTINGS, permissions={"allow": [LATER_RULE], "deny": ["Read(./.env)"]})
        project = self.work / "own rule"
        install_full(project, self.env, settings=own)
        self.assertIn(DROPPED_RULE, json.loads((project / ".claude/settings.json").read_text())["permissions"]["allow"])
        self.update("--to-thin", project, "--version", "99.0.0", project=project)
        self.assertEqual(json.loads((project / ".claude/settings.json").read_text()),
                         dict(own, **plugin_entries("99.0.0")))

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


class Packs(Fixture):
    """harness.py adopt and adopt --remove in a project switched to thin mode. Its lock keeps the hashes of the packs'
    files under "kept" and has no "files": verify takes a lock with "files" for a full install's and refuses every
    change to .claude/settings.json."""

    def harness(self, *args, check=True):
        return self.run_at(self.project, "python3", "-B", LAUNCHER, *args, check=check)

    def switch_to_thin(self, hooks=True):
        self.update("--to-thin", self.project)
        self.commit("chore: switch the agentic harness to thin mode", hooks=hooks)

    def change_the_settings(self):
        """Commit a change to .claude/settings.json through the hooks."""
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        settings["permissions"]["deny"].append("Read(./secrets/**)")
        (self.project / ".claude/settings.json").write_text(json.dumps(settings, indent=2) + "\n")
        self.commit("chore: deny reading secrets")

    def test_a_pack_is_adopted_again_after_the_pin_moved(self):
        """Release 99.0.0 changes two of the container pack's files. Removing the pack at the end shows that the lock
        holds the hashes of the files adopt installed."""
        self.adopt_container()
        packed = self.lock()["adopted"]["container"]["files"]
        self.switch_to_thin()
        self.harness("pin", "99.0.0")
        self.commit("chore: pin the agentic harness to 99.0.0")
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in packed:
            self.assertEqual((self.project / name).read_bytes(),
                             self.release("catalog/container/install/" + name, "99.0.0"), name)
        self.commit("chore: adopt the container pack of 99.0.0")
        self.change_the_settings()
        result = self.harness("adopt", "--remove", "container")
        for name in packed:
            self.assertIn("remove  " + name, result.stdout)
            self.assertFalse((self.project / name).exists(), name)

    def test_removing_a_pack_deletes_the_files_nobody_edited(self):
        self.adopt_container()
        packed = self.lock()["adopted"]["container"]["files"]
        edited = self.edit(PACK_DOC)
        self.commit("chore: a local edit to a pack file", hooks=False)
        self.switch_to_thin()
        result = self.harness("adopt", "--remove", "container")
        self.assertIn("kept    %s (edited locally" % PACK_DOC, result.stdout)
        self.assertEqual((self.project / PACK_DOC).read_bytes(), edited[PACK_DOC])
        for name in sorted(set(packed) - {PACK_DOC}):
            self.assertIn("remove  " + name, result.stdout)
            self.assertFalse((self.project / name).exists(), name)
        self.git("checkout", "HEAD", "--", PACK_FILE)
        own = (self.project / PACK_FILE).read_bytes()
        self.commit("chore: remove the container pack but keep its skill")

        result = self.update("--to-full", self.project)
        for name in (PACK_FILE, PACK_DOC):
            self.assertNotIn(" " + name, result.stdout)
        self.assertEqual((self.project / PACK_FILE).read_bytes(), own)
        self.assertEqual((self.project / PACK_DOC).read_bytes(), edited[PACK_DOC])

    def test_adopting_a_pack_again_without_an_option_removes_the_option_s_files(self):
        (self.project / "backbone/adr/ADR-003-java.md").write_text(JAVA_ADR)
        self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,junit5-assertj,no-lombok")
        self.commit("chore: adopt the java pack", hooks=False)
        self.switch_to_thin(hooks=False)
        result = self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,no-lombok",
                              "--without", "junit5-assertj")
        for name in JAVA_TEST_FILES:
            self.assertIn("remove  " + name, result.stdout)
            self.assertFalse((self.project / name).exists(), name)
            self.assertNotIn(name, self.lock()["kept"])

    def test_removing_a_pack_moves_the_hashes_an_earlier_engine_recorded_under_files(self):
        """An earlier engine recorded a thin project's pack hashes under "files". Removing one pack must move the
        hashes of the packs that stay to "kept", or the next settings commit is refused as a full install's."""
        (self.project / "backbone/adr/ADR-003-java.md").write_text(JAVA_ADR)
        self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,junit5-assertj,no-lombok")
        self.adopt_container()
        self.env = dict(self.env, SKIP_BUILD="1")
        self.switch_to_thin()
        lock = self.lock()
        names =self.lock()["adopted"]["container"]["files"] + self.lock()["adopted"]["java"]["files"]
        lock["files"] = {name: lock["kept"].pop(name) for name in names}
        (self.project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
        self.commit("chore: the lock an earlier engine's adopt left", hooks=False)
        self.harness("adopt", "--remove", "container")
        self.assertNotIn("files", self.lock())
        self.change_the_settings()

    def test_pinning_moves_the_hashes_an_earlier_engine_recorded_under_files(self):
        self.adopt_container()
        self.switch_to_thin()
        lock = self.lock()
        packed = self.lock()["adopted"]["container"]["files"]
        lock["files"] = {name: lock["kept"].pop(name) for name in packed}
        (self.project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
        self.commit("chore: the lock an earlier engine's adopt left", hooks=False)
        self.harness("pin", "99.0.0")
        self.commit("chore: pin the agentic harness to 99.0.0")
        self.assertNotIn("files", self.lock())
        self.assertEqual(sorted(name for name in packed if name in self.lock()["kept"]), sorted(packed))
        self.change_the_settings()

    def test_adopting_a_pack_again_moves_the_hashes_an_earlier_engine_recorded_under_files(self):
        """An earlier engine's adopt recorded a thin project's pack files under "files"."""
        self.adopt_container()
        packed = self.lock()["adopted"]["container"]["files"]
        self.switch_to_thin()
        lock = self.lock()
        lock["files"] = {name: lock["kept"].pop(name) for name in packed}
        (self.project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
        self.commit("chore: the lock an earlier engine's adopt left", hooks=False)
        self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman")
        self.commit("chore: adopt the container pack again")
        self.change_the_settings()
        result = self.harness("adopt", "--remove", "container")
        for name in packed:
            self.assertIn("remove  " + name, result.stdout)

    def test_adopting_a_pack_again_after_the_pin_moved_keeps_an_edited_file(self):
        """Release 99.0.0 changes SKILL.md, which the user edited: adopt keeps the edit, writes the release's copy
        beside it and exits 1, as update.sh does. The lock records the release's copy, as update.sh does, so the
        next adoption is clean once the user has merged."""
        self.adopt_container()
        edited = self.edit(PACK_FILE)
        self.commit("chore: a local edit to a pack file", hooks=False)
        self.switch_to_thin()
        self.harness("pin", "99.0.0")
        self.commit("chore: pin the agentic harness to 99.0.0")
        release = self.release("catalog/container/install/" + PACK_FILE, "99.0.0")
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CONFLICT %s" % PACK_FILE, result.stdout)
        self.assertEqual(content(self.project / PACK_FILE), edited[PACK_FILE])
        self.assertEqual(content(self.project / (PACK_FILE + ".harness-new")), release)
        self.assertEqual(self.lock()["kept"][PACK_FILE], hashlib.sha256(release).hexdigest())
        self.assertEqual(content(self.project / PACK_DOC),
                         self.release("catalog/container/install/" + PACK_DOC, "99.0.0"))
        self.assertFalse((self.project / (PACK_DOC + ".harness-new")).exists())

    def test_adopting_a_pack_again_moves_an_edited_option_file_s_hash_out_of_files(self):
        """An earlier engine recorded a thin project's pack files under "files", and verify reads a non-empty "files"
        as a full install. The edited option file the re-adoption drops is no longer a harness file, so the lock
        keeps no hash for it under either table."""
        (self.project / "backbone/adr/ADR-003-java.md").write_text(JAVA_ADR)
        self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,junit5-assertj,no-lombok")
        self.commit("chore: adopt the java pack", hooks=False)
        edited = self.edit(JAVA_TEST_FILES[1])
        self.commit("chore: a local edit to an option file", hooks=False)
        self.switch_to_thin(hooks=False)
        lock = self.lock()
        recorded = lock["kept"][JAVA_TEST_FILES[1]]
        lock["files"] = {name: lock["kept"].pop(name) for name in JAVA_TEST_FILES}
        (self.project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
        self.commit("chore: the lock an earlier engine's adopt left", hooks=False)
        result = self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,no-lombok",
                              "--without", "junit5-assertj", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(content(self.project / JAVA_TEST_FILES[1]), edited[JAVA_TEST_FILES[1]])
        lock = self.lock()
        self.assertFalse(lock.get("files"))
        self.assertNotIn(JAVA_TEST_FILES[1], lock["kept"])
        self.assertTrue(recorded)
        self.commit("chore: adopt the java pack without junit5-assertj", hooks=False)
        self.env = dict(self.env, SKIP_BUILD="1")
        self.change_the_settings()


class AdoptEdits(Fixture):
    """harness.py adopt in a full install. A pack file the user edited is never overwritten: when the release changed
    it too, the release's copy goes to <file>.harness-new and adopt exits 1, as update.sh does. The release is the
    vendored catalog, which a later release would replace."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(cls.shared.name).resolve()
        env, cls.adopted = environment(cls.source, base), base / "adopted with container"
        shutil.copytree(str(cls.template), str(cls.adopted), symlinks=True)
        (cls.adopted / "backbone/adr/ADR-002-containers.md").write_text(ADR)
        run(cls.adopted, env, "python3", "-B", "scripts/harness/lib/harness.py", "adopt", "container", "--adr",
            "ADR-002", "--with", "podman")
        run(cls.adopted, env, "git", "add", "-A")
        run(cls.adopted, env, "git", "commit", "-qm", "chore: adopt the container pack", "--no-verify")
        cls.packed = sorted(json.loads((cls.adopted / LOCK).read_text())["adopted"]["container"]["files"])

    def harness(self, *args, project=None, check=True):
        return self.run_at(project or self.project, "python3", "-B", "scripts/harness/lib/harness.py", *args,
                           check=check)

    def adopt_container(self):
        (self.project / "backbone/adr/ADR-002-containers.md").write_text(ADR)
        self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman")
        self.commit("chore: adopt the container pack", hooks=False)

    def release_changes(self, project, *names):
        """The vendored catalog as a later release ships it: each named file gets a line."""
        for name in names:
            with open(str(project / CATALOG_INSTALL / name), "a") as handle:
                handle.write("# next release\n")
        self.commit("chore: the vendored catalog as a later release ships it", hooks=False, project=project)

    def test_adopting_again_after_the_release_changed_an_edited_file_keeps_the_edit(self):
        self.adopt_container()
        edited = self.edit(PACK_FILE)
        self.commit("chore: a local edit to a pack file", hooks=False)
        self.release_changes(self.project, PACK_FILE)
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CONFLICT %s" % PACK_FILE, result.stdout)
        self.assertEqual(content(self.project / PACK_FILE), edited[PACK_FILE])
        self.assertEqual(content(self.project / (PACK_FILE + ".harness-new")),
                         content(self.project / CATALOG_INSTALL / PACK_FILE))
        self.assertFalse((self.project / (PACK_DOC + ".harness-new")).exists())

    def test_adopting_again_with_the_same_release_keeps_the_edit_without_a_conflict(self):
        self.adopt_container()
        edited = self.edit(PACK_FILE)
        self.commit("chore: a local edit to a pack file", hooks=False)
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(content(self.project / PACK_FILE), edited[PACK_FILE])
        self.assertFalse((self.project / (PACK_FILE + ".harness-new")).exists())

    def conflict_then_release_again(self):
        """The user edited a pack file and release 1 changed it too, so adopt wrote the release's copy beside it;
        release 2 then changes the file again."""
        self.adopt_container()
        self.edit(PACK_FILE)
        self.commit("chore: a local edit to a pack file", hooks=False)
        self.release_changes(self.project, PACK_FILE)
        self.assertEqual(self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
                         .returncode, 1)
        self.release_changes(self.project, PACK_FILE)

    def test_once_the_conflict_is_merged_adopting_again_is_clean(self):
        """update.sh records the release's copy on a conflict, so after the user merges and deletes .harness-new, the
        next adoption (here with the same options) reports no conflict and writes nothing."""
        self.adopt_container()
        self.edit(PACK_FILE)
        self.commit("chore: a local edit to a pack file", hooks=False)
        self.release_changes(self.project, PACK_FILE)
        self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        merged = (self.project / PACK_FILE).read_bytes() + b"# merged by hand\n"
        (self.project / PACK_FILE).write_bytes(merged)
        (self.project / (PACK_FILE + ".harness-new")).unlink()
        self.commit("chore: merge the new version of a pack file", hooks=False)
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("CONFLICT", result.stdout)
        self.assertEqual(content(self.project / PACK_FILE), merged)
        self.assertFalse((self.project / (PACK_FILE + ".harness-new")).exists())

    def test_adopting_again_refuses_to_overwrite_a_harness_new_from_an_earlier_adoption(self):
        """A half-merged .harness-new holds the user's work: a later conflict on the same file is refused before
        anything is written, and the file is left as it is."""
        self.conflict_then_release_again()
        half_merged = b"half merged, not yet copied back\n"
        (self.project / (PACK_FILE + ".harness-new")).write_bytes(half_merged)
        self.commit("chore: half-merge the new version of a pack file", hooks=False)
        before = self.snapshot()
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(PACK_FILE + ".harness-new already exists", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(content(self.project / (PACK_FILE + ".harness-new")), half_merged)

    def test_removing_a_pack_reports_a_harness_new_it_leaves_behind(self):
        self.conflict_then_release_again()
        result = self.harness("adopt", "--remove", "container")
        self.assertIn("left    %s.harness-new" % PACK_FILE, result.stdout)
        self.assertTrue((self.project / (PACK_FILE + ".harness-new")).is_file())

    def test_adopting_again_without_merging_reports_the_pending_harness_new_and_exits_1(self):
        self.adopt_container()
        self.edit(PACK_FILE)
        self.commit("chore: a local edit to a pack file", hooks=False)
        self.release_changes(self.project, PACK_FILE)
        self.assertEqual(self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
                         .returncode, 1)
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("pending %s.harness-new" % PACK_FILE, result.stdout)
        self.assertTrue((self.project / (PACK_FILE + ".harness-new")).is_file())

    if given is None:
        def test_adopting_again_keeps_every_edited_file_and_writes_the_release_copy_beside_it(self):
            self.skipTest("needs hypothesis (pip install -r tests/requirements.txt)")
    else:
        @settings(max_examples=examples(8), deadline=None, database=None, suppress_health_check=list(HealthCheck))
        @given(data=st.data())
        def test_adopting_again_keeps_every_edited_file_and_writes_the_release_copy_beside_it(self, data):
            edits = data.draw(st.sets(st.sampled_from(self.packed)), label="edited")
            changed = data.draw(st.sets(st.sampled_from(self.packed)), label="changed by the release")
            project = self.copy_of(self.adopted, "example")
            try:
                self.check_readoption(project, edits, changed)
            finally:
                shutil.rmtree(str(project), ignore_errors=True)

    def check_readoption(self, project, edits, changed):
        edited = self.edit(*sorted(edits), project=project)
        self.release_changes(project, *sorted(changed))
        conflicts = edits & changed
        result = self.harness("adopt", "container", "--adr", "ADR-002", "--with", "podman", project=project,
                              check=False)
        self.assertEqual(result.returncode, 1 if conflicts else 0, result.stdout + result.stderr)
        recorded = json.loads((self.adopted / LOCK).read_text())["files"]
        lock = self.lock(project)
        for name in self.packed:
            release = content(project / CATALOG_INSTALL / name)
            self.assertEqual(content(project / name), edited.get(name, release), name)
            self.assertEqual(content(project / (name + ".harness-new")), release if name in conflicts else None, name)
            if name in edits:
                expected = hashlib.sha256(release).hexdigest() if name in conflicts else recorded[name]
                self.assertEqual((lock.get("files") or {}).get(name) or lock["kept"].get(name), expected, name)


class OptionRemoval(Fixture):
    """harness.py adopt in a full install drops an option whose file the user edited. The file stays, and since it is
    no longer a harness file the lock records no hash for it, so doctor doesn't warn about it on every run."""

    def harness(self, *args, check=True):
        return self.run_at(self.project, "python3", "-B", LAUNCHER, *args, check=check)

    def test_an_edited_option_file_the_pack_drops_is_no_longer_a_harness_file(self):
        (self.project / "backbone/adr/ADR-003-java.md").write_text(JAVA_ADR)
        self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,junit5-assertj,no-lombok")
        self.commit("chore: adopt the java pack", hooks=False)
        edited = self.edit(JAVA_TEST_FILES[1])
        self.commit("chore: a local edit to an option file", hooks=False)
        result = self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,no-lombok",
                              "--without", "junit5-assertj", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("kept    %s (edited locally" % JAVA_TEST_FILES[1], result.stdout)
        self.assertEqual(content(self.project / JAVA_TEST_FILES[1]), edited[JAVA_TEST_FILES[1]])
        self.assertNotIn(JAVA_TEST_FILES[1], self.lock()["files"])
        doctor = self.harness("doctor", check=False)
        self.assertNotIn(JAVA_TEST_FILES[1], doctor.stdout)

    def test_an_edited_option_file_the_pack_dropped_comes_back_as_an_edited_pack_file(self):
        """Adding the option back keeps the user's edit and writes the release's copy beside it, as for any edited pack
        file, rather than refusing the project file the dropped option left behind."""
        (self.project / "backbone/adr/ADR-003-java.md").write_text(JAVA_ADR)
        self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,junit5-assertj,no-lombok")
        self.commit("chore: adopt the java pack", hooks=False)
        edited = self.edit(JAVA_TEST_FILES[1])
        self.commit("chore: a local edit to an option file", hooks=False)
        dropped = self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,no-lombok",
                               "--without", "junit5-assertj", check=False)
        self.assertEqual(dropped.returncode, 0, dropped.stdout + dropped.stderr)
        self.commit("chore: drop the junit5-assertj option", hooks=False)
        result = self.harness("adopt", "java", "--adr", "ADR-003", "--with", "gradle,junit5-assertj,no-lombok",
                              check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CONFLICT %s" % JAVA_TEST_FILES[1], result.stdout)
        self.assertEqual(content(self.project / JAVA_TEST_FILES[1]), edited[JAVA_TEST_FILES[1]])
        self.assertTrue((self.project / (JAVA_TEST_FILES[1] + ".harness-new")).is_file())
        self.assertNotIn("dropped", self.lock()["adopted"]["java"])


class PackProperties(Fixture):
    """For any set of the container pack's files the user edited in a project switched to thin mode, and wherever its
    lock records their hashes (under "kept", or under "files" as an earlier engine's adopt did; a different hash also
    under "kept" checks that "files" comes first, as in update.sh --to-full), adopt --remove deletes exactly the others
    and keeps the edited ones, and the lock no longer records any of them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(cls.shared.name).resolve()
        env, cls.thin = environment(cls.source, base), base / "thin with container"
        shutil.copytree(str(cls.template), str(cls.thin), symlinks=True)
        (cls.thin / "backbone/adr/ADR-002-containers.md").write_text(ADR)
        run(cls.thin, env, "python3", "-B", LAUNCHER, "adopt", "container", "--adr", "ADR-002", "--with", "podman")
        run(cls.thin, env, "git", "add", "-A")
        run(cls.thin, env, "git", "commit", "-qm", "chore: adopt the container pack", "--no-verify")
        run(cls.thin, env, UPDATE, "--to-thin", cls.thin)
        run(cls.thin, env, "git", "add", "-A")
        run(cls.thin, env, "git", "commit", "-qm", "chore: switch the agentic harness to thin mode")
        cls.packed = sorted(json.loads((cls.thin / LOCK).read_text())["adopted"]["container"]["files"])

    if given is None:
        def test_removing_a_pack_keeps_exactly_the_edited_files(self):
            self.skipTest("needs hypothesis (pip install -r tests/requirements.txt)")
    else:
        @settings(max_examples=examples(6), deadline=None, database=None, suppress_health_check=list(HealthCheck))
        @given(data=st.data())
        def test_removing_a_pack_keeps_exactly_the_edited_files(self, data):
            edits = data.draw(st.sets(st.sampled_from(self.packed)), label="edited")
            under_files = data.draw(st.sets(st.sampled_from(self.packed)), label="recorded under files")
            project = self.copy_of(self.thin, "example")
            try:
                self.check_removal(project, edits, under_files)
            finally:
                shutil.rmtree(str(project), ignore_errors=True)

    def check_removal(self, project, edits, under_files):
        lock = self.lock(project)
        lock["files"] = {name: lock["kept"][name] for name in sorted(under_files)}
        lock["kept"].update(dict.fromkeys(under_files, OTHER_HASH))
        (project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
        edited = self.edit(*sorted(edits), project=project)
        self.commit("chore: local edits to the pack", hooks=False, project=project)
        result = self.run_at(project, "python3", "-B", LAUNCHER, "adopt", "--remove", "container")
        for name in self.packed:
            self.assertEqual(content(project / name), edited.get(name), name)
            self.assertIn(("kept    %s (edited locally" if name in edits else "remove  %s") % name, result.stdout)
        lock = self.lock(project)
        self.assertEqual(sorted(set(self.packed) & (set(lock.get("files", {})) | set(lock.get("kept", {})))), [])


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

        def installed_release(version):
            def apply(project):
                lock = self.lock(project)
                lock["harness_version"] = version
                (project / LOCK).write_text(json.dumps(lock, indent=2) + "\n")
            return apply

        cases = (
            ("a change not committed", edit("backbone/1-PRD.md"), (), "uncommitted changes"),
            ("an untracked file", edit("notes.txt"), (), "uncommitted changes"),
            ("a release that was not published", None, ("--version", "9.9.9"), "release v9.9.9 was not found"),
            ("a release from before thin mode", None, ("--version", "0.26.1"), "does not support thin mode"),
            ("an installed release that was not published, whose permission rules can't be read",
             commit_after(installed_release("9.9.8")), ("--version", VERSION), "the installed release (v9.9.8)"),
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
            ("a lock keeping a file outside the project", commit_after(pin(kept={"../outside.txt": "0" * 64})), (),
             "outside the project"),
            ("a lock whose kept files aren't a table", commit_after(pin(kept=["backbone/8-WORKFLOW.md"])), (),
             "is corrupt"),
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


class Failures(Fixture):
    """A switch that fails part way, here because a write fails, undoes its changes: the project is as it was, and the
    same switch succeeds once the cause is gone."""

    def test_a_switch_that_fails_part_way_is_undone(self):
        if os.geteuid() == 0:
            self.skipTest("root writes read-only files")
        full = self.copy_of(self.template, "full")
        self.edit("AGENTS.md", project=full)
        self.commit("chore: a local harness edit", hooks=False, project=full)
        thin = self.copy_of(full, "thin")
        self.update("--to-thin", thin, project=thin)
        (thin / "backbone/HOOKS.md").chmod(0o755)  # the switch back gives it the release's mode
        self.commit("chore: switch the agentic harness to thin mode", project=thin)

        def read_only_lock(project):
            (project / LOCK).chmod(0o444)
            return lambda: (project / LOCK).chmod(0o644)

        def locked_git_config(project):
            (project / ".git/config.lock").write_text("")
            return (project / ".git/config.lock").unlink

        for template, direction in ((full, "--to-thin"), (thin, "--to-full")):
            for number, (case, prepare) in enumerate((("the lock can't be written", read_only_lock),
                                                       ("git config is locked", locked_git_config))):
                with self.subTest(direction=direction, case=case):
                    project = self.copy_of(template, "%s %d" % (direction, number))
                    before = self.snapshot(project)
                    remove_cause = prepare(project)
                    try:
                        result = self.update(direction, project, check=False, project=project)
                    finally:
                        remove_cause()
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("undid its changes", result.stderr)
                    self.assertEqual(self.snapshot(project), before)
                    self.update(direction, project, project=project)


class Properties(Fixture):
    """For any set of harness files the user edited: the switch to thin mode keeps exactly those, as backups, and
    removes the rest, but leaves backbone/ as it is; the switch back restores every harness file and keeps the
    backups, keeps each edited backbone document without a conflict (the release didn't change), and update.sh status
    reports exactly those documents as edited."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owned = sorted(json.loads((cls.template / LOCK).read_text())["files"])

    if given is None:
        def test_edited_files_are_backed_up_and_restored(self):
            self.skipTest("needs hypothesis (pip install -r tests/requirements.txt)")
    else:
        @settings(max_examples=examples(8), deadline=None, database=None, suppress_health_check=list(HealthCheck))
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
        edited = self.edit(*sorted(edits), project=project)
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

        result = self.update("--to-full", project, check=False, project=project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        kept = sorted(name for name in edits if name.startswith("backbone/"))
        for name in self.owned:
            self.assertEqual(content(project / name), edited[name] if name in kept else original[name], name)
            self.assertIsNone(content(project / (name + ".harness-new")), name)
            self.assertEqual(content(project / (name + ".harness-bak")),
                             None if name.startswith("backbone/") else edited.get(name), name)
        self.assertEqual(self.hooks_path(project), FULL_HOOKS)
        self.assertEqual(self.locally_edited(project), kept)


if __name__ == "__main__":
    unittest.main()
