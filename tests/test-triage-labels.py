"""The PR labels `harness.py receipt` suggests for human triage (ADR-002), checked through the receipt command, and
the deliverer's gate letting it apply each of them.

One risk:* label comes from the spec's Change-Class and the receipt's other risks; class:<class> is added when the
spec has a Change-Class line. The class is the one approve and risk use, so an invalid declaration is labelled
feature. The property checks need hypothesis (pip install -r tests/requirements.txt); the decision table runs
without it.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from hypothesis_profiles import examples

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("docs", "refactor", "feature", "schema")
RISK_TERM = " Customers sign in with a password."
# (Change-Class lines, the spec involves a risk term) -> suggested labels, for a change to documentation only
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
    ("Change-Class: <!-- unsure --> docs", False): ["risk:low", "class:docs"],
    ("Change-Class: docs\nChange-Class: DOCS", False): ["risk:low", "class:docs"],
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
Support needs to find customers by name.{context}

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


JUDGE_PASS = {"verdict": "pass", "task": "7.1", "summary": "s", "findings": [],
              "criteria": [{"id": "AC-7.1-1", "met": True, "evidence": "src/search.py:2", "tests": ["test_contains"]}],
              "tests": {"command": "true", "result": "passed"}}


def final_message(report):
    return "Done.\n\n```json\n%s\n```" % json.dumps(report)


class JudgedTask(unittest.TestCase):
    """A project whose task 7.1 has a judge pass on its current code and spec, so `receipt 7.1` answers. The search
    code was committed before the spec, so the task's own change is documentation; --base <adopted> takes in the code
    too."""

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
        cls.commit("chore: adopt agentic harness")
        cls.adopted = cls.command("git", "rev-parse", "HEAD").stdout.strip()
        (cls.project / "src").mkdir(exist_ok=True)
        (cls.project / "src/search.py").write_text(
            "def search(names, q):  # AC-7.1-1\n    return [n for n in names if q.lower() in n.lower()]\n")
        (cls.project / "tests").mkdir(exist_ok=True)
        (cls.project / "tests/test_search.py").write_text("def test_contains():  # AC-7.1-1\n    assert True\n")
        cls.commit("feat: customer search")
        cls.spec = cls.project / "backbone/specs/7.1.md"
        cls.spec.parent.mkdir(parents=True, exist_ok=True)
        cls.spec.write_text(SPEC.format(change_class="", context=""))
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 7.1: Customer search** (spec: backbone/specs/7.1.md)\n")
        cls.commit("docs: spec for task 7.1")
        cls.hook("grill-stop", "griller", {"verdict": "pass", "task": "7.1", "questions": [], "summary": "s"})
        cls.spec.write_text(cls.spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 7.1", "- [WIP] **Task 7.1"))
        (cls.project / "docs").mkdir(exist_ok=True)
        (cls.project / "docs/search.md").write_text("# Customer search\n\nA query matches any part of a name.\n")
        cls.hook("judge-stop", "judge", JUDGE_PASS)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def command(cls, *args, input=None, check=True):
        result = subprocess.run(args, cwd=cls.project, env=cls.env, input=input, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    @classmethod
    def commit(cls, message):
        cls.command("git", "add", "-A")
        cls.command("git", "commit", "-qm", message)

    @classmethod
    def harness(cls, *args, input=None, check=True):
        return cls.command("python3", "-B", str(cls.project / "scripts/harness/lib/harness.py"), *args, input=input,
                           check=check)

    @classmethod
    def hook(cls, event, agent, report):
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": final_message(report)}
        cls.harness("hook", event, input=json.dumps(stop))

    def receipt(self, change_class, risky, *flags, context="", approval=""):
        """`receipt 7.1` with the spec declaring change_class (whole lines, or None for no line), judged again on that
        spec, since a judge pass covers only the spec it judged. context goes at the end of the Context section and
        approval after the Approved-by line."""
        text = SPEC.format(change_class=change_class + "\n" if change_class is not None else "",
                           context=context + (RISK_TERM if risky else ""))
        self.spec.write_text(text + "Approved-by: Ana (2026-11-01)\n" + approval)
        self.hook("judge-stop", "judge", JUDGE_PASS)
        return self.harness("receipt", "7.1", *flags)

    def receipt_json(self, change_class, risky, *flags, **spec):
        data = json.loads(self.receipt(change_class, risky, "--json", *flags, **spec).stdout)
        self.assertEqual(any("password" in reason for reason in data["risks"]), risky, data["risks"])
        return data

    @staticmethod
    def labels_section(text):
        return text[text.index("SUGGESTED LABELS"):]


class SuggestedLabels(JudgedTask):
    def test_each_change_class_and_risk_suggests_its_labels(self):
        for (change_class, risky), labels in TABLE.items():
            with self.subTest(change_class=change_class, risky=risky):
                self.assertEqual(self.receipt_json(change_class, risky)["suggested_labels"], labels)

    def test_a_class_declared_twice_is_labelled_as_feature_as_approve_and_risk_count_it(self):
        for second in ("feature", "schema"):
            for risky, level in ((False, "risk:elevated"), (True, "risk:high")):
                with self.subTest(second=second, risky=risky):
                    data = self.receipt_json("Change-Class: docs\nChange-Class: " + second, risky)
                    risk = self.harness("risk", "7.1", check=False)

                    self.assertEqual(data["suggested_labels"], [level, "class:feature"])
                    self.assertEqual(data["change_class_problem"],
                                     "Change-Class is declared more than once (docs, %s): keep one" % second)
                    self.assertEqual(risk.returncode, 1, risk.stdout)
                    self.assertIn("Change-Class is invalid (see spec-check), so it counts as feature", risk.stdout)

    def test_an_invalid_class_is_labelled_as_feature_as_approve_and_risk_count_it(self):
        for value in ("chore", "`docs`", "docs refactor", "docs (typo fix)", "<docs | refactor | feature | schema>"):
            for risky, level in ((False, "risk:elevated"), (True, "risk:high")):
                with self.subTest(value=value, risky=risky):
                    data = self.receipt_json("Change-Class: " + value, risky)

                    self.assertEqual(data["suggested_labels"], [level, "class:feature"])
                    self.assertEqual(data["change_class_problem"],
                                     "Change-Class '%s' is not one of docs, refactor, feature, schema" % value)

    def test_a_class_under_approval_is_not_declared(self):
        data = self.receipt_json(None, False, approval="Change-Class: docs\n")

        self.assertEqual(data["suggested_labels"], ["risk:elevated"])
        self.assertIsNone(data["change_class_problem"])

    def test_a_docs_class_whose_change_touches_code_is_a_risk(self):
        data = self.receipt_json("Change-Class: docs", False, "--base", self.adopted)

        self.assertEqual(data["suggested_labels"], ["risk:elevated", "class:docs"])
        self.assertTrue(any("doesn't cover a change to files that aren't documentation: src/search.py" in reason
                            for reason in data["risks"]), data["risks"])

    def test_the_deliverer_may_apply_every_label_a_receipt_suggests(self):
        for change_class, risky in (("Change-Class: docs", False), ("Change-Class: refactor", True),
                                    ("Change-Class: feature", True), ("Change-Class: schema", False),
                                    ("Change-Class: chore", False)):
            with self.subTest(change_class=change_class, risky=risky):
                labels = self.receipt_json(change_class, risky)["suggested_labels"]

                gate = self.harness("hook", "pre-tool-use", check=False, input=json.dumps({
                    "session_id": "s", "agent_id": "a1", "agent_type": "deliverer", "tool_name": "Bash",
                    "tool_input": {"command": "gh pr create --title t --body b --label " + ",".join(labels)}}))

                self.assertEqual(gate.returncode, 0, gate.stderr)

    def test_the_text_receipt_lists_the_labels_as_advisory(self):
        section = self.labels_section(self.receipt("Change-Class: feature", True).stdout)

        self.assertIn("never approves or merges", section.splitlines()[0])
        self.assertEqual(re.findall(r"(?m)^  - (\S+)$", section), ["risk:high", "class:feature"])

    def test_the_text_receipt_says_why_a_spec_is_rated_as_feature(self):
        undeclared = self.labels_section(self.receipt(None, False).stdout)
        twice = self.labels_section(self.receipt("Change-Class: docs\nChange-Class: feature", False).stdout)
        docs = self.labels_section(self.receipt("Change-Class: docs", False).stdout)

        self.assertEqual(re.findall(r"(?m)^  - (\S+)$", undeclared), ["risk:elevated"])
        self.assertIn("rated as feature, as approve and risk count it, because the spec declares no Change-Class",
                      undeclared)
        self.assertIn("labelled as feature, as approve and risk count it, because Change-Class is declared more "
                      "than once (docs, feature): keep one", twice)
        self.assertNotIn("as feature", docs)


if given is not None:
    values = st.from_regex(r"[A-Za-z0-9_`*<>|:.-]{1,12}", fullmatch=True)
    class_names = st.sampled_from(CLASSES).flatmap(lambda name: st.sampled_from((name, name.upper(), name.title())))

    class SuggestedLabelProperties(JudgedTask):
        @settings(max_examples=examples(20), deadline=None)
        @given(name=st.sampled_from(CLASSES), case=st.sampled_from((str.lower, str.upper, str.title)),
               key=st.sampled_from(("Change-Class:", "change-class:", "CHANGE-CLASS:")),
               gap=st.sampled_from(("", " ", "\t", "   ")), trailer=st.sampled_from(("", "  ", "\t")),
               risky=st.booleans())
        def test_a_declared_class_is_read_whatever_its_case_and_spacing(self, name, case, key, gap, trailer, risky):
            data = self.receipt_json("%s%s%s%s" % (key, gap, case(name), trailer), risky)

            self.assertEqual(data["suggested_labels"], [LEVEL[name, risky], "class:" + name])

        @settings(max_examples=examples(15), deadline=None)
        @given(value=values.filter(lambda v: v.lower() not in CLASSES), risky=st.booleans())
        def test_any_other_value_is_labelled_like_a_declared_feature(self, value, risky):
            # The value is in both specs, so a risk term it happens to spell counts in both.
            invalid = self.receipt_json("Change-Class: " + value, risky)
            feature = self.receipt_json("Change-Class: feature", risky, context=" " + value)

            self.assertEqual(invalid["suggested_labels"], feature["suggested_labels"])

        @settings(max_examples=examples(25), deadline=None)
        @given(declared=st.lists(class_names | values, max_size=2), risky=st.booleans())
        def test_the_labels_name_the_class_approve_and_risk_use(self, declared, risky):
            labels = self.receipt_json("\n".join("Change-Class: " + v for v in declared) if declared else None,
                                       risky)["suggested_labels"]
            gates = json.loads(self.harness("next", "7.1", "--json").stdout)
            risk = self.harness("risk", "7.1", check=False)

            self.assertEqual(labels[1:], ["class:" + gates["change_class"]] if declared else [])
            self.assertEqual(labels[0] == "risk:low", risk.returncode == 0, risk.stdout)

        @settings(max_examples=examples(10), deadline=None)
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
