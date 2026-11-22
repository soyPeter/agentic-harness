# Runtime dependency and lost-write audit

Date: 2026-11-15. Baseline: `aa5144781461463f5ca7736c4139c96ea91899e8`.
The release preparation commit `dad4dcf` arrived in the shared checkout during implementation; its release and
pin changes are separate from this work.

## Findings

Both gaps were reproduced in disposable installed projects, without external credentials or real service writes.

1. Task 9.3 appeared before task 9.2 and declared `(after: 9.2)`. Its spec was valid, fixture-approved and grilled.
   `next --json` selected 9.3 with step `start`; `start 9.3` exited 0 and marked it WIP although 9.2 was pending.
   The existing Orca-only selection check did not protect the shared start gate or `ready_tasks`.
2. A stand-in Linear transport accepted a comment and then raised a lost-reply error. Calling `post_comment`
   again made a second write: two accepted writes, no observed result. The baseline `linear_receipt` wrapper and escalation command were then run twice with accepted-but-lost replies: each made **two writes**. Inspection found the same absence of a
   durable pre-dispatch record in escalation issue creation, direct runner PR creation and deliverer shell writes.
   A PR read in an agent's instructions is insufficient to cover PR edits or guarantee recovery after process death.

## Implementation

A shared dependency function now checks the task list visible in the current worktree. The start gate refuses
unfinished prerequisites; default selection skips them; explicit `next` returns `blocked` with the prerequisite
IDs. Existing WIP tasks remain resumable. Missing references, cycles and work started early are warnings for this
release, including in doctor, spec-check and verify. Existing dependency notes cannot be changed by agents.
Orca still waits for prerequisites on its base checkout before allocating work, then checks the worktree through
the same `next` API. A reused stale worktree is synchronized before accepting a dependency-blocked result.

External writes now use a separate `writes.jsonl` journal beside the shared git-directory event log. It records
stable task/operation/target/intent keys, with content digests rather than command or comment bodies. The journal
uses an OS lock, flush/fsync and a durable pre-dispatch attempt. Failed attempt persistence sends no write.
A successful result must be persisted before the attempt clears. Corrupt journals fail closed.

Coverage: harness escalation issue creation, direct runner PR creation, deliverer shell PR create/edit and issue
create calls, and harness Linear receipt comments/state changes. Successfully observed harness writes reuse their
stored result. A process death, missing tool result, failed response or uncertain result persistence leaves an
unresolved attempt. Compound shell commands cannot establish a successful individual write merely by exiting 0.
The runner and Orca park before retrying or starting another worker when such an attempt exists.

## Recovery policy and limits

Recovery is deliberately conservative: one unresolved attempt parks scheduling and in-scope writes throughout the
repository, including linked worktrees. The journal is not a distributed lock for multiple clones and does not
control arbitrary scripts, uncontracted MCP tools or writes outside the existing harness paths. Credentials and
forge protection remain the authority boundary.

This implementation does **not** automatically infer a write's outcome from a PR URL, issue title, comment text
or current issue state. A person inspects the precise target and intended fields using the original run's transcript
and external history. Incomplete reads, stale PR fields or conflicting evidence leave the attempt parked.
`write-reconcile` lists pending attempts. After establishing the outcome, the person records either:

- `write-reconcile KEY --observed <evidence-reference>`: the intended write was confirmed; no repeated write.
- `write-reconcile KEY --allow-retry <evidence-reference>`: the person established absence and explicitly permits
  another attempt under that key. If the next attempt loses its reply, it parks again.

Reconciliation is user-only, like external delivery recording. Evidence is stored as a digest; preserve the actual
reference and investigation outside the journal. An observed resolution does not invent a judge pass, PR URL,
green CI result or delivery success. Existing gates must still establish those facts.

Operation-specific automatic reconciliation is deferred. The safety fix is reconcile-or-park, with human
reconciliation rather than automatic retry. The plans' product ADR statuses and the project's release pin are
not changed by this work. This note does not mark the existing gated audit tasks complete.

## Validation

`tests/test-runtime-recovery.py` covers dependency selection/start/refusal, dependency-note protection,
cycle/missing-reference warnings, durable attempts across process death, lost replies, result reuse, persistence
failures, journal corruption, explicit retry authorization, and tool-hook recovery. The escalation fixture accepts
a write but returns failure, then verifies that a second invocation makes no second external call.

Validation results:

- New runtime recovery suite: **19 tests passed**, including dirty-worktree retention and inline import protection.
- Factory contract: **31 tests passed**. Delivery policy with property coverage: **54 tests passed**.
  Triage labels with property coverage: **12 tests passed**.
- Full self-test with test requirements installed, `HYPOTHESIS_PROFILE=ci` and `HARNESS_TEST_JOBS=6`:
  **1,376 passed, 1 failed**. Output: `/tmp/harness-runtime-complete-tests.log`.
- The one failure is the existing Markdown parser property
  `BlockStartAgreement.test_the_gates_cut_the_spec_where_commonmark_does_or_refuse_it`.
  For `- <div>\n  text\n</pre>\n# Title\n`, the harness finds heading line 3 while CommonMark finds none.
  The exact counterexample was reproduced against both this working tree and baseline
  `aa5144781461463f5ca7736c4139c96ea91899e8`, producing the same mismatch:
  `([3], None, 4)` versus `([], None, 4)`. The Markdown parser was not changed by this work.
- `git diff --check` passes. Live-agent and live-container tests remain opt-in and were not run.

No live factory qualification is claimed.

## Check while merging v0.31.0 (2026-11-22)

A Codex review on 15 November raised two problems. This note said both were covered. Checked again through the hooks
and the runner, on the saved work (`d427a0f`) and on the merge with `main` at `9056f88`:

- **Importing `write_journal` directly: partly covered.** `import write_journal`, `from write_journal import ...`,
  `import_module("write_journal")` and code that executes the module's file are refused, in `python3 -c` and in a
  heredoc. `import os, write_journal`, a computed module name, `pkgutil.resolve_name`, and copying or linking
  `write_journal.py` are allowed. Run end to end, the comma form cleared a pending attempt and the same write was then
  allowed. `main`'s guard has the same comma-form gap for `harness` and `launcher`, but refuses copies of `harness.py`.
- **A parked worktree: covered for an indeterminate write.** `run --worktree` keeps the worktree with its uncommitted
  files when the session leaves an unresolved attempt, when a later run follows `write-reconcile --allow-retry`, and
  when the runner's own pull request loses its reply. Not covered, and the same on `main`: a task parked by an
  *escalation* in `run --worktree` without `--pr` loses its uncommitted files, because the worktree is removed by force.

Also found, in the work as it was saved:

- **The deliverer's documented pull request call parks the repository after it succeeds.** Its instructions pass the
  body as `--body "$(cat <<'EOF' ... EOF)"`. The journal doesn't count that as a sole call, so the successful result
  isn't observed: the next write is refused and `next` answers `blocked` until the user reconciles it. The existing
  deliverer tests now delete the journal between probes, so they don't show it.
- **Codex reports no result for a shell call**, and neither does OpenCode's version 1 plugin API, so every `gh pr
  create`, `gh pr edit` and `gh issue create` from them parks. So does a call the user declines at the permission
  prompt: the attempt is recorded before the prompt.
- **With `HARNESS_ESCALATE_GH=on` (default off), any failing `gh issue create`** (no login, no such label) parks the
  repository too, and the escalation command exits with an error after writing the BLOCKED note.

The merge also needed changes where `main` had gained redirection-free gh words (#100), eval replay (#92) and the
approval check at finish (ADR-007); the tests for them are in `tests/test-runtime-recovery.py`.
