"""Delivery from a trusted clone (ADR-008, follow-up 4), from the factory's side.

With HARNESS_DELIVER="external" the lane holds no GitHub credential: `run` ends a finished, committed task at the
deliver step (`ready-to-deliver`) instead of starting the deliverer or retrying. `harness.py delivery-plan <id> --json`
tells the factory what to push and open, under the deliverer's rules (only the receipt's risk:* and class:* labels, a
risk:* label that only goes up, a draft PR naming the escalation for an escalated task), and
`harness.py delivery-record <id> <report.json>`, refused to agents, records the outcome that `next` reads, with the
checks the deliverer's own report gets. The factory's push and PR calls aren't in this repository.
"""
import json
import unittest

from factory_fixture import Project, agent_script

FINISHING_AGENT = """printf '%s\\n' "$prompt" > "$PROMPT_OUT"
task=$(printf '%s\\n' "$prompt" | sed -n 's/^Drive Task \\([^ ]*\\) .*/\\1/p')
sed -i.bak "s/^- \\[WIP\\] \\*\\*Task $task/- [x] **Task $task/" backbone/3-TASKS.md && rm -f backbone/3-TASKS.md.bak
git add -A && HARNESS_VERIFY=off git commit -qm "feat: task $task"
echo '{"type":"result","total_cost_usd":0.3,"num_turns":2,"result":"ok"}'
"""
# (labels on the PR already) -> (labels the plan adds, labels it removes), for a receipt suggesting risk:elevated
# and class:docs. One risk:* label per PR, and it only goes up.
LABELS = {
    (): (["risk:elevated", "class:docs"], []),
    ("risk:low",): (["risk:elevated", "class:docs"], ["risk:low"]),
    ("risk:elevated",): (["class:docs"], []),
    ("risk:high",): (["class:docs"], []),
    ("risk:elevated", "class:docs"): ([], []),
    ("risk:low", "risk:high"): (["class:docs"], []),
    ("bug", "risk:low", "class:docs"): (["risk:elevated"], ["risk:low"]),
}
EXTERNAL = {"HARNESS_DELIVER": "external"}


class ExternalDelivery(unittest.TestCase):
    """Task 7.1 is judged on branch harness/task-7.1 and finished by a runner session; 7.2 is escalated."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project("external delivery ", **EXTERNAL)
        cls.p.command("git", "checkout", "-q", "-b", "harness/task-7.1")
        cls.p.judged_task("7.1")
        cls.p.add_task("7.2", "Needs a decision")
        cls.p.commit("feat: customer search, judged")
        cls.prompt = cls.p.base / "prompt.txt"
        cls.finished = cls.p.harness("run", "--only", "7.1", check=False, env=dict(
            HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block", HARNESS_RUN_ATTEMPTS="2",
            PROMPT_OUT=str(cls.prompt), HARNESS_AGENT_CMD=agent_script(cls.p.base / "finish.sh", FINISHING_AGENT)))
        cls.head = cls.p.command("git", "rev-parse", "HEAD").stdout.strip()
        cls.step = cls.p.json("next", "7.1", "--json")

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def plan(self, *flags, check=True):
        result = self.p.harness("delivery-plan", "7.1", "--json", *flags, check=check)
        return json.loads(result.stdout), result.returncode

    def record(self, report, task="7.1"):
        path = self.p.base / "report.json"
        path.write_text(json.dumps(report))
        return self.p.harness("delivery-record", task, str(path), check=False)

    def delivered(self, **report):
        return dict(dict(delivery="delivered", branch="harness/task-7.1", base="main", head=self.head,
                         pr="https://github.com/o/r/pull/9", checks="passed", findings=[]), **report)

    def deliver_events(self):
        return [e for e in self.p.events("deliver") if e.get("task") == "7.1"]

    def test_run_ends_a_finished_task_ready_to_deliver_without_the_deliverer(self):
        step = self.step

        self.assertEqual(self.finished.returncode, 0, self.finished.stdout)
        self.assertIn("run: ready-to-deliver task 7.1", self.finished.stdout)
        self.assertNotIn("task 7.1 attempt 2", self.finished.stdout)
        self.assertEqual(self.p.json("escalations", "--json")["escalations"], [])
        self.assertEqual((step["step"], step["role"], step["external"]), ("deliver", None, True))
        self.assertIn("Delivery is external (HARNESS_DELIVER=external)", self.prompt.read_text())

    def test_the_plan_names_the_branch_the_commit_the_pr_and_the_labels(self):
        plan, code = self.plan()
        receipt = self.p.json("receipt", "7.1", "--json", "--base", "main")

        self.assertEqual(code, 0, plan)
        self.assertEqual((plan["ready"], plan["task"], plan["branch"], plan["base"], plan["head"], plan["draft"]),
                         (True, "7.1", "harness/task-7.1", "main", self.head, False))
        self.assertEqual(plan["title"], "Task 7.1: Customer search")
        self.assertIn("Receipt: Task 7.1: Customer search", plan["body"])
        self.assertIn("Only a human merges", plan["body"])
        self.assertEqual(receipt["suggested_labels"], ["risk:elevated", "class:docs"])
        self.assertEqual(plan["labels"], {"add": receipt["suggested_labels"], "remove": []})

    def test_a_risk_label_only_goes_up(self):
        for current, (add, remove) in LABELS.items():
            with self.subTest(current=current):
                plan, _ = self.plan("--pr-labels", ",".join(current))

                self.assertEqual(plan["labels"], {"add": add, "remove": remove})

    def test_an_escalated_task_gets_a_draft_pr_naming_the_escalation(self):
        self.p.harness("escalate", "7.2", "--reason", "the wording of the error is the user's call",
                       "--kind", "decision")
        self.p.commit("chore: escalate 7.2")
        try:
            plan = json.loads(self.p.harness("delivery-plan", "7.2", "--json").stdout)
        finally:
            self.p.command("git", "reset", "-q", "--hard", self.head)

        self.assertEqual((plan["ready"], plan["draft"], plan["labels"]), (True, True, {"add": [], "remove": []}))
        self.assertIn("BLOCKED", plan["body"])
        self.assertIn("decision: the wording of the error is the user's call", plan["body"])
        self.assertIn("No receipt: task 7.2 has no judge pass", plan["body"])

    def test_no_plan_names_uncommitted_work(self):
        self.p.write("notes.txt", "draft\n")
        try:
            result = self.p.harness("delivery-plan", "7.1", "--json", check=False)
        finally:
            (self.p.path / "notes.txt").unlink()
        plan = json.loads(result.stdout)

        self.assertEqual((result.returncode, plan["ready"]), (1, False))
        self.assertIn("commit", plan["needed"])

    def test_no_plan_for_a_task_still_being_built(self):
        self.p.add_task("7.3", "Not built")
        try:
            result = self.p.harness("delivery-plan", "7.3", "--json", check=False)
        finally:
            self.p.command("git", "checkout", "-q", "--", "backbone/3-TASKS.md")
        plan = json.loads(result.stdout)

        self.assertEqual((result.returncode, plan["ready"]), (1, False))
        self.assertIn("task 7.3 is at step define", plan["needed"])

    def test_a_record_that_doesnt_match_the_checkout_is_refused_and_records_nothing(self):
        cases = {
            "another head": (self.delivered(head="0" * 40), "is not the task's HEAD"),
            "no head": (self.delivered(head=None), "head is required"),
            "checks pending": (self.delivered(checks="pending"), "checks are 'pending'"),
            "an unknown outcome": (self.delivered(delivery="merged"), "delivery must be one of delivered, hold, "
                                                                      "ci-failed"),
            "a hold without findings": (self.delivered(delivery="hold", findings=[]), "lists the findings"),
            "a finding without an owner": (self.delivered(delivery="ci-failed", checks="failed",
                                                          findings=[{"issue": "lint"}]), "each with an owner"),
        }
        for case, (report, message) in cases.items():
            with self.subTest(case=case):
                before = len(self.deliver_events())
                result = self.record(report)

                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(message, result.stdout)
                self.assertEqual(len(self.deliver_events()), before)

    def test_next_reads_what_the_factory_recorded(self):
        failed = self.record(self.delivered(delivery="ci-failed", checks="failed", findings=[
            {"issue": "test_search fails on Windows paths", "owner": "implementer"}]))
        after_failure = self.p.json("next", "7.1", "--json")
        delivered = self.record(self.delivered())
        after_delivery = self.p.json("next", "7.1", "--json")
        [*_, event] = self.deliver_events()

        self.assertEqual(failed.returncode, 0, failed.stdout)
        self.assertEqual((after_failure["step"], after_failure["owners"]), ("delivery-failed", ["implementer"]))
        self.assertEqual(delivered.returncode, 0, delivered.stdout)
        self.assertEqual((after_delivery["step"], after_delivery["pr"]), ("done", "https://github.com/o/r/pull/9"))
        self.assertEqual((event["via"], event["head"], event["checks"]), ("external", self.head, "passed"))

    def test_agents_may_plan_but_not_record_a_delivery(self):
        self.assertEqual(self.p.bash("python3 scripts/harness/lib/harness.py delivery-plan 7.1 --json",
                                     "implementer").returncode, 0)
        self.assertEqual(self.p.bash("python3 scripts/harness/lib/harness.py delivery-record 7.1 r.json",
                                     "implementer").returncode, 2)

    def test_a_deliverer_in_the_lane_neither_pushes_nor_records(self):
        before = len(self.p.events("deliver"))
        push = self.p.bash("git push -u origin HEAD", "deliverer")
        stop = self.p.hook("deliver-stop", {"hook_event_name": "SubagentStop", "agent_type": "deliverer",
                                            "stop_hook_active": True, "last_assistant_message": "Done.\n\n```json\n%s\n```"
                                            % json.dumps({"delivery": "delivered", "checks": "none", "findings": []})})

        self.assertEqual(push.returncode, 2, push.stderr)
        self.assertIn("HARNESS_DELIVER=external", push.stderr)
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertEqual(len(self.p.events("deliver")), before)

    def test_doctor_knows_the_delivery_modes(self):
        accepted = self.p.harness("doctor", check=False).stdout
        rejected = self.p.harness("doctor", check=False, env={"HARNESS_DELIVER": "factory"}).stdout

        self.assertNotIn("HARNESS_DELIVER must be", accepted)
        self.assertIn("HARNESS_DELIVER must be on, off or external", rejected)

    def test_the_contract_declares_the_plan(self):
        commands = self.p.json("contract", "--json")["commands"]

        self.assertLessEqual({"ready", "task", "branch", "base", "head", "title", "body", "draft", "labels"},
                             set(commands["delivery-plan"]["fields"]))
        self.assertLessEqual({"delivery", "head", "checks", "findings"},
                             set(commands["delivery-record"]["report_fields"]))


if __name__ == "__main__":
    unittest.main()
