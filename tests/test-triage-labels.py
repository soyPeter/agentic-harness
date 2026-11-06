"""The PR labels `harness.py receipt` suggests for human triage (ADR-002), checked through the receipt command.

One risk:* label comes from the spec's Change-Class and the receipt's risks; class:<class> is added when the spec
declares one of the four classes. The property checks need hypothesis (pip install -r tests/requirements.txt); the
decision table runs without it.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("docs", "refactor", "feature", "schema")
RISK_TERM = " Customers sign in with a password."
# (Change-Class line, the spec involves a risk term) -> suggested labels
TABLE = {
    ("Change-Class: docs", False): ["risk:low", "class:docs"],
    ("Change-Class: docs", True): ["risk:elevated", "class:docs"],
    ("Change-Class: refactor", False): ["risk:low", "class:refactor"],
    ("Change-Class: refactor", True): ["risk:elevated", "class:refactor"],
    ("Change-Class: feature", False): ["risk:elevated", "class:feature"],
    ("Change-Class: feature", True): ["risk:high", "class:feature"],
    ("Change-Class: schema", False): ["risk:high", "class:schema"],
    ("Change-Class: schema", True): ["risk:high", "class:schema"],
    (None, False): ["risk:elevated"],
    (None, True): ["risk:high"],
    ("Change-Class: chore", False): ["risk:elevated"],
    ("Change-Class: chore", True): ["risk:high"],
    ("Change-Class: <docs | refactor | feature | schema>", False): ["risk:elevated"],
    ("Change-Class: <docs | refactor | feature | schema>", True): ["risk:high"],
    ("Change-Class: <!-- unsure --> docs", False): ["risk:low", "class:docs"],
    ("Change-Class: `docs`", False): ["risk:elevated"],
}
LEVEL = {("docs", False): "risk:low", ("docs", True): "risk:elevated",
         ("refactor", False): "risk:low", ("refactor", True): "risk:elevated",
         ("feature", False): "risk:elevated", ("feature", True): "risk:high",
         ("schema", False): "risk:high", ("schema", True): "risk:high"}

SPEC = """# Spec 7.1: Customer search

Task: 7.1
PRD: none
{change_class}
## Context
Support needs to find customers by name.{risk}

## Requirements
- REQ-7.1-1: The system shall return customers whose name contains the query, ignoring case.

## Acceptance criteria
- AC-7.1-1 (REQ-7.1-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.

## Non-functional requirements
- none

## Architecture
ADRs: ADR-001
Tech requirements:
- The search lives in src/search.py.

## Skills
- code-quality: all code

## Out of scope
- Fuzzy matching.

## Assumptions
- none

## Open questions
- none

## Approval
"""


def final_message(report):
    return "Done.\n\n```json\n%s\n```" % json.dumps(report)


class JudgedTask(unittest.TestCase):
    """A project whose task 7.1 has a judge pass on its current code, so `receipt 7.1` answers."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="triage labels ")
        cls.project = Path(cls.temp.name).resolve() / "project"
        cls.project.mkdir()
        cls.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test",
                       GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                       GIT_COMMITTER_EMAIL="test@example.com", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true",
                       HARNESS_REVIEW="off", HARNESS_DELIVER="off", PYTHONDONTWRITEBYTECODE="1",
                       CLAUDE_PROJECT_DIR=str(cls.project))
        for key in ("HARNESS_ROOT", "HARNESS_AUTONOMY", "HARNESS_PROFILE", "HARNESS_ROLE"):
            cls.env.pop(key, None)
        cls.command("git", "init", "-q", "-b", "main")
        cls.command(str(ROOT / "bootstrap.sh"), str(cls.project), "--name", "labels")
        cls.command("git", "add", "-A")
        cls.command("git", "commit", "-qm", "chore: adopt agentic harness")
        cls.spec = cls.project / "backbone/specs/7.1.md"
        cls.spec.parent.mkdir(parents=True, exist_ok=True)
        cls.spec.write_text(SPEC.format(change_class="", risk=""))
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n")
        cls.command("git", "add", "-A")
        cls.command("git", "commit", "-qm", "docs: spec for task 7.1")
        cls.hook("grill-stop", "griller", {"verdict": "pass", "task": "7.1", "questions": [], "summary": "s"})
        cls.spec.write_text(cls.spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 7.1", "- [WIP] **Task 7.1"))
        (cls.project / "src").mkdir(exist_ok=True)
        (cls.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (cls.project / "tests").mkdir(exist_ok=True)
        (cls.project / "tests/test_search.py").write_text("def test_contains():  # AC-7.1-1\n    assert True\n")
        cls.hook("judge-stop", "judge", {
            "verdict": "pass", "task": "7.1", "summary": "s", "findings": [],
            "criteria": [{"id": "AC-7.1-1", "met": True, "evidence": "src/search.py:2", "tests": ["test_contains"]}],
            "tests": {"command": "true", "result": "passed"}})

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def command(cls, *args, input=None):
        result = subprocess.run(args, cwd=cls.project, env=cls.env, input=input, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    @classmethod
    def hook(cls, event, agent, report):
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": final_message(report)}
        cls.command("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"), "hook", event,
                    input=json.dumps(stop))

    def receipt(self, change_class, risky, *flags):
        """`receipt 7.1` with the spec declaring change_class (a whole line, or None for no line)."""
        text = SPEC.format(change_class=change_class + "\n" if change_class is not None else "",
                           risk=RISK_TERM if risky else "")
        self.spec.write_text(text + "Approved-by: Ana (2026-11-01)\n")
        return self.command("python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "receipt",
                            "7.1", *flags)

    def receipt_json(self, change_class, risky):
        data = json.loads(self.receipt(change_class, risky, "--json").stdout)
        self.assertEqual(any("password" in reason for reason in data["risks"]), risky, data["risks"])
        return data


class SuggestedLabels(JudgedTask):
    def test_each_change_class_and_risk_suggests_its_labels(self):
        for (change_class, risky), labels in TABLE.items():
            with self.subTest(change_class=change_class, risky=risky):
                self.assertEqual(self.receipt_json(change_class, risky)["suggested_labels"], labels)

    def test_the_text_receipt_lists_the_labels_as_advisory(self):
        text = self.receipt("Change-Class: feature", True).stdout

        section = text[text.index("SUGGESTED LABELS"):]
        self.assertIn("never approves or merges", section.splitlines()[0])
        self.assertEqual(re.findall(r"(?m)^  - (\S+)$", section), ["risk:high", "class:feature"])

    def test_the_text_receipt_says_why_an_undeclared_class_is_rated_as_feature(self):
        text = self.receipt(None, False).stdout

        section = text[text.index("SUGGESTED LABELS"):]
        self.assertEqual(re.findall(r"(?m)^  - (\S+)$", section), ["risk:elevated"])
        self.assertIn("no valid Change-Class", section)
        self.assertNotIn("no valid Change-Class", self.receipt("Change-Class: docs", False).stdout)


if given is not None:
    values = st.from_regex(r"[A-Za-z0-9_`*<>|:.-]{1,12}", fullmatch=True)

    class SuggestedLabelProperties(JudgedTask):
        @settings(max_examples=25, deadline=None)
        @given(name=st.sampled_from(CLASSES), case=st.sampled_from((str.lower, str.upper, str.title)),
               key=st.sampled_from(("Change-Class:", "change-class:", "CHANGE-CLASS:")),
               gap=st.sampled_from(("", " ", "\t", "   ")), trailer=st.sampled_from(("", " (typo fix)", "  ")),
               risky=st.booleans())
        def test_a_declared_class_is_read_whatever_its_case_and_spacing(self, name, case, key, gap, trailer, risky):
            data = self.receipt_json("%s%s%s%s" % (key, gap, case(name), trailer), risky)

            self.assertEqual(data["suggested_labels"], [LEVEL[name, bool(data["risks"])], "class:" + name])

        @settings(max_examples=25, deadline=None)
        @given(value=values.filter(lambda v: v.lower() not in CLASSES), risky=st.booleans())
        def test_any_other_value_is_rated_as_feature_without_a_class_label(self, value, risky):
            data = self.receipt_json("Change-Class: " + value, risky)

            self.assertEqual(data["suggested_labels"], [LEVEL["feature", bool(data["risks"])]])

        @settings(max_examples=15, deadline=None)
        @given(value=st.sampled_from(CLASSES) | values)
        def test_risks_never_lower_the_risk_label(self, value):
            order = ("risk:low", "risk:elevated", "risk:high")
            calm = self.receipt_json("Change-Class: " + value, False)["suggested_labels"][0]
            risky = self.receipt_json("Change-Class: " + value, True)["suggested_labels"][0]

            self.assertGreaterEqual(order.index(risky), order.index(calm))
else:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")


if __name__ == "__main__":
    unittest.main()
