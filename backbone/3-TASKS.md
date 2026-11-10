# 3. Tasks: agentic-harness

The task index. Each task has a spec in `backbone/specs/<id>.md` and goes through the pipeline in `8-WORKFLOW.md`. Only one task may be `[WIP]` at a time in a single worktree. Orca runs one worktree per task. Edit lines in place.

Wave 1 is ready. The lines below are the only ones the engine parses. Later waves are in a comment, so `orca` does not start them. Pedro uncomments a later line after he has read the audit it depends on and merged that pull request.

A worker reads the plan at the path on the line from the base branch. A path that is not on the base branch is not a plan yet.

## Milestones

| Milestone | Status | Description |
|---|---|---|
| M1 | planned | Wave 1 audits. Docs class. Policy can approve them. |

## M1: Wave 1 audits

- [ ] **Task 1.1: Dependency gate WP0 audit** (spec: backbone/specs/1.1.md) (plan: docs/research/2026-11-task-dependency-gate-plan.md)
- [ ] **Task 1.2: PR body WP1 audit** (spec: backbone/specs/1.2.md) (plan: docs/research/2026-11-pr-body-reviewer-opener-plan.md)
- [ ] **Task 1.3: Indeterminate outcome WP0 audit** (spec: backbone/specs/1.3.md) (plan: docs/research/2026-11-indeterminate-side-effect-outcome-plan.md)
- [ ] **Task 1.4: Delegation contracts P0 reuse map** (spec: backbone/specs/1.4.md) (plan: docs/research/2026-11-delegation-contracts-qualification-plan.md)
- [ ] **Task 1.5: Design challenge D0 reuse map** (spec: backbone/specs/1.5.md) (plan: docs/research/2026-11-design-challenge-agent-onboarding-plan.md)
- [ ] **Task 1.6: ADR-003, ADR-004 and ADR-005 follow-up triage** (spec: backbone/specs/1.6.md) (plan: docs/adr/ADR-003-sandbox-backends.md) (plan: docs/adr/ADR-004-traceability-export.md) (plan: docs/adr/ADR-005-verdict-attestations.md)
- [ ] **Task 1.7: Model change WP1 baseline on fixture tasks** (spec: backbone/specs/1.7.md) (plan: docs/research/2026-11-model-change-instruction-review-plan.md)

Task 1.6 triages the local-code follow-ups only. It does not build them. Task 1.7 runs on the fixture tasks in `tests/coefficiency` and `tests/colsum` and spends model tokens.

## Later waves (not started)

Commented out so the engine does not parse them. Each line keeps the task format and an `(after: ...)` note. The structural skeleton plan (`docs/research/2026-11-structural-skeleton-spec-plan.md`) is parked and has no task.

<!--
Wave 2. Small changes. 2.1 and 2.3 both touch next, run and delivery, so 2.3 waits for 2.1 as well as for 1.3.

- [ ] **Task 2.1: Dependency gate WP1 rule and start gate** (spec: backbone/specs/2.1.md) (after: 1.1) (plan: docs/research/2026-11-task-dependency-gate-plan.md)
- [ ] **Task 2.2: PR body WP2 template** (spec: backbone/specs/2.2.md) (after: 1.2) (plan: docs/research/2026-11-pr-body-reviewer-opener-plan.md)
- [ ] **Task 2.3: Indeterminate outcome WP1 journal and outcome** (spec: backbone/specs/2.3.md) (after: 1.3, 2.1) (plan: docs/research/2026-11-indeterminate-side-effect-outcome-plan.md)
- [ ] **Task 2.4: Model change WP2 checklist** (spec: backbone/specs/2.4.md) (after: 1.7) (plan: docs/research/2026-11-model-change-instruction-review-plan.md)
- [ ] **Task 2.5: ADR-004 follow-up 1 HTML matrix step in harness-verify** (spec: backbone/specs/2.5.md) (after: 1.6) (plan: docs/adr/ADR-004-traceability-export.md)
- [ ] **Task 2.6: ADR-005 follow-up 1 read the merged PR harness-change-approved label** (spec: backbone/specs/2.6.md) (after: 1.6) (plan: docs/adr/ADR-005-verdict-attestations.md)

Wave 3. Follow-on work packages. ADR-003 follow-ups 1, 4 and 8 are one task each.

- [ ] **Task 3.1: Dependency gate WP2 selection** (spec: backbone/specs/3.1.md) (after: 2.1) (plan: docs/research/2026-11-task-dependency-gate-plan.md)
- [ ] **Task 3.2: Dependency gate WP3 validation** (spec: backbone/specs/3.2.md) (after: 2.1) (plan: docs/research/2026-11-task-dependency-gate-plan.md)
- [ ] **Task 3.3: Indeterminate outcome WP2 reconcile** (spec: backbone/specs/3.3.md) (after: 2.3) (plan: docs/research/2026-11-indeterminate-side-effect-outcome-plan.md)
- [ ] **Task 3.4: Indeterminate outcome WP3 coordinator** (spec: backbone/specs/3.4.md) (after: 2.3) (plan: docs/research/2026-11-indeterminate-side-effect-outcome-plan.md)
- [ ] **Task 3.5: Model change WP3 lint report** (spec: backbone/specs/3.5.md) (after: 2.4) (plan: docs/research/2026-11-model-change-instruction-review-plan.md)
- [ ] **Task 3.6: PR body WP3 docs** (spec: backbone/specs/3.6.md) (after: 2.2) (plan: docs/research/2026-11-pr-body-reviewer-opener-plan.md)
- [ ] **Task 3.7: ADR-003 follow-up 1 DNS allowlist** (spec: backbone/specs/3.7.md) (after: 1.6) (plan: docs/adr/ADR-003-sandbox-backends.md)
- [ ] **Task 3.10: ADR-003 follow-up 4 gate on sandbox evidence** (spec: backbone/specs/3.10.md) (after: 1.6) (plan: docs/adr/ADR-003-sandbox-backends.md)
- [ ] **Task 3.11: ADR-003 follow-up 8 egress denials in the receipt** (spec: backbone/specs/3.11.md) (after: 1.6) (plan: docs/adr/ADR-003-sandbox-backends.md)
- [ ] **Task 3.8: ADR-005 follow-up 5 cosign check and predicate policy helper** (spec: backbone/specs/3.8.md) (after: 1.6) (plan: docs/adr/ADR-005-verdict-attestations.md)
- [ ] **Task 3.9: ADR-004 follow-up 3 reqifz with the receipt** (spec: backbone/specs/3.9.md) (after: 1.6) (plan: docs/adr/ADR-004-traceability-export.md)

Wave 4. Docs and qualification, only where an audit found a real gap. Delegation and design-challenge lines stay commented until that audit says there is a gap. ADR-006 is decided with the design-challenge work.

- [ ] **Task 4.1: Dependency gate WP4 docs** (spec: backbone/specs/4.1.md) (after: 3.1, 3.2) (plan: docs/research/2026-11-task-dependency-gate-plan.md)
- [ ] **Task 4.2: Indeterminate outcome WP4 docs** (spec: backbone/specs/4.2.md) (after: 3.3, 3.4) (plan: docs/research/2026-11-indeterminate-side-effect-outcome-plan.md)
- [ ] **Task 4.3: Delegation contracts P1 report** (spec: backbone/specs/4.3.md) (after: 1.4) (plan: docs/research/2026-11-delegation-contracts-qualification-plan.md)
- [ ] **Task 4.6: Delegation contracts P2 report** (spec: backbone/specs/4.6.md) (after: 4.3) (plan: docs/research/2026-11-delegation-contracts-qualification-plan.md)
- [ ] **Task 4.7: Delegation contracts P3 report** (spec: backbone/specs/4.7.md) (after: 4.6) (plan: docs/research/2026-11-delegation-contracts-qualification-plan.md)
- [ ] **Task 4.4: Design challenge D1 report** (spec: backbone/specs/4.4.md) (after: 1.5) (plan: docs/research/2026-11-design-challenge-agent-onboarding-plan.md)
- [ ] **Task 4.8: Design challenge D2 report** (spec: backbone/specs/4.8.md) (after: 4.4) (plan: docs/research/2026-11-design-challenge-agent-onboarding-plan.md)
- [ ] **Task 4.9: Design challenge D3 report** (spec: backbone/specs/4.9.md) (after: 4.8) (plan: docs/research/2026-11-design-challenge-agent-onboarding-plan.md)
- [ ] **Task 4.5: ADR-003 follow-up 5 run starts the sandbox** (spec: backbone/specs/4.5.md) (after: 1.6) (plan: docs/adr/ADR-003-sandbox-backends.md)
- [ ] **Task 4.10: ADR-003 follow-up 6 Orca workers inside a sandbox** (spec: backbone/specs/4.10.md) (after: 1.6) (plan: docs/adr/ADR-003-sandbox-backends.md)
- [ ] **Task 4.11: ADR-003 follow-up 9 sandbox for thin installs** (spec: backbone/specs/4.11.md) (after: 1.6) (plan: docs/adr/ADR-003-sandbox-backends.md)
-->

## Status markers

| Marker | Meaning |
|---|---|
| `[ ]` | Defined or being defined (spec, ADRs, grilling, approval) |
| `[WIP]` | Being built and judged; at most one task |
| `[x]` | Done: judge passed, Definition of Done met |
