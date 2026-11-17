"""The contract between the harness and the agent software factory (ADR-008, follow-up 1), from the factory's side:
the commands, flags, JSON fields and event kinds it reads.

Version 1 is pinned here, field by field. Within a version fields are only added, so each answer must hold at least
these fields, and `contract --json` must declare at least them; a field taken out of an answer, or out of the
declaration, fails here. The factory runtime isn't in this repository: these tests run the harness as the factory
would, through its commands, its hooks and its event log.
"""
import json
import os
import shlex
import shutil
import subprocess
import time
import unittest

from factory_fixture import Project, agent_script

# Version 1, as ADR-008 section 2 names it.
NEXT_FIELDS = ("task", "title", "state", "change_class", "step", "role", "progress")
NEXT_STEPS = ("define", "grill", "answer", "approve", "start", "test", "implement", "judge", "diagnose", "fix",
              "review", "finish", "deliver", "delivery-failed", "blocked", "done")
STATE_FIELDS = ("autonomous", "tasks", "halted")
STATE_TASK_FIELDS = ("task", "title", "state", "spec", "change_class", "spec_problems", "grill", "approved", "judge",
                     "escalations")
RECEIPT_FIELDS = ("task", "title", "objective", "base", "changed", "backbone_changed", "requirements", "verified",
                  "not_verified", "decisions", "change_class", "change_class_problem", "risks", "rounds", "judged_at",
                  "sandbox", "approval", "approval_needed", "suggested_labels")
ESCALATION_FIELDS = ("task", "kind", "class", "reason", "needed", "status", "at")
EVENT_FIELDS = ("at", "kind", "v")
EVENT_KINDS = {
    "task-start": ("task",), "task-finish": ("task",), "verdict": ("task", "agent", "verdict"),
    "review": ("task", "lens", "verdict"), "approval": ("task", "rule"),
    "escalation": ("task", "escalation", "failure_class", "reason"), "proposal": ("failure_class",),
    "deliver": ("delivery", "head", "pr", "checks", "findings", "owners"), "run-start": ("tasks",),
    "run-attempt": ("task", "attempt", "exit", "state", "cost_usd"), "run-budget": ("spent", "limit"),
    "run-halt": (), "run-agent-failed": ("task", "error"), "run-end": ("summary",), "tamper": ("files",),
    "block": ("reason",), "gate": ("gate",), "linear-import": ("task", "issue"), "outward": ("action", "via"),
}
FAKE_GH = """#!/bin/sh
case "$*" in
  "issue create"*) echo "https://github.com/o/r/issues/12" ;;
  "pr view"*"--json labels"*) echo '{"labels": []}' ;;
  *) echo "fake gh: no answer for: gh $*" >&2; exit 1 ;;
esac
"""


class FactoryProject(unittest.TestCase):
    """Task 1.1 has no spec yet, 1.2 is escalated, 7.1 is judged on its current code."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project("factory contract ")
        cls.p.add_task("1.1", "Not defined yet")
        cls.p.add_task("1.2", "Needs a decision")
        cls.p.commit("chore: tasks")
        cls.p.harness("escalate", "1.2", "--reason", "needs a product decision", "--kind", "decision",
                      "--needed", "the user picks the wording")
        cls.p.judged_task("7.1")

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()


class Contract(FactoryProject):
    def test_contract_names_the_versions_it_serves(self):
        data = self.p.json("contract", "--json")

        self.assertEqual(data["contract"], 1)
        self.assertIn(1, data["versions"])
        self.assertEqual(self.p.harness("contract").stdout.strip().splitlines()[0],
                         "contract: version 1 (serves 1)")

    def test_contract_declares_every_version_1_field(self):
        commands = self.p.json("contract", "--json")["commands"]
        events = self.p.json("contract", "--json")["events"]

        self.assertLessEqual(set(NEXT_FIELDS), set(commands["next"]["fields"]))
        self.assertLessEqual(set(NEXT_STEPS), set(commands["next"]["steps"]))
        self.assertLessEqual(set(STATE_FIELDS), set(commands["state"]["fields"]))
        self.assertLessEqual(set(STATE_TASK_FIELDS), set(commands["state"]["task_fields"]))
        self.assertLessEqual(set(RECEIPT_FIELDS), set(commands["receipt"]["fields"]))
        self.assertLessEqual(set(ESCALATION_FIELDS), set(commands["escalations"]["entry_fields"]))
        self.assertLessEqual(set(EVENT_FIELDS), set(events["fields"]))
        for kind, fields in EVENT_KINDS.items():
            with self.subTest(kind=kind):
                self.assertLessEqual(set(fields), set(events["kinds"][kind]))

    def test_agents_may_read_the_contract(self):
        self.assertEqual(self.p.bash("python3 scripts/harness/lib/harness.py contract --json", "implementer")
                         .returncode, 0)


class Answers(FactoryProject):
    def test_next_answers_carry_the_declared_fields(self):
        declared = self.p.json("contract", "--json")["commands"]["next"]
        for task, step in (("1.1", "define"), ("1.2", "blocked"), ("7.1", "finish")):
            with self.subTest(task=task):
                answer = self.p.json("next", task, "--json")

                self.assertEqual(answer["step"], step)
                self.assertLessEqual(set(declared["fields"]), set(answer))
                self.assertLessEqual(set(declared["step_fields"].get(step, ())), set(answer))

    def test_a_blocked_task_names_its_escalation(self):
        answer = self.p.json("next", "1.2", "--json")

        self.assertEqual(len(answer["escalations"]), 1)
        self.assertIn("Task 1.2: decision", answer["escalations"][0])

    def test_state_carries_the_declared_fields_for_every_task(self):
        declared = self.p.json("contract", "--json")["commands"]["state"]
        answer = self.p.json("state", "--json")

        self.assertLessEqual(set(declared["fields"]), set(answer))
        self.assertEqual({t["task"] for t in answer["tasks"]} >= {"1.1", "1.2", "7.1"}, True, answer["tasks"])
        for task in answer["tasks"]:
            with self.subTest(task=task["task"]):
                self.assertLessEqual(set(declared["task_fields"]), set(task))

    def test_the_receipt_carries_the_declared_fields(self):
        declared = self.p.json("contract", "--json")["commands"]["receipt"]

        self.assertLessEqual(set(declared["fields"]), set(self.p.json("receipt", "7.1", "--json")))

    def test_escalations_json_lists_the_open_ones_with_kind_class_reason_and_needed(self):
        data = self.p.json("escalations", "--json")
        entry = next(e for e in data["escalations"] if e["task"] == "1.2")

        self.assertLessEqual(set(self.p.json("contract", "--json")["commands"]["escalations"]["entry_fields"]),
                             set(entry))
        self.assertEqual((entry["kind"], entry["class"], entry["reason"], entry["needed"], entry["status"]),
                         ("decision", "missing_context", "needs a product decision", "the user picks the wording",
                          "open"))
        self.assertEqual(data["by_class"]["missing_context"], 1)

    def test_escalations_json_leaves_out_resolved_ones(self):
        p = Project("escalations resolved ")
        try:
            p.add_task("2.1", "Done with")
            p.add_task("2.2", "Still open")
            p.harness("escalate", "2.1", "--reason", "first", "--kind", "decision")
            p.harness("escalate", "2.2", "--reason", "second", "--kind", "runner")
            p.write("backbone/escalations.md", p.read("backbone/escalations.md").replace("- Status: open",
                                                                                          "- Status: resolved", 1))
            data = p.json("escalations", "--json")
        finally:
            p.cleanup()

        self.assertEqual([(e["task"], e["kind"]) for e in data["escalations"]], [("2.2", "runner")])
        self.assertEqual(sum(data["by_class"].values()), 2)


class Events(FactoryProject):
    def test_every_event_carries_the_contract_version(self):
        self.p.bash("git push --force origin main", "implementer")   # a refusal, logged as a block
        events = self.p.events()

        self.assertTrue(events)
        for event in events:
            with self.subTest(kind=event.get("kind")):
                self.assertLessEqual(set(EVENT_FIELDS), set(event))
                self.assertEqual(event["v"], 1)

    def test_events_of_a_declared_kind_carry_its_fields(self):
        self.p.bash("git push --force origin main", "implementer")
        declared = self.p.json("contract", "--json")["events"]["kinds"]
        seen = set()
        for event in self.p.events():
            if event["kind"] in declared:
                seen.add(event["kind"])
                with self.subTest(kind=event["kind"]):
                    self.assertLessEqual(set(declared[event["kind"]]), set(event))

        self.assertLessEqual({"escalation", "verdict", "block"}, seen)


class Outward(unittest.TestCase):
    """An outward write the harness lets through, or makes itself, is an `outward` event."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project("factory outward ")
        cls.p.command("git", "remote", "add", "origin", "git@github.com:o/r.git")
        cls.p.command("git", "checkout", "-q", "-b", "feat/x")
        cls.bin = cls.p.base / "bin"
        cls.bin.mkdir()
        (cls.bin / "gh").write_text(FAKE_GH)
        (cls.bin / "gh").chmod(0o755)
        cls.p.env["PATH"] = str(cls.bin) + os.pathsep + os.environ["PATH"]

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def outward_since(self, count):
        return self.p.events("outward")[count:]

    def call(self, command, agent, failed=False):
        """A Bash call through the hooks: pre-tool-use, then post-tool-use (PostToolUseFailure when failed) if it
        was let through. The pre-tool-use answer."""
        answer = self.p.bash(command, agent)
        if answer.returncode == 0:
            data = {"session_id": "s1", "agent_id": "a1", "agent_type": agent, "tool_name": "Bash",
                    "hook_event_name": "PostToolUseFailure" if failed else "PostToolUse",
                    "tool_input": {"command": command}}
            self.p.hook("post-tool-use", data, check=True)
        return answer

    def test_the_deliverers_push_and_pr_calls_are_outward_events_once_they_ran(self):
        for command, action in (("git push -u origin HEAD", "push"), ("command git push origin feat/x", "push"),
                                ("gh pr create --base main --title t --body b --label risk:low", "pr-create"),
                                ("gh pr edit 7 --add-label risk:low", "pr-edit"),
                                ("gh label create risk:low --color 0E8A16", "label-create")):
            with self.subTest(command=command):
                before = len(self.p.events("outward"))
                allowed = self.p.bash(command, "deliverer")
                after_pre = self.outward_since(before)
                self.call(command, "deliverer")
                found = self.outward_since(before)

                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                self.assertEqual(after_pre, [])
                self.assertEqual([(e["action"], e["via"], e["result"]) for e in found],
                                 [(action, "deliverer", "succeeded")])
                self.assertEqual(found[0]["command"], command.replace("command ", "", 1))

    def test_a_failed_push_is_recorded_as_failed(self):
        before = len(self.p.events("outward"))
        self.call("git push origin feat/x", "implementer", failed=True)

        self.assertEqual([(e["action"], e["result"]) for e in self.outward_since(before)], [("push", "failed")])

    def test_a_push_through_opencode_is_recorded_with_the_status_opencode_gives(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        script = """
const api = process.env.API;
const mod = (await import(process.env.PLUGIN)).default;
const event = { tool: 'bash', input: { command: 'git push origin feat/x' }, sessionID: 's1', agent: 'implementer' };
if (api === 'v1') {
  const hooks = await mod({ directory: process.env.PROJECT });
  await hooks['tool.execute.after']({ tool: 'bash', args: event.input, sessionID: 's1', agent: 'implementer' }, {});
} else {
  let after;
  await mod.setup({ tool: { hook: async (name, callback) => { if (name === 'execute.after') after = callback;
    return { dispose() {} }; } } });
  await after({ ...event, cwd: process.env.PROJECT, status: api });
}
"""
        results = {}
        for api in ("error", "completed", "v1"):
            before = len(self.p.events("outward"))
            env = dict(self.p.env, API=api, PROJECT=str(self.p.path),
                       PLUGIN=str(self.p.path / ".opencode/plugins/harness.js"),
                       HARNESS_OPENCODE_PLUGIN_API="v1" if api == "v1" else "")
            ran = subprocess.run(["node", "--input-type=module", "-e", script], cwd=str(self.p.path), env=env,
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            results[api] = [e["result"] for e in self.outward_since(before)]

        self.assertEqual(results, {"error": ["failed"], "completed": ["succeeded"], "v1": ["unknown"]})

    def test_codex_gives_no_status_so_the_result_is_unknown(self):
        before = len(self.p.events("outward"))
        self.p.harness("hook", "post-tool-use", "--from", "codex", input=json.dumps({
            "session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "git push origin feat/x"}}))

        self.assertEqual([e["result"] for e in self.outward_since(before)], ["unknown"])

    def test_github_api_writes_are_outward_events(self):
        for command in ("gh api repos/o/r/pulls -X POST -f title=t -f head=feat/x -f base=main",
                        "gh api --method PATCH repos/o/r/pulls/7 -f title=t",
                        "gh api repos/o/r/issues/7/labels -f 'labels[]=risk:low'"):
            with self.subTest(command=command):
                before = len(self.p.events("outward"))
                self.call(command, "implementer")

                self.assertEqual([e["action"] for e in self.outward_since(before)], ["api-write"])
        before = len(self.p.events("outward"))
        self.call("gh api repos/o/r/pulls/7", "implementer")
        self.assertEqual(self.outward_since(before), [])

    def test_a_refused_call_is_no_outward_event(self):
        before = len(self.p.events("outward"))
        answer = self.call("gh pr merge 7", "deliverer")

        self.assertEqual(answer.returncode, 2)
        self.assertEqual(self.outward_since(before), [])

    def test_reads_are_no_outward_events(self):
        before = len(self.p.events("outward"))
        for command in ("git status --porcelain", "gh pr checks 7", "git fetch origin"):
            self.assertEqual(self.call(command, "deliverer").returncode, 0, command)

        self.assertEqual(self.outward_since(before), [])

    def test_a_push_from_another_role_is_an_outward_event_too(self):
        before = len(self.p.events("outward"))
        self.call("git push origin feat/x", "implementer")

        self.assertEqual([(e["action"], e["via"]) for e in self.outward_since(before)], [("push", "implementer")])

    def test_the_escalation_issue_the_harness_opens_is_an_outward_event(self):
        self.p.add_task("5.1", "Escalated to GitHub")
        before = len(self.p.events("outward"))
        self.p.harness("escalate", "5.1", "--reason", "needs a decision", env={"HARNESS_ESCALATE_GH": "on"})
        found = self.outward_since(before)

        self.assertEqual([(e["action"], e["via"], e["task"], e["url"]) for e in found],
                         [("issue-create", "harness", "5.1", "https://github.com/o/r/issues/12")])


# The commands only the user, CI, the factory or an Orca precheck runs, with the arguments they need.
USER_ONLY = ("run --only 1.1", "linear import DIS-1 --task 9.1", "linear receipt 7.1", "intake request.json",
             "delivery-record 7.1 report.json", "snapshot", "orca --pr", "orca-nightly", "ci-judge --range a..b",
             "ci-protect", "pin 0.31.0", "sandbox-approve")
# Every way an agent could start the engine with one of them: {c} is the command.
SPELLINGS = (
    "python3 scripts/harness/lib/harness.py {c}",
    "python3 -B -I scripts/harness/lib/harness.py {c}",
    "python3 -u -X dev scripts/harness/lib/harness.py {c}",
    "python3.12 scripts/harness/lib/harness.py {c}",
    "./scripts/harness/lib/harness.py {c}",
    "env python3 scripts/harness/lib/harness.py {c}",
    "timeout 60 python3 scripts/harness/lib/harness.py {c}",
    "python3 /opt/engines/0.30.0/plugin/launcher.py {c}",
    "python3 -m runpy scripts/harness/lib/harness.py {c}",
    "cd scripts/harness/lib && python3 -m harness {c}",
    "PYTHONPATH=scripts/harness/lib python3 -m harness {c}",
    "python3 scripts/harness/lib/harness.p? {c}",
    "H=scripts/harness/lib/harness.py; python3 $H {c}",
    "h() {{ python3 scripts/harness/lib/harness.py \"$@\"; }}; h {c}",
    "sh -c 'python3 -B scripts/harness/lib/harness.py {c}'",
    "eval \"python3 scripts/harness/lib/harness.py {c}\"",
    "echo {c} | xargs python3 scripts/harness/lib/harness.py",
    "printf '%s\\n' scripts/harness/lib/harness.py | xargs -I{{}} python3 {{}} {c}",
    "find scripts -name harness.py -exec python3 {{}} {c} \\;",
    "find scripts/harness/lib -name 'h*.py' -exec python3 {{}} {c} \\;",
    "cd scripts/harness/lib && python3 - {c} < harness.py",
    "cd scripts/harness/lib && python3 - {c} <harness.py",
    "cat scripts/harness/lib/harness.py | python3 - {c}",
    "python3 /dev/stdin {c} < scripts/harness/lib/harness.py",
    "cd scripts/harness/lib && < harness.py python3 - {c}",
    "cat scripts/harness/lib/harness.py | cat | python3 - {c}",
    "cd scripts/harness/lib && python3 - {c} < h*.py",
    "echo 'scripts/harness/lib/harness.py {c}' | xargs python3",
    "echo scripts/harness/lib/harness.py | xargs -I@ sh -c 'python3 @ {c}'",
    "find scripts -name harness.py -exec {{}} {c} \\;",
    "echo 'python3 scripts/harness/lib/harness.py {c}' | sh",
    "echo 'python3 scripts/harness/lib/harness.py {c}' | bash -s",
    "env -S 'python3 scripts/harness/lib/harness.py {c}'",
    "git -c alias.x='!python3 scripts/harness/lib/harness.py {c}' x",
    "awk 'BEGIN{{system(\"python3 scripts/harness/lib/harness.py {c}\")}}'",
    "python3 <(cat scripts/harness/lib/harness.py) {c}",
)
# Running the engine through code the hooks don't read, or from a copy, whatever the command.
CODE_AND_COPIES = (
    "python3 -c \"import runpy; runpy.run_path('scripts/harness/lib/harness.py', run_name='__main__')\" intake r.json",
    "python3 - <<'EOF'\nimport sys, runpy\nsys.argv = ['h', 'intake', 'r.json']\n"
    "runpy.run_path('scripts/harness/lib/harness.py', run_name='__main__')\nEOF",
    "python3 -c 'import sys; sys.path.insert(0, \"scripts/harness/lib\"); import harness'",
    "cp scripts/harness/lib/harness.py /tmp/h.py",
    "cat scripts/harness/lib/harness.py > h.py",
    "git show HEAD:scripts/harness/lib/harness.py > /tmp/h.py",
    "ln -s $PWD/scripts/harness/lib/harness.py tool.py",
    "alias h='python3 scripts/harness/lib/harness.py'",
    "python3 -c \"exec(open('scripts/harness/lib/harness.py').read())\"",
)
# A program read from stdin (a pipe, a redirect, input to xargs or find -exec) is code the hooks can't read; a literal
# heredoc or here-string they can.
STDIN_PROGRAMS = ("echo 'print(1)' | python3", "echo 'print(1)' | python3 -", "python3 < tool.py", "node < tool.js",
                  "python3 - <<< \"$(cat tool.py)\"", "find tests -name 'test_*.py' -exec python3 {} \\;",
                  "ls *.sh | xargs -n1 bash", "git ls-files | xargs sh -c 'echo $0'", "timeout 9 python3 - < tool.py",
                  "echo ls | sh", "bash -s < cmds.txt", "awk '{system($0)}' cmds.txt", "git config alias.x '!ls'",
                  "git -c core.sshCommand=x fetch origin", "python3 <(cat tool.py)", "source <(cat tool.sh)",
                  "env -S 'python3 - < tool.py'")
LITERAL_PROGRAMS = ("python3 - <<'EOF'\nprint(1)\nEOF", "python3 - <<< 'print(1)'", "python3 tools/x.py < input.txt",
                    "cat data.csv | python3 tools/x.py", "python3 --version", "node --version",
                    "git ls-files '*.py' | xargs python3 -m pyflakes", "bash <<'EOF'\necho hi\nEOF",
                    "awk '{print $1}' data.txt", "git -c user.name=x log -1", "git config user.name x",
                    "python3 -c \"print(open('scripts/harness/lib/harness.py').read()[:10])\"")
ALLOWED = ("python3 scripts/harness/lib/harness.py next 1.1 --json", "python3 -B scripts/harness/lib/harness.py contract",
           "python3 scripts/harness/lib/harness.py escalate 1.1 --reason x",
           "python3 scripts/harness/lib/harness.py delivery-plan 7.1 --json",
           "python3 scripts/harness/lib/harness.py linear import DIS-1 --task 9.1 --dry-run",
           "python3 scripts/harness/lib/harness.py orca --pr --dry-run",
           "grep -n 'def intake' scripts/harness/lib/harness.py", "git diff -- scripts/harness/lib/harness.py",
           "python3 scripts/harness/lib/harness.py next 1.1 --json > /tmp/next.json",
           "python3 scripts/harness/lib/harness.py state --json 2>/dev/null | head -5",
           "find tests -name '*.py' -exec grep -l intake {} \\;", "git ls-files '*.py' | xargs python3 -m pyflakes",
           "python3 - <<'EOF'\nprint(1)\nEOF",
           "npm run build", "make run", "docker run --rm alpine true")


class UserOnlyCommands(unittest.TestCase):
    """The user-only commands are refused to agents however the engine is started."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project("factory user-only ")

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def test_every_spelling_of_a_user_only_command_is_refused(self):
        for spelling in SPELLINGS:
            for command in USER_ONLY:
                with self.subTest(command=spelling.format(c=command)):
                    self.assertEqual(self.p.bash(spelling.format(c=command), "implementer").returncode, 2)

    def test_the_engine_run_through_code_or_from_a_copy_is_refused(self):
        for command in CODE_AND_COPIES:
            with self.subTest(command=command):
                self.assertEqual(self.p.bash(command, "implementer").returncode, 2)

    def test_a_program_from_stdin_is_refused_and_a_literal_one_allowed(self):
        for command in STDIN_PROGRAMS:
            with self.subTest(command=command):
                self.assertEqual(self.p.bash(command, "implementer").returncode, 2)
        for command in LITERAL_PROGRAMS:
            with self.subTest(command=command):
                answer = self.p.bash(command, "implementer")

                self.assertEqual(answer.returncode, 0, answer.stderr)

    def test_the_agents_own_commands_and_reads_of_the_engine_are_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                answer = self.p.bash(command, "implementer")

                self.assertEqual(answer.returncode, 0, answer.stderr)


class GitDirectory(unittest.TestCase):
    """The harness keeps its records (events, cost ledgers, run locks) in the shared git directory: agents write
    nothing there, from the checkout or from a linked worktree, with the file tools or the shell."""

    @classmethod
    def setUpClass(cls):
        # The skill gate would ask for code-quality before the control write to src/; these tests are about .git.
        cls.p = Project("factory git directory ", HARNESS_SKILL_GATE="off")
        cls.p.harness("contract")   # an event, so .git/harness exists
        cls.common = cls.p.path / ".git"
        lane = cls.p.base / "lane"
        cls.p.command("git", "worktree", "add", "-q", "-b", "lane", str(lane))
        cls.lane = Project.__new__(Project)
        cls.lane.__dict__.update(cls.p.__dict__, path=lane, env=dict(cls.p.env, CLAUDE_PROJECT_DIR=str(lane)))

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def write(self, project, path, agent="implementer"):
        return project.file_tool("Write", path, agent=agent, content="{}\n")

    def test_the_file_tools_write_nothing_under_the_git_directory(self):
        cases = {
            "the event log": (self.p, ".git/harness/events.jsonl"),
            "a cost ledger": (self.p, ".git/harness/costs/task-1.1.jsonl"),
            "git's config": (self.p, ".git/config"),
            "the shared git directory, by its absolute path": (self.lane, str(self.common / "harness/events.jsonl")),
            "a ledger in it": (self.lane, str(self.common / "harness/costs/task-1.1.jsonl")),
            "the worktree's .git file": (self.lane, ".git"),
        }
        for case, (project, path) in cases.items():
            for agent in ("implementer", "tester", None):
                with self.subTest(case=case, agent=agent):
                    answer = self.write(project, path, agent)

                    self.assertEqual(answer.returncode, 2, answer.stderr)
                    self.assertIn("git directory", answer.stderr)

    def test_the_shell_writes_nothing_under_the_git_directory(self):
        for project, command in (
                (self.p, "echo '{}' >> .git/harness/events.jsonl"),
                (self.p, "rm -f .git/harness/costs/task-1.1.jsonl"),
                (self.p, "cp /dev/null .git/index"),
                (self.lane, "rm -f %s" % shlex.quote(str(self.common / "harness/costs/task-1.1.jsonl"))),
                (self.lane, "echo '{}' > %s" % shlex.quote(str(self.common / "harness/events.jsonl"))),
                (self.lane, "truncate -s 0 %s" % shlex.quote(str(self.common / "harness/locks/task-1.1.lock"))),
                (self.p, "find .git/harness -name '*.jsonl' -delete"),
                (self.p, "find .git -name '*.lock' -exec rm {} \\;"),
                (self.lane, "find %s -type f -delete" % shlex.quote(str(self.common / "harness"))),
                (self.lane, 'rm "$(git rev-parse --git-common-dir)/harness/costs/task-1.1.jsonl"'),
                (self.lane, "rm -f `git rev-parse --git-dir`/../../harness/events.jsonl"),
                (self.lane, "D=$(git rev-parse --git-common-dir); rm -f $D/harness/costs/task-1.1.jsonl"),
                (self.lane, 'echo "{}" > "$GIT_DIR/harness/events.jsonl"'),
                (self.p, "find . -name '*.jsonl' -delete"), (self.lane, "find . -name .git -delete"),
                (self.p, "rm -rf .gi?/harness"), (self.p, "truncate -s0 .gi*/harness/events.jsonl"),
                (self.p, 'rm -f "$PWD/.git/harness/events.jsonl"'),
                (self.lane, 'cd "$(git rev-parse --git-common-dir)" && rm -f harness/costs/task-1.1.jsonl'),
                (self.p, "find .git/harness -type f | xargs rm"), (self.p, "ln -sf /dev/null .git/harness/events.jsonl"),
                (self.p, 'D=.git; rm -rf "$D/harness"'), (self.p, 'export D=.git && rm -rf "$D/harness/costs"'),
                (self.p, "pushd .git && rm -rf harness"),
                (self.p, "find .git/harness -name '*.jsonl' -exec sed -i '' 's/1/0/' {} +"),
                (self.p, 'for f in .git/harness/costs/*; do echo "{}" > "$f"; done'),
                (self.p, "ls .git/harness/costs/* | xargs cp /dev/null"),
                (self.p, 'find .git/harness -type f | while read f; do : > "$f"; done'),
                (self.p, 'D=$(git rev-parse --git-common-dir); rm -rf "$D/harness"'),
                (self.p, 'rm -rf "$UNSET_HARNESS_TEST_VARIABLE/harness"')):
            with self.subTest(command=command):
                self.assertEqual(project.bash(command, "implementer").returncode, 2)

    def test_reads_and_other_writes_are_allowed(self):
        for project, command in ((self.p, "cat .git/harness/events.jsonl"), (self.lane, "git status --short"),
                                 (self.p, "find src -name '*.pyc' -delete"), (self.p, 'rm -f "$TMPDIR/x.txt"'),
                                 (self.p, "rm -f build/*.o"), (self.p, 'rm -f "$PWD/build/x.o"'),
                                 (self.p, "cd src && rm -f x.pyc"), (self.p, "find . -name '*.pyc' -delete"),
                                 (self.p, "find . -name __pycache__ -exec rm -rf {} +"),
                                 (self.p, "find . -path ./.git -prune -o -name '*.log' -exec rm -f {} +"),
                                 (self.p, "find . -not -path './.git/*' -name '*.tmp' -delete"),
                                 (self.p, "find . -name '*.o' -print0 | xargs -0 rm -f"),
                                 (self.p, "git ls-files -z '*.pyc' | xargs -0 rm -f"),
                                 (self.p, 'cd "$(mktemp -d)" && touch x'), (self.p, 'T=$(mktemp); echo x > "$T"'),
                                 (self.p, 'for f in src/*.tmp; do rm -f "$f"; done'),
                                 (self.p, 'OUT=build/out.txt; echo x > "$OUT"'),
                                 (self.p, "find .git -name '*.lock' -print"),
                                 (self.lane, "tail -3 %s" % shlex.quote(str(self.common / "harness/events.jsonl")))):
            with self.subTest(command=command):
                self.assertEqual(project.bash(command, "implementer").returncode, 0)
        self.assertEqual(self.write(self.lane, "src/tool.py").returncode, 0)


class TaskLock(unittest.TestCase):
    """Two lanes on one task: `run --only` holds a lock in the shared git directory while it drives the task."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project("factory task lock ")
        for task in ("3.1", "3.2", "3.3"):
            cls.p.add_task(task, "Locked task %s" % task)
        cls.p.commit("chore: tasks")
        cls.env = dict(HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block", HARNESS_RUN_ATTEMPTS="1",
                       HARNESS_AGENT_CMD=agent_script(cls.p.base / "agent.sh", (
                           'touch "$LOCK_STARTED"\ni=0\n'
                           'while [ ! -f "$LOCK_RELEASE" ] && [ $i -lt 600 ]; do sleep 0.1; i=$((i+1)); done\n'
                           'echo \'{"type":"result","total_cost_usd":0.1,"num_turns":1,"result":"ok"}\'\n')))

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def files(self, task):
        """The agent's signal that its session started, and the file that lets it end, for task's runs."""
        started, release = self.p.base / ("started-" + task), self.p.base / ("release-" + task)
        return started, release, dict(self.env, LOCK_STARTED=str(started), LOCK_RELEASE=str(release))

    def run_in_background(self, task, env):
        command = ["python3", "-B", str(self.p.path / "scripts/harness/lib/harness.py"), "run", "--only", task]
        return subprocess.Popen(command, cwd=str(self.p.path), env=dict(self.p.env, **env),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def wait_for(self, path, process):
        deadline = time.time() + 60
        while not path.exists() and process.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(path.exists(), "the first run's agent session never started")

    def test_a_second_run_of_the_same_task_is_refused_while_the_first_holds_it(self):
        started, release, env = self.files("3.1")
        first = self.run_in_background("3.1", env)
        try:
            self.wait_for(started, first)
            second = self.p.harness("run", "--only", "3.1", check=False, env=env)
        finally:
            release.touch()
            output = first.communicate(timeout=120)[0]

        self.assertEqual(second.returncode, 1, second.stdout)
        self.assertIn("run: task 3.1 is being run already (pid %d)" % first.pid, second.stdout)
        self.assertIn("run: locked       task 3.1", second.stdout)
        self.assertIn("task 3.1 attempt 1", output)
        self.assertNotIn("task 3.1 attempt 1", second.stdout)

    def test_a_lock_left_by_a_run_that_ended_holds_nothing(self):
        locks = self.p.path / ".git/harness/locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "task-3.2.lock").write_text(json.dumps({"pid": 1, "started": "2026-11-11T00:00:00+0000"}))
        _, release, env = self.files("3.2")
        release.touch()
        result = self.p.harness("run", "--only", "3.2", check=False, env=env)

        self.assertIn("task 3.2 attempt 1", result.stdout)
        self.assertNotIn("being run already", result.stdout)

    def test_every_runner_path_takes_the_lock(self):
        self.p.add_task("3.4", "Locked by another lane")
        started, release, env = self.files("3.4")
        first = self.run_in_background("3.4", env)
        try:
            self.wait_for(started, first)
            _, done, other = self.files("other")
            done.touch()
            plain = self.p.harness("run", check=False, env=other)
            orca = self.p.harness("orca", "--tasks", "3.4", check=False, env=other)
        finally:
            release.touch()
            first.communicate(timeout=120)

        self.assertIn("run: task 3.4 is being run already (pid %d)" % first.pid, plain.stdout)
        self.assertNotIn("task 3.4 attempt", plain.stdout)
        self.assertIn("orca: task(s) 3.4 are being run already; left out", orca.stdout)
        self.assertIn("orca: no ready task", orca.stdout)

    def test_agents_may_not_write_the_lock(self):
        self.assertEqual(self.p.bash("echo '{}' > .git/harness/locks/task-3.3.lock", "implementer").returncode, 2)


if __name__ == "__main__":
    unittest.main()
