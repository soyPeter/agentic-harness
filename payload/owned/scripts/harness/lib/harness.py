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
  harness.py attest --range <base>..<tip> [--allow-user-changes]     (in-toto statement of a verified range, ADR-005)
  harness.py environment-check <environment.json> <policies.json> <branch>   (CI: the attest environment's rule, ADR-005)
  harness.py repository-check <secrets.json> <variables.json>    (CI: no repository-level attest secrets, ADR-005)
  harness.py approve <task-id>                                    (autonomous mode: policy approval of a low-risk spec)
  harness.py escalate <task-id> --reason <text> [--kind <k>] [--class <failure class>] [--needed <text>]
  harness.py escalations [--json]                                 (open escalations for the user)
  harness.py contract [--json]                                    (the factory contract versions served, ADR-008)
  harness.py risk <task-id>
  harness.py run [--max-tasks N] [--only <task>] [--worktree [--pr]] [--dry-run]   (autonomous, unattended)
  harness.py report [--days N] [--json | --rules]                 (events: verdicts, gates, rules, lift, candidates)
  harness.py receipt <task-id> [--base <rev>] [--json]            (what the harness can prove about a judged task)
  harness.py delivery-plan <task-id> [--base <branch>] [--pr-labels a,b] [--json]
                                                                  (HARNESS_DELIVER=external: what to push and open)
  harness.py delivery-record <task-id> <report.json>              (the trusted clone's delivery outcome; user-only)
  harness.py linear import <ISSUE> --task <id> [--light] [--from F] [--sender S] [--sender-verdict trusted|untrusted]
  harness.py linear receipt <task> [--status S] [--matrix U]      (Linear as the system of record; user-only)
  harness.py intake <request.json> [--json]                       (a request from the factory's doors, ADR-008; user-only)
  harness.py trace <task-id> [--json]                             (the task's events: context, skills, edits, refusals, tests)
  harness.py trace export --format reqif|reqifz|needs|html [--out DIR] [--task ID]
                                                                  (derived traceability export, ADR-004)
  harness.py trace link <matrix-url> [--task ID]                  (the comment that links a matrix, ADR-004)
  harness.py ci-judge --range <base>..<tip>                       (CI: independent re-judging of finished tasks)
  harness.py ci-protect [--branch main] [--with-judge] [--dry-run] (require the CI checks; needs gh)
  harness.py ci-protect --attest [--dry-run] [--recorded-fallback] [--delete-repo-copies]
                                                                  (the harness-attest environment: default branch only)
  harness.py doctor
"""
import fnmatch
import glob
import hashlib
import hmac
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
from collections import Counter
from pathlib import Path
from stat import S_ISREG

sys.dont_write_bytecode = True   # no __pycache__ in the project
sys.path.insert(0, str(Path(__file__).resolve().parent))
import decisions  # noqa: E402  (sibling module)
import sandbox  # noqa: E402  (sibling module)

# The engine is the folder holding scripts/harness/: the project itself in a full install, or a pinned release outside
# it in thin mode (ADR-001). Engine-owned files (core rules and routes, core skills, agents, catalog) come from here.
ENGINE = Path(__file__).resolve().parents[3]


def find_root():
    # HARNESS_ROOT lets CI run the base branch's copy of this file against a pull request's checkout,
    # so a pull request cannot change the verifier that checks it.
    if os.environ.get("HARNESS_ROOT"):
        return Path(os.environ["HARNESS_ROOT"])
    if (ENGINE / "backbone" / ".harness-lock.json").is_file() or (ENGINE / ".git").exists():
        return ENGINE
    start = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        top = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        top = ""
    return Path(top or start)


ROOT = find_root().resolve()
BACKBONE = ROOT / "backbone"
TASKS = BACKBONE / "3-TASKS.md"
MEMORY = BACKBONE / "6-MEMORY.md"
SPECS = BACKBONE / "specs"
ADRS = BACKBONE / "adr"
VERDICTS = BACKBONE / ".verdicts"
CONF_FILE = BACKBONE / "harness.conf"
LOCK_FILE = BACKBONE / ".harness-lock.json"
TOOLS_FILE = BACKBONE / "tools.conf"
SKILLS = ROOT / ".claude" / "skills"
ENGINE_SKILLS = ENGINE / ".claude" / "skills"
AGENT_DIRS = [ROOT / ".claude" / "agents", ENGINE / ".claude" / "agents"]
SETTINGS_FILE = ROOT / ".claude" / "settings.json"
RULE_FILES = [ENGINE / "scripts/harness/guardrails.core.conf", BACKBONE / "guardrails.conf"]
ROUTE_FILES = [ENGINE / "scripts/harness/routing.core.conf", BACKBONE / "routing.conf"]
# An installed engine has the catalog copied in; a checkout of the harness repository (thin mode) keeps it at the top.
CATALOG_DIR = next((d for d in (ENGINE / "scripts/harness/catalog", ENGINE.parent.parent / "catalog")
                    if d.is_dir()), ENGINE / "scripts/harness/catalog")
HOOKS_PATH = "scripts/harness/git-hooks"
HOOK_MARK = "scripts/harness/"
FILE_TOOLS = ("Write", "Edit", "MultiEdit")
TOOL_CLASSES = ("read", "write", "exec", "network", "agent")
# Contracts for the agents' own tools (Claude Code, Codex, OpenCode names). They come before backbone/tools.conf, which
# adds contracts for other tools but can't reclassify these: "NotebookEdit read" would open backbone/ to it.
BUILTIN_TOOL_CONTRACTS = """
Write Edit MultiEdit                    write    path=file_path
NotebookEdit                            write    path=notebook_path
apply_patch                             write
Bash KillShell KillBash TaskStop Monitor EnterWorktree ExitWorktree   exec
Task Agent SendMessage ListAgents       agent
WebFetch WebSearch                      network
Read Grep Glob LS NotebookRead TodoWrite TodoRead TaskCreate TaskGet TaskList TaskUpdate TaskOutput BashOutput   read
ToolSearch AskUserQuestion EnterPlanMode ExitPlanMode Skill SlashCommand ListMcpResourcesTool ReadMcpResourceTool   read
LSP                                     read
read glob grep list todowrite todoread question lsp codesearch skill   read
webfetch websearch                      network
task subagent                           agent
"""
PIPELINE_AGENTS = ("analyst", "architect", "griller", "tester", "implementer", "judge", "debugger", "scribe",
                   "reviewer", "deliverer")
# The reviewer runs once per lens, in parallel; each lens records its own verdict on the code.
REVIEW_LENSES = ("correctness", "structure", "lean")
USER_ONLY_KEYS = ("HARNESS_SPEC_GATE", "HARNESS_SKILL_GATE", "HARNESS_JUDGE_GATE", "HARNESS_JUDGE_MAX_ROUNDS",
                  "HARNESS_VERIFY", "HARNESS_ORCHESTRATOR_SCOPE",
                  "HARNESS_AUTONOMY", "HARNESS_AUTO_APPROVE", "HARNESS_RISK_TERMS", "HARNESS_RISK_PATHS",
                  "HARNESS_RISK_MAX_FILES", "HARNESS_DOC_PATHS", "HARNESS_GRILL_MAX_ROUNDS", "HARNESS_ESCALATE_GH",
                  "HARNESS_AGENT_CMD", "HARNESS_RUN_TASK_TIMEOUT", "HARNESS_RUN_ATTEMPTS",
                  "HARNESS_RUN_MAX_COST", "HARNESS_TASK_BUDGET_USD", "HARNESS_CI_JUDGE_CMD",
                  "HARNESS_DECISION_PROVIDER", "HARNESS_DECISION_MODE", "HARNESS_DECISION_ADR",
                  "HARNESS_DECISION_CMD", "HARNESS_DECISION_MODEL", "HARNESS_DECISION_URL",
                  "HARNESS_KNOWLEDGE_ROOT", "HARNESS_KNOWLEDGE_TOOLS", "HARNESS_KNOWLEDGE_PATHS",
                  "HARNESS_TESTER", "HARNESS_ACCEPTANCE_PATHS", "HARNESS_ORCA_AGENTS", "HARNESS_ORCA_LAUNCH",
                  "HARNESS_SPEC_MAX_ITEMS", "HARNESS_LIGHT_LANE", "HARNESS_LIGHT_MAX_ITEMS", "HARNESS_LIGHT_MAX_FILES",
                  "HARNESS_REVIEW", "HARNESS_DELIVER", "HARNESS_PROFILE", "HARNESS_REQ_STYLE",
                  "HARNESS_SANDBOX_BACKEND")
# Organisation profiles (HARNESS_PROFILE, user-only). "triple": a supervised pilot where only a human merges, so the
# coordinator's --merge and --trust and the scheduled backlog run are refused. "no-merge": the same refusals for any
# organisation, such as an agent factory's lanes (ADR-008), without Triple's catalog pack.
PROFILES = ("", "triple", "no-merge")
NO_MERGE_PROFILES = ("triple", "no-merge")
MERGE_ENDPOINT = re.compile(r"/pulls/\d+/merge\b|/merges\b")
MERGE_TOOL = re.compile(r"^mcp__.*merge", re.I)
# The knowledge source: an MCP server registered as "knowledge" (claude mcp add) over a folder of notes, that the
# analyst, architect and griller consult when grilling raises questions. Read-only; answers are cited as vault:<path>.
KNOWLEDGE_TOOL_PREFIX = "mcp__knowledge__"
KNOWLEDGE_PATH_KEYS = ("path", "paths", "note", "notes", "hub", "name", "file", "files", "target")
# Paths an agent may change only through the file tools, where the hooks see the change. Shell writes to
# them are refused: they would skip the gates (task states, approvals, verdicts, settings, skill state).
SHELL_PROTECTED = (r"^backbone(/|$)", r"^scripts/harness(/|$)", r"^\.claude(/|$)", r"^\.codex(/|$)", r"^\.opencode(/|$)",
                   r"^(AGENTS|CLAUDE)\.md$", r"^\.githooks(/|$)",
                   r"^\.git(/|$)", r"^harness-attest\.pub$")
# Thin mode (ADR-001): the launcher names the engine cache and the plugin it runs from. They decide the project's gates
# but lie outside it, beyond the reach of the repository-relative protections.
INSTALL_DIRS = (("HARNESS_ENGINES", "the harness engine cache"), ("HARNESS_PLUGIN_ROOT", "the harness plugin"))
INSTALL_SCRIPTS = ("harness.py", "launcher.py", "thin.py")
# Codex and OpenCode plugins can't ship agents, so a thin session start installs the pinned engine's role agents where
# each CLI loads user-level agents (ADR-001). A file there without this mark is the user's own and is left alone.
USER_AGENTS = {"codex": (".codex/agents", ".toml", "Codex"), "opencode": (".opencode/agents", ".md", "OpenCode")}
USER_AGENT_MARK = "Agentic harness: generated from"
# Harness files whose edits change enforcement; verify refuses commits that change them away from the lock.
ENFORCEMENT_FILES = (r"^scripts/harness/", r"^\.claude/agents/", r"^\.github/workflows/harness-[^/]+\.ya?ml$",
                     r"^\.devcontainer/harness-agent/", r"^\.codex/(hooks\.json$|agents/|rules/harness\.rules$)",
                     r"^\.opencode/(plugins/harness\.js$|agents/)", r"^harness-attest\.pub$")
# What the main session (the orchestrator) may edit itself; specs, ADRs and code go through the role agents.
ORCHESTRATOR_ALLOW = (r"^backbone/(?!specs/|adr/|\.verdicts/)", r"^\.claude/skills/", r"^CLAUDE\.md$")
DECISIONS_FILE = ENGINE / "scripts/harness/decisions.json"
ESCALATIONS = BACKBONE / "escalations.md"
AUTONOMY_MODES = ("supervised", "autonomous")
# Requirement wording (HARNESS_REQ_STYLE, user-only). ears: every requirement follows an EARS pattern
# (requirements-writing skill, ears.md), and acceptance criteria may prove NFR-<task>-<n> items as well.
REQ_STYLES = ("plain", "ears")
EARS_SHAPE = re.compile(r"^(?:(?:While|When|Where)\s+.+?,\s*|If\s+.+?,\s*then\s+)*the\s+\S.*?\s+shall\s+\S", re.I)
EARS_VAGUE = re.compile(r"(?i)\b(appropriate(ly)?|adequate(ly)?|user[- ]friendly|easy|easily|fast|quickly|efficient(ly)?|"
                        r"as (needed|required|appropriate)|if possible|where possible|etc\.?|and/or|robust|seamless(ly)?|"
                        r"intuitive|flexible|sufficient|reasonable|normally|usually|support(s)? for|be able to)(?=\W|$)")
EARS_PASSIVE = re.compile(r"(?i)\bshall\s+(not\s+)?be\s+(\w+ed|\w+en|sent|shown|built|kept|made|set|put|run|held)\b")
BLOCKED_NOTE = re.compile(r"\s+[-\u2014]+\s+BLOCKED:\s*(.*)$")
LIGHT_MARK = re.compile(r"\(light\)", re.I)
POLICY_APPROVAL = re.compile(r"^\s*Approved-by:\s*policy:(\S+)\s*\((.*)\)", re.M)


def heading_pattern(title):
    """A '## <title>' Markdown heading at column 0, with an optional closing run of #s. Case-insensitive."""
    return re.compile(r"^##[ \t]+%s(?:[ \t]+#+)?[ \t]*\r?$" % re.escape(title), re.M | re.I)


APPROVAL_HEADING = heading_pattern("Approval")
# A section runs to the next heading of level 1 or 2, as a reader sees it.
SECTION_END = re.compile(r"^#{1,2}(?:[ \t\r]|$)", re.M)

# The kind of work a spec declares (the harness's ADR-002). A spec without the line counts as feature.
CHANGE_CLASSES = ("docs", "refactor", "feature", "schema")
CHANGE_CLASS_LINE = re.compile(r"^[ \t]*Change-Class:(.*)$", re.M | re.I)
# Markdown's fences. A fence opens at column 0 and closes at 0-3 spaces with nothing after its marker. A fence or heading
# a list item, a quote or an HTML block could hold is refused, not guessed at: see scan_lines.
FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})(.*)$")
FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
WIDE_FENCE = re.compile(r"^(?:[ \t]*\t| {4,})[ \t]*(`{3,}|~{3,})")
FENCE_RUN = re.compile(r"`{3,}|~{3,}")
ATX_HEADING = re.compile(r"#{1,6}(?:[ \t]|$)")
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
CONTAINER = re.compile(r"(?:>|(?:[-*+]|\d{1,9}[.)])(?=[ \t]|$))[ \t]*")
# CommonMark's HTML blocks (types 1, 3, 4, 5: they end at the line holding their end condition, blank lines included;
# types 6 and 7: they end at a blank line, and only 7 may not interrupt a paragraph). Type 2 is a comment, see
# blank_comments_in_line.
# '<!-->' and '<!--->' are whole comments (CommonMark 0.31), and a '-->' may share its dashes with the '<!--' before it:
# the alternatives are tried in order, so each of these is matched whole and its '-->' is not missed.
COMMENT_MARK = re.compile(r"<!--->|<!-->|<!--|-->")
INLINE_COMMENT = re.compile(r"<!---?>|<!--.*?-->")
HTML_BLOCKS = (
    (re.compile(r"<(?:pre|script|style|textarea)(?=[ \t>]|$)", re.I),
     re.compile(r"</(?:pre|script|style|textarea)>", re.I)),
    (re.compile(r"<\?"), re.compile(r"\?>")),
    (re.compile(r"<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>")),
)
HTML_TAG_BLOCK = re.compile(
    r"</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|"
    r"dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|"
    r"menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|"
    r"tr|track|ul)(?=[ \t>]|/>|$)", re.I)
_ATTRIBUTE = r"[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*(?:[ \t]*=[ \t]*(?:[^\"'=<>`\x00-\x20]+|'[^']*'|\"[^\"]*\"))?"
HTML_TAG_ALONE = re.compile(
    r"(?:<[A-Za-z][A-Za-z0-9-]*(?:%s)*[ \t]*/?>|</[A-Za-z][A-Za-z0-9-]*[ \t]*>)[ \t]*$" % _ATTRIBUTE, re.I)
# Indented code starts with 4 spaces or a tab, so anything else after 0-3 spaces is text, a non-breaking space included.
PLAIN_INDENT = re.compile(r" {0,3}[^ \t]")
THEMATIC_BREAK = re.compile(r" {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
FENCE_REASON = ("the spec has a code fence indented 4 or more columns, or with a tab: keep fences at column 0, so every "
                "reader ends them where the gates do")
STRUCTURE_REASON = ("the spec has a heading or code fence that is indented, follows a list or quote marker, or sits in an "
                    "HTML block: keep headings and fences at column 0, outside HTML blocks")
HTML_REASON = ("the spec has a tag alone on a line right after a list or quote paragraph or a link reference definition: "
               "a reader may take it for text or for an HTML block; put a blank line before it")
NESTED_HTML_REASON = ("the spec has an HTML block inside a list item or quote, or indented, that a reader may end where the "
                      "item or quote ends: start a pre, script, style or textarea block, a '<?', a '<!' declaration or a "
                      "CDATA block at column 0, and put a blank line after an indented tag")
SETEXT_REASON = "the spec has a setext heading (text over a line of = or -): write headings as '## Title'"
LINE_BREAK_REASON = ("the spec has a line break character a reader may take for a line end (a vertical tab, form feed, NEL, "
                     "or a Unicode line or paragraph separator): remove it")
UNUSUAL_SPACE_REASON = ("the spec has an unusual space or control character on a line with a tag, heading or fence: use a "
                        "plain space or tab there")
LINE_BREAKS = re.compile(r"[\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")
UNUSUAL_SPACES = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\xa0\u1680\u2000-\u200f\u2028\u2029\u202f\u205f\u2060\u3000\ufeff]")
# A backtick or tilde matters only in a fence marker; inline code may hold any space.
STRUCTURE_CHARS = re.compile(r"[<#]|^[^A-Za-z`~]*(?:`{3}|~{3})")
# A paragraph starting like this may be a link reference definition, which is no paragraph to CommonMark: a tag alone on
# the next line may start an HTML block.
LINK_DEFINITION_START = re.compile(r" {0,3}\[")
COMMENT_REASON = ("the spec has an HTML comment a reader may not end where the gates do: a comment that doesn't start at "
                  "column 0 must close on its own line")
USER_APPROVED_CLASSES = ("feature", "schema")
CLASS_GATES = {
    "docs": "policy may approve it when nothing is risky; a change to anything but documentation is a risk",
    "refactor": "policy may approve it when nothing is risky",
    "feature": "the user approves it, never policy",
    "schema": "the user approves it, never policy; it never takes the light lane",
}
# Pull request labels a receipt suggests for human triage. The risk label starts at the class's step and goes one
# step up when the receipt lists other risks: docs and refactor may be policy-approved, feature never is, and schema
# is migrations, auth, secrets, payments and infrastructure.
RISK_LABELS = ("risk:low", "risk:elevated", "risk:high")
CLASS_RISK_STEP = {"docs": 0, "refactor": 0, "feature": 1, "schema": 2}
TRIAGE_LABELS = RISK_LABELS + tuple("class:" + name for name in CHANGE_CLASSES)

# Write scope per agent: ("allow", patterns) permits only matches; ("deny", patterns) refuses matches.
AGENT_SCOPES = {
    "analyst": ("allow", (r"^backbone/specs/[^/]+\.md$", r"^backbone/1-PRD\.md$")),
    "architect": ("allow", (r"^backbone/adr/[^/]+\.md$", r"^backbone/specs/[^/]+\.md$",
                            r"^backbone/5-DECISIONS\.md$", r"^backbone/2-PLANNING\.md$")),
    "scribe": ("allow", (r"^backbone/6-MEMORY\.md$", r"^backbone/adr/[^/]+\.md$", r"^backbone/5-DECISIONS\.md$",
                         r"^backbone/proposals/[^/]+\.md$")),
    "implementer": ("deny", (r"^backbone/", r"^\.claude/", r"^\.codex/", r"^\.opencode/", r"^scripts/harness/",
                             r"^(AGENTS|CLAUDE)\.md$", r"^harness-attest\.pub$")),
    # Reviewers never edit. Claude Code enforces this with their tool list; Codex has no per-agent tool list.
    "griller": ("allow", ()),
    "judge": ("allow", ()),
    "debugger": ("allow", ()),
    "tester": ("allow", ()),   # plus HARNESS_ACCEPTANCE_PATHS (see role_scope)
    "reviewer": ("allow", ()),
    "deliverer": ("allow", ()),
}
SCOPE_HELP = {
    "analyst": "It writes specs (backbone/specs/) and the PRD only.",
    "architect": "It writes ADRs (backbone/adr/), their index, 2-PLANNING.md and the Architecture section of specs.",
    "scribe": "It writes 6-MEMORY.md, ADRs for decisions taken during implementation, and draft proposals.",
    "implementer": "It writes code and tests only; backbone/, .claude/ and harness files belong to other roles.",
    "griller": "It reviews the spec and asks questions; it never edits files.",
    "judge": "It judges the code against the spec; it never edits files.",
    "debugger": "It diagnoses the judge's failures and writes a fix brief; it never edits files.",
    "tester": "It writes acceptance tests only, in files matching HARNESS_ACCEPTANCE_PATHS.",
    "reviewer": "It reviews the task's change through one lens and reports findings; it never edits files.",
    "deliverer": "It pushes the reviewed branch, opens the PR and watches CI; fixes go back to the implementer.",
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
    # A folder doesn't make a file documentation (docs/conf.py is Sphinx's code), and some .txt files are build or
    # dependency input: CMake's, and pip's requirements and constraints, which Read the Docs installs.
    "HARNESS_DOC_PATHS": r"(?i)^(?!(.*/)?CMakeLists\.txt$|.*(requirements|constraints)[^.]*\.txt$)(.*/)?"
                         r"([^/]+\.(md|mdx|markdown|rst|adoc|asciidoc|txt)"
                         r"|README|CHANGELOG|CHANGES|HISTORY|LICEN[CS]E|NOTICE|CONTRIBUTING|AUTHORS|COPYING)$",
    "HARNESS_GRILL_MAX_ROUNDS": "3",
    "HARNESS_ESCALATE_GH": "off",
    "HARNESS_AGENT_CMD": "claude -p --permission-mode acceptEdits --output-format json",
    "HARNESS_RUN_TASK_TIMEOUT": "3600",
    "HARNESS_RUN_ATTEMPTS": "2",
    "HARNESS_RUN_MAX_COST": "",
    "HARNESS_TASK_BUDGET_USD": "",
    "HARNESS_SANDBOX_BACKEND": "devcontainer",
    "HARNESS_CI_JUDGE_CMD": "claude -p --agent judge --dangerously-skip-permissions --output-format json",
    "HARNESS_SKILL_MAX_AGE": "180",
    "HARNESS_HOOK_SLOW": "5",
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
    "HARNESS_REVIEW": "on",
    "HARNESS_DELIVER": "on",
    "HARNESS_SPEC_MAX_ITEMS": "30",
    "HARNESS_LIGHT_LANE": "off",
    "HARNESS_LIGHT_MAX_ITEMS": "3",
    "HARNESS_LIGHT_MAX_FILES": "3",
    "HARNESS_ORCA_AGENTS": "default=claude",
    "HARNESS_PROFILE": "",
    "HARNESS_REQ_STYLE": "plain",
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


def committed_conf():
    """The settings in backbone/harness.conf and the defaults, without environment overrides: the trace export reads
    these, so the same commit gives the same bytes on every machine (ADR-004)."""
    values = dict(DEFAULTS)
    values.update(parse_conf(read(CONF_FILE)))
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


CANONICAL_PATHS = ("backbone/3-TASKS.md", "backbone/harness.conf", "backbone/tools.conf", "backbone/.harness-lock.json",
                   "backbone/escalations.md", "backbone/.verdicts/", "backbone/specs/", "backbone/adr/", "backbone/")


def canonical(path):
    """path with a gated backbone name spelled as the gates expect: on a case-insensitive disk (macOS, Windows)
    backbone/3-tasks.md is the same file as backbone/3-TASKS.md, and must not skip its checks."""
    lower = path.lower()
    for name in CANONICAL_PATHS:
        if lower == name.lower() or (name.endswith("/") and lower.startswith(name.lower())):
            return name + path[len(name):] if name.endswith("/") else name
    return path


def rel(path_str):
    """Repository-relative POSIX path, or the absolute path if it lies outside the repo. Relative paths are resolved
    against the repo too: src/../backbone/x must meet the backbone gates."""
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
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


def line_endings(text):
    """text with CRLF and lone CR line ends read as LF, which is how a Markdown reader reads them and how read() loads
    a file. A hook must compare and parse proposed text in this form too."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def blank(text):
    """text with every character but its line breaks replaced by a space, so an offset in it is one in text."""
    return re.sub(r"[^\n]", " ", text)


def blank_line(line):
    """CommonMark's blank line: spaces and tabs only. str.strip() also takes a non-breaking space, which is text."""
    return line.strip(" \t") == ""


def blank_text(text):
    return text.strip(" \t\r\n") == ""


def character_reason(body, fenced):
    """Why a line's characters could be read differently from the gates, or ''. A line break a reader or splitlines takes
    for one is refused anywhere. An unusual space or control character is refused beside a tag, heading or fence, where
    a reader would start a block, and is ordinary text elsewhere."""
    if LINE_BREAKS.search(body):
        return LINE_BREAK_REASON
    if not fenced and UNUSUAL_SPACES.search(body) and STRUCTURE_CHARS.search(body):
        return UNUSUAL_SPACE_REASON
    return ""


def blank_comments_in_line(line, inside):
    """(line with its HTML comment text blanked, whether a comment is still open at its end, whether a comment on the
    line is one a reader may not end where the gates do). A comment that starts at column 0 runs to its '-->', across
    lines, as a Markdown HTML block does; '<!-->' and '<!--->' are whole comments. Any other comment must close on its
    line: after text a reader takes it for an inline comment that ends with its paragraph, indented for one in a list
    item that ends with the item, or for code. A '<!--' inside a comment opens nothing."""
    pieces, pos, ambiguous, must_close = [], 0, False, False
    for m in COMMENT_MARK.finditer(line):
        if inside and m.group(0).endswith("-->"):
            pieces.append(blank(line[pos:m.end()]))
            pos, inside, must_close = m.end(), False, False
        elif not inside and m.group(0).startswith("<!--"):
            lead = line[:m.start()]
            pieces.append(line[pos:m.start()])
            ambiguous = ambiguous or (lead.strip() == "" and not re.fullmatch(r" {0,3}", lead))
            if m.group(0) == "<!--":
                pos, inside = m.start(), True
                must_close = lead != ""
            else:
                pieces.append(blank(m.group(0)))
                pos = m.end()
    pieces.append(blank(line[pos:]) if inside else line[pos:])
    return "".join(pieces), inside, ambiguous or (inside and must_close)


def closes_fence(run, fence):
    return run[0] == fence[0] and len(run) >= len(fence)


def block_start(body):
    """(what a line holds once its list and quote markers are stripped, whether it had any)."""
    rest, nested = body.lstrip(" \t"), False
    while True:
        m = CONTAINER.match(rest)
        if not m:
            return rest, nested
        rest, nested = rest[m.end():], True


def setext_underline(body):
    """Whether body, or what it holds after any of its list and quote markers, is a setext underline. A lone '-' after
    paragraph text is an underline, not an empty list item, since an empty item may not interrupt a paragraph."""
    rest = body
    while not (SETEXT_UNDERLINE.match(rest) or SETEXT_UNDERLINE.match(rest.lstrip(" \t"))):
        m = CONTAINER.match(rest.lstrip(" \t"))
        if not m:
            return False
        rest = rest.lstrip(" \t")[m.end():]
    return True


def html_block(rest, interrupts):
    """How a line whose text (after its indentation) is rest opens an HTML block: the pattern its block ends at, 'blank'
    for a block a blank line ends, or None when it opens none. interrupts: the line directly follows paragraph text."""
    for start, end in HTML_BLOCKS:
        if start.match(rest):
            return end
    if HTML_TAG_BLOCK.match(rest):
        return "blank"
    if not interrupts and HTML_TAG_ALONE.match(rest):
        return "blank"
    return None


def scan_lines(text):
    """(line, fenced, commentless, reason) for each line of text, read the way Markdown reads its blocks. A fence opens
    at column 0 and closes with a run of its character, at least as long, at 0-3 spaces with nothing after it. A comment
    doesn't open inside a fence, and a fence marker inside a comment opens nothing. fenced: the line is a fence or in one.
    commentless: the line with its comment text blanked, code kept. reason: why a reader could read the line differently
    from the gates, or ''. Only column-0 headings and fences are read: an indented one, one after a list or quote marker,
    one in an HTML block and a setext heading are refused, since Markdown may read them as text or code. HTML blocks
    start and end as html_block says; one a reader may end with its list item or quote is refused unless it ends on its
    line or at the blank line after it. A line break or an unusual space or control character a reader may read differently
    is refused too (character_reason)."""
    fence, comment, html, prev_text, prev_doubtful, loose_html, prev_code = None, False, None, False, False, False, False
    for line in re.findall(r"[^\n]*\n|[^\n]+\Z", text or ""):
        body = line.rstrip("\r\n")
        if fence is not None:
            wide = WIDE_FENCE.match(body)
            close = FENCE_CLOSE.match(body)
            yield line, True, line, character_reason(body, True) or (
                FENCE_REASON if wide and closes_fence(wide.group(1), fence) else "")
            if close and closes_fence(close.group(1), fence):
                fence = None
            prev_text = prev_code = False
            continue
        in_html = html is not None
        if html == "blank" and blank_line(body):
            html, in_html = None, False
        rest, nested = block_start(body)
        off_column = nested or body[:1] in (" ", "\t") or in_html
        reason = ""
        if not comment and off_column and (FENCE_RUN.match(rest) or ATX_HEADING.match(rest)):
            reason = STRUCTURE_REASON
        # Indented code after a list item may be the item's text instead, which an underline makes a heading.
        elif not comment and (prev_text or prev_code) and setext_underline(body):
            reason = SETEXT_REASON
        elif not comment and not in_html and prev_text and prev_doubtful and not nested and HTML_TAG_ALONE.match(rest):
            reason = HTML_REASON
        reason = character_reason(body, False) or reason
        if loose_html and not blank_line(body):
            reason = reason or NESTED_HTML_REASON
        loose_html = False
        opening = None if comment or reason or off_column else FENCE_OPEN.match(body)
        if opening and not ("`" in opening.group(2) and opening.group(1)[0] == "`"):
            fence = opening.group(1)
            yield line, True, line, ""
            prev_text = prev_code = False
            continue
        started = None
        if not comment and not reason and not in_html and PLAIN_INDENT.match(body):
            started = html_block(rest, prev_text or nested)
        # A block in a list item or quote ends with the item or quote, so it isn't carried to the next line: that line is
        # in the container too, nested or indented and refused wherever it matters, or past the container's end. An
        # indented block may be in a list item, or not: only a blank line after it ends it in both readings.
        if started is not None and (nested or body[:1] == " ") and started != "blank":
            reason = NESTED_HTML_REASON
        elif started is not None and not nested:
            html, loose_html = started, body[:1] == " "
        block_comment = comment or bool(PLAIN_INDENT.match(body) and body.lstrip(" ").startswith("<!--"))
        if (in_html or started is not None) and not comment:
            commentless, ambiguous = line, False
        else:
            commentless, comment, ambiguous = blank_comments_in_line(line, comment)
        if html not in (None, "blank") and html.search(body):
            html = None
        yield line, False, commentless, COMMENT_REASON if ambiguous else reason
        code = not prev_text and not blank_line(body) and not PLAIN_INDENT.match(body)
        # Only '---' after text is a setext underline (refused above); '***' and '___' end the paragraph.
        thematic = bool(THEMATIC_BREAK.match(body))
        doubtful = nested or (not prev_text and LINK_DEFINITION_START.match(body))
        prev_text = (not blank_line(body) and not ATX_HEADING.match(body) and not in_html and started is None
                     and not code and not block_comment and not thematic)
        prev_doubtful = prev_text and bool(doubtful or prev_doubtful)
        prev_code = code


def comment_free(text):
    """text with its HTML comments blanked out and its code blocks kept, offsets kept: what the gates read a spec's
    words from, examples included."""
    return "".join(commentless for _, _, commentless, _ in scan_lines(text))


def outline(text):
    """text with its HTML comments and fenced code blocks blanked out, offsets kept: the spec's structure as Markdown
    shows it. Headings, sections and Approved-by: lines are read from here only."""
    return "".join(blank(line) if fenced else commentless for line, fenced, commentless, _ in scan_lines(text))


def section_bounds(view, title):
    """(heading start, body start, body end) of the '## <title>' section of view (an outline), or None."""
    m = heading_pattern(title).search(view)
    if not m:
        return None
    nxt = SECTION_END.search(view, m.end())
    return m.start(), m.end(), nxt.start() if nxt else len(view)


def md_section(text, title):
    """Body of the '## <title>' section as outline() shows it (no comments, no code blocks), or None if absent."""
    view = outline(text)
    bounds = section_bounds(view, title)
    return None if bounds is None else view[bounds[1]:bounds[2]]


def without_section(text, title, view=None):
    """text without its '## <title>' section, the section found in text as the gates find it. view, when given, is a
    version of text with the same offsets (comments kept, say) that the section is cut from."""
    bounds = section_bounds(outline(text), title)
    base = text if view is None else view
    return base if bounds is None else base[:bounds[0]] + base[bounds[2]:]


def approval_start(text):
    """Where the spec's Approval section starts (its heading), or the end of text."""
    m = APPROVAL_HEADING.search(outline(text))
    return m.start() if m else len(text)


def without_approval(text):
    """text outside its Approval section: what the grill fingerprint covers and approval freezes."""
    return without_section(text, "Approval")


def frozen_text(text):
    """What the grill fingerprint covers and the freeze keeps: the spec outside its Approval section, or all of it when a
    reader could read its sections differently, since then no section can be trusted."""
    return text if spec_reading_problem(text) else without_approval(text)


def approval_section(text):
    """The Approval section as approved() and policy approval read it: from its heading to the next '## ' heading."""
    return md_section(text, "Approval")


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
    text = outline(read(TASKS) if text is None else text)
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
    text = outline(read(TASKS) if text is None else text)
    lines = text.splitlines()
    return [task_id_at(lines, i) for i, line in enumerate(lines) if WIP_LINE.match(line)]


def finished_tasks(before, after):
    """Ids of [WIP] tasks this edit takes out of progress, other than by reverting them to
    '- [ ]' (abandoning). Marking [x], rewording or deleting all count as finishing."""
    after_lines = outline(after).splitlines()
    pending = {PENDING_LINE.sub("", line).strip() for line in after_lines if PENDING_LINE.match(line)}
    lines = outline(before).splitlines()
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
    return sorted(set(ADR_ID.findall(md_section(text, "Architecture") or "")))


def spec_skills(text):
    names = []
    for item in bullets(md_section(text, "Skills")):
        m = re.match(r"`?([a-z0-9][a-z0-9-]*)`?", item)
        if m:
            names.append(m.group(1))
    return names


def adr_file(adr_id):
    found = sorted(ADRS.glob("%s-*.md" % adr_id)) + ([ADRS / ("%s.md" % adr_id)] if (ADRS / ("%s.md" % adr_id)).is_file() else [])
    return found[0] if found else None


def adr_status(text):
    lines = [line.strip() for line in (md_section(text, "Status") or "").splitlines() if not blank_line(line)]
    return lines[0] if lines else ""


def validate_adr(text, name):
    problems = ["%s: section '## %s' is missing or empty" % (name, title)
                for title in ADR_SECTIONS if blank_text(md_section(text, title) or "")]
    return problems + stubs(name, comment_free(text))


def approval_heading_problem(text):
    """Why the spec's '## Approval' heading is ambiguous, or None: one inside a code block, or one inside or next to an
    HTML comment. A reader that doesn't skip those would start the Approval section there, where the grill fingerprint
    and the freeze don't end."""
    for line, fenced, commentless, _ in scan_lines(text):
        body = line.rstrip("\r\n")
        if not (APPROVAL_HEADING.match(body) or APPROVAL_HEADING.match(INLINE_COMMENT.sub("", body))):
            continue
        if not fenced and APPROVAL_HEADING.match(commentless.rstrip("\r\n")):
            continue
        if fenced:
            return ("the spec has an '## Approval' heading inside a fenced code block: keep one '## Approval' heading, "
                    "on a line of its own, outside code blocks (indent an example's heading)")
        return ("the spec has an '## Approval' heading inside or next to an HTML comment: keep one '## Approval' "
                "heading, on a line of its own, outside comments")
    return None


def reading_problem(text):
    """Why a reader could read the spec's code, comments or headings differently from the gates, or None (scan_lines)."""
    return next((reason for *_, reason in scan_lines(text) if reason), None)


def spec_reading_problems(text):
    """Why the spec is refused for how a reader would read it, one reason each: see scan_lines and approval_heading_problem."""
    return [p for p in (approval_heading_problem(text), reading_problem(text)) if p]


def spec_reading_problem(text):
    problems = spec_reading_problems(text)
    return problems[0] if problems else None


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
        elif items and not blank_line(line):
            items[-1] += " " + line.strip()
    return items


def knowledge_citation_problems(text):
    """Assumptions without a source, or citing vault:<path> notes that don't exist or aren't allowed."""
    problems = []
    root = knowledge_root()
    for n, item in enumerate(top_level_items(md_section(text, "Assumptions")), 1):
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
    return sorted(line.strip() for line in text.split("\n") if APPROVAL_LINE.match(line))


def approved(text):
    return bool(approval_lines(approval_section(text) or ""))


def ears_problems(req, text):
    """Why a requirement's wording is not EARS: one shall, a named system, a trigger after When/While/If/Where,
    active voice, testable terms."""
    sentence = re.sub(r"^[\s:*]+|\*+", "", text).strip()
    shalls = len(re.findall(r"\bshall\b", sentence, re.I))
    if not shalls:
        return ["%s has no 'shall' (EARS: '<When trigger,> the <system> shall <response>')" % req]
    problems = []
    if shalls > 1:
        problems.append("%s has %d 'shall's: one response per requirement, split it" % (req, shalls))
    lead = re.match(r"(?i)(when|while|where|if)\b([^,]*?)(,|\bshall\b)", sentence)
    if lead and (lead.group(3).lower() == "shall" or not lead.group(2).strip()):
        what = {"when": "trigger", "while": "state", "if": "condition", "where": "feature"}[lead.group(1).lower()]
        problems.append("%s: '%s' needs a %s and a comma before the system ('%s <%s>, %sthe <system> shall ...')"
                        % (req, lead.group(1), what, lead.group(1).capitalize(), what,
                           "then " if what == "condition" else ""))
    elif re.match(r"(?i)if\b", sentence) and not re.match(r"(?i)if\s+[^,]+,\s*then\b", sentence):
        problems.append("%s: unwanted behaviour reads 'If <condition>, then the <system> shall ...'" % req)
    elif not EARS_SHAPE.match(sentence):
        problems.append("%s is not an EARS pattern: name the system that acts ('the <system> shall'), after an "
                        "optional 'When <trigger>,', 'While <state>,', 'If <condition>, then' or 'Where <feature>,'"
                        % req)
    if EARS_PASSIVE.search(sentence):
        problems.append("%s is passive ('%s'): say what the system does ('the system shall send ...')"
                        % (req, EARS_PASSIVE.search(sentence).group(0)))
    vague = sorted({m.group(0).lower() for m in EARS_VAGUE.finditer(sentence)})
    if vague:
        problems.append("%s is untestable as worded (%s): state a measurable or enumerable response"
                        % (req, ", ".join(vague)))
    return problems


def change_class(text):
    """(class, declared, problem) from the spec's Change-Class: line. Without one the spec counts as feature;
    a value that isn't exactly one class, or two different values, is a problem and counts as feature too."""
    # Not from the Approval section, where agents may still write once the spec is approved, nor from a code block or
    # comment, where the line is an example.
    values = [v.strip() for v in CHANGE_CLASS_LINE.findall(without_section(text, "Approval", view=outline(text)))]
    distinct = sorted({v.lower() for v in values})
    if reading_problem(text):   # a reader may take a line for code or a heading, so no class in it can be trusted
        return "feature", bool(values), None
    if not values:
        return "feature", False, None
    if len(distinct) > 1:
        return "feature", True, "Change-Class is declared more than once (%s): keep one" % ", ".join(distinct)
    if distinct[0] not in CHANGE_CLASSES:
        return "feature", True, "Change-Class '%s' is not one of %s" % (values[0], ", ".join(CHANGE_CLASSES))
    return distinct[0], True, None


def class_label(text):
    cls, declared, problem = change_class(text)
    return "Change-Class %s%s" % (cls, " (the declared one is invalid)" if problem else
                                  "" if declared else " (not declared)")


def validate_spec(task, text=None):
    text = read(spec_path(task)) if text is None else text
    if blank_text(text):
        return ["no spec at %s (the analyst agent writes it)" % spec_rel(task)]
    body = comment_free(text)
    problems = []
    reqs = spec_items(body, "REQ", task)
    acs = spec_items(body, "AC", task)
    req_ids = {req for req, _ in reqs}
    ears = conf()["HARNESS_REQ_STYLE"] == "ears"
    nfr_ids = {nfr for nfr, _ in spec_items(md_section(text, "Non-functional requirements") or "", "NFR", task)}
    if ears:
        for req, rest in reqs:
            problems.extend(ears_problems(req, rest))
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
        nfr_refs = set(re.findall(r"NFR-%s-\d+" % re.escape(task), rest)) if ears else set()
        covered |= refs
        if not refs and not nfr_refs:
            problems.append("%s does not reference the requirement%s it proves" % (ac, " or NFR" if ears else ""))
        problems.extend("%s references unknown %s" % (ac, ref) for ref in sorted(refs - req_ids))
        problems.extend("%s references unknown %s" % (ac, ref) for ref in sorted(nfr_refs - nfr_ids))
        if not all(re.search(r"\b%s\b" % word, rest, re.I) for word in ("given", "when", "then")):
            problems.append("%s is not written as Given ..., when ..., then ..." % ac)
    problems.extend("%s has no acceptance criterion" % req for req in sorted(req_ids - covered))
    problems.extend(p for p in [change_class(text)[2]] + spec_reading_problems(text) if p)
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
    open_items = [q for q in bullets(md_section(text, "Open questions"))
                  if q.lower().rstrip(".") not in ("none", "n/a")]
    if open_items:
        problems.append("open questions remain: %s" % "; ".join(open_items)[:300])
    if PLACEHOLDER.search(body) or STUB_WORDS.search(body):
        problems.append("the spec still contains FILL, TODO, TBD or FIXME placeholders")
    return problems


def spec_fingerprint(task, text=None):
    """Hash of the spec (without its Approval section) and of every ADR it references."""
    text = read(spec_path(task)) if text is None else text
    digest = hashlib.sha256(frozen_text(text).encode("utf-8"))
    for adr in spec_adrs(text):
        path = adr_file(adr)
        digest.update(adr.encode("utf-8"))
        digest.update(read(path).encode("utf-8") if path else b"")
    return digest.hexdigest()


# --------------------------------------------------------------------------- skills

def skill_files():
    """{skill name: its SKILL.md}: the engine's core skills, then the project's, which win on a shared name."""
    found = {}
    for base in (ENGINE_SKILLS, SKILLS):
        for path in sorted(base.glob("*/SKILL.md")):
            found[path.parent.name] = path
    return found


def available_skills():
    return set(skill_files())


def skill_read(file_path, cwd=None):
    """The skill whose SKILL.md file_path is, or None."""
    path = Path(file_path).expanduser()
    path = (path if path.is_absolute() else ROOT / (cwd or "") / path).resolve()
    return next((name for name, f in skill_files().items() if f.resolve() == path), None)


def skill_invoked(name):
    namespace, separator, skill = name.partition(":")
    if separator:
        if namespace != "agentic-harness":
            return None
        return skill_read(ENGINE_SKILLS / skill / "SKILL.md")
    path = skill_files().get(name)
    return skill_read(path) if path else None


def load_routes():
    routes, errors = [], []
    for path in ROUTE_FILES:
        origin = rel(str(path))
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
    log_event("skill", name=name)
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
    files = skill_files()
    loaded = loaded_skills(data)
    missing = [(skill, why) for skill, why in sorted(required_skills(path).items())
               if skill in files and skill not in loaded]
    if not missing:
        return None
    return ("  - Load these skills before editing %s, then retry:\n%s"
            % (path, "\n".join("      %s: read %s (or invoke the skill). Required by: %s"
                               % (skill, rel(str(files[skill])), why) for skill, why in missing)))


# --------------------------------------------------------------------------- guardrail rules

class Rule(object):
    def __init__(self, severity, target, content, message, origin, source):
        self.severity = severity
        self.target = target      # compiled path regex, or None for Bash commands (@bash)
        self.content = content
        self.message = message
        self.origin = origin
        self.source = source


def load_rules():
    rules, errors = [], []
    for source, path in zip(("core", "project"), RULE_FILES):
        origin = rel(str(path))
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
            rules.append(Rule(parts[0], target, content, parts[3], where, source))
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


def log_rule_hits(hits):
    """One `rule` event per rule that matched, so harness.py report can tell which rules earn their place."""
    for rule, _ in hits:
        log_event("rule", rule=rule.message[:120], origin=rule.origin, severity=rule.severity)


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
# Not <<<, a here-string: the lines after it are commands, not a body.
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SETTING_ASSIGNMENT = re.compile(r"^(HARNESS_[A-Z0-9_]+|SKIP_BUILD)=")
PROTECTED_MENTION = re.compile(r"(?:^|[\s'\"/=(:])(backbone/|scripts/harness/|\.claude/|AGENTS\.md|CLAUDE\.md"
                               r"|\.git/|harness-attest\.pub)")
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
            elif quote == '"' and (ch == "`" or command.startswith("$(", i)):
                # A quote inside "$(...)" belongs to the substitution, not to the string around it.
                end = closing_paren(command, i + 1) if ch == "$" else command.find("`", i + 1)
                end = len(command) if end < 0 else end
                current.append(command[i + 1:end + 1])
                i = end
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


GIT_DIRS = []   # resolved once per process


def git_dirs():
    """The checkout's .git (a file in a linked worktree), its git directory and the repository's common one, where
    git keeps its data and the harness its records: events, cost ledgers, run locks."""
    if not GIT_DIRS:
        found = {os.path.realpath(str(ROOT / ".git"))}
        found.update(os.path.realpath(line) for line in git("rev-parse", "--path-format=absolute", "--absolute-git-dir",
                                                            "--git-common-dir").splitlines() if line.strip())
        GIT_DIRS.extend(sorted(found))
    return GIT_DIRS


def in_git_dir(path_str, cwd=None):
    path = os.path.expandvars(os.path.expanduser(path_str))
    if not os.path.isabs(path):
        path = os.path.join(cwd or str(ROOT), path)
    full = os.path.realpath(path)
    return any(full == d or full.startswith(d + os.sep) for d in git_dirs())


def protected_path(path_str, cwd):
    """Repository-relative path if path_str points into a shell-protected harness path (or the path itself, when it
    is in a git directory outside the checkout), else None."""
    if not path_str or path_str.startswith("-"):
        return None
    path = os.path.expandvars(os.path.expanduser(path_str))
    if not os.path.isabs(path):
        path = os.path.join(cwd or str(ROOT), path)
    full, root = os.path.realpath(path), os.path.realpath(str(ROOT))
    if full != root and not full.startswith(root + os.sep):
        return path_str if in_git_dir(full) else None
    name = os.path.relpath(full, root).replace(os.sep, "/")
    return name if any(re.search(p, name) for p in SHELL_PROTECTED) else None


GIT_DIR_REFUSAL = ("%s is in the git directory, which holds git's own data and the harness's records (events, cost "
                   "ledgers, run locks); agents don't write there.")
# A path the hooks can't resolve (a $VAR or a command substitution) that still points at the git directory or the
# harness's records in it.
GIT_DIR_HINT = re.compile(r"git-dir|git-common-dir|rev-parse|(?:^|/)\.git(?:/|$)|\bGIT_(?:DIR|COMMON_DIR)\b|"
                          r"(?:^|/)harness/(?:costs|locks|events|runs|sessions|receipts|intake|STOP)\b")
GIT_SUBSTITUTION = re.compile(r"\$\([^)]*\bgit\b[^)]*\)|`[^`]*\bgit\b[^`]*`")


def find_starts(words):
    """The paths find searches: its operands before the first expression."""
    starts = []
    for word in words[1:]:
        if word.startswith("-") or word in ("(", "!"):
            break
        starts.append(word)
    return starts or ["."]


UNKNOWN_DIR = "/.harness-unresolved-directory"   # the cwd after a cd the hooks can't resolve


TEMP_SUBSTITUTION = re.compile(r"\$\(\s*mktemp\b[^)]*\)|`\s*mktemp\b[^`]*`")
TEMP_VARIABLE = re.compile(r"\$(?:\{(TMPDIR|TMP|TEMP)\}|(TMPDIR|TMP|TEMP)\b)")


def shell_path(path, cwd, env=None):
    """path as the shell would resolve it against cwd: variables the command assigned earlier (env; a loop's list,
    or None when the hooks can't know the value), $PWD, a temp folder for $TMPDIR and $(mktemp), ~ and the
    environment's variables: (the absolute paths it can name, whether an expansion is left that the hooks can't
    resolve). A glob gives the paths it matches now, dotfiles only by a dot."""
    here = cwd if cwd and cwd != UNKNOWN_DIR else str(ROOT)
    variants = [TEMP_SUBSTITUTION.sub(lambda _: os.path.join(tempfile.gettempdir(), "mktemp"), path)]
    for name, value in (env or {}).items():
        pattern = re.compile(r"\$(?:\{%s\}|%s(?![A-Za-z0-9_]))" % (re.escape(name), re.escape(name)))
        expanded = []
        for text in variants:
            if not pattern.search(text) or value is None:
                expanded.append(text)
            else:
                expanded.extend(pattern.sub(lambda _: item, text) for item in (value if isinstance(value, list)
                                                                                else [value]))
        variants = expanded
    fulls, unresolved = [], False
    for text in variants:
        text = re.sub(r"\$(?:\{PWD\}|PWD(?![A-Za-z0-9_]))", lambda _: here, text)
        text = TEMP_VARIABLE.sub(lambda m: os.environ.get(m.group(1) or m.group(2)) or tempfile.gettempdir(), text)
        text = os.path.expandvars(os.path.expanduser(text))
        unresolved = unresolved or bool(re.search(r"[$`]", text)) or (cwd == UNKNOWN_DIR and not os.path.isabs(text))
        full = text if os.path.isabs(text) else os.path.join(here, text)
        # A glob that matches nothing stays as written, as the shell leaves it.
        fulls.extend((glob.glob(full) or [full]) if any(c in full for c in "*?[") else [full])
    return fulls, unresolved


def assigned_value(value, env):
    """What VAR=value gives a later path: the text with earlier variables in it, a temp folder for $(mktemp), or None
    for a command substitution whose output the hooks can't know."""
    value = TEMP_SUBSTITUTION.sub(lambda _: os.path.join(tempfile.gettempdir(), "mktemp"), value)
    if re.search(r"\$\(|`", value):
        return None
    for name, known in env.items():
        if isinstance(known, str):
            value = re.sub(r"\$(?:\{%s\}|%s(?![A-Za-z0-9_]))" % (re.escape(name), re.escape(name)),
                           lambda _: known, value)
    return value


def reaches_git_dir(full):
    """Whether a delete or write at full can touch a git directory: it is one, is in one, or holds one (find walks
    down from it)."""
    real = os.path.realpath(full)
    return any(real == d or real.startswith(d + os.sep) or d.startswith(real.rstrip(os.sep) + os.sep)
               for d in git_dirs())


GIT_PATTERN = re.compile(r"(?:^|/|\*)\.git(?:/\*?)?$")
GIT_NAMES = []   # every name in the git directories, read once per process
# Names the harness and git create there that may not exist yet when a find is checked.
GIT_RECORD_NAMES = {".git", "events.jsonl", "task-1.jsonl", "task-1.lock", "orca.lock", "adr.lock", "intake.lock",
                    "snapshot.json", "STOP", "1", "1.1", "index", "index.lock", "HEAD", "config", "packed-refs",
                    "ORIG_HEAD", "FETCH_HEAD", "x.pack", "x.idx", "1-1.log", "x.receipt.txt", "intake-next"}


def writes_files(words):
    """Whether a command writes or deletes the files it names: rm, mv, cp, ln, tee, dd, truncate, sed -i, perl -i."""
    name = program(words)
    writers = MUTATORS + COPY_PROGRAMS + ("dd", "tee", "shred", "patch")
    return name in writers or (name in ("sed", "gsed", "perl") and any(
        w.startswith(("-i", "-pi")) or w == "--in-place" for w in words[1:]))


def git_dir_names():
    """The names of every file and folder in the git directories (None when there are too many to read)."""
    if not GIT_NAMES:
        names, count = set(), 0
        for top in git_dirs():
            names.add(os.path.basename(top))
            for _, dirs, files in os.walk(top) if os.path.isdir(top) else []:
                names.update(dirs)
                names.update(files)
                count += len(dirs) + len(files)
                if count > 200000:
                    GIT_NAMES.append(None)
                    return None
        GIT_NAMES.append(names)
    return GIT_NAMES[0]


def find_walk_safe(words, starts):
    """Whether a find that deletes or writes can't reach the git directory: its start folders don't hold it, its
    expression prunes or excludes .git (-path ./.git -prune, -not -path './.git/*'), or its -name patterns match no
    name in it. A negated -name could match anything."""
    if not any(reaches_git_dir(f) for f in starts):
        return True
    if any(in_git_dir(f) for f in starts):
        return False
    expression = words[1 + len(find_starts(words)):]
    for i, word in enumerate(expression[:-1]):
        if word in ("-path", "-wholename", "-name", "-ipath", "-iname") and GIT_PATTERN.search(expression[i + 1]):
            if expression[i + 2:i + 3] == ["-prune"] or expression[i - 1:i] in (["!"], ["-not"]):
                return True
    patterns, negated, i = [], False, 0
    while i < len(expression):
        word = expression[i]
        if word in ("!", "-not"):
            negated = True
        elif word in ("-name", "-iname") and i + 1 < len(expression):
            if negated:
                return False
            patterns.append((expression[i + 1], word == "-iname"))
            i += 1
        else:
            negated = False
        i += 1
    names = git_dir_names()
    if not patterns or names is None:
        return False
    names = names | GIT_RECORD_NAMES
    return not any(fnmatch.fnmatchcase(n.lower() if folded else n, p.lower() if folded else p)
                   for p, folded in patterns for n in names)


def safe_producer(producer, cwd, env):
    """Whether the command piped into xargs names no file in the git directory: a find that can't reach it, or git
    listing tracked files."""
    name = program(producer)
    if name == "git":
        return git_subcommand(producer) in ("ls-files", "ls-tree", "diff", "grep")
    if name == "find":
        starts = [f for start in find_starts(producer) for f in shell_path(start, cwd, env)[0]]
        return find_walk_safe(producer, starts)
    return False


def git_dir_findings(prog, words, segment, cwd, env=None):
    """Deletes and writes that can reach the git directory, which written_paths alone doesn't name: find -delete or a
    writer run by -exec from a folder that holds it (unless the walk prunes .git or its names can't match), a glob
    or a variable that resolves into it, $PWD, and a write whose target the hooks can't resolve at all."""
    run, _ = runner_command(prog, words)
    destroys = prog == "find" and ("-delete" in words or bool(run and writes_files(run[program_index(run):])))
    starts = find_starts(words) if destroys else []
    for path in written_paths(segment, words) + starts:
        fulls, unresolved = shell_path(path, cwd, env)
        if unresolved:
            return [GIT_DIR_REFUSAL % path if GIT_DIR_HINT.search(path) else
                    "it writes or deletes %s, a path from an expansion the hooks can't resolve (a command "
                    "substitution, read, or a cd they can't follow): name the path." % path]
        if path in starts:
            if not find_walk_safe(words, fulls):
                return ["find deletes or writes from %s, which holds the git directory: prune it (-path ./.git -prune "
                        "-o ...), or start in a folder that doesn't hold it." % path]
        elif any(in_git_dir(f, cwd) for f in fulls):
            return [GIT_DIR_REFUSAL % path]
    if (prog in MUTATORS or prog in COPY_PROGRAMS or destroys) and GIT_SUBSTITUTION.search(segment):
        return [GIT_DIR_REFUSAL % "a path from git rev-parse"]
    return []


def thin_mode():
    return ENGINE != ROOT and lock().get("mode") == "thin"


def user_agents_dir(source):
    if source == "codex":
        return Path(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")) / "agents"
    if os.environ.get("OPENCODE_CONFIG_DIR"):
        return Path(os.environ["OPENCODE_CONFIG_DIR"]) / "agents"
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "opencode" / "agents"


def user_agent_files():
    """(engine copy, user-level path) of each role agent a thin session start installs for Codex and OpenCode."""
    if not thin_mode():
        return []
    return [(agent, user_agents_dir(source) / agent.name)
            for source, (folder, suffix, _) in USER_AGENTS.items()
            for agent in sorted((ENGINE / folder).glob("*" + suffix))]


def install_user_agents(source):
    """Install or refresh the pinned engine's role agents for source; session-start lines saying what happened."""
    target, cli = user_agents_dir(source), USER_AGENTS[source][2]
    changed, kept, failed = [], [], []
    for agent, path in user_agent_files():
        if path.parent != target:
            continue
        text = agent.read_text(encoding="utf-8")
        try:
            current = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        except OSError:
            failed.append(path.name)
            continue
        if current == text:
            continue
        if current is not None and USER_AGENT_MARK not in current:
            kept.append(str(path))
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(".%s.harness-tmp" % path.name)
            temporary.write_text(text, encoding="utf-8")
            os.replace(str(temporary), str(path))
            changed.append(path.stem)
        except OSError:
            failed.append(path.name)
    lines = []
    if changed:
        lines.append("Installed the pinned engine's role agents (%s) in %s; restart %s to load them."
                     % (", ".join(changed), target, cli))
    if kept:
        lines.append("Kept %s: not written by the harness, so the harness's agent of that name isn't installed. The "
                     "user renames or removes it to use the harness's." % ", ".join(kept))
    if failed:
        lines.append("Could not install the role agents %s in %s." % (", ".join(failed), target))
    return lines


def thin_paths():
    """The full-install paths that role agents' instructions name, as they are in a thin project."""
    return ("This project runs the agentic harness in thin mode: it has no AGENTS.md and no scripts/harness/ folder; "
            "the pinned engine in %s supplies them. Where instructions name those paths:\n"
            "- `python3 scripts/harness/lib/harness.py <command>` is `python3 %s <command>`\n"
            "- `AGENTS.md` (the agent rules) is `%s`\n"
            "- `scripts/harness/routing.core.conf` (the core routes) is `%s`\n"
            "- a core skill's `.claude/skills/<name>/SKILL.md` is `%s/<name>/SKILL.md` unless the project has its own"
            % (ENGINE, shlex.quote(str(ENGINE / "scripts/harness/lib/harness.py")), ENGINE / "AGENTS.md",
               ENGINE / "scripts/harness/routing.core.conf", ENGINE_SKILLS))


def install_path(path_str, cwd):
    """Which harness install (engine cache, plugin or installed role agents) path_str is in, or contains, else None."""
    if not path_str or path_str.startswith("-"):
        return None
    path = os.path.expandvars(os.path.expanduser(path_str))
    if not os.path.isabs(path):
        path = os.path.join(cwd or str(ROOT), path)
    full, root = os.path.realpath(path), os.path.realpath(str(ROOT))
    for variable, label in INSTALL_DIRS:
        base = os.environ.get(variable)
        if not base:
            continue
        base = os.path.realpath(base)
        if root == base or root.startswith(base + os.sep):
            continue   # a project inside the install (the harness developed in thin mode) keeps its own gates
        if full == base or full.startswith(base + os.sep) or base.startswith(full.rstrip(os.sep) + os.sep):
            return label
    for _, agent in user_agent_files():
        agent = os.path.realpath(str(agent))
        if full == agent or agent.startswith(full.rstrip(os.sep) + os.sep):
            return "the harness's role agents"
    return None


def written_paths(segment, words):
    """Paths a segment writes, moves or deletes: redirection targets and mutating programs' operands."""
    paths = re.findall(r"(?:^|[^<>&0-9])(?:[0-9]?>>?|&>>?)\s*('[^']*'|\"[^\"]*\"|[^\s;|&<>]+)", segment)
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


AWK_RUNS = re.compile(r"\bsystem\s*\(|\|\s*&?\s*getline|\b(?:print|printf)\b[^;}]*\|\s*&?\s*[\"\w$(]")
# git settings whose value is a command git runs (an alias that starts with ! included).
GIT_COMMAND_KEYS = re.compile(r"(?i)^(?:core\.(?:sshcommand|pager|editor|askpass|fsmonitor|gitproxy|hookspath)|"
                              r"credential\.|diff\.external|diff\..+\.(?:textconv|command)|filter\.|"
                              r"merge\..+\.driver|gpg\.(?:.+\.)?program|sequence\.editor|pager\.|web\.browser|"
                              r"browser\.|uploadpack\.|receivepack\.|remote\..+\.(?:uploadpack|receivepack|proxy)|"
                              r"ssh\.variant|interactive\.difffilter|man\.|core\.alternaterefscommand)")


def git_command_config(words):
    """Why a git call sets a command for git to run, or None: -c, --config-env or git config with an alias that starts
    with ! or a key whose value git runs (core.sshCommand, core.pager, credential helpers, filters...)."""
    pairs = []
    for i, word in enumerate(words[1:], 1):
        if word == "-c" and i + 1 < len(words):
            pairs.append(words[i + 1].partition("=")[::2])
        elif word.startswith("--config-env"):
            pairs.append((word.split("=", 1)[-1].partition("=")[0], "!"))
    if git_subcommand(words) == "config":
        rest = [w for w in words[words.index("config") + 1:] if not w.startswith("-")]
        if len(rest) >= 2 and not any(w in GIT_CONFIG_READS for w in words):
            pairs.append((rest[0], rest[1]))
    for key, value in pairs:
        if GIT_COMMAND_KEYS.match(key) or (key.lower().startswith("alias.") and value.lstrip().startswith("!")):
            return ("git %s=... sets a command git runs, which the hooks can't read; run the command itself, or "
                    "--no-pager." % key)
    return None


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
    found = []
    if PROTECTED_MENTION.search(code) and CODE_WRITES.search(code):
        found.append("%s writes to harness-protected paths (backbone/, scripts/harness/, .claude/, git hooks, "
                     "harness-attest.pub); use the Write/Edit tools so the gates see the change." % label)
    if ENGINE_IMPORT.search(code) or (ENGINE_NAME.search(code) and CODE_RUNS.search(code)):
        found.append("%s runs the harness engine from code the hooks don't read; run harness.py itself, with the "
                     "commands agents may run." % label)
    return found


# The commands only the user, CI, an agent factory or an Orca automation's precheck runs. Their dry runs (where they
# have one) change nothing.
USER_COMMANDS = ("run", "orca", "orca-nightly", "snapshot", "linear", "intake", "delivery-record", "ci-judge",
                 "ci-protect")
FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
PLANNING_COMMANDS = ("orca", "orca-nightly", "linear")
ENGINE_MODULES = ("harness", "launcher", "thin")
ENGINE_NAME = re.compile(r"\b(?:harness|launcher|thin)\.py\b")
ENGINE_IMPORT = re.compile(r"\brunpy\b|\b(?:import|from)\s+(?:harness|launcher|thin)\b|"
                           r"\b(?:import_module|__import__)\s*\(\s*['\"](?:harness|launcher|thin)\b")
CODE_RUNS = re.compile(r"\bexec(?:file)?\s*\(|\bcompile\s*\(|\bimportlib\b|\bsubprocess\b|\bchild_process\b|\bsystem\s*\(|"
                       r"\bos\.(?:system|popen|exec\w*|spawn\w*)\b|\b(?:spawn|exec)Sync\b")
USER_COMMAND_REFUSAL = ("harness.py %s is for the user, CI, an agent factory or an Orca automation's precheck, not "
                        "agents, however the engine is started: run, orca, orca-nightly, snapshot, linear, intake, "
                        "delivery-record, ci-judge, ci-protect and pin are theirs.")


def engine_script(word):
    """The harness script (harness.py, launcher.py, thin.py) word names, a glob included, or None."""
    base = word.rsplit("/", 1)[-1]
    if any(c in base for c in GLOB_CHARS):
        # '*.py' names every script; 'h*.py' or 'harness.p?' aims at these.
        if not re.sub(r"[%s]" % re.escape(GLOB_CHARS), "", base.rsplit(".", 1)[0]):
            return None
        return next((name for name in INSTALL_SCRIPTS if fnmatch.fnmatch(name, base)), None)
    return base if base in INSTALL_SCRIPTS else None


def is_runtime(word):
    name = program([word])
    return name in INTERPRETERS or bool(RUNTIMES.fullmatch(name))


def redirections(words):
    """(words without their redirections, [(operator, target)]): < x, 2>/dev/null, <<EOF and <<< text, wherever they
    stand, a redirection before the command included."""
    kept, found, i = [], [], 0
    while i < len(words):
        m = REDIRECTION.match(words[i]) if not words[i].startswith(("<(", ">(")) else None
        if not m:
            kept.append(words[i])
            i += 1
            continue
        rest = words[i][m.end():]
        found.append((m.group(1), rest if rest else (words[i + 1] if i + 1 < len(words) else "")))
        i += 1 if rest else 2
    return kept, found


XARGS_VALUE_FLAGS = ("-I", "-J", "-L", "-n", "-P", "-s", "-E", "-e", "-a", "-d", "-R", "-S")


def runner_command(prog, words):
    """(the command words, its replacement token) that xargs, parallel or find -exec runs with arguments from its
    input or its search, or (None, None)."""
    if prog in ("xargs", "parallel"):
        i, token = 1, "{}"
        while i < len(words) and words[i].startswith("-"):
            flag = words[i]
            if flag[:2] in ("-I", "-J") and flag[:2] in XARGS_VALUE_FLAGS:
                token = flag[2:] or (words[i + 1] if i + 1 < len(words) else "")
                i += 1 if flag[2:] else 2
            elif flag in XARGS_VALUE_FLAGS:
                i += 2
            else:
                i += 1
        return words[i:], token
    at = next((i for i, w in enumerate(words) if w in FIND_EXEC), None) if prog == "find" else None
    if at is None:
        return None, None
    end = next((j for j in range(at + 1, len(words)) if words[j] in (";", "+")), len(words))
    return words[at + 1:end], "{}"


def script_operand(words):
    """The script an interpreter command runs ("" when it reads it from stdin), or None for -c and -m code."""
    i = 1
    while i < len(words):
        word = words[i]
        if word in ("-c", "-m"):
            return None
        if word in ("-X", "-W"):
            i += 2
            continue
        if word == "-" or not word.startswith("-"):
            return "" if word == "-" or STDIN_FILE.search(word) or word.startswith(("<(", ">(")) else word
        i += 1
    return ""


def program_findings(prog, words, producer=None, cwd=None, env=None):
    """A program the hooks can't read: an interpreter's program from stdin (a pipe or a file redirect; a literal
    heredoc or here-string is read), and a shell or interpreter a runner (xargs, parallel, find -exec) gives a program
    from its input. A program in a file runs as the repo's code, which the gates and the judge check."""
    command, redirects = redirections(words)
    command = command[program_index(command):]
    name = program(command)
    versions = VERSION_FLAGS + (("-v",) if name.startswith(SHORT_VERSION_FLAG) else ())
    reader = is_runtime(name) or name in SHELLS + ("fish",)
    if reader and not any(w in versions for w in command[1:]) and script_operand(command) == "":
        literal = any(op in ("<<", "<<-") or (op == "<<<" and not re.search(r"[$`]", target))
                      for op, target in redirects)
        if not literal:
            return ["It runs %s on a program from stdin (a pipe or a redirect), which the hooks can't read: put the "
                    "program in a file, or in a heredoc." % name]
    run, token = runner_command(prog, words)
    if not run:
        return []
    run = run[program_index(run):]
    from_input = lambda w: not w or "{}" in w or bool(token and token in w)
    name = program(run)
    operand = script_operand(run) if is_runtime(name) else None
    module = run[run.index("-m") + 1] if is_runtime(name) and "-m" in run[:-1] else None
    if from_input(run[0]) or name in SHELLS or (operand is not None and (from_input(operand) or engine_script(operand))) \
            or module in ENGINE_MODULES + ("runpy",):
        return ["It runs a program or shell whose code comes from %s's input or search, which the hooks can't read; "
                "run the script by its path, with its arguments written out." % prog]
    if prog in ("xargs", "parallel") and writes_files(run) and not (producer and safe_producer(producer, cwd, env)):
        return ["%s %s changes the files its input names, which the hooks can't read: name them, or pipe in a find "
                "that prunes .git or git ls-files." % (prog, name)]
    return []


def engine_findings(prog, words, written):
    """Why a command that starts, copies or aliases the harness engine is refused to agents. The engine runs from its
    own path, where the hooks read its command; a copy, an alias, a module run or a script word from an expansion
    would run any command unread. A program from stdin or from a runner's input is program_findings'."""
    script = next((i for i, w in enumerate(words) if engine_script(w)), None)
    run = script is not None and (script == 0 or any(w in INTERPRETERS or RUNTIMES.fullmatch(w)
                                                     for w in map(program, ([w] for w in words[:script]))))
    if script is not None and (prog in COPY_PROGRAMS or prog == "alias" or (written and not run)):
        return ["It copies, links or aliases the harness engine (%s); agents run it where it is, so the hooks read "
                "its command." % engine_script(words[script])]
    if script is None and "-m" in words[:-1] and words[words.index("-m") + 1] in ENGINE_MODULES + ("runpy",):
        script = words.index("-m") + 1
    if script is None:
        runtime = prog in INTERPRETERS or RUNTIMES.fullmatch(prog)
        operand = next((w for w in words[1:] if not w.startswith("-")), "") if runtime else ""
        if not EXPANSION.search(operand):
            return []
        script = words.index(operand)
    command = next((w for w in words[script + 1:] if not w.startswith("-")), "")
    if command == "pin":
        return ["pin moves the engine release this project pins, and with it every gate; only the user does that, in "
                "their own terminal."]
    if EXPANSION.search(words[script]) and any(w in USER_COMMANDS for w in words[script + 1:]):
        return [USER_COMMAND_REFUSAL % "<expansion>"]
    if EXPANSION.search(command):
        return ["It runs the harness engine with a command from an expansion ($... or `...`), which the hooks can't "
                "read; write the command out."]
    if command in USER_COMMANDS and not (command in PLANNING_COMMANDS and "--dry-run" in words):
        return [USER_COMMAND_REFUSAL % command]
    return []


def shell_findings(command, cwd=None, depth=0):
    """Blocking problems with a shell command, beyond the @bash guardrail rules."""
    found = []
    command, bodies = split_heredocs(command)
    if depth < 3:
        for inner in scan_expansions(command)[0]:
            found.extend(shell_findings(inner, cwd, depth + 1))
    segments = split_segments(command)
    env, dirs = {}, []   # what the command itself assigns, and pushd's stack
    for index, (segment, op) in enumerate(segments):
        assignments, words = shell_words(segment)
        while words and words[0] in SHELL_KEYWORDS:
            words = words[1:]
        for assignment in assignments:
            if SETTING_ASSIGNMENT.match(assignment):
                found.append("Setting %s from the shell overrides a harness setting or skips a check; only the user "
                             "may do that, in their own terminal." % assignment.split("=", 1)[0])
        if not words:
            for assignment in assignments:
                name, _, value = assignment.partition("=")
                env[name] = assigned_value(value, env)
            continue
        if words[0] in ("for", "select") and words[2:3] == ["in"]:
            items = words[3:]
            env[words[1]] = None if any(re.search(r"\$\(|`", w) for w in items) else items
            continue
        if words[0] == "read":
            names = [w for w in words[1:] if not w.startswith("-")]
            env.update({name: None for name in names})
        if words[0] in ("-S", "--split-string") or words[0].startswith(("-S", "--split-string=")):
            split = " ".join(([words[0][2:]] if words[0][:2] == "-S" and len(words[0]) > 2 else
                              [words[0].split("=", 1)[1]] if "=" in words[0] else []) + words[1:])
            if depth < 3:
                found.extend(shell_findings(split, cwd, depth + 1))
            continue
        prog = program(words)
        if prog in ("cd", "pushd"):
            target = next((w for w in words[1:] if not w.startswith("-")), os.path.expanduser("~"))
            fulls, unresolved = shell_path(target, cwd, env)
            if prog == "pushd":
                dirs.append(cwd)
            cwd = UNKNOWN_DIR if unresolved or len(fulls) != 1 else fulls[0]
            continue
        if prog == "popd":
            cwd = dirs.pop() if dirs else UNKNOWN_DIR
            continue
        producer = shell_words(segments[index - 1][0])[1] if index > 0 and segments[index - 1][1] == "|" else None
        found.extend(engine_findings(prog, words, written_paths(segment, words)))
        found.extend(program_findings(prog, words, producer, cwd, env))
        found.extend(git_dir_findings(prog, words, segment, cwd, env))
        for path in [full for written in written_paths(segment, words) for full in shell_path(written, cwd, env)[0]]:
            label = install_path(path, cwd)
            if label:
                found.append("%s is in %s, which decides this project's gates; agents may not change it."
                             % (path, label))
                continue
            name = protected_path(path, cwd)
            if name and (name == ".git" or name.startswith(".git/") or in_git_dir(path, cwd)):
                found.append(GIT_DIR_REFUSAL % name)
            elif name:
                found.append("Shell writes to %s skip the harness gates; change it with the Write or Edit tool "
                             "(or not at all, for verdicts and user-only settings)." % name)
        if prog == "git":
            found.extend(git_findings(words))
            configured = git_command_config(words)
            if configured:
                found.append(configured)
        elif prog in ("awk", "gawk", "mawk", "nawk") and AWK_RUNS.search(segment):
            found.append("awk runs a command (system(), or a pipe to or from one), which the hooks can't read; run the "
                         "command itself.")
        elif prog in ("source", ".") and (len(words) < 2 or script_operand(["sh"] + words[1:]) == ""):
            found.append("%s runs commands from stdin or a process substitution, which the hooks can't read; source a "
                         "file." % prog)
        elif prog == "gh" and profile() in NO_MERGE_PROFILES and (
                words[1:3] == ["pr", "merge"] or (words[1:2] == ["api"] and any(MERGE_ENDPOINT.search(w) for w in words))):
            found.append("Merging is refused under HARNESS_PROFILE=%s: only a human merges, on GitHub." % profile())
        elif prog == "find" and ("-delete" in words or ("-exec" in words and "rm" in words)):
            start = next((w for w in words[1:] if not w.startswith("-")), ".")
            if start.rstrip("/") in ("", "~", "$HOME", "${HOME}") or (start.startswith("/") and start.count("/") <= 1):
                found.append("find ... -delete on %s deletes from the filesystem root or home." % start)
        elif prog in SHELLS and depth < 3:
            if "-c" in words and words.index("-c") + 1 < len(words):
                found.extend(shell_findings(words[words.index("-c") + 1], cwd, depth + 1))
        elif prog == "eval" and depth < 3:
            found.extend(shell_findings(" ".join(words[1:]), cwd, depth + 1))
        elif prog in INTERPRETERS or RUNTIMES.fullmatch(prog):
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
        elif prog in INTERPRETERS or RUNTIMES.fullmatch(prog):
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


def code_fingerprint(include_backbone=False):
    """Git tree hash of the working tree, hashed from the files' content (tracked and untracked, ignores respected),
    excluding backbone/ unless include_backbone. Identical code gives an identical hash, committed or not."""
    git_dir = git("rev-parse", "--absolute-git-dir").strip()
    if not git_dir:
        return None
    tmp = tempfile.mkdtemp(prefix="harness-index-")
    try:
        index = os.path.join(tmp, "index")
        if os.path.isfile(os.path.join(git_dir, "index")):
            shutil.copyfile(os.path.join(git_dir, "index"), index)
            # Git skips hashing a file whose size and timestamps match its index entry, unless the entry is as new as
            # the index file. Dated 1970 (not 0, which git reads as no date), the copy is older than every entry, so
            # git hashes every file: a same-size edit made within the second of an index write is still seen.
            os.utime(index, (1, 1))
        env = dict(os.environ, GIT_INDEX_FILE=index)

        def run(*args):
            return subprocess.run(["git"] + list(args), cwd=str(ROOT), env=env, capture_output=True, text=True)

        run("add", "-A", "--", ".")
        if not include_backbone:
            run("rm", "-r", "--cached", "-q", "--ignore-unmatch", "--", "backbone")
        result = run("write-tree")
        return result.stdout.strip() if result.returncode == 0 else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def computed_once(compute):
    """compute, memoized: the first call runs it, later calls return its value. Hashing the working tree costs
    seconds on a large checkout, so a command that checks many tasks shares one fingerprint."""
    memo = []

    def get():
        if not memo:
            memo.append(compute())
        return memo[0]
    return get


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


def ac_test_references(task, rev=None, test_paths_pattern=None):
    """{AC id: [test files mentioning it]}, searching tracked and untracked files outside backbone/, or the files of
    commit rev."""
    test_paths = re.compile(test_paths_pattern or conf()["HARNESS_TEST_PATHS"])
    pattern = "AC-%s-[0-9]+" % re.escape(task).replace("\\-", "-")
    output = git("grep", "-I", *(("-o", "-E", pattern, rev) if rev else ("--untracked", "-o", "-E", pattern)))
    found = {}
    for line in output.splitlines():
        name, _, match = (line[len(rev) + 1:] if rev else line).partition(":")
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
    acs = [ac for ac, _ in spec_items(comment_free(spec_text), "AC", task)]
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
    seconds = round(time.time() - started, 1)
    log_event("tests-run", command=command, exit=exit_code, seconds=seconds)
    return {"command": command, "exit": exit_code, "seconds": seconds,
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
                   "test_run": report.get("test_run"), "sandbox": sandbox.evidence(conf()["HARNESS_SANDBOX_BACKEND"])}
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
                     "the user's decision on the findings", debug_class(task) if kind == "judge" else None)
            note += ". Escalated after %d failed rounds: the task is BLOCKED (backbone/escalations.md); " \
                    "continue with another task." % consecutive_fails(recent)
    emit({"systemMessage": note})


# --------------------------------------------------------------------------- autonomy
# In autonomous mode no human answers questions in the loop. The harness itself approves low-risk specs
# (deterministically, from the spec and later the diff), and everything else becomes an escalation:
# the task is parked with a BLOCKED note and an entry in backbone/escalations.md, and work moves on.

def autonomous():
    return conf()["HARNESS_AUTONOMY"] == "autonomous"


def profile():
    """The organisation profile. Unlike other keys, the environment can add a profile but never remove the one
    harness.conf sets: HARNESS_PROFILE= in a shell must not lift a no-merge policy."""
    names = {parse_conf(read(CONF_FILE)).get("HARNESS_PROFILE", ""), os.environ.get("HARNESS_PROFILE", "")}
    if os.environ.get("TRIPLE_MODE") == "1":
        names.add("triple")
    return next((name for name in NO_MERGE_PROFILES if name in names), next((n for n in names if n), ""))


def no_merge_refusal(command, argv):
    """Why the profile refuses this coordinator call, or None."""
    name = profile()
    if name not in NO_MERGE_PROFILES:
        return None
    if command == "orca-nightly":
        return ("orca-nightly: refused under HARNESS_PROFILE=%s: scheduled backlog runs merge unattended; run "
                "harness.py orca --pr yourself and merge the pull requests by hand" % name)
    flags = [flag for flag in ("--merge", "--trust") if flag in argv]
    if flags:
        return ("orca: %s refused under HARNESS_PROFILE=%s: only a human merges; use --pr, which opens pull requests "
                "and never merges" % (" and ".join(flags), name))
    return None


def halt_file():
    common = git("rev-parse", "--git-common-dir").strip()
    base = Path(common) if common and os.path.isabs(common) else ROOT / (common or ".git")
    return base / "harness" / "STOP"


def task_line(task, text=None):
    """(index, line) of task's line in 3-TASKS.md (outside comments), or (None, None)."""
    lines = outline(read(TASKS) if text is None else text).splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and task_id_at(lines, i) == task:
            return i, line
    return None, None


def blocked_tasks(text):
    lines = outline(text).splitlines()
    return {task_id_at(lines, i) for i, line in enumerate(lines)
            if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and BLOCKED_NOTE.search(line)}


def policy_approval(text):
    """{'rule', 'base'} of a policy approval line in the spec text, or None."""
    m = POLICY_APPROVAL.search(approval_section(text) or "")
    if not m:
        return None
    base = re.search(r"\bbase ([0-9a-f]{7,40})", m.group(2))
    return {"rule": m.group(1), "base": base.group(1) if base else None}


def diff_names(*args):
    """The paths git diff args lists. A move lists both: with rename detection only its new path shows, so moving code
    into the docs, or a file out of a sensitive or harness path, would go unseen."""
    return [n for n in git("diff", "--name-only", "--no-renames", "-z", *args).split("\0") if n]


def changed_files(base):
    """Code files changed since commit base (committed, staged, unstaged or untracked), outside backbone/."""
    names = set(diff_names(base)) if base else set()
    names |= set(n for n in git("ls-files", "-z", "--others", "--exclude-standard").split("\0") if n)
    if not base:
        names |= set(n for n in git("ls-files", "-z").split("\0") if n)
    return sorted(n for n in names if not n.startswith("backbone/"))


def risk_reasons(task, base=None):
    """Why a task is not low-risk (empty list = low risk). With base, the diff since then is assessed too."""
    text = read(spec_path(task))
    changed = changed_files(base) if base is not None else None
    return class_risks(text) + content_risks(text, changed) + class_mismatch(text, changed or []) + source_risks(text)


def source_risks(text):
    """An untrusted sender's request (its '## Source' section, written by intake) always waits for a person."""
    verdicts = source_verdicts(text)
    if verdicts and any(v != "trusted" for v in verdicts):
        return ["the request came from an untrusted sender (see its '## Source' section): a person approves it, "
                "not policy"]
    return []


def class_risks(text):
    """Why the spec's Change-Class alone rules out policy approval: feature and schema work is the user's to approve."""
    cls, declared, problem = change_class(text)
    if cls not in USER_APPROVED_CLASSES:
        return []
    why = ("the spec's Change-Class is invalid (see spec-check), so it counts as feature" if problem else
           "Change-Class %s" % cls if declared else "no Change-Class declared, so it counts as feature")
    return ["%s: the user approves it, not policy" % why]


def class_mismatch(text, changed):
    """The changed files a docs Change-Class can't describe: anything that isn't documentation (HARNESS_DOC_PATHS)."""
    if change_class(text)[0] != "docs":
        return []
    try:
        docs = re.compile(conf()["HARNESS_DOC_PATHS"])
    except re.error:   # doctor reports it; a crash here would let a finishing edit through, so nothing is a doc
        docs = None
    other = [n for n in changed if not (docs and docs.search(n))]
    return ["Change-Class docs doesn't cover a change to files that aren't documentation: %s"
            % ", ".join(other[:6])] if other else []


def content_risks(text, changed=None):
    """What makes the spec, or the files its change touches (changed, when given), not low-risk, whatever its
    Change-Class: a class never lowers what these find."""
    values = conf()
    # Skills only says which skills the agents load, and explaining why `security` isn't needed ("no auth or
    # personal data") would read as risk. What the work does is in the other sections and in the diff.
    outside = without_approval(text)
    body = without_section(outside, "Skills", view=comment_free(outside))
    reasons = []
    unread = spec_reading_problem(text)
    if unread:
        reasons.append("the spec can't be read the way Markdown renders it: %s" % unread)
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
    if changed is not None:
        sensitive = [n for n in changed if paths.search(n)]
        if sensitive:
            reasons.append("the change touches sensitive paths: %s" % ", ".join(sensitive[:6]))
        limit = int(values["HARNESS_RISK_MAX_FILES"]) if values["HARNESS_RISK_MAX_FILES"].isdigit() else 20
        if len(changed) > limit:
            reasons.append("the change touches %d files (limit %d)" % (len(changed), limit))
    return reasons


# Failure classes: why a task stopped, each with the playbook that recovers from it. An escalation is classified from
# its kind and reason (or --class); a class that repeats gets a draft proposal in backbone/proposals/ for the user.
FAILURE_CLASSES = {
    "tool_timeout": ("retry with backoff", "a tool or worker timed out or died: retry once after a pause, then "
                     "escalate", "a timeout, a tool contract or a sandbox allowlist entry"),
    "invalid_args": ("repair the call", "a tool or command was called wrongly: fix the arguments from its usage "
                     "and call again", "a skill note on how to call the tool"),
    "missing_context": ("retrieve the source", "the answer is in a source nobody read: find it in backbone/, the "
                        "knowledge source or the code, cite it, and continue", "a 4-KNOWLEDGE.md entry or a skill"),
    "failed_test": ("repair from the debugger's brief", "the judge failed the code: the debugger diagnoses, the "
                    "implementer fixes, the judge re-runs", "a regression test or a guardrail for the defect pattern"),
    "permission_denied": ("request approval", "a gate, a guardrail or a contract refused the action: ask the user, "
                          "never route around it", "a guardrail or tools.conf review"),
    "contradictory_req": ("escalate to the user", "the spec, an ADR or the PRD disagree or leave the behaviour open: "
                          "the user decides", "a requirements-writing rule or a PRD clarification"),
    "unchanged_repeat": ("stop", "the same step came back without progress: stop the task and hand it over",
                         "a smaller task split or a playbook change"),
}
FAILURE_RULES = (   # (class, regex over "<kind> <reason>"), first match wins
    ("unchanged_repeat", r"(?i)changed nothing|without progress|no progress|no resolution|came back \d+ times"),
    ("tool_timeout", r"(?i)time[sd]? ?out|timed out|worker .*failed|unreachable"),
    ("permission_denied", r"(?i)^(approval|out-of-band change)\b|refused|permission|not allowed|blocked by"),
    ("invalid_args", r"(?i)invalid (arg|argument|input|option)|unknown (argument|option|flag)|usage:"),
    ("failed_test", r"(?i)^judge failed|tests? fail|not met|delivery failed|checks? failed"),
    ("contradictory_req", r"(?i)^griller failed|contradict|ambiguous|conflict"),
    ("missing_context", r"(?i)^decision\b|question|unanswered|no source|missing context"),
)


def failure_class(kind, reason):
    text = "%s %s" % (kind, reason)
    return next((name for name, pattern in FAILURE_RULES if re.search(pattern, text)), "missing_context")


def debug_class(task):
    """The class the last debugger brief points at: a spec or test it blames is contradictory, else a failed test."""
    briefs = verdict_history(task, "debug")
    owners = {str(c.get("owner")) for c in (briefs[-1].get("root_causes") or []) if isinstance(c, dict)} \
        if briefs else set()
    return "contradictory_req" if owners & {"analyst", "tester", "user"} else "failed_test"


def class_entries():
    """[(class, task, reason)] for every classified escalation in escalations.md, oldest first."""
    found = []
    for entry in re.split(r"(?m)^## ", read(ESCALATIONS))[1:]:
        cls = re.search(r"(?m)^- Class:\s*(\w+)", entry)
        task = re.search(r"\bTask\s+(\S+):", entry.splitlines()[0])
        reason = re.search(r"(?m)^- Reason:\s*(.*)$", entry)
        if cls:
            found.append((cls.group(1), task.group(1) if task else "?", reason.group(1) if reason else ""))
    return found


def class_counts():
    counts = {}
    for cls, _, _ in class_entries():
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def propose(cls):
    """A failure class seen twice or more gets a draft proposal for the user, listing every occurrence. The harness
    applies nothing: the scribe drafts the change and it lands only through a task the user approves."""
    occurrences = [(task, reason) for c, task, reason in class_entries() if c == cls]
    if len(occurrences) < 2:
        return None
    path = BACKBONE / "proposals" / ("%s.md" % cls)
    action, _, change = FAILURE_CLASSES[cls]
    text = read(path)
    if not text:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = ("# Proposal: %s keeps recurring\n\n- Status: draft (the user accepts, edits or drops it; the harness "
                "applies nothing)\n- Playbook: %s\n- Proposed change: %s\n\n## Draft\n\n(the scribe writes the "
                "concrete change here)\n\n## Occurrences\n" % (cls, action, change))
        lines = occurrences
    else:
        lines = occurrences[-1:]
    text += "".join("- task %s: %s\n" % (task, reason.strip()[:300]) for task, reason in lines)
    path.write_text(text, encoding="utf-8")
    return path


def escalate(task, kind, reason, needed=None, cls=None, refresh=True):
    """Park task for the user: a BLOCKED note on its line (out of [WIP]) and an entry in escalations.md. A user-only
    command passes refresh=False: run by an agent anyway, its writes must still show as out-of-band changes."""
    cls = cls if cls in FAILURE_CLASSES else failure_class(kind, reason)
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
    entry = ("\n## %s Task %s: %s\n\n- Status: open\n- Class: %s\n- Playbook: %s\n- Reason: %s\n- Needed: %s\n"
             % (stamp, task, kind, cls, FAILURE_CLASSES[cls][0], reason.strip(), needed or "a decision from the user"))
    log_event("escalation", task=task, escalation=kind, failure_class=cls, reason=reason.strip()[:500])
    with ESCALATIONS.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    if propose(cls):
        log_event("proposal", failure_class=cls)
    if refresh:
        snapshot_refresh()
    issue = None
    if conf()["HARNESS_ESCALATE_GH"] == "on" and shutil.which("gh"):
        result = subprocess.run(["gh", "issue", "create", "--title", "Harness escalation: task %s: %s" % (task, kind),
                                 "--body", entry.strip(), "--label", "harness-escalation"],
                                cwd=str(ROOT), capture_output=True, text=True)
        issue = result.stdout.strip() if result.returncode == 0 else None
        if issue:
            log_event("outward", action="issue-create", via="harness", task=task, url=issue)
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
    light = light_lane(task)
    if invalid or (not light and (not last or last.get("verdict") != "pass"
                                  or last.get("fingerprint") != spec_fingerprint(task))):
        print("approve: the spec must be valid and have a current griller pass first (spec-check %s)" % task)
        return 1
    asked = sum(len(entry.get("questions") or []) for entry in history)
    assumptions = [a for a in top_level_items(md_section(text, "Assumptions"))
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
    line = "Approved-by: policy:low-risk (%s; base %s; %s)" % (
        time.strftime("%Y-%m-%d"), base, "light lane" if light else "grill %s" % last.get("fingerprint", "")[:12])
    has_heading = approval_start(text) < len(text)
    text = (text.rstrip("\n") + "\n\n## Approval\n" if not has_heading else text.rstrip("\n")) + "\n" + line + "\n"
    spec_path(task).write_text(text, encoding="utf-8")
    log_event("approval", task=task, rule="low-risk", base=base)
    snapshot_refresh()
    print("approve: %s approved by policy (low risk, %s)." % (spec_rel(task), class_label(text)))
    return 0


def escalate_command(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write("usage: harness.py escalate <task> --reason <text> [--kind <kind>] [--needed <text>]\n")
        return 64
    task, opts, key = argv[0], {}, None
    for arg in argv[1:]:
        if arg in ("--reason", "--kind", "--needed", "--class"):
            key = arg[2:]
        elif key:
            opts[key] = (opts.get(key, "") + " " + arg).strip()
    if not opts.get("reason"):
        sys.stderr.write("escalate: --reason is required\n")
        return 64
    if opts.get("class") and opts["class"] not in FAILURE_CLASSES:
        sys.stderr.write("escalate: --class must be one of %s\n" % ", ".join(FAILURE_CLASSES))
        return 64
    issue = escalate(task, opts.get("kind", "decision"), opts["reason"], opts.get("needed"), opts.get("class"))
    print("escalate: task %s parked as BLOCKED; recorded in backbone/escalations.md%s. Continue with another task."
          % (task, " and " + issue if issue else ""))
    return 0


def escalation_entries():
    """Every entry of escalations.md as the contract's fields, oldest first."""
    found = []
    for entry in re.split(r"(?m)^## ", read(ESCALATIONS))[1:]:
        head = re.match(r"(\S+ \S+) Task (\S+): (.*)$", entry.splitlines()[0])
        fields = dict((k.lower(), v.strip()) for k, v in re.findall(r"(?m)^- (Status|Class|Playbook|Reason|Needed):"
                                                                     r"[ \t]*(.*)$", entry))
        found.append({"task": head.group(2) if head else None, "kind": head.group(3).strip() if head else None,
                      "class": fields.get("class"), "playbook": fields.get("playbook"), "reason": fields.get("reason"),
                      "needed": fields.get("needed"), "status": fields.get("status"),
                      "at": head.group(1) if head else None})
    return found


def escalations_command(argv=()):
    if "--json" in argv:
        entries = [e for e in escalation_entries() if (e["status"] or "").lower() == "open"]
        print(json.dumps({"escalations": entries, "by_class": class_counts()}, indent=2))
        return 0
    items = open_escalations()
    for item in items:
        print("open  %s" % item)
    print("%d open escalation(s)" % len(items))
    counts = class_counts()
    if counts:
        print("by class (all escalations): %s" % ", ".join("%s %d" % (c, counts[c]) for c in FAILURE_CLASSES
                                                           if c in counts))
    return 0


# Out-of-band changes. Shell checks can't see what a script file does. The harness keeps a snapshot of the
# protected files, refreshed after every file-tool edit and every write of its own, and compares it after each
# shell command. A protected file that changed in between, and is not simply back to its committed version, was
# written some other way. In supervised mode the user edits these files too, so the snapshot is also taken as a
# command starts, and only what changed while that command ran is reported.
SNAPSHOT_ROOTS = ("backbone", "scripts/harness", ".claude", ".codex", ".opencode")
SNAPSHOT_FILES = ("AGENTS.md", "CLAUDE.md", "harness-attest.pub")
SNAPSHOT_SKIP = (".claude/settings.local.json",)


SNAPSHOT_PATH = []   # resolved once per process: the snapshot is read and written around every shell command
# A command whose end never came (interrupted) stops counting as running after its timeout (Bash: 2 minutes unless
# the call sets one) plus this margin; until then, edits made meanwhile are reported against it.
RUNNING_MARGIN_SECONDS = 30


def snapshot_file():
    """Per worktree (its own git dir), not in the shared .git/harness: each worktree has its own protected files,
    and worktrees sharing one snapshot see each other's files as out-of-band changes."""
    if not SNAPSHOT_PATH:
        git_dir = git("rev-parse", "--absolute-git-dir").strip()
        SNAPSHOT_PATH.append((Path(git_dir) / "harness" / "snapshot.json") if git_dir
                             else events_file().parent / "snapshot.json")
    return SNAPSHOT_PATH[0]


def protected_files():
    for top in SNAPSHOT_ROOTS:
        for folder, dirs, files in os.walk(str(ROOT / top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")
                       and not (d == "worktrees" and Path(folder) == ROOT / ".claude")]   # Claude Code's worktrees
            for name in files:
                full = Path(folder) / name
                key = full.relative_to(ROOT).as_posix()
                if key not in SNAPSHOT_SKIP and not name.endswith((".pyc", ".harness-new", ".harness-bak")):
                    yield key, full
    for name in SNAPSHOT_FILES:
        if (ROOT / name).is_file():
            yield name, ROOT / name


def protected_state(previous=None):
    """{path: [size, mtime_ns, ctime_ns, sha256]}. A hash is reused while the stat is unchanged: the snapshot is taken
    around every shell command, and rehashing the whole backbone each time would make every command slow. ctime is
    in the key because a script can put mtime back (touch -r), but not ctime."""
    previous = previous or {}
    state = {}
    for key, full in protected_files():
        try:
            st = full.stat()
        except OSError:
            continue
        stat = [st.st_size, st.st_mtime_ns, st.st_ctime_ns]
        old = previous.get(key)
        state[key] = old if isinstance(old, list) and len(old) == 4 and old[:3] == stat else stat + [sha256(full)]
    return state


def read_snapshot():
    """{"files": protected_state, "running": {mark: {"command", "at"}}}: the shell commands started and not yet
    finished (supervised mode), which all share the snapshot taken when the first of them started."""
    try:
        data = json.loads(read(snapshot_file()) or "null")
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None
    running = data.get("running") if isinstance(data.get("running"), dict) else {}
    data["running"] = {m: v for m, v in running.items()
                       if isinstance(v, dict) and time.time() < (v.get("until") or 0)}
    return data


def write_snapshot(files, running):
    try:
        path = snapshot_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"files": files, "running": running}), encoding="utf-8")
    except OSError:
        pass


def snapshot_refresh():
    """After a write of the harness's own or a file-tool edit, so it isn't reported as out-of-band."""
    snapshot = read_snapshot() or {}
    if autonomous() or snapshot.get("running"):
        write_snapshot(protected_state(snapshot.get("files")), snapshot.get("running") or {})


def command_mark(data):
    tool_input = data.get("tool_input") or {}
    return data.get("tool_use_id") or hashlib.sha256(str(tool_input.get("command") or "").encode("utf-8")).hexdigest()


def command_started(data):
    """Supervised mode: the user edits protected files too, so only what changes while a command runs is reported.
    While another command still runs, its snapshot stays: re-taking it would hide what that command changed."""
    snapshot = read_snapshot() or {}
    running = snapshot.get("running") or {}
    files = snapshot["files"] if running else protected_state(snapshot.get("files"))
    tool_input = data.get("tool_input") or {}
    timeout = tool_input.get("timeout")
    seconds = timeout / 1000.0 if isinstance(timeout, (int, float)) and timeout > 0 else 120
    running[command_mark(data)] = {"command": str(tool_input.get("command") or "")[:300],
                                   "until": time.time() + seconds + RUNNING_MARGIN_SECONDS}
    write_snapshot(files, running)


def command_finished(data):
    """(changed files, commands that were running) for a command whose start was seen; ([], []) otherwise."""
    snapshot = read_snapshot()
    mark = command_mark(data)
    if snapshot is None or mark not in snapshot["running"]:
        return [], []
    commands = [v.get("command", "") for v in snapshot["running"].values()]
    changed, current = protected_changes(snapshot["files"])
    del snapshot["running"][mark]
    write_snapshot(current, snapshot["running"])
    return changed, commands


def protected_changes(files):
    """(protected files changed since files, other than restores to the committed version; the current state)."""
    previous = {k: v[3] for k, v in files.items() if isinstance(v, list) and len(v) == 4}
    current = protected_state(files)
    hashes = {k: v[3] for k, v in current.items()}
    differ = sorted(name for name in set(previous) | set(hashes) if previous.get(name) != hashes.get(name))
    committed = committed_blobs(differ)
    return [name for name in differ if name not in committed or committed[name] != blob_id(ROOT / name)], current


def committed_blobs(names):
    """{path: blob id at HEAD} in one git call: a script can change hundreds of files, and a git show per file made
    the check take seconds."""
    blobs = {}
    if names:
        for line in git("ls-tree", "-r", "-z", "HEAD", "--", *names).split("\0"):
            meta, _, name = line.partition("\t")
            parts = meta.split()
            if len(parts) == 3 and parts[1] == "blob":
                blobs[name] = parts[2]
    return blobs


def blob_id(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def out_of_band_changes():
    """Autonomous mode: protected files changed since the snapshot."""
    snapshot = read_snapshot()
    return protected_changes(snapshot["files"])[0] if snapshot else []


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


# The light lane (HARNESS_LIGHT_LANE, user-only): a task the user marks "(light)" on its line skips the architect and
# the griller when its spec is small and low-risk. The approval, the judge and verify still apply, and finishing
# refuses a light task whose change grew past HARNESS_LIGHT_MAX_FILES files.

def light_tasks(text):
    lines = outline(text or "").splitlines()
    return {task_id_at(lines, i) for i, line in enumerate(lines)
            if re.match(r"^\s*[-*]\s+\[[^\]]*\]", line) and LIGHT_MARK.search(BLOCKED_NOTE.sub("", line))}


def light_marked(task):
    return conf()["HARNESS_LIGHT_LANE"] == "on" and task in light_tasks(read(TASKS))


def conf_int(key, default):
    value = conf()[key]
    return int(value) if value.isdigit() else default


def light_reasons(task):
    """Why a task marked (light) still needs the full pipeline; empty when the light lane applies. The user's mark
    is enough for feature work, which the user approves anyway; schema work never takes the lane."""
    text = read(spec_path(task))
    body = comment_free(text)
    cls, _, problem = change_class(text)
    if problem:
        reasons = [problem]
    elif cls == "schema":
        reasons = ["Change-Class schema never takes the light lane"]
    else:
        reasons = []
    items = len(spec_items(body, "REQ", task)) + len(spec_items(body, "AC", task))
    limit = conf_int("HARNESS_LIGHT_MAX_ITEMS", 3)
    if items > limit:
        reasons.append("the spec has %d requirements and acceptance criteria (HARNESS_LIGHT_MAX_ITEMS %d)"
                       % (items, limit))
    return reasons + content_risks(text)


def light_lane(task):
    """True when task goes through the light lane: the lane is on, the user marked it, and its spec qualifies."""
    return light_marked(task) and not light_reasons(task)


def light_guard(before, after):
    added = light_tasks(after) - light_tasks(before)
    if added:
        return ("  - Only the user marks a task (light) (task %s): it skips the architect and the griller."
                % ", ".join(sorted(added)))
    return None


def record_light_start(task):
    """Remember the commit a light task started from, so finishing measures everything it changed since, committed
    or not (the spec may never have been committed, and code may be committed in pieces)."""
    if not light_lane(task):
        return
    history = verdict_history(task, "light")
    history.append({"base": git("rev-parse", "-q", "--verify", "HEAD").strip() or None,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(task, "light").write_text(json.dumps({"task": task, "kind": "light", "history": history}, indent=2)
                                           + "\n", encoding="utf-8")


def light_base(task):
    history = verdict_history(task, "light")
    return history[-1].get("base") if history else None


def light_drift(task):
    """A light task's change that grew past the lane: too many files, or sensitive paths. None when it stayed light."""
    if not light_marked(task):
        return None
    if not verdict_history(task, "light"):
        return ("Task %s is marked (light) but has no recorded start (backbone/.verdicts/%s.light.json): it was not "
                "started through the light lane. Ask the user to remove (light), or start it again." % (task, slug(task)))
    base = light_base(task)
    changed = changed_files(base)
    limit = conf_int("HARNESS_LIGHT_MAX_FILES", 3)
    paths = re.compile(conf()["HARNESS_RISK_PATHS"])
    sensitive = [n for n in changed if paths.search(n)]
    why = []
    if len(changed) > limit:
        why.append("it changes %d files (HARNESS_LIGHT_MAX_FILES %d)" % (len(changed), limit))
    if sensitive:
        why.append("it touches sensitive paths: %s" % ", ".join(sensitive[:6]))
    if not why:
        return None
    return ("Task %s outgrew the light lane: %s. It needs the full pipeline: ask the user to remove (light) from its "
            "line, then have the architect and the griller review the spec." % (task, "; ".join(why)))


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
    note = ""
    if light_marked(task):
        reasons = light_reasons(task)
        if not reasons:
            return None if approved(read(spec_path(task))) else (
                "Task %s cannot start: the user has not approved the spec (light lane: no grilling needed). Ask them "
                "to review %s and add 'Approved-by: <name> (<date>)' under '## Approval' themselves." % (task, spec))
        note = " It is marked (light), but %s, so it goes through the griller." % "; ".join(reasons)
    if last is None:
        return ("Task %s cannot start: the spec has not been grilled. Ask the griller agent to review %s.%s"
                % (task, spec, note))
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
    review = review_problems(task, current, max_rounds)
    if review:
        return review
    drift = light_drift(task)
    if drift:
        return drift
    policy = policy_approval(read(spec_path(task)))
    if policy:
        risks = risk_reasons(task, policy["base"] if policy["base"] != "none" else "")
        if risks:
            return ("Task %s was approved by policy as low-risk, but %s. Escalate it: python3 "
                    "scripts/harness/lib/harness.py escalate %s --kind approval --reason \"...\""
                    % (task, "; ".join(risks), task))
    return None


def review_on():
    return conf()["HARNESS_REVIEW"] != "off"


def lens_reviews(task):
    """{lens: its latest review entry, or None}."""
    history = verdict_history(task, "review")
    return {lens: next((e for e in reversed(history) if e.get("lens") == lens), None) for lens in REVIEW_LENSES}


def review_problems(task, current, max_rounds):
    """Why task's reviews don't allow finishing it: a lens with no review, a failed one, or one on older code."""
    if not review_on():
        return None
    history = since_last_escalation(task, verdict_history(task, "review"))
    problems = []
    for lens, last in lens_reviews(task).items():
        if last is None:
            problems.append("Task %s has no %s review. Run the reviewer on task %s with the %s lens (the lenses run "
                            "in parallel)." % (task, lens, task, lens))
        elif last.get("verdict") != "pass":
            fails = consecutive_fails([e for e in history if e.get("lens") == lens])
            issues = "; ".join(str(f.get("issue")) for f in last.get("findings") or []
                               if isinstance(f, dict) and f.get("severity") == "must-fix")[:400]
            if fails >= max_rounds:
                problems.append("The %s review failed task %s %d times. Stop retrying: report the findings to the "
                                "user and ask how to proceed. Must-fix: %s" % (lens, task, fails, issues))
            else:
                problems.append("The %s review failed task %s: %s. Have the implementer fix the must-fix findings, "
                                "then judge and review again." % (lens, task, issues))
        elif current and last.get("fingerprint") != current:
            problems.append("The code changed after the %s review of task %s passed. Review it again." % (lens, task))
    return " ".join(problems) or None


def acceptance_problem(task):
    """With HARNESS_TESTER on: the tester's acceptance tests exist, cover every AC, and are unchanged."""
    if not tester_on():
        return None
    history = verdict_history(task, "tests")
    if not history:
        return ("Task %s has no acceptance tests from the tester (HARNESS_TESTER is on). Ask the tester to write "
                "them; the implementer may not." % task)
    acs = [ac for ac, _ in spec_items(comment_free(read(spec_path(task))), "AC", task)]
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
    """Approval lines are the user's alone, and an approved spec is frozen. Approval lines are read from outline(), the
    text approved() reads, so a line that only a comment hides is no way round it."""
    before, after = line_endings(before), line_endings(after)
    if approval_lines(outline(before)) != approval_lines(outline(after)) or approved(before) != approved(after):
        return "  - Only the user may add, change or remove 'Approved-by:' lines."
    if source_section(before) != source_section(after):
        return ("  - The '## Source' section records who asked for this task, through which door, and whether the "
                "sender is trusted; only harness.py intake and linear import write it. Keep it exactly as it is and "
                "rewrite the other sections.")
    if approved(before) and frozen_text(before) != frozen_text(after):
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
        if without_section(before, "Status") != without_section(after, "Status"):
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
        # Without -f, git keeps an entry that differs from both HEAD and the checkout, as backbone/ files of an
        # older commit do, and the fingerprint would include them.
        run("rm", "-r", "--cached", "-q", "-f", "--ignore-unmatch", "--", "backbone")
        result = run("write-tree")
        return result.stdout.strip() if result.returncode == 0 else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def task_states(text):
    lines = outline(text).splitlines()
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
    marked = light_tasks(show(after, tasks_rel) or "") - light_tasks(show(before, tasks_rel) if before else "")
    if marked and before and not allow_user_changes:
        problems.append("the change marks task(s) %s (light), which skips the architect and the griller. Only the "
                        "user does that, and commits it with HARNESS_VERIFY=off git commit ..." % ", ".join(sorted(marked)))
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
    for name in changed if before and not allow_user_changes else []:
        if re.match(r"^backbone/specs/[^/]+\.md$", name):
            old = show(before, name)
            if old is not None and source_section(old) != source_section(show(after, name) or ""):
                problems.append("%s: its '## Source' section changed. It records who asked for the task and whether "
                                "the sender is trusted; only harness.py intake and linear import write it" % name)
    conf_rel = CONF_FILE.relative_to(ROOT).as_posix()
    old_conf = show(before, conf_rel) if before else None
    if conf_rel in changed and old_conf is not None and not allow_user_changes:
        old, new = parse_conf(old_conf), parse_conf(show(after, conf_rel) or "")
        keys = [key for key in USER_ONLY_KEYS if old.get(key) != new.get(key)]
        if keys:
            problems.append("user-only setting(s) changed in backbone/harness.conf: %s. Only the user may change "
                            "them and commit that change (HARNESS_VERIFY=off git commit ...)." % ", ".join(keys))
    tools_rel = TOOLS_FILE.relative_to(ROOT).as_posix()
    if tools_rel in changed and before and show(before, tools_rel) is not None and not allow_user_changes:
        problems.append("the tool contracts change (%s). They decide what agents may run, so only the user changes "
                        "them and commits that change (HARNESS_VERIFY=off git commit ...)." % tools_rel)
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
        changed = diff_names("--cached", "HEAD")
    else:
        changed = [n for n in git("ls-files", "-z").split("\0") if n]
    fingerprint = tree_fingerprint()
    return verify_changes("HEAD" if head else "", "", changed, lambda task: fingerprint)


def verify_range(spec, allow_user_changes=False):
    base, _, tip = spec.partition("..")
    tip = tip or "HEAD"
    commits = [c for c in git("rev-list", "--reverse", "%s..%s" % (base, tip)).split() if c]
    changed = diff_names(base, tip)
    return verify_changes(base, tip, changed, lambda task: tree_fingerprint(done_commit(task, commits, tip)),
                          allow_user_changes)


def done_commit(task, commits, tip):
    """The first of commits (oldest first) whose task list marks task done, else tip."""
    tasks_rel = TASKS.relative_to(ROOT).as_posix()
    return next((c for c in commits if task in task_states(show(c, tasks_rel))[1]), tip)


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


# --------------------------------------------------------------------------- attestation (ADR-005)

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
VERDICTS_PREDICATE = "https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1"
VERIFIER_ID = "https://github.com/soyPeter/agentic-harness"
ATTEST_USAGE = "usage: harness.py attest --range <base>..<tip> [--allow-user-changes]\n"


def verdict_brief(history):
    """The latest of a verdict history as the statement states it, or None."""
    if not history:
        return None
    last = history[-1]
    return {"verdict": last.get("verdict"), "fingerprint": last.get("fingerprint"), "at": last.get("at"),
            "rounds": len(history)}


def base_lock(base):
    """The release base's backbone/.harness-lock.json names: what CI runs as the verifier. None without a lock."""
    try:
        data = json.loads(show(base, LOCK_FILE.relative_to(ROOT).as_posix()) or "null")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("mode") == "thin":
        return {"mode": "thin", "version": data.get("version"), "commit": data.get("commit")}
    return {"mode": "full", "version": data.get("harness_version")}


def attested_task(task, commits, tip):
    """A finished task's verdict chain. The receipt is matched against the code of the commit that finished the task,
    which verify has checked, so an earlier task keeps its receipt when a later commit in the range changes code."""
    spec_text = read(spec_path(task))
    finished_in = done_commit(task, commits, tip)
    base = receipt_base(task, spec_text)
    risks = risk_reasons(task, base)
    cls, declared, problem = change_class(spec_text)
    receipt, _ = receipt_data(task, base, code=tree_fingerprint(finished_in))
    judges = verdict_history(task, "judge")
    judge = verdict_brief(judges)
    if judge:
        run = judges[-1].get("test_run")
        judge["testRun"] = {"command": run.get("command"), "exit": run.get("exit"),
                            "outputSha256": run.get("output_sha256")} if isinstance(run, dict) else None
    reviews = verdict_history(task, "review")
    return {
        "task": task,
        "title": task_title(task),
        "finishedIn": finished_in,
        "spec": {"path": spec_rel(task),
                 "fingerprint": spec_fingerprint(task, spec_text) if not blank_text(spec_text) else None,
                 "approval": approval_lines(md_section(spec_text, "Approval") or "")},
        "changeClass": {"class": cls, "declared": declared, "problem": problem},
        "grill": verdict_brief(verdict_history(task, "grill")),
        "judge": judge,
        "reviews": {lens: verdict_brief([e for e in reviews if e.get("lens") == lens]) for lens in REVIEW_LENSES},
        "risk": {"reasons": risks, "labels": suggested_labels(spec_text, risks)},
        "receipt": {"verified": receipt["verified"], "notVerified": receipt["not_verified"],
                    "approvalNeeded": receipt["approval_needed"]} if receipt else None,
    }


def verification_settings():
    """Every setting the engine resolves through conf(), with its value and whether the environment set it. verify
    reads its settings only through conf(), so this is what its result can depend on."""
    values = conf()
    return {key: {"value": values[key], "environment": key in os.environ} for key in sorted(values)}


def attest_statement(base_ref, tip_ref, allow_user_changes=False):
    """(in-toto Statement, []) for a range that passes verify, checked out at its tip; else (None, problems)."""
    commits_of = {}
    for ref in (base_ref, tip_ref):
        commits_of[ref] = git("rev-parse", "-q", "--verify", ref + "^{commit}").strip()
        if not commits_of[ref]:
            return None, ["%s is not a commit" % ref]
    base, tip = commits_of[base_ref], commits_of[tip_ref]
    head = git("rev-parse", "-q", "--verify", "HEAD").strip()
    if head != tip:
        return None, ["the checkout is at %s, not %s: check out the commit the statement is about"
                      % (head[:12], tip[:12])]
    # Receipts, risks and fingerprints read the checkout, so it has to be exactly the commit.
    dirty = [line[3:] for line in git("status", "--porcelain", "--untracked-files=all").splitlines() if line.strip()]
    if dirty:
        return None, ["the checkout has uncommitted or untracked files (%s); the statement is about commit %s, so "
                      "commit or remove them first" % (", ".join(dirty[:5]), tip[:12])]
    problems = verify_range("%s..%s" % (base, tip), allow_user_changes)
    if problems:
        return None, problems
    commits = [c for c in git("rev-list", "--reverse", "%s..%s" % (base, tip)).split() if c]
    tasks_rel = TASKS.relative_to(ROOT).as_posix()
    finished = sorted(task_states(show(tip, tasks_rel))[1] - task_states(show(base, tasks_rel))[1])
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": "commit", "digest": {"gitCommit": tip}},
                    {"name": "code", "digest": {"gitTree": tree_fingerprint(tip)}}],
        "predicateType": VERDICTS_PREDICATE,
        "predicate": {
            "verifier": {"id": VERIFIER_ID, "engineSha256": sha256(__file__), "baseLock": base_lock(base)},
            "verification": {"base": base, "tip": tip, "result": "PASSED", "allowUserChanges": allow_user_changes,
                             "settings": verification_settings()},
            "tasks": [attested_task(task, commits, tip) for task in finished],
        },
    }, []


def attest_command(argv):
    """Print the in-toto Statement of a verified range; nothing on stdout when the range doesn't verify."""
    allow = "--allow-user-changes" in argv
    args = [a for a in argv if a != "--allow-user-changes"]
    if args[:1] != ["--range"] or len(args) != 2 or ".." not in args[1] or args[1].startswith(".."):
        sys.stderr.write(ATTEST_USAGE)
        return 64
    base, _, tip = args[1].partition("..")
    statement, problems = attest_statement(base, tip or "HEAD", allow)
    for problem in problems:
        sys.stderr.write("attest: %s\n" % problem)
    if problems:
        return 1
    sys.stdout.write(json.dumps(statement, indent=2, sort_keys=True) + "\n")
    return 0


ATTEST_ENVIRONMENT = "harness-attest"
ATTEST_BRANCH_VARIABLE = "HARNESS_ATTEST_BRANCH"
ATTEST_RECORDED_VARIABLE = "HARNESS_ATTEST_RECORDED_FALLBACK"
ATTEST_SECRETS = ("HARNESS_ATTEST_KEY", "HARNESS_ATTEST_PASSWORD")
ATTEST_POLICY_SECRET = "HARNESS_ATTEST_POLICY_TOKEN"
ATTEST_PUBLIC_KEY = "harness-attest.pub"


def environment_problems(environment, policies, branch):
    """Why the harness-attest environment doesn't admit only branch, from the JSON of GET repos/<r>/environments/<name>
    and of its deployment-branch-policies. [] when it does: selected branches only, and exactly one branch policy."""
    rule = environment.get("deployment_branch_policy") if isinstance(environment, dict) else None
    found = policies.get("branch_policies") if isinstance(policies, dict) else None
    problems = []
    if not isinstance(rule, dict) or rule.get("protected_branches") is not False \
            or rule.get("custom_branch_policies") is not True:
        problems.append("the environment doesn't restrict deployments to selected branches")
    if not isinstance(found, list) or [(p.get("type"), p.get("name")) for p in found if isinstance(p, dict)] != [
            ("branch", branch)]:
        problems.append("the environment's deployment branches are not exactly %s" % branch)
    return problems


def environment_check_command(argv):
    """harness-verify's attest job: the environment's JSON from gh api, judged here (ADR-005)."""
    if len(argv) != 3:
        sys.stderr.write("usage: harness.py environment-check <environment.json> <policies.json> <branch>\n")
        return 64
    try:
        environment, policies = json.loads(read(argv[0]) or "null"), json.loads(read(argv[1]) or "null")
    except ValueError as exc:
        print("environment-check: the environment's JSON doesn't parse: %s" % exc)
        return 1
    problems = environment_problems(environment, policies, argv[2])
    for problem in problems:
        print("environment-check: %s" % problem)
    if not problems:
        print("environment-check: %s deploys only from %s" % (ATTEST_ENVIRONMENT, argv[2]))
    return 1 if problems else 0


def repository_copies(secrets, variables):
    """[(kind, name)] of the repository-level secrets and variables named like the attest job's secrets, from the JSON
    of GET repos/<r>/actions/secrets and /variables; None when either list isn't whole. A repository secret signs when
    the environment has none, and a variable of that name holds the key in plain text."""
    found = []
    for listing, kind in ((secrets, "secrets"), (variables, "variables")):
        items = listing.get(kind) if isinstance(listing, dict) else None
        if not isinstance(items, list) or listing.get("total_count") != len(items):
            return None
        found += [(kind, i["name"]) for i in items if isinstance(i, dict) and i.get("name") in ATTEST_SECRETS]
    return found


def copy_label(kind, name):
    return "the repository %s %s" % (kind[:-1], name)


def repository_check_command(argv):
    """harness-verify's attest job: the repository's secrets and variables from gh api, judged here (ADR-005)."""
    if len(argv) != 2:
        sys.stderr.write("usage: harness.py repository-check <secrets.json> <variables.json>\n")
        return 64
    try:
        copies = repository_copies(json.loads(read(argv[0]) or "null"), json.loads(read(argv[1]) or "null"))
    except ValueError as exc:
        print("repository-check: the repository's JSON doesn't parse: %s" % exc)
        return 1
    if copies is None:
        print("repository-check: the lists of the repository's secrets and variables are incomplete")
        return 1
    for kind, name in copies:
        print("repository-check: %s would sign or expose the attest key; keep %s in %s only" % (
            copy_label(kind, name), name, ATTEST_ENVIRONMENT))
    if not copies:
        print("repository-check: no repository-level %s" % " or ".join(ATTEST_SECRETS))
    return 1 if copies else 0


def attest_repository(name):
    """What the attest job finds on GitHub (ADR-005): (the names of harness-attest's secrets, whether the recorded-branch
    opt-in is set, the repository-level copies of its secrets). Each is None when gh can't read it."""
    ok, listed = gh_api("repos/%s/environments/%s/secrets" % (name, ATTEST_ENVIRONMENT))
    environment = [s.get("name") for s in listed.get("secrets") or [] if isinstance(s, dict)] \
        if ok and isinstance(listed, dict) else None
    ok_secrets, secrets = gh_api("repos/%s/actions/secrets?per_page=100" % name)
    ok_variables, variables = gh_api("repos/%s/actions/variables?per_page=100" % name)
    copies = repository_copies(secrets, variables) if ok_secrets and ok_variables else None
    recorded = any(isinstance(v, dict) and v.get("name") == ATTEST_RECORDED_VARIABLE and v.get("value") == "true"
                   for v in variables.get("variables") or []) if copies is not None else None
    return environment, recorded, copies


def attest_health():
    """(the attest mode doctor states, its issues)."""
    name, _ = github_repo()
    if name.startswith("<"):
        return "unknown: gh sees no GitHub repository", []
    environment, recorded, copies = attest_repository(name)
    mode = attest_mode(None if environment is None else ATTEST_POLICY_SECRET in environment, recorded)
    issues = [("warn", "%s: the attest job refuses to sign while it exists; delete it with harness.py ci-protect "
                       "--attest --delete-repo-copies" % copy_label(kind, copy)) for kind, copy in copies or []]
    return mode, issues


def gh_api(endpoint, method=None, body=None):
    """(ok, parsed JSON or None) for gh api endpoint; body goes in as JSON."""
    words = ["gh", "api"] + (["-X", method] if method else []) + [endpoint] + (["--input", "-"] if body else [])
    try:
        result = subprocess.run(words, cwd=str(ROOT), capture_output=True, text=True, timeout=GIT_TIMEOUT,
                                input=json.dumps(body) if body else None)
    except subprocess.TimeoutExpired:
        return False, None
    if result.returncode:
        return False, None
    try:
        return True, json.loads(result.stdout or "null")
    except ValueError:
        return True, None


def attest_mode(policy_token, recorded):
    """The mode the attest job runs in, as ci-protect --attest states it. policy_token is True, False or None when
    the environment's secrets can't be listed."""
    if policy_token is None:
        return "unknown: can't list the secrets of %s" % ATTEST_ENVIRONMENT
    if recorded is None:
        return "unknown: can't list the repository's secrets and variables"
    if policy_token:
        return "live: the job reads the rule with %s, and %s" % (
            ATTEST_POLICY_SECRET, "accepts the recorded branch when it can't read the rule (opted in)" if recorded
            else "refuses to sign when it can't read the rule")
    if recorded:
        return ("recorded branch: no %s, so the job accepts the branch ci-protect recorded (opted in), and the rule "
                "is not re-read" % ATTEST_POLICY_SECRET)
    return "none: no %s and no opt-in, so the job refuses to sign" % ATTEST_POLICY_SECRET


def public_key_line(default):
    """Whether the public key the attest job checks against is committed on the default branch (ADR-005)."""
    if show(default, ATTEST_PUBLIC_KEY):
        return "%s is committed on %s" % (ATTEST_PUBLIC_KEY, default)
    return ("%s is not on %s: the job refuses to sign until it is committed there" % (ATTEST_PUBLIC_KEY, default))


def ci_protect_attest(name, default, dry_run, recorded=False, delete_copies=False):
    """Set the harness-attest environment up for the attest job (ADR-005): only the default branch may deploy to it,
    no repository-level secret or variable of the same names may stand in for its own (delete_copies deletes them), and
    the default branch is recorded in the repository variable the job reads only when the user opted in (recorded=True)
    and the rule can't be read. States the mode the job runs in, and checks the result before it says so."""
    rule = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
    endpoint = "repos/%s/environments/%s" % (name, ATTEST_ENVIRONMENT)
    if dry_run or name.startswith("<"):
        print("ci-protect --attest: would refuse while repository secrets or variables %s exist (with "
              "--delete-repo-copies: delete them)" % ", ".join(ATTEST_SECRETS))
        print("ci-protect --attest: would PUT %s %s" % (endpoint, json.dumps(rule)))
        print("ci-protect --attest: would make %s the only deployment branch of %s" % (default, ATTEST_ENVIRONMENT))
        print("ci-protect --attest: would set the repository variable %s=%s" % (ATTEST_BRANCH_VARIABLE, default))
        print("ci-protect --attest: would %s" % (
            "set the repository variable %s=true" % ATTEST_RECORDED_VARIABLE if recorded
            else "delete the repository variable %s" % ATTEST_RECORDED_VARIABLE))
        print("ci-protect --attest: attest mode with %s in %s: %s" % (
            ATTEST_POLICY_SECRET, ATTEST_ENVIRONMENT, attest_mode(True, recorded)))
        print("ci-protect --attest: attest mode without it: %s" % attest_mode(False, recorded))
        print("ci-protect --attest: %s" % public_key_line(default))
        return 0 if dry_run else 1
    _, _, copies = attest_repository(name)
    if copies is None:
        print("ci-protect --attest: can't list %s's secrets and variables, so nothing was changed" % name)
        return 1
    for kind, copy in copies:
        if not delete_copies:
            print("ci-protect --attest: %s would stand in for the environment's or expose the key, and the attest "
                  "job refuses to sign while it exists" % copy_label(kind, copy))
        elif gh_api("repos/%s/actions/%s/%s" % (name, kind, copy), "DELETE")[0]:
            print("ci-protect --attest: deleted %s" % copy_label(kind, copy))
        else:
            print("ci-protect --attest: can't delete %s, so nothing else was changed" % copy_label(kind, copy))
            return 1
    if copies and not delete_copies:
        print("ci-protect --attest: nothing was changed. Put the key in %s first if it is only there, then run "
              "harness.py ci-protect --attest --delete-repo-copies to delete them" % ATTEST_ENVIRONMENT)
        return 1
    if not gh_api(endpoint, "PUT", rule)[0]:
        print("ci-protect --attest: can't set %s, so nothing else was changed" % ATTEST_ENVIRONMENT)
        return 1
    policies_endpoint = endpoint + "/deployment-branch-policies"
    ok, current = gh_api(policies_endpoint)
    for policy in (current or {}).get("branch_policies") or []:
        if (policy.get("type"), policy.get("name")) != ("branch", default):
            gh_api("%s/%s" % (policies_endpoint, policy.get("id")), "DELETE")
    kept = [(p.get("type"), p.get("name")) for p in (current or {}).get("branch_policies") or []]
    if ("branch", default) not in kept:
        gh_api(policies_endpoint, "POST", {"name": default, "type": "branch"})
    ok_env, environment = gh_api(endpoint)
    ok_policies, policies = gh_api(policies_endpoint)
    problems = environment_problems(environment, policies, default) if ok_env and ok_policies else ["unreadable"]
    if problems:
        print("ci-protect --attest: %s still doesn't match (%s); fix it in the repository's settings"
              % (ATTEST_ENVIRONMENT, "; ".join(problems)))
        return 1
    subprocess.run(["gh", "variable", "set", ATTEST_BRANCH_VARIABLE, "--body", default], cwd=str(ROOT),
                   capture_output=True, text=True)
    if recorded:
        subprocess.run(["gh", "variable", "set", ATTEST_RECORDED_VARIABLE, "--body", "true"], cwd=str(ROOT),
                       capture_output=True, text=True)
    else:
        subprocess.run(["gh", "variable", "delete", ATTEST_RECORDED_VARIABLE], cwd=str(ROOT),
                       capture_output=True, text=True)
    ok_secrets, listed = gh_api("repos/%s/environments/%s/secrets" % (name, ATTEST_ENVIRONMENT))
    names = [s.get("name") for s in (listed or {}).get("secrets") or [] if isinstance(s, dict)] \
        if ok_secrets and isinstance(listed, dict) else None
    print("ci-protect --attest: %s deploys only from %s; repository variable %s=%s recorded. Add the secrets %s to "
          "the environment only, and %s there too if the rule should be read live." % (
              ATTEST_ENVIRONMENT, default, ATTEST_BRANCH_VARIABLE, default, ", ".join(ATTEST_SECRETS),
              ATTEST_POLICY_SECRET))
    print("ci-protect --attest: attest mode: %s" % attest_mode(
        None if names is None else ATTEST_POLICY_SECRET in names, recorded))
    print("ci-protect --attest: %s" % public_key_line(default))
    return 0


# --------------------------------------------------------------------------- health

CHAINED_HOOKS = ("pre-commit", "commit-msg", "pre-push")


def chained_hooks_missing(hooks_path):
    """Hooks another manager owns (core.hooksPath set to, say, Husky's .husky/_) that don't hand on to the harness's.
    Husky's .husky/_/<hook> wrappers run .husky/<hook>, so that script counts too."""
    base = Path(hooks_path) if os.path.isabs(hooks_path) else ROOT / hooks_path
    places = [base] + ([base.parent] if base.name == "_" else [])
    return [name for name in CHAINED_HOOKS
            if not any(("%s/%s" % (HOOKS_PATH, name)) in read(place / name) for place in places)]


def plugin_mismatch():
    """Why the plugin running the hooks isn't the release this project pins, or None. The plugin supplies the agents,
    skills and agent rules; the pinned engine supplies the gates, so a mismatch pairs agents with gates they don't
    match (ADR-001)."""
    plugin_root, info = os.environ.get("HARNESS_PLUGIN_ROOT"), lock()
    if not plugin_root or info.get("mode") != "thin":
        return None
    try:
        plugin = (Path(plugin_root) / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        plugin = "unknown"
    pinned = str(info.get("version") or "")
    if plugin == pinned:
        return None
    return ("the agentic-harness plugin is v%s, but this project pins v%s: its agents and skills don't match the "
            "pinned gates. Update the plugin to v%s; or the user moves the pin (harness.py pin %s)"
            % (plugin, pinned, pinned, plugin))


def health():
    """List of (level, message) for misconfigurations; level is 'error' or 'warn'."""
    issues = []
    thin = thin_mode()
    hooks_path = git("config", "--get", "core.hooksPath").strip()
    if thin:
        if hooks_path != ".githooks":
            issues.append(("error", "git hooks inactive: core.hooksPath is %s, expected .githooks "
                                    "(fix: git config core.hooksPath .githooks)" % (hooks_path or "unset")))
        if not os.access(str(ROOT / ".githooks/pre-commit"), os.X_OK):
            issues.append(("error", ".githooks/pre-commit is missing or not executable"))
        if not (ENGINE / "AGENTS.md").is_file():
            issues.append(("error", "the pinned engine has no AGENTS.md to supply agent rules"))
        if "agentic-harness@agentic-harness" not in read(SETTINGS_FILE):
            issues.append(("error", ".claude/settings.json has no harness plugin entry"))
        mismatch = plugin_mismatch()
        if mismatch:
            issues.append(("error" if autonomous() else "warn", mismatch))
    else:
        unchained = chained_hooks_missing(hooks_path) if hooks_path and hooks_path != HOOKS_PATH else None
        if hooks_path != HOOKS_PATH and unchained != []:
            issues.append(("error", "git hooks inactive: core.hooksPath is %s, expected %s (fix: git config "
                                    "core.hooksPath %s, or have each hook there call %s/<hook>; missing: %s)"
                           % (hooks_path or "unset", HOOKS_PATH, HOOKS_PATH, HOOKS_PATH,
                              ", ".join(unchained or CHAINED_HOOKS))))
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
    for skill in sorted(skill_files().values()) if max_age else []:
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
    if values["HARNESS_REQ_STYLE"] not in REQ_STYLES:
        issues.append(("error", "HARNESS_REQ_STYLE must be one of %s" % "|".join(REQ_STYLES)))
    if values["HARNESS_PROFILE"] not in PROFILES:
        issues.append(("error", "HARNESS_PROFILE must be empty or one of %s" % "|".join(p for p in PROFILES if p)))
    if values["HARNESS_DELIVER"] not in DELIVER_MODES:
        issues.append(("error", "HARNESS_DELIVER must be on, off or external"))
    if values["HARNESS_TASK_BUDGET_USD"].strip() and dollars(values["HARNESS_TASK_BUDGET_USD"]) is None:
        issues.append(("error", "HARNESS_TASK_BUDGET_USD must be empty or a number of dollars"))
    unusable = sandbox.problem(values["HARNESS_SANDBOX_BACKEND"])
    if unusable:
        issues.append(("error", unusable))
    unpublished = sandbox.unpublished_allowlist()
    if unpublished:
        issues.append(("error", unpublished))
    stale = stale_sandbox_config()
    if stale:
        issues.append(("warn", stale))
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
    for key in ("HARNESS_RISK_TERMS", "HARNESS_RISK_PATHS", "HARNESS_DOC_PATHS"):
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
    missing = [a for a in PIPELINE_AGENTS if not any((d / ("%s.md" % a)).is_file() for d in AGENT_DIRS)]
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


def stale_sandbox_config():
    """A warning when the project's devcontainer.json starts one container and no egress container: an edited copy that
    an update kept (ADR-003)."""
    try:
        text = (ROOT / ".devcontainer/harness-agent/devcontainer.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        config = sandbox.jsonc_loads(text)
    except ValueError:
        return ("devcontainer.json can't be parsed, so doctor can't tell whether it predates the two-container sandbox "
                "(ADR-003): check it against devcontainer.json.harness-new (if update wrote one)")
    if not isinstance(config, dict) or config.get("dockerComposeFile"):
        return None
    return ("devcontainer.json predates the two-container sandbox (ADR-003): it names no dockerComposeFile, so the egress "
            "container never starts. Take the upstream file (devcontainer.json.harness-new, if update wrote one) and move "
            "HARNESS_FIREWALL_ALLOW into docker-compose.yml")


def doctor():
    info = lock()
    values = conf()
    print("agentic harness %s  project: %s  stack packs: %s" % (info.get("harness_version", "?"),
                                                                 values["HARNESS_PROJECT_NAME"] or ROOT.name,
                                                                 adopted_summary(info)))
    issues = health()
    if (ROOT / ".github/workflows/harness-verify.yml").is_file():
        mode, attest_issues = attest_health()
        print("attest mode: %s" % mode)
        issues += attest_issues
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


def recorded_hash(info, rel_path):
    """The hash the lock records for a harness file: under "files", or under "kept" in a thin project."""
    for table in ("files", "kept"):
        if rel_path in (info.get(table) or {}):
            return info[table][rel_path]
    return None


def record_hash(info, rel_path, digest):
    forget_hash(info, rel_path)
    # verify takes a lock with "files" for a full install's and refuses every change to .claude/settings.json; CI runs
    # the base branch's engine, perhaps an older release, so a thin lock keeps its hashes under "kept", as
    # update.sh --to-thin and init --thin do.
    info.setdefault("kept" if info.get("mode") == "thin" else "files", {})[rel_path] = digest


def forget_hash(info, rel_path):
    for table in ("files", "kept"):
        (info.get(table) or {}).pop(rel_path, None)


def thin_hashes_under_kept(info):
    """An earlier engine's adopt recorded a thin project's hashes under "files", and verify reads a non-empty "files"
    as a full install: it would refuse every change to .claude/settings.json."""
    if info.get("mode") == "thin" and "files" in info:
        for rel_path, digest in info.pop("files").items():
            info.setdefault("kept", {})[rel_path] = digest


def conflict_with_edit(info, rel_path, src):
    """The user edited the pack file and the release changed it too, so adopt keeps the edit."""
    current, recorded, release_digest = sha256(ROOT / rel_path), recorded_hash(info, rel_path), sha256(src)
    return current not in (None, recorded, release_digest) and recorded != release_digest


def check_pack_files(info, name, files, dropped):
    """Refuses before anything is written: a project file the lock doesn't know, or a <file>.harness-new that a
    conflict would overwrite (it may hold a half-merged version). A file the pack dropped and the user kept is known."""
    for rel_path, src in sorted(files.items()):
        dest = ROOT / rel_path
        if (dest.exists() and rel_path not in dropped and recorded_hash(info, rel_path) is None
                and sha256(dest) != sha256(src)):
            raise HarnessError("%s already exists as a project file; rename it or remove it before adopting %s"
                               % (rel_path, name))
        if (ROOT / (rel_path + ".harness-new")).exists() and conflict_with_edit(info, rel_path, src):
            raise HarnessError("%s.harness-new already exists; merge it into %s and delete it, then adopt again"
                               % (rel_path, rel_path))


def report_new_copy(report, rel_path):
    if (ROOT / (rel_path + ".harness-new")).exists():
        report.append("left    %s.harness-new (not removed; merge it or delete it yourself)" % rel_path)


def adopt(names, adr, chosen, declined, dry_run):
    info = lock()
    thin_hashes_under_kept(info)
    adopted = info.setdefault("adopted", {})
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
    payloads = [(name, options, pack_payload(name, options)) for name, options in plans]
    for name, _, (files, _, _, _) in payloads:
        check_pack_files(info, name, files, set((adopted.get(name) or {}).get("dropped", [])))
    today = time.strftime("%Y-%m-%d")
    guardrails, routing, conf_text = read(BACKBONE / "guardrails.conf"), read(BACKBONE / "routing.conf"), read(CONF_FILE)
    report, conflicts = [], []
    for name, options, (files, rules, routes, values) in payloads:
        previous = set((adopted.get(name) or {}).get("files", []))
        dropped = set((adopted.get(name) or {}).get("dropped", []))
        for rel_path in sorted(previous - set(files)):
            if sha256(ROOT / rel_path) == recorded_hash(info, rel_path):
                report.append("remove  %s" % rel_path)
                if not dry_run:
                    (ROOT / rel_path).unlink()
            elif (ROOT / rel_path).exists():
                report.append("kept    %s (edited locally; no longer part of the pack)" % rel_path)
                dropped.add(rel_path)
            forget_hash(info, rel_path)
            report_new_copy(report, rel_path)
        for rel_path, src in sorted(files.items()):
            dest, release_digest = ROOT / rel_path, sha256(src)
            current, recorded = sha256(dest), recorded_hash(info, rel_path)
            dropped.discard(rel_path)
            if conflict_with_edit(info, rel_path, src):
                report.append("CONFLICT %s (edited locally, and the release's copy differs: the new version is in "
                              "%s.harness-new)" % (rel_path, rel_path))
                conflicts.append(rel_path)
                if not dry_run:
                    shutil.copyfile(str(src), str(dest) + ".harness-new")
                    record_hash(info, rel_path, release_digest)
            elif current not in (None, recorded, release_digest):
                report.append("kept    %s (edited locally; the release has not changed it)" % rel_path)
            else:
                report.append("install %s" % rel_path)
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(src), str(dest))
                    shutil.copymode(str(src), str(dest))
                    record_hash(info, rel_path, release_digest)
            if (ROOT / (rel_path + ".harness-new")).exists() and rel_path not in conflicts:
                report.append("pending %s.harness-new (not merged yet: merge it into %s and delete it)"
                              % (rel_path, rel_path))
                conflicts.append(rel_path)
        header = "(%s, %s; options: %s)" % (adr, today, ", ".join(options) or "none")
        guardrails = replace_block(guardrails, name, rules or ["# (no rules)"], header)
        routing = replace_block(routing, name, routes or ["# (no routes)"], header)
        conf_text = set_conf_values(conf_text, values)
        report.append("rules   %d guardrail(s), %d route(s) into backbone/guardrails.conf and routing.conf"
                      % (len(rules), len(routes)))
        report.extend("conf    %s=\"%s\"" % kv for kv in sorted(values.items()))
        adopted[name] = {"adr": adr, "options": options, "date": today, "files": sorted(files)}
        if dropped:
            adopted[name]["dropped"] = sorted(dropped)
    if not dry_run:
        (BACKBONE / "guardrails.conf").write_text(guardrails, encoding="utf-8")
        (BACKBONE / "routing.conf").write_text(routing, encoding="utf-8")
        CONF_FILE.write_text(conf_text, encoding="utf-8")
        write_lock(info)
    print("%s %s from %s:" % ("Would adopt" if dry_run else "Adopted", ", ".join(n for n, _ in plans), adr))
    print("\n".join("  " + line for line in report))
    if conflicts:
        print("Resolve each conflict: merge <file>.harness-new into <file> and delete the .harness-new file.")
    if not dry_run:
        print("Record the adoption in %s's Consequences, list the skills in backbone/9-AGENT-SKILLS.md, and commit." % adr)
    return 1 if conflicts else 0


def unadopt(names, dry_run):
    info = lock()
    thin_hashes_under_kept(info)
    adopted = info.get("adopted", {})
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
            if sha256(ROOT / rel_path) == recorded_hash(info, rel_path):
                report.append("remove  %s" % rel_path)
                if not dry_run:
                    (ROOT / rel_path).unlink()
            else:
                report.append("kept    %s (edited locally; delete it yourself if unwanted)" % rel_path)
            forget_hash(info, rel_path)
            report_new_copy(report, rel_path)
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


EVENTS_FILE = []   # resolved once per process: events now fire on every edit, and each lookup runs git


def events_file():
    if EVENTS_FILE:
        return EVENTS_FILE[0]
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(ROOT), capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except subprocess.TimeoutExpired:
        common = ".git"
    base = Path(common) if common and os.path.isabs(common) else ROOT / (common or ".git")
    EVENTS_FILE.append(base / "harness" / "events.jsonl")
    return EVENTS_FILE[0]


HOOK_CONTEXT = {}   # who the current hook call is for: session and agent, set by main()


def log_event(kind, **fields):
    """Append one event to .git/harness/events.jsonl (never fails the caller). Events carry the task in progress and,
    inside a hook, the session and agent, so harness.py trace can rebuild a task's history."""
    try:
        path = events_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "v": CONTRACT_VERSION}
        entry.update({k: v for k, v in HOOK_CONTEXT.items() if v})
        if "task" not in fields:
            tasks = wip_task_ids()
            if len(tasks) == 1:
                entry["task"] = tasks[0]
        entry.update(fields)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    except Exception:   # deny() logs before it exits 2; raising here would exit 1 and let the call through
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
        return line_endings(tool_input.get("content"))
    if tool == "Edit":
        return line_endings(tool_input.get("new_string"))
    return "\n".join(line_endings((edit or {}).get("new_string")) for edit in tool_input.get("edits") or [])


def resulting_text(tool, tool_input, path_str):
    if tool == "Write":
        return line_endings(tool_input.get("content"))
    path = Path(path_str)
    current = read(path if path.is_absolute() else ROOT / path)
    edits = [tool_input] if tool == "Edit" else (tool_input.get("edits") or [])
    for edit in edits:
        old, new = line_endings(edit.get("old_string")), line_endings(edit.get("new_string"))
        if not old:
            continue
        current = current.replace(old, new) if edit.get("replace_all") else current.replace(old, new, 1)
    return current


def hook_session_start(_data):
    values = conf()
    info = lock()
    thin = thin_mode()
    lines = ["[agentic harness %s] project: %s, stack packs: %s"
             % (info.get("harness_version") or info.get("version") or "?",
                values["HARNESS_PROJECT_NAME"] or ROOT.name, adopted_summary(info))]
    if thin:
        rules = read(ENGINE / "AGENTS.md")
        if rules:
            command = "python3 %s" % shlex.quote(str(ENGINE / "scripts/harness/lib/harness.py"))
            rules = rules.replace(
                "Project knowledge lives in `backbone/`, role agents in `.claude/agents/`, skills in "
                "`.claude/skills/`, and hooks in `scripts/harness/` enforce the process.",
                "Project knowledge lives in `backbone/`. The plugin supplies role agents and core skills; "
                "the pinned engine enforces the process through hooks.")
            rules = rules.replace("Skills live in `.claude/skills/<name>/SKILL.md`:",
                                  "Project skills live in `.claude/skills/<name>/SKILL.md`; core skills come from "
                                  "the plugin:")
            rules = rules.replace("python3 scripts/harness/lib/harness.py", command)
            rules = rules.replace("scripts/harness/routing.core.conf",
                                  str(ENGINE / "scripts/harness/routing.core.conf"))
            lines.extend(("Agent rules from the pinned engine (there is no project AGENTS.md):", rules))
        lines.append(thin_paths())
        if HOOK_SOURCE in USER_AGENTS:
            lines.extend(install_user_agents(HOOK_SOURCE))
    pending = placeholders()
    if pending:
        lines.append("SETUP INCOMPLETE: %d FILL placeholder(s) in %s. Run first-run setup "
                     "(agent rules section 1) with the user before any other work."
                     % (sum(pending.values()), ", ".join(sorted(pending))))
    else:
        lines.append("Before changing anything read: %sbackbone/4-KNOWLEDGE.md, backbone/7-CONVENTIONS.md, "
                     "backbone/8-WORKFLOW.md, backbone/3-TASKS.md." % ("" if thin else "AGENTS.md, "))
    snapshot_refresh()
    mismatch = plugin_mismatch()
    if mismatch and not autonomous():   # autonomous mode lists it below, with the other errors
        lines.append("PLUGIN MISMATCH: " + mismatch + ".")
    if values["HARNESS_REQ_STYLE"] == "ears":
        lines.append("REQUIREMENTS IN EARS (HARNESS_REQ_STYLE=ears): every REQ follows an EARS pattern; read "
                     "requirements-writing/ears.md. spec-check enforces it.")
    if profile():
        lines.append("PROFILE %s: only a human merges. Never merge a pull request or run harness.py orca with --merge "
                     "or --trust." % profile())
    if autonomous():
        lines.append("AUTONOMOUS MODE: no user is in the loop. Never ask the user; approve low-risk specs with "
                     "harness.py approve <id>, escalate everything else with harness.py escalate <id> --reason ..., "
                     "and continue with the next ready task (agent rules section 7).")
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
        lines.append("Harness problems (details: %s):" %
                     ("python3 %s doctor" % (ENGINE / "scripts/harness/lib/harness.py")
                      if thin else "scripts/harness/doctor.sh"))
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


def hook_subagent_start(_data):
    # Role agents' instructions name the full-install paths, and a subagent doesn't see the session-start context.
    if thin_mode():
        add_context("SubagentStart", thin_paths())


def hook_pre_tool_use(data):
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if halt_file().exists():
        deny("Harness halted: %s exists (the user's kill switch). Stop working and report your state; the user "
             "removes the file to resume." % halt_file())
    if autonomous() and tool not in ("Read", "Grep", "Glob", "LS"):
        mismatch = plugin_mismatch()
        if mismatch:
            deny("Harness blocked this call: %s. In autonomous mode no work runs until they match; stop and report "
                 "it." % mismatch)
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
        if data.get("harness_role"):
            hook_agent_guard(data, data["harness_role"])
        problems = ["  - " + p for p in shell_findings(command, data.get("cwd"))]
        hits = check_text(rules, None, rule_text(command), ("block",))
        if hits:
            log_rule_hits(hits)
            problems.append(describe(hits))
        if problems:
            deny("Harness blocked this command:\n%s\nIf the user really wants it, ask them to run it "
                 "themselves (in Claude Code: `! <command>`). Do not rephrase the command to get "
                 "around the rule." % "\n".join(problems))
        refusal = external_refusal(command) if conf()["HARNESS_DELIVER"] == "external" else None
        if refusal:
            deny("Harness blocked this command: %s" % refusal)
        if not autonomous():
            command_started(data)
        return
    if tool not in FILE_TOOLS:
        tool_gate(data, tool, tool_input)
        return
    if not tool_input.get("file_path"):
        return
    path_str = tool_input["file_path"]
    if in_git_dir(path_str, data.get("cwd")):
        deny("Harness blocked this change: " + GIT_DIR_REFUSAL % path_str)
    label = install_path(path_str, data.get("cwd"))
    if label:
        deny("Harness blocked this change to %s: it is in %s, which decides this project's gates. The user changes "
             "it (with pin, or a plugin update)." % (path_str, label))
    path = canonical(rel(path_str))
    if data.get("harness_role"):
        hook_agent_guard(data, data["harness_role"])
    if path.startswith("backbone/.verdicts/"):
        deny("Harness blocked this change to %s: verdicts are recorded only by the griller's and judge's hooks."
             % path)
    problems = []
    hits = check_text(rules, path, added_text(tool, tool_input), ("block",))
    if hits:
        log_rule_hits(hits)
        problems.append(describe(hits))
    checks = ()
    if path == LOCK_FILE.relative_to(ROOT).as_posix():
        deny("Harness blocked this change to %s: the lock is written by the installer and harness.py adopt only."
             % path)
    if path == ".githooks/pre-commit" and lock().get("mode") == "thin":
        deny("Harness blocked this change to %s: in thin mode it is the shim that runs the pinned engine's checks, "
             "written by init --thin only." % path)
    if path == "backbone/tools.conf":
        deny("Harness blocked this change to %s: the tool contracts decide what agents may run, so only the user "
             "changes them. Ask the user to edit it." % path)
    if path == "backbone/escalations.md":
        deny("Harness blocked this change to %s: escalations are written by harness.py escalate and resolved by "
             "the user." % path)
    if path == "backbone/3-TASKS.md":
        checks = (wip_collision, start_gate, judge_gate, blocked_guard, light_guard)
    elif path == "backbone/harness.conf":
        checks = (user_only_change,)
    elif re.match(r"^backbone/specs/[^/]+\.md$", path):
        checks = (spec_guard,)
    elif re.match(r"^backbone/adr/[^/]+\.md$", path):
        checks = (adr_guard,)
    before = after = None
    if checks:
        before = read(ROOT / path)
        after = resulting_text(tool, tool_input, path_str)
        for check in checks:
            problem = check(before, after)
            if problem:
                log_event("gate", gate=check.__name__)
                problems.append(problem)
    scope = orchestrator_scope(data, path)
    if scope:
        log_event("gate", gate="orchestrator_scope")
        problems.append(scope)
    skills = skill_gate(data, path)
    if skills:
        log_event("gate", gate="skill_gate")
        problems.append(skills)
    if problems:
        deny("Harness blocked this change to %s:\n%s" % (path, "\n".join(problems)))
    if path == "backbone/3-TASKS.md":
        for task in started_tasks(before, after):
            log_event("task-start", task=task)
            record_light_start(task)
        for task in finished_tasks(before, after):
            if task_state_in(after, task) == "done":
                log_event("task-finish", task=task)


def parse_tool_contracts(text):
    """Lines of `<tool or pattern>... <class> [path=<field>[,<field>]] [confirm]`; patterns are shell-style."""
    contracts = []
    for line in (text or "").splitlines():
        words = line.split("#", 1)[0].split()
        # The class is the last class word: OpenCode names a tool "read", which is also a class.
        at = max((i for i, w in enumerate(words) if w in TOOL_CLASSES), default=None)
        if not at:
            continue
        cls = words[at]
        options = words[at + 1:]
        paths = [f for w in options if w.startswith("path=") for f in w[5:].split(",") if f]
        for pattern in words[:at]:
            contracts.append({"pattern": pattern, "class": cls, "paths": paths, "confirm": "confirm" in options})
    return contracts


def tool_contract(tool):
    for contract in parse_tool_contracts(BUILTIN_TOOL_CONTRACTS) + parse_tool_contracts(read(TOOLS_FILE)):
        if fnmatch.fnmatchcase(tool, contract["pattern"]):
            return contract
    return None


def contract_paths(contract, tool_input):
    paths = []
    for field in contract["paths"]:
        value = tool_input.get(field)
        paths.extend(v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v)
    return paths


def tool_gate(data, tool, tool_input):
    """Tools other than Bash and the file tools: what their contract (backbone/tools.conf) says they may do."""
    if profile() in NO_MERGE_PROFILES and MERGE_TOOL.search(tool):
        deny("Harness blocked %s: merging is refused under HARNESS_PROFILE=%s; only a human merges." % (tool, profile()))
    contract = tool_contract(tool)
    if contract is None:
        log_event("tool-unknown", tool=tool)
        if autonomous():
            deny("Harness blocked %s: it has no tool contract, so the gates can't tell what it changes. In autonomous "
                 "mode only tools with a contract run; the user adds one to backbone/tools.conf (for example "
                 "`%s write path=<the input field that holds the path>`)." % (tool, tool))
        add_context("PreToolUse", "Harness: %s has no tool contract in backbone/tools.conf, so the gates don't check "
                    "what it changes. Make file changes with Write or Edit, and tell the user, who can add a contract."
                    % tool)
        return
    if contract["confirm"] and autonomous():
        deny("Harness blocked %s: its contract in backbone/tools.conf says confirm, and in autonomous mode no one is "
             "there to confirm it. Leave it for the user and say so in your report." % tool)
    if contract["class"] != "write":
        return
    paths = contract_paths(contract, tool_input)
    if not paths:
        if autonomous():
            deny("Harness blocked %s: its contract in backbone/tools.conf names no path field, so the gates can't "
                 "see which files it writes. The user adds path=<field> to its line." % tool)
        add_context("PreToolUse", "Harness: the contract for %s names no path field, so the gates don't check which "
                    "files it writes." % tool)
        return
    for path_str in paths:
        path = canonical(rel(path_str))
        if any(re.search(pattern, path) for pattern in SHELL_PROTECTED):
            deny("Harness blocked %s on %s: harness files change only through the Write or Edit tools, where the "
                 "gates see the whole change." % (tool, path))
        hook_pre_tool_use(dict(data, tool_name="Write", tool_input={"file_path": path_str, "content": ""}))


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
        add_context(data.get("hook_event_name") or "PostToolUse", "\n\n".join(notes))


# Reads worth a trace line: the project knowledge and instructions an agent based its work on, not every code file.
CONTEXT_SOURCES = r"^(backbone/|\.claude/skills/|AGENTS\.md$|CLAUDE\.md$)"
SKILL_READERS = ("cat", "sed", "head", "tail", "less", "more", "bat", "nl", "awk")


def shell_skills(command, cwd=None):
    command, _ = split_heredocs(command)
    for segment, _ in split_segments(command):
        try:
            lexer = shlex.shlex(segment, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            words = list(lexer)
        except ValueError:
            continue
        prog = program(words)
        if prog == "cd" and len(words) == 2:
            cwd = ROOT / (cwd or "") / Path(words[1]).expanduser()
        if prog not in SKILL_READERS:
            continue
        for index, word in enumerate(words[1:], 1):
            if index > 1 and ">" in words[index - 1]:
                continue
            if Path(word).name == "SKILL.md":
                skill = skill_read(word, cwd)
                if skill:
                    yield skill


def tool_result(data):
    """How a Bash call ended, as far as the agent CLI says: failed, succeeded or unknown. Claude Code sends failures to
    PostToolUseFailure; the OpenCode adapter passes OpenCode's status (tool_status), which its v1 API doesn't give;
    Codex says nothing either way."""
    response = data.get("tool_response") if isinstance(data.get("tool_response"), dict) else {}
    code = next((response[k] for k in ("exit_code", "exitCode", "returncode") if number(response.get(k))), None)
    if (data.get("hook_event_name") == "PostToolUseFailure" or response.get("interrupted") is True
            or data.get("tool_status") == "error" or code not in (None, 0)):
        return "failed"
    if code == 0 or data.get("tool_status") == "completed" or (
            HOOK_SOURCE == "claude" and data.get("hook_event_name") == "PostToolUse"):
        return "succeeded"
    return "unknown"


def post_tool_notes(data):
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    notes = []
    if tool == "Read":
        path = rel(tool_input.get("file_path") or "")
        skill = skill_read(tool_input.get("file_path") or "")
        if skill:
            remember_skill(data, skill)
        elif re.match(CONTEXT_SOURCES, path):
            log_event("context", path=path)
        return notes
    if tool == "Skill":
        skill = skill_invoked(str(tool_input.get("skill") or tool_input.get("name") or "").strip())
        if skill:
            remember_skill(data, skill)
        return notes
    if tool in FILE_TOOLS and tool_input.get("file_path"):
        snapshot_refresh()
        path = rel(tool_input["file_path"])
        log_event("edit", path=path, tool=tool)
        rules, _ = load_rules()
        hits = check_text(rules, path, added_text(tool, tool_input), ("warn",))
        if hits:
            log_rule_hits(hits)
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
    elif tool not in ("Bash", "apply_patch") and not tool.startswith(KNOWLEDGE_TOOL_PREFIX):
        contract = tool_contract(tool)
        if contract and contract["class"] != "read":
            log_event("tool", tool=tool, paths=[rel(p) for p in contract_paths(contract, tool_input)],
                      **{"class": contract["class"]})
    elif tool == "Bash":
        command = tool_input.get("command") or ""
        log_outward(command, data.get("harness_role") or "session", tool_result(data))
        # Agents without a Read or Skill tool (Codex) load a skill by printing its SKILL.md.
        for skill in shell_skills(command, data.get("cwd")):
            remember_skill(data, skill)
        rules, _ = load_rules()
        hits = check_text(rules, None, rule_text(command), ("warn",))
        if hits:
            log_rule_hits(hits)
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
        else:
            changed, commands = command_finished(data)
            if changed:
                log_event("tamper", files=changed[:20], command=command[:300], running=commands[:5])
                notes.append("Harness-protected files changed during `%s`, outside the Write/Edit tools: %s. If a "
                             "command changed them, restore them (git checkout -- <file>) and make the change with "
                             "the file tools, where the gates apply. The user may also have edited them meanwhile."
                             % ("` or `".join(c[:120] for c in commands), ", ".join(changed[:8])))
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


def default_branch():
    ref = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
    return ref.rsplit("/", 1)[-1] if ref else None


# The deliverer's gh calls, read as the shell and gh would read them. What the harness can't read is refused.
RUNNERS = ("timeout", "gtimeout", "nice", "nohup", "stdbuf", "time", "env", "sudo", "doas", "command", "exec",
           "watch", "ionice", "chronic", "caffeinate", "flock", "setsid", "unbuffer", "script", "su")
SHELL_KEYWORDS = ("!", "(", ")", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until")
# bash's and zsh's precommand modifiers, which take no options: the command follows them.
PRECOMMANDS = ("builtin", "noglob", "nocorrect")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIRECTION = re.compile(r"^[0-9]*(<<<|<<-?|<>|<&|>&|>>|>\||&>>|&>|<|>)")
EXPANSION = re.compile(r"\$\S|`")
# bash's and zsh's alias tables: setting an entry defines an alias, as the alias builtin does.
ALIAS_TABLE = re.compile(r"^(BASH_ALIASES|aliases)(\[[^\]]*\])?\+?=")
# The gh commands delivery needs (ADR-002), with gh's own aliases for them. gh api, held to reads, is checked apart.
DELIVERY_GH = {"pr": ("create", "new", "edit", "view", "checks", "list", "ls"),
               "run": ("view", "list", "ls", "watch"), "label": ("create", "list", "ls"), "repo": ("view",)}
# The flags that take a value (gh pr|issue create|new|edit, gh api, gh label create). Every other flag is a switch.
ITEM_VALUE_FLAGS = ("-a", "-B", "-b", "-F", "-H", "-l", "-m", "-p", "-r", "-R", "-T", "-t", "--add-assignee",
                    "--add-blocked-by", "--add-blocking", "--add-label", "--add-project", "--add-reviewer",
                    "--add-sub-issue", "--assignee", "--attach", "--base", "--blocked-by", "--blocking", "--body",
                    "--body-file", "--head", "--json", "--label", "--milestone", "--parent", "--project", "--recover",
                    "--repo",
                    "--remove-assignee", "--remove-blocked-by", "--remove-blocking", "--remove-label",
                    "--remove-project", "--remove-reviewer", "--remove-sub-issue", "--reviewer", "--template",
                    "--title", "--type")
API_VALUE_FLAGS = ("-F", "-f", "-H", "-p", "-q", "-t", "-X", "--cache", "--field", "--header", "--hostname", "--input",
                   "--jq", "--method", "--preview", "--raw-field", "--template")
LABEL_VALUE_FLAGS = ("-c", "-d", "-R", "--color", "--description", "--repo")
MERGE_REFUSAL = "it opens and updates the PR; merging is the user's call, like closing or approving it."
EXTERNAL_REFUSAL = ("delivery is external here (HARNESS_DELIVER=external): the factory pushes and talks to GitHub from "
                    "its trusted clone, and the lane has no credentials to; agents run gh reads only and no git push "
                    "(nor git or gh through xargs or find -exec, nor git's own git-* programs). Stop and report")
EXPANSION_REFUSAL = ("write the gh command out: an expansion ($... or `...`) outside a flag's value can add flags or "
                     "commands the harness can't read.")
DELIVERY_GH_REFUSAL = ("it runs only the gh commands delivery needs: gh pr create, edit, view, checks and list, "
                       "gh run view, list and watch, gh label list and create, gh repo view, and gh api reads. %s is "
                       "the user's call.")
# The shell expands these unquoted into other words: a brace expansion names another command or flag, and a glob adds
# the names of files the harness doesn't see. A comma expands only inside braces, which are refused already.
GLOB_CHARS = "{}*?[]"
ENV_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
# A browser, pager or editor runs the command it's set to; ssh and askpass commands run for git's network calls; the
# rest point gh or git at another program or configuration.
RISKY_ENV = ("BROWSER", "PAGER", "EDITOR", "VISUAL", "PATH", "HOME", "ENV", "BASH_ENV", "IFS", "SHELLOPTS", "BASHOPTS",
             "LESSOPEN", "LESSCLOSE", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "NODE_OPTIONS", "PYTHONPATH",
             "XDG_CONFIG_HOME")
RISKY_ENV_PREFIXES = ("GH_", "GIT_", "DYLD_", "LD_", "BASH_FUNC_")
GIT_OPTIONS_REFUSED = ("-c", "--config-env", "--exec-path", "--git-dir", "--work-tree")
GIT_CONFIG_READS = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list")
GIT_CONFIG_WRITES = ("--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section",
                     "--edit", "-e")
GLOB_REFUSAL = ("the shell expands an unquoted {, }, *, ?, [ or ] into words the harness doesn't read: quote it, as "
                "written.")
ENV_REFUSAL = ("it sets %s for the command: a browser, pager or editor runs the command it names, and PATH, HOME, "
               "GH_ and GIT_ settings change what gh and git run or read; that's the user's call.")
WEB_REFUSAL = ("--web hands a URL to a browser, which runs whatever BROWSER names; the deliverer doesn't open pages.")
GIT_OPTION_REFUSAL = ("it runs git with its own configuration (-c, --config-env, --exec-path, --git-dir, --work-tree): "
                      "an alias or ssh command set there runs a command the harness doesn't read.")
GIT_CONFIG_REFUSAL = ("it doesn't change git's configuration: an alias that starts with ! or an ssh command runs a "
                      "command the harness doesn't read. Reading it (git config --get, --list) is fine.")
GIT_EXEC_REFUSAL = "--exec, --upload-pack and --receive-pack run a command the harness doesn't read."
PUSH_ALL_REFUSAL = "--all and --mirror push every branch, the default one included: push the branch by name."
PUSH_DEFAULT_REFUSAL = ("it pushes only its own branch; the default branch changes through the PR, when the user "
                        "merges it.")
PUSH_AFTER_SWITCH_REFUSAL = ("it doesn't push in a command that changes the branch (git checkout, switch): the harness "
                             "checks a push against the branch the checkout is on now. Push in a command of its own.")
REBASE_BRANCH_REFUSAL = ("git rebase with a branch argument checks that branch out first, and fast-forwards it: the "
                         "deliverer rebases only its own branch onto an upstream (git rebase origin/main).")
INTERACTIVE_REBASE_REFUSAL = ("an interactive rebase (-i, --interactive, --edit-todo, pull --rebase=interactive) waits "
                              "for an editor the deliverer can't drive: rebase with no -i (git rebase origin/main).")
# Short flags that take the rest of their cluster as a value, so an i after them is that value, not -i.
REBASE_VALUE_FLAGS = {"rebase": "sXxCS", "pull": "sXjSo"}
COPY_PROGRAMS = ("ln", "link", "cp", "mv", "install", "rsync", "ditto", "hash")
CODE_PROGRAMS = ("awk", "gawk", "mawk", "nawk", "sed", "osascript", "fish", "csh", "tcsh", "tclsh", "pwsh", "lua", "php",
                 "expect", "busybox", "jshell", "jrunscript", "Rscript", "julia", "runghc", "scala", "groovy", "swift",
                 "ed", "ex", "vi", "vim", "nvim", "emacs", "less", "more", "man")
# pytest loads any module as a plugin (-p code) and imports the conftest.py files it finds.
TEST_RUNNERS = ("pytest", "py.test")
LATER_PROGRAMS = ("coproc", "trap")
RUNTIMES = re.compile(r"(?:python|perl|ruby|node|nodejs|bun|deno|tsx|ts-node)[\d.]*")
# uv, pipx and poetry run a package, a script or an interpreter with whatever arguments follow.
REGISTRY_RUNNERS = ("npx", "bunx", "pnpx", "uvx", "uv", "pipx", "poetry")
PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun", "deno")
REGISTRY_SUBCOMMANDS = ("x", "exec", "dlx", "create", "eval", "repl")
MAKE_LIKE = ("make", "gmake", "just", "task", "ninja")
# Build and task files a tool reads from the working directory as code, when a command writes one of them.
IMPLICIT_READERS = MAKE_LIKE + ("npm", "pnpm", "yarn", "bun", "deno")
VERSION_FLAGS = ("--version", "-V", "--help", "-h")
# Node's and Bun's -v is their version; Python's and Ruby's is verbose mode, which then reads stdin.
SHORT_VERSION_FLAG = ("node", "nodejs", "bun", "deno", "perl")
INLINE_CODE = re.compile(r"^-(?!-)[A-Za-z]*[cepEmi]|^--(eval|print|command|interactive)(=|$)")
PERL_MODULE = re.compile(r"[A-Za-z_][\w:]*(?:=[\w.,:/+-]*)?")
# A URL, a registry or JSR package, or a data: URL is code from outside the repo.
URL_WORD = re.compile(r"data:|://|^(npm|jsr):")
# A stdin path or a file descriptor a program reads a file from: -, /dev/stdin, /dev/fd/N, /proc/self/fd/N.
STDIN_FILE = re.compile(r"(?:^|=|-[A-Za-z])(?:/dev/stdin|/dev/fd/\d+|/proc/self/fd/\d+|-)$")
WRITE_REDIRECTION = re.compile(r"(?:&>>?|>>?\|?)\s*")
# The options that name the file a download writes.
OUTPUT_OPTIONS = {"curl": ("-o", "--output"), "wget": ("-O", "--output-document")}
SYSTEM_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/opt/", "/Library/", "/System/", "/Applications/", "/nix/")
GITHUB_REPO = re.compile(r"github\.com[/:]([^/\s]+/[^/\s#?]+?)(?:\.git)?(?:[/#?\s]|$)")
# The git commands that change which branch HEAD names, so a push after one pushes a branch the gate didn't check.
BRANCH_CHANGES = ("checkout", "switch", "symbolic-ref", "bisect", "worktree")
REF_COMMANDS = ("checkout", "switch", "merge", "rebase", "reset", "branch", "fetch", "pull", "update-ref",
                "symbolic-ref", "restore", "cherry-pick", "revert", "am", "worktree", "push")
# Matched on command_view, the command without a PR's title and body. Heredoc bodies stay in the text, so a merge named
# in one is refused too; the parser reads only the calls it can see, and this catches a merge it can't.
FORBIDDEN_TEXT = re.compile(
    r"\bgh\b[^;&|\n]*?\b(?:pr\s+(?:merge|close|review|ready)\b|api\b[^;&|\n]*?/merge\b|repo\s+(?:edit|delete)\b"
    r"|--enable-auto-merge\b|workflow\s+run\b|(?:secret|variable)\s+set\b|run\s+rerun\b)"
    r"|\bgit\b[^;&|\n]*?(?:\s-c\b|--exec\b|--upload-pack\b|--receive-pack\b|--config-env\b|--git-dir\b"
    r"|--work-tree\b|\bpush\b[^;&|\n]*?--(?:all|mirror)\b)")
PR_TEXT_VALUE = re.compile(r"""(?<!\S)(?:--body|--title|-b|-t)(?:=|\s+)("(?:[^"\\]|\\.)*"|'[^']*'|\S+)""")
COPY_REFUSAL = ("it copies or links a program, which can run gh or git under another name; the deliverer runs gh and git "
                "by name.")
CODE_REFUSAL = ("%s runs the code or commands its arguments name, which the harness doesn't read; the deliverer runs no "
                "%s.")
LATER_REFUSAL = "%s runs a command later, which the harness doesn't read; run the command where it's written."
INLINE_REFUSAL = "%s runs code from its arguments (-c, -e, -p, -i), which the harness doesn't read: run a script file."
STDIN_REFUSAL = "%s reads its code from stdin, which the harness doesn't read: run a script file."
MODULE_REFUSAL = ("%s runs a module that can run any code it's given (pty and pdb run what they're given, unittest "
                  "imports what it names, pytest loads any plugin): the deliverer runs no tests and no modules.")
PERL_MODULE_REFUSAL = "perl -M runs the code its argument holds, which the harness doesn't read: name a module."
URL_REFUSAL = ("%s loads code from a URL, a package or a data: URL, which the harness doesn't read: run a script file "
               "in the repo.")
REGISTRY_REFUSAL = ("%s runs a package from the registry, or the code its arguments hold, which the harness doesn't "
                    "read: the deliverer runs no packages.")
JAVA_REFUSAL = ("java --source, or - for its code, runs Java the harness doesn't read: run a compiled class or a jar "
                "the repo has.")
GO_REFUSAL = ("go run -exec runs a command, and a stdin, /dev/ path, module@version or URL runs code from outside the "
              "repo: run a .go file or a package the repo has.")
MAKE_REFUSAL = "%s reads its file from stdin or from an expansion, which the harness doesn't read: name a file the repo has."
WRITES_RUN_REFUSAL = ("the command writes %s and runs %s: the harness reads what the command writes as text, not what "
                      "it runs; that's the user's call.")
IMPLICIT_RUN_REFUSAL = ("the command writes %s and runs %s, which reads its build or test files as code: the harness "
                        "can't read what they run.")
PATH_REFUSAL = ("it runs %s by path: the deliverer runs gh, git and the shell by name, and a program from a system "
                "directory; a file it wrote itself can be another program.")
NAME_REFUSAL = "it runs a gh or git binary under another name, which the harness reads by the name it's given."
REPO_REFUSAL = ("gh acts on this repository (origin, %s) only: %s is another repository or host, where the call would "
                "go.")
NO_ORIGIN_REFUSAL = "gh acts on this repository only, and the harness can't read its origin: %s is refused."
DEFAULT_BRANCH_REFUSAL = ("it moves no git ref onto the default branch or from it: the default branch changes through "
                          "the PR, when the user merges it.")
GIT_EXPANSION_REFUSAL = ("a git call with $ or a backtick can name the default branch in a way the harness doesn't read: "
                         "write the ref out.")
FORBIDDEN_TEXT_REFUSAL = ("the command names a merge, a repository change or a git option the deliverer doesn't run, as "
                          "text or as a call; that's the user's call.")
ALIAS_REFUSAL = ("it defines no shell aliases: the shell can expand one on a later line into a gh command the harness "
                 "doesn't see.")
SHELL_INPUT_REFUSAL = ("a shell that reads its commands from a pipe or a file runs commands the harness can't read; run "
                       "them written out.")


def scan_expansions(text, quotes=True):
    """(the commands text runs in $(...), `...`, <(...) and >(...), whether an expansion sits outside quotes, where
    word splitting can make it several words). Nothing expands in single quotes; a heredoc body (quotes=False) has
    no quotes."""
    commands, bare, quote, i = [], False, None, 0
    while i < len(text):
        ch, after = text[i], text[i + 1:i + 2]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quotes and ch == "'" and quote is None:
            quote = "'"
        elif quotes and ch == '"':
            quote = None if quote else '"'
        elif ch == "`":
            end = text.find("`", i + 1)
            end = len(text) if end < 0 else end
            commands.append(text[i + 1:end])
            bare, i = bare or quote is None, end
        elif after == "(" and (ch == "$" or (ch in "<>" and quote is None)):
            end = closing_paren(text, i + 1)
            commands.append(text[i + 2:end])
            bare, i = bare or (ch == "$" and quote is None), end
        elif ch == "$" and quote is None and after.strip():
            bare = True
        i += 1
    return commands, bare


def closing_paren(text, start):
    """The index of the ) that closes the ( at text[start] (quotes and nested $(...) included), or len(text)."""
    depth, quote, i = 0, None, start
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote == '"':
            if ch == '"':
                quote = None
            elif ch == "$" and text[i + 1:i + 2] == "(":
                i = closing_paren(text, i + 1)
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def shell_split(text):
    """The words of a segment as the shell splits them, quotes removed. A $(...) or `...` stays whole inside its word,
    whatever quotes it holds: shlex reads it as plain text, and a quote in it can fold the next arguments into one."""
    return [word for word, _ in shell_split_marked(text)]


def shell_split_marked(text):
    """shell_split's words, each with the unquoted brace and glob characters (GLOB_CHARS) it holds."""
    words, word, marks, quote, i = [], None, "", None, 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote, word = (None, word) if ch == "'" else (quote, word + ch)
        elif ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            word = (word or "") + ("" if nxt == "\n" else "\\" + nxt if quote and nxt not in '$`"\\' else nxt)
            i += 1
        elif ch == "`" or text.startswith("$(", i):
            end = closing_paren(text, i + 1) if ch == "$" else text.find("`", i + 1)
            end = len(text) if end < 0 else end
            word, i = (word or "") + text[i:end + 1], end
        elif quote == '"':
            quote, word = (None, word) if ch == '"' else (quote, word + ch)
        elif ch in "'\"":
            quote, word = ch, word or ""
        elif ch.isspace():
            if word is not None:
                words.append((word, marks))
            word, marks = None, ""
        elif ch == "#" and word is None:
            break
        else:
            word = (word or "") + ch
            marks += ch if ch in GLOB_CHARS else ""
        i += 1
    return words + ([(word, marks)] if word is not None else [])


def run_words(words):
    """(the words of the command a segment runs, why the harness can't read it or ""). Keywords, grouping, leading
    assignments and redirections go; runners such as timeout 60, env -i or nice -n 5 run the command after their own
    options. xargs, parallel and find -exec add arguments the command line doesn't show, and a command named by an
    expansion can be any command."""
    while words:
        first = words[0]
        if first == "case":
            words = words[words.index("in") + 1:] if "in" in words else []
        elif first == "function":
            words = words[2:]
        elif REDIRECTION.match(first):
            words = words[1 + (REDIRECTION.match(first).end() == len(first)):]
        elif (first in SHELL_KEYWORDS or first in WRAPPERS or first in PRECOMMANDS or ASSIGNMENT.match(first)
              or first.endswith("()") or (first.endswith(")") and "(" not in first)):
            words = words[1:]
        elif first[:1] in ("(", "{") and first.lstrip("({"):
            words = [first.lstrip("({")] + words[1:]
        else:
            break
    named = "it runs a command named by an expansion ($... or `...`), which the harness can't read."
    if words and EXPANSION.search(words[0]):
        return words, named
    prog, runs = program(words), ("gh", "eval") + SHELLS
    if prog == "find":
        start = next((i + 1 for i, w in enumerate(words) if w in ("-exec", "-execdir", "-ok", "-okdir")), len(words))
        if words[start:] and (program(words[start:]) in runs or EXPANSION.search(words[start])):
            return words[start:], "find -exec adds arguments the harness can't read; run gh with them written out."
    elif prog in RUNNERS + ("xargs", "parallel") or prog.startswith("-"):
        hidden = ("%s adds arguments the harness can't read; run gh with them written out." % prog
                  if prog in ("xargs", "parallel") else "")
        for j in range(1, len(words)):
            if program(words[j:]) in runs:
                return words[j:], hidden
            if program(words[j:]) in RUNNERS + ("xargs", "parallel", "find"):
                inner, why = run_words(words[j:])
                return inner, hidden or why
            if EXPANSION.search(words[j]):
                return words[j:], named
    return words, ""


def shell_script(words):
    """(the command string a shell runs with -c, its other operands): bash -lc 'x', sh -e -c 'x' and
    bash -o pipefail -c 'x' run x; bash file.sh reads file.sh. Redirections aren't operands."""
    i, has_c = 1, False
    while i < len(words) and len(words[i]) > 1 and words[i][0] in "-+" and words[i] != "--":
        if words[i] in ("-o", "+o", "-O", "+O"):
            i += 1
        elif words[i][0] == "-" and not words[i].startswith("--") and "c" in words[i]:
            has_c = True
        i += 1
    operands, skip = [], False
    for word in words[i + (words[i:i + 1] == ["--"]):]:
        m = REDIRECTION.match(word)
        if not skip and not m:
            operands.append(word)
        skip = not skip and bool(m) and m.end() == len(word)
    return (operands[0] if has_c and operands else None), operands


def gh_calls(command, depth=0):
    """(segment, words, why the harness can't read it or "") of each gh call command runs: direct, behind a runner
    such as timeout or env, in sh -c or eval, in $(...) or backticks, in a heredoc or here-string a shell reads, and
    in $(...) in an unquoted heredoc. Commands it can't read come with why: gh behind xargs, a shell reading its
    commands from a pipe or a file, a command named by an expansion, an alias definition."""
    if depth > 4:
        return [(command, [], "its commands nest deeper than the harness reads; write them out.")]
    calls = []
    kept, bodies = split_heredocs(command)
    for inner in scan_expansions(kept)[0]:
        calls += gh_calls(inner, depth + 1)
    segments = split_segments(kept)
    for index, (segment, _) in enumerate(segments):
        calls += segment_calls(segment, index > 0 and segments[index - 1][1] == "|", depth)
    for opening, body in bodies:
        if any(not m.group(1) for m in HEREDOC.finditer(opening)):
            for inner in scan_expansions(body, quotes=False)[0]:
                calls += gh_calls(inner, depth + 1)
        if any(program(run_words(shell_split(seg))[0]) in SHELLS
               for seg, _ in split_segments(opening) if HEREDOC.search(seg)):
            calls += gh_calls(body, depth + 1)
    return calls


def segment_calls(segment, piped, depth):
    marked = shell_split_marked(segment)
    written = [word for word, _ in marked]
    words, why = run_words(written)
    prog = program(words)
    if why:
        return [(segment, words, why)]
    if prog == "alias" or any(ALIAS_TABLE.match(word) for word in written):
        return [(segment, words, ALIAS_REFUSAL)]
    problem = command_problem(marked, words)
    if problem or prog in ("gh", "git"):
        return [(segment, words, problem)]
    if prog in ("source", "."):
        return [(segment, words, SHELL_INPUT_REFUSAL)]
    if prog == "eval":
        return gh_calls(" ".join(words[1:]), depth + 1)
    if prog in SHELLS:
        script, operands = shell_script(words)
        here = next((w[3:] or (words[i + 1:i + 2] or [""])[0] for i, w in enumerate(words) if w.startswith("<<<")),
                    None)
        if script is not None or here is not None:
            return gh_calls(here if script is None else script, depth + 1)
        if not any(re.match(r"^[0-9]*<<", w) for w in words) and (
                piped or operands or any(re.match(r"^[0-9]*<(?![<&>])", w) for w in words)):
            return [(segment, words, SHELL_INPUT_REFUSAL)]
        return []
    if prog in RUNNERS or prog.startswith("-"):
        # watch 'gh ...', script -c 'gh ...': the command is one word
        return ([call for w in words[1:] if re.search(r"\s", w.strip()) for call in gh_calls(w, depth + 1)]
                or [(segment, words, problem)])
    return [(segment, words, "")]


def command_problem(marked, words):
    """Why the deliverer may not run a command the shell changes before it runs, or "": a variable that runs a command
    or redirects gh and git, and an unquoted glob or brace that expands into words the harness doesn't read. A glob
    in a command's arguments is read by the command, so only gh and git calls are checked there. marked and words are
    shell_split_marked's words and the words of the command they run."""
    for word, _ in marked:
        name = ENV_ASSIGNMENT.match(word)
        if name and (name.group(1) in RISKY_ENV or name.group(1).startswith(RISKY_ENV_PREFIXES)):
            return ENV_REFUSAL % name.group(1)
    offset, at = len(marked) - len(words), program_index(words)
    command = program(words[at:])
    api = command == "gh" and words[at + 1:at + 2] == ["api"]
    for index, (word, marks) in enumerate(marked[offset:]):
        if word in ("[", "[[", "]", "]]"):
            continue
        if "{" in marks and "}" in marks and ("," in word or ".." in word):
            return GLOB_REFUSAL
        if index == at:
            checked = marks
        elif command == "gh" and api:
            checked = marks.replace("?", "").replace("{", "").replace("}", "")
        elif command == "git":
            checked = marks.replace("{", "").replace("}", "") if re.search(r"@\{[^}]*\}", word) else marks
        elif command == "gh":
            checked = marks
        else:
            continue
        if checked:
            return GLOB_REFUSAL
    return ""


def program_index(words):
    """The index of the word a command runs: past the options and times of a runner such as timeout 60 or nice -n 5."""
    if not words or program(words) not in RUNNERS:
        return 0
    for i in range(1, len(words)):
        if not (words[i].startswith("-") or re.match(r"^\d+[smhd]?$", words[i]) or ASSIGNMENT.match(words[i])):
            return i
    return len(words)


def real_name(prog):
    """The name of the program prog runs once symlinks are followed, as the hook sees the PATH, or ""."""
    path = prog if "/" in prog else shutil.which(prog)
    return os.path.basename(os.path.realpath(path)) if path else ""


def first_operand(words):
    """The first word that isn't an option, or ""."""
    return next((w for w in words if not w.startswith("-")), "")


def value_options(base):
    """The options a runtime takes a separate value for: read as the value, not as the script."""
    if base.startswith("python"):
        return ("-W", "-X")
    if base.startswith("perl"):
        return ("-I",)
    if base.startswith("ruby"):
        return ("-I", "-r", "-C", "-E")
    if base.startswith("deno"):
        return ("--import-map", "--config", "-L", "--lock", "--env-file")
    if base.startswith("bun"):
        return ("--preload", "-r", "--conditions", "--env-file")
    return ("-r", "--require", "--import", "--loader", "--experimental-loader", "-C", "--conditions", "--input-type",
            "--env-file", "--title")


def interpreter_refusal(base, rest):
    """Why a runtime's arguments run code the harness doesn't read, or "": inline code (-c, -e, -p, -i), a module other
    than the test runners, code from stdin, a URL or data: URL, or a perl -M argument that holds code. A version or
    help flag alone runs nothing; a script file is read by its name."""
    short = base.startswith(SHORT_VERSION_FLAG)
    if len(rest) == 1 and rest[0] in VERSION_FLAGS + (("-v",) if short else ()):
        return ""
    value_flags, k = value_options(base), 0
    while k < len(rest) and rest[k].startswith("-") and rest[k] != "-":
        word = rest[k]
        if base.startswith("python") and re.match(r"-[A-Za-z]*m", word):
            return MODULE_REFUSAL % (base + " -m")
        if base.startswith("perl") and word[:2] in ("-M", "-m"):
            value = word[2:] or (rest[k + 1] if k + 1 < len(rest) else "")
            if not PERL_MODULE.fullmatch(value):
                return PERL_MODULE_REFUSAL
            k += 1 if len(word) > 2 else 2
            continue
        if INLINE_CODE.match(word):
            return INLINE_REFUSAL % base
        if URL_WORD.search(word):
            return URL_REFUSAL % base
        if word in value_flags:
            if k + 1 < len(rest) and URL_WORD.search(rest[k + 1]):
                return URL_REFUSAL % base
            k += 2
            continue
        k += 1
    if k >= len(rest) or STDIN_FILE.search(rest[k]) or REDIRECTION.match(rest[k]):
        return STDIN_REFUSAL % base
    if URL_WORD.search(rest[k]):
        return URL_REFUSAL % base
    return ""


def program_refusal(words):
    """Why the deliverer may not run the program a segment runs, or "": a program that copies or links another, runs
    code or commands from its arguments or stdin, a registry package, a make-style tool reading stdin, runs a command
    later, or runs gh or git by a path or name that isn't theirs."""
    at = program_index(words)
    if at >= len(words):
        return ""
    prog = words[at]
    base = prog.rsplit("/", 1)[-1]
    rest = words[at + 1:]
    if base in COPY_PROGRAMS:
        return COPY_REFUSAL
    if base in TEST_RUNNERS:
        return MODULE_REFUSAL % base
    if base in CODE_PROGRAMS:
        return CODE_REFUSAL % (base, base)
    if base in LATER_PROGRAMS:
        return LATER_REFUSAL % base
    if base in REGISTRY_RUNNERS or (base in PACKAGE_MANAGERS and first_operand(rest) in REGISTRY_SUBCOMMANDS):
        return REGISTRY_REFUSAL % base
    if base in MAKE_LIKE and any(w == "-" or STDIN_FILE.search(w) or re.search(r"[$`]|^[<>]\(", w) for w in rest):
        return MAKE_REFUSAL % base
    if base == "java" and ("-" in rest or any(w == "--source" or w.startswith("--source=") for w in rest)):
        return JAVA_REFUSAL
    if base == "go" and "run" in rest:
        after = rest[rest.index("run") + 1:]
        if any(w in ("-exec", "--exec") or w.startswith(("-exec=", "/dev/", "--exec=")) or w == "-" or "@" in w
               or "://" in w for w in after):
            return GO_REFUSAL
    if RUNTIMES.fullmatch(base):
        if base.startswith(("bun", "deno")) and first_operand(rest) == "run":
            rest = rest[rest.index("run") + 1:]
        why = interpreter_refusal(base, rest)
        if why:
            return why
    if "/" in prog and ((base not in ("gh", "git") + SHELLS and not RUNTIMES.fullmatch(base))
                        or not os.path.realpath(prog).startswith(SYSTEM_PREFIXES)):
        return PATH_REFUSAL % prog
    real = real_name(prog)
    if real in ("gh", "git") and real != base:
        return NAME_REFUSAL
    return ""


ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.S)
ANSI_C_ESCAPE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|[0-7]{1,3}|.)", re.S)
ANSI_C_SIMPLE = {"a": " ", "b": " ", "e": " ", "E": " ", "f": " ", "n": " ", "r": " ", "t": " ", "v": " "}
# A heredoc whose body is a PR's body or a commit message, which the shell reads as text.
TEXT_BODY_FILE = re.compile(r"\bgh\s+(?:-\S+\s+)*pr\s+(?:create|new|edit)\b.*--body-file(?:=|\s+)-(?=\s|$)"
                            r"|\bgit\b.*\bcommit\b.*(?:-[A-Za-z]*F|--file)(?:=|\s+)-(?=\s|$)")


def decode_ansi_c(match):
    key = match.group(1)
    if len(key) > 1 and key[0] in "xu":
        return chr(int(key[1:], 16))
    if key[0] in "01234567":
        return chr(int(key, 8))
    return ANSI_C_SIMPLE.get(key, key)


def ansi_c_view(command):
    """The command with each $'...' string read as the characters its escapes name: a \\t or \\n is a blank, so a
    command after one is a word of its own."""
    return ANSI_C.sub(lambda m: ANSI_C_ESCAPE.sub(decode_ansi_c, m.group(1)), command)


def text_bodies_removed(command):
    """The command with the bodies of heredocs that carry a PR's body (--body-file -) or a commit message (-F -) taken
    out. The opening line stays, so a call on it is still read."""
    lines, out, i = command.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        match = HEREDOC.search(line)
        if match and TEXT_BODY_FILE.search(line):
            while i < len(lines) and lines[i].strip() != match.group(2):
                i += 1
    return "\n".join(out)


def command_view(command):
    """The command as the text check reads it: its $'...' strings decoded, a PR's title and body and a commit message
    taken out, and the bodies of heredocs that carry a PR body or commit message removed. The text of these is text,
    not calls."""
    view = text_bodies_removed(ansi_c_view(command))
    if re.search(r"\bgh\s+(?:-\S+\s+)*pr\s+(?:create|new|edit)\b", view):
        view = PR_TEXT_VALUE.sub("", view)
    parts = []
    for segment, op in split_segments(view):
        _, words = shell_words(segment)
        if program(words) == "git" and "commit" in words[1:]:
            segment = COMMIT_MESSAGE.sub(lambda m: m.group(1) + "''", segment)
        parts.append(segment + op)
    return "".join(parts)


def gh_parts(words):
    """(command, subcommand, arguments) of a gh call. --repo may come before the subcommand: gh pr -R o/r edit 7 is
    ("pr", "edit", ["-R", "o/r", "7"]). gh api has no subcommand; its endpoint stays among the arguments."""
    command, sub, args, i = None, None, [], 1
    while i < len(words):
        word = words[i]
        if command and command != "api" and sub is None and word in ("-R", "--repo"):
            args += words[i:i + 2]
            i += 2
            continue
        if word.startswith("-") or sub is not None or command == "api":
            args.append(word)
        elif command is None:
            command = word
        else:
            sub = word
        i += 1
    return command, sub, args


def gh_flags(args, value_flags):
    """([(flag, value)], positional words), as gh's flag parser reads args: a flag in value_flags takes the rest of
    its word or the next word, whatever it holds (--title --add-label is the title "--add-label"); short switches
    combine (-dl x is -d -l x); everything after -- is positional."""
    flags, positional, i = [], [], 0
    while i < len(args):
        word = args[i]
        if word == "--":
            positional += args[i + 1:]
            break
        if word.startswith("--"):
            name, eq, value = word.partition("=")
            if name in value_flags and not eq:
                i += 1
                value = args[i] if i < len(args) else ""
            flags.append((name, value))
        elif word.startswith("-") and word != "-":
            for k in range(1, len(word)):
                name, rest = "-" + word[k], word[k + 1:]
                if name not in value_flags:
                    flags.append((name, ""))
                    continue
                if len(rest) > 1 and rest[0] == "=":
                    value = rest[1:]
                elif rest:
                    value = rest
                else:
                    i += 1
                    value = args[i] if i < len(args) else ""
                flags.append((name, value))
                break
        else:
            positional.append(word)
        i += 1
    return flags, positional


def hidden_arguments(segment, flags, positional):
    """Whether expansions could give gh flags the harness doesn't see: one outside quotes (word splitting), one in a
    flag's name, or one at the start of a positional word, which can expand to a flag."""
    return (scan_expansions(segment)[1] or any(EXPANSION.search(name) or name.endswith("$") for name, _ in flags)
            or any(word.startswith(("$", "`")) for word in positional))


def gh_refusal(segment, words, cwd, risk_added):
    """Why the deliverer may not run this gh call, or None. risk_added holds the risk labels that the command's
    other gh calls add."""
    if program(words) != "gh":
        return None
    command, sub, args = gh_parts(words)
    if command is None:
        return None
    if EXPANSION.search(command + " " + (sub or "")):
        return EXPANSION_REFUSAL
    if command == "pr" and sub in ("merge", "close", "review", "ready"):
        return MERGE_REFUSAL
    flags, positional = gh_flags(args, ITEM_VALUE_FLAGS + API_VALUE_FLAGS + LABEL_VALUE_FLAGS)
    if any(name in ("--web", "-w") for name, _ in flags):
        return WEB_REFUSAL
    if command == "api":
        return api_refusal(segment, args)
    if sub not in DELIVERY_GH.get(command, ()):
        return DELIVERY_GH_REFUSAL % " ".join(w for w in ("gh", command, sub) if w)
    repo_why = repository_refusal(cwd, flags, positional, command == "repo")
    if repo_why:
        return repo_why
    if command == "label" and sub == "create":
        return label_create_refusal(segment, args)
    if command == "pr" and sub in ("create", "new", "edit"):
        return label_change_refusal(sub, segment, args, cwd, risk_added)
    return None


def label_create_refusal(segment, args):
    """Why a gh label create call would make a label other than the triage labels, or rewrite one, or None."""
    flags, positional = gh_flags(args, LABEL_VALUE_FLAGS)
    if hidden_arguments(segment, flags, positional):
        return EXPANSION_REFUSAL
    if (positional or [None])[0] not in TRIAGE_LABELS:
        return ("it creates only the triage labels it applies (gh label create <label> ...); other labels are the "
                "user's call.")
    if any(name in ("-f", "--force") for name, _ in flags):
        return "it creates a missing triage label without --force, which rewrites a label someone else defined."
    return None


def origin_repository(cwd):
    """owner/repo of the origin remote, lowercased, or None."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd or str(ROOT), capture_output=True,
                             text=True, timeout=GIT_TIMEOUT).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"[:/]([^/:\s]+/[^/\s]+?)(?:\.git)?/?$", url)
    return match.group(1).lower() if match else None


def repository_refusal(cwd, flags, positional, names_repo):
    """Why a gh call names a repository other than this one (-R, a PR or issue URL, or gh repo view's argument), or
    None. The call would act on, and send the token to, that repository."""
    named = [value for name, value in flags if name in ("-R", "--repo")]
    named += [m.group(1) for word in positional for m in [GITHUB_REPO.search(word)] if m]
    if names_repo and positional:
        named.append(positional[0])
    if not named:
        return None
    origin = origin_repository(cwd)
    if origin is None:
        return NO_ORIGIN_REFUSAL % named[0]
    for value in named:
        match = GITHUB_REPO.search(value)
        name = match.group(1) if match else value
        if name.lower().strip("/") != origin:
            return REPO_REFUSAL % (origin, value)
    return None


def api_refusal(segment, args):
    """Why a gh api call could change something, or None. GraphQL can label, merge and enable auto-merge, and a
    REST write can do the same through a body the harness may not see."""
    flags, positional = gh_flags(args, API_VALUE_FLAGS)
    if hidden_arguments(segment, flags, positional):
        return EXPANSION_REFUSAL
    if any(name == "--hostname" for name, _ in flags):
        return "--hostname sends the request, and the token, to the host it names: the deliverer calls github.com only."
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", (positional or [""])[0]):
        return "gh api takes a path on this repository's host, not a URL: the request would go to the host the URL names."
    endpoint = (positional or [""])[0].split("?")[0]
    method = next((value for name, value in reversed(flags) if name in ("-X", "--method")), None)
    sends = any(name in ("-f", "-F", "--raw-field", "--field", "--input") for name, _ in flags)
    sent = (method or ("POST" if sends else "GET")).upper()
    if re.search(r"(^|/)graphql/?$", endpoint) or sent not in ("GET", "HEAD"):
        return ("gh api only reads (GET), and never through GraphQL: it changes the PR with gh pr create/edit and gh "
                "label create, where the harness sees what changes.")
    return None


def label_change_refusal(sub, segment, args, cwd, risk_added):
    """Why a gh pr create|edit call changes labels beyond the triage labels the receipts suggest, or None, adding its
    risk label to risk_added. Other labels can gate CI or merges (harness-change-approved lets a PR change the
    harness), so they stay the user's."""
    flags, positional = gh_flags(args, ITEM_VALUE_FLAGS)
    if hidden_arguments(segment, flags, positional):
        return EXPANSION_REFUSAL
    if any(name == "--recover" for name, _ in flags):
        return "it doesn't use --recover: the file it reads can carry labels the harness can't see."
    added = [n for name, value in flags if name in ("-l", "--label", "--add-label") for n in value.split(",")]
    removed = [n for name, value in flags if name == "--remove-label" for n in value.split(",")]
    foreign = [n for n in added if n not in TRIAGE_LABELS]
    if foreign:
        return ("it applies only the triage labels its receipts suggest (%s); %s is the user's call."
                % (", ".join(TRIAGE_LABELS), ", ".join(foreign)))
    risk = [n for n in RISK_LABELS if n in added]
    if len(risk) > 1:
        return "a PR keeps one risk:* label: add only the highest the receipts suggest, %s." % risk[-1]
    top = RISK_LABELS.index(risk[0]) if risk else -1
    kept = [n for n in removed if n not in RISK_LABELS or RISK_LABELS.index(n) >= top]
    if kept:
        return ("it removes only a lower risk:* label, in the call that adds the higher one; %s may have been set by "
                "a person." % ", ".join(kept))
    # Every call is checked against the PR's labels before the command runs, so the next call can't see this one's.
    others = sorted(risk_added - set(risk), key=RISK_LABELS.index)
    if risk and others:
        return ("a PR keeps one risk:* label, and another gh call in this command adds %s: add only the highest the "
                "receipts suggest, %s, in one call." % (", ".join(others), max(others + risk, key=RISK_LABELS.index)))
    risk_added.update(risk)
    if sub == "edit" and risk:
        repo = next((value for name, value in reversed(flags) if name in ("-R", "--repo")), None)
        return risk_label_refusal(positional[:1], repo, risk[0], removed, cwd)
    return None


def risk_label_refusal(targets, repo, added, removed, cwd):
    """Why adding the risk label added would leave a second risk label on the PR, as GitHub has its labels, or None."""
    for target in targets or [None]:
        names, error = pr_labels(target, repo, cwd)
        if names is None:
            return ("it adds a risk:* label only once the harness has read the PR's labels, and gh pr view failed: %s"
                    % error)
        others = [n for n in RISK_LABELS if n in names and n != added and n not in removed]
        higher = [n for n in others if RISK_LABELS.index(n) > RISK_LABELS.index(added)]
        if higher:
            return ("the PR already has %s, and a risk label only goes up: leave it, without adding %s."
                    % (higher[-1], added))
        if others:
            return ("the PR has %s: remove it in the same call (--remove-label %s), so the PR keeps one risk:* label."
                    % (", ".join(others), ",".join(others)))
    return None


def pr_labels(target, repo, cwd):
    """(the names of the labels on a pull request, None), or (None, why gh couldn't read them)."""
    args = ["gh", "pr", "view"] + ([target] if target else []) + (["--repo", repo] if repo else [])
    try:
        result = subprocess.run(args + ["--json", "labels"], cwd=cwd or str(ROOT), capture_output=True, text=True,
                                timeout=15)
        if result.returncode == 0:
            return [label["name"] for label in json.loads(result.stdout)["labels"]], None
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        return None, str(exc) or type(exc).__name__
    return None, (result.stderr.strip().splitlines() or ["exit %d" % result.returncode])[-1]


def names_default(word, targets):
    """Whether a ref word (src:dst, heads/main, refs/heads/main, origin/main) names a default branch in targets."""
    for part in word.lstrip("+").split(":"):
        name = part
        for prefix in ("refs/heads/", "heads/", "refs/remotes/origin/", "origin/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        if name in targets:
            return True
    return False


def writes_default(word, targets):
    """Whether a refspec's destination (src:dst) is the default branch, or a wildcard that could be (+main:refs/heads/main,
    refs/heads/*:refs/heads/*). A source alone writes nothing."""
    if ":" not in word:
        return False
    dst = word.lstrip("+").split(":", 1)[1]
    if "*" in dst:
        return True
    for prefix in ("refs/heads/", "heads/"):
        if dst.startswith(prefix):
            dst = dst[len(prefix):]
            break
    return dst in targets


def git_subcommand(words):
    """The subcommand of a git call, past git's own options, or None."""
    if program(words) != "git":
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] == "-C" else 1
    return words[i] if i < len(words) else None


def git_refusal(segment, words, targets, on_default):
    """Why the deliverer may not run this git call, or None. git runs the commands its configuration names, and a ref
    command may move the default branch, by name or by the branch it's on."""
    if program(words) != "git":
        return None
    args = words[1:]
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i].split("=", 1)[0] in GIT_OPTIONS_REFUSED:
            return GIT_OPTION_REFUSAL
        i += 2 if args[i] == "-C" else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    if any(w.split("=", 1)[0] in ("--exec", "--upload-pack", "--receive-pack") for w in rest):
        return GIT_EXEC_REFUSAL
    if sub == "config":
        names = {w.split("=", 1)[0] for w in rest}
        values = [w for w in rest if not w.startswith("-")]
        if names & set(GIT_CONFIG_WRITES) or (len(values) > 1 and not names & set(GIT_CONFIG_READS)):
            return GIT_CONFIG_REFUSAL
    if sub in REF_COMMANDS:
        if "$" in segment or "`" in segment:
            return GIT_EXPANSION_REFUSAL
        if sub in ("fetch", "pull", "rebase"):
            if on_default and sub in ("pull", "rebase"):
                return DEFAULT_BRANCH_REFUSAL
            if sub in ("pull", "rebase") and interactive_rebase(sub, rest):
                return INTERACTIVE_REBASE_REFUSAL
            if sub == "rebase" and rebase_branch(rest):
                return REBASE_BRANCH_REFUSAL
            if any(writes_default(w, targets) for w in rest if not w.startswith("-")):
                return DEFAULT_BRANCH_REFUSAL
            return None
        for word in rest:
            if word == "-" or "@{-" in word:
                return DEFAULT_BRANCH_REFUSAL
            if not word.startswith("-") and names_default(word, targets):
                return DEFAULT_BRANCH_REFUSAL
    if sub == "push":
        if on_default:
            return PUSH_DEFAULT_REFUSAL
        if any(w in ("--all", "--mirror") for w in rest):
            return PUSH_ALL_REFUSAL
        if any("*" in w for w in rest):
            return PUSH_DEFAULT_REFUSAL
    return None


def interactive_rebase(sub, rest):
    """Whether a git rebase or pull rebases interactively, however git reads the flag: an unambiguous prefix of the long
    option (--inter), a short flag in a cluster (-ki), or pull's --rebase value (--reb=i, -ri)."""
    for word in rest:
        if word == "--":
            break
        name, _, value = word.partition("=")
        if sub == "rebase" and ((name.startswith("--in") and "--interactive".startswith(name))
                                or (name.startswith("--edi") and "--edit-todo".startswith(name))):
            return True
        if sub == "pull" and name.startswith("--reb") and "--rebase".startswith(name) and value in ("i", "interactive"):
            return True
        if word.startswith("-") and not word.startswith("--"):
            for at, letter in enumerate(word[1:], 1):
                if sub == "rebase" and letter == "i":
                    return True
                if sub == "pull" and letter == "r":
                    return word[at + 1:] in ("i", "interactive")
                if letter in REBASE_VALUE_FLAGS[sub]:
                    break
    return False


def rebase_branch(rest):
    """Whether a git rebase names the branch to rebase (git rebase <upstream> <branch>, --root <branch>), which it
    checks out first."""
    operands, i = [], 0
    while i < len(rest):
        word = rest[i]
        if word in ("--onto", "-s", "--strategy", "-X", "--strategy-option", "-x", "--exec", "-C"):
            i += 2
            continue
        if not word.startswith("-"):
            operands.append(word)
        i += 1
    return len(operands) > ("--root" not in rest)


def written_files(command):
    """The names of the files a command writes: redirection targets, tee's files, the last operand of cp, mv, install
    and ln, dd's of= and a download's -o or -O. Each is read as the shell reads it (quotes and backslashes removed),
    by its last path component. A /dev/ path, a file descriptor and stdout aren't files."""
    kept = split_heredocs(command)[0]
    paths = []
    for segment, _ in split_segments(kept):
        for match in WRITE_REDIRECTION.finditer(segment):
            target = shell_split(segment[match.end():])[:1]
            paths += [re.split(r"[<>()]", target[0])[0]] if target else []
        words = run_words(shell_split(segment))[0]
        words = words[program_index(words):]
        prog = program(words)
        if prog == "tee":
            paths += [w for w in words[1:] if not w.startswith("-")]
        elif prog in ("cp", "mv", "install", "ln") and len(words) > 2:
            paths.append(words[-1])
        elif prog == "dd":
            paths += [w[3:] for w in words[1:] if w.startswith("of=")]
        elif prog in OUTPUT_OPTIONS:
            flags = gh_flags(words[1:], OUTPUT_OPTIONS[prog])[0]
            paths += [value for name, value in flags if name in OUTPUT_OPTIONS[prog]]
    return {os.path.basename(os.path.normpath(p)) for p in paths if p and not p.startswith(("/dev/", "&", "-"))}


def written_run_refusal(words, written):
    """Why a call that runs a file the same command writes, or a tool that reads its build or test files from the
    directory, is refused, or None. Files are compared by name, whatever directory the call spells: an expansion or a
    glob could name any of them. The harness reads the text a command writes, not what the file will run."""
    if not written:
        return None
    prog = program(words)
    runs_operands = RUNTIMES.fullmatch(prog) or prog in IMPLICIT_READERS
    named = [words[0]] + [w for w in words[1:] if runs_operands and not w.startswith("-")]
    unread = [w for w in named if EXPANSION.search(w) or any(ch in w for ch in "*?[")]
    ran = sorted({os.path.basename(os.path.normpath(w)) for w in named if w} & written) or unread
    if ran:
        return WRITES_RUN_REFUSAL % (", ".join(sorted(written)), ran[0])
    if prog in IMPLICIT_READERS:
        return IMPLICIT_RUN_REFUSAL % (", ".join(sorted(written)), prog)
    return None


def role_command_refusal(agent, command, cwd=None):
    """Why agent may not run command, or None. The deliverer reaches GitHub, but the decisions there stay the user's."""
    if agent != "deliverer":
        return None
    if conf()["HARNESS_DELIVER"] == "external":
        refusal = external_refusal(command)
        if refusal:
            return refusal
    risk_added = set()
    targets = {b for b in ("main", "master", default_branch()) if b}
    on_default = git("rev-parse", "--abbrev-ref", "HEAD").strip() in targets
    written = written_files(command)
    calls = gh_calls(command)
    switches = any(git_subcommand(words) in BRANCH_CHANGES for _, words, _ in calls)
    for segment, words, why in calls:
        refusal = (why or program_refusal(words) or gh_refusal(segment, words, cwd, risk_added)
                   or git_refusal(segment, words, targets, on_default) or written_run_refusal(words, written))
        if not refusal and switches and git_subcommand(words) == "push":
            refusal = PUSH_AFTER_SWITCH_REFUSAL
        if refusal:
            return refusal
    if FORBIDDEN_TEXT.search(command_view(command)):
        return FORBIDDEN_TEXT_REFUSAL
    return None


def hook_agent_guard(data, agent):
    """PreToolUse scoped to one agent: keep its edits inside its role."""
    scope = role_scope(agent)
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") == "Bash":
        why = role_command_refusal(agent, tool_input.get("command") or "", data.get("cwd"))
        if why:
            deny("The %s agent may not run this: %s" % (agent, why))
        return
    if scope is None or data.get("tool_name") not in FILE_TOOLS or not tool_input.get("file_path"):
        return
    path = canonical(rel(tool_input["file_path"]))
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
    lines = outline(read(TASKS)).splitlines()
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


def task_status(task, fingerprint=code_fingerprint):
    state = task_state(task)
    exists = spec_path(task).is_file()
    text = read(spec_path(task)) if exists else ""
    grill = verdict_history(task, "grill")
    judge = verdict_history(task, "judge")
    last_grill, last_judge = (grill[-1] if grill else None), (judge[-1] if judge else None)
    return {
        "task": task, "title": task_title(task), "state": state, "spec": spec_rel(task) if exists else None,
        "change_class": change_class(text)[0] if exists else None,
        "spec_problems": validate_spec(task) if exists else ["no spec yet"],
        "grill": last_grill and {"verdict": last_grill.get("verdict"),
                                 "current": last_grill.get("fingerprint") == spec_fingerprint(task)},
        "approved": bool(exists and approved(text)),
        "judge": last_judge and {"verdict": last_judge.get("verdict"),
                                 "current": last_judge.get("fingerprint") == fingerprint()},
        "escalations": [e for e in open_escalations() if re.search(r"\bTask %s:" % re.escape(task), e)],
    }


TECH_PLACEHOLDER = re.compile(r"(?i)^<.*>$|\b(to be (added|filled|decided|defined)|tbd|todo|fill(ed)? in later|pending)\b")


def architecture_pending(text):
    """The architect hasn't filled in the spec yet: no tech requirement beyond the template's placeholders."""
    section = md_section(text, "Architecture") or ""
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


def next_step(task, fingerprint=code_fingerprint):
    """What task needs next: {step, role (who does it, or null), command (what to run), ...}."""
    s = task_status(task, fingerprint)
    step = {"task": task, "title": s["title"], "state": s["state"], "change_class": s["change_class"]}
    if s["state"] == "missing":
        return dict(step, step="unknown", role=None, reason="no such task in backbone/3-TASKS.md")
    if s["state"] == "blocked":
        return dict(step, step="blocked", role=None, needed="the user", escalations=s["escalations"])
    if s["state"] == "done":
        return delivery_step(step)
    if s["state"] == "pending":
        if not s["spec"]:
            return dict(step, step="define", role="analyst", reason="no spec yet")
        if s["spec_problems"]:
            design = any(re.search(r"(?i)architecture|skills|ADR", p) for p in s["spec_problems"])
            return dict(step, step="define", role="architect" if design else "analyst", problems=s["spec_problems"])
        light = light_lane(task)
        if light and not s["approved"]:
            if autonomous():
                return dict(step, step="approve", role=None, light=True,
                            command="python3 scripts/harness/lib/harness.py approve %s" % task)
            return dict(step, step="approve", role=None, light=True,
                        needed="the user's Approved-by: line in %s" % s["spec"])
        if light:
            return dict(step, step="start", role=None, light=True,
                        command="python3 scripts/harness/lib/harness.py start %s" % task)
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
    if s["spec"] and not light_lane(task) and not (s["grill"] and s["grill"]["current"]
                                                   and s["grill"]["verdict"] == "pass"):
        return dict(step, step="grill", role="griller", reason="the spec changed during the build (an answered "
                                                                 "question); grill it again before going on")
    if tester_on():
        tests = verdict_history(task, "tests")
        if not tests or acceptance_fingerprint(task) != tests[-1].get("fingerprint"):
            return dict(step, step="test", role="tester",
                        reason="no acceptance tests yet" if not tests else "the acceptance tests changed since the "
                                                                          "tester recorded them")
    judge = s["judge"]
    if judge and judge["current"] and judge["verdict"] == "pass" and review_on():
        current = fingerprint()
        reviews = lens_reviews(task)
        on_current = {lens: e for lens, e in reviews.items() if e and e.get("fingerprint") == current}
        failed = [lens for lens, e in on_current.items() if e.get("verdict") != "pass"]
        if failed:
            return dict(step, step="fix", role="implementer", reason="must-fix findings from the %s review"
                        % ", ".join(failed), findings=[dict(f, lens=lens) for lens in failed
                                                       for f in on_current[lens].get("findings") or []
                                                       if f.get("severity") == "must-fix"])
        due = [lens for lens in REVIEW_LENSES if lens not in on_current]
        if due:
            return dict(step, step="review", role="reviewer", lenses=due,
                        then="run one reviewer per lens, all at once; each records its own verdict")
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


def latest_delivery(head, signed=False, task=None):
    """The last deliverer report logged for commit head, or None. signed: only a record delivery-record signed with
    HARNESS_DELIVERY_KEY counts. task: only a record for that task (delivery-record names one; the deliverer's report
    covers the branch)."""
    try:
        lines = events_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("kind") != "deliver" or event.get("head") != head:
            continue
        if task is not None and event.get("task") != task:
            continue
        if signed and not hmac.compare_digest(str(event.get("mac") or ""), delivery_mac(event) or "-"):
            continue
        return event
    return None


def delivery_step(step):
    """A finished task is done once the branch tip that holds it is delivered: pushed, in a PR, CI green."""
    mode = conf()["HARNESS_DELIVER"]
    if mode == "off":
        return dict(step, step="done", role=None)
    head = git("rev-parse", "-q", "--verify", "HEAD").strip()
    if git("status", "--porcelain").strip():
        return dict(step, step="deliver", role=None, needed="the finished task committed (the deliverer pushes "
                                                             "only committed work)")
    if mode == "external":
        last = latest_delivery(head, signed=bool(os.environ.get(DELIVERY_KEY)), task=step["task"])
        if last and last.get("delivery") == "delivered":
            return dict(step, step="done", role=None, pr=last.get("pr"))
        if last:
            return dict(step, step="delivery-failed", role=None, delivery=last.get("delivery"), pr=last.get("pr"),
                        findings=last.get("findings_detail") or [], owners=last.get("owners") or [],
                        needed="a fix task for each finding (or the user, for theirs), then deliver again")
        return dict(step, step="deliver", role=None, external=True, head=head[:12],
                    needed="delivery from the trusted clone (HARNESS_DELIVER=external): harness.py delivery-plan "
                           "%s --json, then delivery-record" % step["task"])
    if not git("remote", "get-url", "origin").strip():
        return dict(step, step="deliver", role=None, needed="an origin remote to push to (or the user turns "
                                                             "delivery off: HARNESS_DELIVER=\"off\")")
    last = latest_delivery(head)
    if last and last.get("delivery") == "delivered":
        return dict(step, step="done", role=None, pr=last.get("pr"))
    if last:
        return dict(step, step="delivery-failed", role=None, delivery=last.get("delivery"), pr=last.get("pr"),
                    findings=last.get("findings_detail") or [], owners=last.get("owners") or [],
                    needed="a fix task for each finding (or the user, for theirs), then deliver again")
    return dict(step, step="deliver", role="deliverer", head=head[:12])


def workspace_fingerprint():
    """Fingerprint of everything an agent session can change in the checkout: code, specs, verdicts, task lines."""
    return code_fingerprint(include_backbone=True)


def set_task_marker(task, marker, checks):
    """Move task's line to [marker] if the gates allow it (the same checks as an edit of 3-TASKS.md)."""
    before = read(TASKS)
    index, line = task_line(task, before)
    if index is None:
        return ["no task %s in backbone/3-TASKS.md" % task]
    lines = before.splitlines()
    lines[index] = re.sub(r"^(\s*[-*]\s+)\[[^\]]*\]", lambda m: m.group(1) + "[%s]" % marker, line, count=1)
    after = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    problems = []
    for check in checks:
        problem = check(before, after)
        if problem:
            log_event("gate", gate=check.__name__)
            problems.append(problem)
    if problems:
        return problems
    TASKS.write_text(after, encoding="utf-8")
    if marker == "WIP":
        record_light_start(task)
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
    fingerprint = computed_once(code_fingerprint)
    states = [task_status(t, fingerprint) for t in task_ids()]
    if "--json" in argv:
        print(json.dumps({"autonomous": autonomous(), "tasks": states, "halted": halt_file().exists()}, indent=2))
        return 0
    for s in states:
        print("%-8s %-8s %s" % (s["task"], s["state"], s["title"]))
    return 0


def next_command(argv):
    tasks = [a for a in argv if not a.startswith("--")] or [t for t, _, _ in ready_tasks()][:1]
    # progress: the whole workspace's fingerprint, specs and verdicts included. A coordinator that gets the same step
    # back with the same progress knows the last worker changed nothing.
    progress = workspace_fingerprint()
    fingerprint = computed_once(code_fingerprint)
    steps = [dict(next_step(t, fingerprint), progress=progress) for t in tasks]
    if "--json" in argv:
        print(json.dumps(steps[0] if len(steps) == 1 else steps, indent=2))
        return 0
    for s in steps:
        print("next %s: %s%s%s" % (s["task"], s["step"], " (%s)" % s["role"] if s.get("role") else "",
                                   ": " + s["command"] if s.get("command") else ""))
        if s.get("change_class"):
            print("  %s" % class_label(read(spec_path(s["task"]))))
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


# --------------------------------------------------------------------------- the factory contract (ADR-008)
# What an outside runner (the agent software factory) may rely on: these commands, their JSON fields and the event
# kinds. Within a version fields are only added; removing one or changing its meaning is a new version.
CONTRACT_VERSION = 1
CONTRACT_VERSIONS = (1,)
CONTRACT_COMMANDS = {
    "next": {"command": "next <task> --json",
             "fields": ["task", "title", "state", "change_class", "step", "role", "progress"],
             "steps": ["define", "grill", "answer", "approve", "start", "test", "implement", "judge", "diagnose",
                       "fix", "review", "finish", "deliver", "delivery-failed", "blocked", "done", "unknown"],
             "step_fields": {"blocked": ["escalations", "needed"], "answer": ["questions", "roles", "needs_user"],
                             "review": ["lenses"], "fix": ["findings"],
                             "delivery-failed": ["delivery", "pr", "findings", "owners", "needed"]}},
    "state": {"command": "state --json", "fields": ["autonomous", "tasks", "halted"],
              "task_fields": ["task", "title", "state", "spec", "change_class", "spec_problems", "grill", "approved",
                              "judge", "escalations"]},
    "receipt": {"command": "receipt <task> --json",
                "fields": ["task", "title", "objective", "base", "changed", "backbone_changed", "requirements",
                           "verified", "not_verified", "decisions", "change_class", "change_class_problem", "risks",
                           "rounds", "judged_at", "sandbox", "approval", "approval_needed", "suggested_labels",
                           "cost"]},
    "escalations": {"command": "escalations --json", "fields": ["escalations", "by_class"],
                    "entry_fields": ["task", "kind", "class", "playbook", "reason", "needed", "status", "at"]},
    "intake": {"command": "intake <request.json> --json",
               "request_fields": ["contract", "source", "channel", "message_id", "url", "sender", "sender_verdict",
                                  "received_at", "dedupe_key", "text"],
               "fields": ["contract", "task", "created", "spec", "escalated", "dedupe_key"]},
    "delivery-plan": {"command": "delivery-plan <task> [--base <branch>] [--pr-labels a,b] --json",
                      "fields": ["contract", "task", "ready", "needed", "branch", "base", "head", "title", "body",
                                 "draft", "labels", "escalations"]},
    "delivery-record": {"command": "delivery-record <task> <report.json>",
                        "report_fields": ["delivery", "branch", "base", "head", "pr", "checks", "findings",
                                          "verify"]},
    "run": {"command": "run --only <task>"},
    "trace": {"command": "trace <task> --json"},
    "report": {"command": "report --json"},
    "contract": {"command": "contract --json"},
}
CONTRACT_EVENTS = {
    "task-start": ["task"], "task-finish": ["task"], "verdict": ["task", "agent", "verdict", "claimed"],
    "review": ["task", "lens", "verdict"], "approval": ["task", "rule", "base"],
    "escalation": ["task", "escalation", "failure_class", "reason"], "proposal": ["failure_class"],
    "deliver": ["delivery", "branch", "base", "head", "pr", "checks", "findings", "owners"],
    "run-start": ["tasks"], "run-attempt": ["task", "attempt", "exit", "seconds", "state", "cost_usd", "turns"],
    "run-budget": ["scope", "spent", "limit"], "run-session": ["task", "session", "attempt"], "run-halt": [], "run-agent-failed": ["task", "error"], "run-end": ["summary"],
    "tamper": ["files", "command"], "block": ["reason", "detail"], "gate": ["gate"],
    "linear-import": ["task", "issue"], "outward": ["action", "via"],
    "intake": ["task", "contract", "source", "sender", "sender_verdict", "dedupe_key"],
}


def contract_command(argv):
    engine = lock().get("harness_version") or lock().get("version") or "unknown"
    if "--json" in argv:
        print(json.dumps({"contract": CONTRACT_VERSION, "versions": list(CONTRACT_VERSIONS), "engine": engine,
                          "commands": CONTRACT_COMMANDS,
                          "events": {"file": ".git/harness/events.jsonl", "fields": ["at", "kind", "v"],
                                     "kinds": CONTRACT_EVENTS}}, indent=2))
        return 0
    print("contract: version %d (serves %s)" % (CONTRACT_VERSION, ", ".join(str(v) for v in CONTRACT_VERSIONS)))
    print("engine: %s" % engine)
    return 0


OUTWARD_GH = {("pr", "create"): "pr-create", ("pr", "new"): "pr-create", ("pr", "edit"): "pr-edit",
              ("label", "create"): "label-create"}


def api_write(args):
    """Whether gh api args send a request that can change something (any method but GET and HEAD)."""
    flags, _ = gh_flags(args, API_VALUE_FLAGS)
    method = next((value for name, value in reversed(flags) if name in ("-X", "--method")), None)
    sends = any(name in ("-f", "-F", "--raw-field", "--field", "--input") for name, _ in flags)
    return (method or ("POST" if sends else "GET")).upper() not in ("GET", "HEAD")


def outward_actions(command):
    """[(action, words)] for each push, PR create or edit, label create and GitHub API write command makes, the gh and
    git calls the deliverer's gate can't read included."""
    if not re.search(r"(?<![\w.-])(git|gh)(?![\w.-])", command):
        return []
    found = []
    for _, words, _ in gh_calls(command):
        words = words[program_index(words):] if program(words) not in ("git", "gh") else words
        parts = gh_parts(words) if program(words) == "gh" else (None, None, [])
        action = "push" if git_subcommand(words) == "push" else OUTWARD_GH.get(parts[:2]) or (
            "api-write" if parts[0] == "api" and api_write(parts[2]) else None)
        if action:
            found.append((action, words))
    return found


# Under HARNESS_DELIVER="external" the lane only reads GitHub: these gh subcommands (None: all of them), gh api reads,
# and git without its push equivalents.
EXTERNAL_GH_READS = {"pr": ("view", "checks", "list", "ls", "status", "diff"), "run": ("view", "list", "watch"),
                     "repo": ("view",), "label": ("list",), "issue": ("view", "list", "status"),
                     "release": ("view", "list"), "workflow": ("view", "list"), "auth": ("status",), "search": None,
                     "status": None}
# git subcommands that push, or run commands that may (None: every form; a tuple: with one of these words).
GIT_PUSHES = {"push": None, "send-pack": None, "http-push": None, "subtree": None, "submodule": ("foreach",),
              "lfs": ("push",)}


def external_refusal(command):
    """Why a command is refused to every agent under external delivery, or None: the factory pushes and talks to
    GitHub from its trusted clone, so the lane runs no gh write and no git push, by any name."""
    for segment, words, why in gh_calls(command):
        prog = program(words[program_index(words):])
        if why:
            return "%s (%s)" % (EXTERNAL_REFUSAL, why.rstrip("."))
        run, _ = runner_command(prog, words)
        if prog.startswith("git-") or (run and (program(run).startswith("git") or program(run) == "gh")):
            return EXTERNAL_REFUSAL
        words = words[program_index(words):]
        if prog == "gh":
            name, sub, args = gh_parts(words)
            reads = EXTERNAL_GH_READS.get(name, ())
            if (name == "api" and api_write(args)) or (name != "api" and reads is not None and sub not in reads):
                return EXTERNAL_REFUSAL
        elif prog == "git":
            options = words[1:words.index(git_subcommand(words))] if git_subcommand(words) in words else words[1:]
            sub = git_subcommand(words)
            pushes = sub in GIT_PUSHES and (GIT_PUSHES[sub] is None or any(w in GIT_PUSHES[sub] for w in words))
            if any(o.split("=", 1)[0] in ("-c", "--config-env", "--exec-path") for o in options) or pushes:
                return EXTERNAL_REFUSAL
            if sub == "config" and not any(w in GIT_CONFIG_READS for w in words) and \
                    len([w for w in words[words.index("config") + 1:] if not w.startswith("-")]) >= 2:
                return EXTERNAL_REFUSAL
            if sub and git("config", "--get", "alias." + sub).strip():
                return EXTERNAL_REFUSAL
    return None


def log_outward(command, via, result):
    """An outward event for each outward write in a Bash call that ran (post-tool-use), with how it ended."""
    try:
        for action, words in outward_actions(command):
            log_event("outward", action=action, via=via, result=result, command=" ".join(words)[:500])
    except Exception:   # the audit trail never fails the call it describes
        pass


def task_lock_acquire(task):
    """One run per task across the repository's worktrees: an exclusive OS lock on locks/task-<id>.lock in the shared
    git directory, held until the process ends. Returns None once held, else what the holder recorded."""
    import fcntl
    folder = orca_dir(create=True) / "locks"
    folder.mkdir(exist_ok=True)
    fd = os.open(str(folder / ("task-%s.lock" % slug(task))), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            holder = json.loads(os.read(fd, 4096).decode("utf-8") or "{}")
        except ValueError:
            holder = {}
        os.close(fd)
        return holder if isinstance(holder, dict) else {}
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps({"pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}).encode("utf-8"))
    TASK_LOCKS[task] = fd
    return None


TASK_LOCKS = {}


def task_lock_release(task):
    fd = TASK_LOCKS.pop(task, None)
    if fd is not None:
        try:
            os.ftruncate(fd, 0)
            os.close(fd)
        except OSError:
            pass


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
    refusal = no_merge_refusal("orca-nightly", argv)
    if refusal:
        print(refusal)
        log_event("profile-refused", command="orca-nightly")
        return 1
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
    lines = outline(read(TASKS)).splitlines()
    deps = {}
    for i, line in enumerate(lines):
        m = AFTER_NOTE.search(line)
        if m and re.match(r"^\s*[-*]\s+\[[^\]]*\]", line):
            deps[task_id_at(lines, i)] = [d.rstrip(".") for d in re.split(r"[,\s]+", m.group(1))
                                          if re.match(r"^\d+(\.\d+[a-z]?)*\.?$", d)]
    return deps


def orca_command(argv):
    """harness.py orca: drive ready tasks with Orca supervised workers (scripts/harness/lib/coordinator.py)."""
    if delivery_key_refusal("orca"):
        return 1
    import coordinator
    valued = ("--agents", "--tasks", "--parallel", "--run", "--wait-ms", "--timeout")
    flags = ("--here", "--dry-run", "--trust", "--merge", "--pr")
    usage = ("usage: harness.py orca [--tasks 1.3,1.4] [--parallel N] [--agents default=claude,judge=codex] "
             "[--trust] [--merge | --pr] [--here] [--run ID] [--wait-ms MS] [--timeout S] [--dry-run]")
    unknown, i = [], 0
    while i < len(argv):
        if argv[i] in valued:
            i += 2
            continue
        if argv[i] not in flags:
            unknown.append(argv[i])
        i += 1
    if unknown:
        print(usage if any(a in ("-h", "--help") for a in unknown) else "orca: unknown argument %s\n%s"
              % (", ".join(unknown), usage))
        return 0 if any(a in ("-h", "--help") for a in unknown) else 2
    refusal = no_merge_refusal("orca", argv)
    if refusal:
        print(refusal)
        log_event("profile-refused", command="orca", argv=argv[:12])
        return 1
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
            "launch_wait": int(os.environ.get("HARNESS_ORCA_LAUNCH_WAIT", "8")),
            "retry_wait": int(os.environ.get("HARNESS_ORCA_RETRY_WAIT", "30")), "here": "--here" in argv, "pr": "--pr" in argv,
            "orca": os.environ.get("HARNESS_ORCA_BIN"),
            "wait_ms": int(value("--wait-ms")) if (value("--wait-ms") or "").isdigit() else 900000,
            "timeout": int(value("--timeout")) if (value("--timeout") or "").isdigit() else 4 * 3600}
    if not orca_lock_acquire():
        print("orca: a backlog run is already going for this repository (pid %s); not starting another"
              % orca_lock_holder())
        return 1
    held = [t for t in tasks if task_lock_acquire(t) is not None]
    if held:
        print("orca: task(s) %s are being run already; left out" % ", ".join(held))
        tasks = [t for t in tasks if t not in held]
    if not tasks:
        orca_lock_release()
        print("orca: no ready task that no other run holds")
        return 0
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
  judge fail, the debugger's brief goes to the implementer.
- Review: after the judge passes, start one reviewer per lens that `harness.py next {task} --json` lists, all at
  once. A must-fix finding goes to the implementer, then the judge and the reviews again.
- Record and deliver: the scribe, then mark the task [x] and commit. When `next` says deliver, run the deliverer.
- When anything needs a human, escalate: python3 scripts/harness/lib/harness.py escalate {task} --reason "..."
Stop when `python3 scripts/harness/lib/harness.py next {task}` says done, or the task is BLOCKED. Do not start other
tasks."""


EXTERNAL_NOTE = ("\nDelivery is external (HARNESS_DELIVER=external): don't run the deliverer. Stop once the task is [x] "
                 "and committed; the factory pushes it and opens the PR from its trusted clone.")


def attempt_cause(code, seconds, outcome, dirty):
    """(class, sentence) for why a runner session ended without finishing its task."""
    if code is None:
        return "timeout", "was stopped after %d s (HARNESS_RUN_TASK_TIMEOUT) before it finished" % int(seconds)
    if outcome == "done" and dirty:
        return "uncommitted", "marked the task [x] but left changes uncommitted: commit them with the task"
    if outcome == "undelivered":
        return "undelivered", "finished and committed the task but did not deliver it: run the deliverer"
    if code != 0:
        return "agent-error", "ended with exit code %s" % code
    return "unfinished", "ended before the task was [x] or BLOCKED"


def events_since(started_at, kinds):
    """Events of these kinds logged at or after started_at (same timestamp format, so text order is time order)."""
    found = []
    for line in read(events_file()).splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("kind") in kinds and str(event.get("at", "")) >= started_at:
            found.append(event)
    return found


def retry_brief(task, attempt, attempts, cause, step, started_at):
    """What the next session needs to know: why the last one stopped, where the task stands and what was refused,
    so the retry changes something instead of replaying the same session."""
    lines = ["", "", "Previous attempt %d of %d %s." % (attempt, attempts, cause)]
    detail = step.get("reason") or "; ".join(str(p) for p in (step.get("problems") or [])[:5])
    lines.append("Next step (from the harness): %s%s%s" % (step.get("step"), " (%s)" % step["role"] if step.get("role")
                                                         else "", ": " + detail if detail else ""))
    for finding in (step.get("findings") or [])[:8]:
        lines.append("  - judge: %s" % (finding.get("issue") if isinstance(finding, dict) else finding))
    for cause_item in ((step.get("brief") or {}).get("root_causes") or [])[:8]:
        if isinstance(cause_item, dict):
            lines.append("  - debugger (%s): %s; fix: %s" % (cause_item.get("owner"), cause_item.get("cause"),
                                                            cause_item.get("fix")))
    refused = []
    for event in events_since(started_at, ("block", "verify")):
        reason = re.sub(r"\s+", " ", str(event.get("reason") or "")).strip()
        if reason and reason not in refused:
            refused.append(reason)
    if refused:
        lines.append("The harness refused during it: %s. Fix the cause; don't retry the same call."
                     % "; ".join(refused[:5]))
    lines.append("Continue from that step. What the gates already record (the spec, its grill pass and approval, the "
                 "verdicts) stays valid: don't redo it. If this step can't move forward, escalate it.")
    return "\n".join(lines)


def ready_tasks(text=None):
    """[(id, title, state)] the runner may work on: a [WIP] task first, then pending ones, never BLOCKED."""
    lines = outline(read(TASKS) if text is None else text).splitlines()
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


def task_state_in(text, task):
    """task_state for the given 3-TASKS.md text."""
    _, line = task_line(task, text)
    if line is None:
        return "missing"
    return "done" if DONE_LINE.match(line) else "wip" if WIP_LINE.match(line) else "pending"


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


def engine_command(tree):
    """argv and environment that run the harness on tree: its own copy in a full install, else this engine (thin)."""
    env = dict(os.environ)
    env.pop("HARNESS_ROOT", None)
    vendored = Path(tree) / "scripts/harness/lib/harness.py"
    if vendored.is_file():
        return [sys.executable, str(vendored)], env
    env["HARNESS_ROOT"] = str(tree)
    return [sys.executable, str(Path(__file__).resolve())], env


def harness_cli():
    """The harness command as agents type it in this project."""
    if thin_mode():
        return "python3 " + shlex.quote(str(ENGINE / "scripts/harness/lib/harness.py"))
    return "python3 scripts/harness/lib/harness.py"


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
        command, env = engine_command(tree)
        child = subprocess.run(command + ["run", "--only", task], cwd=str(tree), env=env, capture_output=True, text=True)
        sys.stdout.write(child.stdout)
        m = re.search(r"^run: (\S+)\s+task %s$" % re.escape(task), child.stdout, re.M)
        outcome = m.group(1) if m else "error"
        if outcome == "agent-failed":
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(ROOT), capture_output=True)
            git("branch", "-D", branch)
            summary.append((task, outcome))
            break
        # A done task was delivered by its own run (the deliver step); a stuck one is pushed for a person to look at.
        if open_prs and outcome in ("blocked", "escalated"):
            dirty = git_in(tree, "status", "--porcelain").strip()
            if dirty:
                git_in(tree, "add", "-A")
                subprocess.run(["git", "commit", "-qm", "chore(harness): record escalation for task %s" % task],
                               cwd=str(tree), capture_output=True, text=True, env=dict(os.environ, HARNESS_VERIFY="block"))
            pushed = subprocess.run(["git", "push", "-q", "-u", "origin", branch], cwd=str(tree),
                                    capture_output=True, text=True)
            if pushed.returncode == 0:
                log_event("outward", action="push", via="harness", task=task, branch=branch)
            if pushed.returncode == 0 and shutil.which("gh"):
                state = "ready for review" if outcome == "done" else "BLOCKED, see backbone/escalations.md"
                body = "Opened by harness.py run: task %s is %s.\n\nThe harness-verify check re-checks the gates." \
                       % (task, state)
                receipt = subprocess.run(command + ["receipt", task], cwd=str(tree), env=env, capture_output=True,
                                         text=True)
                if receipt.returncode == 0:
                    body += "\n\n```\n%s\n```" % receipt.stdout.strip()
                pr = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", base_branch, "--title",
                                     "Task %s: %s" % (task, title), "--body", body],
                                    cwd=str(tree), capture_output=True, text=True)
                print("run: task %s: %s" % (task, pr.stdout.strip() or pr.stderr.strip()))
                log_event("run-pr", task=task, branch=branch, url=pr.stdout.strip())
                if pr.returncode == 0:
                    log_event("outward", action="pr-create", via="harness", task=task, url=pr.stdout.strip())
            else:
                print("run: task %s: branch %s kept locally (push failed or gh missing)" % (task, branch))
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(ROOT), capture_output=True)
        summary.append((task, outcome))
    for task, outcome in summary:
        print("run: %-12s task %s" % (outcome, task))
    return 0 if all(o in ("done", "blocked", "escalated", "skipped", "ready-to-deliver") for _, o in summary) else 1


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


def dollars(value):
    value = (value or "").strip()
    return float(value) if re.match(r"^\d+(\.\d+)?$", value) else None


class LedgerError(Exception):
    pass


def cost_ledger(task):
    """The task's cost ledger in the shared git directory: it outlives the worktree and the run, so a resumed task
    counts what it spent before (ADR-008). A session is reserved before it starts and settled when it ends."""
    return orca_dir() / "costs" / ("task-%s.jsonl" % slug(task))


def write_ledger(task, entry):
    path = cost_ledger(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(entry, at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), task=task), sort_keys=True)
                     + "\n")


def run_marker(task):
    return orca_dir() / "ran" / slug(task)


def task_has_run(task):
    """Whether any record shows a runner session for task: its marker, a run log, or the event log. A ledger can go
    missing; so can any one of these."""
    if run_marker(task).exists() or glob.glob(str(events_file().parent / "runs" / "*" / ("%s-*.log" % slug(task)))):
        return True
    for line in read(events_file()).splitlines():
        if '"task": %s' % json.dumps(task) in line and ('"run-session"' in line or '"run-attempt"' in line):
            return True
    return False


def cost_or_none(task):
    try:
        return (task_cost(task) or {}).get("total_usd")
    except LedgerError:
        return None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def task_cost(task):
    """{total_usd, sessions, sessions_without_cost, unsettled_sessions} from the task's ledger, or None when it has
    none. A session reserved and never settled (its run was killed) counts as the budget it reserved, and a session
    whose agent reported no cost (Codex prices nothing) as nothing. Raises LedgerError when the ledger can't be
    read."""
    path = cost_ledger(task)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError("the cost ledger %s can't be read (%s)" % (path, exc.__class__.__name__))
    reserved, settled = {}, []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        if not isinstance(entry, dict):
            raise LedgerError("the cost ledger %s is corrupt (line %d)" % (path, n))
        if "reserved_usd" in entry:
            reserved[entry.get("session")] = entry
        else:
            reserved.pop(entry.get("session"), None)
            settled.append(entry)
    if not reserved and not settled:
        return None
    unsettled = list(reserved.values())
    total = sum(e["cost_usd"] for e in settled if number(e.get("cost_usd")))
    total += sum(e["reserved_usd"] for e in unsettled if number(e.get("reserved_usd")))
    return {"total_usd": round(total, 6), "sessions": len(settled) + len(unsettled),
            "sessions_without_cost": len([e for e in settled if not number(e.get("cost_usd"))])
            + len([e for e in unsettled if not number(e.get("reserved_usd"))]),
            "unsettled_sessions": len(unsettled)}

BUDGET_REFUSAL = re.compile(r"(?i)\b402\b|payment required")


def budget_refusal(log_path, code):
    """The error a session ended with when the key proxy refused its model calls for a spending cap: an HTTP 402
    (Payment Required) in the agent's own error report (Claude Code's result, a Codex or OpenCode error event), never
    in free text the session printed. None otherwise."""
    data = session_result(log_path)
    if data:
        text = str(data.get("result") or "") if data.get("is_error") else ""
    else:
        errors = [e for e in jsonl_events(log_path) if e.get("type") in ("error", "turn.failed")]
        text = " ".join(str(e.get("message") or e.get("error") or "") for e in errors)
    return re.sub(r"\s+", " ", text).strip()[:300] if BUDGET_REFUSAL.search(text) else None


def run_agent(prompt, log_path, timeout):
    values = conf()
    backend = sandbox.backend(values["HARNESS_SANDBOX_BACKEND"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    box = backend.create(ROOT)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            code = backend.exec(box, values["HARNESS_AGENT_CMD"], stdin=prompt, log=log, timeout=timeout)
    finally:
        backend.teardown(box)
    return code, round(time.time() - started, 1)


def delivery_key_refusal(command):
    """Refuse to start agents while the delivery key is in this environment: a process can read its parent's (ps
    eww, /proc/<pid>/environ), so dropping it here wouldn't hide it."""
    if not os.environ.get(DELIVERY_KEY):
        return False
    print("%s: HARNESS_DELIVERY_KEY is set in this environment, and the agent sessions this would start could read it "
          "from this process. Set it only for delivery-record and next, never for %s." % (command, command))
    return True


def run_command(argv):
    if delivery_key_refusal("run"):
        return 1
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
    if only and not queue:
        holder = task_lock_acquire(only)
        if holder is not None:
            print("run: task %s is being run already (pid %s); not starting a second run"
                  % (only, holder.get("pid") or "unknown"))
            print("run: %-12s task %s" % ("locked", only))
            return 1
    timeout = int(values["HARNESS_RUN_TASK_TIMEOUT"]) if values["HARNESS_RUN_TASK_TIMEOUT"].isdigit() else 3600
    attempts = int(values["HARNESS_RUN_ATTEMPTS"]) if values["HARNESS_RUN_ATTEMPTS"].isdigit() else 2
    run_dir = events_file().parent / "runs" / time.strftime("%Y%m%d-%H%M%S")
    log_event("run-start", tasks=[t for t, _, _ in queue])
    summary = []
    max_cost = float(values["HARNESS_RUN_MAX_COST"]) if re.match(r"^\d+(\.\d+)?$", values["HARNESS_RUN_MAX_COST"]) else None
    task_budget = dollars(values["HARNESS_TASK_BUDGET_USD"])
    spent = 0.0
    for task, title, state in queue:
        retry_note, last_signature = "", None
        holder = task_lock_acquire(task)
        if holder is not None:
            print("run: task %s is being run already (pid %s); not starting a second run"
                  % (task, holder.get("pid") or "unknown"))
            summary.append((task, "locked"))
            continue
        if max_cost is not None and spent >= max_cost:
            print("run: budget reached ($%.2f of $%.2f); stopping before task %s" % (spent, max_cost, task))
            log_event("run-budget", scope="run", spent=spent, limit=max_cost)
            summary.append((task, "budget"))
            break
        outcome = None
        for attempt in range(1, attempts + 1):
            if halt_file().exists():
                print("run: halted by %s" % halt_file())
                log_event("run-halt")
                outcome = "halted"
                break
            try:
                ledger = task_cost(task)
                if ledger is None and task_budget is not None and task_has_run(task):
                    raise LedgerError("the cost ledger %s is missing, but the task has run before" % cost_ledger(task))
                used = (ledger or {}).get("total_usd", 0.0)
            except LedgerError as exc:
                if task_budget is None:
                    used = 0.0
                else:
                    print("run: task %s: %s; not starting a session" % (task, exc))
                    log_event("run-budget", task=task, scope="ledger", spent=None, limit=task_budget, error=str(exc))
                    escalate(task, "budget", "%s, so the task's spending is unknown" % exc,
                             "a person checks the ledger: fix or remove it, or drop the task", "permission_denied")
                    outcome = "escalated"
                    break
            if task_budget is not None and used >= task_budget:
                print("run: task %s has spent $%.2f of its $%.2f budget (HARNESS_TASK_BUDGET_USD); not starting "
                      "another session" % (task, used, task_budget))
                log_event("run-budget", task=task, scope="task", spent=used, limit=task_budget)
                escalate(task, "budget", "the task has spent $%.2f of its $%.2f budget (HARNESS_TASK_BUDGET_USD)"
                         % (used, task_budget), "the user raises the task's budget, or drops the task",
                         "permission_denied")
                outcome = "escalated"
                break
            resume = ("The task is already [WIP]: resume it." if task_state(task) == "wip"
                      else "The task is pending.")
            prompt = (RUN_PROMPT.format(task=task, title=title, state=resume)
                      + (EXTERNAL_NOTE if values["HARNESS_DELIVER"] == "external" else "") + retry_note).replace(
                "python3 scripts/harness/lib/harness.py", harness_cli())
            log_path = run_dir / ("%s-%d.log" % (slug(task), attempt))
            started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            session = "%s-%d-%d" % (run_dir.name, os.getpid(), attempt)
            try:
                # Reserved before the session starts, so a run killed during it still counts it.
                write_ledger(task, {"session": session, "attempt": attempt, "reserved_usd": None if task_budget is None
                                    else round(max(task_budget - used, 0.0), 6)})
                log_event("run-session", task=task, session=session, attempt=attempt)
                run_marker(task).parent.mkdir(parents=True, exist_ok=True)
                run_marker(task).touch()
            except OSError as exc:
                log_event("run-ledger", task=task, error=str(exc))
                if task_budget is not None:
                    print("run: task %s: the cost ledger can't be written (%s); not starting a session"
                          % (task, exc.__class__.__name__))
                    escalate(task, "budget", "the cost ledger can't be written (%s), so the task's spending can't be "
                             "counted" % exc.__class__.__name__, "a person checks .git/harness/costs/",
                             "permission_denied")
                    outcome = "escalated"
                    break
            code, seconds = run_agent(prompt, log_path, timeout)
            cost, turns = session_usage(log_path)
            try:
                write_ledger(task, {"session": session, "attempt": attempt, "cost_usd": cost, "turns": turns,
                                    "log": str(log_path)})
            except OSError as exc:   # the reservation stands, so the budget still counts the session
                log_event("run-ledger", task=task, error=str(exc))
            refusal = budget_refusal(log_path, code) if task_budget is not None else None
            if refusal:
                # The proxy refused for the task's cap or the day's: another session, or another task, is refused too.
                print("run: the agent's model calls were refused for a spending cap (%s); stopping the run. Log: %s"
                      % (refusal, log_path))
                log_event("run-attempt", task=task, attempt=attempt, exit=code, seconds=seconds, state=task_state(task),
                          uncommitted=bool(git("status", "--porcelain").strip()), cost_usd=cost, turns=turns,
                          cause="cap-hit", step=None)
                log_event("run-budget", task=task, scope="proxy", spent=cost_or_none(task), limit=task_budget,
                          error=refusal)
                escalate(task, "budget", "the key proxy refused the session's model calls for a spending cap: %s"
                         % refusal, "the user raises the cap (the task's or the day's), or drops the task",
                         "permission_denied")
                outcome = "cap-hit"
                break
            failure = agent_start_failure(log_path, code)
            if failure:
                print("run: the agent could not start (%s); stopping the run. Log: %s" % (failure, log_path))
                log_event("run-agent-failed", task=task, error=failure)
                outcome = "agent-failed"
                break
            spent += cost or 0.0
            if halt_file().exists():
                print("run: halted by %s during task %s" % (halt_file(), task))
                log_event("run-halt", task=task)
                outcome = "halted"
                break
            outcome = task_state(task)
            dirty = bool(git("status", "--porcelain").strip())
            if outcome == "done" and not dirty:
                after = next_step(task)
                if after["step"] == "delivery-failed":
                    escalate(task, "runner", "delivery failed (%s): %s" % (after.get("delivery"), json.dumps(
                        after.get("findings"), ensure_ascii=False)[:800]), after["needed"])
                    outcome = "escalated"
                    break
                if after.get("external"):
                    outcome = "ready-to-deliver"
                elif after["step"] == "deliver" and not after.get("role"):
                    escalate(task, "runner", "the finished task can't be delivered", after["needed"])
                    outcome = "escalated"
                    break
                elif after["step"] != "done":
                    outcome = "undelivered"
            settled = outcome in ("done", "blocked", "ready-to-deliver")
            step = next_step(task) if not settled else {}
            cause = attempt_cause(code, seconds, outcome, dirty)
            log_event("run-attempt", task=task, attempt=attempt, exit=code, seconds=seconds, state=outcome,
                      uncommitted=dirty, cost_usd=cost, turns=turns, cause=cause[0], step=step.get("step"))
            print("run: task %s attempt %d: %s (%ss, exit %s%s)" % (task, attempt, outcome, seconds, code,
                                                                   ", uncommitted changes" if dirty else ""))
            if not settled:
                # Only a session that ended cleanly having done nothing proves a retry futile: an agent error (an API
                # overload) or a timeout (a long test run) can pass, so those keep their attempts.
                signature = (workspace_fingerprint(), git("rev-parse", "-q", "--verify", "HEAD").strip(),
                             step.get("step"), step.get("role"))
                if cause[0] == "unfinished" and signature == last_signature:
                    escalate(task, "runner", "attempt %d changed nothing: the task is still at step %s, with the same "
                             "files as after attempt %d (logs: %s)" % (attempt, step.get("step"), attempt - 1, run_dir),
                             "a look at the run logs: a further identical session would repeat the same failure")
                    outcome = "escalated"
                    break
                last_signature = signature
                retry_note = retry_brief(task, attempt, attempts, cause[1], step, started_at)
            if outcome in ("done", "ready-to-deliver") and not dirty:
                data, _ = receipt_data(task)
                if data:
                    receipt = run_dir / ("%s.receipt.txt" % slug(task))
                    receipt.write_text(receipt_text(data) + "\n", encoding="utf-8")
                    print("run: task %s receipt: %s" % (task, receipt))
                break
            if outcome == "blocked":
                break
            if outcome == "done" and dirty:
                outcome = "done-uncommitted"
        else:
            if outcome not in ("done", "blocked", "agent-failed", "escalated", "cap-hit", "ready-to-deliver"):
                escalate(task, "runner", "no resolution after %d agent session(s) (last state: %s; logs: %s)"
                         % (attempts, outcome, run_dir), "a look at the run logs and the task's state")
                outcome = "escalated"
        summary.append((task, outcome))
        task_lock_release(task)
        if outcome in ("halted", "agent-failed", "cap-hit"):
            break
    log_event("run-end", summary=summary)
    for task, outcome in summary:
        print("run: %-12s task %s" % (outcome, task))
    return 0 if all(o in ("done", "blocked", "escalated", "ready-to-deliver") for _, o in summary) else 1


CI_JUDGE_PROMPT = """You are the judge, running in CI on a pull request. Task {task} is marked [x] in
backbone/3-TASKS.md. Judge task {task} against backbone/specs/{task}.md exactly as your instructions say, on the
code as committed (ignore the [WIP] lookup: the task is {task}). Do not modify anything. End with the verdict JSON."""


def ci_judge_command(argv):
    """CI: re-judge every task finished in a range with an independent judge session."""
    if delivery_key_refusal("ci-judge"):
        return 1
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


def github_repo():
    """(owner/name, default branch) of the repository gh sees; placeholders when it sees none."""
    repo = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"], cwd=str(ROOT),
                          capture_output=True, text=True) if shutil.which("gh") else None
    try:
        info = json.loads(repo.stdout) if repo is not None and repo.returncode == 0 else {}
    except ValueError:
        info = {}
    return (info.get("nameWithOwner") or "<owner>/<repo>",
            (info.get("defaultBranchRef") or {}).get("name") or "main")


def ci_protect_command(argv):
    """Make the harness-verify check required on a branch and create the approval label (needs gh). With --attest,
    set up the harness-attest environment instead (ADR-005)."""
    name, default = github_repo()
    if "--attest" in argv:
        return ci_protect_attest(name, default, "--dry-run" in argv, "--recorded-fallback" in argv,
                                 "--delete-repo-copies" in argv)
    contexts = ["verify"] + (["judge"] if "--with-judge" in argv else [])
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


def report_events(days):
    cutoff = time.time() - days * 86400
    events = []
    for line in read(events_file()).splitlines():
        try:
            event = json.loads(line)
            stamp = time.mktime(time.strptime(event["at"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, KeyError, TypeError):
            continue
        if stamp >= cutoff:
            events.append(event)
    return events


def by_tasks(pairs):
    """{key: sorted task ids} from (key, task) pairs, tasks deduplicated."""
    found = {}
    for key, task in pairs:
        if key and task:
            found.setdefault(key, set()).add(task)
    return {k: sorted(v) for k, v in found.items()}


# A candidate is a failure seen in several tasks: the instruction, rule or skill that would prevent it is missing.
CANDIDATE_TASKS = {"block": 3, "judge": 2, "escalation": 2}


def lift(events):
    """What the harness buys and what it costs: accepted work, refusals per gate and per rule, slow hooks, and the
    failures that keep coming back across tasks (harness candidates)."""
    stamp = lambda e: time.mktime(time.strptime(e["at"][:19], "%Y-%m-%dT%H:%M:%S"))
    judged = {}
    for e in events:
        if e.get("kind") == "verdict" and e.get("agent") == "judge" and e.get("task"):
            judged.setdefault(e["task"], []).append(e)
    first_pass = {"tasks": len(judged), "passed": sum(1 for v in judged.values() if v[0].get("verdict") == "pass")}
    fails = changed = 0
    for path in sorted(VERDICTS.glob("*.grill.json")):
        history = verdict_history(path.name[:-len(".grill.json")], "grill")
        for entry, after in zip(history, history[1:]):
            if entry.get("verdict") != "pass":
                fails += 1
                changed += entry.get("fingerprint") != after.get("fingerprint")
    started = {}
    durations = []
    for e in events:
        if e.get("kind") == "task-start" and e.get("task"):
            started[e["task"]] = stamp(e)
        elif e.get("kind") == "task-finish" and e.get("task") in started:
            durations.append(stamp(e) - started.pop(e["task"]))
    finished = {e.get("task") for e in events if e.get("kind") in ("task-finish", "orca-merge")
                or (e.get("kind") == "run-attempt" and e.get("state") == "done")} - {None}
    cost = sum(e.get("cost_usd") or 0 for e in events if e.get("kind") == "run-attempt")
    escalations = [e for e in events if e.get("kind") == "escalation"]
    gates = {}
    for e in events:
        if e.get("kind") == "gate":
            gates[e.get("gate")] = gates.get(e.get("gate"), 0) + 1
    fired = {}
    for e in events:
        if e.get("kind") == "rule":
            fired[e.get("rule")] = fired.get(e.get("rule"), 0) + 1
    rules, _ = load_rules()
    # Core rules guard against rare disasters and are meant to stay quiet; a project rule that never fires may no
    # longer apply.
    never = sorted({r.message[:120] for r in rules} - set(fired))
    project = {r.message[:120] for r in rules if r.source == "project"}
    slow = [e for e in events if e.get("kind") == "hook-slow"]
    candidates = []
    for reason, tasks in sorted(by_tasks((re.sub(r"\s+", " ", e.get("reason", "")).strip(), e.get("task"))
                                         for e in events if e.get("kind") == "block").items()):
        if len(tasks) >= CANDIDATE_TASKS["block"]:
            candidates.append("\"%s\" was refused in %d tasks (%s): agents keep trying it; say why in "
                              "backbone/4-KNOWLEDGE.md or the skill they use" % (reason[:100], len(tasks), ", ".join(tasks)))
    judge_fails = []
    for e in events:
        if e.get("kind") == "verdict" and e.get("agent") == "judge" and e.get("verdict") != "pass":
            for reason in e.get("reasons") or []:
                if str(reason).startswith("judge verdict:"):
                    continue   # the judge's own "fail", not a cause
                judge_fails.append((re.sub(r"\b(AC|REQ)-[\w.]+?-\d+\b", r"<\1>", str(reason)), e.get("task")))
    for reason, tasks in sorted(by_tasks(judge_fails).items()):
        if len(tasks) >= CANDIDATE_TASKS["judge"]:
            candidates.append("the judge failed %d tasks (%s) for: %s; a skill, test convention or rule could prevent "
                              "it" % (len(tasks), ", ".join(tasks), reason[:120]))
    for kind, tasks in sorted(by_tasks((e.get("escalation"), e.get("task")) for e in escalations).items()):
        if len(tasks) >= CANDIDATE_TASKS["escalation"]:
            candidates.append("the harness escalated %d tasks (%s) as %s; look for the common cause"
                              % (len(tasks), ", ".join(tasks), kind))
    return {
        "first_pass_judge": first_pass,
        "grill": {"fails": fails, "fails_followed_by_spec_change": changed},
        "start_to_finish": {"tasks": len(durations),
                            "median_minutes": round(sorted(durations)[len(durations) // 2] / 60, 1) if durations else None},
        "finished_tasks": sorted(finished),
        "cost_per_finished_task": round(cost / len(finished), 4) if finished and cost else None,
        "escalations_per_finished_task": round(len(escalations) / len(finished), 2) if finished else None,
        "gate_refusals": gates,
        "rules": {"loaded": len({r.message[:120] for r in rules}), "fired": fired, "never_fired": never,
                  "project_never_fired": [r for r in never if r in project]},
        "slow_hooks": {"count": len(slow), "slowest": max(slow, key=lambda e: e.get("seconds") or 0) if slow else None},
        "candidates": candidates,
        "tools_without_contract": dict(sorted(Counter(e.get("tool") for e in events if e.get("kind") == "tool-unknown"
                                                       and e.get("tool") and tool_contract(e["tool"]) is None).items())),
    }


def report_command(argv):
    days = (int(argv[argv.index("--days") + 1]) if "--days" in argv and argv.index("--days") + 1 < len(argv)
            and argv[argv.index("--days") + 1].isdigit() else 7)
    events = report_events(days)
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
    measures = lift(events)
    if "--rules" in argv:
        print("rules, last %d day(s): %d loaded" % (days, measures["rules"]["loaded"]))
        for rule, n in sorted(measures["rules"]["fired"].items(), key=lambda kv: -kv[1]):
            print("  %4d  %s" % (n, rule))
        for rule in measures["rules"]["never_fired"]:
            print("     0  %s%s" % (rule, "" if rule in measures["rules"]["project_never_fired"] else "  (core)"))
        return 0
    by_class = {}
    for e in events:
        if e.get("kind") == "escalation":
            by_class[e.get("failure_class") or "unclassified"] = by_class.get(e.get("failure_class") or "unclassified", 0) + 1
    if "--json" in argv:
        data = {"days": days, "events": len(events), "tasks_finished": done, "escalations_by_class": by_class,
                "judge_verdicts": len(judged), "judge_passes": passes, "overturned_passes": overturned,
                "escalations": count("escalation"), "open_escalations": len(open_escalations()),
                "policy_approvals": count("approval"), "blocked_tool_calls": count("block"),
                "verify_refusals": count("verify"), "out_of_band_changes": count("tamper"),
                "knowledge_lookups": count("knowledge"), "orca_merged": merged,
                "orca_workers": len(workers), "orca_failed_workers": failed_workers,
                "orca_integrations": count("orca-integrate"),
                "cost_usd": round(sum(e.get("cost_usd") or 0 for e in attempts), 4),
                "block_reasons": reasons}
        data.update(measures)
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print("harness report, last %d day(s), %d event(s)" % (days, len(events)))
    print("  tasks finished by the runner: %d %s" % (len(done), ", ".join(done)))
    print("  judge verdicts: %d (%d pass, %d fail); claimed passes overturned by the harness: %d"
          % (len(judged), passes, len(judged) - passes, overturned))
    print("  escalations: %d (open now: %d); policy approvals: %d" % (count("escalation"), len(open_escalations()),
                                                                       count("approval")))
    if by_class:
        print("    by class: %s" % ", ".join("%s %d" % kv for kv in sorted(by_class.items(), key=lambda kv: -kv[1])))
    print("  blocked tool calls: %d; commits refused by verify: %d; out-of-band changes: %d"
          % (count("block"), count("verify"), count("tamper")))
    if workers or merged:
        print("  orca: %d task(s) merged %s; %d worker(s), %d not succeeded; %d integration(s)"
              % (len(merged), ", ".join(merged), len(workers), failed_workers, count("orca-integrate")))
    print("  knowledge source lookups: %d" % count("knowledge"))
    print("  agent cost: $%.2f over %d session(s)" % (sum(e.get("cost_usd") or 0 for e in attempts), len(attempts)))
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:8]:
        print("    %4d  %s" % (n, reason))
    m = measures
    fp = m["first_pass_judge"]
    print("  accepted work:")
    print("    first-pass judge rate: %d of %d task(s)%s" % (fp["passed"], fp["tasks"],
                                                           " (%d%%)" % (100 * fp["passed"] // fp["tasks"]) if fp["tasks"] else ""))
    print("    griller fails followed by a spec change: %d of %d (all time)" % (m["grill"]["fails_followed_by_spec_change"],
                                                                            m["grill"]["fails"]))
    if m["start_to_finish"]["tasks"]:
        print("    start to finish: %d task(s), median %s min" % (m["start_to_finish"]["tasks"],
                                                              m["start_to_finish"]["median_minutes"]))
    if m["cost_per_finished_task"] is not None:
        print("    cost per finished task: $%.2f" % m["cost_per_finished_task"])
    if m["escalations_per_finished_task"] is not None:
        print("    escalations per finished task: %.1f (%d finished)" % (m["escalations_per_finished_task"],
                                                                        len(m["finished_tasks"])))
    print("  gate refusals: %s" % (", ".join("%s %d" % kv for kv in sorted(m["gate_refusals"].items())) or "none"))
    fired = m["rules"]["fired"]
    print("  rules: %d loaded; fired: %s" % (m["rules"]["loaded"], "; ".join(
        "%s (%d)" % kv for kv in sorted(fired.items(), key=lambda kv: -kv[1])[:5]) or "none"))
    print("    never fired in %d day(s): %d, of them project rules: %d (do they still apply? harness.py report --rules)"
          % (days, len(m["rules"]["never_fired"]), len(m["rules"]["project_never_fired"])))
    slow = m["slow_hooks"]
    print("  slow hook calls: %d%s" % (slow["count"], " (slowest %ss, %s)" % (slow["slowest"].get("seconds"),
                                                                           slow["slowest"].get("hook"))
                                      if slow["slowest"] else ""))
    unknown = m["tools_without_contract"]
    print("  tools used with no contract: %s" % ("; ".join("%s (%d)" % kv for kv in unknown.items())
                                              + " (add contracts in backbone/tools.conf)" if unknown else "none"))
    print("  harness candidates (a failure seen in several tasks):")
    for line in m["candidates"] or ["none"]:
        print("    - %s" % line)
    return 0


# --------------------------------------------------------------------------- trace

def trace_line(event):
    kind = event.get("kind", "?")
    detail = {
        "context": lambda e: e.get("path"),
        "skill": lambda e: e.get("name"),
        "edit": lambda e: "%s (%s)" % (e.get("path"), e.get("tool")),
        "block": lambda e: e.get("reason"),
        "verify": lambda e: e.get("reason"),
        "tests-run": lambda e: "%s: exit %s in %ss" % (e.get("command"), e.get("exit"), e.get("seconds")),
        "tests": lambda e: "acceptance tests recorded, missing: %s" % (", ".join(e.get("missing") or []) or "none"),
        "verdict": lambda e: "%s %s%s" % (e.get("agent"), e.get("verdict"),
                                          " (claimed %s)" % e.get("claimed") if e.get("claimed") != e.get("verdict")
                                          else ""),
        "debug": lambda e: "brief for %s" % ", ".join(e.get("owners") or []),
        "escalation": lambda e: "%s: %s" % (e.get("escalation"), e.get("reason")),
        "approval": lambda e: "policy %s, base %s" % (e.get("rule"), e.get("base")),
        "run-attempt": lambda e: "attempt %s: %s, %s at step %s, %ss" % (e.get("attempt"), e.get("state"),
                                                                       e.get("cause"), e.get("step"), e.get("seconds")),
        "hook-slow": lambda e: "%s hook took %ss" % (e.get("hook"), e.get("seconds")),
        "tool": lambda e: "%s (%s)%s" % (e.get("tool"), e.get("class"),
                                         ": " + ", ".join(e["paths"]) if e.get("paths") else ""),
        "tool-unknown": lambda e: "%s ran with no tool contract" % e.get("tool"),
    }.get(kind, lambda e: ", ".join("%s=%s" % (k, v) for k, v in sorted(e.items())
                                    if k not in ("at", "kind", "task", "session", "agent")))(event)
    label = {"tests-run": "tests", "run-attempt": "run"}.get(kind, kind)
    who = event.get("agent") or event.get("session")
    return "%s  %-8s %s%s" % (str(event.get("at", ""))[:19].replace("T", " "), label, detail,
                              "  [%s]" % who if who else "")


def trace_command(argv):
    if argv[:1] == ["export"]:
        return trace_export_command(argv[1:])
    if argv[:1] == ["link"]:
        return trace_link_command(argv[1:])
    task = next((a for a in argv if not a.startswith("--")), None)
    if not task:
        sys.stderr.write("usage: harness.py trace <task> [--json]\n")
        return 64
    events = []
    for line in read(events_file()).splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("task") == task:
            events.append(event)
    if "--json" in argv:
        print(json.dumps({"task": task, "events": events}, indent=2))
        return 0 if events else 1
    if not events:
        print("trace: nothing recorded for task %s" % task)
        return 1
    print("trace: task %s, %d event(s)" % (task, len(events)))
    for event in events:
        print(trace_line(event))
    return 0


# --------------------------------------------------------------------------- traceability export (ADR-004)
# A derived, one-way view of the chain requirement -> criterion -> test -> verdict -> commit for ALM and docs-as-code
# tools. backbone/ and git stay the record: nothing reads the export back, and it never touches the network.

TRACE_USAGE = "usage: harness.py trace export --format reqif|reqifz|needs|html [--out DIR] [--task ID]\n"
TRACE_LINK_USAGE = "usage: harness.py trace link <matrix-url> [--task ID]\n"
# A link a pull request or Linear comment shows as written: https, and none of the characters that end a Markdown link
# or autolink early, open an HTML tag or start emphasis or code.
MATRIX_URL = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~:/?#@!$&+,;=%-]*)?")
TASK_ID = re.compile(r"^[A-Za-z0-9._-]*[A-Za-z0-9]$")
XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")
EARS_LEAD = re.compile(r"^((?:(?:While|When|Where)\s+.+?,\s*|If\s+.+?,\s*then\s+)*)the\s+\S.*?\s+shall\s+\S", re.I)
EARS_KINDS = {"when": "event-driven", "while": "state-driven", "if": "unwanted behaviour", "where": "optional feature"}


def clean(text):
    """text without the control characters XML can't carry, so every format exports the same string."""
    return XML_ILLEGAL.sub("", text)


def trace_item_text(rest):
    """A spec item's text after its id: without a criterion's leading (REQ-...) list, the colon and bold markers."""
    return clean(re.sub(r"^\s*(\([^)]*\))?[\s:*]*", "", rest)).strip()


def ears_pattern(rest):
    """The EARS pattern of a requirement, read from its leading clauses as spec-check reads the shape."""
    m = EARS_LEAD.match(re.sub(r"^[\s:*]+|\*+", "", rest).strip())
    if not m:
        return "not an EARS pattern"
    kinds = sorted({k.lower() for k in re.findall(r"(?i)(?:^|,\s*)(while|when|where|if)\s", m.group(1))})
    return "complex" if len(kinds) > 1 else EARS_KINDS[kinds[0]] if kinds else "ubiquitous"


HISTORY_SHALLOW = ("this clone is shallow, so the judged code may be in a commit it doesn't have: fetch the full "
                   "history with `git fetch --unshallow` (in CI, actions/checkout with fetch-depth: 0)")
HISTORY_UNREADABLE = ("git timed out or failed reading the history, so the judged code may be in a commit that wasn't "
                      "read: rerun the export")
HISTORY_MISSING = ("git can't read %d tree(s) of the history (their objects are missing: a partial clone that can't "
                   "fetch them, or a damaged repository), so the judged code may be in one of them: restore the "
                   "missing objects, in a partial clone by fetching them from its remote")


def commits_by_code():
    """({code fingerprint: [commits reachable from HEAD with exactly that code, newest first]}, why the history may be
    incomplete, or None). A commit's fingerprint is its tree without the top-level backbone entry, as tree_fingerprint
    computes it; reading every tree through one git process and hashing it here keeps this fast on a long history."""
    try:
        log = subprocess.run(["git", "log", "--format=%H %T", "HEAD"], cwd=str(ROOT), capture_output=True, text=True,
                             timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {}, HISTORY_UNREADABLE
    if log.returncode:
        return {}, HISTORY_UNREADABLE
    pairs = [line.split() for line in log.stdout.splitlines() if len(line.split()) == 2]
    trees = sorted({tree for _, tree in pairs})
    try:
        batch = subprocess.run(["git", "cat-file", "--batch"], cwd=str(ROOT), capture_output=True, timeout=GIT_TIMEOUT,
                               input="".join(tree + "\n" for tree in trees).encode())
    except subprocess.TimeoutExpired:
        return {}, HISTORY_UNREADABLE
    if batch.returncode:
        return {}, HISTORY_UNREADABLE
    out, unreadable = batch.stdout, 0
    code, pos = {}, 0
    for tree in trees:
        end = out.find(b"\n", pos)
        fields = out[pos:end].split() if end >= 0 else []
        if len(fields) == 2 and fields[1] == b"missing":
            unreadable += 1
            pos = end + 1
            continue
        if len(fields) != 3 or fields[0] != tree.encode():
            return {}, HISTORY_UNREADABLE
        size, oid_bytes = int(fields[2]), len(tree) // 2
        body, pos = out[end + 1:end + 1 + size], end + 2 + size
        kept, i = [], 0
        while i < len(body):
            nul = body.index(b"\0", i)
            if body[i:nul].split(b" ", 1)[1] != b"backbone":
                kept.append(body[i:nul + 1 + oid_bytes])
            i = nul + 1 + oid_bytes
        content = b"".join(kept)
        code[tree] = hashlib.new("sha1" if oid_bytes == 20 else "sha256",
                                 b"tree %d\0" % len(content) + content).hexdigest()
    found = {}
    for commit, tree in pairs:
        if tree in code:
            found.setdefault(code[tree], []).append(commit)
    shallow = git("rev-parse", "--is-shallow-repository").strip() == "true"
    reasons = ([HISTORY_SHALLOW] if shallow else []) + ([HISTORY_MISSING % unreadable] if unreadable else [])
    return found, "; ".join(reasons) or None


def trace_task(task, current, by_code, incomplete, settings):
    """One task's part of the export: its requirements, criteria and test files, the latest verdicts on them, the
    commits that carry the judged code, and the gaps the harness can see. incomplete: why the history may lack the
    judged code, or None."""
    text = read(spec_path(task))
    body = comment_free(text)
    nfr_section = md_section(body, "Non-functional requirements") or ""
    ears = settings["HARNESS_REQ_STYLE"] == "ears"
    requirements = []
    for kind, items in (("REQ", spec_items(body, "REQ", task)), ("NFR", spec_items(nfr_section, "NFR", task))):
        for rid, rest in items:
            if rid not in {r["id"] for r in requirements}:
                requirements.append({"id": rid, "kind": kind, "text": trace_item_text(rest),
                                     "ears_pattern": ears_pattern(rest) if ears and kind == "REQ" else None})
    judge = verdict_history(task, "judge")
    last = judge[-1] if judge else None
    fingerprint = last.get("fingerprint") if last else None
    verdict = ("not judged" if last is None else "fail" if last.get("verdict") != "pass" else
               "pass on the current code" if fingerprint == current else "pass on earlier code")
    commits = by_code.get(fingerprint, []) if fingerprint else []
    paths = settings["HARNESS_TEST_PATHS"]
    if last is None or fingerprint == current:
        references, files_from = ac_test_references(task, None, paths), "the current code"
    elif commits:
        references, files_from = ac_test_references(task, commits[0], paths), "commit %s" % commits[0]
    else:
        references, files_from = {}, None
    gaps = {"not judged": ["no judge verdict: nothing in this task is verified"],
            "fail": ["the latest judge verdict is a fail"],
            "pass on earlier code": ["the judge's pass is on earlier code, not on the current code"]}.get(verdict, [])
    if incomplete and last is not None and fingerprint != current and not commits:
        gaps.append("history incomplete: %s" % incomplete)
    if files_from is None and not incomplete:
        gaps.append("the judged code is in no commit, so its test files are unknown")
    known = [r["id"] for r in requirements]
    judged = {str(c.get("id")): c for c in (last or {}).get("criteria") or [] if isinstance(c, dict)}
    criteria, tests = [], {}
    for aid, rest in spec_items(body, "AC", task):
        if aid in {c["id"] for c in criteria}:
            continue
        cited = list(dict.fromkeys(re.findall(r"\b(?:REQ|NFR)-%s-\d+\b" % re.escape(task), rest)))
        item = judged.get(aid)
        result = ("not judged" if last is None else "not evaluated" if item is None else
                  "met" if item.get("met") is True else "not met")
        files = references.get(aid, [])
        for name in files:
            tests.setdefault(name, []).append(aid)
        criteria.append({"id": aid, "text": trace_item_text(rest), "proves": [r for r in cited if r in known],
                         "unknown": [r for r in cited if r not in known], "result": result, "files": files,
                         "evidence": clean(str(item.get("evidence") or "")) if item else "",
                         "judge_tests": [clean(str(t)) for t in item.get("tests") or []] if item else [],
                         "tests": [trace_test_id(task, name) for name in files]})
    proven = {r for c in criteria for r in c["proves"]}
    gaps += ["%s has no acceptance criterion" % rid for rid in known if rid not in proven]
    for c in criteria:
        gaps += ["%s references %s, which the spec doesn't define" % (c["id"], rid) for rid in c["unknown"]]
        if c["result"] in ("not met", "not evaluated"):
            gaps.append("%s: %s" % (c["id"], c["result"] if c["result"] == "not met" else "not evaluated by the judge"))
        if files_from and not c["files"]:
            gaps.append("%s: no test file mentions it" % c["id"])
    gaps += ["NFR without an id, so no criterion traces it: %s" % clean(n) for n in top_level_items(nfr_section)
             if n.lower().rstrip(".") not in ("none", "n/a") and not re.match(r"\**NFR-%s-\d+" % re.escape(task), n)]
    for f in (last or {}).get("findings") or []:
        if isinstance(f, dict):
            where = ":".join(str(x) for x in (f.get("file"), f.get("line")) if x not in (None, ""))
            gaps.append(clean("%s finding left open: %s%s" % (f.get("severity", "minor"), f.get("issue", "?"),
                                                              " (%s)" % where if where else "")))
    grills = verdict_history(task, "grill")
    grill = grills[-1] if grills else None
    run = (last or {}).get("test_run")
    cls, declared, problem = change_class(text)
    _, line = task_line(task)
    title = re.match(r"^#\s+Spec\s+\S+:\s*(.+)$", body.strip().splitlines()[0]) if body.strip() else None
    return {
        "id": task,
        "title": clean(title.group(1).strip() if title else task_title(task)),
        "status": ("not in 3-TASKS.md" if line is None else "blocked" if BLOCKED_NOTE.search(line) else
                   "in progress" if WIP_LINE.match(line) else "done" if DONE_LINE.match(line) else "pending"),
        "spec": spec_rel(task),
        "spec_fingerprint": spec_fingerprint(task, text),
        "change_class": cls + (" (the declared one is invalid)" if problem else "" if declared else " (not declared)"),
        "grill": "none" if grill is None else "%s on %s (%s)" % (
            grill.get("verdict"), "the current spec" if grill.get("fingerprint") == spec_fingerprint(task, text)
            else "an earlier spec", grill.get("at")),
        "approval": [clean(a) for a in approval_lines(md_section(body, "Approval") or "")],
        "verdict": verdict,
        "judged_at": last.get("at") if last else None,
        "code_fingerprint": fingerprint,
        "commits": commits,
        "test_run": "%s: exit %s in %ss, output sha256 %s" % (clean(str(run.get("command"))), run.get("exit"),
                                                               run.get("seconds"), run.get("output_sha256"))
        if isinstance(run, dict) else None,
        "test_files_from": files_from or "unknown",
        "reviews": "; ".join("%s: %s" % (lens, "none" if e is None else e.get("verdict") + (
            "" if e.get("fingerprint") == fingerprint else " on other code than the judged code"))
            for lens, e in lens_reviews(task).items()),
        "requirements": requirements,
        "criteria": criteria,
        "tests": [{"id": trace_test_id(task, name), "path": clean(name), "criteria": acs}
                  for name, acs in sorted(tests.items())],
        "gaps": gaps,
    }


def trace_test_id(task, path):
    return "TEST-%s-%s" % (task, hashlib.sha256(path.encode("utf-8")).hexdigest()[:12])


def trace_model(tasks, receipts=False):
    """The export's model of tasks; with receipts, each task also carries its `receipt` text, or None where the
    receipt command would refuse."""
    head = git("rev-parse", "-q", "--verify", "HEAD").strip() or None
    current = code_fingerprint()
    by_code, incomplete = commits_by_code()
    incomplete = incomplete if head else None
    settings = committed_conf()
    version = lock().get("harness_version") or lock().get("version") or "unknown"
    model = {"project": clean(settings["HARNESS_PROJECT_NAME"] or "unnamed project"), "version": version,
             "tool": "agentic-harness %s" % version, "head": head,
             "time": git("log", "-1", "--format=%cI", "HEAD").strip() if head else "1970-01-01T00:00:00+00:00",
             "code_fingerprint": current, "code_matches_head": bool(head) and head in by_code.get(current, []),
             "req_style": settings["HARNESS_REQ_STYLE"],
             "tasks": [trace_task(task, current, by_code, incomplete, settings) for task in tasks]}
    for task in model["tasks"] if receipts else []:
        data, _ = receipt_data(task["id"], code=current)
        task["receipt"] = receipt_text(data) + "\n" if data else None
    return model


def stdout_file_in_repository():
    """The repository file that stdout is redirected to, tracked or not, or None: the shell creates it before the
    harness runs, so the export finds it by comparing files with stdout."""
    try:
        seen = os.fstat(sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        return None
    if not S_ISREG(seen.st_mode):
        return None
    for rel in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"):
        try:
            if rel and os.path.samestat(os.stat(ROOT / rel), seen):
                return rel
        except OSError:
            continue
    return None


def trace_export_command(argv):
    import traceability
    flags, rest = {"--format": None, "--out": None, "--task": None}, list(argv)
    while rest:
        flag = rest.pop(0)
        if flag not in flags or flags[flag] is not None or not rest:
            sys.stderr.write(TRACE_USAGE)
            return 64
        flags[flag] = rest.pop(0)
    if flags["--format"] not in traceability.FORMATS:
        sys.stderr.write(TRACE_USAGE)
        return 64
    render, name = traceability.FORMATS[flags["--format"]]
    task = flags["--task"]
    if task is not None and not (TASK_ID.match(task) and spec_path(task).is_file()):
        print("trace export: no spec at %s" % spec_rel(task))
        return 1
    tasks = [task] if task else sorted((p.stem for p in SPECS.glob("*.md") if TASK_ID.match(p.stem)),
                                       key=lambda t: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", t)])
    target = Path(flags["--out"]).expanduser().resolve() / name if flags["--out"] else None
    if target is not None and (target == ROOT or ROOT in target.parents):
        rel = target.relative_to(ROOT).as_posix()
        if not git("check-ignore", "--", rel).strip():
            sys.stderr.write("trace export: %s is inside the repository and git doesn't ignore it: an untracked file "
                             "there counts as code and would make the judge's passes stale. Write it outside the "
                             "repository or to a git-ignored folder.\n" % rel)
            return 1
    if target is None:
        rel = stdout_file_in_repository()
        if rel and not git("check-ignore", "--", rel).strip():
            sys.stderr.write("trace export: stdout goes to %s, inside the repository and not ignored by git: an "
                             "untracked file there counts as code and would make the judge's passes stale; redirect "
                             "stdout outside the repository or to a git-ignored file.\n" % rel)
            return 1
    document = render(trace_model(tasks, receipts=flags["--format"] == "reqifz"))
    if target is None:
        if isinstance(document, bytes):
            sys.stdout.flush()
            sys.stdout.buffer.write(document)
        else:
            sys.stdout.write(document)
        return 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(document, bytes):
            target.write_bytes(document)
        else:
            target.write_text(document, encoding="utf-8")
    except OSError as exc:
        print("trace export: can't write %s: %s" % (target, exc))
        return 1
    print("trace export: wrote %s" % target)
    return 0


def matrix_link_problem(url):
    if MATRIX_URL.fullmatch(url):
        return None
    return ("%r is not an https link a comment shows as written: letters, digits and -._~:/?#@!$&+,;=%% only, no "
            "spaces, quotes, brackets or parentheses" % url)


def trace_link_text(url, task, head):
    """The comment that links the traceability matrix at url, which describes commit head."""
    return ("**Traceability matrix** (ADR-004): %s\n\n"
            "It traces requirement -> acceptance criterion -> test -> judge verdict -> commit for %s at commit %s. It is "
            "derived from backbone/ and git, not the record: `harness.py trace export --format html` at that commit, with "
            "the same engine, writes the same file.\n" % (url, "task %s" % task if task else "every task with a spec",
                                                          head))


def trace_link_command(argv):
    url, task, rest = None, None, list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--task" and rest and task is None:
            task = rest.pop(0)
        elif not word.startswith("--") and url is None:
            url = word
        else:
            sys.stderr.write(TRACE_LINK_USAGE)
            return 64
    if url is None:
        sys.stderr.write(TRACE_LINK_USAGE)
        return 64
    head = git("rev-parse", "-q", "--verify", "HEAD").strip()
    problem = (matrix_link_problem(url) or
               ("no spec at %s" % spec_rel(task) if task is not None and not (TASK_ID.match(task) and
                                                                               spec_path(task).is_file()) else None) or
               (None if head else "the repository has no commit, and a matrix describes one"))
    if problem:
        sys.stderr.write("trace link: %s\n" % problem)
        return 1
    sys.stdout.write(trace_link_text(url, task, head))
    return 0


# --------------------------------------------------------------------------- change receipt
# What the harness can prove about a judged task, built only from recorded evidence (the spec, the verdicts, the
# diff), never from what an agent says it did. Reviewers read it instead of the transcript; a pull request carries it.

def receipt_base(task, spec_text, given=None):
    """The commit the task's change is measured from: --base, the policy approval's base, else the parent of the
    commit that added the spec, else HEAD (only the uncommitted work)."""
    if given:
        return given
    if light_base(task):
        return light_base(task)
    policy = policy_approval(spec_text)
    if policy and policy["base"] and policy["base"] != "none":
        return policy["base"]
    added = git("log", "--format=%H", "--diff-filter=A", "--", spec_rel(task)).split()
    if added and git("rev-parse", "-q", "--verify", added[-1] + "^").strip():
        return added[-1] + "^"
    return git("rev-parse", "-q", "--verify", "HEAD").strip() or None


def changed_since(base):
    """[(path, status)] changed since base, committed or not, untracked included."""
    found = {}
    for line in git("diff", "--name-status", "--no-renames", base).splitlines() if base else []:
        status, _, name = line.partition("\t")
        found[name] = {"A": "added", "D": "deleted"}.get(status[:1], "modified")
    for name in git("ls-files", "-z", "--others", "--exclude-standard").split("\0"):
        if name:
            found.setdefault(name, "added")
    return sorted(found.items())


def suggested_labels(spec_text, risks):
    """One risk:* label, and class:<class> when the spec has a Change-Class line: the class approve and risk use, so
    feature when the declared one is invalid. Advisory: a label approves nothing."""
    cls, declared, _ = change_class(spec_text)
    # risks holds the class's own reason (the user approves feature and schema work); the step already counts it.
    own = class_risks(spec_text)
    raised = any(reason not in own for reason in risks)
    step = min(CLASS_RISK_STEP[cls] + (1 if raised else 0), len(RISK_LABELS) - 1)
    return [RISK_LABELS[step]] + (["class:" + cls] if declared else [])


def receipt_data(task, base=None, code=None):
    """(receipt dict, None) for a task with a judge pass on the current code (or on code, a code fingerprint), else
    (None, why not)."""
    spec_text = read(spec_path(task))
    judge = verdict_history(task, "judge")
    passed = judge[-1] if judge and judge[-1].get("verdict") == "pass" else None
    if passed is None:
        return None, "task %s has no judge pass on record; a receipt states only what the judge proved" % task
    if not spec_text.strip():
        return None, "no spec at %s" % spec_rel(task)
    if passed.get("fingerprint") != (code or code_fingerprint()):
        return None, "the code changed after the judge passed task %s; judge it again first" % task
    body = comment_free(spec_text)
    title = re.match(r"^#\s+Spec\s+\S+:\s*(.+)$", body.strip().splitlines()[0]) if body.strip() else None
    base = receipt_base(task, spec_text, base)
    changes = changed_since(base)
    reqs = dict(spec_items(body, "REQ", task))
    criteria = {str(c.get("id")): c for c in passed.get("criteria") or [] if isinstance(c, dict)}
    references = ac_test_references(task)
    verified, not_verified = [], []
    run = passed.get("test_run")
    if run:
        verified.append("HARNESS_TEST_CMD (%s) run by the harness: exit %s in %ss"
                        % (run.get("command"), run.get("exit"), run.get("seconds")))
    for ac, rest in spec_items(body, "AC", task):
        proves = ", ".join(re.findall(r"REQ-%s-\d+" % re.escape(task), rest))
        item = criteria.get(ac) or {}
        line = "%s (%s): met; tests: %s; evidence: %s; test files: %s" % (
            ac, proves, ", ".join(item.get("tests") or []), item.get("evidence") or "-",
            ", ".join(references.get(ac) or []) or "-")
        (verified if item.get("met") is True else not_verified).append(line if item.get("met") is True
                                                                         else "%s (%s): not met" % (ac, proves))
    tests = verdict_history(task, "tests")
    if tests:
        verified.append("acceptance tests written by the tester before the code, unchanged since: %s"
                        % ", ".join(sorted({f for files in (tests[-1].get("files") or {}).values()
                                            for f in (files if isinstance(files, list) else [files])})) or "-")
    nfrs = [n for n in top_level_items(md_section(spec_text, "Non-functional requirements"))
            if n.lower().rstrip(".") not in ("none", "n/a")]
    not_verified.extend("NFR not covered by any acceptance criterion: %s" % n for n in nfrs)
    for f in passed.get("findings") or []:
        if isinstance(f, dict):
            where = ":".join(str(x) for x in (f.get("file"), f.get("line")) if x not in (None, ""))
            not_verified.append("%s finding left open: %s%s" % (f.get("severity", "minor"), f.get("issue", "?"),
                                                                " (%s)" % where if where else ""))
    adrs, approval_needed = [], []
    for name, status in changes:
        m = re.match(r"^backbone/adr/(ADR-\d+)[^/]*\.md$", name)
        if m and status != "deleted":
            state = adr_status(read(ROOT / name)) or "no status"
            adrs.append("%s (%s): %s" % (m.group(1), state, status))
            if not state.lower().startswith("accepted"):
                approval_needed.append("accept or reject %s (%s)" % (m.group(1), name))
    governing = ["%s (%s)" % (adr, adr_status(read(adr_file(adr))) if adr_file(adr) else "missing")
                 for adr in spec_adrs(spec_text)]
    assumptions = [a for a in top_level_items(md_section(spec_text, "Assumptions")) if a.lower().rstrip(".") not in
                   ("none", "n/a")]
    escalations = [e for e in open_escalations() if re.search(r"\bTask %s:" % re.escape(task), e)]
    approval_needed.extend("resolve the open escalation: %s" % e for e in escalations)
    grills = verdict_history(task, "grill")
    data = {
        "task": task,
        "title": title.group(1).strip() if title else task_title(task),
        "objective": " ".join((md_section(spec_text, "Context") or "").split()),
        "base": base,
        "changed": [{"path": n, "status": s} for n, s in changes if not n.startswith("backbone/")],
        "backbone_changed": [{"path": n, "status": s} for n, s in changes if n.startswith("backbone/")],
        "requirements": sorted(reqs),
        "verified": verified,
        "not_verified": not_verified,
        "decisions": {"governing_adrs": governing, "adrs_changed": adrs, "assumptions": assumptions},
        "change_class": change_class(spec_text)[0],
        "change_class_problem": change_class(spec_text)[2],
        "risks": risk_reasons(task, base),
        "rounds": {"grill": len(grills), "judge": len(judge), "debug": len(verdict_history(task, "debug"))},
        "judged_at": passed.get("at"),
        "sandbox": sandbox.normalized(passed.get("sandbox")),
        "approval": approval_lines(approval_section(spec_text) or ""),
        "approval_needed": approval_needed,
        "cost": receipt_cost(task),
    }
    data["suggested_labels"] = suggested_labels(spec_text, data["risks"])
    return data, None


def sandbox_lines(evidence):
    if not evidence:
        return ["not recorded: the judge pass predates sandbox evidence (ADR-003); judge the task again to record it"]
    evidence = sandbox.normalized(evidence)
    lines = ["%s: %s" % (field, evidence.get(field, "unknown")) for field in sandbox.EVIDENCE_FIELDS]
    if evidence.get("isolation_class") == "none":
        reason = evidence.get("isolation_reason")
        lines.append("nothing isolated the session from the host" + (": %s" % reason if reason else ""))
    elif evidence.get("allowlist_hash") == "none":
        lines.append("container without an allowlist: no egress allowlist was published, so its outbound traffic is "
                     "not limited")
    if str(evidence.get("allowlist_hash", "")).startswith("sha256:"):
        lines.append("allowlist_hash covers host names only, not the addresses they resolve to or the GitHub ranges "
                     "init-firewall.sh adds")
    return lines


def receipt_cost(task):
    try:
        return task_cost(task)
    except LedgerError as exc:
        return {"total_usd": None, "sessions": None, "sessions_without_cost": None, "unsettled_sessions": None,
                "error": str(exc)}


def cost_lines(cost):
    if not cost:
        return ["not recorded: no runner session worked on this task"]
    if cost.get("error"):
        return ["unknown: %s" % cost["error"]]
    lines = ["$%.2f over %d session(s)" % (cost["total_usd"], cost["sessions"])]
    if cost["sessions_without_cost"]:
        lines.append("%d session(s) reported no cost, so the total is a floor" % cost["sessions_without_cost"])
    if cost["unsettled_sessions"]:
        lines.append("%d session(s) never settled (their run was stopped): each counts as the budget it reserved"
                     % cost["unsettled_sessions"])
    return lines


def receipt_text(d):
    lines = ["Receipt: Task %s: %s" % (d["task"], d["title"]), "",
             "OBJECTIVE", "  %s" % (d["objective"] or "(the spec has no Context section)"), "",
             "CHANGED (since %s)" % ((d["base"] or "the empty tree")[:12])]
    lines += ["  %-8s %s" % (c["status"], c["path"]) for c in d["changed"]] or ["  (no code changes)"]
    if d["backbone_changed"]:
        lines.append("  backbone: %s" % ", ".join(c["path"] for c in d["backbone_changed"]))
    sections = (("VERIFIED (judge pass %s, re-checked by the harness)" % d["judged_at"], d["verified"]),
                ("NOT VERIFIED", d["not_verified"] or ["nothing outside the acceptance criteria"]),
                ("SANDBOX (where the judge pass was recorded)", sandbox_lines(d["sandbox"])),
                ("COST (the runner's agent sessions for this task)", cost_lines(d.get("cost"))),
                ("DECISIONS", ["follows %s" % a for a in d["decisions"]["governing_adrs"]] +
                 ["ADR changed: %s" % a for a in d["decisions"]["adrs_changed"]] +
                 ["assumption %s" % a for a in d["decisions"]["assumptions"]]),
                ("RISKS (Change-Class %s)" % d["change_class"],
                 d["risks"] + ["grill rounds: %d; judge rounds: %d; debugger briefs: %d"
                               % (d["rounds"]["grill"], d["rounds"]["judge"], d["rounds"]["debug"])]),
                ("APPROVAL", d["approval"] or ["(not approved)"]),
                ("APPROVAL NEEDED", d["approval_needed"] or ["none"]))
    for heading, items in sections:
        lines += ["", heading] + ["  - %s" % i for i in items or ["none"]]
    lines += ["", "SUGGESTED LABELS (for whoever triages the pull request; a label never approves or merges it)"]
    lines += ["  - %s" % label for label in d["suggested_labels"]]
    if d["change_class_problem"]:
        lines.append("  (labelled as feature, as approve and risk count it, because %s)" % d["change_class_problem"])
    elif not any(label.startswith("class:") for label in d["suggested_labels"]):
        lines.append("  (rated as feature, as approve and risk count it, because the spec declares no Change-Class)")
    return "\n".join(lines)


LINEAR_LINE = re.compile(r"^Linear:\s*([A-Z][A-Z0-9]{0,9}-\d+)\b", re.M)
LINEAR_USAGE = ("usage: harness.py linear import <ISSUE-ID> --task <id> [--light] [--from <issue.json>] [--sender <name>] "
                "[--sender-verdict trusted|untrusted] [--dry-run]\n"
                "       harness.py linear receipt <task> [--status <state name>] [--base <rev>] [--matrix <url>] "
                "[--dry-run]\n")


def linear_import(issue, task, light, dry_run, sender=None, verdict=None):
    """A draft spec and a pending task line from a Linear issue. The issue's text goes in as quoted source material,
    and its provenance in a '## Source' section, as intake writes it. The user runs the import, so the ticket is
    trusted unless they (or the factory) say otherwise."""
    identifier = issue["identifier"]
    verdict = verdict or "trusted"
    if verdict not in SENDER_VERDICTS:
        raise HarnessError("--sender-verdict must be trusted or untrusted")
    path = spec_path(task)
    tasks_text = read(TASKS)
    if path.exists():
        raise HarnessError("%s exists already; import into a new task id" % spec_rel(task))
    if re.search(r"\bTask\s+%s\b" % re.escape(task), outline(tasks_text)):
        raise HarnessError("task %s is already in backbone/3-TASKS.md" % task)
    if re.search(r"\blinear:\s*%s\b" % re.escape(identifier), tasks_text):
        raise HarnessError("%s is imported already (backbone/3-TASKS.md)" % identifier)
    title = request_title(issue.get("title"), identifier)
    description = str(issue.get("description") or "")
    creator = issue.get("creator") if isinstance(issue.get("creator"), dict) else {}
    team = issue.get("team") if isinstance(issue.get("team"), dict) else {}
    source = source_block((CONTRACT_VERSION, "linear", team.get("key"), identifier, issue.get("url"),
                           sender or creator.get("name") or "the user (harness.py linear import)", verdict,
                           time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "linear:%s" % identifier, description))
    spec = draft_spec(task, title, source, "Imported from Linear %s on %s. The ticket below is source material"
                      % (identifier, time.strftime("%Y-%m-%d")), quoted_request(description or "(no description)"))
    spec = re.sub(r"(?m)^(PRD: .*)$", lambda m: "%s\nLinear: %s (%s)" % (m.group(1), identifier, issue.get("url") or "-"),
                  spec, count=1)
    line = "- [ ] **Task %s: %s** (spec: %s; linear: %s)%s" % (task, title, spec_rel(task), identifier,
                                                              " (light)" if light else "")
    print("%s %s as task %s:\n  spec  %s (the analyst writes its requirements)\n  task  %s"
          % ("Would import" if dry_run else "Imported", identifier, task, spec_rel(task), line))
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spec, encoding="utf-8")
        add_task_line(line)
        log_event("linear-import", task=task, issue=identifier, sender_verdict=verdict)
        if verdict != "trusted":
            escalate(task, "intake", "the ticket came from an untrusted sender (%s via linear): a person reads it "
                     "before any work" % source_value(sender or creator.get("name") or "unknown"),
                     "a person reviews %s; nothing builds until a person approves the spec (Approved-by:)"
                     % spec_rel(task), "permission_denied", refresh=False)
    return 0


def linear_receipt(task, status, base, dry_run, matrix=None):
    """Post the task's receipt as a comment on its Linear issue, with the link to the traceability matrix at matrix if
    given, and optionally move the issue (never to a closed state)."""
    import linear
    if matrix and matrix_link_problem(matrix):
        raise HarnessError(matrix_link_problem(matrix))
    m = LINEAR_LINE.search(read(spec_path(task)))
    if not m:
        raise HarnessError("%s has no 'Linear: <ISSUE-ID>' line; import the task with harness.py linear import"
                           % spec_rel(task))
    data, problem = receipt_data(task, base)
    if problem:
        raise HarnessError(problem)
    body = "**agentic harness receipt** (task %s)\n\n```\n%s\n```\n\nOnly a human merges the pull request and " \
           "closes this issue." % (task, receipt_text(data))
    if matrix:
        body += "\n\n" + trace_link_text(matrix, task, git("rev-parse", "-q", "--verify", "HEAD").strip()).strip()
    if dry_run:
        print("Would comment on %s:\n%s%s" % (m.group(1), body, "\nWould move %s to '%s'" % (m.group(1), status)
                                               if status else ""))
        return 0
    try:
        issue = linear.fetch_issue(m.group(1))
        state = linear.target_state(issue, status) if status else None
        url = linear.post_comment(issue["id"], body)
        log_event("outward", action="linear-comment", via="harness", task=task, issue=m.group(1), url=url)
        print("linear: posted the receipt on %s %s" % (m.group(1), url))
        if state:
            moved = linear.move_issue(issue, state)
            log_event("outward", action="linear-state", via="harness", task=task, issue=m.group(1), state=moved)
            print("linear: moved %s to '%s'" % (m.group(1), moved))
    except linear.LinearError as exc:
        raise HarnessError("linear: %s" % exc)
    log_event("linear-receipt", task=task, issue=m.group(1), status=status)
    return 0


def linear_command(argv):
    import linear
    value = lambda flag: argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    try:
        if argv[:1] == ["import"] and len(argv) >= 2 and value("--task"):
            if value("--from"):
                try:
                    issue = linear.issue_from(json.loads(read(Path(value("--from")))))
                except ValueError as exc:
                    raise HarnessError("%s is not JSON: %s" % (value("--from"), exc))
                if issue["identifier"] != argv[1]:
                    raise HarnessError("%s holds %s, not %s" % (value("--from"), issue["identifier"], argv[1]))
            else:
                issue = linear.fetch_issue(argv[1])
            return linear_import(issue, value("--task"), "--light" in argv, "--dry-run" in argv, value("--sender"),
                                 value("--sender-verdict"))
        if argv[:1] == ["receipt"] and len(argv) >= 2:
            return linear_receipt(argv[1], value("--status"), value("--base"), "--dry-run" in argv, value("--matrix"))
    except linear.LinearError as exc:
        sys.stderr.write("harness: linear: %s\n" % exc)
        return 1
    except HarnessError as exc:
        sys.stderr.write("harness: %s\n" % exc)
        return 1
    sys.stderr.write(LINEAR_USAGE)
    return 64


# --------------------------------------------------------------------------- intake (ADR-008)
# A request from one of an agent factory's doors becomes a pending task. The factory checks the sender; the harness
# records who asked, through which door and the factory's verdict in a '## Source' section only it writes, and quotes
# the request as source material. Request text is data from any sender, never instructions.
INTAKE_SOURCES = ("slack", "github", "linear", "clock")
SENDER_VERDICTS = ("trusted", "untrusted")
INTAKE_USAGE = "usage: harness.py intake <request.json> [--json]\n"
INTAKE_TASK = re.compile(r"\bTask\s+intake\.(\d+)\b")


def source_value(value):
    """value on one line, as text a Markdown reader can't take for a tag, a comment or code."""
    text = re.sub(r"[<>`]", "", "" if value is None else str(value))
    return re.sub(r"\s+", " ", UNUSUAL_SPACES.sub(" ", LINE_BREAKS.sub(" ", text))).strip()[:300] or "-"


def source_block(fields):
    """The '## Source' section for fields: (contract, source, channel, message, url, sender, verdict, received,
    dedupe key, text)."""
    labels = ("Contract", "Source", "Channel", "Message", "URL", "Sender", "Sender verdict", "Received", "Dedupe key")
    lines = ["- %s: %s" % (label, source_value(value)) for label, value in zip(labels, fields[:9])]
    lines.append("- Text SHA-256: %s" % hashlib.sha256(str(fields[9]).encode("utf-8")).hexdigest())
    return "## Source\n" + "\n".join(lines) + "\n\n"


def source_section(text):
    """Every '## Source' section's raw text, heading included, as the gates find them, or None. The blank lines after
    a section don't count: rewriting the next section may change them."""
    text = text or ""
    view = outline(text)
    parts = []
    for m in heading_pattern("Source").finditer(view):
        end = SECTION_END.search(view, m.end())
        parts.append(text[m.start():end.start() if end else len(text)].rstrip() + "\n")
    return "".join(parts) or None


def source_verdicts(text):
    """The sender verdict of each '## Source' section that records one: a section without a "- Sender verdict:"
    line is not provenance."""
    view = outline(text or "")
    found = []
    for m in heading_pattern("Source").finditer(view):
        end = SECTION_END.search(view, m.end())
        verdict = re.search(r"(?m)^- Sender verdict:[ \t]*(\S*)", view[m.end():end.start() if end else len(view)])
        if verdict:
            found.append(verdict.group(1))
    return found


def quoted_request(text):
    """text as a Markdown quote that reads only as quoted text: no heading, fence, HTML, comment or setext line of its
    own survives, and odd line breaks and spaces become plain ones."""
    text = LINE_BREAKS.sub("\n", str(text).replace("\r\n", "\n").replace("\r", "\n")).strip("\n")
    lines = []
    for line in text.split("\n"):
        line = UNUSUAL_SPACES.sub(" ", line.replace("\t", " ")).rstrip()
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        line = re.sub(r"`{3,}|~{3,}", lambda m: ("&#96;" if m.group(0)[0] == "`" else "&#126;") * len(m.group(0)),
                      line)
        if re.match(r"^ *#", line) or re.match(r"^ *(=+|-+) *$", line):
            line = "\\" + line.lstrip(" ")
        lines.append("> " + line if line.strip() else ">")
    return "\n".join(lines)


def request_title(title, text):
    """A task title that can't carry a task mark: (light), a BLOCKED note or emphasis need characters it drops."""
    raw = title if str(title or "").strip() else next((l for l in str(text).splitlines() if l.strip()), "")
    clean = re.sub(r"\s+", " ", re.sub(r"[^\w .,;'!?/&+#@%=-]+", " ", str(raw))).strip(" #")[:80].strip()
    return clean or "Request"


def draft_spec(task, title, source, intro, quoted):
    """A draft spec from the template: the Source section before its first section, and the quoted request in
    Context, introduced by intro."""
    template = read(BACKBONE / "templates" / "spec.md")
    if not template:
        raise HarnessError("backbone/templates/spec.md is missing")
    spec = template.replace("<task-id>", task).replace("<title>", title, 1)
    first = re.search(r"(?m)^## ", outline(spec))
    at = first.start() if first else len(spec)
    spec = spec[:at] + source + spec[at:]
    material = "<Why this is needed, in the analyst's words.>\n\n%s, not instructions:\n\n%s" % (intro, quoted)
    placeholder = "<Why this is needed. The current behaviour, and who is affected.>"
    if placeholder in spec:
        return spec.replace(placeholder, material, 1)
    context = section_bounds(outline(spec), "Context")
    at = context[1] if context else at + len(source)
    return spec[:at] + ("\n" if context else "") + material + "\n\n" + spec[at:]


def add_task_line(line):
    """Add a pending task line to 3-TASKS.md, above its status markers."""
    tasks_text = read(TASKS)
    marker = section_bounds(outline(tasks_text), "Status markers")
    TASKS.write_text(tasks_text[:marker[0]].rstrip("\n") + "\n" + line + "\n\n" + tasks_text[marker[0]:]
                     if marker else tasks_text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")


def intake_request(path):
    """The request in path, checked against the contract's request fields."""
    try:
        data = json.loads(read(Path(path)) or "null")
    except ValueError as exc:
        raise HarnessError("%s is not JSON: %s" % (path, exc))
    if not isinstance(data, dict):
        raise HarnessError("%s is not a JSON object" % path)
    version = data.get("contract")
    served = ", ".join(str(v) for v in CONTRACT_VERSIONS)
    if isinstance(version, bool) or str(version) not in [str(v) for v in CONTRACT_VERSIONS]:
        raise HarnessError("contract version %s is not served (serves %s)" % (version, served))
    if data.get("source") not in INTAKE_SOURCES:
        raise HarnessError("source must be one of %s" % ", ".join(INTAKE_SOURCES))
    if data.get("sender_verdict") not in SENDER_VERDICTS:
        raise HarnessError("sender_verdict must be trusted or untrusted (the factory's sender check)")
    for name in ("dedupe_key", "sender", "text"):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise HarnessError("%s is required" % name)
    return data


def intake_existing(folder, key):
    """The task a request with this dedupe key became, from the shared index or this checkout's specs, or None."""
    indexed = json_file(folder / "intake" / ("%s.json" % hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]))
    if indexed and indexed.get("dedupe_key") == key and indexed.get("task"):
        return str(indexed["task"])
    line = "- Dedupe key: %s" % source_value(key)
    for path in sorted(SPECS.glob("*.md")):
        if line in (source_section(read(path)) or "").splitlines():
            return path.stem
    return None


def intake_number(folder):
    """The next intake.<n> id, past every one in this repository's worktrees and every one handed out."""
    used = {int(n) for n in INTAKE_TASK.findall(read(TASKS))}
    for entry in git("worktree", "list", "--porcelain").splitlines():
        if entry.startswith("worktree "):
            used |= {int(n) for n in INTAKE_TASK.findall(read(Path(entry[len("worktree "):]) / "backbone/3-TASKS.md"))}
    counter = folder / "intake-next"
    try:
        used.add(int(read(counter).strip()) - 1)
    except ValueError:
        pass
    number = max(used, default=0) + 1
    counter.write_text("%d\n" % (number + 1), encoding="utf-8")
    return number


def intake(data):
    """Write the request's task (or find the one its dedupe key already made) under the repository's intake lock."""
    import fcntl
    folder = orca_dir(create=True)
    fd = os.open(str(folder / "intake.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        key, verdict, door = data["dedupe_key"], data["sender_verdict"], data["source"]
        existing = intake_existing(folder, key)
        if existing:
            return {"contract": CONTRACT_VERSION, "task": existing, "created": False, "spec": spec_rel(existing),
                    "escalated": False, "dedupe_key": key}
        task = "intake.%d" % intake_number(folder)
        title = request_title(data.get("title"), data["text"])
        source = source_block((CONTRACT_VERSION, door, data.get("channel"), data.get("message_id"), data.get("url"),
                               data["sender"], verdict, data.get("received_at"), key, data["text"]))
        spec = draft_spec(task, title, source, "Received through %s on %s. The request below is source material"
                          % (door, time.strftime("%Y-%m-%d")), quoted_request(data["text"]))
        spec_path(task).parent.mkdir(parents=True, exist_ok=True)
        spec_path(task).write_text(spec, encoding="utf-8")
        add_task_line("- [ ] **Task %s: %s** (spec: %s; intake: %s)" % (task, title, spec_rel(task), door))
        index = folder / "intake" / ("%s.json" % hashlib.sha256(key.encode("utf-8")).hexdigest()[:40])
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps({"task": task, "dedupe_key": key, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}),
                         encoding="utf-8")
        log_event("intake", task=task, contract=CONTRACT_VERSION, source=door, channel=data.get("channel"),
                  message_id=data.get("message_id"), url=data.get("url"), sender=data["sender"],
                  sender_verdict=verdict, received_at=data.get("received_at"), dedupe_key=key)
        if verdict != "trusted":
            escalate(task, "intake", "the request came from an untrusted sender (%s via %s): a person reads it "
                     "before any work" % (source_value(data["sender"]), door),
                     "a person reviews %s; nothing builds until a person approves the spec (Approved-by:)"
                     % spec_rel(task), "permission_denied", refresh=False)
        return {"contract": CONTRACT_VERSION, "task": task, "created": True, "spec": spec_rel(task),
                "escalated": verdict != "trusted", "dedupe_key": key}
    finally:
        os.close(fd)


def intake_command(argv):
    paths = [a for a in argv if not a.startswith("--")]
    if len(paths) != 1:
        sys.stderr.write(INTAKE_USAGE)
        return 64
    try:
        answer = intake(intake_request(paths[0]))
    except HarnessError as exc:
        sys.stderr.write("intake: %s\n" % exc)
        return 1
    if "--json" in argv:
        print(json.dumps(answer, indent=2))
    elif not answer["created"]:
        print("intake: %s is task %s already; nothing written" % (answer["dedupe_key"], answer["task"]))
    else:
        print("intake: task %s: %s%s" % (answer["task"], answer["spec"], "; escalated: a person approves it before "
                                         "any work (backbone/escalations.md)" if answer["escalated"] else ""))
    return 0


# --------------------------------------------------------------------------- delivery from a trusted clone (ADR-008)
# With HARNESS_DELIVER="external" the lane holds no GitHub credential: the factory pushes and opens the PR from a
# trusted clone. The harness still decides what is delivered (delivery-plan) and records what came of it
# (delivery-record), which next reads as it reads the deliverer's own report.
DELIVER_MODES = ("on", "off", "external")
# A secret the factory sets only when it runs delivery-record and next, never for run (which drops it from the agent
# sessions anyway): the lane's agents can run code, so a record they could write unsigned proves nothing.
DELIVERY_KEY = "HARNESS_DELIVERY_KEY"
SIGNED_FIELDS = ("task", "delivery", "head", "pr", "checks", "findings_detail", "verify")


def delivery_mac(event):
    """HMAC-SHA256 of a deliver event's fields under HARNESS_DELIVERY_KEY, or None without the key."""
    key = os.environ.get(DELIVERY_KEY, "")
    if not key:
        return None
    fields = json.dumps({k: event.get(k) for k in SIGNED_FIELDS}, sort_keys=True, default=str)
    return hmac.new(key.encode("utf-8"), fields.encode("utf-8"), hashlib.sha256).hexdigest()


def plan_labels(suggested, current):
    """{add, remove}: the receipt's class:* labels the PR lacks, and its risk:* label when it is higher than every
    risk:* label the PR has, replacing those. A PR keeps one risk:* label, which only goes up."""
    risk = next((label for label in suggested if label in RISK_LABELS), None)
    held = [label for label in current if label in RISK_LABELS]
    top = max((RISK_LABELS.index(label) for label in held), default=-1)
    add = [label for label in suggested if label.startswith("class:") and label not in current]
    if risk and RISK_LABELS.index(risk) > top:
        return {"add": [risk] + add, "remove": held}
    return {"add": add, "remove": []}


def plan_base(given):
    if given:
        return given
    return default_branch() or next((b for b in ("main", "master")
                                     if git("rev-parse", "-q", "--verify", "refs/heads/%s" % b).strip()), None)


def delivery_plan(task, base=None, current=()):
    """What the factory pushes and opens for task, or {ready: false, needed}."""
    plan = {"contract": CONTRACT_VERSION, "task": task, "ready": False}
    step = next_step(task)
    if step["step"] not in ("deliver", "delivery-failed", "done", "blocked"):
        return dict(plan, needed="task %s is at step %s; a plan comes once it is finished and committed"
                    % (task, step["step"]))
    if git("status", "--porcelain").strip():
        return dict(plan, needed="commit the task's changes first: a plan names a commit")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    base = plan_base(base)
    if not base:
        return dict(plan, needed="the base branch: pass --base <branch>")
    if branch in ("", "HEAD", base):
        return dict(plan, needed="the task's own branch checked out (harness/task-%s), not %s" % (slug(task),
                                                                                                 branch or "nothing"))
    blocked = step["step"] == "blocked"
    data, problem = receipt_data(task, base if git("rev-parse", "-q", "--verify", base).strip() else None)
    escalations = [e for e in escalation_entries() if e["task"] == task and (e["status"] or "").lower() == "open"]
    lines = []
    if blocked:
        lines += ["BLOCKED: task %s is escalated and waits for a person (backbone/escalations.md):" % task, ""]
        lines += ["- %s: %s (needed: %s)" % (e["kind"], e["reason"], e["needed"]) for e in escalations] + [""]
    lines += ["```", receipt_text(data), "```"] if data else ["No receipt: %s." % problem]
    follow = ["- %s (%s review, %s)" % (f.get("issue"), lens, f.get("severity"))
              for lens, entry in sorted(lens_reviews(task).items()) if entry
              for f in entry.get("findings") or [] if f.get("severity") in ("should-fix", "nice-to-have")]
    lines += ["", "Follow-ups:"] + (follow or ["- none"])
    lines += ["", "Planned by harness.py delivery-plan; the harness-verify check re-checks the gates. Only a human "
                  "merges this pull request."]
    labels = plan_labels(data["suggested_labels"] if data else [], current)
    return dict(plan, ready=True, branch=branch, base=base, head=git("rev-parse", "HEAD").strip(),
                title="Task %s: %s" % (task, task_title(task) or (data or {}).get("title") or task),
                body="\n".join(lines), draft=blocked, labels=labels, escalations=escalations)


def delivery_plan_command(argv):
    value = lambda flag: argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    task = next((a for i, a in enumerate(argv) if not a.startswith("--")
                 and (i == 0 or argv[i - 1] not in ("--base", "--pr-labels"))), None)
    if not task:
        sys.stderr.write("usage: harness.py delivery-plan <task> [--base <branch>] [--pr-labels a,b] [--json]\n")
        return 64
    current = [label.strip() for label in (value("--pr-labels") or "").split(",") if label.strip()]
    plan = delivery_plan(task, value("--base"), current)
    if "--json" in argv:
        print(json.dumps(plan, indent=2))
    elif not plan["ready"]:
        print("delivery-plan: not ready: %s" % plan["needed"])
    else:
        print("delivery-plan: push %s (%s) and open a %sPR into %s: %s\nlabels: add %s; remove %s\n\n%s"
              % (plan["branch"], plan["head"][:12], "draft " if plan["draft"] else "", plan["base"], plan["title"],
                 ", ".join(plan["labels"]["add"]) or "none", ", ".join(plan["labels"]["remove"]) or "none",
                 plan["body"]))
    return 0 if plan["ready"] else 1


def delivery_record(task, report):
    """Problems with the trusted clone's report on task; with none, the deliver event next reads is logged."""
    if not isinstance(report, dict):
        return ["the report is not a JSON object"]
    outcome, findings = report.get("delivery"), report.get("findings") or []
    head = git("rev-parse", "-q", "--verify", "HEAD").strip()
    pushed = str(report.get("head") or "")
    problems = []
    if task_state(task) == "missing":
        problems.append("there is no task %s in backbone/3-TASKS.md" % task)
    if outcome not in DELIVERY_OUTCOMES:
        problems.append("delivery must be one of %s, not %r" % (", ".join(DELIVERY_OUTCOMES), outcome))
    if not pushed:
        problems.append("head is required: the commit the trusted clone pushed")
    elif git("rev-parse", "-q", "--verify", pushed + "^{commit}").strip() != head:
        problems.append("the pushed head %s is not the task's HEAD %s" % (pushed[:12], head[:12] or "?"))
    if not isinstance(findings, list):
        problems.append("findings must be a list")
        findings = []
    verify = report.get("verify")
    if not isinstance(verify, dict):
        problems.append("verify is required: the range, head and exit of the trusted clone's harness.py verify --range")
        verify = {}
    elif git("rev-parse", "-q", "--verify", str(verify.get("head") or "-") + "^{commit}").strip() != head:
        problems.append("verify ran on %s, not the task's HEAD %s" % (str(verify.get("head"))[:12], head[:12]))
    elif git("rev-parse", "-q", "--verify", str(verify.get("range") or "").partition("..")[2] + "^{commit}").strip() \
            != head:
        problems.append("the verified range doesn't end at the task's HEAD %s: %s" % (head[:12], verify.get("range")))
    elif not isinstance(verify.get("exit"), int) or isinstance(verify.get("exit"), bool):
        problems.append("verify's exit must be its exit status, a number")
    if outcome == "delivered" and verify.get("exit") not in (0, None):
        problems.append("verify exited %s: record a hold with its findings" % verify.get("exit"))
    if outcome == "delivered":
        if git("status", "--porcelain").strip():
            problems.append("there are uncommitted changes, so the PR doesn't hold what was reviewed")
        if report.get("checks") not in ("passed", "none"):
            problems.append("checks are %r: record ci-failed, or wait until they pass" % report.get("checks"))
    elif outcome in DELIVERY_OUTCOMES and (not findings or not all(isinstance(f, dict) and f.get("owner")
                                                                   for f in findings)):
        problems.append("a %s report lists the findings that stopped delivery, each with an owner" % outcome)
    if problems:
        return problems
    owners = sorted({str(f.get("owner")) for f in findings})
    event = dict(task=task, delivery=outcome, branch=report.get("branch"), base=report.get("base"), head=head,
                 pr=report.get("pr"), checks=report.get("checks"), findings=len(findings), owners=owners,
                 findings_detail=findings[:20], problems=None, via="external",
                 verify={"range": verify.get("range"), "head": head, "exit": verify.get("exit")})
    log_event("deliver", mac=delivery_mac(event), **event)
    return []


def delivery_record_command(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: harness.py delivery-record <task> <report.json>\n")
        return 64
    try:
        report = json.loads(read(Path(argv[1])) or "null")
    except ValueError as exc:
        print("delivery-record: %s is not JSON: %s" % (argv[1], exc))
        return 1
    problems = delivery_record(argv[0], report)
    if problems:
        print("delivery-record: refused, nothing recorded:\n- " + "\n- ".join(problems))
        return 1
    print("delivery-record: task %s: %s recorded for %s" % (argv[0], report.get("delivery"), str(report["head"])[:12]))
    return 0


def receipt_command(argv):
    base = argv[argv.index("--base") + 1] if "--base" in argv and argv.index("--base") + 1 < len(argv) else None
    task = next((a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--base")),
                None)
    if not task:
        sys.stderr.write("usage: harness.py receipt <task> [--base <rev>] [--json]\n")
        return 64
    data, problem = receipt_data(task, base)
    if problem:
        print("receipt: %s" % problem)
        return 1
    print(json.dumps(data, indent=2) if "--json" in argv else receipt_text(data))
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


def git_pre_push(remote):
    """The pushed commits must pass verify, reviews included: the same check CI runs on the pull request."""
    if conf()["HARNESS_VERIFY"] == "off":
        return 0
    zero = re.compile(r"^0+$")
    problems = []
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4 or zero.match(parts[1]):
            continue
        local, known = parts[1], parts[3]
        # A force-push or a remote commit we don't have: check what isn't on the remote instead.
        if not zero.match(known) and subprocess.run(["git", "merge-base", "--is-ancestor", known, local],
                                                    cwd=str(ROOT), capture_output=True).returncode == 0:
            base = known
        else:
            new = git("rev-list", local, "--not", "--remotes=%s" % remote).split()
            if not new:
                continue
            base = git("rev-parse", "-q", "--verify", new[-1] + "^").strip() or new[-1]
        problems += verify_range("%s..%s" % (base, local))
    for problem in problems:
        log_event("verify", reason=problem.splitlines()[0][:200], hook="pre-push")
    if problems:
        sys.stderr.write("harness: push blocked; the pushed commits break the harness gates:\n%s\n"
                         "The user can push a deliberate exception with HARNESS_VERIFY=off.\n"
                         % "\n".join("  - " + p for p in problems))
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
    acs = [ac for ac, _ in spec_items(comment_free(read(spec_path(task))), "AC", task)]
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


def record_review(data):
    """The reviewer's Stop: one lens's verdict on the current code. A must-fix finding fails it, whatever was claimed."""
    report = extract_report(data.get("last_assistant_message")
                            or last_message_from_transcript(data.get("transcript_path")), "lens")
    retry = not data.get("stop_hook_active")
    if report is None:
        if retry:
            deny("End your final message with the JSON block described in your instructions.")
        return
    lens = report.get("lens")
    if lens not in REVIEW_LENSES:
        if retry:
            deny("Set \"lens\" to the lens you reviewed through: one of %s." % ", ".join(REVIEW_LENSES))
        return
    task = task_for_role(report)
    if task is None:
        if retry:
            deny("Set \"task\" to the [WIP] task you reviewed: one of %s." % (", ".join(wip_task_ids()) or "(none)"))
        return
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    verdict = "fail" if any(f.get("severity") == "must-fix" for f in findings) else "pass"
    history = verdict_history(task, "review")
    history.append({"lens": lens, "verdict": verdict, "claimed": report.get("verdict"),
                    "fingerprint": code_fingerprint(), "findings": findings,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "summary": report.get("summary")})
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(task, "review").write_text(json.dumps({"task": task, "kind": "review", "history": history}, indent=2)
                                            + "\n", encoding="utf-8")
    snapshot_refresh()
    log_event("review", task=task, lens=lens, verdict=verdict, claimed=report.get("verdict"), findings=len(findings))
    emit({"systemMessage": "harness: %s review of task %s: %s." % (lens, task, verdict.upper())})


DELIVERY_OUTCOMES = ("delivered", "hold", "ci-failed")


def record_delivery(data):
    """The deliverer's Stop: a "delivered" claim must match the checkout (pushed, clean, CI green), and a stop short
    of it must name what stopped it, so the orchestrator can route each finding to its owner."""
    if conf()["HARNESS_DELIVER"] == "external":
        emit({"systemMessage": "harness: delivery is external (HARNESS_DELIVER=external); only delivery-record "
                               "records it, so the deliverer's report is not recorded."})
        return
    report = extract_report(data.get("last_assistant_message")
                            or last_message_from_transcript(data.get("transcript_path")), "delivery")
    if report is None:
        if not data.get("stop_hook_active"):
            deny("End your final message with the JSON block described in your instructions.")
        return
    outcome, findings = report.get("delivery"), report.get("findings") or []
    head = git("rev-parse", "HEAD").strip()
    problems = []
    if outcome not in DELIVERY_OUTCOMES:
        problems.append("delivery must be one of %s, not %r." % (", ".join(DELIVERY_OUTCOMES), outcome))
    elif outcome == "delivered":
        if git("status", "--porcelain").strip():
            problems.append("There are uncommitted changes, so the PR doesn't hold what was reviewed.")
        if not head or git("rev-parse", "@{upstream}").strip() != head:
            problems.append("HEAD %s is not pushed to its upstream branch." % (head[:12] or "?"))
        if report.get("checks") not in ("passed", "none"):
            problems.append("CI checks are %r; report ci-failed, or wait until they pass." % report.get("checks"))
    elif not findings:
        problems.append("A %s report lists the findings that stopped delivery, each with an owner." % outcome)
    if problems and not data.get("stop_hook_active"):
        deny("Your delivery report doesn't match the checkout:\n- " + "\n- ".join(problems))
        return
    owners = sorted({str(f.get("owner")) for f in findings if isinstance(f, dict) and f.get("owner")})
    log_event("deliver", delivery=outcome, branch=report.get("branch"), base=report.get("base"), head=head,
              pr=report.get("pr"), checks=report.get("checks"), findings=len(findings), owners=owners,
              findings_detail=findings[:20],
              problems=problems or None)


ROLE_RECORDERS = {
    "griller": lambda data: record_verdict(data, "grill"),
    "judge": lambda data: record_verdict(data, "judge"),
    "tester": record_tests,
    "debugger": record_debug,
    "reviewer": record_review,
    "deliverer": record_delivery,
}


# --------------------------------------------------------------------------- entry point

HOOKS = {
    "session-start": hook_session_start,
    "subagent-start": hook_subagent_start,
    "pre-tool-use": hook_pre_tool_use,
    "post-tool-use": hook_post_tool_use,
    "stop": hook_stop,
    "grill-stop": lambda data: record_verdict(data, "grill"),
    "judge-stop": lambda data: record_verdict(data, "judge"),
    "subagent-stop": hook_subagent_stop,
    "tester-stop": record_tests,
    "debug-stop": record_debug,
    "review-stop": record_review,
    "deliver-stop": record_delivery,
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


def hook_slow_threshold():
    """Seconds after which a hook call is logged as slow (HARNESS_HOOK_SLOW; 0 = never)."""
    try:
        return max(0.0, float(conf()["HARNESS_HOOK_SLOW"]))
    except ValueError:
        return 0.0


def main(argv):
    global HOOK_SOURCE
    if (argv[1:2] == ["init"] and "--thin" in argv[2:]) or argv[1:2] == ["pin"]:
        command = ENGINE.parent.parent / "tools/thin.py"
        if not command.is_file():
            sys.stderr.write("thin: this engine has no thin-mode installer\n")
            return 2
        return subprocess.run([sys.executable, str(command)] + argv[1:]).returncode
    if argv[1:2] == ["hook"] and "--from" in argv:
        i = argv.index("--from")
        HOOK_SOURCE = argv[i + 1] if i + 1 < len(argv) and argv[i + 1] in HOOK_SOURCES else "claude"
        argv = argv[:i] + argv[i + 2:]
    if argv[1:2] == ["hook"] and len(argv) >= 3 and argv[2] not in ("grill-stop", "judge-stop", "subagent-stop",
                                                                    "tester-stop", "debug-stop"):
        hook_budget(argv[2])   # the verdict recorders run the tests and have their own, longer timeout
    if len(argv) == 3 and argv[1] == "hook" and argv[2] in HOOKS:
        started, data = time.time(), {}
        try:
            data = normalize_hook(read_hook_input(), HOOK_SOURCE)
            HOOK_CONTEXT.update(session=data.get("session_id"), agent=data.get("agent_type") or data.get("agent_id"))
            HOOKS[argv[2]](data)
        finally:
            slow = hook_slow_threshold()
            elapsed = time.time() - started
            if slow and elapsed >= slow:
                log_event("hook-slow", hook=argv[2], seconds=round(elapsed, 3), tool=data.get("tool_name"))
            if HOOK_SOURCE == "codex" and not EMITTED:
                sys.stdout.write("{}\n")   # Codex wants JSON on stdout when a hook exits 0
        return 0
    if len(argv) == 4 and argv[1:3] == ["hook", "agent-guard"]:
        hook_agent_guard(read_hook_input(), argv[3])
        return 0
    if argv[1:] == ["git", "pre-commit"]:
        return git_pre_commit()
    if argv[1:3] == ["git", "pre-push"]:
        return git_pre_push(argv[3] if len(argv) > 3 else "origin")
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
    if argv[1:2] == ["attest"]:
        return attest_command(argv[2:])
    if argv[1:2] == ["environment-check"]:
        return environment_check_command(argv[2:])
    if argv[1:2] == ["repository-check"]:
        return repository_check_command(argv[2:])
    if len(argv) == 3 and argv[1] == "approve":
        return approve_command(argv[2])
    if argv[1:2] == ["escalate"]:
        return escalate_command(argv[2:])
    if argv[1:2] == ["escalations"]:
        return escalations_command(argv[2:])
    if argv[1:2] == ["contract"]:
        return contract_command(argv[2:])
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
    if argv[1:2] == ["receipt"]:
        return receipt_command(argv[2:])
    if argv[1:2] == ["delivery-plan"]:
        return delivery_plan_command(argv[2:])
    if argv[1:2] == ["delivery-record"]:
        return delivery_record_command(argv[2:])
    if argv[1:2] == ["linear"]:
        return linear_command(argv[2:])
    if argv[1:2] == ["intake"]:
        return intake_command(argv[2:])
    if argv[1:2] == ["trace"]:
        return trace_command(argv[2:])
    if argv[1:2] == ["ci-judge"]:
        return ci_judge_command(argv[2:])
    if argv[1:2] == ["ci-protect"]:
        return ci_protect_command(argv[2:])
    if len(argv) == 3 and argv[1] == "risk":
        reasons = risk_reasons(argv[2])
        text = read(spec_path(argv[2]))
        print("risk %s: %s" % (argv[2], "; ".join(reasons) if reasons else "low"))
        print("  %s: %s" % (class_label(text), CLASS_GATES[change_class(text)[0]]))
        return 1 if reasons else 0
    sys.stderr.write(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
