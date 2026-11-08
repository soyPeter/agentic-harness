"""harness.py attest (ADR-005): the unsigned in-toto Statement that harness-verify signs, checked through the command
and through the workflow's statement step, in throwaway projects.

Signing, and checking a signature, are cosign's job. What the harness owns is the statement: that it exists only for a
range that verifies, what it says about each finished task, and that the same commits give the same bytes. No cosign
is needed here. The property checks need hypothesis (pip install -r tests/requirements.txt) and are skipped without it.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
except ImportError:
    given = None


HARNESS = Path(__file__).resolve().parents[1]
ENGINE = HARNESS / "payload/owned/scripts/harness/lib/harness.py"
LAUNCHER = HARNESS / "plugin/launcher.py"
WORKFLOW = HARNESS / "payload/owned/.github/workflows/harness-verify.yml"
VERSION = (HARNESS / "VERSION").read_text().strip()
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1"
VERIFIER = "https://github.com/soyPeter/agentic-harness"
LENSES = ("correctness", "structure", "lean")
APPROVAL = "Approved-by: Ana (2026-11-01)"
STATEMENT_FILE = "harness-attestation/harness-verdicts.intoto.json"
SPEC = """# Spec {task}: {title}

Task: {task}
PRD: none
Change-Class: {change_class}

## Context
Support needs to find customers by name.

## Requirements
- REQ-{task}-1: The system shall return customers whose name contains the query, ignoring case.

## Acceptance criteria
- AC-{task}-1 (REQ-{task}-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.

## Non-functional requirements
- Search answers within 200 ms.

## Architecture
ADRs: ADR-001
Tech requirements:
- The code lives in src/.

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
SEARCH = {"src/search.py": "def search(names, query):\n    return [n for n in names if query.lower() in n.lower()]\n",
          "tests/test_search.py": "def test_ac():  # AC-1.1-1\n    assert True\n"}
# Rewrites src/search.py at another size, so the judge's fingerprint can't read a stale index entry.
SORT = {"src/sort.py": "def by_name(names):\n    return sorted(names, key=str.lower)\n",
        "src/search.py": "def search(names, query):\n    query = query.lower()\n"
                         "    return [n for n in names if query in n.lower()]\n",
        "tests/test_sort.py": "def test_ac():  # AC-1.2-1\n    assert True\n"}


def environment(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="test",
               GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com",
               PYTHONDONTWRITEBYTECODE="1", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true")
    env.update(settings)
    return env


def run(cwd, *args, input=None, check=True, **settings):
    streams = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    result = subprocess.run([str(a) for a in args], cwd=str(cwd), env=environment(**settings), capture_output=True,
                            text=True, **streams)
    if check and result.returncode:
        raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(map(str, args)), result.returncode,
                                                             result.stdout, result.stderr))
    return result


def sha256(data):
    return hashlib.sha256(data).hexdigest()


TAKE_BASE = "Take the verifier from the base branch"
TAKE_PUSHED = "Take the verifier from the pushed commit"


def step_script(name, source=None):
    """The shell script of the harness-verify step called name, with the harness repository's URL pointed at
    source."""
    step = WORKFLOW.read_text().split("      - name: %s\n" % name, 1)[1]
    script = textwrap.dedent(re.split(r"\n(?=      - name:|  \S)", step.split("        run: |\n", 1)[1], maxsplit=1)[0])
    return script.replace("https://github.com/soyPeter/agentic-harness.git", str(source)) if source else script


class Project:
    """A throwaway repository holding an install of this checkout as its first commit, self.adopted. settings go
    into the environment of every command run in it."""

    def __init__(self, root, installer=None, **settings):
        self.root = root
        self.settings = settings
        root.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        if installer:
            installer(self)
        else:
            self.run(HARNESS / "bootstrap.sh", root, "--name", "attest")
        self.adopted = self.commit("chore: adopt the agentic harness")

    @property
    def engine(self):
        return self.root / "scripts/harness/lib/harness.py"

    def run(self, *args, **options):
        return run(self.root, *args, **dict(self.settings, **options))

    def git(self, *args):
        return self.run("git", *args).stdout.strip()

    def harness(self, *args, check=False, **settings):
        return self.run("python3", "-B", self.engine, *args, check=check, **settings)

    def attest(self, base, *flags, **settings):
        return self.harness("attest", "--range", "%s..HEAD" % base, *flags, **settings)

    def statement(self, base, *flags, **settings):
        return json.loads(self.attest(base, *flags, check=True, **settings).stdout)

    def hook(self, event, agent, report):
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": "Done.\n\n```json\n%s\n```" % json.dumps(report)}
        self.run("python3", "-B", self.engine, "hook", event, CLAUDE_PROJECT_DIR=str(self.root), input=json.dumps(stop))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append(self, name, text):
        with open(str(self.root / name), "a", encoding="utf-8") as handle:
            handle.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def set_marker(self, task, old, new):
        # The seed's comment shows an example "- [ ] **Task 1.1:" line above the real ones.
        head, line, tail = (self.root / "backbone/3-TASKS.md").read_text(encoding="utf-8").rpartition(
            "- [%s] **Task %s:" % (old, task))
        self.write("backbone/3-TASKS.md", head + line.replace("[%s]" % old, "[%s]" % new, 1) + tail)

    def specify(self, task, title, change_class="feature"):
        """task's spec, grilled and approved by the user, committed with its pending task line."""
        self.write("backbone/specs/%s.md" % task, SPEC.format(task=task, title=title, change_class=change_class))
        self.append("backbone/3-TASKS.md", "- [ ] **Task %s: %s** (spec: backbone/specs/%s.md)\n" % (task, title, task))
        self.hook("grill-stop", "griller", {"verdict": "pass", "task": task, "questions": [], "summary": "s"})
        self.append("backbone/specs/%s.md" % task, APPROVAL + "\n")
        return self.commit("docs: spec for task %s" % task)

    def build(self, task, files):
        """task's change (files), judged and reviewed through every lens on that code, marked done and committed."""
        self.set_marker(task, " ", "WIP")
        for name, text in files.items():
            self.write(name, text)
        self.hook("judge-stop", "judge", {
            "verdict": "pass", "task": task, "summary": "s", "findings": [],
            "criteria": [{"id": "AC-%s-1" % task, "met": True, "evidence": "src", "tests": ["test_ac"]}],
            "tests": {"command": "true", "result": "passed"}})
        for lens in LENSES:
            self.hook("review-stop", "reviewer", {"task": task, "lens": lens, "verdict": "pass", "findings": [],
                                                  "summary": "s"})
        self.set_marker(task, "WIP", "x")
        return self.commit("feat: task %s" % task)

    def finish(self, task, title, files, change_class="feature"):
        self.specify(task, title, change_class)
        return self.build(task, files)

    def verdicts(self, task, kind):
        return json.loads((self.root / ("backbone/.verdicts/%s.%s.json" % (task, kind))).read_text())["history"]


def new_project(test):
    temp = tempfile.TemporaryDirectory(prefix="attest ")
    test.addCleanup(temp.cleanup)
    return Project(Path(temp.name).resolve() / "project")


class FinishedTask(unittest.TestCase):
    """Task 1.1's spec in one commit; its code, judged and reviewed, and its [x] in the next (the tip)."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="attest ")
        cls.addClassCleanup(temp.cleanup)
        cls.work = Path(temp.name).resolve()
        cls.project = Project(cls.work / "project")
        cls.tip = cls.project.finish("1.1", "Customer search", SEARCH)
        cls.output = cls.project.harness("attest", "--range", cls.project.adopted + "..HEAD", check=True).stdout
        cls.made = json.loads(cls.output)


class Statement(FinishedTask):
    def test_it_is_an_in_toto_statement_about_the_tip_commit_and_its_code(self):
        judge = self.project.verdicts("1.1", "judge")[-1]

        self.assertEqual(self.made["_type"], STATEMENT_TYPE)
        self.assertEqual(self.made["predicateType"], PREDICATE_TYPE)
        self.assertEqual(self.made["subject"], [{"name": "commit", "digest": {"gitCommit": self.tip}},
                                                {"name": "code", "digest": {"gitTree": judge["fingerprint"]}}])

    def test_the_code_subject_leaves_backbone_out(self):
        self.assertNotEqual(self.made["subject"][1]["digest"]["gitTree"], self.project.git("rev-parse", "HEAD^{tree}"))

    def test_the_verifier_is_the_engine_that_ran_and_the_release_the_base_commit_installed(self):
        self.assertEqual(self.made["predicate"]["verifier"], {
            "id": VERIFIER, "engineSha256": sha256(self.project.engine.read_bytes()),
            "baseLock": {"mode": "full", "version": VERSION}})

    def test_the_verification_names_the_range_its_result_and_every_setting_verify_read(self):
        verification = self.made["predicate"]["verification"]

        self.assertEqual({k: v for k, v in verification.items() if k != "settings"}, {
            "base": self.project.adopted, "tip": self.tip, "result": "PASSED", "allowUserChanges": False})
        self.assertEqual(verification["settings"]["HARNESS_SPEC_GATE"], {"value": "on", "environment": False})
        self.assertEqual(verification["settings"]["HARNESS_JUDGE_GATE"], {"value": "on", "environment": False})
        self.assertEqual(verification["settings"]["HARNESS_REVIEW"], {"value": "on", "environment": False})
        self.assertEqual(verification["settings"]["HARNESS_TESTER"], {"value": "off", "environment": False})
        self.assertEqual(verification["settings"]["HARNESS_ALLOW_PARALLEL_WIP"], {"value": "0", "environment": False})
        self.assertEqual(verification["settings"]["HARNESS_VERIFY"], {"value": "off", "environment": True})
        self.assertTrue(all(key.startswith("HARNESS_") for key in verification["settings"]))

    def test_a_finished_task_carries_its_spec_class_and_verdicts(self):
        grill = self.project.verdicts("1.1", "grill")[-1]
        judge = self.project.verdicts("1.1", "judge")[-1]
        reviews = {entry["lens"]: entry for entry in self.project.verdicts("1.1", "review")}

        task = self.made["predicate"]["tasks"][0]

        self.assertEqual(len(self.made["predicate"]["tasks"]), 1)
        self.assertEqual((task["task"], task["title"], task["finishedIn"]), ("1.1", "Customer search", self.tip))
        self.assertEqual(task["spec"], {"path": "backbone/specs/1.1.md", "fingerprint": grill["fingerprint"],
                                        "approval": [APPROVAL]})
        self.assertEqual(task["changeClass"], {"class": "feature", "declared": True, "problem": None})
        self.assertEqual(task["grill"], {"verdict": "pass", "fingerprint": grill["fingerprint"], "at": grill["at"],
                                         "rounds": 1})
        self.assertEqual(task["judge"], {"verdict": "pass", "fingerprint": judge["fingerprint"], "at": judge["at"],
                                         "rounds": 1, "testRun": {"command": "true", "exit": 0,
                                                                  "outputSha256": judge["test_run"]["output_sha256"]}})
        self.assertEqual(task["reviews"], {lens: {"verdict": "pass", "fingerprint": judge["fingerprint"],
                                                  "at": reviews[lens]["at"], "rounds": 1} for lens in LENSES})

    def test_its_risk_and_receipt_are_what_the_receipt_says(self):
        receipt = json.loads(self.project.harness("receipt", "1.1", "--json", check=True).stdout)

        task = self.made["predicate"]["tasks"][0]

        self.assertEqual(task["risk"], {"reasons": receipt["risks"], "labels": receipt["suggested_labels"]})
        self.assertEqual(task["receipt"], {"verified": receipt["verified"], "notVerified": receipt["not_verified"],
                                           "approvalNeeded": receipt["approval_needed"]})
        self.assertIn("NFR not covered by any acceptance criterion: Search answers within 200 ms.",
                      task["receipt"]["notVerified"])
        self.assertEqual(task["risk"]["labels"], ["risk:elevated", "class:feature"])

    def test_it_is_written_with_sorted_keys_and_fixed_indentation(self):
        self.assertEqual(self.output, json.dumps(self.made, indent=2, sort_keys=True) + "\n")

    def test_the_same_commits_give_the_same_bytes_at_another_time_zone_and_locale(self):
        again = self.project.harness("attest", "--range", self.project.adopted + "..HEAD", check=True,
                                     TZ="Asia/Kathmandu", LC_ALL="C", LANG="C")

        self.assertEqual(again.stdout, self.output)

    def test_a_clone_somewhere_else_gives_the_same_bytes(self):
        clone = self.work / "another place" / "clone"
        run(self.work, "git", "clone", "-q", self.project.root, clone)

        again = run(clone, "python3", "-B", clone / "scripts/harness/lib/harness.py", "attest", "--range",
                    self.project.adopted + "..HEAD")

        self.assertEqual(again.stdout, self.output)


class Refusals(unittest.TestCase):
    """A range verify --range rejects gets no statement: attest exits 1, writes nothing to stdout and gives verify's
    problems on stderr."""

    def setUp(self):
        self.project = new_project(self)

    def assert_refused_as_verify_refuses(self, base):
        verify = self.project.harness("verify", "--range", base + "..HEAD")
        attest = self.project.attest(base)

        self.assertEqual(verify.returncode, 1, verify.stdout)
        self.assertEqual((attest.returncode, attest.stdout), (1, ""))
        self.assertEqual(attest.stderr, verify.stdout.replace("verify: ", "attest: "))

    def test_a_user_only_setting_changed_in_the_range(self):
        self.project.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\n')
        self.project.commit("chore: switch the reviews off")

        self.assert_refused_as_verify_refuses(self.project.adopted)

    def test_a_task_finished_without_a_judge_pass(self):
        self.project.specify("1.1", "Customer search")
        self.project.set_marker("1.1", " ", "x")
        self.project.commit("feat: task 1.1")

        self.assert_refused_as_verify_refuses(self.project.adopted)

    def test_recorded_verdicts_rewritten(self):
        base = self.project.finish("1.1", "Customer search", SEARCH)
        self.project.write("backbone/.verdicts/1.1.judge.json", json.dumps({"task": "1.1", "kind": "judge",
                                                                            "history": []}))
        self.project.commit("chore: tidy the verdicts")

        self.assert_refused_as_verify_refuses(base)

    def test_the_harness_itself_changed(self):
        self.project.append("scripts/harness/lib/harness.py", "# a local change\n")
        self.project.commit("chore: change the harness")

        self.assert_refused_as_verify_refuses(self.project.adopted)

    def test_the_allow_flag_lets_a_user_only_change_through_and_is_recorded(self):
        self.project.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\nHARNESS_JUDGE_MAX_ROUNDS="3"\n')
        self.project.commit("chore: switch the reviews off")

        made = self.project.statement(self.project.adopted, "--allow-user-changes")

        settings = made["predicate"]["verification"]["settings"]
        self.assertTrue(made["predicate"]["verification"]["allowUserChanges"])
        self.assertEqual(settings["HARNESS_REVIEW"], {"value": "off", "environment": False})
        self.assertEqual(settings["HARNESS_JUDGE_MAX_ROUNDS"], {"value": "3", "environment": False})

    def test_a_setting_only_the_environment_sets_changes_what_verify_accepts_and_is_recorded_as_overridden(self):
        self.project.specify("1.1", "Customer search")
        self.project.specify("1.2", "Sorted results")
        self.project.set_marker("1.1", " ", "WIP")
        self.project.set_marker("1.2", " ", "WIP")
        self.project.commit("chore: start two tasks")
        self.assert_refused_as_verify_refuses(self.project.adopted)

        made = self.project.statement(self.project.adopted, HARNESS_ALLOW_PARALLEL_WIP="1")

        self.assertEqual(made["predicate"]["verification"]["settings"]["HARNESS_ALLOW_PARALLEL_WIP"],
                         {"value": "1", "environment": True})

    def test_untracked_or_uncommitted_files_get_no_statement(self):
        tip = self.project.finish("1.1", "Customer search", SEARCH)
        for change in ("untracked", "modified", "staged"):
            with self.subTest(change=change):
                if change == "untracked":
                    self.project.write("notes/todo.txt", "later\n")
                elif change == "modified":
                    self.project.append("src/search.py", "# later\n")
                else:
                    self.project.append("src/search.py", "# later\n")
                    self.project.git("add", "src/search.py")

                attest = self.project.attest(self.project.adopted)

                self.assertEqual((attest.returncode, attest.stdout), (1, ""))
                self.assertIn("uncommitted", attest.stderr)
                self.assertIn("notes/todo.txt" if change == "untracked" else "src/search.py", attest.stderr)
                self.project.git("reset", "-q", "--hard", tip)
                self.project.git("clean", "-fdq")

    def test_a_checkout_of_another_commit_gets_no_statement(self):
        tip = self.project.finish("1.1", "Customer search", SEARCH)
        self.project.git("checkout", "-q", "--detach", "HEAD~1")

        attest = self.project.harness("attest", "--range", "%s..%s" % (self.project.adopted, tip))

        self.assertEqual((attest.returncode, attest.stdout), (1, ""))
        self.assertIn("the checkout is at %s, not %s" % (self.project.git("rev-parse", "HEAD")[:12], tip[:12]),
                      attest.stderr)

    def test_a_revision_that_is_not_a_commit_gets_no_statement(self):
        attest = self.project.harness("attest", "--range", "no-such-branch..HEAD")

        self.assertEqual((attest.returncode, attest.stdout), (1, ""))
        self.assertIn("no-such-branch is not a commit", attest.stderr)

    def test_without_a_range_it_prints_its_usage(self):
        for args in ((), ("--range",), ("--range", "HEAD"), ("--range", "HEAD~1..HEAD", "--json")):
            with self.subTest(args=args):
                attest = self.project.harness("attest", *args)

                self.assertEqual((attest.returncode, attest.stdout), (64, ""))
                self.assertIn("usage: harness.py attest --range <base>..<tip> [--allow-user-changes]", attest.stderr)


class Ranges(unittest.TestCase):
    def setUp(self):
        self.project = new_project(self)

    def test_a_task_finished_before_later_code_keeps_the_code_it_was_judged_on(self):
        first = self.project.finish("1.1", "Customer search", SEARCH)
        first_code = self.project.statement(self.project.adopted)["subject"][1]["digest"]["gitTree"]
        tip = self.project.finish("1.2", "Sorted results", SORT)

        made = self.project.statement(self.project.adopted)

        code = made["subject"][1]["digest"]["gitTree"]
        tasks = {task["task"]: task for task in made["predicate"]["tasks"]}
        self.assertEqual(sorted(tasks), ["1.1", "1.2"])
        self.assertEqual((tasks["1.1"]["finishedIn"], tasks["1.2"]["finishedIn"]), (first, tip))
        self.assertEqual(tasks["1.1"]["judge"]["fingerprint"], first_code)
        self.assertNotEqual(first_code, code)
        self.assertEqual(tasks["1.2"]["judge"]["fingerprint"], code)
        self.assertIsNotNone(tasks["1.1"]["receipt"])
        self.assertIsNotNone(tasks["1.2"]["receipt"])

    def test_the_rounds_count_every_recorded_verdict_and_the_latest_is_stated(self):
        self.project.specify("1.1", "Customer search")
        self.project.set_marker("1.1", " ", "WIP")
        self.project.hook("judge-stop", "judge", {"verdict": "fail", "task": "1.1", "summary": "s", "criteria": [],
                                                  "findings": [], "tests": {"command": "true", "result": "failed"}})
        self.project.set_marker("1.1", "WIP", " ")
        self.project.build("1.1", SEARCH)

        judge = self.project.statement(self.project.adopted)["predicate"]["tasks"][0]["judge"]

        self.assertEqual((judge["verdict"], judge["rounds"]), ("pass", 2))

    def test_a_range_that_finishes_no_task_is_attested_with_no_tasks(self):
        self.project.write("docs/guide.md", "# Guide\n")
        self.project.commit("docs: a guide")

        made = self.project.statement(self.project.adopted)

        self.assertEqual(made["predicate"]["tasks"], [])
        self.assertEqual(made["predicate"]["verification"]["result"], "PASSED")

    def test_verify_passes_a_range_whose_later_commit_changes_backbone_after_a_task_is_finished(self):
        self.project.finish("1.1", "Customer search", SEARCH)
        self.project.append("backbone/6-MEMORY.md", "\n- Search ignores case.\n")
        self.project.commit("docs: remember how search works")

        verify = self.project.harness("verify", "--range", self.project.adopted + "..HEAD")

        self.assertEqual((verify.returncode, verify.stdout), (0, "verify: ok\n"))

    def test_a_commit_that_changes_only_backbone_keeps_the_code_digest(self):
        tip = self.project.finish("1.1", "Customer search", SEARCH)
        before = self.project.statement(self.project.adopted)
        self.project.append("backbone/6-MEMORY.md", "\n- Search ignores case.\n")
        memory = self.project.commit("docs: remember how search works")

        after = self.project.statement(self.project.adopted)

        self.assertEqual(after["subject"][0]["digest"], {"gitCommit": memory})
        self.assertEqual(after["subject"][1], before["subject"][1])
        self.assertEqual(after["predicate"]["tasks"][0]["finishedIn"], tip)


class Workflow(unittest.TestCase):
    """harness-verify's steps, run as CI runs them in throwaway projects: the take step fetches the verifier from a ref,
    then the verify step checks a pull request and the statement step writes a pushed range's statement. The rest of the
    workflow (checkouts, uploads, signing) is checked in its text."""

    def pull_request(self, project, base):
        """The ref a pull request's base is taken from, with base as origin/review-base."""
        project.git("update-ref", "refs/remotes/origin/review-base", base)
        return "origin/review-base"

    def take_engine(self, project, ref, take=TAKE_PUSHED, source=None):
        """(runner's temp dir, the engine the take step leaves for the steps after it)."""
        runner = Path(tempfile.mkdtemp(prefix="runner ", dir=str(project.root.parent)))
        ci = dict(BASE_REF=ref, RUNNER_TEMP=str(runner), GITHUB_ENV=str(runner / "github-env"))
        project.run("bash", "-e", "-o", "pipefail", "-c", step_script(take, source), **ci)
        return runner, (runner / "github-env").read_text().strip().split("=", 1)[1]

    def verify_pull_request(self, project, engine, allow=""):
        return project.run("bash", "-e", "-c", step_script("Verify the pull request's commits"), check=False,
                           ENGINE_SCRIPT=engine, HARNESS_ROOT=str(project.root), BASE="review-base", ALLOW=allow)

    def write_statement(self, project, ref, before, source=None):
        """Takes the verifier from ref, then writes the statement of before..HEAD: (the step's result, runner's temp dir)."""
        runner, engine = self.take_engine(project, ref, source=source)
        result = project.run("bash", "-e", "-c", step_script("Write the verdict attestation"), check=False,
                             ENGINE_SCRIPT=engine, HARNESS_ROOT=str(project.root), BEFORE=before,
                             RUNNER_TEMP=str(runner))
        return result, runner

    def ci_statement(self, project, ref, before, source=None):
        result, runner = self.write_statement(project, ref, before, source=source)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((runner / STATEMENT_FILE).read_text())

    def test_a_pull_request_is_verified_by_the_base_branch_engine_even_when_it_changes_the_engine(self):
        project = new_project(self)
        project.finish("1.1", "Customer search", SEARCH)
        project.write("scripts/harness/lib/harness.py", project.engine.read_text().replace(
            "def verify_command(argv):\n", "def verify_command(argv):\n    return 0\n", 1))
        project.commit("chore: make verify pass")
        self.assertEqual(project.harness("verify", "--range", project.adopted + "..HEAD").returncode, 0)
        ref = self.pull_request(project, project.adopted)
        _, base_engine = self.take_engine(project, ref, take=TAKE_BASE)

        refused = self.verify_pull_request(project, base_engine)
        allowed = self.verify_pull_request(project, base_engine, allow="--allow-user-changes")

        self.assertEqual(refused.returncode, 1)
        self.assertIn("verify: the harness itself changes (scripts/harness/lib/harness.py)", refused.stdout)
        self.assertEqual((allowed.returncode, allowed.stdout), (0, "verify: ok\n"))

    def test_a_pushed_commit_is_attested_for_its_range_with_the_engine_at_its_tip(self):
        project = new_project(self)
        tip = project.finish("1.1", "Customer search", SEARCH)

        made = self.ci_statement(project, tip, project.adopted)

        self.assertEqual(made["subject"][0]["digest"], {"gitCommit": tip})
        self.assertEqual(made["predicate"]["verification"]["base"], project.adopted)
        self.assertEqual(made["predicate"]["verifier"]["engineSha256"], sha256(project.engine.read_bytes()))
        self.assertFalse(made["predicate"]["verification"]["allowUserChanges"])
        self.assertEqual([task["task"] for task in made["predicate"]["tasks"]], ["1.1"])

    def test_a_pushed_harness_change_gets_no_statement(self):
        project = new_project(self)
        project.finish("1.1", "Customer search", SEARCH)
        project.append("scripts/harness/lib/harness.py", "# a local change\n")
        project.commit("chore: change the harness")

        result, runner = self.write_statement(project, project.git("rev-parse", "HEAD"), project.adopted)

        self.assertEqual(result.returncode, 1)
        self.assertIn("the harness itself changes", result.stderr)
        self.assertFalse((runner / STATEMENT_FILE).exists())

    def test_a_pushed_range_whose_base_is_not_an_ancestor_gets_no_statement(self):
        project = new_project(self)
        tip = project.finish("1.1", "Customer search", SEARCH)

        result, runner = self.write_statement(project, tip, "0" * 40)

        self.assertEqual(result.returncode, 1)
        self.assertIn("is not an ancestor", result.stderr)
        self.assertFalse((runner / STATEMENT_FILE).exists())

    def test_a_thin_project_is_attested_by_the_engine_its_pin_names(self):
        temp = tempfile.TemporaryDirectory(prefix="attest thin ")
        self.addCleanup(temp.cleanup)
        work = Path(temp.name).resolve()
        source = work / "source"
        thin = dict(HARNESS_ENGINE_SOURCE=str(source), HARNESS_ENGINES=str(work / "cache"),
                    CODEX_HOME=str(work / "codex"), OPENCODE_CONFIG_DIR=str(work / "opencode"),
                    XDG_CONFIG_HOME=str(work / "xdg"))
        source.mkdir()
        run(source, "git", "init", "-q", "-b", "main")
        listed = run(HARNESS, "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
        for name in filter(None, listed.split("\0")):
            if (HARNESS / name).is_file():
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(HARNESS / name), str(source / name))
        run(source, "git", "add", "-A")
        run(source, "git", "commit", "-qm", "release")
        run(source, "git", "tag", "v" + VERSION)
        pinned = run(source, "git", "rev-parse", "HEAD").stdout.strip()
        project = Project(work / "project", lambda p: p.run("python3", "-B", LAUNCHER, "init", "--thin", "--name",
                                                             "demo"), **thin)
        project.write("docs/guide.md", "# Guide\n")
        tip = project.commit("docs: a guide")

        made = self.ci_statement(project, tip, project.adopted, source=source)

        self.assertEqual(made["predicate"]["verifier"]["baseLock"], {"mode": "thin", "version": VERSION,
                                                                     "commit": pinned})
        self.assertEqual(made["predicate"]["verifier"]["engineSha256"], sha256(ENGINE.read_bytes()))
        self.assertEqual(made["predicate"]["tasks"], [])

    def jobs(self):
        """The workflow's jobs, by name, as text."""
        parts = re.split(r"\n(?=  [a-z-]+:\n)", WORKFLOW.read_text().split("\njobs:\n", 1)[1])
        return {part.split(":", 1)[0].strip(): part for part in parts}

    def test_the_pull_request_run_has_no_secret_no_environment_and_no_signing(self):
        verify = self.jobs()["verify"]

        self.assertIn("if: github.event_name == 'pull_request'\n", verify)
        for word in ("secrets.", "environment:", "cosign", "HARNESS_ATTEST", "upload-artifact", "attest"):
            self.assertNotIn(word, verify)

    def test_the_signing_job_runs_only_for_a_push_to_the_default_branch_in_its_protected_environment(self):
        workflow, attest = WORKFLOW.read_text(), self.jobs()["attest"]

        self.assertIn("\non:\n  pull_request:\n", workflow)
        self.assertIn("\n  push:\n    branches: [main]\n", workflow)
        self.assertIn("if: github.event_name == 'push'\n", attest)
        self.assertIn("environment: harness-attest\n", attest)
        self.assertIn("\npermissions:\n  contents: read\n", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("HARNESS_ATTEST_SIGN: ${{ secrets.HARNESS_ATTEST_KEY != '' }}\n", attest)
        for word in ("continue-on-error", "always()", "failure()", "cancelled()", "needs:"):
            self.assertNotIn(word, workflow)

    def test_every_attestation_step_is_opt_in_and_the_statement_is_written_for_the_pushed_range_only(self):
        attest = self.jobs()["attest"]
        steps = attest.split("\n      - name: ")[1:]

        self.assertEqual([s.splitlines()[0] for s in steps], [
            "Take the verifier from the pushed commit", "Write the verdict attestation",
            "Sign the verdict attestation", "Upload the verdict attestation"])
        for step in steps:
            self.assertIn("if: env.HARNESS_ATTEST_SIGN == 'true'\n", step)
        self.assertIn('--range "$BEFORE..HEAD"', steps[1])
        self.assertNotIn("ALLOW", steps[1])

    def test_secrets_and_untrusted_event_data_reach_no_run_block(self):
        for job in self.jobs().values():
            for run in re.findall(r"^        run: \|\n((?:(?: {10}.*)?\n)*)", job, re.M):
                self.assertNotIn("${{", run)
                self.assertNotIn("secrets.", run)

    def test_both_jobs_take_the_engine_the_same_way(self):
        self.assertEqual(step_script(TAKE_BASE), step_script(TAKE_PUSHED))


if given is not None:
    class StatementProperties(FinishedTask):
        @settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(place=st.text(st.sampled_from("abcXYZ09 -_.ñé"), min_size=1, max_size=12),
               zone=st.sampled_from(("UTC", "Asia/Kathmandu", "America/St_Johns", "Pacific/Kiritimati")),
               locale=st.sampled_from(("C", "en_US.UTF-8", "de_DE.UTF-8")))
        def test_where_when_and_in_which_locale_it_is_made_change_no_byte(self, place, zone, locale):
            clone = Path(tempfile.mkdtemp(prefix=place, dir=str(self.work))) / "clone"
            run(self.work, "git", "clone", "-q", self.project.root, clone)

            again = run(clone, "python3", "-B", clone / "scripts/harness/lib/harness.py", "attest", "--range",
                        self.project.adopted + "..HEAD", TZ=zone, LC_ALL=locale, LANG=locale)

            self.assertEqual(again.stdout, self.output)

        @settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(name=st.from_regex(r"(backbone/|src/|tests/|\.github/|)[a-z][a-z0-9_-]{0,8}\.(txt|py|md|json)",
                                  fullmatch=True))
        def test_any_file_outside_the_commit_stops_it(self, name):
            self.project.write(name, "not committed\n")
            try:
                attest = self.project.attest(self.project.adopted)
            finally:
                self.project.git("checkout", "-q", "--", ".")
                self.project.git("clean", "-fdq")

            self.assertEqual((attest.returncode, attest.stdout), (1, ""))
            self.assertIn(name, attest.stderr)
else:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")


if __name__ == "__main__":
    unittest.main()
