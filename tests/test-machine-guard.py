"""The machine guard: in a git repository under the roots in ~/.agentic-harness/machine.json that isn't enrolled in
the harness, an agent's edits get a reminder (warn) or are refused (block). It runs as the hook machine.sh installs or
as the plugin's own hook (launcher.py hook machine-guard). The tests install it with machine.sh into a throwaway home
and run the hooks a CLI would run for each tool call (the property checks need hypothesis)."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
import uuid

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


ROOT = Path(__file__).resolve().parents[1]
THIN_LOCK = {"mode": "thin", "version": "9.9.9", "commit": "0" * 40}
USER_HOOKS = {"claude": ".claude/settings.json", "codex": ".codex/hooks.json"}
# What backbone/.harness-lock.json holds, and whether that alone (no engine in scripts/harness/) is enrolled.
LOCKS = (
    ("no lock", None, False),
    ("a thin pin", json.dumps(THIN_LOCK), True),
    ("a full install's lock", json.dumps({"harness_version": "0.30.0", "files": {}}), False),
    ("an empty lock", "{}", False),
    ("a merge conflict", "<<<<<<< HEAD\n%s\n=======\n{}\n>>>>>>> other\n" % json.dumps(THIN_LOCK), True),
    ("a lock that is not an object", "[]", True),
    ("a folder in place of the lock", "folder", True),
)


def matches(matcher, tool):
    """Claude Code's and Codex's rule: no matcher or "*" matches every tool, letters, digits, "_" and "|" list exact
    names, anything else is a regular expression."""
    if not matcher or matcher == "*":
        return True
    if re.fullmatch(r"[A-Za-z0-9_|]+", matcher):
        return tool in matcher.split("|")
    return re.search(matcher, tool) is not None


def environment(home, work):
    for folder in (".claude", ".codex"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items()
           if key not in ("HARNESS_MACHINE_CONFIG", "CLAUDE_PROJECT_DIR", "HARNESS_ROOT")}
    env.update(HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, PYTHONDONTWRITEBYTECODE="1",
               HARNESS_ENGINES=str(work / "engines"), HARNESS_ENGINE_SOURCE=str(work / "offline"),
               CLAUDE_PLUGIN_ROOT=str(ROOT), PLUGIN_ROOT=str(ROOT))
    return env


def git_repo(path, env, vendored=False, lock=None):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    if vendored:
        (path / "scripts/harness/lib").mkdir(parents=True)
        (path / "scripts/harness/lib/harness.py").write_text("")
    if lock == "folder":
        (path / "backbone/.harness-lock.json").mkdir(parents=True)
    elif lock is not None:
        (path / "backbone").mkdir()
        (path / "backbone/.harness-lock.json").write_text(lock)
    return path


def places(work, env):
    """A repository of each kind under the roots (work/repos), one outside them, and a folder outside any repository."""
    roots = work / "repos"
    desk = work / "desk"
    desk.mkdir()
    return {"plain": git_repo(roots / "plain", env), "full": git_repo(roots / "full", env, vendored=True),
            "thin": git_repo(roots / "thin", env, lock=json.dumps(THIN_LOCK)),
            "outside": git_repo(work / "elsewhere", env), "desk": desk}


def machine(env, *args):
    result = subprocess.run([str(ROOT / "machine.sh")] + list(args), env=env, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError("machine.sh %s: %s" % (" ".join(args), result.stdout + result.stderr))
    return result.stdout


def edit(source, path, cwd, session="s1"):
    """The file edit of each CLI: Claude Code's Write, Codex's apply_patch."""
    if source == "codex":
        patch = "*** Begin Patch\n*** Add File: %s\n+x\n*** End Patch" % path
        return {"session_id": session, "tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(cwd)}
    return {"session_id": session, "tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x\n"},
            "cwd": str(cwd)}


def shell(command, cwd, session="s1"):
    return {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def enrolment_hooks(env, source, plugin):
    """(matcher, command) of the PreToolUse hooks that check enrolment, as the CLI loads them: the user's own, where
    machine.sh adds its guard, and, when the plugin is installed, the plugin's machine-guard hook."""
    path = Path(env["HOME"]) / USER_HOOKS[source]
    groups = list((json.loads(path.read_text()).get("hooks") or {}).get("PreToolUse") or []) if path.exists() else []
    if plugin:
        manifest = json.loads((ROOT / "plugin" / (source + "-hooks.json")).read_text())["hooks"]["PreToolUse"]
        groups += [dict(group, hooks=[hook for hook in group["hooks"] if " hook machine-guard" in hook["command"]])
                   for group in manifest]
    return [(group.get("matcher"), hook["command"]) for group in groups for hook in group["hooks"]]


def cli(env, source, call, plugin=False):
    """What the CLI makes of a tool call after running those hooks: (refused, the messages they gave)."""
    refused, messages = False, []
    for matcher, command in enrolment_hooks(env, source, plugin):
        if not matches(matcher, call["tool_name"]):
            continue
        result = subprocess.run(["sh", "-c", command], cwd=call["cwd"], env=env, input=json.dumps(call),
                                capture_output=True, text=True)
        if result.returncode == 2 and result.stderr.strip():
            refused = True
            messages.append(result.stderr.strip())
        elif result.returncode:
            raise AssertionError("%s exited %d: %s" % (command, result.returncode, result.stderr))
        else:
            output = json.loads(result.stdout) if result.stdout.strip() else {}
            message = output.get("systemMessage") or (output.get("hookSpecificOutput") or {}).get("additionalContext")
            if message:
                messages.append(message)
    return refused, messages


class MachineGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="machine guard ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name).resolve()
        self.home = self.work / "home"
        self.env = environment(self.home, self.work)
        self.roots = self.work / "repos"
        found = places(self.work, self.env)
        self.plain, self.full, self.thin, self.outside = found["plain"], found["full"], found["thin"], found["outside"]

    def install(self, mode, *flags):
        return machine(self.env, "install", "--roots", str(self.roots), "--mode", mode, *flags)

    def user_hooks(self, source):
        return (self.home / USER_HOOKS[source]).read_text()

    def test_a_thin_project_counts_as_enrolled(self):
        self.install("block")
        for source in ("claude", "codex"):
            with self.subTest(source=source):
                self.assertEqual(cli(self.env, source, edit(source, self.thin / "x.py", self.thin)), (False, []))
                self.assertEqual(cli(self.env, source, shell("make", self.thin)), (False, []))
                refused, messages = cli(self.env, source, edit(source, self.plain / "x.py", self.plain))
                self.assertTrue(refused)
                self.assertIn("enroll.sh %s" % self.plain, messages[0])
        self.install("warn")
        self.assertEqual(cli(self.env, "claude", edit("claude", self.thin / "x.py", self.thin, "s2")), (False, []))
        refused, messages = cli(self.env, "claude", edit("claude", self.plain / "x.py", self.plain, "s2"))
        self.assertFalse(refused)
        self.assertIn("is not enrolled in the agentic harness", messages[0])

    def test_the_guard_and_the_plugin_count_as_enrolled_what_the_launcher_runs_an_engine_for(self):
        table = [(state, vendored, enrolled or vendored,
                  git_repo(self.roots / ("table-%d-%s" % (number, vendored)), self.env, vendored, lock))
                 for number, (state, lock, enrolled) in enumerate(LOCKS) for vendored in (False, True)]
        launcher = [subprocess.run(["python3", "-B", str(ROOT / "plugin/launcher.py"), "doctor"], cwd=repo,
                                   env=self.env, capture_output=True, text=True).stderr for *_, repo in table]
        self.install("block")
        guard = [cli(self.env, "claude", edit("claude", repo / "x.py", repo))[0] for *_, repo in table]
        self.install("block", "--plugin")
        plugin = [cli(self.env, "claude", edit("claude", repo / "x.py", repo), plugin=True)[0] for *_, repo in table]
        for (state, vendored, enrolled, _), says, guard_refused, plugin_refused in zip(table, launcher, guard, plugin):
            with self.subTest(lock=state, vendored_engine=vendored):
                self.assertEqual(guard_refused, not enrolled)
                self.assertEqual(plugin_refused, not enrolled)
                self.assertEqual("has no harness installed" in says, not enrolled, says)

    def test_the_plugin_checks_where_no_guard_hook_is_installed(self):
        out = self.install("block", "--plugin")
        self.assertIn("agentic-harness plugin", out)
        for source in ("claude", "codex"):
            with self.subTest(source=source):
                self.assertNotIn("--harness-machine-guard", self.user_hooks(source) if (
                    self.home / USER_HOOKS[source]).exists() else "")
                self.assertEqual(cli(self.env, source, edit(source, self.plain / "x.py", self.plain)), (False, []))
                refused, messages = cli(self.env, source, edit(source, self.plain / "x.py", self.plain), plugin=True)
                self.assertTrue(refused)
                self.assertEqual(len(messages), 1)
                self.assertIn("refused this edit", messages[0])
                self.assertIn("enroll.sh %s" % self.plain, messages[0])
                refused, messages = cli(self.env, source, shell("make", self.plain), plugin=True)
                self.assertTrue(refused)
                self.assertIn("refused this command", messages[0])
                for place in (self.thin, self.full, self.outside):
                    self.assertEqual(cli(self.env, source, edit(source, place / "x.py", place), plugin=True),
                                     (False, []))
                    self.assertEqual(cli(self.env, source, shell("make", place), plugin=True), (False, []))
                enroll = shell("%s ." % shlex.quote(str(ROOT / "enroll.sh")), self.plain)
                self.assertFalse(cli(self.env, source, enroll, plugin=True)[0])
                into = shell("cp notes.txt %s" % shlex.quote(str(self.plain / "notes.txt")), self.thin)
                self.assertTrue(cli(self.env, source, into, plugin=True)[0])

    def test_the_plugin_reminds_once_per_session_and_repository(self):
        self.install("warn", "--plugin")
        for source in ("claude", "codex"):
            with self.subTest(source=source):
                session = "session-" + source
                refused, messages = cli(self.env, source, edit(source, self.plain / "x.py", self.plain, session),
                                        plugin=True)
                self.assertFalse(refused)
                self.assertEqual(len(messages), 1)
                self.assertIn("is not enrolled in the agentic harness", messages[0])
                self.assertEqual(cli(self.env, source, shell("make", self.plain, session), plugin=True), (False, []))
                self.assertEqual(len(cli(self.env, source, shell("make", self.plain, session + "-2"), plugin=True)[1]),
                                 1)

    def test_with_both_a_guard_hook_and_the_plugin_one_of_them_answers(self):
        self.install("block")
        for source in ("claude", "codex"):
            with self.subTest(source=source, mode="block"):
                refused, messages = cli(self.env, source, edit(source, self.plain / "x.py", self.plain), plugin=True)
                self.assertTrue(refused)
                self.assertEqual(len(messages), 1, messages)
        self.install("warn")
        for source in ("claude", "codex"):
            with self.subTest(source=source, mode="warn"):
                session = "both-" + source
                refused, messages = cli(self.env, source, edit(source, self.plain / "x.py", self.plain, session),
                                        plugin=True)
                self.assertEqual(len(messages), 1, messages)
                self.assertEqual(cli(self.env, source, shell("make", self.plain, session), plugin=True), (False, []))

    def test_install_for_the_plugin_takes_out_a_guard_hook_installed_earlier(self):
        settings_path = self.home / USER_HOOKS["claude"]
        settings_path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "true another-tool-hook"}]}]}, "model": "opus"}))
        self.install("block")
        self.assertIn("--harness-machine-guard", self.user_hooks("claude"))
        self.assertIn("--harness-machine-guard", self.user_hooks("codex"))
        out = self.install("block", "--plugin")
        self.assertIn("guard hook removed", out)
        for source in ("claude", "codex"):
            self.assertNotIn("--harness-machine-guard", self.user_hooks(source))
        self.assertIn("another-tool-hook", self.user_hooks("claude"))
        self.assertEqual(json.loads(self.user_hooks("claude"))["model"], "opus")
        self.assertFalse((self.home / ".agentic-harness/guard.py").exists())
        self.assertEqual(json.loads((self.home / ".agentic-harness/machine.json").read_text())["mode"], "block")
        status = machine(self.env, "status")
        self.assertIn('"mode": "block"', status)
        self.assertIn("no guard hook", status)
        self.assertNotIn("guard hook present", status)
        machine(self.env, "remove")
        self.assertEqual(cli(self.env, "claude", edit("claude", self.plain / "x.py", self.plain), plugin=True),
                         (False, []))

    def test_a_guard_error_never_blocks_through_the_plugin(self):
        self.install("block", "--plugin")
        call = edit("claude", self.plain / "x.py", self.plain)
        self.assertTrue(cli(self.env, "claude", call, plugin=True)[0])
        launcher = ["python3", str(ROOT / "plugin/launcher.py"), "hook", "machine-guard"]
        for source in ((), ("--from", "codex")):
            garbled = subprocess.run(launcher + list(source), cwd=self.plain, env=self.env, input="not json",
                                     capture_output=True, text=True)
            self.assertEqual(garbled.returncode, 0, garbled.stderr)
        copy = self.work / "plugin without the guard"
        for part in ("plugin/launcher.py", "tools/machine.py"):
            (copy / part).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / part, copy / part)
        partial = subprocess.run(["python3", str(copy / "plugin/launcher.py"), "hook", "machine-guard"],
                                 cwd=self.plain, env=self.env, input=json.dumps(call), capture_output=True, text=True)
        self.assertEqual((partial.returncode, partial.stdout, partial.stderr), (0, "", ""))
        (self.home / ".agentic-harness/machine.json").write_text("not json")
        self.assertEqual(cli(self.env, "claude", call, plugin=True), (False, []))


if given is None:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")
else:
    class WhoAnswers(unittest.TestCase):
        """One answer per tool call, from the guard hook where machine.sh installed it, otherwise from the plugin."""

        @classmethod
        def setUpClass(cls):
            cls.temp = tempfile.TemporaryDirectory(prefix="machine guard properties ")
            work = Path(cls.temp.name).resolve()
            cls.places = places(work, environment(work / "home", work))
            cls.envs = {}
            for install in ("guard", "plugin", "none"):
                for mode in ("warn", "block"):
                    env = environment(work / ("home %s %s" % (install, mode)), work)
                    if install != "none":
                        machine(env, "install", "--roots", str(work / "repos"), "--mode", mode,
                                *(("--plugin",) if install == "plugin" else ()))
                    cls.envs[install, mode] = env

        @classmethod
        def tearDownClass(cls):
            cls.temp.cleanup()

        def call(self, source, kind, target, cwd):
            session = uuid.uuid4().hex
            if kind == "edit":
                return edit(source, self.places[target] / "x.py", self.places[cwd], session)
            if kind == "shell":
                return shell("make", self.places[cwd], session)
            return shell("cp notes.txt %s" % shlex.quote(str(self.places[target] / "notes.txt")), self.places[cwd],
                         session)

        @settings(max_examples=60, deadline=None)
        @given(install=st.sampled_from(("guard hook", "plugin", "guard hook and plugin", "plugin, no settings")),
               source=st.sampled_from(("claude", "codex")), mode=st.sampled_from(("warn", "block")),
               kind=st.sampled_from(("edit", "shell", "shell into")),
               target=st.sampled_from(("plain", "full", "thin", "outside")),
               cwd=st.sampled_from(("plain", "full", "thin", "outside", "desk")))
        def test_one_hook_answers_and_block_mode_refuses_writes_into_an_unenrolled_repository(
                self, install, source, mode, kind, target, cwd):
            home = {"guard hook": "guard", "plugin": "plugin", "guard hook and plugin": "guard",
                    "plugin, no settings": "none"}[install]
            touched = {"edit": {target}, "shell": {cwd}, "shell into": {target, cwd}}[kind]
            answered = "plain" in touched and home != "none"

            refused, messages = cli(self.envs[home, mode], source, self.call(source, kind, target, cwd),
                                    plugin=install != "guard hook")

            self.assertEqual(refused, answered and mode == "block", messages)
            self.assertEqual(len(messages), 1 if answered else 0, messages)

        @settings(max_examples=30, deadline=None)
        @given(source=st.sampled_from(("claude", "codex")), mode=st.sampled_from(("warn", "block")),
               tool=st.sampled_from(("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "apply_patch", "Read",
                                     "Task")),
               target=st.sampled_from(("plain", "full", "thin", "outside")),
               cwd=st.sampled_from(("plain", "full", "thin", "outside", "desk")))
        def test_the_plugin_answers_as_the_guard_hook(self, source, mode, tool, target, cwd):
            path = self.places[target] / "x.py"
            tool_input = {"Bash": {"command": "touch %s" % shlex.quote(str(path))},
                          "apply_patch": edit("codex", path, self.places[cwd])["tool_input"]}.get(
                tool, {"file_path": str(path), "content": "x\n"})
            call = {"tool_name": tool, "tool_input": tool_input, "cwd": str(self.places[cwd])}

            guard = cli(self.envs["guard", mode], source, dict(call, session_id=uuid.uuid4().hex))
            plugin = cli(self.envs["plugin", mode], source, dict(call, session_id=uuid.uuid4().hex), plugin=True)

            self.assertEqual(plugin, guard)


if __name__ == "__main__":
    unittest.main()
