# ADR-017: Apply one computed task-dependency rule across start and selection paths

## Status
Proposed

## Date
2026-11-13

## Context
The [task-dependency plan](../research/2026-11-task-dependency-gate-plan.md) reports a code-read baseline where
Orca honors `(after: ...)` but shared start/selection paths appear not to. Missing references and cycles may also
go undiagnosed. That hypothesis needs WP0 runtime qualification; it is not a finding about every current path.

Pedro recorded option B on 10 November 2026 if WP0 finds no dependency gate outside Orca. The same hard rule
should apply in supervised sessions. Bad-reference validation warns for one release before becoming an error.

## Decision
Audit current behavior first. If the gap is confirmed, compute unmet dependencies through one shared rule using
the existing Markdown task parser, and use it consistently for start gates and task selection.

- `(after: ...)` and the existing supported colonless syntax remain the source. Do not introduce a stored blocked
  state or a second task database. A prerequisite is met when marked `[x]` in the authoritative task view.
- WP0 must choose and document a consistent base/worktree view before implementation, including a prerequisite
  merged on the base but absent from an older worktree. Gate and coordinator must not disagree about readiness.
- `start` refuses transition to WIP with unmet dependencies and names them. Agent edits that remove or change
  dependency notes are refused under the existing task-line guard; the user retains authority to change them.
- `ready_tasks`, `next` and `run` skip unmet pending tasks and expose the reason in dry-run output. Existing WIP
  work is warned about rather than retroactively blocked; preserve single-WIP behavior and supported worktree use.
- Validate missing/self references and cycles, naming task IDs and cycle paths. In the first release report these
  as warnings, then errors in the next release. Started/completed tasks with unmet prerequisites produce warnings.
  Record the transition in release documentation and qualify both phases.
- Report an all-waiting queue in the existing run summary. Do not invent automatic escalation writes or a new
  reporting channel merely because no task is ready.

WP0 stops the plan if equivalent coverage already exists outside Orca. Implementation does not change approval,
independent judgment or human merge, and dependency order is not proof of behavioral compatibility.

## Alternatives considered
- Keep dependencies Orca-only: the same backlog can start differently depending on its runner.
- Store a blocked flag: becomes stale when prerequisites finish; computed state avoids synchronization work.
- Move tasks to a JSON board or external tracker: adds a competing source of truth to solve a bounded gate gap.

## Consequences
- WP1 shared rule/start protection precedes WP2 selection and WP3 validation; WP4 documents the common behavior.
  Fixtures cover supervised/autonomous refusal, successful prerequisite completion, protected notes, selection,
  missing/self/cyclic references, warning-to-error migration and base/worktree agreement. Existing Orca tests stay green.
- Invalid existing backlogs need repair during the warning release; warn-first validation does not make an unmet
  dependency eligible for start.
- Roll back gate/selection changes through review if necessary. Task syntax and stored data require no migration.
