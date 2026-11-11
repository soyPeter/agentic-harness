# Plan: run the open harness plans and ADR follow-ups through Orca

- Status: Accepted (2026-11-10). Pedro accepted the 16 defaults in [Decisions (2026-11-10)](#6-decisions-2026-11-10). Nothing has started in the repository and no code has changed.
- Date: 10 Nov 2026 (Europe/Madrid). Accepted the same day.
- Repository: soyPeter/agentic-harness. The inventory below was taken against origin/main at `6e2f8ac` (v0.30.0). By the afternoon of 10 Nov 2026, origin/main had moved to `8d31682` and already included the merges of PR 78 and PR 80.
- Related: the plans and ADRs in this folder and in `docs/adr/`, and [PR 82](https://github.com/soyPeter/agentic-harness/pull/82).
- Ask (t88u): "plan and ask orca to start executing all plans and pending adrs in the agentic harness project".

## 1. Inventory

Sources: origin/main, PR 82 (cursor/docs-research-proposed-plans-86c6), and untracked files in Pedro's copy on Estix (branch soyPeter/docs-redo).

### ADRs

| ADR | Where | Status in file | Built? | Still pending |
|---|---|---|---|---|
| ADR-001 thin-mode plugin | origin/main | Accepted | Yes (thin mode since 0.30.0) | Nothing |
| ADR-002 change-class ladder | origin/main | Accepted | Yes (gates, labels, deliverer rules) | Nothing |
| ADR-003 sandbox backends | origin/main | Proposed | v1 yes: devcontainer backend, sandbox evidence in receipts | 9 follow-ups listed in the ADR |
| ADR-004 traceability export | origin/main | Proposed | v1 yes: trace export reqif, needs, html | 4 follow-ups |
| ADR-005 verdict attestations | origin/main | Proposed | First slice yes, plus the key anchor guard | 6 follow-ups |
| [ADR-007](../adr/ADR-007-evidence-closed-loop.md) evidence closed loop | this docs PR | Proposed | No | Renumbered from a draft that clashed with ADR-003 sandbox, and converted to the repository ADR format. Umbrella only. Its work lives in the delegation plan |
| [ADR-006](../adr/ADR-006-external-agent-resource-admission.md) external agent resource admission | this docs PR | Proposed | No | Conditional on an audit. Tied to design-challenge D2 |

ADR-003, 004 and 005 still say Proposed although their first slices shipped. Only a human should change that status.

### Plans in docs/research

| Plan | Where | Status | Built? | Work packages |
|---|---|---|---|---|
| agent-sdlc-landscape | origin/main | Research only | n/a | None |
| [design-challenge agent onboarding](2026-11-design-challenge-agent-onboarding-plan.md) | origin/main, decisions added in this docs PR | Proposed | No | D0 audit, D1 to D3. Audits only unless D0 shows real gaps |
| [delegation contracts qualification](2026-11-delegation-contracts-qualification-plan.md) | this docs PR | Proposed | No | P0 audit, P1 to P3, plus V refinements. Audits only unless P0 shows real gaps |
| [task dependency gate](2026-11-task-dependency-gate-plan.md) | PR 82 | Proposed | No | WP0 audit, WP1 to WP4. Option B if WP0 finds no existing gate; hard gate in supervised mode too; bad references warn for one release then error |
| [PR body reviewer opener](2026-11-pr-body-reviewer-opener-plan.md) | PR 82 | Proposed | No | WP1 audit, WP2 to WP4. Opener optional and labelled; do not record model or effort yet |
| [structural skeleton spec](2026-11-structural-skeleton-spec-plan.md) | PR 82 | Proposed, parked after WP0 (no-go) | No | None now. WP0 no-go accepted |
| [model change instruction review](2026-11-model-change-instruction-review-plan.md) | this docs PR | Proposed | No | WP1 baseline, WP2 to WP4. Option C; an Orca worker runs WP1 on fixture tasks; lint covers `payload/owned` only |
| [indeterminate side-effect outcome](2026-11-indeterminate-side-effect-outcome-plan.md) | this docs PR | Proposed | No | WP0 audit, WP1 to WP4. Option B; all four write paths; park when the result cannot be known |

Pending: 7 plans with work (skeleton excluded), 3 shipped ADRs with 19 follow-ups, and 2 draft ADRs in this docs PR (ADR-006 and ADR-007).

## 2. How Orca works with the harness (read from origin/main)

- Entry point: `harness.py orca [--tasks 1.3,1.4] [--parallel N] [--agents default=claude,judge=codex] [--trust] [--merge | --pr] [--here] [--run ID] [--wait-ms MS] [--timeout S] [--dry-run]`. Default parallel is 2, default timeout 4 hours.
- In a thin project the same arguments go through the plugin's `launcher.py`, which runs the pinned engine from `~/.agentic-harness/engines/<version>/`.
- Work enters as task lines in `backbone/3-TASKS.md` (`- [ ] **Task 1.1: <title>**`). An optional `(after: 1.1)` on the line orders tasks. Each task gets a spec in `backbone/specs/<id>.md`, written by the analyst and architect, grilled by the griller. Linear issues can become tasks with `harness.py linear import <ISSUE> --task <id>`. There are no CHNG records or PRD to RFC chains in the engine.
- Orca drives each ready task with one worker per step and one worktree per task. It asks `harness.py next` before every step.
- Requirements, checked in code:
  - `HARNESS_AUTONOMY="autonomous"` in `backbone/harness.conf`. Only the user sets it. Without it, orca refuses.
  - `doctor` must report no errors. A fresh seed with `{{FILL}}` placeholders is unfinished setup.
  - One Orca run per repository (a lock). The Orca app must be running. It is running on Estix (Orca 1.4.255, runtime ready).
  - Only the user starts it. The agent hooks refuse `harness.py orca` and `orca-nightly` from an agent. Only `--dry-run`, `orca-digest`, `state`, `report` and `escalations` are open to agents.
- Approval in autonomous mode: the harness approves a spec by policy only when its Change-Class is `docs` or `refactor` and it is low risk. Feature and schema specs are escalated and wait for the user's `Approved-by:` line. Human approval of real changes stays.
- Delivery: after the judge and the three reviewers, the deliverer pushes the branch and opens a PR. It never merges.
- `--merge` merges finished task branches into the local base branch so dependent tasks can start. `--trust` answers the CLIs' trust prompts for worktrees. Under `HARNESS_PROFILE=triple` both are refused and orca-nightly too.
- Kill switch: create `.git/harness/STOP`.

### Can Orca run on agentic-harness itself?

Not today. The repository is the harness source. It has no `backbone/`, no `3-TASKS.md` and no install, so orca has nothing to read. No project under `~/Work/repos` on Estix has the harness for this work: only `tests/coefficiency` and `tests/colsum`, which are test fixtures.

To run it here, the harness must be installed into its own repository. Thin mode is the better fit. The gates then come from the pinned release v0.30.0 in `~/.agentic-harness/engines/`, not from the code the workers edit. A task that changes a gate cannot weaken the gate that judges it. The new gate applies only after Pedro cuts a release and moves the pin.

## 3. Prerequisites (P0). Pedro or a human does these. No agent work yet.

1. Do not use Pedro's copy (`~/Work/repos/agentic-harness`). It is on `soyPeter/docs-redo`, behind origin, with 9 untracked drafts. Make a fresh clone at `~/Work/repos/agentic-harness-orca` from origin/main.
2. Land the inputs on origin/main through PRs Pedro merges:
   - PR 82 (three plans).
   - A new docs PR with the untracked files: model-change plan, indeterminate plan, delegation plan, ADR-006, and the evidence closed-loop draft renumbered to ADR-007.
   - Workers read plans from the base branch. A plan that is not there does not exist for them.
3. PRs 78 (spec parsing) and 80 (deliverer gate) already merged to origin/main on 10 Nov 2026 (`8d31682`). That prerequisite is done. PRs 74 and 77 (README) can wait but will conflict with doc tasks.
4. Self-enrollment PR, in the new clone, on a branch from origin/main:
   - Install the plugin at v0.30.0 in Claude Code (`/plugin marketplace add soyPeter/agentic-harness#v0.30.0`, then `/plugin install agentic-harness@agentic-harness`). It is not installed on Estix today. If the judge runs on Codex, install the Codex plugin too and trust its hooks.
   - `python3 plugin/launcher.py init --thin --version 0.30.0 --name agentic-harness` from the clone root.
   - First-run setup: fill `1-PRD.md`, `2-PLANNING.md`, `4-KNOWLEDGE.md`, `7-CONVENTIONS.md` and the stack ADR in `backbone/adr` (Python 3.8+, standard library only, bash self-test). Link the existing `docs/adr` files from `backbone/5-DECISIONS.md` so specs can follow them.
   - `backbone/harness.conf`: `HARNESS_AUTONOMY="autonomous"`, `HARNESS_TEST_CMD="tests/run-tests.sh"`, `HARNESS_ORCA_AGENTS="default=claude judge=codex"`, and `HARNESS_PROFILE="triple"` so the no-merge rule is enforced by the tool (check with `doctor` that the profile does not demand the triple pack).
   - Add the task lines from section 5 to `backbone/3-TASKS.md`.
   - `doctor` clean. `orca --dry-run` lists the wave 1 tasks.
   - Open the PR. Check that `harness-verify` passes on it and does not block ordinary human PRs. Pedro merges.
5. Linear: decide whether each plan gets one Linear issue in the harness team, imported with `linear import`. Creating issues is an external write and needs Pedro's yes.

## 4. How to start Orca (Pedro, by hand)

In an Orca terminal of its own on Estix:

```sh
cd ~/Work/repos/agentic-harness-orca
git switch main && git pull --ff-only
python3 <launcher> doctor
python3 <launcher> orca --dry-run
python3 <launcher> orca --pr --parallel 2 --tasks <wave ids>
```

`<launcher>` is the plugin's `launcher.py` at the pinned release. Confirm its exact path after the thin init. Do not run it from the clone's own `plugin/launcher.py` once tasks start editing it.

Never use `--merge` or `--trust` here. Never schedule `orca-nightly` or `enroll.sh --automation`. Read results with `orca-digest`, `state --json`, `escalations` and `report`.

Because there is no `--merge`, a dependent task starts only after Pedro merges the PR of the task it waits for. So work runs in waves.

## 5. Proposed order

Task ids are proposals. Change-Class in brackets.

### Wave 1: audits only [docs]. Policy can approve them, so they run without per-spec sign-off.

| Task | Source | Output |
|---|---|---|
| 1.1 Dependency gate WP0 audit | dependency gate plan | Findings note at a pinned revision. Stop the plan if a gate already exists outside Orca |
| 1.2 PR body WP1 audit | PR body plan | Findings note with 3 to 5 real PR bodies. Stop if bodies are already short |
| 1.3 Indeterminate WP0 audit | indeterminate plan | Kill tests on a fixture for PR, issue and Linear writes. Stop or narrow scope |
| 1.4 Delegation P0 and P0-V reuse map | delegation plan | Revision-pinned reuse and gap matrix |
| 1.5 Design challenge D0 reuse map | design challenge plan | Reuse and gap map, expected outcomes |
| 1.6 ADR follow-up triage | ADR-003, 004, 005 | Which of the 19 follow-ups are already done, which are local code, which need outside services |
| 1.7 Model change WP1 baseline | model change plan | Results table on 5 to 10 fixture tasks (tests/coefficiency, tests/colsum). Spends model tokens |

Then Pedro reads the notes, closes plans the audits find unneeded, and answers the decisions in section 6.

### Wave 2: small changes, independent of each other

| Task | After | Class |
|---|---|---|
| 2.1 Dependency gate WP1 rule and start gate | 1.1 | feature |
| 2.2 PR body WP2 template | 1.2 | feature |
| 2.3 Indeterminate WP1 journal and outcome | 1.3 | feature |
| 2.4 Model change WP2 checklist | 1.7 | docs |
| 2.5 ADR-004 follow-up 1: HTML matrix step in harness-verify | 1.6 | feature |
| 2.6 ADR-005 follow-up 1: read the merged PR's harness-change-approved label | 1.6 | feature |

2.1 and 2.3 both touch `next`, `run` and delivery code in `harness.py`. Run them one after the other, not in parallel.

### Wave 3: follow-on work packages

| Task | After | Class |
|---|---|---|
| 3.1 Dependency gate WP2 selection | 2.1 | feature |
| 3.2 Dependency gate WP3 validation | 2.1 | feature |
| 3.3 Indeterminate WP2 reconcile | 2.3 | feature |
| 3.4 Indeterminate WP3 coordinator | 2.3 | feature |
| 3.5 Model change WP3 lint report | 2.4 | feature |
| 3.6 PR body WP3 docs | 2.2 | docs |
| 3.7 ADR-003 follow-ups 1 (DNS), 4 (gate on evidence), 8 (egress denials in receipt) | 1.6 | feature, one task each |
| 3.8 ADR-005 follow-up 5: cosign check and predicate policy helper | 1.6 | feature |
| 3.9 ADR-004 follow-up 3: .reqifz with the receipt | 1.6 | feature |

### Wave 4: docs and qualification, only where the audits found gaps

- 4.1 Dependency gate WP4 docs, after 3.1 and 3.2.
- 4.2 Indeterminate WP4 docs, after 3.3 and 3.4.
- 4.3 Delegation P1, then P2, then P3, report-only. Only if 1.4 found real gaps.
- 4.4 Design challenge D1 to D3, report-only. Only if 1.5 found real gaps. ADR-006 is decided here.
- 4.5 ADR-003 follow-ups 5 (run starts the sandbox), 6 (Orca workers inside a sandbox), 9 (sandbox for thin installs).

### Not for Orca now

- Structural skeleton plan: parked. Re-open only for a greenfield task, a project with the tester on, or judge failures caused by interfaces.
- PR body WP4 trial and model change WP4: they need Pedro's judgment on real PRs and a real model change.
- ADR-003 follow-ups 2 (brokered credentials), 3 (publish and pin the built image), 7 (first vendor backend with its own ADR): they need registries, vendor accounts or money.
- ADR-005 follow-ups 2 (KMS), 3 (keyless), 4 (release assets, OCI), 6 (predicate v1 once the schema settles).
- ADR-004 follow-ups 2 (links on PR and Linear ticket, an outside write) and 4 (signed exports, after ADR-005 is accepted).
- Changing any ADR status to Accepted. That stays Pedro's call.

## 6. Decisions (2026-11-10)

Pedro accepted all 16 defaults below on 10 Nov 2026 (Europe/Madrid). These are the starting rules for the rollout.

| # | Decision | Proposed default |
|---|---|---|
| D1 | Run Orca on the harness repo itself through a thin self-enrollment PR | Yes, thin mode pinned at v0.30.0, in a fresh clone |
| D2 | Merge PR 82 and a new docs PR with the untracked plans and ADRs | Yes. Renumber the evidence closed-loop draft to ADR-007 |
| D3 | Turn on autonomous mode in that repo | Yes, with `HARNESS_PROFILE="triple"` so merge flags are refused |
| D4 | Agents per role | `default=claude judge=codex`, so the judge runs on a different model |
| D5 | Delivery mode | `--pr` only. Pedro merges each PR, which also releases the next wave |
| D6 | Parallel workers | 2 |
| D7 | Linear | One issue per plan in the harness team. Needs Pedro's yes to create them |
| D8 | Dependency gate plan | Option B, if WP0 finds no gate outside Orca. Hard gate in supervised mode too. Bad references warn for one release, then error |
| D9 | PR body plan | Run the WP1 audit. Opener optional and labelled. Do not record model and effort yet |
| D10 | Model change plan | Option C. An Orca worker runs WP1 on fixture tasks. The lint covers `payload/owned` only |
| D11 | Indeterminate outcome plan | Option B. All four write paths. Park the task when the result cannot be known |
| D12 | Skeleton plan | Accept the WP0 no-go and keep it parked |
| D13 | Delegation and design challenge plans | Run only the audits (P0, D0). Build nothing unless they show real gaps |
| D14 | ADR follow-ups in scope | Only local code follow-ups listed in waves 2 to 4. Not the ones that need outside services |
| D15 | Open PRs 78 and 80 | Merge or close them before wave 2. Accepted, and already done: both had merged to origin/main by the time this plan was accepted |
| D16 | Release cadence | Cut a release and move the pin only after a wave is merged, so new gates apply to the next wave |

## 7. Risks

- The harness edits its own gates. Thin mode keeps the running gates on the pinned release. A full install or a pin moved mid-wave would break that.
- Pedro's working copy. Running anything there would mix with his untracked drafts and the docs-redo branch. Use the separate clone only.
- Merge conflicts. Several tasks touch `harness.py` and `coordinator.py`, and PRs 74 and 77 (README) are still open. Keep build tasks on those files serial.
- Self-enrollment side effects. Adding `harness-verify.yml` to the harness repo means every future PR there gets checked. It may fail human PRs that touch nothing in `backbone/`. Check this on the enrollment PR before merging.
- Doctor may treat the harness source tree oddly (it has `payload/`, `plugin/`, `catalog/`). The dry run will show it.
- Cost and time. The self-test is long and runs on every judge pass. Each task runs about ten role workers. Wave 1 alone is 7 tasks.
- Escalations. Feature specs wait for Pedro's approval. Expect most of waves 2 to 4 to sit in `escalations` until he approves each spec. That is the intended human gate.
- The audit-first plans can close themselves. Good outcome. Do not build work packages just to fill a wave.

## 8. Rollback

- Stop: create `.git/harness/STOP` in the clone.
- Each task is its own PR. Close it to drop it.
- Remove the self-enrollment with one revert PR. The `docs/` plans and ADRs stay.
