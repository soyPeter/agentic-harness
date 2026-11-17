# Proposed plan: a refactor change that edits tests is not low-risk

- **Status:** Proposed. Not accepted, not implemented, and not permission to change any gate, hook or test.
- **Date:** 2026-11-12 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-refactor-class-test-change-plan.md`. Work packages and evidence remain here; the decision is recorded in [ADR-015](../adr/ADR-015-refactor-test-change-risk.md).
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** ADR-002 (Change-Class ladder), [ADR-004](../adr/ADR-004-traceability-export.md) section on what the export does not show, `backbone/HOOKS.md` section "Tester and debugger".

## Why

ADR-002 defines `refactor` as "rename/extract with no behaviour change", and policy may approve it when it is low risk. A refactor that also edits tests can change the behaviour the tests pin down, and nobody is asked. That is the case where agent-written tests drift without anyone seeing it.

## Evidence and baseline

### External source (primary, read in full)

Matteo Vaccari, ["Tests as data"](https://martinfowler.com/articles/tests-as-data.html), martinfowler.com, 11 Nov 2026. He interviewed 26 developers who use coding agents heavily. They said they no longer trust their tests, because the AI refactors the tests together with the code. His table of expected file changes per task type says that a refactoring changes production code and does not change test data or the test runner. He suggests a CI check that verifies which files changed for the task type, and says hooks alone are not bullet-proof.

This is one practitioner's article with a small interview sample. It supports the rule as cheap and sensible. It does not show that the rule improves outcomes.

### Harness today (code read on 12 Nov 2026 at `dd2f9e9`, nothing run)

- `risk_reasons()` in `payload/owned/scripts/harness/lib/harness.py` (L2041) combines `class_risks`, `content_risks` and `class_mismatch`.
- `class_mismatch()` (L2058) only checks the `docs` class: a docs change that touches non-documentation files is a risk. There is no matching check for `refactor`.
- `content_risks()` (L2071) flags sensitive paths, risk terms, non-Accepted ADRs and too many files. It does not look at test paths.
- `HARNESS_TEST_PATHS` (L314) and `HARNESS_ACCEPTANCE_PATHS` (L368) already define what a test file is.
- With `HARNESS_TESTER` on, acceptance tests are fingerprinted and the judge refuses a finish if they changed (`HOOKS.md`). That protects acceptance files during one task. It does not cover a later refactor task that edits ordinary tests, and the tester is off by default.

Not checked: whether `HARNESS_RISK_PATHS` in any project already matches test paths, how often refactor specs are policy-approved in practice, and runtime behaviour. No test was run.

## Options

| Option | For | Against |
| --- | --- | --- |
| A. Do nothing | No change, no false alarms | Keeps the gap: a policy-approved refactor can rewrite tests unseen |
| B. Add a `refactor` branch to `class_mismatch`: a change to files matching `HARNESS_TEST_PATHS` or `HARNESS_ACCEPTANCE_PATHS` makes it not low-risk, so the user approves | Small, reuses existing paths, same shape as the docs rule, no new ceremony | Some honest refactors move or rename tests and will now need a person |
| C. Block refactor changes to tests outright | Strongest | Too strict: renames that touch test imports would fail; adds a hard stop the ladder does not have today |

Recommended: **B**. It escalates to a person and never blocks or approves anything on its own.

## Work packages

1. **WP1. Baseline (read-only).** Count recent tasks with `Change-Class: refactor` in this repo and the `triple` pilot, and how many touched test paths. Exit: a short table in the PR. If none touched tests, report that and ask whether to continue.
2. **WP2. Rule.** Extend `class_mismatch()` for `refactor` with the reason "Change-Class refactor doesn't cover a change to tests: <files>". Update ADR-002's table text and `HOOKS.md`. Depends on WP1 and Pedro's go-ahead.
3. **WP3. Tests.** Cases in `tests/run-tests.sh`: a refactor touching only code stays low-risk; a refactor touching a test file is escalated with the reason; a docs change is unchanged; a feature change is unchanged.

## Acceptance evidence

- The four WP3 cases pass in CI.
- `harness.py approve` on a refactor spec whose diff touches a test escalates instead of writing `Approved-by: policy:low-risk`.
- The receipt shows the new reason and suggests `risk:elevated`.

## Risks and rollback

- More refactors reach a person. Measured by WP1. If the noise is high, narrow the rule to acceptance paths only.
- Rollback: revert the one function branch and the doc lines. No data or state migration.

## Out of scope

Tests-as-data DSLs, mutation testing of recorded acceptance tests and oracles. Vaccari covers them, and they would address the ADR-004 gap that a named test does not prove it exercises the behaviour. They need their own proposal if wanted.

## Decisions needed

1. Accept option B, or keep A.
2. Should the rule cover all test paths or only acceptance paths.
3. Who owns WP1 (proposed: maintainer).
