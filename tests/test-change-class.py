"""Change-Class (the harness's ADR-002) through the public entry points, in throwaway projects.

  class      approve by policy (autonomous)   light lane (the user's mark)   a diff that contradicts it
  docs       when nothing is risky            when the light rules pass      anything but documentation
  refactor   when nothing is risky            when the light rules pass      sensitive paths (as for any class)
  feature    never: the user approves it      when the light rules pass      -
  schema     never: the user approves it      never                          -

A spec without the line counts as feature; a value that isn't one class makes the spec invalid.
The property checks need hypothesis (pip install -r tests/requirements.txt) and are skipped without it.
"""
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


HARNESS = Path(__file__).resolve().parents[1]
CLASSES = ("docs", "refactor", "feature", "schema")
RISKY = "Passwords are hashed before storage."
CHANGES = {   # contents name the task, so every task changes the files again
    "docs": {"README.md": "# Readme for {task}\n", "docs/guide.md": "# Guide for {task}\n"},
    "code": {"src/app.py": "TASK = '{task}'\n"},
    "migration": {"db/migrations/001_init.sql": "-- {task}\nCREATE TABLE t (id int);\n"},
}
SPEC = """# Spec {task}: Item

Task: {task}
PRD: none
{header}
## Context
A change. {context}

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
"""


def declared(change_class):
    return "" if change_class is None else "Change-Class: %s\n" % change_class


def environment(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com", PYTHONDONTWRITEBYTECODE="1",
               HARNESS_VERIFY="off", HARNESS_REVIEW="off", HARNESS_DELIVER="off", HARNESS_TEST_CMD="true")
    env.update(settings)
    return env


def verdict(report):
    return "Done.\n\n```json\n%s\n```" % json.dumps(report)


class Project:
    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        subprocess.run([str(HARNESS / "bootstrap.sh"), str(root)], env=environment(), check=True, capture_output=True)
        self.commit("chore: adopt the harness")

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

    def add_task(self, task, header="", context="", light=False):
        self.write("backbone/specs/%s.md" % task, SPEC.format(task=task, header=header, context=context))
        with open(self.root / "backbone/3-TASKS.md", "a", encoding="utf-8") as tasks:
            tasks.write("- [ ] **Task %s: Item** (spec: backbone/specs/%s.md)%s\n" % (task, task,
                                                                                    " (light)" if light else ""))

    def approve_as_user(self, task):
        with open(self.root / ("backbone/specs/%s.md" % task), "a", encoding="utf-8") as spec:
            spec.write("Approved-by: Ana (2026-11-06)\n")

    def set_marker(self, task, old, new):
        tasks = self.read("backbone/3-TASKS.md")
        self.write("backbone/3-TASKS.md", tasks.replace("- [%s] **Task %s: Item**" % (old, task),
                                                        "- [%s] **Task %s: Item**" % (new, task), 1))

    def task_line(self, task):
        return next(line for line in self.read("backbone/3-TASKS.md").splitlines()
                    if "**Task %s: Item**" % task in line)

    def grill_pass(self, task):
        return self.hook("grill-stop", {"agent_type": "griller", "last_assistant_message": verdict(
            {"verdict": "pass", "task": task, "questions": [], "summary": "s"})})

    def judge_pass(self, task):
        return self.hook("judge-stop", {"agent_type": "judge", "last_assistant_message": verdict(
            {"verdict": "pass", "task": task, "findings": [], "summary": "s",
             "criteria": [{"id": "AC-%s-1" % task, "met": True, "evidence": "e", "tests": ["test_ac"]}],
             "tests": {"command": "true", "result": "passed"}})})

    def start_check(self, task, **settings):
        """The start gate's answer when an agent marks the task [WIP]; the task line itself is left as it is."""
        line = "- [ ] **Task %s: Item**" % task
        return self.hook("pre-tool-use", {"agent_id": "session", "tool_name": "Edit", "tool_input": {
            "file_path": str(self.root / "backbone/3-TASKS.md"), "old_string": line,
            "new_string": line.replace("[ ]", "[WIP]")}}, **settings)


def new_project(test):
    temp = tempfile.TemporaryDirectory(prefix="change class ")
    test.addCleanup(temp.cleanup)
    return Project(Path(temp.name).resolve() / "project")


class SpecRisk(unittest.TestCase):
    # Change-Class   risky text   low risk
    TABLE = (
        (None,         False,       False),
        ("docs",       False,       True),
        ("refactor",   False,       True),
        ("feature",    False,       False),
        ("schema",     False,       False),
        (None,         True,        False),
        ("docs",       True,        False),
        ("refactor",   True,        False),
        ("feature",    True,        False),
        ("schema",     True,        False),
    )

    def setUp(self):
        self.project = new_project(self)

    def test_only_docs_and_refactor_specs_with_nothing_risky_are_low_risk(self):
        for n, (change_class, risky, low) in enumerate(self.TABLE, 1):
            task = "1.%d" % n
            with self.subTest(change_class=change_class, risky=risky):
                self.project.add_task(task, declared(change_class), RISKY if risky else "")

                code, out = self.project.harness("risk", task)

                self.assertEqual(code, 0 if low else 1, out)

    def test_policy_approves_only_docs_and_refactor_specs_with_nothing_risky(self):
        for n, (change_class, risky, low) in enumerate(self.TABLE, 1):
            task = "1.%d" % n
            with self.subTest(change_class=change_class, risky=risky):
                self.project.add_task(task, declared(change_class), RISKY if risky else "")
                self.project.grill_pass(task)

                code, out = self.project.harness("approve", task, HARNESS_AUTONOMY="autonomous")

                approval = self.project.read("backbone/specs/%s.md" % task).split("## Approval")[1]
                if low:
                    self.assertEqual(code, 0, out)
                    self.assertIn("Approved-by: policy:low-risk", approval)
                else:
                    self.assertEqual(code, 1, out)
                    self.assertNotIn("Approved-by:", approval)
                    self.assertIn("BLOCKED: approval", self.project.task_line(task))

    def test_feature_and_schema_go_to_the_user_whatever_else_the_spec_says(self):
        cases = ((None, "no Change-Class declared, so it counts as feature"), ("feature", "Change-Class feature"),
                 ("schema", "Change-Class schema"))
        for n, (change_class, reason) in enumerate(cases, 1):
            task = "2.%d" % n
            with self.subTest(change_class=change_class):
                self.project.add_task(task, declared(change_class))
                self.project.grill_pass(task)

                code, out = self.project.harness("approve", task, HARNESS_AUTONOMY="autonomous")

                self.assertEqual(code, 1, out)
                self.assertIn(reason + ": the user approves it, not policy", out)
                self.assertIn(reason + ": the user approves it, not policy",
                              self.project.read("backbone/escalations.md"))

    def test_risk_and_next_name_the_class(self):
        self.project.add_task("3.1", declared("docs"))
        self.project.add_task("3.2")

        _, docs_risk = self.project.harness("risk", "3.1")
        _, docs_next = self.project.harness("next", "3.1")
        _, default_next = self.project.harness("next", "3.2")

        self.assertIn("Change-Class docs", docs_risk)
        self.assertIn("Change-Class docs", docs_next)
        self.assertIn("Change-Class feature (not declared)", default_next)
        self.assertEqual(json.loads(self.project.harness("next", "3.1", "--json")[1])["change_class"], "docs")
        self.assertEqual(json.loads(self.project.harness("next", "3.2", "--json")[1])["change_class"], "feature")


class LightLane(unittest.TestCase):
    # Change-Class   marked (light)   risky text   light lane
    TABLE = (
        (None,         True,            False,       True),
        ("docs",       True,            False,       True),
        ("refactor",   True,            False,       True),
        ("feature",    True,            False,       True),
        ("schema",     True,            False,       False),
        ("docs",       False,           False,       False),
        ("feature",    False,           False,       False),
        ("docs",       True,            True,        False),
        ("feature",    True,            True,        False),
    )
    LANE = {"HARNESS_LIGHT_LANE": "on"}

    def setUp(self):
        self.project = new_project(self)

    def test_the_user_marks_light_tasks_and_schema_never_takes_the_lane(self):
        for n, (change_class, marked, risky, light) in enumerate(self.TABLE, 1):
            task = "4.%d" % n
            with self.subTest(change_class=change_class, marked=marked, risky=risky):
                self.project.add_task(task, declared(change_class), RISKY if risky else "", light=marked)
                self.project.approve_as_user(task)

                step = json.loads(self.project.harness("next", task, "--json", **self.LANE)[1])
                code, out = self.project.start_check(task, **self.LANE)

                self.assertEqual(step.get("light", False), light, step)
                self.assertEqual(code, 0 if light else 2, out)

    def test_the_start_gate_says_schema_never_takes_the_light_lane(self):
        self.project.add_task("4.1", declared("schema"), light=True)
        self.project.approve_as_user("4.1")

        _, out = self.project.start_check("4.1", **self.LANE)

        self.assertIn("marked (light), but Change-Class schema never takes the light lane", out)

    def test_a_light_feature_still_needs_the_users_approval_in_autonomous_mode(self):
        self.project.add_task("4.1", declared("feature"), light=True)
        self.project.add_task("4.2", declared("docs"), light=True)

        feature_code, feature_out = self.project.harness("approve", "4.1", HARNESS_AUTONOMY="autonomous", **self.LANE)
        docs_code, docs_out = self.project.harness("approve", "4.2", HARNESS_AUTONOMY="autonomous", **self.LANE)

        self.assertEqual(feature_code, 1, feature_out)
        self.assertIn("Change-Class feature: the user approves it, not policy", feature_out)
        self.assertEqual(docs_code, 0, docs_out)
        self.assertIn("Approved-by: policy:low-risk", self.project.read("backbone/specs/4.2.md"))


class Validity(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)

    def test_a_value_that_is_not_one_class_makes_the_spec_invalid(self):
        values = ("chore", "", "<docs | refactor | feature | schema>", "docs refactor", "feature, schema")
        for n, value in enumerate(values, 1):
            task = "5.%d" % n
            with self.subTest(value=value):
                self.project.add_task(task, "Change-Class: %s\n" % value)

                code, out = self.project.harness("spec-check", task)

                self.assertEqual(code, 1, out)
                self.assertIn("Change-Class '%s' is not one of docs, refactor, feature, schema" % value, out)

    def test_two_different_classes_make_the_spec_invalid(self):
        self.project.add_task("5.1", "Change-Class: docs\nChange-Class: schema\n")

        code, out = self.project.harness("spec-check", "5.1")

        self.assertEqual(code, 1, out)
        self.assertIn("Change-Class is declared more than once (docs, schema)", out)

    def test_the_value_is_case_insensitive(self):
        self.project.add_task("5.1", "Change-Class:  DOCS \n")

        self.assertEqual(self.project.harness("spec-check", "5.1")[0], 0)
        self.assertEqual(self.project.harness("risk", "5.1")[0], 0)

    def test_an_invalid_class_fails_the_grill_and_goes_back_to_the_analyst(self):
        self.project.add_task("5.1", "Change-Class: chore\n")

        _, grilled = self.project.grill_pass("5.1")
        step = json.loads(self.project.harness("next", "5.1", "--json")[1])

        self.assertIn("FAIL", grilled)
        self.assertIn("spec: Change-Class 'chore' is not one of", grilled)
        self.assertEqual((step["step"], step["role"]), ("define", "analyst"), step)

    def test_a_class_in_a_comment_or_under_approval_is_not_declared(self):
        self.project.add_task("5.1", "<!--\nChange-Class: docs\n-->\n")
        self.project.add_task("5.2")
        with open(self.project.root / "backbone/specs/5.2.md", "a", encoding="utf-8") as spec:
            spec.write("Change-Class: docs\n")

        for task in ("5.1", "5.2"):
            with self.subTest(task=task):
                code, out = self.project.harness("risk", task)

                self.assertEqual(code, 1, out)
                self.assertIn("no Change-Class declared, so it counts as feature", out)

    def test_the_class_is_part_of_what_the_griller_and_the_user_passed(self):
        self.project.add_task("5.1", declared("docs"))
        self.project.grill_pass("5.1")
        self.project.approve_as_user("5.1")
        spec = self.project.root / "backbone/specs/5.1.md"

        code, out = self.project.hook("pre-tool-use", {"agent_id": "session", "tool_name": "Edit", "tool_input": {
            "file_path": str(spec), "old_string": "Change-Class: docs", "new_string": "Change-Class: refactor"}})
        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

        spec.write_text(spec.read_text(encoding="utf-8").replace("Change-Class: docs", "Change-Class: refactor"),
                        encoding="utf-8")
        _, out = self.project.start_check("5.1")
        self.assertIn("changed after the griller passed it", out)


class DiffRisk(unittest.TestCase):
    # Change-Class   change        low risk
    TABLE = (
        ("docs",       "docs",       True),
        ("docs",       "code",       False),
        ("docs",       "migration",  False),
        ("refactor",   "docs",       True),
        ("refactor",   "code",       True),
        ("refactor",   "migration",  False),
        ("feature",    "docs",       False),
        ("schema",     "migration",  False),
        (None,         "code",       False),
    )

    def setUp(self):
        self.project = new_project(self)

    def receipt(self, task, change_class, files, **settings):
        """The receipt of a judged task whose change is files, measured from the commit before them."""
        self.project.add_task(task, declared(change_class))
        self.project.write("tests/test_ac_%s.py" % task.replace(".", "_"),
                           "def test_ac():  # AC-%s-1\n    pass\n" % task)
        base = self.project.commit("docs: spec for task %s" % task)
        self.project.set_marker(task, " ", "WIP")
        for name, text in files.items():
            self.project.write(name, text.format(task=task))
        self.project.judge_pass(task)
        code, out = self.project.harness("receipt", task, "--base", base, "--json", **settings)
        self.assertEqual(code, 0, out)
        self.project.set_marker(task, "WIP", "x")
        self.project.commit("feat: task %s" % task)
        return json.loads(out)

    def test_a_change_that_contradicts_docs_or_refactor_is_a_risk(self):
        for n, (change_class, change, low) in enumerate(self.TABLE, 1):
            with self.subTest(change_class=change_class, change=change):
                receipt = self.receipt("6.%d" % n, change_class, CHANGES[change])

                self.assertEqual(receipt["risks"] == [], low, receipt["risks"])
                self.assertEqual(receipt["change_class"], change_class or "feature")

    def test_the_receipt_says_which_files_contradict_a_docs_class(self):
        receipt = self.receipt("6.1", "docs", dict(CHANGES["docs"], **CHANGES["code"]))

        self.assertIn("Change-Class docs doesn't cover a change to files that aren't documentation: src/app.py",
                      receipt["risks"])

    def test_the_receipt_heads_its_risks_with_the_class(self):
        self.receipt("6.1", "refactor", CHANGES["code"])

        _, out = self.project.harness("receipt", "6.1", "--base", "HEAD~1")

        self.assertIn("RISKS (Change-Class refactor)", out)

    def test_the_user_says_where_documentation_lives(self):
        site = {"site/index.html": "<h1>Docs for {task}</h1>\n"}

        default = self.receipt("6.1", "docs", site)
        configured = self.receipt("6.2", "docs", site, HARNESS_DOC_PATHS="(^|/)site/")

        self.assertNotEqual(default["risks"], [])
        self.assertEqual(configured["risks"], [])

    def test_a_broken_documentation_regex_counts_nothing_as_documentation(self):
        receipt = self.receipt("6.1", "docs", CHANGES["docs"], HARNESS_DOC_PATHS="(")

        self.assertIn("Change-Class docs doesn't cover a change to files that aren't documentation: README.md, "
                      "docs/guide.md", receipt["risks"])
        self.assertIn("HARNESS_DOC_PATHS is not a valid regex",
                      self.project.harness("doctor", HARNESS_DOC_PATHS="(")[1])

    def test_agents_cannot_say_where_documentation_lives(self):
        conf = self.project.root / "backbone/harness.conf"

        code, out = self.project.hook("pre-tool-use", {"agent_id": "session", "tool_name": "Edit", "tool_input": {
            "file_path": str(conf), "old_string": 'HARNESS_LIGHT_LANE="off"',
            "new_string": 'HARNESS_LIGHT_LANE="off"\nHARNESS_DOC_PATHS=".*"'}})

        self.assertEqual(code, 2, out)
        self.assertIn("HARNESS_DOC_PATHS may only be changed by the user", out)

    def test_a_policy_approved_docs_task_that_changes_code_cannot_finish(self):
        auto = {"HARNESS_AUTONOMY": "autonomous"}
        self.project.add_task("7.1", declared("docs"))
        self.project.write("tests/test_ac.py", "def test_ac():  # AC-7.1-1\n    pass\n")
        self.project.commit("docs: spec for task 7.1")
        self.project.grill_pass("7.1")
        self.assertEqual(self.project.harness("approve", "7.1", **auto)[0], 0)
        self.assertEqual(self.project.harness("start", "7.1", **auto)[0], 0)

        self.project.write("src/app.py", "VALUE = 1\n")
        self.project.judge_pass("7.1")
        code, out = self.project.harness("finish", "7.1", **auto)
        self.assertEqual(code, 1, out)
        self.assertIn("approved by policy as low-risk, but Change-Class docs doesn't cover a change to files that "
                      "aren't documentation: src/app.py", out)

        (self.project.root / "src/app.py").unlink()
        self.project.write("docs/guide.md", "# Guide\n")
        self.project.judge_pass("7.1")
        code, out = self.project.harness("finish", "7.1", **auto)
        self.assertEqual(code, 0, out)


@unittest.skipIf(given is None, "hypothesis is not installed (pip install -r tests/requirements.txt)")
class Properties(unittest.TestCase):
    SENTENCES = ("Nothing else changes.", RISKY, "It moves src/auth/session.py.", "Add an RBAC check.",
                 "Rename the helper in src/app.py.", "It edits db/migrations/002_add.sql.")
    ids = itertools.count(1)

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="change class properties ")
        cls.project = Project(Path(cls.temp.name).resolve() / "project")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def risk(self, header, context=""):
        """(exit code, the reasons on risk's first line) of a new spec."""
        task = "9.%d" % next(self.ids)
        self.project.add_task(task, header, context)
        code, out = self.project.harness("risk", task)
        return code, out.splitlines()[0].split(": ", 1)[1]

    if given is not None:
        line_text = st.text(st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp"), blacklist_characters="<"),
                            max_size=24)
        any_case = st.sampled_from(CLASSES).flatmap(lambda name: st.tuples(
            st.lists(st.booleans(), min_size=len(name), max_size=len(name)), st.sampled_from(("", " ", "\t", "  ")))
            .map(lambda case: case[1] + "".join(c.upper() if up else c for c, up in zip(name, case[0])) + case[1]))

        @settings(max_examples=60, deadline=None)
        @given(value=st.one_of(line_text, any_case))
        def test_spec_check_takes_exactly_one_class_name_in_any_case(self, value):
            task = "8.%d" % next(self.ids)
            self.project.add_task(task, "Change-Class: %s\n" % value)

            _, out = self.project.harness("spec-check", task)

            self.assertEqual("is not one of docs, refactor, feature, schema" in out,
                             value.strip().lower() not in CLASSES, out)

        @settings(max_examples=25, deadline=None)
        @given(context=st.lists(st.sampled_from(SENTENCES), max_size=3),
               change_class=st.sampled_from((None,) + CLASSES))
        def test_no_class_hides_what_the_risk_checks_find(self, context, change_class):
            text = " ".join(context)
            docs_code, docs_reasons = self.risk(declared("docs"), text)

            code, reasons = self.risk(declared(change_class), text)

            if docs_code:
                self.assertEqual(code, 1, reasons)
                self.assertIn(docs_reasons, reasons)
            if change_class in ("docs", "refactor"):
                self.assertEqual((code, reasons), (docs_code, docs_reasons))


if __name__ == "__main__":
    unittest.main()
