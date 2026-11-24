# Research and plans

The plans, audits and research behind the [ADRs](../adr/README.md). Each document is dated; the status column repeats
its own header, and a plan's later findings are in its dated updates.

| Document | Kind | Status | ADR |
|---|---|---|---|
| [Agent-SDLC landscape](2026-11-agent-sdlc-landscape.md) | Research: compliance and traceability tools, agent sandboxes | Research only, no decision | Where ADR-003 to ADR-005 came from |
| [Brokered model credentials at the egress container](2026-11-brokered-credentials-egress-proxy-plan.md) | Plan for ADR-003 follow-up 2 | Proposed | None yet |
| [Delegation contracts, trajectories and integrated acceptance](2026-11-delegation-contracts-qualification-plan.md) | Plan | Proposed | [ADR-009](../adr/ADR-009-delegation-contracts-qualification.md) |
| [Design challenge and agent-readable onboarding](2026-11-design-challenge-agent-onboarding-plan.md) | Plan | Proposed | [ADR-010](../adr/ADR-010-design-challenge-agent-onboarding.md) |
| [Factory integration readiness and bounded pilot](2026-11-factory-integration-readiness.md) | Audit, 2026-11-13: the factory prerequisites in main and what a live pilot still needs | | [ADR-008](../adr/ADR-008-harness-inside-agent-factory.md) |
| [An indeterminate outcome for unobserved side-effecting writes](2026-11-indeterminate-side-effect-outcome-plan.md) | Plan | Proposed; implementation update 2026-11-15 | [ADR-011](../adr/ADR-011-indeterminate-side-effect-outcomes.md) |
| [Review carried-over instructions on every agent model change](2026-11-model-change-instruction-review-plan.md) | Plan | Proposed | [ADR-012](../adr/ADR-012-model-change-instruction-review.md) |
| [Run the open harness plans and ADR follow-ups through Orca](2026-11-orca-self-rollout-plan.md) | Plan | Accepted (its 16 defaults, 10 November 2026) | [ADR-013](../adr/ADR-013-orca-self-rollout.md) |
| [Reviewer-first pull request bodies](2026-11-pr-body-reviewer-opener-plan.md) | Plan | Proposed | [ADR-014](../adr/ADR-014-pr-body-reviewer-opener.md) |
| [A refactor change that edits tests is not low-risk](2026-11-refactor-class-test-change-plan.md) | Plan | Proposed | [ADR-015](../adr/ADR-015-refactor-test-change-risk.md) |
| [Runtime dependency and lost-write audit](2026-11-runtime-gap-audit.md) | Audit, 2026-11-15 | | [ADR-011](../adr/ADR-011-indeterminate-side-effect-outcomes.md), [ADR-017](../adr/ADR-017-task-dependency-gate.md) |
| [An optional code-like skeleton in the spec's Architecture section](2026-11-structural-skeleton-spec-plan.md) | Plan | Proposed, parked after WP0 | [ADR-016](../adr/ADR-016-structural-skeleton-spec.md) |
| [One dependency gate for `(after: ...)` task lines](2026-11-task-dependency-gate-plan.md) | Plan | Proposed; implementation update 2026-11-15 | [ADR-017](../adr/ADR-017-task-dependency-gate.md) |

A new plan or audit gets a row here in the same pull request.
