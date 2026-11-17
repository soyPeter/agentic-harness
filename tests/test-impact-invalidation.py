"""Impact invalidation (the harness's ADR-007) through the public entry points, in throwaway projects.

  what changed after a pass was recorded     grill pass   judge, review and tester records   finishing the task
  nothing                                    current      current                            allowed
  a criterion, a constraint, an assumption,  stale        stale (another spec revision)      refused until the griller, the user's
  the Change-Class or any other spec line                                                    approval and the judge (lenses, tester)
  but an Approved-by line                                                                    cover the current spec again
  an ADR the spec references                 stale        stale                              refused until re-grilled and re-judged
  the code                                   current      stale (other code)                 refused until re-judged
  another task's spec                        current      current                            allowed

An approved spec is frozen for agents, so a spec changes after approval only when the user removes the approval;
finishing then needs it back. A record from before verdicts carried the spec revision counts as stale: what it judged
is unknown. A stale pass stays in the verdict history, and the new one is appended after it. Verify (pre-commit and
CI) refuses a commit that finishes a task whose spec isn't approved, and one that changes an approved spec while its
Approved-by lines stay as they were: that approval was given on the earlier text.
The property checks need hypothesis (pip install -r tests/requirements.txt) and are skipped without it.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from hypothesis_profiles import examples

try:
    from hypothesis import example, given, settings, strategies as st
except ImportError:
    given = None


HARNESS = Path(__file__).resolve().parents[1]
TASK = "1.1"
SPEC = """# Spec {task}: Search

Task: {task}
PRD: none
Change-Class: feature

## Context
Users search the catalogue by name.

## Requirements
- REQ-{task}-1: The system shall list the items whose name matches the query.

## Acceptance criteria
- AC-{task}-1 (REQ-{task}-1): Given a catalogue, when a user searches "tea", then the items named tea are listed.

## Non-functional requirements
- Search runs on the existing index.

## Architecture
ADRs: {adrs}
Tech requirements:
- Keep the current module layout.

## Skills
- code-quality: all code

## Out of scope
- Ranking.

## Assumptions
- A1: The catalogue fits in memory (source: backbone/4-KNOWLEDGE.md).

## Open questions
- none

## Approval
"""
ADR = """# ADR-002: Search over the in-memory index

## Status
Proposed

## Context
Search needs an index.

## Decision
Search the in-memory index.

## Alternatives considered
- A search service: more to run.

## Consequences
- Search is limited to one process.
"""
APPROVAL = "Approved-by: Ana (2026-11-10)\n"
RENEWED = "Approved-by: Ana (2026-11-11, after the change)\n"
EDITS = {   # what the user changes in the spec, as (old text, new text)
    "criterion": ("then the items named tea are listed.", "then the items named tea are listed, cheapest first."),
    "constraint": ("- Search runs on the existing index.", "- Search runs on the existing index, within 200 ms."),
    "assumption": ("The catalogue fits in memory", "The catalogue may outgrow memory"),
    "class": ("Change-Class: feature", "Change-Class: schema"),
    "context": ("Users search the catalogue by name.", "Shop staff search the catalogue by name."),
}
CODE = {"src/search.py": "def search(items, query):\n    return [i for i in items if query in i]\n",
        "tests/test_search.py": "# AC-{task}-1\ndef test_ac():\n    assert True\n"}
STALE_SPEC = "changed after the judge passed"
LATE_CRITERION = ("- AC-{task}-2 (REQ-{task}-1): Given a catalogue, when a user searches, then the results show within 1 "
                  "second.\n").format(task=TASK)


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
        self.write("backbone/adr/ADR-002-search.md", ADR)
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

    def spec(self, task=TASK):
        return "backbone/specs/%s.md" % task

    def add_task(self, task=TASK, adrs="ADR-001"):
        self.write(self.spec(task), SPEC.format(task=task, adrs=adrs))
        with open(self.root / "backbone/3-TASKS.md", "a", encoding="utf-8") as tasks:
            tasks.write("- [ ] **Task %s: Search** (spec: backbone/specs/%s.md)\n" % (task, task))

    def task_line(self, task=TASK):
        return next(line for line in self.read("backbone/3-TASKS.md").splitlines()
                    if "**Task %s: Search**" % task in line)

    def set_marker(self, old, new, task=TASK):
        tasks = self.read("backbone/3-TASKS.md")
        self.write("backbone/3-TASKS.md", tasks.replace("- [%s] **Task %s: Search**" % (old, task),
                                                        "- [%s] **Task %s: Search**" % (new, task), 1))

    def approve(self, line=APPROVAL, task=TASK):
        """The user's own approval line, written by hand as the user does."""
        self.write(self.spec(task), self.read(self.spec(task)) + line)

    def remove_approval(self, task=TASK):
        text = self.read(self.spec(task))
        self.write(self.spec(task), "".join(l for l in text.splitlines(True) if not l.startswith("Approved-by:")))

    def edit_spec(self, edit, task=TASK):
        old, new = EDITS[edit]
        text = self.read(self.spec(task))
        assert old in text, (edit, old)
        self.write(self.spec(task), text.replace(old, new, 1))

    def change_spec(self, edit, task=TASK):
        """The user's way to change an approved spec: remove the approval, change the text, grill it again."""
        self.remove_approval(task)
        self.edit_spec(edit, task)
        self.grill_pass(task)

    def grill_pass(self, task=TASK):
        return self.hook("grill-stop", {"agent_type": "griller", "last_assistant_message": verdict(
            {"verdict": "pass", "task": task, "questions": [], "summary": "s"})})

    def judge_pass(self, task=TASK, criteria=(1,), **settings):
        return self.hook("judge-stop", {"agent_type": "judge", "last_assistant_message": verdict(
            {"verdict": "pass", "task": task, "findings": [], "summary": "s",
             "criteria": [{"id": "AC-%s-%d" % (task, n), "met": True, "evidence": "src/search.py:1",
                           "tests": ["test_ac"]} for n in criteria],
             "tests": {"command": "true", "result": "passed"}})}, **settings)

    def review_pass(self, lens, task=TASK, **settings):
        return self.hook("review-stop", {"agent_type": "reviewer", "last_assistant_message": verdict(
            {"lens": lens, "verdict": "pass", "task": task, "findings": [], "summary": "s"})}, **settings)

    def tester_records(self, task=TASK, **settings):
        self.write("tests/acceptance/test_search_acceptance.py", "# AC-%s-1\ndef test_ac():\n    assert True\n" % task)
        return self.hook("tester-stop", {"agent_type": "tester", "last_assistant_message": verdict(
            {"tests": ["tests/acceptance/test_search_acceptance.py"], "task": task, "red": True, "summary": "s"})},
            **settings)

    def build(self, task=TASK):
        for name, text in CODE.items():
            self.write(name, text.format(task=task))

    def judged_wip(self, task=TASK, adrs="ADR-001"):
        """A task the user approved, the griller passed, that started, was built and the judge passed."""
        self.add_task(task, adrs)
        self.approve(task=task)
        self.grill_pass(task)
        code, out = self.harness("start", task)
        assert code == 0, out
        self.build(task)
        code, out = self.judge_pass(task)
        assert "PASS" in out, out

    def finish(self, task=TASK, **settings):
        return self.harness("finish", task, **settings)

    def next_step(self, task=TASK, **settings):
        return json.loads(self.harness("next", task, "--json", **settings)[1])

    def state(self, task=TASK, **settings):
        return next(t for t in json.loads(self.harness("state", "--json", **settings)[1])["tasks"]
                    if t["task"] == task)

    def history(self, kind, task=TASK):
        return json.loads(self.read("backbone/.verdicts/%s.%s.json" % (task, kind)))["history"]

    def drop_spec_revisions(self, kind, task=TASK):
        """The record as a harness from before spec-bound verdicts wrote it: without the spec revision."""
        name = "backbone/.verdicts/%s.%s.json" % (task, kind)
        record = json.loads(self.read(name))
        for entry in record["history"]:
            entry.pop("spec", None)
        self.write(name, json.dumps(record, indent=2) + "\n")

    def verify(self, *args):
        self.git("add", "-A")
        return self.harness("verify", *args)


def new_project(test):
    temp = tempfile.TemporaryDirectory(prefix="impact ")
    test.addCleanup(temp.cleanup)
    return Project(Path(temp.name).resolve() / "project")


class Finish(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)
        self.project.judged_wip()

    def test_an_unchanged_spec_keeps_its_evidence(self):
        code, out = self.project.finish()

        self.assertEqual(code, 0, out)
        self.assertIn("[x]", self.project.task_line())

    def test_a_judge_pass_on_the_earlier_spec_does_not_finish_the_task(self):
        for edit in EDITS:
            with self.subTest(edit=edit):
                self.project.change_spec(edit)
                self.project.approve(RENEWED)

                code, out = self.project.finish()

                self.assertEqual(code, 1, out)
                self.assertIn(STALE_SPEC, out)
                self.assertIn("[WIP]", self.project.task_line())
                self.project.judge_pass()

    def test_the_judge_on_the_current_spec_lets_it_finish(self):
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)
        self.project.judge_pass()

        code, out = self.project.finish()

        self.assertEqual(code, 0, out)

    def test_finishing_needs_the_approval_back_after_the_spec_changed(self):
        self.project.change_spec("criterion")
        self.project.judge_pass()

        refused, out = self.project.finish()
        self.project.approve(RENEWED)
        finished, after = self.project.finish()

        self.assertEqual(refused, 1, out)
        self.assertIn("Task 1.1 cannot finish", out)
        self.assertIn("approve", out)
        self.assertEqual(finished, 0, after)

    def test_finishing_needs_a_grill_pass_on_the_changed_spec(self):
        self.project.remove_approval()
        self.project.edit_spec("constraint")
        self.project.approve(RENEWED)
        self.project.judge_pass()

        code, out = self.project.finish()

        self.assertEqual(code, 1, out)
        self.assertIn("Task 1.1 cannot finish: the spec or its ADRs changed after the griller passed it", out)

    def test_an_agent_marking_the_task_done_meets_the_same_refusal(self):
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)
        line = "- [WIP] **Task 1.1: Search**"

        code, out = self.project.hook("pre-tool-use", {"agent_id": "session", "tool_name": "Edit", "tool_input": {
            "file_path": str(self.project.root / "backbone/3-TASKS.md"), "old_string": line,
            "new_string": line.replace("[WIP]", "[x]")}})

        self.assertEqual(code, 2, out)
        self.assertIn(STALE_SPEC, out)

    def test_a_pass_recorded_without_the_spec_revision_counts_as_stale(self):
        self.project.drop_spec_revisions("judge")

        code, out = self.project.finish()

        self.assertEqual(code, 1, out)
        self.assertIn("records no spec revision", out)


class NextAndState(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)
        self.project.judged_wip()

    def test_next_sends_the_task_back_to_the_judge_after_its_spec_changed(self):
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)

        step = self.project.next_step()

        self.assertEqual((step["step"], step["role"]), ("judge", "judge"), step)
        self.assertIn("spec changed after the judge", step["reason"])

    def test_next_asks_for_the_approval_again_before_the_task_goes_on(self):
        self.project.change_spec("criterion")

        supervised = self.project.next_step()
        autonomous = self.project.next_step(HARNESS_AUTONOMY="autonomous")

        self.assertEqual((supervised["step"], supervised["role"]), ("approve", None), supervised)
        self.assertIn("backbone/specs/1.1.md", supervised["needed"])
        self.assertIn("no longer approved", supervised["reason"])
        self.assertEqual(autonomous["step"], "approve", autonomous)
        self.assertIn("harness.py approve 1.1", autonomous["command"])

    def test_next_sends_a_pass_without_a_spec_revision_back_to_the_judge(self):
        self.project.drop_spec_revisions("judge")

        step = self.project.next_step()

        self.assertEqual(step["step"], "judge", step)
        self.assertIn("records no spec revision", step["reason"])

    def test_state_says_which_evidence_is_stale(self):
        before = self.project.state()
        self.project.change_spec("constraint")
        after = self.project.state()
        code, text = self.project.harness("state")

        self.assertEqual(before["judge"], {"verdict": "pass", "current": True, "stale": None})
        self.assertEqual(after["judge"], {"verdict": "pass", "current": False, "stale": "spec"})
        self.assertFalse(after["approved"])
        self.assertEqual(code, 0, text)
        self.assertIn("judge pass on an earlier spec", text)
        self.assertIn("not approved", text)

    def test_state_still_names_changed_code_first(self):
        self.project.write("src/search.py", "def search(items, query):\n    return []\n")

        self.assertEqual(self.project.state()["judge"], {"verdict": "pass", "current": False, "stale": "code"})

    def test_review_lenses_passed_on_the_earlier_spec_are_due_again(self):
        review = {"HARNESS_REVIEW": "on"}
        for lens in ("correctness", "structure", "lean"):
            self.project.review_pass(lens, **review)
        self.assertEqual(self.project.next_step(**review)["step"], "finish")
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)
        self.project.judge_pass(**review)

        step = self.project.next_step(**review)
        code, out = self.project.finish(**review)

        self.assertEqual(step["step"], "review", step)
        self.assertEqual(step["lenses"], ["correctness", "structure", "lean"])
        self.assertEqual(code, 1, out)
        self.assertIn("The spec changed after the correctness review of task 1.1 passed", out)

    def test_acceptance_tests_recorded_on_the_earlier_spec_go_back_to_the_tester(self):
        tester = {"HARNESS_TESTER": "on"}
        self.project.tester_records(**tester)
        self.project.judge_pass(**tester)
        self.assertEqual(self.project.next_step(**tester)["step"], "finish")
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)
        self.project.judge_pass(**tester)

        step = self.project.next_step(**tester)
        code, out = self.project.finish(**tester)

        self.assertEqual((step["step"], step["role"]), ("test", "tester"), step)
        self.assertIn("spec changed", step["reason"])
        self.assertEqual(code, 1, out)
        self.assertIn("changed after the tester recorded", out)


class Receipt(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)
        self.project.judged_wip()

    def test_the_receipt_names_the_spec_revision_and_code_the_judge_passed(self):
        code, out = self.project.harness("receipt", TASK, "--json")

        receipt = json.loads(out)
        grill = self.project.history("grill")[-1]
        judge = self.project.history("judge")[-1]
        self.assertEqual(code, 0, out)
        self.assertEqual(receipt["judged_on"], {"spec": grill["fingerprint"], "code": judge["fingerprint"]})

    def test_the_receipt_refuses_a_pass_on_the_earlier_spec(self):
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)

        code, out = self.project.harness("receipt", TASK)

        self.assertEqual(code, 1, out)
        self.assertIn("the spec changed after the judge passed task 1.1; judge it again first", out)
        self.assertNotIn("cheapest first", out)

    def test_the_receipt_refuses_a_pass_without_a_spec_revision(self):
        self.project.drop_spec_revisions("judge")

        code, out = self.project.harness("receipt", TASK)

        self.assertEqual(code, 1, out)
        self.assertIn("records no spec revision", out)


class History(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)
        self.project.judged_wip()

    def test_the_stale_pass_stays_in_the_history_next_to_the_new_one(self):
        first = self.project.history("judge")
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)
        self.project.judge_pass()

        history = self.project.history("judge")

        self.assertEqual(history[:1], first)
        self.assertEqual(len(history), 2)
        self.assertNotEqual(history[0]["spec"], history[1]["spec"])
        self.assertEqual(history[1]["spec"], self.project.history("grill")[-1]["fingerprint"])


class Scope(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)

    def test_another_tasks_spec_change_leaves_this_tasks_evidence_current(self):
        self.project.judged_wip()
        self.project.add_task("1.2")
        self.project.approve(task="1.2")
        self.project.change_spec("criterion", task="1.2")

        self.assertTrue(self.project.state()["judge"]["current"])
        self.assertEqual(self.project.finish()[0], 0)

    def test_a_change_to_an_adr_the_spec_follows_makes_its_passes_stale(self):
        self.project.judged_wip(adrs="ADR-002")
        self.project.write("backbone/adr/ADR-002-search.md",
                           ADR.replace("Search the in-memory index.", "Search a sharded index."))

        state = self.project.state()
        code, out = self.project.finish()

        self.assertFalse(state["grill"]["current"])
        self.assertEqual(state["judge"]["stale"], "spec")
        self.assertEqual(self.project.next_step()["step"], "grill")
        self.assertEqual(code, 1, out)
        self.assertIn(STALE_SPEC, out)


class CriterionUnderApproval(unittest.TestCase):
    """The template puts '## Approval' last, so a criterion appended at the end of a spec lands inside it. It is part
    of what the griller, the user and the judge passed all the same."""

    def setUp(self):
        self.project = new_project(self)
        self.project.add_task()
        self.project.write(self.project.spec(), self.project.read(self.project.spec()) + LATE_CRITERION)
        self.project.approve()
        self.project.grill_pass()
        code, out = self.project.harness("start", TASK)
        assert code == 0, out
        self.project.build()
        self.project.write("tests/test_speed.py", "# AC-%s-2\ndef test_ac():\n    assert True\n" % TASK)
        code, out = self.project.judge_pass(criteria=(1, 2))
        assert "PASS" in out, out

    def reword(self):
        text = self.project.read(self.project.spec())
        self.project.write(self.project.spec(), text.replace("within 1 second", "within 60 seconds"))

    def test_rewording_it_makes_the_judge_pass_stale(self):
        self.reword()

        state = self.project.state()
        code, out = self.project.finish()
        receipt, refusal = self.project.harness("receipt", TASK)

        self.assertFalse(state["grill"]["current"], state)
        self.assertEqual(state["judge"]["stale"], "spec", state)
        self.assertEqual(code, 1, out)
        self.assertIn(STALE_SPEC, out)
        self.assertEqual(receipt, 1, refusal)
        self.assertNotIn("within 1 second", refusal)

    def test_an_agent_cannot_reword_it_once_the_spec_is_approved(self):
        code, out = self.project.hook("pre-tool-use", {"agent_id": "analyst", "tool_name": "Edit", "tool_input": {
            "file_path": str(self.project.root / self.project.spec()), "old_string": "within 1 second",
            "new_string": "within 60 seconds"}}, HARNESS_SKILL_GATE="off")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

    def test_its_words_count_when_policy_assesses_the_risk(self):
        self.project.add_task("1.2")
        text = self.project.read(self.project.spec("1.2")).replace("Change-Class: feature", "Change-Class: refactor")
        self.project.write(self.project.spec("1.2"), text + "- AC-1.2-2 (REQ-1.2-1): Given a catalogue, when a user "
                           "searches, then no password is shown.\n")
        self.project.grill_pass("1.2")

        code, out = self.project.harness("approve", "1.2", HARNESS_AUTONOMY="autonomous")

        self.assertEqual(code, 1, out)
        self.assertIn("the spec involves password", out)
        self.assertNotIn("Approved-by:", self.project.read(self.project.spec("1.2")))

    def test_verify_refuses_a_commit_that_rewords_it_under_the_same_approval(self):
        self.project.commit("feat: start task 1.1")
        self.reword()

        code, out = self.project.verify()

        self.assertEqual(code, 1, out)
        self.assertIn("approval was given on the earlier text", out)


class Verify(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)
        self.project.judged_wip()
        self.base = self.project.commit("feat: start task 1.1")

    def test_a_commit_that_finishes_a_task_needs_its_spec_approved(self):
        self.project.change_spec("criterion")
        self.project.judge_pass()
        self.project.set_marker("WIP", "x")

        code, out = self.project.verify()

        self.assertEqual(code, 1, out)
        self.assertIn("Task 1.1 cannot finish", out)

    def test_a_commit_that_finishes_a_task_on_the_renewed_spec_passes(self):
        self.project.change_spec("criterion")
        self.project.approve(RENEWED)
        self.project.judge_pass()
        self.project.set_marker("WIP", "x")

        code, out = self.project.verify()

        self.assertEqual(code, 0, out)

    def test_a_commit_that_changes_an_approved_spec_needs_a_new_approval_line(self):
        self.project.edit_spec("criterion")

        kept, out = self.project.verify()
        self.project.remove_approval()
        self.project.approve(RENEWED)
        renewed, after = self.project.verify()

        self.assertEqual(kept, 1, out)
        self.assertIn("approval was given on the earlier text", out)
        self.assertEqual(renewed, 0, after)

    def test_ci_refuses_it_in_a_range_unless_a_maintainer_let_user_changes_through(self):
        self.project.edit_spec("assumption")
        self.project.commit("docs: reword an assumption")

        code, out = self.project.harness("verify", "--range", "%s..HEAD" % self.base)
        allowed, after = self.project.harness("verify", "--range", "%s..HEAD" % self.base, "--allow-user-changes")

        self.assertEqual(code, 1, out)
        self.assertIn("approval was given on the earlier text", out)
        self.assertEqual(allowed, 0, after)

    def test_ci_accepts_an_approval_removed_with_the_change_and_given_again_with_the_same_line(self):
        self.project.remove_approval()
        self.project.edit_spec("criterion")
        self.project.grill_pass()
        changed, out = self.project.verify()
        self.project.commit("docs: change a criterion, approval taken back")
        self.project.approve(APPROVAL)
        approved, after = self.project.verify()
        self.project.commit("docs: approve the changed spec (same day, same line)")

        code, ranged = self.project.harness("verify", "--range", "%s..HEAD" % self.base)

        self.assertEqual((changed, approved), (0, 0), out + after)
        self.assertEqual(code, 0, ranged)

    def test_ci_accepts_a_merge_that_brings_in_such_a_renewal(self):
        self.project.git("checkout", "-q", "-b", "spec-change")
        self.project.remove_approval()
        self.project.edit_spec("criterion")
        self.project.grill_pass()
        self.project.commit("docs: change a criterion, approval taken back")
        self.project.approve(APPROVAL)
        self.project.commit("docs: approve the changed spec (same day, same line)")
        self.project.git("checkout", "-q", "main")
        self.project.write("docs/notes.md", "Notes.\n")
        self.project.commit("docs: notes")
        self.project.git("merge", "-q", "--no-ff", "-m", "Merge the spec change", "spec-change")

        code, out = self.project.harness("verify", "--range", "%s..HEAD" % self.base)

        self.assertEqual(code, 0, out)

    def test_ci_accepts_a_change_whose_approval_a_later_commit_renews(self):
        self.project.edit_spec("criterion")
        self.project.commit("docs: change a criterion (committed outside the hooks)")
        self.project.remove_approval()
        self.project.approve(RENEWED)
        self.project.commit("docs: approve the changed spec")

        code, out = self.project.harness("verify", "--range", "%s..HEAD" % self.base)

        self.assertEqual(code, 0, out)

    def test_ci_refuses_a_change_under_an_approval_renewed_only_before_it(self):
        self.project.remove_approval()
        self.project.edit_spec("criterion")
        self.project.grill_pass()
        self.project.approve(RENEWED)
        self.project.commit("docs: change a criterion and approve it")
        self.project.edit_spec("assumption")
        self.project.commit("docs: reword an assumption under that approval")

        code, out = self.project.harness("verify", "--range", "%s..HEAD" % self.base)

        self.assertEqual(code, 1, out)
        self.assertIn("approval was given on the earlier text", out)


@unittest.skipIf(given is None, "hypothesis is not installed (pip install -r tests/requirements.txt)")
class Properties(unittest.TestCase):
    """The two rules as decision tables, each example on one shared project reset to a committed baseline."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="impact properties ")
        cls.project = Project(Path(cls.temp.name).resolve() / "project")
        cls.project.judged_wip(adrs="ADR-002")
        cls.judged = cls.project.commit("feat: start task 1.1")
        cls.project.remove_approval()
        cls.unapproved = cls.project.commit("docs: take the approval back")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reset(self, commit):
        self.project.git("reset", "-q", "--hard", commit)
        self.project.git("clean", "-fdq")

    if given is not None:
        @settings(max_examples=examples(40), deadline=None)
        @given(edit=st.sampled_from((None,) + tuple(EDITS)), code=st.booleans(), adr=st.booleans(),
               unrecorded=st.booleans())
        @example(edit=None, code=False, adr=False, unrecorded=False)
        def test_a_judge_pass_is_current_only_on_the_code_and_spec_it_judged(self, edit, code, adr, unrecorded):
            self.reset(self.judged)
            if edit:
                self.project.edit_spec(edit)
            if code:
                self.project.write("src/search.py", "def search(items, query):\n    return []\n")
            if adr:
                self.project.write("backbone/adr/ADR-002-search.md",
                                   ADR.replace("Search the in-memory index.", "Search a sharded index."))
            if unrecorded:
                self.project.drop_spec_revisions("judge")

            judge = self.project.state()["judge"]

            self.assertEqual(judge["current"], not (edit or code or adr or unrecorded), judge)

        @settings(max_examples=examples(40), deadline=None)
        @given(approved_before=st.booleans(), approval_after=st.sampled_from(("none", "same", "renewed")),
               edit=st.sampled_from((None, "criterion", "class", "note in Approval")))
        @example(approved_before=True, approval_after="same", edit="criterion")
        @example(approved_before=True, approval_after="same", edit="note in Approval")
        @example(approved_before=True, approval_after="none", edit="criterion")
        def test_an_approval_holds_only_for_the_text_it_was_given_on(self, approved_before, approval_after, edit):
            self.reset(self.judged if approved_before else self.unapproved)
            self.project.remove_approval()
            if edit == "note in Approval":
                self.project.approve("Reviewed with the support team.\n")
            elif edit:
                self.project.edit_spec(edit)
            self.project.approve({"none": "", "same": APPROVAL, "renewed": RENEWED}[approval_after])

            code, out = self.project.verify()

            frozen = approved_before and approval_after == "same" and edit is not None
            self.assertEqual("approval was given on the earlier text" in out, frozen, out)
            self.assertEqual(code, 1 if frozen else 0, out)


if __name__ == "__main__":
    unittest.main()
