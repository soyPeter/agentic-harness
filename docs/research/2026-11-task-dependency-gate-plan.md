# Proposed plan: one dependency gate for `(after: ...)` task lines (start, next, run and verify)

- **Status:** Proposed — not accepted, not implemented, and not permission to change any gate, hook, runner or test.
- **Date:** 2026-11-09 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-task-dependency-gate-plan.md`. Work packages and evidence remain here; the decision is recorded in [ADR-017](../adr/ADR-017-task-dependency-gate.md).
- **Decision authority (proposed role, unassigned):** repository maintainer; PR merge stays with the user as today.
- **Related:** `payload/owned/backbone/HOOKS.md` (Orca queue, start gate); `payload/owned/backbone/8-WORKFLOW.md` step 7; `payload/owned/AGENTS.md` sections 4 and 7; [ADR-002](../adr/ADR-002-change-class-ladder.md). Does not depend on [ADR-007](../adr/ADR-007-evidence-closed-loop.md) or [ADR-006](../adr/ADR-006-external-agent-resource-admission.md).

## Decisions (2026-11-10)

Pedro accepted the following defaults:

- Run the WP0 audit. If it finds no existing gate outside Orca, implement option B (one computed `blocked` state, `start` refuses a blocked task, and a bad reference is handled as below). If a gate already exists, stop the plan.
- Dependencies are a hard gate in supervised mode as well as in `run` and Orca, so behaviour does not depend on the runner.
- Bad references warn for one release, then become an error.

## Evidence and baseline

### External pattern (primary source, code read)

[XMihura/Kanvas](https://github.com/XMihura/Kanvas) at commit `e69958bb36c6fafdc80d35397a097165a60e0982` (v0.4.0, MIT), a task board shared by a human and coding agents. Read: `README.md`, `AGENTS.md`, `skill/SKILL.md`, `CHANGELOG.md` and the model/CLI/server sections of `kanvas.py`. Its dependency handling is **one rule used by every path**:

- `unmet_deps()` and `view_state()` (`kanvas.py` L370, L424) derive `blocked` from unfinished dependencies; blocked is computed, never stored.
- `cmd_start()` (`kanvas.py` L1025) refuses a blocked task with an error naming the unfinished dependencies (`"<ID> is blocked by unfinished <deps>"`), so a human session and an agent session get the same refusal.
- `problems()` / `find_cycles()` (`kanvas.py` L636, L578) report self-dependencies, dependencies on missing tasks and cycles as errors, and work started ahead of its dependencies as a warning; `check` exits 1 on errors.
- Covered by `test_agents_cannot_start_blocked_proposed_or_running_tasks` (`tests/test_kanvas.py` L1169). We ran the Kanvas stdlib suite once on a scratch box: 199 tests, 1 failure in an install-path test caused by the box's environment (`uvx` detection), not by the dependency logic. Browser tests may have been skipped; not checked.

This is a practitioner's small open-source tool, not a study. It is evidence that the pattern is cheap and testable, not that it improves outcomes.

### Harness baseline (code read at `origin/main` `ec6ac7706c023170afcb81a3b301c84620b46820`, not executed)

- `(after: 1.1, 1.2)` / `(after 1.1)` on a `3-TASKS.md` line is parsed by `task_dependencies()` (`payload/owned/scripts/harness/lib/harness.py` L5260). Its only caller found is `orca_command` (L5313), and the Orca coordinator honours it when filling slots (`coordinator.py` `start_next`, L610–L618). HOOKS.md documents dependencies only for the Orca queue.
- `start_problems()` (L2480), used by the start gate, checks BLOCKED, spec validity, grill pass/fingerprint and approval. **No dependency check was found.**
- `ready_tasks()` (L5435) returns WIP then pending, non-BLOCKED tasks in file order, with **no dependency filter**. `next` defaults to its first entry (L5072) and `harness.py run` queues it as is (L5727, L5746).
- No validation of `(after: ...)` references was found (missing task ids, self-reference, cycles). A grep for "cycle" in `harness.py` found nothing. In the coordinator, an unsatisfiable dependency ends as an outcome `"waiting for ..."` when nothing else runs, which is graceful but silent until a run.
- Tests: `tests/run-tests.sh` covers dependencies **for Orca only** (around L1684–L1700, including "9.3 waited for 9.2 although it was listed first").
- History: CHANGELOG entry "Dependencies written without a colon count" records that `(after 6.1a)` was previously ignored, so "the coordinator would have run tasks in parallel that must run one after another". That was a parser fix in the Orca path; it shows dependency mistakes do happen in real backlogs.

**Hypothesis to confirm in WP0, not a finding yet:** outside Orca (supervised orchestrator session, `next`, `run`, `run --worktree`), a task whose `(after: ...)` dependency is not `[x]` can be started, and a typo'd or circular dependency is never reported. Code was read, not run; there may be a check elsewhere that the grep missed.

## Problem

The harness enforces its workflow through gates every path shares (spec, grill, approval, judge). Task order is the exception: it is a scheduling hint for one runner rather than a gate. That makes the same backlog behave differently in supervised and autonomous modes, and lets work start on top of unmerged prerequisites, which the judge would only catch indirectly, if at all.

## Options

| Option | Benefit | Cost / risk |
|---|---|---|
| A. Keep dependencies Orca-only; document it | No change | Different behaviour per runner; silent bad references remain |
| B. One dependency rule in the shared gates (recommended) | Same refusal in every path; reuses the existing parser and gate style; small | Must not break the single-WIP default, parallel worktrees, or tasks merged on the base but not yet in the worktree |
| C. Move tasks to structured data (JSON board like Kanvas) or treat Linear "blocked by" relations as the source | Richer graph, UI | Second source of truth next to `3-TASKS.md`; conflicts with Linear as tool of record for tickets and with the Markdown backbone; out of proportion to the gap |

**Proposed: B**, conditional on WP0 confirming the gap. C is rejected for now; a one-way Linear relation import can be revisited later only if a real backlog needs it.

## Proposed behaviour (B)

1. **One function** decides unmet dependencies for a task: dependencies come from `task_dependencies()`; "met" means `[x]` (in the worktree's `3-TASKS.md`, and, where the coordinator already does so, on the base branch — WP0 decides which view each path uses so the two never disagree).
2. **Start gate:** `start_problems()` refuses `[WIP]` for a task with unmet dependencies: `Task 1.4 cannot start: it waits for 1.2, 1.3 (not [x]). Finish them first, or ask the user to remove the (after: ...) note.` Agents may not remove or edit an `(after: ...)` note on a line (mirrors the light-mark guard); the user may.
3. **`ready_tasks()` / `next` / `run`** skip tasks with unmet dependencies and say why in `--dry-run`, as Orca's dry run already does. A `[WIP]` task already in progress is not retroactively blocked; it is reported as a warning.
4. **Validation** in `spec-check`/`doctor`/verify: an `(after: ...)` reference to a missing task, to itself, or in a cycle is an **error**; a task `[WIP]`/`[x]` with an unmet dependency is a **warning**. Messages name the task ids and the cycle path.
5. **Escalation:** in autonomous mode, a queue where every remaining task waits on something not done is reported in the run summary (and the Monday update picks it up from there); no new status channel.

## Work packages

| WP | Scope | Depends on | Acceptance / evidence |
|---|---|---|---|
| WP0 Audit | Confirm the hypothesis by running `next`, `run --dry-run` and a supervised `[WIP]` edit on a fixture backlog with `(after:)` lines; list every place tasks are selected or started | — | Short findings note with commands and outputs at a pinned revision. **Stop here if a dependency check already exists outside Orca.** |
| WP1 Rule + gate | Shared unmet-dependency function; start-gate refusal; agent edits to `(after:)` notes refused | WP0 | Tests: starting 9.3 before 9.2 is refused in supervised and autonomous mode with the message above; after 9.2 is `[x]` it starts; an agent removing `(after: 9.2)` is refused; Orca tests unchanged and green |
| WP2 Selection | `ready_tasks`/`next`/`run` skip unmet tasks; dry runs show the reason | WP1 | Tests: `next` with 9.3 listed first returns 9.2; `run --dry-run` prints "waits for 9.2"; single-WIP default unchanged |
| WP3 Validation | Missing/self/cycle errors and started-early warnings in spec-check/doctor/verify | WP1 | Tests: `(after: 9.9)` (missing), `(after: 9.3)` on 9.3, and a 9.2↔9.3 cycle each fail with the ids named; `(afterwards, see notes)` still ignored |
| WP4 Docs | HOOKS.md start gate and queue, AGENTS.md section 4, 8-WORKFLOW step 7 | WP1–WP3 | Docs state one rule for every runner; CHANGELOG entry |

Out of scope: a board UI, a JSON task store, Kanvas itself, YOLO-style scoped autonomy, changes to approval/judge/merge, Linear writes. Linear stays the tool of record and the Monday update stays the single status report.

## Risks and rollback

- **Base vs worktree view:** a dependency merged on the base but not yet synced into a task worktree could be refused by the gate while Orca considers it met. WP0 must pick one definition and test both paths.
- **Existing backlogs:** projects with circular or stale `(after:)` notes will start failing verify; ship validation as a warning for one release, then an error (maintainer decides).
- **False sense of order:** a dependency gate orders tasks; it does not prove the prerequisite's behaviour is what the dependent task assumed. Judge and review stay the evidence.
- **Rollback:** revert the gate and selection changes; no stored data changes, `3-TASKS.md` syntax unchanged.

## Other Kanvas patterns considered (not part of this plan)

| Pattern (Kanvas source) | Disposition |
|---|---|
| Proposed → human-approved task intake (`README.md` states table; `kanvas.py` `cmd_propose`) | Covered: harness spec approval, grill and Change-Class gates are stricter |
| Human-only "done", agents finish to review with a required summary (`cmd_finish`, L1047) | Covered and stronger: receipts are built from verdicts and diff, not agent words; Linear never closed by the harness (`linear.py` `CLOSED_TYPES`) |
| "Waiting for you" question marker that survives the chat (`cmd_ask` L1114, `open_question` L540) | Mostly covered: griller questions in verdicts (`harness.py questions`), escalations and BLOCKED notes |
| YOLO: human grants autonomy for one dependency chain, one review at its end (`yolo_cover` L385) | Not proposed: it skips per-task review, which the harness never does; would need an ADR against ADR-002 if ever wanted |
| "Writing for the human" summary rules (`skill/SKILL.md`) | Supporting evidence for the local Proposed PR-body opener plan; no separate plan |
| Lock + atomic replace, ETag compare-and-swap for concurrent writers (`mutate` L317, `do_PUT` L2230) | Covered: harness already uses `fcntl` locks and `os.replace` |
| Agent identity is a free string (`actor()` L695; `--as human` is not refused) and the localhost API is unauthenticated | Lesson, not a pattern: a cooperative CLI is not an authority boundary. Supports the harness's hook + verify + CI re-check approach |

## Decisions needed (human)

Resolved on 2026-11-10. See Decisions (2026-11-10).
