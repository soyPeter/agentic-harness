# ADR-005: Signed verdict attestations in CI

## Status
Proposed

## Date
2026-11-07, revised 2026-11-08 (signing moved to the default branch's push; see "Revision")

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
CI, with self-managed keys or a KMS preferred to keyless signing, and no fabricated SLSA levels.

Checked on 2026-11-07, revised on 2026-11-08:

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
- **GitHub Actions secrets** reach a `pull_request` run of a branch in the same repository, and that run uses the
  workflow file as the pull request has it. Forks get no secrets by default, but a repository setting can send them
  to fork pull requests (for private repositories), so a `pull_request` run is not a secrets boundary.
- **GitHub environments**: a job that names an environment gets that environment's secrets only when the
  environment's deployment-branch rule admits the run's ref. A name that doesn't exist yet is created on first use
  with no rule, so the rule has to be set before the secret is added.

## Decision
When a change lands on the default branch, the `attest` job of `harness-verify.yml` runs. It verifies the pushed
range, writes an in-toto Statement about the pushed commit with the engine the push starts from (the default branch's
previous tip), and, when the project has configured a signing key, signs the statement with cosign inside the protected
environment `harness-attest` and keeps both as a workflow artifact. Pull requests get the verify check only: no secrets, no signing, nothing for a pull
request to edit into a signature.

### Where and when the statement is made
- **The pushed range** is `github.event.before..github.sha`. The statement is about the commit on the default branch.
  For a squash or rebase merge that is not the pull request's head, and the head is not attested at all.
- **The engine is the one the push starts from.** The job takes the verifier from `github.event.before`, the previous
  tip of the default branch, with the steps the pull request check uses for its base: a pinned engine in thin mode,
  else the `scripts/harness/` of that commit. The engine at the pushed tip, which the push may have changed, never
  checks its own change. The statement's check is `verify --range` with the same flags, and for a range without
  `--allow-user-changes` it refuses any change in the range to the engine (`scripts/harness/`), to the workflows
  (`.github/workflows/harness-*`), to the lock, to the tool contracts and to user-only settings. So the statement is
  written by the verifier that was in force before the push, and a push that changes the harness gets no statement.
- **No label in CI.** The job never passes `--allow-user-changes`. A push that changes the harness, even one a
  maintainer approved with `harness-change-approved`, gets no statement: the job fails and says why. Reading the
  merged pull request's label to allow that case is a follow-up.
- **A first or forced push gets no statement.** The `Check the pushed range` step refuses an all-zero
  `github.event.before` (a first push) and a previous tip that isn't an ancestor of the pushed commit (a forced push),
  before any engine is taken.
- **The environment is checked before anything is written or signed.** The `Check the harness-attest environment` step
  refuses unless the environment admits only the default branch (see Keys).

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
| `predicate.verification` | the `base` and `tip` commits, `result: "PASSED"`, `allowUserChanges`, and `settings`: every setting the engine resolves through `conf()` (the defaults and `backbone/harness.conf`, overridden by the environment), each as `{"value", "environment"}`, where `environment` is true when the environment set it |
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
schema may still change. v0.1 has not shipped in a release, so its shape changes in place; once a release carries it,
a breaking change gets a new type.

### Keys
In order of preference:

1. **A self-managed key (v1).** A cosign key pair: the encrypted private key and its password are secrets of the
   `harness-attest` environment, `HARNESS_ATTEST_KEY` and `HARNESS_ATTEST_PASSWORD`. The project publishes the public
   key, for example on its default branch and in its documentation; a verifier takes it from there, never from the
   change it checks. Signing uses a signing config without services, so nothing leaves the runner and nothing becomes
   public.

   `harness.py ci-protect --attest` sets the environment up. It refuses while repository-level secrets named
   `HARNESS_ATTEST_KEY` or `HARNESS_ATTEST_PASSWORD` exist, makes the default branch the environment's only deployment
   branch, reads the result back, and records the branch in the repository variable `HARNESS_ATTEST_BRANCH`. The
   attest job reads the environment with its own token when GitHub lets that token do so, and accepts it only if the
   rule is selected branches with exactly the default branch. When the token can't read it, the job accepts only the
   branch the variable records. Any other case refuses to sign. Whether a workflow token may read environments depends
   on GitHub's permissions, so the job takes both paths.

   **Repository secrets.** GitHub resolves a secret of a job in an environment from the environment first, and from
   the repository when the environment has none. The job can't stop the second lookup, so `ci-protect --attest` refuses
   while repository-level attestation secrets exist. Keep the two secrets in the environment only.
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
on the attested code, and the settings the policy depends on (`settings`). To check the verifier's output as well as its signature, run the
same engine's `attest` on the same commits and compare bytes.

### Where it is stored
- **v1: a workflow artifact**, `harness-attestation`, on the push's run, holding the statement and the bundle. It
  needs no extra permission and expires with the repository's artifact retention (90 days by default): evidence for
  the default branch's history, not for a pull request.
- **A release asset (follow-up):** when a release is cut, the bundle of the release commit is attached to it and
  lives as long as the release.
- **An OCI registry (follow-up, optional):** for organisations that keep their evidence in a registry.
- Not in git: a commit from CI would need write access and would change the tree it attests.

### Failure behaviour
- The pull request's `verify` is the only check that gates a merge. Nothing in the `attest` job runs on a pull request,
  and nothing in it can change the result of that check.
- `attest` runs the checks again itself, so a statement for a failing range can't be written, not even by hand. The
  job fails and the artifact is not written.
- A failed check of the environment, a first or forced push, or a range that changes the harness, fails the job before
  anything is written or signed.
- The push has already happened when the job runs, so a failure is an alarm, not a gate: a red run on the default
  branch that needs a fix and a rerun. A failure to write, sign or upload fails the job when the key is configured;
  a project that asked for attestations gets no silent gaps.
- Without the key the job does nothing: the checkout runs and every other step is skipped. Nothing is written and
  nothing fails.

### What a signature proves, and what it doesn't
- It proves that a holder of the key signed the statement's bytes. The bundle carries no run, workflow or time, so it
  does not say which run made the statement. The run is in GitHub's record of the push; a keyless signature (follow-up
  3) would carry its identity.
- The job signs only a statement of a range that changed no harness file (see "The engine is the one at the tip"),
  because it never passes `--allow-user-changes`. So the workflow that signed is the one the default branch had before
  the push. Anyone holding the key can sign a statement made by hand, so consumers check the content, not only the
  signature: running the same engine's `attest` on the same commits must give the same bytes.
- **Who can make one.** Anyone who can read `HARNESS_ATTEST_KEY` and its password, and any run that the
  `harness-attest` environment admits. The environment's deployment-branch rule (only the default branch) keeps
  pull requests out, and the repository's files can't set that rule. `ci-protect --attest` sets it and the attest job
  checks it, but a job that creates the environment on first use gets no rule, so a maintainer runs `ci-protect
  --attest` before the secrets are added. Consider required reviewers on the environment, so each signing waits for a
  person. A key holder can sign anything offline
  until the key is rotated and verifiers stop trusting it.
- **Settings are recorded as resolved.** A value placed in a setting, and in particular one placed in the environment
  (a URL with a token in it, for example), is in the statement and in the artifact. Credentials don't belong in
  harness settings.
- **`gitCommit` names the default branch's commit.** A deploy gate that means "this commit" checks `gitCommit` against
  the commit it deploys. `gitTree` says only that the code is the code that was judged; it matches any commit with the
  same code outside `backbone/`, such as a cherry-pick on another branch.
- **Timing.** The statement exists when the push's job has finished. A deploy gate that runs earlier has to wait for
  the artifact (or, later, the release asset).
- **Not covered.** A compromised engine, runner or GitHub account, and a merge a reviewer should have refused: the
  statement records what `verify` found, not whether the merge was wise. Changes approved with the label have no
  statement from CI in v1.
- **Pull requests.** A pull request's `verify` runs the workflow file as the pull request has it, so a pull request
  can edit its own check. That is the label's job (a maintainer approves such a change), and the attestation doesn't
  rely on it: the push's job runs the workflow the default branch has after the merge, and the range check above
  proves that the merge changed no harness file.

## Revision
The first draft signed the statement in the pull request's run with the repository's secrets. A pull request can
edit its workflow and read the key with a step that encodes it past log masking, so a signature from that run meant
"someone with write access signed this". The signing moved to the default branch's push, into a protected
environment, and the pull request's run lost its secrets and its signing steps. The statement's gate settings became
the full resolved `settings`, because verify's result depends on every setting it reads through `conf()`, not on four
of them, and a statement that names only some of them makes a claim it can't keep. The statement is about the commit
on the default branch, not the pull request's head.

Later in the same change: the engine moved from the pushed tip to the previous tip. The first version took the verifier
from the commit being attested, so a push that made `harness.py` pass everything would have been signed by the engine it
brought in. The environment's rule became a check in the job, since the job creates an environment with no rule on
first use, and `ci-protect --attest` sets it.

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
- **Signing in the pull request's run (the first draft)**: rejected, see "Revision".
- **Signing in a separate workflow file**: the same protection, but the push job and the pull request check then
  duplicate their verifier steps across files. One file keeps them together, and the enforcement rule already covers
  every `harness-*` workflow.
- **No attestation**: the check status stays the only record, and nobody outside GitHub can check it.

## Consequences
- **Easier**:
  - Anyone with the public key can check, offline and later, that a commit on the default branch passed
    `harness-verify`, and with which verdicts and settings.
  - A deploy gate or a customer's quality system can require it, and the harness depends on no compliance platform.
  - The engine stays standard-library Python; cosign runs only in CI, and only on a push to the default branch.
  - Pull requests carry no secrets and no signing, and signing can't turn a failing `verify` into a pass.
- **Harder**:
  - The statement exists only after the merge. A deploy gate waits for it, and a harness change approved with the label
    gets none in v1.
  - The project manages a key and an environment: setting the deployment-branch rule before the secrets, rotating the
    key, publishing the public key, and revoking by policy (a signature made with an old key stays valid until
    verifiers stop trusting that key).
  - The engine-taking steps are in both jobs of the workflow; a test keeps the two copies identical.
  - CI downloads cosign, and a failed download or signature fails the `attest` job of a project that configured a key.
- **Unchanged**:
  - What `verify` checks and how it gates.
  - Projects without the key.
- **Follow-up work**, each as its own change:
  1. Read the merged pull request's `harness-change-approved` label, so an approved harness change gets a statement.
  2. KMS key references.
  3. Keyless signing as an explicit opt-in.
  4. Durable storage: release assets, then OCI.
  5. A helper that runs the cosign check and a predicate policy.
  6. Predicate `v1` once the schema settles.
