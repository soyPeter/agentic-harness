# ADR-009: Qualify delegation contracts and verification before expanding execution

## Status
Proposed

## Date
2026-11-13

## Context
The [delegation-contracts qualification plan](../research/2026-11-delegation-contracts-qualification-plan.md)
turns [ADR-007](ADR-007-evidence-closed-loop.md) into bounded qualification work. Tool permission,
individually passing workers and agreement between models do not establish that actions serve approved intent
or that combined output meets the shared acceptance criteria. Verification procedures can also have faulty oracles.

The plan's baseline is documentation-only and does not establish missing runtime controls. Pedro's recorded
decision on 10 November 2026 authorizes only P0 and the P0-V reuse map; implementation remains conditional on gaps.

## Decision
Audit and reuse the existing contracts, trace, gates and Orca before adding mechanisms. Retain serialized writes
with parallel read-only research/review as the control and a valid final outcome. Increased concurrency requires
separate evidence and a human adoption decision.

- Map approved request, spec revision, authority, target, scope and relevant events onto existing identifiers.
  Untrusted source text and generated plans cannot grant action authority.
- Describe unit ownership, resource boundaries, REQ/AC evidence and each dependency's artifact or ordering reason.
  Disjoint files alone do not establish independence: ports, databases, credentials and semantics may be shared.
- Bind evidence to the actual unit and integrated trees. Changed prerequisites or constraints invalidate affected
  evidence. Independent judgment and checks on the combined result remain necessary.
- Qualify verification itself: launch prerequisites and owned resources; doctor checks for the correct instance,
  revision and tenant; executable action-to-state recipes; revision-bound evidence; cleanup of owned resources only.
  Distinguish PASS, FAIL, BLOCKED, NOT_RUN and infrastructure failure. An unexecuted recipe is draft evidence.
- Independently establish expected outcomes and validate fixtures. Separate construction, development and held-out
  sets; compare current/candidate on paired cases and report missed violations, false blocks, uncertainty, cost and
  review load. Another model is not proof of independence. Do not collect private chain of thought.
- Lessons remain candidates with provenance, counterexamples and independent evaluation until human activation.
  New semantic signals begin report-only and cannot weaken permissions or mandatory gates.

P0/P0-V may conclude that existing coverage is sufficient. Only demonstrated gaps justify P1 provenance fixtures,
P2 decomposition/integration qualification or P3 learning/adoption experiments and their verifier refinements.
This ADR adds no scheduler, registry, runtime, fixed concurrency target or automatic merge authority.

## Alternatives considered
- Keep the current serialized path without qualification: viable if the audit establishes adequate coverage;
  otherwise leaves consequential assumptions untested.
- Copy a standalone graph/checker/learning system: duplicates the control plane and can let mutable checks certify
  themselves. Use source ideas as negative fixtures instead.
- Adopt parallel writes immediately: unit success and file isolation do not prove safe composition.

## Consequences
- The first deliverable is a revision-pinned reuse/gap map and independently agreed negative cases, not new code.
- Qualification adds fixture, oracle and privacy maintenance. Stop if reliable evidence is unavailable or the cost
  exceeds demonstrated value; no-gap and inconclusive results are legitimate outcomes.
- Follow the plan's P/V dependencies. Evaluate any optional execution path against the supported serialized path.
  Roll back additive guidance/reporters through reviewed changes while preserving core controls and evidence.
- Human approval and merge remain; Triple retains Linear as record and Monday consolidated reporting.
