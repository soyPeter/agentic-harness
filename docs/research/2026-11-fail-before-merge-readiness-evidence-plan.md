# Proposed plan: fail-before evidence for bug fixes, and scope reach in review

- **Status:** Proposed. Not accepted, not implemented, and not permission to change any gate, hook, agent or test.
- **Date:** 2026-11-21 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-fail-before-merge-readiness-evidence-plan.md`. No ADR yet. If Pedro accepts an option, the decision gets its own ADR and the work packages stay here.
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** [ADR-004](../adr/ADR-004-traceability-export.md) ("doesn't show that the test exercises the behaviour"), [ADR-008](../adr/ADR-008-harness-inside-agent-factory.md) (judge role in the factory), [ADR-015](../adr/ADR-015-refactor-test-change-risk.md) and the [refactor test-change plan](2026-11-refactor-class-test-change-plan.md) (its Out of scope asks for a separate proposal on tests that prove behaviour), `payload/owned/.claude/agents/judge.md` steps 4, 5 and 7, `payload/owned/backbone/HOOKS.md` sections "Tester and debugger" and "Reviewer". Not merged yet, so not linked: `2026-11-spec-counterexample-test-plan.md` on branch `soyPeter/spec-counterexample-delegation-plans-2026-11-19` (checks the spec; this plan checks the tests) and draft PR #99 (judge review hygiene).

## Why

The judge passes a task when every AC is traced to a test that names it and passes. ADR-004 already admits the gap: a passing test does not show that it exercises the behaviour. For a bug fix the cheapest proof is that the regression test fails on the code before the fix and passes after it. Nothing in the harness asks for that today.

A second gap is scope reach. The judge (step 7, Proportion) and the reviewer's correctness lens (blast radius) look at scope. `content_risks()` counts changed files against `HARNESS_RISK_MAX_FILES`. Neither says that a small diff can have a wide effect, such as a container-wide hook or a global default that covers cases the bug never touched.

## Evidence and baseline

### External sources (primary, read in full unless noted)

- Laura Kassovic, ["Testing Astra 6 v Fable 5.1 on a Gradle docs bug"](https://blog.gradle.org/two-agents-one-gradle-bug), Gradle blog, 9 Sep 2026. Two coding agents fixed the same one-line docs bug (issue #34751) under the same limits in Gradle's `gradle-eval` harness on Inspect AI. An LLM judge passed both. The reviewers would merge only one: it shipped a TestKit regression test and changed only the two source sets the bug affected. The other was three correct lines with no test and a `configureEach` that also covers future source sets. The smaller diff had the wider reach. The author calls it n=1: one run, one bug, one judge. The merged-candidate agent showed fail-before in a separate repro project. The post does not say its new test was run against the unfixed code.
- Lo Gullstrand Heander, Markus Borg et al., ["CodeHealth Predicts the Token Cost of Agentic Code Review"](https://arxiv.org/html/2610.21914), preprint, read in part, and Borg's [blog summary](https://codescene.com/blog/does-code-quality-affect-ai-token-costs), 26 Oct 2026. Pre-registered, 465 agent-authored PRs, 246 repos, a five-agent review-and-fix pipeline, three LLMs. Each CodeHealth point went with 3.5% to 6.1% fewer tokens. Median unhealthy (2.8) to median healthy (9.7) is 21.8% to 35.0%. PR size is the strongest driver and unrelated to CodeHealth. The effect is associational and absorbed by file size. CodeScene co-authored it and owns the metric.

These support the checks as cheap and sensible. They do not show the checks improve outcomes in this harness.

### Harness today (docs and code read on 21 Nov 2026 at `dad4dcf` on `release/0.31.0`, nothing run)

- `judge.md` step 4: runs `HARNESS_TEST_CMD` on the current code and checks each AC's test asserts its Then. No run on the base revision.
- `judge.md` step 7 and the `major` severity already cover code the task does not need. They do not name reach beyond the bug.
- `HOOKS.md` "Reviewer": the correctness lens covers "bugs, security, blast radius, missing tests".
- `content_risks()` in `harness.py` (about L2517) flags sensitive paths and more than `HARNESS_RISK_MAX_FILES` files (default 20). A pure count.
- `HARNESS_TESTER` (default off) fingerprints acceptance tests so they cannot change during the task. It does not run them against the base.
- ADR-002 has no bug-fix Change-Class. A fix is usually `feature`.

Not checked: how many recent tasks were bug fixes, whether their tests would have failed on the base, runtime cost of a second test run, and what the `triple` pilot's specs look like for fixes.

## Options

| Option | For | Against |
| --- | --- | --- |
| A. Do nothing | No change | Keeps the ADR-004 gap for the case where it is cheapest to close |
| B. Fail-before evidence for regression ACs, report-only first (recommended) | Closes the gap where a bug is the reason for the task; reuses the judge and receipt; one extra test run | Needs a way to mark a regression AC; some bugs cannot be reproduced in a test (docs rendering, timing) |
| C. B plus a hard gate | Strongest | A new stop before the baseline shows the noise level; flaky tests would block |

Scope reach and CodeHealth are add-ons to B, not separate options.

## Bounded package (if B is accepted)

1. **Marking.** A spec AC can carry a `Regression:` line naming the bug (issue link or one sentence). Opt-in, like `HARNESS_REQ_STYLE=ears`. No new Change-Class.
2. **Fail-before evidence.** For each regression AC, the harness runs the AC's named tests on the task's base revision in a throwaway worktree, then on the current code. It records both results in the judge pass: `failed` before and `passed` after is the evidence. `passed` before means the test does not catch the bug. A test that cannot run on the base (new file, missing fixture) is recorded as `not-run` with the reason. Report-only in the first release: the receipt shows the line under "Needs you", it blocks nothing.
3. **Judge text.** Step 4 adds: for a regression AC, read the fail-before record; a test that passed before the fix is a **major** finding (weak test), as weak tests already are.
4. **Scope reach.** Step 7 adds one sentence: flag changes whose effect reaches beyond the bug's blast radius (container-wide or global hooks, shared defaults, files the bug does not touch), even when the diff is small. Name the narrower placement in `fix`. Severity stays under the existing rules. The reviewer's correctness lens gets the same example in `change-review`. No line or file threshold.
5. **CodeHealth signal (optional, later).** If a project already has a code-health tool, the receipt may show the score of the touched files as a review-cost hint (expect more review rounds). Report-only. Never a gate, never a reason to refactor inside the fix task.

Unchanged: human spec approval, human PR merge, no GitHub auto-merge, independent judge as decider, `HARNESS_JUDGE_MAX_ROUNDS`, Change-Class rules, the receipt as the single review summary. No new ceremony or meeting.

## Work packages

1. **WP0. Baseline (read-only).** List the last 20 finished tasks in this repo and the `triple` pilot. Mark which were bug fixes and, for those, check by hand whether the named test fails on the base. Exit: a short table in the PR. If fewer than three bug fixes or every test already fails before, report and stop.
2. **WP1. Marking and record.** `Regression:` line parsing, base-revision run in a throwaway worktree, results in the judge pass and receipt. Depends on WP0 and Pedro's go-ahead.
3. **WP2. Judge and reviewer text.** Steps 4 and 7 of `judge.md`, one example in `change-review`. Docs only.
4. **WP3. Tests.** Cases in `tests/run-tests.sh`: a regression test that fails before and passes after is recorded as evidence; one that passes before is flagged; one that cannot run on the base is `not-run` with a reason; a task with no regression AC is unchanged.
5. **WP4 (optional).** CodeHealth hint, only if a project already runs such a tool.

## Acceptance evidence

- The four WP3 cases pass in CI.
- On one real bug-fix task, the receipt shows the fail-before line and the judge pass holds both runs, tied to the code fingerprint.
- A task without `Regression:` produces the same receipt as today.
- WP0 table attached to the PR.

## Risks

- Extra test time on every judge round for regression tasks. Limit the base run to the named tests.
- Flaky tests read as "passed before". Report-only first, so it can be seen before it blocks.
- Base checkout side effects. Use a throwaway worktree and never touch the working tree.
- Agents write `Regression:` lines nobody asked for. The analyst only adds one when the ticket is a bug.
- The reach rule turns into taste arguments. Keep it a finding with a named narrower placement, under the existing severities.
- CodeHealth is a vendor metric with a modest, associational effect. Keep it optional and never a gate.

## Rollback

Remove the `Regression:` parsing and the base run, and revert the judge and `change-review` lines. Recorded passes keep an extra field that nothing reads. No data or state migration.

## Out of scope

Mutation testing, tests-as-data, a bug-fix Change-Class, automatic merge, any CodeHealth threshold, and refactoring for health inside a fix task.

## Decisions needed (Pedro)

1. Accept B, keep A, or go straight to C.
2. How a regression AC is marked: a `Regression:` line on the AC, or a spec-level field.
3. Is a regression test that passes before the fix a **major** (fails the judge) or report-only at first.
4. Should the reach rule live in the judge, the reviewer's correctness lens, or both.
5. Include the CodeHealth hint (WP4) at all, and which tool if so.
6. Who owns WP0 (proposed: maintainer).
