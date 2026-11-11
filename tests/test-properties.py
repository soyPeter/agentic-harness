"""Property-based checks of the hook entry point (needs hypothesis: pip install -r tests/requirements.txt).

An agent loaded from the plugin is named <plugin>:<role>. The gates must treat it exactly as the project's own
agent of that role, whatever it writes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hypothesis_profiles import examples

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

    def write_decision(self, agent_type, path):
        """(exit code, message) of the pre-tool-use hook for agent_type writing path."""
        hook_input = {"session_id": "s", "agent_id": "a1", "agent_type": agent_type, "tool_name": "Write",
                      "tool_input": {"file_path": str(self.project / path), "content": "x\n"}}
        result = subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "hook",
                                 "pre-tool-use"], cwd=self.project, input=json.dumps(hook_input), capture_output=True,
                                text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project)))
        return result.returncode, result.stderr

    @settings(max_examples=examples(60), deadline=None)
    @given(role=st.sampled_from(ROLES), plugin=plugin_names, folder=st.sampled_from(FOLDERS), name=file_names)
    def test_a_plugin_agent_gets_the_decision_of_its_role(self, role, plugin, folder, name):
        self.assertEqual(self.write_decision(plugin + ":" + role, folder + name),
                         self.write_decision(role, folder + name))

    @settings(max_examples=examples(30), deadline=None)
    @given(role=st.sampled_from(ROLES), plugin=plugin_names, name=file_names)
    def test_no_agent_writes_a_verdict(self, role, plugin, name):
        code, message = self.write_decision(plugin + ":" + role, "backbone/.verdicts/" + name)

        self.assertEqual(code, 2, message)


if __name__ == "__main__":
    unittest.main()
