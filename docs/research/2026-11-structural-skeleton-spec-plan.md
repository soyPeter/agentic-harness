# Proposed plan: an optional code-like skeleton in the spec's Architecture section

- **Status:** Proposed, parked after WP0 (no-go for WP1 now; see WP0 results). Not accepted, not implemented, and not permission to change any template, agent, gate or test.
- **Human decisions recorded (10 Nov 2026, Pedro):** run WP0 as read-only analysis; first level is stubs only (signatures and types, no contracts); a signature mismatch against the frozen skeleton is a judge **blocker**.
- **Date:** 2026-11-10 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-structural-skeleton-spec-plan.md`. Work packages and evidence remain here; the decision is recorded in [ADR-016](../adr/ADR-016-structural-skeleton-spec.md).
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user.
- **Related:** `payload/owned/backbone/templates/spec.md` (Architecture, Tech requirements); `payload/owned/.claude/agents/architect.md`; `payload/owned/.claude/agents/judge.md`; `HARNESS_REQ_STYLE=ears` as the precedent for an opt-in spec style; [ADR-002](../adr/ADR-002-change-class-ladder.md); [ADR-004](../adr/ADR-004-traceability-export.md). Does not depend on [ADR-007](../adr/ADR-007-evidence-closed-loop.md), [ADR-006](../adr/ADR-006-external-agent-resource-admission.md) or the [delegation-contracts plan](2026-11-delegation-contracts-qualification-plan.md). Distinct from the dependency-gate plan (task order) and the PR-body opener plan (review summary).

## Decisions (2026-11-10)

Pedro accepted the following defaults:

- Accept the WP0 no-go and keep the plan parked.
- Re-run WP0 only for a greenfield task, a project with the tester on, or judge failures caused by interfaces or type mismatches.

## Evidence and baseline

### External evidence (primary source, read)

Golatkar, Achille, Zabounidis, Sobal et al., *Skeleton Coding: Program Structure as a Specification for Agents*, AWS Agentic AI, [arXiv:2610.38214v1](https://arxiv.org/abs/2610.38214), 28 Oct 2026. PDF SHA-256 `1f38624ee567052360de81114490502db99422dbe60ea32520c572082963a323`. Sections 1 to 5 and appendices A to D read; proofs skimmed. KB note: `20-Platform/Research/SDD/plt-SDD-Skeleton-Coding-AWS-2026-10.md`.

What it reports, on the authors' own setup (not reproduced):

- Code-like structure (stubs, signatures, per-function contracts, global invariants) cut mean test error 48.4% against the best purely behavioural spec, across four models and three benchmarks.
- Code-like stubs beat prose architecture documents, even prose 4 to 7 times longer.
- Correct but overly detailed contracts lowered pass rates, mostly for smaller models.
- A small model with a detailed skeleton came within 5 to 8 points of the large model at 15 to 26 times lower implementation cost.
- An informal contract checked by an LLM judge has a false-accept floor that no judge removes (Proposition 3.2). Mechanical checks per component are much cheaper than whole-program rejection (Proposition 3.1).

Limits that matter here: skeletons were generated from the true reference code, tasks were mostly greenfield rebuilds of public projects, contracts were not machine-checked, and spec-writing cost was excluded. The paper does not show that an architect agent can write a good skeleton, or that it helps on brownfield tasks in an existing repository.

### Supporting practitioner view (talk, not a study)

A 57-minute session by the pstack author (reposted on X by [@yourm11nd](https://x.com/yourm11nd/status/2119926038532866197), 9 Nov 2026; auto-transcribed, speaker inferred as Lauren Tan) makes the brownfield version of the same argument. Greenfield code without guardrails drifts because agents pick whatever is convenient. Structure enforced in code and CI (import-boundary checks, banned patterns, one directory per feature) works better than rules an agent reads. KB note: `20-Platform/Research/SDD/plt-SDD-Tan-Trust-Verification-Talk-2026-11.md`. Her auto-merge practice is not part of this plan.

### Harness baseline (read at `origin/main` `6e2f8ac2fac5f3ac8d279be42b8fe7c607de3410`, not executed)

- `backbone/templates/spec.md`: `## Architecture` holds `ADRs:` and free-text `Tech requirements:` bullets ("layers, libraries, patterns, data, API contracts").
- `architect.md`: "Keep tech requirements to the decisions that matter for correctness and the ADRs: module, public interface, data types, error types. Don't write the implementation into the spec." So the content the paper calls a skeleton is already asked for, in prose.
- `judge.md`, step 1 and step 6: the judge reads "the NFRs and tech requirements" and looks for violations. No mechanical check that the code matches the named interfaces was found.
- No grep hit for `skeleton`, `stub` (other than test tooling and the tester rule "never write production code, stubs of it") or signature specs in the templates, agents, local drafts or KB.
- `HARNESS_REQ_STYLE=ears` shows the pattern for an opt-in spec style with `spec-check` support.

**Gap (hypothesis):** the harness has the right content in the wrong format for agents, and the judge checks interface conformance only by reading. Whether that costs us anything on real tasks is unknown. WP0 must find out before anything is built.

## Options

| Option | Benefit | Cost / risk |
|---|---|---|
| A. Keep prose Tech requirements; note the paper | No change | Leaves a cheap, evidence-backed format unused |
| B. Opt-in skeleton block in Architecture (recommended if WP0 shows a signal) | Code-like stubs with short contracts, approved and frozen with the spec; judge checks them; reuses the EARS opt-in pattern | Architect effort; risk of overspecifying (the paper's own warning); a wrong skeleton gets frozen; language-specific checks |
| C. Make skeletons mandatory for `feature`/`schema` | Uniform | No evidence on our tasks; heavier review for the user; conflicts with "simplest design" |
| D. Generate stub files into the repo before the implementer starts | Agent sees real code | Turns the architect into a code writer, which `architect.md` forbids; mixes spec and code ownership; needs an ADR |

**Proposed: B**, conditional on WP0. C and D are not proposed.

## Proposed behaviour (B)

1. **Opt-in:** a user-only setting, for example `HARNESS_SPEC_SKELETON=off|stubs` (default `off`), set like `HARNESS_REQ_STYLE`. A later `contracts` level is out of scope until a pilot shows stubs help; the paper found overly detailed contracts lowered pass rates.
2. **Where:** a fenced code block under `## Architecture`, `Skeleton:`, in the project's language. It holds only public or cross-module types and callables the task adds or changes: names, signatures, field types and error types, each with a one-line purpose. No `Requires`/`Ensures` contracts at this level. Bodies are `...` or the language's placeholder. No algorithms or message wording, which keeps the existing "don't write the implementation into the spec" rule.
3. **Size guard:** `spec-check` warns when the skeleton grows past an agreed limit, based on the paper's finding that excess detail hurts. WP0 proposes the number.
4. **Approval:** the skeleton is part of the spec, so the user's `Approved-by:` and the grill fingerprint cover it. Agents cannot edit it after approval, same as the rest of the spec. A needed change goes back through the architect and a new approval.
5. **Judge:** checks each skeleton entry exists in the diff with the same name, parameter types, return type and declared errors. A missing entry or a signature that differs from the frozen skeleton is a **blocker** (decided by Pedro, 10 Nov 2026). The fix is to change the code, or to send the skeleton back through the architect and a new approval; an agent may not edit the skeleton to match the code. The independent judge stays the decider.
5a. **Tester:** when `HARNESS_TESTER` is on, the tester writes acceptance tests against the skeleton's names instead of assuming them (today `tester.md` says to report "which names you assumed" when the Architecture names no interface).
6. **Mechanical check (later, per language pack):** where cheap, a pack can supply a signature-match check (for example compiled-class signatures in Java). That check backs the judge and does not replace it. It is scoped to WP3 and only after WP2 shows value.

Unchanged: EARS and Given/When/Then stay the evidence layer, Change-Class rules, human approval and human merge, independent judge, evidence bound to the reviewed revision, Linear as tool of record, Monday update as the single status report.

## Work packages

| WP | Scope | Depends on | Acceptance / evidence |
|---|---|---|---|
| WP0 Offline check | Take 6 to 10 closed harness tasks with judge history. For each, write a skeleton from the approved spec only (not from the final code). Count judge fail rounds and findings that a skeleton would have prevented (wrong interface, wrong data type, extra layer). Note skeleton size and time to write | none | Findings note at a pinned revision with the task list and counts. **Stop and close the plan if fewer than about a fifth of failed rounds trace to structure.** The threshold is a proposal for the maintainer to set |
| WP1 Format | Template block, `HARNESS_SPEC_SKELETON=off\|stubs` setting, architect instructions, `spec-check` shape and size warning | WP0 go | Tests: a spec with the setting on and no skeleton fails `spec-check` for `feature`; a skeleton with bodies fails; an oversized one warns; setting off leaves today's behaviour byte-identical |
| WP2 Judge + pilot | Judge step for skeleton conformance (mismatch = blocker); pilot on one Triple project with the setting on for a few weeks | WP1 | Judge verdicts list skeleton entries as met or unmet with `file:line`; a renamed or retyped entry fails the verdict as a blocker. Pilot report compares fail rounds and review time with the WP0 baseline. User decides go or stop |
| WP3 Pack checks | Optional signature-match check in one language pack | WP2 go | Test: a renamed public method fails the check; unchanged code passes |
| WP4 Docs | HOOKS.md/AGENTS.md, triple pack README, CHANGELOG | WP1 to WP3 | Docs name the setting, its default and its limits |

Out of scope: generating code from skeletons, formal verification (Dafny, Verus, Lean), model routing to smaller models, changes to approval, judge independence or merge.

## Risks and rollback

- **Frozen wrong design.** A skeleton written before the code is explored may be wrong. The architect already explores the code first; the change path is a new approval, not an agent edit.
- **Overspecification.** The paper shows more detail can hurt. The size guard and "public or cross-module only" limit this.
- **Review load.** The user approves more text. Stubs are usually shorter than prose, but WP2 must measure review time. The thread author's point that long spec prose is hard to sign off applies.
- **Transfer.** Greenfield results may not hold for brownfield work in existing repos, where the code already narrows the design. WP0 uses our own tasks for that reason.
- **Rollback:** set the option to `off`; nothing else changes. Specs with a skeleton block stay valid.

## WP0 results (10 Nov 2026, read-only)

**Method.** Read-only on Estix. No working copy changed, nothing run, no tests executed. I looked for every project on the machine with harness task records (`backbone/specs/*.md` plus `backbone/.verdicts/*.json`) under `/Users/peter/Work/repos`. Only one has them: `tests/coefficiency` at `44057bad09cd189c9e1efa818cfda413ab0cff44` (Java, Jooby/JDBI/SQLite, brownfield refactor, harness 0.17.0, `HARNESS_TESTER` off). `agentic-harness` itself, `coef-calc`, `colsum`, `triple`, `triple-disputes` and `agentic-backbone` have no harness specs or verdicts in their tracked files (git history also checked for `coef-calc` and `colsum`). For each task I read the spec's Architecture section size and every grill and judge round in the verdict history, and classified each finding: **structural** (a public type, signature, field set, error type or module placement a stubs-only skeleton would have stated) or **other** (fixtures, test commands, baselines, tooling, scope wording, ignore rules, environment).

**Tasks (6, below the 6 to 10 target because no more exist).**

| Task | Spec size / Architecture lines | Grill rounds (fail) | Judge rounds (fail) | Structural findings |
|---|---|---|---|---|
| 6.1 (draft, later split) | 5 / 0 | 1 (1) | none | 2 of about 9 questions (controllers holding JDBI types; layering split of a requirement) |
| 6.1a | 196 / 102 | 5 (3) | 1 (0) | 2 of 13 (request DTO field types; where shared validation lives) |
| 6.1b | 270 / 114 | 4 (2) | none (not implemented) | 0 of 4 |
| 6.1c | 280 / 131 | 6 (2) | 2 (0) | 2 of 5 (update request has 8 fields, frontend sends 11; image-build API call). Judge: 2 minor structural notes (a build call differing from Tech requirements, a duplicated constructor) |
| 6.1d | 196 / 87 | 4 (1) | none (not implemented) | 0 of 3 |
| 6.1e | 253 / 119 | 3 (1) | none (not implemented) | 1 of 3 (scope of two new `SettingsService` methods) |

**Findings.**

1. **Judge: zero failed rounds.** Both implemented tasks (6.1a, 6.1c) passed the judge first time. 6.1c's second judge round, on 3 Nov, re-judged new code and also passed. The plan's stop rule ("fewer than about a fifth of failed rounds trace to structure") is met trivially at the judge: there are no failed rounds to explain.
2. **Grill: structure caused about 7 of about 37 questions (roughly 19%) across 10 failed rounds.** All were caught before approval. A stubs block might have made some visible earlier, for example the 8-field versus 11-key mismatch in 6.1c. The griller already catches them.
3. **The specs are already near-skeletons in prose.** Architecture sections run 87 to 131 lines and name records, fields, boxed types, method names and error mapping. The paper's main gain comes from greenfield work where the agent picks the structure. Here the structure was fixed in detail by the architect and by the existing code.
4. **Most spec failures were about evidence, not structure.** Fixtures that cannot tell right from wrong code, test-command and baseline choices, missing lint config, and runtime checks that depend on files not written yet.

**Limits.** One project, one stack, one person, brownfield only. Only two tasks reached the judge, and the tester role was off. Classification is mine and was not checked by a second reader. The verdict files keep reasons, not timings, so I could not measure review time.

**Recommendation: no-go for WP1 now.** Park the plan as Proposed, with the decisions above recorded. Re-run WP0 when either (a) a greenfield task or a project with `HARNESS_TESTER=on` has judge history, or (b) any project shows judge failures traced to interface or type mismatches. If the user wants a zero-cost trial in the meantime, the architect could put the signatures it already lists in a fenced block inside today's Tech requirements on one task. That is a writing choice inside the existing section and needs no harness change.

## Decisions needed (human)

Resolved on 2026-11-10. See Decisions (2026-11-10).
