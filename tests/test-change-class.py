"""Change-Class (the harness's ADR-002) through the public entry points, in throwaway projects.

  class      approve by policy (autonomous)   light lane (the user's mark)   a diff that contradicts it
  docs       when nothing is risky            when the light rules pass      anything but documentation
  refactor   when nothing is risky            when the light rules pass      sensitive paths (as for any class)
  feature    never: the user approves it      when the light rules pass      -
  schema     never: the user approves it      never                          -

A spec without the line counts as feature; a value that isn't one class makes the spec invalid. The class is read
only where the grill fingerprint reads, so it can't change after the griller and the user passed the spec; a class in
a code block is an example. The Approval section starts at the first '## Approval' heading outside comments and code
blocks, for the fingerprint, the freeze, the class, the risk checks and approval alike, and a heading inside either
makes the spec invalid. Documentation is a file with a documentation extension, and a move counts as both paths.
The property checks need hypothesis (pip install -r tests/requirements.txt) and are skipped without it.
"""
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from hypothesis_profiles import examples

try:
    from hypothesis import assume, example, given, settings, strategies as st
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
APPROVAL = "Approved-by: Ana (2026-11-06)\n"
MISMATCH = "Change-Class docs doesn't cover a change to files that aren't documentation: %s"
HIDDEN_HEADING = "'## Approval' heading inside or next to an HTML comment"
FENCED_HEADING = "'## Approval' heading inside a fenced code block"
LAYOUTS = (   # what a spec may put above its Change-Class line, and the problem that makes the spec invalid
    ("nothing",                               "",                                     None),
    ("a comment",                             "<!-- A note for the analyst. -->\n",   None),
    ("a commented-out Approval heading",      "<!--\n## Approval\n-->\n",             HIDDEN_HEADING),
    ("a comment before an Approval heading",  "<!-- note -->## Approval\n",           HIDDEN_HEADING),
    ("an Approval heading in a code block",   "```\n## Approval\n```\n",              FENCED_HEADING),
    ("one in a tilde code block",             "~~~markdown\n## Approval\n~~~\n",      FENCED_HEADING),
)
SNIPPETS = tuple(above for _, above, _ in LAYOUTS) + (   # for the property checks, around the Change-Class line
    "A plain line.\n", "## Approval <!-- note -->\n", "```\nChange-Class: docs\n```\n", "<!--\nChange-Class: schema\n-->\n")


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

    def write_spec(self, task, header="", context=""):
        self.write("backbone/specs/%s.md" % task, SPEC.format(task=task, header=header, context=context))

    def add_task(self, task, header="", context="", light=False):
        self.write_spec(task, header, context)
        with open(self.root / "backbone/3-TASKS.md", "a", encoding="utf-8") as tasks:
            tasks.write("- [ ] **Task %s: Item** (spec: backbone/specs/%s.md)%s\n" % (task, task,
                                                                                    " (light)" if light else ""))

    def approve_as_user(self, task):
        with open(self.root / ("backbone/specs/%s.md" % task), "a", encoding="utf-8") as spec:
            spec.write(APPROVAL)

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

    def analyst_edit(self, task, tool_name, **tool_input):
        """The hook's answer when the analyst edits the task's spec; the file is left as it is. The skill gate is off:
        it would only ask for the requirements-writing skill first."""
        tool_input["file_path"] = str(self.root / ("backbone/specs/%s.md" % task))
        return self.hook("pre-tool-use", {"agent_id": "a1", "agent_type": "analyst", "tool_name": tool_name,
                                          "tool_input": tool_input}, HARNESS_SKILL_GATE="off")

    def state(self, task):
        """The task in state --json: its class, spec problems, grill verdict (and whether it is current), approval."""
        return next(t for t in json.loads(self.harness("state", "--json")[1])["tasks"] if t["task"] == task)

    def move(self, source, destination):
        (self.root / destination).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", source, destination)

    def receipt_risks(self, task, base, files=None):
        """The risks on the receipt of the [WIP] task for its change since base, judged on the current code with files
        (path: text) added; the files are removed again afterwards."""
        files = files or {}
        for name, text in files.items():
            self.write(name, text)
        self.judge_pass(task)
        code, out = self.harness("receipt", task, "--base", base, "--json")
        for name in files:
            (self.root / name).unlink()
        if code:
            raise AssertionError(out)
        return json.loads(out)["risks"]


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


class WhatWasPassed(unittest.TestCase):
    """The class is read only from the part of the spec that the grill fingerprint covers and approval freezes."""

    def setUp(self):
        self.project = new_project(self)

    def test_policy_never_approves_a_class_changed_after_the_grill(self):
        for n, (layout, above, _) in enumerate(LAYOUTS, 1):
            task = "10.%d" % n
            with self.subTest(layout=layout):
                self.project.add_task(task, above + declared("feature"))
                self.project.grill_pass(task)
                self.project.write_spec(task, above + declared("refactor"))

                code, out = self.project.harness("approve", task, HARNESS_AUTONOMY="autonomous")

                self.assertEqual(code, 1, out)
                self.assertNotIn("Approved-by: policy", self.project.read("backbone/specs/%s.md" % task))

    def test_an_approval_heading_in_a_comment_or_a_code_block_makes_the_spec_invalid(self):
        for n, (layout, above, problem) in enumerate(LAYOUTS, 1):
            task = "11.%d" % n
            with self.subTest(layout=layout):
                self.project.add_task(task, above + declared("docs"))
                self.project.grill_pass(task)

                code, out = self.project.harness("spec-check", task)

                self.assertEqual(code, 1 if problem else 0, out)
                self.assertEqual(HIDDEN_HEADING in out, problem == HIDDEN_HEADING, out)
                self.assertEqual(FENCED_HEADING in out, problem == FENCED_HEADING, out)
                self.assertEqual(self.project.state(task)["grill"]["verdict"], "fail" if problem else "pass")

    def test_an_approved_spec_stays_frozen_whatever_is_above_its_class(self):
        edits = (("Change-Class: docs", "Change-Class: refactor"),
                 ("The system shall do one thing.", "The system shall do nothing."))
        for n, (layout, above, _) in enumerate(LAYOUTS, 1):
            task = "12.%d" % n
            self.project.add_task(task, above + declared("docs"))
            self.project.approve_as_user(task)
            for old, new in edits:
                with self.subTest(layout=layout, new=new):
                    code, out = self.project.analyst_edit(task, "Edit", old_string=old, new_string=new)

                    self.assertEqual(code, 2, out)
                    self.assertIn("approved and therefore frozen", out)


class FencedApproval(unittest.TestCase):
    """A '## Approval' heading in a fenced code block is an example: the spec's own heading starts the Approval section
    for the grill fingerprint, the freeze, the class, the risk checks and approval."""
    EXAMPLE = "Every spec ends like this:\n\n```markdown\n## Approval\n```\n"
    STORAGE = "Passwords are stored in plain text."

    def setUp(self):
        self.project = new_project(self)

    def add_task(self, task, example=EXAMPLE, header=declared("docs")):
        """A task whose Context shows example, followed by a requirement that is a risk."""
        self.project.add_task(task, header, example)
        spec = "backbone/specs/%s.md" % task
        self.project.write(spec, self.project.read(spec).replace("## Requirements\n",
                                                                 "## Requirements\n%s\n" % self.STORAGE))

    def test_the_risk_checks_read_the_spec_below_the_example(self):
        self.add_task("30.1")

        code, out = self.project.harness("risk", "30.1")

        self.assertEqual(code, 1, out)
        self.assertIn("the spec involves password", out)

    def test_policy_does_not_approve_the_spec(self):
        self.add_task("30.1")
        self.project.grill_pass("30.1")

        code, out = self.project.harness("approve", "30.1", HARNESS_AUTONOMY="autonomous")

        self.assertEqual(code, 1, out)
        self.assertNotIn("Approved-by: policy", self.project.read("backbone/specs/30.1.md"))

    def test_spec_check_says_the_heading_is_in_a_code_block(self):
        self.add_task("30.1")

        code, out = self.project.harness("spec-check", "30.1")

        self.assertEqual(code, 1, out)
        self.assertIn(FENCED_HEADING, out)

    def test_the_grill_pass_covers_the_spec_below_the_example(self):
        self.add_task("30.1")
        self.project.grill_pass("30.1")
        spec = "backbone/specs/30.1.md"

        self.project.write(spec, self.project.read(spec).replace(self.STORAGE, "Passwords are hashed."))

        self.assertFalse(self.project.state("30.1")["grill"]["current"])

    def test_the_users_approval_freezes_the_spec_below_the_example(self):
        self.add_task("30.1")
        self.project.approve_as_user("30.1")

        code, out = self.project.analyst_edit("30.1", "Edit", old_string=self.STORAGE,
                                              new_string="Passwords are hashed.")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

    def test_the_class_below_the_example_is_the_declared_one(self):
        self.add_task("30.1", header=self.EXAMPLE + declared("refactor"), example="")

        self.assertEqual(self.project.state("30.1")["change_class"], "refactor")

    def test_an_approved_by_line_in_a_code_block_is_an_example_not_the_users_approval(self):
        self.add_task("30.1", self.EXAMPLE.replace("## Approval\n", "## Approval\n" + APPROVAL))
        self.add_task("30.2", "")
        with open(self.project.root / "backbone/specs/30.2.md", "a", encoding="utf-8") as spec:
            spec.write("```\n%s```\n" % APPROVAL)

        for task in ("30.1", "30.2"):
            with self.subTest(task=task):
                self.assertFalse(self.project.state(task)["approved"])


FENCE_INDENT = "a code fence indented 4 or more columns"


class FenceRules(unittest.TestCase):
    """Where a fenced code block ends, as Markdown decides it, for every gate that reads a spec. The example's '## Approval'
    heading is a heading only when the line after it closes the block: a run of the same character at least as long as
    the opener, at 0-3 spaces, with nothing after it. Then the passwords below it are in the Approval section and aren't
    screened. A deeper marker is refused as misplaced, since a list item would read it as closing the block."""
    # opener   candidate closer   closes  misplaced
    TABLE = (
        ("```",   "```",           True,   False),
        ("```",   "   ```",        True,   False),
        ("```",   "```   ",        True,   False),
        ("```",   "    ```",       False,  True),
        ("```",   "        ```",   False,  True),
        ("```",   "\t```",         False,  True),
        ("````",  "```",           False,  False),
        ("````",  "`````",         True,   False),
        ("```",   "``` yaml",      False,  False),
        ("```",   "~~~",           False,  False),
        ("~~~",   "```",           False,  False),
        ("~~~",   "~~~",           True,   False),
    )
    CONTEXT = "Example:\n\n%s\nexample = 1\n%s\n## Approval\nPasswords are stored in plain text.\n"
    ids = itertools.count(1)

    def setUp(self):
        self.project = new_project(self)

    def add(self, task, opener, candidate):
        self.project.add_task(task, declared("docs"), self.CONTEXT % (opener, candidate))

    def test_a_fence_closes_only_where_markdown_closes_it(self):
        for n, (opener, candidate, closes, misplaced) in enumerate(self.TABLE, 1):
            with self.subTest(opener=opener, candidate=candidate):
                task = "51.%d" % n
                self.add(task, opener, candidate)

                code, out = self.project.harness("risk", task)
                self.assertEqual("password" in out, not closes, out)
                code, out = self.project.harness("spec-check", task)
                self.assertEqual(FENCE_INDENT in out, misplaced, out)

    if given is not None:
        @settings(max_examples=examples(25), deadline=None)
        @given(opener=st.sampled_from(("```", "~~~")), indent=st.integers(0, 8), same=st.booleans(),
               length=st.integers(3, 5))
        def test_a_closer_closes_at_up_to_three_spaces_and_a_deeper_one_is_misplaced(
                self, opener, indent, same, length):
            other = "~" if opener[0] == "`" else "`"
            candidate = " " * indent + (opener[0] if same else other) * length
            task = "52.%d" % next(self.ids)
            self.add(task, opener, candidate)

            code, out = self.project.harness("risk", task)
            self.assertEqual("password" in out, not (indent <= 3 and same), out)
            code, out = self.project.harness("spec-check", task)
            self.assertEqual(FENCE_INDENT in out, same and indent >= 4, out)


class CommentApproval(unittest.TestCase):
    """The Approved-by: line the gates read is the one approved() reads, whatever a comment does to its line. An agent
    can't write one behind a comment, nor move an example line into the Approval section."""
    WRAPPED = ("<!-- x -->Approved-by: agent (2026-11-08)\n",
               "<!--\n-->Approved-by: agent (2026-11-08)\n",
               "<!-- a\nb --> Approved-by: agent (2026-11-08)\n")
    ids = itertools.count(1)

    def setUp(self):
        self.project = new_project(self)

    def test_an_agent_cannot_write_an_approval_behind_a_comment(self):
        for n, wrapped in enumerate(self.WRAPPED, 1):
            with self.subTest(wrapped=wrapped):
                task = "53.%d" % n
                self.project.add_task(task, declared("docs"))

                code, out = self.project.analyst_edit(task, "Edit", old_string="## Approval\n",
                                                      new_string="## Approval\n" + wrapped)

                self.assertEqual(code, 2, out)
                self.assertFalse(self.project.state(task)["approved"])

    def test_an_agent_cannot_move_an_example_line_into_the_approval_section(self):
        self.project.add_task("53.9", declared("docs"), "Example:\n\n```\n%s```\n" % APPROVAL)
        spec = self.project.read("backbone/specs/53.9.md")
        edited = spec.replace("```\n%s```\n" % APPROVAL, "") + APPROVAL

        code, out = self.project.analyst_edit("53.9", "Write", content=edited)

        self.assertEqual(code, 2, out)
        self.assertFalse(self.project.state("53.9")["approved"])

    if given is not None:
        junk = st.text(alphabet=" \nx-", max_size=6).filter(lambda text: "-->" not in text)
        gap = st.text(alphabet=" \t", max_size=3)

        @settings(max_examples=examples(25), deadline=None)
        @given(lead=junk, gap=gap)
        def test_no_agent_edit_writes_an_approval_behind_a_comment(self, lead, gap):
            task = "54.%d" % next(self.ids)
            self.project.add_task(task, declared("docs"))
            wrapped = "<!--%s-->%sApproved-by: agent (2026-11-08)\n" % (lead, gap)

            code, out = self.project.analyst_edit(task, "Edit", old_string="## Approval\n",
                                                  new_string="## Approval\n" + wrapped)

            self.assertEqual(code, 2, out)
            self.assertFalse(self.project.state(task)["approved"])

    def test_the_users_approval_under_a_heading_a_reader_sees_still_freezes_the_spec(self):
        for n, heading in enumerate(("## Approval ##\n", "## Approval\r\n"), 2):
            with self.subTest(heading=heading):
                task = "55.%d" % n
                self.project.add_task(task, declared("docs"))
                spec = "backbone/specs/%s.md" % task
                self.project.write(spec, self.project.read(spec).replace("## Approval\n", heading))
                self.project.approve_as_user(task)

                code, out = self.project.analyst_edit(task, "Edit", old_string="The system shall do one thing.",
                                                      new_string="The system shall do nothing.")

                self.assertEqual(code, 2, out)

    def test_an_indented_closer_leaves_the_requirements_below_it_frozen(self):
        self.project.add_task("55.1", declared("docs"), "Example:\n\n```markdown\n        ```\n## Approval\n```\n")
        self.project.approve_as_user("55.1")

        code, out = self.project.analyst_edit("55.1", "Edit", old_string="The system shall do one thing.",
                                              new_string="The system shall do nothing.")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)


class FencedSections(unittest.TestCase):
    """A '## <title>' heading in a code block is an example. The sections the gates read are the spec's own, whatever an
    example above them shows, and a comment opened in a code block doesn't hide what follows it."""
    FENCES = ("```", "~~~", "````")

    def setUp(self):
        self.project = new_project(self)

    def test_a_fenced_skills_heading_leaves_the_text_after_it_screened(self):
        for n, fence in enumerate(self.FENCES, 1):
            with self.subTest(fence=fence):
                task = "56.%d" % n
                self.project.add_task(task, declared("docs"), "Example:\n\n%s\n## Skills\n%s\nThe change rewrites the "
                                                              "password hashing in auth.\n" % (fence, fence))

                code, out = self.project.harness("risk", task)

                self.assertEqual(code, 1, out)
                self.assertIn("password", out)

    def test_a_fenced_open_questions_heading_does_not_hide_the_real_one(self):
        for n, fence in enumerate(self.FENCES, 1):
            with self.subTest(fence=fence):
                task = "57.%d" % n
                self.project.add_task(task, declared("docs"), "Example:\n\n%s\n## Open questions\n- none\n%s\n"
                                      % (fence, fence))
                self.open_question(task)

                code, out = self.project.harness("spec-check", task)

                self.assertEqual(code, 1, out)
                self.assertIn("open questions remain: Which hash function?", out)

    def test_a_comment_opened_in_a_code_block_hides_nothing(self):
        self.project.add_task("58.1", declared("docs"), "Example:\n\n```\n<!--\n```\n")
        self.open_question("58.1")
        self.project.write("backbone/specs/58.1.md", self.project.read("backbone/specs/58.1.md") + "-->\n")

        code, out = self.project.harness("spec-check", "58.1")

        self.assertEqual(code, 1, out)
        self.assertIn("open questions remain: Which hash function?", out)

    def open_question(self, task):
        spec = "backbone/specs/%s.md" % task
        self.project.write(spec, self.project.read(spec).replace("- none\n\n## Approval",
                                                                "- Which hash function?\n\n## Approval"))


COMMENT_AMBIGUOUS = "an HTML comment a reader may not end where the gates do"


class CommentReach(unittest.TestCase):
    """A comment a reader ends where the gates do: one that starts at column 0, which a reader takes as an HTML block
    ending at its '-->'. One that starts after text may end with its paragraph for a reader, one indented 1-3 columns
    with a list item, and one 4 or more columns in may be code, so the spec is invalid rather than read one way or the
    other."""
    # context above the Requirements, text appended after the spec, ambiguous?
    TABLE = (
        ("A change. <!-- note\n\n", "-->\n", True),
        ("A change. <!-- note\n", "", True),
        ("A change.\n\n        <!-- note -->\n", "", True),
        ("A change.\n\n\t<!-- note -->\n", "", True),
        ("A change. <!-- note -->\n", "", False),
        ("A change.\n\n<!--\nnote\n\n-->\n", "", False),
        ("A change.\n\n   <!-- note\n-->\n", "", True),
        ("A change.\n\n   <!-- note -->\n", "", False),
    )

    def setUp(self):
        self.project = new_project(self)

    def test_a_comment_a_reader_may_end_elsewhere_makes_the_spec_invalid(self):
        for n, (context, after, ambiguous) in enumerate(self.TABLE, 1):
            with self.subTest(context=context):
                task = "59.%d" % n
                self.project.add_task(task, declared("docs"), context)
                spec = "backbone/specs/%s.md" % task
                self.project.write(spec, self.project.read(spec) + after)

                code, out = self.project.harness("spec-check", task)

                self.assertEqual(COMMENT_AMBIGUOUS in out, ambiguous, out)

    def test_a_comment_cannot_hide_an_open_question(self):
        self.project.add_task("59.9", declared("docs"))
        spec = "backbone/specs/59.9.md"
        self.project.write(spec, self.project.read(spec).replace(
            "## Open questions\n- none\n\n## Approval",
            "## Open questions\nNote <!-- review\n- Which hash function?\n-->\n\n## Approval"))

        code, out = self.project.harness("spec-check", "59.9")

        self.assertEqual(code, 1, out)
        self.assertIn(COMMENT_AMBIGUOUS, out)


class DocumentationPaths(unittest.TestCase):
    # a docs task changes          it is documentation
    TABLE = (
        ("README.md",                True),
        ("docs/guide.md",            True),
        ("docs/index.mdx",           True),
        ("docs/api.rst",             True),
        ("manual.adoc",              True),
        ("notes/meeting.txt",        True),
        ("LICENSE",                  True),
        ("LICENSE.txt",              True),
        ("src/docs/handler.py",      False),
        ("app/api/docs/routes.ts",   False),
        ("tools/doc/run.sh",         False),
        ("docs/conf.py",             False),   # Sphinx runs it
        ("docs/hooks.py",            False),   # MkDocs hooks
        ("mkdocs.yml",               False),
        ("README.py",                False),
        ("LICENSE.sh",               False),
        ("docs/requirements.txt",    False),   # Read the Docs installs it
        ("CMakeLists.txt",           False),
        ("docs/Makefile",            False),
    )

    def setUp(self):
        self.project = new_project(self)
        self.project.add_task("13.1", declared("docs"))
        self.project.write("tests/test_ac.py", "def test_ac():  # AC-13.1-1\n    pass\n")
        self.project.set_marker("13.1", " ", "WIP")
        self.base = self.project.commit("docs: start task 13.1")

    def test_documentation_is_a_file_with_a_documentation_extension(self):
        for path, documentation in self.TABLE:
            with self.subTest(path=path):
                risks = self.project.receipt_risks("13.1", self.base, {path: "Changed by the docs task.\n"})

                self.assertEqual(MISMATCH % path in risks, not documentation, risks)


class Moves(unittest.TestCase):
    # Change-Class   moved from              to                 the receipt's risks
    TABLE = (
        ("docs",       "src/app.py",           "docs/app.md",     [MISMATCH % "src/app.py"]),
        ("refactor",   "src/auth/session.py",  "src/session.py",  ["the change touches sensitive paths: src/auth/session.py"]),
        ("docs",       "docs/old.md",          "docs/new.md",     []),
        ("refactor",   "src/old.py",           "src/new.py",      []),
    )
    GATED = (   # a commit moves          to                             verify --range says
        (".claude/agents/judge.md",  "docs/judge.md",               "the harness itself changes (.claude/agents/judge.md"),
        ("backbone/harness.conf",    "backbone/harness.conf.orig",  "user-only setting(s) changed in backbone/harness.conf"),
    )

    def setUp(self):
        self.project = new_project(self)

    def test_a_move_counts_as_its_old_path_and_its_new_one(self):
        for n, (change_class, source, destination, risks) in enumerate(self.TABLE, 1):
            task = "14.%d" % n
            with self.subTest(source=source, destination=destination):
                self.project.add_task(task, declared(change_class))
                self.project.write(source, "VALUE = '%s'\n" % task)
                self.project.write("tests/test_ac_%d.py" % n, "def test_ac():  # AC-%s-1\n    pass\n" % task)
                self.project.set_marker(task, " ", "WIP")
                base = self.project.commit("chore: before task %s" % task)
                self.project.move(source, destination)

                self.assertEqual(self.project.receipt_risks(task, base), risks)

                self.project.set_marker(task, "WIP", "x")

    def test_a_policy_approved_docs_task_cannot_move_code_into_the_docs_and_finish(self):
        auto = {"HARNESS_AUTONOMY": "autonomous"}
        self.project.write("src/app.py", "VALUE = 1\n")
        self.project.add_task("15.1", declared("docs"))
        self.project.write("tests/test_ac.py", "def test_ac():  # AC-15.1-1\n    pass\n")
        self.project.commit("docs: spec for task 15.1")
        self.project.grill_pass("15.1")
        self.assertEqual(self.project.harness("approve", "15.1", **auto)[0], 0)
        self.assertEqual(self.project.harness("start", "15.1", **auto)[0], 0)
        self.project.move("src/app.py", "docs/app.md")
        self.project.judge_pass("15.1")

        code, out = self.project.harness("finish", "15.1", **auto)

        self.assertEqual(code, 1, out)
        self.assertIn("approved by policy as low-risk, but " + MISMATCH % "src/app.py", out)

    def test_a_light_task_cannot_move_a_file_out_of_a_sensitive_path(self):
        lane = {"HARNESS_LIGHT_LANE": "on"}
        self.project.write("src/auth/session.py", "TTL = 60\n")
        self.project.add_task("16.1", declared("refactor"), light=True)
        self.project.approve_as_user("16.1")
        self.project.write("tests/test_ac.py", "def test_ac():  # AC-16.1-1\n    pass\n")
        self.project.commit("refactor: spec for task 16.1")
        self.assertEqual(self.project.harness("start", "16.1", **lane)[0], 0)
        self.project.move("src/auth/session.py", "src/session.py")
        self.project.judge_pass("16.1")

        code, out = self.project.harness("finish", "16.1", **lane)

        self.assertEqual(code, 1, out)
        self.assertIn("outgrew the light lane: it touches sensitive paths: src/auth/session.py", out)

    def test_verify_sees_a_staged_move_of_the_hook_settings(self):
        self.project.move(".claude/settings.json", ".claude/settings.json.bak")

        code, out = self.project.harness("verify")

        self.assertEqual(code, 1, out)
        self.assertIn(".claude/settings.json no longer runs the harness hook(s)", out)

    def test_verify_sees_a_commit_that_moves_a_gated_file_away(self):
        for source, destination, problem in self.GATED:
            with self.subTest(source=source):
                base = self.project.git("rev-parse", "HEAD")
                self.project.move(source, destination)
                self.project.commit("chore: move %s" % source)

                code, out = self.project.harness("verify", "--range", "%s..HEAD" % base)

                self.assertEqual(code, 1, out)
                self.assertIn(problem, out)


class FencedExamples(unittest.TestCase):
    # the lines above the spec's Context                              the class it declares
    TABLE = (
        ("```\nChange-Class: docs\n```\n",                            "feature"),
        ("~~~\nChange-Class: docs\n~~~\n",                            "feature"),
        ("````\n```\nChange-Class: docs\n```\n````\n",                "feature"),
        ("~~~\n```\nChange-Class: docs\n```\n~~~\n",                  "feature"),
        ("```\n```text\nChange-Class: docs\n```\n",                   "feature"),   # ```text can't close it
        ("- For example:\n  ```\n  Change-Class: docs\n  ```\n",      "feature"),
        ("```text\nChange-Class: docs\n",                             "feature"),   # left open: to the end
        ("Change-Class: refactor\n```\nChange-Class: schema\n```\n",  "refactor"),
        ("```\nChange-Class: schema\n```\nChange-Class: docs\n",      "docs"),
        ("```inline``` code\nChange-Class: docs\n",                   "docs"),
    )

    def setUp(self):
        self.project = new_project(self)

    def test_a_class_in_a_fenced_code_block_is_an_example_not_a_declaration(self):
        for n, (header, change_class) in enumerate(self.TABLE, 1):
            task = "17.%d" % n
            with self.subTest(header=header):
                self.project.add_task(task, header)

                state = self.project.state(task)

                self.assertEqual(state["change_class"], change_class, state)
                self.assertEqual([p for p in state["spec_problems"] if "Change-Class" in p], [], state)


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

        @settings(max_examples=examples(60), deadline=None)
        @given(value=st.one_of(line_text, any_case))
        def test_spec_check_takes_exactly_one_class_name_in_any_case(self, value):
            task = "8.%d" % next(self.ids)
            self.project.add_task(task, "Change-Class: %s\n" % value)

            _, out = self.project.harness("spec-check", task)

            self.assertEqual("is not one of docs, refactor, feature, schema" in out,
                             value.strip().lower() not in CLASSES, out)

        @settings(max_examples=examples(25), deadline=None)
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


@unittest.skipIf(given is None, "hypothesis is not installed (pip install -r tests/requirements.txt)")
class SpecProperties(unittest.TestCase):
    ids = itertools.count(1)

    def setUp(self):
        self.project = new_project(self)

    def task(self):
        return "20.%d" % next(self.ids)

    if given is not None:
        around = st.lists(st.sampled_from(SNIPPETS), max_size=3)
        fenced = st.builds(lambda marker, length, info, values: "%s%s\n%s%s\n" % (
            marker * length, info, "".join(declared(v) for v in values), marker * length),
            st.sampled_from(("`", "~")), st.integers(3, 5), st.sampled_from(("", "text", "yaml")),
            st.lists(st.sampled_from(CLASSES + ("chore", "")), min_size=1, max_size=3))

        @settings(max_examples=examples(25), deadline=None)
        @given(above=around, below=around, old=st.sampled_from(CLASSES), new=st.sampled_from(CLASSES))
        @example(above=["<!--\n## Approval\n-->\n"], below=[], old="feature", new="refactor")
        def test_the_class_read_changes_only_with_the_grill_fingerprint(self, above, below, old, new):
            task = self.task()
            self.project.add_task(task, "".join(above) + declared(old) + "".join(below))
            self.project.grill_pass(task)
            graded = self.project.state(task)["change_class"]

            self.project.write_spec(task, "".join(above) + declared(new) + "".join(below))
            state = self.project.state(task)

            self.assertTrue(state["change_class"] == graded or not state["grill"]["current"], (graded, state))

        @settings(max_examples=examples(20), deadline=None)
        @given(above=around, below=around, old=st.sampled_from(CLASSES), new=st.sampled_from(CLASSES))
        @example(above=["<!--\n## Approval\n-->\n"], below=[], old="docs", new="refactor")
        def test_no_agent_edit_changes_the_class_of_an_approved_spec(self, above, below, old, new):
            task = self.task()
            self.project.add_task(task, "".join(above) + declared(old) + "".join(below))
            self.project.approve_as_user(task)
            approved = self.project.state(task)
            edited = SPEC.format(task=task, header="".join(above) + declared(new) + "".join(below), context="") + APPROVAL

            code, out = self.project.analyst_edit(task, "Write", content=edited)
            self.project.write("backbone/specs/%s.md" % task, edited)
            state = self.project.state(task)

            self.assertTrue(code == 2 or not approved["approved"] or state["change_class"] == approved["change_class"],
                            (out, approved, state))

        @settings(max_examples=examples(20), deadline=None)
        @given(change_class=st.sampled_from(CLASSES), above=st.lists(fenced, max_size=2),
               below=st.lists(fenced, max_size=2))
        @example(change_class="refactor", above=[], below=["```\nChange-Class: schema\n```\n"])
        def test_a_fenced_example_never_changes_the_declared_class(self, change_class, above, below):
            task = self.task()
            self.project.add_task(task, "".join(above) + declared(change_class) + "".join(below))

            state = self.project.state(task)

            self.assertEqual(state["change_class"], change_class, state)
            self.assertEqual([p for p in state["spec_problems"] if "Change-Class" in p], [], state)

        example_lines = st.lists(st.sampled_from((APPROVAL, declared("docs"), "## Requirements\n", "\n",
                                                  "- The system shall log users in.\n")), max_size=2)
        approval_example = st.builds(lambda marker, length, info, before, after: "%s%s\n%s## Approval\n%s%s\n" % (
            marker * length, info, "".join(before), "".join(after), marker * length),
            st.sampled_from(("`", "~")), st.integers(3, 5), st.sampled_from(("", "markdown", "text")),
            example_lines, example_lines)
        replacement = st.one_of(
            st.text(st.characters(blacklist_categories=("Cs", "Cc")), max_size=12),
            st.lists(st.sampled_from(("## Approval\n", "```\n", "~~~\n", "<!--", "-->", "\n", declared("refactor"),
                                      FencedApproval.STORAGE)), min_size=1, max_size=4).map("".join))

        def edit_below(self, task, example, data):
            """The spec with one span, between the example's '## Approval' line and the spec's own, replaced."""
            text = self.project.read("backbone/specs/%s.md" % task)
            low = text.index(example) + example.index("## Approval\n") + len("## Approval\n")
            start, stop = sorted(data.draw(st.lists(st.integers(low, text.rindex("## Approval\n")),
                                                    min_size=2, max_size=2)))
            edited = text[:start] + data.draw(self.replacement) + text[stop:]
            assume(edited != text)
            return edited

        def write_task(self, example, above_class):
            task = self.task()
            self.project.add_task(task, example + declared("docs") if above_class else declared("docs"),
                                  "" if above_class else "\n" + example)
            return task

        @settings(max_examples=examples(25), deadline=None)
        @given(example=approval_example, above_class=st.booleans(), data=st.data())
        def test_an_edit_below_a_fenced_approval_heading_stales_the_grill_or_invalidates_the_spec(
                self, example, above_class, data):
            task = self.write_task(example, above_class)
            self.project.grill_pass(task)

            self.project.write("backbone/specs/%s.md" % task, self.edit_below(task, example, data))
            state = self.project.state(task)

            self.assertTrue(not state["grill"]["current"] or state["spec_problems"], state)

        @settings(max_examples=examples(25), deadline=None)
        @given(example=approval_example, above_class=st.booleans(), data=st.data())
        def test_an_agent_edit_below_a_fenced_approval_heading_is_frozen_or_invalidates_the_spec(
                self, example, above_class, data):
            task = self.write_task(example, above_class)
            self.project.approve_as_user(task)
            edited = self.edit_below(task, example, data)

            code, out = self.project.analyst_edit(task, "Write", content=edited)
            self.project.write("backbone/specs/%s.md" % task, edited)
            state = self.project.state(task)

            self.assertTrue(code == 2 or state["spec_problems"], (out, state))


@unittest.skipIf(given is None, "hypothesis is not installed (pip install -r tests/requirements.txt)")
class ChangeProperties(unittest.TestCase):
    FOLDERS = ("docs", "doc", "documentation", "src", "app", "notes")
    STEMS = ("README", "LICENSE", "CHANGELOG", "index", "conf", "hooks", "guide")
    ids = itertools.count(1)

    def setUp(self):
        self.project = new_project(self)
        self.project.add_task("13.1", declared("docs"))
        self.project.write("tests/test_ac.py", "def test_ac():  # AC-13.1-1\n    pass\n")
        self.project.set_marker("13.1", " ", "WIP")
        self.base = self.project.commit("docs: start task 13.1")

    if given is not None:
        folders = st.lists(st.sampled_from(FOLDERS), max_size=2)

        @settings(max_examples=examples(15), deadline=None)
        @given(folders=folders, stem=st.sampled_from(STEMS), extension=st.sampled_from(
            ("py", "ts", "js", "sh", "rb", "go", "yml", "toml", "json", "html", "css", "png")))
        @example(folders=["docs"], stem="conf", extension="py")
        def test_a_file_without_a_documentation_extension_is_never_documentation(self, folders, stem, extension):
            path = "/".join(folders + ["%s.%s" % (stem, extension)])

            risks = self.project.receipt_risks("13.1", self.base, {path: "Changed by the docs task.\n"})

            self.assertIn(MISMATCH % path, risks)

        @settings(max_examples=examples(15), deadline=None)
        @given(folders=folders, name=st.one_of(
            st.tuples(st.sampled_from(STEMS), st.sampled_from(("md", "mdx", "markdown", "rst", "adoc", "asciidoc", "txt")))
            .map(lambda parts: "%s.%s" % parts),
            st.sampled_from(("README", "LICENSE", "CHANGELOG", "NOTICE", "AUTHORS"))))
        @example(folders=["notes"], name="guide.txt")
        def test_a_file_with_a_documentation_extension_is_documentation(self, folders, name):
            path = "/".join(folders + [name])

            risks = self.project.receipt_risks("13.1", self.base, {path: "Changed by the docs task.\n"})

            self.assertEqual(risks, [])

        @settings(max_examples=examples(10), deadline=None)
        @given(source=st.sampled_from(("src/app.py", "src/auth/session.py", "docs/guide.md", "db/migrations/001.sql")),
               folder=st.sampled_from(("docs", "src", "src/auth", "archive")), suffix=st.sampled_from(("", ".md")),
               change_class=st.sampled_from(("docs", "refactor")))
        @example(source="src/app.py", folder="docs", suffix=".md", change_class="docs")
        def test_staging_a_move_never_changes_how_it_is_assessed(self, source, folder, suffix, change_class):
            n = next(self.ids)
            task, source = "22.%d" % n, "case%d/%s" % (n, source)
            destination = "case%d/%s/%s%s" % (n, folder, os.path.basename(source), suffix)
            assume(destination != source)
            self.project.add_task(task, declared(change_class))
            self.project.write(source, "VALUE = '%s'\n" % task)
            self.project.write("tests/test_ac_%d.py" % n, "def test_ac():  # AC-%s-1\n    pass\n" % task)
            self.project.set_marker(task, " ", "WIP")
            base = self.project.commit("chore: before task %s" % task)

            os.renames(self.project.root / source, self.project.root / destination)
            unstaged = self.project.receipt_risks(task, base)
            os.renames(self.project.root / destination, self.project.root / source)
            self.project.move(source, destination)
            staged = self.project.receipt_risks(task, base)
            self.project.set_marker(task, "WIP", "x")

            self.assertEqual(staged, unstaged)


if __name__ == "__main__":
    unittest.main()
