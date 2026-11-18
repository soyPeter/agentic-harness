# ADR-016: Keep structural spec skeletons parked pending relevant evidence

## Status
Proposed

## Date
2026-11-13

## Context
The [structural-skeleton plan](../research/2026-11-structural-skeleton-spec-plan.md) considers an optional
stubs-only Architecture block to fix public or cross-module signatures before implementation. External results
motivate the idea, but local brownfield specifications may already constrain structure sufficiently.

WP0 read six task records in one project; only two tasks reached judgment and there were no failed judge rounds.
Architecture prose already specified types and methods. Some grill questions were structural, but were caught
before approval. The small, single-stack sample did not demonstrate enough benefit to implement WP1.
Pedro accepted WP0's no-go on 10 November 2026. This ADR records that disposition without reopening execution.

## Decision
Keep the skeleton feature parked. Re-run WP0 only when a greenfield task, a project with the tester enabled,
or judge failures caused by interface/type mismatches provides relevant evidence.

If a later human go decision reopens implementation, retain the plan's bounded design:

- Opt in through the proposed `HARNESS_SPEC_SKELETON=off|stubs`, default off, for the plan's feature scope.
  Use signatures, types and declared errors for public/cross-module boundaries; exclude bodies and algorithms.
- The architect owns the skeleton within the existing spec. Size/shape checks should discourage excessive detail;
  the limit remains a WP0 decision, not a number invented by this ADR.
- Grill fingerprints and user approval cover it. A mismatch in name, parameter/return type or declared error is a
  judge blocker under the recorded design decision. Fix code or obtain a newly reviewed/approved skeleton;
  an agent may not rewrite the approved contract to fit its implementation.
- The tester uses those names when enabled. A later language-pack mechanical signature check may support, never
  replace, independent judgment after the pilot demonstrates value.

The existing plan remains the package-level source for WP0–WP4. Recording the option is not approval to add a
setting, change a template or activate a new gate input.

## Alternatives considered
- Implement immediately from the external result: local evidence does not show a judge-failure problem to solve.
- Keep prose-only specifications indefinitely: the current control; reconsider if new relevant failures appear.
- Try a fenced signature example in today's Tech requirements: possible as an ordinary writing choice within
  the existing workflow, without a new engine feature or a claim of demonstrated effectiveness.

## Consequences
- No runtime, template, gate or task is added for the parked plan. Historical decisions and WP0 limits remain visible.
- Reopening needs a baseline with independently assessed structural failures and review effort, followed by a human
  go/no-go before WP1 format and WP2 pilot. WP3 pack checks come only after pilot value; WP4 documents adopted behavior.
- A future feature risks freezing wrong design and increasing approval load. Reapproval and a small boundary-only
  skeleton limit those risks; an inconclusive evaluation may keep the plan parked.
- If implemented later, default-off is the rollback path and existing skeleton text remains valid spec content.
