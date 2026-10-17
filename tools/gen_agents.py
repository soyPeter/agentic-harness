#!/usr/bin/env python3
"""Generate the Codex and OpenCode role agents from the Claude Code ones (payload/owned/.claude/agents/*.md).

  tools/gen_agents.py           write payload/owned/.codex/agents/*.toml and payload/owned/.opencode/agents/*.md
  tools/gen_agents.py --check   exit 1 if they are out of date (the self-test runs this)

The Claude Code files are the source: edit them, then regenerate. Tool limits that Codex can't express per agent
are enforced by the harness hooks, which know each role's write scope.
"""
import json
import re
import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent.parent / "payload" / "owned"
SOURCE = PAYLOAD / ".claude" / "agents"
NOTE = ("You run outside Claude Code, so map its tool names to yours: read files with your read or shell tool, and "
        "load a skill by printing its `.claude/skills/<name>/SKILL.md` (for example with `cat`); the harness records "
        "that as loaded. The harness hooks apply the same gates here, including what the {name} role may edit.")


def parse(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise SystemExit("%s has no frontmatter" % path)
    front, body = m.groups()
    field = lambda key: (re.search(r"^%s:\s*(.+)$" % key, front, re.M) or [None, ""])[1].strip()
    return {"name": field("name"), "description": field("description"),
            "tools": [t.strip() for t in field("tools").split(",") if t.strip()], "body": body.strip() + "\n"}


def codex(agent):
    body = NOTE.format(name=agent["name"]) + "\n\n" + agent["body"]
    if "'''" in body:
        raise SystemExit("%s: the body contains ''' and can't be a TOML literal string" % agent["name"])
    return ("# Agentic harness: generated from .claude/agents/%s.md by tools/gen_agents.py (harness-owned).\n"
            "name = %s\ndescription = %s\ndeveloper_instructions = '''\n%s'''\n"
            % (agent["name"], json.dumps(agent["name"]), json.dumps(agent["description"]), body))


def opencode(agent):
    rules = []
    if not {"Write", "Edit", "MultiEdit"} & set(agent["tools"]):
        rules.append(("edit", "deny"))
    if "Bash" not in agent["tools"]:
        rules.append(("shell", "deny"))
    permissions = "".join("  - action: %s\n    resource: \"*\"\n    effect: %s\n" % rule for rule in rules)
    return ("---\n# Agentic harness: generated from .claude/agents/%s.md by tools/gen_agents.py (harness-owned).\n"
            "description: %s\nmode: subagent\n%s---\n\n%s\n\n%s"
            % (agent["name"], json.dumps(agent["description"]), ("permissions:\n" + permissions) if rules else "",
               NOTE.format(name=agent["name"]), agent["body"]))


def outputs():
    files = {}
    for path in sorted(SOURCE.glob("*.md")):
        agent = parse(path)
        files[PAYLOAD / ".codex" / "agents" / ("%s.toml" % agent["name"])] = codex(agent)
        files[PAYLOAD / ".opencode" / "agents" / ("%s.md" % agent["name"])] = opencode(agent)
    return files


def main(argv):
    files = outputs()
    stale = [p for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    expected = set(files)
    extra = [p for d in (PAYLOAD / ".codex" / "agents", PAYLOAD / ".opencode" / "agents") if d.is_dir()
             for p in d.iterdir() if p not in expected]
    if "--check" in argv:
        for p in stale + extra:
            print("out of date: %s" % p.relative_to(PAYLOAD.parent.parent))
        return 1 if stale or extra else 0
    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[p], encoding="utf-8")
        print("wrote %s" % p.relative_to(PAYLOAD.parent.parent))
    for p in extra:
        p.unlink()
        print("removed %s" % p.relative_to(PAYLOAD.parent.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
