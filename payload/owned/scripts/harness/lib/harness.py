#!/usr/bin/env python3
"""Agentic harness runtime: Claude Code hooks, git hooks, gates and health checks.

Harness-owned file: the harness update replaces it. Upstream changes to the
harness repository instead of editing this copy.

Usage:
  harness.py hook session-start|pre-tool-use|post-tool-use|stop   (hook JSON on stdin)
  harness.py hook grill-stop|judge-stop                           (verdict recorders, agent-scoped)
  harness.py hook agent-guard <agent>                             (write scope, agent-scoped)
  harness.py git pre-commit
  harness.py git commit-msg <message-file>
  harness.py spec-check <task-id>
  harness.py scan [--quiet]                                       (existing rule violations in tracked files)
  harness.py catalog                                              (stack packs available for adoption)
  harness.py decisions [--last N]                                 (decision-layer log summary)
  harness.py adopt <pack>[,<pack>] --adr ADR-NNN --with <opts> --without <opts> [--dry-run]
  harness.py adopt --remove <pack>[,<pack>] [--dry-run]
  harness.py verify [--range <base>..<tip>] [--allow-user-changes]   (gates on the staged change, or a CI range)
  harness.py approve <task-id>                                    (autonomous mode: policy approval of a low-risk spec)
  harness.py escalate <task-id> --reason <text> [--kind <k>] [--needed <text>]
  harness.py escalations                                          (open escalations for the user)
  harness.py risk <task-id>
  harness.py run [--max-tasks N] [--only <task>] [--worktree [--pr]] [--dry-run]   (autonomous, unattended)
  harness.py report [--days N] [--json]                           (events: verdicts, escalations, blocks, runs)
  harness.py ci-judge --range <base>..<tip>                       (CI: independent re-judging of finished tasks)
  harness.py ci-protect [--branch main] [--with-judge] [--dry-run] (require the CI checks; needs gh)
  harness.py doctor
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True   # no __pycache__ in the project
sys.path.insert(0, str(Path(__file__).resolve().parent))
import decisions  # noqa: E402  (sibling module)

# HARNESS_ROOT lets CI run the base branch's copy of this file against a pull request's checkout,
# so a pull request cannot change the verifier that checks it.
ROOT = Path(os.environ.get("HARNESS_ROOT") or Path(__file__).resolve().parents[3]).resolve()
BACKBONE = ROOT / "backbone"
TASKS = BACKBONE / "3-TASKS.md"
MEMORY = BACKBONE / "6-MEMORY.md"
SPECS = BACKBONE / "specs"
ADRS = BACKBONE / "adr"
VERDICTS = BACKBONE / ".verdicts"
CONF_FILE = BACKBONE / "harness.conf"
LOCK_FILE = BACKBONE / ".harness-lock.json"
SKILLS = ROOT / ".claude" / "skills"
AGENTS_DIR = ROOT / ".claude" / "agents"
SETTINGS_FILE = ROOT / ".claude" / "settings.json"
RULE_FILES = [ROOT / "scripts/harness/guardrails.core.conf", BACKBONE / "guardrails.conf"]
ROUTE_FILES = [ROOT / "scripts/harness/routing.core.conf", BACKBONE / "routing.conf"]
CATALOG_DIR = ROOT / "scripts/harness/catalog"
HOOKS_PATH = "scripts/harness/git-hooks"
HOOK_MARK = "scripts/harness/"
FILE_TOOLS = ("Write", "Edit", "MultiEdit")
PIPELINE_AGENTS = ("analyst", "architect", "griller", "tester", "implementer", "judge", "debugger", "scribe")
USER_ONLY_KEYS = ("HARNESS_SPEC_GATE", "HARNESS_SKILL_GATE", "HARNESS_JUDGE_GATE", "HARNESS_JUDGE_MAX_ROUNDS",
                  "HARNESS_VERIFY", "HARNESS_ORCHESTRATOR_SCOPE",
                  "HARNESS_AUTONOMY", "HARNESS_AUTO_APPROVE", "HARNESS_RISK_TERMS", "HARNESS_RISK_PATHS",
                  "HARNESS_RISK_MAX_FILES", "HARNESS_GRILL_MAX_ROUNDS", "HARNESS_ESCALATE_GH",
                  "HARNESS_AGENT_CMD", "HARNESS_RUN_TASK_TIMEOUT", "HARNESS_RUN_ATTEMPTS",
                  "HARNESS_RUN_MAX_COST", "HARNESS_CI_JUDGE_CMD",
                  "HARNESS_DECISION_PROVIDER", "HARNESS_DECISION_MODE", "HARNESS_DECISION_ADR",
                  "HARNESS_DECISION_CMD", "HARNESS_DECISION_MODEL", "HARNESS_DECISION_URL",
                  "HARNESS_KNOWLEDGE_ROOT", "HARNESS_KNOWLEDGE_TOOLS", "HARNESS_KNOWLEDGE_PATHS",
                  "HARNESS_TESTER", "HARNESS_ACCEPTANCE_PATHS", "HARNESS_ORCA_AGENTS", "HARNESS_ORCA_LAUNCH",
                  "HARNESS_SPEC_MAX_ITEMS")
# The knowledge source: an MCP server registered as "knowledge" (claude mcp add) over a folder of notes, that the
# analyst, architect and griller consult when grilling raises questions. Read-only; answers are cited as vault:<path>.
KNOWLEDGE_TOOL_PREFIX = "mcp__knowledge__"
KNOWLEDGE_PATH_KEYS = ("path", "paths", "note", "notes", "hub", "name", "file", "files", "target")
# Paths an agent may change only through the file tools, where the hooks see the change. Shell writes to
# them are refused: they would skip the gates (task states, approvals, verdicts, settings, skill state).
SHELL_PROTECTED = (r"^backbone(/|$)", r"^scripts/harness(/|$)", r"^\.claude(/|$)", r"^\.codex(/|$)", r"^\.opencode(/|$)",
                   r"^(AGENTS|CLAUDE)\.md$",
                   r"^\.git/(hooks|harness)(/|$)", r"^\.git/config$")
# Harness files whose edits change enforcement; verify refuses commits that change them away from the lock.
ENFORCEMENT_FILES = (r"^scripts/harness/", r"^\.claude/agents/", r"^\.github/workflows/harness-[^/]+\.ya?ml$",
                     r"^\.devcontainer/harness-agent/", r"^\.codex/(hooks\.json$|agents/|rules/harness\.rules$)",
                     r"^\.opencode/(plugins/harness\.js$|agents/)")
# What the main session (the orchestrator) may edit itself; specs, ADRs and code go through the role agents.
ORCHESTRATOR_ALLOW = (r"^backbone/(?!specs/|adr/|\.verdicts/)", r"^\.claude/skills/", r"^CLAUDE\.md$")
DECISIONS_FILE = ROOT / "scripts/harness/decisions.json"
ESCALATIONS = BACKBONE / "escalations.md"
AUTONOMY_MODES = ("supervised", "autonomous")
BLOCKED_NOTE = re.compile(r"\s+[-\u2014]+\s+BLOCKED:\s*(.*)$")
POLICY_APPROVAL = re.compile(r"^\s*Approved-by:\s*policy:(\S+)\s*\((.*)\)", re.M)

# Write scope per agent: ("allow", patterns) permits only matches; ("deny", patterns) refuses matches.
AGENT_SCOPES = {
    "analyst": ("allow", (r"^backbone/specs/[^/]+\.md$", r"^backbone/1-PRD\.md$")),
    "architect": ("allow", (r"^backbone/adr/[^/]+\.md$", r"^backbone/specs/[^/]+\.md$",
                            r"^backbone/5-DECISIONS\.md$", r"^backbone/2-PLANNING\.md$")),
    "scribe": ("allow", (r"^backbone/6-MEMORY\.md$", r"^backbone/adr/[^/]+\.md$", r"^backbone/5-DECISIONS\.md$")),
    "implementer": ("deny", (r"^backbone/", r"^\.claude/", r"^\.codex/", r"^\.opencode/", r"^scripts/harness/",
                             r"^(AGENTS|CLAUDE)\.md$")),
    # Reviewers never edit. Claude Code enforces this with their tool list; Codex has no per-agent tool list.
    "griller": ("allow", ()),
    "judge": ("allow", ()),
    "debugger": ("allow", ()),
    "tester": ("allow", ()),   # plus HARNESS_ACCEPTANCE_PATHS (see role_scope)
}
SCOPE_HELP = {
    "analyst": "It writes specs (backbone/specs/) and the PRD only.",
    "architect": "It writes ADRs (backbone/adr/), their index, 2-PLANNING.md and the Architecture section of specs.",
    "scribe": "It writes 6-MEMORY.md and ADRs for decisions taken during implementation.",
    "implementer": "It writes code and tests only; backbone/, .claude/ and harness files belong to other roles.",
    "griller": "It reviews the spec and asks questions; it never edits files.",
    "judge": "It judges the code against the spec; it never edits files.",
    "debugger": "It diagnoses the judge's failures and writes a fix brief; it never edits files.",
    "tester": "It writes acceptance tests only, in files matching HARNESS_ACCEPTANCE_PATHS.",
}

# A task line, not any mention of the marker (legends and prose must not count).
WIP_LINE = re.compile(r"^\s*[-*]\s+\[WIP\]\s*")
PENDING_LINE = re.compile(r"^\s*[-*]\s+\[ \]\s*")
DONE_LINE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s*")
TASK_REF = re.compile(r"\bTask\s+([A-Za-z0-9._-]*[A-Za-z0-9])")
TASK_HEAD = re.compile(r"^#{2,4}\s+Task\s+([A-Za-z0-9._-]*[A-Za-z0-9])")
ANY_HEAD = re.compile(r"^#{1,4}\s")
APPROVAL_LINE = re.compile(r"^\s*Approved-by:\s*\S")
ADR_ID = re.compile(r"\bADR-\d{3,}\b")
ADR_SECTIONS = ("Status", "Context", "Decision", "Alternatives considered", "Consequences")
PLACEHOLDER = re.compile(r"\{\{FILL:[^}]*\}\}")
STUB_WORDS = re.compile(r"\b(TODO|TBD|FIXME)\b")

DEFAULTS = {
    "HARNESS_PROJECT_NAME": "",
    "HARNESS_BUILD_CMD": "",
    "HARNESS_TEST_CMD": "",
    "HARNESS_TEST_PATHS": r"(^|/)(tests?|__tests__|spec|it)/|(^|/)test_[^/]*$|[._-](test|spec|it)\.[A-Za-z0-9]+$"
                          r"|(Test|Tests|IT|Spec)\.[A-Za-z0-9]+$",
    "HARNESS_COMMIT_TYPES": "feat|fix|refactor|perf|test|docs|build|ci|chore|style|revert",
    "HARNESS_SUBJECT_MAX": "72",
    "HARNESS_STOP_MODE": "remind",
    "HARNESS_ALLOW_PARALLEL_WIP": "0",
    "HARNESS_SPEC_GATE": "on",
    "HARNESS_SKILL_GATE": "on",
    "HARNESS_JUDGE_GATE": "on",
    "HARNESS_JUDGE_MAX_ROUNDS": "2",
    "HARNESS_VERIFY": "block",
    "HARNESS_ORCHESTRATOR_SCOPE": "on",
    "HARNESS_TEST_TIMEOUT": "900",
    "HARNESS_AUTONOMY": "supervised",
    "HARNESS_AUTO_APPROVE": "low",
    "HARNESS_RISK_TERMS": r"(?i)\b(auth(entication|orization)?|logins?|passwords?|secrets?|tokens?|credentials?|"
                          r"encrypt\w*|access control|RBAC|role-based|(user|admin) roles?|permission (model|check|system)s?|"
                          r"payments?|billing|personal data|PII|GDPR|migrations?|"
                          r"schema changes?|breaking changes?|public API|deletes? (all|every))\b",
    "HARNESS_RISK_PATHS": r"(?i)(^|/)(auth|security|migrations?|db/migration|infra|deploy|\.github)/|openapi|swagger"
                          r"|Dockerfile|(^|/)(pom\.xml|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|package\.json|"
                          r"go\.mod|Cargo\.toml|requirements[^/]*\.txt|pyproject\.toml)$",
    "HARNESS_RISK_MAX_FILES": "20",
    "HARNESS_GRILL_MAX_ROUNDS": "3",
    "HARNESS_ESCALATE_GH": "off",
    "HARNESS_AGENT_CMD": "claude -p --permission-mode acceptEdits --output-format json",
    "HARNESS_RUN_TASK_TIMEOUT": "3600",
    "HARNESS_RUN_ATTEMPTS": "2",
    "HARNESS_RUN_MAX_COST": "",
    "HARNESS_CI_JUDGE_CMD": "claude -p --agent judge --dangerously-skip-permissions --output-format json",
    "HARNESS_SKILL_MAX_AGE": "180",
    "HARNESS_SCOPE_CHECK": "on",
    "HARNESS_CROSS_SCOPES": "deps|build|ci|docs|backbone|harness|release|config|tests?",
    "HARNESS_COMMIT_NUDGE": "8",
    "HARNESS_CONTAINER_ENGINE": "",
    "HARNESS_DECISION_PROVIDER": "none",
    "HARNESS_DECISION_MODE": "off",
    "HARNESS_DECISION_ADR": "",
    "HARNESS_DECISION_CMD": "",
    "HARNESS_DECISION_MODEL": "",
    "HARNESS_DECISION_TIMEOUT": "20",
    "HARNESS_DECISION_URL": "",
    "HARNESS_KNOWLEDGE_ROOT": "",
    "HARNESS_KNOWLEDGE_TOOLS": r"^((search|read|get|list|find|query|lookup|fetch)\w*|note_meta|batch_read|backlinks|"
                               r"hub_children|decisions_status|pending_questions)$",
    "HARNESS_KNOWLEDGE_PATHS": "",
    "HARNESS_TESTER": "off",
    "HARNESS_ACCEPTANCE_PATHS": r"(^|/)acceptance([/._-]|$)",
    "HARNESS_DEBUGGER": "on",
    "HARNESS_SPEC_MAX_ITEMS": "30",
    "HARNESS_ORCA_AGENTS": "default=claude",
    "HARNESS_ORCA_LAUNCH": "codex=codex --dangerously-bypass-hook-trust -c check_for_update_on_startup=false",
}
STOP_MODES = ("remind", "block", "off")


# --------------------------------------------------------------------------- utilities

def read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_conf(text):
    values = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            value = m.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[m.group(1)] = value
    return values


def conf():
    """harness.conf values (KEY="value" lines, never sourced), overridden by environment."""
    values = dict(DEFAULTS)
    values.update(parse_conf(read(CONF_FILE)))
    for key in list(values):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def gate_on(key):
    return conf()[key] != "off"


# A hook Claude Code kills for running too long counts as a non-blocking error: the tool call goes through.
# So hooks keep their own budget below the settings timeout (30 s) and fail closed when they run out,
# and git calls inside hooks time out well before that.
GIT_TIMEOUT = 120
HOOK_BUDGET = 25
FAIL_CLOSED_HOOKS = ("pre-tool-use", "agent-guard")


def git(*args):
    try:
        result = subprocess.run(["git"] + list(args), cwd=str(ROOT), capture_output=True, text=True,
                                timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        log_event("git-timeout", args=list(args)[:6])
        return ""
    return result.stdout if result.returncode == 0 else ""


def rel(path_str):
    """Repository-relative POSIX path, or the path unchanged if it lies outside the repo."""
    path = Path(path_str)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def lock():
    try:
        return json.loads(read(LOCK_FILE) or "{}")
    except ValueError:
        return {}


def owned_files():
    return set(lock().get("files", {}))


def sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")[:60] or "task"


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def md_section(text, title):
    """Body of the '## <title>' section (case-insensitive), or None if absent."""
    m = re.search(r"^##\s+%s\s*$" % re.escape(title), text, re.M | re.I)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def bullets(section):
    return [re.sub(r"^\s*[-*]\s+", "", line).strip()
            for line in (section or "").splitlines() if re.match(r"^\s*[-*]\s+\S", line)]


def placeholders():
    """FILL placeholders left in project-owned backbone docs: {relative path: count}."""
    owned = owned_files()
    found = {}
    for path in sorted(BACKBONE.glob("**/*.md")):
        name = path.relative_to(ROOT).as_posix()
        if name in owned:
            continue
        count = len(PLACEHOLDER.findall(read(path)))
        if count:
            found[name] = count
    return found


def stubs(path, text=None):
    text = read(path) if text is None else text
    lines = [n for n, line in enumerate(text.splitlines(), 1) if STUB_WORDS.search(line)]
    if not lines:
        return []
    return ["%s has TODO/TBD/FIXME stubs on line(s) %s; write the real content"
            % (Path(path).name, ", ".join(map(str, lines[:5])))]


# --------------------------------------------------------------------------- tasks

def mask_comments(text):
    """text with HTML comments blanked out but line breaks kept, so line indexes still match the file."""
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text or "", flags=re.S)


def wip_tasks(text=None):
    text = mask_comments(read(TASKS) if text is None else text)
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1) if WIP_LINE.match(line)]


def task_id_at(lines, index):
    """Id of the task on lines[index]: 'Task <id>' in the line itself, else the nearest
    '### Task <id>' heading above it, else a slug of the line."""
    m = TASK_REF.search(lines[index])
    if m:
        return m.group(1)
    for i in range(index - 1, -1, -1):
        m = TASK_HEAD.match(lines[i])
        if m:
            return m.group(1)
        if ANY_HEAD.match(lines[i]):
            break
    return slug(re.sub(r"^\s*[-*]\s+\[[^\]]*\]\s*", "", lines[index]).strip())


def wip_task_ids(text=None):
    text = mask_comments(read(TASKS) if text is None else text)
    lines = text.splitlines()
    return [task_id_at(lines, i) for i, line in enumerate(lines) if WIP_LINE.match(line)]


def finished_tasks(before, after):
    """Ids of [WIP] tasks this edit takes out of progress, other than by reverting them to
    '- [ ]' (abandoning). Marking [x], rewording or deleting all count as finishing."""
    after_lines = mask_comments(after).splitlines()
    pending = {PENDING_LINE.sub("", line).strip() for line in after_lines if PENDING_LINE.match(line)}
    lines = mask_comments(before).splitlines()
    finished = []
    for i, line in enumerate(lines):
        if WIP_LINE.match(line) and line not in after_lines:
            if WIP_LINE.sub("", line).strip() not in pending:
                finished.append(task_id_at(lines, i))
    return finished


def started_tasks(before, after):
    old = wip_task_ids(before)
    return [task for task in wip_task_ids(after) if task not in old]


# --------------------------------------------------------------------------- specs and ADRs

def spec_path(task):
    return SPECS / ("%s.md" % slug(task))


def spec_rel(task):
    return spec_path(task).relative_to(ROOT).as_posix()


def spec_items(text, kind, task):
    pattern = re.compile(r"^\s*[-*]\s+\**(%s-%s-\d+)\b\**(.*)$" % (kind, re.escape(task)), re.M)
    return [(m.group(1), m.group(2)) for m in pattern.finditer(text)]


def spec_adrs(text):
    return sorted(set(ADR_ID.findall(md_section(strip_comments(text), "Architecture") or "")))


def spec_skills(text):
    names = []
    for item in bullets(md_section(strip_comments(text), "Skills")):
        m = re.match(r"`?([a-z0-9][a-z0-9-]*)`?", item)
        if m:
            names.append(m.group(1))
    return names


def adr_file(adr_id):
    found = sorted(ADRS.glob("%s-*.md" % adr_id)) + ([ADRS / ("%s.md" % adr_id)] if (ADRS / ("%s.md" % adr_id)).is_file() else [])
    return found[0] if found else None


def adr_status(text):
    lines = [line.strip() for line in (md_section(strip_comments(text), "Status") or "").splitlines() if line.strip()]
    return lines[0] if lines else ""


def validate_adr(text, name):
    body = strip_comments(text)
    problems = ["%s: section '## %s' is missing or empty" % (name, title)
                for title in ADR_SECTIONS if not (md_section(body, title) or "").strip()]
    return problems + stubs(name, body)


def without_approval(text):
    m = re.search(r"^##\s+Approval\s*$", text, re.M | re.I)
    return text[:m.start()] if m else text


def without_section(text, title):
    """text without any '## <title>' section."""
    return re.sub(r"^##\s+%s\s*\n(?:(?!##\s).*\n?)*" % re.escape(title), "", text, flags=re.M | re.I)


def knowledge_root():
    """The knowledge source's folder (HARNESS_KNOWLEDGE_ROOT), or None when the knowledge source is off."""
    value = conf()["HARNESS_KNOWLEDGE_ROOT"].strip()
    if not value:
        return None
    path = Path(os.path.expanduser(value))
    return (path if path.is_absolute() else ROOT / path).resolve()


def knowledge_path_allowed(path):
    """A vault-relative path inside the folders HARNESS_KNOWLEDGE_PATHS allows (all when empty)."""
    path = path.strip().lstrip("/")
    if not path or ".." in Path(path).parts:
        return False
    prefixes = [p.strip("/") for p in conf()["HARNESS_KNOWLEDGE_PATHS"].split() if p.strip("/")]
    return not prefixes or any(path == p or path.startswith(p + "/") for p in prefixes)


def top_level_items(section):
    """The section's top-level bullets, each with its indented continuation and sub-bullets joined to it (a nested
    list belongs to the item above it)."""
    items = []
    for line in (section or "").splitlines():
        if re.match(r"^[-*]\s+\S", line):
            items.append(re.sub(r"^[-*]\s+", "", line).strip())
        elif items and line.strip():
            items[-1] += " " + line.strip()
    return items


def knowledge_citation_problems(text):
    """Assumptions without a source, or citing vault:<path> notes that don't exist or aren't allowed."""
    problems = []
    root = knowledge_root()
    for n, item in enumerate(top_level_items(md_section(strip_comments(text), "Assumptions")), 1):
        if item.lower().rstrip(".") in ("none", "n/a"):
            continue
        label = (re.match(r"^(A\d+)", item) or [None, "assumption %d" % n])[1]
        if "source:" not in item.lower():
            problems.append("%s has no (source: ...)" % label)
        for cited in re.findall(r"vault:([^\s;,)]+)", item):
            cited = cited.rstrip(".")
            if root is None:
                problems.append("%s cites vault:%s, but the knowledge source is off (HARNESS_KNOWLEDGE_ROOT)"
                                % (label, cited))
                continue
            target = (root / cited.lstrip("/")).resolve()
            candidates = [target, target.with_name(target.name + ".md")]
            inside = target == root or root in target.parents
            if not inside or not knowledge_path_allowed(cited):
                problems.append("%s cites vault:%s, outside HARNESS_KNOWLEDGE_PATHS" % (label, cited))
            elif not any(c.is_file() for c in candidates):
                problems.append("%s cites vault:%s, which is not a note in the knowledge source" % (label, cited))
    return problems


def knowledge_guard(tool, tool_input):
    """Pre-tool check for the knowledge server's tools: on, read-only, inside the allowed folders."""
    name = tool[len(KNOWLEDGE_TOOL_PREFIX):]
    if knowledge_root() is None:
        deny("Harness blocked %s: the knowledge source is off (HARNESS_KNOWLEDGE_ROOT is empty). Answer from "
             "backbone/ and escalate what it cannot answer." % tool)
    try:
        read_only = re.search(conf()["HARNESS_KNOWLEDGE_TOOLS"], name)
    except re.error:
        read_only = None
    if not read_only:
        deny("Harness blocked %s: the knowledge source is read-only for agents (HARNESS_KNOWLEDGE_TOOLS). Record "
             "answers in the spec's Assumptions; questions it can't answer are escalated, not written to it." % tool)
    backbone_paths = [v for k, v in tool_input.items() if k in KNOWLEDGE_PATH_KEYS and isinstance(v, str)
                      and re.match(r"^(\./)?(backbone|src|tests?|scripts|\.claude)/", v)]
    prefixed = [v for k, v in tool_input.items() if k in KNOWLEDGE_PATH_KEYS and isinstance(v, str)
                and v.startswith("vault:")]
    if prefixed:
        deny("Harness blocked %s on %s: vault: marks a citation in the spec; call the server with the plain path "
             "(%s)." % (tool, prefixed[0], prefixed[0][len("vault:"):]))
    if backbone_paths:
        deny("Harness blocked %s on %s: that is a project file; read it with Read. The knowledge server serves "
             "only the vault." % (tool, ", ".join(backbone_paths[:4])))
    if conf()["HARNESS_KNOWLEDGE_PATHS"].split():
        named = []
        for key in KNOWLEDGE_PATH_KEYS:
            value = tool_input.get(key)
            named += [value] if isinstance(value, str) else [v for v in (value or []) if isinstance(v, str)]
        outside = [v for v in named if "/" not in v or not knowledge_path_allowed(v)]
        if outside:
            deny("Harness blocked %s on %s: only notes under HARNESS_KNOWLEDGE_PATHS (%s) may be read, named by "
                 "their path in the vault." % (tool, ", ".join(outside[:4]), conf()["HARNESS_KNOWLEDGE_PATHS"]))
    looked_up = {k: tool_input[k] for k in ("query", "path", "paths", "name", "hub", "pillar")
                 if isinstance(tool_input.get(k), (str, list)) and tool_input.get(k)}
    log_event("knowledge", tool=name, **{k: (v if isinstance(v, str) else v[:5]) for k, v in looked_up.items()})


def approval_lines(text):
    return sorted(line.strip() for line in text.splitlines() if APPROVAL_LINE.match(line))


def approved(text):
    return bool(approval_lines(md_section(strip_comments(text), "Approval") or ""))


def validate_spec(task, text=None):
    text = read(spec_path(task)) if text is None else text
    if not text.strip():
        return ["no spec at %s (the analyst agent writes it)" % spec_rel(task)]
    body = strip_comments(text)
    problems = []
    reqs = spec_items(body, "REQ", task)
    acs = spec_items(body, "AC", task)
    req_ids = {req for req, _ in reqs}
    if not reqs:
        problems.append("no requirements: add '- REQ-%s-1: The system shall ...'" % task)
    if not acs:
        problems.append("no acceptance criteria: add '- AC-%s-1 (REQ-%s-1): Given ..., when ..., then ...'" % (task, task))
    limit = conf()["HARNESS_SPEC_MAX_ITEMS"]
    if limit.isdigit() and int(limit) and len(reqs) + len(acs) > int(limit):
        problems.append("the spec has %d requirements and acceptance criteria (HARNESS_SPEC_MAX_ITEMS %s): cut it to "
                        "what the task needs, or split the task" % (len(reqs) + len(acs), limit))
    covered = set()
    for ac, rest in acs:
        refs = set(re.findall(r"REQ-%s-\d+" % re.escape(task), rest))
        covered |= refs
        if not refs:
            problems.append("%s does not reference the requirement it proves" % ac)
        problems.extend("%s references unknown %s" % (ac, ref) for ref in sorted(refs - req_ids))
        if not all(re.search(r"\b%s\b" % word, rest, re.I) for word in ("given", "when", "then")):
            problems.append("%s is not written as Given ..., when ..., then ..." % ac)
    problems.extend("%s has no acceptance criterion" % req for req in sorted(req_ids - covered))
    problems.extend(knowledge_citation_problems(text))
    adrs = spec_adrs(text)
    if not adrs:
        problems.append("the Architecture section must reference at least one ADR (e.g. 'ADRs: ADR-002'); "
                        "the architect agent writes new ADRs when the task needs a decision")
    for adr in adrs:
        path = adr_file(adr)
        if path is None:
            problems.append("%s is referenced but not found in backbone/adr/" % adr)
            continue
        status = adr_status(read(path))
        if not status.lower().startswith(("accepted", "proposed")):
            problems.append("%s has status '%s'; reference an accepted or proposed ADR" % (adr, status or "missing"))
        problems.extend(validate_adr(read(path), path.name))
    skills = spec_skills(text)
    if not skills:
        problems.append("the Skills section must list the skills the implementation needs")
    available = available_skills()
    problems.extend("skill '%s' does not exist in .claude/skills/" % s for s in skills if s not in available)
    open_items = [q for q in bullets(md_section(body, "Open questions"))
                  if q.lower().rstrip(".") not in ("none", "n/a")]
    if open_items:
        problems.append("open questions remain: %s" % "; ".join(open_items)[:300])
    if PLACEHOLDER.search(body) or STUB_WORDS.search(body):
        problems.append("the spec still contains FILL, TODO, TBD or FIXME placeholders")
    return problems


def spec_fingerprint(task, text=None):
    """Hash of the spec (without its Approval section) and of every ADR it references."""
    text = read(spec_path(task)) if text is None else text
    digest = hashlib.sha256(without_approval(text).encode("utf-8"))
    for adr in spec_adrs(text):
        path = adr_file(adr)
        digest.update(adr.encode("utf-8"))
        digest.update(read(path).encode("utf-8") if path else b"")
    return digest.hexdigest()


# --------------------------------------------------------------------------- skills

def available_skills():
    return {path.parent.name for path in SKILLS.glob("*/SKILL.md")}


def load_routes():
    routes, errors = [], []
    for path in ROUTE_FILES:
        origin = path.relative_to(ROOT).as_posix()
        for n, raw in enumerate(read(path).splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            where = "%s:%d" % (origin, n)
            parts = [p.strip() for p in line.split(" | ", 2)]
            skills = [s.strip() for s in parts[1].split(",") if s.strip()] if len(parts) == 3 else []
            if len(parts) != 3 or not skills or not parts[2]:
                errors.append("%s: expected '<path regex> | <skill>[, <skill>...] | <why>'" % where)
                continue
            try:
                routes.append((re.compile(parts[0]), skills, parts[2], where))
            except re.error as exc:
                errors.append("%s: invalid regex (%s)" % (where, exc))
    return routes, errors


def required_skills(path):
    """{skill: reason} for editing path: routing rules plus the [WIP] spec's Skills for code."""
    needed = {}
    routes, _ = load_routes()
    for pattern, skills, why, where in routes:
        if pattern.search(path):
            for skill in skills:
                needed.setdefault(skill, "%s [%s]" % (why, where))
    if not path.startswith(("backbone/", ".claude/", "scripts/harness/")):
        tasks = wip_task_ids()
        if len(tasks) == 1:
            for skill in spec_skills(read(spec_path(tasks[0]))):
                needed.setdefault(skill, "listed under Skills in %s" % spec_rel(tasks[0]))
    return needed


def session_file(data):
    common = git("rev-parse", "--git-common-dir").strip()
    if not common:
        return None
    base = Path(common) if os.path.isabs(common) else ROOT / common
    key = str(data.get("session_id") or "session")
    if data.get("agent_id"):
        key += "-" + str(data["agent_id"])
    return base / "harness" / "sessions" / ("%s.json" % slug(key))


def loaded_skills(data):
    path = session_file(data)
    try:
        return set(json.loads(read(path) or "{}").get("skills", [])) if path else set()
    except ValueError:
        return set()


def remember_skill(data, name):
    path = session_file(data)
    if path is None or not name:
        return
    skills = loaded_skills(data) | {name}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"skills": sorted(skills), "updated": time.time()}), encoding="utf-8")
    cutoff = time.time() - 14 * 86400
    for old in path.parent.glob("*.json"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass


def skill_gate(data, path):
    if not gate_on("HARNESS_SKILL_GATE") or path.startswith("/"):
        return None
    available = available_skills()
    loaded = loaded_skills(data)
    missing = [(skill, why) for skill, why in sorted(required_skills(path).items())
               if skill in available and skill not in loaded]
    if not missing:
        return None
    return ("  - Load these skills before editing %s, then retry:\n%s"
            % (path, "\n".join("      %s: read .claude/skills/%s/SKILL.md (or invoke the skill). Required by: %s"
                               % (skill, skill, why) for skill, why in missing)))


# --------------------------------------------------------------------------- guardrail rules

class Rule(object):
    def __init__(self, severity, target, content, message, origin):
        self.severity = severity
        self.target = target      # compiled path regex, or None for Bash commands (@bash)
        self.content = content
        self.message = message
        self.origin = origin


def load_rules():
    rules, errors = [], []
    for path in RULE_FILES:
        origin = path.relative_to(ROOT).as_posix()
        for n, raw in enumerate(read(path).splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            where = "%s:%d" % (origin, n)
            parts = [p.strip() for p in line.split(" | ", 3)]
            if len(parts) != 4 or parts[0] not in ("block", "warn") or not all(parts):
                errors.append("%s: expected '<block|warn> | <path regex or @bash> | <content regex> | <message>'" % where)
                continue
            try:
                target = None if parts[1] == "@bash" else re.compile(parts[1])
                content = re.compile(parts[2], re.M)
            except re.error as exc:
                errors.append("%s: invalid regex (%s)" % (where, exc))
                continue
            rules.append(Rule(parts[0], target, content, parts[3], where))
    return rules, errors


def check_text(rules, path, text, severities=("block", "warn")):
    """Rules matching text. path=None means text is a Bash command."""
    hits = []
    for rule in rules:
        if rule.severity not in severities:
            continue
        if path is None:
            if rule.target is not None:
                continue
        elif rule.target is None or not rule.target.search(path):
            continue
        match = rule.content.search(text)
        if match:
            hits.append((rule, match.group(0)))
    return hits


def scan(max_files=20000, max_bytes=1000000):
    """Rule violations already present in tracked and untracked (not ignored) files.
    Returns ([(path, rule, matched)], files_checked). Rules normally only see added text; this finds drift."""
    rules, _ = load_rules()
    file_rules = [r for r in rules if r.target is not None]
    names = [n for n in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0") if n]
    found, checked = [], 0
    for name in names[:max_files]:
        candidates = [r for r in file_rules if r.target.search(name)]
        path = ROOT / name
        if not candidates or not path.is_file() or path.stat().st_size > max_bytes:
            continue
        checked += 1
        text = read(path)
        for rule in candidates:
            match = rule.content.search(text)
            if match:
                found.append((name, rule, match.group(0)))
    return found, checked


def scan_report(quiet=False):
    found, checked = scan()
    blocks = [f for f in found if f[1].severity == "block"]
    if not quiet:
        for name, rule, matched in found:
            print("%-5s %s\n%s" % (rule.severity, name, describe([(rule, matched)])))
    print("scan: %d file(s) checked, %d blocking and %d warning violation(s) already in the codebase"
          % (checked, len(blocks), len(found) - len(blocks)))
    return 1 if blocks else 0


def describe(hits):
    lines = []
    for rule, matched in hits:
        shown = matched.strip().splitlines()[0] if matched.strip() else matched
        shown = shown if len(shown) <= 16 else shown[:12] + "..."   # never echo whole secrets
        lines.append("  - %s  [%s, matched: %r]" % (rule.message, rule.origin, shown))
    return "\n".join(lines)


# --------------------------------------------------------------------------- shell commands
# Commands are split into segments on shell operators and tokenized, so checks see the program that runs
# and its arguments rather than any text that happens to appear (commit messages, data heredocs).

SQL_CLIENTS = ("psql", "mysql", "mariadb", "sqlite3", "clickhouse-client", "cockroach", "sqlcmd")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
INTERPRETERS = ("python", "python3", "perl", "ruby", "node")
WRAPPERS = ("sudo", "env", "time", "nohup", "command", "exec", "nice")
MUTATORS = ("rm", "rmdir", "unlink", "mv", "chmod", "chown", "truncate", "tee", "touch")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SETTING_ASSIGNMENT = re.compile(r"^(HARNESS_[A-Z0-9_]+|SKIP_BUILD)=")
PROTECTED_MENTION = re.compile(r"(?:^|[\s'\"/=(:])(backbone/|scripts/harness/|\.claude/|AGENTS\.md|CLAUDE\.md"
                               r"|\.git/(?:hooks|harness|config))")
CODE_WRITES = re.compile(r"open\([^)]*,\s*['\"][wax+]|\.write_(text|bytes)\(|\bos\.(remove|unlink|rename|replace|"
                         r"chmod|truncate)\(|\bshutil\.(copy|move|rmtree)|\.(unlink|rename|touch|rmdir)\(|"
                         r"\bfs\.(writeFile|appendFile|unlink|rename|rm|copyFile)|\bFile\.(write|delete|rename)|"
                         r"\bunlink\b|\brename\b")
DELETE_ALL = re.compile(r"(?i)\bdelete\s+from\s+[\w.\"`]+\s*(;|$|['\"])", re.M)
COMMIT_MESSAGE = re.compile(r"""(?<!\S)(--message(?:=|\s+)|--file(?:=|\s+)|-[A-Za-z]*[mF]\s*)"""
                            r"""("(?:[^"\\]|\\.)*"|'[^']*'|\S+)""")


def split_heredocs(command):
    """(command without heredoc bodies, [(opening line, body)])."""
    lines, kept, bodies, i = command.split("\n"), [], [], 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for m in HEREDOC.finditer(line):
            body = []
            while i < len(lines) and lines[i].strip() != m.group(2):
                body.append(lines[i])
                i += 1
            i += 1
            bodies.append((line, "\n".join(body)))
    return "\n".join(kept), bodies


def split_segments(command):
    """[(segment, operator after it)], splitting on ; && || | & and newlines outside quotes."""
    segments, current, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(command):
                current.append(command[i + 1])
                i += 1
        elif ch in "'\"":
            quote = ch
            current.append(ch)
        elif command.startswith(("&&", "||"), i):
            segments.append(("".join(current), command[i:i + 2]))
            current = []
            i += 1
        elif ch == "&" and (command[i - 1:i] in (">", "<") or command[i + 1:i + 2] == ">"):
            current.append(ch)  # a redirection such as 2>&1 or &>file
        elif ch in ";\n|&":
            segments.append(("".join(current), ch))
            current = []
        else:
            current.append(ch)
        i += 1
    segments.append(("".join(current), ""))
    return [(s, op) for s, op in segments if s.strip()]


def shell_words(segment):
    """(leading VAR=value assignments, remaining words), with wrappers such as sudo and env dropped."""
    try:
        words = shlex.split(segment, comments=True)
    except ValueError:
        words = segment.split()
    assignments = []
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS
                     or (words[0] == "export" and len(words) > 1)):
        if words[0] != "export" and "=" in words[0] and not words[0].startswith("-"):
            assignments.append(words[0])
        elif words[0] == "export":
            assignments.extend(w for w in words[1:] if "=" in w)
            return assignments, []
        words = words[1:]
    return assignments, words


def program(words):
    return words[0].rsplit("/", 1)[-1] if words else ""


def short_flags(words):
    return {c for w in words if w.startswith("-") and not w.startswith("--") for c in w[1:]}


def protected_path(path_str, cwd):
    """Repository-relative path if path_str points into a shell-protected harness path, else None."""
    if not path_str or path_str.startswith("-"):
        return None
    path = os.path.expandvars(os.path.expanduser(path_str))
    if not os.path.isabs(path):
        path = os.path.join(cwd or str(ROOT), path)
    full, root = os.path.realpath(path), os.path.realpath(str(ROOT))
    if full != root and not full.startswith(root + os.sep):
        return None
    name = os.path.relpath(full, root).replace(os.sep, "/")
    return name if any(re.search(p, name) for p in SHELL_PROTECTED) else None


def written_paths(segment, words):
    """Paths a segment writes, moves or deletes: redirection targets and mutating programs' operands."""
    paths = re.findall(r"(?:^|[^<>&0-9])(?:[0-9]?>>?|&>>?)\s*([^\s;|&<>]+)", segment)
    prog, args = program(words), [w for w in words[1:] if not w.startswith("-")]
    if prog in MUTATORS:
        paths += args
    elif prog in ("cp", "ln", "install", "rsync"):
        paths += args[-1:]
    elif prog == "dd":
        paths += [a[3:] for a in args if a.startswith("of=")]
    elif prog in ("sed", "gsed", "perl") and any(w.startswith("-i") or w.startswith("-pi") or w == "--in-place"
                                                for w in words[1:]):
        paths += args[1:]
    elif prog == "git" and len(words) > 1 and words[1] in ("rm", "mv"):
        paths += [w for w in words[2:] if not w.startswith("-")]
    return [p.strip("'\"") for p in paths]


def git_findings(words):
    args = words[1:]
    while args and args[0].startswith("-"):
        if args[0] == "-c" and len(args) > 1 and args[1].lower().startswith("core.hookspath"):
            return ["git -c core.hooksPath=... turns off the harness git hooks."]
        args = args[2:] if args[0] in ("-c", "-C") else args[1:]
    if not args:
        return []
    sub, rest = args[0], args[1:]
    found = []
    if sub == "commit" and "n" in short_flags(rest):
        found.append("git commit -n is --no-verify: it skips the harness git hooks; fix what the hook reports instead.")
    if sub == "config" and any(w.lower() == "core.hookspath" for w in rest):
        # Reading the setting is fine; setting, adding or unsetting it is not.
        key = next(i for i, w in enumerate(rest) if w.lower() == "core.hookspath")
        writes = {"--unset", "--unset-all", "--add", "--replace-all", "set", "unset", "--edit", "-e"}
        reads = {"--get", "--get-all", "--get-regexp", "-l", "--list", "get"}
        value = [w for w in rest[key + 1:] if not w.startswith("-")]
        if (writes & set(rest)) or (value and not reads & set(rest)):
            found.append("Changing core.hooksPath turns off the harness git hooks.")
    if sub == "push":
        if any(w.startswith("+") for w in rest) or "--mirror" in rest:
            found.append("A '+<ref>' or --mirror push is a force push: it rewrites remote history.")
        if "--delete" in rest or "d" in short_flags(rest) or any(w.startswith(":") for w in rest):
            found.append("That push deletes a remote branch or tag.")
    return found


def code_findings(code, label):
    if PROTECTED_MENTION.search(code) and CODE_WRITES.search(code):
        return ["%s writes to harness-protected paths (backbone/, scripts/harness/, .claude/, git hooks); "
                "use the Write/Edit tools so the gates see the change." % label]
    return []


def shell_findings(command, cwd=None, depth=0):
    """Blocking problems with a shell command, beyond the @bash guardrail rules."""
    found = []
    command, bodies = split_heredocs(command)
    segments = split_segments(command)
    for index, (segment, op) in enumerate(segments):
        assignments, words = shell_words(segment)
        for assignment in assignments:
            if SETTING_ASSIGNMENT.match(assignment):
                found.append("Setting %s from the shell overrides a harness setting or skips a check; only the user "
                             "may do that, in their own terminal." % assignment.split("=", 1)[0])
        prog = program(words)
        if prog == "cd" and len(words) > 1:
            cwd = os.path.join(cwd or str(ROOT), os.path.expanduser(words[1]))
            continue
        for path in written_paths(segment, words):
            name = protected_path(path, cwd)
            if name:
                found.append("Shell writes to %s skip the harness gates; change it with the Write or Edit tool "
                             "(or not at all, for verdicts and user-only settings)." % name)
        if prog == "git":
            found.extend(git_findings(words))
        elif prog == "find" and ("-delete" in words or ("-exec" in words and "rm" in words)):
            start = next((w for w in words[1:] if not w.startswith("-")), ".")
            if start.rstrip("/") in ("", "~", "$HOME", "${HOME}") or (start.startswith("/") and start.count("/") <= 1):
                found.append("find ... -delete on %s deletes from the filesystem root or home." % start)
        elif prog in SHELLS and depth < 3:
            if "-c" in words and words.index("-c") + 1 < len(words):
                found.extend(shell_findings(words[words.index("-c") + 1], cwd, depth + 1))
        elif prog == "eval" and depth < 3:
            found.extend(shell_findings(" ".join(words[1:]), cwd, depth + 1))
        elif prog in INTERPRETERS:
            command = next((w for w in words[2:4] if w in ("run", "ci-judge", "ci-protect", "orca", "orca-nightly",
                                                         "snapshot")), None)
            planning = command in ("orca", "orca-nightly") and "--dry-run" in words   # these dry runs change nothing
            if any(w.endswith("harness.py") for w in words[1:3]) and command and not planning:
                found.append("harness.py run, orca, orca-nightly, snapshot, ci-judge and ci-protect are for the user, "
                             "CI or an Orca automation's precheck, not agents.")
            flag = next((f for f in ("-c", "-e", "-pe", "-ne") if f in words), None)
            if flag and words.index(flag) + 1 < len(words):
                found.extend(code_findings(words[words.index(flag) + 1], "That %s one-liner" % prog))
        if (prog in SQL_CLIENTS or any(w in SQL_CLIENTS for w in words[:6])) and DELETE_ALL.search(segment):
            found.append("DELETE without a WHERE clause removes every row.")
        if prog in ("curl", "wget") and op == "|" and index + 1 < len(segments):
            if program(shell_words(segments[index + 1][0])[1]) in SHELLS:
                found.append("Piping a download into a shell runs unreviewed remote code.")
    for opening, body in bodies:
        _, words = shell_words(split_segments(opening)[0][0] if split_segments(opening) else "")
        prog = program(words)
        if prog in SHELLS and depth < 3:
            found.extend(shell_findings(body, cwd, depth + 1))
        elif prog in INTERPRETERS:
            found.extend(code_findings(body, "That %s script" % prog))
        elif any(client in opening for client in SQL_CLIENTS) and DELETE_ALL.search(body):
            found.append("DELETE without a WHERE clause removes every row.")
    return sorted(set(found), key=found.index)


def rule_text(command):
    """The command as @bash guardrail rules see it: commit and tag messages and the bodies of data
    heredocs (cat > file <<EOF) are left out, so text that only mentions a command does not match."""
    stripped, bodies = split_heredocs(command)
    executed = [body for opening, body in bodies
                if any(re.search(r"\b%s\b" % re.escape(p), opening) for p in SQL_CLIENTS + SHELLS + INTERPRETERS)]
    parts = []
    for segment, op in split_segments(stripped):
        _, words = shell_words(segment)
        if program(words) == "git" and any(w in ("commit", "tag") for w in words[1:3]):
            segment = COMMIT_MESSAGE.sub(lambda m: m.group(1) + "''", segment)
        parts.append(segment + op)
    return "".join(parts) + "".join("\n" + body for body in executed)


# --------------------------------------------------------------------------- verdicts

def verdict_path(task, kind):
    return VERDICTS / ("%s.%s.json" % (slug(task), kind))


def verdict_history(task, kind):
    try:
        return json.loads(read(verdict_path(task, kind)) or "{}").get("history") or []
    except ValueError:
        return []


def since_last_escalation(task, history):
    """The verdicts recorded after task's latest escalation: a person answered it, so its rounds start over."""
    stamps = re.findall(r"(?m)^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) Task %s:" % re.escape(task), read(ESCALATIONS))
    if not stamps:
        return history
    latest = max(stamps).replace(" ", "T")
    return [e for e in history if str(e.get("at", ""))[:16] > latest]


def consecutive_fails(history):
    fails = 0
    for entry in reversed(history):
        if entry.get("verdict") == "pass":
            break
        fails += 1
    return fails


def code_fingerprint():
    """Git tree hash of the working tree (tracked and untracked, ignores respected),
    excluding backbone/. Identical code gives an identical hash, committed or not."""
    git_dir = git("rev-parse", "--absolute-git-dir").strip()
    if not git_dir:
        return None
    tmp = tempfile.mkdtemp(prefix="harness-index-")
    try:
        index = os.path.join(tmp, "index")
        if os.path.isfile(os.path.join(git_dir, "index")):
            shutil.copyfile(os.path.join(git_dir, "index"), index)
        env = dict(os.environ, GIT_INDEX_FILE=index)

        def run(*args):
            return subprocess.run(["git"] + list(args), cwd=str(ROOT), env=env, capture_output=True, text=True)

        run("add", "-A", "--", ".")
        run("rm", "-r", "--cached", "-q", "--ignore-unmatch", "--", "backbone")
        result = run("write-tree")
        return result.stdout.strip() if result.returncode == 0 else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extract_report(message, key="verdict"):
    """The agent's report: the last JSON object in the message that has `key` (the griller's and judge's verdict,
    the tester's "tests", the debugger's "root_causes")."""
    if not message:
        return None
    for block in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", message, re.S)):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and key in data:
            return data
    decoder = json.JSONDecoder()
    for start in reversed([m.start() for m in re.finditer(r"\{", message)]):
        try:
            data, _ = decoder.raw_decode(message[start:])
        except ValueError:
            continue
        if isinstance(data, dict) and key in data:
            return data
    return None


def last_message_from_transcript(path):
    """Fallback when the hook input has no last_assistant_message: last assistant text in the transcript."""
    text = None
    for line in read(path).splitlines() if path else []:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            if any(parts):
                text = "\n".join(parts)
    return text


def serious(items):
    return [i for i in items or [] if isinstance(i, dict) and str(i.get("severity", "")).lower() in ("blocker", "major")]


def effective_grill(task, report):
    """Pass only if the griller passed, nothing serious is open and the spec is structurally valid."""
    reasons = []
    if str(report.get("verdict", "")).lower() != "pass":
        reasons.append("griller verdict: %s" % report.get("verdict"))
    reasons.extend("%s question: %s" % (q.get("severity"), q.get("question", "?")) for q in serious(report.get("questions")))
    reasons.extend("recommendation to apply: %s" % q.get("question", "?") for q in report.get("questions") or []
                   if isinstance(q, dict) and q.get("apply") and not serious([q]))
    reasons.extend("spec: " + problem for problem in validate_spec(task))
    return ("pass" if not reasons else "fail"), reasons


def mark_recommendations(questions):
    """A non-blocker question that carries the griller's recommendation needs nobody's answer: it is marked
    `apply`, and the analyst or architect applies the recommendation without asking. A blocker is always asked
    or escalated; its recommendation is only a proposal. Returns how many questions were marked."""
    marked = 0
    for q in questions or []:
        if isinstance(q, dict):
            q["apply"] = bool(str(q.get("recommendation") or "").strip()) and \
                str(q.get("severity", "")).lower() != "blocker"
            marked += q["apply"]
    return marked


def ac_test_references(task):
    """{AC id: [test files mentioning it]}, searching tracked and untracked files outside backbone/."""
    test_paths = re.compile(conf()["HARNESS_TEST_PATHS"])
    output = git("grep", "-I", "--untracked", "-o", "-E", "AC-%s-[0-9]+" % re.escape(task).replace("\\-", "-"))
    found = {}
    for line in output.splitlines():
        name, _, match = line.partition(":")
        if name.startswith("backbone/") or not test_paths.search(name):
            continue
        found.setdefault(match, set()).add(name)
    return {ac: sorted(files) for ac, files in found.items()}


def effective_judge(task, report):
    """Pass only if every acceptance criterion is met with evidence and traced to a test, nothing
    serious was found, and the tests ran and passed."""
    reasons = []
    if str(report.get("verdict", "")).lower() != "pass":
        reasons.append("judge verdict: %s" % report.get("verdict"))
    spec_text = read(spec_path(task))
    acs = [ac for ac, _ in spec_items(strip_comments(spec_text), "AC", task)]
    if not acs:
        reasons.append("no acceptance criteria found in %s" % spec_rel(task))
    by_id = {}
    for item in report.get("criteria") or []:
        if isinstance(item, dict):
            by_id[str(item.get("id", "")).strip()] = item
    references = ac_test_references(task)
    for ac in acs:
        item = by_id.get(ac)
        if item is None:
            reasons.append("%s was not evaluated" % ac)
        elif item.get("met") is not True:
            reasons.append("%s not met" % ac)
        elif not item.get("tests"):
            reasons.append("%s lists no test" % ac)
        if ac not in references:
            reasons.append("no test file references %s (tests must mention the AC id)" % ac)
    reasons.extend("%s finding: %s" % (f.get("severity"), f.get("issue", "?")) for f in serious(report.get("findings")))
    result = str((report.get("tests") or {}).get("result", "")).lower()
    if result != "passed":
        reasons.append("tests %s" % (result or "not reported"))
    run = report.get("test_run")
    if run is not None and run.get("exit") != 0:
        reasons.append("the harness ran HARNESS_TEST_CMD (%s) and it %s" % (
            run.get("command"), "timed out" if run.get("exit") is None else "failed with exit code %s" % run.get("exit")))
    return ("pass" if not reasons else "fail"), reasons


def run_tests():
    """Run HARNESS_TEST_CMD as the judge's evidence. None when no test command is configured."""
    values = conf()
    command = values["HARNESS_TEST_CMD"]
    if not command:
        return None
    timeout = int(values["HARNESS_TEST_TIMEOUT"]) if values["HARNESS_TEST_TIMEOUT"].isdigit() else 900
    started = time.time()
    try:
        result = subprocess.run(command, shell=True, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
        exit_code, output = result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        output = "%s%s" % (exc.stdout or "", exc.stderr or "")
        output = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
    return {"command": command, "exit": exit_code, "seconds": round(time.time() - started, 1),
            "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "tail": output.strip().splitlines()[-15:]}


def record_verdict(data, kind):
    """SubagentStop for the griller (kind 'grill') or judge (kind 'judge')."""
    agent_name = {"grill": "griller", "judge": "judge"}[kind]
    agent = str(data.get("agent_type") or agent_name)
    if agent != agent_name and not agent.endswith(":" + agent_name):
        return
    retry = not data.get("stop_hook_active")
    report = extract_report(data.get("last_assistant_message")
                            or last_message_from_transcript(data.get("transcript_path")))
    if report is None:
        if retry:
            deny("End your final message with the verdict JSON block described in your instructions.")
        emit({"systemMessage": "harness: the %s returned no verdict JSON; nothing was recorded." % agent_name})
        return
    claimed = re.sub(r"(?i)^task\s+", "", str(report.get("task") or "")).strip()
    if kind == "judge":
        candidates = wip_task_ids()
        task = claimed if claimed in candidates else (candidates[0] if len(candidates) == 1 else None)
        hint = "the [WIP] task you reviewed: one of %s" % (", ".join(candidates) or "(none is [WIP])")
    else:
        task = claimed if claimed and spec_path(claimed).is_file() else None
        hint = "the id of the spec you reviewed (backbone/specs/<id>.md)"
    if task is None:
        if retry:
            deny("Set \"task\" in the verdict JSON to %s." % hint)
        emit({"systemMessage": "harness: the %s verdict names no valid task; nothing was recorded." % agent_name})
        return
    to_apply = 0
    if kind == "grill":
        to_apply = mark_recommendations(report.get("questions"))
        verdict, reasons = effective_grill(task, report)
        fingerprint = spec_fingerprint(task)
        details = {"questions": report.get("questions")}
    else:
        report.pop("test_run", None)   # only the harness may supply this evidence
        verdict, reasons = effective_judge(task, report)
        fingerprint = code_fingerprint()
        if verdict == "pass":
            # The judge's "tests passed" is a claim; the harness runs the test command itself.
            report["test_run"] = run_tests()
            if report["test_run"] is not None:
                verdict, reasons = effective_judge(task, report)
        details = {"criteria": report.get("criteria"), "findings": report.get("findings"), "tests": report.get("tests"),
                   "test_run": report.get("test_run")}
    history = verdict_history(task, kind)
    entry = {"verdict": verdict, "claimed": report.get("verdict"), "reasons": reasons, "fingerprint": fingerprint,
             "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "summary": report.get("summary")}
    entry.update(details)
    history.append(entry)
    log_event("verdict", agent=agent_name, task=task, verdict=verdict, claimed=report.get("verdict"),
              reasons=reasons[:10], to_apply=to_apply)
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(task, kind).write_text(json.dumps({"task": task, "kind": kind, "history": history}, indent=2) + "\n",
                                        encoding="utf-8")
    snapshot_refresh()
    note = "harness: %s verdict for task %s: %s" % (agent_name, task, verdict.upper())
    if to_apply:
        note += ": the analyst or architect applies %d recommendation(s) without asking anyone" % to_apply
    if verdict == "fail":
        note += " (%s)" % "; ".join(reasons)[:500]
        values = conf()
        key = "HARNESS_JUDGE_MAX_ROUNDS" if kind == "judge" else "HARNESS_GRILL_MAX_ROUNDS"
        limit = int(values[key]) if values[key].isdigit() else 2
        recent = since_last_escalation(task, history)
        if autonomous() and consecutive_fails(recent) >= limit:
            escalate(task, "%s failed %d times" % (agent_name, consecutive_fails(recent)), "; ".join(reasons),
                     "the user's decision on the findings")
            note += ". Escalated after %d failed rounds: the task is BLOCKED (backbone/escalations.md); " \
                    "continue with another task." % consecutive_fails(recent)
    emit({"systemMessage": note})


# --------------------------------------------------------------------------- autonomy
# In autonomous mode no human answers questions in the loop. The harness itself approves low-risk specs
# (deterministically, from the spec and later the diff), and everything else becomes an escalation:
# the task is parked with a BLOCKED note and an entry in backbone/escalations.md, and work moves on.

def autonomous():
    return conf()["HARNESS_AUTONOMY"] == "autonomous"


def halt_file():
    common = git("rev-parse", "--git-common-dir").strip()
    base = Path(common) if common and os.path.isabs(common) else ROOT / (common or ".git")
    return base / "harness" / "STOP"


def task_line(task, text=None):
    """(index, line) of task's line in 3-TASKS.md (outside comments), or (None, None)."""
    lines = mask_comments(read(TASKS) if text is None else text).splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and task_id_at(lines, i) == task:
            return i, line
    return None, None


def blocked_tasks(text):
    lines = mask_comments(text).splitlines()
    return {task_id_at(lines, i) for i, line in enumerate(lines)
            if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and BLOCKED_NOTE.search(line)}


def policy_approval(text):
    """{'rule', 'base'} of a policy approval line in the spec text, or None."""
    m = POLICY_APPROVAL.search(md_section(strip_comments(text or ""), "Approval") or "")
    if not m:
        return None
    base = re.search(r"\bbase ([0-9a-f]{7,40})", m.group(2))
    return {"rule": m.group(1), "base": base.group(1) if base else None}


def changed_files(base):
    """Code files changed since commit base (committed, staged, unstaged or untracked), outside backbone/."""
    names = set(n for n in git("diff", "--name-only", "-z", base).split("\0") if n) if base else set()
    names |= set(n for n in git("ls-files", "-z", "--others", "--exclude-standard").split("\0") if n)
    if not base:
        names |= set(n for n in git("ls-files", "-z").split("\0") if n)
    return sorted(n for n in names if not n.startswith("backbone/"))


def risk_reasons(task, base=None):
    """Why a task is not low-risk (empty list = low risk). With base, the diff since then is assessed too."""
    values = conf()
    text = read(spec_path(task))
    # Skills only says which skills the agents load, and explaining why `security` isn't needed ("no auth or
    # personal data") would read as risk. What the work does is in the other sections and in the diff.
    body = without_section(without_approval(strip_comments(text)), "Skills")
    reasons = []
    terms = re.compile(values["HARNESS_RISK_TERMS"])
    paths = re.compile(values["HARNESS_RISK_PATHS"])
    hits = sorted({m.group(0).lower() for m in terms.finditer(body)})
    if hits:
        reasons.append("the spec involves %s" % ", ".join(hits[:6]))
    # Harness files the spec cites as sources (skills, backbone docs) aren't code the change touches.
    named = sorted({w for w in re.findall(r"[\w.-]+(?:/[\w.-]+)+", body) if paths.search(w)
                    and not re.match(r"^\.?(claude/skills|backbone|scripts/harness)/", w.lstrip("./"))})
    if named:
        reasons.append("the spec names sensitive paths: %s" % ", ".join(named[:6]))
    for adr in spec_adrs(text):
        found = adr_file(adr)
        if found is not None and not adr_status(read(found)).lower().startswith("accepted"):
            reasons.append("%s is not Accepted: the user decides on it" % adr)
    if base is not None:
        changed = changed_files(base)
        sensitive = [n for n in changed if paths.search(n)]
        if sensitive:
            reasons.append("the change touches sensitive paths: %s" % ", ".join(sensitive[:6]))
        limit = int(values["HARNESS_RISK_MAX_FILES"]) if values["HARNESS_RISK_MAX_FILES"].isdigit() else 20
        if len(changed) > limit:
            reasons.append("the change touches %d files (limit %d)" % (len(changed), limit))
    return reasons


def escalate(task, kind, reason, needed=None):
    """Park task for the user: a BLOCKED note on its line (out of [WIP]) and an entry in escalations.md."""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    text = read(TASKS)
    lines = text.splitlines()
    index, line = task_line(task, text)
    if index is not None:
        line = BLOCKED_NOTE.sub("", line)
        line = re.sub(r"^(\s*[-*]\s+)\[WIP\]", r"\1[ ]", line)
        lines[index] = "%s \u2014 BLOCKED: %s (backbone/escalations.md)" % (line, kind)
        TASKS.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    if not ESCALATIONS.exists():
        ESCALATIONS.write_text("# Escalations\n\nWritten by the harness when an autonomous run needs a human "
                               "decision. Resolve an entry by acting on it, setting its status to resolved, and "
                               "removing the BLOCKED note from the task line in 3-TASKS.md.\n", encoding="utf-8")
    entry = ("\n## %s Task %s: %s\n\n- Status: open\n- Reason: %s\n- Needed: %s\n"
             % (stamp, task, kind, reason.strip(), needed or "a decision from the user"))
    log_event("escalation", task=task, escalation=kind, reason=reason.strip()[:500])
    with ESCALATIONS.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    snapshot_refresh()
    issue = None
    if conf()["HARNESS_ESCALATE_GH"] == "on" and shutil.which("gh"):
        result = subprocess.run(["gh", "issue", "create", "--title", "Harness escalation: task %s: %s" % (task, kind),
                                 "--body", entry.strip(), "--label", "harness-escalation"],
                                cwd=str(ROOT), capture_output=True, text=True)
        issue = result.stdout.strip() if result.returncode == 0 else None
    notify_coordinator("escalation", "Task %s: %s" % (task, kind), entry.strip(), task)
    return issue


def notify_coordinator(kind, subject, body, task=None):
    """Under an Orca coordinator (HARNESS_ORCA_RUN, set by `harness.py orca`), tell it too. Best effort."""
    run_id = os.environ.get("HARNESS_ORCA_RUN", "").strip()
    orca = shutil.which(os.environ.get("HARNESS_ORCA_BIN", "orca"))
    if not run_id or not orca:
        return False
    argv = [orca, "orchestration", "send", "--run", run_id, "--type", kind, "--subject", subject, "--body", body,
            "--json"]
    if task:
        argv += ["--payload", json.dumps({"harness_task": task})]
    try:
        return subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def open_escalations():
    entries = re.split(r"(?m)^## ", read(ESCALATIONS))[1:]
    return [e.splitlines()[0] for e in entries if re.search(r"(?mi)^- Status:\s*open\b", e)]


def approve_command(task):
    if not autonomous():
        print("approve: only in autonomous mode (HARNESS_AUTONOMY=\"autonomous\"); otherwise the user approves "
              "the spec by adding their Approved-by: line")
        return 1
    if conf()["HARNESS_AUTO_APPROVE"] != "low":
        print("approve: policy approval is off (HARNESS_AUTO_APPROVE); escalating to the user")
        escalate(task, "approval", "policy approval is switched off", "the user's review and Approved-by: line")
        return 1
    text = read(spec_path(task))
    if approved(text):
        print("approve: %s is already approved" % spec_rel(task))
        return 0
    if task in blocked_tasks(read(TASKS)):
        print("approve: task %s is BLOCKED; see backbone/escalations.md" % task)
        return 1
    cited = knowledge_citation_problems(text)
    if cited:
        print("approve: fix the Assumptions' sources first:\n  " + "\n  ".join(cited))
        return 1
    invalid = validate_spec(task)
    history = verdict_history(task, "grill")
    last = history[-1] if history else None
    if invalid or not last or last.get("verdict") != "pass" or last.get("fingerprint") != spec_fingerprint(task):
        print("approve: the spec must be valid and have a current griller pass first (spec-check %s)" % task)
        return 1
    asked = sum(len(entry.get("questions") or []) for entry in history)
    assumptions = [a for a in top_level_items(md_section(strip_comments(text), "Assumptions"))
                   if a.lower().rstrip(".") not in ("none", "n/a")]
    if asked and not assumptions:
        print("approve: the griller asked %d question(s); record how each was settled under '## Assumptions' "
              "(with its source in backbone/ or vault:<path>), grill again, then approve. Escalate what the "
              "sources cannot answer." % asked)
        return 1
    reasons = risk_reasons(task)
    if reasons:
        escalate(task, "approval", "; ".join(reasons), "the user's review of %s and their Approved-by: line"
                 % spec_rel(task))
        print("approve: task %s is not low-risk (%s); escalated to the user in backbone/escalations.md. "
              "Continue with another task." % (task, "; ".join(reasons)))
        return 1
    base = git("rev-parse", "--verify", "-q", "HEAD").strip()[:12] or "none"
    line = "Approved-by: policy:low-risk (%s; base %s; grill %s)" % (time.strftime("%Y-%m-%d"), base,
                                                                    last.get("fingerprint", "")[:12])
    m = re.search(r"^##\s+Approval\s*$", text, re.M | re.I)
    text = (text.rstrip("\n") + "\n\n## Approval\n" if not m else text.rstrip("\n")) + "\n" + line + "\n"
    spec_path(task).write_text(text, encoding="utf-8")
    log_event("approval", task=task, rule="low-risk", base=base)
    snapshot_refresh()
    print("approve: %s approved by policy (low risk)." % spec_rel(task))
    return 0


def escalate_command(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write("usage: harness.py escalate <task> --reason <text> [--kind <kind>] [--needed <text>]\n")
        return 64
    task, opts, key = argv[0], {}, None
    for arg in argv[1:]:
        if arg in ("--reason", "--kind", "--needed"):
            key = arg[2:]
        elif key:
            opts[key] = (opts.get(key, "") + " " + arg).strip()
    if not opts.get("reason"):
        sys.stderr.write("escalate: --reason is required\n")
        return 64
    issue = escalate(task, opts.get("kind", "decision"), opts["reason"], opts.get("needed"))
    print("escalate: task %s parked as BLOCKED; recorded in backbone/escalations.md%s. Continue with another task."
          % (task, " and " + issue if issue else ""))
    return 0


def escalations_command():
    items = open_escalations()
    for item in items:
        print("open  %s" % item)
    print("%d open escalation(s)" % len(items))
    return 0


# Out-of-band changes. Shell checks can't see what a script file does. In autonomous mode the harness keeps
# a snapshot of the protected files, refreshed after every file-tool edit and every write of its own, and
# compares it after each shell command. A protected file that changed in between, and is not simply back
# to its committed version, was written some other way.
SNAPSHOT_ROOTS = ("backbone", "scripts/harness", ".claude", ".codex", ".opencode")
SNAPSHOT_FILES = ("AGENTS.md", "CLAUDE.md")
SNAPSHOT_SKIP = (".claude/settings.local.json",)


def snapshot_file():
    """Per worktree (its own git dir), not in the shared .git/harness: each worktree has its own protected files,
    and worktrees sharing one snapshot see each other's files as out-of-band changes."""
    git_dir = git("rev-parse", "--absolute-git-dir").strip()
    return (Path(git_dir) / "harness" / "snapshot.json") if git_dir else events_file().parent / "snapshot.json"


def protected_hashes():
    hashes = {}
    for top in SNAPSHOT_ROOTS:
        for folder, dirs, files in os.walk(str(ROOT / top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
            for name in files:
                full = Path(folder) / name
                key = full.relative_to(ROOT).as_posix()
                if key not in SNAPSHOT_SKIP and not name.endswith((".pyc", ".harness-new", ".harness-bak")):
                    hashes[key] = sha256(full)
    for name in SNAPSHOT_FILES:
        if (ROOT / name).is_file():
            hashes[name] = sha256(ROOT / name)
    return hashes


def snapshot_refresh():
    if not autonomous():
        return
    try:
        path = snapshot_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(protected_hashes()), encoding="utf-8")
    except OSError:
        pass


def out_of_band_changes():
    """Protected files changed since the snapshot, other than restores to the committed version."""
    try:
        previous = json.loads(read(snapshot_file()) or "null")
    except ValueError:
        previous = None
    if previous is None:
        return []
    current = protected_hashes()
    changed = []
    for name in sorted(set(previous) | set(current)):
        if previous.get(name) == current.get(name):
            continue
        committed = show("HEAD", name)
        committed_hash = hashlib.sha256(committed.encode("utf-8")).hexdigest() if committed is not None else None
        if current.get(name) != committed_hash:
            changed.append(name)
    return changed


def blocked_guard(before, after):
    removed = blocked_tasks(before) - blocked_tasks(after)
    if removed:
        return ("  - Only the user clears a BLOCKED note (task %s), after resolving its entry in "
                "backbone/escalations.md." % ", ".join(sorted(removed)))
    return None


# --------------------------------------------------------------------------- gates

def wip_collision(before, after):
    if conf()["HARNESS_ALLOW_PARALLEL_WIP"] == "1":
        return None
    old, new = wip_tasks(before), wip_tasks(after)
    if len(new) > 1 and len(new) > len(old):
        current = "\n".join("    3-TASKS.md:%d %s" % task for task in old) or "    (another task in this edit)"
        return ("  - Only one task may be [WIP]. Already in progress:\n%s\n"
                "    Finish it (mark [x]) or ask the user. To allow parallel tasks the user sets "
                "HARNESS_ALLOW_PARALLEL_WIP=\"1\" in backbone/harness.conf." % current)
    return None


def start_problems(task):
    """Why task cannot be [WIP] (or done): spec, grill and approval. None when it may start."""
    spec = spec_rel(task)
    if task in blocked_tasks(read(TASKS)):
        return ("Task %s is BLOCKED by an escalation; the user resolves it in backbone/escalations.md and "
                "removes the note. Continue with another task." % task)
    invalid = validate_spec(task)
    history = verdict_history(task, "grill")
    last = history[-1] if history else None
    if invalid:
        return ("Task %s cannot start: %s is not ready:\n      - %s\n    The analyst writes requirements "
                "and acceptance criteria, the architect the ADRs and Architecture section."
                % (task, spec, "\n      - ".join(invalid)))
    if last is None:
        return "Task %s cannot start: the spec has not been grilled. Ask the griller agent to review %s." % (task, spec)
    if last.get("verdict") != "pass":
        return ("Task %s cannot start: the griller failed the spec (%s). Take its open questions to the user (have "
                "the analyst or architect apply the recommendations marked apply without asking), update the spec "
                "and grill again." % (task, "; ".join(last.get("reasons") or [])[:400]))
    if last.get("fingerprint") != spec_fingerprint(task):
        return "Task %s cannot start: the spec or its ADRs changed after the griller passed it. Grill again." % task
    report = dict(last, verdict=last.get("claimed"))
    rederived, reasons = effective_grill(task, report)
    if rederived != "pass":
        return "Task %s cannot start: the recorded grill pass does not hold up (%s)." % (task, "; ".join(reasons)[:400])
    if not approved(read(spec_path(task))):
        return ("Task %s cannot start: the user has not approved the spec. Ask them to review %s and add "
                "'Approved-by: <name> (<date>)' under '## Approval' themselves; agents cannot." % (task, spec))
    return None


def start_gate(before, after):
    """Starting a task requires a valid spec, a current griller pass and the user's approval."""
    if not gate_on("HARNESS_SPEC_GATE"):
        return None
    problems = [p for p in (start_problems(task) for task in started_tasks(before, after)) if p]
    return "\n".join("  - " + p for p in problems) if problems else None


def judge_problems(task, current, max_rounds):
    """Why task cannot be finished: no judge pass on the code with fingerprint current. None when it may."""
    history = verdict_history(task, "judge")
    last = history[-1] if history else None
    fails = consecutive_fails(since_last_escalation(task, history))
    reasons = "; ".join((last or {}).get("reasons") or [])[:400]
    if last is None:
        return "Task %s has no judge verdict. Ask the judge agent to review task %s." % (task, task)
    if last.get("verdict") != "pass" and fails >= max_rounds:
        return ("The judge failed task %s %d times. Stop retrying: report the findings to the user and "
                "ask how to proceed. Last reasons: %s" % (task, fails, reasons))
    if last.get("verdict") != "pass":
        return ("The judge failed task %s (round %d of %d): %s. Have the implementer fix the findings, "
                "then run the judge again." % (task, fails, max_rounds, reasons))
    problem = acceptance_problem(task)
    if problem:
        return problem
    if current and last.get("fingerprint") != current:
        return "The code changed after the judge passed task %s. Run the judge again on the current code." % task
    report = dict(last, verdict=last.get("claimed"))
    rederived, why = effective_judge(task, report)
    if rederived != "pass":
        return "The recorded judge pass for task %s does not hold up: %s." % (task, "; ".join(why)[:400])
    policy = policy_approval(read(spec_path(task)))
    if policy:
        risks = risk_reasons(task, policy["base"] if policy["base"] != "none" else "")
        if risks:
            return ("Task %s was approved by policy as low-risk, but %s. Escalate it: python3 "
                    "scripts/harness/lib/harness.py escalate %s --kind approval --reason \"...\""
                    % (task, "; ".join(risks), task))
    return None


def acceptance_problem(task):
    """With HARNESS_TESTER on: the tester's acceptance tests exist, cover every AC, and are unchanged."""
    if not tester_on():
        return None
    history = verdict_history(task, "tests")
    if not history:
        return ("Task %s has no acceptance tests from the tester (HARNESS_TESTER is on). Ask the tester to write "
                "them; the implementer may not." % task)
    acs = [ac for ac, _ in spec_items(strip_comments(read(spec_path(task))), "AC", task)]
    missing = [ac for ac in acs if ac not in acceptance_files(task)]
    if missing:
        return "No acceptance test covers %s of task %s. Ask the tester to add them." % (", ".join(missing), task)
    if acceptance_fingerprint(task) != history[-1].get("fingerprint"):
        return ("The acceptance tests of task %s changed after the tester recorded them. Only the tester may change "
                "them: restore them (git checkout -- <file>), or ask the tester to revise and re-record them."
                % task)
    return None


def judge_gate(before, after):
    """Finishing a task requires a pass verdict from the judge on the current code."""
    values = conf()
    if values["HARNESS_JUDGE_GATE"] == "off":
        return None
    finished = finished_tasks(before, after)
    if not finished:
        return None
    max_rounds = int(values["HARNESS_JUDGE_MAX_ROUNDS"] or 2)
    current = code_fingerprint()
    problems = [p for p in (judge_problems(task, current, max_rounds) for task in finished) if p]
    if not problems:
        return None
    return ("  - " + "\n  - ".join(problems) +
            "\n    To abandon a task instead, change its line back to '- [ ]' without rewording it.")


def spec_guard(before, after):
    """Approval lines are the user's alone, and an approved spec is frozen."""
    if approval_lines(before) != approval_lines(after):
        return "  - Only the user may add, change or remove 'Approved-by:' lines."
    if approved(before) and without_approval(before) != without_approval(after):
        return ("  - This spec is approved and therefore frozen. If it must change, ask the user to remove their "
                "approval first; it will need grilling and approval again.")
    return None


def user_only_change(before, after):
    old, new = parse_conf(before), parse_conf(after)
    changed = [key for key in USER_ONLY_KEYS if old.get(key) != new.get(key)]
    if changed:
        return ("  - %s may only be changed by the user. Ask them to edit backbone/harness.conf themselves."
                % ", ".join(changed))
    return None


def adr_guard(before, after):
    """Accepting an ADR is the user's decision, and an accepted ADR changes only by being superseded."""
    old, new = adr_status(before), adr_status(after)
    if new.lower().startswith("accepted") and not old.lower().startswith("accepted"):
        return ("  - Only the user may set an ADR's status to Accepted. Leave it Proposed and ask the user "
                "to review and accept it.")
    if old.lower().startswith("accepted") and new.lower().startswith("accepted"):
        def body(text):
            return re.sub(r"^##\s+Status\s*$.*?(?=^##\s)", "", strip_comments(text), flags=re.M | re.S | re.I)
        if body(before) != body(after):
            return ("  - This ADR is Accepted and therefore frozen. Record a change as a new ADR that supersedes it "
                    "(and set this one's status to 'Superseded by ADR-NNN').")
    return None


def orchestrator_scope(data, path):
    """The main session orchestrates: specs, ADRs and code are written by the role agents."""
    if data.get("agent_id") or conf()["HARNESS_ORCHESTRATOR_SCOPE"] == "off" or path.startswith("/"):
        return None
    if any(re.search(pattern, path) for pattern in ORCHESTRATOR_ALLOW):
        return None
    role = ("the analyst (requirements) or architect (Architecture, Skills)" if path.startswith("backbone/specs/")
            else "the architect or scribe" if path.startswith("backbone/adr/")
            else "the implementer")
    return ("  - The main session orchestrates and does not edit %s itself; have %s agent make the change."
            % (path, role))


# --------------------------------------------------------------------------- verify
# The hooks guard edits made with the file tools. verify checks the resulting state instead, so it also
# catches changes made any other way: it runs in pre-commit on the staged change, and in CI on a range.

def show(rev, name):
    """Content of name at rev ('' = the index), or None if it does not exist there."""
    try:
        result = subprocess.run(["git", "show", "%s:%s" % (rev, name)], cwd=str(ROOT), capture_output=True,
                                text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    return result.stdout if result.returncode == 0 else None


def tree_fingerprint(commit=None):
    """code_fingerprint for the index (commit None) or a commit: its tree hash without backbone/."""
    git_dir = git("rev-parse", "--absolute-git-dir").strip()
    if not git_dir:
        return None
    tmp = tempfile.mkdtemp(prefix="harness-index-")
    try:
        index = os.path.join(tmp, "index")
        env = dict(os.environ, GIT_INDEX_FILE=index)

        def run(*args):
            return subprocess.run(["git"] + list(args), cwd=str(ROOT), env=env, capture_output=True, text=True)

        if commit:
            run("read-tree", commit)
        elif os.path.isfile(os.path.join(git_dir, "index")):
            shutil.copyfile(os.path.join(git_dir, "index"), index)
        run("rm", "-r", "--cached", "-q", "--ignore-unmatch", "--", "backbone")
        result = run("write-tree")
        return result.stdout.strip() if result.returncode == 0 else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def task_states(text):
    lines = mask_comments(text).splitlines()
    wip = {task_id_at(lines, i) for i, line in enumerate(lines) if WIP_LINE.match(line)}
    done = {task_id_at(lines, i) for i, line in enumerate(lines) if DONE_LINE.match(line)}
    return wip, done


def verify_changes(before, after, changed, done_fingerprint, allow_user_changes=False):
    """Problems with going from revision before to after ('' = index). changed: paths that differ;
    done_fingerprint(task): the code fingerprint at the point task was marked done."""
    values = conf()
    problems = []
    tasks_rel = TASKS.relative_to(ROOT).as_posix()
    old_wip, old_done = task_states(show(before, tasks_rel) if before else "")
    new_wip, new_done = task_states(show(after, tasks_rel))
    if values["HARNESS_ALLOW_PARALLEL_WIP"] != "1" and len(new_wip) > 1 and len(new_wip) > len(old_wip):
        problems.append("more than one task is [WIP]: %s" % ", ".join(sorted(new_wip)))
    if gate_on("HARNESS_SPEC_GATE"):
        for task in sorted((new_wip | new_done) - old_wip - old_done):
            problem = start_problems(task)
            if problem:
                problems.append(problem)
    if values["HARNESS_JUDGE_GATE"] != "off":
        max_rounds = int(values["HARNESS_JUDGE_MAX_ROUNDS"] or 2)
        for task in sorted(new_done - old_done):
            problem = judge_problems(task, done_fingerprint(task), max_rounds)
            if problem:
                problems.append(problem.replace("Run the judge again on the current code.",
                                                "The committed code differs from the code the judge passed "
                                                "(uncommitted or untracked files?); run the judge again."))
    for name in changed:
        if name.startswith("backbone/.verdicts/") and before:
            try:
                old_history = json.loads(show(before, name) or "{}").get("history") or []
                new_history = json.loads(show(after, name) or "{}").get("history") or []
            except ValueError:
                problems.append("%s is not valid JSON" % name)
                continue
            if new_history[:len(old_history)] != old_history:
                problems.append("%s: recorded verdicts were changed or removed; verdict history is append-only "
                                "and written only by the griller's and judge's hooks" % name)
    conf_rel = CONF_FILE.relative_to(ROOT).as_posix()
    old_conf = show(before, conf_rel) if before else None
    if conf_rel in changed and old_conf is not None and not allow_user_changes:
        old, new = parse_conf(old_conf), parse_conf(show(after, conf_rel) or "")
        keys = [key for key in USER_ONLY_KEYS if old.get(key) != new.get(key)]
        if keys:
            problems.append("user-only setting(s) changed in backbone/harness.conf: %s. Only the user may change "
                            "them and commit that change (HARNESS_VERIFY=off git commit ...)." % ", ".join(keys))
    locked = (json.loads(show(after, LOCK_FILE.relative_to(ROOT).as_posix()) or "{}") or {}).get("files", {})
    lock_rel = LOCK_FILE.relative_to(ROOT).as_posix()
    if before and after and not allow_user_changes:
        touched = [n for n in changed if n == lock_rel or any(re.search(p, n) for p in ENFORCEMENT_FILES)]
        if touched:
            problems.append("the harness itself changes (%s). A pull request can rewrite the lock along with the "
                            "files, so harness changes need a human: CI passes --allow-user-changes only when a "
                            "maintainer has approved them." % ", ".join(touched[:5]))
    for name in changed if not allow_user_changes else []:
        if name in locked and any(re.search(p, name) for p in ENFORCEMENT_FILES):
            content = show(after, name)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content is not None else None
            if digest != locked[name]:
                problems.append("%s is a harness enforcement file and differs from the installed version "
                                "(backbone/.harness-lock.json). Harness changes come from update.sh; the user "
                                "commits a deliberate local change with HARNESS_VERIFY=off." % name)
    settings_rel = SETTINGS_FILE.relative_to(ROOT).as_posix()
    if settings_rel in changed and locked:
        commands = []
        try:
            for entries in (json.loads(show(after, settings_rel) or "{}").get("hooks") or {}).values():
                for entry in entries or []:
                    commands.extend(str(h.get("command", "")) for h in entry.get("hooks") or [])
        except (ValueError, AttributeError):
            pass
        missing = [event for event in ("session-start", "pre-tool-use", "post-tool-use", "stop")
                   if not any(re.search(r"harness\.py\"?\s+hook\s+%s\b" % event, c) for c in commands)]
        if missing:
            problems.append(".claude/settings.json no longer runs the harness hook(s): %s" % ", ".join(missing))
    return problems


def verify_staged():
    head = git("rev-parse", "--verify", "-q", "HEAD").strip()
    if head:
        changed = [n for n in git("diff", "--cached", "--name-only", "-z", "HEAD").split("\0") if n]
    else:
        changed = [n for n in git("ls-files", "-z").split("\0") if n]
    fingerprint = tree_fingerprint()
    return verify_changes("HEAD" if head else "", "", changed, lambda task: fingerprint)


def verify_range(spec, allow_user_changes=False):
    base, _, tip = spec.partition("..")
    tip = tip or "HEAD"
    commits = [c for c in git("rev-list", "--reverse", "%s..%s" % (base, tip)).split() if c]
    changed = [n for n in git("diff", "--name-only", "-z", base, tip).split("\0") if n]
    tasks_rel = TASKS.relative_to(ROOT).as_posix()

    def done_fingerprint(task):
        for commit in commits:
            if task in task_states(show(commit, tasks_rel))[1]:
                return tree_fingerprint(commit)
        return tree_fingerprint(tip)

    return verify_changes(base, tip, changed, done_fingerprint, allow_user_changes)


def verify_command(argv):
    allow = "--allow-user-changes" in argv
    args = [a for a in argv if a != "--allow-user-changes"]
    if args[:1] == ["--range"] and len(args) == 2:
        problems = verify_range(args[1], allow)
    elif not args:
        problems = verify_staged()
    else:
        sys.stderr.write("usage: harness.py verify [--range <base>..<tip>] [--allow-user-changes]\n")
        return 64
    for problem in problems:
        print("verify: %s" % problem)
    if not problems:
        print("verify: ok")
    return 1 if problems else 0


# --------------------------------------------------------------------------- health

def health():
    """List of (level, message) for misconfigurations; level is 'error' or 'warn'."""
    issues = []
    hooks_path = git("config", "--get", "core.hooksPath").strip()
    if hooks_path != HOOKS_PATH:
        issues.append(("error", "git hooks inactive: core.hooksPath is %s, expected %s "
                                "(fix: git config core.hooksPath %s)"
                       % (hooks_path or "unset", HOOKS_PATH, HOOKS_PATH)))
    for name in ("pre-commit", "commit-msg"):
        if not os.access(str(ROOT / HOOKS_PATH / name), os.X_OK):
            issues.append(("error", "%s/%s is missing or not executable" % (HOOKS_PATH, name)))
    if HOOK_MARK not in read(SETTINGS_FILE):
        issues.append(("error", ".claude/settings.json has no harness hooks (re-run the harness update)"))
    _, rule_errors = load_rules()
    issues.extend(("error", "guardrail " + e) for e in rule_errors)
    routes, route_errors = load_routes()
    issues.extend(("error", "skill route " + e) for e in route_errors)
    available = available_skills()
    for _, skills, _, where in routes:
        issues.extend(("warn", "skill route %s names missing skill '%s'; the skill gate ignores it until it exists"
                       % (where, s)) for s in skills if s not in available)
    values = conf()
    max_age = int(values["HARNESS_SKILL_MAX_AGE"]) if values["HARNESS_SKILL_MAX_AGE"].isdigit() else 0
    for skill in sorted(SKILLS.glob("*/SKILL.md")) if max_age else []:
        m = re.search(r"^last-verified:\s*(\d{4}-\d{2}-\d{2})\s*$", read(skill), re.M)
        name = skill.parent.name
        if not m:
            issues.append(("warn", "skill %s has no last-verified date (backbone/SKILLS.md)" % name))
            continue
        try:
            age = (time.time() - time.mktime(time.strptime(m.group(1), "%Y-%m-%d"))) / 86400
        except ValueError:
            issues.append(("warn", "skill %s has an invalid last-verified date" % name))
            continue
        if age > max_age:
            issues.append(("warn", "skill %s was last verified %d days ago (HARNESS_SKILL_MAX_AGE %d): re-check it "
                                   "against the current stack" % (name, age, max_age)))
    if values["HARNESS_STOP_MODE"] not in STOP_MODES:
        issues.append(("error", "HARNESS_STOP_MODE must be one of %s" % "|".join(STOP_MODES)))
    for key in ("HARNESS_SPEC_GATE", "HARNESS_SKILL_GATE", "HARNESS_JUDGE_GATE", "HARNESS_ORCHESTRATOR_SCOPE"):
        if values[key] not in ("on", "off"):
            issues.append(("error", "%s must be on or off" % key))
    if values["HARNESS_AUTONOMY"] not in AUTONOMY_MODES:
        issues.append(("error", "HARNESS_AUTONOMY must be one of %s" % "|".join(AUTONOMY_MODES)))
    elif values["HARNESS_AUTONOMY"] == "autonomous":
        if workspace_trusted() is False and os.environ.get("HARNESS_SKIP_TRUST_CHECK") != "1":
            issues.append(("warn", "Claude Code has not trusted this folder: `claude -p` would ignore the project's "
                                   "hooks here, so harness.py run refuses to start (accept the trust dialog once)"))
        if not values["HARNESS_TEST_CMD"]:
            issues.append(("error", "autonomous mode needs HARNESS_TEST_CMD: the judge's tests are the only evidence"))
        if values["HARNESS_VERIFY"] == "off" or values["HARNESS_JUDGE_GATE"] == "off" or values["HARNESS_SPEC_GATE"] == "off":
            issues.append(("error", "autonomous mode needs HARNESS_VERIFY, HARNESS_SPEC_GATE and HARNESS_JUDGE_GATE on"))
    if values["HARNESS_AUTO_APPROVE"] not in ("low", "off"):
        issues.append(("error", "HARNESS_AUTO_APPROVE must be low or off"))
    if values["HARNESS_TESTER"] not in ("on", "off"):
        issues.append(("error", "HARNESS_TESTER must be on or off"))
    try:
        re.compile(values["HARNESS_ACCEPTANCE_PATHS"])
    except re.error as exc:
        issues.append(("error", "HARNESS_ACCEPTANCE_PATHS is not a valid regex (%s)" % exc))
    root = knowledge_root()
    if root is not None:
        if not root.is_dir():
            issues.append(("error", "HARNESS_KNOWLEDGE_ROOT is not a folder: %s" % root))
        if knowledge_server_registered() is False:
            issues.append(("warn", "the knowledge source is on, but no MCP server named \"knowledge\" is registered "
                                   "for this folder: claude mcp add -s local knowledge -- <command>"))
        try:
            re.compile(values["HARNESS_KNOWLEDGE_TOOLS"])
        except re.error as exc:
            issues.append(("error", "HARNESS_KNOWLEDGE_TOOLS is not a valid regex (%s)" % exc))
    for key in ("HARNESS_RISK_TERMS", "HARNESS_RISK_PATHS"):
        try:
            re.compile(values[key])
        except re.error as exc:
            issues.append(("error", "%s is not a valid regex (%s)" % (key, exc)))
    for key in ("HARNESS_RISK_MAX_FILES", "HARNESS_GRILL_MAX_ROUNDS"):
        if not values[key].isdigit():
            issues.append(("error", "%s must be a number" % key))
    if values["HARNESS_VERIFY"] not in ("block", "off"):
        issues.append(("error", "HARNESS_VERIFY must be block or off"))
    if not values["HARNESS_TEST_TIMEOUT"].isdigit():
        issues.append(("error", "HARNESS_TEST_TIMEOUT must be a number of seconds"))
    if not values["HARNESS_JUDGE_MAX_ROUNDS"].isdigit() or int(values["HARNESS_JUDGE_MAX_ROUNDS"]) < 1:
        issues.append(("error", "HARNESS_JUDGE_MAX_ROUNDS must be a positive integer"))
    missing = [a for a in PIPELINE_AGENTS if not (AGENTS_DIR / ("%s.md" % a)).is_file()]
    if missing:
        issues.append(("error", "agent definitions missing in .claude/agents/: %s; the gates cannot be passed "
                                "(re-run the harness update)" % ", ".join(missing)))
    try:
        re.compile(values["HARNESS_TEST_PATHS"])
    except re.error as exc:
        issues.append(("error", "HARNESS_TEST_PATHS is not a valid regex (%s)" % exc))
    if not LOCK_FILE.exists():
        issues.append(("warn", "backbone/.harness-lock.json is missing; updates cannot detect local edits"))
    for name, digest in sorted(lock().get("files", {}).items()):
        current = sha256(ROOT / name)
        if current is None:
            issues.append(("warn", "harness file deleted locally: %s" % name))
        elif current != digest:
            issues.append(("warn", "harness file edited locally (conflicts on update): %s" % name))
    for name, entry in sorted(lock().get("adopted", {}).items()):
        path = adr_file(entry.get("adr", ""))
        if not (CATALOG_DIR / name / "pack.json").is_file():
            issues.append(("warn", "adopted pack %s is no longer in the catalog" % name))
        if path is None or not adr_status(read(path)).lower().startswith("accepted"):
            issues.append(("warn", "pack %s was adopted via %s, which is missing or no longer Accepted; re-adopt from the "
                                   "superseding ADR or remove it (harness.py adopt --remove %s)" % (name, entry.get("adr"), name)))
    if values["HARNESS_DECISION_MODE"] not in decisions.MODES:
        issues.append(("error", "HARNESS_DECISION_MODE must be one of %s" % "|".join(decisions.MODES)))
    if values["HARNESS_DECISION_PROVIDER"] not in decisions.PROVIDERS:
        issues.append(("error", "HARNESS_DECISION_PROVIDER must be one of %s" % "|".join(decisions.PROVIDERS)))
    elif values["HARNESS_DECISION_PROVIDER"] != "none" and values["HARNESS_DECISION_MODE"] != "off":
        ok, reason = decision_authorised(values)
        if not ok:
            issues.append(("error", "decision layer configured but not authorised (no calls are made): %s" % reason))
    try:
        issues.extend(("error", "decisions.json " + p)
                      for p in decisions.validate_definitions(decisions.load_definitions(str(DECISIONS_FILE))))
    except decisions.DecisionError as exc:
        issues.append(("error", str(exc)))
    if not values["HARNESS_COMMIT_NUDGE"].isdigit():
        issues.append(("error", "HARNESS_COMMIT_NUDGE must be a number (0 disables the nudge)"))
    if not values["HARNESS_BUILD_CMD"]:
        issues.append(("warn", "HARNESS_BUILD_CMD is empty: pre-commit cannot check the build"))
    if not values["HARNESS_TEST_CMD"]:
        issues.append(("warn", "HARNESS_TEST_CMD is empty: the judge has no standard test command"))
    return issues


def adopted_summary(info):
    adopted = info.get("adopted", {})
    if not adopted:
        return "none adopted (the stack is decided in the design phase; see harness.py catalog)"
    return ", ".join("%s via %s (%s)" % (name, entry.get("adr"), ", ".join(entry.get("options") or []) or "no options")
                     for name, entry in sorted(adopted.items()))


def doctor():
    info = lock()
    values = conf()
    print("agentic harness %s  project: %s  stack packs: %s" % (info.get("harness_version", "?"),
                                                                 values["HARNESS_PROJECT_NAME"] or ROOT.name,
                                                                 adopted_summary(info)))
    issues = health()
    found, _ = scan()
    if found:
        blocks = sum(1 for f in found if f[1].severity == "block")
        issues.append(("warn", "%d existing rule violation(s) in the codebase (%d blocking); list them with "
                               "python3 scripts/harness/lib/harness.py scan" % (len(found), blocks)))
    pending = placeholders()
    if pending:
        issues.append(("warn", "setup incomplete: %d FILL placeholder(s) in %s"
                       % (sum(pending.values()), ", ".join(sorted(pending)))))
    for level, message in issues:
        print("%s %s" % ("ERROR" if level == "error" else "warn ", message))
    if not issues:
        print("ok   harness healthy")
    return 1 if any(level == "error" for level, _ in issues) else 0


def spec_check(task):
    problems = validate_spec(task)
    history = verdict_history(task, "grill")
    last = history[-1] if history else None
    print("spec %s" % spec_rel(task))
    for problem in problems:
        print("  invalid   %s" % problem)
    if not problems:
        print("  valid")
    if last is None:
        print("  grill     not grilled")
    else:
        stale = last.get("fingerprint") != spec_fingerprint(task)
        print("  grill     %s%s" % (last.get("verdict"), " (stale: spec or ADRs changed since)" if stale else ""))
    print("  approval  %s" % ("approved" if approved(read(spec_path(task))) else "not approved"))
    return 1 if problems else 0


# --------------------------------------------------------------------------- stack catalog

class HarnessError(Exception):
    pass


def pack_names():
    return sorted(path.parent.name for path in CATALOG_DIR.glob("*/pack.json"))


def pack_meta(name):
    path = CATALOG_DIR / name / "pack.json"
    if not path.is_file():
        raise HarnessError("unknown pack '%s' (available: %s)" % (name, ", ".join(pack_names()) or "none"))
    return json.loads(read(path))


def catalog_list():
    names = pack_names()
    if not names:
        print("The catalog is empty.")
        return 0
    adopted = lock().get("adopted", {})
    for name in names:
        meta = pack_meta(name)
        state = "adopted via %s" % adopted[name]["adr"] if name in adopted else "not adopted"
        print("%s  [%s]%s\n  %s\n  applies when: %s"
              % (name, state, "  requires: %s" % ", ".join(meta["requires"]) if meta.get("requires") else "",
                 meta.get("description", ""), meta.get("decides", "")))
        groups = meta.get("groups", {})
        for group, info in sorted(groups.items()):
            members = [o["id"] for o in meta.get("options", []) if o.get("group") == group]
            print("  choose %s %s: %s  (%s)" % ("exactly one" if info.get("required") else "at most one",
                                                group, " | ".join(members), info.get("description", "")))
        for option in meta.get("options", []):
            if not option.get("group"):
                print("  decide %-16s %s" % (option["id"], option.get("description", "")))
    print("\nAdopt after the stack ADR is accepted, deciding every option in it:\n"
          "  python3 scripts/harness/lib/harness.py adopt <pack> --adr ADR-NNN --with <ids> --without <ids>")
    return 0


def rule_lines(path):
    return [line.rstrip() for line in read(path).splitlines() if line.strip() and not line.lstrip().startswith("#")]


def pack_payload(name, options):
    """(files {project path: source}, guardrail lines, route lines, conf) for a pack and its chosen options."""
    meta = pack_meta(name)
    base = CATALOG_DIR / name
    files, guardrails, routes, values = {}, rule_lines(base / "guardrails.conf"), rule_lines(base / "routing.conf"), {}
    for root in [base / "install"] + [base / "options" / o / "install" for o in options]:
        for path in sorted(root.rglob("*")) if root.is_dir() else []:
            if path.is_file() and path.name != ".DS_Store":
                files[path.relative_to(root).as_posix()] = path
    for option in options:
        guardrails += rule_lines(base / "options" / option / "guardrails.conf")
        routes += rule_lines(base / "options" / option / "routing.conf")
        values.update(next(o for o in meta["options"] if o["id"] == option).get("conf", {}))
    return files, guardrails, routes, values


def decide_options(name, chosen, declined):
    """The pack's chosen option ids; raises unless every option of the pack is decided."""
    meta = pack_meta(name)
    options = meta.get("options", [])
    problems, picked = [], []
    for group, info in sorted(meta.get("groups", {}).items()):
        members = [o["id"] for o in options if o.get("group") == group]
        selected = [m for m in members if m in chosen]
        if len(selected) > 1:
            problems.append("%s: choose only one %s, not %s" % (name, group, " and ".join(selected)))
        elif not selected and info.get("required"):
            problems.append("%s: choose the %s (one of %s) as the ADR decided" % (name, group, ", ".join(members)))
        picked += selected
    for option in options:
        if option.get("group"):
            continue
        if option["id"] in chosen:
            picked.append(option["id"])
        elif option["id"] not in declined:
            problems.append("%s: decide '%s' with --with or --without (%s)" % (name, option["id"], option.get("description", "")))
    if problems:
        raise HarnessError("options not decided:\n  - " + "\n  - ".join(problems))
    return picked


def set_conf_values(text, values):
    for key, value in values.items():
        line = '%s="%s"' % (key, value.replace('"', '\\"'))
        pattern = re.compile(r"^#?\s*%s=.*$" % re.escape(key), re.M)
        text = pattern.sub(lambda _m: line, text, count=1) if pattern.search(text) else text.rstrip("\n") + "\n" + line + "\n"
    return text


def replace_block(text, name, lines, header=None):
    """Replace (or append, or with lines=None remove) the marked block of an adopted pack."""
    pattern = re.compile(r"\n?# >>> adopted pack: %s\b.*?# <<< adopted pack: %s <<<\n?" % (re.escape(name), re.escape(name)), re.S)
    text = pattern.sub("\n", text).rstrip("\n") + "\n"
    if lines is None:
        return text
    return text + "\n# >>> adopted pack: %s %s >>>\n%s\n# <<< adopted pack: %s <<<\n" % (name, header, "\n".join(lines), name)


def write_lock(data):
    LOCK_FILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def adopt(names, adr, chosen, declined, dry_run):
    info = lock()
    adopted = info.setdefault("adopted", {})
    tracked = info.setdefault("files", {})
    for name in names:
        for required in pack_meta(name).get("requires", []):
            if required not in names and required not in adopted:
                raise HarnessError("%s requires the %s pack: adopt it too (in the same command or first)" % (name, required))
    path = adr_file(adr)
    if path is None:
        raise HarnessError("%s not found in backbone/adr/; record the stack decision in an ADR first" % adr)
    if not adr_status(read(path)).lower().startswith("accepted"):
        raise HarnessError("%s is not Accepted (status: %s); packs are adopted only from accepted decisions"
                           % (adr, adr_status(read(path)) or "missing"))
    missing = [n for n in names if not re.search(r"\b%s\b" % re.escape(n), read(path), re.I)]
    if missing:
        raise HarnessError("%s does not mention %s; the ADR must state the decision the pack implements"
                           % (adr, ", ".join(missing)))
    known = {o["id"] for n in names for o in pack_meta(n).get("options", [])}
    unknown = sorted((set(chosen) | set(declined)) - known)
    if unknown:
        raise HarnessError("unknown option(s) for %s: %s (see: harness.py catalog)" % (", ".join(names), ", ".join(unknown)))
    plans = [(name, decide_options(name, chosen, declined)) for name in names]
    today = time.strftime("%Y-%m-%d")
    guardrails, routing, conf_text = read(BACKBONE / "guardrails.conf"), read(BACKBONE / "routing.conf"), read(CONF_FILE)
    report = []
    for name, options in plans:
        files, rules, routes, values = pack_payload(name, options)
        previous = set((adopted.get(name) or {}).get("files", []))
        for rel_path, src in sorted(files.items()):
            dest = ROOT / rel_path
            if dest.exists() and rel_path not in tracked and sha256(dest) != sha256(src):
                raise HarnessError("%s already exists as a project file; rename it or remove it before adopting %s"
                                   % (rel_path, name))
        for rel_path in sorted(previous - set(files)):
            if sha256(ROOT / rel_path) == tracked.get(rel_path):
                report.append("remove  %s" % rel_path)
                if not dry_run:
                    (ROOT / rel_path).unlink()
                    tracked.pop(rel_path, None)
        for rel_path, src in sorted(files.items()):
            report.append("install %s" % rel_path)
            if not dry_run:
                dest = ROOT / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(src), str(dest))
                shutil.copymode(str(src), str(dest))
                tracked[rel_path] = sha256(dest)
        header = "(%s, %s; options: %s)" % (adr, today, ", ".join(options) or "none")
        guardrails = replace_block(guardrails, name, rules or ["# (no rules)"], header)
        routing = replace_block(routing, name, routes or ["# (no routes)"], header)
        conf_text = set_conf_values(conf_text, values)
        report.append("rules   %d guardrail(s), %d route(s) into backbone/guardrails.conf and routing.conf"
                      % (len(rules), len(routes)))
        report.extend("conf    %s=\"%s\"" % kv for kv in sorted(values.items()))
        adopted[name] = {"adr": adr, "options": options, "date": today, "files": sorted(files)}
    if not dry_run:
        (BACKBONE / "guardrails.conf").write_text(guardrails, encoding="utf-8")
        (BACKBONE / "routing.conf").write_text(routing, encoding="utf-8")
        CONF_FILE.write_text(conf_text, encoding="utf-8")
        write_lock(info)
    print("%s %s from %s:" % ("Would adopt" if dry_run else "Adopted", ", ".join(n for n, _ in plans), adr))
    print("\n".join("  " + line for line in report))
    if not dry_run:
        print("Record the adoption in %s's Consequences, list the skills in backbone/9-AGENT-SKILLS.md, and commit." % adr)
    return 0


def unadopt(names, dry_run):
    info = lock()
    adopted = info.get("adopted", {})
    tracked = info.get("files", {})
    for name in names:
        if name not in adopted:
            raise HarnessError("%s is not adopted" % name)
        dependents = [n for n in adopted if n not in names and name in pack_meta(n).get("requires", [])]
        if dependents:
            raise HarnessError("%s is required by %s; remove those first or together" % (name, ", ".join(dependents)))
    guardrails, routing = read(BACKBONE / "guardrails.conf"), read(BACKBONE / "routing.conf")
    report = []
    for name in names:
        for rel_path in adopted[name].get("files", []):
            if sha256(ROOT / rel_path) == tracked.get(rel_path):
                report.append("remove  %s" % rel_path)
                if not dry_run:
                    (ROOT / rel_path).unlink()
            else:
                report.append("kept    %s (edited locally; delete it yourself if unwanted)" % rel_path)
            tracked.pop(rel_path, None)
        guardrails = replace_block(guardrails, name, None)
        routing = replace_block(routing, name, None)
        del adopted[name]
    if not dry_run:
        (BACKBONE / "guardrails.conf").write_text(guardrails, encoding="utf-8")
        (BACKBONE / "routing.conf").write_text(routing, encoding="utf-8")
        write_lock(info)
    print("%s %s:" % ("Would remove" if dry_run else "Removed", ", ".join(names)))
    print("\n".join("  " + line for line in report) or "  (no files)")
    print("harness.conf values set by the pack were left as they are; review them.")
    return 0


def adopt_command(argv):
    import argparse
    parser = argparse.ArgumentParser(prog="harness.py adopt")
    parser.add_argument("packs", nargs="?")
    parser.add_argument("--adr")
    parser.add_argument("--with", dest="chosen", default="")
    parser.add_argument("--without", dest="declined", default="")
    parser.add_argument("--remove")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    split = lambda value: [v.strip() for v in (value or "").split(",") if v.strip()]
    try:
        if args.remove:
            return unadopt(split(args.remove), args.dry_run)
        if not args.packs or not args.adr:
            raise HarnessError("usage: adopt <pack>[,<pack>] --adr ADR-NNN --with <ids> --without <ids>")
        for name in split(args.packs):
            pack_meta(name)
        return adopt(split(args.packs), args.adr, split(args.chosen), split(args.declined), args.dry_run)
    except HarnessError as exc:
        sys.stderr.write("harness: %s\n" % exc)
        return 2


# --------------------------------------------------------------------------- Claude Code hooks

def emit(payload):
    global EMITTED
    EMITTED = True
    sys.stdout.write(json.dumps(payload) + "\n")


def add_context(event, text):
    emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def events_file():
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(ROOT), capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except subprocess.TimeoutExpired:
        common = ".git"
    base = Path(common) if common and os.path.isabs(common) else ROOT / (common or ".git")
    return base / "harness" / "events.jsonl"


def log_event(kind, **fields):
    """Append one event to .git/harness/events.jsonl (never fails the caller)."""
    try:
        path = events_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind}
        entry.update(fields)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


def deny(reason, kind="block"):
    """PreToolUse/SubagentStop: exit 2 blocks and shows stderr to the agent."""
    lines = [line.strip(" -") for line in reason.strip().splitlines() if line.strip()]
    specific = next((line for line in lines[1:] if line), lines[0] if lines else "")
    log_event(kind, reason=specific[:200], detail=reason[:2000])
    sys.stderr.write(reason.rstrip() + "\n")
    sys.exit(2)


def added_text(tool, tool_input):
    if tool == "Write":
        return tool_input.get("content") or ""
    if tool == "Edit":
        return tool_input.get("new_string") or ""
    return "\n".join((edit or {}).get("new_string") or "" for edit in tool_input.get("edits") or [])


def resulting_text(tool, tool_input, path_str):
    if tool == "Write":
        return tool_input.get("content") or ""
    path = Path(path_str)
    current = read(path if path.is_absolute() else ROOT / path)
    edits = [tool_input] if tool == "Edit" else (tool_input.get("edits") or [])
    for edit in edits:
        old, new = edit.get("old_string") or "", edit.get("new_string") or ""
        if not old:
            continue
        current = current.replace(old, new) if edit.get("replace_all") else current.replace(old, new, 1)
    return current


def hook_session_start(_data):
    values = conf()
    info = lock()
    lines = ["[agentic harness %s] project: %s, stack packs: %s"
             % (info.get("harness_version", "?"), values["HARNESS_PROJECT_NAME"] or ROOT.name, adopted_summary(info))]
    pending = placeholders()
    if pending:
        lines.append("SETUP INCOMPLETE: %d FILL placeholder(s) in %s. Run first-run setup "
                     "(AGENTS.md section 1) with the user before any other work."
                     % (sum(pending.values()), ", ".join(sorted(pending))))
    else:
        lines.append("Before changing anything read: AGENTS.md, backbone/4-KNOWLEDGE.md, backbone/7-CONVENTIONS.md, "
                     "backbone/8-WORKFLOW.md, backbone/3-TASKS.md.")
    snapshot_refresh()
    if autonomous():
        lines.append("AUTONOMOUS MODE: no user is in the loop. Never ask the user; approve low-risk specs with "
                     "harness.py approve <id>, escalate everything else with harness.py escalate <id> --reason ..., "
                     "and continue with the next ready task (AGENTS.md section 7).")
        if knowledge_root() is not None:
            lines.append("Knowledge source on: the analyst and architect answer the griller's questions from "
                         "backbone/ and the knowledge MCP server (cite vault:<path>); escalate what neither answers.")
    if halt_file().exists():
        lines.append("HALTED: %s exists. Do not change anything; report your state." % halt_file())
    pending_escalations = open_escalations()
    if pending_escalations:
        lines.append("Open escalations waiting for the user: %d (backbone/escalations.md); tasks marked BLOCKED "
                     "are parked." % len(pending_escalations))
    tasks = wip_task_ids()
    if tasks:
        lines.append("Task in progress (resume it, or ask the user before starting other work): %s "
                     "(spec: %s)" % (", ".join(tasks), ", ".join(spec_rel(t) for t in tasks)))
    errors = [message for level, message in health() if level == "error"]
    if errors:
        lines.append("Harness problems (details: scripts/harness/doctor.sh):")
        lines.extend("  - " + message for message in errors)
    found, _ = scan()
    blocks = sorted({name for name, rule, _ in found if rule.severity == "block"})
    if blocks:
        lines.append("Existing code already breaks blocking rules in %d file(s), e.g. %s. Don't copy those "
                     "patterns; fixing them needs its own task (list: python3 scripts/harness/lib/harness.py scan)."
                     % (len(blocks), ", ".join(blocks[:3])))
    if HOOK_SOURCE == "codex":
        add_context("SessionStart", "\n".join(lines))
    else:
        print("\n".join(lines))


def hook_pre_tool_use(data):
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if halt_file().exists():
        deny("Harness halted: %s exists (the user's kill switch). Stop working and report your state; the user "
             "removes the file to resume." % halt_file())
    if tool.startswith(KNOWLEDGE_TOOL_PREFIX):
        knowledge_guard(tool, tool_input)
        return
    if tool == "apply_patch":
        for name, call_input in patch_calls(tool_input.get("command") or tool_input.get("patch") or ""):
            hook_pre_tool_use(dict(data, tool_name=name, tool_input=call_input))
        return
    rules, _ = load_rules()
    if tool == "Bash":
        command = tool_input.get("command") or ""
        problems = ["  - " + p for p in shell_findings(command, data.get("cwd"))]
        hits = check_text(rules, None, rule_text(command), ("block",))
        if hits:
            problems.append(describe(hits))
        if problems:
            deny("Harness blocked this command:\n%s\nIf the user really wants it, ask them to run it "
                 "themselves (in Claude Code: `! <command>`). Do not rephrase the command to get "
                 "around the rule." % "\n".join(problems))
        return
    if tool not in FILE_TOOLS or not tool_input.get("file_path"):
        return
    path_str = tool_input["file_path"]
    path = rel(path_str)
    if data.get("harness_role"):
        hook_agent_guard(data, data["harness_role"])
    if path.startswith("backbone/.verdicts/"):
        deny("Harness blocked this change to %s: verdicts are recorded only by the griller's and judge's hooks."
             % path)
    problems = []
    hits = check_text(rules, path, added_text(tool, tool_input), ("block",))
    if hits:
        problems.append(describe(hits))
    checks = ()
    if path == LOCK_FILE.relative_to(ROOT).as_posix():
        deny("Harness blocked this change to %s: the lock is written by the installer and harness.py adopt only."
             % path)
    if path == "backbone/escalations.md":
        deny("Harness blocked this change to %s: escalations are written by harness.py escalate and resolved by "
             "the user." % path)
    if path == "backbone/3-TASKS.md":
        checks = (wip_collision, start_gate, judge_gate, blocked_guard)
    elif path == "backbone/harness.conf":
        checks = (user_only_change,)
    elif re.match(r"^backbone/specs/[^/]+\.md$", path):
        checks = (spec_guard,)
    elif re.match(r"^backbone/adr/[^/]+\.md$", path):
        checks = (adr_guard,)
    if checks:
        before = read(ROOT / path)
        after = resulting_text(tool, tool_input, path_str)
        problems.extend(p for p in (check(before, after) for check in checks) if p)
    scope = orchestrator_scope(data, path)
    if scope:
        problems.append(scope)
    skills = skill_gate(data, path)
    if skills:
        problems.append(skills)
    if problems:
        deny("Harness blocked this change to %s:\n%s" % (path, "\n".join(problems)))


def fresh_commit(max_age=120):
    stamp = git("log", "-1", "--format=%ct").strip()
    return stamp.isdigit() and time.time() - int(stamp) < max_age


def dod_after_commit():
    notes = []
    files = [f for f in git("show", "--name-only", "--format=", "HEAD").splitlines() if f]
    code = [f for f in files if not f.startswith("backbone/")]
    if code and "backbone/3-TASKS.md" not in files:
        notes.append("This commit changes code but not backbone/3-TASKS.md. If it finishes the task, mark it [x] "
                     "(Definition of Done, backbone/8-WORKFLOW.md).")
    for name in files:
        if re.match(r"^backbone/adr/ADR-\d+[^/]*\.md$", name):
            notes.extend(validate_adr(read(ROOT / name), Path(name).name))
    if "backbone/6-MEMORY.md" in files:
        notes.extend(stubs(MEMORY))
    tasks = wip_task_ids()
    if tasks:
        notes.append("Still [WIP]: %s. When the judge has passed it, mark it [x] and commit." % ", ".join(tasks))
    return notes


def hook_post_tool_use(data):
    notes = []
    if data.get("tool_name") == "apply_patch":
        command = (data.get("tool_input") or {}).get("command") or (data.get("tool_input") or {}).get("patch") or ""
        for name, call_input in patch_calls(command):
            notes += post_tool_notes(dict(data, tool_name=name, tool_input=call_input))
    else:
        notes = post_tool_notes(data)
    if notes:
        add_context("PostToolUse", "\n\n".join(notes))


SKILL_FILE = re.compile(r"(?:^|[\s'\"=/])(?:\./)?(?:\.claude|\.agents)/skills/([A-Za-z0-9._-]+)/SKILL\.md\b")
SKILL_READERS = re.compile(r"^\s*(cat|sed|head|tail|less|more|bat|nl|awk)\b")


def post_tool_notes(data):
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    notes = []
    if tool == "Read":
        m = re.match(r"^\.claude/skills/([^/]+)/SKILL\.md$", rel(tool_input.get("file_path") or ""))
        if m:
            remember_skill(data, m.group(1))
        return notes
    if tool == "Skill":
        name = str(tool_input.get("skill") or tool_input.get("name") or "").split(":")[-1].strip()
        remember_skill(data, name)
        return notes
    if tool in FILE_TOOLS and tool_input.get("file_path"):
        snapshot_refresh()
        path = rel(tool_input["file_path"])
        rules, _ = load_rules()
        hits = check_text(rules, path, added_text(tool, tool_input), ("warn",))
        if hits:
            notes.append("Guardrail warnings for %s:\n%s" % (path, describe(hits)))
        if path in owned_files():
            notes.append("%s is harness-owned: the next harness update will flag this edit as a conflict. "
                         "Put project rules in the project-owned backbone files instead, or upstream the "
                         "change to the harness." % path)
        m = re.match(r"^backbone/specs/([^/]+)\.md$", path)
        if m:
            problems = validate_spec(m.group(1))
            if problems:
                notes.append("Spec %s is not ready yet (the start gate needs it valid):\n  - %s"
                             % (path, "\n  - ".join(problems)))
    elif tool == "Bash":
        command = tool_input.get("command") or ""
        # Agents without a Read or Skill tool (Codex) load a skill by printing its SKILL.md.
        for part in re.split(r"&&|;|\|\|", command):
            if SKILL_READERS.match(part):
                for name in SKILL_FILE.findall(part):
                    remember_skill(data, name)
        rules, _ = load_rules()
        hits = check_text(rules, None, rule_text(command), ("warn",))
        if hits:
            notes.append("Guardrail warnings for that command:\n%s" % describe(hits))
        if re.search(r"\bgit\b[^\n;&|]*\bcommit\b", command) and fresh_commit():
            notes.extend(dod_after_commit())
        if autonomous():
            changed = out_of_band_changes()
            if changed:
                log_event("tamper", files=changed[:20], command=command[:300])
                notes.append("Harness-protected files changed outside the Write/Edit tools: %s. Restore them "
                             "(git checkout -- <file>) and make the change with the file tools, where the gates "
                             "apply." % ", ".join(changed[:8]))
                for task in wip_task_ids():
                    escalate(task, "out-of-band change", "protected files changed outside the file tools: %s"
                             % ", ".join(changed[:8]), "a check of what changed them, and a restore")
                    notes.append("Task %s is BLOCKED for review (backbone/escalations.md)." % task)
            snapshot_refresh()
    return notes


def uncommitted_count():
    return len([line for line in git("status", "--porcelain").splitlines() if line and not line.startswith("??")])


def hook_stop(data):
    role = data.get("harness_role") if session_role() else None
    if role:
        # A session that plays one role (HARNESS_ROLE) ends like that role's subagent would: the griller's and
        # judge's verdicts are recorded; the coordinator, not the role, owns the Definition of Done.
        if role in ROLE_RECORDERS:
            ROLE_RECORDERS[role](data)
        return
    values = conf()
    mode = values["HARNESS_STOP_MODE"]
    if halt_file().exists():
        return
    if autonomous() and mode != "off":
        mode = "block"
    tasks = wip_tasks()
    if mode == "off":
        return
    if not tasks:
        threshold = int(values["HARNESS_COMMIT_NUDGE"]) if values["HARNESS_COMMIT_NUDGE"].isdigit() else 0
        changed = uncommitted_count() if threshold else 0
        if threshold and changed >= threshold:
            emit({"systemMessage": "harness: %d tracked file(s) have uncommitted changes and no task is [WIP]; "
                                   "consider committing." % changed})
        return
    titles = "; ".join(task for _, task in tasks[:2])
    if mode == "block" and not data.get("stop_hook_active"):
        emit({"decision": "block",
              "reason": "Task still [WIP] in backbone/3-TASKS.md: %s\nBefore stopping, complete the "
                        "Definition of Done (backbone/8-WORKFLOW.md), or if you are waiting for the user, "
                        "say so and stop again." % titles})
        return
    emit({"systemMessage": "harness: still [WIP]: %s (Definition of Done: backbone/8-WORKFLOW.md)" % titles})


def role_scope(agent):
    """(mode, patterns) for agent's writes. The acceptance tests belong to the tester when HARNESS_TESTER is on."""
    scope = AGENT_SCOPES.get(agent)
    if scope is None:
        return None
    mode, patterns = scope
    acceptance = conf()["HARNESS_ACCEPTANCE_PATHS"]
    if agent == "tester":
        patterns = patterns + (acceptance,)
    elif agent == "implementer" and tester_on():
        patterns = patterns + (acceptance,)
    return mode, patterns


def tester_on():
    return conf()["HARNESS_TESTER"] == "on"


def hook_agent_guard(data, agent):
    """PreToolUse scoped to one agent: keep its edits inside its role."""
    scope = role_scope(agent)
    tool_input = data.get("tool_input") or {}
    if scope is None or data.get("tool_name") not in FILE_TOOLS or not tool_input.get("file_path"):
        return
    path = rel(tool_input["file_path"])
    mode, patterns = scope
    try:
        hit = any(re.search(pattern, path) for pattern in patterns)
    except re.error:
        hit = mode == "deny"
    if (mode == "allow" and not hit) or (mode == "deny" and hit):
        extra = (" The acceptance tests (HARNESS_ACCEPTANCE_PATHS) belong to the tester; if one contradicts the "
                 "spec, say so and the coordinator sends it back." if agent == "implementer" and tester_on() else "")
        deny("The %s agent may not edit %s. %s%s" % (agent, path, SCOPE_HELP[agent], extra))


# --------------------------------------------------------------------------- coordinator API
# A coordinator (harness.py orca, harness.py run, or any script) asks the harness what a task needs next instead of
# knowing the workflow. The answers come from the artifacts the gates check, so they can't drift from them; start and
# finish move a task line through the same gates as an edit of 3-TASKS.md.

DESIGN_TOPICS = re.compile(r"(?i)\b(ADR|architecture|design|skills?|tech(nical)?|module|layer|stack|dependenc)")


def task_ids():
    lines = mask_comments(read(TASKS)).splitlines()
    found = []
    for i, line in enumerate(lines):
        if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and TASK_REF.search(line):
            task = task_id_at(lines, i)
            if task and task not in found:
                found.append(task)
    return found


def task_title(task):
    _, line = task_line(task)
    if not line:
        return ""
    title = re.sub(r"^\s*[-*]\s+\[[^\]]*\]\s*\**Task\s+[A-Za-z0-9._-]*[A-Za-z0-9]:?\s*", "", line)
    return title.split("**")[0].strip()


def question_route(question):
    """Who answers a griller question: the architect for design, the analyst for everything else."""
    about = "%s %s" % (question.get("about") or "", question.get("question") or "")
    return "architect" if DESIGN_TOPICS.search(about) else "analyst"


def open_questions(task):
    history = verdict_history(task, "grill")
    last = history[-1] if history else None
    if not last or last.get("verdict") == "pass":
        return []
    return [dict(q, route=question_route(q)) for q in (last.get("questions") or []) if isinstance(q, dict)]


def task_status(task):
    state = task_state(task)
    exists = spec_path(task).is_file()
    text = read(spec_path(task)) if exists else ""
    grill = verdict_history(task, "grill")
    judge = verdict_history(task, "judge")
    last_grill, last_judge = (grill[-1] if grill else None), (judge[-1] if judge else None)
    return {
        "task": task, "title": task_title(task), "state": state, "spec": spec_rel(task) if exists else None,
        "spec_problems": validate_spec(task) if exists else ["no spec yet"],
        "grill": last_grill and {"verdict": last_grill.get("verdict"),
                                 "current": last_grill.get("fingerprint") == spec_fingerprint(task)},
        "approved": bool(exists and approved(text)),
        "judge": last_judge and {"verdict": last_judge.get("verdict"),
                                 "current": last_judge.get("fingerprint") == code_fingerprint()},
        "escalations": [e for e in open_escalations() if re.search(r"\bTask %s:" % re.escape(task), e)],
    }


TECH_PLACEHOLDER = re.compile(r"(?i)^<.*>$|\b(to be (added|filled|decided|defined)|tbd|todo|fill(ed)? in later|pending)\b")


def architecture_pending(text):
    """The architect hasn't filled in the spec yet: no tech requirement beyond the template's placeholders."""
    section = md_section(strip_comments(text), "Architecture") or ""
    tech = section.split("Tech requirements:", 1)[1] if "Tech requirements:" in section else ""
    items = [b for b in bullets(tech) if b]
    return not items or all(TECH_PLACEHOLDER.search(b) for b in items)


def code_changed():
    """Uncommitted changes outside backbone/ and the tester's acceptance tests (the implementer's work)."""
    try:
        acceptance = re.compile(conf()["HARNESS_ACCEPTANCE_PATHS"]) if tester_on() else None
    except re.error:
        acceptance = None
    names = [n for n in git("status", "--porcelain", "-uall").splitlines()]
    harness_files = [p for p in SHELL_PROTECTED] + list(ENFORCEMENT_FILES)
    return any(n[3:] and not n[3:].startswith("backbone/") and not (acceptance and acceptance.search(n[3:]))
               and not any(re.search(p, n[3:]) for p in harness_files) for n in names)


def next_step(task):
    """What task needs next: {step, role (who does it, or null), command (what to run), ...}."""
    s = task_status(task)
    step = {"task": task, "title": s["title"], "state": s["state"]}
    if s["state"] == "missing":
        return dict(step, step="unknown", role=None, reason="no such task in backbone/3-TASKS.md")
    if s["state"] == "blocked":
        return dict(step, step="blocked", role=None, needed="the user", escalations=s["escalations"])
    if s["state"] == "done":
        return dict(step, step="done", role=None)
    if s["state"] == "pending":
        if not s["spec"]:
            return dict(step, step="define", role="analyst", reason="no spec yet")
        if s["spec_problems"]:
            design = any(re.search(r"(?i)architecture|skills|ADR", p) for p in s["spec_problems"])
            return dict(step, step="define", role="architect" if design else "analyst", problems=s["spec_problems"])
        if architecture_pending(read(spec_path(task))):
            return dict(step, step="define", role="architect",
                        reason="the Architecture section has no tech requirements yet (the architect designs next)")
        if not (s["grill"] and s["grill"]["current"]):
            return dict(step, step="grill", role="griller", reason="no griller verdict on the current spec")
        if s["grill"]["verdict"] != "pass":
            questions = open_questions(task)
            # The role that owns a blocker answers first; then design before requirements.
            rank = lambda r: (not any(q["route"] == r and q.get("severity") == "blocker" for q in questions),
                              r != "architect")
            roles = sorted({q["route"] for q in questions}, key=rank) or ["analyst"]
            asked = [q for q in questions if not q.get("apply")]
            return dict(step, step="answer", role=roles[0], roles=roles, questions=questions,
                        needs_user=bool(asked) and not autonomous(),
                        then="grill again (the answers change the spec)")
        if not s["approved"]:
            if autonomous():
                return dict(step, step="approve", role=None, command="python3 scripts/harness/lib/harness.py "
                                                                       "approve %s" % task)
            return dict(step, step="approve", role=None, needed="the user's Approved-by: line in %s" % s["spec"])
        return dict(step, step="start", role=None, command="python3 scripts/harness/lib/harness.py start %s" % task)
    if s["spec"] and not (s["grill"] and s["grill"]["current"] and s["grill"]["verdict"] == "pass"):
        return dict(step, step="grill", role="griller", reason="the spec changed during the build (an answered "
                                                                 "question); grill it again before going on")
    if tester_on():
        tests = verdict_history(task, "tests")
        if not tests or acceptance_fingerprint(task) != tests[-1].get("fingerprint"):
            return dict(step, step="test", role="tester",
                        reason="no acceptance tests yet" if not tests else "the acceptance tests changed since the "
                                                                          "tester recorded them")
    judge = s["judge"]
    if judge and judge["current"] and judge["verdict"] == "pass":
        return dict(step, step="finish", role="scribe", then="python3 scripts/harness/lib/harness.py finish %s, "
                                                               "then commit" % task)
    if judge and judge["current"]:
        last = verdict_history(task, "judge")[-1]
        briefs = [b for b in verdict_history(task, "debug") if b.get("judge_at") == last.get("at")]
        if conf()["HARNESS_DEBUGGER"] == "on" and not briefs:
            return dict(step, step="diagnose", role="debugger", reasons=last.get("reasons"))
        owners = sorted({str(c.get("owner")) for c in (briefs[-1] if briefs else {}).get("root_causes") or []
                         if isinstance(c, dict)} - {"implementer", "None"})
        return dict(step, step="fix", role="implementer", findings=last.get("findings") or last.get("reasons"),
                    brief=briefs[-1] if briefs else None,
                    **({"needs": owners} if owners else {}))
    if not judge and not code_changed():
        return dict(step, step="implement", role="implementer")
    return dict(step, step="judge", role="judge", reason="no judge verdict on the current code")


def set_task_marker(task, marker, checks):
    """Move task's line to [marker] if the gates allow it (the same checks as an edit of 3-TASKS.md)."""
    before = read(TASKS)
    index, line = task_line(task, before)
    if index is None:
        return ["no task %s in backbone/3-TASKS.md" % task]
    lines = before.splitlines()
    lines[index] = re.sub(r"^(\s*[-*]\s+)\[[^\]]*\]", lambda m: m.group(1) + "[%s]" % marker, line, count=1)
    after = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    problems = [p for p in (check(before, after) for check in checks) if p]
    if problems:
        return problems
    TASKS.write_text(after, encoding="utf-8")
    snapshot_refresh()
    log_event("task-%s" % ("start" if marker == "WIP" else "finish"), task=task)
    return []


def start_command(task):
    problems = set_task_marker(task, "WIP", (blocked_guard, wip_collision, start_gate))
    print("start: task %s is [WIP]" % task if not problems else "start: task %s can't start:\n%s"
          % (task, "\n".join(problems)))
    return 1 if problems else 0


def finish_command(task):
    problems = set_task_marker(task, "x", (blocked_guard, judge_gate))
    print("finish: task %s is [x]; commit it with its code, tests, spec and verdicts" % task if not problems
          else "finish: task %s can't finish:\n%s" % (task, "\n".join(problems)))
    return 1 if problems else 0


def state_command(argv):
    states = [task_status(t) for t in task_ids()]
    if "--json" in argv:
        print(json.dumps({"autonomous": autonomous(), "tasks": states, "halted": halt_file().exists()}, indent=2))
        return 0
    for s in states:
        print("%-8s %-8s %s" % (s["task"], s["state"], s["title"]))
    return 0


def next_command(argv):
    tasks = [a for a in argv if not a.startswith("--")] or [t for t, _, _ in ready_tasks()][:1]
    steps = [next_step(t) for t in tasks]
    if "--json" in argv:
        print(json.dumps(steps[0] if len(steps) == 1 else steps, indent=2))
        return 0
    for s in steps:
        print("next %s: %s%s%s" % (s["task"], s["step"], " (%s)" % s["role"] if s.get("role") else "",
                                   ": " + s["command"] if s.get("command") else ""))
    return 0


def questions_command(argv):
    task = next((a for a in argv if not a.startswith("--")), None)
    if not task:
        sys.stderr.write("usage: harness.py questions <task> [--json]\n")
        return 64
    questions = open_questions(task)
    if "--json" in argv:
        print(json.dumps({"task": task, "questions": questions}, indent=2))
        return 0
    for q in questions:
        if q.get("apply"):
            print("[%s -> %s, apply] %s: %s Recommendation: %s" % (q.get("severity"), q["route"], q.get("about"),
                                                                   q.get("question"), q.get("recommendation")))
        else:
            print("[%s -> %s] %s: %s" % (q.get("severity"), q["route"], q.get("about"), q.get("question")))
    return 0


def orca_dir(create=False):
    """<git common dir>/harness: shared by the repository's worktrees. Reads don't create it."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    path = Path(common) / "harness" if common else ROOT / ".git" / "harness"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


ORCA_LOCK = {"fd": None}


def orca_lock_holder():
    """The pid recorded by a live coordinator of this repository (it holds an OS lock on orca.lock), or None."""
    path = orca_dir() / "orca.lock"
    if not path.exists():
        return None
    try:
        import fcntl
        fd = os.open(str(path), os.O_RDONLY)
    except (ImportError, OSError):
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            try:
                return int(json.loads(os.read(fd, 4096).decode("utf-8") or "{}").get("pid")) or -1
            except (ValueError, TypeError):
                return -1
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def orca_lock_acquire():
    """One coordinator per repository: an exclusive OS lock on orca.lock, held until the process ends. A stale file
    (its process gone) holds no lock, so nothing needs deleting and there is no window between check and claim."""
    import fcntl
    fd = os.open(str(orca_dir(create=True) / "orca.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps({"pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}).encode("utf-8"))
    ORCA_LOCK["fd"] = fd
    return True


def orca_lock_release():
    if ORCA_LOCK["fd"] is not None:
        try:
            os.ftruncate(ORCA_LOCK["fd"], 0)
            os.close(ORCA_LOCK["fd"])
        except OSError:
            pass
        ORCA_LOCK["fd"] = None


def adr_numbers(folder):
    return {int(m.group(1)) for p in Path(folder).glob("ADR-*.md") for m in [re.match(r"ADR-(\d+)", p.name)] if m}


def adr_next():
    """The next free ADR number for this repository, shared by all its worktrees (parallel tasks would otherwise
    each take "the next one" and collide). Under a lock in the shared git directory; returns the number."""
    import fcntl
    folder = orca_dir(create=True)
    fd = os.open(str(folder / "adr.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        used = adr_numbers(ADRS)
        for line in git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                used |= adr_numbers(Path(line[len("worktree "):]) / "backbone" / "adr")
        counter = folder / "adr-next"
        try:
            used.add(int(counter.read_text(encoding="utf-8").strip()) - 1)
        except (OSError, ValueError):
            pass
        number = max(used, default=0) + 1
        counter.write_text("%d\n" % (number + 1), encoding="utf-8")
        return number
    finally:
        os.close(fd)


def orca_digest():
    """The summary of the last finished backlog run (orca-digest.txt, written when a run ends), or None."""
    text = read(orca_dir() / "orca-digest.txt").strip()
    return text or None


def orca_digest_publish(text):
    path = orca_dir(create=True) / "orca-digest.txt"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text.strip() + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def orca_digest_command(_argv):
    digest = orca_digest()
    holder = orca_lock_holder()
    print(digest or "orca-digest: no finished backlog run yet")
    if holder:
        print("orca-digest: a backlog run is going now (pid %s)" % holder)
    return 0


def orca_nightly_command(argv):
    """For a scheduled Orca automation (its --precheck): print the last digest, then start the coordinator in its
    own Orca terminal unless one is still running for this repository. Never runs from an agent's shell."""
    print(orca_digest() or "orca-nightly: no earlier run")
    holder = orca_lock_holder()
    if holder:
        print("orca-nightly: a backlog run is still going (pid %d); not starting another" % holder)
        return 0
    binary = shutil.which(os.environ.get("HARNESS_ORCA_BIN", "orca"))
    if not binary:
        print("orca-nightly: orca is not installed")
        return 1
    log = orca_dir() / "orca-latest.log"
    extra = [a for a in argv if a not in ("--dry-run",)] or ["--merge", "--trust"]
    if "--dry-run" not in argv:
        orca_dir(create=True)
    command = "%s %s orca %s > %s 2>&1" % (shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve())),
                                            " ".join(shlex.quote(a) for a in extra), shlex.quote(str(log)))
    if "--dry-run" in argv:
        print("orca-nightly: would open an Orca terminal running: %s" % command)
        return 0
    # Its own terminal: an Orca terminal coordinates one Run, so the coordinator must not share the caller's.
    result = subprocess.run([binary, "terminal", "create", "--worktree", "path:%s" % ROOT, "--title",
                             "harness backlog", "--command", command, "--json"], cwd=str(ROOT), capture_output=True,
                            text=True)
    ok = result.returncode == 0 and '"ok": false' not in result.stdout and '"ok":false' not in result.stdout
    print("orca-nightly: %s" % ("started the backlog run in an Orca terminal; log: %s" % log if ok
                                 else "could not open a terminal: %s" % (result.stderr or result.stdout).strip()[:300]))
    log_event("orca-nightly", started=ok)
    return 0 if ok else 1


AFTER_NOTE = re.compile(r"\(after(?::\s*|\s+)([^)]+)\)", re.I)   # "(after: 1.1, 1.2)" or "(after 1.1)"


def task_dependencies():
    """{task: [tasks it waits for]} from "(after: 1.1, 1.2)" or "(after 1.1)" on its line in 3-TASKS.md."""
    lines = mask_comments(read(TASKS)).splitlines()
    deps = {}
    for i, line in enumerate(lines):
        m = AFTER_NOTE.search(line)
        if m and re.match(r"^\s*[-*]\s+\[[^\]]*\]", line):
            deps[task_id_at(lines, i)] = [d.rstrip(".") for d in re.split(r"[,\s]+", m.group(1))
                                          if re.match(r"^\d+(\.\d+[a-z]?)*\.?$", d)]
    return deps


def orca_command(argv):
    """harness.py orca: drive ready tasks with Orca supervised workers (scripts/harness/lib/coordinator.py)."""
    import coordinator
    if not autonomous():
        print("orca: needs HARNESS_AUTONOMY=\"autonomous\" (set by the user in backbone/harness.conf): the workers "
              "answer the griller's questions and approve low-risk specs by policy")
        return 1
    errors = [m for level, m in health() if level == "error"]
    if errors:
        print("orca: fix the harness first:\n  " + "\n  ".join(errors))
        return 1
    value = lambda flag: argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    agents = dict(pair.split("=", 1) for pair in (value("--agents") or conf()["HARNESS_ORCA_AGENTS"]).replace(
        ",", " ").split() if "=" in pair)
    ready = [t for t, _, _ in ready_tasks()]
    tasks = [t for t in (value("--tasks") or "").split(",") if t] or ready
    tasks = [t for t in tasks if t in ready]
    limit = int(value("--parallel")) if (value("--parallel") or "").isdigit() else 2
    if "--here" in argv:
        tasks, limit = tasks[:1], 1
    deps = task_dependencies()
    if not tasks:
        print("orca: no ready task (pending or [WIP], not BLOCKED)")
        return 0
    if "--dry-run" in argv:
        done = task_states(read(TASKS))[1]
        for task in tasks:
            step = next_step(task)
            waits = sorted(set(deps.get(task, [])) - done)
            print("orca: would drive task %s (next: %s%s)%s, agents %s" % (task, step["step"],
                  " by the %s" % step["role"] if step.get("role") else "",
                  ", after %s is done" % ", ".join(waits) if waits else "", agents))
        return 0
    launch = dict(part.strip().split("=", 1) for part in conf()["HARNESS_ORCA_LAUNCH"].split(";") if "=" in part)
    opts = {"run": value("--run"), "agents": agents, "launch": launch, "trust": "--trust" in argv,
            "parallel": limit, "deps": deps, "merge": "--merge" in argv,
            "launch_wait": int(os.environ.get("HARNESS_ORCA_LAUNCH_WAIT", "8")), "here": "--here" in argv, "pr": "--pr" in argv,
            "orca": os.environ.get("HARNESS_ORCA_BIN"),
            "wait_ms": int(value("--wait-ms")) if (value("--wait-ms") or "").isdigit() else 900000,
            "timeout": int(value("--timeout")) if (value("--timeout") or "").isdigit() else 4 * 3600}
    if not orca_lock_acquire():
        print("orca: a backlog run is already going for this repository (pid %s); not starting another"
              % orca_lock_holder())
        return 1
    log_event("orca-start", tasks=tasks, agents=agents)
    lines = []

    def log(line):
        lines.append(line)
        print(line, flush=True)
    try:
        code = coordinator.Coordinator(ROOT, opts, log=log, event=log_event).drive(tasks)
        summary = next((l for l in reversed(lines) if l.startswith("harness orca: run ")), None)
        if summary:
            orca_digest_publish("%s (finished %s)" % (summary, time.strftime("%Y-%m-%d %H:%M")))
    except coordinator.CoordinatorError as exc:
        hint = (" An Orca terminal coordinates one Run at a time, and this one was bound to another. Run harness.py "
                "orca in its own terminal (harness.py orca-nightly opens one)." if "consumer_fenced" in str(exc) else "")
        print("orca: stopped: %s%s" % (exc, hint))
        log_event("orca-error", error=str(exc)[:500])
        return 1
    finally:
        orca_lock_release()
    log_event("orca-end", code=code)
    return code


# --------------------------------------------------------------------------- runner and report
# harness.py run drives tasks unattended: for each ready task it starts a fresh agent session with
# HARNESS_AGENT_CMD (the prompt on stdin), waits, and reads the outcome from 3-TASKS.md. The hooks,
# gates and verify do the enforcing; the runner only sequences, budgets and escalates stalls.

RUN_PROMPT = """You are running unattended: autonomous mode, no user in the loop (AGENTS.md section 7).
Drive Task {task} ("{title}") through the whole pipeline in backbone/8-WORKFLOW.md.
{state}
- Define: if backbone/specs/{task}.md is missing or not ready, have the analyst write it from the task title and
  backbone/, the architect complete Architecture and Skills, and the griller grill it. Answer the griller's
  questions from backbone/ and the knowledge source (if on) as Assumptions; escalate what they cannot answer.
- Approve: python3 scripts/harness/lib/harness.py approve {task}
- Build, judge and record: the tester first when HARNESS_TESTER is on, then the implementer and the judge; after a
  judge fail, the debugger's brief goes to the implementer; then the scribe. Mark the task [x] and commit.
- When anything needs a human, escalate: python3 scripts/harness/lib/harness.py escalate {task} --reason "..."
Stop when the task is [x] and committed, or BLOCKED. Do not start other tasks."""


def ready_tasks(text=None):
    """[(id, title, state)] the runner may work on: a [WIP] task first, then pending ones, never BLOCKED."""
    lines = mask_comments(read(TASKS) if text is None else text).splitlines()
    found = []
    for i, line in enumerate(lines):
        if BLOCKED_NOTE.search(line) or not (WIP_LINE.match(line) or PENDING_LINE.match(line)):
            continue
        task = task_id_at(lines, i)
        if not TASK_REF.search(line):
            continue
        title = re.sub(r"^\s*[-*]\s+\[[^\]]*\]\s*\**Task\s+[A-Za-z0-9._-]*[A-Za-z0-9]:?\s*", "", line)
        title = title.split("**")[0].strip()
        found.append((task, title, "wip" if WIP_LINE.match(line) else "pending"))
    return sorted(found, key=lambda t: t[2] != "wip")


def task_state(task):
    index, line = task_line(task)
    if line is None:
        return "missing"
    if BLOCKED_NOTE.search(line):
        return "blocked"
    if DONE_LINE.match(line):
        return "done"
    return "wip" if WIP_LINE.match(line) else "pending"


def session_result(log_path):
    """The result object an agent log written with --output-format json ends with, else {}."""
    text = read(log_path)
    decoder = json.JSONDecoder()
    for start in reversed([m.start() for m in re.finditer(r"\{", text)]):
        try:
            data, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(data, dict) and ("total_cost_usd" in data or "num_turns" in data):
            return data
    return {}


def jsonl_events(log_path):
    """The JSON objects of a JSONL agent log (codex exec --json, opencode run --format json)."""
    events = []
    for line in read(log_path).splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def find_number(value, key):
    """The first number under `key` anywhere in a JSON value."""
    if isinstance(value, dict):
        if isinstance(value.get(key), (int, float)) and not isinstance(value.get(key), bool):
            return value[key]
        for item in value.values():
            found = find_number(item, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_number(item, key)
            if found is not None:
                return found
    return None


def session_usage(log_path):
    """(cost in USD, turns) from an agent log: Claude Code's --output-format json, Codex's exec --json (turns only,
    it reports tokens and no price) or OpenCode's run --format json (cost per step). (None, None) if unknown."""
    data = session_result(log_path)
    if data:
        return data.get("total_cost_usd"), data.get("num_turns")
    events = jsonl_events(log_path)
    codex_turns = sum(1 for e in events if e.get("type") == "turn.completed")
    if codex_turns:
        return None, codex_turns
    steps = [e for e in events if e.get("type") in ("step_finish", "step-finish")]
    if steps:
        return round(sum(find_number(e, "cost") or 0 for e in steps), 6), len(steps)
    return None, None


def agent_start_failure(log_path, code):
    """The agent's error when a session failed without doing any work (not logged in, bad API key), else None.
    Retrying or moving to the next task cannot help then, so the run stops instead of escalating every task."""
    if code in (0, None):
        return None
    data = session_result(log_path)
    if data:
        if not data.get("is_error") or data.get("total_cost_usd") not in (0, 0.0):
            return None
        return str(data.get("result") or "exit %s" % code)
    events = jsonl_events(log_path)
    worked = any(e.get("type") in ("turn.completed", "step_finish", "step-finish", "tool_use") for e in events)
    errors = [e for e in events if e.get("type") in ("error", "turn.failed")]
    if worked or not errors:
        return None
    error = errors[0]
    message = error.get("message") or (error.get("error") or {}).get("message") if isinstance(error.get("error"), dict) \
        else error.get("message") or error.get("error")
    return str(message or "exit %s" % code)[:300]


def run_worktrees(queue, open_prs):
    """Run each task in its own worktree on branch harness/task-<id>, from the current HEAD."""
    common = git("rev-parse", "--git-common-dir").strip()
    base_dir = Path(common) if os.path.isabs(common) else ROOT / common
    base_branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    summary = []
    for task, title, _ in queue:
        branch = "harness/task-%s" % slug(task)
        if git("rev-parse", "--verify", "-q", "refs/heads/%s" % branch).strip():
            print("run: task %s already has branch %s; skipped (delete the branch to retry)" % (task, branch))
            summary.append((task, "skipped"))
            continue
        if halt_file().exists():
            print("run: halted by %s" % halt_file())
            break
        tree = base_dir / "harness" / "worktrees" / slug(task)
        added = subprocess.run(["git", "worktree", "add", "-q", "-b", branch, str(tree), "HEAD"], cwd=str(ROOT),
                               capture_output=True, text=True)
        if added.returncode != 0:
            print("run: could not create a worktree for task %s: %s" % (task, added.stderr.strip()))
            summary.append((task, "error"))
            continue
        child = subprocess.run([sys.executable, str(tree / "scripts/harness/lib/harness.py"), "run", "--only", task],
                               cwd=str(tree), capture_output=True, text=True)
        sys.stdout.write(child.stdout)
        m = re.search(r"^run: (\S+)\s+task %s$" % re.escape(task), child.stdout, re.M)
        outcome = m.group(1) if m else "error"
        if outcome == "agent-failed":
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(ROOT), capture_output=True)
            git("branch", "-D", branch)
            summary.append((task, outcome))
            break
        if open_prs and outcome in ("done", "blocked", "escalated"):
            dirty = git_in(tree, "status", "--porcelain").strip()
            if dirty:
                git_in(tree, "add", "-A")
                subprocess.run(["git", "commit", "-qm", "chore(harness): record escalation for task %s" % task],
                               cwd=str(tree), capture_output=True, text=True, env=dict(os.environ, HARNESS_VERIFY="block"))
            pushed = subprocess.run(["git", "push", "-q", "-u", "origin", branch], cwd=str(tree),
                                    capture_output=True, text=True)
            if pushed.returncode == 0 and shutil.which("gh"):
                state = "ready for review" if outcome == "done" else "BLOCKED, see backbone/escalations.md"
                pr = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", base_branch, "--title",
                                     "Task %s: %s" % (task, title), "--body",
                                     "Opened by harness.py run: task %s is %s.\n\nThe harness-verify check "
                                     "re-checks the gates." % (task, state)],
                                    cwd=str(tree), capture_output=True, text=True)
                print("run: task %s: %s" % (task, pr.stdout.strip() or pr.stderr.strip()))
                log_event("run-pr", task=task, branch=branch, url=pr.stdout.strip())
            else:
                print("run: task %s: branch %s kept locally (push failed or gh missing)" % (task, branch))
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(ROOT), capture_output=True)
        summary.append((task, outcome))
    for task, outcome in summary:
        print("run: %-12s task %s" % (outcome, task))
    return 0 if all(o in ("done", "blocked", "escalated", "skipped") for _, o in summary) else 1


def git_in(tree, *args):
    result = subprocess.run(["git"] + list(args), cwd=str(tree), capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def workspace_trusted(path=None):
    """True/False from ~/.claude.json (this folder or a parent accepted the trust dialog), None if unknown."""
    config = Path(os.path.expanduser("~/.claude.json"))
    try:
        projects = json.loads(config.read_text(encoding="utf-8")).get("projects") or {}
    except (OSError, ValueError):
        return None
    folder = Path(path or ROOT).resolve()
    candidates = [folder] + list(folder.parents)
    for candidate in candidates:
        for key in {str(candidate), str(candidate).replace("/private/", "/", 1)}:
            if (projects.get(key) or {}).get("hasTrustDialogAccepted") is True:
                return True
    return False


def knowledge_server_registered():
    """True/False: an MCP server named "knowledge" is in ~/.claude.json (user scope, or local scope for this
    folder) or in .mcp.json; None if ~/.claude.json can't be read."""
    if "knowledge" in ((json_file(ROOT / ".mcp.json") or {}).get("mcpServers") or {}):
        return True
    config = Path(os.path.expanduser("~/.claude.json"))
    data = json_file(config) if config.exists() else {}
    if data is None:
        return None
    if "knowledge" in (data.get("mcpServers") or {}):
        return True
    folder = ROOT.resolve()
    for key in {str(folder), str(folder).replace("/private/", "/", 1)}:
        if "knowledge" in (((data.get("projects") or {}).get(key) or {}).get("mcpServers") or {}):
            return True
    return False


def json_file(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def agent_cli(command):
    """claude | codex | opencode | other: which agent CLI a HARNESS_*_CMD starts."""
    words = re.findall(r"[^\s'\"]+", command or "")
    first = next((w for w in words if "=" not in w and w not in ("env", "caffeinate", "-i", "nice")), "")
    name = os.path.basename(first)
    return name if name in ("claude", "codex", "opencode") else "other"


def trust_problem(command=None):
    if os.environ.get("HARNESS_SKIP_TRUST_CHECK") == "1":
        return None
    command = command if command is not None else conf()["HARNESS_AGENT_CMD"]
    cli = agent_cli(command)
    if cli == "codex":
        if "--dangerously-bypass-hook-trust" in command:
            return None
        return ("Codex skips project hooks nobody has trusted (and re-skips each one after it changes), so the "
                "harness hooks in .codex/hooks.json may not run in `codex exec`. Run unattended Codex with "
                "--dangerously-bypass-hook-trust inside a sandbox, or trust the hooks once with /hooks in Codex and "
                "set HARNESS_SKIP_TRUST_CHECK=1.")
    if cli != "claude":
        return None   # OpenCode loads .opencode/plugins/ without a trust step
    trusted = workspace_trusted()
    if trusted:
        return None
    return ("Claude Code has not trusted %s, and in an untrusted folder `claude -p` ignores the project's hooks, "
            "agent hooks and permissions, so the harness would not run at all. Run Claude Code here once "
            "interactively and accept the trust dialog, or set projects[\"%s\"].hasTrustDialogAccepted to true "
            "in ~/.claude.json (CI does this in the workflow). HARNESS_SKIP_TRUST_CHECK=1 skips this check for "
            "agent commands other than Claude Code." % (ROOT, ROOT))


def run_agent(prompt, log_path, timeout):
    command = conf()["HARNESS_AGENT_CMD"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(command, shell=True, cwd=str(ROOT), input=prompt, stdout=log,
                                    stderr=subprocess.STDOUT, text=True, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = None
    return code, round(time.time() - started, 1)


def run_command(argv):
    max_tasks = 0
    dry_run = "--dry-run" in argv
    only = argv[argv.index("--only") + 1] if "--only" in argv and argv.index("--only") + 1 < len(argv) else None
    if "--max-tasks" in argv:
        i = argv.index("--max-tasks")
        max_tasks = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 0
    values = conf()
    if not autonomous():
        print("run: needs HARNESS_AUTONOMY=\"autonomous\" (set by the user in backbone/harness.conf)")
        return 1
    errors = [m for level, m in health() if level == "error"]
    if errors:
        print("run: fix the harness first:\n  " + "\n  ".join(errors))
        return 1
    problem = trust_problem() if not dry_run else None
    if problem:
        print("run: " + problem)
        return 1
    queue = ready_tasks()
    if only:
        queue = [t for t in queue if t[0] == only]
    if max_tasks:
        queue = queue[:max_tasks]
    if "--worktree" in argv and not dry_run:
        return run_worktrees(queue, "--pr" in argv)
    if dry_run:
        for task, title, state in queue:
            print("run: would %s task %s: %s" % ("resume" if state == "wip" else "start", task, title))
        return 0
    timeout = int(values["HARNESS_RUN_TASK_TIMEOUT"]) if values["HARNESS_RUN_TASK_TIMEOUT"].isdigit() else 3600
    attempts = int(values["HARNESS_RUN_ATTEMPTS"]) if values["HARNESS_RUN_ATTEMPTS"].isdigit() else 2
    run_dir = events_file().parent / "runs" / time.strftime("%Y%m%d-%H%M%S")
    log_event("run-start", tasks=[t for t, _, _ in queue])
    summary = []
    max_cost = float(values["HARNESS_RUN_MAX_COST"]) if re.match(r"^\d+(\.\d+)?$", values["HARNESS_RUN_MAX_COST"]) else None
    spent = 0.0
    for task, title, state in queue:
        if max_cost is not None and spent >= max_cost:
            print("run: budget reached ($%.2f of $%.2f); stopping before task %s" % (spent, max_cost, task))
            log_event("run-budget", spent=spent, limit=max_cost)
            summary.append((task, "budget"))
            break
        outcome = None
        for attempt in range(1, attempts + 1):
            if halt_file().exists():
                print("run: halted by %s" % halt_file())
                log_event("run-halt")
                outcome = "halted"
                break
            resume = ("The task is already [WIP]: resume it." if task_state(task) == "wip"
                      else "The task is pending.")
            prompt = RUN_PROMPT.format(task=task, title=title, state=resume)
            log_path = run_dir / ("%s-%d.log" % (slug(task), attempt))
            code, seconds = run_agent(prompt, log_path, timeout)
            failure = agent_start_failure(log_path, code)
            if failure:
                print("run: the agent could not start (%s); stopping the run. Log: %s" % (failure, log_path))
                log_event("run-agent-failed", task=task, error=failure)
                outcome = "agent-failed"
                break
            cost, turns = session_usage(log_path)
            spent += cost or 0.0
            if halt_file().exists():
                print("run: halted by %s during task %s" % (halt_file(), task))
                log_event("run-halt", task=task)
                outcome = "halted"
                break
            outcome = task_state(task)
            dirty = bool(git("status", "--porcelain").strip())
            log_event("run-attempt", task=task, attempt=attempt, exit=code, seconds=seconds, state=outcome,
                      uncommitted=dirty, cost_usd=cost, turns=turns)
            print("run: task %s attempt %d: %s (%ss, exit %s%s)" % (task, attempt, outcome, seconds, code,
                                                                   ", uncommitted changes" if dirty else ""))
            if outcome == "done" and not dirty:
                break
            if outcome == "blocked":
                break
            if outcome == "done" and dirty:
                outcome = "done-uncommitted"
        else:
            if outcome not in ("done", "blocked", "agent-failed"):
                escalate(task, "runner", "no resolution after %d agent session(s) (last state: %s; logs: %s)"
                         % (attempts, outcome, run_dir), "a look at the run logs and the task's state")
                outcome = "escalated"
        summary.append((task, outcome))
        if outcome in ("halted", "agent-failed"):
            break
    log_event("run-end", summary=summary)
    for task, outcome in summary:
        print("run: %-12s task %s" % (outcome, task))
    return 0 if all(o in ("done", "blocked", "escalated") for _, o in summary) else 1


CI_JUDGE_PROMPT = """You are the judge, running in CI on a pull request. Task {task} is marked [x] in
backbone/3-TASKS.md. Judge task {task} against backbone/specs/{task}.md exactly as your instructions say, on the
code as committed (ignore the [WIP] lookup: the task is {task}). Do not modify anything. End with the verdict JSON."""


def ci_judge_command(argv):
    """CI: re-judge every task finished in a range with an independent judge session."""
    if argv[:1] != ["--range"] or len(argv) < 2:
        sys.stderr.write("usage: harness.py ci-judge --range <base>..<tip>\n")
        return 64
    base, _, tip = argv[1].partition("..")
    tip = tip or "HEAD"
    tasks_rel = TASKS.relative_to(ROOT).as_posix()
    finished = sorted(task_states(show(tip, tasks_rel))[1] - task_states(show(base, tasks_rel))[1])
    if not finished:
        print("ci-judge: no task finished in %s" % argv[1])
        return 0
    problem = trust_problem(conf()["HARNESS_CI_JUDGE_CMD"])
    if problem:
        print("ci-judge: " + problem)
        return 1
    command = conf()["HARNESS_CI_JUDGE_CMD"]
    timeout = int(conf()["HARNESS_RUN_TASK_TIMEOUT"]) if conf()["HARNESS_RUN_TASK_TIMEOUT"].isdigit() else 3600
    problems = []
    for task in finished:
        try:
            result = subprocess.run(command, shell=True, cwd=str(ROOT), input=CI_JUDGE_PROMPT.format(task=task),
                                    capture_output=True, text=True, timeout=timeout)
            output = result.stdout
        except subprocess.TimeoutExpired:
            problems.append("task %s: the CI judge timed out" % task)
            continue
        try:
            wrapped = json.loads(output)
            output = wrapped.get("result", output) if isinstance(wrapped, dict) else output
        except ValueError:
            pass
        report = extract_report(output)
        if report is None:
            problems.append("task %s: the CI judge returned no verdict JSON" % task)
            continue
        report.pop("test_run", None)
        report["test_run"] = run_tests()
        verdict, reasons = effective_judge(task, report)
        log_event("ci-judge", task=task, verdict=verdict, claimed=report.get("verdict"), reasons=reasons[:10])
        print("ci-judge: task %s: %s%s" % (task, verdict.upper(), " (%s)" % "; ".join(reasons)[:400] if reasons else ""))
        if verdict != "pass":
            problems.append("task %s: the independent judge does not confirm the pass: %s" % (task, "; ".join(reasons)[:400]))
    for problem in problems:
        print("ci-judge: %s" % problem)
    return 1 if problems else 0


def protection_payload(current, contexts):
    """The PUT body that adds contexts to a branch's existing protection without weakening any of it."""
    checks = current.get("required_status_checks") or {}
    kept_checks = [{"context": c["context"], **({"app_id": c["app_id"]} if c.get("app_id") is not None else {})}
                   for c in checks.get("checks") or [] if c.get("context")]
    named = {c["context"] for c in kept_checks}
    kept_checks += [{"context": c} for c in checks.get("contexts") or [] if c not in named]
    named |= set(checks.get("contexts") or [])
    kept_checks += [{"context": c} for c in contexts if c not in named]
    reviews = current.get("required_pull_request_reviews")
    kept_reviews = None
    if reviews:
        kept_reviews = {k: reviews[k] for k in ("dismiss_stale_reviews", "require_code_owner_reviews",
                                                "required_approving_review_count", "require_last_push_approval")
                        if k in reviews}
        for key in ("dismissal_restrictions", "bypass_pull_request_allowances"):
            if isinstance(reviews.get(key), dict):
                kept_reviews[key] = {"users": [u.get("login") for u in reviews[key].get("users") or []],
                                     "teams": [t.get("slug") for t in reviews[key].get("teams") or []],
                                     "apps": [a.get("slug") for a in reviews[key].get("apps") or []]}
    restrictions = current.get("restrictions")
    kept_restrictions = None
    if restrictions:
        kept_restrictions = {"users": [u.get("login") for u in restrictions.get("users") or []],
                             "teams": [t.get("slug") for t in restrictions.get("teams") or []],
                             "apps": [a.get("slug") for a in restrictions.get("apps") or []]}
    payload = {"required_status_checks": {"strict": True if not checks else bool(checks.get("strict", True)),
                                          "checks": kept_checks},
               "enforce_admins": bool((current.get("enforce_admins") or {}).get("enabled")),
               "required_pull_request_reviews": kept_reviews, "restrictions": kept_restrictions}
    for key in ("required_linear_history", "allow_force_pushes", "allow_deletions",
                "required_conversation_resolution", "block_creations", "lock_branch"):
        if isinstance(current.get(key), dict) and "enabled" in current[key]:
            payload[key] = bool(current[key]["enabled"])
    return payload


def ci_protect_command(argv):
    """Make the harness-verify check required on a branch and create the approval label (needs gh)."""
    contexts = ["verify"] + (["judge"] if "--with-judge" in argv else [])
    repo = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"], cwd=str(ROOT),
                          capture_output=True, text=True) if shutil.which("gh") else None
    try:
        info = json.loads(repo.stdout) if repo is not None and repo.returncode == 0 else {}
    except ValueError:
        info = {}
    name = info.get("nameWithOwner") or "<owner>/<repo>"
    default = (info.get("defaultBranchRef") or {}).get("name") or "main"
    branch = argv[argv.index("--branch") + 1] if "--branch" in argv and argv.index("--branch") + 1 < len(argv) else default
    endpoint = "repos/%s/branches/%s/protection" % (name, branch)
    current = {}
    if not name.startswith("<"):
        got = subprocess.run(["gh", "api", endpoint], cwd=str(ROOT), capture_output=True, text=True)
        if got.returncode != 0:
            if "Branch not protected" not in got.stdout + got.stderr:
                print("ci-protect: can't read %s's current protection, so nothing was changed: %s"
                      % (branch, (got.stderr or got.stdout).strip()[:300]))
                return 1
        else:
            try:
                current = json.loads(got.stdout)
            except ValueError:
                print("ci-protect: %s's current protection isn't JSON, so nothing was changed" % branch)
                return 1
    payload = protection_payload(current, contexts)
    if "--dry-run" in argv or name.startswith("<"):
        print("ci-protect: would PUT %s\n%s" % (endpoint, json.dumps(payload, indent=2)))
        print("ci-protect: would create the label harness-change-approved")
        return 0 if "--dry-run" in argv else 1
    put = subprocess.run(["gh", "api", "-X", "PUT", endpoint, "--input", "-"], cwd=str(ROOT), input=json.dumps(payload),
                         capture_output=True, text=True)
    if put.returncode != 0:
        print("ci-protect: branch protection failed: %s" % (put.stderr.strip() or put.stdout.strip()))
        return 1
    subprocess.run(["gh", "label", "create", "harness-change-approved", "--force", "--color", "B60205",
                    "--description", "A maintainer approved changes to the harness or its user-only settings"],
                   cwd=str(ROOT), capture_output=True, text=True)
    print("ci-protect: %s now requires %s; label harness-change-approved created. Restrict who can label pull "
          "requests (triage access)." % (branch, ", ".join(contexts)))
    return 0


def report_command(argv):
    days = (int(argv[argv.index("--days") + 1]) if "--days" in argv and argv.index("--days") + 1 < len(argv)
            and argv[argv.index("--days") + 1].isdigit() else 7)
    cutoff = time.time() - days * 86400
    events = []
    for line in read(events_file()).splitlines():
        try:
            event = json.loads(line)
            stamp = time.mktime(time.strptime(event["at"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, KeyError):
            continue
        if stamp >= cutoff:
            events.append(event)
    count = lambda kind: sum(1 for e in events if e.get("kind") == kind)
    verdicts = [e for e in events if e.get("kind") == "verdict"]
    judged = [e for e in verdicts if e.get("agent") == "judge"]
    passes = sum(1 for e in judged if e.get("verdict") == "pass")
    overturned = sum(1 for e in verdicts if e.get("claimed") == "pass" and e.get("verdict") != "pass")
    attempts = [e for e in events if e.get("kind") == "run-attempt"]
    done = sorted({e.get("task") for e in attempts if e.get("state") == "done"})
    merged = sorted({e.get("task") for e in events if e.get("kind") == "orca-merge"})
    workers = [e for e in events if e.get("kind") == "orca-worker"]
    failed_workers = sum(1 for e in workers if e.get("outcome") != "succeeded")
    reasons = {}
    for e in events:
        if e.get("kind") in ("block", "verify"):
            key = re.sub(r"\s+", " ", e.get("reason", ""))[:70]
            reasons[key] = reasons.get(key, 0) + 1
    if "--json" in argv:
        print(json.dumps({"days": days, "events": len(events), "tasks_finished": done,
                          "judge_verdicts": len(judged), "judge_passes": passes, "overturned_passes": overturned,
                          "escalations": count("escalation"), "open_escalations": len(open_escalations()),
                          "policy_approvals": count("approval"), "blocked_tool_calls": count("block"),
                          "verify_refusals": count("verify"), "out_of_band_changes": count("tamper"),
                          "knowledge_lookups": count("knowledge"), "orca_merged": merged,
                          "orca_workers": len(workers), "orca_failed_workers": failed_workers,
                          "orca_integrations": count("orca-integrate"),
                          "cost_usd": round(sum(e.get("cost_usd") or 0 for e in attempts), 4),
                          "block_reasons": reasons}, indent=2, sort_keys=True))
        return 0
    print("harness report, last %d day(s), %d event(s)" % (days, len(events)))
    print("  tasks finished by the runner: %d %s" % (len(done), ", ".join(done)))
    print("  judge verdicts: %d (%d pass, %d fail); claimed passes overturned by the harness: %d"
          % (len(judged), passes, len(judged) - passes, overturned))
    print("  escalations: %d (open now: %d); policy approvals: %d" % (count("escalation"), len(open_escalations()),
                                                                       count("approval")))
    print("  blocked tool calls: %d; commits refused by verify: %d; out-of-band changes: %d"
          % (count("block"), count("verify"), count("tamper")))
    if workers or merged:
        print("  orca: %d task(s) merged %s; %d worker(s), %d not succeeded; %d integration(s)"
              % (len(merged), ", ".join(merged), len(workers), failed_workers, count("orca-integrate")))
    print("  knowledge source lookups: %d" % count("knowledge"))
    print("  agent cost: $%.2f over %d session(s)" % (sum(e.get("cost_usd") or 0 for e in attempts), len(attempts)))
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:8]:
        print("    %4d  %s" % (n, reason))
    return 0


# --------------------------------------------------------------------------- git hooks

def git_pre_commit():
    rules, errors = load_rules()
    if errors:
        sys.stderr.write("harness: fix guardrail rules first:\n  %s\n" % "\n  ".join(errors))
        return 1
    blocked, warned = [], []
    staged = [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0") if f]
    for name in staged:
        diff = git("diff", "--cached", "-U0", "--no-color", "--", name)
        added = "\n".join(line[1:] for line in diff.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        if not added:
            continue
        for rule, matched in check_text(rules, name, added):
            (blocked if rule.severity == "block" else warned).append((name, rule, matched))
    for label, items in (("warning", warned), ("BLOCKED", blocked)):
        for name, rule, matched in items:
            sys.stderr.write("harness %s: %s\n%s\n" % (label, name, describe([(rule, matched)])))
    if blocked:
        sys.stderr.write("harness: commit blocked by guardrail rules.\n")
        return 1
    if conf()["HARNESS_VERIFY"] != "off":
        problems = verify_staged()
        for problem in problems:
            log_event("verify", reason=problem.splitlines()[0][:200])
        if problems:
            sys.stderr.write("harness: commit blocked; the staged state breaks the harness gates:\n%s\n"
                             "The user can commit a deliberate exception with HARNESS_VERIFY=off.\n"
                             % "\n".join("  - " + p for p in problems))
            return 1
    build = conf()["HARNESS_BUILD_CMD"]
    if build and os.environ.get("SKIP_BUILD") != "1":
        sys.stderr.write("harness: build check: %s  (skip once with SKIP_BUILD=1)\n" % build)
        if subprocess.call(build, shell=True, cwd=str(ROOT)) != 0:
            sys.stderr.write("harness: build failed; commit blocked.\n")
            return 1
    return 0


def git_commit_msg(message_file):
    values = conf()
    lines = [line for line in read(message_file).splitlines() if not line.startswith("#")]
    subject = next((line for line in lines if line.strip()), "")
    if re.match(r"^(Merge|Revert|fixup!|squash!|amend!) ", subject):
        return 0
    types = values["HARNESS_COMMIT_TYPES"]
    max_len = int(values["HARNESS_SUBJECT_MAX"] or 72)
    if not re.match(r"^(%s)(\([a-z0-9][a-z0-9._/-]*\))?!?: \S" % types, subject):
        sys.stderr.write("harness: commit subject must follow Conventional Commits:\n"
                         "  got:      %s\n  expected: <type>(<scope>): <description>\n  types:    %s\n"
                         % (subject, types.replace("|", " ")))
        return 1
    if len(subject) > max_len:
        sys.stderr.write("harness: commit subject is %d characters; the limit is %d.\n" % (len(subject), max_len))
        return 1
    scope_warning(subject, values)
    commit_decision(subject, lines, values)
    return 0


def decision_log():
    common = git("rev-parse", "--git-common-dir").strip() or ".git"
    base = Path(common) if os.path.isabs(common) else ROOT / common
    return base / "harness" / "decisions.jsonl"


def decision_authorised(values):
    """(ok, reason): providers that send project data anywhere need an Accepted ADR that names them."""
    provider = values["HARNESS_DECISION_PROVIDER"]
    if provider == "none" or values["HARNESS_DECISION_MODE"] == "off":
        return False, "off"
    if provider not in decisions.PROVIDERS:
        return False, "unknown provider %s" % provider
    adr = values["HARNESS_DECISION_ADR"]
    path = adr_file(adr) if adr else None
    if path is None:
        return False, "HARNESS_DECISION_ADR must name the ADR that approved the %s decision provider" % provider
    text = read(path)
    if not adr_status(text).lower().startswith("accepted"):
        return False, "%s is not Accepted" % adr
    if not re.search(r"\b%s\b" % re.escape(provider), text, re.I):
        return False, "%s does not mention the %s provider" % (adr, provider)
    return True, ""


def run_decision(name, state):
    values = conf()
    ok, _ = decision_authorised(values)
    if not ok:
        return None, []
    try:
        definitions = decisions.load_definitions(str(DECISIONS_FILE))
    except decisions.DecisionError:
        return None, []
    return decisions.decide(name, state, definitions, values, str(decision_log()))


def commit_state(subject, lines):
    """Deterministic snapshot of a commit for the commit-message decision (no model work)."""
    files = []
    for row in git("diff", "--cached", "--numstat").splitlines():
        parts = row.split("\t")
        if len(parts) == 3:
            files.append({"path": parts[2], "added": parts[0], "removed": parts[1]})
    excerpt = git("diff", "--cached", "-U2", "--no-color")
    body = "\n".join(l for l in lines if l.strip() and l != subject).strip()
    return {
        "message": {"subject": subject, "body": body[:2000]},
        "files": files[:60],
        "file_count": len(files),
        "diff_excerpt": excerpt[:8000] + ("\n[... truncated]" if len(excerpt) > 8000 else ""),
        "task_in_progress": wip_task_ids()[:1],
    }


def commit_decision(subject, lines, values):
    ok, _ = decision_authorised(values)
    if not ok:
        return
    _, notes = run_decision("commit-message", commit_state(subject, lines))
    for note in notes:
        sys.stderr.write("harness decision (advisory): %s\n" % note)


def scope_warning(subject, values):
    """Warn (never block) when a commit scope names no path segment of any staged file."""
    m = re.match(r"^\w+\(([^)]+)\)", subject)
    if values["HARNESS_SCOPE_CHECK"] == "off" or not m:
        return
    scope = m.group(1)
    if re.fullmatch(values["HARNESS_CROSS_SCOPES"], scope):
        return
    staged = [f for f in git("diff", "--cached", "--name-only").splitlines() if f]
    segments = {part.lower() for name in staged for part in re.split(r"[/._-]", name) if part}
    if staged and not any(part in segments for part in re.split(r"[/._-]", scope.lower()) if part):
        sys.stderr.write("harness warning: scope '%s' matches no path of the %d staged file(s) (e.g. %s). Use the "
                         "module or layer that changed, or no scope for cross-cutting changes.\n"
                         % (scope, len(staged), ", ".join(staged[:3])))


# --------------------------------------------------------------------------- agent CLIs
# The gates are written against Claude Code's hook input. Codex sends almost the same shape (its file edits arrive
# as one apply_patch call with the raw patch text); the OpenCode plugin (.opencode/plugins/harness.js) translates
# its tool calls before calling this script. normalize_hook() makes all of them look like Claude Code's.

HOOK_SOURCES = ("claude", "codex", "opencode")
HOOK_SOURCE = "claude"
EMITTED = False


def session_role():
    """The pipeline role a whole session plays (HARNESS_ROLE, set by whoever starts the session), or None."""
    role = os.environ.get("HARNESS_ROLE", "").strip()
    return role if role in PIPELINE_AGENTS else None


def normalize_hook(data, source):
    data = dict(data)
    agent = str(data.get("agent_type") or "").split(":")[-1]
    if agent not in PIPELINE_AGENTS:
        agent = ""
        if source != "claude":
            # OpenCode's primary agents (build, plan) and Codex's built-ins are the main session, not a role.
            data.pop("agent_type", None)
            data.pop("agent_id", None)
    role = agent or session_role()
    if role:
        data["agent_type"] = data.get("agent_type") or role
        data["agent_id"] = data.get("agent_id") or "role-%s" % role
        data["harness_role"] = role
    return data


def parse_patch(text):
    """Codex/OpenCode patch grammar (*** Begin Patch ... *** End Patch) -> [{op, path, move_to, content, hunks}]."""
    ops, current, hunk = [], None, None
    for line in (text or "").splitlines():
        header = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", line)
        if header:
            current = {"op": header.group(1).lower(), "path": header.group(2), "move_to": None, "content": [],
                       "hunks": []}
            ops.append(current)
            hunk = None
            continue
        if current is None or line.startswith("*** End Patch") or line.startswith("*** Begin Patch"):
            continue
        move = re.match(r"^\*\*\* Move to: (.+?)\s*$", line)
        if move:
            current["move_to"] = move.group(1)
            continue
        if line.startswith("*** End of File"):
            continue
        if current["op"] == "add":
            if line.startswith("+"):
                current["content"].append(line[1:])
            continue
        if current["op"] == "update":
            if line.startswith("@@") or hunk is None:
                hunk = {"old": [], "new": []}
                current["hunks"].append(hunk)
                if line.startswith("@@"):
                    continue
            if line.startswith("-"):
                hunk["old"].append(line[1:])
            elif line.startswith("+"):
                hunk["new"].append(line[1:])
            else:
                kept = line[1:] if line.startswith(" ") else line
                hunk["old"].append(kept)
                hunk["new"].append(kept)
    return ops


def patch_calls(command):
    """One apply_patch call as the Write / MultiEdit calls the gates understand (a delete writes empty content)."""
    calls = []
    for op in parse_patch(command):
        if op["op"] == "add":
            calls.append(("Write", {"file_path": op["path"], "content": "\n".join(op["content"]) + "\n"}))
        elif op["op"] == "delete":
            calls.append(("Write", {"file_path": op["path"], "content": ""}))
        else:
            edits = [{"old_string": "\n".join(h["old"]), "new_string": "\n".join(h["new"])}
                     for h in op["hunks"] if h["old"] or h["new"]]
            if op["move_to"]:
                calls.append(("Write", {"file_path": op["move_to"],
                                        "content": resulting_text("MultiEdit", {"edits": edits}, op["path"])}))
                calls.append(("Write", {"file_path": op["path"], "content": ""}))
            else:
                calls.append(("MultiEdit", {"file_path": op["path"], "edits": edits}))
    return calls


def hook_subagent_stop(data):
    """SubagentStop (Codex) / the subagent tool's result (OpenCode): run the role's recorder."""
    agent = str(data.get("agent_type") or "").split(":")[-1]
    recorder = ROLE_RECORDERS.get(agent)
    if recorder:
        recorder(data)


def acceptance_files(task):
    """{AC id: [acceptance test files mentioning it]} for task (files matching HARNESS_ACCEPTANCE_PATHS)."""
    try:
        acceptance = re.compile(conf()["HARNESS_ACCEPTANCE_PATHS"])
    except re.error:
        return {}
    return {ac: [f for f in files if acceptance.search(f)] for ac, files in ac_test_references(task).items()
            if any(acceptance.search(f) for f in files)}


def acceptance_fingerprint(task):
    """Hash of every acceptance test file that mentions one of task's AC ids (content and path)."""
    files = sorted({f for names in acceptance_files(task).values() for f in names})
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode("utf-8") + b"\0")
        try:
            digest.update((ROOT / name).read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest() if files else None


def task_for_role(report):
    claimed = re.sub(r"(?i)^task\s+", "", str(report.get("task") or "")).strip()
    candidates = wip_task_ids()
    return claimed if claimed in candidates else (candidates[0] if len(candidates) == 1 else None)


def record_tests(data):
    """The tester's Stop: record which acceptance tests cover which criteria, and fingerprint them."""
    retry = not data.get("stop_hook_active")
    report = extract_report(data.get("last_assistant_message")
                            or last_message_from_transcript(data.get("transcript_path")), "tests")
    if report is None:
        if retry:
            deny("End your final message with the JSON block described in your instructions.")
        return
    task = task_for_role(report)
    if task is None:
        if retry:
            deny("Set \"task\" in the JSON to the [WIP] task you wrote tests for.")
        return
    acs = [ac for ac, _ in spec_items(strip_comments(read(spec_path(task))), "AC", task)]
    covered = acceptance_files(task)
    missing = [ac for ac in acs if ac not in covered]
    if missing and retry:
        deny("No acceptance test file (HARNESS_ACCEPTANCE_PATHS) mentions %s yet. Write a test for each, naming its "
             "AC id, then stop again." % ", ".join(missing))
    history = verdict_history(task, "tests")
    entry = {"fingerprint": acceptance_fingerprint(task), "files": covered, "missing": missing,
             "red": report.get("red"), "problems": report.get("problems") or [],
             "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "summary": report.get("summary")}
    history.append(entry)
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(task, "tests").write_text(json.dumps({"task": task, "kind": "tests", "history": history}, indent=2)
                                           + "\n", encoding="utf-8")
    snapshot_refresh()
    log_event("tests", task=task, criteria=len(covered), missing=missing, red=report.get("red"))
    note = "harness: recorded the acceptance tests for task %s (%d criteria covered%s)." % (
        task, len(covered), "; missing: " + ", ".join(missing) if missing else "")
    if report.get("red") is False:
        note += " They passed before implementation, so they may not prove the new behaviour."
    emit({"systemMessage": note})


def record_debug(data):
    """The debugger's Stop: keep its fix brief next to the judge verdict it diagnosed."""
    report = extract_report(data.get("last_assistant_message")
                            or last_message_from_transcript(data.get("transcript_path")), "root_causes")
    if report is None:
        if not data.get("stop_hook_active"):
            deny("End your final message with the JSON block described in your instructions.")
        return
    task = task_for_role(report)
    if task is None:
        return
    judge = verdict_history(task, "judge")
    history = verdict_history(task, "debug")
    history.append({"code": code_fingerprint(), "judge_at": (judge[-1] if judge else {}).get("at"),
                    "root_causes": report.get("root_causes") or [], "confidence": report.get("confidence"),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "summary": report.get("summary")})
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(task, "debug").write_text(json.dumps({"task": task, "kind": "debug", "history": history}, indent=2)
                                           + "\n", encoding="utf-8")
    snapshot_refresh()
    owners = sorted({str(c.get("owner")) for c in report.get("root_causes") or [] if isinstance(c, dict)})
    log_event("debug", task=task, confidence=report.get("confidence"), owners=owners)


ROLE_RECORDERS = {
    "griller": lambda data: record_verdict(data, "grill"),
    "judge": lambda data: record_verdict(data, "judge"),
    "tester": record_tests,
    "debugger": record_debug,
}


# --------------------------------------------------------------------------- entry point

HOOKS = {
    "session-start": hook_session_start,
    "pre-tool-use": hook_pre_tool_use,
    "post-tool-use": hook_post_tool_use,
    "stop": hook_stop,
    "grill-stop": lambda data: record_verdict(data, "grill"),
    "judge-stop": lambda data: record_verdict(data, "judge"),
    "subagent-stop": hook_subagent_stop,
    "tester-stop": record_tests,
    "debug-stop": record_debug,
}


def read_hook_input():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def hook_budget(name):
    """Fail closed if a gate hook runs out of time, instead of being killed (which would let the call through)."""
    global GIT_TIMEOUT
    budget = int(os.environ.get("HARNESS_HOOK_BUDGET", HOOK_BUDGET)) if str(
        os.environ.get("HARNESS_HOOK_BUDGET", HOOK_BUDGET)).isdigit() else HOOK_BUDGET
    GIT_TIMEOUT = max(1, budget - 5)
    if not hasattr(signal, "SIGALRM"):
        return

    def expired(_signum, _frame):
        if name in FAIL_CLOSED_HOOKS:
            sys.stderr.write("Harness hook ran out of time (%ds; slow git or filesystem). The call is refused to stay "
                             "safe; retry it.\n" % budget)
            os._exit(2)
        os._exit(0)

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(budget)


def main(argv):
    global HOOK_SOURCE
    if argv[1:2] == ["hook"] and "--from" in argv:
        i = argv.index("--from")
        HOOK_SOURCE = argv[i + 1] if i + 1 < len(argv) and argv[i + 1] in HOOK_SOURCES else "claude"
        argv = argv[:i] + argv[i + 2:]
    if argv[1:2] == ["hook"] and len(argv) >= 3 and argv[2] not in ("grill-stop", "judge-stop", "subagent-stop",
                                                                    "tester-stop", "debug-stop"):
        hook_budget(argv[2])   # the verdict recorders run the tests and have their own, longer timeout
    if len(argv) == 3 and argv[1] == "hook" and argv[2] in HOOKS:
        try:
            HOOKS[argv[2]](normalize_hook(read_hook_input(), HOOK_SOURCE))
        finally:
            if HOOK_SOURCE == "codex" and not EMITTED:
                sys.stdout.write("{}\n")   # Codex wants JSON on stdout when a hook exits 0
        return 0
    if len(argv) == 4 and argv[1:3] == ["hook", "agent-guard"]:
        hook_agent_guard(read_hook_input(), argv[3])
        return 0
    if argv[1:] == ["git", "pre-commit"]:
        return git_pre_commit()
    if len(argv) == 4 and argv[1:3] == ["git", "commit-msg"]:
        return git_commit_msg(argv[3])
    if len(argv) == 3 and argv[1] == "spec-check":
        return spec_check(argv[2])
    if argv[1:] == ["doctor"]:
        return doctor()
    if argv[1:2] == ["scan"]:
        return scan_report(quiet="--quiet" in argv[2:])
    if argv[1:] == ["catalog"]:
        return catalog_list()
    if argv[1:2] == ["decisions"]:
        last = int(argv[3]) if len(argv) >= 4 and argv[2] == "--last" and argv[3].isdigit() else 10
        print(decisions.report(str(decision_log()), last))
        return 0
    if argv[1:2] == ["adopt"]:
        return adopt_command(argv[2:])
    if argv[1:2] == ["verify"]:
        return verify_command(argv[2:])
    if len(argv) == 3 and argv[1] == "approve":
        return approve_command(argv[2])
    if argv[1:2] == ["escalate"]:
        return escalate_command(argv[2:])
    if argv[1:] == ["escalations"]:
        return escalations_command()
    if argv[1:2] == ["run"]:
        return run_command(argv[2:])
    if argv[1:2] == ["state"]:
        return state_command(argv[2:])
    if argv[1:2] == ["orca"]:
        return orca_command(argv[2:])
    if argv[1:2] == ["orca-nightly"]:
        return orca_nightly_command(argv[2:])
    if argv[1:2] == ["orca-digest"]:
        return orca_digest_command(argv[2:])
    if argv[1:] == ["adr-number"]:
        print("ADR-%03d" % adr_next())
        return 0
    if argv[1:] == ["test-run"]:
        run = run_tests()
        print(json.dumps(run or {"error": "no HARNESS_TEST_CMD"}))
        return 0 if run and run.get("exit") == 0 else 1
    if argv[1:] == ["snapshot"]:
        # The coordinator's own git operations (an integration merge) change protected files on purpose; refreshing the
        # out-of-band snapshot records them. Refused to agents by the shell gate.
        snapshot_refresh()
        print("snapshot: refreshed")
        return 0
    if argv[1:2] == ["next"]:
        return next_command(argv[2:])
    if argv[1:2] == ["questions"]:
        return questions_command(argv[2:])
    if len(argv) == 3 and argv[1] == "start":
        return start_command(argv[2])
    if len(argv) == 3 and argv[1] == "finish":
        return finish_command(argv[2])
    if argv[1:2] == ["report"]:
        return report_command(argv[2:])
    if argv[1:2] == ["ci-judge"]:
        return ci_judge_command(argv[2:])
    if argv[1:2] == ["ci-protect"]:
        return ci_protect_command(argv[2:])
    if len(argv) == 3 and argv[1] == "risk":
        reasons = risk_reasons(argv[2])
        print("risk %s: %s" % (argv[2], "; ".join(reasons) if reasons else "low"))
        return 1 if reasons else 0
    sys.stderr.write(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
