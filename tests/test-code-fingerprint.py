"""The code fingerprint a judge verdict records, through the public entry points, in throwaway projects.

The judge gate (finish), the receipt and the coordinator's state compare it with the fingerprint of the code now.
Git skips hashing a file whose size and timestamps (whole seconds) match its index entry, so the fingerprint must
come from the files' content: a same-size edit made within the second of an index write, or one that keeps the
file's mtime, is still a change.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


HARNESS = Path(__file__).resolve().parents[1]
TASK = "1.1"
SPEC = """# Spec 1.1: Item

Task: 1.1
PRD: none

## Context
A change.

## Requirements
- REQ-1.1-1: The system shall do one thing.

## Acceptance criteria
- AC-1.1-1 (REQ-1.1-1): Given a, when b, then c.

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
JUDGE_PASS = {"verdict": "pass", "task": TASK, "findings": [], "summary": "s",
              "criteria": [{"id": "AC-1.1-1", "met": True, "evidence": "e", "tests": ["test_app"]}],
              "tests": {"command": "true", "result": "passed"}}
STALE = "The code changed after the judge passed task 1.1"


def environment(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com", PYTHONDONTWRITEBYTECODE="1",
               HARNESS_VERIFY="off", HARNESS_REVIEW="off", HARNESS_DELIVER="off", HARNESS_TEST_CMD="true")
    env.update(settings)
    return env


def within_one_second(steps):
    """Run steps inside one wall-clock second, then wait for the next second. False if the clock ticked meanwhile."""
    # Linux stamps files with a clock that can lag by a scheduler tick, so start clear of the second's edge.
    while not 0.05 < time.time() % 1 < 0.3:
        time.sleep(0.005)
    second = int(time.time())
    steps()
    if int(time.time()) != second:
        return False
    while int(time.time()) == second:
        time.sleep(0.02)
    return True


class Project:
    """A project with the harness installed and task 1.1 [WIP], its spec and an acceptance test committed."""

    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        subprocess.run([str(HARNESS / "bootstrap.sh"), str(root)], env=environment(), check=True, capture_output=True)
        self.write("backbone/specs/1.1.md", SPEC)
        with open(root / "backbone/3-TASKS.md", "a", encoding="utf-8") as tasks:
            tasks.write("- [WIP] **Task 1.1: Item** (spec: backbone/specs/1.1.md)\n")
        self.write("tests/test_app.py", "def test_app():  # AC-1.1-1\n    pass\n")
        self.commit("chore: adopt the harness, start task 1.1")

    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=self.root, env=environment(), check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def harness(self, *args):
        result = subprocess.run(["python3", "-B", str(self.root / "scripts/harness/lib/harness.py")] + list(args),
                                cwd=self.root, env=environment(), capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def judge_pass(self):
        result = subprocess.run(
            ["python3", "-B", str(self.root / "scripts/harness/lib/harness.py"), "hook", "judge-stop"],
            cwd=self.root, capture_output=True, text=True, env=environment(CLAUDE_PROJECT_DIR=str(self.root)),
            input=json.dumps({"agent_type": "judge",
                              "last_assistant_message": "Done.\n\n```json\n%s\n```" % json.dumps(JUDGE_PASS)}))
        if "task 1.1: PASS" not in result.stdout:
            raise AssertionError("the judge pass was not recorded: %s%s" % (result.stdout, result.stderr))

    def judge_pass_current(self):
        """Whether the coordinator's state calls the judge pass current, i.e. on the code as it is now."""
        _, out = self.harness("state", "--json")
        return next(t for t in json.loads(out)["tasks"] if t["task"] == TASK)["judge"]["current"]

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def new_project(test):
    temp = tempfile.TemporaryDirectory(prefix="code fingerprint ")
    test.addCleanup(temp.cleanup)
    return Project(Path(temp.name).resolve() / "project")


class SameSecondEdit(unittest.TestCase):
    """src/app.py staged as 'a', then rewritten to 'b' (same size) within the second of that index write: from the
    next second on, its size and timestamps match the index entry although its content does not."""

    def setUp(self):
        self.project = new_project(self)

        def stage_then_rewrite():
            self.project.write("src/app.py", "VALUE = 'a'\n")
            self.project.git("add", "-A")
            self.project.write("src/app.py", "VALUE = 'b'\n")

        if not any(within_one_second(stage_then_rewrite) for _ in range(5)):
            self.fail("could not stage and rewrite src/app.py within one second")

    def test_committing_the_judged_code_keeps_its_judge_pass(self):
        self.project.judge_pass()
        self.project.commit("feat: task 1.1")

        code, out = self.project.harness("receipt", TASK)

        self.assertEqual(code, 0, out)

    def test_restoring_the_staged_version_after_the_judge_needs_a_new_judge_pass(self):
        self.project.judge_pass()
        self.project.git("checkout", "--", "src/app.py")

        code, out = self.project.harness("finish", TASK)

        self.assertEqual(code, 1, out)
        self.assertIn(STALE, out)


class KeptMtime(unittest.TestCase):
    def test_a_same_size_edit_that_keeps_the_mtime_needs_a_new_judge_pass(self):
        project = new_project(self)
        # With ctime not trusted (as on file systems that change it behind git's back), git has only the mtime and
        # the size to tell that a file changed, and it trusts them for a file older than the index: dated 2020.
        project.git("config", "core.trustctime", "false")
        app = project.write("src/app.py", "VALUE = 'a'\n")
        os.utime(app, (1577836800, 1577836800))
        project.commit("feat: app")
        project.judge_pass()

        project.write("src/app.py", "VALUE = 'b'\n")
        os.utime(app, (1577836800, 1577836800))   # the old mtime again, as cp -p and touch -r leave it
        code, out = project.harness("finish", TASK)

        self.assertEqual(code, 1, out)
        self.assertIn(STALE, out)


class WhatCounts(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)
        self.project.write(".gitignore", "*.log\nbuild/\n")
        self.project.write("build/bundle.js", "a\n")
        self.project.git("add", "-f", "build/bundle.js")
        self.project.commit("build: bundle")
        self.project.judge_pass()

    def test_a_new_untracked_file_makes_the_judge_pass_stale(self):
        self.project.write("src/new.py", "VALUE = 1\n")

        self.assertFalse(self.project.judge_pass_current())

    def test_an_ignored_file_leaves_the_judge_pass_current(self):
        self.project.write("debug.log", "trace\n")

        self.assertTrue(self.project.judge_pass_current())

    def test_a_tracked_file_that_matches_gitignore_still_counts(self):
        self.project.write("build/bundle.js", "rebuilt\n")

        self.assertFalse(self.project.judge_pass_current())


if __name__ == "__main__":
    unittest.main()
