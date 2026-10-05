# Harness Hooks and Gates

Harness-owned. All hook logic lives in `scripts/harness/lib/harness.py`, which needs `python3` and `git`.

## Claude Code hooks (`.claude/settings.json`)

| Event | Tools | What it does | Effect |
|---|---|---|---|
| SessionStart | all | Shows the reading list, SETUP INCOMPLETE if FILL placeholders remain, the `[WIP]` task, and harness errors | Added to context |
| PreToolUse | Bash | `@bash` block rules: destructive git, recursive root/home delete, DROP/TRUNCATE, `--no-verify`, shell writes to `.verdicts/` | Command refused |
| PreToolUse | Write, Edit, MultiEdit | Block rules for the path, the **skill gate**, plus per file (see below) | Edit refused |
| PostToolUse | Read, Skill | Records which skills the session has loaded (for the skill gate) | Silent |
| PostToolUse | Write, Edit, MultiEdit | Warn rules; harness-owned file edited; spec readiness after a spec edit | Added to context |
| PostToolUse | Bash | `@bash` warn rules (discarding changes, force branch delete, amend, ...); after a fresh `git commit`: task log touched, ADR format, TODO stubs, WIP left | Added to context |
| Stop | n/a | If a task is still `[WIP]`: `remind` shows a one-line note; `block` makes the agent address the DoD once. With no `[WIP]`, a commit nudge once `HARNESS_COMMIT_NUDGE` tracked files are changed | Per `HARNESS_STOP_MODE` |

Session start and `doctor.sh` also run a **scan**: every file rule against the full content of tracked and untracked files. Rules otherwise only see added text, so the scan finds violations that already existed (drift). Session start names files with blocking violations so agents don't copy those patterns; `python3 scripts/harness/lib/harness.py scan` lists them all.

Per-file checks in PreToolUse:

| File | Checks |
|---|---|
| `backbone/3-TASKS.md` | One `[WIP]` at a time; **start gate** for a new `[WIP]`; **judge gate** for finishing one |
| `backbone/specs/*.md` | `Approved-by:` lines are user-only; an approved spec is frozen |
| `backbone/harness.conf` | `HARNESS_SPEC_GATE`, `HARNESS_SKILL_GATE`, `HARNESS_JUDGE_GATE` and `HARNESS_JUDGE_MAX_ROUNDS` are user-only |
| `backbone/.verdicts/*` | Never writable by agents |

### Hooks scoped to agents (`.claude/agents/*.md` frontmatter)

| Agent | Event | What it does |
|---|---|---|
| `analyst`, `architect`, `implementer`, `scribe` | PreToolUse | Write scope: analyst may edit specs and the PRD; architect ADRs, the ADR index, `2-PLANNING.md` and specs; scribe `6-MEMORY.md`, ADRs and the index; implementer anything except `backbone/`, `.claude/` and harness files |
| `griller` | Stop (as SubagentStop) | Records the grill verdict with the spec fingerprint in `.verdicts/<id>.grill.json` |
| `judge` | Stop (as SubagentStop) | Records the judge verdict with the code fingerprint in `.verdicts/<id>.judge.json` |

Both recorders take the verdict JSON from the agent's final message, falling back to the transcript. If there is no valid JSON, they send the agent back once. A claimed pass is **re-derived** from the agent's own evidence and the files before it is recorded, as described below. Project subagents and their hooks only load once Claude Code trusts the project folder.

## The gates

### Start gate (`HARNESS_SPEC_GATE`)

A task line may become `[WIP]` only when all of these hold. Check them with `python3 scripts/harness/lib/harness.py spec-check <id>`.

1. **Spec valid:**
   - It has at least one requirement `REQ-<id>-<n>`.
   - Every acceptance criterion `AC-<id>-<n>` is Given/When/Then and references existing requirements, and every requirement has an acceptance criterion.
   - The Architecture section references at least one existing ADR, with status Accepted or Proposed and all its sections filled.
   - The Skills section lists existing skills.
   - Open questions is `- none`, and there are no FILL, TODO or TBD markers.
2. **Grill pass on the current spec.** The fingerprint covers the spec text (without the Approval section) and every referenced ADR, so changing either makes the pass stale. A pass is recorded as a fail if any blocker or major question is open, or if the spec is invalid.
3. **User approval:** an `Approved-by:` line under `## Approval`. Only the user can write it. Once it is there, agents can't change the spec.

### Skill gate (`HARNESS_SKILL_GATE`)

Before an agent edits a file, it must have loaded, in the same session, every skill routed to that path (`routing.core.conf` and `backbone/routing.conf`). For code while a task is `[WIP]`, it also needs the skills listed in the spec. "Loaded" means it read `.claude/skills/<name>/SKILL.md` or invoked the skill. The refusal message lists the missing skills. Paths under `backbone/`, `.claude/` and `scripts/harness/` only need their routes.

### Judge gate (`HARNESS_JUDGE_GATE`)

Taking a task out of `[WIP]`, other than reverting it to `- [ ]` with the same text, requires a latest judge verdict of **pass** whose code fingerprint equals the current code. The fingerprint is the git tree hash of the working tree, excluding `backbone/`.

A judge pass is recorded as a fail unless all of these hold:
- Every AC in the spec was evaluated as met, with tests listed.
- Every AC id appears in at least one test file (matching `HARNESS_TEST_PATHS`, outside `backbone/`).
- There are no blocker or major findings.
- Tests were reported `passed`.

After `HARNESS_JUDGE_MAX_ROUNDS` consecutive fails, the agent is told to escalate to the user.

The user can always act directly. Hooks only see agent edits, so the user can edit `3-TASKS.md` or a spec themselves, or switch a gate off in `harness.conf`.

## Git hooks (`core.hooksPath = scripts/harness/git-hooks`)

| Hook | What it does | Blocks? |
|---|---|---|
| pre-commit | Checks added lines of staged files against block and warn rules, then runs `HARNESS_BUILD_CMD` if it is set | Yes, on a block rule or a failed build |
| commit-msg | Conventional Commits, types from `HARNESS_COMMIT_TYPES`, subject within `HARNESS_SUBJECT_MAX`. Merge, Revert, `fixup!`, `squash!` and `amend!` are exempt. Warns (does not block) when the scope matches no staged path, unless it is a cross-cutting scope (`HARNESS_CROSS_SCOPES`) | Yes, on format |

A fresh clone needs `git config core.hooksPath scripts/harness/git-hooks` once. `doctor.sh` and the session-start note report when it is missing.

## Rule and route files

```
guardrails:  <block|warn> | <path regex, or @bash> | <content regex> | <message>
routes:      <path regex> | <skill>[, <skill>...] | <why>
```

Fields are separated by a space, a pipe and a space. Regexes use Python syntax. Guardrails match per line, and only the text being added (an edit's new text, or a staged diff's added lines).

Two files of each kind apply: the core file in `scripts/harness/`, then the project's file in `backbone/`. Stack packs adopted from an accepted ADR add their rules and routes to the project files, as blocks marked `# >>> adopted pack: <name> (ADR-NNN, ...)`. Re-adopting replaces the block, and `adopt --remove` deletes it. A block's rules belong to that ADR's decision. To change one, change the decision: write a superseding ADR, then re-adopt.

## Configuration (`backbone/harness.conf`)

`KEY="value"` lines. The file is parsed, never executed. An environment variable with the same name overrides the file.

| Key | Default | Meaning |
|---|---|---|
| `HARNESS_PROJECT_NAME` | folder name | Shown at session start |
| `HARNESS_BUILD_CMD` | empty | Run by pre-commit; empty skips it |
| `HARNESS_TEST_CMD` | empty | The test command the implementer and judge run |
| `HARNESS_TEST_PATHS` | common test layouts | Regex for test files, used for AC traceability |
| `HARNESS_COMMIT_TYPES` | `feat\|fix\|refactor\|perf\|test\|docs\|build\|ci\|chore\|style\|revert` | Allowed commit types |
| `HARNESS_SUBJECT_MAX` | `72` | Maximum length of a commit subject |
| `HARNESS_STOP_MODE` | `remind` | `remind`, `block` or `off` |
| `HARNESS_ALLOW_PARALLEL_WIP` | `0` | `1` allows several `[WIP]` tasks |
| `HARNESS_SPEC_GATE` | `on` | Start gate. User-only |
| `HARNESS_SKILL_GATE` | `on` | Skill gate. User-only |
| `HARNESS_JUDGE_GATE` | `on` | Judge gate. User-only |
| `HARNESS_JUDGE_MAX_ROUNDS` | `2` | Judge fails before escalating. User-only |
| `HARNESS_SCOPE_CHECK` | `on` | Commit-scope warning |
| `HARNESS_CROSS_SCOPES` | `deps\|build\|ci\|docs\|backbone\|harness\|release\|config\|tests?` | Scopes exempt from the scope check (regex) |
| `HARNESS_CONTAINER_ENGINE` | empty | Container engine chosen in the stack ADR (set when a container pack is adopted) |
| `HARNESS_DECISION_PROVIDER`, `_MODE`, `_ADR`, `_CMD`, `_MODEL`, `_TIMEOUT` | `none`, `off`, empty, empty, empty, `20` | Decision layer (see above). User-only, except the timeout |
| `HARNESS_COMMIT_NUDGE` | `8` | With no `[WIP]` task, nudge to commit at this many changed tracked files; `0` turns it off |

## Decision layer (advisory)

Some checks need judgement that code cannot compute. The decision layer asks a model for **typed answers**, not prose: a choice among declared options, a score on a declared scale, or a yes/no probability, each with a confidence. Deterministic checks never move here, and decisions never block anything.

- **Providers:**
  - `none` (default);
  - `command`: any executable, given JSON on stdin and printing JSON on stdout, so local models fit behind it;
  - `claude`: the Claude Messages API over plain HTTPS, with structured outputs, effort `low`, and refusal fallback. It needs no install, only `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) in the environment of whoever commits;
  - `jev`: TypeSafe Jev via `typesafe-sdk`. This adapter is written from published examples and is unverified.
- **Authorisation:** a provider receives project data (diffs and messages), so it runs only when `HARNESS_DECISION_ADR` names an **Accepted** ADR that mentions it. Choosing a provider is a design decision like any other stack choice. All `HARNESS_DECISION_*` keys are user-only.
- **Modes:** `shadow` only logs. `advise` also prints the answers that cross their thresholds. Start in shadow mode, compare the log with your own judgement, then tune thresholds before switching to advise.
- **Questions and thresholds** live in `scripts/harness/decisions.json`, versioned. The model never sees question ids, so the meaning has to be in `instructions` and the option texts. `warn_if` thresholds sit next to each question and are reviewed like code.
- **Log:** every call is appended to `.git/harness/decisions.jsonl`, with its state, questions, answers, latency and errors, so any change can be replayed. Summarise it with `python3 scripts/harness/lib/harness.py decisions [--last N]`.
- **Failures never block:** a timeout, error, refusal or off-schema answer is logged and ignored.

| Decision | Where | Questions |
|---|---|---|
| `commit-message` | commit-msg hook, after the format checks pass | `fit` (accurate / partial / mismatch); `unmentioned` (significant change not in the message); `leftovers` (debug prints, commented-out code, skipped tests) |

## Escape hatches

- `SKIP_BUILD=1 git commit ...` skips the build check once. Agents must say when they use it.
- Blocked destructive commands are run by the user, never rephrased by agents.
- A wrong rule or route is fixed in its file, not bypassed.

## Troubleshooting

- Run `scripts/harness/doctor.sh`. It reports inactive git hooks, missing settings hooks or agents, invalid rules or routes, routes to missing skills, locally edited harness files and empty commands.
- Run a hook by hand. For example: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 scripts/harness/lib/harness.py hook pre-tool-use`.
- Session skill state lives in `.git/harness/sessions/`, outside the repository content.
