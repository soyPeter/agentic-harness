# ADR-005: Signed verdict attestations in CI

## Status
Proposed

## Date
2026-11-07

## Context
The harness already proves things about a change, inside the repository:

- The verdicts in `backbone/.verdicts/` are tied to fingerprints: the griller's to the spec and its ADRs, the
  judge's and each review lens's to the code tree.
- `harness-verify` re-checks every pull request with the **base branch's** verifier (`verify --range`), so a pull
  request can't weaken the check that gates it.
- `harness.py receipt <id>` states what was verified about a task and what wasn't.

It can't hand that proof to anyone outside the repository host. The outcome of `harness-verify` is a check status on
GitHub. An auditor, a deploy gate or a customer's quality system that wants to know "commit X passed the harness's
gates, with these verdicts" has to trust GitHub's record or re-run the verifier on a full clone. The verdict files
are in git but unsigned: anyone who can push can write one.

The research in [2026-11-agent-sdlc-landscape.md](../research/2026-11-agent-sdlc-landscape.md) (recommendation 3,
and candidate 5 of its next steps, which calls it ADR-004) proposes signing the verdicts in CI instead of buying a
compliance platform: an in-toto Statement about the commit with a custom verdict predicate, signed with cosign in
`harness-verify`, with self-managed keys or a KMS preferred to keyless signing, and no fabricated SLSA levels.

Checked on 2026-11-07:

- **in-toto Statement v1** (`"_type": "https://in-toto.io/Statement/v1"`): `subject` lists the artifacts the
  statement is about, each identified by digest; `predicateType` is a URI that names the predicate's schema. The
  digest set has `gitCommit` and `gitTree` (lowercase hex git object ids), and a `gitTree` may name a tree git never
  stored.
- **SLSA v1.2**: its Verification Summary Attestation (`https://slsa.dev/verification_summary/v1`) reports
  `verifiedLevels`, which are SLSA levels. A harness verdict is not a SLSA level, and the VSA spec says itself that
  a VSA doesn't protect against a compromised verifier.
- **cosign v3.1.4** (2026-10-20), run locally with the release binary:
  - `cosign attest-blob --statement <file>` signs a ready-made Statement as a DSSE envelope and writes a Sigstore
    bundle (`--bundle`). It checks only that the file parses as a Statement.
  - With a key and a signing config that names no services (`cosign signing-config create` with no flags), it
    contacts no transparency log and no timestamp authority. `--tlog-upload=false` is refused with the default
    signing config, which cosign fetches from Sigstore's TUF repository.
  - `cosign verify-blob-attestation --key <public key> --bundle <bundle> --type <predicateType> --digest <commit>
    --digestAlg gitCommit --insecure-ignore-tlog` checks the signature, the predicate type and that a subject
    carries that commit. A wrong commit, type or key, or an edited statement, fails.
- **Keyless signing** (Fulcio and Rekor) writes the signer's identity into a public transparency log that can't be
  edited: for a GitHub Actions run, the repository, workflow and ref; for a person, their email address.
- **GitHub Actions secrets** reach `pull_request` runs from branches of the same repository, not from forks, and
  such a run uses the workflow file as the pull request has it.

## Decision
After `verify --range` passes, `harness-verify` writes an in-toto Statement about the pull request's head commit with
the base branch's engine. When the project has configured a signing key, it signs the statement with cosign and keeps
both as a workflow artifact.

### The statement
`harness.py attest --range <base>..<tip> [--allow-user-changes]` writes the unsigned Statement to stdout.

- It runs the checks of `verify --range`, with the same flags, and writes nothing when they fail (exit 1, the
  problems on stderr). A statement can only exist for a range that verifies, whoever runs the command.
- It refuses unless the checkout is at `<tip>` with a clean working tree: the receipt facts it carries are read from
  the checkout, and the statement is about the commit.
- It is deterministic. The output depends only on the commits, the files they hold, the harness settings
  (`harness.conf` and the environment) and the bytes of the engine that runs. No clock, host name, path or run id
  goes in; keys are sorted and the indentation is fixed. The same inputs give the same bytes, so anyone with the same
  engine can re-create the statement and compare. When it was signed is the signature's business, not the
  statement's.

| Field | Value |
|---|---|
| `subject` | `{"name": "commit", "digest": {"gitCommit": <tip>}}` and `{"name": "code", "digest": {"gitTree": <tip's tree without backbone/>}}`. The second is the code fingerprint the judge and the reviewers pass, so it also matches the same code on another commit. |
| `predicateType` | `https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1` |
| `predicate.verifier` | `id` (this repository's URL), `engineSha256` (the `harness.py` that ran), `baseLock` (the mode, version and, in thin mode, commit that the base commit's `backbone/.harness-lock.json` names; null without one) |
| `predicate.verification` | the `base` and `tip` commits, `result: "PASSED"`, `allowUserChanges` (in CI, the `harness-change-approved` label) and the gate settings verify read: `spec`, `judge`, `review`, `tester` |
| `predicate.tasks` | one entry per task finished in the range, sorted by id |

Each task entry carries the task's verdict chain:

- `finishedIn`: the first commit in the range that marks the task `[x]`;
- `spec`: its path, its fingerprint (the one the griller's pass names when the chain holds) and its Approval lines;
- `changeClass`: the class `approve` and `risk` use, whether the spec declares one, and why a declaration is invalid;
- `grill`, `judge` and `reviews` (one per lens): the latest verdict with its fingerprint, when it was recorded and
  how many rounds there were; for the judge also the test run the harness did (command, exit code, output hash);
- `risk`: the reasons and the suggested labels that `receipt` gives;
- `receipt`: the `verified`, `notVerified` and `approvalNeeded` lists of `harness.py receipt`, or null where it
  would refuse (no spec, or no judge pass on the code the task was finished with). The judge pass is matched against
  the commit that finished the task, so an earlier task of a range keeps its receipt when a later one changes code.

A judge fingerprint that differs from the `code` subject means a later commit in the range changed the code after the
task was finished. The statement shows it rather than hiding it; a consumer's policy decides what it accepts.

No SLSA level is claimed anywhere, and this is neither a SLSA provenance nor a VSA. The `v0.1` in the type says the
schema may still change; a breaking change gets a new type.

### Keys
In order of preference:

1. **A self-managed key (v1).** A cosign key pair: the encrypted private key and its password are repository
   secrets, `HARNESS_ATTEST_KEY` and `HARNESS_ATTEST_PASSWORD`. The project publishes the public key, for example
   on its default branch and in its documentation; a verifier takes it from there, never from the change it checks.
   Signing uses a signing config without services, so nothing leaves the runner and nothing becomes public.
2. **A cloud KMS key (follow-up).** `--key gcpkms://…`, `awskms://…`, `azurekms://…` or `hashivault://…`, with the
   workflow authenticating through OIDC federation. The key can't be copied out of the KMS, which logs every use.
   Preferred for regulated profiles such as `triple`.
3. **Keyless (explicit opt-in, follow-up).** A Fulcio certificate for the workflow's OIDC identity and an entry in
   the public Rekor log. Only for a project that accepts publishing its repository and workflow identity for good;
   never the default.

### How a verifier checks it
```sh
cosign verify-blob-attestation --key harness-attest.pub --bundle harness-verdicts.sigstore.json \
  --type https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1 \
  --digest "$(git rev-parse <commit>)" --digestAlg gitCommit --insecure-ignore-tlog
```

`--insecure-ignore-tlog` is needed because a key-signed bundle has no log entry, by design. Then the verifier's own
policy reads the predicate (it is in the bundle, and next to it as plain JSON): for example, every task's judge pass
on the attested code, `allowUserChanges` only where a person approved the harness change, and the gates on. To check
the verifier's output as well as its signature, run the same engine's `attest` on the same commits and compare bytes.

### Where it is stored
- **v1: a workflow artifact**, `harness-attestation`, on the pull request's run, holding the statement and the
  bundle. It needs no extra permission and expires with the repository's artifact retention (90 days by default):
  evidence for the review and the merge.
- **A release asset (follow-up):** when a release is cut, the bundle of the release commit is attached to it and
  lives as long as the release.
- **An OCI registry (follow-up, optional):** for organisations that keep their evidence in a registry.
- Not in git: a commit from CI would need write access and would change the tree it attests.

### Failure behaviour
- `verify` alone decides whether the check passes. The attestation steps come after it and run only when it passed;
  none of them can turn a failing verify into a pass (no `continue-on-error`, no `always()`).
- `attest` runs the checks again itself, so a statement for a failing range can't be written, not even by hand.
- With the key configured, a failure to write, sign or upload fails the job: a project that asked for attestations
  gets no silent gaps. Rerun once the cause (key, password, download) is fixed.
- Without the key, and on a pull request from a fork (no secrets), the steps don't run and nothing changes.

### What a signature proves, and what it doesn't
- In v1 it proves that a holder of the key signed the statement. A repository secret reaches every workflow run that
  gets secrets, including a run of a same-repository pull request that edits the workflow. That edit shows in the
  pull request and fails `verify` without the `harness-change-approved` label, but the edited run could skip
  `verify` and sign anyway. So a v1 signature means "a harness-verify run in this repository signed this", not "the
  base branch's workflow did".
- Signing on the default branch after the merge closes that gap, with the key in an environment restricted to that
  branch or a KMS key whose OIDC trust condition names that branch's workflow. It is the first follow-up.
- Like a VSA, a signature doesn't protect against a compromised verifier (the base branch's engine) or runner.

### This change (v1)
- `harness.py attest --range <base>..<tip> [--allow-user-changes]`, standard library only.
- `harness-verify.yml`: when `HARNESS_ATTEST_KEY` is set, write the statement with the base branch's engine, sign
  it with a pinned cosign release (its SHA-256 checked) and an empty signing config, and upload the statement and
  the bundle as `harness-attestation`.
- Tests of the statement's content and determinism through `harness.py attest` and the workflow's statement step,
  in throwaway repositories, without cosign.

## Alternatives considered
- **SLSA VSA as the predicate**: `verifiedLevels` would have to carry made-up levels. The useful ideas of a VSA
  (the verifier's identity, the result, the inputs) are fields of the custom predicate instead.
- **`cosign sign-blob` on the statement**: a bare signature over bytes, not the DSSE envelope that in-toto tools and
  `verify-blob-attestation` read.
- **`cosign attest-blob --predicate` with a file as subject**: cosign would make the subject a file's SHA-256, not
  the commit.
- **GitHub artifact attestations (`actions/attest`)**: keyless only, on the public Rekor log for public
  repositories, so they are a form of the keyless option rather than the default.
- **Keyless by default**: the easiest to set up, but it publishes identities for good; for the `triple` pilot that is
  a new data flow to review.
- **Signing in a separate job**: signing would get its own check status, at the cost of handing the statement from
  job to job. Possible later.
- **No attestation**: the check status stays the only record, and nobody outside GitHub can check it.

## Consequences
- **Easier**:
  - Anyone with the public key can check, offline and later, that a commit passed `harness-verify` and with which
    verdicts.
  - A deploy gate or a customer's quality system can require it, and the harness depends on no compliance platform.
  - The engine stays standard-library Python; cosign runs only in CI.
- **Harder**:
  - The project manages a key: rotating it, publishing the public key, and revoking by policy (a signature made with
    an old key stays valid until verifiers stop trusting that key).
  - CI downloads cosign, and a failed download or signature fails the job of a project that configured a key.
- **Unchanged**:
  - What `verify` checks and how it gates.
  - Projects without the key.
- **Follow-up work**, each as its own change:
  1. Signing on the default branch after the merge, with a key scoped to it (environment or KMS).
  2. KMS key references.
  3. Keyless signing as an explicit opt-in.
  4. Durable storage: release assets, then OCI.
  5. A helper that runs the cosign check and a predicate policy.
  6. Predicate `v1` once the schema settles.
