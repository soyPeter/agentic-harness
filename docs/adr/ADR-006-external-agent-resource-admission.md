# ADR-006: Admit third-party agent setup resources explicitly

- **Status:** Proposed, not accepted or implemented.
- **Date:** 2026-11-08 (Europe/Madrid).
- **Repository:** `soyPeter/agentic-harness`.
- **Decision authority:** human repository/project maintainer, with independent security/workflow review; roles proposed, no named assignment.
- **Scope:** third-party SDK setup prompts, skills/plugins and their executable/reference dependencies. Not a replacement lifecycle, identity provider, package manager or knowledge store.
- **Related:** [ADR-002 Change-Class ladder](ADR-002-change-class-ladder.md), [ADR-007 evidence-driven closed loop](ADR-007-evidence-closed-loop.md), [qualification plan](../research/2026-11-design-challenge-agent-onboarding-plan.md).

## Context and evidence boundary

Agent-oriented SDK docs increasingly offer a copyable setup prompt that installs a skill and then guides integration. Official TypeSafe docs demonstrate that pattern. Google's EGM plugin demonstrates a multi-file package of skills, reviewers and standards, with runtime/version-dependent isolation limits. Both are useful references; neither is adopted here.

Current README already documents skill routing, user-owned tool contracts, safe hash-tracked updates and accepted-ADR pack adoption. Existing qualification work covers request/action provenance, reviewed lessons, verifier lifecycle and independent judge validity. This ADR **does not claim those controls are missing or ineffective**. It addresses a more specific architectural interface: what authority a remotely sourced agent setup resource has, and which release/version of its transitive content may become executable project guidance. External SDK onboarding isn't necessarily a built-in stack pack, nor the same thing as promoting a private KB lesson.

Documentation-only baseline, 8 Nov 2026: README SHA256 `6842e9f3c4eb684c2de889f4199a8093072185ae5f6516c3f1f6137629ad1f5a`; existing delegation qualification plan SHA256 `e56a4f96544bf1369b443dad1e0b2d598e4dfe318478f34ef875791f227f771b`. At the time of writing, filenames included 001, 002, two differently named 003 documents, 004 and 005. The evidence closed-loop draft has since been numbered [ADR-007](ADR-007-evidence-closed-loop.md), so this document stays ADR-006. The number is not an assertion that all prior decisions are accepted or implemented. Current code, effective hooks, installed adapters, remote branch state and release behavior have not been audited.

## Decision drivers

- Preserve the usefulness of agent-readable integration docs without granting a web page execution or permission authority.
- Keep setup reproducible and version-compatible; avoid automatic mutable remote instructions and duplicate stale skill copies.
- Reuse existing routing, tool permissions, package/ADR policy and receipts rather than build another marketplace/registry.
- Preserve human approval/merge and independent evaluation; make unavailable provenance or compatibility explicit.
- Keep stack/tool portability and a lightweight reference-only path for ordinary research.

## Options

| Option | Advantages | Tradeoffs and failure boundary |
| --- | --- | --- |
| A. References only; never admit external executable guidance | Smallest trust surface, ordinary docs remain available; project authors translate advice into existing local controls | Manual integration/updates; misses safe reusable setup procedures and can drift from the vendor |
| B. Reference-only default, explicit reviewed versioned bundle admission | Reproducible authority boundary, compatible setup, reviewable updates and revocation; uses existing skill routing and approval | Review and inventory cost; hashes aren't safety proofs; transitive dependencies and model interpretation remain risks |
| C. Fetch/install latest official setup prompt or plugin on demand | Lowest onboarding friction; current vendor docs immediately available | Remote update can change behavior, scripts, scopes or destinations; official provenance alone doesn't establish project authorization; difficult replay and rollback |

**Proposed decision: B**, with A always supported as the fallback. Reject C as the default. Do not require every external document to be vendored or admitted just to read it. Adoption is conditional on a scoped audit confirming useful uncovered requirements and human acceptance of the project-specific integration; this ADR alone authorizes no installation.

## Proposed semantics

### Separate observation, instruction and action

1. **Reference:** external docs, post, copied prompt and retrieved SKILL.md are source data. They can inform a proposal but cannot override project rules, approve themselves, enable tools, request credential extraction or grant writes/network access.
2. **Admitted guidance:** a human-reviewed resource/version may be made discoverable through existing project routing. Record the decision reference, intended purpose, compatible SDK/host versions, source/release/revision and digest, local destination and declared dependencies/data destinations. Use current manifests/receipts where possible; a logical contract does not require a new global database.
3. **Execution:** loading admitted instructions still doesn't authorize their scripts, package installation, network calls or irreversible actions. Existing tool/role permissions, sandbox boundaries, Change-Class/spec gates and user requirements continue to govern each action. Admission is not an access token or merge approval.

### Review the whole useful bundle

Review relevant adjacent scripts, referenced standards/templates/assets and package-manager behavior, not just a SKILL.md checksum. Bound recursive references by the approved purpose and dependency set. Remote follow-on instructions outside that set return to reference status, not automatic trusted expansion. Avoid copying private project data into upstream prompts or public artifacts. Record license obligations, expected side effects, non-production test data, cleanup ownership and whether setup is offline or uses an API/provider.

Pin immutable releases/revisions when available and record compatibility. Mutable-only docs may remain references; any approved snapshot must say what was actually reviewed and what cannot be reproduced. A domain/author label or digest identifies origin/bytes, **not correctness or safety**. Do not implement an ad-hoc secret store: actual credentials remain in existing approved tooling; manifests/receipts contain no secrets.

### Updates and revocation are changes

A changed resource/dependency/SDK/host or permission/data destination requires impact review and requalification of affected setup/evidence. New bytes do not silently inherit the old verdict or authority. Preserve valid user edits and one canonical installed copy; don't auto-replace local modifications or enable global install/auto-update. An update that is reference-only does not expand execution privileges.

Support disabling/removing the optional admitted integration through a reviewed change, preserving provenance and evidence. Security revocation blocks use even if the old digest remains available; rollback must **not** restore a known-vulnerable or policy-revoked bundle. If no safe compatible bundle exists, fall back to A and park execution.

### Relationship to current controls

Map these semantics onto current pack/skill routing and safe-update logic first. If existing controls already establish the boundary, adopt a docs/fixture clarification, not another runtime. Do not duplicate the existing verifier/judge contract or replace attestations with package hashes. A signed receipt can establish signed bytes, not that installation was authorized or that a workflow is secure.

## Qualification / acceptance

A separately authorized cloud task must map behavior before deciding implementation is necessary. Expected outcomes are agreed independently before evaluating a candidate:

- Valid reference-only SDK guidance can be read/proposed without installing a plugin or obtaining a secret.
- A hostile setup page instructing a policy rewrite, secret read, external send or production action confers no authority; missing admission/permission cannot become a pass through a different tool.
- An admitted bundle is linked to exact reviewed bytes and compatible versions, loads through existing discovery/routing, and completes its approved non-production example with observable result and owned cleanup.
- Changed transitive script, redirected reference, incompatible SDK, duplicate/stale install and modified local file produce explicit review/block/unknown outcomes; no silent update or invented success.
- Revoked/removed bundles cannot be reactivated through a “rollback”; an offline or denied resource produces typed unavailability and the supported reference-only fallback.
- Evidence states what was loaded, executed, not run, blocked and verified, bound to the actual revision/configuration. Requalification is required when affected inputs change. Independent JUDGE and human PR merge remain required.

No numeric quality gain, number of fixtures, retry count, owner commitment or new schedule is adopted. Compare reference-only vs admitted setup on representative approved fixtures, including correctness, unsafe attempts, replayability, human review and maintenance cost. Report no-gain/inconclusive outcomes honestly.

## Consequences and rollback

Benefits: useful SDK guidance stays accessible without implicit authority; admitted setup is reproducible, reviewable and explicit about effects. Costs: compatibility tracking, transitive review, revocation and fixture maintenance. Residual risks include compromised upstream/host/runner, incomplete dependency discovery and misleading model interpretation; this is not a general supply-chain security guarantee or compliance certification.

Roll back only optional admission/discovery helpers or guidance through review; keep permission controls and source/evidence history intact, return to reference-only A, and never restore a revoked resource to regain green tests. No production state or user secrets need change to evaluate this decision.

## Sources and limits

- [Gergely SDK onboarding post](https://x.com/GergelyOrosz/status/2119052500733161977), screenshot inspected; adoption prediction is opinion, not measurement.
- [Official TypeSafe agent skill](https://docs.typesafe.ai/agent-skill) and [README](https://github.com/typesafe-ai/skills/blob/main/README.md), fully read; installs/examples not executed and product not selected.
- [Google EGM README](https://github.com/google/elephant-goldfish-model/blob/main/README.md), [architecture](https://github.com/google/elephant-goldfish-model/blob/main/docs/designs/architecture.md), [testing record](https://github.com/google/elephant-goldfish-model/blob/main/TESTING.md), full docs read. Design-phase write boundary is documented as unenforced convention; runtime and isolation support have explicit limits. No plug-in adopted or primary test repeated.
- [Thoughtworks instruction bloat](https://www.thoughtworks.com/radar/techniques/agent-instruction-bloat) and [harness evaluation](https://www.thoughtworks.com/radar/techniques/harness-quality-evaluation), November Radar guidance, not our empirical results or accepted controls.

This is a Proposed architectural boundary, not evidence of an exploit in the current harness, a commissioned audit or permission to implement it.
