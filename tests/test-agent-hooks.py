"""How the hooks treat each pipeline agent: a project agent through the hooks its file declares, and a plugin agent
(<plugin>:<role>) through the plugin's own hooks, because Claude Code ignores the ones a plugin agent declares."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "payload/owned/.claude/agents"


def agent_hook_commands(agent, event):
    """The commands agent's frontmatter declares for event (Stop, PreToolUse)."""
    front = (AGENTS / ("%s.md" % agent)).read_text().split("---\n")[1]
    commands, current = [], None
    for line in front.splitlines():
        heading = re.match(r"^  (\w+):$", line)
        if heading:
            current = heading.group(1)
        command = re.match(r"^\s+command: '(.*)'$", line)
        if command and current == event:
            commands.append(command.group(1))
    return commands


class AgentHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="agent hooks ")
        cls.project = Path(cls.temp.name) / "project"
        cls.project.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.project)], check=True)
        subprocess.run([str(ROOT / "bootstrap.sh"), str(cls.project)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_agent_hook(self, agent, event, hook_input):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project))
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        results = [subprocess.run(["sh", "-c", command], cwd=self.project, env=env, input=json.dumps(hook_input),
                                  capture_output=True, text=True)
                   for command in agent_hook_commands(agent, event)]
        self.assertTrue(results, "%s declares no %s hook" % (agent, event))
        return results[0]

    def run_harness_hook(self, event, hook_input):
        return subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "hook", event],
                              cwd=self.project, input=json.dumps(hook_input), capture_output=True, text=True,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project)))

    def test_a_verdict_agent_stopping_without_its_verdict_is_asked_for_it(self):
        for agent in ("griller", "judge"):
            with self.subTest(agent=agent):
                result = self.run_agent_hook(agent, "Stop", {"agent_type": agent, "last_assistant_message": "Done."})

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("End your final message with the verdict JSON", result.stderr)

    def test_a_scoped_agent_may_not_write_outside_its_role(self):
        for agent, path in (("analyst", "src/app.py"), ("architect", "src/app.py"),
                            ("implementer", "backbone/1-PRD.md"), ("scribe", "src/app.py")):
            with self.subTest(agent=agent):
                result = self.run_agent_hook(agent, "PreToolUse", {
                    "tool_name": "Write", "tool_input": {"file_path": str(self.project / path), "content": "x"}})

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("The %s agent may not edit %s" % (agent, path), result.stderr)

    def test_a_scoped_agent_may_write_inside_its_role(self):
        for agent, path in (("analyst", "backbone/specs/9.9.md"), ("architect", "backbone/adr/ADR-009-x.md"),
                            ("implementer", "src/app.py"), ("scribe", "backbone/6-MEMORY.md")):
            with self.subTest(agent=agent):
                result = self.run_agent_hook(agent, "PreToolUse", {
                    "tool_name": "Write", "tool_input": {"file_path": str(self.project / path), "content": "x"}})

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_plugin_agent_may_not_write_outside_its_role(self):
        for agent, path in (("analyst", "src/app.py"), ("implementer", "backbone/1-PRD.md"), ("scribe", "src/app.py")):
            with self.subTest(agent=agent):
                result = self.run_harness_hook("pre-tool-use", {
                    "session_id": "s", "agent_id": "a1", "agent_type": "agentic-harness:" + agent, "tool_name": "Write",
                    "tool_input": {"file_path": str(self.project / path), "content": "x"}})

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("The %s agent may not edit %s" % (agent, path), result.stderr)

    def test_the_plugin_deliverer_may_not_merge(self):
        result = self.run_harness_hook("pre-tool-use", {
            "session_id": "s", "agent_id": "a1", "agent_type": "agentic-harness:deliverer", "tool_name": "Bash",
            "tool_input": {"command": "gh pr merge 7 --squash"}})

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("merging is the user's", result.stderr)

    def test_a_plugin_verdict_agent_stopping_without_its_verdict_is_asked_for_it(self):
        # Claude Code names a plugin agent <plugin>:<role>; Codex sends the bare role.
        for agent in ("agentic-harness:griller", "agentic-harness:judge", "griller", "judge"):
            with self.subTest(agent=agent):
                result = self.run_harness_hook("subagent-stop", {"agent_type": agent, "last_assistant_message": "Done."})

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("End your final message with the verdict JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
