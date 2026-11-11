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
        verify = {"range": "origin/main..%s" % self.head, "head": self.head, "exit": 0}
        return dict(dict(delivery="delivered", branch="harness/task-7.1", base="main", head=self.head,
                         pr="https://github.com/o/r/pull/9", checks="passed", findings=[], verify=verify), **report)

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
            "no verify result": (self.delivered(verify=None), "verify is required"),
            "verify of another head": (self.delivered(verify={"range": "origin/main..%s" % ("0" * 40),
                                                              "head": "0" * 40, "exit": 0}),
                                       "verify ran on 000000000000, not the task's HEAD"),
            "verify of another range": (self.delivered(verify={"range": "origin/main..main", "head": self.head,
                                                               "exit": 0}), "the verified range doesn't end at"),
            "a failed verify, delivered": (self.delivered(verify={"range": "origin/main..%s" % self.head,
                                                                  "head": self.head, "exit": 1}),
                                           "verify exited 1"),
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

    def test_a_failed_verify_is_recorded_as_a_hold(self):
        held = self.record(self.delivered(delivery="hold", checks="none", verify={
            "range": "origin/main..%s" % self.head, "head": self.head, "exit": 1},
            findings=[{"issue": "verify: the judge pass is stale", "owner": "judge"}]))
        step = self.p.json("next", "7.1", "--json")
        self.record(self.delivered())

        self.assertEqual(held.returncode, 0, held.stdout)
        self.assertEqual((step["step"], step["owners"]), ("delivery-failed", ["judge"]))

    def test_with_a_delivery_key_next_trusts_only_signed_records(self):
        key = {"HARNESS_DELIVERY_KEY": "factory-secret"}
        events = self.p.path / ".git/harness/events.jsonl"
        failed = self.delivered(delivery="ci-failed", checks="failed", findings=[{"issue": "red", "owner": "implementer"}])
        path = self.p.base / "signed.json"
        path.write_text(json.dumps(failed))
        self.p.harness("delivery-record", "7.1", str(path), env=key)
        forged = dict(json.loads(events.read_text().splitlines()[-1]), delivery="delivered", checks="passed",
                      findings=0, owners=[], findings_detail=[])
        with events.open("a") as log:
            log.write(json.dumps(forged) + "\n")

        signed_view = self.p.json("next", "7.1", "--json", env=key)
        unsigned_view = self.p.json("next", "7.1", "--json")
        self.record(self.delivered())

        self.assertEqual(signed_view["step"], "delivery-failed")
        self.assertEqual(unsigned_view["step"], "done")

    def test_a_record_counts_only_for_its_own_task(self):
        self.p.add_task("7.5", "Finished alongside", marker="x")
        self.p.commit("chore: task 7.5 done")
        head = self.p.command("git", "rev-parse", "HEAD").stdout.strip()
        try:
            recorded = self.record(self.delivered(head=head, verify={"range": "origin/main..%s" % head, "head": head,
                                                                     "exit": 0}))
            own = self.p.json("next", "7.1", "--json")
            other = self.p.json("next", "7.5", "--json")
        finally:
            self.p.command("git", "reset", "-q", "--hard", self.head)

        self.assertEqual(recorded.returncode, 0, recorded.stdout)
        self.assertEqual(own["step"], "done")
        self.assertEqual(other["step"], "deliver")

    def test_run_and_orca_refuse_to_start_with_the_delivery_key(self):
        seen = self.p.base / "session-started"
        agent = agent_script(self.p.base / "key-agent.sh", 'touch "%s"\necho \'{"type":"result","total_cost_usd":0,'
                                                          '"num_turns":1,"result":"ok"}\'\n' % seen)
        env = dict(HARNESS_AUTONOMY="autonomous", HARNESS_VERIFY="block", HARNESS_RUN_ATTEMPTS="1",
                   HARNESS_AGENT_CMD=agent, HARNESS_DELIVERY_KEY="factory-secret")
        run = self.p.harness("run", check=False, env=env)
        orca = self.p.harness("orca", "--pr", check=False, env=env)
        judge = self.p.harness("ci-judge", "--range", "HEAD~1..HEAD", check=False, env=env)

        for name, result in (("run", run), ("orca", orca), ("ci-judge", judge)):
            with self.subTest(command=name):
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("%s: HARNESS_DELIVERY_KEY is set in this environment" % name, result.stdout)
                self.assertNotIn("factory-secret", result.stdout)
        self.assertFalse(seen.exists())

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

    def test_no_role_pushes_or_opens_a_pr_in_external_mode(self):
        for agent in ("implementer", "scribe", None):
            for command in ("git push -u origin HEAD", "gh pr create --base main --title t --body b",
                            "gh pr edit 9 --add-label risk:low"):
                with self.subTest(agent=agent, command=command):
                    answer = self.p.bash(command, agent)

                    self.assertEqual(answer.returncode, 2, answer.stderr)
                    self.assertIn("HARNESS_DELIVER=external", answer.stderr)
        self.assertEqual(self.p.bash("git status --short", "implementer").returncode, 0)

    def test_every_role_only_reads_github_and_pushes_nothing_in_external_mode(self):
        refused = ("gh pr merge 9", "gh pr close 9", "gh pr ready 9", "gh pr review 9 --approve",
                   "gh issue create -t x -b y", "gh release create v1", "gh workflow run deploy.yml",
                   "gh api -X POST repos/o/r/pulls -f title=t", "gh repo edit --enable-auto-merge",
                   "git -c alias.p=push p origin HEAD", "git send-pack origin HEAD", "git config alias.p push",
                   "git --config-env=user.name=X fetch origin", "echo 9 | xargs gh pr merge")
        allowed = ("gh pr view 9", "gh pr checks 9", "gh run view 1", "gh api repos/o/r/pulls/9", "git status",
                   "git log -1", "git fetch origin", "git config --get user.name", "git diff HEAD~1")
        for agent in ("implementer", None):
            for command in refused:
                with self.subTest(agent=agent, command=command):
                    answer = self.p.bash(command, agent)

                    self.assertEqual(answer.returncode, 2, answer.stderr)
                    self.assertIn("HARNESS_DELIVER=external", answer.stderr)
            for command in allowed:
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(self.p.bash(command, agent).returncode, 0)

    def test_git_runs_no_push_through_runners_subcommands_or_its_own_binaries(self):
        refused = ("find . -maxdepth 0 -exec git push origin HEAD \\;", "git subtree push --prefix=x origin main",
                   "/usr/libexec/git-core/git-push origin HEAD", "git-push origin HEAD",
                   "git submodule foreach git push", "git lfs push origin HEAD", "echo HEAD | xargs git push origin",
                   "sh -c 'git push origin HEAD'", "find . -maxdepth 0 -exec gh pr merge 9 \\;")
        for agent in ("implementer", "deliverer", None):
            for command in refused:
                with self.subTest(agent=agent, command=command):
                    answer = self.p.bash(command, agent)

                    self.assertEqual(answer.returncode, 2, answer.stderr)
        self.assertEqual(self.p.bash("git submodule status", "implementer").returncode, 0)

    def test_doctor_knows_the_delivery_modes(self):
        accepted = self.p.harness("doctor", check=False).stdout
        rejected = self.p.harness("doctor", check=False, env={"HARNESS_DELIVER": "factory"}).stdout

        self.assertNotIn("HARNESS_DELIVER must be", accepted)
        self.assertIn("HARNESS_DELIVER must be on, off or external", rejected)

    def test_the_contract_declares_the_plan(self):
        commands = self.p.json("contract", "--json")["commands"]

        self.assertLessEqual({"ready", "task", "branch", "base", "head", "title", "body", "draft", "labels"},
                             set(commands["delivery-plan"]["fields"]))
        self.assertLessEqual({"delivery", "head", "checks", "findings", "verify"},
                             set(commands["delivery-record"]["report_fields"]))


if __name__ == "__main__":
    unittest.main()
