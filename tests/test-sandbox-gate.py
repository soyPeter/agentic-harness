"""The sandbox gate (follow-up 4 of the harness's ADR-003): work of a Change-Class may need a sandbox of at least some
isolation class, set by the user in HARNESS_SANDBOX_REQUIRE (default: schema=container).

  where checked              which evidence                                    entry points
  start                      the sandbox the starting session runs in          start, an agent's edit of 3-TASKS.md
  finish                     the sandbox recorded with the latest judge pass   finish, an agent's edit, verify (CI)
  run                        the sandbox its sessions would run in             run (skips the task before any session)

A requirement holds for its class and every class above it on ADR-002's ladder (docs < refactor < feature < schema).
The gate fails closed: a judge pass with no recorded sandbox, an isolation class the harness doesn't know, and a setting
it can't read all refuse. On the host every session is isolation_class none, so these checks start and finish tasks on
the host with the evidence replaced in the verdict file; tests/test-sandbox-egress.py records real container evidence
(HARNESS_E2E=1). The property checks need hypothesis and are skipped without it.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from hypothesis_profiles import examples

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


HARNESS = Path(__file__).resolve().parents[1]
CLASSES = ("docs", "refactor", "feature", "schema")
ISOLATION = ("none", "container", "userspace-kernel", "microVM", "dedicated-VM")
TASKS = {"docs": "1.1", "refactor": "1.2", "feature": "1.3", "schema": "1.4"}
SPEC = """# Spec {task}: Item

Task: {task}
PRD: none
Change-Class: {change_class}

## Context
A change.

## Requirements
- REQ-{task}-1: The system shall do one thing.

## Acceptance criteria
- AC-{task}-1 (REQ-{task}-1): Given a, when b, then c.

## Non-functional requirements
- none

## Architecture
ADRs: ADR-001
Tech requirements:
- Keep the current module layout.

## Skills
- code-quality: all code

## Open questions
- none

## Approval
Approved-by: Ana (2026-11-06)
"""
RECORDED = {"backend": "devcontainer", "base_image_digest": "sha256:" + "a" * 64,
            "allowlist_hash": "sha256:" + "b" * 64, "region": "local", "control_plane": "local",
            "credential_mode": "login", "isolation_reason": "recorded by the test"}


def environment(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com", PYTHONDONTWRITEBYTECODE="1",
               HARNESS_VERIFY="off", HARNESS_REVIEW="off", HARNESS_DELIVER="off", HARNESS_TEST_CMD="true",
               HARNESS_ALLOW_PARALLEL_WIP="1")
    for key in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    env.update(settings)
    return env


def verdict(report):
    return "Done.\n\n```json\n%s\n```" % json.dumps(report)


def sandbox(isolation_class):
    """A recorded sandbox with that isolation class; None is a judge pass recorded before sandbox evidence."""
    return None if isolation_class is None else dict(RECORDED, isolation_class=isolation_class)


class Project:
    """A project whose tasks 1.1 to 1.4 (docs, refactor, feature, schema) are approved, [WIP] and judged."""

    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        subprocess.run([str(HARNESS / "bootstrap.sh"), str(root)], env=environment(), check=True, capture_output=True)
        self.commit("chore: adopt the harness")
        lines = []
        for change_class, task in TASKS.items():
            self.write("backbone/specs/%s.md" % task, SPEC.format(task=task, change_class=change_class))
            lines.append("- [ ] **Task %s: Item** (spec: backbone/specs/%s.md)\n" % (task, task))
        self.write("backbone/3-TASKS.md", self.read("backbone/3-TASKS.md") + "".join(lines))
        self.write("tests/test_ac.py", "".join("def test_ac_%s():  # AC-%s-1\n    pass\n" % (t.replace(".", "_"), t)
                                              for t in TASKS.values()))
        for task in TASKS.values():
            self.hook("grill-stop", {"agent_type": "griller", "last_assistant_message": verdict(
                {"verdict": "pass", "task": task, "questions": [], "summary": "s"})})
        self.base = self.commit("docs: specs for tasks 1.1 to 1.4")

    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=self.root, env=environment(), check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def harness(self, *args, **settings):
        result = subprocess.run(["python3", "-B", str(self.root / "scripts/harness/lib/harness.py")] + list(args),
                                cwd=self.root, env=environment(**settings), capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def hook(self, event, data, **settings):
        result = subprocess.run(["python3", "-B", str(self.root / "scripts/harness/lib/harness.py"), "hook", event],
                                cwd=self.root, input=json.dumps(data), capture_output=True, text=True,
                                env=environment(CLAUDE_PROJECT_DIR=str(self.root), **settings))
        return result.returncode, result.stdout + result.stderr

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, name):
        return (self.root / name).read_text(encoding="utf-8")

    def set_conf(self, **settings):
        """backbone/harness.conf with these settings, as the user writes it."""
        text = self.read("backbone/harness.conf")
        self.write("backbone/harness.conf", text + "".join('%s="%s"\n' % item for item in settings.items()))

    def mark(self, task, old, new):
        tasks = self.read("backbone/3-TASKS.md")
        self.write("backbone/3-TASKS.md", tasks.replace("- [%s] **Task %s: Item**" % (old, task),
                                                        "- [%s] **Task %s: Item**" % (new, task), 1))

    def start_all_and_judge(self):
        """Every task [WIP], as the user marks them, and a judge pass for each on the current code (on the host)."""
        for task in TASKS.values():
            self.mark(task, " ", "WIP")
        self.write("src/app.py", "VALUE = 1\n")
        for task in TASKS.values():
            code, out = self.hook("judge-stop", {"agent_type": "judge", "last_assistant_message": verdict(
                {"verdict": "pass", "task": task, "findings": [], "summary": "s",
                 "criteria": [{"id": "AC-%s-1" % task, "met": True, "evidence": "e", "tests": ["test_ac"]}],
                 "tests": {"command": "true", "result": "passed"}})})
            assert code == 0, out

    def record(self, task, isolation_class):
        """The latest judge pass of task with this sandbox, as if it had been recorded there."""
        path = self.root / ("backbone/.verdicts/%s.judge.json" % task)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isolation_class is None:
            data["history"][-1].pop("sandbox", None)
        else:
            data["history"][-1]["sandbox"] = sandbox(isolation_class)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def tasks_edit(self, task, old, new, **settings):
        """The gates' answer when an agent edits the task's marker; the file is left as it is."""
        line = "- [%s] **Task %s: Item**" % (old, task)
        return self.hook("pre-tool-use", {"agent_id": "session", "tool_name": "Edit", "tool_input": {
            "file_path": str(self.root / "backbone/3-TASKS.md"), "old_string": line,
            "new_string": line.replace("[%s]" % old, "[%s]" % new)}}, **settings)


def new_project(test):
    temp = tempfile.TemporaryDirectory(prefix="sandbox gate ")
    test.addCleanup(temp.cleanup)
    return Project(Path(temp.name).resolve() / "project")


class Finish(unittest.TestCase):
    """Finishing reads the sandbox recorded with the latest judge pass."""
    # HARNESS_SANDBOX_REQUIRE        Change-Class  recorded isolation  finishes
    TABLE = (
        (None,                           "schema",     "none",             False),
        (None,                           "schema",     "container",        True),
        (None,                           "schema",     "microVM",          True),
        (None,                           "schema",     None,               False),
        (None,                           "schema",     "unknown",          False),
        (None,                           "feature",    "none",             True),
        (None,                           "docs",       None,               True),
        ("",                             "schema",     "none",             True),
        ("schema=none",                  "schema",     None,               True),
        ("feature=container",            "refactor",   "none",             True),
        ("feature=container",            "feature",    "none",             False),
        ("feature=container",            "schema",     "none",             False),
        ("feature=container",            "schema",     "container",        True),
        ("refactor=container schema=microVM", "schema", "container",       False),
        ("refactor=container schema=microVM", "schema", "dedicated-VM",    True),
        ("refactor=container schema=microVM", "feature", "container",      True),
        ("refactor=container schema=microVM", "feature", "none",           False),
        ("docs=userspace-kernel",        "docs",       "container",        False),
        ("Schema=MICROVM",               "schema",     "microVM",          True),
    )

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="sandbox gate ")
        cls.addClassCleanup(temp.cleanup)
        cls.project = Project(Path(temp.name).resolve() / "project")
        cls.project.start_all_and_judge()

    def finish_check(self, change_class, isolation_class, requirement):
        task = TASKS[change_class]
        self.project.record(task, isolation_class)
        settings = {} if requirement is None else {"HARNESS_SANDBOX_REQUIRE": requirement}
        return self.project.tasks_edit(task, "WIP", "x", **settings)

    def test_each_class_finishes_only_with_a_judge_pass_recorded_in_the_sandbox_it_requires(self):
        for requirement, change_class, isolation_class, finishes in self.TABLE:
            with self.subTest(requirement=requirement, change_class=change_class, recorded=isolation_class):
                code, out = self.finish_check(change_class, isolation_class, requirement)

                self.assertEqual(code, 0 if finishes else 2, out)

    def test_the_refusal_names_the_class_the_isolation_it_needs_and_what_was_recorded(self):
        code, out = self.finish_check("schema", "none", None)

        self.assertEqual(code, 2, out)
        self.assertIn("Change-Class schema", out)
        self.assertIn("at least container", out)
        self.assertIn("isolation_class none", out)
        self.assertIn("HARNESS_SANDBOX_REQUIRE", out)

    def test_a_judge_pass_without_sandbox_evidence_does_not_count_as_isolated(self):
        code, out = self.finish_check("schema", None, None)

        self.assertEqual(code, 2, out)
        self.assertIn("recorded no sandbox", out)

    def test_an_isolation_class_the_harness_does_not_know_does_not_count(self):
        code, out = self.finish_check("schema", "quantum", None)

        self.assertEqual(code, 2, out)
        self.assertIn("quantum", out)

    def test_a_setting_the_harness_cannot_read_stops_every_finish(self):
        for requirement in ("schema=vm", "schema", "chore=container", "schema=container schema=none"):
            with self.subTest(requirement=requirement):
                code, out = self.finish_check("docs", "dedicated-VM", requirement)

                self.assertEqual(code, 2, out)
                self.assertIn("HARNESS_SANDBOX_REQUIRE", out)

    def test_the_finish_command_applies_the_same_gate(self):
        self.project.record(TASKS["schema"], "none")

        code, out = self.project.harness("finish", TASKS["schema"])

        self.assertEqual(code, 1, out)
        self.assertIn("at least container", out)
        self.assertIn("- [WIP] **Task 1.4: Item**", self.project.read("backbone/3-TASKS.md"))

    if given is not None:
        @settings(max_examples=examples(30), deadline=None)
        @given(named=st.dictionaries(st.sampled_from(CLASSES), st.sampled_from(ISOLATION), max_size=4),
               change_class=st.sampled_from(CLASSES),
               recorded=st.one_of(st.none(), st.sampled_from(ISOLATION + ("unknown",))))
        def test_a_requirement_holds_for_its_class_and_every_class_above_it(self, named, change_class, recorded):
            requirement = " ".join("%s=%s" % item for item in named.items())
            reach = CLASSES[:CLASSES.index(change_class) + 1]
            needed = max([ISOLATION.index(named[c]) for c in reach if c in named] or [0])
            finishes = needed == 0 or (recorded in ISOLATION and ISOLATION.index(recorded) >= needed)

            code, out = self.finish_check(change_class, recorded, requirement)

            self.assertEqual(code, 0 if finishes else 2, out)


class Start(unittest.TestCase):
    """Starting reads the sandbox the starting session runs in: on the host, none."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="sandbox gate ")
        cls.addClassCleanup(temp.cleanup)
        cls.project = Project(Path(temp.name).resolve() / "project")

    def test_schema_work_does_not_start_on_the_host_by_default(self):
        code, out = self.project.tasks_edit(TASKS["schema"], " ", "WIP")

        self.assertEqual(code, 2, out)
        self.assertIn("Change-Class schema", out)
        self.assertIn("at least container", out)
        self.assertIn(".devcontainer/harness-agent/", out)

    def test_other_classes_start_on_the_host_by_default(self):
        for change_class in ("docs", "refactor", "feature"):
            with self.subTest(change_class=change_class):
                code, out = self.project.tasks_edit(TASKS[change_class], " ", "WIP")

                self.assertEqual(code, 0, out)

    def test_the_user_can_lower_the_requirement(self):
        self.project.set_conf(HARNESS_SANDBOX_REQUIRE="")
        self.addCleanup(self.project.git, "checkout", "--", "backbone/harness.conf")

        code, out = self.project.tasks_edit(TASKS["schema"], " ", "WIP")

        self.assertEqual(code, 0, out)

    def test_the_start_command_applies_the_same_gate(self):
        code, out = self.project.harness("start", TASKS["schema"])

        self.assertEqual(code, 1, out)
        self.assertIn("at least container", out)
        self.assertIn("- [ ] **Task 1.4: Item**", self.project.read("backbone/3-TASKS.md"))

    def test_an_unknown_backend_is_no_sandbox_at_all(self):
        code, out = self.project.tasks_edit(TASKS["feature"], " ", "WIP", HARNESS_SANDBOX_BACKEND="e2b",
                                            HARNESS_SANDBOX_REQUIRE="feature=container")

        self.assertEqual(code, 2, out)

    def test_a_setting_the_harness_cannot_read_stops_every_start(self):
        code, out = self.project.tasks_edit(TASKS["docs"], " ", "WIP", HARNESS_SANDBOX_REQUIRE="docs=sandbox")

        self.assertEqual(code, 2, out)
        self.assertIn("HARNESS_SANDBOX_REQUIRE", out)


class Settings(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)

    def test_doctor_reports_a_setting_it_cannot_read_as_an_error(self):
        code, out = self.project.harness("doctor", HARNESS_SANDBOX_REQUIRE="schema=vm")

        self.assertEqual(code, 1, out)
        self.assertIn("ERROR HARNESS_SANDBOX_REQUIRE", out)

    def test_doctor_accepts_the_default_and_an_empty_setting(self):
        for requirement in (None, ""):
            with self.subTest(requirement=requirement):
                settings = {} if requirement is None else {"HARNESS_SANDBOX_REQUIRE": requirement}
                _, out = self.project.harness("doctor", **settings)

                self.assertNotIn("HARNESS_SANDBOX_REQUIRE", out)

    def test_only_the_user_changes_the_requirement(self):
        conf = str(self.project.root / "backbone/harness.conf")
        text = self.project.read("backbone/harness.conf")

        code, out = self.project.hook("pre-tool-use", {"agent_id": "session", "tool_name": "Write", "tool_input": {
            "file_path": conf, "content": text + 'HARNESS_SANDBOX_REQUIRE=""\n'}})

        self.assertEqual(code, 2, out)
        self.assertIn("HARNESS_SANDBOX_REQUIRE may only be changed by the user", out)


class Verify(unittest.TestCase):
    """CI's verify checks the recorded evidence, never the sandbox CI itself runs in."""

    def setUp(self):
        self.project = new_project(self)
        self.project.start_all_and_judge()

    def verify(self):
        return self.project.harness("verify", "--range", "%s..HEAD" % self.project.base, HARNESS_VERIFY="block")

    def test_a_schema_task_finished_with_a_judge_pass_on_the_host_fails_verify(self):
        self.project.mark(TASKS["schema"], "WIP", "x")
        self.project.commit("feat: task 1.4")

        code, out = self.verify()

        self.assertEqual(code, 1, out)
        self.assertIn("at least container", out)

    def test_a_schema_task_finished_with_a_judge_pass_in_a_container_passes_verify(self):
        self.project.record(TASKS["schema"], "container")
        self.project.mark(TASKS["schema"], "WIP", "x")
        self.project.commit("feat: task 1.4")

        code, out = self.verify()

        self.assertEqual(code, 0, out)


class Run(unittest.TestCase):
    """The runner skips a task its sessions couldn't start or finish where they would run, before any session."""

    def setUp(self):
        self.project = new_project(self)
        home = self.project.root.parent / "home"
        home.mkdir()
        (home / ".claude.json").write_text(json.dumps(
            {"projects": {str(self.project.root): {"hasTrustDialogAccepted": True}}}))
        self.home = str(home)

    def run_tasks(self, *args, **settings):
        return self.project.harness("run", *args, HOME=self.home, HARNESS_AUTONOMY="autonomous",
                                    HARNESS_VERIFY="block", **settings)

    def test_a_dry_run_says_which_tasks_the_sandbox_rules_out(self):
        code, out = self.run_tasks("--dry-run")

        self.assertEqual(code, 0, out)
        self.assertIn("would start task 1.3", out)
        self.assertIn("would skip task 1.4", out)
        self.assertIn("at least container", out)

    def test_the_runner_starts_no_session_for_a_task_the_sandbox_rules_out(self):
        marker = self.project.root.parent / "session-started"
        code, out = self.run_tasks("--only", TASKS["schema"], HARNESS_AGENT_CMD="touch %s" % marker)

        self.assertEqual(code, 1, out)
        self.assertIn("sandbox", out)
        self.assertFalse(marker.exists(), out)


class Receipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="sandbox gate ")
        cls.addClassCleanup(temp.cleanup)
        cls.project = Project(Path(temp.name).resolve() / "project")
        cls.project.start_all_and_judge()

    def receipt(self, task):
        code, text = self.project.harness("receipt", task)
        self.assertEqual(code, 0, text)
        code, out = self.project.harness("receipt", task, "--json")
        self.assertEqual(code, 0, out)
        return text, json.loads(out)

    def test_the_receipt_says_what_the_class_requires_and_whether_the_judge_pass_met_it(self):
        self.project.record(TASKS["schema"], "none")
        text, data = self.receipt(TASKS["schema"])

        self.assertEqual(data["sandbox_required"], {"isolation_class": "container", "met": False})
        self.assertIn("required for Change-Class schema (HARNESS_SANDBOX_REQUIRE): container; NOT met", text)

        self.project.record(TASKS["schema"], "container")
        text, data = self.receipt(TASKS["schema"])

        self.assertEqual(data["sandbox_required"], {"isolation_class": "container", "met": True})
        self.assertIn("required for Change-Class schema (HARNESS_SANDBOX_REQUIRE): container; met", text)


if __name__ == "__main__":
    unittest.main()
