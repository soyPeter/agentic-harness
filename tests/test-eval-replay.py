"""harness.py eval (ADR-002 follow-up (c)): the hook inputs the gates refused, and a bounded sample of those they
allowed, kept for replay; report candidates with ids and the inputs behind them; fixtures exported for review; and
`eval replay`, which runs the state-free fixtures through `hook pre-tool-use` with this engine or another one.

Everything runs through the public entry points (hook JSON on stdin, harness.py report, eval and verify) in throwaway
projects. The property checks need hypothesis (pip install -r tests/requirements.txt); the rest runs without it.
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hypothesis_profiles import examples  # noqa: E402

try:
    from hypothesis import assume, example, given, settings, strategies as st
except ImportError:
    given = None

ROOT = Path(__file__).resolve().parents[1]
ENGINE = "scripts/harness/lib/harness.py"
SPEC = """# Spec {task}: Item

## Context
Needed.

## Requirements
- REQ-{task}-1: The system shall do one thing.

## Acceptance criteria
- AC-{task}-1 (REQ-{task}-1): Given a, when b, then c.

## Non-functional requirements
- none

## Architecture
ADRs: ADR-001
Tech requirements:
- src/

## Skills
- code-quality: all code

## Open questions
- none
"""
SECRETS = {
    "aws": "AKIAQ7X3MPLE9KEY0Z4W",
    "github": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "anthropic": "sk-ant-api03-" + "Zq9" * 12,
    "slack": "xoxb-1234567890-abcdefGHIJKL",
    "pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7s9WbG2+fake+key+body+lines\nQ0x9mZ=\n"
           "-----END RSA PRIVATE KEY-----",
    "env": "s3cr3t-Value-77",
    "url": "pa55-in-url",
    "bearer": "tok3n.Bearer.Value",
}

PLANTED = (   # (where the secret sits, the secret): every shape a review found passing the first redaction
    ("aws_secret_access_key=%s aws s3 ls", "Zq81wLxs9VbT2mKp7RfY"),
    ("password=%s ./run", "Zq82hunter2-Kp7"),
    ("DB_PASS=%s ./run", "Zq83dbpass"),
    ("export db_password='%s and more'", "Zq84 with space"),
    ("API_TOKEN=\"%s$HOME\" ./run", "Zq85$dollar"),
    ("mysql -u root -p%s shop", "Zq86mysqlpw"),
    ("curl -u admin:%s https://example.com", "Zq87curlpw"),
    ("curl --user admin:%s https://example.com", "Zq88curlpw"),
    ("./deploy --password %s", "Zq89flagpw"),
    ("./deploy --token=%s", "Zq90flagtok"),
    ("echo '{\"password\": \"%s\"}'", "Zq91jsonpw"),
    ("curl -H 'X-Api-Key: %s' https://example.com", "Zq92apikey"),
    ("echo %s", "sk_live_" + "51HZq93StripeLiveKeyAbCdEf"),
    ("echo %s", "AIza" + "SyZq94GoogleKeyAbCdEfGhIjKlMnOpQrS"),
    ("echo %s", "npm_" + "Zq95NpmTokenAbCdEfGhIjKlMnOpQrStUvWx"),
    ("echo %s", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJacTk2In0.Zq96SignatureAbCdEfGhIjKlMnOp"),
    ("cat <<EOF\n%s\nEOF", "-----BEGIN PGP PRIVATE KEY BLOCK-----\n\nlQOYBGZq97PgpKeyBodyLine\n=Zq97\n"
                           "-----END PGP PRIVATE KEY BLOCK-----"),
    ("cat <<EOF\n%s\nEOF", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktZq98\n"
                           "-----END OPENSSH PRIVATE KEY-----"),
    ("echo %s", "Zq99x8Kd02LmQwTz7Rv4Yp1Nb6Hc3Js5Fg"),
)


def secret_command(kind, secret):
    """A refused shell command (git reset --hard) that carries secret where that kind of secret is usually found."""
    holder = {"env": "export DEPLOY_API_TOKEN=%s", "url": "git clone https://bot:%s@example.com/o/r.git",
              "bearer": "curl -H 'Authorization: Bearer %s' https://example.com"}.get(kind, "echo '%s'")
    return "git reset --hard HEAD~1; " + holder % secret


TEMPLATE = []   # one bootstrapped project, copied for each test


def base_env():
    """The test's environment without the developer's harness settings or GitHub login: no test reaches GitHub."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HARNESS_", "CLAUDE_")) and k not in (
        "TRIPLE_MODE", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com", HARNESS_TEST_CMD="true",
               HARNESS_REVIEW="off", HARNESS_DELIVER="off", PYTHONDONTWRITEBYTECODE="1",
               GH_CONFIG_DIR=os.path.join(tempfile.gettempdir(), "eval-replay-no-gh-login"))
    return env


def template():
    if not TEMPLATE:
        folder = Path(tempfile.mkdtemp(prefix="eval template ")).resolve()
        project = folder / "project"
        project.mkdir()
        env = dict(base_env(), CLAUDE_PROJECT_DIR=str(project), HARNESS_VERIFY="off")
        for args in (["git", "init", "-q", "-b", "main"], [str(ROOT / "bootstrap.sh"), str(project), "--name", "evals"],
                     ["git", "add", "-A"], ["git", "commit", "-qm", "chore: adopt agentic harness"]):
            result = subprocess.run(args, cwd=str(project), env=env, capture_output=True, text=True)
            if result.returncode != 0:
                shutil.rmtree(str(folder), ignore_errors=True)
                raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(args), result.returncode, result.stdout,
                                                                     result.stderr))
        TEMPLATE.append(folder)
    return TEMPLATE[0] / "project"


def tearDownModule():
    for folder in TEMPLATE:
        shutil.rmtree(str(folder), ignore_errors=True)


class Project(unittest.TestCase):
    """A bootstrapped project per test (a copy of one bootstrap), driven through its hooks and commands."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eval replay ")
        self.addCleanup(self.temp.cleanup)
        self.outside = Path(self.temp.name).resolve()
        self.project = self.outside / "project"
        shutil.copytree(str(template()), str(self.project), symlinks=True)
        self.env = dict(base_env(), CLAUDE_PROJECT_DIR=str(self.project))

    def run_command(self, *args, input=None, env=None, cwd=None, check=False):
        result = subprocess.run(args, cwd=str(cwd or self.project), env=dict(self.env, **(env or {})), input=input,
                                capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(map(str, args)), result.returncode,
                                                                 result.stdout, result.stderr))
        return result

    def harness(self, *args, **kwargs):
        return self.run_command("python3", "-B", str(self.project / ENGINE), *args, **kwargs)

    def pre(self, tool, tool_input, env=None, **fields):
        data = dict({"session_id": "s1", "tool_name": tool, "tool_input": tool_input, "cwd": str(self.project)},
                    **fields)
        return self.harness("hook", "pre-tool-use", input=json.dumps(data), env=env)

    def bash(self, command, env=None, **fields):
        return self.pre("Bash", {"command": command}, env=env, **fields)

    def write(self, path, content, env=None, **fields):
        return self.pre("Write", {"file_path": str(self.project / path), "content": content}, env=env, **fields)

    def blocked(self, result):
        self.assertEqual(result.returncode, 2, "expected a refusal:\n%s%s" % (result.stdout, result.stderr))
        return result.stderr

    def allowed(self, result):
        self.assertEqual(result.returncode, 0, "expected the call through:\n%s%s" % (result.stdout, result.stderr))

    def export(self, *args, out=None, check=True):
        """The fixtures `eval export` writes into out (a new folder outside the project unless given)."""
        out = Path(out) if out else Path(tempfile.mkdtemp(prefix="evals-", dir=str(self.outside)))
        result = self.harness("eval", "export", *args, "--out", str(out))
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return out, self.fixtures(out), result

    @staticmethod
    def fixtures(folder):
        return {p.name: json.loads(p.read_text()) for p in sorted(Path(folder).glob("**/*.json"))}

    def replay(self, folder, *args):
        result = self.harness("eval", "replay", str(folder), "--json", *args)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            self.fail("eval replay --json printed no JSON (exit %d):\n%s%s" % (result.returncode, result.stdout,
                                                                             result.stderr))
        return result, data

    @staticmethod
    def status_of(data, fixture_id):
        found = [r["status"] for r in data["results"] if r["id"] == fixture_id]
        assert found, "no result for %s in %s" % (fixture_id, data)
        return found[0]

    @staticmethod
    def by_command(fixtures, command):
        found = [f for f in fixtures.values() if f["kind"] != "prompt"
                 and f["call"]["input"].get("tool_input", {}).get("command") == command]
        assert len(found) == 1, "expected one fixture for %r, got %d" % (command, len(found))
        return found[0]

    def keep_fixtures(self, folder, commit=True):
        """What the user does with drafts they keep: copy them into backbone/evals/ and commit them."""
        evals = self.project / "backbone/evals"
        evals.mkdir(parents=True, exist_ok=True)
        for path in Path(folder).glob("*.json"):
            shutil.copyfile(str(path), str(evals / path.name))
        if commit:
            self.run_command("git", "add", "backbone/evals", check=True)
            self.run_command("git", "commit", "-qm", "test(evals): keep fixtures", env={"HARNESS_VERIFY": "off"},
                             check=True)
        return evals

    def add_rule(self, line):
        conf = self.project / "backbone/guardrails.conf"
        conf.write_text(conf.read_text() + line + "\n")

    def drop_rule(self, line):
        conf = self.project / "backbone/guardrails.conf"
        conf.write_text(conf.read_text().replace(line + "\n", ""))

    def set_tasks(self, lines):
        tasks = self.project / "backbone/3-TASKS.md"
        text = re.sub(r"(?m)^- \[[^\]]*\] \*\*Task .*\n", "", tasks.read_text())
        tasks.write_text(text + "".join(line + "\n" for line in lines))

    @staticmethod
    def secret_lines(secret):
        """The parts of secret that must not be kept: a key's BEGIN and END lines stay, so its rule still fires."""
        return [line for line in secret.splitlines() if len(line) >= 8 and not line.startswith("-----")]

    def harness_files(self):
        """Every file the harness keeps for this project, as text: its records in the git folder, and drafts."""
        files = [p for folder in (self.project / ".git/harness", self.project / "backbone/proposals")
                 for p in folder.rglob("*") if p.is_file()]
        return {p: p.read_text(errors="replace") for p in files}

    def kept_and_printed(self):
        """What the harness keeps and prints about the calls made: its files, eval export's default output and
        report --json."""
        printed = [self.harness("eval", "export", what).stdout for what in ("--refusals", "--allows")]
        printed.append(self.harness("report", "--json").stdout)
        return dict(self.harness_files(), **{"printed by command %d" % i: text for i, text in enumerate(printed)})

    def plant(self, command):
        """command run, and written into a file, where the gates refuse it and where they may let it through (the
        guardrails refuse some secrets anywhere)."""
        self.blocked(self.bash("git reset --hard; " + command))
        self.bash(command)
        self.blocked(self.write("backbone/tools.conf", command + "\n"))
        self.write("docs/notes.md", command + "\n", agent_id="a1", agent_type="implementer")


class Capture(Project):
    def test_a_refused_call_is_kept_for_replay_outside_the_work_tree(self):
        self.blocked(self.bash("git reset --hard HEAD~1"))
        self.assertEqual(self.run_command("git", "status", "--porcelain").stdout, "", "nothing new in the work tree")
        _, fixtures, _ = self.export("--refusals")
        fixture = self.by_command(fixtures, "git reset --hard HEAD~1")
        self.assertEqual(fixture["kind"], "refusal")
        self.assertEqual(fixture["expect"]["outcome"], "blocked")
        self.assertIn("git reset --hard discards uncommitted work", fixture["expect"]["reason"])
        self.assertEqual(fixture["call"]["input"]["tool_name"], "Bash")
        self.assertEqual(fixture["replay"]["state"], "free")
        self.assertEqual(fixture["call"]["env"], {"HARNESS_DELIVER": "off", "HARNESS_REVIEW": "off"},
                         "the environment's settings, without the commands (HARNESS_TEST_CMD)")
        provenance = fixture["provenance"]
        self.assertTrue(provenance["captures"] and provenance["engine"] and provenance["settings"]["fingerprint"])
        self.assertIn("redacted", fixture["redaction"].lower())

    def test_the_project_folder_is_kept_as_a_placeholder_not_as_this_machine_s_path(self):
        self.blocked(self.write("backbone/tools.conf", "Bash read\n"))
        _, fixtures, _ = self.export("--refusals")
        text = json.dumps(fixtures)
        self.assertNotIn(str(self.project), text)
        self.assertNotIn(str(self.outside), text)

    def test_secrets_never_reach_the_captures_events_fixtures_or_report(self):
        for kind, secret in SECRETS.items():
            with self.subTest(kind=kind):
                self.blocked(self.bash(secret_command(kind, secret)))
                self.allowed(self.bash("echo done; " + secret_command(kind, secret).split("; ", 1)[1]))
        self.blocked(self.write("src/%s.txt" % SECRETS["github"], "a note"))
        out, fixtures, _ = self.export("--refusals")
        self.export("--allows", out=out)
        report = self.harness("report", "--json").stdout
        texts = dict(self.harness_files(), report=report,
                     **{name: json.dumps(f) for name, f in self.fixtures(out).items()})
        for kind, secret in SECRETS.items():
            for name, text in texts.items():
                for part in self.secret_lines(secret):
                    self.assertNotIn(part, text, "the %s secret leaked into %s" % (kind, name))

    def test_a_redacted_secret_still_trips_the_rule_that_refused_it(self):
        for name, content in (("aws.py", "KEY = '%s'\n" % SECRETS["aws"]), ("key.py", SECRETS["pem"] + "\n")):
            with self.subTest(file=name):
                self.blocked(self.write("src/" + name, content, agent_id="a1", agent_type="implementer"))
        out, fixtures, _ = self.export("--refusals")
        self.assertEqual(len(fixtures), 2)
        for fixture in fixtures.values():
            self.assertNotIn(SECRETS["aws"], json.dumps(fixture))
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(data["counts"].get("as-expected"), 2, data)

    def test_allowed_calls_are_a_bounded_sample_per_gate(self):
        for n in range(25):
            self.allowed(self.bash("ls folder-%d" % n))
        self.allowed(self.pre("mcp__tracker__list_issues", {"team": "core"}))
        _, fixtures, _ = self.export("--allows")
        shell = [f for f in fixtures.values() if f["call"]["input"]["tool_name"] == "Bash"]
        tools = [f for f in fixtures.values() if f["call"]["input"]["tool_name"] != "Bash"]
        self.assertEqual(len(shell), 20, "the newest 20 allowed shell commands are kept")
        self.assertIn("ls folder-24", [f["call"]["input"]["tool_input"]["command"] for f in shell])
        self.assertNotIn("ls folder-0", [f["call"]["input"]["tool_input"]["command"] for f in shell])
        self.assertEqual(len(tools), 1)
        self.assertTrue(all(f["kind"] == "allow" and f["expect"]["outcome"] == "allowed" for f in fixtures.values()))

    def test_an_allowed_file_change_keeps_its_path_size_and_digest_not_its_content(self):
        implementer = dict(agent_id="a1", agent_type="implementer")
        self.allowed(self.write("docs/notes.md", "host=db\napi=Zq77NotNamedAsASecret\n", **implementer))
        self.allowed(self.pre("Edit", {"file_path": str(self.project / "docs/notes.md"), "old_string": "db",
                                       "new_string": "Zq78NewText"}, **implementer))
        _, fixtures, result = self.export("--allows")
        self.assertEqual(fixtures, {}, "an allowed file change isn't replayed")
        self.assertIn("path, size and digest", result.stdout)
        kept = self.kept_and_printed()
        for text in ("Zq77NotNamedAsASecret", "Zq78NewText"):
            for name, content in kept.items():
                self.assertNotIn(text, content, "an allowed change's content was kept in %s" % name)
        self.assertTrue(any("docs/notes.md" in content for content in kept.values()), "its path is kept")

    def test_no_planted_secret_reaches_the_captures_drafts_exports_or_report(self):
        for holder, secret in PLANTED:
            self.plant(holder % secret)
        kept = self.kept_and_printed()
        for holder, secret in PLANTED:
            for part in self.secret_lines(secret):
                for name, text in kept.items():
                    self.assertNotIn(part, text, "%r leaked into %s" % (holder % secret, name))

    def test_export_writes_no_fixture_that_still_holds_a_secret(self):
        """A capture an engine with a narrower redaction kept: export leaves it out rather than write it."""
        self.blocked(self.bash("git reset --hard"))
        (path,) = (self.project / ".git/harness/captures").rglob("*.json")
        record = json.loads(path.read_text())
        record["call"]["input"]["tool_input"]["command"] = "git reset --hard; export STRIPE=sk_live_51Zq55AbCdEfGhIjKl"
        path.write_text(json.dumps(record))
        out, fixtures, result = self.export("--refusals")
        self.assertEqual(fixtures, {})
        self.assertIn("looks like a secret", result.stdout)
        self.assertNotIn("Zq55", result.stdout + self.harness("report", "--json").stdout)

    def test_the_same_allowed_call_is_kept_once(self):
        for _ in range(3):
            self.allowed(self.bash("git status"))
        _, fixtures, _ = self.export("--allows")
        self.assertEqual(len(fixtures), 1)

    def test_an_input_over_the_size_cap_is_not_kept(self):
        self.blocked(self.write("backbone/tools.conf", "x" * (70 * 1024)))
        out, fixtures, result = self.export("--refusals")
        self.assertEqual(fixtures, {})
        self.assertIn("64 KiB", result.stdout)
        sizes = sum(p.stat().st_size for p in (self.project / ".git/harness").rglob("*") if p.is_file())
        self.assertLess(sizes, 64 * 1024)

    def test_each_refusal_says_whether_it_replays_from_its_input_alone(self):
        self.set_tasks(["- [ ] **Task 9.1: Item** (spec: backbone/specs/9.1.md)"])
        cases = {
            "shell check": (self.bash("git commit -n -m x"), "free"),
            "tool contracts": (self.write("backbone/tools.conf", "Bash read\n"), "free"),
            "orchestrator scope (with the skill gate too)": (self.write("src/main.py", "print(1)\n"), "free"),
            "deliverer gate": (self.bash("gh pr merge 1", agent_id="d1", agent_type="deliverer"), "free"),
            "start gate": (self.pre("Edit", {"file_path": str(self.project / "backbone/3-TASKS.md"),
                                             "old_string": "- [ ] **Task 9.1:", "new_string": "- [WIP] **Task 9.1:"}),
                           "dependent"),
            "skill gate": (self.write("src/app.py", "print(1)\n", agent_id="a1", agent_type="implementer"),
                           "dependent"),
        }
        for result, _ in cases.values():
            self.blocked(result)
        _, fixtures, _ = self.export("--refusals")
        by_tool = {}
        for fixture in fixtures.values():
            tool_input = fixture["call"]["input"]["tool_input"]
            key = tool_input.get("command") or tool_input.get("file_path", "").rsplit("/", 1)[-1]
            by_tool[key] = fixture
        expected = {"git commit -n -m x": "free", "tools.conf": "free", "main.py": "free", "gh pr merge 1": "free",
                    "3-TASKS.md": "dependent", "app.py": "dependent"}
        for key, state in expected.items():
            with self.subTest(call=key):
                self.assertEqual(by_tool[key]["replay"]["state"], state, by_tool[key]["replay"])
                self.assertTrue(by_tool[key]["replay"]["why"])
        self.assertIn("skill", by_tool["app.py"]["replay"]["why"])
        self.assertEqual(by_tool["gh pr merge 1"]["call"]["role"], "deliverer")
        self.assertIn("main session", by_tool["main.py"]["expect"]["reason"])

    def test_refusals_that_read_more_than_the_input_say_what(self):
        engines = self.outside / "engines"
        engines.mkdir()
        self.blocked(self.write(str(engines / "x.py"), "x = 1\n", env={"HARNESS_ENGINES": str(engines)}))
        self.blocked(self.pre("mcp__knowledge__search_notes", {"query": "retries"}, agent_id="a1",
                              agent_type="analyst"))
        self.run_command("git", "remote", "add", "origin", "https://github.com/acme/widgets.git", check=True)
        self.run_command("git", "checkout", "-qb", "feature/x", check=True)
        self.blocked(self.bash("gh pr edit 1 --add-label risk:high", agent_id="d1", agent_type="deliverer"))
        stop = self.project / ".git/harness/STOP"
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("")
        self.blocked(self.bash("ls"))
        stop.unlink()
        out, fixtures, _ = self.export("--refusals")
        self.assertEqual(sorted(f["replay"]["state"] for f in fixtures.values()), ["dependent"] * 4)
        whys = " | ".join(f["replay"]["why"] for f in fixtures.values())
        for word in ("install folders", "knowledge", "labels", "kill switch"):
            self.assertIn(word, whys)
        result, data = self.replay(out)
        self.assertEqual((result.returncode, data["counts"]), (0, {"skipped": 4}), data)

    def test_a_shell_refusal_that_followed_a_symlink_depends_on_the_disk(self):
        os.symlink("backbone", str(self.project / "b"))
        self.blocked(self.bash("echo x > b/notes.md"))
        _, fixtures, _ = self.export("--refusals")
        fixture = self.by_command(fixtures, "echo x > b/notes.md")
        self.assertEqual(fixture["replay"]["state"], "dependent")
        self.assertIn("symlink", fixture["replay"]["why"])

    def test_a_capture_left_half_written_is_cleared(self):
        self.blocked(self.bash("git reset --hard"))
        (capture,) = (self.project / ".git/harness/captures").rglob("*.json")
        stale, fresh = capture.parent / "tmpkilled.tmp", capture.parent / "tmpwriting.tmp"
        for path in (stale, fresh):
            path.write_text("{")
        hour_ago = time.time() - 3600
        os.utime(str(stale), (hour_ago, hour_ago))
        self.blocked(self.bash("git reset --hard HEAD~2"))
        self.assertFalse(stale.exists(), "a capture killed mid-write leaves a .tmp file, cleared later")
        self.assertTrue(fresh.exists(), "one another hook may be writing now is left alone")

    def test_a_role_set_by_harness_role_replays_with_it(self):
        self.blocked(self.bash("gh pr merge 1", env={"HARNESS_ROLE": "deliverer"}))
        self.allowed(self.bash("gh pr merge 1"))
        out, fixtures, _ = self.export("--refusals")
        fixture = self.by_command(fixtures, "gh pr merge 1")
        self.assertEqual((fixture["call"]["role"], fixture["call"]["role_from_env"]), ("deliverer", True))
        result, data = self.replay(out)
        self.assertEqual(data["counts"], {"as-expected": 1}, data)

    def test_a_codex_call_replays_as_codex(self):
        call = {"session_id": "s1", "agent_id": "w1", "agent_type": "worker", "tool_name": "Write",
                "tool_input": {"file_path": str(self.project / "src/a.py"), "content": "x = 1\n"},
                "cwd": str(self.project)}
        self.blocked(self.harness("hook", "pre-tool-use", "--from", "codex", input=json.dumps(call)))
        out, fixtures, _ = self.export("--refusals")
        (fixture,) = fixtures.values()
        self.assertEqual(fixture["call"]["source"], "codex")
        self.assertIn("main session", fixture["expect"]["reason"])
        result, data = self.replay(out)
        self.assertEqual(data["counts"], {"as-expected": 1}, data)


class SharedRecords(Project):
    """A linked worktree shares the git folder, with the harness's records in it, and can name the main checkout's
    files by their absolute path: neither is the agent's to write."""

    def setUp(self):
        super().setUp()
        self.worktree = self.outside / "lane"
        self.run_command("git", "worktree", "add", "-q", "-b", "lane", str(self.worktree), check=True)

    def in_lane(self, tool, tool_input, **fields):
        data = dict({"session_id": "s1", "agent_id": "a1", "agent_type": "implementer", "tool_name": tool,
                     "tool_input": tool_input, "cwd": str(self.worktree)}, **fields)
        return self.run_command("python3", "-B", str(self.worktree / ENGINE), "hook", "pre-tool-use",
                                input=json.dumps(data), env={"CLAUDE_PROJECT_DIR": str(self.worktree)},
                                cwd=self.worktree)

    def test_no_agent_writes_the_harness_s_records_or_another_checkout_s_fixtures(self):
        self.blocked(self.bash("git reset --hard"))
        (capture,) = (self.project / ".git/harness/captures").rglob("*.json")
        evals = self.project / "backbone/evals/forged.json"
        for path in (capture, self.project / ".git/harness/captures/blocked/forged.json", evals,
                     self.project / ".git/harness/STOP"):
            with self.subTest(path=path):
                self.blocked(self.in_lane("Write", {"file_path": str(path), "content": "{}"}))
                self.blocked(self.in_lane("Bash", {"command": "echo {} > %s" % shlex.quote(str(path))}))
                self.blocked(self.write(str(path), "{}", agent_id="a1", agent_type="implementer"))
        self.assertFalse(evals.exists())

    def test_eval_export_writes_neither_the_records_nor_another_checkout_s_fixtures(self):
        self.blocked(self.bash("git reset --hard"))
        for out in (self.project / ".git/harness/captures/blocked", self.project / "backbone/evals"):
            with self.subTest(out=out):
                result = self.run_command("python3", "-B", str(self.worktree / ENGINE), "eval", "export",
                                          "--refusals", "--out", str(out), cwd=self.worktree,
                                          env={"CLAUDE_PROJECT_DIR": str(self.worktree)})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.project / ".git/harness/captures").rglob("refusal-*")], [])

    def test_a_flood_of_refusals_does_not_push_out_the_others(self):
        self.blocked(self.bash("git clean -fd"))
        self.blocked(self.bash("git push --force origin main", session_id="s3"))
        for n in range(210):
            self.blocked(self.bash("git reset --hard HEAD~%d" % n, session_id="flood"))
        _, fixtures, _ = self.export("--refusals")
        commands = [f["call"]["input"]["tool_input"]["command"] for f in fixtures.values()]
        self.assertIn("git clean -fd", commands)
        self.assertIn("git push --force origin main", commands)
        self.assertIn("git reset --hard HEAD~209", commands, "the newest of the flood are kept")
        self.assertEqual(len(commands), 100, "at most 100 refusals are kept per gate")


class Budget(Project):
    """Claude Code kills a hook that runs past 30 s, and a killed hook lets the call through: a hook answers well
    inside that whatever the input, with the answer it gives the short command."""
    PADDING = ("TOKEN", "a", "Ab1", "a://b", "eyJ", "AKIA", "-----BEGIN ", "x=", "Authorization: ", "sk-", "-p", ":",
               "DB_PASS=", "\"k\": ")

    def timed(self, command):
        started = time.monotonic()
        result = self.bash(command, env={"HARNESS_HOOK_BUDGET": "120"})
        return result, time.monotonic() - started

    def test_a_refused_command_padded_with_secret_like_text_is_refused_in_time(self):
        reason = self.blocked(self.bash("rm -rf backbone/"))
        problem = next(line for line in reason.splitlines() if line.startswith("  - "))
        for size in (60 * 1024, 1024 * 1024):
            for padding in self.PADDING:
                with self.subTest(padding=padding, size=size):
                    result, seconds = self.timed("rm -rf backbone/ backbone/A" + padding * (size // len(padding)))
                    self.assertIn(problem, self.blocked(result))
                    self.assertLess(seconds, 15)

    def test_an_allowed_command_padded_with_secret_like_text_is_allowed_in_time(self):
        for size in (60 * 1024, 1024 * 1024):
            for padding in self.PADDING:
                with self.subTest(padding=padding, size=size):
                    result, seconds = self.timed("echo " + padding * (size // len(padding)))
                    self.allowed(result)
                    self.assertLess(seconds, 15)


class Candidates(Project):
    """Three tasks refuse the same command, two fail the judge for the same reason and two are escalated."""

    def setUp(self):
        super().setUp()
        tasks = ["10.1", "10.2", "10.3"]
        for task in tasks:
            spec = self.project / ("backbone/specs/%s.md" % task)
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(SPEC.format(task=task))
        for task in tasks:
            self.set_tasks(["- [%s] **Task %s: Item** (spec: backbone/specs/%s.md)" % ("WIP" if t == task else " ",
                                                                                      t, t) for t in tasks])
            self.blocked(self.bash("git commit -n -m wip"))
            if task != "10.1":
                report = {"verdict": "fail", "task": task, "summary": "s", "findings": [],
                          "criteria": [{"id": "AC-%s-1" % task, "met": False, "evidence": "src/a.py:1", "tests": []}],
                          "tests": {"command": "true", "result": "passed"}}
                stop = {"hook_event_name": "SubagentStop", "agent_type": "judge", "stop_hook_active": False,
                        "last_assistant_message": "```json\n%s\n```" % json.dumps(report)}
                self.harness("hook", "judge-stop", input=json.dumps(stop))
                self.harness("escalate", task, "--kind", "runner", "--reason", "stalled", check=True)

    def candidates(self):
        return {c["kind"]: c for c in json.loads(self.harness("report", "--json", check=True).stdout)["candidates"]}

    def test_report_json_gives_each_candidate_an_id_kind_reason_tasks_and_inputs(self):
        found = self.candidates()
        self.assertEqual(sorted(found), ["escalation", "judge-fail", "refusal"])
        refusal = found["refusal"]
        self.assertTrue(refusal["id"].startswith("refusal-"))
        self.assertIn("git commit -n", refusal["reason"])
        self.assertEqual(refusal["tasks"], ["10.1", "10.2", "10.3"])
        self.assertEqual(len(refusal["captures"]), 1)
        capture = refusal["captures"][0]
        self.assertTrue(capture["id"] and capture["digest"])
        self.assertNotIn("input", capture, "report --json names a captured input; eval export writes it out")
        self.assertEqual(refusal["captures"][0]["replay"]["state"], "free")
        self.assertEqual(found["judge-fail"]["tasks"], ["10.2", "10.3"])
        self.assertEqual(found["escalation"]["reason"], "runner")
        self.assertEqual(found["escalation"]["captures"], [])
        self.assertEqual(len({c["id"] for c in found.values()}), 3)

    def test_the_text_report_keeps_its_sentences_and_names_the_ids(self):
        found = self.candidates()
        text = self.harness("report", check=True).stdout
        self.assertIn("refused in 3 tasks (10.1, 10.2, 10.3)", text)
        self.assertIn("judge failed 2 tasks (10.2, 10.3) for: <AC> not met", text)
        self.assertIn("escalated 2 tasks (10.2, 10.3) as runner", text)
        for candidate in found.values():
            self.assertIn("[%s]" % candidate["id"], text)

    def test_a_candidate_s_ids_are_stable_across_reports(self):
        self.assertEqual({k: c["id"] for k, c in self.candidates().items()},
                         {k: c["id"] for k, c in self.candidates().items()})

    def test_a_refusal_candidate_exports_its_inputs_as_fixtures_in_the_drafts_folder(self):
        refusal = self.candidates()["refusal"]
        status = self.run_command("git", "status", "--porcelain").stdout
        result = self.harness("eval", "export", refusal["id"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.run_command("git", "status", "--porcelain").stdout, status, "drafts are never committed")
        drafts = self.fixtures(self.project / ".git/harness/eval-drafts")
        fixture = self.by_command(drafts, "git commit -n -m wip")
        self.assertEqual(fixture["provenance"]["candidate"], refusal["id"])
        self.assertEqual(fixture["provenance"]["tasks"], ["10.1", "10.2", "10.3"])
        self.assertFalse((self.project / "backbone/evals").exists())

    def test_judge_and_escalation_candidates_export_as_eval_prompts_not_replayed(self):
        found = self.candidates()
        out = Path(tempfile.mkdtemp(dir=str(self.outside)))
        for kind in ("judge-fail", "escalation"):
            self.harness("eval", "export", found[kind]["id"], "--out", str(out), check=True)
        prompts = self.fixtures(out)
        self.assertEqual(sorted(p["kind"] for p in prompts.values()), ["prompt", "prompt"])
        for prompt in prompts.values():
            self.assertIn(prompt["candidate"]["id"], (found["judge-fail"]["id"], found["escalation"]["id"]))
            self.assertTrue(prompt["candidate"]["tasks"] and prompt["candidate"]["reason"])
            self.assertIn("not replayed", prompt["replay"]["why"])
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(data["counts"], {"skipped": 2})
        text = self.harness("eval", "replay", str(out)).stdout
        self.assertIn("not replayed in v1", text)

    def test_fixtures_are_not_written_among_the_code(self):
        for out in ("src/evals", "."):
            result = self.harness("eval", "export", "--refusals", "--out", out)
            self.assertEqual(result.returncode, 1, out)
            self.assertIn("judge's passes stale", result.stderr)
        self.assertFalse((self.project / "src").exists())
        self.assertEqual(self.run_command("git", "status", "--porcelain", "--", ":!backbone").stdout, "")

    def test_an_unknown_candidate_is_refused(self):
        result = self.harness("eval", "export", "refusal-0000000000")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no candidate refusal-0000000000", result.stdout + result.stderr)


class UserOwnedFixtures(Project):
    """backbone/evals/ defines what must stay refused or allowed: like tools.conf, only the user changes it."""

    def test_agents_cannot_write_fixtures_into_backbone_evals(self):
        self.assertIn("user", self.blocked(self.write("backbone/evals/x.json", "{}")))
        self.blocked(self.write("backbone/evals/x.json", "{}", agent_id="a1", agent_type="implementer"))
        command = "python3 %s eval export --refusals --out backbone/evals" % ENGINE
        self.assertIn("backbone/evals", self.blocked(self.bash(command)))
        self.blocked(self.bash("python3 %s eval export --refusals --out=./backbone/evals/" % ENGINE))
        self.allowed(self.bash("python3 %s eval export --refusals" % ENGINE))
        self.allowed(self.bash("python3 %s eval replay" % ENGINE))

    def test_verify_refuses_a_commit_that_changes_backbone_evals_unless_the_user_allows_it(self):
        self.blocked(self.bash("git reset --hard"))
        out, _, _ = self.export("--refusals")
        self.keep_fixtures(out, commit=False)
        self.run_command("git", "add", "-A")
        result = self.harness("verify")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("backbone/evals/", result.stdout)
        self.run_command("git", "commit", "-qm", "test(evals): first fixture", env={"HARNESS_VERIFY": "off"},
                         check=True)
        self.assertEqual(self.harness("verify", "--range", "HEAD~1..HEAD").returncode, 1)
        self.assertEqual(self.harness("verify", "--range", "HEAD~1..HEAD", "--allow-user-changes").returncode, 0)

    def test_a_differently_spelled_path_to_backbone_evals_is_refused_too(self):
        self.assertIn("only the user", self.blocked(self.write("backbone/EVALS/y.json", "{}")))
        self.blocked(self.write("backbone/Evals/y.json", "{}", agent_id="a1", agent_type="implementer"))

    def test_eval_export_itself_refuses_to_write_into_backbone_evals(self):
        """However the agent names it: a shell variable, a symlink or another spelling, which the hook can't see."""
        self.blocked(self.bash("git reset --hard"))
        evals = self.project / "backbone/evals"
        evals.mkdir(parents=True)
        os.symlink("backbone/evals", str(self.project / "d"))
        for out in (str(evals), "backbone/evals/sub", "backbone/EVALS", "d", str(self.project / "d/sub")):
            with self.subTest(out=out):
                result = self.harness("eval", "export", "--refusals", "--out", out)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("backbone/evals", result.stderr)
        self.assertEqual(list(evals.rglob("*")), [])

    def test_replay_of_backbone_evals_reads_the_committed_fixtures_only(self):
        self.blocked(self.bash("git reset --hard"))
        out, fixtures, _ = self.export("--refusals")
        evals = self.keep_fixtures(out)
        ((name, fixture),) = fixtures.items()
        (evals / name).write_text(json.dumps(dict(fixture, replay={"state": "dependent", "why": "an agent said so"})))
        (evals / "planted.json").write_text(json.dumps(dict(fixture, id="planted", expect={"outcome": "allowed"})))
        result = self.harness("eval", "replay", "--json")
        data = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, data)
        self.assertEqual(data["counts"], {"as-expected": 1}, data)
        self.assertCountEqual(data["uncommitted"], ["backbone/evals/" + name, "backbone/evals/planted.json"])
        self.assertIn("only committed fixtures", self.harness("eval", "replay").stdout)

    def test_an_agent_exporting_drafts_in_autonomous_mode_is_not_an_out_of_band_change(self):
        auto = {"HARNESS_AUTONOMY": "autonomous"}
        self.harness("hook", "session-start", input="{}", env=auto)
        self.blocked(self.bash("git reset --hard", env=auto))
        command = "python3 %s eval export --refusals" % ENGINE
        self.allowed(self.bash(command, env=auto))
        self.harness("eval", "export", "--refusals", env=auto, check=True)
        data = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command},
                "tool_response": {"exit_code": 0}, "cwd": str(self.project)}
        self.harness("hook", "post-tool-use", input=json.dumps(data), env=auto)
        events = (self.project / ".git/harness/events.jsonl").read_text()
        self.assertNotIn('"kind": "tamper"', events)
        self.assertTrue(list((self.project / ".git/harness/eval-drafts").glob("*.json")))


class Replay(Project):
    REFUSED = ["git reset --hard HEAD~1", "git clean -fd", "rm -rf /", "git push --force origin main",
               "echo x > backbone/harness.conf", "git commit -n -m x"]
    ALLOWED = ["ls", "git status", "git log --oneline -3", "python3 -m pytest -q", "cat README.md"]

    def capture_mix(self):
        for command in self.REFUSED:
            self.blocked(self.bash(command))
        for command in self.ALLOWED:
            self.allowed(self.bash(command))
        self.blocked(self.write("backbone/tools.conf", "Bash read\n"))
        self.blocked(self.bash("gh pr merge 7 --squash", agent_id="d1", agent_type="deliverer"))
        self.set_tasks(["- [ ] **Task 9.1: Item** (spec: backbone/specs/9.1.md)"])
        self.blocked(self.pre("Edit", {"file_path": str(self.project / "backbone/3-TASKS.md"),
                                       "old_string": "- [ ] **Task 9.1:", "new_string": "- [WIP] **Task 9.1:"}))
        out, _, _ = self.export("--refusals")
        self.export("--allows", out=out)
        return out

    def test_an_unchanged_engine_reports_no_change(self):
        out = self.capture_mix()
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        counts = data["counts"]
        self.assertEqual(counts.get("as-expected"), len(self.REFUSED) + len(self.ALLOWED) + 2, data)
        self.assertEqual(counts.get("skipped"), 1, "the start-gate refusal depends on the task list")
        skipped = [r for r in data["results"] if r["status"] == "skipped"]
        self.assertIn("state", skipped[0]["detail"])

    def test_replay_leaves_the_project_untouched(self):
        out = self.capture_mix()
        events = (self.project / ".git/harness/events.jsonl").read_text()
        status = self.run_command("git", "status", "--porcelain").stdout
        self.replay(out)
        self.assertEqual((self.project / ".git/harness/events.jsonl").read_text(), events)
        self.assertEqual(self.run_command("git", "status", "--porcelain").stdout, status)

    def test_a_removed_rule_makes_its_fixtures_newly_allowed(self):
        rule = "block | @bash | \\bfrobnicate\\b | Never frobnicate the build."
        self.add_rule(rule)
        self.blocked(self.bash("frobnicate --all"))
        out, fixtures, _ = self.export("--refusals")
        fixture = self.by_command(fixtures, "frobnicate --all")
        self.drop_rule(rule)
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.status_of(data, fixture["id"]), "newly-allowed")
        text = self.harness("eval", "replay", str(out)).stdout
        self.assertIn("newly allowed (a hole): 1", text)
        self.assertIn(fixture["id"], text)

    def test_a_new_rule_makes_a_past_allow_newly_blocked(self):
        self.allowed(self.bash("make lint"))
        out, fixtures, _ = self.export("--allows")
        fixture = self.by_command(fixtures, "make lint")
        self.add_rule("block | @bash | \\bmake\\s+lint\\b | Run the linter through the test command.")
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.status_of(data, fixture["id"]), "newly-blocked")
        self.assertIn("newly blocked (a false block): 1", self.harness("eval", "replay", str(out)).stdout)

    def test_a_refusal_that_no_longer_gives_its_reason_is_reported(self):
        rule = "block | @bash | \\bfrobnicate\\b | Never frobnicate the build."
        self.add_rule(rule)
        self.blocked(self.bash("frobnicate --all"))
        out, fixtures, _ = self.export("--refusals")
        self.drop_rule(rule)
        self.add_rule("block | @bash | \\bfrobnicate\\b | Something else entirely.")
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.status_of(data, self.by_command(fixtures, "frobnicate --all")["id"]), "reason-changed")

    def test_moving_a_rule_line_keeps_its_reason(self):
        rule = "block | @bash | \\bfrobnicate\\b | Never frobnicate the build."
        self.add_rule(rule)
        self.blocked(self.bash("frobnicate --all"))
        out, _, _ = self.export("--refusals")
        conf = self.project / "backbone/guardrails.conf"
        conf.write_text("# a comment that moves every rule down a line\n" + conf.read_text())
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 0, data)

    def test_another_engine_is_replayed_with_engine(self):
        out = self.capture_mix()
        engine = self.outside / "engine"
        shutil.copytree(str(ROOT / "payload/owned"), str(engine))
        core = engine / "scripts/harness/guardrails.core.conf"
        core.write_text("\n".join(line for line in core.read_text().splitlines()
                                  if "git\\s+reset\\s+--hard" not in line) + "\n")
        result, data = self.replay(out, "--engine", str(engine / ENGINE))
        self.assertEqual(result.returncode, 1)
        holes = [r for r in data["results"] if r["status"] == "newly-allowed"]
        self.assertEqual([r["command"] for r in holes], ["git reset --hard HEAD~1"])
        self.assertEqual(data["engine"], str(engine / ENGINE))
        same, data = self.replay(out, "--engine", str(self.project / ENGINE))
        self.assertEqual(same.returncode, 0, data)

    def test_an_engine_that_fails_is_an_error_not_a_pass(self):
        self.blocked(self.bash("git reset --hard"))
        out, _, _ = self.export("--refusals")
        broken = self.outside / "broken/scripts/harness/lib/harness.py"
        broken.parent.mkdir(parents=True)
        broken.write_text("import sys\nsys.exit(1)\n")
        result, data = self.replay(out, "--engine", str(broken))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["counts"], {"error": 1})

    def test_an_empty_folder_replays_nothing(self):
        (self.outside / "empty").mkdir()
        result, data = self.replay(self.outside / "empty")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(data["results"], [])

    def test_a_missing_folder_is_an_error_not_a_pass(self):
        result = self.harness("eval", "replay", str(self.outside / "none"))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no folder", result.stderr)
        result = self.harness("eval", "replay")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no fixtures committed", result.stderr)

    def test_the_default_folder_is_backbone_evals(self):
        self.blocked(self.bash("git reset --hard"))
        out, _, _ = self.export("--refusals")
        self.keep_fixtures(out)
        result = self.harness("eval", "replay", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"], {"as-expected": 1})

    def test_a_deliverer_fixture_replays_with_its_branch_and_origin(self):
        self.run_command("git", "remote", "add", "origin", "https://github.com/acme/widgets.git", check=True)
        self.run_command("git", "checkout", "-qb", "feature/x", check=True)
        role = dict(agent_id="d1", agent_type="deliverer")
        self.blocked(self.bash("gh pr view 3 -R other/repo", **role))
        self.allowed(self.bash("gh pr view 3 -R acme/widgets", **role))
        self.blocked(self.bash("git push origin feature/x:main", **role))
        self.allowed(self.bash("git push origin feature/x", **role))
        out, fixtures, _ = self.export("--refusals")
        self.export("--allows", out=out)
        result, data = self.replay(out)
        self.assertEqual(result.returncode, 0, data)
        self.assertEqual(data["counts"], {"as-expected": 4}, data)


@unittest.skipIf(given is None, "hypothesis is not installed (pip install -r tests/requirements.txt)")
class Properties(Project):
    if given is not None:
        upper = string.ascii_uppercase + string.digits
        alnum = string.ascii_letters + string.digits
        shaped = st.one_of(
            st.text(alphabet=upper, min_size=16, max_size=24).map(lambda s: "AKIA" + s),
            st.text(alphabet=alnum, min_size=36, max_size=44).map(lambda s: "ghp_" + s),
            st.text(alphabet=alnum + "_", min_size=22, max_size=60).map(lambda s: "github_pat_" + s),
            st.text(alphabet=alnum + "-_", min_size=20, max_size=60).map(lambda s: "sk-ant-api03-" + s),
            st.text(alphabet=alnum + "-", min_size=10, max_size=40).map(lambda s: "xoxb-" + s),
            st.text(alphabet=alnum + "+/=\n", min_size=16, max_size=120).map(
                lambda s: "-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----" % s),
            st.text(alphabet=alnum + "+/=\n", min_size=16, max_size=120).map(
                lambda s: "-----BEGIN PGP PRIVATE KEY BLOCK-----\n\n%s\n-----END PGP PRIVATE KEY BLOCK-----" % s),
            st.text(alphabet=alnum, min_size=24, max_size=40).map(lambda s: "sk_live_" + s),
            st.text(alphabet=alnum + "-_", min_size=35, max_size=35).map(lambda s: "AIza" + s),
            st.text(alphabet=alnum, min_size=36, max_size=36).map(lambda s: "npm_" + s),
            st.tuples(*[st.text(alphabet=alnum + "-_", min_size=10, max_size=40)] * 3).map(
                lambda p: "eyJ%s.eyJ%s.%s" % p),
            st.randoms().map(lambda r: "".join(r.choice(string.ascii_letters + string.digits) for _ in range(40))))
        value = st.text(alphabet=alnum + "!#%*+,-.:=?^_~", min_size=6, max_size=40).map(lambda s: "Sk" + s)
        placed = st.one_of(
            st.tuples(shaped, st.sampled_from(["echo '%s'", "printf %%s '%s' > /tmp/k", "X=1 cat <<EOF\n%s\nEOF"])),
            st.tuples(value, st.sampled_from(["export SERVICE_TOKEN=%s", "DB_PASSWORD='%s' ./run",
                                              "git clone https://ci:%s@example.com/r.git",
                                              "curl -H \"Authorization: Bearer %s\" https://example.com"]
                                             + [holder for holder, _ in PLANTED if not holder.startswith(("echo %",
                                                                                                         "cat <<"))])))

        @settings(max_examples=examples(12))
        @given(placed)
        @example(("AKIAZZZZYYYYQQQQWWWW", "echo '%s'"))
        def test_redaction_never_leaks_a_planted_secret(self, case):
            secret, holder = case
            assume("REDACTED" not in secret and "XXXX" not in secret)
            self.plant(holder % secret)
            out, _, _ = self.export("--refusals")
            self.export("--allows", out=out)
            texts = list(self.kept_and_printed().values()) + [p.read_text() for p in out.rglob("*.json")]
            for line in self.secret_lines(secret):
                for text in texts:
                    self.assertNotIn(line, text)

        commands = st.lists(st.sampled_from(Replay.REFUSED + Replay.ALLOWED + ["make build", "rm -rf ~",
                                                                              "git branch -D old", "ls -la src"]),
                            min_size=1, max_size=6, unique=True)

        @settings(max_examples=examples(12))
        @given(commands)
        def test_an_unchanged_engine_replays_every_fixture_as_expected(self, chosen):
            for command in chosen:
                self.bash(command)
            out, _, _ = self.export("--refusals")
            self.export("--allows", out=out)
            result, data = self.replay(out)
            self.assertEqual(result.returncode, 0, data)
            self.assertEqual(set(data["counts"]), {"as-expected"}, data)

        words = st.text(alphabet=string.ascii_lowercase, min_size=5, max_size=12).filter(
            lambda w: w not in ("rmdir", "sudo", "chmod", "chown", "touch", "unlink", "truncate"))

        @settings(max_examples=examples(12))
        @given(words)
        def test_a_removed_rule_makes_its_refusals_newly_allowed(self, word):
            rule = "block | @bash | \\b%s\\b | Never %s here." % (word, word)
            self.add_rule(rule)
            command = "%s --now" % word
            self.blocked(self.bash(command))
            out, fixtures, _ = self.export("--refusals")
            fixture = self.by_command(fixtures, command)
            self.drop_rule(rule)
            result, data = self.replay(out)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(self.status_of(data, fixture["id"]), "newly-allowed")


if __name__ == "__main__":
    unittest.main()
