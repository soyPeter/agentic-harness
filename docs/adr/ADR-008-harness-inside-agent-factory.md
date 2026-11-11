# ADR-008: The harness as the gate inside the agent software factory

## Status
Proposed

## Date
2026-11-11

## Context
The maintainer has designed an **agent software factory**: an always-on service on a Hetzner box (`claude-box`)
where agents pull work, open pull requests and report, and a person reviews. It was built on 2026-11-11 and installed
switched off. It has never run with a real model or with real Slack, Linear or GitHub. Its code is not in this
repository. This ADR does not describe its internals; where a decision depends on them, it says "assumed".

The design, from its diagram:

- **Doors**: a Slack mention (reports land in the channel), GitHub (a review of the factory's PR, or a comment naming
  it) and Linear (an issue delegated to it, or labelled eligible).
- **Inbox**: every event is sender-checked, de-duplicated and queued. A **clock** adds an hourly janitor and scheduled
  QA (the QA sweep is not built: it needs a preview stack).
- **The loop a worker runs**: 1 Pick (takes an issue as its delegate), 2 Build (a fix in a sandbox; a daemon
  re-checks), 3 Challenge (Fable always, Mythos on risky diffs), 4 Open PR (evidence in, the user as reviewer),
  5 You review (tag the agent for changes, back to Build), 6 Close out (keep lessons, queue a KB note, report).
- **Crew**, one shared identity, one session per task: Worker (Opus, one per project, from pick to PR), QA (not
  built), Challenger (Fable, attacks every diff before the PR), Security (Mythos, risky diffs: public surfaces,
  external calls, databases, new systems).
- **Memory**: a task ledger, a project KB (Markdown in git, per project, changed by reviewed PR) and project notes
  (lessons shown to the next worker).
- **Foundations**: its own identity and tokens (none set yet); trusted senders (only named people give orders, other
  text is data); spend caps ($25 a task, $100 a day, booked before each call); a sandbox (agent code runs without
  secrets or open ports); log and stop (every outward action audited, one stop switch); a risk flag (rules flag a diff,
  Fable can escalate, only the user downgrades); the user keeps merge, deploy, spend and infrastructure.
- **Runtime**: a listener (no open ports; polls Slack, Linear and GitHub every 30 s), a dispatcher (plain code: checks
  the sender, drops repeats, routes), a runner (one session per task, resumed on review; a fixed number of lanes), a
  lane (the whole session boxed from outside; pushes only from a trusted clone), a key proxy (holds the real keys,
  enforces the caps; lanes get stand-ins), a watchdog (heartbeat to systemd; disk and memory alerts to Slack), a
  janitor (frees lanes and branches a week after a task settles) and a preview stack (not built).
- **When an agent stops and asks**: it needs a ruling (behaviour nobody has decided), it is blocked (missing access,
  repeated failed attempts), a cap is hit, or the work is off limits (production, infrastructure, secrets,
  security-labelled issues).

Most of the worker loop exists in the harness today. Paths below are in this repository; `harness.py` is
`payload/owned/scripts/harness/lib/harness.py`.

| Factory need | The harness today | Where |
|---|---|---|
| Task ledger | `backbone/3-TASKS.md` (task lines, `[WIP]`, `[x]`, `BLOCKED` notes), `backbone/specs/`, `backbone/.verdicts/`, `backbone/escalations.md`; read with `harness.py state --json` and `next <id> --json` | `harness.py` (`state_command`, `next_command`, `next_step`); `payload/owned/backbone/HOOKS.md` "Coordinator API" |
| Pick | `harness.py run [--only <id>] [--worktree [--pr]]` drives ready tasks, one fresh agent session per attempt; `harness.py orca` drives them with Orca workers | `harness.py` (`run_command`, `run_worktrees`); `payload/owned/scripts/harness/lib/coordinator.py` |
| Intake | `harness.py linear import <ISSUE> --task <id> [--from <issue.json>]` writes a draft spec quoting the ticket as source material, not instructions; `linear receipt` posts the receipt. User-only; agents may run `--dry-run` only | `harness.py` (`linear_command`, `linear_import`); `payload/owned/scripts/harness/lib/linear.py`; HOOKS.md "Change receipt" (Linear) |
| Build in a sandbox | implementer (and tester when on), under the skill gate and write scopes; `.devcontainer/harness-agent/` with an egress allowlist, full installs only; sandbox evidence on each judge verdict | `payload/owned/.claude/agents/`; `harness.py` (`AGENT_SCOPES`); `payload/owned/.devcontainer/harness-agent/`; `payload/owned/scripts/harness/lib/sandbox.py`; [ADR-003](ADR-003-sandbox-backends.md) |
| "Daemon re-checks" | the judge recorder re-runs `HARNESS_TEST_CMD` and re-derives the verdict; `verify` at pre-commit; `harness-verify` in CI with the base branch's verifier | `harness.py` (`record_verdict`, `verify_command`); `payload/owned/.github/workflows/harness-verify.yml` |
| Challenge | griller (spec), judge, debugger, three reviewer lenses (`correctness`, `structure`, `lean`) | `payload/owned/.claude/agents/`; `harness.py` (`REVIEW_LENSES`) |
| Model per role | `harness.py orca --agents default=claude,judge=codex` or `HARNESS_ORCA_AGENTS`, with launch commands in `HARNESS_ORCA_LAUNCH`, both user-only. `run` has one `HARNESS_AGENT_CMD`; the role agents declare `model: inherit` (the scribe `haiku`). Verdicts don't record the model | `coordinator.py` (`agent_for`, `start_worker`); `payload/owned/.claude/agents/*.md` |
| Open PR | the deliverer pushes, opens or updates the PR with the receipt, applies the receipt's `risk:*` and `class:*` labels (risk only goes up), watches CI, never merges; its gh and git calls go through an allowlist | HOOKS.md "Deliverer"; `harness.py` (`record_delivery`, `suggested_labels`) |
| Evidence | `harness.py receipt <id> --json`; `trace export` ([ADR-004](ADR-004-traceability-export.md)); signed verdict attestations ([ADR-005](ADR-005-verdict-attestations.md)) | `harness.py` (`receipt_data`, `attest_command`); `payload/owned/scripts/harness/lib/traceability.py` |
| Risk flag | Change-Class and `risk_reasons` from `HARNESS_RISK_TERMS`, `HARNESS_RISK_PATHS`, `HARNESS_RISK_MAX_FILES` (user-only); an approved spec is frozen | [ADR-002](ADR-002-change-class-ladder.md); `harness.py` (`risk_reasons`, `change_class`, `USER_ONLY_KEYS`) |
| Close out | the scribe writes `backbone/6-MEMORY.md`, emergent ADRs (Proposed) and `backbone/proposals/`; a failure class escalated twice opens a proposal | `harness.py` (`AGENT_SCOPES`, `propose`); `payload/owned/.claude/agents/scribe.md` |
| Project KB | a read-only knowledge source (`HARNESS_KNOWLEDGE_ROOT`, `_TOOLS`, `_PATHS`): write tools refused, citations checked | HOOKS.md "Knowledge source" |
| Stops and asks | `harness.py escalate` parks a task as `BLOCKED` with a kind and a failure class; kinds in use: `approval`, `decision`, `runner`, `coordinator`, `integration`, `out-of-band change`, `<agent> failed N times` | `harness.py` (`escalate`, `FAILURE_CLASSES`); `coordinator.py` |
| Log and stop | `.git/harness/events.jsonl`, `trace <id> --json`, `report --json`; the kill switch `.git/harness/STOP` refuses every tool call and stops `run` between sessions | `harness.py` (`log_event`, `halt_file`, `hook_pre_tool_use`) |
| Spend | `HARNESS_RUN_MAX_COST` (dollars per `run`, checked before the next task, from each session's `total_cost_usd`); `run-attempt` events carry `cost_usd` | `harness.py` (`run_command`, `session_usage`) |
| Protected state | shell writes to `backbone/`, `scripts/harness/`, `.claude/`, `.git/harness/` and others refused; enforcement files checked against the lock; user-only settings | `harness.py` (`SHELL_PROTECTED`, `ENFORCEMENT_FILES`, `USER_ONLY_KEYS`) |
| Only a human merges | the deliverer never merges; the `triple` profile refuses `gh pr merge`, merge APIs and merge tools for every agent, and `orca --merge` | [ADR-002](ADR-002-change-class-ladder.md); `harness.py` (`NO_MERGE_PROFILES`, `no_merge_refusal`) |
| Scheduling | `orca-nightly`, an Orca automation precheck (defaults to `orca --merge --trust`); `.github/workflows/nightly.yml` is this repository's own self-test, not a project scheduler | `harness.py` (`orca_nightly_command`); `.github/workflows/nightly.yml` |
| Engine version | thin mode: the project pins a release in `backbone/.harness-lock.json`; the launcher runs it and refuses everything but reads when it can't | [ADR-001](ADR-001-thin-mode-plugin.md); `plugin/launcher.py` |

What the factory needs and the harness lacks:

- No provenance on a task: nothing records who asked, through which door, or whether the sender is trusted.
- Spend is limited per `run` and only between tasks, after the cost is known. There is no per-task cap that survives
  resumes, no per-day cap, and nothing booked before a call.
- No security reviewer that risk switches on.
- Review comments on a pull request don't come back into the task. Red CI does (`delivery-failed`, HOOKS.md
  "Deliverer").
- No place for a KB note distinct from `6-MEMORY.md`.
- Nothing tells a janitor when a worktree or branch is safe to delete.
- Model routing per role exists in `orca` only, and no verdict says which model produced it.
- The deliverer pushes from inside the agent's session, so it needs a GitHub credential there. The factory keeps
  credentials out of lanes and pushes from a trusted clone.

## Decision
The harness is the gate inside each lane of the factory. The factory brings work in, runs lanes and talks to the
outside world; the harness decides whether the work in a lane is good enough and records why. They meet at a small,
versioned contract of harness commands.

### 1. Who owns what

| Concern | Owner |
|---|---|
| Doors, listener, inbox, de-duplication, dispatch, routing to a project | factory |
| The trusted-sender list and the sender check | factory (the harness records the verdict, section 2) |
| Identity and tokens (GitHub, Linear, Slack, model keys), the key proxy, spend enforcement | factory |
| Lanes: isolation, the trusted clone, worktree and branch creation, pushes and PR calls | factory |
| Runner (lane count, session start, resume), watchdog, janitor, clock, Slack reports, the factory audit log | factory |
| Spec, Change-Class, grill, approval rules, skill and judge gates, review lenses, verdicts, receipts | harness |
| What may be delivered and how (PR body, labels, never merge), escalations, failure classes | harness |
| Memory writes (`6-MEMORY.md`, proposals, KB note drafts) and the task ledger in `backbone/` | harness |

- **The harness is the system of record for task state in each project**: `backbone/3-TASKS.md`, the spec, the
  verdicts and `escalations.md`, committed with the work and read through `next` and `state`. The factory's task
  ledger is an index keyed by (repository, task id, intake id), refreshed from those answers. When they disagree, the
  harness's answer wins. The factory never edits `backbone/`.
- **Each lane runs the harness in thin mode** (ADR-001), at the release the project pins. The factory never chooses
  or moves a pin: `launcher.py pin` stays the user's command, reviewed as a pull request. The engine cache is
  read-only inside a lane. A project with a full install runs its own copy; the launcher already defers to it.
- **One lane drives one task**, in its own worktree on `harness/task-<id>` (the branch name `run --worktree` uses), so
  the one-`[WIP]` rule holds per worktree. The lane drives it with the harness's runner, `harness.py run --only <id>`,
  and so inherits its attempts, timeouts, kill-switch checks and escalations; the factory doesn't re-implement the
  workflow. One `run` invocation is the factory's "session".
- **A project joins the factory by the user's own settings**, all user-only: thin pin; `HARNESS_AUTONOMY="autonomous"`;
  `HARNESS_AGENT_CMD` set to the lane's agent command; `HARNESS_REVIEW` on; `HARNESS_DELIVER` on (`external` once
  follow-up 4 ships); a no-merge profile
  (follow-up 10); `harness-verify` required on the default branch (`harness.py ci-protect`). `run` already refuses to
  start while `doctor` reports an error.

### 2. The contract

The contract is the commands, flags, JSON fields and event kinds named below. It is **version 1**. Within a version,
fields are only added; removing a field or changing its meaning is a new version. The harness will state the
versions it serves (`harness.py contract --json`, proposed, follow-up 1), and the factory refuses a lane whose pinned
engine doesn't serve its version. Until that command exists, the factory's adapter lists the engine releases it was
tested with (assumed).

**Hand a task in.** In the lane's worktree, before `run`:

- Linear, today: the factory fetches the issue with its own token and runs `harness.py linear import <ISSUE> --task
  <id> --from <issue.json>`, so no Linear token enters the lane.
- Every door, proposed (follow-up 2): `harness.py intake <request.json> [--json]`, with `contract`, `source`
  (`slack`, `github`, `linear`, `clock`), `channel`, `message_id` and `url`, `sender`, `sender_verdict` (`trusted` or
  `untrusted`, from the factory's check), `received_at`, `dedupe_key` and `text`. It writes the draft spec with a
  frozen `## Source` section holding the provenance, quotes `text` as source material (as `linear import` does),
  adds the task line and logs an `intake` event. It allocates the task id under a lock in the shared git directory,
  as `adr_next` does for ADR numbers, and returns it. The same `dedupe_key` returns the existing task and writes
  nothing. An `untrusted` request is recorded and escalated (kind `intake`); nothing builds until a person approves
  the spec. `linear import` gains the same provenance.

**Drive it.** `harness.py run --only <id>` in the worktree. Its exit code is not the outcome; the factory reads the
outcome from `next`.

**Read progress and outcome**, all existing:

| Command | What the factory uses |
|---|---|
| `harness.py next <id> --json` | `step` (`define`, `grill`, `answer`, `approve`, `start`, `test`, `implement`, `judge`, `diagnose`, `fix`, `review`, `finish`, `deliver`, `delivery-failed`, `blocked`, `done`), `role`, `progress` (unchanged means the last session did nothing), `change_class`, `escalations`, `pr`, `findings` |
| `harness.py state --json` | every task's state and verdicts, `autonomous`, `halted` |
| `harness.py receipt <id> --json` | the PR body's evidence: `changed`, `verified`, `not_verified`, `change_class`, `risks`, `sandbox`, `approval_needed`, `suggested_labels` |
| `harness.py escalations` | open escalations, by class. Text today; `--json` with `kind`, `class`, `reason`, `needed` is proposed (follow-up 1) |
| `harness.py trace <id> --json`, `report --json` | the task's history and cost, for the report and the audit log |

The four ways an agent "stops and asks" map onto escalations:

| Factory stop | Harness escalation |
|---|---|
| Needs a ruling | kinds `approval` (a `feature` or `schema` spec, or risk found), `decision`, griller failures; classes `contradictory_req`, `missing_context` |
| Blocked | kinds `runner`, `coordinator`, `integration`, judge failures; classes `tool_timeout`, `unchanged_repeat`, `permission_denied`, `failed_test`. An agent that can't start (`run-agent-failed`) is a lane problem, not the task's |
| Cap hit | `run-budget` event per run today; kind `budget` proposed (follow-up 3) |
| Off limits | `approval` with risk reasons for `schema` work and risk paths; `out-of-band change`. Security-labelled issues and production or infrastructure requests are refused by the dispatcher before intake |

A spec that needs a person's approval is approved by that person writing their `Approved-by:` line on the task
branch. A reply in Slack is not an approval, and the factory never writes the line.

**Deliver across the boundary.** The lane holds no GitHub credential, so the deliverer's push and gh calls move to the
factory's trusted clone. The harness still decides what is delivered. Proposed (follow-up 4):

- `HARNESS_DELIVER="external"` (user-only): `run` ends a finished, committed task at `deliver` with outcome
  `ready-to-deliver` instead of starting the deliverer or retrying.
- `harness.py delivery-plan <id> --json`: the branch, base, head commit, PR title and body (with the receipt) and the
  labels, under the deliverer's rules: only `risk:*` and `class:*` labels from the receipt, and a `risk:*` label that
  only goes up. Escalated tasks get a plan for a draft PR naming the escalation.
- The factory fetches the branch into the trusted clone, runs `harness.py verify --range origin/<base>..<head>` with
  the engine the base branch pins, pushes, opens or updates the PR as planned and watches the checks.
- `harness.py delivery-record <id> <report.json>`, refused to agents: records the `deliver` event `next` reads, with
  the checks `record_delivery` applies today (the pushed head equals the task's `HEAD`; `delivered` needs checks
  `passed` or `none`; `hold` and `ci-failed` need findings with owners).

Until follow-up 4 ships, a lane that must push holds a GitHub stand-in that the proxy forwards only to the endpoints
the deliverer's allowlist permits (assumed), and the deliverer runs in the lane as today.

**Stop a lane.** The factory's stop switch creates `.git/harness/STOP` in each project clone: every agent tool call is
refused and `run` stops between sessions. The factory then ends its sessions. A killed session leaves the task `[WIP]`,
and the next `run` resumes it. Removing `STOP` is the user's act; the factory never removes it.

**Cost.** The key proxy is the enforcement point: it books each call's estimated cost against the task's cap ($25)
and the day's ($100) before forwarding it, and refuses past either (assumed). Each lane gets one stand-in key per task,
so the proxy can attribute spend (assumed). The harness, proposed (follow-up 3):

- reads the task's remaining budget from the runner's environment (`HARNESS_TASK_BUDGET_USD`, set by the factory for
  the `run` process, which agents can't change);
- adds each session's cost to a per-task ledger in `.git/harness/` that survives resumes, and puts the total on the
  receipt;
- refuses to start another session once the ledger reaches the budget, and treats the proxy's refusal as a cap hit
  rather than a retryable failure: it escalates with kind `budget` and stops.

`HARNESS_RUN_MAX_COST` stays as the per-run limit for runs outside the factory.

**Events for the factory's audit log.** The factory tails `.git/harness/events.jsonl` read-only and forwards each
event with its lane, project and intake id. Each line is a JSON object with `at`, `kind`, and where known `task`,
`session` and `agent`. Version 1 covers `intake` (proposed), `task-start`, `task-finish`, `verdict`, `review`,
`approval`, `escalation`, `proposal`, `deliver`, `run-start`, `run-attempt` (with `cost_usd`), `run-budget`,
`run-halt`, `run-agent-failed`, `run-end`, `tamper`, `block`, `gate` and `linear-import`. Proposed (follow-up 1): a
`v` field on every event, and an `outward` event for each outward write the harness itself allows (a push, PR create
or edit, label, Linear comment). The factory audits the outward actions it performs itself. `log_event` never fails
its caller, so a missing event is a gap in the audit log, not evidence that nothing happened.

### 3. Roles and steps

| Factory | Harness | Status |
|---|---|---|
| 1 Pick | dispatcher routes to a project; intake in the lane; then DEFINE: analyst spec, architect, griller, approval (policy only for low-risk `docs` and `refactor`; a person for `feature` and `schema`) | intake with provenance proposed |
| 2 Build | implementer (and tester); hooks, skill gate, write scopes; the judge recorder re-runs the tests; `verify` at commit | exists |
| 3 Challenge | judge and the three reviewer lenses on the Challenger's model, debugger on a judge fail; the security lens when risk triggers it | security lens and routing in `run` proposed |
| 4 Open PR | delivery plan from the harness, push and PR by the factory; receipt and labels in the PR; `harness-verify` in CI | split delivery proposed |
| 5 You review | review comments from trusted reviewers become a `fix` step; the next delivery updates the same PR | proposed |
| 6 Close out | the scribe at `finish` (`6-MEMORY.md`, Proposed ADRs, proposals); a KB note draft; the receipt, and `linear receipt` run by the factory with its token | KB note drafts proposed |
| Worker (Opus) | the `run` session (`HARNESS_AGENT_CMD` on Opus) and the analyst, architect, tester, implementer and scribe it delegates to | exists |
| Challenger (Fable) | judge and reviewer lenses; the griller too if the user routes it there | routing in `run` proposed |
| Security (Mythos) | a `security` reviewer lens, added when risk triggers it | proposed |
| QA (not built) | none: the tester's acceptance tests are the closest; browser QA waits for preview stacks | out of scope |

The Pick step gains DEFINE: the factory's loop goes from issue to fix, the harness's from issue to approved spec to
fix. For `feature` and `schema` work that means a person approves the spec before Build, as ADR-002 requires. The
light lane (`HARNESS_LIGHT_LANE`, the user's switch) keeps small fixes short.

**Model routing the harness must support** (follow-ups 5 and 6), user-only, in both `run` and `orca`:

- **Role to model**: for example `implementer=opus judge=fable reviewer=fable griller=fable security=mythos`. `orca`
  has this through `HARNESS_ORCA_AGENTS` and `HARNESS_ORCA_LAUNCH` (untested with model flags); `run` needs it.
- **Risk to extra reviewer**: `next` adds the `security` lens to `lenses` when the spec's class is `schema`,
  `risk_reasons` is not empty, or the diff touches the paths in a new user-only `HARNESS_SECURITY_PATHS` (public
  surfaces, external calls, database, new systems). The judge gate then requires its pass, like the other lenses. A
  reviewer may raise risk (a finding that asks for the security lens adds it and raises the label); nothing in a lane
  lowers it. Lowering stays with the user: the class is in the approved, frozen spec and the risk settings are
  user-only, as today.
- **Evidence**: every grill, judge and review verdict records the agent and model that produced it, and the receipt
  shows them, so "Fable challenged this diff" is a fact on the PR, not a setting.

### 4. What stays out of the harness
- **Listeners for Slack, GitHub and Linear, the inbox and the dispatcher.** They are long-running, network-facing and
  hold tokens. The harness is a per-project engine that runs per call, with the standard library only.
- **Identity, tokens and the key proxy.** The harness runs in the lane, next to the agent: anything it holds, the agent
  can reach. Key custody belongs outside the lane (ADR-003's follow-up for brokered credentials).
- **Watchdog, janitor deletions, the clock.** They are per box, not per project. The harness only says what is safe to
  delete (follow-up 9). `orca-nightly`, which defaults to `--merge`, is not the factory's clock.
- **Trusted-sender lists, Slack reports, preview stacks and QA.**

### 5. Failure modes at the boundary
Every case fails closed: no work starts, and nothing is pushed or merged that the harness hasn't passed.

| Situation | Expected behaviour |
|---|---|
| Factory down (listener, dispatcher or runner) | Nothing new starts. Task state is in the worktrees and git; a lane killed mid-session leaves the task `[WIP]` and the next `run` resumes it. Open PRs and the CI floor are unaffected. The watchdog alerts |
| Harness refuses (a gate, `doctor` error, `verify`, plugin mismatch) | The refusal is the outcome. The factory reports the `next` step or the escalation and does not retry in a loop. It never sets `HARNESS_VERIFY=off`, edits `harness.conf` or runs `pin`, `ci-protect` or `orca --merge` |
| Stale pin, or the pinned engine can't be fetched | The launcher refuses everything but reads; in autonomous mode a plugin mismatch stops `run` (ADR-001). The factory reports it; the user moves the pin in a reviewed PR |
| Contract version not served | The factory doesn't route tasks to that project |
| Cap hit mid-task | The proxy refuses the call; the session ends; the harness records the cost and escalates (`budget`); the task stays `BLOCKED` with its work committed or left in the worktree, never delivered half-judged. A day cap holds new sessions until the next day |
| Duplicate events | The inbox drops repeats by source and message id. `intake` is idempotent on `dedupe_key`; `run` on a done task does nothing; a delivery updates the same PR; a review comment id is processed once (follow-up 7) |
| Two lanes on one task | The runner assigns one lane per (project, task) (assumed); `run --only` takes a per-task lock in the shared git directory, as `orca` takes one per repository (follow-up 1) |
| Lane dies after the commit, before the PR | `next` still says `deliver`; the next delivery opens or updates the PR |
| Janitor runs while a task is live | It deletes only what the harness reports safe (follow-up 9): settled, no open escalation, nothing unpushed |

### 6. Security
- **Prompt injection through Slack, GitHub or Linear.** Only the dispatcher's sender check decides whether a request
  may start work, and the harness records that verdict. Request text is quoted into the spec as source material
  (`linear_import` does this today, and `linear.py` says issue text is untrusted), then rewritten by the analyst,
  grilled and approved. Policy approval reaches only low-risk `docs` and `refactor` specs; an untrusted sender's task
  always waits for a person (follow-up 2). Review comments count only from trusted reviewers (follow-up 7). Whatever
  a session reads (PR text, CI logs, vault notes), its tools stay held by the hooks: write scopes, guardrails, the
  deliverer's allowlist, protected paths, user-only settings and the read-only knowledge tools. An injected
  instruction can still steer the model within those tools; the judge, the lenses, the security lens, the CI floor
  and the human review are the defence. Proposed [ADR-006](ADR-006-external-agent-resource-admission.md) applies the
  same rule to third-party setup resources: reference data, not authority.
- **Cross-project leakage between lanes.** One lane holds one project's clone and nothing of another's (assumed).
  Harness state is per repository (`backbone/`, `.git/harness/`), and the knowledge source is configured per project
  (`HARNESS_KNOWLEDGE_ROOT`, `HARNESS_KNOWLEDGE_PATHS`). The engine cache is shared across projects and must be
  mounted read-only. Codex and OpenCode role agents are installed per user (ADR-001), so each lane runs with its own
  home folder (assumed). Stand-in keys are per lane and task, so one project can't spend another's budget (assumed).
  Lessons stay per project: the factory doesn't copy `6-MEMORY.md` or KB notes between projects.
- **The factory identity's permissions.** GitHub: write to branches other than the default branch and to pull
  requests, read checks; no admin role (admins can bypass branch protection), not on the default branch's push
  restriction or a ruleset's bypass list, no `workflows` permission, no access to secrets, variables or environments.
  Linear: read issues and comment; `linear receipt` already refuses states that complete or cancel a ticket. Slack:
  read mentions and post in the factory's channels. Model keys: held by the proxy only.
- **How ADR-002's "only a human merges" holds.** Three layers, the second being the boundary:
  1. In the lane, the deliverer never merges and its gh allowlist refuses merge, review, close and auto-merge; a
     no-merge profile extends the refusal of `gh pr merge`, merge APIs and merge tools to every agent (follow-up 10).
  2. GitHub: the default branch restricts who may push, which includes merging a pull request, to named people; it
     requires an approving review from someone other than the last pusher and the `harness-verify` check. The
     factory's identity can't merge, approve its own PR or change those rules.
  3. CI: `harness-verify` checks every PR with the base branch's verifier, so a PR can't weaken its own check.

  A `risk:low` label and a policy approval of a spec are never merge approval.

## Alternatives considered
- **The factory implements its own loop and state**, using the harness as a linter or not at all: two systems of
  record, and the CI floor no longer checks the verdicts the factory acted on.
- **The harness grows into the factory** (listeners, identity, scheduler in `harness.py`): it runs inside the lane next
  to the agent, so it would put tokens within the agent's reach, and it would turn a per-call engine into a daemon.
- **The factory drives each step itself through `next --json`**, one worker per step, as the Orca coordinator does: it
  gives each role its own session and model without new routing in `run`, but it duplicates `coordinator.py` in the
  factory and ties the factory to the workflow. Kept as the fallback if follow-up 5 proves hard.
- **Run `harness.py orca` on the box**: Orca drives desktop terminals and the box is headless (assumed), and its
  scheduled entry point defaults to merging.
- **Full installs per project**: they work, since the launcher defers to them, but bring back the version spread
  ADR-001 removed.
- **Keep the deliverer pushing from the lane**: no new commands, but a GitHub credential inside the lane, against the
  factory's "no secrets" rule; kept only as the stop-gap above.

## Consequences
- **Easier**:
  - The factory gets the harness's gates, receipts and CI floor without re-implementing them, and one task's evidence
    is the same whether a person or the factory started it.
  - The factory's ledger can be rebuilt from the projects at any time.
  - Lanes hold no long-lived credentials once delivery moves to the trusted clone.
- **Harder**:
  - `feature` and `schema` work stops for a person's spec approval before Build, which is slower than the factory's
    loop as drawn.
  - The factory must refuse to route work to projects that aren't set up (pin, autonomy, profile, protection).
  - Delivery code lives on both sides of the boundary until the plan and record commands settle.
- **Unchanged**:
  - Supervised use, `run` and `orca` outside the factory.
  - The CI floor, the receipt and ADR-002's ladder.
  - Merging stays with a person.
- **Before the factory takes real work**: follow-ups 1, 2, 3, 4 and 10, and the GitHub settings in section 6.
- **Follow-up work**, each its own change with tests in `tests/run-tests.sh`. Size: S is one small PR, M one PR across
  several hooks or commands, L more than one PR.
  1. **Contract surface** (S): `contract --json`; `escalations --json`; a `v` field and `outward` events; a per-task
     lock for `run --only`; tests that pin the JSON shapes of `next`, `state`, `receipt` and the events.
  2. **Intake with provenance and the trusted-sender verdict** (M): `intake`, the frozen `## Source` section,
     idempotence on `dedupe_key`, escalation for untrusted senders; the same provenance on `linear import`.
  3. **Spend caps per task and per day** (S to M): `HARNESS_TASK_BUDGET_USD`, the per-task ledger, refusing a new
     session over budget, the `budget` escalation kind and cost on the receipt. The per-day cap and booking before each
     call are the proxy's.
  4. **Delivery from a trusted clone** (M): `HARNESS_DELIVER="external"`, `delivery-plan`, `delivery-record`.
  5. **Model routing per role in `run`, and the model in every verdict** (M).
  6. **A security lens that risk switches on** (M): the `security` lens, `HARNESS_SECURITY_PATHS`, the trigger in
     `next`, the judge gate requiring its pass, a reviewer raising risk, and the lens on the receipt.
  7. **Resume on pull request review comments** (M to L): `harness.py feedback <id> <review.json>` records comments
     from trusted reviewers, with their ids, as findings, so `next` returns `fix` as it does for red CI; `run --only`
     resumes a task whose branch exists; the next delivery updates the same PR.
  8. **Project KB note drafts** (S to M): the scribe drafts `backbone/kb-notes/<task>.md` (status draft), separate from
     `6-MEMORY.md`; the factory opens the KB pull request. The KB stays read-only to agents, served as the knowledge
     source (assumed to be the same Markdown repository).
  9. **Lifecycle signals for the janitor** (S): `harness.py lifecycle --json`: per task, whether it is settled (PR
     merged or closed, or the task dropped, with no open escalation), since when, its branch and worktree, and whether
     anything is unpushed or uncommitted.
  10. **A no-merge profile not tied to Triple** (S): the merge refusals of `triple` without its catalog pack, for
      factory lanes.
  11. **Lane sandbox evidence** (S to M, mostly factory side): the lane meets ADR-003's checks for `container` (no
      NET_ADMIN or NET_RAW, `no-new-privileges`, the egress allowlist published), and `credential_mode: brokered`
      describes stand-in keys (ADR-003 follow-ups 2 and 9). Until then, thin-mode receipts from lanes say
      `isolation_class: none`.
- Proposed [ADR-007](ADR-007-evidence-closed-loop.md) describes signal intake with a source reference and a
  deduplication key; follow-up 2 is the harness side of that for the factory's doors.

## Implementation notes (2026-11-11)
Follow-ups 1, 2, 3, 4 and 10, the ones Consequences requires before the factory takes real work, are built in the
harness on branch `soyPeter/adr008-prereqs` (pull request #90), with the fixes an independent review of that pull
request asked for. The Status stays Proposed: accepting the decision is the maintainer's call. The factory's runtime
isn't in this repository, so each follow-up is tested from the harness's side only, through its commands, hooks and
event log: `tests/test-factory-contract.py`, `test-no-merge-profile.py`, `test-task-budget.py`, `test-intake.py` and
`test-external-delivery.py`.

What was built, and where it reads this ADR one way among several:

- **1, contract surface.** `contract --json` serves version 1. Besides the versions it declares the fields each answer
  of `next`, `state`, `receipt`, `escalations`, `intake` and `delivery-plan` always has, and the fields of each event
  kind, so the factory can check an engine before routing work to it; the tests pin version 1 against both the
  declaration and the answers. `escalations --json` and `v` on every event as proposed. `outward` events are logged by
  post-tool-use once a Bash call has run, with its `result` (`unknown` where the agent CLI doesn't say): a push, a pull
  request created or edited, a label created or a GitHub API write, however it is spelled, with the agent's role as
  `via`; and the GitHub issue, push, pull request and Linear comment the harness makes itself. `gh pr comment` and
  `ci-protect` are not covered. The per-task lock is an OS lock in `.git/harness/locks/`, taken by every runner path:
  `run` with or without `--only` (under `run --worktree`, the child run in the worktree), and `orca` for the tasks it
  drives.
- **10, no-merge profile.** `HARNESS_PROFILE="no-merge"` has the refusals of `triple` and nothing else.
  `enroll --profile no-merge` refuses `--automation` but allows `--protect`, since requiring `harness-verify` is part
  of a project joining the factory (section 1).
- **3, spend per task.** `HARNESS_TASK_BUDGET_USD` is read as the task's whole cap, not what remains of it: the ledger
  (`.git/harness/costs/task-<id>.jsonl`) holds what the task spent across runs and resumes, so the factory sets the
  same value on every run of a task. Each session is reserved before it starts, for what remains of the budget, and
  settled when it ends, so a session whose run was killed counts as all it could have spent. A ledger that can't be
  read or written, is corrupt, or is missing while the event log shows the task ran, stops the task (`budget`)
  instead of reading as nothing. Reaching the cap escalates
  the task (`budget`) and the run goes on with other tasks. The proxy's refusal is recognised only while a budget is
  set, as an HTTP 402 in the agent's own error report; the proxy must refuse that way (assumed). It escalates
  `budget` and stops the run, since the day's cap may refuse the next task too. The escalation's class is
  `permission_denied`. A session whose agent reports no price (Codex) adds nothing, so the ledger is a floor; the
  proxy stays the enforcement point.
- **2, intake.** Task ids are `intake.<n>`. The dedupe index is in the shared git directory, with the Source sections
  of the checkout's specs as a fallback. An untrusted request is escalated (`intake`) at once and, once a person
  resolves that, its Source is a risk reason, so `approve` escalates it again and only a person's `Approved-by:` line
  lets it start. A Source section counts only with a `- Sender verdict:` line, and the heading is reserved. The quoted
  text is escaped (headings, fences, HTML, comments, setext lines), and titles keep plain characters only. That title
  rule now applies to `linear import` too: a ticket titled `... (light)` could put its task on the light lane, and
  one with `- BLOCKED:` made it look blocked. The hooks refuse any change to a Source section, `verify` refuses one in
  a range (unless the user approves it with `--allow-user-changes`), and the analyst's instructions say to keep it.
  `linear import` trusts the ticket by default, since the user runs it; the factory passes `--sender-verdict`. The
  user-only commands (`intake`, `delivery-record`, and `run`, `linear` and the others that were refused only in one
  spelling before) are refused to agents however the engine is started: interpreter flags, the launcher, a module
  run, an expansion, a shell function, code that runs it, a copy. Two rules hold for every program: an interpreter
  reading its program from stdin is refused unless it is a literal heredoc, and `xargs`, `parallel` and `find -exec`
  may not run a shell or an interpreter whose program comes from their input.
  `intake` and `linear import` leave the out-of-band snapshot alone, so if an agent runs them anyway by a path the
  shell checks miss, their writes show as tampering.
- **4, delivery from a trusted clone.** The lane can't read the pull request's labels, so the factory passes them to
  `delivery-plan` (`--pr-labels`) and gets the labels to add and remove. `delivery-record` takes the trusted clone's
  `verify` result and refuses a report whose verified head or range isn't the task's `HEAD`, or a `delivered` one
  whose verify failed. In external mode the boundary is that the lane holds no push credential;
  the hooks add defence in depth (every agent runs `gh` reads only and no push-capable git, nor git or gh through a
  runner or as a `git-*` program), and a deliverer's report isn't recorded: only `delivery-record` writes the `deliver` event `next` reads, and a record
  counts only for its own task. With `HARNESS_DELIVERY_KEY`, a secret the factory sets for `delivery-record` and
  `next` only (`run`, `orca` and `ci-judge` refuse to start while it is in their environment, since a session could read it
  from its parent), records are signed and `next` counts only signed ones. `harness.py orca` was not
  otherwise adapted: it leaves such a task waiting at the deliver step and starts no deliverer.
- **Agents write nothing in the git directory**, with the file tools or the shell, by a relative or an absolute path,
  from the checkout or a linked worktree, through a glob, `$PWD`, `$VAR`, `git rev-parse` or an unresolved `cd`, or
  with `find -delete` from a folder that holds it: the event log, the cost ledgers, the run locks and the
  out-of-band snapshot live there. A task's run also leaves a marker beside them, so a missing ledger fails closed
  even when the event log is gone too.

What remains open, plainly: the shell checks read command text, and a text check can't see every spelling; the
lane's agents can also run code the hooks don't read (a test or a script they write and run). Such code can still append to the event log, change or delete the cost ledger, delete a run lock, or rewrite
the out-of-band snapshot, all in the git directory, and so hide a change to `backbone/` from the tamper check too.
The boundaries that hold are the credentials a lane doesn't have (the key proxy enforces spend whatever the ledger
says, and with external delivery only the trusted clone can push), `harness-verify` in CI with the base branch's
engine, and the human review; signed delivery records (`HARNESS_DELIVERY_KEY`) keep a forged delivery from counting,
and a missing ledger stops a task that ran before. The shell checks and the out-of-band snapshot are defence in depth. Without the key, `next` trusts every delivery record, as
it trusts the deliverer's own report today.

Not built, and why:

- Follow-ups 5 to 9 and 11: not among the prerequisites above, so left for their own changes.
- The per-day cap and booking each call before it goes out: the key proxy's (section 2).
- The factory's side of each step (the adapter that checks `contract`, the sender check, the proxy, the trusted
  clone's fetch, verify, push and pull request calls, keeping `HARNESS_DELIVERY_KEY`) and the GitHub settings of
  section 6: they are not in this repository.
- Intake de-duplication across clones: the index is per clone, and a fresh clone finds earlier intakes only through
  the Source sections its checkout holds. The factory's inbox drops repeats before intake.
