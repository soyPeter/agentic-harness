"""`harness.py trace export` (ADR-004): the trace chain requirement -> acceptance criterion -> test -> verdict -> commit
as ReqIF 1.2, Sphinx-Needs needs.json (format 1) and an HTML matrix, checked through the command in a throwaway
project whose verdicts are recorded by the harness's own hooks.

The ReqIF output is checked against a minimal subset of the OMG schema vendored in tests/reqif_check.py, offline. The
property checks need hypothesis (pip install -r tests/requirements.txt); the rest runs without it.
"""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reqif_check  # noqa: E402

from hypothesis_profiles import examples

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None

ROOT = Path(__file__).resolve().parents[1]

SPEC = """# Spec {task}: {title}

Task: {task}
PRD: none
Change-Class: feature

## Context
{context}

## Requirements
{requirements}

## Acceptance criteria
{criteria}

## Non-functional requirements
{nfrs}

## Architecture
ADRs: ADR-001
Tech requirements:
- The code lives in src/.

## Skills
- code-quality: all code

## Out of scope
- Anything else.

## Assumptions
- none

## Open questions
- none

## Approval
"""
SPECS = {
    "7.1": dict(title="Customer search", context="Support needs to find customers by name.", requirements="""\
- REQ-7.1-1: The system shall return customers whose name contains the query, ignoring case.
- REQ-7.1-2: The system shall return no customer for an empty query.""", criteria="""\
- AC-7.1-1 (REQ-7.1-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.
- AC-7.1-2 (REQ-7.1-2): Given customers "Ana" and "Bob", when searching "", then nothing is returned.""",
                nfrs="- A search answers within 200 ms."),
    "7.2": dict(title="Search by email", context="Support also searches by email address.", requirements="""\
- REQ-7.2-1: The system shall return the customer whose email address starts with the query.""", criteria="""\
- AC-7.2-1 (REQ-7.2-1): Given <ana@example.com> & <bob@example.com>, when searching "ana@", then only \
<ana@example.com> is returned.""", nfrs="- none"),
    "7.3": dict(title="Export customers", context="Support exports the customer list.", requirements="""\
- REQ-7.3-1: The system shall export customers as CSV.
- REQ-7.3-2: The system shall name the file after the date.""", criteria="""\
- AC-7.3-1 (REQ-7.3-1): Given two customers, when exporting, then the CSV has two rows.
- AC-7.3-2 (REQ-7.3-9): Given no customers, when exporting, then the CSV holds only its header.""", nfrs="- none"),
    "7.4": dict(title="Duplicates", context="A draft that defines ids twice.", requirements="""\
- REQ-7.4-1: The system shall keep the first definition.
- REQ-7.4-1: The system shall ignore the second definition.""", criteria="""\
- AC-7.4-1 (REQ-7.4-1): Given a spec, when it is exported, then the first text is kept.
- AC-7.4-1 (REQ-7.4-1): Given a spec, when it is exported, then the second text is dropped.""", nfrs="- none"),
    "8.1": dict(title="Case view", context="Agents work disputes from the case list.", requirements="""\
- REQ-8.1-1: The case list shall show each case's status.
- REQ-8.1-2: When an agent opens a case, the case view shall show its evidence.
- REQ-8.1-3: While a case is locked, the case editor shall reject edits with 409.
- REQ-8.1-4: If an evidence file exceeds 10 MB, then the upload form shall reject it with "File too large".
- REQ-8.1-5: Where CSV export is enabled, the case list shall offer a download.
- REQ-8.1-6: While a case is open, when its deadline passes, the case list shall mark it overdue.
- REQ-8.1-7: Cases shall be listed quickly.""", criteria="""\
- AC-8.1-1 (REQ-8.1-1, REQ-8.1-2, REQ-8.1-3, REQ-8.1-4, REQ-8.1-5, REQ-8.1-6, REQ-8.1-7): Given an open case, when \
an agent opens it, then the case view shows its status and evidence.
- AC-8.1-2 (NFR-8.1-1): Given a case with 50 evidence files, when an agent opens it, then the case view renders \
within 300 ms.""", nfrs="""\
- NFR-8.1-1: The case view shall render within 300 ms.
- Closed cases stay readable for 7 years."""),
}
EARS_PATTERNS = {"REQ-8.1-1": "ubiquitous", "REQ-8.1-2": "event-driven", "REQ-8.1-3": "state-driven",
                 "REQ-8.1-4": "unwanted behaviour", "REQ-8.1-5": "optional feature", "REQ-8.1-6": "complex",
                 "REQ-8.1-7": "not an EARS pattern"}
SEARCH = "def search(names, q):\n    return [n for n in names if q and q.lower() in n.lower()]\n"
TASKS = """
- [x] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)
- [x] **Task 7.2: Search by email** (spec: backbone/specs/7.2.md)
- [ ] **Task 7.3: Export customers** (spec: backbone/specs/7.3.md)
"""


def final_message(report):
    return "Done.\n\n```json\n%s\n```" % json.dumps(report)


def tid(task, path):
    """The export's id for a test file (ADR-004)."""
    return "TEST-%s-%s" % (task, hashlib.sha256(path.encode("utf-8")).hexdigest()[:12])


class Matrix(HTMLParser):
    """The HTML matrix as a reader sees it: per task section, each table row's cells and each gap."""

    def __init__(self, document):
        super().__init__()
        self.sections, self.links = {}, []
        self._section = self._row = self._cell = self._item = None
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.links += [attrs[name] for name in ("src", "href") if name in attrs]
        if tag == "section":
            self._section = self.sections.setdefault(attrs.get("id"), {"rows": [], "gaps": []})
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "li":
            self._item = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._section is not None:
            self._section["rows"].append(self._row)
            self._row = None
        elif tag == "li" and self._item is not None and self._section is not None:
            self._section["gaps"].append(" ".join("".join(self._item).split()))
            self._item = None

    def handle_data(self, data):
        for part in (self._cell, self._item):
            if part is not None:
                part.append(data)

    def row(self, task, first):
        """The first row of task's tables whose first cell starts with first."""
        return next((r for r in self.sections["task-" + task]["rows"] if r and r[0].startswith(first)), None)

    def facts(self, task):
        """The task section's two-cell rows: {label: value}."""
        return {r[0]: r[1] for r in self.sections["task-" + task]["rows"] if len(r) == 2}


class Project(unittest.TestCase):
    """A bootstrapped project in a temporary folder, driven through the harness's commands and hooks."""

    @classmethod
    def make_project(cls, label):
        cls.temp = tempfile.TemporaryDirectory(prefix="trace export %s " % label)
        cls.outside = Path(cls.temp.name).resolve()
        cls.project = cls.outside / "project"
        cls.project.mkdir()
        cls.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test",
                       GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                       GIT_COMMITTER_EMAIL="test@example.com", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true",
                       HARNESS_REVIEW="off", HARNESS_DELIVER="off", PYTHONDONTWRITEBYTECODE="1",
                       CLAUDE_PROJECT_DIR=str(cls.project))
        for key in ("HARNESS_ROOT", "HARNESS_AUTONOMY", "HARNESS_PROFILE", "HARNESS_ROLE", "HARNESS_REQ_STYLE"):
            cls.env.pop(key, None)
        cls.command("git", "init", "-q", "-b", "main")
        cls.command(str(ROOT / "bootstrap.sh"), str(cls.project), "--name", "trace")
        with open(cls.project / ".gitignore", "a") as ignore:
            ignore.write("\ntrace-out/\n")
        cls.commit("chore: adopt agentic harness")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def command(cls, *args, input=None, check=True, cwd=None, env=None):
        result = subprocess.run(args, cwd=cwd or cls.project, env=dict(cls.env, **(env or {})), input=input,
                                capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    @classmethod
    def commit(cls, message):
        cls.command("git", "add", "-A")
        cls.command("git", "commit", "-qm", message)
        return cls.command("git", "rev-parse", "HEAD").stdout.strip()

    @classmethod
    def harness(cls, *args, **kwargs):
        return cls.command("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"), *args, **kwargs)

    @classmethod
    def hook(cls, event, report):
        agent = {"grill-stop": "griller", "judge-stop": "judge", "review-stop": "reviewer"}[event]
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": final_message(report)}
        out = cls.harness("hook", event, input=json.dumps(stop))
        return out.stdout + out.stderr

    @classmethod
    def write(cls, name, text):
        path = cls.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    @classmethod
    def write_spec(cls, task, **fields):
        cls.write("backbone/specs/%s.md" % task, SPEC.format(task=task, **dict(SPECS.get(task, {}), **fields)))

    @classmethod
    def set_task(cls, task, marker):
        tasks = cls.project / "backbone/3-TASKS.md"
        line = r"(?m)^- \[[^\]]*\] \*\*Task %s:" % re.escape(task)
        tasks.write_text(re.sub(line, "- [%s] **Task %s:" % (marker, task), tasks.read_text()))

    @classmethod
    def judge(cls, task, criteria, findings=()):
        """Grill, approve, start and judge task (pass), as the pipeline's hooks record it."""
        grilled = cls.hook("grill-stop", {"verdict": "pass", "task": task, "questions": [], "summary": "s"})
        assert "PASS" in grilled, grilled
        spec = cls.project / ("backbone/specs/%s.md" % task)
        spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        cls.set_task(task, "WIP")
        judged = cls.hook("judge-stop", {
            "verdict": "pass", "task": task, "summary": "s", "findings": list(findings),
            "criteria": [{"id": ac, "met": True, "evidence": "src/search.py:2", "tests": tests}
                         for ac, tests in criteria],
            "tests": {"command": "true", "result": "passed"}})
        assert "PASS" in judged, judged

    def export(self, fmt, *args, env=None, cwd=None):
        return self.harness("trace", "export", "--format", fmt, *args, env=env, cwd=cwd).stdout


class TracedProject(Project):
    """Task 7.1 was judged and committed, then task 7.2 changed the code, so 7.1's pass is on earlier code and 7.2's on
    the current code. 7.3 is a draft with gaps, 8.1 an EARS draft that isn't in 3-TASKS.md. Built once for every class
    below; tests leave it as they found it."""

    @classmethod
    def setUpClass(cls):
        if "project" not in TracedProject.__dict__:
            TracedProject.build()

    @classmethod
    def tearDownClass(cls):
        pass

    @classmethod
    def build(cls):
        cls.make_project("fixture")
        cls.write("src/search.py", SEARCH)
        cls.write("tests/test_search.py", "def test_contains():  # AC-7.1-1\n    assert True\n")
        cls.write("tests/test_search_empty.py", "def test_empty():  # AC-7.1-2\n    assert True\n")
        cls.write_spec("7.1")
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + TASKS)
        cls.judge("7.1", [("AC-7.1-1", ["test_contains"]), ("AC-7.1-2", ["test_empty"])],
                  findings=[{"severity": "minor", "file": "src/search.py", "line": 2, "issue": "No docstring"}])
        cls.set_task("7.1", "x")
        cls.first = cls.commit("feat: customer search")
        for task in ("7.2", "7.3", "7.4", "8.1"):
            cls.write_spec(task)
        cls.specs = cls.commit("docs: specs for tasks 7.2 to 8.1")
        cls.write("src/search.py",
                  SEARCH + "\n\ndef by_email(emails, q):\n    return [e for e in emails if e.startswith(q)]\n")
        cls.write("tests/test_email.py", "def test_email():  # AC-7.2-1\n    assert True\n")
        cls.command("git", "mv", "tests/test_search_empty.py", "tests/test_empty_query.py")
        cls.judge("7.2", [("AC-7.2-1", ["test_email"])])
        reviewed = cls.harness("hook", "review-stop", input=json.dumps({
            "agent_type": "reviewer", "last_assistant_message": final_message(
                {"task": "7.2", "lens": "correctness", "verdict": "pass", "findings": [], "summary": "s"})}))
        assert "PASS" in reviewed.stdout + reviewed.stderr, reviewed
        cls.set_task("7.2", "x")
        cls.second = cls.commit("feat: search by email")

    def clone(self, name, depth=None, **settings):
        """A clone of the project in its own folder, with settings written over its harness.conf (uncommitted)."""
        root = self.outside / name
        self.command("git", "clone", "-q", *(["--depth", str(depth)] if depth else []), "file://%s" % self.project,
                     str(root), cwd=self.outside)
        conf = root / "backbone/harness.conf"
        text = conf.read_text()
        for key, value in settings.items():
            text, found = re.subn(r"(?m)^\s*%s\s*=.*$" % key, '%s="%s"' % (key, value), text)
            if not found:
                text += '%s="%s"\n' % (key, value)
        conf.write_text(text)
        return root

    def export_at(self, root, fmt, *args, env=None):
        return self.command("python3", "-B", str(root / "scripts/harness/lib/harness.py"), "trace", "export",
                            "--format", fmt, *args, env=env, cwd=root).stdout

    def needs(self, *args, env=None):
        return self.needs_at(self.project, *args, env=env)

    def needs_at(self, root, *args, env=None):
        data = json.loads(self.export_at(root, "needs", *args, env=env))
        return data["versions"][data["current_version"]]["needs"]


class ReqIF(TracedProject):
    def test_the_export_meets_the_vendored_reqif_schema_check(self):
        for args in ((), ("--task", "7.3")):
            with self.subTest(args=args):
                self.assertEqual(reqif_check.problems(self.export("reqif", *args)), [])

    def test_the_vendored_check_finds_what_breaks_the_schema(self):
        document = self.export("reqif", "--task", "7.1")
        broken = re.sub(r"<TITLE>[^<]*</TITLE>", "", document, count=1)
        broken = re.sub(r"(<SPEC-OBJECT-TYPE-REF>)[^<]*(</SPEC-OBJECT-TYPE-REF>)", r"\1AH-NOWHERE\2", broken, count=1)
        broken = broken.replace("<REQ-IF-VERSION>1.0</REQ-IF-VERSION>", "<REQ-IF-VERSION>1.2</REQ-IF-VERSION>")

        found = reqif_check.problems(broken)

        self.assertTrue(any("element TITLE is required" in p for p in found), found)
        self.assertTrue(any("'AH-NOWHERE' names no SPEC-OBJECT-TYPE" in p for p in found), found)
        self.assertTrue(any("fixes it to 1.0" in p for p in found), found)

    def test_the_header_names_the_harness_and_the_head_commit(self):
        header = reqif_check.header(self.export("reqif"))

        self.assertEqual(header["REQ-IF-VERSION"], "1.0")
        self.assertEqual(header["TITLE"], "Traceability: trace")
        self.assertTrue(header["REQ-IF-TOOL-ID"].startswith("agentic-harness "), header)
        self.assertIn(self.second, header["COMMENT"])
        self.assertEqual(header["CREATION-TIME"],
                         self.command("git", "log", "-1", "--format=%cI").stdout.strip())

    def test_each_requirement_criterion_and_test_is_an_object_with_the_spec_s_id_and_text(self):
        objects = reqif_check.objects(self.export("reqif"))

        self.assertEqual({k: objects["REQ-7.1-1"][k] for k in ("type", "identifier", "ReqIF.Text", "Harness.Kind",
                                                              "Harness.Task")},
                         {"type": "Requirement", "identifier": "REQ-7.1-1", "Harness.Kind": "REQ",
                          "Harness.Task": "7.1", "ReqIF.Text":
                          "The system shall return customers whose name contains the query, ignoring case."})
        self.assertEqual(objects["AC-7.1-1"]["type"], "Acceptance criterion")
        self.assertEqual(objects["AC-7.1-1"]["ReqIF.Text"],
                         'Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.')
        test = objects[tid("7.1", "tests/test_search.py")]
        self.assertEqual((test["type"], test["ReqIF.Name"], test["Harness.Task"]),
                         ("Test", "tests/test_search.py", "7.1"))
        self.assertEqual((objects["7.1"]["element"], objects["7.1"]["identifier"], objects["7.1"]["ReqIF.Name"]),
                         ("SPECIFICATION", "TASK-7.1", "Customer search"))

    def test_relations_trace_criteria_to_requirements_and_tests_to_criteria(self):
        relations = reqif_check.relations(self.export("reqif", "--task", "7.1"))

        self.assertEqual(relations, sorted([
            ("Tests", tid("7.1", "tests/test_search.py"), "AC-7.1-1"),
            ("Tests", tid("7.1", "tests/test_search_empty.py"), "AC-7.1-2"),
            ("Verifies", "AC-7.1-1", "REQ-7.1-1"),
            ("Verifies", "AC-7.1-2", "REQ-7.1-2")]))

    def test_a_criterion_carries_the_judge_s_result_the_judged_code_and_its_commits(self):
        objects = reqif_check.objects(self.export("reqif"))
        verdicts = json.loads((self.project / "backbone/.verdicts/7.1.judge.json").read_text())["history"]

        self.assertEqual({k: objects["AC-7.1-1"][k] for k in ("Harness.Result", "Harness.Verdict", "Harness.Evidence",
                                                             "Harness.JudgeTests", "Harness.JudgedAt",
                                                             "Harness.CodeFingerprint", "Harness.Commits")},
                         {"Harness.Result": "met", "Harness.Verdict": "pass on earlier code",
                          "Harness.Evidence": "src/search.py:2", "Harness.JudgeTests": "test_contains",
                          "Harness.JudgedAt": verdicts[-1]["at"],
                          "Harness.CodeFingerprint": verdicts[-1]["fingerprint"],
                          "Harness.Commits": "%s %s" % (self.specs, self.first)})
        self.assertEqual(objects["AC-7.2-1"]["Harness.Verdict"], "pass on the current code")
        self.assertEqual(objects["AC-7.2-1"]["Harness.Commits"], self.second)

    def test_each_task_s_hierarchy_holds_its_requirements_criteria_and_tests(self):
        self.assertEqual(reqif_check.hierarchy(self.export("reqif", "--task", "7.1")), {"7.1": [
            "REQ-7.1-1", "REQ-7.1-2", "AC-7.1-1", "AC-7.1-2", tid("7.1", "tests/test_search.py"),
            tid("7.1", "tests/test_search_empty.py")]})

    def test_an_id_the_spec_defines_twice_is_exported_once_with_its_first_text(self):
        document = self.export("reqif", "--task", "7.4")
        objects = reqif_check.objects(document)

        self.assertEqual(reqif_check.problems(document), [])
        self.assertEqual(objects["REQ-7.4-1"]["ReqIF.Text"], "The system shall keep the first definition.")
        self.assertEqual(reqif_check.hierarchy(document), {"7.4": ["REQ-7.4-1", "AC-7.4-1"]})

    def test_a_reference_to_an_undefined_requirement_makes_no_relation(self):
        document = self.export("reqif", "--task", "7.3")

        self.assertEqual(reqif_check.relations(document), [("Verifies", "AC-7.3-1", "REQ-7.3-1")])
        self.assertIn("AC-7.3-2 references REQ-7.3-9, which the spec doesn't define",
                      reqif_check.objects(document)["7.3"]["Harness.Gaps"].splitlines())


class NeedsJson(TracedProject):
    def test_the_export_has_the_released_format_1_layout(self):
        data = json.loads(self.export("needs"))
        version = data["versions"][data["current_version"]]

        self.assertEqual(sorted(data), ["current_version", "project", "versions"])
        self.assertEqual((data["current_version"], data["project"]), (self.second, "trace"))
        self.assertEqual(sorted(version), ["creator", "needs", "needs_amount"])
        self.assertEqual(version["creator"]["program"], "agentic-harness")
        self.assertEqual(version["needs_amount"], len(version["needs"]))
        for key, need in version["needs"].items():
            with self.subTest(need=key):
                self.assertEqual(need["id"], key)
                self.assertIn(need["type"], ("task", "req", "ac", "test"))
                self.assertTrue(need["title"] and isinstance(need["title"], str))
                self.assertEqual((need["tags"], need["links"]), ([], []))
                for target in need.get("verifies", []) + need.get("tests", []):
                    self.assertIn(target, version["needs"])

    def test_needs_keep_the_spec_s_ids_and_link_the_chain(self):
        needs = self.needs()

        self.assertEqual({k: needs["REQ-7.1-1"][k] for k in ("type", "title", "harness_kind", "harness_task")},
                         {"type": "req", "harness_kind": "REQ", "harness_task": "7.1",
                          "title": "The system shall return customers whose name contains the query, ignoring case."})
        self.assertEqual({k: needs["AC-7.1-2"][k] for k in ("type", "verifies", "status", "harness_result")},
                         {"type": "ac", "verifies": ["REQ-7.1-2"], "status": "met", "harness_result": "met"})
        test = needs[tid("7.1", "tests/test_search.py")]
        self.assertEqual({k: test[k] for k in ("type", "title", "tests", "harness_path")},
                         {"type": "test", "title": "tests/test_search.py", "tests": ["AC-7.1-1"],
                          "harness_path": "tests/test_search.py"})

    def test_each_task_says_whether_its_judge_pass_is_on_the_current_code(self):
        needs = self.needs()
        expected = {"7.1": ("pass on earlier code", [self.specs, self.first]),
                    "7.2": ("pass on the current code", [self.second]),
                    "7.3": ("not judged", [])}

        for task, (verdict, commits) in expected.items():
            with self.subTest(task=task):
                need = needs["TASK-" + task]
                self.assertEqual(need["harness_verdict"], verdict)
                self.assertEqual(need.get("harness_commits", "").split(), commits)

    def test_the_test_files_of_an_earlier_pass_come_from_a_commit_that_carries_the_judged_code(self):
        needs = self.needs()

        self.assertEqual(needs["TASK-7.1"]["harness_test_files_from"], "commit %s" % self.specs)
        self.assertEqual(needs[tid("7.1", "tests/test_search_empty.py")]["tests"], ["AC-7.1-2"])
        self.assertNotIn(tid("7.1", "tests/test_empty_query.py"), needs)
        self.assertEqual(needs["TASK-7.2"]["harness_test_files_from"], "the current code")

    def test_a_task_carries_its_status_spec_grill_approval_test_run_and_reviews(self):
        needs = self.needs()
        first, second = needs["TASK-7.1"], needs["TASK-7.2"]

        self.assertEqual({k: first[k] for k in ("type", "title", "status", "harness_spec", "harness_change_class",
                                                "harness_approval")},
                         {"type": "task", "title": "Task 7.1: Customer search", "status": "done",
                          "harness_spec": "backbone/specs/7.1.md", "harness_change_class": "feature",
                          "harness_approval": "Approved-by: Ana (2026-11-01)"})
        self.assertRegex(first["harness_spec_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertTrue(first["harness_grill"].startswith("pass on the current spec ("), first["harness_grill"])
        self.assertRegex(first["harness_test_run"], r"^true: exit 0 in [0-9.]+s, output sha256 [0-9a-f]{64}$")
        self.assertEqual(second["harness_reviews"], "correctness: pass; structure: none; lean: none")
        self.assertEqual((needs["TASK-7.3"]["status"], needs["TASK-8.1"]["status"]), ("pending", "not in 3-TASKS.md"))

    def test_the_gaps_list_what_the_harness_cannot_show(self):
        needs = self.needs()

        self.assertEqual(needs["TASK-7.1"]["harness_gaps"].splitlines(), [
            "the judge's pass is on earlier code, not on the current code",
            "NFR without an id, so no criterion traces it: A search answers within 200 ms.",
            "minor finding left open: No docstring (src/search.py:2)"])
        self.assertEqual(needs["TASK-7.3"]["harness_gaps"].splitlines(), [
            "no judge verdict: nothing in this task is verified",
            "REQ-7.3-2 has no acceptance criterion",
            "AC-7.3-1: no test file mentions it",
            "AC-7.3-2 references REQ-7.3-9, which the spec doesn't define",
            "AC-7.3-2: no test file mentions it"])
        self.assertNotIn("harness_gaps", needs["TASK-7.2"])


class HtmlMatrix(TracedProject):
    def test_each_requirement_and_criterion_is_a_row_with_tests_result_verdict_and_commits(self):
        matrix = Matrix(self.export("html"))
        short = lambda *commits: " ".join(c[:12] for c in commits)

        self.assertEqual(matrix.row("7.1", "REQ-7.1-1"), [
            "REQ-7.1-1 The system shall return customers whose name contains the query, ignoring case.",
            'AC-7.1-1 Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.',
            "tests/test_search.py", "met", "pass on earlier code", short(self.specs, self.first)])
        self.assertEqual(matrix.row("7.2", "REQ-7.2-1")[2:], ["tests/test_email.py", "met",
                                                              "pass on the current code", short(self.second)])
        self.assertEqual(matrix.row("7.3", "REQ-7.3-2"), [
            "REQ-7.3-2 The system shall name the file after the date.", "no acceptance criterion", "-", "-",
            "not judged", "-"])
        self.assertEqual(matrix.row("7.3", "no known requirement")[1:3], [
            "AC-7.3-2 Given no customers, when exporting, then the CSV holds only its header.", "none"])

    def test_each_task_section_states_its_verdict_and_lists_its_gaps(self):
        matrix = Matrix(self.export("html"))

        self.assertEqual(matrix.facts("7.1")["Judge verdict"], "pass on earlier code")
        self.assertEqual(matrix.facts("7.2")["Reviews"], "correctness: pass; structure: none; lean: none")
        self.assertIn("REQ-7.3-2 has no acceptance criterion", matrix.sections["task-7.3"]["gaps"])
        self.assertEqual(matrix.sections["task-7.2"]["gaps"], [])

    def test_spec_text_is_escaped_and_the_page_loads_nothing(self):
        document = self.export("html")

        self.assertNotIn("<ana@example.com>", document)
        self.assertIn("&lt;ana@example.com&gt; &amp; &lt;bob@example.com&gt;", document)
        self.assertNotIn("<script", document.lower())
        self.assertEqual(Matrix(document).links, [])
        self.assertIn('Given <ana@example.com> & <bob@example.com>, when searching "ana@"',
                      Matrix(document).row("7.2", "REQ-7.2-1")[1])


class Ears(TracedProject):
    def test_under_ears_each_requirement_carries_its_pattern(self):
        ears = self.clone("ears", HARNESS_REQ_STYLE="ears")
        needs = self.needs_at(ears, "--task", "8.1")
        objects = reqif_check.objects(self.export_at(ears, "reqif", "--task", "8.1"))
        matrix = Matrix(self.export_at(ears, "html", "--task", "8.1"))

        for requirement, pattern in EARS_PATTERNS.items():
            with self.subTest(requirement=requirement):
                self.assertEqual(needs[requirement]["harness_ears_pattern"], pattern)
                self.assertEqual(objects[requirement]["Harness.EARSPattern"], pattern)
                self.assertEqual(matrix.row("8.1", requirement)[1], pattern)

    def test_plain_style_exports_no_pattern(self):
        needs = self.needs("--task", "8.1")
        objects = reqif_check.objects(self.export("reqif", "--task", "8.1"))
        matrix = Matrix(self.export("html", "--task", "8.1"))

        self.assertNotIn("harness_ears_pattern", needs["REQ-8.1-2"])
        self.assertNotIn("Harness.EARSPattern", objects["REQ-8.1-2"])
        self.assertTrue(matrix.row("8.1", "REQ-8.1-2")[1].startswith("AC-8.1-1"))

    def test_an_nfr_with_an_id_is_a_requirement_its_criterion_verifies(self):
        for root in (self.project, self.clone("ears-nfr", HARNESS_REQ_STYLE="ears")):
            with self.subTest(root=root.name):
                needs = self.needs_at(root, "--task", "8.1")

                self.assertEqual((needs["NFR-8.1-1"]["type"], needs["NFR-8.1-1"]["harness_kind"],
                                  needs["NFR-8.1-1"]["title"]),
                                 ("req", "NFR", "The case view shall render within 300 ms."))
                self.assertEqual(needs["AC-8.1-2"]["verifies"], ["NFR-8.1-1"])
                self.assertIn("NFR without an id, so no criterion traces it: Closed cases stay readable for 7 years.",
                              needs["TASK-8.1"]["harness_gaps"].splitlines())


class History(TracedProject):
    def test_a_shallow_clone_reports_incomplete_history_not_a_missing_commit(self):
        shallow = self.clone("shallow", depth=1)
        needs = self.needs_at(shallow)

        self.assertIn("history incomplete", needs["TASK-7.1"]["harness_gaps"])
        self.assertIn("git fetch --unshallow", needs["TASK-7.1"]["harness_gaps"])
        self.assertNotIn("is in no commit", needs["TASK-7.1"]["harness_gaps"])
        self.assertNotIn("history incomplete", needs["TASK-7.2"].get("harness_gaps", ""))

    def test_a_shallow_clone_that_holds_the_judged_commit_reports_no_gap(self):
        shallow = self.clone("shallow-holding", depth=3)
        needs = self.needs_at(shallow)

        self.assertEqual(needs["TASK-7.1"]["harness_test_files_from"], "commit %s" % self.specs)
        self.assertNotIn("history incomplete", needs["TASK-7.1"]["harness_gaps"])

    def test_a_full_clone_finds_the_commit_that_carries_the_judged_code(self):
        full = self.clone("full")
        needs = self.needs_at(full)

        self.assertEqual(needs["TASK-7.1"]["harness_test_files_from"], "commit %s" % self.specs)
        self.assertNotIn("history incomplete", needs["TASK-7.1"]["harness_gaps"])

    def test_trees_git_cannot_read_make_the_history_incomplete_not_a_missing_commit(self):
        root = self.copy_without_trees("missing", [self.first, self.specs])
        needs = self.needs_at(root)

        self.assertIn("history incomplete: git can't read", needs["TASK-7.1"]["harness_gaps"])
        self.assertNotIn("is in no commit", needs["TASK-7.1"]["harness_gaps"])
        self.assertNotIn("history incomplete", needs["TASK-7.2"].get("harness_gaps", ""))

    def test_a_partial_clone_whose_remote_is_gone_reports_incomplete_history(self):
        source = self.copy_without_trees("remote", [])
        self.command("git", "config", "uploadpack.allowFilter", "true", cwd=source)
        partial = self.outside / "partial"
        self.command("git", "clone", "-q", "--filter=tree:0", "file://%s" % source, str(partial), cwd=self.outside)
        shutil.rmtree(str(source))
        needs = self.needs_at(partial)

        self.assertIn("history incomplete: git timed out or failed reading the history",
                      needs["TASK-7.1"]["harness_gaps"])
        self.assertNotIn("is in no commit", needs["TASK-7.1"]["harness_gaps"])

    def copy_without_trees(self, name, commits):
        """A copy of the project whose root trees of commits are gone from its object store, as a partial clone that
        can't fetch them has them. The copy keeps loose objects, so each one is a file to remove."""
        root = self.outside / name
        shutil.copytree(str(self.project), str(root), symlinks=True)
        for commit in commits:
            tree = self.command("git", "rev-parse", commit + "^{tree}", cwd=root).stdout.strip()
            (root / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
        return root


class StateFingerprint(TracedProject):
    def hashes_during(self, *args):
        """The git write-tree calls a harness command makes: each one hashes the working tree (code_fingerprint).
        A logging wrapper in front of the real git on PATH counts them."""
        shim, log = self.outside / "shim", self.outside / "git-calls.txt"
        shim.mkdir(exist_ok=True)
        (shim / "git").write_text('#!/bin/sh\necho "$*" >> "%s"\nexec "%s" "$@"\n' % (log, shutil.which("git")))
        (shim / "git").chmod(0o755)
        log.write_text("")
        result = self.harness(*args, env={"PATH": "%s:%s" % (shim, os.environ["PATH"])})
        return result.stdout, [line for line in log.read_text().splitlines() if line.startswith("write-tree")]

    def test_state_hashes_the_working_tree_once_however_many_tasks_are_judged(self):
        out, hashed = self.hashes_during("state", "--json")

        judged = {t["task"]: t["judge"]["current"] for t in json.loads(out)["tasks"] if t["judge"]}
        self.assertEqual(judged, {"7.1": False, "7.2": True})
        self.assertLessEqual(len(hashed), 1, hashed)

    def test_next_hashes_the_working_tree_once_for_all_the_tasks_it_is_given(self):
        out, hashed = self.hashes_during("next", "7.1", "7.2", "--json")

        self.assertEqual([s["task"] for s in json.loads(out)], ["7.1", "7.2"])
        self.assertEqual(len(hashed), 2, hashed)  # the workspace's progress, then the code shared by both tasks


class Command(TracedProject):
    def test_the_same_repository_state_gives_the_same_bytes(self):
        for fmt in ("reqif", "needs", "html"):
            with self.subTest(format=fmt):
                first = self.export(fmt)

                self.assertEqual(self.export(fmt, env={"TZ": "Asia/Tokyo"}, cwd=self.project / "src"), first)

    def test_task_limits_the_export_to_one_task(self):
        needs = self.needs("--task", "7.2")

        self.assertEqual(sorted(needs),
                         sorted(["TASK-7.2", "REQ-7.2-1", "AC-7.2-1", tid("7.2", "tests/test_email.py")]))

    def test_a_task_without_a_spec_is_refused(self):
        result = self.harness("trace", "export", "--format", "needs", "--task", "9.9", check=False)

        self.assertEqual((result.returncode, result.stdout.strip()),
                         (1, "trace export: no spec at backbone/specs/9.9.md"))

    def test_out_writes_the_document_to_the_file_named_for_its_format(self):
        out = self.outside / "exports"
        for fmt, name in (("reqif", "traceability.reqif"), ("needs", "needs.json"), ("html", "traceability.html")):
            with self.subTest(format=fmt):
                result = self.harness("trace", "export", "--format", fmt, "--out", str(out))

                self.assertEqual(result.stdout.strip(), "trace export: wrote %s" % (out / name))
                self.assertEqual((out / name).read_text(), self.export(fmt))

    def test_out_inside_the_repository_is_refused_unless_git_ignores_it(self):
        refused = self.harness("trace", "export", "--format", "html", "--out", "exports", check=False)

        self.assertEqual(refused.returncode, 1)
        self.assertIn("exports/traceability.html is inside the repository and git doesn't ignore it", refused.stderr)
        self.assertFalse((self.project / "exports").exists())
        written = self.harness("trace", "export", "--format", "html", "--out", "trace-out")
        try:
            self.assertTrue((self.project / "trace-out/traceability.html").is_file(), written.stdout)
            self.assertEqual(self.harness("receipt", "7.2", check=False).returncode, 0)
        finally:
            shutil.rmtree(self.project / "trace-out", ignore_errors=True)

    def test_stdout_redirected_into_the_repository_is_refused_unless_git_ignores_it(self):
        def redirect(path):
            with open(path, "w") as out:
                return subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"),
                                       "trace", "export", "--format", "html"], cwd=self.project, env=self.env,
                                      stdout=out, stderr=subprocess.PIPE, text=True)

        untracked = self.project / "trace.html"
        ignored = self.project / "trace-out" / "trace.html"
        try:
            refused = redirect(untracked)

            self.assertEqual(refused.returncode, 1)
            self.assertIn("redirect stdout outside the repository", refused.stderr)
            self.assertEqual(untracked.read_text(), "")
            (self.project / "trace-out").mkdir(exist_ok=True)
            allowed = redirect(ignored)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertEqual(ignored.read_text(), self.export("html"))
        finally:
            untracked.unlink(missing_ok=True)
            shutil.rmtree(self.project / "trace-out", ignore_errors=True)

    def test_the_bytes_do_not_depend_on_the_folder_name_or_environment_overrides(self):
        first = self.clone("first", HARNESS_PROJECT_NAME="")
        second = self.clone("second-folder", HARNESS_PROJECT_NAME="")
        overridden = {"HARNESS_TEST_PATHS": "^nothing$", "HARNESS_REQ_STYLE": "ears", "HARNESS_PROJECT_NAME": "other"}
        for fmt in ("reqif", "needs", "html"):
            with self.subTest(format=fmt):
                self.assertEqual(self.export_at(second, fmt), self.export_at(first, fmt))
                self.assertEqual(self.export_at(first, fmt, env=overridden), self.export_at(first, fmt))

    def test_a_wrong_call_prints_the_usage(self):
        for args in ((), ("--format",), ("--format", "pdf"), ("--format", "html", "--task"),
                     ("--format", "html", "--colour", "red"), ("--format", "html", "--format", "needs")):
            with self.subTest(args=args):
                result = self.harness("trace", "export", *args, check=False)

                self.assertEqual(result.returncode, 64, result.stdout)
                self.assertIn("usage: harness.py trace export --format reqif|needs|html", result.stderr)

    def test_trace_of_a_task_still_prints_its_events(self):
        result = self.harness("trace", "7.1")

        self.assertTrue(result.stdout.startswith("trace: task 7.1, "), result.stdout)


def tearDownModule():
    if "temp" in TracedProject.__dict__:
        TracedProject.temp.cleanup()


if given is not None:
    # One line of text, as a spec item holds it: no line breaks and no HTML comment, which the harness strips.
    line_text = st.text(st.characters(blacklist_categories=("Cs",), blacklist_characters="\n\r"), max_size=40) \
        .filter(lambda t: "<!--" not in t)
    tokens = st.sampled_from(["REQ-9.1-1", "REQ-9.1-7", "NFR-9.1-1", "(REQ-9.1-1)", "AC-9.1-1", "<b>", "&amp;", "]]>",
                              "\x0c", "\x00", "\t", "\u2028", "*", ":"])
    item_text = st.lists(st.one_of(line_text, tokens), max_size=5).map("".join)
    # Text a spec states as it is: no control or separator characters, no XML non-characters, no surrounding space,
    # and not starting with the colon or bold marker that follows an item's id.
    printable = st.text(st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp"),
                                      blacklist_characters="\ufffe\uffff"), min_size=1, max_size=40) \
        .filter(lambda t: "<!--" not in t and t == t.strip() and t[0] not in ":*")

    class Properties(Project):
        @classmethod
        def setUpClass(cls):
            cls.make_project("properties")

        def documents(self, requirement, criterion, formats=("reqif", "needs", "html")):
            self.write_spec("9.1", title="Generated", context="Generated text.", nfrs="- none",
                            requirements="- REQ-9.1-1: %s" % requirement,
                            criteria="- AC-9.1-1 (REQ-9.1-1): Given %s, when it runs, then it works." % criterion)
            return {fmt: self.export(fmt, "--task", "9.1") for fmt in formats}

        @settings(max_examples=examples(20), deadline=None)
        @given(requirement=item_text, criterion=item_text)
        def test_any_spec_text_gives_valid_documents_that_agree(self, requirement, criterion):
            documents = self.documents(requirement, criterion)
            objects = reqif_check.objects(documents["reqif"])
            data = json.loads(documents["needs"])
            needs = data["versions"][data["current_version"]]["needs"]
            matrix = Matrix(documents["html"])

            self.assertEqual(reqif_check.problems(documents["reqif"]), [])
            for item in ("REQ-9.1-1", "AC-9.1-1"):
                text = objects[item].get("ReqIF.Text", "")
                self.assertEqual(needs[item]["title"], text or item)
                self.assertIn(" ".join(text.split()), matrix.row("9.1", "REQ-9.1-1")[0 if item[0] == "R" else 1])
            self.assertEqual([r for _, s, t in reqif_check.relations(documents["reqif"]) for r in (s, t)],
                             ["AC-9.1-1", "REQ-9.1-1"])

        @settings(max_examples=examples(15), deadline=None)
        @given(requirement=printable)
        def test_printable_text_is_exported_as_written(self, requirement):
            documents = self.documents(requirement, "a customer", formats=("reqif",))

            self.assertEqual(reqif_check.objects(documents["reqif"])["REQ-9.1-1"]["ReqIF.Text"], requirement)
else:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")


if __name__ == "__main__":
    unittest.main()
