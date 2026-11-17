# ADR-010: Qualify design comprehension and onboarding within the existing workflow

## Status
Proposed

## Date
2026-11-13

## Context
The [design-challenge and onboarding plan](../research/2026-11-design-challenge-agent-onboarding-plan.md)
asks whether a fresh reviewer can understand a design from its artifacts and whether a fresh integration session
can discover compatible setup guidance safely. A design can be understandable and correctly implemented while
its main product assumption remains untested. Existing DEFINE, griller, routing and judge controls may already
cover these cases; the plan has not audited runtime behavior.

Pedro's recorded 10 November 2026 decision limits current work to D0, the reuse/gap map. Implementation is
conditional on demonstrated gaps. [ADR-006](ADR-006-external-agent-resource-admission.md) governs any external
resource admission; [ADR-009](ADR-009-delegation-contracts-qualification.md) covers shared verification qualification.

## Decision
Use the existing DEFINE and review workflow to qualify artifact comprehension, bounded onboarding and
decision-relevant product evidence. Begin with D0 and add only uncovered fixtures or guidance.

- D1 gives a fresh reviewer the accepted artifact and references rather than the drafting conversation. Check goal,
  non-goals, rationale, constraints, criteria and unresolved questions. Keep required host/security policy present;
  record actual observable context and reads. Unsupported isolation is a limitation, not a simulated pass.
- Include missing, denied, contradictory, stale and injected references. A request to read is not proof of a
  successful read. Missing information is a finding; reviewers must not invent intent.
- D2 uses one authoritative entry point to versioned setup guidance, current catalog and routing. Prefer an internal
  non-production fixture. Discovery, installation, loading and observed successful setup are distinct claims.
  Changed bytes, incompatible versions, local modifications and revoked resources require explicit review.
  Reference-only research causes no installation, signup or external write.
- D3 reuses existing provenance and qualification cases. Distinguish initiating human, workload identity and
  delegated authority; unknown attribution stays unknown. Equivalent paraphrases and material requirement changes
  form paired tests, with independently checked expectations and evidence invalidation where applicable.
- The E0–E2 refinement distinguishes observed facts, owner choices, supported inferences and unsupported assumptions
  in existing artifacts. Consequential hypotheses link to outcomes and criteria with dated sources and an agreed
  reconsideration rule. Append disconfirming evidence without erasing history. Implementation success cannot
  establish demand or authorize a change to accepted intent.

These signals start advisory. No new spec format, approval gate, identity system or catalog is introduced.
Any helper or blocking behavior needs a separate reviewed scope after the audit. Simple changes need no mandatory
market study, mockup, external research or user experiment.

## Alternatives considered
- Keep existing artifacts and controls: the control and preferred endpoint if D0 finds sufficient coverage.
- Import an external workflow wholesale: duplicates lifecycle and creates update/authority risks without local proof.
- Add a separate design or product-value judge: duplicates existing review and increases ceremony before value is shown.

## Consequences
- D0 produces a revision-pinned map and expected outcomes. D1–D3 and E0–E2 follow the plan's dependencies only
  where uncovered; compare useful findings, false blocks, missing evidence and maintenance/review effort.
- Privacy, unobservable host context or unreliable fixtures may stop the work. BLOCKED and UNKNOWN remain distinct
  from product failure or success.
- Roll back additive examples/helpers through reviewed changes, preserving observations, core controls and receipts.
  No automatic policy promotion, accepted-spec rewrite, outreach, merge or deployment follows.
