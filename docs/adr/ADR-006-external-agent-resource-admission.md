# ADR-006: Admit third-party agent setup resources explicitly

## Status
Proposed

## Date
2026-11-08

## Context
Agent-oriented SDK docs increasingly offer a copyable setup prompt that installs a skill and then guides integration.
Official TypeSafe docs demonstrate that pattern. Google's EGM plugin demonstrates a multi-file package of skills,
reviewers and standards, with isolation limits that depend on the runtime and its version. Both are useful references;
neither is adopted here.

The README already documents skill routing, user-owned tool contracts, safe hash-tracked updates and accepted-ADR pack
adoption. Existing qualification work covers request and action provenance, reviewed lessons, verifier lifecycle and
independent judge validity. This ADR **does not claim those controls are missing or ineffective**. It addresses a more
specific architectural interface: what authority a remotely sourced agent setup resource has, and which release or
version of its transitive content may become executable project guidance. External SDK onboarding isn't necessarily a
built-in stack pack, nor the same thing as promoting a private KB lesson.

The scope is third-party SDK setup prompts, skills and plugins, and their executable and reference dependencies. This
ADR is not a replacement lifecycle, identity provider, package manager or knowledge store. It relates to
[ADR-002](ADR-002-change-class-ladder.md) (Change-Class ladder), [ADR-007](ADR-007-evidence-closed-loop.md)
(evidence-driven closed loop) and the
[qualification plan](../research/2026-11-design-challenge-agent-onboarding-plan.md).

The decision has to:

- Preserve the usefulness of agent-readable integration docs without granting a web page execution or permission
  authority.
- Keep setup reproducible and version-compatible; avoid automatic mutable remote instructions and duplicate stale skill
  copies.
- Reuse existing routing, tool permissions, package and ADR policy, and receipts rather than build another marketplace
  or registry.
- Preserve human approval and merge, and independent evaluation; make unavailable provenance or compatibility explicit.
- Keep stack and tool portability, and a lightweight reference-only path for ordinary research.

**Evidence boundary.** Documentation-only baseline, 8 Nov 2026 (Europe/Madrid): README SHA256
`6842e9f3c4eb684c2de889f4199a8093072185ae5f6516c3f1f6137629ad1f5a`; existing delegation qualification plan SHA256
`e56a4f96544bf1369b443dad1e0b2d598e4dfe318478f34ef875791f227f771b`. At the time of writing, filenames included 001, 002,
two differently named 003 documents, 004 and 005. The evidence closed-loop draft has since been numbered
[ADR-007](ADR-007-evidence-closed-loop.md), so this document stays ADR-006. The number is not an assertion that all
prior decisions are accepted or implemented. Current code, effective hooks, installed adapters, remote branch state and
release behavior have not been audited.

Sources, and how far each was read:

- [Gergely SDK onboarding post](https://x.com/GergelyOrosz/status/2119052500733161977), screenshot inspected; adoption
  prediction is opinion, not measurement.
- [Official TypeSafe agent skill](https://docs.typesafe.ai/agent-skill) and
  [README](https://github.com/typesafe-ai/skills/blob/main/README.md), fully read; installs and examples not executed,
  and product not selected.
- [Google EGM README](https://github.com/google/elephant-goldfish-model/blob/main/README.md),
  [architecture](https://github.com/google/elephant-goldfish-model/blob/main/docs/designs/architecture.md),
  [testing record](https://github.com/google/elephant-goldfish-model/blob/main/TESTING.md), full docs read. Design-phase
  write boundary is documented as unenforced convention; runtime and isolation support have explicit limits. No plug-in
  adopted or primary test repeated.
- [Thoughtworks instruction bloat](https://www.thoughtworks.com/radar/techniques/agent-instruction-bloat) and
  [harness evaluation](https://www.thoughtworks.com/radar/techniques/harness-quality-evaluation), November Radar
  guidance, not our empirical results or accepted controls.

Accepting this ADR is for the human repository or project maintainer, with an independent security and workflow review.
These roles are proposed; nobody is named. This is a Proposed architectural boundary, not evidence of an exploit in the
current harness, a commissioned audit or permission to implement it.

## Decision
Third-party agent setup resources are references by default, and a reviewed, versioned bundle becomes project guidance
only through explicit admission (option B). References only (option A) stays supported as the fallback. Fetching the
latest setup prompt or plugin on demand (option C) is rejected as the default. A and C are under "Alternatives
considered".

Do not require every external document to be vendored or admitted just to read it. Adoption is conditional on a scoped
audit confirming useful uncovered requirements and human acceptance of the project-specific integration; this ADR alone
authorizes no installation.

### Separate observation, instruction and action
1. **Reference:** external docs, post, copied prompt and retrieved SKILL.md are source data. They can inform a proposal
   but cannot override project rules, approve themselves, enable tools, request credential extraction or grant write or
   network access.
2. **Admitted guidance:** a human-reviewed version of a resource may be made discoverable through existing project
   routing. Record the decision reference, intended purpose, compatible SDK and host versions, source release or
   revision and digest, local destination, and declared dependencies and data destinations. Use current manifests and
   receipts where possible; a logical contract does not require a new global database.
3. **Execution:** loading admitted instructions still doesn't authorize their scripts, package installation, network
   calls or irreversible actions. Existing tool and role permissions, sandbox boundaries, Change-Class and spec gates,
   and user requirements continue to govern each action. Admission is not an access token or merge approval.

### Review the whole useful bundle
- Review relevant adjacent scripts, referenced standards, templates and assets, and package-manager behavior, not just a
  SKILL.md checksum.
- Bound recursive references by the approved purpose and dependency set. Remote follow-on instructions outside that set
  return to reference status, not automatic trusted expansion.
- Avoid copying private project data into upstream prompts or public artifacts.
- Record license obligations, expected side effects, non-production test data, cleanup ownership, and whether setup is
  offline or uses an API or a provider.
- Pin immutable releases or revisions when available and record compatibility. Mutable-only docs may remain references;
  any approved snapshot must say what was actually reviewed and what cannot be reproduced.
- A domain or author label identifies the origin, and a digest the bytes, **not correctness or safety**.
- Do not implement an ad-hoc secret store: actual credentials remain in existing approved tooling, and manifests and
  receipts contain no secrets.

### Updates and revocation are changes
- A changed resource, dependency, SDK, host, permission or data destination requires impact review and requalification
  of the affected setup and evidence. New bytes do not silently inherit the old verdict or authority.
- Preserve valid user edits and one canonical installed copy; don't auto-replace local modifications or enable global
  install or auto-update.
- An update that is reference-only does not expand execution privileges.
- Support disabling or removing the optional admitted integration through a reviewed change, preserving provenance and
  evidence.
- Security revocation blocks use even if the old digest remains available; rollback must **not** restore a
  known-vulnerable or policy-revoked bundle. If no safe compatible bundle exists, fall back to A and park execution.

### Relationship to current controls
Map these semantics onto current pack and skill routing and safe-update logic first. If existing controls already
establish the boundary, adopt a docs or fixture clarification, not another runtime. Do not duplicate the existing
verifier and judge contract, or replace attestations with package hashes. A signed receipt can establish signed bytes,
not that installation was authorized or that a workflow is secure.

### Adoption criteria
A separately authorized cloud task must map behavior before deciding implementation is necessary. Expected outcomes are
agreed independently before evaluating a candidate:

- Valid reference-only SDK guidance can be read and proposed without installing a plugin or obtaining a secret.
- A hostile setup page instructing a policy rewrite, secret read, external send or production action confers no
  authority; missing admission or permission cannot become a pass through a different tool.
- An admitted bundle is linked to exact reviewed bytes and compatible versions, loads through existing discovery and
  routing, and completes its approved non-production example with observable result and owned cleanup.
- Changed transitive script, redirected reference, incompatible SDK, duplicate or stale install, and modified local file
  produce explicit review, block or unknown outcomes; no silent update or invented success.
- Revoked or removed bundles cannot be reactivated through a "rollback"; an offline or denied resource produces typed
  unavailability and the supported reference-only fallback.
- Evidence states what was loaded, executed, not run, blocked and verified, bound to the actual revision and
  configuration. Requalification is required when affected inputs change. Independent JUDGE and human PR merge remain
  required.

No numeric quality gain, number of fixtures, retry count, owner commitment or new schedule is adopted. Compare
reference-only and admitted setup on representative approved fixtures, including correctness, unsafe attempts,
replayability, human review and maintenance cost. Report no-gain or inconclusive outcomes honestly.

## Alternatives considered
- **A. References only; never admit external executable guidance**: the smallest trust surface. Ordinary docs remain
  available, and project authors translate advice into existing local controls. But integration and updates are manual,
  it misses safe reusable setup procedures, and it can drift from the vendor. It stays supported as the fallback.
- **C. Fetch or install the latest official setup prompt or plugin on demand**: the lowest onboarding friction, with
  current vendor docs immediately available. But a remote update can change behavior, scripts, scopes or destinations;
  official provenance alone doesn't establish project authorization; and replay and rollback are difficult. Rejected as
  the default.

## Consequences
- **Easier**:
  - Useful SDK guidance stays accessible without implicit authority.
  - Admitted setup is reproducible, reviewable and explicit about its effects: a reproducible authority boundary,
    compatible setup, and reviewable updates and revocation.
  - Admission uses the existing skill routing and approval.
- **Harder**:
  - Review and inventory cost: compatibility tracking, transitive review, revocation and fixture maintenance.
  - Hashes aren't safety proofs, and transitive dependencies and model interpretation remain risks. Residual risks
    include a compromised upstream, host or runner, incomplete dependency discovery, and misleading model
    interpretation.
  - This is not a general supply-chain security guarantee or a compliance certification.
- **Unchanged**:
  - No production state or user secrets need to change to evaluate this decision.
- **Rollback**:
  - Roll back only the optional admission and discovery helpers or guidance, through review.
  - Keep permission controls and the source and evidence history intact, and return to reference-only A.
  - Never restore a revoked resource to regain green tests.
