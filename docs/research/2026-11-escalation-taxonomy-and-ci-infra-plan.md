# Proposed plan: a closed escalation taxonomy and infrastructure CI classification

- **Status:** Proposed. Not accepted, not implemented, and not permission to change the coordinator, any gate or test, or to start Orca.
- **Date:** 2026-11-19 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-escalation-taxonomy-and-ci-infra-plan.md`. This plan adds no new ADR. If accepted, the taxonomy extends the escalation kinds already named in [ADR-008](../adr/ADR-008-harness-inside-agent-factory.md) section 2, and the CI split is a narrowing of today's `delivery-failed` fix path.
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** [ADR-008](../adr/ADR-008-harness-inside-agent-factory.md) (factory contract, escalations, `delivery-failed`, follow-up 7), [ADR-002](../adr/ADR-002-change-class-ladder.md), `payload/owned/AGENTS.md` section 7, `payload/owned/backbone/8-WORKFLOW.md`, `harness.py escalate` and `next`. KB summary: `60-AI/Research/ai-Archdev-Software-Factory-Grunewald-2026-11.md` in the knowledge base, branch `soyPeter/grunewald-factory-note-2026-11-19`.

## Why

Two problems show up once a coding factory runs without someone watching the chat.

First, workers ask a person questions they could have decided themselves. The answers, if they arrive at all, live in a session and never reach the next worker. Grunewald reports 151 such requests in about 21 hours, and 67 paused Tasks the overseer never surfaced. Those two figures are his claims, unverified. The failure mode is still real: an open-ended escalate path will be used for convenience.

Second, a red CI check is treated as a code defect. A runner timeout or a flaky infrastructure log then enters the same fix loop as a real test failure. The fix agent "repairs" the wrong thing, or burns a judge round on a failure it cannot fix.

This plan proposes the smallest harness changes that close those two gaps. It does not build a second local git server, does not implement ADR-008 follow-up 7 (resume on trusted PR review comments), and does not give any agent merge rights.

## Evidence and baseline

### External source

Calvin Grunewald, ["A Look Inside the Factory"](https://thebuildingmachine.com/p/a-look-inside-the-factory), The Building Machine, 19 Nov 2026. Read in full on 19 Nov 2026 from [his post](https://x.com/CalvinGrunewald/status/2123472779559436533). Relevant points, as he states them:

- A question is a paused Task with a kind, the question, why the worker stopped, and a recommended answer. The human reply is stored on the Task. The next worker's prompt includes that reply.
- Only six kinds may be asked of a person: credentials, spending, live infrastructure (merging counts), irreversible actions, product decisions, and anything the Task itself says needs sign-off. Any other question is rejected, decided by the overseer, and recorded on the Task with the reason.
- `archdev.json` can list `infrastructure_log_patterns` so CI failures that are the runner's fault are not treated as code defects.

### What the harness already covers

| Idea in the article | Harness today | Status |
| --- | --- | --- |
| Task as the unit of work, one PR per task | Task ledger, one branch, deliverer updates or opens a PR | Covered |
| Human merge | The deliverer never merges. ADR-008 no-merge profile is in main (follow-up 10) | Covered |
| Independent review before publish | Judge, lenses, pre-push hooks, trusted-clone delivery (ADR-008 follow-ups 1-4 and 10) | Covered |
| A private bare repo in front of GitHub | Trusted clone plus hooks already hold the publish gate. A second local git server would be a new component | Out of scope |
| Resume on PR review comments | ADR-008 follow-up 7 proposes `harness.py feedback`. Still open | Leave to follow-up 7 |
| Policy evals as JSON arms against frozen findings | PR #92 replays refused hook calls against rule and engine changes. That is a different eval. Review-and-fix arms against frozen PR findings are not in this plan | Out of scope |
| Park work and continue | `harness.py escalate` writes a `BLOCKED:` note and an `escalations.md` entry. Only the user clears it. AGENTS.md section 7 | Partial: the park exists; the taxonomy and recommended answer do not |
| Red CI becomes a fix step | `next` can return `delivery-failed`. 8-WORKFLOW.md says each finding names an owner, and a follow-up task's delivery updates the same PR | Partial: there is a fix path, but no infra-vs-code split in the docs read for this plan |

### WP0 must confirm before any change

The statements in the table come from ADR-008, AGENTS.md, 8-WORKFLOW.md and the command surface. They are not a full code audit. WP0 has to pin a revision and check the code, then stop the matching work package if that gap is already closed.

## Decisions to make

1. **The default human-decision list.** The proposed default is the six kinds above, with `live-infrastructure` including merge, deploys, and changes to running systems. Pedro can add or remove kinds before WP1. A kind that is not on the list must not pause for a person.
2. **Whether a missing recommended answer is a hard error.** The default is yes: `escalate` without `--recommended` (or the same field in the JSON form) is rejected, and the worker must either decide and record why, or resubmit with a proposal.

## Work packages

### WP0. Audit

Pin a revision. Read `escalate`, the escalation record, how a `BLOCKED` task is resumed, what the next session prompt includes, and how `delivery-failed` findings are classified and turned into a fix step.

Stop the matching work package, and close that part of the plan, if:

- An escalation already requires a kind from a closed list and a recommended answer, the user's reply is stored on the task, and the next session prompt includes that reply, or
- Red CI findings are already classified as infrastructure vs code from configurable log patterns, and infrastructure findings escalate instead of entering the fix loop.

Write the findings in this file under "WP0 results". No code change in WP0.

### WP1. Closed escalation taxonomy

Only if WP0 finds the gap.

- Extend `harness.py escalate` (and the JSON contract field, if one is needed) so an escalation that waits for a person names one kind from the closed list and includes a recommended answer. Refuse an escalation that is missing either field.
- An escalation that is not on the list is not recorded as waiting for a person. The orchestrator or runner decides, writes the decision and the reason on the task, and continues. Same rule in autonomous mode.
- When the user resolves an on-list escalation, store the reply on the task (the escalation entry and, if useful, a short comment in the task file). The next `run` or `next` prompt for that task must include the question, the recommendation, and the reply.
- Merge, credentials, spend, live infrastructure, irreversible actions and product decisions stay on the list unless Pedro shortens it. "The Task says this needs sign-off" is already satisfied by an `Approved-by` requirement and existing approval escalations; WP1 should reuse those, not invent a second sign-off flag.
- Tests in `tests/run-tests.sh` (or the existing escalate test file, if one exists): a valid on-list escalate with a recommendation parks the task; a missing kind or recommendation is refused; an off-list reason is recorded as a decision and does not park; after the user writes a reply, the next prompt contains it.

Do not change who may clear a `BLOCKED` note. That stays the user.

### WP2. Infrastructure vs code on red CI

Only if WP0 finds the gap.

- Add a user-owned, repo-level list of regular expressions for CI logs that mean the runner failed (timeouts, lost executors, known infrastructure errors). Start empty. An empty list changes nothing about today's fix path.
- When `next` would return `delivery-failed` from a red check, apply the list to the failing log or summary the harness already has. A match becomes a finding owned by `user` (or a new infra owner), not a code fix step. It escalates with a recommended action (rerun, wait, or inspect the runner). A non-match keeps the current fix path.
- The list must not be writable by the implementer during the run that produced the failure.
- Do not auto-rerun CI in WP2. Do not merge. Do not open a new PR. Do not treat this as follow-up 7: review comments stay out of scope.
- Tests: a fixture log that matches the list escalates and does not start fix; a fixture log that does not match keeps today's `delivery-failed` fix path; an empty list keeps today's path for both.

### Out of scope

- A local bare git server, SQLite job queue, or new daemon process.
- ADR-008 follow-up 7 (`harness.py feedback`).
- Auto-merge, production credentials, or any change to the human merge rule.
- Review-and-fix eval arms against frozen PR findings. PR #92 covers hook-call replay, which is a different eval.
- Process supervisors for Orca workers.
- Fail-open lint that continues into a fix agent. That is a policy choice for later, and a poor default for payments work.

## Stop conditions

- WP0 shows both gaps already closed: mark the plan done with no code, and leave the file as the audit record.
- A work package would need merge rights, a new long-lived daemon, or a change to trusted-clone delivery: stop and write why, rather than widening the plan.
- Tests for a work package fail, or a fixture cannot be built without touching production CI: leave the code unmerged and record the blockage.

## Decision recorded here if accepted

- Escalations that wait for a person use a closed kind list and a recommended answer. Off-list questions are decided and recorded, not parked.
- Red CI is split into infrastructure and code using a user-owned pattern list, before a fix loop starts.
- Merge stays with the user.
