"""Brace expansion in the shell gate, checked through the pre-tool-use hook as an agent CLI calls it.

The shell expands an unquoted {a,b} or {1..3} before it runs a command, so {rm,-rf,backbone/} is rm -rf backbone/ and
the gate's decision is the one for the command written out, wherever the braces stand. What the shell leaves as
written stays text. Past a fixed limit, or where bash and zsh read the braces differently, a command whose operands
the gates check is refused. Every command here is only the hook's input: none of them runs. The property check needs
hypothesis (pip install -r tests/requirements.txt) and asks the shells on this machine what they make of a word, with
printf.
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

from hypothesis_profiles import examples

try:
    from hypothesis import assume, example, given, settings, strategies as st
except ImportError:
    given = None

ROOT = Path(__file__).resolve().parents[1]
MOVED = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "XDG_CONFIG_HOME",
         "CLAUDE_PLUGIN_ROOT", "HARNESS_AUTONOMY", "HARNESS_PROFILE", "HARNESS_DELIVER", "PYTHONPATH")

# Spellings of rm -rf backbone/ that brace expansion makes, in command position or in its arguments.
DELETES = ("{rm,-rf,backbone/}", "{rm,-rf} backbone/", "r{m,} -rf backbone/", "{,rm} -rf backbone/",
           "rm -rf back{bone,}/", "rm -rf {backbone,x}/", "rm -rf {x,backbone}/", "rm -rf {x,{y,backbone}}/",
           "rm -rf {x,{y,{z,back{bone,}}}}/", "rm -rf {x{y,z},back{q,bone}}", "rm -rf {{backbone,x},y}",
           "rm -rf ba{c..d}kbone/", "rm -rf {a..c}ackbone", "rm -rf {c..a}ackbone", "rm -rf {b..b}ackbone",
           "rm -rf {1..3}/../backbone", "rm -rf {01..03}/../backbone", "rm -rf x{1..9..4}/../../backbone/..{,/backbone}",
           "{'rm',-rf,backbone/}", "{\"rm\",\"-rf\",'backbone/'}", "{r\\m,-rf,backbone/}", "{rm,-rf,back\\bone/}",
           "rm -rf 'back'{bone,x}", "rm -rf \"back\"{bone,x}", "rm -rf {'x y',backbone}", "rm -rf {x\\,y,backbone}",
           "rm -rf {\"a,b\",backbone}", "rm -rf {$(echo a,b),backbone}", "rm -rf {`echo a,b`,backbone}",
           "rm -rf {${X:-a,b},backbone}", "rm -rf {#x,backbone}", "rm -rf {x}{,/../backbone}",
           "rm -rf {}{,/../backbone}", "rm -rf {x{a,/../backbone}", "rm -rf ./{},/../backbone,x}",
           "rm -rf {x},/../backbone}", "rm -rf {a{b,/../../backbone/}..d}", "rm -rf {y,+}/../backbone",
           "rm -rf ./back{.../}one/../backbone", "rm -rf x{.../}..{.../}backbone", "rm -rf back{'b'..c}one",
           "a=b; rm -rf {$a..$a}ackbone", "X=back; Xbone=x; Xy=x; rm -rf $X{bone,y}",
           "rm -rf {,backbone}", "rm -rf x{,/../backbone}{,}", "rm -rf {a,b}{/..,/../..}{/backbone,/x}")
# Ways of running a command that come down to running it: {c} is the command, {q} the command quoted as one word.
CARRIERS = ("sh -c {q}", "bash -lc {q}", "zsh -c {q}", "eval {q}", "eval {c}", "( {c} )", "({c})", "{{ {c}; }}",
            "f() {{ {c}; }}; f", "function f {{ {c}; }}; f", "x=$({c})", "echo \"$({c})\"", "echo `{c}`",
            "timeout 5 {c}", "env -i {c}", "nice -n 5 {c}", "command {c}", "nohup {c}", "env -S {q}",
            "sudo -u x {c}", "busybox sh -c {q}", "true && {c}", "{c} | cat", "if {c}; then :; fi",
            "for i in 1; do {c}; done", "case x in x) {c};; esac", "! {c}", "FOO=1 {c}", "bash <<'EOF'\n{c}\nEOF", "{{bash,-s}} <<'EOF'\n{c}\nEOF",
            "sh -c 'sh -c \"$1\"' _ x; {c}", "trap {q} EXIT", "{c} >/dev/null 2>&1", "X={q}; eval \"$X\"",
            "cat <({c})")
CARRIED = ("{rm,-rf,backbone/}", "rm -rf {x,back{bone,}}/", "rm -rf {a..c}ackbone")
# Writes, moves and copies: the target comes out of the expansion.
WRITES = ("echo x > {backbone,y}/tools.conf", "echo x > {y,backbone}/tools.conf", "echo x >{y,backbone/tools.conf}",
          "echo x >>backbone/tools.con{f,g}", "echo x 2>{y,backbone/tools.conf}", "echo x &>{y,backbone}/tools.conf",
          "> {y,backbone}/tools.conf echo x", "echo x >| {y,backbone}/tools.conf", "cat <> {y,backbone}/tools.conf",
          "echo x | tee {y,backbone}/tools.conf", "cp evil {x,backbone/tools.conf}", "cp evil{,} back{,bone}/tools.conf",
          "mv {backbone,x}/tools.conf y", "mv evil {x,backbone/tools.conf}", "ln -sf evil {x,backbone/tools.conf}",
          "dd if=x of={y,backbone}/tools.conf", "sed -i s/a/b/ {x,backbone/tools.conf}", "touch {x,backbone}/y",
          "chmod 777 {x,scripts}/harness/lib/harness.py", "truncate -s 0 {x,.claude/settings.json}",
          "for f in {x,backbone}/y; do rm $f; done", "for f in {a..c}; do rm -rf ${f}ackbone; done",
          "set -- {x,backbone/y}; rm \"$2\"", "f() { rm -rf \"$2\"; }; f {x,backbone}",
          "export D={x,backbone}; rm -rf $D", "export D={backbone,x}; eval rm -rf $D",
          "export D={rm,-rf,backbone/}; eval $D", "X={x,backbone}; eval rm -rf $X", "D=back{bone,x}; eval \"rm -rf $D\"",
          "find {x,.} -delete", "find . -exec {rm,-rf} {} +",
          "xargs {rm,-rf} < list", "rm -rf .g{it,x}/harness", "cd {backbone,x} && rm y",
          "rsync evil {x,backbone/}", "echo x > ~/.cla{ude,x}/settings.json", "cp evil.json ~/.{x,claude}/settings.json",
          "rm -rf ~/.{claude,x}", "mytool ~/.{claude,x}/settings.json", "tar -xf e.tar -C {~,x}",
          "tar -xf e.tar {-C,$HOME}", "unzip e.zip -d {~,x}", "cp -R evil/{.,} {x,~}")
# The git and gh gates, the engine, nested sessions and the @bash rules.
CALLS = ("git commit -{n,q} -m x", "git {commit,-n,-m,x}", "{git,commit,-n,-m,x}", "{git,} commit -n -m x",
         "git push --{mirror,x}", "git push origin {+,}main", "git {push,--mirror}", "git push -{f,q} origin main",
         "git push --for{ce,x} origin main", "git reset --{hard,x}", "git clean -{fd,q}",
         "git -c core.hooks{Path=x,y} commit", "git config core.hooksPath{,} x", "git config {core.hooksPath,x}",
         "git reflog {expire,--all}", "git {filter-branch,x}", "git apply {-,x}", "git rm -r {x,backbone}",
         "git mv {x,backbone/tools.conf} y", "git {config,alias.x} '!ls'",
         "python3 scripts/harness/lib/harness.py {pin,1}", "python3 scripts/harness/lib/harness.py {run,x}",
         "python3 {scripts/harness/lib/harness.py,run}", "{python3,scripts/harness/lib/harness.py,run}",
         "cp scripts/harness/lib/{harness,x}.py y", "claude --{bare,x}", "claude {--bare,-p} x",
         "codex {--disable,hooks}", "HARNESS_VERIFY=off{,} git commit -m x", "export HARNESS_{VERIFY,x}=off", "env HARNESS_{VERIFY,x}=off git commit", "bash {-c,'rm -rf backbone/'}",
         "{bash,-c,'rm -rf backbone/'}", "psql -c 'delete from users'{,}")
# What the shell doesn't expand, or expands into nothing the gates mind.
LITERAL = ("echo '{rm,-rf,backbone/}'", "echo \"{rm,-rf,backbone/}\"", "echo \\{rm,-rf,backbone/\\}",
           "touch '{backbone,x}'", "touch \\{backbone,x}", "touch \"{backbone,x}\"", "touch {backbone\\,x}",
           "touch {'backbone,x'}", "touch '{'backbone,x}", "touch {backbone}", "touch x{backbone}y", "touch {backbone,x",
           "touch backbone,x}", "touch {backbone x}", "touch {backbone, x}", "touch {a..bb}ackbone", "touch {1...3}",
           "X={x,backbone}; echo $X", "find . -name '*.pyc' -exec grep -l x {} \\;", "find . -name x -exec ls {} +",
           "ls | xargs -I{} echo {}", "ls | xargs -I {} cat {}/README.md", "echo ${HOME} ${X:-x} ${X:-{a,b}}",
           "D=build; rm -rf ${D}", "{ echo a; echo b; }", "if true; then { echo a,b; }; fi",
           "f() { echo a,b; }; f", "curl -d '{\"a\":1,\"b\":[1,2]}' localhost", "curl -d \"{\\\"a\\\":1,\\\"b\\\":2}\" x",
           "git diff HEAD@{1}", "git show stash@{0}", "git stash show -p stash@{0}", "git log HEAD@{1.day.ago}..HEAD",
           "git rev-parse @{u}", "git log @{upstream}..HEAD", "git log --format='%h{%an,%s}'",
           "awk '{print $1,$2}' data.txt", "jq '{a,b}' x.json", "python3 -c 'print({1,2})'",
           "docker ps --format '{{.ID}},{{.Names}}'", "[[ $x =~ ^a{1,2}$ ]] && echo y", "grep -E 'a{1,3}' x.txt",
           "echo a{b,c d}e", "echo {} {,} {x} }{", "printf '%s\\n' {}", "echo $((1+2)) {a}", "cat <<< {a,b}",
           "git commit -m 'feat: {a,b} and {1..3}'", "git commit -m \"feat: {rm,-rf,backbone/}\"",
           "cat > notes.md <<'EOF'\n{rm,-rf,backbone/}\nEOF", "gh pr view 7 --json title --jq '{a,b}'")
EVERYDAY = ("mkdir -p src/{a,b}", "mkdir -p src/{main,test}/{java,resources}", "cp file{,.bak}", "mv notes.{txt,md}",
            "git diff HEAD@{1}", "git diff HEAD~{2,1}", "git add src/{a,b}.py", "git checkout -b x{1..1}",
            "ls src/{a,b}/*.py", "cat {a,b}.txt", "diff {old,new}/x.py", "touch src/{a,b,c}.py", "rm -f build/{a,b}.o",
            "rm -rf build/{a..e} dist/{1..20}", "for i in {1..3}; do echo $i; done",
            "for i in {1..100}; do echo $i > out/$i.txt; done", "for i in {1..10}; do bash -c \"echo $i\"; done",
            "for i in {1..100}; do bash -c \"echo $i\"; done", "for i in {1..100}; do ./run$i.sh; done",
            "for i in {1..1000}; do touch out/$i; done", "for i in {1..50}; do for j in {1..50}; do touch o/$i-$j; done; done",
            "for s in {a..z}; do mkdir -p out/$s; done", "touch f{001..100}.txt", "echo {1..100000}", "echo {1..9}{1..9}{1..9}",
            "for i in {1..100000}; do echo $i; done", "for i in {1..100000}; do curl -s localhost/$i; done",
            "npx prettier --write 'src/**/*.{ts,tsx}'", "eslint --ext .{js,ts} src", "pytest tests/test_{a,b}.py",
            "tar -czf out.tgz src/{a,b}", "rsync -a --exclude={node_modules,.git} src/ dest/",
            "grep -rn TODO --include=*.{py,js} src", "kubectl get {pods,svc}", "echo {a,b}{c,d}", "curl localhost/{a,b}",
            "cd src/{,} && ls", "seq 1 3 | xargs -I{} echo out/{}.txt{,.bak}", "find . -name x -exec cp {} {}.bak \\;",
            "git log --oneline HEAD~{3,1}", "git show HEAD:{a,b}.py", "gh pr view 7 --json {title,body}",
            "X=out; mkdir -p $X/{a,b}", "X=out; rm -f $X/{a,b}.o", "N=3; for i in {1..$N}; do echo $i; done")
NINES = "{1..9}" * 12
# Past the limit: refused where the gates check an operand, and let through where the command only prints or reads.
PAST_REFUSED = ("rm -rf " + NINES, "rm -f x{1..100000}", NINES + " x", "echo x > " + NINES, "echo x | tee " + NINES,
                "cp a " + NINES, "mv " + NINES + " x", "git commit -" + NINES, "git add f{1..100000}", "gh " + NINES,
                "sh -c " + NINES, "eval " + NINES, "timeout 5 rm " + NINES, "sh -c 'rm " + NINES + "'",
                "(rm " + NINES + ")", "x=$(rm " + NINES + ")", "f() { rm " + NINES + "; }; f",
                "for i in " + NINES + "; do rm $i; done", "for i in " + NINES + "; do $i x; done",
                "cp evil ~/.cla{ude,%s}/settings.json" % NINES, "mytool ~/.cla{u,%s}de/settings.json" % NINES,
                "claude --ba{r,%s}e" % NINES, "python3 scripts/harness/lib/harness.py " + NINES,
                "rm {1..99999999999999999999}", "rm {a,b}" + "{a,b}" * 40, "rm " + "{a," * 3000 + "b" + "}" * 3000,
                "tar -xf e.tar -C " + NINES, "export HARNESS_{VERIFY,%s}=off" % NINES, "env HARNESS_{VERIFY,%s}=off git commit" % NINES,
                "find . -{exec,%s} rm x" % NINES, "find " + NINES + " -delete",
                "for i in {1..1000}; do for j in {1..1000}; do rm $i$j; done; done")
PAST_ALLOWED = ("echo " + NINES, "printf '%s\\n' " + NINES, "ls " + NINES, "cat " + NINES, "grep x " + NINES,
                "for i in " + NINES + "; do echo $i; done", "[ -n " + NINES + " ]", "echo '" + NINES + "' > x",
                "rm '" + NINES + "'")


class BraceProject(unittest.TestCase):
    CONF = {}

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="braces ")
        cls.addClassCleanup(cls.temp.cleanup)
        work = Path(cls.temp.name).resolve()
        cls.project = work / "project"
        (work / "home").mkdir()
        cls.project.mkdir()
        cls.env = {k: v for k, v in os.environ.items() if k not in MOVED}
        cls.env.update(HOME=str(work / "home"), CLAUDE_PROJECT_DIR=str(cls.project), GIT_CONFIG_GLOBAL=os.devnull,
                       PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.project)], check=True, env=cls.env)
        subprocess.run([str(ROOT / "bootstrap.sh"), str(cls.project)], check=True, capture_output=True, env=cls.env)
        conf = cls.project / "backbone/harness.conf"
        text = conf.read_text()
        for name, value in cls.CONF.items():
            text = re.sub(r"(?m)^%s=.*\n" % name, "", text) + '\n%s="%s"\n' % (name, value)
        conf.write_text(text)
        for command in (["git", "add", "-A"], ["git", "commit", "-qm", "init", "--no-verify"]):
            subprocess.run(command, cwd=cls.project, env=cls.env, check=True, capture_output=True)

    def hook(self, command, event="pre-tool-use", **fields):
        data = dict({"session_id": "s", "tool_name": "Bash", "tool_input": {"command": command},
                     "cwd": str(self.project)}, **fields)
        return subprocess.run(["python3", str(self.project / "scripts/harness/lib/harness.py"), "hook", event],
                              cwd=self.project, input=json.dumps(data), capture_output=True, text=True, env=self.env)

    def refused(self, command, **fields):
        result = self.hook(command, **fields)
        self.assertEqual(result.returncode, 2, "let through: %s\n%s" % (command[:300], result.stderr))
        return result.stderr

    def allowed(self, command, **fields):
        result = self.hook(command, **fields)
        self.assertEqual(result.returncode, 0, "refused: %s\n%s" % (command[:300], result.stderr))


class BraceExpansion(BraceProject):
    def each(self, check, commands):
        for command in commands:
            with self.subTest(command=command[:200]):
                check(command)

    def test_the_reported_command_gets_the_refusal_of_the_command_it_expands_to(self):
        written_out = self.refused("rm -rf backbone/")
        self.assertEqual(self.refused("{rm,-rf,backbone/}"), written_out)

    def test_a_delete_spelled_with_braces_is_refused(self):
        self.each(self.refused, DELETES)

    def test_it_is_refused_however_the_shell_runs_it(self):
        self.each(self.refused, [carrier.format(c=command, q=shlex.quote(command))
                                 for carrier in CARRIERS for command in CARRIED])

    def test_a_path_that_only_a_shell_without_brace_expansion_reads_is_still_refused(self):
        self.each(self.refused, ("sh -c 'rm -rf {x,/../backbone/y}'", "dash -c 'echo x > {a,b/../backbone/y}'"))

    def test_a_write_to_a_target_from_braces_is_refused(self):
        self.each(self.refused, WRITES)

    def test_the_git_engine_session_and_rule_gates_read_the_words_expanded(self):
        self.each(self.refused, CALLS)

    def test_what_the_shell_leaves_as_written_stays_text(self):
        self.each(self.allowed, LITERAL)

    def test_everyday_braces_are_allowed(self):
        self.each(self.allowed, EVERYDAY)

    def test_past_the_limit_a_command_whose_operands_matter_is_refused(self):
        self.each(self.refused, PAST_REFUSED)

    def test_past_the_limit_a_command_that_only_prints_or_reads_is_allowed(self):
        self.each(self.allowed, PAST_ALLOWED)

    def test_the_refusal_past_the_limit_says_so(self):
        self.assertIn("brace", self.refused("rm -f x{1..100000}"))

    def test_a_push_spelled_with_braces_is_logged_as_one(self):
        self.hook("git pu{sh,} origin feat/x", event="post-tool-use", tool_response={"exit_code": 0})
        events = (self.project / ".git/harness/events.jsonl").read_text().splitlines()
        self.assertIn("push", [e.get("action") for e in map(json.loads, events) if e.get("kind") == "outward"])

    def test_braces_cannot_take_the_hook_past_its_budget(self):
        """A hook past its budget refuses everything, or is killed and lets everything through."""
        wide = ("{", "}", "{a,", "{a,b}", "{a,b} ", "{1..9} ", "},{", "${", "{..", "{1..100000} ", "{{a,b},", "{x},",
                "{$X", "$x{a,")
        # Each of these is a command of its own, which costs as much on its own as without braces.
        many = ("$(echo {1..9000})", "{a,b};", "rm {1..9000};", "for i in {1..9000}; do rm $i; done;")
        for padding, size in [(p, (512 if " " in p else 1024) * 1024) for p in wide] + [(p, 128 * 1024) for p in many]:
            with self.subTest(padding=padding):
                started = time.monotonic()
                self.refused("rm -rf {backbone,x} " + padding * (size // len(padding)))
                self.assertLess(time.monotonic() - started, 15)
        with self.subTest("nested loops"):
            started = time.monotonic()
            self.refused("for i in {1..1000}; do for j in {1..1000}; do rm $i$j; done; done")
            self.assertLess(time.monotonic() - started, 15)
        for padding in ("{a,b}", "{a,b} ", "{x} ", "{1..9}"):
            with self.subTest(padding=padding, printed=True):
                started = time.monotonic()
                self.allowed("echo " + padding * (512 * 1024 // len(padding)))
                self.assertLess(time.monotonic() - started, 15)


class NoMergeProfile(BraceProject):
    CONF = {"HARNESS_PROFILE": "no-merge"}

    def test_a_merge_spelled_with_braces_is_refused(self):
        for command in ("gh pr merge 7", "gh pr {merge,7}", "{gh,pr,merge,7}", "gh {pr,merge} 7", "{gh,} pr merge 7",
                        "sh -c 'gh pr {merge,7}'", "gh api -X PUT repos/o/r/pulls/7/{merge,x}",
                        "gh api {-X,PUT} repos/o/r/pulls/7/merge", "timeout 5 gh pr {merge,7}"):
            with self.subTest(command=command):
                self.refused(command)
        self.allowed("gh pr view 7 --json {title,body}")


class ExternalDeliveryAndTheDeliverer(BraceProject):
    CONF = {"HARNESS_DELIVER": "external"}

    def test_a_push_or_a_gh_write_spelled_with_braces_is_refused_to_every_agent(self):
        for command in ("git push", "git pu{sh,}", "{git,push}", "git {push,origin}", "sh -c 'git {push,origin}'",
                        "timeout 5 git {push,origin}", "gh pr {create,--fill}", "{gh,pr,create}",
                        "X={push,origin}; eval git $X", "X=pu{sh,}; eval \"git $X\"", "X=pu{sh,}; sh -c \"git $X\"",
                        "for s in {push,x}; do git $s; done"):
            for role in ("", "implementer", "deliverer"):
                with self.subTest(command=command, role=role):
                    self.refused(command, **({"agent_type": role} if role else {}))

    def test_reading_is_still_allowed(self):
        for command in ("git diff HEAD@{1}", "git log -1", "gh pr view 7"):
            with self.subTest(command=command):
                self.allowed(command)


SHELLS = [shell for shell in (["bash", "--norc"], ["zsh", "-f"]) if shutil.which(shell[0])]


def expansions(shell, word):
    """The words shell makes of word, or None when it can't parse it. Only printf runs."""
    result = subprocess.run(shell + ["-c", "printf '%%s\\0' %s" % word], cwd=tempfile.gettempdir(), capture_output=True,
                            env={"PATH": "/usr/bin:/bin"})
    if result.returncode != 0 or result.stderr:
        return None
    return result.stdout.decode().split("\0")[:-1]


def protected(words):
    names = [os.path.normpath(os.path.join("/p", word)) for word in words]
    return any(name == "/p/backbone" or name.startswith("/p/backbone/") for name in names)


if given is not None:
    ATOMS = st.sampled_from(["backbone", "back", "bone", "b", "x", "'x'", '"y"', "\\,", "\\{", "\\}", "','", "'{'",
                             "/", "..", "", "", "1"])
    RANGES = st.sampled_from(["{a..c}", "{c..a}", "{1..3}", "{01..2}", "{b..b}", "{x..}", "{1..a}", "{}", "{x}", "{"])

    def groups(inner):
        parts = st.lists(inner, min_size=1, max_size=3).map(lambda items: "{%s}" % ",".join(items))
        return st.lists(st.one_of(inner, parts, RANGES, st.sampled_from(["}", ","])), min_size=1, max_size=3).map("".join)

    WORDS = st.recursive(st.one_of(ATOMS, RANGES), groups, max_leaves=8)

    class BraceProperties(BraceProject):
        @example("{x,backbone}")
        @example("{},backbone,x}")
        @example("x{},/../backbone,x}")
        @example("{x}{backbone,y}")
        @example("{a..c}ackbone")
        @example("{x,{y,backbone}")
        @example("{backbone'}',x}")
        @example("{},backbone}x")
        @example("{..}")
        @given(WORDS)
        @settings(max_examples=examples(250))
        def test_the_gate_decides_as_the_shells_expand_the_word(self, word):
            # ~, a leading # or - and an empty word mean something else to a shell or to touch.
            assume(word and word[0] not in "#-~=" and len(word) < 200)
            found = [words for words in (expansions(shell, word) for shell in SHELLS) if words is not None]
            assume(found)
            result = self.hook("touch " + word)
            if any(map(protected, found)):
                self.assertEqual(result.returncode, 2, "%s is %s and was let through" % (word, found))
            elif len(found) == len(SHELLS) and all(words == found[0] for words in found) and not protected([word]):
                self.assertEqual(result.returncode, 0, "%s is %s and was refused: %s" % (word, found, result.stderr))


if __name__ == "__main__":
    unittest.main()
