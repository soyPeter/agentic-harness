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
  harness.py run [--max-tasks N] [--dry-run]                      (autonomous: drive ready tasks unattended)
  harness.py report [--days N]                                    (events: verdicts, escalations, blocks, runs)
  harness.py doctor
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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
PIPELINE_AGENTS = ("analyst", "architect", "griller", "implementer", "judge", "scribe")
USER_ONLY_KEYS = ("HARNESS_SPEC_GATE", "HARNESS_SKILL_GATE", "HARNESS_JUDGE_GATE", "HARNESS_JUDGE_MAX_ROUNDS",
                  "HARNESS_VERIFY", "HARNESS_ORCHESTRATOR_SCOPE",
                  "HARNESS_AUTONOMY", "HARNESS_AUTO_APPROVE", "HARNESS_RISK_TERMS", "HARNESS_RISK_PATHS",
                  "HARNESS_RISK_MAX_FILES", "HARNESS_GRILL_MAX_ROUNDS", "HARNESS_ESCALATE_GH",
                  "HARNESS_AGENT_CMD", "HARNESS_RUN_TASK_TIMEOUT", "HARNESS_RUN_ATTEMPTS",
                  "HARNESS_DECISION_PROVIDER", "HARNESS_DECISION_MODE", "HARNESS_DECISION_ADR",
                  "HARNESS_DECISION_CMD", "HARNESS_DECISION_MODEL", "HARNESS_DECISION_URL")
# Paths an agent may change only through the file tools, where the hooks see the change. Shell writes to
# them are refused: they would skip the gates (task states, approvals, verdicts, settings, skill state).
SHELL_PROTECTED = (r"^backbone(/|$)", r"^scripts/harness(/|$)", r"^\.claude(/|$)", r"^(AGENTS|CLAUDE)\.md$",
                   r"^\.git/(hooks|harness)(/|$)", r"^\.git/config$")
# Harness files whose edits change enforcement; verify refuses commits that change them away from the lock.
ENFORCEMENT_FILES = (r"^scripts/harness/", r"^\.claude/agents/", r"^\.github/workflows/harness-[^/]+\.ya?ml$")
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
    "implementer": ("deny", (r"^backbone/", r"^\.claude/", r"^scripts/harness/", r"^(AGENTS|CLAUDE)\.md$")),
}
SCOPE_HELP = {
    "analyst": "It writes specs (backbone/specs/) and the PRD only.",
    "architect": "It writes ADRs (backbone/adr/), their index, 2-PLANNING.md and the Architecture section of specs.",
    "scribe": "It writes 6-MEMORY.md and ADRs for decisions taken during implementation.",
    "implementer": "It writes code and tests only; backbone/, .claude/ and harness files belong to other roles.",
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
                          r"encrypt\w*|permissions?|roles?|payments?|billing|personal data|PII|GDPR|migrations?|"
                          r"schema changes?|breaking changes?|public API|deletes? (all|every))\b",
    "HARNESS_RISK_PATHS": r"(?i)(^|/)(auth|security|migrations?|db/migration|infra|deploy|\.github)/|openapi|swagger"
                          r"|Dockerfile|(^|/)(pom\.xml|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|package\.json|"
                          r"go\.mod|Cargo\.toml|requirements[^/]*\.txt|pyproject\.toml)$",
    "HARNESS_RISK_MAX_FILES": "20",
    "HARNESS_GRILL_MAX_ROUNDS": "3",
    "HARNESS_ESCALATE_GH": "off",
    "HARNESS_AGENT_CMD": "claude -p --permission-mode acceptEdits",
    "HARNESS_RUN_TASK_TIMEOUT": "3600",
    "HARNESS_RUN_ATTEMPTS": "2",
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


def git(*args):
    result = subprocess.run(["git"] + list(args), cwd=str(ROOT), capture_output=True, text=True)
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

def wip_tasks(text=None):
    text = read(TASKS) if text is None else text
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
    text = read(TASKS) if text is None else text
    lines = text.splitlines()
    return [task_id_at(lines, i) for i, line in enumerate(lines) if WIP_LINE.match(line)]


def finished_tasks(before, after):
    """Ids of [WIP] tasks this edit takes out of progress, other than by reverting them to
    '- [ ]' (abandoning). Marking [x], rewording or deleting all count as finishing."""
    after_lines = after.splitlines()
    pending = {PENDING_LINE.sub("", line).strip() for line in after_lines if PENDING_LINE.match(line)}
    lines = before.splitlines()
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
            if any(w.endswith("harness.py") for w in words[1:3]) and "run" in words[2:4]:
                found.append("harness.py run starts agent sessions; only the user (or CI) runs it.")
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


def extract_report(message):
    """The agent's verdict: the last JSON object in the message that has a 'verdict' key."""
    if not message:
        return None
    for block in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", message, re.S)):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and "verdict" in data:
            return data
    decoder = json.JSONDecoder()
    for start in reversed([m.start() for m in re.finditer(r"\{", message)]):
        try:
            data, _ = decoder.raw_decode(message[start:])
        except ValueError:
            continue
        if isinstance(data, dict) and "verdict" in data:
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
    reasons.extend("spec: " + problem for problem in validate_spec(task))
    return ("pass" if not reasons else "fail"), reasons


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
    if kind == "grill":
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
              reasons=reasons[:10])
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(task, kind).write_text(json.dumps({"task": task, "kind": kind, "history": history}, indent=2) + "\n",
                                        encoding="utf-8")
    note = "harness: %s verdict for task %s: %s" % (agent_name, task, verdict.upper())
    if verdict == "fail":
        note += " (%s)" % "; ".join(reasons)[:500]
        values = conf()
        key = "HARNESS_JUDGE_MAX_ROUNDS" if kind == "judge" else "HARNESS_GRILL_MAX_ROUNDS"
        limit = int(values[key]) if values[key].isdigit() else 2
        if autonomous() and consecutive_fails(history) >= limit:
            escalate(task, "%s failed %d times" % (agent_name, consecutive_fails(history)), "; ".join(reasons),
                     "the user's decision on the findings")
            note += ". Escalated after %d failed rounds: the task is BLOCKED (backbone/escalations.md); " \
                    "continue with another task." % consecutive_fails(history)
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
    """(index, line) of task's line in 3-TASKS.md, or (None, None)."""
    lines = (read(TASKS) if text is None else text).splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and task_id_at(lines, i) == task:
            return i, line
    return None, None


def blocked_tasks(text):
    lines = (text or "").splitlines()
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
    body = without_approval(strip_comments(text))
    reasons = []
    terms = re.compile(values["HARNESS_RISK_TERMS"])
    paths = re.compile(values["HARNESS_RISK_PATHS"])
    hits = sorted({m.group(0).lower() for m in terms.finditer(body)})
    if hits:
        reasons.append("the spec involves %s" % ", ".join(hits[:6]))
    named = sorted({w for w in re.findall(r"[\w.-]+(?:/[\w.-]+)+", body) if paths.search(w)})
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
    issue = None
    if conf()["HARNESS_ESCALATE_GH"] == "on" and shutil.which("gh"):
        result = subprocess.run(["gh", "issue", "create", "--title", "Harness escalation: task %s: %s" % (task, kind),
                                 "--body", entry.strip(), "--label", "harness-escalation"],
                                cwd=str(ROOT), capture_output=True, text=True)
        issue = result.stdout.strip() if result.returncode == 0 else None
    return issue


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
    invalid = validate_spec(task)
    history = verdict_history(task, "grill")
    last = history[-1] if history else None
    if invalid or not last or last.get("verdict") != "pass" or last.get("fingerprint") != spec_fingerprint(task):
        print("approve: the spec must be valid and have a current griller pass first (spec-check %s)" % task)
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
        return ("Task %s cannot start: the griller failed the spec (%s). Take its questions to the user, "
                "update the spec and grill again." % (task, "; ".join(last.get("reasons") or [])[:400]))
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
    fails = consecutive_fails(history)
    reasons = "; ".join((last or {}).get("reasons") or [])[:400]
    if last is None:
        return "Task %s has no judge verdict. Ask the judge agent to review task %s." % (task, task)
    if last.get("verdict") != "pass" and fails >= max_rounds:
        return ("The judge failed task %s %d times. Stop retrying: report the findings to the user and "
                "ask how to proceed. Last reasons: %s" % (task, fails, reasons))
    if last.get("verdict") != "pass":
        return ("The judge failed task %s (round %d of %d): %s. Have the implementer fix the findings, "
                "then run the judge again." % (task, fails, max_rounds, reasons))
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
    result = subprocess.run(["git", "show", "%s:%s" % (rev, name)], cwd=str(ROOT), capture_output=True, text=True)
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
    lines = (text or "").splitlines()
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
    if values["HARNESS_STOP_MODE"] not in STOP_MODES:
        issues.append(("error", "HARNESS_STOP_MODE must be one of %s" % "|".join(STOP_MODES)))
    for key in ("HARNESS_SPEC_GATE", "HARNESS_SKILL_GATE", "HARNESS_JUDGE_GATE", "HARNESS_ORCHESTRATOR_SCOPE"):
        if values[key] not in ("on", "off"):
            issues.append(("error", "%s must be on or off" % key))
    if values["HARNESS_AUTONOMY"] not in AUTONOMY_MODES:
        issues.append(("error", "HARNESS_AUTONOMY must be one of %s" % "|".join(AUTONOMY_MODES)))
    elif values["HARNESS_AUTONOMY"] == "autonomous":
        if not values["HARNESS_TEST_CMD"]:
            issues.append(("error", "autonomous mode needs HARNESS_TEST_CMD: the judge's tests are the only evidence"))
        if values["HARNESS_VERIFY"] == "off" or values["HARNESS_JUDGE_GATE"] == "off" or values["HARNESS_SPEC_GATE"] == "off":
            issues.append(("error", "autonomous mode needs HARNESS_VERIFY, HARNESS_SPEC_GATE and HARNESS_JUDGE_GATE on"))
    if values["HARNESS_AUTO_APPROVE"] not in ("low", "off"):
        issues.append(("error", "HARNESS_AUTO_APPROVE must be low or off"))
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
    sys.stdout.write(json.dumps(payload) + "\n")


def add_context(event, text):
    emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def events_file():
    common = git("rev-parse", "--git-common-dir").strip()
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
    if autonomous():
        lines.append("AUTONOMOUS MODE: no user is in the loop. Never ask the user; approve low-risk specs with "
                     "harness.py approve <id>, escalate everything else with harness.py escalate <id> --reason ..., "
                     "and continue with the next ready task (AGENTS.md section 7).")
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
    print("\n".join(lines))


def hook_pre_tool_use(data):
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if halt_file().exists():
        deny("Harness halted: %s exists (the user's kill switch). Stop working and report your state; the user "
             "removes the file to resume." % halt_file())
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
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    notes = []
    if tool == "Read":
        m = re.match(r"^\.claude/skills/([^/]+)/SKILL\.md$", rel(tool_input.get("file_path") or ""))
        if m:
            remember_skill(data, m.group(1))
        return
    if tool == "Skill":
        name = str(tool_input.get("skill") or tool_input.get("name") or "").split(":")[-1].strip()
        remember_skill(data, name)
        return
    if tool in FILE_TOOLS and tool_input.get("file_path"):
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
        rules, _ = load_rules()
        hits = check_text(rules, None, rule_text(command), ("warn",))
        if hits:
            notes.append("Guardrail warnings for that command:\n%s" % describe(hits))
        if re.search(r"\bgit\b[^\n;&|]*\bcommit\b", command) and fresh_commit():
            notes.extend(dod_after_commit())
    if notes:
        add_context("PostToolUse", "\n\n".join(notes))


def uncommitted_count():
    return len([line for line in git("status", "--porcelain").splitlines() if line and not line.startswith("??")])


def hook_stop(data):
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


def hook_agent_guard(data, agent):
    """PreToolUse scoped to one agent: keep its edits inside its role."""
    scope = AGENT_SCOPES.get(agent)
    tool_input = data.get("tool_input") or {}
    if scope is None or data.get("tool_name") not in FILE_TOOLS or not tool_input.get("file_path"):
        return
    path = rel(tool_input["file_path"])
    mode, patterns = scope
    hit = any(re.search(pattern, path) for pattern in patterns)
    if (mode == "allow" and not hit) or (mode == "deny" and hit):
        deny("The %s agent may not edit %s. %s" % (agent, path, SCOPE_HELP[agent]))


# --------------------------------------------------------------------------- runner and report
# harness.py run drives tasks unattended: for each ready task it starts a fresh agent session with
# HARNESS_AGENT_CMD (the prompt on stdin), waits, and reads the outcome from 3-TASKS.md. The hooks,
# gates and verify do the enforcing; the runner only sequences, budgets and escalates stalls.

RUN_PROMPT = """You are running unattended: autonomous mode, no user in the loop (AGENTS.md section 7).
Drive Task {task} ("{title}") through the whole pipeline in backbone/8-WORKFLOW.md.
{state}
- Define: if backbone/specs/{task}.md is missing or not ready, have the analyst write it from the task title and
  backbone/, the architect complete Architecture and Skills, and the griller grill it. Answer the griller's
  questions from backbone/ as Assumptions; escalate what backbone/ cannot answer.
- Approve: python3 scripts/harness/lib/harness.py approve {task}
- Build, judge and record with the implementer, judge and scribe; then mark the task [x] and commit.
- When anything needs a human, escalate: python3 scripts/harness/lib/harness.py escalate {task} --reason "..."
Stop when the task is [x] and committed, or BLOCKED. Do not start other tasks."""


def ready_tasks(text=None):
    """[(id, title, state)] the runner may work on: a [WIP] task first, then pending ones, never BLOCKED."""
    lines = strip_comments(read(TASKS) if text is None else text).splitlines()
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
    queue = ready_tasks()
    if max_tasks:
        queue = queue[:max_tasks]
    if dry_run:
        for task, title, state in queue:
            print("run: would %s task %s: %s" % ("resume" if state == "wip" else "start", task, title))
        return 0
    timeout = int(values["HARNESS_RUN_TASK_TIMEOUT"]) if values["HARNESS_RUN_TASK_TIMEOUT"].isdigit() else 3600
    attempts = int(values["HARNESS_RUN_ATTEMPTS"]) if values["HARNESS_RUN_ATTEMPTS"].isdigit() else 2
    run_dir = events_file().parent / "runs" / time.strftime("%Y%m%d-%H%M%S")
    log_event("run-start", tasks=[t for t, _, _ in queue])
    summary = []
    for task, title, state in queue:
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
            code, seconds = run_agent(prompt, run_dir / ("%s-%d.log" % (slug(task), attempt)), timeout)
            if halt_file().exists():
                print("run: halted by %s during task %s" % (halt_file(), task))
                log_event("run-halt", task=task)
                outcome = "halted"
                break
            outcome = task_state(task)
            dirty = bool(git("status", "--porcelain").strip())
            log_event("run-attempt", task=task, attempt=attempt, exit=code, seconds=seconds, state=outcome,
                      uncommitted=dirty)
            print("run: task %s attempt %d: %s (%ss, exit %s%s)" % (task, attempt, outcome, seconds, code,
                                                                   ", uncommitted changes" if dirty else ""))
            if outcome == "done" and not dirty:
                break
            if outcome == "blocked":
                break
            if outcome == "done" and dirty:
                outcome = "done-uncommitted"
        else:
            if outcome not in ("done", "blocked"):
                escalate(task, "runner", "no resolution after %d agent session(s) (last state: %s; logs: %s)"
                         % (attempts, outcome, run_dir), "a look at the run logs and the task's state")
                outcome = "escalated"
        summary.append((task, outcome))
        if outcome == "halted":
            break
    log_event("run-end", summary=summary)
    for task, outcome in summary:
        print("run: %-12s task %s" % (outcome, task))
    return 0 if all(o in ("done", "blocked", "escalated") for _, o in summary) else 1


def report_command(argv):
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv and argv[-1].isdigit() else 7
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
    reasons = {}
    for e in events:
        if e.get("kind") in ("block", "verify"):
            key = re.sub(r"\s+", " ", e.get("reason", ""))[:70]
            reasons[key] = reasons.get(key, 0) + 1
    print("harness report, last %d day(s), %d event(s)" % (days, len(events)))
    print("  tasks finished by the runner: %d %s" % (len(done), ", ".join(done)))
    print("  judge verdicts: %d (%d pass, %d fail); claimed passes overturned by the harness: %d"
          % (len(judged), passes, len(judged) - passes, overturned))
    print("  escalations: %d (open now: %d); policy approvals: %d" % (count("escalation"), len(open_escalations()),
                                                                       count("approval")))
    print("  blocked tool calls: %d; commits refused by verify: %d" % (count("block"), count("verify")))
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


# --------------------------------------------------------------------------- entry point

HOOKS = {
    "session-start": hook_session_start,
    "pre-tool-use": hook_pre_tool_use,
    "post-tool-use": hook_post_tool_use,
    "stop": hook_stop,
    "grill-stop": lambda data: record_verdict(data, "grill"),
    "judge-stop": lambda data: record_verdict(data, "judge"),
}


def read_hook_input():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def main(argv):
    if len(argv) == 3 and argv[1] == "hook" and argv[2] in HOOKS:
        HOOKS[argv[2]](read_hook_input())
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
    if argv[1:2] == ["report"]:
        return report_command(argv[2:])
    if len(argv) == 3 and argv[1] == "risk":
        reasons = risk_reasons(argv[2])
        print("risk %s: %s" % (argv[2], "; ".join(reasons) if reasons else "low"))
        return 1 if reasons else 0
    sys.stderr.write(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
