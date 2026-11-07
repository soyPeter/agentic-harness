"""The deliverer's command gate, checked through the pre-tool-use hook as the deliverer (ADR-002: it never merges, and
it sets only the triage labels the receipts suggest).

However the shell runs a gh command, the decision is the one for the command written out, and a command whose
arguments the harness can't read is refused. The deliverer's gh api calls only read: GraphQL and REST writes can
label, merge or enable auto-merge. A PR keeps one risk label, which only goes up, and no label someone else set is
removed. The property checks need hypothesis (pip install -r tests/requirements.txt); the tables run without it.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None

ROOT = Path(__file__).resolve().parents[1]
RISK_LABELS = ("risk:low", "risk:elevated", "risk:high")
TRIAGE_LABELS = RISK_LABELS + ("class:docs", "class:refactor", "class:feature", "class:schema")
# Ways of running a command that come down to running it: {c} is the command, {q} the command quoted as one word.
SAME_AS_DIRECT = ("{c}", "x=$({c})", 'echo "$({c})"', 'echo "$(echo "$({c})")"', "echo `{c}`", "cat <({c})",
                  "bash -c {q}", "bash -lc {q}", "sh -e -c {q}", "bash -o pipefail -c {q}", "eval {q}",
                  "timeout 60 {c}", "env -i {c}", "nice -n 5 {c}", "! nohup {c}", "timeout 60 bash -c {q}",
                  "watch -n 5 {q}", "env -S {q}", "bash <<'EOF'\n{c}\nEOF", "bash <<< {q}",
                  "cat <<EOF\nit's $({c})\nEOF", "true && {c}", "{c} | cat", "( {c} )", "({c} )", "{{ {c}; }}",
                  "if FOO=1 {c}; then :; fi", "while false; do {c}; done", "case x in x) {c};; esac",
                  "f() {{ {c}; }}", "function f {{ {c}; }}", "2>/dev/null {c}", "> /dev/null {c}",
                  # A quote inside "$(...)" belongs to the substitution, not to the string around it.
                  'echo "$(printf \'"\')"; {c}; echo "$(printf \'"\')"', 'x="$(echo "$(printf \'"\')"; {c})"')
# Ways of running it that add arguments or commands the harness can't read.
UNREADABLE = ("echo 7 | xargs {c}", "echo 7 | timeout 60 xargs {c}", "parallel {c} ::: 1",
              "find . -name x -exec {c} ';'", "echo {q} | bash", "echo {q} | env bash")
# A stand-in for GitHub, the one service these checks can't run: it answers the harness's own read of a PR's labels
# with the labels a test put on the PR, and fails any other call.
FAKE_GH = """#!/bin/sh
case "$*" in
  "pr view"*"--json labels"*|"issue view"*"--json labels"*) cat "$FAKE_GH_LABELS" ;;
  *) echo "fake gh: no answer for: gh $*" >&2; exit 1 ;;
esac
"""


def keeps_one_risk_label(names):
    """Whether a label command with these labels leaves a PR without labels triage-only, with one risk label."""
    return set(names) <= set(TRIAGE_LABELS) and len(set(names) & set(RISK_LABELS)) <= 1


class GateProject(unittest.TestCase):
    """An installed project, and a gh on PATH whose answers about the PR's labels the test sets."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="deliverer gate ")
        cls.project = Path(cls.temp.name) / "project"
        cls.project.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.project)], check=True)
        subprocess.run([str(ROOT / "bootstrap.sh"), str(cls.project)], check=True, capture_output=True)
        cls.bin = Path(cls.temp.name) / "bin"
        cls.bin.mkdir()
        (cls.bin / "gh").write_text(FAKE_GH)
        (cls.bin / "gh").chmod(0o755)
        cls.labels_file = Path(cls.temp.name) / "labels.json"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def pr_has(self, *names):
        self.labels_file.write_text(json.dumps({"labels": [{"name": name} for name in names]}))

    def decision(self, command, agent="deliverer"):
        """(exit code, message) of the pre-tool-use hook for agent running command with Bash."""
        hook_input = {"session_id": "s", "agent_id": "a1", "agent_type": agent, "tool_name": "Bash",
                      "tool_input": {"command": command}}
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project), FAKE_GH_LABELS=str(self.labels_file),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        result = subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "hook",
                                 "pre-tool-use"], cwd=self.project, input=json.dumps(hook_input), capture_output=True,
                                text=True, env=env)
        return result.returncode, result.stderr


class DelivererGate(GateProject):
    def test_every_way_of_running_a_command_gets_the_decision_for_the_command_written_out(self):
        self.pr_has()
        for names in (["risk:low", "class:docs"], ["harness-change-approved"]):
            command = "gh pr edit 7 --add-label " + ",".join(names)
            for carrier in SAME_AS_DIRECT:
                with self.subTest(carrier=carrier, names=names):
                    code, message = self.decision(carrier.format(c=command, q=shlex.quote(command)))

                    self.assertEqual(code, 0 if keeps_one_risk_label(names) else 2, message)

    def test_quotes_inside_a_substitution_hide_no_arguments(self):
        self.pr_has()
        for names in (["risk:low", "class:docs"], ["harness-change-approved"]):
            with self.subTest(names=names):
                code, message = self.decision("gh pr edit 7 --title \"$(printf '\"')\" --add-label %s "
                                              "--body \"$(printf '\"')\"" % ",".join(names))

                self.assertEqual(code, 0 if keeps_one_risk_label(names) else 2, message)

    def test_a_command_the_harness_cant_read_is_refused(self):
        self.pr_has()
        command = "gh pr edit 7 --add-label class:docs"
        for carrier in UNREADABLE:
            with self.subTest(carrier=carrier):
                code, message = self.decision(carrier.format(c=command, q=shlex.quote(command)))

                self.assertEqual(code, 2, message)


if given is not None:
    other_labels = (st.sampled_from(("harness-change-approved", "automerge", "do-not-merge", "risk:none",
                                     "class:chore", "Risk:High", "bug"))
                    | st.from_regex(r"[a-z][a-z0-9:-]{0,15}", fullmatch=True).filter(lambda n: n not in TRIAGE_LABELS))
    labels = st.sampled_from(RISK_LABELS) | st.sampled_from(TRIAGE_LABELS) | other_labels
    deliverers = st.sampled_from(("deliverer", "agentic-harness:deliverer"))
    ADD_LABEL_FORMS = ("gh pr create --base main --title t --body b --label {}",
                       "gh pr create -l {} --title t --body b",
                       "gh pr create --title t --body b -l{}",
                       "gh pr create --title t --body b -l={}",
                       "gh pr create --title t --body b -dl {}",
                       "gh pr new --label={} --title t --body b",
                       "gh pr edit 7 --add-label {}",
                       "gh pr edit --add-label={} --body b",
                       "gh issue edit 7 --add-label {}")
    API_ENDPOINTS = ("repos/o/r/pulls/7", "repos/o/r/issues/7/labels", "repos/o/r/merges",
                     "repos/o/r/git/refs/heads/main", "graphql", "/graphql", "https://api.github.com/graphql")
    API_METHOD_FORMS = ("-X {}", "--method {}", "--method={}", "-X{}", "-iX {}")
    API_BODIES = ("", "-f a=b", "-F n=1", "--raw-field a=b", "--field a=@body.json", "--input body.json",
                  "--input -")

    class DelivererGateProperties(GateProject):
        @settings(max_examples=40, deadline=None)
        @given(agent=deliverers, names=st.lists(labels, min_size=1, max_size=3),
               form=st.sampled_from(ADD_LABEL_FORMS))
        def test_the_deliverer_adds_only_triage_labels_and_one_risk_label(self, agent, names, form):
            self.pr_has()

            code, message = self.decision(form.format(shlex.quote(",".join(names))), agent)

            self.assertEqual(code, 0 if keeps_one_risk_label(names) else 2, message)

        @settings(max_examples=60, deadline=None)
        @given(agent=deliverers, names=st.lists(labels, min_size=1, max_size=2),
               form=st.sampled_from(ADD_LABEL_FORMS), carrier=st.sampled_from(SAME_AS_DIRECT))
        def test_a_label_command_gets_the_same_decision_however_the_shell_runs_it(self, agent, names, form,
                                                                                   carrier):
            self.pr_has()
            command = form.format(shlex.quote(",".join(names)))

            code, message = self.decision(carrier.format(c=command, q=shlex.quote(command)), agent)

            self.assertEqual(code, 0 if keeps_one_risk_label(names) else 2, message)

        @settings(max_examples=20, deadline=None)
        @given(agent=deliverers, name=labels)
        def test_the_deliverer_creates_only_triage_labels(self, agent, name):
            code, message = self.decision("gh label create %s --color FBCA04" % shlex.quote(name), agent)

            self.assertEqual(code, 0 if name in TRIAGE_LABELS else 2, message)

        @settings(max_examples=60, deadline=None)
        @given(agent=deliverers, on_pr=st.lists(labels, max_size=3, unique=True),
               added=st.none() | st.sampled_from(RISK_LABELS), removed=st.lists(labels, max_size=2, unique=True))
        def test_a_pr_keeps_one_risk_label_that_only_goes_up(self, agent, on_pr, added, removed):
            self.pr_has(*on_pr)
            command = "gh pr edit 7 --body b" + (" --add-label " + added if added else "")
            command += "".join(" --remove-label " + shlex.quote(name) for name in removed)
            lower = set(RISK_LABELS[:RISK_LABELS.index(added)]) if added else set()
            risk_after = (set(on_pr) & set(RISK_LABELS) | {added}) - set(removed)
            keeps_one = set(removed) <= lower and (added is None or risk_after == {added})

            code, message = self.decision(command, agent)

            self.assertEqual(code, 0 if keeps_one else 2, message)

        @settings(max_examples=60, deadline=None)
        @given(agent=deliverers, endpoint=st.sampled_from(API_ENDPOINTS),
               method=st.none() | st.sampled_from(("GET", "get", "HEAD", "POST", "PUT", "PATCH", "DELETE")),
               method_form=st.sampled_from(API_METHOD_FORMS), body=st.sampled_from(API_BODIES),
               endpoint_first=st.booleans())
        def test_the_deliverers_gh_api_calls_only_read(self, agent, endpoint, method, method_form, body,
                                                       endpoint_first):
            flags = [method_form.format(method)] if method else []
            flags += [body] if body else []
            command = " ".join(["gh", "api"] + ([endpoint] + flags if endpoint_first else flags + [endpoint]))
            # gh api sends GET, or POST once it has parameters or a body, unless --method says otherwise.
            sent = (method or ("POST" if body else "GET")).upper()
            reads = sent in ("GET", "HEAD") and not endpoint.endswith("graphql")

            code, message = self.decision(command, agent)

            self.assertEqual(code, 0 if reads else 2, message)
else:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")


if __name__ == "__main__":
    unittest.main()
