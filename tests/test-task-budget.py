"""The per-task spend cap (ADR-008, follow-up 3), from the runner's side.

HARNESS_TASK_BUDGET_USD, set by the factory for the `run` process, is what one task may spend across every session
and every resume. Each session's cost goes to the task's ledger in the shared git directory, which survives resumes;
`run` starts no session once the ledger reaches the budget, and treats a key proxy's refusal (an agent error naming
HTTP 402 or a budget) as a cap hit: it escalates with kind `budget` and stops. The receipt shows the task's cost. The
per-day cap and booking before each call are the factory's key proxy's, not tested here.

The rule "a session starts only while the ledger is under the budget" is checked as a property over sequences of
session costs (needs hypothesis).
"""
import shlex
import unittest

from factory_fixture import Project, agent_script
from hypothesis_profiles import examples

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None

# Each session appends a line to sessions-<task> and makes progress (so a retry isn't an idle repeat), then reports
# the cost in costs-<task>, line by line, or AGENT_COST.
AGENT = """prompt=$(cat)
task=$(printf '%s\\n' "$prompt" | sed -n 's/^Drive Task \\([^ ]*\\) .*/\\1/p')
echo session >> "$AGENT_DIR/sessions-$task"
date +%s%N >> "progress-$task.txt"
n=$(wc -l < "$AGENT_DIR/sessions-$task" | tr -d ' ')
cost=$(sed -n "${n}p" "$AGENT_DIR/costs-$task" 2>/dev/null)
echo "{\\"type\\":\\"result\\",\\"total_cost_usd\\":${cost:-${AGENT_COST:-0.6}},\\"num_turns\\":1,\\"result\\":\\"ok\\"}"
"""
REFUSED_AGENT = """echo '{"type":"result","subtype":"success","is_error":true,"total_cost_usd":0.2,"num_turns":1,"result":"API Error: 402 {\\"error\\":{\\"message\\":\\"task budget exhausted\\"}}"}'
exit 1
"""
FINISHING_AGENT = """task=$(printf '%s\\n' "$prompt" | sed -n 's/^Drive Task \\([^ ]*\\) .*/\\1/p')
sed -i.bak "s/^- \\[WIP\\] \\*\\*Task $task/- [x] **Task $task/" backbone/3-TASKS.md && rm -f backbone/3-TASKS.md.bak
git add -A && HARNESS_VERIFY=off git commit -qm "feat: task $task"
echo '{"type":"result","total_cost_usd":0.45,"num_turns":2,"result":"ok"}'
"""


class Runner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project("task budget ")
        cls.p.command("git", "commit", "-qm", "chore: start", "--allow-empty")
        cls.agent = cls.p.base / "agent.sh"
        cls.agent.write_text("#!/bin/sh\n" + AGENT)
        cls.agent.chmod(0o755)
        cls.env = dict(HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block",
                       HARNESS_AGENT_CMD=shlex.quote(str(cls.agent)),
                       AGENT_DIR=str(cls.p.base))
        cls.tasks = 0

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def new_task(self, costs=None):
        type(self).tasks += 1
        task = "1.%d" % self.tasks
        self.p.add_task(task, "Budgeted task %s" % task)
        if costs is not None:
            (self.p.base / ("costs-" + task)).write_text("".join("%s\n" % c for c in costs))
        return task

    def run_task(self, task, **env):
        return self.p.harness("run", "--only", task, check=False, env=dict(self.env, **env))

    def sessions(self, task):
        path = self.p.base / ("sessions-" + task)
        return len(path.read_text().splitlines()) if path.exists() else 0

    def escalations(self, task, kind):
        return [e for e in self.p.json("escalations", "--json")["escalations"] if e["task"] == task and
                e["kind"] == kind]

    def unblock(self, task):
        """What the user does to resume an escalated task: resolve the entry and remove the BLOCKED note."""
        self.p.write("backbone/escalations.md", self.p.read("backbone/escalations.md").replace(
            "- Status: open", "- Status: resolved"))
        self.p.write("backbone/3-TASKS.md", "\n".join(
            line.split(" — BLOCKED:")[0] if "**Task %s:" % task in line else line
            for line in self.p.read("backbone/3-TASKS.md").splitlines()) + "\n")

    def test_no_session_starts_once_the_task_has_spent_its_budget(self):
        task = self.new_task()
        result = self.run_task(task, HARNESS_TASK_BUDGET_USD="1", HARNESS_RUN_ATTEMPTS="5")

        self.assertEqual(self.sessions(task), 2, result.stdout)
        self.assertIn("run: task %s has spent $1.20 of its $1.00 budget (HARNESS_TASK_BUDGET_USD); not starting "
                      "another session" % task, result.stdout)
        [entry] = self.escalations(task, "budget")
        self.assertEqual(entry["class"], "permission_denied")
        self.assertIn("$1.20 of its $1.00 budget", entry["reason"])
        self.assertEqual(self.p.json("next", task, "--json")["step"], "blocked")
        budget = [e for e in self.p.events("run-budget") if e.get("task") == task]
        self.assertEqual([(e["scope"], e["spent"], e["limit"]) for e in budget], [("task", 1.2, 1.0)])

    def test_the_ledger_survives_a_resume(self):
        task = self.new_task()
        self.run_task(task, HARNESS_TASK_BUDGET_USD="1", HARNESS_RUN_ATTEMPTS="5")
        self.unblock(task)
        again = self.run_task(task, HARNESS_TASK_BUDGET_USD="1", HARNESS_RUN_ATTEMPTS="5")
        self.assertEqual(self.sessions(task), 2, again.stdout)
        self.unblock(task)
        raised = self.run_task(task, HARNESS_TASK_BUDGET_USD="2", HARNESS_RUN_ATTEMPTS="5")

        self.assertEqual(self.sessions(task), 4, raised.stdout)
        self.assertIn("has spent $2.40 of its $2.00 budget", raised.stdout)
        self.assertEqual(len(self.escalations(task, "budget")), 1)

    def test_a_key_proxys_refusal_is_a_cap_hit_that_stops_the_run(self):
        p = Project("task budget proxy ")
        try:
            p.add_task("2.1", "Refused")
            p.add_task("2.2", "Never started")
            refused = agent_script(p.base / "refused.sh", REFUSED_AGENT)
            result = p.harness("run", check=False, env=dict(self.env, HARNESS_AGENT_CMD=refused,
                                                            HARNESS_TASK_BUDGET_USD="25", HARNESS_RUN_ATTEMPTS="3"))
            attempts = [(e["task"], e["attempt"]) for e in p.events("run-attempt")]
            escalated = [(e["task"], e["kind"]) for e in p.json("escalations", "--json")["escalations"]]
            budget = [(e["task"], e["scope"], e["spent"], e["limit"]) for e in p.events("run-budget")]
        finally:
            p.cleanup()

        self.assertEqual(attempts, [("2.1", 1)], result.stdout)
        self.assertIn("run: the agent's model calls were refused for a spending cap", result.stdout)
        self.assertEqual(escalated, [("2.1", "budget")])
        self.assertEqual(budget, [("2.1", "proxy", 0.2, 25.0)])

    def test_without_a_task_budget_a_budget_error_is_an_ordinary_failed_session(self):
        task = self.new_task()
        refused = agent_script(self.p.base / "refused-unbudgeted.sh", REFUSED_AGENT)
        result = self.p.harness("run", "--only", task, check=False,
                                env=dict(self.env, HARNESS_AGENT_CMD=refused, HARNESS_RUN_ATTEMPTS="2"))

        self.assertIn("task %s attempt 2" % task, result.stdout)
        self.assertEqual(self.escalations(task, "budget"), [])

    def test_an_invalid_budget_stops_the_run_before_any_session(self):
        task = self.new_task()
        result = self.run_task(task, HARNESS_TASK_BUDGET_USD="25 dollars")

        self.assertEqual(result.returncode, 1)
        self.assertIn("HARNESS_TASK_BUDGET_USD must be empty or a number of dollars", result.stdout)
        self.assertEqual(self.sessions(task), 0)

    def test_agents_may_change_neither_the_budget_nor_the_ledger(self):
        conf = self.p.file_tool("Edit", "backbone/harness.conf", agent=None, old_string='HARNESS_AUTONOMY=',
                                new_string='HARNESS_TASK_BUDGET_USD="1000"\nHARNESS_AUTONOMY=')
        ledger = self.p.bash("echo '{}' > .git/harness/costs/task-1.1.jsonl", "implementer")

        self.assertEqual(conf.returncode, 2, conf.stderr)
        self.assertIn("HARNESS_TASK_BUDGET_USD may only be changed by the user", conf.stderr)
        self.assertEqual(ledger.returncode, 2, ledger.stderr)

    if given is not None:
        @settings(max_examples=examples(12))
        @given(costs=st.lists(st.integers(min_value=0, max_value=8), min_size=1, max_size=4),
               budget=st.integers(min_value=0, max_value=12))
        def test_a_session_starts_only_while_the_ledger_is_under_the_budget(self, costs, budget):
            costs = [c * 0.25 for c in costs]
            limit = budget * 0.25
            attempts = len(costs)
            task = self.new_task(costs)
            self.run_task(task, HARNESS_TASK_BUDGET_USD="%.2f" % limit, HARNESS_RUN_ATTEMPTS=str(attempts))
            started = next((k for k in range(attempts + 1) if sum(costs[:k]) >= limit), attempts)

            self.assertEqual(self.sessions(task), min(started, attempts))
            self.assertEqual(len(self.escalations(task, "budget")), 1 if started < attempts else 0)


class Receipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project("task budget receipt ")
        cls.p.judged_task("7.1", "7.2")
        cls.p.set_marker("7.2", "x")
        cls.p.commit("feat: judged tasks")
        cls.finished = cls.p.harness("run", "--only", "7.1", check=False, env=dict(
            HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block", HARNESS_TASK_BUDGET_USD="25",
            HARNESS_AGENT_CMD=agent_script(cls.p.base / "finish.sh", FINISHING_AGENT)))

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def test_the_receipt_shows_what_the_tasks_sessions_cost(self):
        data = self.p.json("receipt", "7.1", "--json")
        text = self.p.harness("receipt", "7.1").stdout

        self.assertIn("done         task 7.1", self.finished.stdout)
        self.assertEqual(data["cost"], {"total_usd": 0.45, "sessions": 1, "sessions_without_cost": 0})
        self.assertIn("COST (the runner's agent sessions for this task)\n  - $0.45 over 1 session(s)", text)

    def test_a_task_no_runner_session_worked_on_has_no_recorded_cost(self):
        data = self.p.json("receipt", "7.2", "--json")

        self.assertIsNone(data["cost"])
        self.assertIn("not recorded: no runner session worked on this task", self.p.harness("receipt", "7.2").stdout)

    def test_the_contract_declares_the_cost(self):
        self.assertIn("cost", self.p.json("contract", "--json")["commands"]["receipt"]["fields"])


if __name__ == "__main__":
    unittest.main()
