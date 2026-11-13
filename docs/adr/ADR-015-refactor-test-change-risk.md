# ADR-015: Escalate refactors that change tests for human approval

## Status
Proposed

## Date
2026-11-13

## Context
[ADR-002](ADR-002-change-class-ladder.md) allows policy approval of a low-risk `refactor`, defined as a
rename/extraction without behavior change. Editing tests with the implementation can also change the expected
behavior. The [refactor/test-change plan](../research/2026-11-refactor-class-test-change-plan.md) reports a
code-read gap at `dd2f9e9`: `class_mismatch()` checks docs changes but has no corresponding refactor/test rule.
That is a dated read, not runtime qualification or evidence about current projects' configured risk paths.

Tester fingerprints protect acceptance tests within a task when enabled; they do not establish that ordinary
tests in a later refactor stayed unchanged. The source article is motivation, not measured benefit for this harness.

## Decision
Propose option B: a refactor that changes a configured test path is not eligible for low-risk policy approval.
Route it through the existing risk/escalation and human approval flow rather than banning legitimate test changes.

- WP1 first counts recent refactor tasks and test changes in this repository and the Triple pilot. If none touched
  tests, report that result and obtain the maintainer's decision before implementation.
- Subject to that go-ahead, extend the existing class-mismatch check to changed paths matching
  `HARNESS_TEST_PATHS` or `HARNESS_ACCEPTANCE_PATHS`. The proposed scope is both sets; the maintainer must confirm
  all test paths versus acceptance-only before implementation.
- Report the reason with affected files: `Change-Class refactor doesn't cover a change to tests: <files>`.
  Do not write a low-risk policy approval for that case. Preserve the existing user-approved elevated-risk path.
- Expose the reason in the receipt and suggest `risk:elevated`. Update ADR-002's rule and HOOKS documentation
  only as part of the separately reviewed implementation, keeping this proposal distinct from accepted policy.
- A code-only refactor keeps current risk treatment. Docs and feature classification retain their existing behavior.

This ADR is a proposal for a policy refinement; neither the plan nor this draft records acceptance of option B.

## Alternatives considered
- Keep the current rule: avoids false alarms but can let a policy-approved refactor change its own oracle unseen.
- Forbid all test edits in refactors: prevents valid moves, import fixes and renames that a human can review.
- Cover only acceptance paths: a narrower fallback if the baseline shows excessive noise, but leaves ordinary-test
  changes outside the rule. It needs an explicit scope decision rather than silent narrowing.

## Consequences
- More legitimate refactors may need a person. Measure that cost through WP1 instead of claiming a proven benefit.
- WP3 qualifies code-only refactors, test-changing refactors, docs and feature cases, including approval refusal
  and the receipt reason. Reuse configured path matching rather than introducing another test registry.
- Roll back the risk branch and documentation through review if needed; no stored-state migration is required.
- Tests-as-data formats, mutation testing and oracle validation remain outside this bounded change.
