# ADR-013: Roll out harness changes through pinned gates and human-merged waves

## Status
Proposed

## Date
2026-11-13

## Context
The [Orca self-rollout plan](../research/2026-11-orca-self-rollout-plan.md) records Pedro's acceptance of
16 defaults on 10 November 2026. It sequences audits and conditional implementation of the open plans and
ADR follow-ups. Those recorded decisions remain historical authority; this new ADR does not launch execution.

The harness edits its own gate source. Running those edits as the verifier would let a change judge itself.
[ADR-001](ADR-001-thin-mode-plugin.md) supplies a separately pinned engine. The rollout plan's inventory and
machine/PR observations are dated: the current checkout already contains a thin enrollment and wave-one backlog,
so its old setup commands must not be repeated merely because they appear in the plan.

## Decision
Use thin mode with a pinned released engine to check source changes, deliver task PRs, and release in
human-merged waves. Reconcile current enrollment and task evidence with the plan before starting any work.

- The recorded initial pin is v0.30.0. Workers edit product source while the pinned engine remains the verifier.
  Do not move the pin during a wave or use the edited source as its own trusted gate.
- The recorded rollout uses two parallel workers with `default=claude judge=codex`, `HARNESS_PROFILE="triple"`
  and PR delivery only. The profile is not the Triple catalog pack. Do not use local merge/trust flags or nightly
  automation for this rollout.
- Pedro starts real Orca runs and merges task PRs. An agent may inspect state and dry runs; this ADR does not
  start workers, install plugins, alter autonomy settings or create Linear issues.
- Wave 1 is audits: dependency gates, PR bodies, uncertain writes, delegation, design challenge, local ADR follow-up
  triage and model baseline. Close or narrow plans where existing controls suffice. Keep the skeleton plan parked.
- Later waves follow actual prerequisite merges and audit findings. Feature/schema specs require human approval;
  policy approval remains limited by the existing Change-Class/risk gates.
- Serialize overlapping edits, especially dependency and uncertain-write work in shared harness/coordinator code.
  Two available workers do not imply two safe writers to the same surface.
- Only local-code ADR follow-ups enter these waves. Vendor accounts, registries, credentials, paid services and
  external writes require their own authorization. Linear issue creation remains a separate external action.
- Cut a release and move the pin only after a wave is merged, by Pedro's decision, so new gates apply to the next wave.

## Alternatives considered
- Run the working-tree engine against its own changes: loses the independent verifier boundary.
- Execute every plan immediately in parallel: ignores audit stop rules and shared-file dependencies.
- Merge task branches locally or automate delivery to main: removes the human merge boundary.

## Consequences
- Execution requires current doctor/dry-run evidence, landed input plans and a clean, dedicated execution workspace.
  Reuse a valid enrollment; do not overwrite the maintainer's unrelated drafts or recreate setup blindly.
- Human merges and approvals intentionally limit throughput. Long self-tests and model baseline runs have real cost.
- Check self-enrollment CI against ordinary human PRs before relying on it. A verifier must not reject legitimate
  documentation work merely because its source repository also ships a harness payload.
- Stop with the supported kill switch; close unwanted task PRs. Revert enrollment through a reviewed PR if needed,
  preserving plans, ADRs and evidence. This record changes neither runtime configuration nor the pin.
