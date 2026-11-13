# ADR-008: The harness as the gate inside the agent software factory

## Status
Accepted

## Date
2026-11-11, revised 2026-11-13

## Context
The maintainer's **agent software factory** runs on the Hetzner `claude-box`: agents take delegated work,
open pull requests and report, and a person reviews. The supplied
[factory diagram, captured 13 November 2026](../sdlc/sources/agent-software-factory-2026-11-13.png)
reports it live since 2026-11-11 as `sixseven` (also `67`), using the subscription. This supersedes the earlier
snapshot that described it as installed but switched off. The factory's code is outside this repository;
this update reads the image, not its implementation, deployed settings or a completed build run.
The image still names the first build task as a next action. “Live” does not establish end-to-end qualification.

Source SHA-256: `25d2b177c64f146c967b39b9229d335ec7cad61528491be123f2e8750078a0a3`.
The factory state below is **reported by that snapshot**. The Decision section specifies the harness integration
contract. Follow-ups 1, 2, 3, 4 and 10 have since landed in main through PR #90; the implementation notes below
record their actual semantics and limits. Factory-side integration remains unverified.

### Factory snapshot (13 November 2026)

- **Doors and inbox:** Slack mentions, `sixseven`/`67` or thread replies; GitHub PR reviews or comments naming it;
  Linear delegated issues or comments naming it. The inbox sender-checks and deduplicates. Code decides orders
  and `go` authorization. GitHub comments by Andrei himself go unheard under the current shared identity.
- **Worker loop:** 1 Pick an issue as delegate, 2 Build in a sandbox, 3 Open PR with evidence and reviewers,
  4 You review and tag the agent to revise in the same session, 5 Close out with lessons and a report.
  There is no separate universal Challenge stage in this version of the image.
- **Crew:** Front (Opus, with Haiku sorting what to answer) talks, proposes, reads code and diffs, and can comment,
  file, review, label and merge in the external factory. Worker (Opus) handles one task per project from pick to PR.
  Advisor (Fable) is consulted on features and wide changes; it is not an independent judge of every diff.
  Security (Mythos) is triggered by risky paths (public surfaces, outside calls, databases), but its key is missing:
  a flagged change stops there. QA and the preview stack are not built, and parallel workers per project are not built.
- **Memory:** facts record what Front heard and from whom/where, but remain hearsay until proposed as an entry.
  Entries (rulings, findings, learning or pages) require `go` from the authorized person. The factory drafts a KB PR
  that a person merges. Roles read local pages first, then `triple-kb`. The task ledger includes conversations and
  next actions. The image says KB push is off pending branch protection; automatic promotion is not implied.
- **Identity and authority:** Slack uses the bot; git/GitHub and Linear currently use Andrei's login/key and act as
  him. Dedicated GitHub/Linear identities remain a next action. The roster controls who gives orders and approves;
  a ruling needs its ruler's `go`. Merge is described as requiring a roster ask and GitHub approval, while Front
  can perform it. That is a difference from the harness's human-only merge rule, not proof that rule is enforced.
- **Foundations:** the image states no secrets or open ports in agent code, audited outward actions, one stop switch,
  path-based risk that only a person may downgrade, and human control of deploy, spend and infrastructure.
  It lists caps of $25/task, $100/day and $5/conversation, with a separate Front budget of $25/day across chat.
  Only advisor calls pass through the key proxy. Its cap enforcement therefore does not establish metering or
  pre-call limits over subscription worker/Front activity; that boundary requires qualification.
- **Runtime:** listener (live Slack plus polling all doors every 30 s), code dispatcher, task/chat lanes, one KB writer,
  whole-session boxing and trusted-clone pushes, watchdog, and an hourly janitor that frees settled lanes/branches
  and refreshes the KB copy. A preview stack with an isolated DB and scrubbed connectors is not built.
- **Stops:** undecided behavior, missing access/repeated failures, a cap hit, or off-limits work (production,
  infrastructure, secrets, security-labelled issues). A missing security key is a stop, not a waived check.
- **PR and autonomy:** PRs carry issue/branch/changelog conventions, worker tests and factory reruns, gate evidence,
  rulings, risk, security outcome, advisor use and cost. The project ladder is triage/QA, delegated fixes, then
  self-assignment of `agent-ok` issues; Disputes is on delegated fixes. The ladder controls intake, not spec approval.

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

Integration coverage after PR #90 (factory runtime not qualified here):

- Intake with source provenance, contract version 1, per-task locks and a generic no-merge profile are implemented.
- Per-task budget accounting survives resumes, but is defence in depth, not enforcement against an agent with a
  shell. Factory-owned pre-call/day limits and subscription usage coverage still require qualification.
- External delivery planning and signed recording are implemented; the factory must supply its trusted-clone adapter
  and protect its credentials and delivery key outside the lane.
- Risk-triggered security review, model routing in `run` with model evidence, PR review feedback, KB drafts and safe
  janitor lifecycle signals remain follow-ups. Red CI already returns as `delivery-failed`.

## Decision
The harness is the gate inside each lane of the factory. The factory brings work in, runs lanes and talks to the
outside world; the harness decides whether the work in a lane is good enough and records why. They meet at a small,
versioned contract of harness commands.

### 1. Who owns what

These are requirements for the combined factory/harness path, not assertions about the running external service.
The design overview below is read with the implementation notes, which specify the implemented command semantics.
The factory's conditional advisor remains useful, but every task must still pass the configured independent judge
and review lenses. Intake authorization (`go`, delegation or `agent-ok`) does not replace a required `Approved-by`
line. The shared human credentials and Front's merge capability must not carry into the integrated path.

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
  `HARNESS_AGENT_CMD` set to the lane's agent command; `HARNESS_REVIEW` on; `HARNESS_DELIVER="external"`; `HARNESS_PROFILE="no-merge"`; `harness-verify` required on the default branch (`harness.py ci-protect`). `run` already refuses to
  start while `doctor` reports an error.

### 2. The contract

The contract is the commands, flags, JSON fields and event kinds named below. It is **version 1**. Within a version,
fields are only added; removing a field or changing its meaning is a new version. `harness.py contract --json` declares served versions and answer/event fields (follow-up 1, implemented in PR #90).
The factory must refuse a lane whose pinned engine does not serve its version; deployed adapter behavior is not
verified here. Main's implementation does not automatically upgrade a project's pinned release.

**Hand a task in.** In the lane's worktree, before `run`:

- Linear, today: the factory fetches the issue with its own token and runs `harness.py linear import <ISSUE> --task
  <id> --from <issue.json>`, so no Linear token enters the lane.
- Every door (follow-up 2, implemented): `harness.py intake <request.json> [--json]`, with `contract`, `source`
  (`slack`, `github`, `linear`, `clock`), `channel`, `message_id` and `url`, `sender`, `sender_verdict` (`trusted` or
  `untrusted`, from the factory's check), `received_at`, `dedupe_key` and `text`. It writes the draft spec with a
  frozen `## Source` section holding the provenance, quotes `text` as source material (as `linear import` does),
  adds the task line and logs an `intake` event. It returns a task id in the form `intake.<n>`;
  the dedupe index lives in the shared git directory, with checkout Source sections as fallback. The same `dedupe_key` returns the existing task and writes
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
| `harness.py escalations` | open escalations, by class. `--json` is implemented in follow-up 1; `contract --json` declares its fields |
| `harness.py trace <id> --json`, `report --json` | the task's history and cost, for the report and the audit log |

The four ways an agent "stops and asks" map onto escalations:

| Factory stop | Harness escalation |
|---|---|
| Needs a ruling | kinds `approval` (a `feature` or `schema` spec, or risk found), `decision`, griller failures; classes `contradictory_req`, `missing_context` |
| Blocked | kinds `runner`, `coordinator`, `integration`, judge failures; classes `tool_timeout`, `unchanged_repeat`, `permission_denied`, `failed_test`. An agent that can't start (`run-agent-failed`) is a lane problem, not the task's |
| Cap hit | `run-budget` per run; kind `budget` for the implemented task ledger/proxy-refusal handling (follow-up 3) |
| Off limits | `approval` with risk reasons for `schema` work and risk paths; `out-of-band change`. Security-labelled issues and production or infrastructure requests are refused by the dispatcher before intake |

A spec that needs a person's approval is approved by that person writing their `Approved-by:` line on the task
branch. A reply in Slack is not an approval, and the factory never writes the line.

**Deliver across the boundary.** The lane holds no GitHub credential, so the deliverer's push and gh calls move to the
factory's trusted clone. The harness still decides what is delivered. Follow-up 4 is implemented in PR #90;
its signing, verification and label inputs are detailed in the implementation notes:

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

For a project pinned to an older engine without external delivery, keep integrated delivery disabled until the
user upgrades it. A restricted stand-in remains an unverified interim design: the image says only advisor calls
use the key proxy. The shared human login cannot establish credential isolation. Lost replies to external writes
still need the durable-attempt and operation-specific reconciliation rules proposed in
[ADR-011](ADR-011-indeterminate-side-effect-outcomes.md); an existing PR alone does not prove an edit succeeded.

**Stop a lane.** The factory's stop switch creates `.git/harness/STOP` in each project clone: every agent tool call is
refused and `run` stops between sessions. The factory then ends its sessions. A killed session leaves the task `[WIP]`,
and the next `run` resumes it. Removing `STOP` is the user's act; the factory never removes it.

**Cost.** The factory owns pre-call budget enforcement and attribution across resumes. The image's key proxy
covers advisor calls only; subscription worker/Front calls need a separately qualified limit or usage-control
mechanism. The stated caps are not evidence of complete enforcement. For metered calls, book the estimate against
the applicable task/day/conversation budgets before forwarding and reconcile actual usage. Do not report unknown
subscription usage as zero cost or claim it is covered by the advisor proxy. The harness side of follow-up 3 is implemented in PR #90:

- reads the task's whole cap from `HARNESS_TASK_BUDGET_USD`, with the same value on each resume; the ledger tracks
  prior usage, reserves the remaining amount before a session and settles reported usage afterward;
- adds each session's cost to a per-task ledger in `.git/harness/` that survives resumes, and puts the total on the
  receipt;
- refuses to start another session once the ledger reaches the budget, and treats the proxy's refusal as a cap hit
  rather than a retryable failure: it escalates with kind `budget` and stops.

The ledger is accounting and defence in depth, not the enforcement: an agent with a shell in the lane can write any
file its user can, the ledger included. The factory must enforce the task/day limits outside the lane: the proxy can cover advisor calls, but does not
establish coverage of subscription sessions. The harness reports known usage and recognizes proxy refusal as
described in the implementation notes; unreported prices make its ledger a floor, not full cost evidence.

`HARNESS_RUN_MAX_COST` stays as the per-run limit for runs outside the factory.

**Events for the factory's audit log.** The factory tails `.git/harness/events.jsonl` read-only and forwards each
event with its lane, project and intake id. Each line is a JSON object with `at`, `kind`, and where known `task`,
`session` and `agent`. Version 1 covers `intake`, `task-start`, `task-finish`, `verdict`, `review`,
`approval`, `escalation`, `proposal`, `deliver`, `run-start`, `run-attempt` (with `cost_usd`), `run-budget`,
`run-halt`, `run-agent-failed`, `run-end`, `tamper`, `block`, `gate` and `linear-import`. Follow-up 1 adds a `v`
field on every event and `outward` events; the implementation notes list their coverage and omissions. The factory audits the outward actions it performs itself. `log_event` never fails
its caller, so a missing event is a gap in the audit log, not evidence that nothing happened.

### 3. Roles and steps

| Factory | Harness | Status |
|---|---|---|
| 1 Pick | intake, then analyst/architect, griller and approval; policy only for low-risk docs/refactor, human for feature/schema | intake provenance and DEFINE implemented |
| 2 Build | implementer and optional tester, hooks and skill scopes; then independent judge and three reviewer lenses before delivery | mandatory review exists; conditional advisor does not replace it |
| 3 Open PR | harness delivery plan and receipt, trusted-clone verification/push/PR, base-verifier CI | harness external delivery implemented; factory adapter unverified |
| 4 You review | trusted review comments become findings and a fix step, with fresh affected evidence before updating the same PR | feedback adapter proposed |
| 5 Close out | scribe memory, Proposed ADRs and KB drafts; the factory submits the reviewed KB PR and reports | KB drafts proposed; scribe runs before task finish |
| Front (Opus; Haiku routing) | external conversation and dispatch; cannot approve specs or merge through the integrated identity | factory-owned; current merge capability must be excluded |
| Worker (Opus) | runner session and its delegated analyst, architect, tester, implementer and scribe roles | exists; factory adapter not qualified here |
| Advisor (Fable) | optional feature/wide-change advice, separate from independent acceptance judgment | factory-owned; not a universal Challenger |
| Security (Mythos) | extra security lens when risk triggers it; missing key blocks delivery | lens/routing proposed; image reports missing key |
| QA and preview stack | future ongoing/browser QA; acceptance tests do not establish that a deployed environment works | external and not built in the image |

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
  shows them, so the PR distinguishes advisor consultation from the models that actually judged and reviewed this revision.

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
| Cap hit mid-task | The factory's enforcement point refuses further activity (the proxy for advisor calls; a separately qualified control for subscription sessions); the harness records known usage and escalates (`budget`). The task stays `BLOCKED`, never delivered half-judged. A day cap holds new sessions until the next day |
| Required security review has no key or produces no verdict | Keep the flagged change blocked. Advisor advice, worker tests and human intake authorization do not replace the required security pass |
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
  and the human review are the defence. Accepted [ADR-006](ADR-006-external-agent-resource-admission.md) applies the
  same rule to third-party setup resources: reference data, not authority.
- **Cross-project leakage between lanes.** One lane holds one project's clone and nothing of another's (assumed).
  Harness state is per repository (`backbone/`, `.git/harness/`), and the knowledge source is configured per project
  (`HARNESS_KNOWLEDGE_ROOT`, `HARNESS_KNOWLEDGE_PATHS`). The engine cache is shared across projects and must be
  mounted read-only. Codex and OpenCode role agents are installed per user (ADR-001), so each lane runs with its own
  home folder (assumed). Stand-in keys are per lane and task, so one project can't spend another's budget (assumed).
  Lessons stay per project: the factory doesn't copy `6-MEMORY.md` or KB notes between projects.
- **The required factory identity's permissions.** The image's shared Andrei credentials do not establish this
  boundary. Provision a dedicated identity before integrated delivery. GitHub: write to branches other than the default branch and to pull
  requests, read checks; no admin role (admins can bypass branch protection), not on the default branch's push
  restriction or a ruleset's bypass list, no `workflows` permission, no access to secrets, variables or environments.
  Linear: read issues and comment; `linear receipt` already refuses states that complete or cancel a ticket. Slack:
  read mentions and post in the factory's channels. Model API keys: held by the proxy only. Subscription
  authentication and its usage limits require their own qualified boundary; an advisor stand-in does not cover them.
- **Required enforcement of ADR-002's "only a human merges".** These layers require deployment checks; the image's
  Front merge capability and roster request are not substitutes. Three layers, the second being the boundary:
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
- **Before qualifying the factory/harness path for real work**: follow-ups 1, 2, 3, 4 and 10, the GitHub
  settings in section 6, and evidence that DEFINE, independent judgment and the three review lenses cannot be
  skipped. This is an integration gate; the image already reports an independently running factory. Qualify
  subscription-worker budgets separately from the advisor proxy and keep flagged work stopped until security
  review is available.
- **Follow-up work**, each its own change with tests in `tests/run-tests.sh`. Size: S is one small PR, M one PR across
  several hooks or commands, L more than one PR.
  1. **Contract surface** (S): `contract --json`; `escalations --json`; a `v` field and `outward` events; a per-task
     lock for `run --only`; tests that pin the JSON shapes of `next`, `state`, `receipt` and the events.
  2. **Intake with provenance and the trusted-sender verdict** (M): `intake`, the frozen `## Source` section,
     idempotence on `dedupe_key`, escalation for untrusted senders; the same provenance on `linear import`.
  3. **Spend caps per task and per day** (S to M): `HARNESS_TASK_BUDGET_USD`, the per-task ledger, refusing a new
     session over budget, the `budget` escalation kind and cost on the receipt. The ledger is accounting and defence
     in depth, since an agent with a shell can write any file its user can. Enforcing pre-call and per-day limits
     remain factory-owned; qualify advisor-proxy coverage and subscription worker/Front limits separately.
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
- Accepted [ADR-007](ADR-007-evidence-closed-loop.md) describes signal intake with a source reference and a
  deduplication key; follow-up 2 is the harness side of that for the factory's doors.

## Implementation notes (2026-11-11)
Follow-ups 1, 2, 3, 4 and 10 are implemented and merged into main through
[PR #90](https://github.com/soyPeter/agentic-harness/pull/90), including its independent-review fixes.
The ADR is Accepted; implementation in main does not imply a released/pinned engine or a qualified factory adapter. The factory's runtime
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
- **10, no-merge profile.** `HARNESS_PROFILE="no-merge"` has the refusals of `triple` and nothing else. `enroll
  --profile no-merge` refuses `--automation` but allows `--protect`, since requiring `harness-verify` is part of a
  project joining the factory (section 1).
- **3, spend per task.** `HARNESS_TASK_BUDGET_USD` is read as the task's whole cap, not what remains of it: the ledger
  (`.git/harness/costs/task-<id>.jsonl`) holds what the task spent across runs and resumes, so the factory sets the same
  value on every run of a task. Each session is reserved before it starts, for what remains of the budget, and settled
  when it ends, so a session whose run was killed counts as all it could have spent. A ledger that can't be read or
  written, is corrupt, or is missing while the event log shows the task ran, stops the task (`budget`) instead of
  reading as nothing. Reaching the cap escalates the task (`budget`) and the run goes on with other tasks. The proxy's
  refusal is recognised only while a budget is set, as an HTTP 402 in the agent's own error report; the proxy must
  refuse that way (assumed). It escalates `budget` and stops the run, since the day's cap may refuse the next task too.
  The escalation's class is `permission_denied`. The ledger is accounting and defence in depth: an agent with a shell
  can write any file its user can, the ledger included, so the enforcing per-task cap, like the per-day one, is the
  factory's, outside the lane. The image's advisor-only proxy does not establish subscription-worker coverage.
  A session whose agent reports no price (Codex) adds nothing, so the ledger is a floor.
- **2, intake.** Task ids are `intake.<n>`. The dedupe index is in the shared git directory, with the Source sections of
  the checkout's specs as a fallback. An untrusted request is escalated (`intake`) at once and, once a person resolves
  that, its Source is a risk reason, so `approve` escalates it again and only a person's `Approved-by:` line lets it
  start. A Source section counts only with a `- Sender verdict:` line, and the heading is reserved. The quoted text is
  escaped (headings, fences, HTML, comments, setext lines), and titles keep plain characters only. That title rule now
  applies to `linear import` too: a ticket titled `... (light)` could put its task on the light lane, and one with `-
  BLOCKED:` made it look blocked. The hooks refuse any change to a Source section, `verify` refuses one in a range
  (unless the user approves it with `--allow-user-changes`), and the analyst's instructions say to keep it. `linear
  import` trusts the ticket by default, since the user runs it; the factory passes `--sender-verdict`. The user-only
  commands (`intake`, `delivery-record`, and `run`, `linear` and the others that were refused only in one spelling
  before) are refused to agents however the engine is started: interpreter flags, the launcher, a module run, an
  expansion, a shell function, code that runs it, a copy. Rules hold for every program: an interpreter or a shell
  reading its program from stdin (a pipe, a redirect, a process substitution) is refused unless it is a literal heredoc;
  `xargs`, `parallel` and `find -exec` may not run a shell or an interpreter whose program comes from their input;
  `env -S` is read as its command, and `awk system()` and git given a command to run (a `!` alias, a command key such as
  `core.sshCommand`) are refused; and the gate tracks what the command itself sets (variables, loops, `read`, `cd`,
  `pushd`, `popd`). `intake` and `linear import` leave the out-of-band snapshot alone, so if an agent runs them anyway
  by a path the shell checks miss, their writes show as tampering.
- **4, delivery from a trusted clone.** The lane can't read the pull request's labels, so the factory passes them to
  `delivery-plan` (`--pr-labels`) and gets the labels to add and remove. `delivery-record` takes the trusted clone's
  `verify` result and refuses a report whose verified head or range isn't the task's `HEAD`, or a `delivered` one whose
  verify failed. In external mode the boundary is that the lane holds no push credential; the hooks add defence in depth
  (every agent runs `gh` reads only and no push-capable git, nor git or gh through a runner or as a `git-*` program,
  each command classified by its parsed words and a command named by an expansion refused), and a deliverer's report
  isn't recorded: only `delivery-record` writes the `deliver` event `next` reads, and a record counts only for its own
  task. With `HARNESS_DELIVERY_KEY`, a secret the factory sets for `delivery-record` and `next` only (`run`, `orca` and
  `ci-judge` refuse to start while it is in their environment, since a session could read it from its parent), records
  are signed and `next` counts only signed ones. `harness.py orca` was not otherwise adapted: it leaves such a task
  waiting at the deliver step and starts no deliverer.
- **Agents write nothing in the git directory**, with the file tools or the shell, by a relative or an absolute path,
  from the checkout or a linked worktree, through a glob, `$PWD`, `$VAR`, `git rev-parse` or an unresolved `cd`, or with
  `find -delete` or a writer run by `find -exec` or `xargs` that can reach it (a `find` that prunes `.git`, or whose
  `-name` patterns match nothing there, stays allowed), or through a target the hooks can't resolve: the event log, the
  cost ledgers, the run locks and the out-of-band snapshot live there. A task's run also leaves a marker beside them, so
  a missing ledger fails closed even when the event log is gone too.

What remains open, plainly: the shell checks read command text, and a text check can't see every spelling; the lane's
agents can also run code the hooks don't read (a test or a script they write and run). Such code can still append to the
event log, change or delete the cost ledger, delete a run lock, or rewrite the out-of-band snapshot, all in the git
directory, and so hide a change to `backbone/` from the tamper check too. The boundaries that hold are the credentials a
lane doesn't have (an external budget control must enforce limits regardless of the ledger, and with external
 delivery only the trusted clone can push), `harness-verify` in CI with the base branch's engine, and the human review; signed delivery records
(`HARNESS_DELIVERY_KEY`) keep a forged delivery from counting, and a missing ledger stops a task that ran before. The
shell checks and the out-of-band snapshot are defence in depth. Without the key, `next` trusts every delivery record, as
it trusts the deliverer's own report today.

Not built, and why:

- Follow-ups 5 to 9 and 11: not among the prerequisites above, so left for their own changes.
- Per-day/pre-call enforcement: factory-owned (section 2); advisor-proxy coverage does not qualify subscription usage.
- The factory's side of each step (the adapter that checks `contract`, the sender check, the proxy, the trusted clone's
  fetch, verify, push and pull request calls, keeping `HARNESS_DELIVERY_KEY`) and the GitHub settings of section 6: they
  are not in this repository.
- Intake de-duplication across clones: the index is per clone, and a fresh clone finds earlier intakes only through the
  Source sections its checkout holds. The factory's inbox drops repeats before intake.
