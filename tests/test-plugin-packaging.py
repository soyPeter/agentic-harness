import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PluginPackaging(unittest.TestCase):
    def test_manifests_resolve_components_from_repository_root(self):
        claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
        marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual(claude["name"], codex["name"])
        self.assertEqual(claude["version"], codex["version"])
        self.assertEqual(claude["version"], version)
        self.assertEqual(marketplace["plugins"], [{"name": claude["name"], "source": "./"}])
        for manifest in (claude, codex):
            for skill_dir in manifest["skills"]:
                self.assertTrue(list((ROOT / skill_dir).glob("*/SKILL.md")), skill_dir)
            self.assertTrue((ROOT / manifest["hooks"]).is_file())
        self.assertTrue((ROOT / "plugin/skills/init/SKILL.md").is_file())
        for agent in claude["agents"]:
            self.assertTrue((ROOT / agent).is_file(), agent)
        self.assertNotIn("agents", codex)

    def test_hooks_use_plugin_launcher_for_each_provider(self):
        for name, variable in (("claude", "CLAUDE_PLUGIN_ROOT"), ("codex", "PLUGIN_ROOT")):
            with self.subTest(provider=name):
                hooks = json.loads((ROOT / "plugin" / (name + "-hooks.json")).read_text())["hooks"]
                for groups in hooks.values():
                    for group in groups:
                        for hook in group["hooks"]:
                            self.assertIn("${%s}/plugin/launcher.py" % variable, hook["command"])
                self.assertIn("SessionStart", hooks)
                self.assertIn("SubagentStart", hooks)
                self.assertIn("PreToolUse", hooks)
                self.assertIn("PostToolUse", hooks)
                self.assertIn("Stop", hooks)

    def test_opencode_package_reaches_launcher_in_a_thin_project(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            lock = project / "backbone/.harness-lock.json"
            lock.parent.mkdir()
            lock.write_text(json.dumps({"mode": "thin", "version": "9.9.9", "commit": "0" * 40}))
            script = """
import plugin from './plugin/opencode.js';
let before;
await plugin.setup({ tool: { hook: async (name, callback) => {
  if (name === 'execute.before') before = callback;
  return { dispose() {} };
} } });
try {
  await before({ cwd: process.env.TEST_PROJECT, tool: 'bash', input: { command: 'git status' } });
  process.exitCode = 1;
} catch (error) {
  if (!String(error.message).includes("engine this project pins can't be run")) process.exitCode = 2;
}
"""
            env = dict(os.environ, HARNESS_ENGINES=str(Path(temp) / "engines"),
                       HARNESS_ENGINE_SOURCE=str(Path(temp) / "unavailable"))
            result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                                    env=dict(env, TEST_PROJECT=str(project)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plugin_agent_guard_fails_closed_without_its_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            lock = project / "backbone/.harness-lock.json"
            lock.parent.mkdir()
            lock.write_text(json.dumps({"mode": "thin", "version": "9.9.9", "commit": "0" * 40}))
            agent = (ROOT / "payload/owned/.claude/agents/implementer.md").read_text()
            command = next(line.strip().removeprefix("command: '").removesuffix("'") for line in agent.splitlines()
                           if "command: '" in line)
            env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PROJECT_DIR=str(project),
                       HARNESS_ENGINES=str(Path(temp) / "engines"),
                       HARNESS_ENGINE_SOURCE=str(Path(temp) / "unavailable"))
            result = subprocess.run(["sh", "-c", command], cwd=project, env=env,
                                    input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "example.py"}}),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("engine this project pins can't be run", result.stderr)

    def test_agent_hook_keeps_the_full_install_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run([str(ROOT / "bootstrap.sh"), str(project)], check=True, capture_output=True, text=True)
            agent = (ROOT / "payload/owned/.claude/agents/implementer.md").read_text()
            command = next(line.strip().removeprefix("command: '").removesuffix("'") for line in agent.splitlines()
                           if "command: '" in line)
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
            env.pop("CLAUDE_PLUGIN_ROOT", None)
            result = subprocess.run(["sh", "-c", command], cwd=project, env=env,
                                    input=json.dumps({"tool_name": "Write", "tool_input": {
                                        "file_path": str(project / "backbone/1-PRD.md"), "content": "x"}}),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
