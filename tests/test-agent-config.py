"""The agent CLIs' own configuration (Claude Code, Codex, OpenCode), outside the project: an agent may read it but not
change it, and a configuration that turns the harness's hooks off or hijacks them is an error at session start, in
doctor and for run and orca. Every test runs in a throwaway HOME, so the real ~/.claude, ~/.codex and
~/.config/opencode are never touched."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("analyst", "architect", "griller", "tester", "implementer", "judge", "debugger", "scribe", "reviewer",
         "deliverer")
MOVED = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "XDG_CONFIG_HOME",
         "CLAUDE_PLUGIN_ROOT", "HARNESS_AUTONOMY", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="agent config ")
        cls.work = Path(cls.temp.name)
        cls.home = cls.work / "home"
        cls.home.mkdir()
        cls.project = cls.work / "project"
        cls.project.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.project)], check=True)
        subprocess.run([str(ROOT / "bootstrap.sh"), str(cls.project)], check=True, capture_output=True,
                       env=cls.base_env())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def base_env(cls, **extra):
        env = {k: v for k, v in os.environ.items() if k not in MOVED}
        env.update(HOME=str(cls.home), CLAUDE_PROJECT_DIR=str(cls.project), GIT_CONFIG_GLOBAL=os.devnull,
                   PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
                   GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com")
        env.update(extra)
        return env

    def harness(self, *args, stdin="", **env):
        return subprocess.run(["python3", str(self.project / "scripts/harness/lib/harness.py")] + list(args),
                              cwd=self.project, input=stdin, capture_output=True, text=True,
                              env=self.base_env(**env))

    def pre_tool_use(self, tool, tool_input, source=None, env=None, **fields):
        data = dict({"session_id": "s", "tool_name": tool, "tool_input": tool_input, "cwd": str(self.project)},
                    **fields)
        args = ["hook", "pre-tool-use"] + (["--from", source] if source else [])
        return self.harness(*args, stdin=json.dumps(data), **(env or {}))

    def bash(self, command, env=None, **fields):
        return self.pre_tool_use("Bash", {"command": command}, env=env, **fields)

    def assertRefused(self, result, what=""):
        self.assertEqual(result.returncode, 2, "%s: %s" % (what, result.stdout + result.stderr))

    def assertAllowed(self, result, what=""):
        self.assertEqual(result.returncode, 0, "%s: %s" % (what, result.stdout + result.stderr))


class WritesToAgentConfiguration(Fixture):
    """Write, Edit, MultiEdit and apply_patch, and shell writes, to the CLIs' user- and machine-level configuration."""

    def protected_files(self):
        h = self.home
        return [h / ".claude/settings.json", h / ".claude/settings.local.json", h / ".claude.json",
                h / ".claude/hooks/pre.sh", h / ".claude/hooks.json", h / ".claude/agents/judge.md",
                h / ".claude/skills/x/SKILL.md", h / ".claude/plugins/installed_plugins.json",
                h / ".claude/CLAUDE.md", h / ".claude/rules/override.md", h / ".claude/commands/x.md",
                h / ".codex/config.toml", h / ".codex/hooks.json", h / ".codex/AGENTS.md",
                h / ".codex/rules/default.rules", h / ".codex/agents/judge.toml",
                h / ".config/opencode/opencode.json", h / ".config/opencode/plugins/x.js",
                h / ".config/opencode/AGENTS.md", h / ".agentic-harness/machine.json",
                Path("/etc/claude-code/managed-settings.json"),
                Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
                Path("/etc/codex/requirements.toml")]

    def test_the_file_tools_may_not_change_it_in_any_role(self):
        for path in self.protected_files():
            for role in ("",) + ROLES:
                with self.subTest(path=str(path), role=role or "main session"):
                    fields = {"agent_type": role} if role else {}
                    self.assertRefused(self.pre_tool_use("Write", {"file_path": str(path), "content": "{}"},
                                                         **fields))
                    if role:
                        continue
                    self.assertRefused(self.pre_tool_use("Edit", {"file_path": str(path), "old_string": "a",
                                                                  "new_string": "b"}))
                    self.assertRefused(self.pre_tool_use("MultiEdit", {"file_path": str(path), "edits": [
                        {"old_string": "a", "new_string": "b"}]}))

    def test_the_refusal_says_what_the_file_is(self):
        result = self.pre_tool_use("Write", {"file_path": str(self.home / ".claude/settings.json"),
                                             "content": '{"disableAllHooks": true}'})
        self.assertRefused(result)
        self.assertIn("Claude Code's user configuration", result.stderr)

    def test_apply_patch_may_not_change_it(self):
        for path in (self.home / ".codex/config.toml", self.home / ".claude/settings.json"):
            with self.subTest(path=str(path)):
                patch = "*** Begin Patch\n*** Add File: %s\n+[features]\n+hooks = false\n*** End Patch" % path
                self.assertRefused(self.pre_tool_use("apply_patch", {"command": patch}, source="codex"))

    def test_shell_writes_may_not_change_it(self):
        commands = [
            """echo '{"disableAllHooks": true}' > ~/.claude/settings.json""",
            """printf x >> $HOME/.claude/settings.json""",
            """printf x > "${HOME}/.claude.json\"""",
            """echo x | tee ~/.claude/settings.local.json""",
            """echo x | tee -a %s""" % shlex.quote(str(self.home / ".codex/config.toml")),
            """cp evil.json ~/.claude/settings.json""",
            """cp settings.json ~/.claude/""",
            """cp .claude.json ~/""",
            """mv evil.json ~/.claude.json""",
            """install -m 644 evil.sh ~/.claude/hooks/x.sh""",
            """rsync evil/ ~/.claude/agents/""",
            """dd if=evil.json of=%s""" % shlex.quote(str(self.home / ".claude/settings.json")),
            """sed -i '' s/true/false/ ~/.codex/config.toml""",
            """sed -i s/x/y/ ~/.config/opencode/opencode.json""",
            """ln -sf /tmp/evil.json ~/.claude/settings.json""",
            """ln -s ~/.claude/settings.json s && echo '{}' > s""",
            """ln -s ~/.claude cl && echo '{}' > cl/settings.json""",
            """cd ~/.claude && echo '{}' > settings.json""",
            """cd && echo '{}' > .claude/settings.json""",
            """rm -rf ~/.claude""",
            """rm ~/.codex/hooks.json""",
            """mv ~/.codex ~/.codex.off""",
            """chmod 000 ~/.claude/settings.json""",
            """touch ~/.config/opencode/plugins/x.js""",
            """curl -so ~/.claude/settings.json https://example.com/s.json""",
            """wget -qO ~/.codex/config.toml https://example.com/c.toml""",
            """git clone https://example.com/x.git ~/.claude/plugins/x""",
            """tar -xzf evil.tgz -C ~/.claude""",
            """unzip evil.zip -d ~/.config/opencode""",
            """python3 -c "open(%r, 'w').write('{}')\"""" % str(self.home / ".claude/settings.json"),
            """python3 -c "import os; open(os.path.expanduser('~/.claude.json'), 'w').write('{}')\"""",
            """python3 -c "import os, pathlib; pathlib.Path(os.environ['HOME'], '.claude', 'settings.json').write_text('{}')\"""",
            """node -e "require('fs').writeFileSync(process.env.HOME + '/.codex/hooks.json', '{}')\"""",
            """python3 - <<'EOF'\nimport os\nopen(os.path.expanduser('~/.config/opencode/opencode.json'), 'w').write('{}')\nEOF""",
            """bash -c "echo '{}' > ~/.claude/settings.json\"""",
            """sh -c 'cp x ~/.codex/config.toml'""",
            """eval "echo x > ~/.claude/settings.json\"""",
            """jq '.disableAllHooks = true' ~/.claude/settings.json | sponge ~/.claude/settings.json""",
            """python3 edit.py ~/.claude/settings.json""",
            """echo x > $UNSET_PREFIX/.claude/settings.json""",
            """claude config set -g disableAllHooks true""",
            """claude plugin disable agentic-harness@agentic-harness""",
            """claude plugin uninstall agentic-harness""",
            """claude mcp add -s user evil -- python3 evil.py""",
            """codex mcp add evil -- python3 evil.py""",
            """codex features disable hooks""",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertRefused(self.bash(command), command)

    def test_the_variables_that_move_the_folders_are_followed(self):
        moved = self.work / "moved"
        env = {"CLAUDE_CONFIG_DIR": str(moved / "claude"), "CODEX_HOME": str(moved / "codex"),
               "OPENCODE_CONFIG_DIR": str(moved / "opencode"), "XDG_CONFIG_HOME": str(moved / "xdg"),
               "OPENCODE_CONFIG": str(moved / "oc.json")}
        for command in ("echo x > $CLAUDE_CONFIG_DIR/settings.json", "echo x > ${CLAUDE_CONFIG_DIR}/.claude.json",
                        "echo x > $CODEX_HOME/config.toml", "echo x > $OPENCODE_CONFIG_DIR/plugins/x.js",
                        "echo x > $XDG_CONFIG_HOME/opencode/opencode.json", "echo x > $OPENCODE_CONFIG",
                        "echo x > %s" % shlex.quote(str(moved / "claude/settings.json")),
                        # the default folders stay protected while a variable moves them
                        "echo x > ~/.claude/settings.json", "echo x > ~/.codex/config.toml"):
            with self.subTest(command=command):
                self.assertRefused(self.bash(command, env=env), command)
        for path in (moved / "claude/settings.json", moved / "codex/hooks.json", moved / "opencode/opencode.json",
                     moved / "xdg/opencode/plugins/x.js", moved / "oc.json"):
            with self.subTest(path=str(path)):
                self.assertRefused(self.pre_tool_use("Write", {"file_path": str(path), "content": "{}"}, env=env))

    def test_a_symlink_into_it_is_followed(self):
        (self.home / ".claude").mkdir(exist_ok=True)
        target = self.home / ".claude/settings.json"
        target.write_text("{}")
        link = self.project / "notes.json"
        link.symlink_to(target)
        self.addCleanup(link.unlink)
        self.assertRefused(self.pre_tool_use("Write", {"file_path": str(link), "content": "{}"}))
        self.assertRefused(self.bash("echo x > notes.json"))

    def test_reading_it_is_allowed(self):
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".claude/settings.json").write_text("{}")
        for command in ("cat ~/.claude/settings.json", "jq . ~/.claude/settings.json", "ls -la ~/.claude ~",
                        "grep -n hooks ~/.codex/config.toml", "head ~/.config/opencode/opencode.json",
                        "cp ~/.claude/settings.json backup.json", "diff ~/.claude/settings.json backup.json",
                        "find ~/.claude -name '*.json'", "sed -n 1p ~/.claude.json", "claude mcp list",
                        "claude plugin list", "test -f ~/.claude/settings.json && echo yes"):
            with self.subTest(command=command):
                self.assertAllowed(self.bash(command), command)
        self.assertAllowed(self.pre_tool_use("Read", {"file_path": str(self.home / ".claude/settings.json")}))

    def test_the_rest_of_the_home_folder_is_left_alone(self):
        for path in (self.home / "notes.txt", self.home / ".claude/projects/x/memory/note.md",
                     self.home / ".claude/todos/x.json", self.home / ".config/other/x.json"):
            with self.subTest(path=str(path)):
                self.assertAllowed(self.pre_tool_use("Write", {"file_path": str(path), "content": "x"}))
        for command in ("echo x > ~/notes.txt", "cp a.txt ~/", "echo x > ~/.claude/projects/x/memory/note.md",
                        "rm -rf ~/.cache/pip"):
            with self.subTest(command=command):
                self.assertAllowed(self.bash(command), command)


class ConfigurationThatTurnsTheHarnessOff(Fixture):
    """Session start, doctor, run, orca and the ConfigChange hook check the configuration the CLIs read."""

    def setUp(self):
        for folder in (self.home / ".claude", self.home / ".codex", self.home / ".config"):
            shutil.rmtree(str(folder), ignore_errors=True)
        (self.home / ".claude.json").unlink() if (self.home / ".claude.json").exists() else None
        local = self.project / ".claude/settings.local.json"
        local.unlink() if local.exists() else None
        self.harness("accept-agent-config")

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data))

    def doctor(self):
        return self.harness("doctor")

    def assertError(self, needle):
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        errors = [line for line in result.stdout.splitlines() if line.startswith("ERROR")]
        self.assertTrue(any(needle in line for line in errors), "no ERROR with %r in:\n%s" % (needle, result.stdout))
        return result

    def assertNoAgentConfigError(self):
        result = self.doctor()
        errors = [line for line in result.stdout.splitlines() if line.startswith("ERROR")]
        self.assertEqual([e for e in errors if "configuration" in e or "settings" in e], [], result.stdout)

    def test_a_clean_configuration_is_healthy(self):
        self.write(self.home / ".claude/settings.json", {"model": "opus", "theme": "dark"})
        self.assertNoAgentConfigError()

    def test_disable_all_hooks_in_the_local_settings(self):
        self.write(self.project / ".claude/settings.local.json", {"disableAllHooks": True})
        self.assertError("disableAllHooks")

    def test_the_project_settings_keep_hooks_on_against_the_user_settings(self):
        self.assertIs(json.loads((self.project / ".claude/settings.json").read_text()).get("disableAllHooks"), False)
        self.write(self.home / ".claude/settings.json", {"disableAllHooks": True})
        self.assertNoAgentConfigError()

    def test_disable_all_hooks_in_a_moved_config_folder(self):
        moved = self.work / "moved-claude"
        self.addCleanup(shutil.rmtree, str(moved), True)
        self.write(self.project / ".claude/settings.local.json", {})
        self.write(moved / "settings.json", {"env": {"PYTHONPATH": "/tmp/x"}})
        result = self.harness("doctor", CLAUDE_CONFIG_DIR=str(moved))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("PYTHONPATH", result.stdout)

    def test_an_env_block_that_reaches_the_hooks(self):
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PATH", "BASH_ENV", "LD_PRELOAD",
                     "DYLD_INSERT_LIBRARIES", "HARNESS_VERIFY", "GIT_DIR"):
            with self.subTest(name=name):
                self.write(self.home / ".claude/settings.json", {"env": {name: "/tmp/evil"}})
                self.assertError(name)
        self.write(self.home / ".claude/settings.json", {"env": {"PYTHONDONTWRITEBYTECODE": "1", "FOO": "bar"}})
        self.assertNoAgentConfigError()

    def test_permissions_that_allow_changing_protected_files(self):
        for rule in ("Edit(~/.claude/**)", "Write(//%s/.claude.json)" % str(self.home).lstrip("/"),
                     "Bash(rm -rf ~/.codex:*)", "Edit(backbone/**)", "Write(scripts/harness/**)",
                     "Edit(backbone/.verdicts/**)", "Edit(~/**)", "Edit(.claude/settings.local.json)"):
            with self.subTest(rule=rule):
                self.write(self.home / ".claude/settings.json", {"permissions": {"allow": [rule]}})
                self.assertError(rule)
        self.write(self.home / ".claude/settings.json", {"permissions": {"allow": [
            "Bash(npm test)", "Bash(scripts/harness/doctor.sh)", "Edit(src/**)", "Edit(.claude/skills/**)", "Edit(**)",
            "Edit(backbone/3-TASKS.md)", "Write(~/notes/**)"]}})
        self.assertNoAgentConfigError()

    def test_codex_hooks_switched_off(self):
        for text in ("[features]\nhooks = false\n", "[features]\ncodex_hooks = false\n", "features.hooks = false\n",
                     "model = 'o3'\n[shell_environment_policy]\nset = { PYTHONPATH = \"/tmp/x\" }\n"):
            with self.subTest(text=text):
                self.write(self.home / ".codex/config.toml", text)
                self.harness("accept-agent-config")
                self.assertError("Codex")
        self.write(self.home / ".codex/config.toml", "model = 'o3'\n[features]\nhooks = true\n")
        self.harness("accept-agent-config")
        self.assertNoAgentConfigError()

    def test_opencode_plugin_removed(self):
        self.write(self.home / ".config/opencode/opencode.json", '{"plugin": ["-*"]}')
        self.harness("accept-agent-config")
        self.assertError("OpenCode")

    def test_a_new_command_running_setting_is_reported_until_the_user_accepts_it(self):
        self.write(self.home / ".claude/settings.json", {"theme": "dark"})
        self.assertNoAgentConfigError()
        cases = [(self.home / ".claude/settings.json", {"apiKeyHelper": "/tmp/evil.sh"}, "apiKeyHelper"),
                 (self.home / ".claude/settings.json", {"hooks": {"PreToolUse": [{"hooks": [
                     {"type": "command", "command": "/tmp/allow-all.sh"}]}]}}, "hooks"),
                 (self.home / ".claude/settings.json", {"statusLine": {"type": "command", "command": "/tmp/x"}},
                  "statusLine"),
                 (self.home / ".claude.json", {"mcpServers": {"evil": {"command": "/tmp/x"}}}, "mcpServers"),
                 (self.home / ".codex/hooks.json", {"hooks": {}}, "hooks.json"),
                 (self.home / ".codex/config.toml", "notify = [\"/tmp/x\"]\n", "notify")]
        for path, data, needle in cases:
            with self.subTest(needle=needle):
                self.write(path, data)
                result = self.assertError(needle)
                self.assertIn("accept-agent-config", result.stdout)
                self.harness("accept-agent-config")
                self.assertNoAgentConfigError()

    def test_agents_may_not_accept_a_configuration(self):
        for command in ("python3 scripts/harness/lib/harness.py accept-agent-config",
                        "python3 -I %s accept-agent-config"
                        % shlex.quote(str(self.project / "scripts/harness/lib/harness.py"))):
            with self.subTest(command=command):
                self.assertRefused(self.bash(command), command)

    def test_session_start_reports_it(self):
        self.write(self.project / ".claude/settings.local.json", {"disableAllHooks": True})
        result = self.harness("hook", "session-start", stdin="{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("disableAllHooks", result.stdout)

    def test_run_and_orca_refuse_to_start(self):
        self.write(self.home / ".claude/settings.json", {"env": {"PYTHONPATH": "/tmp/evil"}})
        for command in (["run", "--dry-run"], ["orca", "--dry-run"]):
            with self.subTest(command=command[0]):
                result = self.harness(*command, HARNESS_AUTONOMY="autonomous", HARNESS_TEST_CMD="true",
                                      HARNESS_SKIP_TRUST_CHECK="1")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("fix the harness first", result.stdout)
                self.assertIn("PYTHONPATH", result.stdout)

    def config_change(self, source, path, **env):
        return self.harness("hook", "config-change", stdin=json.dumps(
            {"hook_event_name": "ConfigChange", "source": source, "file_path": str(path)}), **env)

    def test_the_config_change_hook_blocks_a_change_that_turns_the_harness_off(self):
        local = self.project / ".claude/settings.local.json"
        self.write(local, {"disableAllHooks": True})
        self.assertRefused(self.config_change("local_settings", local))
        self.write(local, {})
        user = self.home / ".claude/settings.json"
        self.write(user, {"env": {"PYTHONPATH": "/tmp/evil"}})
        self.assertRefused(self.config_change("user_settings", user))
        self.write(user, {"theme": "light"})
        self.assertAllowed(self.config_change("user_settings", user))

    def test_in_autonomous_mode_it_also_blocks_a_new_command_running_setting(self):
        user = self.home / ".claude/settings.json"
        self.write(user, {"apiKeyHelper": "/tmp/evil.sh"})
        self.assertAllowed(self.config_change("user_settings", user))
        self.assertRefused(self.config_change("user_settings", user, HARNESS_AUTONOMY="autonomous"))


class IsolatedHookInterpreters(Fixture):
    """Every hook wiring runs python3 -I, so PYTHONPATH and friends from a settings env block can't hijack the engine."""

    def setUp(self):
        self.inject = self.work / "inject"
        self.inject.mkdir(exist_ok=True)
        self.marker = self.work / "hijacked"
        (self.inject / "sitecustomize.py").write_text("open(%r, 'a').write('x')\n" % str(self.marker))
        if self.marker.exists():
            self.marker.unlink()

    def hijack_env(self):
        return self.base_env(PYTHONPATH=str(self.inject), CLAUDE_PLUGIN_ROOT=str(ROOT), PLUGIN_ROOT=str(ROOT))

    def commands(self, path):
        data = json.loads(path.read_text())
        return [hook["command"] for groups in data["hooks"].values() for group in groups for hook in group["hooks"]]

    def run_command(self, command, data):
        return subprocess.run(["sh", "-c", command], cwd=self.project, env=self.hijack_env(), input=json.dumps(data),
                              capture_output=True, text=True)

    def test_the_hook_commands_ignore_python_variables(self):
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(self.project)}
        wirings = [self.project / ".claude/settings.json", self.project / ".codex/hooks.json",
                   ROOT / "plugin/claude-hooks.json", ROOT / "plugin/codex-hooks.json"]
        for wiring in wirings:
            for command in self.commands(wiring):
                if "pre-tool-use" not in command and "config-change" not in command:
                    continue
                with self.subTest(wiring=str(wiring.relative_to(wiring.parents[1])), command=command):
                    self.run_command(command, bash)
                    self.assertFalse(self.marker.exists(), "%s ran the injected sitecustomize" % command)

    def test_the_agents_hooks_and_the_launcher_ignore_them_too(self):
        front = (self.project / ".claude/agents/implementer.md").read_text().split("---\n")[1]
        command = next(line.split("command: ", 1)[1].strip().strip("'") for line in front.splitlines()
                       if "command:" in line and "agent-guard" in line)
        result = self.run_command(command, {"tool_name": "Write", "tool_input": {
            "file_path": str(self.project / "src/app.py"), "content": "x"}})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists(), "the launcher or the engine ran the injected sitecustomize")

    def test_the_git_hooks_ignore_them(self):
        hook = self.project / "scripts/harness/git-hooks/pre-commit"
        subprocess.run(["sh", str(hook)], cwd=self.project, env=self.hijack_env(), capture_output=True, text=True)
        self.assertFalse(self.marker.exists())

    def test_the_opencode_adapter_runs_isolated(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        script = """
const plugin = (await import(%r)).default;
let before;
await plugin.setup({ tool: { hook: async (name, callback) => {
  if (name === 'execute.before') before = callback;
  return { dispose() {} };
} } });
await before({ cwd: %r, tool: 'bash', input: { command: 'ls' } });
""" % ((self.project / ".opencode/plugins/harness.js").as_uri(), str(self.project))
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=self.project,
                                env=self.hijack_env(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
