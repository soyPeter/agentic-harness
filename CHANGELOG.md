# Changelog

## 0.13.3 (2026-10-17)

More from the ledger backlog run: **false escalations from over-adversarial grilling.**
- `format_money` was escalated over `Decimal('1E+100000000')`, and `parse_amount` over `str` subclasses and a CLI file-size limit (task 1.9's business). The griller's instruction to cover "abuse cases" applied hostile-input thinking to a local tool reading its own user's bank file.
- Now the griller judges abuse cases by the product's threat model (who supplies the input, across which trust boundary). It doesn't ask about inputs outside the PRD's domain or about another task's scope (at most a minor suggesting "out of scope").
- The analyst settles such questions under Out of scope with their source, instead of escalating them.

## 0.13.2 (2026-10-17)

Findings from the 10-task ledger backlog run:
- **Specs that never converge.** For `parse_amount`, the analyst and architect wrote 31 acceptance criteria, an exact regex and an error-message length cap. The griller kept finding blocker-level contradictions inside that detail, and the task was escalated after 3 rounds. Now:
  - the analyst specifies behaviour, not internals;
  - the architect keeps implementation out of the spec;
  - the griller asks for detail nobody asked for to be removed (major), not perfected, and reserves "blocker" for behaviour that would be wrong for users.
- **Codex in a worktree:** the worktree's git metadata lives in the main repository's `.git`, outside Codex's workspace-write sandbox, so `harness.py next` (and any git write) asked for approval. The coordinator now starts Codex with that `.git` as a writable root.
- **Coordinator log:** it now says when and why a task settles (blocked, done), and it watches the terminals it opened itself for approval prompts (the handle was missing).

## 0.13.1 (2026-10-17)

- **`harness.py orca --trust` also trusts the repository itself.** Claude Code decides trust for a git worktree by its main repository, so trusting only the task worktrees still blocked every Claude Code worker (`Agent startup blocked: agent-trust-workspace`). Found on the first run of the 10-task ledger backlog.

## 0.13.0 (2026-10-17)

- **`harness.py orca` runs a backlog, not just a batch.**
  - All ready tasks are queued; up to `--parallel` run at once, and the next starts when a slot frees.
  - Dependencies come from the task line: `(after: 1.2, 1.3)`. A task waits until they are `[x]` on the base branch, and `--dry-run` shows what it waits for.
  - `--merge` brings each finished task into the base branch, so the tasks after it build on it.
  - Conflicts only in `3-TASKS.md` (neighbouring task lines) and the memory and decision logs are resolved: the base's task list with the task marked `[x]`, and both sides of each log. Any other conflict aborts the merge and is reported.

## 0.12.1 (2026-10-17)

- **Codex workers report to Orca without permission prompts.** `.codex/rules/harness.rules` (harness-owned and lock-checked) allows exactly `orca orchestration check`, `send` and `ask` outside Codex's sandbox; everything else keeps Codex's own approvals (checked with `codex execpolicy check`). Codex loads it once the project's `.codex/` layer is trusted, which `harness.py orca --trust` does for task worktrees. This removes the manual approvals of the 0.12.0 live run.

## 0.12.0 (2026-10-17)

- **Orca coordinator: `harness.py orca`.** It drives ready tasks in parallel with Orca supervised workers, one Orca worktree per task and one worker per step. It asks `harness.py next` what each task needs, and runs approve, start, finish and the commit itself, through the gates.
  - **Questions between agents:** a worker asks the coordinator. An analyst or architect worker answers from the sources into the spec, with its source, and the reply says where. What nobody can answer is escalated.
  - **Griller questions** spanning both roles are answered by each role before the next grill, the blocker's owner first. A spec with only placeholder tech requirements goes to the architect.
  - **The agent per role** is set by `HARNESS_ORCA_AGENTS` (for example `judge=codex`). Launch commands come from `HARNESS_ORCA_LAUNCH`: Codex starts with the hook-trust bypass and without its update prompt.
  - **`--trust`** marks the task worktrees trusted for Claude Code and Codex.
  - **Lifecycle:** every delivery is acknowledged, and a worker is released only after it settles. A worker that Orca reports failed without a report (for example a blocked startup) escalates its task. A worker waiting at a permission prompt is logged and never answered. A step that comes back 3 times without progress is escalated.
- **Live run with Orca:** two tasks in parallel, Claude Code for the roles and Codex as the judge.
  - Both finished: analyst, architect, griller (with answer rounds), policy approval, tester, implementer, Codex judge (verdicts recorded through Codex's `SubagentStop` hook), scribe, commit.
  - One question the sources didn't settle was escalated and answered.
  - The run found and fixed these bugs:
    - the out-of-band snapshot was shared between worktrees, so parallel tasks saw each other's files as tampering;
    - the tester's acceptance files, and harness files, made `next` skip the implementer;
    - "permission" and "role" in ordinary prose made a spec risky (the defaults now name access-control phrases: RBAC, access control, user or admin roles, permission model);
    - Codex's directory-trust and update prompts blocked unattended starts.
  - **Still manual:** Codex asks before each `orca orchestration` command until you allow them once (see `backbone/HOOKS.md`).
- `next` sends a `[WIP]` task back to the griller when its spec changed during the build.

## 0.11.0 (2026-10-17)

- **Tester** (`HARNESS_TESTER`, user-only, default `off`): independent acceptance tests.
  - The new `tester` agent writes at least one acceptance test per AC from the spec, before the code exists, in files matching `HARNESS_ACCEPTANCE_PATHS` (default: paths containing `acceptance`). They should fail at that point.
  - The tester may write only there, and the implementer may not write there.
  - On the tester's Stop, the harness records which files cover which criteria, and a fingerprint of them (`backbone/.verdicts/<id>.tests.json`). It refuses to record while a criterion has no acceptance test.
  - The judge gate refuses to finish a task without recorded tests, with a criterion uncovered, or with the tests changed since, including through the shell. The judge's evidence no longer comes from the code's own author.
- **Debugger** (`HARNESS_DEBUGGER`, default `on`): after a judge fail, `next` sends the task to the new `debugger` agent before the implementer.
  - It changes nothing. It reproduces the failure and records a fix brief, with a root cause, a fix and an owner per problem (`backbone/.verdicts/<id>.debug.json`).
  - `next` hands the brief to the implementer, and flags causes owned by the tester, analyst or user under `needs`.
- `next` gains the steps `test` (tester) and `diagnose` (debugger). The Codex and OpenCode adapters record both roles, and their agents are generated.
- Existing projects get the new settings commented out in `harness.conf` on update.

## 0.10.0 (2026-10-17)

- **Codex and OpenCode reach the same gates as Claude Code.** Every CLI's hooks call `harness.py hook <event> --from <cli>`, which normalises the input before any gate runs.
  - Codex: `.codex/hooks.json`. Its `apply_patch` edits are parsed and checked file by file; verdicts come from `SubagentStop`; a skill counts as loaded when its SKILL.md is printed; the Stop hook always answers with JSON, as Codex requires.
  - OpenCode 2 (and 1): `.opencode/plugins/harness.js` translates `shell`, `edit`, `write` and `patch` calls and refuses blocked ones by throwing (fail closed on crashes and timeouts). Verdicts come from the `subagent` tool's result. Its primary agents (`build`, `plan`) count as the main session.
  - The role agents for both are generated from `.claude/agents/` by `tools/gen_agents.py`. Codex has no per-agent tool list, so the harness now holds the griller and judge to "no edits" itself, by role.
  - Live checks: in both Codex 0.162 and OpenCode 2.0.26, a `git commit -n` and a forged verdict file were refused by the harness hooks.
- **Role sessions:** `HARNESS_ROLE=<role>` makes a whole session one role (a coordinator's worker). It is held to that role's write scope, records the griller's or judge's verdict when it stops, and leaves the Definition of Done to the coordinator.
- **Coordinator API:** `harness.py state`, `next <id>`, `questions <id>`, `start <id>` and `finish <id>`. A coordinator learns the next step and its role from the artifacts the gates check, and moves task lines through the same gates as an edit. Griller questions are routed: design to the architect, the rest to the analyst.
- **Orca:** with `HARNESS_ORCA_RUN` set, `escalate` also posts an `escalation` message to the Orca Run.
- **Runner:** reads Codex's `exec --json` (turns) and OpenCode's `run --format json` (cost per step) logs, and stops when either can't start. The Claude Code trust check applies only to `claude` commands. A Codex command without `--dangerously-bypass-hook-trust` is refused, because Codex would skip untrusted project hooks.

## 0.9.1 (2026-10-13)

- **`update.sh` brings new settings into `harness.conf`.** The file is project-owned, so update never rewrote it, and every new setting meant copying lines from the template by hand. Update now appends any setting the template has and the project's file lacks, **commented out** and with the template's explanation, and reports it as `migrate`. Nothing changes until you uncomment a line; a key you commented out yourself counts as present and isn't added again. User-only settings still need a commit as the user once you uncomment them.

## 0.9.0 (2026-10-13)

- **Knowledge source for grilling (autonomous mode).** When `backbone/` doesn't answer a griller question, the analyst and architect search a read-only notes vault behind an MCP server registered as `knowledge` (for example the second-brain vault). A clear answer becomes an assumption citing `vault:<path>`; a question that is silent, vague, contradicted, or already in the vault's open-questions register is escalated as before. A blocker may be settled from the vault only by an accepted decision record. Nothing is written to the vault.
  - New user-only settings: `HARNESS_KNOWLEDGE_ROOT` (the vault folder; empty = off), `HARNESS_KNOWLEDGE_PATHS` (folders agents may read and cite) and `HARNESS_KNOWLEDGE_TOOLS` (the read-only tool names).
    `backbone/harness.conf` is project-owned, so `update.sh` doesn't add them: existing projects copy the block from the template, and commit it as the user (`HARNESS_VERIFY=off`).
  - The hooks refuse the server's write tools, any knowledge tool while the source is off, and reads outside the allowed folders.
  - `approve` refuses an assumption without a `(source: ...)`, and a `vault:` citation that isn't an existing note in the allowed folders.
  - The griller re-reads every cited source and raises the question again when the note doesn't back the assumption.
  - `.claude/settings.json` gains a `PreToolUse` hook for `mcp__knowledge__.*` and allows `mcp__knowledge` for unattended sessions (the hook keeps it read-only). Doctor warns when the source is on but no `knowledge` server is registered; `report` counts lookups.
- **Stricter `approve`:** every assumption needs a source, with or without a knowledge source.
- **Live runs against the second-brain vault** (2 tasks, with read access limited to the engineering folders):
  - First run: one lookup only. The analyst picked "fixed delay, no jitter" as its own choice, while the vault's reliability note says exponential backoff with jitter. So the analyst and architect now check the vault before any default or design choice of their own, and the griller searches it against such choices.
  - Second run: 12 lookups, including the open-questions register. Exponential backoff was settled from `vault:25-Reliability/rel-Reliability-Failover.md`. The numbers the vault doesn't give (base wait, factor, cap) were escalated with proposed values, and the griller flagged dropping the jitter the note asks for.
  - The hook points agents at Read when they ask the knowledge server for a project file, and at the plain path when they pass a `vault:` citation as a path.

## 0.8.3 (2026-10-13)

- **Fewer false escalations in autonomous mode:** the policy approval no longer reads the spec's Skills section. In the first sandbox run, the architect explained why `security` wasn't needed ("no auth, secret or personal data is handled"), and the keyword check escalated a slug-length task as touching auth, secrets and personal data. Requirements, acceptance criteria, architecture and the diff's sensitive paths are still checked.
  - The analyst and architect are told not to name risks to rule them out, since a negated mention still matches elsewhere in the spec.
- **Sandbox: first real task.** After the fix, the runner took a task from spec to a judged commit inside the sandbox in under 2 minutes with a `CLAUDE_CODE_OAUTH_TOKEN`. The agent passed git and the harness hooks through the firewall, and `verify --range` passes on its commit.
  - Git inside the container needs a user name and email. VS Code copies your `~/.gitconfig` into a dev container; with other tools, set them in the workspace.

## 0.8.2 (2026-10-13)

- **Sandbox built and checked for the first time** (OrbStack, Docker 29). The outbound allowlist works: the Anthropic API and GitHub are reachable, everything else is dropped. The hooks block inside the container, and the self-test passes there.
  - **Bug fixed:** the `~/.claude` volume was created owned by root, so Claude Code couldn't write its sessions or settings. The image now creates the folder for the `agent` user before the volume mounts on it.
  - No agent task has run inside the sandbox yet.
- **Subscription credentials:** the sandbox and the `harness-judge.yml` template accept `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) as well as `ANTHROPIC_API_KEY`, so unattended runs and the CI judge can use a Claude subscription instead of per-token billing.
  - `harness-judge.yml` is project-owned: existing projects add the `CLAUDE_CODE_OAUTH_TOKEN` and `HAS_AUTH` lines themselves.
- **Runner:** an agent session that fails at no cost with an error (not logged in, bad API key) stops the run. Before, each task was retried and then escalated with a misleading "no resolution" note. With `--worktree`, the task's branch is removed so the next run retries it.
- **Self-test in CI** on Ubuntu and macOS. The test API stubs no longer resolve their host name on start, which hung on macOS.

## 0.8.1 (2026-10-11)

- **CI workflow templates use current action versions:** `actions/checkout@v7` and `actions/setup-node@v7`, instead of v4, which GitHub runs on a deprecated Node 20 and warns about.
  - `harness-verify.yml` is harness-owned, so `update.sh` replaces it.
  - `harness-judge.yml` is a project-owned template, so existing projects change its two `@v4` lines themselves.

## 0.8.0 (2026-10-09)

Hardening from the first live unattended run, and the last trust gaps in autonomous mode.

- **Found in the live run (1 task, about 85 minutes, ended BLOCKED with no code):** in a folder Claude Code hasn't trusted, `claude -p` ignores the project's hooks, agent hooks and permissions, so the griller's verdict recorder never ran. The agent correctly escalated rather than forge a verdict.
  - `harness.py run` and `ci-judge` now refuse an untrusted workspace, and doctor warns in autonomous mode.
  - The sandbox and the CI judge trust their own workspace.
- **Bug fixed:** `escalate` (and every task-line parser) could match the example task line inside the HTML comment in `3-TASKS.md`. With the usual first task id `1.1`, the BLOCKED note landed on the comment and the real task stayed runnable.
- **Independent CI judge:** `harness.py ci-judge --range` re-judges tasks a pull request finishes with a fresh session (`HARNESS_CI_JUDGE_CMD`), re-runs the tests, and applies the re-derivation rules. There's a project-owned workflow template, `harness-judge.yml`.
- **`harness.py ci-protect`:** requires the `verify` check (and optionally `judge`) on a branch, and creates the `harness-change-approved` label.
- **Assumptions:** the spec template has an Assumptions section. In autonomous mode `approve` refuses a spec whose griller asked questions while Assumptions is empty. The analyst records settled answers with their source and keeps specs proportionate.
- **Out-of-band changes** (autonomous): a snapshot of the protected files is compared after each shell command. Changes made outside the file tools (for example by a script) are logged and the `[WIP]` task is escalated. Restores to the committed version are fine.
- **Runner:**
  - `--worktree [--pr]` runs each task on its own branch, optionally opening a pull request, and `--only <id>` runs one task.
  - `HARNESS_RUN_MAX_COST` sets a per-run budget, using cost and turns from `--output-format json` (now the default `HARNESS_AGENT_CMD`).
- **Sandbox template** `.devcontainer/harness-agent/`: outbound allowlist, trusted workspace, unattended agent command. Untested on this release.
- **Doctor** flags skills not verified within `HARNESS_SKILL_MAX_AGE` days (default 180), or with no `last-verified` date.
- **`harness.py report --json`**, plus agent cost and out-of-band change counts in the report.
- **No `__pycache__`** written into projects.
- **Reading `core.hooksPath` is allowed;** only setting or unsetting it is refused. This false positive was found by a live probe, which also confirmed that in a trusted folder both the project hooks and the agent (frontmatter) hooks load under `claude -p`.
- **Hooks fail closed on time.** A hook Claude Code kills for running too long lets the tool call through. Gate hooks now have their own 25-second budget (settings and agent hook timeouts are raised to 30 seconds), `git` calls time out inside hooks, and a gate that runs out of time refuses the call.
- **Second live run, in a trusted folder: success end to end.** One task went spec → griller (2 passes, 8 minor questions settled as Assumptions) → policy approval → implementer → judge (pass on round 1; tests re-run by the harness) → scribe → `[x]` and committed. That took 21 turns and $6.39. Wall time was 4.8 hours for about 20 minutes of work, because the idle Mac slept; HOOKS.md now recommends `caffeinate -i`.
- **Self-test:** 490 checks.

## 0.7.0 (2026-10-09)

Unattended runs, with CI as the authority.

- **`harness.py run`** (autonomous mode, user or scheduler only): for each ready task (a `[WIP]` one first, BLOCKED ones skipped), it starts a fresh session with `HARNESS_AGENT_CMD` (prompt on stdin).
  - Budgets: `HARNESS_RUN_TASK_TIMEOUT` per session and `HARNESS_RUN_ATTEMPTS` per task.
  - The outcome is read from `3-TASKS.md`: done when `[x]` and committed, otherwise retried and then escalated as `runner`.
  - It honours the kill switch between sessions and keeps a log per session. Agents can't start it.
- **CI workflow** `.github/workflows/harness-verify.yml` (harness-owned): runs `verify --range` on every pull request with the base branch's `scripts/harness/lib` (new `HARNESS_ROOT`), so a pull request can't change its own verifier. In a range, harness changes and user-only setting changes need the `harness-change-approved` label.
- **The lock is protected:** agents can no longer edit `backbone/.harness-lock.json`. Before, the main session could rewrite it to match a modified harness file.
- **Event log** `.git/harness/events.jsonl` (blocks, verify refusals, verdicts, approvals, escalations, run attempts), summarised by `harness.py report`.
- **Self-test:** 441 checks.

## 0.6.0 (2026-10-09)

Autonomous mode: the harness runs without a human in the loop, and the human-only decisions become policy or escalations.

- **`HARNESS_AUTONOMY`** (`supervised` default, or `autonomous`; user-only). AGENTS.md section 7 replaces every "ask the user", and session start announces the mode.
- **Policy approval:** `harness.py approve <id>` writes `Approved-by: policy:low-risk (...; base <commit>; ...)` for a valid, grilled spec only when it is low-risk.
  - **Risk** is deterministic: `HARNESS_RISK_TERMS` in the spec, `HARNESS_RISK_PATHS` it names, or a referenced ADR that isn't Accepted.
  - When the task finishes, the judge gate re-assesses the diff since the base commit: sensitive paths, or more than `HARNESS_RISK_MAX_FILES` files.
  - `harness.py risk <id>` shows the assessment. `HARNESS_AUTO_APPROVE` (`low`/`off`).
- **Escalation:** `harness.py escalate <id> --reason ...` parks a task (`BLOCKED:` note, out of `[WIP]`) and appends to `backbone/escalations.md`, optionally opening a GitHub issue (`HARNESS_ESCALATE_GH`).
  - BLOCKED tasks can't start, and agents can't clear the note or edit the file.
  - The griller's and judge's recorders escalate automatically after `HARNESS_GRILL_MAX_ROUNDS` / `HARNESS_JUDGE_MAX_ROUNDS` fails.
  - `harness.py escalations` lists open entries.
- **Kill switch:** `.git/harness/STOP` refuses every tool call and lets the session end.
- **Stop hook** acts as `block` in autonomous mode.
- **Doctor:** errors on autonomous mode without `HARNESS_TEST_CMD`, or with verify or a gate off.
- **Self-test:** 419 checks.

## 0.5.0 (2026-10-09)

The gates hold no matter how a change is made. A probe of 0.4.2 found that every file-level gate could be bypassed through the shell (`sed -i` on `3-TASKS.md`, `echo Approved-by: >> spec`, a Python one-liner writing a verdict), that `git commit -n` and `core.hooksPath` switched off the git hooks, and that a task marked `[x]` with no spec, grill or judge verdict could be committed.

- **`harness.py verify`:** re-checks the gates on the resulting state, not on the edit.
  - It runs in pre-commit on the staged change, and in CI with `verify --range <base>..HEAD`.
  - It checks that new `[WIP]`/`[x]` tasks passed the start gate, and that finished tasks have a judge pass matching the committed code.
  - It also checks that verdict history is append-only, user-only settings are unchanged, harness enforcement files match the lock, and settings still run the hooks.
  - `HARNESS_VERIFY` (`block`/`off`, user-only) controls it; the user commits a deliberate exception with `HARNESS_VERIFY=off`.
  - `HOOKS.md` has a GitHub Actions example.
- **Shell checks:** commands are split into segments and tokenized instead of matched as raw text.
  - Shell writes to `backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`, `.git/hooks`, `.git/harness` and `.git/config` are refused. This covers redirections, `rm`/`mv`/`cp`/`tee`, `sed -i`, `git rm`, and interpreter one-liners and heredocs; `cd`, `bash -c` and `eval` are followed.
  - Also refused: `git commit -n`, `core.hooksPath` changes, `HARNESS_*=`/`SKIP_BUILD=` from the shell, `+<ref>`/`--mirror`/delete pushes, `find / -delete`, `DELETE` without `WHERE`, and `curl | sh`.
  - `@bash` rules no longer match commit messages or data heredocs, so `git commit -m "docs: why we never drop table"` is allowed.
- **The judge's tests are run by the harness:** on a claimed pass the recorder runs `HARNESS_TEST_CMD` (`HARNESS_TEST_TIMEOUT`, default 900 s) and records `test_run` (exit code, duration, output hash and tail) in the verdict. A failure or timeout turns the pass into a fail, and test evidence in the judge's JSON is ignored. The judge's hook timeout is 1200 s.
- **Recorded passes are re-derived** from their stored evidence by the gates, so a hand-written `{"verdict": "pass"}` does not count.
- **ADR acceptance is the user's:** agents can't set an ADR to `Accepted`, and an accepted ADR is frozen except for being superseded.
- **Orchestrator scope** (`HARNESS_ORCHESTRATOR_SCOPE`, user-only, default `on`): the main session (no `agent_id`) may edit only `backbone/` docs and configuration, `.claude/skills/` and `CLAUDE.md`. Specs, ADRs and code go through the role agents.
- **`SKIP_BUILD=1` is user-only**, like the other escape hatches.
- **Self-test:** 389 checks, up from 314.

## 0.4.2 (2026-10-05)

- **java pack:** test paths now include `src/intTest` (Gradle's common name for an integration-test source set), for the JUnit-assertion rules, the `java-test` route and the `gradle` option's `HARNESS_TEST_PATHS`. The gap was found by the griller in the first live trial.

## 0.4.1 (2026-10-05)

- **Decision layer: `ollama` provider** for a local Jev-style decision endpoint (Ollama's `/v1/systemone`, default model `nimble`).
  - Data stays on the machine and calls are free.
  - `HARNESS_DECISION_URL` overrides the endpoint, and is user-only like the other decision settings.
- **Decision thresholds:** a choice's `warn_if` can use `min_probability`, the probability of the chosen option, besides `min_confidence`. Local Jev-style models report a low confidence even for likely answers.
- **The `claude` provider uses plain HTTPS** (standard library), so there's no SDK to install.

## 0.4.0 (2026-10-05)

The stack is decided in design, not at install; the reviewed skill library from agentic-backbone.

- **Stack-neutral install:** nothing language- or tool-specific is installed or assumed.
  - First-run setup records the stack in an ADR.
  - A **catalog** of stack packs ships inert in `scripts/harness/catalog/`.
  - `harness.py catalog` lists the packs. `harness.py adopt <pack> --adr ADR-NNN --with ... --without ...` adopts them only from an **Accepted** ADR that names them, and only with every pack option decided.
  - Adopted rules and routes are written into the project's `guardrails.conf` and `routing.conf` as blocks citing the ADR, and options set `harness.conf` values.
  - `adopt --remove` undoes an adoption. Updates refresh adopted packs' files. Doctor warns when a pack's ADR is no longer Accepted.
- **Catalog packs** were rewritten against the review findings (Java 25 API fixes, no Spring/Lombok/JPA in examples), with every tool choice made conditional on an option:

  | Pack | Skills | Options |
  |---|---|---|
  | `java` | `java`, `java-review`, plus `java-test` via the `junit5-assertj` option | `gradle`/`maven`, `no-lombok` |
  | `quarkus` | `quarkus`, `quarkus-cdi`, `native-test.sh` | `no-spring`, `hexagonal-layers`, `named-use-cases` |
  | `jdbi` | `jdbi` | `no-orm`, `hexagonal-layers`, `flyway` |
  | `container` | `containers`, `container-security` | `podman`/`docker` |

  The rules ported from agentic-backbone's `validate-quarkus.sh` are now pack options.
- **New core skills:**
  - `code-quality`, routed to all source files;
  - `module-testing`, routed to tests, with acceptance-criterion traceability;
  - `security`, covering the OWASP Top 10:2025 and NIST SP 800-63B rev. 4;
  - `changelog`, used on demand.
- **Merged into existing core skills:** `architecture` gains `review.md` (with the driving/driven port labels fixed) and `api-design` gains `compatibility.md` (Deprecation/Sunset headers). Every skill now has a **Linked skills** section.
- **`harness.py scan`:** checks the full content of existing files against the rules (drift). It is reported at session start and by `doctor.sh`.
- **Warning rules for shell commands,** reported after the command runs.
- **commit-msg** warns when the scope matches no staged path.
- **Stop hook** nudges to commit when no task is `[WIP]` and many files have changed.
- **`8-WORKFLOW`** gains commit scope and BREAKING CHANGE rules. The judge loads `code-quality`, `module-testing`, `security` and adopted `*-review` skills.
- **Self-test** enforces the skill format contract: frontmatter first, SKILL.md at most 220 lines, linked skills that exist, and no secret-like literals.

## 0.3.0 (2026-10-04)

The define, build, judge and record pipeline.

- **Specs:** one per task in `backbone/specs/<id>.md` (template `backbone/templates/spec.md`).
  - Numbered requirements `REQ-<id>-<n>` and Given/When/Then acceptance criteria `AC-<id>-<n>`, each linked to its requirements.
  - NFRs, an Architecture section with the governing ADRs (at least one required), Skills, Out of scope, Open questions, and Approval.
  - `harness.py spec-check <id>` reports readiness.
- **ADRs** are files in `backbone/adr/` (template `backbone/templates/adr.md`), and `5-DECISIONS.md` is now their index. The seed includes `ADR-001`.
- **Agents:** `analyst` (spec), `architect` (ADRs, tech requirements, skills), `griller` (adversarial spec review), `implementer` (code and tests), `judge`, `scribe`. Analyst, architect, implementer and scribe each have a hook-enforced write scope. `planner` is removed.
- **Start gate:** a task becomes `[WIP]` only with a valid spec, a griller pass on the current spec and ADRs (spec and ADR fingerprint), and the user's `Approved-by:` line. Agents can't write approval lines, and approved specs are frozen.
- **Skill gate:** before editing a file, an agent must have loaded (read or invoked) every skill routed to its path in `scripts/harness/routing.core.conf` and `backbone/routing.conf`. For code during a task, it also needs the skills the spec lists. This is tracked per session in `.git/harness/sessions/`.
- **Judge gate** now judges against the spec. Every AC must be evaluated as met, list its tests, and be mentioned in a test file (`HARNESS_TEST_PATHS`). Tests must be reported `passed`.
- **Harness skills** in `.claude/skills/`: `requirements-writing`, `adr-writing`, `architecture`, `api-design`, `openapi`.
- **New user-only settings:** `HARNESS_SPEC_GATE`, `HARNESS_SKILL_GATE`; plus `HARNESS_TEST_PATHS`.
- The task format is now one line per task, `- [ ] **Task <id>: <title>** (spec: ...)`. The steps and "Done when" lists move into the spec.
- **Upgrade notes from 0.2.0:**
  - Verdict files are now named `<id>.judge.json` and `<id>.grill.json`. Old `<id>.json` files are ignored.
  - A task already `[WIP]` keeps going, but finishing it needs a spec with acceptance criteria and a judge pass. Otherwise the user finishes it or switches `HARNESS_JUDGE_GATE` off.
  - Add `HARNESS_SPEC_GATE` and `HARNESS_SKILL_GATE` to `harness.conf` to make them explicit; both default to on.
  - `routing.conf` and `adr/ADR-001` are created by the update.

## 0.2.0 (2026-10-04)

Agent roles and the judge gate.

- New harness-owned agents in `.claude/agents/`:
  - `planner`: read-only; drafts tasks with "Done when" criteria.
  - `judge`: independent review that returns a structured verdict.
  - `scribe`: writes decisions and memory; a scoped hook limits it to `5-DECISIONS.md` and `6-MEMORY.md`.
- Judge gate: finishing a `[WIP]` task requires a current pass verdict.
  - The judge's scoped Stop/SubagentStop hook records each verdict in `backbone/.verdicts/<task>.json`, with a fingerprint of the code (git tree hash excluding `backbone/`).
  - A claimed pass is recorded as a fail if the judge's own evidence shows an unmet criterion, a blocker or major finding, or failed tests.
  - Rewording or deleting a task line counts as finishing it; reverting to `- [ ]` abandons it.
  - After `HARNESS_JUDGE_MAX_ROUNDS` fails, the agent is told to escalate to the user.
  - Agents can't write verdicts or change `HARNESS_JUDGE_*`.
- New task format: tasks are list lines (`- [ ] **Task <id>: ...**`) with nested "Done when" and steps. `[WIP]` goes on task lines only.
- `doctor.sh` checks the judge configuration.
- **Upgrade note:** the gate is on by default for updated projects too. Existing tasks need "Done when" criteria before the judge can pass them. To finish old tasks without review, set `HARNESS_JUDGE_GATE="off"` in `backbone/harness.conf` yourself.

## 0.1.0 (2026-10-04)

First release. Extracted from `agentic-backbone` as a stack-agnostic core.

- `bootstrap.sh` / `update.sh`: install into any repo root, with hash-tracked updates, conflict files, `--dry-run`, `--force`, and `status`.
- Settings merge: only harness hook entries are replaced; custom hooks, permissions and other settings are kept.
- Git hooks via `core.hooksPath`, so they work in worktrees and nothing is copied into `.git/hooks`.
- A single Python runtime for all hooks, using the output formats Claude Code reads:
  - Blocks go through exit 2 with the reason on stderr.
  - Feedback goes through `additionalContext`.
  - The Stop hook uses `systemMessage`, or `decision: block` guarded by `stop_hook_active`.
- Guardrail rules in a data file (`guardrails.conf`), with core rules for destructive commands and secrets.
- The WIP check matches task lines only. A second `[WIP]` task is refused at edit time.
- Session start reports unfinished setup (FILL placeholders), the open WIP task and harness errors in a few lines.
- `doctor.sh` health check.
