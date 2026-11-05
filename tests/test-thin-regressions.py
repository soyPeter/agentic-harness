import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest


HARNESS = Path(__file__).resolve().parents[1]
ENGINE = HARNESS / "payload/owned/scripts/harness/lib/harness.py"
CORE_SKILL = HARNESS / "payload/owned/.claude/skills/code-quality/SKILL.md"


class ThinRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness review ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name).resolve()
        self.project = self.work / "project"
        self.project.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com",
                        HARNESS_VERIFY="off", HARNESS_AUTONOMY="supervised",
                        HARNESS_SKILL_GATE="on", PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("HARNESS_ROOT", None)
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        self.run_command("git", "init", "-q", "-b", "main")

    def run_command(self, *args, env=None, input=None, check=True):
        result = subprocess.run(args, cwd=self.project, env=env or self.env, input=input,
                                capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self, thin=False):
        self.run_command(str(HARNESS / "bootstrap.sh"), str(self.project))
        if thin:
            shutil.rmtree(self.project / "scripts/harness")
            shutil.rmtree(self.project / ".claude/skills")

    def hook(self, session, tool, tool_input, event="post-tool-use", cwd=None):
        data = {"session_id": session, "agent_id": session,
                "tool_name": tool, "tool_input": tool_input}
        if cwd:
            data["cwd"] = str(cwd)
        return self.run_command("python3", "-B", str(ENGINE), "hook", event,
                                input=json.dumps(data), check=False)

    def assert_gate(self, session, blocked):
        result = self.hook(session, "Write", {"file_path": str(self.project / "example.py"),
                                               "content": "x = 1\n"}, "pre-tool-use")
        self.assertEqual(result.returncode, 2 if blocked else 0, result.stdout + result.stderr)
        if blocked:
            self.assertIn("code-quality", result.stderr)

    def test_project_override_requires_the_selected_skill(self):
        self.install(thin=True)
        override = self.project / ".claude/skills/code-quality/SKILL.md"
        override.parent.mkdir(parents=True)
        override.write_text("# Project-specific coding rules\n")
        cases = [
            ("engine-read", "Read", {"file_path": str(CORE_SKILL)}, True),
            ("engine-cat", "Bash", {"command": "cat " + shlex.quote(str(CORE_SKILL))}, True),
            ("engine-invoke", "Skill", {"skill": "agentic-harness:code-quality"}, True),
            ("other-plugin", "Skill", {"skill": "other-plugin:code-quality"}, True),
            ("project-read", "Read", {"file_path": str(override)}, False),
            ("project-cat", "Bash", {"command": "cat " + shlex.quote(str(override)) + " | head -50"}, False),
            ("project-invoke", "Skill", {"skill": "code-quality"}, False),
        ]
        for session, tool, tool_input, blocked in cases:
            with self.subTest(session=session):
                self.assert_gate(session, True)
                result = self.hook(session, tool, tool_input)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_gate(session, blocked)

    def test_core_skill_loads_without_an_override(self):
        self.install(thin=True)
        for session, tool, tool_input in [
            ("read", "Read", {"file_path": str(CORE_SKILL)}),
            ("shell", "Bash", {"command": "cat " + shlex.quote(str(CORE_SKILL)) + "|head -50"}),
            ("invoke", "Skill", {"skill": "agentic-harness:code-quality"}),
        ]:
            with self.subTest(session=session):
                self.assert_gate(session, True)
                self.assertEqual(self.hook(session, tool, tool_input).returncode, 0)
                self.assert_gate(session, False)

    def test_shell_reads_resolve_aliases_and_working_directory(self):
        self.install(thin=True)
        override = self.project / ".claude/skills/code-quality/SKILL.md"
        override.parent.mkdir(parents=True)
        override.write_text("# Project-specific coding rules\n")
        (self.project / ".agents").mkdir()
        (self.project / ".agents/skills").symlink_to("../.claude/skills", target_is_directory=True)
        nested = self.project / "nested"
        nested.mkdir()
        for session, command, cwd in [
            ("alias", "cat .agents/skills/code-quality/SKILL.md", self.project),
            ("nested", "sed -n '1,50p' ../.claude/skills/code-quality/SKILL.md", nested),
            ("missing", "cat missing/.claude/skills/code-quality/SKILL.md", self.project),
        ]:
            with self.subTest(session=session):
                self.assertEqual(self.hook(session, "Bash", {"command": command}, cwd=cwd).returncode, 0)
                self.assert_gate(session, session == "missing")


if __name__ == "__main__":
    unittest.main()
