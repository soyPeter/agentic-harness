# The software factory, in four diagrams

How a change moves through the agentic harness, from the first signal to a merged pull request. The layout follows
[Eno Reyes's software-factory diagram](https://x.com/EnoReyes/status/2118767454721851680) (November 2026): one process
for every change, whoever or whatever starts it, with people setting the rules.

Solid shapes are built and enforced. Dashed ones are proposed, or outside the harness. The orange person marks each
point where the harness waits for a human.

## 1. The factory at a glance

![The factory: signals, define, build, judge and deliver, merge and observe, with people setting the rules above](1-factory.svg)

- **People set the rules.** Only the user accepts an ADR, writes the tool contracts in `tools.conf`, or changes the
  user-only keys of `harness.conf` (gate switches, risk rules, autonomy mode, profile). Skill routes in
  `routing.conf` and rules in `guardrails.conf` come from the packs an accepted ADR adopts and the rules agreed at
  setup.
- **Signals.** Work comes from a person, a Linear ticket (`harness.py linear import`) or the task list. The harness's
  own feedback adds more: escalations, red CI, failure-class proposals and `harness.py report` candidates. Production
  incidents are not a signal yet.
- **Two lanes, one standard.** In a supervised session (the default), a person answers the griller and signs
  `Approved-by`. In an autonomous run (`harness.py run`, `harness.py orca`), questions are answered from `backbone/`
  and the knowledge vault, with sources. Policy approves only low-risk `docs` and `refactor` specs, and everything
  else is escalated to a person.
- **Same checks, every task.** Whichever lane a task came from, it passes the same checks:
  - the judge, with the harness re-running the tests itself;
  - the three review lenses;
  - the judge gate at finish;
  - verify on every commit;
  - `harness-verify` in CI, with the base branch's verifier.

  Then a person merges the pull request. The deliverer can't merge, and under the `triple` profile no agent can;
  `harness-verify` blocks a merge only once it is a required check in branch protection.
- **What fails becomes the next task.**
  - Red CI becomes a fix task on the same pull request.
  - Escalations wait for a person.
  - A failure class seen twice opens a proposal.
  - The report points at missing rules or skills.

  Tracing a production incident back to its pull request and spec is drawn dashed: it is proposed in
  [ADR-007](../adr/ADR-007-evidence-closed-loop.md), not built. So is triage before Define (deduplicate, set an owner,
  pick a lane or park), which the diagram doesn't draw.

## 2. One task, request by request

![A sequence diagram of one task, from the request to the merged pull request](2-task-flow.svg)

Read it top to bottom. Each arrow is a request, and each box on a lifeline is where the harness checks or records
something. Both loops are bounded: the griller repeats until it passes, and the judge until it passes or
`HARNESS_JUDGE_MAX_ROUNDS` hands the task to a person. The orange bracket is the one step autonomous mode replaces:
`harness.py approve` instead of a person's `Approved-by`, and only for low-risk `docs` and `refactor` specs.

## 3. Who decides, by Change-Class

![Change-Class ladder: light lane, spec approval in supervised and autonomous mode, receipt labels and merge, per class](3-change-class.svg)

[ADR-002](../adr/ADR-002-change-class-ladder.md)'s ladder. The class changes three things:
- whether the light lane applies;
- whether autonomous mode may approve the spec by policy;
- which risk label the receipt suggests.

Whatever the class, a person approves every spec in supervised mode and merges the pull request.

## 4. What the harness can prove about a change

![The evidence chain from spec to receipt, where it is checked again, and the proposed ADRs that extend it](4-evidence.svg)

The receipt is built from evidence, not from what the agents said. Two fingerprints tie each verdict to what it judged,
so an edit after a pass makes that pass stale. The middle row is where the same evidence is checked again outside
the agent's session. The CI floor runs the base branch's verifier, so a pull request can't weaken the check that gates
it. The bottom row holds the three proposed ADRs. Each ships a first slice; none is accepted yet.

## Sources

- [README](../../README.md), and in `payload/owned/`: `AGENTS.md`, `backbone/8-WORKFLOW.md`, `backbone/HOOKS.md`
- [ADR-001](../adr/ADR-001-thin-mode-plugin.md) and [ADR-002](../adr/ADR-002-change-class-ladder.md) are accepted.
  [ADR-003](../adr/ADR-003-sandbox-backends.md), [ADR-004](../adr/ADR-004-traceability-export.md) and
  [ADR-005](../adr/ADR-005-verdict-attestations.md) are on `main` as Proposed: each ships a first slice, none is
  accepted yet; diagram 4 shows them as proposed.
- [Agent-SDLC landscape research](../research/2026-11-agent-sdlc-landscape.md)

The SVGs are plain text and carry their own background, so they read the same in GitHub's light and dark themes.
Update a diagram in the same pull request as the behaviour it shows.
