# Architecture decision records

The harness's own decisions (product ADRs). Each ADR's `## Status` line is the decision's status, which only the
maintainer changes; this table is the one list of them. A status says nothing about implementation: an Accepted ADR
can have follow-ups that aren't built, and a Proposed one can have parts in main: ADR-011's write journal with
reconcile-or-park and ADR-017's task-dependency gate shipped in 0.32.0, and both ADRs are still Proposed.

This repository's own enrollment keeps two project ADRs in [backbone/adr/](../../backbone/adr/), indexed in
[backbone/5-DECISIONS.md](../../backbone/5-DECISIONS.md), which also says how a spec cites a product ADR.

| ADR | Decision | Status | Date | Plan or research |
|---|---|---|---|---|
| [ADR-001](ADR-001-thin-mode-plugin.md) | Thin mode: the engine ships as an agent plugin, the project keeps its state and a version pin | Accepted | 2026-11-03 | |
| [ADR-002](ADR-002-change-class-ladder.md) | Change-class ladder and human PR merge | Accepted | 2026-11-06 | |
| [ADR-003](ADR-003-sandbox-backends.md) | Sandbox backends and sandbox evidence | Accepted | 2026-11-07 | [Agent-SDLC landscape](../research/2026-11-agent-sdlc-landscape.md) |
| [ADR-004](ADR-004-traceability-export.md) | Traceability export from the receipt's evidence: ReqIF, needs.json and an HTML matrix, derived and one-way | Accepted | 2026-11-07 | [Agent-SDLC landscape](../research/2026-11-agent-sdlc-landscape.md) |
| [ADR-005](ADR-005-verdict-attestations.md) | Signed verdict attestations in CI | Accepted | 2026-11-07, revised 2026-11-08 | [Agent-SDLC landscape](../research/2026-11-agent-sdlc-landscape.md) |
| [ADR-006](ADR-006-external-agent-resource-admission.md) | Admit third-party agent setup resources explicitly | Accepted | 2026-11-08 | [Design challenge and onboarding](../research/2026-11-design-challenge-agent-onboarding-plan.md) |
| [ADR-007](ADR-007-evidence-closed-loop.md) | Evidence-driven closed loop | Accepted | 2026-11-07, revised 2026-11-10 | [Delegation contracts](../research/2026-11-delegation-contracts-qualification-plan.md) |
| [ADR-008](ADR-008-harness-inside-agent-factory.md) | The harness as the gate inside the agent software factory | Accepted | 2026-11-11, revised 2026-11-13 | [Factory integration readiness](../research/2026-11-factory-integration-readiness.md) |
| [ADR-009](ADR-009-delegation-contracts-qualification.md) | Qualify delegation contracts and verification before expanding execution | Proposed | 2026-11-13 | [Delegation contracts](../research/2026-11-delegation-contracts-qualification-plan.md) |
| [ADR-010](ADR-010-design-challenge-agent-onboarding.md) | Qualify design comprehension and onboarding within the existing workflow | Proposed | 2026-11-13 | [Design challenge and onboarding](../research/2026-11-design-challenge-agent-onboarding-plan.md) |
| [ADR-011](ADR-011-indeterminate-side-effect-outcomes.md) | Reconcile indeterminate external writes before retrying | Proposed | 2026-11-13 | [Indeterminate outcomes](../research/2026-11-indeterminate-side-effect-outcome-plan.md) |
| [ADR-012](ADR-012-model-change-instruction-review.md) | Review carried-over instructions when an agent model changes | Proposed | 2026-11-13 | [Model-change review](../research/2026-11-model-change-instruction-review-plan.md) |
| [ADR-013](ADR-013-orca-self-rollout.md) | Roll out harness changes through pinned gates and human-merged waves | Accepted | 2026-11-13, accepted 2026-11-23 | [Orca self-rollout](../research/2026-11-orca-self-rollout-plan.md) |
| [ADR-014](ADR-014-pr-body-reviewer-opener.md) | Keep human-action items visible in reviewer-first PR bodies | Proposed | 2026-11-13 | [PR body opener](../research/2026-11-pr-body-reviewer-opener-plan.md) |
| [ADR-015](ADR-015-refactor-test-change-risk.md) | Escalate refactors that change tests for human approval | Proposed | 2026-11-13 | [Refactor test change](../research/2026-11-refactor-class-test-change-plan.md) |
| [ADR-016](ADR-016-structural-skeleton-spec.md) | Keep structural spec skeletons parked pending relevant evidence | Proposed | 2026-11-13 | [Structural skeleton](../research/2026-11-structural-skeleton-spec-plan.md) |
| [ADR-017](ADR-017-task-dependency-gate.md) | Apply one computed task-dependency rule across start and selection paths | Proposed | 2026-11-13 | [Task dependency gate](../research/2026-11-task-dependency-gate-plan.md) |

A new product ADR gets a row here in the same pull request.
