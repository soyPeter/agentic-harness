# Proposed plan: an indeterminate outcome for unobserved side-effecting writes

- **Status:** Proposed. Not accepted, not implemented, and not permission to change any gate, hook, runner or test.
- **Date:** 2026-11-10 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-indeterminate-side-effect-outcome-plan.md` (implementation plan under existing decisions; not an ADR, because it adds an outcome and a journal for writes the harness already makes, without a new architectural boundary).
- **Decision authority (proposed role, unassigned):** repository maintainer; PR merge stays with the user as today.
- **Related:** `payload/owned/scripts/harness/lib/coordinator.py` (`failed_workers`, `END_STEPS`); `payload/owned/scripts/harness/lib/harness.py` (`record_delivery`, `DELIVERY_OUTCOMES`, `escalate`, `FAILURE_CLASSES`); `payload/owned/scripts/harness/lib/linear.py`; `payload/owned/.claude/agents/deliverer.md`; [ADR-002](../adr/ADR-002-change-class-ladder.md). KB note `20-Platform/Research/SDD/plt-SDD-Durable-Execution-Agents-Prakash-2026-11.md`.


## Decisions (2026-11-10)

Pedro accepted the following defaults:

- Option B: an explicit `indeterminate` outcome for unobserved side-effecting writes, an attempt journal, and reconcile-or-park before any retry of the write. Conditional on WP0 confirming the gap.
- Scope is all four write paths: opening or editing a PR, opening a GitHub escalation issue, posting a Linear comment, and moving a Linear issue. WP0 may drop any path that is already safe to retry.
- If reconcile cannot tell whether the write happened, park the task for the user. Do not retry the write.

## Evidence and baseline

### External pattern (primary source)

Kiran Prakash, [Long-horizon agents and durable execution](https://martinfowler.com/articles/durable-execution-agents.html), published on martinfowler.com on 10 November 2026. Read in full.

Durable execution records the input and output of each step that talks to the outside world, then replays after a crash so completed steps are not run again. Retries are at-least-once. If the other system accepted the write and only the reply was lost, the runtime has no record and calls again. The article says a persistent log records what the agent saw. That can differ from what actually happened. The practical rule is that "we don't know" has to be kept as its own state. If that case is stored as failed, later deterministic steps act as if the write never happened.

The article's mitigations are an idempotency key that stays the same on every attempt, and a compensating action once the duplicate is noticed. Adopting Temporal, Cloudflare Workflows or another durable runtime is described there as the way to get replay. That path is option C below and is rejected for this factory.

A reply by @SilentBytez pointed at this article and at [SourceShift/mini-ork](https://github.com/SourceShift/mini-ork). The README and `docs/WHY.md` were skimmed. `certify` can return PROVEN, REFUTED or UNVERIFIED, and the WHY page claims "idempotent tool receipts" and "Durable-DAG resume". The repo was not cloned and the code was not audited. It is a self-promoting secondary source. This plan does not adopt it.

### Harness baseline (code read at `origin/main` `6e2f8ac2fac5f3ac8d279be42b8fe7c607de3410`, not executed)

- Task lines are `pending`, `wip`, `done`, `blocked` or `missing` (`task_state`).
- `next_step` can return step name `unknown` when the task is missing from `3-TASKS.md`. The coordinator's `END_STEPS` are `blocked`, `done` and `unknown`. An unrecognised step becomes the outcome `stopped at an unknown step` and the run stops. That marks a missing or unrecognised step. It does not mark an unobserved write.
- Delivery outcomes are `delivered`, `hold` and `ci-failed` (`DELIVERY_OUTCOMES`). `record_delivery` writes a `deliver` event only when the deliverer's Stop hook runs. `latest_delivery` looks in the events log for that commit. If there is no event, `delivery_step` asks the deliverer to run again.
- If a worker ends without `worker_done`, the coordinator logs `failed-before-reporting`, classifies the case as `tool_timeout`, retries the step once after a pause, then escalates (`failed_workers` loop). The module comment says that when the state is unclear the coordinator stops and reports instead of guessing. That comment applies to unclear step names. A worker death is still treated as a timeout failure.
- The deliverer's instructions say to call `gh pr view` and to update an existing PR rather than create a second one. A retry after a successful but unreported `gh pr create` can be safe if those instructions are followed. This was not tested.
- `escalate()` may call `gh issue create` when `HARNESS_ESCALATE_GH` is on. There is no check for an existing issue with the same title. If the issue is created and the reply is lost, the return value is empty.
- `linear.py` `post_comment` and `move_issue` have no idempotency key. A repeat of `post_comment` would add another comment. The harness never closes a Linear ticket (`CLOSED_TYPES`).
- Failure classes already exist, each with a playbook. None of them records an unobserved write.
- `retry_brief` tells a later session not to redo work the gates already recorded.

**Hypothesis to confirm in WP0, not a finding yet:** a deliverer or escalate path that dies after the write and before the record can repeat `gh issue create`, and may repeat a Linear comment. The PR path may already be safe because of `gh pr view`. Code was read, not run.

## Problem

The harness already stops when a step name is unclear. It still folds a lost reply to an external write into `failed` or `tool_timeout` and retries the step. Later deterministic steps then proceed as if the write did not happen. For a PR that may already be fine. For a GitHub issue or a Linear comment it may not be.

## Options

| Option | Benefit | Cost / risk |
|---|---|---|
| A. Keep current behaviour; document the `gh pr view` reconcile and the `gh issue create` gap | No code change | Lost replies stay classified as failures; issue and comment writes can repeat |
| B. An explicit `indeterminate` outcome for unobserved side-effecting writes, an attempt journal, and reconcile-or-park before any retry of the write (recommended) | Same rule for every write path; reuses events log and existing delivery recording; small | Must not block a later human merge or invent a success |
| C. Run the coordinator loop on a durable execution runtime (Temporal, Cloudflare Workflows or similar) | Replay of every step, including model calls | New runtime and operational surface next to git, worktrees and Linear; out of proportion to the gap; would touch how every step resumes |

**Proposed: B**, conditional on WP0 confirming the gap. C is rejected for now.

## Proposed behaviour (B)

1. **Writes in scope (WP0 may narrow this).** Opening or editing a PR, opening a GitHub escalation issue, posting a Linear comment, and moving a Linear issue. Judge, grill and review verdicts stay `pass` or `fail`. A missing verdict JSON still means nothing was recorded.
2. **Attempt journal.** Before each in-scope write, append an event with the intent, a stable idempotency key, the target (branch, issue title, Linear id) and state `attempted`. After a known result, the same key is updated to `observed` with the result (PR url, issue url, comment url, new Linear state). The events log already used by `record_delivery` is the first place to put this, unless WP0 finds a better existing file.
3. **`indeterminate` outcome.** If the process dies, times out, or gets no reply after `attempted` and before `observed`, the step outcome is `indeterminate`. It is not `failed`, `tool_timeout`, `hold` or `ci-failed`. `delivery_step` / `next` / the coordinator must not treat that as "run the write again".
4. **Reconcile before any retry.** On resume, read the external system with a safe query (`gh pr view`, search issues by the exact escalation title, read Linear comments or state). If the write is found, record `observed` and continue. If it is clearly absent, a person (decision 3) either parks the task or allows one retry under the same key. If the query cannot tell, park the task for the user with the journal entry cited. Do not guess.
5. **`gh issue create`.** Use a stable title already in the code (`Harness escalation: task %s: %s`). Before creating, search for an open issue with that title and label `harness-escalation`. If one exists, reuse its url.
6. **Linear comments.** The journal key is the issue id plus a hash of the comment body plus the task id. A retry with the same key does not post again if a comment with that body is already present (WP0 confirms how to detect this cheaply). `move_issue` may be retried: moving to the same state is harmless, and tickets still cannot be closed.
7. **Failure class.** Add `indeterminate_write` to `FAILURE_CLASSES` with playbook "reconcile or park". Do not auto-draft a proposal from a single occurrence.

Human merge, the independent judge, evidence bound to a revision, Linear as the tool of record and the Monday update stay as they are. This plan does not change the approval, judge or merge gates.

## Work packages

| WP | Scope | Depends on | Acceptance / evidence |
|---|---|---|---|
| WP0 Audit | On a fixture: kill the deliverer after `gh pr create` and before Stop; kill `escalate` after `gh issue create` and before the return; list whether a retry duplicates the write. Search existing events if any real runs are available. | none | Short findings note with commands and outputs at a pinned revision. **Stop and close the plan if every in-scope write is already safe to retry.** Narrow the scope if only one path is unsafe. |
| WP1 Journal + outcome | Attempt event, `observed` update, `indeterminate` outcome, `delivery_step`/`next`/`orca` honour it, new failure class | WP0 | Tests: a killed write leaves `attempted` and `indeterminate`; `next` does not return "deliver" or "create the issue again"; a later observed result clears it. Existing delivery tests stay green. |
| WP2 Reconcile | `gh pr view` already in the deliverer becomes the documented reconcile for PRs; `gh issue create` searches first; Linear comment retry checks for the same body | WP1 | Tests: a second create with the same title reuses the issue; a second comment with the same key is not posted; a PR that already exists is edited. |
| WP3 Coordinator | A worker that dies during an in-scope write is `indeterminate`, not `tool_timeout`. No automatic retry of the write. Reconcile or park. Workers that die on a read-only step (judge, grill) keep the current timeout playbook. | WP1 | Tests: deliverer death after `attempted` does not start a second deliverer until reconcile; a judge worker death still retries once. |
| WP4 Docs | HOOKS.md, deliverer instructions, CHANGELOG. One paragraph in AGENTS.md on unobserved writes. | WP1 to WP3 | Docs name the outcome and the reconcile rule. |

Out of scope: Temporal or any new workflow runtime, changing verdict values, closing Linear tickets, auto-merging, compensating "undo" tools, and any change to the approval, judge or merge gates.

## Risks and rollback

- **False indeterminate:** a slow `gh` call that later succeeds could leave the task parked. Mitigation: reconcile is the first action on resume, and a late success updates the journal to `observed`.
- **False reuse:** searching GitHub issues by title could attach to the wrong issue. Mitigation: match the exact title and the `harness-escalation` label, in this repository only.
- **Events log growth:** attempt records are small. If the log becomes awkward, move them to a dedicated file in a follow-up. Do not invent a second source of truth in WP1.
- **Rollback:** revert the commits. Tasks already parked as `indeterminate` can be released by the user the same way as BLOCKED. No gate change to undo.

## Decisions needed (human)

Resolved on 2026-11-10. See [Decisions (2026-11-10)](#decisions-2026-11-10).
