"""Live check of thin mode with a real Claude Code session (opt-in: HARNESS_E2E=1, needs `claude` on the PATH).

A thin project with task 2.1 grilled, approved, [WIP] and implemented; the session loads this repository as the
plugin and runs the plugin's judge. The harness must record the judge's verdict, as it does for a full install.
Costs one short agent session (about USD 0.50) per run, so it runs before a release, not on every push.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "plugin/launcher.py"
RELEASE_FILES = ("VERSION", "payload", "plugin", "tools/thin.py", ".claude-plugin", ".codex-plugin", "package.json")

SPEC = """# Spec 2.1: Customer search

Task: 2.1
PRD: none

## Context
Support needs to find customers by name.

## Requirements
- REQ-2.1-1: The system shall return the customers whose name contains the query, ignoring case.
- REQ-2.1-2: The system shall reject queries shorter than 2 characters.

## Acceptance criteria
- AC-2.1-1 (REQ-2.1-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.
- AC-2.1-2 (REQ-2.1-2): Given customers "Ana" and "Bob", when searching "a", then a ValueError is raised.

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
<!-- The user approves by adding a line "Approved-by: <name> (<date>)" below. Agents cannot. -->
Approved-by: Test (2026-11-06)
"""

CODE = '''def search(query, customers):
    if len(query) < 2:
        raise ValueError("a query needs at least 2 characters")
    return [name for name in customers if query.lower() in name.lower()]
'''

TESTS = '''import unittest

from src.search import search


class SearchTest(unittest.TestCase):
    def test_returns_names_containing_the_query_ignoring_case(self):  # AC-2.1-1
        self.assertEqual(search("an", ["Ana", "Bob"]), ["Ana"])

    def test_rejects_a_one_character_query(self):  # AC-2.1-2
        with self.assertRaises(ValueError):
            search("a", ["Ana", "Bob"])
'''

GRILL_PASS = "Grilled.\n\n```json\n" + json.dumps({"verdict": "pass", "task": "2.1", "questions": [],
                                                    "summary": "Complete and testable."}) + "\n```"

PROMPT = ("Task 2.1 is [WIP] and implemented; its next step is the judge. Launch the judge subagent "
          "(agentic-harness:judge) on task 2.1. Do not edit any files and do nothing else.")


@unittest.skipUnless(os.environ.get("HARNESS_E2E") == "1" and shutil.which("claude"),
                     "live agent session: set HARNESS_E2E=1 (needs claude on the PATH)")
class LivePlugin(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="live plugin ")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.release = self.work / "release"
        self.project = self.work / "project"
        self.env = dict(os.environ, HARNESS_ENGINE_SOURCE=str(self.release), HARNESS_ENGINES=str(self.work / "engines"),
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com")
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        self.publish_release()
        self.make_project()

    def run_at(self, cwd, *args, stdin=""):
        result = subprocess.run(args, cwd=cwd, env=self.env, input=stdin, capture_output=True, text=True,
                                timeout=900)
        self.assertEqual(result.returncode, 0, "%s: %s" % (" ".join(args), result.stdout + result.stderr))
        return result

    def publish_release(self):
        """This working tree, released as v<VERSION> in a local repository the launcher fetches from."""
        for name in RELEASE_FILES:
            source, target = ROOT / name, self.release / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, target)
        version = (ROOT / "VERSION").read_text().strip()
        self.run_at(self.release, "git", "init", "-q", "-b", "main")
        self.run_at(self.release, "git", "add", "-A")
        self.run_at(self.release, "git", "commit", "-qm", "release")
        self.run_at(self.release, "git", "tag", "v" + version)

    def make_project(self):
        self.project.mkdir()
        self.run_at(self.project, "git", "init", "-q", "-b", "main")
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        conf = self.project / "backbone/harness.conf"
        conf.write_text(conf.read_text().replace('HARNESS_TEST_CMD=""',
                                                 'HARNESS_TEST_CMD="python3 -m unittest discover -s tests"', 1))
        (self.project / "backbone/specs").mkdir(exist_ok=True)
        (self.project / "backbone/specs/2.1.md").write_text(SPEC)
        tasks = self.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 2.1: Customer search** (spec: backbone/specs/2.1.md)\n")
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "grill-stop",
                    stdin=json.dumps({"agent_type": "griller", "last_assistant_message": GRILL_PASS}))
        tasks.write_text(tasks.read_text().replace("- [ ] **Task 2.1", "- [WIP] **Task 2.1"))
        self.run_at(self.project, "git", "add", "-A")
        self.run_at(self.project, "git", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "chore: start task 2.1")
        for name, text in (("src/__init__.py", ""), ("src/search.py", CODE), ("tests/test_search.py", TESTS)):
            (self.project / name).parent.mkdir(exist_ok=True)
            (self.project / name).write_text(text)   # uncommitted, as the implementer leaves it

    def test_the_plugin_judge_verdict_is_recorded(self):
        step = json.loads(self.run_at(self.project, "python3", "-B", str(LAUNCHER), "next", "2.1", "--json").stdout)
        self.assertEqual(step["step"], "judge", step)

        session = self.run_at(self.project, "claude", "-p", "--plugin-dir", str(self.release),
                              "--permission-mode", "bypassPermissions", PROMPT)

        verdict = self.project / "backbone/.verdicts/2.1.judge.json"
        self.assertTrue(verdict.is_file(), "no judge verdict recorded; the session said:\n" + session.stdout)
        self.assertEqual(json.loads(verdict.read_text())["history"][-1]["test_run"]["exit"], 0)


if __name__ == "__main__":
    unittest.main()
