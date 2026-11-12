import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "payload/owned/scripts/harness/lib/harness.py"
LAUNCHER = ROOT / "plugin/launcher.py"


class ThinInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="thin install ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / "source"
        self.project = self.work / "project"
        self.source.mkdir()
        self.project.mkdir()
        self.env = dict(os.environ, HARNESS_ENGINE_SOURCE=str(self.source),
                        HARNESS_ENGINES=str(self.work / "cache"), HARNESS_VERIFY="off",
                        CODEX_HOME=str(self.work / "codex"), OPENCODE_CONFIG_DIR=str(self.work / "opencode"),
                        XDG_CONFIG_HOME=str(self.work / "xdg"),
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com")
        self.run_at(self.source, "git", "init", "-q", "-b", "main")
        shutil.copytree(ROOT / "payload", self.source / "payload")
        (self.source / "VERSION").write_text("0.26.1\n")
        self.run_at(self.source, "git", "add", "-A")
        self.run_at(self.source, "git", "commit", "-qm", "legacy engine")
        self.run_at(self.source, "git", "tag", "v0.26.1")
        shutil.copytree(ROOT / "plugin", self.source / "plugin")
        (self.source / "tools").mkdir()
        shutil.copy2(ROOT / "tools/thin.py", self.source / "tools/thin.py")
        shutil.copytree(ROOT / ".claude-plugin", self.source / ".claude-plugin")
        shutil.copytree(ROOT / ".codex-plugin", self.source / ".codex-plugin")
        shutil.copy2(ROOT / "package.json", self.source / "package.json")
        self.set_release_version("0.30.0")
        self.run_at(self.source, "git", "add", "-A")
        self.run_at(self.source, "git", "commit", "-qm", "thin engine")
        self.run_at(self.source, "git", "tag", "v0.30.0")
        self.set_release_version("0.30.1")
        self.run_at(self.source, "git", "add", "-A")
        self.run_at(self.source, "git", "commit", "-qm", "next thin engine")
        self.run_at(self.source, "git", "tag", "v0.30.1")
        self.run_at(self.project, "git", "init", "-q", "-b", "main")

    def set_release_version(self, version):
        (self.source / "VERSION").write_text(version + "\n")
        for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "package.json"):
            path = self.source / name
            data = json.loads(path.read_text())
            data["version"] = version
            path.write_text(json.dumps(data, indent=2) + "\n")

    def run_at(self, cwd, *args, check=True):
        result = subprocess.run(args, cwd=cwd, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_init_and_pin(self):
        settings_path = self.project / ".claude/settings.json"
        settings_path.parent.mkdir()
        settings_path.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)"]}}))
        self.run_at(self.project, "python3", "-B", str(ENGINE), "init", "--thin")
        lock_path = self.project / "backbone/.harness-lock.json"
        lock = json.loads(lock_path.read_text())
        harness_docs = ROOT / "payload/owned/backbone"
        self.assertEqual(lock, {"mode": "thin", "version": "0.30.0",
                                "commit": self.run_at(self.source, "git", "rev-parse", "v0.30.0").stdout.strip(),
                                "kept": {"backbone/" + path.relative_to(harness_docs).as_posix():
                                         hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in sorted(harness_docs.rglob("*")) if path.is_file()}})
        self.assertFalse((self.project / "scripts/harness").exists())
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.assertNotIn("@AGENTS.md", (self.project / "CLAUDE.md").read_text())
        self.assertTrue((self.project / ".github/workflows/harness-verify.yml").is_file())
        self.assertFalse((self.project / ".github/workflows/harness-judge.yml").exists())
        self.assertTrue((self.project / ".githooks/pre-commit").stat().st_mode & 0o111)
        self.assertEqual(self.run_at(self.project, "git", "config", "--get", "core.hooksPath").stdout.strip(),
                         ".githooks")
        self.assertEqual(self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin",
                                     check=False).returncode, 2)
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "pin", "0.30.1")
        lock = json.loads(lock_path.read_text())
        self.assertEqual(lock["version"], "0.30.1")
        self.assertEqual(lock["commit"], self.run_at(self.source, "git", "rev-parse", "v0.30.1").stdout.strip())
        settings = json.loads(settings_path.read_text())
        self.assertEqual(settings["permissions"]["deny"], ["Read(./.env)"])
        self.assertEqual(settings["extraKnownMarketplaces"]["agentic-harness"]["source"]["ref"], "v0.30.1")
        self.assertNotIn("sha", settings["extraKnownMarketplaces"]["agentic-harness"]["source"])
        self.assertTrue(settings["enabledPlugins"]["agentic-harness@agentic-harness"])

    def test_pre_commit_fetches_pinned_engine_on_a_fresh_clone(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        shutil.rmtree(self.work / "cache/0.30.0")
        self.run_at(self.project, "git", "add", "-A")
        result = self.run_at(self.project, "python3", "-B", ".githooks/pre-commit", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cache = self.work / "cache/0.30.0"
        self.assertTrue((cache / "payload/owned/scripts/harness/lib/harness.py").is_file())
        self.assertEqual(self.run_at(cache, "git", "rev-parse", "HEAD").stdout.strip(),
                         json.loads((self.project / "backbone/.harness-lock.json").read_text())["commit"])

    def test_session_start_supplies_rules_without_a_project_agents_file(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        self.assertFalse((self.project / "AGENTS.md").exists())
        result = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start")
        self.assertIn("Agent rules from the pinned engine", result.stdout)
        self.assertIn("## 1. First-run setup", result.stdout)
        self.assertIn("## 5. Guardrails", result.stdout)
        self.assertIn("payload/owned/scripts/harness/lib/harness.py' catalog", result.stdout)
        self.assertNotIn("Before changing anything read: AGENTS.md", result.stdout)
        self.assertNotIn("Harness problems", result.stdout)
        codex = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start",
                            "--from", "codex")
        context = json.loads(codex.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Agent rules from the pinned engine", context)
        self.assertIn("## 5. Guardrails", context)
        doctor = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "doctor")
        self.assertNotIn("git hooks inactive", doctor.stdout)

    def test_existing_project_file_is_kept_without_partial_install(self):
        document = self.project / "backbone/8-WORKFLOW.md"
        document.parent.mkdir()
        document.write_text("project workflow\n")
        result = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin",
                             "--version", "0.30.0", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(document.read_text(), "project workflow\n")
        self.assertFalse((self.project / "backbone/.harness-lock.json").exists())
        self.assertFalse((self.project / ".githooks/pre-commit").exists())

    def test_existing_project_owned_docs_are_preserved(self):
        claude = self.project / "CLAUDE.md"
        prd = self.project / "backbone/1-PRD.md"
        prd.parent.mkdir()
        claude.write_text("Existing project instructions\n")
        prd.write_text("Existing product requirements\n")
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        self.assertEqual(claude.read_text(), "Existing project instructions\n")
        self.assertEqual(prd.read_text(), "Existing product requirements\n")
        self.assertTrue((self.project / "backbone/.harness-lock.json").exists())

    def test_old_release_is_rejected_before_project_files_are_written(self):
        result = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin",
                             "--version", "0.26.1", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not support thin mode", result.stderr)
        self.assertFalse((self.project / "backbone/.harness-lock.json").exists())
        self.assertFalse((self.project / ".github/workflows/harness-verify.yml").exists())

    def test_default_version_must_be_published_before_installing(self):
        self.run_at(self.source, "git", "tag", "-d", "v0.30.0")
        result = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("release v0.30.0 was not found", result.stderr)
        self.assertFalse((self.project / "backbone/.harness-lock.json").exists())

    def test_init_copies_assets_from_the_pinned_release(self):
        workflow = "payload/owned/.github/workflows/harness-verify.yml"
        (self.source / workflow).write_text("modified working tree\n")
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        expected = self.run_at(self.source, "git", "show", "v0.30.0:" + workflow).stdout
        self.assertEqual((self.project / ".github/workflows/harness-verify.yml").read_text(), expected)

    def test_modified_engine_cache_is_rejected(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        cached = self.work / "cache/0.30.0/plugin/pre-commit"
        cached.write_text("modified cache\n")
        other = self.work / "other-project"
        other.mkdir()
        self.run_at(other, "git", "init", "-q", "-b", "main")
        result = self.run_at(other, "python3", "-B", str(LAUNCHER), "init", "--thin", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("has local changes", result.stderr)
        self.assertFalse((other / "backbone/.harness-lock.json").exists())

    def hook(self, event, tool, tool_input, **fields):
        payload = json.dumps(dict({"session_id": "s", "tool_name": tool, "tool_input": tool_input,
                                   "cwd": str(self.project)}, **fields))
        return subprocess.run(["python3", "-B", str(LAUNCHER), "hook", event], cwd=self.project, env=self.env,
                              input=payload, capture_output=True, text=True)

    def assert_hook(self, code, tool, tool_input, says=None, **fields):
        result = self.hook("pre-tool-use", tool, tool_input, **fields)
        self.assertEqual(result.returncode, code, "%s %s: %s" % (tool, tool_input, result.stdout + result.stderr))
        if says:
            self.assertIn(says, result.stderr)

    def test_hooks_refuse_an_engine_cache_with_local_changes(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        engine = self.work / "cache/0.30.0/payload/owned/scripts/harness/lib/harness.py"
        engine.write_text("import sys\nsys.exit(0)\n" + engine.read_text())
        self.assert_hook(2, "Bash", {"command": "echo hello"}, "local changes")
        self.assert_hook(0, "Read", {"file_path": str(self.project / "CLAUDE.md")})
        self.run_at(self.project, "git", "add", "-A")
        commit = self.run_at(self.project, "python3", "-B", ".githooks/pre-commit", check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn("local changes", commit.stdout + commit.stderr)

    def test_agents_cannot_write_the_engine_cache_or_the_plugin(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        cached = self.work / "cache/0.30.0/payload/owned/scripts/harness/guardrails.core.conf"
        launcher = ROOT / "plugin/launcher.py"
        for tool, tool_input in (
                ("Write", {"file_path": str(cached), "content": ""}),
                ("Edit", {"file_path": str(launcher), "old_string": "a", "new_string": "b"}),
                ("Bash", {"command": "echo > '%s'" % cached}),
                ("Bash", {"command": "rm -rf '%s'" % (self.work / "cache")}),
                ("Bash", {"command": "rm -rf '%s'" % self.work}),
                ("Bash", {"command": "cp /dev/null '%s'" % launcher}),
                ("Bash", {"command": "echo > .githooks/pre-commit"})):
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assert_hook(2, tool, tool_input)
        self.assert_hook(2, "Write", {"file_path": str(self.project / ".githooks/pre-commit"), "content": ""},
                         "init --thin", agent_id="implementer-1", agent_type="implementer")
        self.assert_hook(0, "Bash", {"command": "echo hello > '%s'" % (self.work / "scratch.txt")})

    def test_agents_cannot_move_the_pin(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        engine = self.work / "cache/0.30.0/payload/owned/scripts/harness/lib/harness.py"
        for command in ("python3 '%s' pin 0.30.1" % LAUNCHER,
                        "python3 '%s' pin 0.30.1" % engine,
                        "cd '%s' && python3 tools/thin.py pin 0.30.1" % ROOT):
            with self.subTest(command=command):
                self.assert_hook(2, "Bash", {"command": command}, "pin")
        self.assert_hook(0, "Bash", {"command": "python3 '%s' doctor" % LAUNCHER})

    def test_a_malformed_lock_fails_closed(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        lock = self.project / "backbone/.harness-lock.json"
        lock.write_text("<<<<<<< HEAD\n" + lock.read_text() + "=======\n{}\n>>>>>>> other\n")
        self.assert_hook(2, "Bash", {"command": "echo hello"}, ".harness-lock.json")
        self.assert_hook(0, "Read", {"file_path": str(lock)})
        start = self.hook("session-start", None, None)
        self.assertEqual(start.returncode, 0)
        self.assertIn(".harness-lock.json", start.stdout)

    def test_session_start_reports_a_plugin_that_is_not_the_pinned_release(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        self.assertNotIn("plugin is v", self.hook("session-start", None, None).stdout)
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "pin", "0.30.1")
        start = self.hook("session-start", None, None)
        self.assertIn("plugin is v0.30.0, but this project pins v0.30.1", start.stdout)
        self.assert_hook(0, "Bash", {"command": "echo hello"})

    def test_autonomous_work_stops_while_the_plugin_is_not_the_pinned_release(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        self.env["HARNESS_AUTONOMY"] = "autonomous"
        self.assert_hook(0, "Bash", {"command": "echo hello"})
        self.assertNotIn("plugin is v", self.run_at(self.project, "python3", "-B", str(LAUNCHER), "run", "--dry-run",
                                                    check=False).stdout)
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "pin", "0.30.1")
        self.assert_hook(2, "Bash", {"command": "echo hello"}, "plugin is v0.30.0, but this project pins v0.30.1")
        self.assert_hook(0, "Read", {"file_path": str(self.project / "CLAUDE.md")})
        for command in ("run", "orca"):
            with self.subTest(command=command):
                result = self.run_at(self.project, "python3", "-B", str(LAUNCHER), command, "--dry-run", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("plugin is v0.30.0, but this project pins v0.30.1", result.stdout + result.stderr)


    def test_subagents_are_told_where_the_pinned_engine_is(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        engine = (self.work / "cache/0.30.0/payload/owned").resolve()
        for source in ((), ("--from", "codex")):
            with self.subTest(source=source):
                result = subprocess.run(["python3", "-B", str(LAUNCHER), "hook", "subagent-start", *source],
                                        cwd=self.project, env=self.env, capture_output=True, text=True,
                                        input=json.dumps({"agent_type": "griller", "agent_id": "a1"}))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "SubagentStart")
                context = output["additionalContext"]
                self.assertIn("python3 %s" % shlex.quote(str(engine / "scripts/harness/lib/harness.py")), context)
                self.assertIn(str(engine / "AGENTS.md"), context)
                self.assertIn(str(engine / "scripts/harness/routing.core.conf"), context)

    def test_codex_and_opencode_sessions_install_the_pinned_role_agents(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        engine = self.work / "cache/0.30.0/payload/owned"
        codex = self.work / "codex/agents"
        codex.mkdir(parents=True)
        mine = 'name = "reviewer"\ndescription = "my own reviewer"\n'
        (codex / "reviewer.toml").write_text(mine)
        (codex / "judge.toml").write_text("# Agentic harness: generated from .claude/agents/judge.md by "
                                          "tools/gen_agents.py (harness-owned).\nname = \"judge\"\n")
        start = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start", "--from", "codex")
        context = json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"]
        for agent in sorted((engine / ".codex/agents").glob("*.toml")):
            if agent.name != "reviewer.toml":
                self.assertEqual((codex / agent.name).read_text(), agent.read_text(), agent.name)
        self.assertEqual((codex / "reviewer.toml").read_text(), mine)
        self.assertIn("restart Codex", context)
        self.assertIn(str(codex / "reviewer.toml"), context)
        again = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start", "--from", "codex")
        context = json.loads(again.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("restart Codex", context)
        self.assertIn(str(codex / "reviewer.toml"), context)
        opencode = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start",
                               "--from", "opencode")
        for agent in sorted((engine / ".opencode/agents").glob("*.md")):
            self.assertEqual((self.work / "opencode/agents" / agent.name).read_text(), agent.read_text(), agent.name)
        self.assertIn("restart OpenCode", opencode.stdout)
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start")
        self.assertFalse((self.work / "xdg").exists())

    def test_agents_cannot_change_the_installed_role_agents(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "hook", "session-start", "--from", "codex")
        judge = self.work / "codex/agents/judge.toml"
        for tool, tool_input in (
                ("Write", {"file_path": str(judge), "content": ""}),
                ("Bash", {"command": "echo > '%s'" % judge}),
                ("Edit", {"file_path": str(self.work / "opencode/agents/judge.md"), "old_string": "a",
                          "new_string": "b"})):
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assert_hook(2, tool, tool_input)
        # The user's own agents there are Codex's configuration too, which agents don't change either.
        self.assert_hook(2, "Write", {"file_path": str(self.work / "codex/agents/mine.toml"), "content": ""})

    def test_opencode_sessions_get_the_session_start_context(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        script = """
import plugin from './plugin/opencode.js';
const project = process.env.TEST_PROJECT;
let context;
await plugin.setup({ directory: project, tool: { hook: async () => ({ dispose() {} }) },
  session: { hook: async (name, callback) => { if (name === 'context') context = callback; return { dispose() {} }; } } });
const texts = [];
for (const sessionID of ['s1', 's1', 's2']) {
  const event = { sessionID, agent: 'build', system: [], messages: [], options: {}, tools: {} };
  await context(event);
  texts.push(event.system.map((part) => part.text).join('\\n'));
}
const v1 = await plugin.server({ directory: project });
const output = { system: [] };
await v1['experimental.chat.system.transform']({ sessionID: 's3' }, output);
texts.push(output.system.join('\\n'));
console.log(JSON.stringify(texts));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                                env=dict(self.env, TEST_PROJECT=str(self.project)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        texts = json.loads(result.stdout)
        self.assertEqual(len(texts), 4)
        for text in texts:
            self.assertIn("Agent rules from the pinned engine", text)
            self.assertIn("payload/owned/scripts/harness/lib/harness.py", text)
            self.assertIn("no AGENTS.md and no scripts/harness/ folder", text)


    def test_run_drives_a_task_in_its_own_worktree(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        tasks = self.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 6.1: Item** (spec: backbone/specs/6.1.md)\n")
        self.run_at(self.project, "git", "add", "-A")
        self.run_at(self.project, "git", "commit", "-qm", "chore: adopt agentic harness")
        agent = self.work / "fake-agent.sh"
        agent.write_text("#!/bin/sh\n"
                         "cat > \"$PROMPT_OUT\"\n"
                         "sed -i.bak 's/^- \\[ \\] \\*\\*Task 6.1/- [x] **Task 6.1/' backbone/3-TASKS.md\n"
                         "rm -f backbone/3-TASKS.md.bak\n"
                         "echo done > out-6.1.txt\n"
                         "git add -A && HARNESS_VERIFY=off git commit -qm 'feat: task 6.1'\n"
                         "echo '{\"type\":\"result\",\"total_cost_usd\":0.1,\"num_turns\":1,\"result\":\"ok\"}'\n")
        agent.chmod(0o755)
        prompt = self.work / "prompt.txt"
        env = dict(self.env, HARNESS_AUTONOMY="autonomous", HARNESS_TEST_CMD="true", HARNESS_VERIFY="block",
                   HARNESS_DELIVER="off", HARNESS_AGENT_CMD=shlex.quote(str(agent)), PROMPT_OUT=str(prompt))
        result = subprocess.run(["python3", "-B", str(LAUNCHER), "run", "--worktree", "--only", "6.1"],
                                cwd=self.project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"run: done\s+task 6.1")
        self.assertEqual(self.run_at(self.project, "git", "log", "-1", "--format=%s", "harness/task-6.1").stdout.strip(),
                         "feat: task 6.1")
        self.assertIn("payload/owned/scripts/harness/lib/harness.py", prompt.read_text())
        self.assertNotIn("python3 scripts/harness/lib/harness.py", prompt.read_text())

    def test_orca_drives_tasks_with_the_pinned_engine(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        tasks = self.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [ ] **Task 6.1: Item** (spec: backbone/specs/6.1.md)\n")
        self.run_at(self.project, "git", "add", "-A")
        self.run_at(self.project, "git", "commit", "-qm", "chore: adopt agentic harness")
        orca = self.work / "fake-orca.py"
        shutil.copy2(ROOT / "tests/fake-orca.py", orca)
        state = self.work / "orca-state.json"
        env = dict(self.env, HARNESS_AUTONOMY="autonomous", HARNESS_TEST_CMD="true", HARNESS_VERIFY="block",
                   HARNESS_ORCA_BIN=str(orca), HARNESS_ORCA_LAUNCH_WAIT="0", FAKE_ORCA_STATE=str(state),
                   FAKE_ORCA_WT=str(self.work / "orca-worktrees"))
        result = subprocess.run(["python3", "-B", str(LAUNCHER), "orca", "--tasks", "6.1", "--wait-ms", "10"],
                                cwd=self.project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        specs = json.loads(state.read_text()).get("specs") if state.exists() else None
        self.assertTrue(specs, result.stdout + result.stderr)
        self.assertIn("Harness step for task 6.1", specs[0])
        self.assertIn("payload/owned/scripts/harness/lib/harness.py", specs[0])
        self.assertNotIn("python3 scripts/harness/lib/harness.py", specs[0])

    def test_commits_in_a_linked_worktree_run_the_pinned_engine(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        self.run_at(self.project, "git", "add", "-A")
        self.run_at(self.project, "git", "commit", "-qm", "chore: adopt agentic harness")
        tree = self.work / "tree"
        self.run_at(self.project, "git", "worktree", "add", "-q", "-b", "feature", str(tree), "HEAD")
        (tree / "notes.txt").write_text("notes\n")
        self.run_at(tree, "git", "add", "-A")
        commit = self.run_at(tree, "git", "commit", "-qm", "docs: notes", check=False)
        self.assertEqual(commit.returncode, 0, commit.stdout + commit.stderr)
        tasks = tree / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "- [x] **Task 7.1: Unjudged** (spec: backbone/specs/7.1.md)\n")
        self.run_at(tree, "git", "add", "-A")
        env = dict(self.env, HARNESS_VERIFY="block")
        refused = subprocess.run(["git", "commit", "-qm", "feat: task 7.1"], cwd=tree, env=env,
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        self.assertIn("7.1", refused.stdout + refused.stderr)

    def test_pin_brings_the_release_files_to_the_new_release(self):
        self.run_at(self.project, "python3", "-B", str(LAUNCHER), "init", "--thin")
        shim = self.source / "plugin/pre-commit"
        shim.write_text(shim.read_text() + "# 0.30.2\n")
        workflow = self.source / "payload/owned/.github/workflows/harness-verify.yml"
        workflow.write_text(workflow.read_text() + "# 0.30.2\n")
        self.set_release_version("0.30.2")
        self.run_at(self.source, "git", "add", "-A")
        self.run_at(self.source, "git", "commit", "-qm", "release 0.30.2")
        self.run_at(self.source, "git", "tag", "v0.30.2")
        result = self.run_at(self.project, "python3", "-B", str(LAUNCHER), "pin", "0.30.2")
        self.assertEqual((self.project / ".githooks/pre-commit").read_text(), shim.read_text())
        self.assertTrue((self.project / ".githooks/pre-commit").stat().st_mode & 0o111)
        self.assertEqual((self.project / ".github/workflows/harness-verify.yml").read_text(), workflow.read_text())
        self.assertIn(".githooks/pre-commit", result.stdout)


if __name__ == "__main__":
    unittest.main()
