# Harness Hooks and Gates

Harness-owned. All hook logic lives in `scripts/harness/lib/harness.py`, which needs `python3` and `git`.

## Claude Code hooks (`.claude/settings.json`)

| Event | Tools | What it does | Effect |
|---|---|---|---|
| SessionStart | all | Shows the reading list, SETUP INCOMPLETE if FILL placeholders remain, the `[WIP]` task, and harness errors | Added to context |
| PreToolUse | Bash | **Shell checks** (below) and `@bash` block rules: destructive git, recursive root/home delete, DROP/TRUNCATE, `--no-verify` | Command refused |
| PreToolUse | Write, Edit, MultiEdit | Block rules for the path, the **orchestrator scope**, the **skill gate**, plus per file (see below) | Edit refused |
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
| `backbone/adr/*.md` | Only the user sets an ADR to `Accepted`; an accepted ADR is frozen except for being superseded |
| `backbone/harness.conf` | The gate switches, `HARNESS_JUDGE_MAX_ROUNDS`, `HARNESS_VERIFY`, `HARNESS_ORCHESTRATOR_SCOPE` and the decision-layer keys are user-only |
| `backbone/.verdicts/*` | Never writable by agents |
| `backbone/.harness-lock.json` | Written only by the installer and `harness.py adopt` |
| `backbone/escalations.md` | Written by `harness.py escalate`; resolved by the user |

**Orchestrator scope** (`HARNESS_ORCHESTRATOR_SCOPE`, user-only, default `on`): the main session (a tool call without an `agent_id`) may edit only `backbone/` docs and configuration (not specs, ADRs or verdicts), `.claude/skills/` and `CLAUDE.md`. Specs, ADRs and code are written by the role agents.

**Shell checks.** A command is split into its segments (`;`, `&&`, `|`, newlines) and tokenized, so the checks see the program that runs and its arguments, not text that only mentions a command. `@bash` rules don't see commit or tag messages or the bodies of data heredocs (`cat > notes.md <<EOF`). Refused:
- Shell writes, moves and deletes in `backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`, `.git/hooks`, `.git/harness` and `.git/config`: redirections, `rm`/`mv`/`cp`/`tee`/`touch`/`chmod`, `sed -i`/`perl -i`, `git rm|mv`, and `python -c`/`node -e` or interpreter heredocs that write there. Every gate is enforced on the file tools, so these changes go through Write or Edit. `cd` and `bash -c`/`eval` are followed.
- Bypasses: `git commit -n`, `git -c core.hooksPath=...`, `git config core.hooksPath`, and setting `HARNESS_*` or `SKIP_BUILD` from the shell (those are the user's, in their own terminal).
- `git push` with a `+<ref>`, `--mirror` or a branch delete; `find / ... -delete`; `DELETE` without `WHERE` sent to a SQL client; `curl ... | sh`.

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
- **The harness ran the tests itself.** When the judge claims a pass, its recorder runs `HARNESS_TEST_CMD` (timeout `HARNESS_TEST_TIMEOUT`, default 900 seconds) and records the exit code, duration, output hash and tail in the verdict as `test_run`. A non-zero exit or a timeout turns the pass into a fail. Test evidence in the judge's own JSON is ignored.

Gates re-derive a recorded pass from its stored evidence before trusting it, so a hand-written `{"verdict": "pass"}` does not count.

After `HARNESS_JUDGE_MAX_ROUNDS` consecutive fails, the agent is told to escalate to the user.

The user can always act directly. Hooks only see agent edits, so the user can edit `3-TASKS.md` or a spec themselves, or switch a gate off in `harness.conf`. To commit such a deliberate exception, they use `HARNESS_VERIFY=off git commit ...` (see verify below).

## Verify (`HARNESS_VERIFY`)

The hooks guard edits made through the tools. `harness.py verify` checks the **resulting state**, so it also catches changes made any other way. It runs in the pre-commit hook on the staged change, and in CI on a range of commits:

- Every task that became `[WIP]` or `[x]` passes the start gate: valid spec, current grill pass, user approval.
- Every task that became `[x]` has a judge pass whose fingerprint equals the committed code (in CI, the code of the commit that marked it done), and the pass holds up when re-derived.
- At most one `[WIP]` task (unless `HARNESS_ALLOW_PARALLEL_WIP="1"`).
- Verdict history is append-only.
- User-only settings in `harness.conf` are unchanged.
- Harness enforcement files (`scripts/harness/`, `.claude/agents/`) match `backbone/.harness-lock.json`, and `.claude/settings.json` still runs the harness hooks.

`HARNESS_VERIFY` is `block` (default) or `off`, and user-only. The user commits a deliberate exception with `HARNESS_VERIFY=off git commit ...`; agents can't set it.

**CI** is the authoritative copy of this check, because nothing in an agent's session can switch it off. The harness installs `.github/workflows/harness-verify.yml`, which on every pull request:
- takes `scripts/harness/lib` from the **base branch** and runs it against the pull request's checkout (`HARNESS_ROOT`), so a pull request can't change the verifier that checks it;
- runs `verify --range origin/<base>..HEAD`.

In a range, any change to the harness itself (enforcement files, the lock) or to user-only settings fails. The only way through is the `harness-change-approved` label, which the workflow turns into `--allow-user-changes`. Make the check required in branch protection, and restrict who may label pull requests.

## Autonomous mode (`HARNESS_AUTONOMY`)

`supervised` (default) or `autonomous`, user-only. In autonomous mode no human is in the loop, and AGENTS.md section 7 replaces every "ask the user":

| Mechanism | What it does |
|---|---|
| `harness.py approve <id>` | Policy approval. For a valid spec with a current griller pass, it writes `Approved-by: policy:low-risk (<date>; base <commit>; grill <fingerprint>)`, but only if `risk_reasons` finds nothing. Otherwise it escalates. Only `HARNESS_AUTO_APPROVE="low"` enables it; `off` escalates every spec. |
| Risk | Spec text (outside the Skills section) matching `HARNESS_RISK_TERMS`, spec paths matching `HARNESS_RISK_PATHS`, or a referenced ADR that isn't Accepted. When finishing a policy-approved task, the judge gate also assesses the diff since the base commit: sensitive paths, or more than `HARNESS_RISK_MAX_FILES` files. `harness.py risk <id>` shows the assessment. |
| `harness.py escalate <id> --reason ...` | Parks the task. Its line leaves `[WIP]` with a `BLOCKED: <kind>` note, and an entry goes into `backbone/escalations.md` (a GitHub issue too with `HARNESS_ESCALATE_GH="on"` and `gh`). A BLOCKED task cannot start. Agents can't clear the note or edit `escalations.md`. `harness.py escalations` lists open entries. |
| Automatic escalation | The griller's recorder after `HARNESS_GRILL_MAX_ROUNDS` consecutive fails, the judge's after `HARNESS_JUDGE_MAX_ROUNDS`. |
| Stop hook | Behaves as `block` (once per stop) whenever a task is `[WIP]`. |
| Kill switch | While `.git/harness/STOP` exists, every Bash and file tool call is refused, and the Stop hook lets the session end. Agents can't remove it through the shell. |

`doctor.sh` reports an error if autonomous mode runs without `HARNESS_TEST_CMD`, or with verify, the start gate or the judge gate off.

## Runner (`harness.py run`)

The user (or a scheduled job) runs `python3 scripts/harness/lib/harness.py run [--max-tasks N] [--dry-run]` in autonomous mode. The runner only sequences work; the hooks, gates and verify still do all the enforcing. For each ready task (a `[WIP]` one first, then pending lines in order; BLOCKED tasks are skipped), it:

- starts a fresh agent session with `HARNESS_AGENT_CMD`, passing the task prompt on stdin;
- stops the session after `HARNESS_RUN_TASK_TIMEOUT` seconds;
- reads the outcome from `3-TASKS.md`:
  - `[x]` with a clean working tree means done;
  - a `BLOCKED` note means the agent escalated;
  - anything else is retried, up to `HARNESS_RUN_ATTEMPTS` sessions, and then escalated as `runner`;
- checks the kill switch between sessions.

Logs go to `.git/harness/runs/<timestamp>/<task>-<attempt>.log`. Agents can't start the runner.

- **Workspace trust.** In a folder Claude Code hasn't trusted, `claude -p` ignores the project's hooks, agent hooks and permissions, so the harness would not run at all. The runner refuses to start there; accept the trust dialog once interactively. The sandbox and the CI judge trust their own workspace. `HARNESS_SKIP_TRUST_CHECK=1` is for agent commands other than Claude Code.
- **Budgets.**
  - `HARNESS_RUN_TASK_TIMEOUT` per session and `HARNESS_RUN_ATTEMPTS` per task.
  - `HARNESS_RUN_MAX_COST`: dollars per run. The run stops before the next task once spent. Cost and turns are read from `--output-format json` output (the default command uses it).
  - Per session, add `--max-budget-usd <n>` to `HARNESS_AGENT_CMD`.
- **`--worktree [--pr]`:** each task runs in its own worktree, on branch `harness/task-<id>` from the current HEAD. The base branch is left untouched.
  - With `--pr`, a done or escalated task's branch is pushed and a pull request opened (`gh`), so CI gates each task separately.
  - A task that already has a branch is skipped; delete the branch to retry.
  - Tasks run independently of each other, so `3-TASKS.md` may need a rebase between their pull requests.
- **`--only <id>`** runs one task.
- **An agent that cannot start** (not logged in, bad API key: it fails at no cost) stops the run. Retrying or moving to the next task can't help, so no task is escalated for it, and the task stays ready.
- **Keep the machine awake.** A sleeping laptop suspends the run, so wall time grows while nothing happens. On macOS, start the runner with `caffeinate -i python3 scripts/harness/lib/harness.py run`.

**Sandbox.** `.devcontainer/harness-agent/` is a container for unattended runs. It has been built and checked (firewall, hooks, self-test), and has run a real task end to end (spec, grill, policy approval, build, judge) with a subscription token. Review it before use, and add your toolchain. It provides:
- outbound traffic limited to the Anthropic API, GitHub and `HARNESS_FIREWALL_ALLOW`;
- no host credentials apart from `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, counted against your Claude subscription) or `ANTHROPIC_API_KEY` (billed per token). The host's keychain login isn't visible in the container;
- a trusted workspace;
- `HARNESS_AGENT_CMD` set to `--dangerously-skip-permissions`, because the container, not the prompt, is the boundary.

Add your toolchain in a Dockerfile that builds `FROM` it.

`HARNESS_AGENT_CMD` defaults to `claude -p --permission-mode acceptEdits --output-format json`. The prompt arrives on stdin. That matters because `--allowedTools` takes any number of values and would swallow a prompt passed as an argument; quote each pattern, as in `--allowedTools 'Bash(git:*)' 'Bash(python3:*)'`. An unattended agent needs its tools pre-approved: allow the build and test commands in `.claude/settings.json`, or run it in a container or VM with `--dangerously-skip-permissions`. The harness hooks apply either way. Work on a branch and let the CI check gate the merge.

## Out-of-band changes (autonomous mode)

The shell checks can't see what a script file does. In autonomous mode the harness keeps a snapshot of the protected files (`backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`). The snapshot is refreshed after every file-tool edit and every write of the harness's own.

After each shell command, any protected file that changed outside those, and isn't simply back to its committed version, is reported. It is logged as `tamper`, and the `[WIP]` task is escalated for review. Restore the file with `git checkout -- <file>`.

## Event log and report

Blocks, verify refusals, verdicts, approvals, escalations and run attempts are appended to `.git/harness/events.jsonl`. `harness.py report [--days N]` summarises them (`--json` for machines):
- tasks finished;
- judge verdicts, and claimed passes the harness overturned;
- escalations and policy approvals;
- blocked tool calls and refused commits, by reason.

## CI judge and branch protection

`harness.py ci-judge --range <base>..<tip>` re-judges every task the range marks `[x]`:
- It runs a fresh judge session with `HARNESS_CI_JUDGE_CMD` (default `claude -p --agent judge ...`).
- It re-runs `HARNESS_TEST_CMD`, and applies the same re-derivation rules as the judge recorder.
- It fails unless the independent verdict is a pass.

The verdicts committed with a task were produced inside the agent's session; this one isn't. The project-owned template `.github/workflows/harness-judge.yml` runs it on pull requests when the `ANTHROPIC_API_KEY` secret is set; add your toolchain steps to it.

`harness.py ci-protect [--branch main] [--with-judge] [--dry-run]` (needs `gh`) does two things:
- requires the `verify` check (and optionally `judge`) on the branch;
- creates the `harness-change-approved` label.

Agents can't run `ci-judge` or `ci-protect`.

## Git hooks (`core.hooksPath = scripts/harness/git-hooks`)

| Hook | What it does | Blocks? |
|---|---|---|
| pre-commit | Checks added lines of staged files against block and warn rules, runs **verify** on the staged change, then runs `HARNESS_BUILD_CMD` if it is set | Yes, on a block rule, a verify problem or a failed build |
| commit-msg | Conventional Commits, types from `HARNESS_COMMIT_TYPES`, subject within `HARNESS_SUBJECT_MAX`. Merge, Revert, `fixup!`, `squash!` and `amend!` are exempt. Warns (does not block) when the scope matches no staged path, unless it is a cross-cutting scope (`HARNESS_CROSS_SCOPES`) | Yes, on format |

A fresh clone needs `git config core.hooksPath scripts/harness/git-hooks` once. `doctor.sh` and the session-start note report when it is missing.

## Hook time budget

Claude Code treats a hook it kills for running too long as a non-blocking error, and lets the tool call through. So the harness keeps its own budget of 25 seconds, under the 30-second timeout in `.claude/settings.json`, and its `git` calls time out before that:
- `pre-tool-use` and the agents' write-scope checks **fail closed** when the budget runs out: the call is refused with "retry".
- Other hooks exit quietly.
- The griller's and judge's verdict recorders are exempt: they run the tests under `HARNESS_TEST_TIMEOUT`.

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
| `HARNESS_VERIFY` | `block` | `block` or `off`: verify in pre-commit. User-only |
| `HARNESS_ORCHESTRATOR_SCOPE` | `on` | Main session may not edit specs, ADRs or code. User-only |
| `HARNESS_TEST_TIMEOUT` | `900` | Seconds the judge recorder lets `HARNESS_TEST_CMD` run |
| `HARNESS_AUTONOMY` | `supervised` | `supervised` or `autonomous` (see above). User-only |
| `HARNESS_AUTO_APPROVE` | `low` | `low`: `approve` approves low-risk specs in autonomous mode; `off`: every spec is escalated. User-only |
| `HARNESS_RISK_TERMS`, `HARNESS_RISK_PATHS` | security, data, API and build terms and paths | Regexes for what is not low-risk. User-only |
| `HARNESS_RISK_MAX_FILES` | `20` | A policy-approved change touching more files is escalated. User-only |
| `HARNESS_GRILL_MAX_ROUNDS` | `3` | Griller fails before an autonomous escalation. User-only |
| `HARNESS_ESCALATE_GH` | `off` | `on`: escalations also open a GitHub issue (`gh`). User-only |
| `HARNESS_AGENT_CMD` | `claude -p --permission-mode acceptEdits --output-format json` | The runner's agent command (prompt on stdin). User-only |
| `HARNESS_RUN_TASK_TIMEOUT` | `3600` | Seconds per agent session in a run. User-only |
| `HARNESS_RUN_ATTEMPTS` | `2` | Sessions per task before the runner escalates it. User-only |
| `HARNESS_RUN_MAX_COST` | empty (no limit) | Dollars per run; the runner stops before the next task once spent. User-only |
| `HARNESS_CI_JUDGE_CMD` | `claude -p --agent judge --dangerously-skip-permissions --output-format json` | The CI judge session. User-only |
| `HARNESS_SKILL_MAX_AGE` | `180` | Days after which doctor flags a skill's `last-verified` date; `0` turns it off |
| `HARNESS_SCOPE_CHECK` | `on` | Commit-scope warning |
| `HARNESS_CROSS_SCOPES` | `deps\|build\|ci\|docs\|backbone\|harness\|release\|config\|tests?` | Scopes exempt from the scope check (regex) |
| `HARNESS_CONTAINER_ENGINE` | empty | Container engine chosen in the stack ADR (set when a container pack is adopted) |
| `HARNESS_DECISION_PROVIDER`, `_MODE`, `_ADR`, `_CMD`, `_MODEL`, `_URL`, `_TIMEOUT` | `none`, `off`, empty, empty, empty, empty, `20` | Decision layer (see above). User-only, except the timeout |
| `HARNESS_COMMIT_NUDGE` | `8` | With no `[WIP]` task, nudge to commit at this many changed tracked files; `0` turns it off |

## Decision layer (advisory)

Some checks need judgement that code cannot compute. The decision layer asks a model for **typed answers**, not prose: a choice among declared options, a score on a declared scale, or a yes/no probability, each with a confidence. Deterministic checks never move here, and decisions never block anything.

- **Providers:**
  - `none` (default);
  - `command`: any executable, given JSON on stdin and printing JSON on stdout, so local models fit behind it;
  - `ollama`: a local Jev-style decision endpoint (Ollama's `/v1/systemone`, default model `nimble`). Data stays on the machine, and there's no per-call cost. `HARNESS_DECISION_URL` overrides the endpoint;
  - `claude`: the Claude Messages API over plain HTTPS, with structured outputs, effort `low`, and refusal fallback. It needs no install, only `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) in the environment of whoever commits;
  - `jev`: TypeSafe Jev via `typesafe-sdk`. This adapter is written from published examples and is unverified.
- **Authorisation:** a provider receives project data (diffs and messages), so it runs only when `HARNESS_DECISION_ADR` names an **Accepted** ADR that mentions it. Choosing a provider is a design decision like any other stack choice. All `HARNESS_DECISION_*` keys are user-only.
- **Modes:** `shadow` only logs. `advise` also prints the answers that cross their thresholds. Start in shadow mode, compare the log with your own judgement, then tune thresholds before switching to advise.
- **Questions and thresholds** live in `scripts/harness/decisions.json`, versioned. The model never sees question ids, so the meaning has to be in `instructions` and the option texts. `warn_if` thresholds sit next to each question and are reviewed like code. A choice warns when its confidence reaches `min_confidence`, or when the probability of the chosen option reaches `min_probability`. Providers calibrate confidence differently: local Jev-style models report low confidence even for likely answers.
- **Log:** every call is appended to `.git/harness/decisions.jsonl`, with its state, questions, answers, latency and errors, so any change can be replayed. Summarise it with `python3 scripts/harness/lib/harness.py decisions [--last N]`.
- **Failures never block:** a timeout, error, refusal or off-schema answer is logged and ignored.

| Decision | Where | Questions |
|---|---|---|
| `commit-message` | commit-msg hook, after the format checks pass | `fit` (accurate / partial / mismatch); `unmentioned` (significant change not in the message); `leftovers` (debug prints, commented-out code, skipped tests) |

## Escape hatches

- `SKIP_BUILD=1 git commit ...` skips the build check once, and `HARNESS_VERIFY=off git commit ...` the verify check. Both are for the user in their own terminal; agents can't set them.
- Blocked destructive commands are run by the user, never rephrased by agents.
- A wrong rule or route is fixed in its file, not bypassed.

## Troubleshooting

- Run `scripts/harness/doctor.sh`. It reports inactive git hooks, missing settings hooks or agents, invalid rules or routes, routes to missing skills, locally edited harness files and empty commands.
- Run a hook by hand. For example: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 scripts/harness/lib/harness.py hook pre-tool-use`.
- Session skill state lives in `.git/harness/sessions/`, outside the repository content.
