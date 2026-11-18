# 5. Decisions: agentic-harness

The index of Architecture Decision Records. Project ADRs live in `backbone/adr/` and are the ones a spec's `ADRs:` line can name. Product ADRs live in `docs/adr/`. They are linked here so a spec can follow them. Do not copy them into `backbone/adr/`, and do not change their status. Pedro does that.

## Project ADRs

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](adr/ADR-001-adopt-agentic-harness.md) | Adopt the agentic harness | Accepted | 2026-11-10 |
| [ADR-002](adr/ADR-002-python-stdlib.md) | Python 3.8 and the standard library | Accepted | 2026-11-10 |

## Product ADRs

These are the harness's own decisions. A spec that needs one of them on its `ADRs:` line cannot see it: `spec-check` only looks in `backbone/adr/`. Cite ADR-002 there, and name the product ADR in the narrative. A Proposed product ADR on the `ADRs:` line would also block policy approval, once a copy existed.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](../docs/adr/ADR-001-thin-mode-plugin.md) | Thin mode plugin | Accepted | 2026-11-03 |
| [ADR-002](../docs/adr/ADR-002-change-class-ladder.md) | Change-class ladder | Accepted | 2026-11-06 |
| [ADR-003](../docs/adr/ADR-003-sandbox-backends.md) | Sandbox backends | Accepted | 2026-11-07 |
| [ADR-004](../docs/adr/ADR-004-traceability-export.md) | Traceability export | Accepted | 2026-11-07 |
| [ADR-005](../docs/adr/ADR-005-verdict-attestations.md) | Verdict attestations | Accepted | 2026-11-07, revised 2026-11-08 |
| [ADR-006](../docs/adr/ADR-006-external-agent-resource-admission.md) | External agent resource admission | Accepted | 2026-11-08 |
| [ADR-007](../docs/adr/ADR-007-evidence-closed-loop.md) | Evidence closed loop | Accepted | 2026-11-07, revised 2026-11-10 |
| [ADR-008](../docs/adr/ADR-008-harness-inside-agent-factory.md) | Harness inside the agent factory | Accepted | 2026-11-11, revised 2026-11-13 |
| [ADR-009](../docs/adr/ADR-009-delegation-contracts-qualification.md) | Delegation contracts and verification qualification | Proposed | 2026-11-13 |
| [ADR-010](../docs/adr/ADR-010-design-challenge-agent-onboarding.md) | Design comprehension and agent onboarding | Proposed | 2026-11-13 |
| [ADR-011](../docs/adr/ADR-011-indeterminate-side-effect-outcomes.md) | Indeterminate external writes | Proposed | 2026-11-13 |
| [ADR-012](../docs/adr/ADR-012-model-change-instruction-review.md) | Model-change instruction review | Proposed | 2026-11-13 |
| [ADR-013](../docs/adr/ADR-013-orca-self-rollout.md) | Pinned self-rollout in human-merged waves | Proposed | 2026-11-13 |
| [ADR-014](../docs/adr/ADR-014-pr-body-reviewer-opener.md) | Reviewer-first PR bodies | Proposed | 2026-11-13 |
| [ADR-015](../docs/adr/ADR-015-refactor-test-change-risk.md) | Refactor test-change risk | Proposed | 2026-11-13 |
| [ADR-016](../docs/adr/ADR-016-structural-skeleton-spec.md) | Park structural spec skeletons pending evidence | Proposed | 2026-11-13 |
| [ADR-017](../docs/adr/ADR-017-task-dependency-gate.md) | Shared task-dependency gate | Proposed | 2026-11-13 |
