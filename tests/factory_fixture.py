"""A throwaway project with the harness installed, for the tests of the factory contract (ADR-008). Tests drive it
only through what the factory and the agents use: harness.py's commands, its hooks (JSON on stdin) and git.

Not a test file itself: tests/test-*.py import it, as they import hypothesis_profiles.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# Settings a developer's shell may hold that would change what the harness decides in the throwaway project.
CLEARED = ("HARNESS_ROOT", "HARNESS_AUTONOMY", "HARNESS_PROFILE", "HARNESS_ROLE", "TRIPLE_MODE", "HARNESS_ORCA_RUN",
           "HARNESS_TASK_BUDGET_USD", "HARNESS_RUN_MAX_COST", "HARNESS_AGENT_CMD", "HARNESS_RUN_ATTEMPTS",
           "LINEAR_API_KEY", "HARNESS_LINEAR_URL", "HARNESS_ESCALATE_GH", "CLAUDE_CONFIG_DIR", "CODEX_HOME")

SPEC = """# Spec {task}: {title}

Task: {task}
PRD: none
{change_class}
{source}## Context
Support needs to find customers by name.{context}

## Requirements
- REQ-{task}-1: The system shall return customers whose name contains the query, ignoring case.

## Acceptance criteria
- AC-{task}-1 (REQ-{task}-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.

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


def agent_script(path, body):
    """An executable stand-in for the agent CLI the runner starts (HARNESS_AGENT_CMD): body is shell."""
    path.write_text("#!/bin/sh\ncat >/dev/null\n" + body)
    path.chmod(0o755)
    return shlex.quote(str(path))


class Project(object):
    """An installed project in its own temporary folder, on branch main, with the harness committed."""

    def __init__(self, prefix, **env):
        self.temp = tempfile.TemporaryDirectory(prefix=prefix)
        self.base = Path(self.temp.name).resolve()
        self.path = self.base / "project"
        self.path.mkdir()
        (self.base / "home").mkdir()
        self.env = dict(os.environ, HOME=str(self.base / "home"), GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                        GIT_COMMITTER_EMAIL="test@example.com", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true",
                        HARNESS_REVIEW="off", HARNESS_DELIVER="off", PYTHONDONTWRITEBYTECODE="1",
                        CLAUDE_PROJECT_DIR=str(self.path))
        for key in CLEARED:
            self.env.pop(key, None)
        self.env.update(env)
        self.command("git", "init", "-q", "-b", "main")
        self.command(str(ROOT / "bootstrap.sh"), str(self.path), "--name", "factory")
        self.commit("chore: adopt agentic harness")

    def cleanup(self):
        self.temp.cleanup()

    def command(self, *args, input=None, check=True, env=None, cwd=None):
        result = subprocess.run(args, cwd=str(cwd or self.path), env=dict(self.env, **(env or {})), input=input,
                                capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                 result.stderr))
        return result

    def harness(self, *args, input=None, check=True, env=None):
        return self.command("python3", "-B", str(self.path / "scripts/harness/lib/harness.py"), *args, input=input,
                            check=check, env=env)

    def json(self, *args, env=None):
        return json.loads(self.harness(*args, env=env).stdout)

    def hook(self, event, data, check=False, env=None):
        return self.harness("hook", event, input=json.dumps(data), check=check, env=env)

    def bash(self, command, agent=None, env=None):
        """The pre-tool-use hook's answer to a Bash call (from agent's subagent, or the main session)."""
        data = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command}}
        if agent:
            data.update(agent_id="a1", agent_type=agent)
        return self.hook("pre-tool-use", data, env=env)

    def file_tool(self, tool, path, agent="analyst", **tool_input):
        """The pre-tool-use hook's answer to a file tool call from agent's subagent (None: the main session)."""
        data = {"session_id": "s1", "tool_name": tool, "tool_input": dict(tool_input, file_path=str(self.path / path))}
        if agent:
            data.update(agent_id="a1", agent_type=agent)
        return self.hook("pre-tool-use", data)

    def commit(self, message):
        self.command("git", "add", "-A")
        self.command("git", "commit", "-qm", message, "--allow-empty")

    def read(self, rel):
        return (self.path / rel).read_text(encoding="utf-8")

    def write(self, rel, text):
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def add_task(self, task, title, marker=" "):
        tasks = self.path / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [%s] **Task %s: %s** (spec: backbone/specs/%s.md)\n"
                         % (marker, task, title, task))

    def set_marker(self, task, marker):
        tasks = self.path / "backbone/3-TASKS.md"
        text = tasks.read_text()
        lines = [line if "**Task %s:" % task not in line else
                 line[:line.index("[")] + "[%s]" % marker + line[line.index("]") + 1:] for line in text.splitlines()]
        tasks.write_text("\n".join(lines) + "\n")

    def spec_text(self, task, title="Customer search", change_class="Change-Class: docs", source="", context=""):
        return SPEC.format(task=task, title=title, change_class=change_class, source=source, context=context)

    def grill_pass(self, task):
        self.hook("grill-stop", {"hook_event_name": "SubagentStop", "agent_type": "griller", "stop_hook_active": False,
                                 "last_assistant_message": final_message(
                                     {"verdict": "pass", "task": task, "questions": [], "summary": "s"})}, check=True)

    def judge_pass(self, task):
        self.hook("judge-stop", {"hook_event_name": "SubagentStop", "agent_type": "judge", "stop_hook_active": False,
                                 "last_assistant_message": final_message({
                                     "verdict": "pass", "task": task, "summary": "s", "findings": [],
                                     "criteria": [{"id": "AC-%s-1" % task, "met": True, "evidence": "src/search.py:2",
                                                   "tests": ["test_contains"]}],
                                     "tests": {"command": "true", "result": "passed"}})}, check=True)

    def judged_task(self, task, title="Customer search", source=""):
        """task with a user-approved spec, [WIP], its code written and a judge pass on it (not committed)."""
        self.write("backbone/specs/%s.md" % task, self.spec_text(task, title, source=source))
        if "**Task %s:" % task not in self.read("backbone/3-TASKS.md"):
            self.add_task(task, title)
        self.grill_pass(task)
        self.write("backbone/specs/%s.md" % task, self.read("backbone/specs/%s.md" % task)
                   + "Approved-by: Ana (2026-11-01)\n")
        self.set_marker(task, "WIP")
        self.write("src/search.py", "def search(names, q):  # AC-%s-1\n    return [n for n in names if q.lower() in "
                                    "n.lower()]\n" % task)
        self.write("tests/test_search.py", "def test_contains():  # AC-%s-1\n    assert True\n" % task)
        self.judge_pass(task)

    def events(self, kind=None):
        path = self.path / ".git/harness/events.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        found = [json.loads(line) for line in lines if line.strip()]
        return [e for e in found if kind is None or e.get("kind") == kind]

    def trust_agent(self, script_name, body, **env):
        """Set the runner's agent to a shell stand-in; returns the env for harness.py run."""
        command = agent_script(self.base / script_name, body)
        return dict(dict(HARNESS_AGENT_CMD=command, HARNESS_AUTONOMY="autonomous", HARNESS_RUN_ATTEMPTS="1"), **env)
