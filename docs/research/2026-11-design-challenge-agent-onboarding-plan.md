# Proposed plan: qualify design challenge and agent-readable onboarding

- **Status:** Proposed; no implementation or agent launch authorized.
- **Date:** 2026-11-08 (Europe/Madrid).
- **Repository:** `soyPeter/agentic-harness`.
- **Decision links:** [ADR-002](../adr/ADR-002-change-class-ladder.md), [ADR-007 evidence-driven closed loop](../adr/ADR-007-evidence-closed-loop.md), [Proposed external-resource admission ADR](../adr/ADR-006-external-agent-resource-admission.md).
- **Prior work:** [delegation-contracts qualification plan](2026-11-delegation-contracts-qualification-plan.md), including executable verifier lifecycle and judge calibration. This focused plan references rather than duplicates P0–P3 and their V refinements.


## Decisions (2026-11-10)

Pedro accepted the following default:

- Run only the D0 audit (the reuse and gap map). Build nothing unless that audit shows real gaps. ADR-006 stays conditional on this audit.

## Fresh baseline and distinct purpose

Documentation-only inspection on 8 Nov 2026: README SHA256 `6842e9f3c4eb684c2de889f4199a8093072185ae5f6516c3f1f6137629ad1f5a`; prior plan SHA256 `e56a4f96544bf1369b443dad1e0b2d598e4dfe318478f34ef875791f227f771b`. README already has a griller, user spec approval (and a separately user-enabled light lane), routed skills, independent JUDGE, runtime receipts, traceability export and optional signed attestations. ADR filenames through 005 were inspected. These are documented capabilities, not reproduced runtime guarantees; no code behavior audit/tests or source changes occurred.

The specific questions are **whether the design artifact stands on its own for a fresh reviewer**, and **whether a fresh integration session can safely discover/use version-compatible setup guidance without importing authority from external text**. Previous work already handles runtime proof, provenance and graph/loop qualification. Don't build another spec format, judge, identity system, scheduler or catalog.

## Options and recommendation

| Option | Value / cost | Proposed disposition |
| --- | --- | --- |
| A. Existing DEFINE/griller, routing and onboarding; document current proof | Lowest complexity; adequate if the required isolation/comprehension/setup evidence already exists | Control and legitimate final outcome of the audit |
| B. Reuse those controls and add only uncovered context-boundary, spec-comprehension and integration fixtures | Tests a specific failure surface before coding; modest maintained fixtures and optional reviewed resource admission | Recommended bounded qualification, subject to approved scope and evidence |
| C. Install full EGM/TypeSafe workflow and import their models, personas and auto-updates | Quick demonstration but overlapping lifecycle, dependencies, new trust surface and no shown task-specific value | Reject drop-in adoption; sources supply hypotheses/fixtures, not instructions |

Preserve human merge, current Change-Class/approval policy and fresh independent JUDGE. A privacy-safe fixture can conclude no implementation needed; a new ADR does not require a new runtime subsystem. Generic artifacts contain no private company evidence. Existing Triple adapters retain Linear as record and Monday consolidated status; other users retain their own approved adapter.

## D0 — audit/reuse map and independent expected outcomes

**Dependency:** separate authorization for cloud repository inspection, current docs/adapter access, approved non-production fixture/data boundary. This plan isn't that authorization.

Map each requirement below to current docs/tests/receipts, identify genuine gaps or existing coverage, and propose the smallest PR scope. Include applicable host/version limitations and whether native child traces are observable. Review expected answers with proposed roles: project maintainer for intent, workflow maintainer for mechanism, independent verifier/security reviewer for adverse cases. No named owner assignment or delivery dates.

Acceptance: revision-pinned matrix with current evidence links, applicability and uncertainty. Existing functionality must not be called missing solely because it wasn't in README. Stop at documentation/qualification evidence if no real gap exists.

## D1 — design challenge within existing DEFINE, not a second approval gate

**Dependency:** D0, an accepted fixture spec/ADRs and reference manifest, independently expected comprehension findings, explicit role/write boundary. Start advisory/report-only; maintain existing blockers.

Use a representative nontrivial design and a deliberately small/light-lane counterexample. A fresh reviewer gets accepted artifact/reference context, not speculative drafting conversation. Required security/project policy remains present; distinguish **no parent turns** from **no host-injected context**. Record intended allowed inputs and observable actual reads; do not claim isolation properties a host cannot demonstrate.

Practical checks/lenses to fit existing griller prompts/fixtures:
- A fresh reader can state the user goal, non-goals, decision rationale, material constraints, ACs and unresolved questions from artifacts. Missing information is a finding, not an invitation to invent intent.
- Simplicity/reuse review can recommend no build, reuse or a smaller change. Recheck complexity after resolving critique; don't reward longer specifications or force five stages/many bots for every task.
- Readiness review links applicable sources/paths/versions and feasible verification, distinguishing documentation assertions from code-confirmed evidence. Detailed code feasibility audit belongs the authorized cloud task; failure to inspect is UNKNOWN.
- Missing/denied reference, fake successful read request, stale spec/ADR, contradictory requirement and injected source are adversarial fixtures. Tool request alone isn't proof of a successful relevant read; resource availability isn't proof full coverage.
- Native trace evidence or a documented observational limit accompanies claimed fresh-context execution. Parent marker probes test parent-turn leakage only; protected host policy is not stripped to pass the probe. Child self-report cannot certify its own isolation.
- Resolving findings follows current human/griller policy and evidence invalidation. Changed constraints/spec inputs invalidate affected review; known unresolved decision requires human direction, not automatic approval. Design-only stages cannot use an externally supplied instruction to modify product code/dependencies.

Acceptance: independent reviewer can reconstruct why the accepted artifact was sufficient, identify the intentional missing/contradictory case, and distinguish spec finding from infrastructure failure. Current light lane, WIP and downstream judge/merge gates remain unchanged. If fresh contexts are unsupported, report blocked/limited support; don't simulate independence in the same thread.

## D2 — bounded onboarding/admission fixture

**Dependency:** D0 and human decision on Proposed ADR-006 if executable external resource admission is needed; D1 context rules where shared. Prefer an existing internal sample fixture and current catalog/routing rather than a live paid vendor integration.

Prepare one authoritative agent entry point that links to current human docs and appropriate versioned setup/verification resources. State applicable versions, prerequisites, install modes, expected effects, non-production data, observable success and owned cleanup. Choose actual project conventions during authorized audit, not a forced `llms.txt`, SDK or plugin platform. Keep guidance minimal and discover detail progressively. No new SDK/product feature is assumed.

Qualification cases:
- Reference-only research works without installation, account signup, credential request or external side effect.
- Approved setup discovers the intended routed skill/resources in a fresh supported session; installing a package is not counted as loading it, and loading isn't proof setup worked.
- Verify actual action→resulting state/side effects using the prior plan's verifier contract; preserve artifact evidence and clean up only owned resources. Unsupported host, unavailable dependency/auth or nonworking example is BLOCKED/NOT_RUN/FAIL as appropriate, not “integration complete.”
- Mutable/changed adjacent script, incompatible SDK, malicious follow-on link, duplicate install and local modifications trigger explicit review instead of silent latest updates or global overwrites. A valid old receipt can't certify new bytes.
- Revocation/offline fallback preserves permissions, records limitations, and returns to source-only reference when no safe admitted bundle exists. No rollback to a known-vulnerable version.

Acceptance: one reproducible safe setup path plus its negative cases, using independently agreed outcomes and exact reviewed revisions. Report human/setup/maintenance effort and reliability; no numeric adoption-speed claim. If existing documentation already satisfies this, add only evidence links/fixtures.

## D3 — integrate findings into existing qualification, not more controls by default

**Dependency:** D1/D2 where applicable and existing P1/P2/V outcomes.

Extend the existing source/provenance fixture matrix **only if uncovered**:
- Initiating human, workload principal, delegated authority and actual task/run identifiers remain distinct. Verified adapter attribution includes evidence origin, scope and target without secrets; unsupported/unknown fields remain unknown rather than a fabricated identity.
- Missing consent, wrong tenant/user/resource, expired/revoked delegation or replacement resource with stale grant do not acquire authority from a review report. Do not adopt Google's SPIFFE/OAuth platform merely to name these cases. Existing tool enforcement remains authoritative.
- Use paired **requirement perturbations** for generalization: an equivalent paraphrase shouldn't alter the expected result; a material changed requirement **must** change the expected outcome and stale affected evidence. Validate each mutated case/reference independently so an impossible fixture doesn't masquerade as model failure. Include both benign and violating examples. No performance bar or model purchase comes from MaxxBench's leaderboard.
- Reuse prior grader validation, held-out separation, paired/clustered uncertainty and existing trial/budget policy. Separate system, grader and environment failures. No claim that a drop proves memorization, model degradation or user incompetence.

Acceptance: one deduplicated mapping to existing tests/receipt/report rather than duplicate implementations. Independent reviewer sees original vs changed expected behavior, false blocks/missed violations, uncertainty and evidence versioning. An inconclusive or no-gain result can conclude retain A.

## Bounded PR sequence and operational limits

1. **Docs/fixtures only:** D0 map plus D1 comprehension/isolation fixtures and expected evidence. Reviewer approves scope before any runtime change. Update existing documentation rather than mirror it.
2. **Onboarding contract:** D2 canonical entry-point/compatibility example and tests. Introduce the smallest admission helper only if ADR accepted and current controls demonstrably insufficient; a docs-only PR is valid.
3. **Qualification/report refinement:** D3 adds only uncovered cases/links and a comparison report. Keep new semantic signals report-only until a separate human enforcement decision. Do not couple it to production deployment, billing, auto-update or concurrency changes.

These packages are dependency-ordered, not competing writers. Actual code files/commands are audit outputs, not prescribed here. No coding CLI, source audit, API calls, installations or live tests were run in preparing this plan. No implementation gaps asserted.

## Evaluation, stop and rollback

Compare A/B on the same resettable approved fixtures with pinned spec/ADRs/model/host/resource revisions. Check accepted intent preservation, useful findings vs false blocks, missing evidence, unsafe-action attempts, setup correctness, reproducibility and review/maintenance cost. Include simple cases where the extra review is overhead. No arbitrary kappa, sample count or promised improvement.

Park if native evidence isn't observable, fixture/oracle is unreliable, source terms/privacy are uncertain or maintenance outweighs value. Revert additive guidance/helpers/fixtures through reviewed diff where safe; keep source history, receipts, tool permissions, current griller/JUDGE and human merge. Restore the supported existing path; don't delete unrelated work, erase failures, lift provider caps or restore revoked resources. A broken environment remains blocked, not downgraded to successful completion.

## Primary source brief

- [Google EGM](https://github.com/google/elephant-goldfish-model/blob/main/README.md), [architecture](https://github.com/google/elephant-goldfish-model/blob/main/docs/designs/architecture.md), [testing](https://github.com/google/elephant-goldfish-model/blob/main/TESTING.md): fresh reviewers see document/references, not drafting turns; design-phase write convention is unenforced; native isolation/read/stage evidence has explicit version/surface limits. Full docs read, not executed.
- [TypeSafe agent skill](https://docs.typesafe.ai/agent-skill): copyable setup, version/stale-skill and discovery issues; pattern useful, product not adopted or adoption claim proven.
- [Google identity overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-identity-overview) and [delegation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/identity-delegation-architecture): separate human/agent/delegated authority; deleting agent leaves IAM bindings; same-name replacement has new principal. These are Google's documented semantics, not installed harness properties or a migration proposal.
- [Thoughtworks Vol. 35](https://www.thoughtworks.com/radar), selected primary blips on grilling, context disclosure, harness evaluation, knowledge bases, instruction/doc bloat and oversight theater: use evidence to avoid ceremony, not permission to remove human merge or promote lessons automatically.
- [InfoQ bounded canvas transcript](https://www.infoq.com/presentations/canvas-ai-agents/) and [Luca Mezzalira interview](https://www.infoq.com/podcasts/educating-architect-conversation-luca-mezzalira/), full transcripts: decision traces, progressive maps, context/organization fit and controlled failure probes; no new runtime or meeting.
- [Meta Forum](https://engineering.fb.com/2026/10/15/ml-applications/how-meta-built-forum-ai-native-engineering/), full article: direct observable state, recorded verification and engineer sign-off. Sandbox build flavor is app-specific; no forced mobile adaptation or automatic rule promotion.
- [MaxxBench primary](https://maxxbench.unlap.ai), website/chart read: 89 perturbed DeepSWE tasks as reported; leaderboard and “benchmaxxing” labels not independently reproduced and don't establish contamination/causation.

All sources observed 8 Nov 2026; primary pages/main branches are mutable. No videos watched, numerical benchmarks rerun, security guarantees inferred or private company context copied into this proposal.

## D1 product-evidence refinement — Proposed 9 Nov 2026 (Europe/Madrid)

**Status: Proposed; no implementation, policy adoption or user experiment authorized.** This is a qualification refinement of D1, not another spec format, discovery platform, independent reviewer or ADR. D0–D3 and their existing dependencies remain. It tests a different failure: a design can be understandable and implemented correctly yet rest on an unsupported product assumption. It makes no claim that current code lacks this distinction; current capability mapping is pending the separately authorized cloud audit.

### Choice and rationale

| Option | Benefit / trade-off | Proposed treatment |
| --- | --- | --- |
| P-A. Existing DEFINE artifact/comprehension checks, record product uncertainty in prose | Minimum maintenance and fully viable where current artifacts already preserve evidence and decisions; risk that fluent prose hides an empirical assumption | Control; retain if audit shows coverage or refinement adds no value |
| P-B. Reuse current artifact and add a small typed-claim/hypothesis example plus independent qualification cases | Exposes unsupported premise and decision-changing evidence without adding a runtime gate or duplicating traceability | Recommended bounded, advisory-first pilot |
| P-C. Import the source collection's full proposal/HTML/auto-update workflow | Ready-made methods, but competing formats, update trust and owner-policy conflicts; no demonstrated task-specific benefit | Do not adopt wholesale; source is a method reference |

The choice between P-A/P-B is a human decision after evidence, not automatic policy promotion. P-B is worthwhile only if it improves consequential distinctions enough to justify review/maintenance cost. It does not demand demand-research for every bug, infrastructure task or already-agreed small feature.

### Bounded packages and dependencies

**E0 — reuse audit and expected answers (docs/fixture PR).** Depends on D0, current PRD/RFC/CHNG adapters and approved non-production/public or synthetic fixtures. Proposed roles: product decision-maker for intent/revisit rules, workflow maintainer for mapping, independent verifier for expected outcomes. No named person/date commitment. Map existing fields/receipts and mark supported, uncovered or unknown. Keep private company evidence out of generic fixtures. If equivalent coverage exists, add only links/expected outcomes and stop.

**E1 — one product-evidence example and adversarial pairs (same or next docs PR).** Depends on E0 and human-approved expected outcomes. Reuse the existing artifact; record only decision-relevant items, with stable local hypothesis IDs and source locators/dates:
- Distinguish observed fact/reported behavior, owner choice/constraint, agent inference with evidence, and unsupported assumption. An owner can choose a segment but cannot make “they will pay” established evidence by asserting it. Marketing establishes positioning, not independently proven capability or demand.
- Link one consequential hypothesis to the user job/outcome and relevant requirement/AC; identify a real substitute, manual workaround or doing nothing. Show why refutation would change scope/direction. Don't invent observations or require alternatives where no real trade-off exists.
- Record an intended observation, eligible context/task, actual behavior/source and pre-agreed reconsideration rule. No universal paid experiment, copied success target, sample-size threshold or user contact. Value evidence cannot waive privacy/security/safety constraints; implementation evidence cannot certify value.
- Append dated supporting/disconfirming observations under the same ID, preserve refuted/untested history and approved decision versions, and identify one current recommendation. Any changed commitment follows current human workflow; no automatic PRD rewrite, Linear transition or Monday notification.

**E2 — independent qualification/report (only then consider a minimal adapter PR).** Depends on E1, D1's fresh-context/shared-acceptance rules and existing P/V evidence contracts. Review the artifact using current review mechanisms, not a new judge. If a documented gap survives E0/E2 and a separate authorization is granted, propose the smallest adapter/prompt/validation change with its actual touched files derived by cloud inspection. Do not prescribe code paths from this documentation-only review or introduce a blocking signal without a separate human decision.

### Acceptance cases and objective evidence

Use pinned, resettable benign/adverse pairs with independently agreed labels and source manifests. Record supplied context, relevant actual reads where observable, hypothesis/status changes, expected/actual findings, missed violations, false blocks, unknowns and effort. No invented improvement percentage or arbitrary score threshold.

1. **Choice vs empirical assertion:** a chosen segment is labeled as a decision; the paired “segment pays” assertion without evidence remains untested. A reported user statement is not silently promoted to instrumented behavior or prevalence.
2. **Evidence scope:** a vendor claim, copied anecdote and several mirrors of that same anecdote do not become independent proof. A genuinely sourced observation remains usable without requiring payment to make every fact true.
3. **Green code / uncertain value:** all implementation ACs can pass while the main value hypothesis remains untested or weakened. Reviewer reports both independently, without declaring the product validated or modifying the code expectation to manufacture agreement.
4. **Consequential refutation:** a valid disconfirming observation is appended under the original ID. Current recommendation is revisited through the human decision path; historical evidence/accepted intent remain. A changed requirement invalidates affected evidence under existing rules; a new observation alone is not permission to mutate accepted policy.
5. **Source-method fidelity:** a proposal claims to follow an authoritative method but starts at a different stage or omits a consequential precondition. Reviewer compares the relevant primary method and actual workflow rather than merely finding a quote. A justified, clearly labeled adaptation is acceptable; do not force every author method as policy. A denied/unavailable source produces UNKNOWN, not invented method agreement.
6. **Optional visible journey:** where a user-facing artifact is material, a cold reader can map job → question → action from the artifact/approved context, with sample data labeled. A CLI/API example may be better than screens. A polished mock is not feasibility, demand or runtime proof; screenshot-only comprehension is an additional bounded lens, not a substitute for the judge's shared requirements.
7. **No-gain control:** an already-clear small change or infrastructure fix incurs no mandatory market-study/HTML/new-tracker ceremony. Unsupported fixtures/oracles or host isolation limitations are reported distinctly, not interpreted as product failure.

Evaluate P-A/P-B on the same pinned artifacts and fresh supported sessions. Accept an advisory refinement only if the independent report identifies the seeded consequential distinctions without erasing valid choices, creating blanket research requirements or mislabeling missing evidence as proven failure. Uncertain/no-gain results can retain P-A. Human owner approves scope and any adoption; no mandatory external research, automated outreach or live experiment follows.

### Stop, rollback and governance

Stop if fixtures need unauthorized private data/user contact, observation cannot be verified, source permissions are unclear or maintenance exceeds practical benefit. Revert the additive example/guidance/fixtures through reviewed diff if needed; retain prior records and disconfirming evidence. Return to the supported DEFINE path, not a weakened safety gate. No automatic accepted-spec rewrites, policy/skill promotion, production deployment or merge. Linear remains Triple's work/decision record and Monday its consolidated report; other adapters retain their own approved systems. EARS/PRD→RFC→CHNG/ADR, independent judge/shared acceptance and human merge remain unchanged.

### Pinned source and limits for this refinement

Pawel Huryn / The Product Compass, [product-engineering](https://github.com/phuryn/product-engineering/tree/061014ffe954b4dca1f108de614ce25e4607161e), MIT (copyright 2026 Pawel Huryn), observed 9 Nov 2026. Read the complete README, LICENSE.md, AGENTS.md, propose skill/reference/receipts, intended-vs-implemented, derive-tests, independent-review, release-gate, retro and rejected.md: 12 documentation files, six of the advertised 44 skills, plus full tree inventory. No source scripts/code executed or behavior audited; author receipts/results are anecdotes, not independent measurements.

- [propose](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/product/skills/propose/SKILL.md), [proposal reference](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/product/skills/propose/references/proposal.md), [receipts](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/product/skills/propose/receipts.md): typed claims, consequential hypotheses, jobs and method-alignment failure motivate these cases. Synthesis, not vendoring.
- [intended-vs-implemented](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/ai-shipping/skills/intended-vs-implemented/SKILL.md) and [derive-tests](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/ai-shipping/skills/derive-tests/SKILL.md): keep intent/enforcement/test evidence distinct; actual runtime mapping requires later authorized audit.
- [LICENSE.md](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/LICENSE.md) and [rejected.md](https://github.com/phuryn/product-engineering/blob/061014ffe954b4dca1f108de614ce25e4607161e/rejected.md): permissive license is not authority to install/update. Preserve Proposed ADR006's reviewed admission over source auto-update/latest preferences. Do not import HTML conversion/deletion, no-ticket preferences, vendor defaults, character-count review proof or the claim that a pre-fix-passing regression test necessarily disproves a bug.

## Decisions needed (human)

Resolved on 2026-11-10. See [Decisions (2026-11-10)](#decisions-2026-11-10).
