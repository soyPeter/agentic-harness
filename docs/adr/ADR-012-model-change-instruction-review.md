# ADR-012: Review carried-over instructions when an agent model changes

## Status
Proposed

## Date
2026-11-13

## Context
The [model-change instruction plan](../research/2026-11-model-change-instruction-review-plan.md) describes how
rules written for earlier models may produce unnecessary stops, approval questions or cost on a newer one.
Its vendor examples motivate an evaluation, not a finding that this harness suffers those problems.
The documented baseline has no measured role/model drift.

Pedro recorded option C on 10 November 2026: a model-change checklist and read-only lint, backed by before/after
evaluation. The WP1 baseline uses fixture tasks in `tests/coefficiency` and `tests/colsum`; lint scope is
`payload/owned`, excluding `catalog/`. That earlier worker decision does not launch a worker through this ADR.

## Decision
Review carried-over instructions as part of a proposed model change, using measured behavior before changing rules.

- WP1 selects 5–10 representative recorded or fixture tasks across Change-Classes and measures role-level early
  stops, unnecessary approval questions, transient-error retries and token use on the current model.
- WP2 adds a checklist to an existing backbone document. Review the scope and reason of absolute rules, place
  routine no-approval actions beside approval rules, and inspect old token budgets, thinking limits, delegation
  pushes and ownership claims. Do not introduce ownership claims for client or regulated code.
- WP3 supplies a standard-library, read-only lint report over `payload/owned`: absolute instructions without a
  stated reason and drift between duplicated Claude/OpenCode role text. Findings are review prompts, not proof
  that an instruction is wrong. The script neither edits files nor acts as a gate.
- WP4 runs the same set on old and proposed models when a real model change occurs. A person decides each rule
  edit using the comparison and its reason. Vendor benchmark numbers do not set adoption thresholds.

Human merge, spec approval, independent judgment, risk escalation and secrets controls remain mandatory.
No blanket rewrite or automatic removal of protections follows a model upgrade.

## Alternatives considered
- Keep instructions unchanged without evaluation: avoids maintenance but misses model-dependent drift.
- Rewrite every rule for the latest model: risks weakening controls based on unverified vendor generalizations.
- Enforce lint findings as blockers or auto-fixes: textual heuristics cannot establish behavioral correctness.

## Consequences
- Model changes gain an evidence-backed review step and a small maintained evaluation set.
- A weak or absent signal is reported honestly; retain the current rules or stop at the checklist rather than
  manufacturing cleanup. Any edit remains a separately reviewed change.
- Fixture tests qualify the lint's expected reports and read-only behavior. Evaluation records include limitations
  and cost rather than promising improvement.
- Roll back the checklist or standalone reporter through ordinary reviewed changes; no runtime state migrates.
