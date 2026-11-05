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


    def test_rule_reports_distinguish_core_and_project_in_both_layouts(self):
        self.install()
        with (self.project / "backbone/guardrails.conf").open("a") as handle:
            handle.write("\nwarn | \\.review$ | NEVER_MATCH | Project review sentinel.\n")
        for engine in (self.project / "scripts/harness/lib/harness.py", ENGINE):
            with self.subTest(engine=engine):
                result = self.run_command("python3", "-B", str(engine), "report", "--json")
                rules = json.loads(result.stdout)["rules"]
                self.assertEqual(rules["project_never_fired"], ["Project review sentinel."])
                self.assertGreater(len(rules["never_fired"]), 1)
                report = self.run_command("python3", "-B", str(engine), "report", "--rules").stdout
                self.assertIn("Private keys must never be written into the repository.  (core)", report)
                self.assertNotIn("Project review sentinel.  (core)", report)

    def extraction_script(self):
        workflow = (HARNESS / "payload/owned/.github/workflows/harness-verify.yml").read_text()
        step = workflow.split("      - name: Take the verifier from the base branch\n", 1)[1]
        return textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0])

    def extract(self, check=True):
        runner = self.work / "runner temp"
        runner.mkdir()
        env = dict(self.env, BASE="review-base", RUNNER_TEMP=str(runner))
        result = self.run_command("bash", "-e", "-o", "pipefail", "-c", self.extraction_script(),
                                  env=env, check=check)
        return runner / "trusted", result

    def commit_base(self):
        self.run_command("git", "add", "-A")
        self.run_command("git", "commit", "--allow-empty", "-qm", "chore: review base")
        self.run_command("git", "update-ref", "refs/remotes/origin/review-base", "HEAD")

    def engine_assets(self):
        return ["scripts/harness/lib/harness.py", "scripts/harness/guardrails.core.conf",
                "scripts/harness/routing.core.conf", "scripts/harness/decisions.json"]

    def test_ci_extracts_configuration_from_base_not_pr(self):
        self.install()
        self.commit_base()
        expected = {name: (self.project / name).read_bytes() for name in self.engine_assets()}
        for name in self.engine_assets():
            (self.project / name).write_text("PR replacement\n")
        trusted, result = self.extract()
        self.assertIn("Using the harness from origin/review-base.", result.stdout)
        for name, content in expected.items():
            self.assertEqual((trusted / name).read_bytes(), content, name)
            self.assertEqual((self.project / name).read_text(), "PR replacement\n")
        probe = '''
import json, runpy, sys
h = runpy.run_path(sys.argv[1])
rules, errors = h['load_rules']()
routes, route_errors = h['load_routes']()
assert rules and not errors and routes and not route_errors
assert h['decisions'].load_definitions(str(h['DECISIONS_FILE']))['decisions']
'''
        self.run_command("python3", "-B", "-c", probe, str(trusted / "scripts/harness/lib/harness.py"),
                         env=dict(self.env, HARNESS_ROOT=str(self.project)))

    def test_ci_bootstrap_fallback_includes_configuration(self):
        self.commit_base()
        self.install()
        trusted, result = self.extract()
        self.assertIn("has no harness yet", result.stdout)
        for name in self.engine_assets():
            self.assertEqual((trusted / name).read_bytes(), (self.project / name).read_bytes(), name)

    def test_ci_does_not_replace_an_incomplete_base_engine_with_pr_code(self):
        self.install()
        decisions = self.project / "scripts/harness/decisions.json"
        contents = decisions.read_bytes()
        decisions.unlink()
        self.commit_base()
        decisions.write_bytes(contents)
        trusted, result = self.extract(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("using the pull request's copy", result.stdout)
        self.assertFalse((trusted / "scripts/harness/decisions.json").exists())


if __name__ == "__main__":
    unittest.main()
