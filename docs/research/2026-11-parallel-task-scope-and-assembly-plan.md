# Proposed plan: declared write scope and an assembly check for parallel Orca tasks

- **Status:** Proposed. Not accepted, not implemented, and not permission to change the coordinator, any gate or test, or to start Orca.
- **Date:** 2026-11-19 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-parallel-task-scope-and-assembly-plan.md`. This is a narrow P2 slice of the [delegation contracts qualification plan](2026-11-delegation-contracts-qualification-plan.md), which [ADR-009](../adr/ADR-009-delegation-contracts-qualification.md) records. It adds no new ADR.
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** [ADR-009](../adr/ADR-009-delegation-contracts-qualification.md), [ADR-013](../adr/ADR-013-orca-self-rollout.md) (Orca rollout, "two available workers do not imply two safe writers"), [ADR-017](../adr/ADR-017-task-dependency-gate.md) (task dependency gate), [ADR-007 implementation notes](../adr/ADR-007-evidence-closed-loop.md#implementation-notes-2026-11-11), `orca/skills/agentic-harness/SKILL.md`, `payload/owned/scripts/harness/lib/coordinator.py`.

## Why

Two tasks can each pass every gate in their own worktree and still break the product when combined. Git merges them cleanly because they changed different files. One changed what a field means and the other relied on the old meaning. A worktree isolates files. It does not isolate what a change means.

The delegation plan already names this case in its qualification matrix ("individually green units combine into broken integrated behavior") and defines a unit contract with owned paths. Pedro's decision of 10 Nov 2026 (D13) allows building only where the audits show real gaps. This plan shows four such gaps in the current coordinator and proposes the smallest fix for each.

## Evidence and baseline

### External sources

- Jaroslaw Wasowski, ["Spec-Driven Development: Parallel AI Agents in One Codebase"](https://medium.com/@wasowski.jarek/spec-driven-development-parallel-ai-agents-in-one-codebase-spec-owner-delegation-contract-and-c3f859c0af00), Level Up Coding, 7 Nov 2026. Read in full on 19 Nov 2026. He proposes a delegation contract per session (owner, change boundary with a "leave alone" list, required interfaces, a checkable done condition, `escalate_if`), one owner per spec, an assembly test on the merge result because "green plus green can be red", hubs integrated last, and a list of cases where parallel work is not worth it. His main case is reported by GitHub about its own Copilot migration (15 child sessions, 140 files, 20 of them changed by more than one session, all hubs). Those numbers are GitHub's and were not checked.
- Ida Silfverskiöld, ["Building the Harness Around AI Coding Tools"](https://medium.com/@ilsilfverskiold/a-blueprint-for-agentic-coding-tools-c1e0e2ed797b), 29 Oct 2026, Level 4.1. Same semantic-conflict example for worktrees.
- KB summary: `20-Platform/Research/SDD/plt-SDD-Parallel-Agents-Delegation-Contract-Wasowski-2026-11.md` in the knowledge base, branch `soyPeter/medium-harness-spec-notes-2026-11-19`.

### What the harness already covers

| Contract field or rule in the article | Harness today | Status |
| --- | --- | --- |
| One owner per spec, who settles intent | The user's `Approved-by:` line. An approved spec is frozen for agents | Covered |
| Protect the oracle from the agent | Tester-written acceptance tests are fingerprinted. Judge passes go stale when the spec or code changes (ADR-007 P1 slice) | Covered |
| `done_when`, a checkable state | Acceptance criteria, the judge, the lenses and the Definition of Done | Covered |
| `required_interfaces` | The spec's Tech requirements (API contracts). The griller checks them | Covered in prose |
| `escalate_if` | `harness.py escalate`, griller questions, Orca questions routed to an analyst | Covered |
| Decisions beyond the session's branch need consent | Workers never merge or mark `[x]`. The deliverer can't merge. Agents can't start Orca | Covered |
| Dependency order | Orca honours `(after: ...)`. ADR-017 extends it beyond Orca | Covered or planned |
| Assembly test after combining work | Only after a merge **conflict** | **Gap 1** |
| Assembly test in PR delivery | Not audited | **Gap 2** |
| Do not run two writers on one hub | Left to the person who picks the wave (ADR-013) | **Gap 3** |
| A "leave alone" list a check can read | "Out of scope" is prose | **Gap 4** |

### The four gaps (code read on 19 Nov 2026 at `origin/main` `4767350`, nothing run)

1. **No tests after a clean merge.** `merge()` (`coordinator.py` L644) runs `git merge --no-ff` into the base. If it succeeds, the task is marked merged with no test run. Tests run on the combined tree only in `finish_integration()` (L776, test run at L791), which runs only after `integrate()` (L745). `integrate()` runs only when the merge left code conflicts. So with `--parallel 2 --merge`, a second task that merges cleanly onto a base that gained the first task is never tested in combination. The next task's own worktree may catch the break later, and blame the wrong task.
2. **PR delivery checks the branch head.** The installed `harness-verify` workflow checks out `github.event.pull_request.head.sha`. That is right for its gate checks. Whether a project's own CI tests the merge result, and whether the forge requires branches to be up to date before merge, was not audited (ADR-007 notes say forge rules were not checked). ADR-013 runs waves as parallel PRs that Pedro merges. Two PRs that pass alone can merge into a red main.
3. **No check against parallel writers on one file.** `start_next()` (L610) fills free slots with any queued task whose dependencies are done. It does not look at which files tasks will touch. `HARNESS_ALLOW_PARALLEL_WIP` controls only whether more than one task may be `[WIP]`.
4. **No machine-readable scope.** The spec template's "Out of scope" section is free text. `risk_reasons()` (`harness.py` L3318) checks class mismatch, sensitive paths and file counts. It does not compare the files a task changed with anything the spec declared.

## Options

| Option | For | Against |
| --- | --- | --- |
| A. Do nothing. Keep serialising by human judgment (ADR-013) | No code. Valid if waves are always picked with care | Gap 1 is silent even with care. Relies on memory for hubs |
| B. Assembly check only. Before merging a finished task into a base that moved, merge the base into the task branch and run the tests there (the existing `integrate` path, used always instead of only on conflict). Document the PR-mode rule | Small. Reuses `integrate()` and `finish_integration()`. Closes the silent case | Does nothing to prevent two writers on a hub, so conflicts and rework still happen |
| C. B plus declared scope. Add optional owned paths and a "leave alone" list per task. Orca does not run two tasks in parallel when their owned paths overlap or both touch a configured hub. After the build, files changed in a "leave alone" path become a risk reason, report-only first | Prevents most hub collisions before they cost a run. Gives the article's contract a field the harness can check | New task or spec syntax. Paths approximate meaning: shared contracts can still couple tasks with disjoint paths |
| D. A full merge queue or speculative-merge service in the coordinator | Strongest ordering | A new control plane. ADR-009 rejects adding a scheduler by default |

Recommended: **B now, C after B's evidence**. B closes the only silent failure. C needs a decision on syntax (decision 2) and is worth it only if WP0 shows hub collisions happen in real waves.

## Proposed behaviour

**Assembly check (B).** When `--merge` is on and the base moved since the task's worktree was created, Orca merges the base into the task branch first and runs `harness.py test-run` in the task worktree. Only a green run lets the task merge into the base. A red run escalates the task with the failing output, as `finish_integration()` already does for conflicts. The base never receives an untested combination. When the base did not move, nothing changes.

**PR mode rule (B, docs).** In the Orca skill and ADR-013: when two wave PRs touch the same module, merge one, then update the other branch and wait for its CI before merging it. Recommend that projects turn on "require branches to be up to date" or a merge queue in their forge. The harness does not change forge settings.

**Declared scope (C).** Proposed form, to be settled in decision 2:

- `Owned-paths:` and `Leave-alone:` lines in the spec header, as globs. They sit inside the spec fingerprint, so the user approves them with the spec. Or a `(touches: ...)` note on the task line in `3-TASKS.md`, which only the user may change, next to `(after: ...)`.
- `HARNESS_HUB_PATHS` in `harness.conf`: files most of the system depends on. Empty by default.
- `start_next()` skips a ready task while a running task's owned paths overlap its own, or both touch a hub. The task waits. It does not fail. `orca --dry-run` prints the reason. A task with no declared scope runs as today.
- Hubs last: among ready tasks, those that touch a hub start after those that do not.
- After the build, a changed file that matches `Leave-alone:` adds a risk reason ("changed a path the spec leaves alone: <files>"). Report-only for one release, then it escalates through the existing risk path.

**When not to parallelise (docs).** Add to rule 8 of the Orca skill, from the article: do not run tasks in parallel when the work is sequential, when they write the same hub, when no test can check the combined result, or when review can't keep up. ADR-013's D6 default of two workers stays.

Agents still never start Orca. Every change here runs inside the coordinator, which only the user starts.

## Work packages

1. **WP0. Reproduce (tests first, no fix).** With `tests/fake-orca.py`, add a fixture where two tasks change different files, each passes alone, and the combination fails a test. Show that the current `--merge` path merges both and reports success. Count, from the last two Orca run digests and the wave PRs, how many tasks touched the same files. Exit: the failing test and a short table. **Stop rule:** if the fixture already fails safely on current main, report that and close gap 1.
2. **WP1. Assembly check (B).** Route every merge onto a moved base through the integrate path with a test run. Keep the cap of 3 integrations. Depends on WP0 and Pedro's go-ahead. Serialise with any ADR-017 work in `coordinator.py`, as ADR-013 requires for shared coordinator code.
3. **WP2. PR mode docs (B).** The rule above in `orca/skills/agentic-harness/SKILL.md` and an implementation note in ADR-013. No workflow change.
4. **WP3. Declared scope (C).** Only after decision 2 and WP0's collision count. Parse the chosen syntax, add `HARNESS_HUB_PATHS`, the `start_next()` check, the dry-run reason and hub-last ordering.
5. **WP4. Leave-alone risk reason (C).** Add the reason in `risk_reasons()`, report-only first. Same shape as the `docs` class mismatch.
6. **WP5. Tests:**
   - the WP0 fixture now escalates instead of merging;
   - a task merging onto an unchanged base runs no extra test;
   - two tasks with overlapping owned paths never run at the same time, and the second starts after the first settles;
   - a task without declared scope runs as today;
   - a leave-alone change shows as a risk reason;
   - existing Orca and `test-impact-invalidation.py` tests stay green.

## Acceptance evidence

- The WP0 fixture fails on current main and passes after WP1: the combination is tested and the task escalates with the test output.
- `orca --dry-run` shows "waiting: shares <path> with task <id>" for an overlapping pair after WP3.
- The Orca run digest lists assembly checks run and their results.

## Risks and rollback

- **Slower waves.** One more test run per task that lands on a moved base. Serialised hub tasks lose some parallelism. That is the intended trade at two workers.
- **Paths miss meaning.** Disjoint paths can still share a contract, a database or an API reading. The assembly check is the backstop. Contract tests owned by the spec owner remain the project's job.
- **Syntax churn.** A new spec or task-line field touches `spec-check`, the fingerprint and the guards. Decision 2 picks one form. WP3 waits for it.
- **Overlap with ADR-017.** Both touch task selection. Run them one after the other.
- **Rollback:** revert WP1 to restore the conflict-only integrate path. Scope lines are optional and ignored when absent. Recorded events stay readable.

## Out of scope

- A merge queue, scheduler or second task database (rejected in ADR-009).
- Changing forge settings or branch protection on any repository.
- Semantic diffing of API contracts.
- Automatic merges into main. Pedro merges.
- More than the current two parallel workers (ADR-013 D6).

## Decisions needed

1. Accept B now (recommended), B and C together, or A.
2. Where declared scope lives: spec header lines (approved with the spec) or a `(touches: ...)` note on the task line (owned by the user like `(after: ...)`).
3. Should a red assembly check escalate at once (proposed) or start one implementer worker to fix the combination first, as `integrate()` does for conflicts?
4. The default for `HARNESS_HUB_PATHS` in this repository. Proposed: `payload/owned/scripts/harness/lib/harness.py`, `payload/owned/scripts/harness/lib/coordinator.py` and `CHANGELOG.md`.
5. Who runs WP0 (proposed: maintainer, or an Orca worker started by Pedro).
