# ADR-011: Reconcile indeterminate external writes before retrying

## Status
Proposed

## Date
2026-11-13

## Context
The [indeterminate-outcome plan](../research/2026-11-indeterminate-side-effect-outcome-plan.md) identifies a
possible gap between an external write succeeding and the harness recording its result. A worker death or lost
reply does not establish that nothing happened. Treating it as an ordinary timeout can duplicate an issue or comment.
The plan's code-read baseline is a hypothesis, not a reproduced runtime finding.

Pedro recorded option B on 10 November 2026, conditional on WP0 confirming the gap: cover PR create/edit,
GitHub escalation issues, Linear comments and Linear state moves; park when reconciliation is inconclusive.

## Decision
Audit the four paths first. For paths not already safe to retry, record an attempt before the external write and
represent an unobserved result as `indeterminate`. Reconcile through safe reads before considering another write.

- Reuse the existing events journal only through a writer that confirms durable persistence and reports errors;
  the existing best-effort `log_event` cannot supply that guarantee. Persist an `attempted` event before dispatch
  with stable intent/key, target, operation, task identity and the intended postcondition (or a digest of its fields).
  If persistence fails or cannot be confirmed, park without dispatching the external write. Do not put secrets in
  the journal. Scope keys so distinct intended writes are not treated as duplicates.
- Append and durably persist an `observed` result with the same key before clearing a pending attempt or advancing
  delivery. Preserve history rather than rewriting events. If recording the result fails after dispatch, retain the
  pending attempt for reconciliation; a successful remote reply alone must not enable an automatic retry.
- A crash, timeout or lost reply between those events cannot become `delivered`, an ordinary retryable failure or
  a fresh deliverer launch. Add the `indeterminate_write` failure class with the reconcile-or-park playbook.
- Query the intended target and compare its state with the recorded operation's postcondition. For PR creation,
  match repository and head/base branches and the intended fields; for an edit, match the exact PR and the changed
  fields or their digest. Finding an existing PR or URL alone does not establish that an edit succeeded.
  Record `observed` only when that postcondition is established. An incomplete read, mismatch or ambiguous result
  retains `indeterminate` and parks the task with its journal reference. If the write is proven not to have taken
  effect, a person decides whether to allow one retry using the same key or keep it parked. A current mismatch alone
  is not proof of absence: another actor may have changed the resource after the write.
- Reuse an escalation issue only after matching its exact stable title and `harness-escalation` label in the intended
  repository and confirm it represents the intended escalation. For comments, match the intended issue, task and
  body hash against observable comments; for Linear moves, confirm the intended issue's target state.
- A Linear move to the same state may be safely repeatable if WP0 confirms it. Preserve the prohibition on closing
  tickets. PR lookup/update may already provide adequate reconciliation and can be excluded after qualification.
- An agent's shell write counts as observed only when the agent CLI reports that this one call succeeded and
  nothing ran after it in the same command (its redirections, a heredoc it reads and command substitutions in its
  words don't count). An agent CLI that reports no result for shell calls (Codex; OpenCode's version 1 plugin API)
  leaves each such write `indeterminate`: the harness has no observation, so the write parks like a lost reply. It is
  not treated as unobservable by design, because recording it as done would be the guessed effect this ADR rules out.
- The attempt is recorded before the agent CLI's permission check. When the CLI reports that it refused that call
  before running it (Claude Code's `PermissionDenied`, in auto mode), that call's own attempt is withdrawn. A denial
  at an interactive permission prompt reaches no hook, so its attempt stays parked until the user releases it.
- An edit that was observed (`gh pr edit` sets fields) may run again under the same key; a create may not.
- Only the agent CLI runs the hooks and only the user reconciles: agents may not run `harness.py hook`, load the
  journal's or the engine's modules from inline code, or copy them. A script an agent writes and runs stays beyond
  the shell checks, as for the harness's other records.
- Worker failure on a read-only judge/grill step retains its existing retry policy. Do not change verdict values or
  mistake a missing verdict for success.

WP0 stops the plan if every path is already safe, or narrows it to demonstrated gaps. A local key is correlation
evidence, not a claim that the remote service guarantees exactly-once execution.

## Alternatives considered
- Document current retry behavior only: insufficient for a demonstrated duplicate-write path.
- Treat a missing reply as failure and retry: confuses missing observation with absence of effect.
- Introduce a durable workflow runtime: disproportionate operational scope and still needs remote-write semantics.

## Consequences
- Resume logic must consult pending attempts; late results and reconciliation must preserve a truthful history.
- WP1 journals/outcomes precede WP2 reconciliation and WP3 coordinator handling; WP4 documents the behavior.
  Fixtures interrupt each unsafe path after effect and before recording, then prove that retry cannot duplicate it.
  Include failed attempt persistence (no external call), failed result persistence (pending attempt retained), an
  existing PR with stale edited fields (not observed), and a matching postcondition (durably observed before resume).
- With Codex or OpenCode's version 1 plugin API, every in-scope shell write parks until the user reconciles it, until
  WP2's read-based reconciliation exists.
- False indeterminate results can delay delivery. Reconciliation and explicit user decisions trade speed for avoiding
  guessed effects. Secrets and raw credentials do not belong in journal entries.
- Rollback requires explicit reconciliation or user release of outstanding attempts; removing the feature must not
  silently replay them. Approval, independent judgment and human merge remain in force.
