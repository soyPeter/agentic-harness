# 8. Workflow and Definition of Done

Harness-owned. Project-specific additions go in `7-CONVENTIONS.md` under "Definition of Done additions".

## Orchestration loop

The main session orchestrates; the role agents do the work. Give each agent a self-contained request (task id plus anything not already in `backbone/`), because each one starts with a fresh context.

### Phase 1: Define

1. **Register:** add `- [ ] **Task <id>: <title>** (spec: backbone/specs/<id>.md)` to `3-TASKS.md`.
2. **Analyst:** "Write the spec for task `<id>`: `<the user's request>`." It produces requirements, Given/When/Then acceptance criteria, NFRs and open questions.
3. **Architect:** "Design task `<id>`." It writes the ADRs it needs and fills the spec's Architecture and Skills sections.
4. **Griller:** "Grill the spec for task `<id>`." Its verdict is recorded in `backbone/.verdicts/<id>.grill.json`.
5. **Grill the user:** relay the griller's **open** questions to the user verbatim — blockers and anything without a recommendation. A non-blocker question the griller recommended a fix for is settled by its recorder into the spec's Assumptions (`source: griller-recommended`) and is not asked. Have the analyst or architect apply the answers, then grill again. Repeat until the griller passes.
6. **Approval:** ask the user to review `backbone/specs/<id>.md` and add `Approved-by: <name> (<date>)` under `## Approval` themselves. In autonomous mode, run `python3 scripts/harness/lib/harness.py approve <id>` instead: it approves a low-risk spec or escalates the task (AGENTS.md section 7).

Check the state at any time with `python3 scripts/harness/lib/harness.py spec-check <id>`.

### Phase 2: Build

7. **Start:** change the task line to `- [WIP]`. The start gate checks the spec, the grill pass and the approval.
8. **Tester** (when `HARNESS_TESTER="on"`): "Write the acceptance tests for task `<id>`." It writes at least one test per AC in files matching `HARNESS_ACCEPTANCE_PATHS`, before any code exists, and they should fail. The harness records and fingerprints them in `backbone/.verdicts/<id>.tests.json`. The implementer may not change them, and the judge gate refuses to finish the task if they changed afterwards.
9. **Implementer:** "Implement task `<id>`." It loads the routed and spec-listed skills (the skill gate enforces this), then writes the code and the tests that mention the AC ids. It runs `HARNESS_BUILD_CMD` and `HARNESS_TEST_CMD`.

### Phase 3: Judge

10. **Judge:** "Judge task `<id>`." Its verdict is recorded in `backbone/.verdicts/<id>.judge.json`. On a fail:
    - **Debugger** (`HARNESS_DEBUGGER`, default `on`): "Diagnose the judge's failure of task `<id>`." It reproduces the failure, finds the root causes and writes a fix brief (`backbone/.verdicts/<id>.debug.json`), without changing anything. Each cause names its owner: the implementer (code), the tester (an acceptance test contradicts the spec), the analyst (the spec) or the user.
    - Give the brief to whoever owns each cause, usually the implementer, then judge again.
    - After `HARNESS_JUDGE_MAX_ROUNDS` fails, stop and take the findings and the brief to the user.

### Phase 4: Record and finish

11. **Scribe:** "Record task `<id>`." It adds memory entries and ADRs for emergent decisions.
12. **Finish:** change the task line to `[x]`. The judge gate requires a pass on the current code. Then commit the code, tests, spec, ADRs, verdicts and backbone updates together.
13. **Report** to the user:
    - what was built (REQ ids);
    - the judge's verdict, with each AC and its tests;
    - the ADRs added;
    - anything skipped or left open.

## Definition of Done

- [ ] The spec has requirements and Given/When/Then acceptance criteria, references its ADRs, passed the griller, and was approved by the user.
- [ ] The task line is `[x]` and no `[WIP]` is left.
- [ ] Every acceptance criterion is met and traced to a passing test that mentions its id, confirmed by a judge **pass** on the final code.
- [ ] The code follows the ADRs, the tech requirements, `4-KNOWLEDGE.md` (including NEVER DO) and `7-CONVENTIONS.md`.
- [ ] `HARNESS_BUILD_CMD` and `HARNESS_TEST_CMD` pass.
- [ ] Every new decision has an ADR, and `6-MEMORY.md` records any trap or lesson.
- [ ] Every item under "Definition of Done additions" in `7-CONVENTIONS.md` is met.
- [ ] One commit (or a series) holds the code, tests, spec, ADRs and `backbone/.verdicts/`, with a subject in `<type>(<scope>): <description>` form.

## Commits

- Types come from `HARNESS_COMMIT_TYPES` in `harness.conf`. Write the subject in the imperative mood, with no trailing period, within `HARNESS_SUBJECT_MAX` characters.
- **Scope:** the module or layer that changed (`feat(customer):`, `fix(api):`). Leave the scope out for cross-cutting changes. The commit-msg hook warns when a scope matches none of the staged paths.
- **Breaking changes:** mark them with `!` after the type or scope (`feat(api)!: remove v1 endpoints`), and add a `BREAKING CHANGE: <what breaks and how to migrate>` footer. An ADR should already cover the change.
- In the body, give what changed and why, and the task id. Reference issues (`Fixes #123`).
