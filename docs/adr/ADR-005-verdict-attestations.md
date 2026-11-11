# ADR-005: Signed verdict attestations in CI

## Status
Accepted

## Date
2026-11-07, revised 2026-11-08 (signing moved to the default branch's push; see "Revision"); follow-ups 2026-11-11
(see "Follow-up status")

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
  written by the verifier that was in force before the push, and a push that changes the harness gets no statement
  unless a labelled pull request made it (see "The merged pull request's label").
- **The previous tip must hold a verifier.** It has a harness, or a thin pin that names the release `v<version>` and
  resolves to the pinned commit (the job fetches that tag and compares it). Otherwise the job refuses, and it never
  falls back to the checked-out copy. The pull request check keeps that fallback for a first install; the attest job
  has none. So a push that deletes the harness, followed by a push that restores a doctored harness, gets no statement:
  the second push's previous tip has no verifier.
- **The merged pull request's label (follow-up 1).** The job passes `--allow-user-changes` only when the pull request
  that made the push carries `harness-change-approved`, as its check did, and the push is that pull request's merge
  alone; the statement then names the pull request (`approval`). Any other push that changes the harness gets no
  statement: the job fails and says why. See "Follow-up status".
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
| `predicateType` | `https://github.com/soyPeter/agentic-harness/attestation/verdicts/v1` (follow-up 6; v0.1 is read, no longer written) |
| `predicate.verifier` | `id` (this repository's URL), `engineSha256` (the `harness.py` that ran), `baseLock` (the mode, version and, in thin mode, commit that the base commit's `backbone/.harness-lock.json` names; null without one) |
| `predicate.verification` | the `base` and `tip` commits, `result: "PASSED"`, `allowUserChanges`, `approval` (v1: `null`, or `{"label": "harness-change-approved", "pullRequest": <number>}` when a merged pull request's label allowed the user changes), and `settings`: every setting the engine resolves through `conf()` (the defaults and `backbone/harness.conf`, overridden by the environment), each as `{"value", "environment"}`, where `environment` is true when the environment set it |
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

No SLSA level is claimed anywhere, and this is neither a SLSA provenance nor a VSA. The type is versioned (follow-up
6): v1 is the first a release carries, so its shape no longer changes in place. A field may be added to v1 when a
reader that ignores it loses nothing; removing, renaming or changing the meaning of a field gets a new type, and the
readers (`attest verify`, `attest policy`) keep accepting every type the engine wrote.

### Keys
In order of preference:

1. **A self-managed key (v1).** A cosign key pair. The public key is committed to the default branch as
   `harness-attest.pub`, the file the verifier example below reads. The encrypted private key and its password are
   secrets of the `harness-attest` environment, `HARNESS_ATTEST_KEY` and `HARNESS_ATTEST_PASSWORD`. Signing uses a
   signing config without services, so nothing leaves the runner and nothing becomes public.

   `harness.py ci-protect --attest` sets the environment up. It refuses while repository-level secrets or variables
   named `HARNESS_ATTEST_KEY` or `HARNESS_ATTEST_PASSWORD` exist, and names them; with `--delete-repo-copies` it
   deletes them first. It makes the default branch the environment's only deployment branch, reads the result back,
   and records the branch in the repository variable `HARNESS_ATTEST_BRANCH`. It then states the mode the job will run
   in, and whether `harness-attest.pub` is on the default branch. `harness.py doctor` states the mode too, and warns of
   repository-level copies.

   **The key is checked against the published public key.** Before anything is written or signed, the job derives the
   public key from the key it received and compares it with `harness-attest.pub` at the previous tip, the commit the
   verifier comes from. A key of any other value refuses, wherever it came from. GitHub resolves a job's secret from the
   environment first and from the repository when the environment has none, and a variable of the same name shadows the
   same way, so the job can't tell where a key came from, only whose key it is. The public key comes from the previous
   tip, never the pushed commit, so a push can't publish the key that signs it.

   **The public key is an enforcement file.** `harness-attest.pub` is the trust anchor of that check, so it is guarded
   like the harness's own files: a pull request that adds or changes it fails `verify --range` unless a maintainer
   adds the `harness-change-approved` label, agents may not write it (the implementer's scope, and the shell and code
   checks of the hooks refuse it), and a push that changes it is attested only as an approved harness change. The user
   publishes it as a harness change: through a pull request with the label, or with their own
   `HARNESS_VERIFY=off git push`, since the pre-push check refuses it otherwise. To rotate: publish the new public key
   that way (merged from a labelled pull request, that push is signed with the old key, which the previous tip still
   publishes; pushed by the user, it gets no statement), then replace the two secrets in the environment; the next push
   is signed with the new key.

   **Reading the rule.** The job checks that the environment admits only the default branch. It reads the rule live in
   its own step, with a fine-grained token in the environment secret `HARNESS_ATTEST_POLICY_TOKEN` that has read access
   to the repository's Actions, Secrets and Variables and nothing else. GitHub's REST reference for "Get an environment"
   names the Actions permission; the page checked was GitHub Enterprise Server's, so confirm it on github.com before
   relying on it. Secrets read lists secret names, never their values. Only that step sees the token. When the rule can't be read, the job refuses, unless a maintainer opted in with
   `harness.py ci-protect --attest --recorded-fallback` (the repository variable `HARNESS_ATTEST_RECORDED_FALLBACK` is
   `true`). The opt-in accepts the branch `HARNESS_ATTEST_BRANCH` records and does not re-read the rule, so a later
   removal of the rule goes unnoticed; that is the price of the opt-in. The job logs the mode it runs in, `live` or
   `recorded branch`, and `ci-protect --attest` states the mode in force.

   **Repository secrets.** A repository-level copy of the key is used where the environment has none, so removing
   the environment's secret would not stop the signing, and every workflow of the repository can read the copy. In
   the same step and with the same token, the job lists the repository's secrets and variables (names only) and refuses
   to sign while one named `HARNESS_ATTEST_KEY` or `HARNESS_ATTEST_PASSWORD` exists; a variable of that name would hold
   the key in plain text. It refuses when either list can't be read or is incomplete (more than 100 entries), unless
   the maintainer opted into the recorded branch, and logs which: `repository copies: checked` or `not checked (opted
   in)`. Without the token the opt-in is the only way to sign, and then a copy goes unnoticed: the key check still
   refuses any key other than the published one. Keep the two secrets in the environment only.
2. **A cloud KMS key (follow-up 2).** `--key gcpkms://…`, `awskms://…`, `azurekms://…` or `hashivault://…`, with the
   workflow authenticating through OIDC federation. The key can't be copied out of the KMS, which logs every use.
   Preferred for regulated profiles such as `triple`. Configured in `backbone/harness.conf` (user-only settings):
   `HARNESS_ATTEST_SIGNING="kms"`, `HARNESS_ATTEST_KMS_KEY` and `HARNESS_ATTEST_KMS_IDENTITY`. See "Follow-up status".
3. **Keyless (explicit opt-in, follow-up 3).** A Fulcio certificate for the workflow's OIDC identity and an entry in
   the public Rekor log. Only for a project that accepts publishing its repository and workflow identity for good;
   never the default: only `HARNESS_ATTEST_SIGNING="keyless"` turns it on.

### How a verifier checks it
`harness.py attest verify` (follow-up 5) runs both halves:

```sh
harness.py attest verify harness-verdicts.intoto.json harness-verdicts.sigstore.json --key harness-attest.pub \
  --commit "$(git rev-parse <commit>)"
```

It is the cosign call below plus a policy on the statement the bundle signs. By hand:

```sh
cosign verify-blob-attestation --key harness-attest.pub --bundle harness-verdicts.sigstore.json \
  --type https://github.com/soyPeter/agentic-harness/attestation/verdicts/v1 \
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
- A failed check of the environment or of the key, a first or forced push, a previous tip with no verifier, or a range
  that changes the harness, fails the job before anything is written or signed.
- The push has already happened when the job runs, so a failure is an alarm, not a gate: a red run on the default
  branch that needs a fix and a rerun. A failure to write, sign or upload fails the job when the key is configured;
  a project that asked for attestations gets no silent gaps.
- Without the key the job does nothing: the checkout runs and every other step is skipped. Nothing is written and
  nothing fails.

### What a signature proves, and what it doesn't
- It proves that a holder of the key signed the statement's bytes. The bundle carries no run, workflow or time, so it
  does not say which run made the statement. The run is in GitHub's record of the push; a keyless signature (follow-up
  3) carries its identity.
- The job signs only a statement of a range that changed no harness file (see "The engine is the one at the tip"),
  because it never passes `--allow-user-changes`. So the workflow that signed is the one the default branch had before
  the push. Anyone holding the key can sign a statement made by hand, so consumers check the content, not only the
  signature: running the same engine's `attest` on the same commits must give the same bytes.
- **Who can make one.** Anyone who can read `HARNESS_ATTEST_KEY` and its password, and any run that the
  `harness-attest` environment admits. The environment's deployment-branch rule (only the default branch) keeps
  pull requests out, and the repository's files can't set that rule. The job checks the rule, but a job that creates
  the environment on first use gets no rule, so a maintainer runs `ci-protect --attest` before the secrets are added.
  Consider required reviewers on the environment, so each signing waits for a person. A key holder can sign anything
  offline until the key is rotated and verifiers stop trusting it.
- **Settings are recorded as resolved.** A value placed in a setting, and in particular one placed in the environment
  (a URL with a token in it, for example), is in the statement and in the artifact. Credentials don't belong in
  harness settings.
- **`gitCommit` names the default branch's commit.** A deploy gate that means "this commit" checks `gitCommit` against
  the commit it deploys. `gitTree` says only that the code is the code that was judged; it matches any commit with the
  same code outside `backbone/`, such as a cherry-pick on another branch.
- **Timing.** The statement exists when the push's job has finished. A deploy gate that runs earlier has to wait for
  the artifact (or, later, the release asset).
- **Not covered.** A compromised engine, runner or GitHub account, and a merge a reviewer should have refused: the
  statement records what `verify` found, not whether the merge was wise. A change approved with the label is attested
  with `allowUserChanges: true` and the pull request that approved it; whether that approval was wise is the
  maintainer's call, which `attest verify` refuses unless the consumer passes `--accept-user-changes`.
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

Then an independent re-review found three gaps, closed in the same change:
- The attest job took the engine from the tip when the previous tip had no harness. That is the first-install fallback
  of the pull request check, and it let a push that restored a doctored harness sign its own verdict. The job now
  refuses instead, and a thin pin must name a release tag.
- A repository-level copy of the key, added after setup, was signed with. A marker variable can't tell the two apart
  (a repository variable of the same name is visible to the job too), so the job checks the key against the public key
  the previous tip publishes.
- The environment's rule was read with the job's `GITHUB_TOKEN`, and the fallback to the recorded branch was taken
  without a choice. The rule is now read with a token of its own, in one step; the recorded branch needs an explicit
  opt-in, and `ci-protect --attest` states the mode in force.

A further re-review found two more:
- `harness-attest.pub` was an ordinary file, so a pull request could replace the trust anchor of the key check without
  the approval label. It is now an enforcement file.
- A repository-level copy of the key, the same key, still signed after the environment's secret was removed, and every
  workflow could read it. The job now lists the repository's secrets and variables with the policy token and refuses
  while a copy exists; `ci-protect --attest --delete-repo-copies` deletes them, and `doctor` reports them and the mode.

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
  - The statement exists only after the merge, and a deploy gate waits for it. A harness change gets one only when a
    labelled pull request's merge made the push (follow-up 1).
  - The project manages a key and an environment: setting the deployment-branch rule before the secrets, rotating the
    key, publishing the public key, and revoking by policy (a signature made with an old key stays valid until
    verifiers stop trusting that key).
  - The engine-taking steps are in both jobs of the workflow; a test keeps the two copies identical.
  - CI downloads cosign, and a failed download or signature fails the `attest` job of a project that configured a key.
  - The job reads the environment's rule with a read-only token the project creates and rotates, or the maintainer
    opts into the recorded branch, which trusts the setup-time record. Either way the mode in force is stated.
  - The public key is a file on the default branch: it's committed before the first signing as a harness change (a
    pull request with the label, or the user's own push), and a rotation takes two pushes (publish the new key, then
    replace the secrets).
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

## Follow-up status
Recorded 2026-11-11. Follow-ups 1, 5 and 6 are done; 2 and 3 are configured and implemented in the workflow but not run
end to end; 4 is deferred. Everything below was built and tested locally only (no CI run, no push): with real git,
real cosign 3.1.4 where cosign is involved, and stand-ins for GitHub's API (a fake `gh`) and for its OIDC token
endpoint and a Vault login (a local HTTP server). No cloud KMS, Vault or Sigstore service was reached.

1. **Done: the merged pull request's label.** A new step, `Read the merged pull request's approval`, asks GitHub for
   the pull requests of the pushed commit (`GET repos/<r>/commits/<sha>/pulls`, with the job's token and
   `pull-requests: read`). The engine the push starts from judges the answer (`harness.py approval-check
   <pulls.json> <before>..<sha> <branch>`). It approves only when exactly one pull request is merged into the pushed
   branch with the pushed commit as its merge commit, carries `harness-change-approved`, and the push is that merge
   alone: one commit on the previous tip (a squash, or the rebase of one commit), or a merge commit of the previous
   tip and the pull request's head. Then the statement step passes `--allow-user-changes --pull-request <number>`, and
   the statement records `approval`. The engine is still the previous tip's.
   - Not approved, so a harness change in them still gets no statement: a rebase merge of several commits, a merge
     queue that lands several pull requests in one push, a direct push, and any failure to read GitHub (logged as a
     warning; a push without a harness change is attested as before).
   - The label is read when the job runs, not as it was at the merge: on a rerun, a label added after the merge counts
     and one removed is withdrawn. The pull request's own check needed the label to pass, so this matters only for a
     merge that bypassed the check.
   - Tested: `approval-check` on real commits of each shape, with property checks that other listed pull requests and
     their order change nothing; the step with a fake `gh`; an approved change to `harness.py` attested by the
     previous tip's engine. Not tested: GitHub's live answer (the fields used, `merged_at`, `merge_commit_sha`,
     `base.ref`, `head.sha` and `labels`, are those of GitHub's REST reference) and the token's permission.
2. **Implemented, not run end to end: KMS keys.** `HARNESS_ATTEST_SIGNING="kms"`, `HARNESS_ATTEST_KMS_KEY` (a
   `gcpkms://`, `awskms://` with the key's ARN, `azurekms://` or `hashivault://` reference) and
   `HARNESS_ATTEST_KMS_IDENTITY` (what the job logs in as: a GCP workload identity provider and optionally a service
   account; an AWS role ARN; an Azure tenant and client ID; a Vault address and JWT role), in `backbone/harness.conf`.
   They are user-only settings, so a range that changes them needs the label, and the job reads them at the commit
   the push starts from (`harness.py signing-check <before> <key set>`), so a push can't choose how it is signed.
   - Refusal rules: one signing source at a time (the key secret, a KMS key, or keyless), a KMS key reference and an
     identity of the same cloud, and settings that name another mode are refused.
   - The job gets `id-token: write`. `Sign in to the KMS` fetches the job's OIDC token for the cloud's audience and
     leaves it where that cloud's SDK reads it: a GCP external-account credential file, `AWS_ROLE_ARN` with
     `AWS_WEB_IDENTITY_TOKEN_FILE`, `AZURE_FEDERATED_TOKEN_FILE`, or a Vault token from Vault's JWT login. The key
     check derives the public key from the KMS and compares it with `harness-attest.pub`, as for the key secret.
     Signing uses the reference with the services-less signing config, after fetching a fresh token.
   - Bind the cloud's trust to the job's OIDC subject `repo:<owner>/<repo>:environment:harness-attest`, so only the
     protected environment's job can use the key.
   - Tested: the settings' decision table (property checks), the token request and each cloud's credential file or
     variables against the stand-ins, and the key check and signing with a key file standing in for the reference
     (cosign reads both through `--key`). Not tested: any cloud or Vault accepting the token, cosign's KMS clients
     reading those credentials, and the OIDC subject GitHub issues.
3. **Implemented, not run end to end: keyless signing.** Only `HARNESS_ATTEST_SIGNING="keyless"` at the commit the
   push starts from turns it on: never by default, never with the key secret or a KMS setting also present, and a
   misspelt value refuses. The signing step then runs `cosign attest-blob` without a key, on Sigstore's public
   services (a Fulcio certificate for the workflow's identity, a Rekor entry for good). The key and KMS branches keep
   the services-less signing config, so cosign can't fall back to keyless signing there (checked: with no key it
   finds no certificate authority and fails). `ci-protect --attest` states the signing mode, and for keyless that the
   identity goes to the public log. `attest verify` takes `--certificate-identity` and `--certificate-oidc-issuer`
   instead of `--key`. Tested: the opt-in rules, the refusals and the branches' commands. Not tested: a keyless
   signature or its verification, which need GitHub's OIDC token, Fulcio and Rekor.
4. **Deferred: durable storage.** Release assets need the workflow to find the push run's artifact and upload it on a
   release, with `contents: write`, a permission the harness-owned workflow doesn't hold today; OCI needs a registry.
   Both happen on GitHub or a registry, so they can't be exercised without network, and widening the workflow's
   permissions is the maintainer's decision. The workflow artifact (90 days) stays the store.
5. **Done: the verify helper.** `harness.py attest verify <statement> <bundle> --key <public key or KMS reference>
   <policy>` checks that the statement file is the statement the bundle signs, has cosign check the signature, the
   predicate type and the commit (or code) subject on a copy of the bundle, then applies the policy to the signed
   statement. `harness.py attest policy <statement> <policy>` applies the policy alone and says that no signature was
   checked. The policy: an in-toto Statement v1, a verdict predicate type (v0.1 or v1 unless `--type` narrows it), a
   subject for each `--commit` and `--tree`, `result: "PASSED"`, `HARNESS_SPEC_GATE`, `HARNESS_JUDGE_GATE` and
   `HARNESS_REVIEW` on (`--require NAME=VALUE` adds or changes one), and `allowUserChanges` false unless
   `--accept-user-changes`. Tested with cosign 3.1.4 on bundles the workflow's own signing step made: the right key,
   another key, another commit, an edited payload, a statement file that isn't the signed one, a v0.1 statement, and
   a property check that changing any field the policy reads refuses. Not tested: `--key` with a KMS reference and the
   keyless flags (see 2 and 3).
6. **Done: predicate v1.** `https://github.com/soyPeter/agentic-harness/attestation/verdicts/v1`: v0.1's fields, plus
   `verification.approval` (see "The statement"). v0.1 never shipped in a release, so `attest` writes only v1; the
   readers accept both, tested against a statement the v0.1 engine wrote (`tests/fixtures/attest/`). From v1 on, a
   breaking change gets a new type.
