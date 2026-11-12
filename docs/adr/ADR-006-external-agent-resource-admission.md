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

## Implementation notes (2026-11-11)
The status stays Proposed: accepting this ADR is the user's decision. As the Decision asks, the semantics were first
mapped onto the existing controls (read-only, on `dd2f9e9`); only the gaps were built, in the engine
(`payload/owned/scripts/harness/lib/admission.py` and small hooks in `harness.py`), with tests in
`tests/test-admission.py`. `backbone/HOOKS.md`, "Third-party skills and setup resources", documents the behaviour.
An independent review of the first version found claims below that went further than the code (2026-11-12); the
table and lists now say what holds, and the fixes are in the same pull request.

**Audit: what already established the boundary**

| ADR semantic | Existing control | Finding |
|---|---|---|
| A reference confers no authority | `tools.conf`, user-only `harness.conf` keys, `Approved-by:` lines and ADR acceptance are the user's (hooks refuse agents, verify refuses commits); built-in tool contracts can't be reclassified; write tools' paths get the file gates; `curl … \| sh` and `HARNESS_*=` are refused | Holds for the file tools, shell redirections and mutating programs, and write tools. **Gap** (found in review, closed): a git command that rewrites a file from another revision, the index or a stash (`git checkout <sha> -- backbone/tools.conf`, `git restore`, `git stash`, `git reset`) changed the user's files outside the hooks. **Gap:** a SKILL.md that an agent writes into `.claude/skills/` and invokes with the Skill tool runs its `` !`…` `` placeholders and frontmatter `hooks` in Claude Code outside every PreToolUse, checked only against permission rules that the skill's own `allowed-tools` can grant |
| Admitted guidance through existing routing, with a decision | `adopt` needs an Accepted ADR naming the pack; pack files hashed in the lock; routes and guardrails in ADR-cited blocks | Holds for first-party packs (the pin is the revision, the lock the digest). **Gap:** a third-party skill can only be a project skill: no decision, revision or digest, routable as soon as its files exist |
| Plugin skills, skill overrides | `agentic-harness:<skill>` resolves to the pinned engine; another plugin's skill never satisfies a route; a project override is the copy that counts | Holds. Other plugins live outside the repository |
| Source revision and digest | The lock hashes harness and pack files; verify refuses drift of enforcement files only | **Gap** for third-party bundles; the lock is the wrong place (`update.sh` would treat them as the harness's) |
| Compatibility, dependencies, data destinations, license | Packs: `requires`, `applies-to`, `last-verified` | **Gap** for third-party bundles |
| Update is a change; keep edits; no auto-update | `update.sh` and `adopt` are three-way via the lock (edits kept, `.harness-new`) and touch only the payload, the catalog and adopted packs; nothing third-party is fetched; a pin move is one reviewed change | Holds. **Gap:** nothing records which third-party bytes were reviewed |
| Revocation; no rollback to a revoked bundle | `adopt --remove` through a reviewed change; nothing stops re-adding | **Gap** |
| Execution: loading guidance authorizes nothing | Loaded skills feed only the skill gate; contracts, shell checks, scopes, spec, judge and verify govern every call | Holds for tool calls (now proven by tests). Gaps: the load-time execution above, and `allowed-tools` skipping the permission prompt a `confirm` contract relies on in supervised mode |
| Offline or denied resource | The harness fetches nothing third-party | Not applicable: what isn't in the repository is reference |

**Built**

- `backbone/admissions.conf`, user-only like `tools.conf`. An `[admit <name>]` record gives the bundle's path, an
  Accepted ADR that names it, source, revision, digest, purpose, compatible versions, dependencies, data destinations
  and license; every field is required. `[revoke sha256:…]` gives a reason. Agents' edits are refused through the
  file tools, shell writes and write tools, and so are git commands that would rewrite it or another user-only file
  (`tools.conf`, `harness.conf`, the lock, `escalations.md`): checkout, switch, restore, reset, stash, read-tree,
  checkout-index and clean when the file would differ from its working, staged or committed copy; cherry-pick,
  revert and stash pop when their commits touch it; apply and am when the patch names it or can't be read. verify
  refuses a commit that changes what the file decides (a pull request needs the `harness-change-approved` label).
  Revocations are read from the working copy, the index, HEAD, the default branch and every commit the reflogs
  record together, so rolling back the working copy, or rewriting the revocation out of local history (rebase,
  reset, amend, filter-branch), doesn't lift one; agents' `filter-branch`, `filter-repo`, `reflog expire`/`delete`
  and settings of `gc.reflogExpire*` are refused. A line the working, staged or committed copy has that the harness can't read blocks
  every project skill bundle (not the core skills) until the user fixes it.
- `harness.py admission digest <path>`: sha256 over the sorted lines `<sha256>  <path in the bundle>`, for the files
  git sees (tracked, or untracked and not ignored); a link counts as where it points, and a link out of the bundle
  makes it inadmissible. A revocation matches that digest or the digest of every file, ignored ones included. `harness.py admission` shows each record's
  state; doctor and the session-start note report the problems.
- A bundle is admitted while its record is complete, its ADR Accepted, its bytes match, no revocation names them, and
  no SKILL.md in it registers hooks, runs placeholders or pre-approves tools. Then its skills load and satisfy routes
  as any skill does. Otherwise it is reference: the Skill tool is refused, reading its SKILL.md doesn't count as
  loading it, edits routed to it are refused (parked for the user), and the shell checks refuse an agent's command
  that runs one of its files: by path, as a shell's, interpreter's or `source`'s operand or option value, on a
  shell's stdin (`sh < f`, `cat f | sh`), through runners (`timeout`, `nice`, `env`), in any letter case; and,
  while such a bundle is in the repository, a command whose code comes from an expansion, glob or substitution. A
  script that another program starts (a Makefile, a script outside the bundle, a test runner) still runs: the shell
  checks read command lines, not what programs do.
- Updates and revocation are changes: verify refuses committed bundle bytes that don't match their record, and, even
  with `--allow-user-changes`, revoked bytes coming back (as files, or files and record) and a removed revocation. A
  revocation also blocks the same bytes in another skill folder, in any `.claude/skills/` of the repository.
- An agent's Skill call is checked against every skill and command in the repository the name can reach, as Claude
  Code resolves it: the folder or file name, the frontmatter `name`, a nested `.claude/skills/` (any depth, any letter
  case) and the part after a namespace's colon; a frontmatter or name the harness can't read reaches every name. It is
  refused when any of them isn't admitted guidance, or registers hooks or runs placeholders as Claude Code 2.1.322
  finds them (a ```` ```! ```` anywhere in the text, `` !` `` after whitespace), admitted or not. Frontmatter keys may
  be quoted; a frontmatter the harness can't read (merge keys, explicit or escaped keys, flow style, repeated keys)
  counts as registering hooks.
- Tests show admission grants nothing: in autonomous mode, a tool without a contract, a `confirm` tool, a write tool
  into `backbone/`, `curl … | sh`, an edit of `tools.conf` and a `HARNESS_*=` assignment get the same refusals with
  the admitted skill loaded and without it.

**Not built, and why**

- Compatibility, dependency and data-destination checks: recorded, not checked. The harness can't read an SDK's or a
  host's version without per-stack probes (new infrastructure), and network access is already governed by the tool
  contracts and the sandbox allowlist (ADR-003).
- Admitting plugins (another plugin's skills, hooks and MCP servers): their bytes live in the CLI's plugin cache, not
  the repository, so verify and CI can't digest them without fetching and hashing plugin releases (new
  infrastructure). Enabling one is the user's settings change: agents can't edit `.claude/settings.json` under the
  role and orchestrator scopes, but verify doesn't treat its plugin entries as user-only.
- `allowed-tools` in a project skill that no record covers still skips the permission prompt that a `confirm`
  contract relies on in supervised mode. Closing it means answering `ask` from the hook on every `confirm` call, a
  change to supervised behaviour beyond this ADR.
- Revoked bytes copied outside `.claude/skills/`, with no record naming that path, are not found; scanning the whole
  tree on every check is out of proportion. A revocation names bytes: revoked files with a file added or changed
  have a new digest, and are an unreviewed project skill, which loads unless it runs commands as it loads.
- Skills outside the repository (the user's `~/.claude/skills`, plugins) aren't checked: their bytes aren't the
  project's. Folders of `.claude/skills/` that recent Claude Code versions adopt as plugins were not audited.
- `git merge`, `pull` and `rebase` may bring a policy file from another branch; they apply committed changes, which
  verify gates, and refusing them would stop agents updating a branch.
- A revocation committed only locally and rewritten out of the branch holds while a reflog records its commit. Git
  expires unreachable reflog entries after 30 days by default (`gc.reflogExpireUnreachable`), so a revocation that
  was never pushed can lapse that long after such a rewrite; push revocations, and CI's verify reads the default
  branch. Refusing every history rewrite would stop agents rebasing a branch.
- The adoption criteria's comparison of reference-only and admitted setup on representative approved fixtures needs
  a candidate SDK and approved fixtures, which this ADR leaves to a separately authorized task.
- Follow-on instructions a bundle points to outside itself stay reference by construction, but the harness can't see
  which instructions an agent follows; only the actions they lead to are gated.
