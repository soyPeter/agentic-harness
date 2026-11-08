"""The machine guard: in a git repository under the roots in ~/.agentic-harness/machine.json that isn't enrolled in
the harness, an agent's edits get a reminder (warn) or are refused (block). It runs as the hook machine.sh installs or
as the plugin's own hook (launcher.py hook machine-guard). The tests install it with machine.sh into a throwaway home
and run the hooks a CLI would run for each tool call, as Codex runs them only once trusted (the property checks need
hypothesis; the check against Codex's own trust records needs codex on the PATH)."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import queue
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest
import uuid

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


ROOT = Path(__file__).resolve().parents[1]
THIN_LOCK = {"mode": "thin", "version": "9.9.9", "commit": "0" * 40}
# Where each CLI reads its user hooks: the folder its variable names, or its folder in the home.
USER_HOOKS = {"claude": ("CLAUDE_CONFIG_DIR", ".claude", "settings.json"),
              "codex": ("CODEX_HOME", ".codex", "hooks.json")}
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
    env = {key: value for key, value in os.environ.items() if key not in (
        "HARNESS_MACHINE_CONFIG", "CLAUDE_PROJECT_DIR", "HARNESS_ROOT", "CLAUDE_CONFIG_DIR", "CODEX_HOME")}
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


def status_line(env, source):
    """What machine.sh status says about one CLI."""
    return [line for line in machine(env, "status").splitlines() if line.split()[:1] == [source]][0]


def edit(source, path, cwd, session="s1"):
    """The file edit of each CLI: Claude Code's Write, Codex's apply_patch."""
    if source == "codex":
        patch = "*** Begin Patch\n*** Add File: %s\n+x\n*** End Patch" % path
        return {"session_id": session, "tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(cwd)}
    return {"session_id": session, "tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x\n"},
            "cwd": str(cwd)}


def shell(command, cwd, session="s1"):
    return {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def user_hooks(env, source):
    variable, folder, name = USER_HOOKS[source]
    return Path(env.get(variable) or Path(env["HOME"]) / folder) / name


def codex_folder(env):
    """Codex's folder as its hook keys name it: $CODEX_HOME with its symlinks resolved, or ~/.codex as it is."""
    return Path(os.path.realpath(env["CODEX_HOME"])) if env.get("CODEX_HOME") else Path(env["HOME"]) / ".codex"


def codex_hooks(env):
    """{(group, hook): (key, hash)} for the PreToolUse hooks in Codex's user hooks.json: the key Codex keeps a hook's
    trust under, and the hash /hooks records when the user trusts it. Codex 0.164 hashes the hook's normalized identity
    as compact JSON with sorted keys (hook_hash in codex-rs/hooks/src/engine/discovery.rs)."""
    path = user_hooks(env, "codex")
    groups = ((json.loads(path.read_text()).get("hooks") or {}).get("PreToolUse") or []) if path.exists() else []
    found = {}
    for number, group in enumerate(groups):
        for index, hook in enumerate(group["hooks"]):
            identity = {"event_name": "pre_tool_use", "hooks": [{"type": "command", "command": hook["command"],
                                                                  "timeout": max(hook.get("timeout", 600), 1),
                                                                  "async": False}]}
            if group.get("matcher") is not None:
                identity["matcher"] = group["matcher"]
            text = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            found[number, index] = ("%s:pre_tool_use:%d:%d" % (codex_folder(env) / "hooks.json", number, index),
                                    "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest())
    return found


def trust_in_codex(env, enabled=True):
    """What trusting every hook in Codex's /hooks records in its config.toml (enabled=False: then turning them off)."""
    lines = ["[hooks.state]", ""]
    for key, digest in codex_hooks(env).values():
        lines += ["[hooks.state.%s]" % json.dumps(key), 'trusted_hash = "%s"' % digest]
        lines += ([] if enabled else ["enabled = false"]) + [""]
    (codex_folder(env) / "config.toml").write_text("\n".join(lines))


def codex_runs(env):
    """Where the user hooks are that a Codex session runs: the ones trusted as they are now, and not turned off."""
    path = codex_folder(env) / "config.toml"
    records = re.findall(r'^\[hooks\.state\.(".*")\]\ntrusted_hash = "(.*)"\n(enabled = false\n)?',
                         path.read_text() if path.exists() else "", re.M)
    trusted = {json.loads(key): digest for key, digest, off in records if not off}
    return {place for place, (key, digest) in codex_hooks(env).items() if trusted.get(key) == digest}


def plugin_hooks(source):
    """(matcher, command) of the plugin's machine-guard hook."""
    manifest = json.loads((ROOT / "plugin" / (source + "-hooks.json")).read_text())["hooks"]["PreToolUse"]
    return [(group.get("matcher"), hook["command"]) for group in manifest for hook in group["hooks"]
            if " hook machine-guard" in hook["command"]]


def session(env, source, plugin=False, bypass_trust=False):
    """(matcher, command) of the PreToolUse hooks that check enrolment, as a CLI session loads them when it starts: the
    user's own, where machine.sh adds its guard, and, when the plugin is installed, the plugin's machine-guard hook.
    Codex runs a user hook only once the user has trusted it in /hooks, unless the session started with
    --dangerously-bypass-hook-trust."""
    path = user_hooks(env, source)
    groups = list((json.loads(path.read_text()).get("hooks") or {}).get("PreToolUse") or []) if path.exists() else []
    if source == "codex" and not bypass_trust:
        runs = codex_runs(env)
        groups = [dict(group, hooks=[hook for index, hook in enumerate(group["hooks"]) if (number, index) in runs])
                  for number, group in enumerate(groups)]
    hooks = [(group.get("matcher"), hook["command"]) for group in groups for hook in group["hooks"]]
    return hooks + (plugin_hooks(source) if plugin else [])


def cli(env, source, call, plugin=False, hooks=None):
    """What the CLI makes of a tool call after running the hooks of a session started now, or of an earlier one's
    hooks: (refused, the messages they gave)."""
    return at_once(env, source, [call], plugin, hooks)[0]


def at_once(env, source, calls, plugin=False, hooks=None):
    """cli for tool calls that a session runs at the same time. Like Claude Code and Codex, it starts the hook
    processes of every call together, each with its input ready."""
    hooks = session(env, source, plugin) if hooks is None else hooks
    jobs = [(number, command, call) for number, call in enumerate(calls) for matcher, command in hooks
            if matches(matcher, call["tool_name"])]
    processes = []
    for _, command, call in jobs:
        read, write = os.pipe()
        os.write(write, json.dumps(call).encode("utf-8"))
        os.close(write)
        processes.append(subprocess.Popen(["sh", "-c", command], cwd=call["cwd"], env=env, stdin=read,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        os.close(read)
    outputs = [process.communicate() for process in processes]
    answers = [(False, []) for _ in calls]
    for (number, command, _), process, (stdout, stderr) in zip(jobs, processes, outputs):
        refused, messages = answers[number]
        if process.returncode == 2 and stderr.strip():
            answers[number] = (True, messages + [stderr.strip()])
        elif process.returncode:
            raise AssertionError("%s exited %d: %s" % (command, process.returncode, stderr))
        else:
            output = json.loads(stdout) if stdout.strip() else {}
            message = output.get("systemMessage") or (output.get("hookSpecificOutput") or {}).get("additionalContext")
            answers[number] = (refused, messages + ([message] if message else []))
    return answers


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

    def install(self, mode, *flags, trust=True):
        """machine.sh install, then trusting the new hook in Codex's /hooks as install asks (trust=False: not yet)."""
        out = machine(self.env, "install", "--roots", str(self.roots), "--mode", mode, *flags)
        if trust:
            trust_in_codex(self.env)
        return out

    def user_hooks(self, source):
        path = user_hooks(self.env, source)
        return path.read_text() if path.exists() else ""

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
                self.assertNotIn("--harness-machine-guard", self.user_hooks(source))
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
        """Also one that Codex doesn't run yet, because nobody trusted it in /hooks."""
        user_hooks(self.env, "claude").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "true another-tool-hook"}]}]}, "model": "opus"}))
        self.install("block", trust=False)
        self.assertIn("--harness-machine-guard", self.user_hooks("claude"))
        self.assertIn("--harness-machine-guard", self.user_hooks("codex"))
        out = self.install("block", "--plugin")
        self.assertIn("guard hook removed", out)
        for source in ("claude", "codex"):
            self.assertNotIn("--harness-machine-guard", self.user_hooks(source))
        self.assertIn("another-tool-hook", self.user_hooks("claude"))
        self.assertEqual(json.loads(self.user_hooks("claude"))["model"], "opus")
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

    def open_sessions(self):
        return {(source, plugin): session(self.env, source, plugin)
                for source in ("claude", "codex") for plugin in (False, True)}

    def test_a_session_open_during_install_for_the_plugin_still_lets_through_what_the_guard_allows(self):
        """Claude Code and Codex load hooks when a session starts, so a session open during install --plugin keeps
        calling the guard hook that install takes out of the settings."""
        self.install("block")
        sessions = self.open_sessions()
        self.install("block", "--plugin")
        for (source, plugin), hooks in sessions.items():
            with self.subTest(source=source, plugin=plugin):
                for place in (self.thin, self.full, self.outside):
                    self.assertEqual(cli(self.env, source, edit(source, place / "x.py", place), hooks=hooks),
                                     (False, []))
                    self.assertEqual(cli(self.env, source, shell("make", place), hooks=hooks), (False, []))
                refused, messages = cli(self.env, source, edit(source, self.plain / "x.py", self.plain), hooks=hooks)
                self.assertTrue(refused)
                for message in messages:
                    self.assertIn("refused this edit", message)

    def test_a_session_open_during_remove_is_no_longer_checked(self):
        self.install("block")
        sessions = self.open_sessions()
        machine(self.env, "remove")
        for (source, plugin), hooks in sessions.items():
            with self.subTest(source=source, plugin=plugin):
                for place in (self.plain, self.thin, self.full, self.outside):
                    self.assertEqual(cli(self.env, source, edit(source, place / "x.py", place), hooks=hooks),
                                     (False, []))
                self.assertEqual(cli(self.env, source, shell("make", self.plain), hooks=hooks), (False, []))

    def test_machine_sh_puts_the_guard_hook_where_each_cli_reads_its_settings(self):
        env = dict(self.env, CLAUDE_CONFIG_DIR=str(self.work / "claude config"),
                   CODEX_HOME=str(self.work / "codex home"))
        for source in ("claude", "codex"):
            Path(env[USER_HOOKS[source][0]]).mkdir()
        machine(env, "install", "--roots", str(self.roots), "--mode", "block")
        trust_in_codex(env)
        for source in ("claude", "codex"):
            with self.subTest(source=source):
                refused, messages = cli(env, source, edit(source, self.plain / "x.py", self.plain))
                self.assertEqual((refused, len(messages)), (True, 1), messages)
        self.assertEqual(machine(env, "status").count("guard hook present"), 2)
        machine(env, "remove")
        for source in ("claude", "codex"):
            self.assertNotIn("--harness-machine-guard", user_hooks(env, source).read_text())

    def test_the_plugin_leaves_the_check_only_to_a_guard_hook_the_cli_loads(self):
        """Claude Code reads its user settings in CLAUDE_CONFIG_DIR and Codex in CODEX_HOME when they are set, and a
        session's environment can differ from the one machine.sh ran in. With the plugin, an edit in a repository that
        isn't enrolled gets one refusal wherever each of them looked, once the user has trusted in Codex the hooks it
        lists."""
        for source, flags, for_machine_sh, for_the_cli in itertools.product(
                ("claude", "codex"), ((), ("--plugin",)), (False, True), (False, True)):
            with self.subTest(source=source, flags=flags, set_for_machine_sh=for_machine_sh,
                              set_for_the_cli=for_the_cli):
                base = self.work / uuid.uuid4().hex
                default = environment(base / "home", self.work)
                elsewhere = dict(default, **{USER_HOOKS[source][0]: str(base / "elsewhere")})
                (base / "elsewhere").mkdir()
                machine(elsewhere if for_machine_sh else default, "install", "--roots", str(self.roots),
                        "--mode", "block", *flags)
                trust_in_codex(elsewhere if for_the_cli else default)
                refused, messages = cli(elsewhere if for_the_cli else default, source,
                                        edit(source, self.plain / "x.py", self.plain), plugin=True)
                self.assertEqual((refused, len(messages)), (True, 1), messages)

    def test_until_codex_trusts_the_guard_hook_the_plugin_refuses_in_its_place(self):
        """Codex runs a new user hook only once the user has trusted it in /hooks: a guard hook installed without that
        step never runs there, so the plugin doesn't wait for it."""
        self.install("block", trust=False)
        call = edit("codex", self.plain / "x.py", self.plain)
        refused, messages = cli(self.env, "codex", call, plugin=True)
        self.assertEqual((refused, len(messages)), (True, 1), messages)
        self.assertIn("enroll.sh %s" % self.plain, messages[0])
        trust_in_codex(self.env)
        for plugin in (True, False):
            with self.subTest(trusted_and_plugin=plugin):
                refused, messages = cli(self.env, "codex", call, plugin=plugin)
                self.assertEqual((refused, len(messages)), (True, 1), messages)

    def test_until_codex_trusts_the_guard_hook_the_plugin_reminds_once_per_session(self):
        self.install("warn", trust=False)
        refused, messages = cli(self.env, "codex", edit("codex", self.plain / "x.py", self.plain, "w1"), plugin=True)
        self.assertEqual((refused, len(messages)), (False, 1), messages)
        self.assertIn("is not enrolled in the agentic harness", messages[0])
        self.assertEqual(cli(self.env, "codex", shell("make", self.plain, "w1"), plugin=True), (False, []))

    def test_the_plugin_checks_again_when_codex_stops_running_the_guard_hook(self):
        """Codex runs a trusted hook only while it stays as it was trusted, where it was trusted, and switched on.
        Installing it again writes the same hook, which Codex goes on trusting."""
        self.install("block")
        self.install("block", trust=False)
        call = edit("codex", self.plain / "x.py", self.plain)
        self.assertEqual(cli(self.env, "codex", call)[0], True)

        def turned_off(hooks):
            trust_in_codex(self.env, enabled=False)
            return hooks

        def changed(hooks):
            hooks["hooks"]["PreToolUse"][-1]["hooks"][0]["timeout"] = 20
            return hooks

        def moved(hooks):
            hooks["hooks"]["PreToolUse"].insert(0, {"matcher": "Bash", "hooks": [{"type": "command",
                                                                                  "command": "true"}]})
            return hooks

        for change in (turned_off, changed, moved):
            with self.subTest(change=change.__name__):
                self.install("block")
                user_hooks(self.env, "codex").write_text(json.dumps(change(json.loads(self.user_hooks("codex")))))
                refused, messages = cli(self.env, "codex", call, plugin=True)
                self.assertEqual((refused, len(messages)), (True, 1), messages)

    def test_machine_sh_status_says_whether_codex_runs_the_guard_hook(self):
        self.install("block", trust=False)
        self.assertIn("not trusted", status_line(self.env, "codex"))
        self.assertIn("/hooks", status_line(self.env, "codex"))
        self.assertNotIn("guard hook present", status_line(self.env, "codex"))
        trust_in_codex(self.env)
        self.assertIn("guard hook present", status_line(self.env, "codex"))
        self.assertNotIn("not trusted", status_line(self.env, "codex"))
        trust_in_codex(self.env, enabled=False)
        self.assertIn("turned off", status_line(self.env, "codex"))
        trust_in_codex(self.env)
        installed = json.loads(self.user_hooks("codex"))
        installed["hooks"]["PreToolUse"][-1]["hooks"][0]["timeout"] = 20
        user_hooks(self.env, "codex").write_text(json.dumps(installed))
        self.assertIn("changed since", status_line(self.env, "codex"))
        self.assertIn("guard hook present", status_line(self.env, "claude"))

    def test_a_codex_session_that_bypasses_hook_trust_is_reminded_once_per_session(self):
        """codex --dangerously-bypass-hook-trust runs the guard hook nobody trusted, and the plugin, which can't see the
        flag, answers as well: both run at once for each call."""
        self.install("warn", trust=False)
        hooks = session(self.env, "codex", plugin=True, bypass_trust=True)
        for number in range(8):
            with self.subTest(session=number):
                call = edit("codex", self.plain / "x.py", self.plain, "bypass-%d" % number)
                refused, messages = cli(self.env, "codex", call, hooks=hooks)
                self.assertEqual((refused, len(messages)), (False, 1), messages)
        self.install("block", trust=False)
        refused, messages = cli(self.env, "codex", edit("codex", self.plain / "x.py", self.plain), hooks=hooks)
        self.assertEqual((refused, len(messages)), (True, 2), messages)
        for message in messages:
            self.assertIn("refused this edit", message)

    def test_calls_a_session_runs_at_once_get_one_reminder(self):
        """Claude Code and Codex can run a session's tool calls in parallel, as they run a call's hooks: the guard
        hooks and the plugin share one record of the reminders given, so the session is still reminded once."""
        self.install("warn")
        for source, number in itertools.product(("claude", "codex"), range(10)):
            with self.subTest(source=source, session=number):
                name = "parallel-%s-%d" % (source, number)
                calls = [edit(source, self.plain / ("x%d.py" % index), self.plain, name) for index in range(5)]
                answers = at_once(self.env, source, calls, plugin=True)
                self.assertEqual(sum(len(messages) for _, messages in answers), 1, answers)

    def test_settings_whose_roots_or_exempt_are_not_lists_of_folders_check_nothing(self):
        """A string in place of the list of roots put every repository on the machine in scope: the guard went through
        its characters, and "/" holds every path. Settings like that are reported, and nothing is checked."""
        self.install("block")
        settings = self.home / ".agentic-harness/machine.json"
        written = json.loads(settings.read_text())
        for name, value in (("roots", str(self.roots)), ("exempt", str(ROOT)), ("roots", [str(self.roots), 7]),
                            ("exempt", None)):
            with self.subTest(name=name, value=value):
                settings.write_text(json.dumps(dict(written, **{name: value})))
                for source, plugin, place in itertools.product(("claude", "codex"), (False, True),
                                                               (self.plain, self.outside)):
                    self.assertEqual(cli(self.env, source, edit(source, place / "x.py", place), plugin=plugin),
                                     (False, []))
                self.assertIn('"%s" must be a list of folders' % name, machine(self.env, "status"))


class CodexAppServer:
    """`codex app-server` in a throwaway home: the hooks as Codex itself lists them, and the trust /hooks records."""

    def __init__(self, env):
        env = {key: value for key, value in env.items() if key not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
        self.process = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, env=env)
        self.replies = queue.Queue()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        self.number = 0
        self.request("initialize", {"clientInfo": {"name": "agentic-harness-tests", "version": "0"}})
        self.send({"method": "initialized"})

    def read(self):
        for line in self.process.stdout:
            try:
                self.replies.put(json.loads(line))
            except ValueError:
                pass

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.number += 1
        self.send({"id": self.number, "method": method, "params": params})
        while True:
            reply = self.replies.get(timeout=60)
            if reply.get("id") == self.number and ("result" in reply or "error" in reply):
                return reply

    def guard_hook(self, cwd):
        reply = self.request("hooks/list", {"cwds": [str(cwd)]})
        if "error" in reply:
            raise unittest.SkipTest("this Codex can't list its hooks: %s" % reply["error"])
        found = [hook for entry in reply["result"]["data"] for hook in entry["hooks"]
                 if "--harness-machine-guard" in (hook.get("command") or "")]
        if len(found) != 1:
            raise AssertionError("Codex lists %d guard hooks: %s" % (len(found), reply))
        return found[0]

    def record(self, key, state):
        reply = self.request("config/batchWrite", {"edits": [{"keyPath": "hooks.state", "value": {key: state},
                                                              "mergeStrategy": "upsert"}], "reloadUserConfig": True})
        if "result" not in reply:
            raise AssertionError("Codex didn't record %s: %s" % (state, reply))

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=10)
        self.process.stdout.close()


@unittest.skipUnless(shutil.which("codex"), "needs codex on the PATH")
class CodexTrust(unittest.TestCase):
    """The plugin against Codex's own trust records: `codex app-server` lists the guard hook as Codex sees it and
    records trust and the on/off switch as /hooks does."""

    def test_the_plugin_leaves_the_check_to_the_guard_hook_exactly_while_codex_runs_it(self):
        steps = (("installed", None), ("trusted", lambda hook: {"trusted_hash": hook["currentHash"]}),
                 ("turned off", lambda hook: {"enabled": False}), ("switched on", lambda hook: {"enabled": True}))
        for codex_home in (None, "a link to the codex home"):
            with self.subTest(CODEX_HOME=codex_home):
                temp = tempfile.TemporaryDirectory(prefix="machine guard codex ")
                self.addCleanup(temp.cleanup)
                work = Path(temp.name).resolve()
                env = environment(work / "home", work)
                if codex_home:
                    (work / "codex home").mkdir()
                    (work / codex_home).symlink_to(work / "codex home")
                    env["CODEX_HOME"] = str(work / codex_home)
                plain = git_repo(work / "repos" / "plain", env)
                machine(env, "install", "--roots", str(work / "repos"), "--mode", "block")
                codex = CodexAppServer(env)
                self.addCleanup(codex.close)
                runs = []
                for step, state in steps:
                    if state:
                        hook = codex.guard_hook(plain)
                        codex.record(hook["key"], state(hook))
                    hook = codex.guard_hook(plain)
                    runs.append(hook["enabled"] and hook["trustStatus"] == "trusted")
                    refused, messages = cli(env, "codex", edit("codex", plain / "x.py", plain),
                                            hooks=plugin_hooks("codex"))
                    status = status_line(env, "codex")
                    self.assertEqual((refused, "guard hook present" in status), (not runs[-1], runs[-1]),
                                     (step, hook, messages, status))
                self.assertEqual(runs, [False, True, False, True])


if given is None:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")
else:
    class WhoAnswers(unittest.TestCase):
        """One answer per tool call, from the guard hook where machine.sh installed it and the CLI runs it, otherwise
        from the plugin."""

        @classmethod
        def setUpClass(cls):
            cls.temp = tempfile.TemporaryDirectory(prefix="machine guard properties ")
            work = cls.work = Path(cls.temp.name).resolve()
            cls.places = places(work, environment(work / "home", work))
            roots = str(work / "repos")
            cls.changes = {"nothing (status)": ("status",), "remove": ("remove",)}
            for mode, plugin in itertools.product(("warn", "block"), ((), ("--plugin",))):
                cls.changes[" ".join(("install", mode) + plugin)] = (
                    ("install", "--roots", roots, "--mode", mode) + plugin)
            cls.envs = {}
            for install in ("guard", "guard not trusted in Codex", "plugin", "none"):
                for mode in ("warn", "block"):
                    env = environment(work / ("home %s %s" % (install, mode)), work)
                    if install != "none":
                        machine(env, "install", "--roots", str(work / "repos"), "--mode", mode,
                                *(("--plugin",) if install == "plugin" else ()))
                    if install == "guard":
                        trust_in_codex(env)
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
        @given(install=st.sampled_from(("guard hook", "plugin", "guard hook and plugin",
                                        "guard hook not trusted in Codex, and plugin", "plugin, no settings")),
               source=st.sampled_from(("claude", "codex")), mode=st.sampled_from(("warn", "block")),
               kind=st.sampled_from(("edit", "shell", "shell into")),
               target=st.sampled_from(("plain", "full", "thin", "outside")),
               cwd=st.sampled_from(("plain", "full", "thin", "outside", "desk")))
        def test_one_hook_answers_and_block_mode_refuses_writes_into_an_unenrolled_repository(
                self, install, source, mode, kind, target, cwd):
            home = {"guard hook": "guard", "plugin": "plugin", "guard hook and plugin": "guard",
                    "guard hook not trusted in Codex, and plugin": "guard not trusted in Codex",
                    "plugin, no settings": "none"}[install]
            touched = {"edit": {target}, "shell": {cwd}, "shell into": {target, cwd}}[kind]
            answered = "plain" in touched and home != "none"

            refused, messages = cli(self.envs[home, mode], source, self.call(source, kind, target, cwd),
                                    plugin=install != "guard hook")

            self.assertEqual(refused, answered and mode == "block", messages)
            self.assertEqual(len(messages), 1 if answered else 0, messages)

        @settings(max_examples=40, deadline=None)
        @given(before=st.sampled_from(("nothing (status)", "install warn", "install block", "install warn --plugin",
                                       "install block --plugin")),
               after=st.sampled_from(("install warn", "install block", "install warn --plugin",
                                      "install block --plugin", "remove")),
               plugin=st.booleans(), source=st.sampled_from(("claude", "codex")),
               kind=st.sampled_from(("edit", "shell", "shell into")),
               target=st.sampled_from(("plain", "full", "thin", "outside")),
               cwd=st.sampled_from(("plain", "full", "thin", "outside", "desk")))
        def test_a_session_open_while_machine_sh_changes_the_install_refuses_only_writes_into_unenrolled_repositories(
                self, before, after, plugin, source, kind, target, cwd):
            env = environment(self.work / uuid.uuid4().hex, self.work)
            machine(env, *self.changes[before])
            trust_in_codex(env)
            hooks = session(env, source, plugin)
            machine(env, *self.changes[after])
            touched = {"edit": {target}, "shell": {cwd}, "shell into": {target, cwd}}[kind]

            refused, messages = cli(env, source, self.call(source, kind, target, cwd), hooks=hooks)

            self.assertTrue(not refused or (after.startswith("install block") and "plain" in touched), messages)
            for message in messages:
                self.assertIn("is not enrolled in the agentic harness", message)

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
