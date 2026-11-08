"""The deliverer's command gate, checked through the pre-tool-use hook as the deliverer (ADR-002: it never merges, and
it sets only the triage labels the receipts suggest).

The deliverer runs only the gh commands delivery needs; the rest of what gh can do (repository settings, workflows,
secrets, issues, releases) is the user's call. However the shell runs a gh command, the decision is the one for the
command written out, and a command whose arguments the harness can't read is refused, as is a shell alias, which can
run gh under another name. The deliverer's gh api calls only read: GraphQL and REST writes can label, merge or enable
auto-merge. A PR keeps one risk label, which only goes up, also across the gh calls of one command, and no label
someone else set is removed or rewritten. The property checks need hypothesis (pip install -r
tests/requirements.txt); the tables run without it.
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
                  "builtin eval {q}", "noglob {c}", "nocorrect {c}",
                  # A quote inside "$(...)" belongs to the substitution, not to the string around it.
                  'echo "$(printf \'"\')"; {c}; echo "$(printf \'"\')"', 'x="$(echo "$(printf \'"\')"; {c})"')
# Ways of running it that add arguments or commands the harness can't read.
UNREADABLE = ("echo 7 | xargs {c}", "echo 7 | timeout 60 xargs {c}", "parallel {c} ::: 1",
              "find . -name x -exec {c} ';'", "echo {q} | bash", "echo {q} | env bash", "source <(echo {q})",
              ". /dev/stdin <<< {q}", "source ./deliver.sh")
# The gh commands delivery needs, as the deliverer's instructions use them, and gh's own aliases for them.
DELIVERY_GH = ("gh pr create --base main --title t --body b", "gh pr new --title t --body b", "gh pr edit 7 --body b",
               "gh pr view --json labels", "gh pr checks --watch --fail-fast", "gh pr list --head feat/x", "gh pr ls",
               "gh pr comment 7 --body b", "gh run view 123 --log-failed", "gh run list --branch feat/x", "gh run ls",
               "gh run watch 123", "gh label list --search risk: --json name", "gh label ls",
               "gh label create risk:low --color 0E8A16", "gh repo view --json defaultBranchRef",
               "gh api repos/o/r/pulls/7")
# The rest of what gh can do: repository settings (auto-merge, the default branch), workflows, secrets, variables,
# issues, releases, rulesets, re-runs, labels other than the triage ones, aliases and extensions.
OTHER_GH = ("gh repo edit --enable-auto-merge", "gh repo edit --default-branch x", "gh workflow run deploy.yml",
            "gh secret set TOKEN --body x", "gh variable set X --body y", "gh issue close 7",
            "gh issue edit 7 --add-label risk:low", "gh pr reopen 7", "gh pr update-branch 7", "gh pr -R o/r reopen 7",
            "gh release create v1", "gh ruleset list", "gh ruleset view 1", "gh run rerun 123", "gh run download 123",
            "gh label edit risk:low --color 000000", "gh label delete risk:low --yes", "gh label clone o/r",
            "gh alias set lbl 'pr edit --add-label automerge'", "gh lbl 7", "gh extension install o/gh-x",
            "gh repo delete o/r --yes")
# An alias defined on one line runs on the next when the shell expands aliases, as Claude Code's shell snapshot often
# makes it do; so the deliverer defines none, however the shell reads the definition.
ALIAS_DEFINITIONS = ("alias g=gh", "alias g='gh pr'", "alias ll='ls -l'", "alias -g X='pr merge'",
                     "command alias g=gh", "builtin alias g=gh", "eval 'alias g=gh'", "bash -c 'alias g=gh'",
                     "true && alias g=gh", "BASH_ALIASES[g]=gh", "aliases[g]=gh")
# --force rewrites the color and description of a label that already exists, which someone else may have defined.
FORCED_LABELS = ("gh label create risk:low --force", "gh label create risk:low -f",
                 "gh label create risk:low -fc 0E8A16", "gh label create risk:low --force=true",
                 "gh label create risk:low --color 0E8A16 $MORE")
# Each gh call is checked against the PR's labels as GitHub has them before the command runs, so two calls in one
# command could each add a different risk label.
TWO_RISK_LABELS = ("gh pr edit 7 --add-label risk:low; gh pr edit 7 --add-label risk:high",
                   "gh pr edit 7 --add-label risk:low && gh pr edit --add-label risk:high",
                   "gh pr edit --add-label risk:high\ngh pr edit 7 --add-label risk:low",
                   "x=$(gh pr edit 7 --add-label risk:high); gh pr edit 7 --add-label risk:low",
                   "gh pr create --title t --body b --label risk:low && gh pr edit --add-label risk:elevated")
ONE_RISK_LABEL = ("gh pr edit 7 --add-label risk:low; gh pr edit 7 --add-label risk:low,class:docs",
                  "gh pr edit 7 --add-label class:docs; gh pr edit 7 --add-label class:feature,risk:elevated")
# The deliverer's documented flow (.claude/agents/deliverer.md), from the preflight to the CI watch.
DOCUMENTED_FLOW = ("git status --porcelain", "git symbolic-ref refs/remotes/origin/HEAD",
                   "gh repo view --json defaultBranchRef", "git fetch origin", "git push -u origin HEAD",
                   "gh pr view --json number,url,labels", "gh label list --search risk:elevated --json name",
                   'gh label create risk:elevated --color FBCA04 --description "Agentic harness triage hint: '
                   'advisory, never a merge approval"',
                   "gh pr create --base main --title 'feat(x): y' --body \"$(cat <<'EOF'\nWhat the branch does.\n\n"
                   "Follow-ups:\n- none\nEOF\n)\" --label risk:elevated,class:feature",
                   "gh pr edit --body \"$(cat <<'EOF'\nWhat the branch does.\nEOF\n)\" --add-label "
                   "risk:elevated,class:feature",
                   "gh pr checks --watch --fail-fast", "timeout 1800 gh pr checks --watch --fail-fast",
                   "gh run view 123 --log-failed")
# A stand-in for GitHub, the one service these checks can't run: it answers the harness's own read of a PR's labels
# with the labels a test put on the PR, and fails any other call.
FAKE_GH = """#!/bin/sh
case "$*" in
  "pr view"*"--json labels"*) cat "$FAKE_GH_LABELS" ;;
  *) echo "fake gh: no answer for: gh $*" >&2; exit 1 ;;
esac
"""


def keeps_one_risk_label(names):
    """Whether a label command with these labels leaves a PR without labels triage-only, with one risk label."""
    return set(names) <= set(TRIAGE_LABELS) and len(set(names) & set(RISK_LABELS)) <= 1


class GateProject(unittest.TestCase):
    """An installed project on a feature branch, and a gh on PATH whose answers about the PR's labels the test sets."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="deliverer gate ")
        base = Path(cls.temp.name)
        (base / "home").mkdir()
        cls.env = dict(os.environ, HOME=str(base / "home"), GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test",
                       GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                       GIT_COMMITTER_EMAIL="test@example.com")
        cls.project = base / "project"
        cls.project.mkdir()
        for command in (["git", "init", "-q", "-b", "main", str(cls.project)],
                        [str(ROOT / "bootstrap.sh"), str(cls.project)],
                        ["git", "-C", str(cls.project), "add", "-A"],
                        ["git", "-C", str(cls.project), "commit", "-qm", "chore: adopt agentic harness"],
                        ["git", "-C", str(cls.project), "checkout", "-q", "-b", "feat/x"]):
            subprocess.run(command, check=True, capture_output=True, env=dict(cls.env, HARNESS_VERIFY="off"))
        cls.bin = base / "bin"
        cls.bin.mkdir()
        (cls.bin / "gh").write_text(FAKE_GH)
        (cls.bin / "gh").chmod(0o755)
        cls.labels_file = base / "labels.json"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def pr_has(self, *names):
        self.labels_file.write_text(json.dumps({"labels": [{"name": name} for name in names]}))

    def decision(self, command, agent="deliverer"):
        """(exit code, message) of the pre-tool-use hook for agent running command with Bash."""
        hook_input = {"session_id": "s", "agent_id": "a1", "agent_type": agent, "tool_name": "Bash",
                      "tool_input": {"command": command}}
        env = dict(self.env, CLAUDE_PROJECT_DIR=str(self.project), FAKE_GH_LABELS=str(self.labels_file),
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

    def test_the_deliverer_runs_only_the_gh_commands_delivery_needs(self):
        self.pr_has()
        for command in DELIVERY_GH + OTHER_GH:
            for carrier in ("{c}", "bash -c {q}", "x=$({c})"):
                with self.subTest(command=command, carrier=carrier):
                    code, message = self.decision(carrier.format(c=command, q=shlex.quote(command)))

                    self.assertEqual(code, 0 if command in DELIVERY_GH else 2, message)

    def test_the_rest_of_gh_is_the_users_call(self):
        for command in OTHER_GH:
            with self.subTest(command=command):
                code, message = self.decision(command)

                self.assertIn("the user's call", message)

    def test_the_deliverer_defines_no_shell_alias(self):
        for definition in ALIAS_DEFINITIONS:
            for then in ("g pr merge 7", "g pr view", "echo done"):
                with self.subTest(definition=definition, then=then):
                    code, message = self.decision(definition + "\n" + then)

                    self.assertEqual(code, 2, message)
                    self.assertIn("alias", message)

    def test_an_alias_in_text_defines_nothing(self):
        self.pr_has()
        for command in ('gh pr create --title "feat: alias support" --body b',
                        "gh pr edit 7 --body \"$(cat <<'EOF'\nalias g=gh\nEOF\n)\"",
                        "git log --grep alias", "grep -rn 'alias g=' docs"):
            with self.subTest(command=command):
                code, message = self.decision(command)

                self.assertEqual(code, 0, message)

    def test_the_deliverer_creates_a_missing_triage_label_without_force(self):
        for command in FORCED_LABELS:
            with self.subTest(command=command):
                code, message = self.decision(command)

                self.assertEqual(code, 2, message)

    def test_one_command_adds_one_risk_label(self):
        self.pr_has()
        for command in TWO_RISK_LABELS + ONE_RISK_LABEL:
            with self.subTest(command=command):
                code, message = self.decision(command)

                self.assertEqual(code, 2 if command in TWO_RISK_LABELS else 0, message)

    def test_the_documented_delivery_flow_runs(self):
        self.pr_has()
        for command in DOCUMENTED_FLOW:
            with self.subTest(command=command):
                code, message = self.decision(command)

                self.assertEqual(code, 0, message)


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
                       "gh pr edit https://github.com/o/r/pull/7 --add-label {}")
    API_ENDPOINTS = ("repos/o/r/pulls/7", "repos/o/r/issues/7/labels", "repos/o/r/merges",
                     "repos/o/r/git/refs/heads/main", "graphql", "/graphql", "https://api.github.com/graphql")
    API_METHOD_FORMS = ("-X {}", "--method {}", "--method={}", "-X{}", "-iX {}")
    API_BODIES = ("", "-f a=b", "-F n=1", "--raw-field a=b", "--field a=@body.json", "--input body.json",
                  "--input -")
    FORCE_FORMS = ("", " --force", " -f", " -fc FBCA04", " --force=true")
    CALL_SEPARATORS = ("; ", " && ", " || ", "\n", " & ")

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

        @settings(max_examples=30, deadline=None)
        @given(agent=deliverers, name=labels, force=st.sampled_from(FORCE_FORMS))
        def test_the_deliverer_creates_only_triage_labels_and_never_forces(self, agent, name, force):
            code, message = self.decision("gh label create %s --color FBCA04%s" % (shlex.quote(name), force), agent)

            self.assertEqual(code, 0 if name in TRIAGE_LABELS and not force else 2, message)

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

        @settings(max_examples=40, deadline=None)
        @given(agent=deliverers, added=st.lists(st.sampled_from(RISK_LABELS), min_size=2, max_size=3),
               forms=st.lists(st.sampled_from(ADD_LABEL_FORMS), min_size=3, max_size=3),
               separator=st.sampled_from(CALL_SEPARATORS))
        def test_a_command_adds_one_risk_label_whatever_its_calls(self, agent, added, forms, separator):
            self.pr_has()
            command = separator.join(form.format(name) for form, name in zip(forms, added))

            code, message = self.decision(command, agent)

            self.assertEqual(code, 0 if len(set(added)) == 1 else 2, message)

        @settings(max_examples=40, deadline=None)
        @given(agent=deliverers, command=st.sampled_from(DELIVERY_GH + OTHER_GH),
               carrier=st.sampled_from(SAME_AS_DIRECT))
        def test_the_deliverer_runs_only_delivery_gh_commands_however_the_shell_runs_them(self, agent, command,
                                                                                         carrier):
            self.pr_has()

            code, message = self.decision(carrier.format(c=command, q=shlex.quote(command)), agent)

            self.assertEqual(code, 0 if command in DELIVERY_GH else 2, message)

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
