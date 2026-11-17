# Factory integration readiness and bounded pilot

Date: 2026-11-13. Source revision: `11215d8e4fd5772cdfff93d7b48801a6537def2a`.
PR #90 merge: `dbc83ff9c406124d197143c5102b4e2517f94b85`.
Related: [ADR-008](../adr/ADR-008-harness-inside-agent-factory.md),
[ADR-011](../adr/ADR-011-indeterminate-side-effect-outcomes.md),
[rollout plan](2026-11-orca-self-rollout-plan.md).

## Result

The harness-side prerequisites from PR #90 are in main. They must not be queued for implementation again.
The live factory pilot is blocked on a release containing them, a reviewed project pin/configuration, and
factory-side evidence. Local fixture tests qualify the source implementation only; they do not prove a live
worker, independent agent judgment, external delivery, branch protection or end-to-end factory behavior.

No release, pin, autonomy setting or credential was changed. No real agent run, factory deployment, external
message, issue creation or PR write was performed for this audit.

## Release and installation evidence

- `VERSION` and this project's `backbone/.harness-lock.json` still name `0.30.0`.
- The pin and remote tag `v0.30.0` resolve to `5b754dcd19fec8adfad234cf306954df91d88fe3`.
- `git merge-base --is-ancestor dbc83ff v0.30.0` returns 1: that tag does not contain PR #90.
  Inspection of its engine finds none of the contract/intake/delivery-plan entry points or task-budget/delivery-key
  settings added by that PR. No newer remote version tag was listed on 13 November.
- GitHub's release listing reports `v0.26.1` as Latest; `gh release view v0.30.0` reports no release object.
  This is separate from the existing v0.30.0 tag: the thin launcher fetches the tag and verifies its commit, so the
  missing release object alone is not the blocker. The missing prerequisite code in the pinned tag is.
- No default engine cache exists at `~/.agentic-harness/engines/` on this machine. The deployed factory's cache,
  plugin version, project pin and effective settings were not inspected.
- Local project settings have review on, delivery `on` and profile `triple`. They describe the existing repository
  rollout, not the proposed credential-free factory lane. An external pilot needs a separately reviewed configuration
  using a capable pinned engine, external delivery and an effective no-merge profile.
- The pushed revision's [self-test CI run](https://github.com/soyPeter/agentic-harness/actions/runs/43487304488)
  was completed with conclusion `success` when read. This is CI evidence for that revision, not a release or deployment.

## Reuse map

| Requirement | Source/evidence | Disposition |
|---|---|---|
| Versioned command/event contract and task locks | `tests/test-factory-contract.py`; ADR-008 implementation notes | Implemented in main; qualify deployed adapter compatibility |
| Frozen source provenance, dedupe and untrusted intake handling | `tests/test-intake.py` | Implemented; retain delegation/design audits for uncovered authority and composition cases |
| Whole-task budget accounting across resumes | `tests/test-task-budget.py` | Implemented as defence in depth; external enforcement and unreported subscription usage remain unqualified |
| Credential-free external delivery plan and signed records | `tests/test-external-delivery.py` | Implemented on harness side; real trusted clone, key custody and exact-head verification need pilot evidence |
| Generic no-merge profile | `tests/test-no-merge-profile.py` | Implemented; dedicated identity and actual forge protection remain deployment prerequisites |
| DEFINE and independent judge/review lenses | Existing workflow and role agents | Reuse; fixture stand-ins do not establish independent live execution |
| Risk-triggered security reviewer and model evidence | ADR-008 follow-ups 5 and 6 | Pending; do not route a flagged task past an unavailable reviewer |
| PR review feedback, KB drafts and janitor lifecycle | ADR-008 follow-ups 7–9 | Pending; no automatic cleanup or knowledge promotion in the first pilot |
| Lost-reply recovery | ADR-011, task 1.3 audit | Still open: delivery signatures do not establish durable write attempts or operation-specific reconciliation |
| Common dependency start/selection gate | `start_problems` and `ready_tasks` in the source revision | No shared dependency check found in this scoped read; retain task 1.1 runtime audit |
| ADR-004 matrix workflow and ReqIF archive | `tests/test-trace-workflow.py`, `tests/test-trace-export.py`, `payload/owned/.github/workflows/harness-verify.yml` | Already in main; retire duplicate build tasks 2.5 and 3.9; deployment/signing checks stay in task 1.6 |

ADR-005 follow-up 1 (merged-PR label handling) remains in triage: a label check on the PR workflow is not proof that
the push attestation reads the merged PR's label. Other original audits remain open; this scoped map does not
claim to complete their independent reviews or mark their task lines done.

## Local qualification

The five existing factory test files were run from the source revision with `python3 -B tests/test-<name>.py` and
`HYPOTHESIS_PROFILE=ci`. They install into temporary repositories, use stand-in agents and mocked external services,
and clean up their owned fixtures. Setup includes synthetic approvals/verdicts and disabled review/delivery in
shared fixtures; these are test inputs, not permission to weaken a real pilot's gates.

All five test files exited 0: **90 tests passed**, no failures.

| Test file | Tests | Result |
|---|---|---|
| `test-factory-contract.py` | 31 | OK |
| `test-no-merge-profile.py` | 9 | OK |
| `test-task-budget.py` | 14 | OK |
| `test-intake.py` | 17 | OK |
| `test-external-delivery.py` | 19 | OK |

Captured unittest summaries:

```text
factory-contract: Ran 31 tests in 83.808s — OK
no-merge-profile: Ran 9 tests in 13.200s — OK
task-budget: Ran 14 tests in 17.462s — OK
intake: Ran 17 tests in 12.783s — OK
external-delivery: Ran 19 tests in 24.695s — OK
```

Hypothesis and markdown-it-py are absent from this local Python environment. Optional property coverage is not
claimed. The full self-test was not rerun locally; the CI result above is separate evidence. No new tests were
written for this documentation audit.

## First live pilot: one delegated documentation change

Use a disposable, enrolled non-production project and one explicitly delegated issue to add a short troubleshooting
example in one Markdown file. The actual repository, issue, permitted file and project owner must be named before
the run; none is inferred from the external factory image. No code, CI, infrastructure, billing, security path or
production data is in scope. One task, one lane and one PR; self-assignment stays off.

### Entry conditions

1. Release an immutable engine version containing PR #90 after release checks pass. The maintainer reviews the
   version/pin change, plugin alignment and doctor result. Do not relabel v0.30.0 or substitute source main for the
   pinned verifier. Keep existing shims that local conventions require.
2. Name the disposable project and request. Confirm its deployed engine serves contract v1 and its effective
   configuration has spec/skill/judge/review gates on, external delivery and a no-merge profile. Run doctor and a
   dry run through that project's pinned launcher; preserve their actual outputs.
3. Qualify a dedicated factory identity without merge/admin/bypass rights, required base-verifier CI and human
   approval. Keep push credentials and the delivery signing key outside the lane. The shared human login from
   the image is not an acceptable substitute. Do not print keys or tokens into evidence.
   The trusted adapter must supply the same nonempty `HARNESS_DELIVERY_KEY` to `delivery-record` and every
   authoritative `next <id> --json` call. It must refuse to read authoritative delivery status when that key is
   unavailable, without falling back to an unkeyed call: `next` otherwise accepts unsigned records. Lane-side
   progress reads cannot establish delivery completion. Inject the key only into those trusted command processes,
   never into the lane, an agent-launch process or the environment of `run`, `orca` or `ci-judge`.
   Before the pilot, qualify the deployed adapter in an isolated fixture: an unsigned record and a record with an
   invalid signature for the current task/head cannot produce `done`; a valid signed failure remains a failure;
   and a valid signed delivery for that task/head can produce `done`. An absent key must stop the adapter before
   an authoritative read. Keep these results distinct from the earlier harness-only test results above.
4. Establish an independently observable judge and all three review lenses on the task's actual revision. Advisor
   consultation cannot fill those roles. Record actual roles/context/model where observable and state any limits.
5. Establish bounded worker/Front usage and advisor spending across resumes. The local mutable ledger alone is
   insufficient. Verify the applicable task/day limit and supported stop procedure without spending to reach it.
6. Test the factory adapter's safe reads and delivery reconciliation in a fixture. If an external write has an
   uncertain outcome, park and reconcile through a person; do not blindly relaunch the write. Without qualified
   automatic recovery, the first pilot uses supervised, single-attempt outward writes and stops on ambiguity.

### Execution and evidence

1. Intake the delegated request through the trusted factory adapter, capturing source identity/verdict, dedupe key
   and allocated task id. A repeated intake must return the same task without another spec or side effect.
2. Complete DEFINE, grill and approval under the project's Change-Class rules. Capture current spec/ADR fingerprints
   and approval evidence; never write a person's `Approved-by` line on their behalf.
3. Build the single-file documentation change. The independent judge and all review lenses inspect it, with
   meaningful documentation checks and the project's required test command. Capture commands, exits, evidence
   and the actual judged revision. Refusal, missing verdict or unknown environment is a stop, not a pass.
4. At `ready-to-deliver`, the trusted clone verifies the exact head with the base-pinned engine, creates the one PR
   from the delivery plan and records the result with `HARNESS_DELIVERY_KEY` supplied only to its trusted
   `delivery-record` process. The trusted adapter then calls `next <id> --json` with the same key and confirms
   signature-checked completion for the current task/head. Record creation alone is not completion evidence.
   Capture the receipt, verified range/head, PR/check result, record reference and trusted keyed-read result,
   without exposing the key. A changed head needs fresh affected evidence and verification.
5. Stop for human PR review and merge. Do not let Front or a lane merge it. For this first pilot, a requested code
   revision is parked for supervised handling until the feedback adapter is qualified; do not claim that unbuilt
   feedback integration worked. Retain the worktree and evidence; perform no janitor deletion or KB push.

Pass means the named task has evidence for every applicable gate, matching judged/verified/delivered revision,
a single traceable PR, bounded usage, human merge authority and a trusted keyed `next` result backed by the
adapter's signature-rejection qualification. A PR URL, signed-record existence or unkeyed progress read alone
is insufficient. Report missing access as BLOCKED, seeded negative cases as expected refusals, and unrun stages
as NOT_RUN.

## Next work

The current readiness result is **BLOCKED for a live pilot**: no published tag containing PR #90, the local project
still pins its predecessor, no installed default engine cache, and no inspected factory checkout, disposable target,
dedicated identity, forge protection, trusted keyed progress reads or independent live-review evidence. Local
fixture success cannot clear these.
The authorized local audit can finish without launching the factory. Release/pin and live-run actions follow their
existing human-owned controls; this note does not change them.
