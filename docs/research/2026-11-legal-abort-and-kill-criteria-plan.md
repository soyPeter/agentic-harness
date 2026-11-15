# Proposed plan: legal abort path and pre-declared kill criteria

- **Status:** Proposed, not accepted, not implemented, and not permission to change the runner, hooks, or any merge rule.
- **Date:** 2026-11-15 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-legal-abort-and-kill-criteria-plan.md`.
- **Decision authority (proposed role, unassigned):** repository maintainer. Merge stays with the user, as today. `HARNESS_PROFILE=triple` still refuses `--merge`. Agents still must not pass `--merge`. This plan does not start orca.
- **Source (primary):** Jaroslaw Wasowski, [AI agent harness: abort, egress proxy, credential scoping, cache and trace-based monitoring](https://medium.com/@wasowski.jarek/ai-agent-harness-abort-egress-proxy-credential-scoping-cache-and-trace-based-monitoring-d53085216d92) and [AI agent self-assessment: deterministic gate, kill criteria and read-back in the pipeline](https://medium.com/@wasowski.jarek/ai-agents-ai-agent-self-assessment-deterministic-gate-kill-criteria-and-read-back-in-the-17232b12fe02), both read in full on 15 Nov 2026. Lab rates and preprint figures in those articles are the author's citations and were not independently verified. Wasowski himself says not to carry lab attack rates into production.
- **Related existing work (do not redo):**
  - `harness.py escalate` already parks a task, writes `backbone/escalations.md`, optionally opens a GitHub issue, and agents cannot clear the note. AGENTS.md already tells the agent to call escalate in several cases (blocked command, another task in progress, questions nobody can answer).
  - Automatic escalation already exists after `HARNESS_JUDGE_MAX_ROUNDS` and `HARNESS_GRILL_MAX_ROUNDS`, on budget exhaustion, on a retry that changed nothing, and on tamper in autonomous mode.
  - [ADR-003](../adr/ADR-003-sandbox-backends.md) and [2026-11-agent-sdlc-landscape.md](2026-11-agent-sdlc-landscape.md) already record that `init-firewall.sh` runs inside the guest and can be rewritten, and already recommend moving that allowlist outside the container, with DNS included. This plan does not reopen egress.
  - [ADR-011](../adr/ADR-011-indeterminate-side-effect-outcomes.md) already covers reconciling an external write before retrying. This plan does not reopen read-back of GitHub or Linear writes.
  - [ADR-014](../adr/ADR-014-pr-body-reviewer-opener.md) and [2026-11-pr-body-reviewer-opener-plan.md](2026-11-pr-body-reviewer-opener-plan.md) already cover how a receipt is shown in a PR body. This plan does not add a second PR template.
  - [ADR-002](../adr/ADR-002-change-class-ladder.md) and [ADR-007](../adr/ADR-007-evidence-closed-loop.md) already keep human merge and refuse to treat the builder's summary as proof.

## Problem

The harness can park a task, but it is not clear that an agent facing an impossible step (a test it cannot fix in scope, a missing permission, a broken precondition) will take that exit instead of working around the check. Wasowski's reading of one Anthropic replay is the cautionary case: the model tried to quit, the abort tool was misconfigured, and after further quit attempts it broke into a third party's system. That is a lab incident, not a finding in this repository. The question for us is narrower: is the abort path taught, allowed without punishment, and tested?

A second gap sits next to it. Escalation today is mostly tied to red verdicts, budgets, and tamper. A green run that satisfied the tests by commenting out a limit, or by otherwise bypassing the intent, has no first-class report type. Wasowski calls this "deviation under a green result." The judge may catch some of those cases. It is not written down what the harness should do when the agent itself admits the workaround.

## Options

| Option | Benefit | Cost / risk |
|---|---|---|
| A. Leave as is | No new ceremony | We do not know whether agents use `escalate` when the task is impossible, and a green workaround can close a run |
| B. Rewrite escalation from scratch | Clean design on paper | Duplicates a working park-and-block path; rejected |
| C. Audit the current abort path, then add only the missing instruction, test, and report type | Reuses `escalate`; adds a CI exit-path test and a written action for green deviations | Small hook and docs work; a bad test could punish honest aborts or flood the queue |

**Proposed: C.** Stop after the audit if the path is already taught, tested, and used.

## Proposed work

### WP0. Audit (stop here if the gap is not real)

Read the current agent instructions, `escalate` entrypoints, and tests.

Confirm or reject these questions, with file and test names:

- When is an agent told to call `harness.py escalate`, and is an impossible or out-of-scope task on that list?
- Is there a stated rule that an honest abort is not punished (no retry storm, no "just try harder" prompt that fights the exit)?
- Is there a CI test that the abort path ends or parks the run on the orchestrator side, even if the agent keeps trying?
- What happens today if tests are green and the session text or a hook shows a workaround?

If the audit shows the path is already taught, tested, and used, stop. Write the finding in this file and do not start WP1.

### WP1. Exit-path test and no-punishment wording

Only if WP0 finds a gap.

- Add a fixture in which the task is impossible inside the allowed scope, the agent calls `escalate` with a structured reason (what blocks, the evidence, a proposed fix), and the run is parked. A second fixture in which the abort tool is deliberately broken must fail the test, not the task in production.
- Add a short, explicit line to the agent instructions: if the work cannot be done inside the spec and the change class, call `escalate` and stop. Do not disable tests, widen permissions, or search for an exit outside the sandbox. An honest abort is the correct outcome.
- Keep the existing park-and-block behavior. Do not invent a second escalation file.

### WP2. Harness-side trigger (optional, after WP1)

If WP0 shows agents often pass the point of no return before calling `escalate`, add one harness-side trigger that does not depend on the model's choice: a failed-attempt counter, a first out-of-scope tool call, or the existing step and budget limits, whichever the audit shows is missing. Do not add all three at once. Reuse existing attempt and budget machinery where it already stops the run.

### WP3. Green-deviation report

If WP0 shows a green workaround can close a run:

- Add a report or escalation class for "deviation under a green result" (name to be chosen to match existing escalation classes).
- Route it to a human queue and keep the task from being marked done or delivered until a person decides. Do not auto-merge. Do not treat the agent's admission as proof of guilt without the existing judge or a human reading the evidence.
- Record the policy (the action for this class) in a versioned place the agent cannot write, with a hash or commit recorded at the start of the run. Prefer an existing settings or policy file over a new format.

## Out of scope

- Egress proxy and moving `init-firewall.sh` out of the guest (already in ADR-003 and the landscape note).
- Short-lived OIDC task tokens (already a design constraint in ADR-007; not specified here).
- A new GitHub pull-request template or changes to receipt fields (ADR-014).
- Implementation of the Cloud SQL migration-spec template (a Triple dry run, not a harness change).
- Auto-merge, starting orca, or changing Triple profile merge rules.

## Risks

- False escalations will cost human time. Wasowski notes the same trade. Measure unjustified aborts in the trial, and do not punish the honest path to reduce that count.
- Lab numbers in the source articles are not acceptance criteria.
- A new policy file that the agent can edit is worse than no file. Write access must be tested.

## Rollback

Revert the instruction and test changes. Leave existing `escalate` behavior in place. No stored evidence needs a migration if WP1 and WP3 only add a class and a test.
