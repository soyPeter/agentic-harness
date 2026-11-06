"""Property-based checks of the hook entry point (needs hypothesis: pip install -r tests/requirements.txt).

An agent loaded from the plugin is named <plugin>:<role>. The gates must treat it exactly as the project's own
agent of that role, whatever it writes.

The deliverer labels its PR with the triage labels the receipts suggest (ADR-002) and nothing else: it never adds
another label, never lowers a risk label and never removes a label someone else set.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    print("skipped: hypothesis is not installed (pip install -r tests/requirements.txt)")
    sys.exit(0)


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("analyst", "architect", "griller", "tester", "implementer", "judge", "debugger", "scribe", "reviewer",
         "deliverer")
FOLDERS = ("", "src/", "tests/", "backbone/", "backbone/specs/", "backbone/adr/", "backbone/.verdicts/", ".claude/",
           ".claude/skills/x/", "scripts/harness/", "docs/")
file_names = st.from_regex(r"[A-Za-z0-9_-]{1,12}\.(py|md|ts|conf)", fullmatch=True)
plugin_names = st.from_regex(r"[a-z][a-z0-9-]{0,15}", fullmatch=True)
RISK_LABELS = ("risk:low", "risk:elevated", "risk:high")
TRIAGE_LABELS = RISK_LABELS + ("class:docs", "class:refactor", "class:feature", "class:schema")
other_labels = (st.sampled_from(("harness-change-approved", "automerge", "do-not-merge", "risk:none", "class:chore",
                                 "Risk:High", "bug"))
                | st.from_regex(r"[a-z][a-z0-9:-]{0,15}", fullmatch=True).filter(lambda n: n not in TRIAGE_LABELS))
labels = st.sampled_from(TRIAGE_LABELS) | other_labels
deliverers = st.sampled_from(("deliverer", "agentic-harness:deliverer"))
ADD_LABEL_FORMS = ("gh pr create --base main --title t --body b --label {}",
                   "gh pr create -l {} --title t --body b",
                   "gh pr create --title t --body b -l{}",
                   "gh pr create --title t --body b -dl {}",
                   "gh pr new --label={} --title t --body b",
                   "gh pr edit 7 --add-label {}",
                   "gh pr edit --add-label={} --body b",
                   "gh issue edit 7 --add-label {}")


class HookProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="hook properties ")
        cls.project = Path(cls.temp.name) / "project"
        cls.project.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.project)], check=True)
        subprocess.run([str(ROOT / "bootstrap.sh"), str(cls.project)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def decision(self, agent_type, tool, tool_input):
        """(exit code, message) of the pre-tool-use hook for agent_type calling tool."""
        hook_input = {"session_id": "s", "agent_id": "a1", "agent_type": agent_type, "tool_name": tool,
                      "tool_input": tool_input}
        result = subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "hook",
                                 "pre-tool-use"], cwd=self.project, input=json.dumps(hook_input), capture_output=True,
                                text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project)))
        return result.returncode, result.stderr

    def write_decision(self, agent_type, path):
        return self.decision(agent_type, "Write", {"file_path": str(self.project / path), "content": "x\n"})

    def command_decision(self, agent_type, command):
        return self.decision(agent_type, "Bash", {"command": command})

    @settings(max_examples=40, deadline=None)
    @given(agent=deliverers, names=st.lists(labels, min_size=1, max_size=3), form=st.sampled_from(ADD_LABEL_FORMS))
    def test_the_deliverer_adds_only_triage_labels(self, agent, names, form):
        code, message = self.command_decision(agent, form.format(shlex.quote(",".join(names))))

        self.assertEqual(code, 0 if set(names) <= set(TRIAGE_LABELS) else 2, message)

    @settings(max_examples=20, deadline=None)
    @given(agent=deliverers, name=labels)
    def test_the_deliverer_creates_only_triage_labels(self, agent, name):
        code, message = self.command_decision(agent, "gh label create %s --color FBCA04" % shlex.quote(name))

        self.assertEqual(code, 0 if name in TRIAGE_LABELS else 2, message)

    @settings(max_examples=40, deadline=None)
    @given(agent=deliverers, added=st.none() | st.sampled_from(RISK_LABELS),
           removed=st.sampled_from(RISK_LABELS) | labels)
    def test_the_deliverer_removes_only_a_lower_risk_label_it_replaces(self, agent, added, removed):
        command = "gh pr edit 7%s --remove-label %s" % (" --add-label " + added if added else "", shlex.quote(removed))
        replaces = (added is not None and removed in RISK_LABELS
                    and RISK_LABELS.index(removed) < RISK_LABELS.index(added))

        code, message = self.command_decision(agent, command)

        self.assertEqual(code, 0 if replaces else 2, message)

    @settings(max_examples=60, deadline=None)
    @given(role=st.sampled_from(ROLES), plugin=plugin_names, folder=st.sampled_from(FOLDERS), name=file_names)
    def test_a_plugin_agent_gets_the_decision_of_its_role(self, role, plugin, folder, name):
        self.assertEqual(self.write_decision(plugin + ":" + role, folder + name),
                         self.write_decision(role, folder + name))

    @settings(max_examples=30, deadline=None)
    @given(role=st.sampled_from(ROLES), plugin=plugin_names, name=file_names)
    def test_no_agent_writes_a_verdict(self, role, plugin, name):
        code, message = self.write_decision(plugin + ":" + role, "backbone/.verdicts/" + name)

        self.assertEqual(code, 2, message)


if __name__ == "__main__":
    unittest.main()
