"""Whether a change to the engine leaves the shell gate's answers as they are: the same commands through the
pre-tool-use hook of this checkout and of another commit, comparing exit codes and messages. For a change that must not
change them (a faster scan, a refactor); run by hand, not by run-tests.sh.

    python3 tests/gate_equivalence.py --base origin/main [--examples 1000] [--corpus]

--corpus also runs every string of the gate tests as a command, as the main agent and as the deliverer. Commands the
base runs out of time on are counted, not compared. Needs hypothesis (pip install -r tests/requirements.txt).
"""
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from hypothesis import HealthCheck, given, settings, strategies as st

ROOT = Path(__file__).resolve().parents[1]
CORPUS_TESTS = ("deliverer-gate", "external-delivery", "agent-hooks", "agent-config", "admission", "eval-replay",
                "factory-contract", "machine-guard", "no-merge-profile", "sandbox-gate")
CARRIERS = ("{c}", "x=$({c})", 'echo "$({c})"', "echo `{c}`", "cat <({c})", "bash -c {q}", "eval {q}", "timeout 60 {c}",
            "sudo -u x env -i A=1 {c}", "bash <<'EOF'\n{c}\nEOF", "bash <<< {q}", "cat <<EOF\n$({c})\nEOF", "( {c} )",
            "({c})2>&1", "{{ {c}; }}", "if true; then {c}; fi", "case x in x) {c};; esac", "f() {{ {c}; }}; f",
            "function f {{ {c}; }}", "> /dev/null {c}", "{c} 2>&1 >out | cat", "{c} | sh", "echo {q} | bash", "! ! {c}",
            "A=1 B=2 {c}", "x='{c}' ; $x", "trap {q} EXIT", "xargs {c}", "find . -exec {c} ';'", "# {c}", "echo '{c}'",
            "cd /tmp && {c}", "cat a|{c}|cat", "busybox {c}", "() () {c}", "watch {q}", "git commit -m {q}; {c}")
TOKENS = ("'", '"', "`", "$(", ")", "(", "{", "}", "${", "$x", "\\", "\n", " ", "\t", ";", "&", "&&", "|", "||", ">", ">>",
          "<", "<<EOF\n", "\nEOF\n", "<<<", "<(", ">(", ">|", "&>", "2>&1", "2>", "#", "*", "?", "[", "]", "~/", "a", "f",
          "f()", "()", "function f", "case", "in", "x)", "/dev/null", "-", "cd ", "rm ", "-rf ", "tee ", "cp ", "git ",
          "push ", "commit ", "--no-verify", "main", "gh ", "pr ", "merge ", "view ", "api ", "repo ", "alias g=gh",
          "backbone/", "backbone/.verdicts", ".git/config", ".claude/settings.json", "~/.claude", "harness.py ", "sh ",
          "-c ", "eval ", "xargs ", "timeout 1 ", "env ", "x=1 ", "export ", "for x in ", "python3 ", "sed -i ", "find ",
          "-delete", "source ", "!", "time ", " ", "é")


def corpus():
    """Every short string in the gate tests, and the commands the shell suite gives the hook."""
    found = []
    for name in CORPUS_TESTS:
        for node in ast.walk(ast.parse((ROOT / "tests" / ("test-%s.py" % name)).read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and 2 < len(node.value) < 400:
                found.append(node.value)
    found += re.findall(r"bash_json '([^'\n]{3,400})'", (ROOT / "tests/run-tests.sh").read_text())
    return sorted({text for text in found if "\0" not in text})


def commands(texts):
    chosen = st.sampled_from(texts)
    tokens = st.lists(st.sampled_from(TOKENS), min_size=1, max_size=14).map("".join)

    @st.composite
    def edited(draw):
        text, at = draw(chosen), draw(st.integers(0, 400))
        cut = draw(st.integers(0, 4))
        return text[:at] + draw(tokens) + text[at + cut:]
    carried = st.builds(lambda carrier, text: carrier.format(c=text, q=shlex.quote(text)), st.sampled_from(CARRIERS),
                        chosen | tokens)
    joined = st.builds(lambda a, op, b: a + op + b, chosen, st.sampled_from((";", " && ", " | ", "\n", " > ", " ", "|")),
                       chosen | tokens)
    padded = st.builds(lambda text, token, count: text + " " + token * count, chosen, st.sampled_from(TOKENS),
                       st.integers(1, 60))
    return chosen | carried | carried | joined | edited() | tokens | padded


class Gate(object):
    """The pre-tool-use hook of one checkout, in a project of its own on a feature branch."""

    def __init__(self, checkout, folder):
        self.project = folder / "project"
        self.project.mkdir(parents=True)
        (folder / "home").mkdir()
        (folder / "bin").mkdir()
        (folder / "bin/gh").write_text("#!/bin/sh\necho '{\"labels\": []}'\n")
        (folder / "bin/gh").chmod(0o755)
        kept = {k: v for k, v in os.environ.items() if not k.startswith(("HARNESS_", "CLAUDE_"))}
        self.env = dict(kept, HOME=str(folder / "home"), GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="test",
                        GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test",
                        GIT_COMMITTER_EMAIL="test@example.com", CLAUDE_PROJECT_DIR=str(self.project),
                        HARNESS_HOOK_BUDGET="60", PATH=str(folder / "bin") + os.pathsep + os.environ["PATH"])
        for command in (["git", "init", "-q", "-b", "main"], [str(checkout / "bootstrap.sh"), str(self.project)],
                        ["git", "add", "-A"], ["git", "commit", "-qm", "chore: adopt agentic harness"],
                        ["git", "remote", "add", "origin", "git@github.com:o/r.git"],
                        ["git", "checkout", "-q", "-b", "feat/x"]):
            subprocess.run(command, cwd=str(self.project), check=True, capture_output=True,
                           env=dict(self.env, HARNESS_VERIFY="off"))

    def answer(self, command, agent, deliver):
        data = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.project)}
        if agent:
            data.update(agent_id="a1", agent_type=agent)
        result = subprocess.run(["python3", "-B", str(self.project / "scripts/harness/lib/harness.py"), "hook",
                                 "pre-tool-use"], cwd=str(self.project), input=json.dumps(data), capture_output=True,
                                text=True, env=dict(self.env, HARNESS_DELIVER=deliver))
        message = result.stderr if result.returncode != 1 else result.stderr.strip().splitlines()[-1]   # a crash
        return result.returncode, message.replace(str(self.project.parent), "<folder>")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--examples", type=int, default=1000)
    parser.add_argument("--corpus", action="store_true")
    options = parser.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="gate-equivalence-")).resolve()
    seen, pool = Counter(), ThreadPoolExecutor(2)
    try:
        (folder / "old").mkdir()
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", options.base], check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(folder / "old")], input=archive.stdout, check=True)
        shutil.copytree(str(ROOT), str(folder / "new"), symlinks=True,
                        ignore=shutil.ignore_patterns(".git", ".hypothesis", "__pycache__"))
        gates = [Gate(folder / name, folder / side) for name, side in (("old", "b"), ("new", "h"))]

        def same(command, agent, deliver):
            base, head = pool.map(lambda gate: gate.answer(command, agent, deliver), gates)
            if "ran out of time" in base[1]:
                seen["the base ran out of time"] += 1
                return
            seen[{0: "allowed", 2: "refused"}.get(base[0], "crashed")] += 1
            assert base == head, "%s (%s, %s)\n  base: %r\n  head: %r" % (ascii(command), agent, deliver, base, head)

        texts = corpus()
        if options.corpus:
            for text in texts:
                for agent in (None, "deliverer"):
                    same(text, agent, "off")
            print("corpus: %d commands, as the main agent and the deliverer: %s" % (len(texts), dict(seen)), flush=True)
            seen.clear()

        @settings(max_examples=options.examples, deadline=None, database=None, print_blob=True,
                  suppress_health_check=list(HealthCheck))
        @given(commands(texts), st.sampled_from((None, None, "implementer", "deliverer", "deliverer")),
               st.sampled_from(("off", "off", "external")))
        def the_gate_answers_as_the_base_does(command, agent, deliver):
            same(command.replace("\0", ""), agent, deliver)
        the_gate_answers_as_the_base_does()
        print("generated: %d examples, no difference: %s" % (sum(seen.values()), dict(seen)), flush=True)
    finally:
        pool.shutdown()
        shutil.rmtree(str(folder), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
