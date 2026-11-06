"""The machine guard: in a git repository under the roots in ~/.agentic-harness/machine.json that isn't enrolled in
the harness, an agent's edits get a reminder (warn) or are refused (block). The tests install it with machine.sh into
a throwaway home and run the PreToolUse hooks a CLI would run for each tool call."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


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


class MachineGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="machine guard ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name).resolve()
        self.home = self.work / "home"
        for folder in (".claude", ".codex"):
            (self.home / folder).mkdir(parents=True)
        self.roots = self.work / "repos"
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("HARNESS_MACHINE_CONFIG", "CLAUDE_PROJECT_DIR", "HARNESS_ROOT")}
        self.env.update(HOME=str(self.home), GIT_CONFIG_GLOBAL=os.devnull, PYTHONDONTWRITEBYTECODE="1",
                        HARNESS_ENGINES=str(self.work / "engines"), HARNESS_ENGINE_SOURCE=str(self.work / "offline"))
        self.plain = self.repo(self.roots / "plain")
        self.full = self.repo(self.roots / "full")
        (self.full / "scripts/harness/lib").mkdir(parents=True)
        (self.full / "scripts/harness/lib/harness.py").write_text("")
        self.thin = self.repo(self.roots / "thin")
        (self.thin / "backbone").mkdir()
        (self.thin / "backbone/.harness-lock.json").write_text(json.dumps(THIN_LOCK))

    def repo(self, path):
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True, env=self.env)
        return path

    def machine(self, *args):
        result = subprocess.run([str(ROOT / "machine.sh")] + list(args), env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def install(self, mode, *flags):
        return self.machine("install", "--roots", str(self.roots), "--mode", mode, *flags)

    def edit(self, source, path, cwd, session="s1"):
        """The file edit of each CLI: Claude Code's Write, Codex's apply_patch."""
        if source == "codex":
            patch = "*** Begin Patch\n*** Add File: %s\n+x\n*** End Patch" % path
            return {"session_id": session, "tool_name": "apply_patch", "tool_input": {"command": patch},
                    "cwd": str(cwd)}
        return {"session_id": session, "tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x\n"},
                "cwd": str(cwd)}

    def shell(self, command, cwd, session="s1"):
        return {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}

    def hooks(self, source):
        """The PreToolUse hook groups in the user's own settings of the CLI, where machine.sh adds its guard."""
        path = self.home / USER_HOOKS[source]
        if not path.exists():
            return []
        return list((json.loads(path.read_text()).get("hooks") or {}).get("PreToolUse") or [])

    def call(self, source, data):
        """What the CLI makes of a tool call after running its hooks: (refused, the messages the hooks gave)."""
        refused, messages = False, []
        for group in self.hooks(source):
            if not matches(group.get("matcher"), data["tool_name"]):
                continue
            for hook in group["hooks"]:
                result = subprocess.run(["sh", "-c", hook["command"]], cwd=data["cwd"], env=self.env,
                                        input=json.dumps(data), capture_output=True, text=True)
                if result.returncode == 2 and result.stderr.strip():
                    refused = True
                    messages.append(result.stderr.strip())
                    continue
                self.assertEqual(result.returncode, 0, "%s: %s" % (hook["command"], result.stderr))
                output = json.loads(result.stdout) if result.stdout.strip() else {}
                message = (output.get("systemMessage")
                           or (output.get("hookSpecificOutput") or {}).get("additionalContext"))
                if message:
                    messages.append(message)
        return refused, messages

    def test_a_thin_project_counts_as_enrolled(self):
        self.install("block")
        for source in ("claude", "codex"):
            with self.subTest(source=source):
                self.assertEqual(self.call(source, self.edit(source, self.thin / "x.py", self.thin)), (False, []))
                self.assertEqual(self.call(source, self.shell("make", self.thin)), (False, []))
                refused, messages = self.call(source, self.edit(source, self.plain / "x.py", self.plain))
                self.assertTrue(refused)
                self.assertIn("enroll.sh %s" % self.plain, messages[0])
        self.install("warn")
        self.assertEqual(self.call("claude", self.edit("claude", self.thin / "x.py", self.thin, "s2")), (False, []))
        refused, messages = self.call("claude", self.edit("claude", self.plain / "x.py", self.plain, "s2"))
        self.assertFalse(refused)
        self.assertIn("is not enrolled in the agentic harness", messages[0])

    def test_the_guard_counts_as_enrolled_what_the_launcher_runs_an_engine_for(self):
        self.install("block")
        for number, (state, lock, enrolled) in enumerate(LOCKS):
            for vendored in (False, True):
                with self.subTest(lock=state, vendored_engine=vendored):
                    repo = self.repo(self.roots / ("table-%d-%s" % (number, vendored)))
                    if vendored:
                        (repo / "scripts/harness/lib").mkdir(parents=True)
                        (repo / "scripts/harness/lib/harness.py").write_text("")
                    if lock == "folder":
                        (repo / "backbone/.harness-lock.json").mkdir(parents=True)
                    elif lock is not None:
                        (repo / "backbone").mkdir()
                        (repo / "backbone/.harness-lock.json").write_text(lock)
                    launcher = subprocess.run(["python3", "-B", str(ROOT / "plugin/launcher.py"), "doctor"], cwd=repo,
                                              env=self.env, capture_output=True, text=True)
                    refused, _ = self.call("claude", self.edit("claude", repo / "x.py", repo))

                    self.assertEqual(refused, not (enrolled or vendored))
                    self.assertEqual("has no harness installed" in launcher.stderr, refused, launcher.stderr)


if __name__ == "__main__":
    unittest.main()
