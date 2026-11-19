# Proposed plan: a counterexample test for specs during the grill

- **Status:** Proposed. Not accepted, not implemented, and not permission to change any gate, hook, agent or test.
- **Date:** 2026-11-19 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-spec-counterexample-test-plan.md`. No ADR yet. If Pedro accepts an option, the decision gets its own ADR and work packages stay here.
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** ADR-002 (Change-Class ladder and light lane), [ADR-007](../adr/ADR-007-evidence-closed-loop.md) (spec fingerprints and stale passes), [ADR-008](../adr/ADR-008-harness-inside-agent-factory.md) (judge role), `payload/owned/.claude/agents/griller.md`, `payload/owned/backbone/8-WORKFLOW.md` Phase 1, draft PR #99 (judge review hygiene).

## Why

A spec can pass the griller and still let through a wrong implementation that looks right. The griller is told to ask one question about this: "Could an implementation pass every criterion and still be wrong?" It answers in prose, mixed with every other finding. Nothing records which clause stops which wrong version, which plausible wrong versions no clause stops, or which clauses stop nothing.

A cheap, structured test exists for that. An agent that sees only the spec writes 5 to 10 plausible wrong implementations, each breaking a different intent, and names the clause that rejects each one. A counterexample with no clause is a gap. A clause with no counterexample may be dead text.

## Evidence and baseline

### External sources

- Jaroslaw Wasowski, ["The Smallest Spec That Rejects Wrong Code"](https://medium.com/@wasowski.jarek/the-smallest-spec-that-rejects-wrong-code-discriminating-power-counterexamples-and-spec-weight-d948e0909afc), Level Up Coding, 26 Oct 2026. Read in full on 19 Nov 2026. He proposes the prompt, the clause-to-counterexample map, a second model for risky changes, and keeping the counterexamples out of the implementing agent's context. He says the output is a list of candidates for a person to judge. It is a practitioner's method with no study of its own.
- Foster, Gulati, Harman et al., ["Mutation-Guided LLM-based Test Generation at Meta"](https://arxiv.org/abs/2501.12862), FSE 2025 industry track. Checked on 19 Nov 2026. An LLM wrote mutants for a described bug class (9,095 that build and pass), and the system generated 571 tests. Engineers accepted 73% of 191 reviewed tests and judged 36% privacy relevant. About 25% of the LLM mutants were trivially equivalent. This supports LLM-written plausible faults as a working technique. It targets code tests and does not validate the spec-review use.
- KB summary: `20-Platform/Research/SDD/plt-SDD-Smallest-Spec-Counterexamples-Wasowski-2026-10.md` in the knowledge base, branch `soyPeter/medium-harness-spec-notes-2026-11-19`.

### Harness today (code and docs read on 19 Nov 2026 at `origin/main` `4767350`, nothing run)

- The griller (`payload/owned/.claude/agents/griller.md`, generated for Codex and OpenCode) reads the spec, its ADRs, the PRD, `4-KNOWLEDGE.md` and `7-CONVENTIONS.md`. It already asks the question quoted above and treats over-specification as a major finding to remove. It returns questions with severity and an optional recommendation. Later rounds look only at the diff and ask at most 5 questions.
- `record_verdict()` (`harness.py` L3167) keeps only `questions` from a grill report (L3196 to L3199). Any extra field the griller returns is dropped today.
- The grill pass is bound to `spec_fingerprint()` (L1127). ADR-007's first P1 slice made judge, review and tester passes stale when the spec changes.
- `HARNESS_GRILL_MAX_ROUNDS` (default 3, L368) bounds grill rounds and escalates after that.
- Spec weight is already handled by the Change-Class ladder and the light lane: `docs` and `refactor` can take lighter paths, `schema` never takes the light lane, and `feature` and `schema` always need a human `Approved-by:`.
- With `HARNESS_TESTER` on, acceptance tests are written before code and fingerprinted, so the implementer can't weaken them.
- Orca maps roles to agents (`HARNESS_ORCA_AGENTS`, `agent_for()` in `coordinator.py`). A role such as `griller` can already run on another family by configuration.
- Draft PR #99 adds to ADR-008 that the judge brief stays unsteered: spec, git range and usage model, without earlier findings.

Not checked: how often grill passes today miss gaps that a judge or a person later finds, and whether any project already runs a similar prompt by hand.

### What is new and what is not

The counterexample idea overlaps with the griller's one question and with mutation testing advice in the `module-testing` skill. Neither produces a clause-to-counterexample map, flags dead clauses, or runs on a second family. This plan adds only that, inside the existing grill step. It adds no new phase, role or gate.

## Options

| Option | For | Against |
| --- | --- | --- |
| A. Do nothing. Leave it to the griller's one question | No cost, no noise | No record of gaps or dead clauses. Nothing to measure |
| B. Griller step, same context. Add a counterexample step to the griller's procedure and record the map in the grill verdict | One agent, one round, reuses questions, recommendations and the apply flow | The griller has read ADRs and the PRD, so its wrong versions may follow what it read instead of the spec text. Wasowski's "spec only" rule is bent |
| C. Separate spec-only pass. The harness sends only the spec text to a fresh griller session in counterexample mode. Its gaps and dead clauses come back as griller questions | Matches the source method. Fresh context per pass. Can run on a second family | One more agent call per spec revision. A second record to bind to the spec fingerprint |
| D. Make it a blocking gate for every spec | Strongest | LLM output is noisy (equivalent mutants, blind spots). Blocking on it would stall honest specs. Costs a call on every docs change |

Recommended: **C, opt-in and report-only first**. Run it on `feature` and `schema` specs only, never on the light lane or `docs`. A second family runs it for `schema` specs and for specs the risk assessment marks elevated.

## Where it fits

- **Phase:** Phase 1, after the griller's first pass on a structurally valid spec and before the user's approval. It runs again only when the spec's Requirements or Acceptance criteria change.
- **Who runs it:** the griller agent, in a fresh session, with a brief the harness builds: the spec text from Context to Out of scope, nothing else. In Orca the coordinator starts it as a `grill` worker with a counterexample instruction. In a supervised session the main session starts it when `next` says so.
- **What it returns:** 5 to 10 candidates, each with the intent it breaks (one sentence) and the clause id that rejects it (`REQ-...`, `AC-...`) or `none`, plus the list of clauses no candidate touches.
- **How results enter the flow:**
  - A candidate with `none` becomes a **major** griller question. Its recommendation is either one new clause, preferably an "unchanged behaviour" requirement ("The system shall continue to ..."), or "accept the risk", which the user records under Assumptions or Out of scope.
  - An untouched clause becomes a **minor** question that recommends sharpening it, moving it to an ADR, or removing it. It never blocks.
  - The candidates count toward the griller's 5-question limit per round, most severe first.
- **Who judges:** the user sees the map at the "grill the user" step and at approval. A person decides which candidates are real. Equivalent candidates are dismissed with one line.
- **Artifact:** `backbone/.verdicts/<id>.counterexamples.json`, append-only like other verdict files, bound to the spec fingerprint. Fields: `candidates[]` (`intent`, `clause` or `none`, `disposition`: `gap`, `covered`, `equivalent`, `accepted-risk`), `untouched_clauses[]`, `agent`, `family`, `fingerprint`, `at`. The receipt adds one line: candidates run, gaps closed, risks accepted.
- **Visibility:** the implementer never gets the candidates. The tester works from the spec, as today, so a closed gap reaches it as a clause. The judge does not get them by default, which keeps the brief unsteered as PR #99 proposes. See decision 3.
- **Flag:** `HARNESS_SPEC_COUNTEREXAMPLES="off|report|on"` in `harness.conf`, default `off`. `report` records the map and raises the questions as minors. `on` raises gaps as majors, so the existing grill pass rule applies. No new block exists beyond that rule.
- **Cost bound:** one fresh call per spec revision that changes Requirements or Acceptance criteria, at most 10 candidates, and at most `HARNESS_GRILL_MAX_ROUNDS` runs per task. A second family doubles it for `schema` and elevated-risk specs only.

## Work packages

1. **WP0. Baseline by hand (read-only).** Run the source prompt on 8 to 10 recently approved `feature` or `schema` specs in this repository and in the `triple` pilot, once with Claude and once with Codex. For each spec record: gaps a person confirms, dead clauses, equivalent candidates, which of those the griller already raised, and tokens and minutes spent. Exit: a table in the PR. **Stop rule:** if fewer than 2 confirmed gaps across all specs were missed by the griller, report that, recommend option A, and stop.
2. **WP1. Recorder and brief.** Add the counterexample mode to the griller's instructions (`griller.md` and the generated Codex and OpenCode files), the spec-only brief, `.counterexamples.json` bound to `spec_fingerprint()`, and the mapping to griller questions. `next --json` names the step and its reason. Report-only. Depends on WP0 and Pedro's go-ahead.
3. **WP2. Visibility.** Refuse implementer and tester reads of `.counterexamples.json` through the existing role guards. Leave the judge out of it unless decision 3 says otherwise.
4. **WP3. Second family.** For `schema` and elevated-risk specs, run the pass on the next installed family from `HARNESS_ORCA_AGENTS`. Record `family` per run. If that family is out of usage, record the run as not done. A missing run never counts as a pass.
5. **WP4. Template and docs.** One comment line in `templates/spec.md` under Requirements: for a bug fix, add a requirement for behaviour that must stay the same. Update `8-WORKFLOW.md` Phase 1, `HOOKS.md` and `docs/sdlc/README.md`.
6. **WP5. Tests** in `tests/run-tests.sh` or a new `tests/test-spec-counterexamples.py`:
   - with the flag `off`, nothing changes;
   - a recorded `none` candidate becomes a griller question with the right severity per mode;
   - an untouched clause becomes a minor;
   - a spec change makes the map stale;
   - an implementer read of the file is refused;
   - a light-lane or `docs` spec skips the step;
   - a second-family run that did not happen shows as not done in the receipt.

## Acceptance evidence

- The WP5 cases pass in CI with the flag `off` and `report`.
- On the Wasowski category example used as a fixture spec, a recorded candidate that guesses unknown categories maps to `none` until an "unchanged behaviour" clause is added. After that it maps to that clause.
- The receipt of a task run with the flag on shows the counterexample line.

## Risks and rollback

- **Noise.** Equivalent or unrealistic candidates waste the user's time. Mitigation: report-only first, the 5-question cap, and WP0's numbers before any build.
- **Spec growth.** Closing every gap can bloat specs, which the source warns against. Mitigation: recommendations prefer one "unchanged" clause or an accepted risk, and the griller keeps flagging over-specification.
- **False comfort.** An LLM misses whole bug classes. The source cites a study where about 17% of real bugs had no matching mutant. The judge, the tests and human review stay as they are.
- **Leakage.** Candidates reaching the implementer can make it code to the list. WP2 guards that.
- **Cost.** One extra call per qualifying spec revision, doubled for `schema`. WP0 measures it.
- **Rollback:** set the flag to `off`. Revert the recorder and guard commits. Old `.counterexamples.json` files stay readable and are ignored.

## Out of scope

- Generating code mutants or tests from the candidates. Meta's ACH does that for code. It would need its own plan.
- Changing the judge's brief or verdict rules. PR #99 owns that.
- A spec-weight matrix. The Change-Class ladder and the light lane already set how much spec a change needs.
- Any change to who approves a spec or merges a PR.

## Decisions needed

1. Accept option C (recommended), B, or A.
2. Which specs qualify: `feature` and `schema` only (proposed), or every non-light spec.
3. Should the judge see the confirmed gaps (not the raw candidates) as a checklist? Proposed: no, to keep the brief unsteered.
4. The trigger for a second family: `schema` plus elevated risk (proposed), or `schema` only.
5. Who runs WP0 (proposed: an Orca worker on fixture specs, started by Pedro, or Pedro by hand).
