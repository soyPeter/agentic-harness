# Changelog

## Unreleased

- **A spec change makes the evidence and approval given on the earlier text stale (ADR-007, Proposed; first slice).**
  Judge, review and tester records now carry the spec fingerprint (the grill's: the spec except its `Approved-by:` lines,
  and every ADR it references) next to the code fingerprint. A pass counts only on the code and the spec it judged, so
  any change to the spec but its `Approved-by:` lines (a criterion, a constraint, an assumption, the Change-Class, or
  only a reworded sentence) or to a referenced ADR sends the task back to the griller, the judge, the tester and every
  review lens even when the code is the same. Finishing a task (the hook, `finish`,
  pre-commit and CI `verify`) now passes the start gate again, as HOOKS.md already said verify did: a spec whose
  approval the user removed to change it needs a current grill pass and their approval again. Verify also refuses a
  commit that changes an approved spec while its `Approved-by:` lines stay as they were, since that approval was given
  on the earlier text (the user approves the new text with a new line; in CI the `harness-change-approved` label lets
  it through). A range is checked commit by commit, so an approval removed with the change and given again later with
  the same line is a renewal, and a change committed under the old approval passes once a later commit changes the
  `Approved-by:` lines. Verify can't tell who wrote an `Approved-by:` line: a commit that changes an approved spec
  and the date on its approval line together passes it, as before; the snapshot of protected files is the check on
  that. `next` routes a changed `[WIP]` task to `grill`, `approve`, `test` and `judge` with a `reason`; `state
  --json` gives the judge verdict's `stale` (`code`, `spec` or `unrecorded`); the receipt refuses a pass on an
  earlier spec and names the spec and code it was judged on (`judged_on`). Stale passes stay in the append-only
  history. Upgrade note: a judge, review or tester record from an earlier release has no spec fingerprint, so it
  counts as stale: run them again for tasks in progress. ADR-007's implementation notes hold the audit (P0) this
  slice came from, and what it leaves out.
- **Text under a spec's `## Approval` heading is part of the spec (ADR-007).** The grill fingerprint, the freeze on an
  approved spec, verify and the risk assessment left out the whole Approval section, but the gates read acceptance
  criteria from anywhere in the spec, and the template puts Approval last, so a criterion appended to a spec landed
  there: rewording it left the grill and judge passes current, an agent could change it after approval, and policy
  approval didn't see a risk term in it. Only the `Approved-by:` lines (and comments and blank lines in that section)
  are left out now. Upgrade note: a spec with other text under `## Approval` gets a new fingerprint, so its grill and
  judge passes go stale: grill and judge it again (its approval stays). A note that goes with an approval belongs in
  the `Approved-by:` line or in a comment.
- **The harness as the gate inside the agent software factory (ADR-008, Proposed; docs only).**
  `docs/adr/ADR-008-harness-inside-agent-factory.md` decides how the harness sits inside an always-on factory that
  takes work from Slack, GitHub and Linear. The factory owns the doors, the sender check, identity and keys, lanes,
  the watchdog, the janitor and the clock. The harness owns everything inside a lane (spec, gates, verdicts, receipts,
  delivery rules, memory) and stays the system of record for task state, running in thin mode at each project's pin.
  It names the contract between them (`next`, `state` and `receipt --json`, the events, `STOP`), maps the factory's
  roles and steps onto the harness's, and lists eleven follow-ups: a versioned contract surface, intake with
  provenance and the trusted-sender verdict, per-task and per-day spend caps, delivery from a trusted clone, model
  routing per role in `run`, a security lens that risk switches on, resuming on review comments, KB note drafts,
  janitor lifecycle signals, a no-merge profile for lanes and lane sandbox evidence. No code changes.

- **harness-verify's take step no longer fails at random on macOS.** It piped `git archive` into `tar -x`. bsdtar,
  macOS's tar, stops reading at the end-of-archive marker, so on a busy runner a `git archive` still writing the
  padding after it died of SIGPIPE: the step failed with "Cannot extract the base branch's verifier and required
  engine configuration" and nothing else, as the macOS self-test jobs did now and then since the test files run in
  parallel. The step now writes the archive to a file in `$RUNNER_TEMP` and unpacks that, and a failure names the
  command and its exit status (`git archive exited with 128`). GNU tar reads a pipe to its end, so Ubuntu runners
  were not affected. `HARNESS_STRESS=1` adds a stress check of the step to `tests/run-tests.sh`: on macOS it failed
  about 1 step in 100 before the change.
- **A macOS self-test job takes about 10 minutes instead of nearly 30, under its timeout.** `tests/run-tests.sh`
  runs the `tests/test-*.py` files alongside its shell sections, one per CPU at a time (`HARNESS_TEST_JOBS` sets
  how many), each with its own temporary folder, and reports them in a last section with each file's time; a test
  file it doesn't list fails the suite. The pull request jobs set `HYPOTHESIS_PROFILE=ci`: a property that starts a
  process per example runs a quarter of its examples, drawn anew on each run, and a failure prints the
  `@reproduce_failure` line that replays it. Local runs keep every example, and the new nightly workflow runs them all
  on the four platforms; it is not a pull request check. The `@example` cases and decision tables run in both. The
  escalation check waits for the next minute instead of 61 seconds, and the job timeout is 45 minutes.
- **The deliverer's gate reads more runtimes and package runners (ADR-002, follow-up).** Refused: `bun`, `deno`, `tsx` and `ts-node` code (`-e`, `eval`), `npx`, `bunx`, `pnpx` and package runners (`npm exec`, `pnpm dlx`, `yarn dlx`, `create`), `java --source`, `jshell`, `go run` from stdin or with `-exec`, `perl -M` with code, `node --eval=` and data: URLs, `pythonX.Y` and `nodejs` by version name, every Python module run (`python3 -m unittest code.interact` reads Python from stdin) and `pytest` (`-p` loads any module): the deliverer runs no tests. A script read from `/dev/stdin` or a `/dev/fd` path, `uvx`, `uv`, `pipx`, `poetry` and `swift` are refused too. `--version` and `--help` alone are allowed. `make`, `just`, `task` and `ninja` read no file from stdin or an expansion. A command that writes a file and then runs it, or runs `make` or `npm` after writing one, is refused; written files include `dd of=`, `curl -o` and `wget -O`, and are compared by name, whatever directory a run spells (`$PWD/s.py`). `$'...'` escapes are read as the characters they name. A commit message and a `--body-file -` heredoc are text. `git fetch origin main`, `git rebase origin/main` and `git pull --rebase origin main` are allowed on a feature branch; a pull or rebase on the default branch, a refspec that writes it, a rebase given a branch to check out (`git rebase feat/x main`, which fast-forwards `main`) and an interactive rebase in any spelling (`-i`, `-ki`, `--interactive`, `--edit-todo`, `git pull --rebase=interactive`, `--rebase=i`, `-ri`), which would wait for an editor, are refused, as is a push in a command that also runs `git checkout` or `switch`. The residual limits are in HOOKS.md.
- **The attest key's trust anchor is guarded, and repository copies of the key refuse (ADR-005, follow-up).**
  `harness-attest.pub`, the public key the `attest` job checks its key against, is now an enforcement file: a pull
  request that adds or changes it fails `verify --range` without the `harness-change-approved` label, a push that
  changes it gets no statement, and agents may not write it (the implementer's scope, shell writes and code writes are
  refused). The `attest` job's live step also lists the repository's secrets and variables with
  `HARNESS_ATTEST_POLICY_TOKEN` and refuses to sign while a repository-level `HARNESS_ATTEST_KEY` or
  `HARNESS_ATTEST_PASSWORD` exists, through the new `harness.py repository-check`; when the lists can't be read it
  refuses unless the recorded-branch opt-in is set, and logs which. `ci-protect --attest` names such secrets and
  variables, and `--delete-repo-copies` deletes them. `doctor` states the attest mode (live, recorded branch, none or
  unknown) and warns of repository copies.
  **Upgrading:** give `HARNESS_ATTEST_POLICY_TOKEN` read access to the repository's Secrets and Variables as well as
  its Actions, or the live job refuses to sign. Publishing or rotating the public key is now a harness change: a pull
  request with the label, or the user's own `HARNESS_VERIFY=off git push`.

- **The deliverer's gh and git calls are read as the shell runs them (ADR-002).** Its gh allowlist can't be reached
  by other means. Refused: a merge, close, review or auto-merge named in a command outside a PR's title and body, `--web`,
  and `gh pr comment`, which delivery doesn't use; programs that run code or commands from their arguments or stdin
  (`python3 -c`, `perl -e`, `node -e`, `awk`, `sed`, `osascript`, `fish`, `csh`, `tcsh`, a heredoc fed to an interpreter),
  `coproc`, `trap` and `hash`; copies and links (`ln`, `cp`, `mv`, `install`); a program run by a path outside the system
  directories, or a gh or git binary under another name. A variable that runs a command (`GH_BROWSER=`, `GIT_SSH_COMMAND=`,
  `PATH=`) set as a prefix or exported; `git -c`, `git config` writes, `--exec`, `--upload-pack` and `--receive-pack`.
  gh acts on this repository only: `-R`, URLs and `gh api --hostname` are refused when they name another one. A git ref
  command that names the default branch in any spelling (`git checkout main`, `git push origin HEAD:heads/main`), or uses
  an expansion, is refused, and so is `git push --all` and `--mirror`. Unquoted globs and braces are refused in gh and
  git calls and in command names; `ls tests/*.py`, `git rev-parse @{u}` and `gh api` placeholders are allowed.

- **Spec parsing reads Markdown the way it renders (ADR-002, follow-up).** The gates now share one reading of a spec's
  headings, code blocks, comments and sections. A fence closes only at a run of its own character at least as long, at
  0-3 spaces, so an indented closer no longer ends a block early and hides the requirements below it from the freeze.
  An `Approved-by:` line that a comment hides is read as `approved()` reads it, so an agent can't write one behind a
  comment. A fenced `## Skills` or `## Open questions` example no longer hides the spec's own section, and a comment
  opened in a code block no longer hides what follows. Headings and fences are read at column 0 only: one that is
  indented, follows a list or quote marker, or sits in an HTML block makes the spec invalid, as does a setext heading
  (text over `=` or `-`); write `## Title`. A section runs to the next `#` or `##` heading, and an approved spec is
  frozen outside its Approval section, whichever section follows it. Only `## Approval` at column 0 is the Approval
  section: `# Approval` and a setext heading are ordinary text, and an `Approved-by:` line under them doesn't approve.
  **Upgrading:** a spec with an indented heading or fence, a fence or heading in a list item, quote or HTML block, or a
  setext heading is invalid until it is rewritten. The user's approval under an indented `  ## Approval` no longer
  counts. A section that a fenced example or an HTML block used to hide is now read, so it may need fixing too.

- **HTML blocks follow CommonMark (follow-up to the Markdown reading).** A `<?`, `<!X` or `<![CDATA[` block now ends at
  its closing mark even after a blank line, so a `## Approval` hidden in one no longer passes as a section. `<pre>`,
  `<script>`, `<style>` and `<textarea>` blocks interrupt a paragraph. An autolink, or a tag followed by text, at the
  start of a line is text, so a heading below it no longer makes the spec invalid. A CR or CRLF line end is read as LF
  in the file and in the text a hook proposes, so a lone CR can't add an unfrozen section to an approved spec.
  **Upgrading:** a spec with a heading inside one of these blocks is invalid, and so is a tag alone on the line after a
  list or quote paragraph; rewrite them.

- **Spaces, blank lines and line breaks follow CommonMark (follow-up to the HTML blocks).** A tag's name ends at a space
  or a tab only, so a form feed, vertical tab or non-breaking space in a tag can't hide a heading below it in an HTML
  block: the spec is refused. A line of only a non-breaking space or another Unicode space is text, not a blank line: it
  keeps an HTML block open, and it is a paragraph ahead of a setext underline. A vertical tab, form feed, NEL, or a
  Unicode line or paragraph separator anywhere in a spec makes it invalid, and so does an unusual space or control
  character on a line with a `<`, `#`, backtick or tilde. **Upgrading:** a spec with a line break character anywhere, or
  an unusual space beside a tag, heading or fence, is invalid until the characters are removed or replaced with an ASCII
  space, tab or newline.

- **Thematic breaks and link reference definitions follow CommonMark (follow-up to the spaces and blank lines).** A
  `***` or `___` line after paragraph text is a thematic break, not more text, so a tag alone on the next line starts an
  HTML block and a `## Approval` under it is refused, not read as the Approval section. A tag alone after a paragraph that
  starts with `[`, which a reader may take for a link reference definition, is refused, and so is a setext underline in a
  list or quote. An unusual space in inline code is text again: only a line that starts with a fence marker counts as a
  fence for the unusual-space check. **Upgrading:** a spec with a heading in the HTML block that a tag alone after a `***` or
  `___` break starts, a tag alone after a `[`-led paragraph, or a setext heading in a list or quote is invalid until it
  is rewritten.

- **Comments and HTML blocks in lists and quotes follow CommonMark (follow-up to the thematic breaks).** `<!-->` and
  `<!--->` are whole, empty comments, as in CommonMark 0.31: they no longer hold a comment open to a later `-->`, where a
  tag after them could hide a `## Approval` that the gates still read. A second comment on a line no longer shifts the
  text the gates read. An HTML block or comment in a list item or quote ends with the item or quote. The gates don't
  track where those end, so they refuse what could be read either way: a `<pre>`, `<script>`, `<style>`, `<textarea>`,
  `<?`, `<!X` or CDATA block in a list item or quote or on an indented line, an indented tag that starts a block with no
  blank line after it, and a comment left open on a line that doesn't start at column 0. A lone `-` under quoted text is
  a setext underline, not an empty list item, and is refused; so is an underline under indented text, which may belong
  to a list item. **Upgrading:** move such
  blocks and multi-line comments to column 0; a spec that relies on them is invalid until they are.

- **Adopting a pack again keeps your edits.** `harness.py adopt` compared a pack file only with the release's copy, so
  a file edited after the last adoption was replaced by the release's copy with no backup, after a pin move or a
  `--to-thin`. An edited file is now kept. When the release changed it too, its copy goes to `<file>.harness-new` and
  `adopt` exits 1, as `update.sh` does. The lock then records the release's copy, as `update.sh` does, so once you have
  merged `<file>.harness-new` and deleted it, the next `adopt` is clean. An existing `<file>.harness-new` is never
  overwritten: `adopt` refuses before it writes anything and names the file (`update.sh` still overwrites one).
  `adopt --remove` lists a `<file>.harness-new` it leaves in place. Adopting again while a `<file>.harness-new` is still
  unmerged reports it as `pending` and exits 1, not 0. A file that a removed option leaves behind no longer has a hash,
  so `doctor` stops warning about it; its pack remembers it, so adding the option back treats it as an edited pack file
  (the release's copy goes to `<file>.harness-new`) instead of refusing the project file. A thin lock's hashes that an earlier engine recorded under `"files"`
  move to `"kept"` when a pack is adopted again, removed, or the pin moves (`harness.py adopt`, `adopt --remove`,
  `pin`), so `verify` no longer reads the project as a full install and refuses the next `.claude/settings.json`
  commit.

- **Attestation setup and the traceability history gap.** `harness.py ci-protect --attest` sets up the `harness-attest`
  environment (the default branch only, no repository-level attestation secrets) and checks it before it reports. It
  states the attest mode in force (a live read with `HARNESS_ATTEST_POLICY_TOKEN`, or the recorded-branch opt-in
  `--recorded-fallback`) and whether `harness-attest.pub` is committed on the default branch.
  `trace export` says `history incomplete` only when the judged commit isn't found and the history may hold it: a
  shallow clone that holds the commit has no gap, and trees git can't read (missing objects, as in a partial clone
  whose remote is gone) are reported, where they were silently skipped before.

- **Traceability export (ADR-004).** `harness.py trace export --format reqif|needs|html [--out DIR] [--task ID]`
  writes the chain requirement → acceptance criterion → test file → judge verdict → commit for every task with a spec,
  or one task: as ReqIF 1.2 (written with `xml.etree`), as a Sphinx-Needs `needs.json` in format 1, or as a
  self-contained HTML matrix to attach to a pull request. It is derived from `backbone/` and git and one-way: no
  network, no new dependency, and no gate reads it. Ids are the spec's own; each task says whether its latest judge
  pass is on the current code, lists every commit whose code is the judged code and the test files that mention each
  criterion in it, and lists the gaps (requirements without a criterion, criteria without a test file, undefined
  references, NFRs without an id, open findings). Under `HARNESS_REQ_STYLE=ears` each requirement carries its EARS
  pattern. `--out`, and stdout redirected into the repository, are refused unless git ignores the file. A shallow
  clone or a failed git read reports `history incomplete` instead of a missing commit. The export reads the committed
  `backbone/harness.conf`, not environment overrides, so the same repository state gives the same bytes on any
  machine. `docs/adr/ADR-004-traceability-export.md` records the decision, including what a regulated team can and
  can't claim from it (it isn't signed, validated or PCI DSS evidence). `tests/test-trace-export.py` checks the ReqIF
  output against a minimal subset of the OMG schema vendored in `tests/reqif_check.py`, offline, plus the
  `needs.json` shape and the HTML matrix, with property checks.

- **`state` and `next` hash the working tree once per command.** Each judged task used to hash the whole working
  tree again, about 0.6 s per hash on 5,000 files; now one command shares one hash across its tasks.

- **Signed verdict attestations (ADR-005, Proposed).** `docs/adr/ADR-005-verdict-attestations.md` decides how
  `harness-verify` turns its verdict into evidence others can check: an in-toto Statement, a custom predicate type
  (`https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1`, no SLSA level claimed), cosign with a
  self-managed key first, a KMS next and keyless only as an explicit opt-in. This release ships its first slice:
  - `harness.py attest --range <base>..<tip> [--allow-user-changes]` prints the unsigned Statement. Its subjects are
    the tip commit (`gitCommit`) and its code tree without `backbone/` (`gitTree`, the judge's fingerprint). The
    predicate names the engine (its SHA-256) and the release the base commit's lock pins, the range, the flag and every
    harness setting it resolved (its value, and whether the environment set it), and for each task finished in the
    range: the commit that finished it, the spec's fingerprint and approval lines, the Change-Class, the latest grill,
    judge and review verdicts, and the receipt's risks, suggested labels and verified / not-verified lists. It runs the checks of `verify --range` and prints nothing (exit 1,
    verify's problems on stderr) when they fail, and refuses a checkout that isn't the tip with a clean working tree.
    Standard library only; the same commits, settings and engine give the same bytes.
  - `harness-verify.yml`: the pull request check is unchanged and has no secrets. On a push to the default branch, the
    `attest` job writes the Statement for the pushed range with the engine the push starts from (the default branch's
    previous tip, so a push can't pass its own change), and, with the secret `HARNESS_ATTEST_KEY` (a cosign private
    key) and `HARNESS_ATTEST_PASSWORD` in the environment `harness-attest`, signs it with cosign 3.1.4 (checked against
    its SHA-256) and a signing config without services, so nothing goes to a transparency log, and uploads the Statement
    and its Sigstore bundle as the `harness-attestation` artifact. A thin pin must name a release tag, which the pull request check fetches too. The job refuses a first or forced push and a previous
    tip with no verifier (it never takes the engine from the tip), checks the key against `harness-attest.pub` on the
    previous tip, and refuses to sign unless the environment admits only the default branch: read live with the
    step-scoped secret `HARNESS_ATTEST_POLICY_TOKEN` (`harness.py environment-check` judges the rule), or, only after
    the maintainer opts in with `ci-protect --attest --recorded-fallback`, against the branch recorded in
    `HARNESS_ATTEST_BRANCH`. Without the key the job does nothing; with it, a failure fails the job, and no
    step can change the pull request's check. A harness change never gets a CI statement in v1. Run
    `harness.py ci-protect --attest` once, then add the secrets to the environment, once the base branch runs a release
    with `attest` (see the ADR).
  - `tests/test-attest.py` checks the Statement's content, refusals and bytes through the command and the workflow's
    statement step, in full and thin projects, with property checks; no cosign needed.

- **verify --range no longer fails a range whose later commit changes `backbone/`.** The code fingerprint of a
  commit kept the `backbone/` files that differ from both HEAD and the checkout, so a task marked done in one commit
  looked changed once a later commit in the range touched `backbone/` (another task's spec, a memory note), and CI
  failed the pull request.
- **Sandbox backends and sandbox evidence (ADR-003, Proposed).** `docs/adr/ADR-003-sandbox-backends.md` decides a
  sandbox backend interface for unattended runs (create, exec, copy in and out, egress policy, teardown, identity),
  with the local devcontainer as the default and the only backend the CI floor may use, and lists E2B, Freestyle and
  Coder as later candidates with the research's risks. This release ships its v1:
  - `harness.py run` starts each agent session through the backend `HARNESS_SANDBOX_BACKEND` names (new, user-only,
    default `devcontainer`). `devcontainer` runs it where the runner runs, as before. Any other value is a doctor
    error, so `run` and `orca` refuse to start; `verify` never reads it.
  - Each judge verdict records the sandbox it was recorded in, and `receipt` shows it (a SANDBOX section; `sandbox`
    in `--json`): `backend`, `isolation_class`, `base_image_digest`, `allowlist_hash`, `region`, `control_plane`,
    `credential_mode`, and `isolation_reason`. `isolation_class` is `container` only when the process is a Linux
    container with NoNewPrivs set, no NET_ADMIN, NET_RAW or SYS_ADMIN in its effective or bounding set, and the egress
    allowlist published at `/run/harness-egress/allowlist`; otherwise `none`, with the reason. A judge
    pass recorded before this release says "not recorded". The evidence never holds a credential, and refuses nothing.
    A receipt flags a container with no published allowlist, and notes that `allowlist_hash` covers host names only.
  - `.devcontainer/harness-agent/` builds from `node:22-bookworm` pinned by digest, and bakes the reference into
    the image (`HARNESS_SANDBOX_IMAGE`).
  - Inside the harness-agent image, an egress allowlist that isn't published at `/run/harness-egress/allowlist`
    (named by `HARNESS_EGRESS_ALLOWLIST`) is a doctor error, so `run` and `orca` refuse to start. `doctor` warns about
    a `devcontainer.json` that names no `dockerComposeFile` (read as JSONC, with comments and trailing commas), or that
    can't be parsed, and `update` warns when it keeps a conflicting local `devcontainer.json`.
  - The egress allowlist moved out of the agent's container: a second container (`egress`, `docker-compose.yml`)
    applies `init-firewall.sh` in the network namespace the agent's container joins, and publishes the host list the
    evidence hashes. The agent's container drops NET_ADMIN and NET_RAW, runs with `no-new-privileges` and has no
    sudo, so the agent can no longer re-run the firewall script as root. Outbound IPv6 is dropped. DNS is still open
    to any resolver.
  - `tests/test-sandbox-evidence.py` (in the self-test) and `tests/test-sandbox-egress.py` (real containers, with
    `HARNESS_E2E=1`: the Compose sandbox needs docker and the devcontainer CLI; the restriction checks need only docker).
  - **Upgrading:** the sandbox is now two containers. Move an edited `HARNESS_FIREWALL_ALLOW` or knowledge mount from
    `devcontainer.json` to `docker-compose.yml`, and rebuild the container; an image built before this release
    records `isolation_class: none`. If `update` reports a conflict on `devcontainer.json`, merge the new file's
    `dockerComposeFile` and `runServices` from the `.harness-new` file first: until you do, `doctor` warns, and the
    harness-agent image refuses to run `run` or `orca`.

- **Change-Class ladder (ADR-002).** Spec template and `requirements-writing` skill declare `Change-Class`
  (`docs` | `refactor` | `feature` | `schema`) plus optional `Parent-CHNG` / `Parent-RFC` / `Parent-ADR` links.
  Policy: PR merge stays human; policy `approve` must not be treated as merge. Runtime enforcement in
  `harness.py` is a follow-up.

- **Change-Class is enforced (ADR-002, follow-up a).** `harness.py` reads the spec's `Change-Class:` line. A spec
  without one counts as `feature`; any other value, or two different ones, makes the spec invalid (`spec-check`, the
  start gate, the griller's pass). `feature` and `schema` are never low-risk: `approve` escalates them to the user's
  `Approved-by:`, and a policy approval stops covering them when the task finishes. The light lane takes a `feature`
  task the user marks `(light)`, never a `schema` one. A `docs` task whose change touches anything but documentation
  (`HARNESS_DOC_PATHS`, new, user-only) is a risk, so a policy-approved one can't finish until it is escalated; a
  `refactor` that touches sensitive paths already was. The class is read outside comments and the Approval section,
  so it is part of what the griller and the user passed. `risk`, `next` and `state` (`change_class` in `--json`)
  and the receipt show it. The spec template says which ADR-002 it means. `tests/test-change-class.py` walks the
  class table through the public commands, with property checks. **Upgrading:** in autonomous mode, specs without
  `Change-Class:` now wait for the user's approval, and so does a task policy-approved before this release when it
  finishes; declare `docs` or `refactor` where policy approval should still apply.

- **Change-Class gaps closed (ADR-002).** A commented-out `## Approval` heading above `Change-Class:` ended the grill
  fingerprint, and the freeze on an approved spec, at the comment while the class below it was still read: a spec
  grilled as `feature` could become `refactor` and be approved by policy. The Approval section now starts at the first
  `## Approval` heading outside comments for the fingerprint, the freeze and what is read from the spec alike, and a
  spec with such a heading inside or next to a comment is invalid. A `Change-Class:` line in a fenced code block is an
  example, not the declaration. `HARNESS_DOC_PATHS` no longer counts code as documentation: a file needs a
  documentation extension (`md`, `mdx`, `markdown`, `rst`, `adoc`, `asciidoc`, `txt`) or a README-style name without
  one, so `src/docs/handler.py`, `docs/conf.py`, `README.py`, `CMakeLists.txt` and `docs/requirements.txt` are code.
  A moved file counts at both its old and its new path in the risk checks, the light lane and `verify`, which saw only
  where it went: moving code into `docs/`, a file out of a sensitive path, or `.claude/settings.json`, `harness.conf`
  or an enforcement file away is now seen. `tests/test-change-class.py` reproduces each gap through the public
  commands, with property checks. **Upgrading:** a `docs` task that touches images, stylesheets or other files without
  a documentation extension now waits for the user (add them to `HARNESS_DOC_PATHS` if your docs need them), and a
  move counts as two files against `HARNESS_RISK_MAX_FILES` and `HARNESS_LIGHT_MAX_FILES`.

- **An `## Approval` heading in a code block no longer ends the spec (ADR-002).** A fenced example showing a spec's
  `## Approval` heading ended the grill fingerprint, the freeze on an approved spec and what is read from the spec at
  the example: the risk checks missed every requirement below it, so policy could approve a `docs` spec that stores
  passwords in plain text, and everything below it could change after approval. `approved()` started the section at
  the example too, so an example with an `Approved-by:` line counted as the user's approval, and the user's own
  approval below it didn't count. The Approval section now starts at the first `## Approval` heading outside comments
  and fenced code blocks for the fingerprint, the freeze, `Change-Class`, the risk checks, `approve`, `approved` and
  the receipt alike; an `Approved-by:` line in a code block is an example; and a spec with such a heading inside a
  code block is invalid (indent the heading in an example). `tests/test-change-class.py` reproduces it through the
  public commands, with property checks that any edit below a fenced heading makes the grill pass stale or the spec
  invalid, and is refused as frozen or leaves the spec invalid. **Upgrading:** a spec with an `## Approval` heading
  in a code block fails `spec-check` until the example's heading is indented.

- **Suggested triage labels (ADR-002, follow-up b).** `harness.py receipt` suggests pull request labels for whoever
  triages the PR, in the text receipt and as `suggested_labels` in `--json`: `risk:low`, `risk:elevated` or
  `risk:high` from the spec's `Change-Class` and the receipt's other risks, plus `class:<class>` when the spec has a
  `Change-Class:` line. The class is the one `approve` and `risk` use, so a spec declaring two different classes, or a
  value that isn't one of the four, is labelled `class:feature`, and the receipt says why (`change_class_problem` in
  `--json`). `docs` and `refactor` start at low, `feature` (and a spec without the line or with an invalid one) at
  elevated and `schema` at high; other risks, such as a `docs` change that touches code, raise the label one step.
  The deliverer puts the highest risk label and every class label on the PR, creating missing labels, and only ever
  raises the risk label. The harness refuses the deliverer any other label change it can read (next entry), such as
  adding `harness-change-approved` or removing a label a person set. Labels are advisory: none approves or merges.

- **The deliverer's gate reads gh calls as the shell runs them (ADR-002).** The gate saw only gh written as a plain
  command: `$(...)`, `xargs`, a gh alias or a GraphQL query on stdin could add any label. It now reads gh calls in
  `$(...)` and backticks, `sh -c` (also `bash -lc`), `eval`, behind runners such as `timeout`, `env` or `nice`, and in
  heredocs and here-strings a shell reads, with `--repo` before the subcommand too. It refuses what it can't read:
  gh behind `xargs`, `parallel` or `find -exec`, a shell reading its commands from a pipe or a file, a command or flag
  that comes from an expansion, `--recover`, and gh aliases and extensions. The deliverer's `gh api` calls only read
  (`GET` or `HEAD`, never GraphQL). Before, `gh api graphql` could merge a PR or enable auto-merge, and REST could merge
  a branch (`/merges`), although ADR-002 says the deliverer never merges. A PR keeps one `risk:*` label: the harness
  reads the PR's labels before the deliverer adds one, and refuses a second. Every shell check now reads the lines
  after a here-string such as `<<<EOF` as commands, not as a heredoc body, and a quote inside `"$(...)"` as part of
  the substitution, so it no longer ends the string around it. The gate stays best-effort: it doesn't see gh run from
  a script or another program, nor other HTTP clients. GitHub permissions remain the boundary.

- **The deliverer's gh access is an allowlist (ADR-002).** The gate refused some gh commands and let the rest through,
  so the deliverer could turn on auto-merge or change the default branch (`gh repo edit`), run a workflow, set a
  secret or variable, close an issue, reopen a PR or publish a release. It now runs only what delivery needs:
  `gh pr create`, `edit`, `view`, `checks`, `list` and `comment`, `gh run view`, `list` and `watch`, `gh label list`
  and `create`, `gh repo view`, and `gh api` reads. Every other gh command is refused as the user's call, `gh issue`
  included: the deliverer labels its PR with `gh pr`. Also refused now: `gh label create --force`, which rewrites a
  label someone else defined; shell alias definitions, since a shell that expands aliases (Claude Code's often does)
  ran `g pr merge 7` as `gh pr merge 7` after `alias g=gh` on the line before; `source` and `.`, which read commands
  the harness can't see; and a command whose gh calls add different `risk:*` labels, which each passed against the
  PR's labels as they were before the command ran. gh behind `builtin`, `noglob` or `nocorrect` is read like gh
  behind `command`.

- **Plugin and pin must match (thin mode).** When the installed plugin isn't the release the project pins, its agents
  and skills don't match the pinned gates. Session start says so, with both versions and the fix. In autonomous mode
  `run` and `orca` refuse to start and every call except reads is refused until they match; `doctor` lists it as an
  error there and as a warning in supervised mode.
- **Role agents and paths in thin mode.** Subagents are told, at start, which pinned-engine paths stand in for the
  project's missing `AGENTS.md` and `scripts/harness/` (a `SubagentStart` hook in the Claude Code and Codex plugins).
  Codex and OpenCode sessions install the pinned role agents in the user's agents folder (a file the harness didn't
  write is kept and reported), and agents can't edit them. OpenCode sessions get the session-start context, which it
  has no hook for.
- **Worktrees in thin mode.** `run --worktree` and `orca` run the pinned engine on each task's worktree, and their
  prompts name its command. The pre-commit shim no longer refuses every commit in a linked worktree: git's hook
  variables pointed its cache check at the project instead of the cache. `pin` also brings `.githooks/pre-commit` and
  `harness-verify.yml` to the new release, so a fix to either reaches pinned projects.
- **Thin mode records verdicts in Claude Code.** Claude Code ignores the hooks a plugin agent declares itself, so the
  plugin's griller, judge, tester, debugger, reviewer and deliverer stopped without their report being recorded: no
  task could pass a gate. The plugin now runs the recorder on `SubagentStop` for those agents, as the Codex plugin
  already did. A live check (`HARNESS_E2E=1 tests/test-live-plugin.py`, one short Claude Code session) runs the
  plugin's judge in a thin project and fails if its verdict isn't recorded.
- **`update.sh --to-thin` and `--to-full` switch an installed project between the full install and thin mode.**
  `--to-thin` pins the installed release (or `--version`), deletes each harness file you haven't edited, Codex's and
  OpenCode's included, and keeps an edited one as `<file>.harness-bak`; `backbone/`, `CLAUDE.md` and adopted packs'
  files stay. The pin keeps the install date and the hashes the full install recorded for the harness's files that
  stay (`"kept"`; `init --thin` now records them for the documents it writes). It adds the pre-commit shim,
  `core.hooksPath=.githooks` and the plugin entries, and takes the harness's hooks and permission rules out of
  `.claude/settings.json`. `--to-full` installs the pinned release's files as `update.sh` would, also after the pin
  moved: a file you haven't edited becomes the release's copy, and an edited one is kept, with the release's copy in
  `<file>.harness-new` when the release changed it too. It appends new `harness.conf` settings, commented out, and
  takes the shim and the plugin entries out again. Both refuse a working tree with uncommitted changes, check
  everything before they write, undo their changes when a write fails part way, and change nothing when run again.
  Switching there and back without moving the pin gives back the install, except that an edited file outside
  `backbone/` becomes the release's copy with the edit kept in `<file>.harness-bak`. The README has a Thin mode
  section: the plugin for each CLI, `init --thin`, `pin`, switching, CI, the plugin/pin rule and the limits.
- **Packs in a thin project work from the hashes the pin keeps.** `harness.py adopt` and `adopt --remove` read a
  file's hash from the lock's `"kept"` when its `"files"` doesn't list it. So in a project switched with
  `update.sh --to-thin`, a pack can be adopted again after the pin moved, adopting it again without an option deletes
  that option's unedited files, and removing it deletes the files nobody edited and keeps the edited ones. In a thin
  lock, `adopt` records a pack's hashes under `"kept"` instead of `"files"`, and a removed pack's files leave both
  tables: `verify` takes a lock with `"files"` for a full install's and refuses every change to
  `.claude/settings.json`, and CI runs the base branch's engine, perhaps an older release. 0.30.0's `adopt` gave a thin
  lock `"files"`; adopting such a pack again, or removing it, takes its files out. Like the backbone documents a thin
  lock keeps, `doctor` doesn't report these files as edited.
- **`update.sh --to-thin --version V` takes the installed release's permission rules out of `.claude/settings.json`,
  not those of `V`.** Otherwise a rule only the installed release had would stay, and a rule of yours that only `V`
  adds would go. It fetches the installed release to read them, and refuses when it can't.
- **The machine guard knows thin projects, and the plugin gives its check.** The guard took a thin project (a
  `"mode": "thin"` pin in `backbone/.harness-lock.json`, no `scripts/harness/`) for one that isn't enrolled: it
  reminded the agent and, in block mode, refused its edits. A thin pin now counts, and so does a lock that can't be
  read (a merge conflict in the pin): the plugin refuses changes there until it is fixed. The plugin's own hooks now
  give the guard's reminder or refusal in Claude Code and Codex, with the same `~/.agentic-harness/machine.json`, so a
  machine with the plugin needs no guard hook: `./machine.sh install --plugin` writes only the settings and takes out a
  guard hook installed earlier. In a CLI that still has the guard hook, the plugin leaves the check to it, so nothing
  is said twice. An installed guard is a copy: run `./machine.sh install` again to get this fix.
- **`machine.sh` no longer breaks open sessions, and finds the CLIs' settings where they do.** Claude Code and Codex
  load hooks when a session starts, so a session open since `install` kept calling the guard after `remove` deleted
  it. Python exits 2 on a missing script, which both CLIs take as a refusal: every edit and shell command in that
  session was refused until it was restarted. `remove` and `install --plugin` now leave the guard's script for those
  sessions (after `remove` it finds no settings and lets every call through); restart them. `install`, `remove`,
  `status` and the plugin's check look for the hooks in `$CLAUDE_CONFIG_DIR` and `$CODEX_HOME` when they are set, as
  the CLIs do; `install` used to write them to `~/.claude` and `~/.codex`, where those CLIs didn't load them.
- **The plugin no longer waits for a Codex guard hook that Codex skips.** Codex runs a new user hook only once the
  user trusts it in `/hooks`, but the plugin left the check to any guard hook listed in Codex's `hooks.json`: after
  `./machine.sh install` without that step, nothing checked in Codex. The plugin now reads the trust Codex records in
  its `config.toml` (a hash of the hook under its file and position, and the on/off switch) and leaves the check to
  the guard hook only while Codex runs it: trusted as it is now, and switched on. Otherwise it answers itself, also
  when it can't read that file, and in sessions started with `--dangerously-bypass-hook-trust`, which it can't see
  (there a refusal can come twice). `machine.sh status` says when the Codex guard hook isn't trusted, changed since it
  was trusted, or is turned off. The plugin also answers when the guard copy in `~/.agentic-harness/guard.py` isn't this
  release's (a plugin upgrade without `./machine.sh install`), since that copy may check other settings; status says to
  install again. Where `status` runs from the checkout that installed the copy, it names the copy's release (`install`
  leaves it in `~/.agentic-harness/guard.release`) and says the plugin checks too wherever its own `guard.py` differs;
  the plugin's copy can't be seen from there. On Python 3.10, which has no `tomllib`, the trust and on/off settings
  are read from tables and dotted keys, quoted or not. A setting in any other form (an inline table, or an `enabled`
  that isn't true or false) can't be read: status says so, and the plugin answers too. `install --plugin` takes out an untrusted guard hook too. A live check
  (`tests/test-machine-guard.py`, needs `codex` on the PATH, no model calls) compares this with what `codex
  app-server` itself lists and records.
- **One reminder per session, also for hooks and tool calls run at once.** Claude Code and Codex run a call's hooks,
  and a session's tool calls, in parallel, and two guard checks could both find no reminder recorded yet and both
  remind. The record is now created atomically, so only one of them reminds. Run `./machine.sh install` again for the
  installed guard copy.
- **Machine settings that aren't usable count as none.** A string in place of the list of roots put every repository on
  the machine in scope (the guard read it character by character, and `/` holds every path). Such settings now check
  nothing, never block, and `machine.sh status` names the field to fix. So do a blank or relative folder in `roots` or
  `exempt` (it resolves against each session's working directory), and an `enroll` that isn't an absolute path, which
  used to let shell commands in unenrolled repositories through silently. `install --roots` writes absolute paths.
- Tests go through the harness's public commands and hooks only: the checks that grepped agent files for hook names
  now run those hooks, and the ones that imported `harness.py` to call its functions now use `approve`,
  `orca --dry-run`, `orca-digest`, `orca-nightly` and a real, held `orca` run.
- Property-based tests (`tests/test-properties.py`, hypothesis, test-only): an agent loaded from a plugin gets the
  decision of its role for any write, and no agent writes a verdict.
- `module-testing` skill: avoid mocks whenever possible; couple tests to public APIs and assert what the user
  observes; Testcontainers for integration tests and Playwright (through its MCP server) for end-to-end flows where
  the stack has them; reproduce a bug in a failing test before fixing it; find missing tests with mutation and
  property-based testing. The judge checklist checks that tests go through public APIs.
- **The code fingerprint comes from the files' content.** The fingerprint that judge, review and debug verdicts
  record, and that `finish`, the receipt, `next` and `state` compare with the code now, trusted git's index for every
  file whose size and timestamps hadn't changed. It read a copy of the index dated when the copy was made, so a
  same-size edit made within the second of the last index write hashed as the old content from the next second on. A
  judge pass could then name code the judge never saw (restoring the staged version after the judge passed got
  through `finish`), and committing the judged code could make the receipt refuse it: "the code changed after the
  judge passed", the intermittent failure in `tests/test-change-class.py`. Every file is now hashed, so a same-size
  edit that keeps the file's mtime (`cp -p`, `touch -r`) counts too where git doesn't trust ctime
  (`core.trustctime=false`). Files marked assume-unchanged or skip-worktree keep their index content, as in a commit.
  It costs more on large checkouts: about 0.4 s for 5,000 files, up from 0.06 s. `tests/test-code-fingerprint.py`
  covers it.

## 0.30.0 (2026-11-06)

- **The engine can run from outside the project** (first step of thin mode, ADR-001). The project is the folder in
  `HARNESS_ROOT`, otherwise the engine's own folder if it is a full install, otherwise the git repository of the
  working directory (or `CLAUDE_PROJECT_DIR`). Engine-owned files come from the engine: the core guardrails and
  routes, `decisions.json`, the pipeline agents, the catalog and the core skills. Project skills are added to the core
  ones and win on a shared name. The skill gate points at the file that is actually there, and reading it counts.
- CI extracts the base branch's core guardrails, routes and decisions alongside its verifier. `verify --range`
  continues to check task gates and protected changes; it does not scan the changed code for guardrail violations.
- Skill overrides apply to file reads, shell reads and skill invocations: loading an overridden engine skill does
  not satisfy the project skill requirement. Reports identify core rules correctly with an external engine.
- **The thin-mode launcher** (`plugin/launcher.py`). It runs the engine a project pins in
  `backbone/.harness-lock.json` (`"mode": "thin"`, `"version"`, `"commit"`):
  - It fetches tag `v<version>` once into `~/.agentic-harness/engines/<version>/` (`HARNESS_ENGINES`, source
    `HARNESS_ENGINE_SOURCE`), and refuses a release or a cached copy whose commit isn't the pinned one.
  - A repository without the harness is left alone, and a full install keeps its own hooks.
  - When the pinned engine can't be run, it fails closed: reads go through, other tool calls are refused with the
    reason, the session is told at start, and commands exit 1.
- `init --thin` now fetches and checks the release before writing project files. It refuses older tags without thin
  plugin assets, seeds files from the pinned release, preserves existing project-owned docs, and pins Claude's
  marketplace to that release tag. The next release version is `0.30.0`; the default install waits for its tag.
- Thin session startup supplies the pinned engine's agent rules as context in Claude and Codex. Health checks now
  recognize the thin pre-commit shim and plugin setting.
- **Thin mode can't be switched off from inside a session.** Agents may not change the engine cache or the plugin
  (file tools or shell, by any path that reaches them), run `pin`, or change the `.githooks/` pre-commit shim. The
  launcher and the shim refuse a cached engine with local changes, and a lock that exists but can't be parsed (an
  unresolved merge conflict) fails closed instead of reading as "not enrolled". Shell redirections to quoted paths
  with spaces are now checked.

## 0.29.0 (2026-11-05)

- **`typescript` pack.** The options:
  - a package manager (`npm` | `pnpm`), which sets a `tsc --noEmit` build check and the test command;
  - a test runner (`vitest` | `jest`), which sets the test paths and installs `typescript-test`;
  - `strict`, which refuses `@ts-ignore` and `@ts-nocheck` and warns on `any`.

  The pack always refuses `eval` and `new Function` and warns on stray `console.log`.
- **`react` pack** (requires `typescript`). It refuses `dangerouslySetInnerHTML` and warns on index keys. Options:
  - `nextjs` routes `app/`, server actions and the request pipeline to the `nextjs` and `security` skills, and refuses
    secrets in `NEXT_PUBLIC_` variables;
  - `testing-library` warns on CSS-selector queries in component tests.

  There is no NestJS pack: `triple-disputes` is Next.js.
- **Chained git hooks.** Doctor accepts a `core.hooksPath` that another manager owns (Husky's `.husky/_`) when its
  `pre-commit`, `commit-msg` and `pre-push` call the harness's, and names any that don't.
- **`disputes-pci` locks fit the real `triple-disputes` tree.**
  - No longer parked: UI cards, i18n `auth` keys, intake chat sessions and deployment helpers.
  - Now parked: PAN-handling modules, the Prisma schema, and the SAML and NextAuth routes.
- **Runbook**: how to fit into `triple-disputes`, covering `AGENTS.md` and `CLAUDE.md`, Husky, the double type check,
  and the PR title convention.

## 0.28.1 (2026-11-05)

- **Disputes pilot runbook** (`catalog/triple/RUNBOOK.md`). The runbook covers:
  - the decisions and approvals the pilot needs;
  - bootstrapping onto a fork or a throwaway repo with `enroll --profile triple`;
  - adopting the `triple` pack and importing one light-lane `DIS-*` ticket;
  - the supervised define → build → judge → receipt → PR loop, where a human merges;
  - the metrics to record.
- **`harness.py report` counts escalations by class** (`escalations_by_class` in `--json`).

## 0.28.0 (2026-11-05)

- **Failure classes.** Every escalation in `backbone/escalations.md` now records a class and the playbook that recovers
  from it. The classes are `tool_timeout`, `invalid_args`, `missing_context`, `failed_test`, `permission_denied`,
  `contradictory_req` and `unchanged_repeat`.
  - The class comes from the escalation's kind and reason, or `escalate --class` sets it.
  - When repeated judge fails escalate a task, the last debugger brief decides the class.
  - `harness.py escalations` counts escalations by class.
- **Coordinator recovery.** A step worker that dies before reporting gets one retry after `HARNESS_ORCA_RETRY_WAIT`
  seconds (`tool_timeout`), and is escalated only after that.
- **Flywheel v1.** A class escalated twice opens a draft proposal, `backbone/proposals/<class>.md`, listing every
  occurrence. The scribe may draft the guardrail, test or skill change there. Nothing is applied until the user acts
  on it through an approved task.

## 0.27.0 (2026-11-05)

Triple adapter layer for the supervised Disputes pilot, on top of the core harness.

- **Profiles** (`HARNESS_PROFILE`, user-only). `triple` means only a human merges, and the code enforces it:
  - `harness.py orca` refuses `--merge` and `--trust`, and `orca-nightly` refuses to start;
  - `enroll` refuses `--automation` and `--protect` before changing anything (`enroll --profile triple` sets the
    profile);
  - the shell gate refuses `gh pr merge` and GitHub's merge API, and the tool gate refuses MCP merge tools.

  `HARNESS_PROFILE=triple` or `TRIPLE_MODE=1` in the environment adds the profile, but clearing the variable never
  lifts one that `harness.conf` sets.
- **EARS requirements** (`HARNESS_REQ_STYLE`, user-only, `plain` | `ears`). With `ears`, `spec-check` refuses a
  requirement that has no `shall`, more than one `shall`, no named system, a `When`/`While`/`If`/`Where` without its
  clause, `If` without `then`, passive voice, or untestable words. Acceptance criteria stay Given/When/Then; they may
  also prove `NFR-<task>-<n>` items, and every criterion must cite a requirement or an NFR. The analyst, architect and
  griller prompts, the spec template and `requirements-writing/ears.md` cover the patterns.
- **Linear as the system of record** (`harness.py linear`, user-only; agents may only run `--dry-run`).
  - `linear import <ISSUE> --task <id> [--light] [--from <issue.json>]` writes a draft spec with a `Linear:` line and
    the ticket quoted as source material, and adds the task line.
  - `linear receipt <task> [--status <state>]` posts the receipt on the ticket and never moves it to a completed or
    canceled state.
  - Standard library only (`lib/linear.py`). It is tested against a local fake of the GraphQL API with a recorded
    `DIS-*` fixture.
- **`triple` catalog pack.** Option `disputes-pci` parks authentication, billing and payments, migrations, PCI
  evidence, secrets and infrastructure:
  - file and shell writes to them are refused, and so are running migrations and storing a CVV; card numbers get a
    warning;
  - those paths and terms make a task not low-risk;
  - it installs the `disputes-pci` skill.

  Option `ears` sets `HARNESS_REQ_STYLE`. `catalog/triple/tools.conf.linear` holds Linear MCP contracts for the user to
  paste into `tools.conf`. The pack's README says the devcontainer is not a PCI attestation.

## 0.26.1 (2026-11-03)

- **Applied recommendations don't grow the spec; out-of-domain cases don't fail a task.** Found in a trial run of
  0.18.2 (colsum, a small local CSV tool):
  - **What went wrong:** all six of the griller's recommendations added detail, and nobody was asked about them. The
    task then failed the judge twice and was escalated, over an argument holding a newline (rated blocker) and over
    argparse accepting `--col` for `--column` (rated major).
  - **Griller:** a recommendation should tighten, merge or remove. It adds a requirement, criterion or case only for
    behaviour the product's users will meet.
  - **Judge:** a case only out-of-domain input can trigger is minor, whatever the requirement's wording, and an AC
    whose own Given, When and Then hold is met.
  - **Reviewer:** such a case is at most `nice-to-have`.

## 0.26.0 (2026-11-03)

- **Review lenses, in parallel, before a task can finish** (`HARNESS_REVIEW`, user-only, default `on`). After the
  judge passes, `next` returns the `review` step with the lenses still due. The orchestrator (or the Orca
  coordinator's worker) starts one new `reviewer` agent per lens, all at once:
  - `correctness`: bugs, security, scale, missing tests, and blast radius, proven by running real code;
  - `structure`: the "code judo" move, files pushed past 1000 lines, spaghetti growth, logic in the wrong layer;
  - `lean`: delete, reuse, stdlib, yagni.

  Each lens records its verdict on the code fingerprint in `backbone/.verdicts/<id>.review.json` (`review-stop`). A
  `must-fix` finding records a fail whatever the reviewer claimed and sends the task to the implementer, then the
  judge and the lenses again. The judge gate requires every lens's pass on the current code, so `finish`,
  pre-commit and CI `verify` refuse a task without it.
- **Delivery is a pipeline step** (`HARNESS_DELIVER`, user-only, default `on`). A committed task is `done` only once
  the new `deliverer` has pushed its branch, opened or updated its PR (receipts, plus the reviews' should-fix
  findings as follow-ups) and seen `gh pr checks` pass. Its report is checked against git: `delivered` needs a clean
  tree, `HEAD` pushed and green checks; `hold` and `ci-failed` need findings with owners. `next` then returns
  `deliver`, `delivery-failed` or `done`. It never edits files: its `gh pr merge`, `close`, `review` and `ready`, and
  any push to or from the default branch, are refused.
- **Pre-push hook.** `verify` runs on the commits being pushed, so no push carries a finished task without its judge
  and review passes. The user pushes a deliberate exception with `HARNESS_VERIFY=off`.
- **The runners deliver.** `harness.py orca` runs the review and deliver steps (a failed delivery is escalated), and
  no longer pushes or opens PRs itself; `--pr` is accepted and does nothing. `harness.py run` sessions drive the task
  until `next` says `done`, and a session that finished without delivering is retried. `run --worktree --pr` pushes
  only blocked or escalated tasks now. In `orca --merge`, the base branch is delivered from its own checkout.
- **Upgrading:** a task finished before 0.26.0 has no reviews. Once this version is on the base branch, CI `verify`
  and the pre-push hook refuse a range that finishes such a task: review it (the lenses run on a `[WIP]` task, so
  reopen it), or have the user push and merge it with `HARNESS_VERIFY=off` and the CI exception they already use.
- **`change-review` core skill**, the reviewers' lenses. Adapted from the MIT-licensed thermo-nuclear reviews and
  pstack's blast-radius and prove-it-works (cursor/plugins), and from ponytail-review (DietrichGebert/ponytail);
  notices in the skill's `NOTICE.md`.

## 0.25.0 (2026-11-03)

- **Supervised mode catches script writes to harness files.** Out-of-band detection ran only in autonomous mode,
  because the user's own edits would look like tampering. Now, in supervised mode, the snapshot of the protected
  files is also taken as each shell command starts, and only what changed while it ran is reported: the agent gets
  a note naming the command and files, and a `tamper` event is logged. Nothing is escalated. Edits made between
  commands are not reported.
- Failed shell commands are checked too (`PostToolUseFailure` hook), in both modes. Overlapping commands share the
  snapshot from the first one's start, so no command's changes are hidden by another starting.
- **Cheaper snapshots.** The snapshot caches each file's hash by size, modification and change time (a script can
  put mtime back, not ctime), and checks restores to the committed version with one `git ls-tree`, so taking it
  around every shell command costs a directory walk. `.claude/worktrees/` is no longer part of it.

## 0.24.0 (2026-11-03)

- **Tool contracts** (`backbone/tools.conf`, user-only). Only Bash, the file tools and the knowledge server went
  through the gates: `NotebookEdit` or an MCP server's write tool could change `backbone/3-TASKS.md` unchecked.
  The PreToolUse hook now runs for every tool except Read, Grep, Glob, LS and TodoWrite. Each tool has a contract:
  class `read`, `write` (with the input field that holds the path), `exec`, `network` or `agent`, and optionally
  `confirm`. A write tool's paths get the same gates as Write and Edit, and harness files are refused to it. A
  `confirm` tool is refused in autonomous mode. The agents' own tools have built-in contracts the file can't change.
- **Tools with no contract** run with a warning in supervised mode and are refused in autonomous mode. Each use is
  logged as `tool-unknown`, and `harness.py report` lists the tools still without a contract.
- Gated tool calls are logged as `tool` events (class and paths), so `trace` shows MCP and notebook writes too.
- Codex sends MCP tools through the PreToolUse and PostToolUse hooks.
- **Relative paths meet the gates.** A relative path with `..` (`src/../backbone/tools.conf`) skipped every
  backbone check, through the file tools, `apply_patch` and now MCP write tools. Paths are resolved against the
  repository first.

## 0.23.0 (2026-11-01)

- **Light lane for small fixes** (`HARNESS_LIGHT_LANE`, user-only, off by default). A task the user marks `(light)`
  on its line skips the architect and the griller when its spec has at most `HARNESS_LIGHT_MAX_ITEMS` requirements
  plus criteria (default 3) and is low-risk. It still needs a valid spec, the user's approval (or policy approval in
  autonomous mode), a judge pass and verify. Starting a light task records the commit it started from, and finishing counts every file
  changed since, committed or not: a light task that changed more than `HARNESS_LIGHT_MAX_FILES` files (default 3) or
  touched a sensitive path is refused; the user then removes the mark and it is grilled. A marked task that doesn't qualify is grilled, and the start gate says why. Only the user adds the mark:
  agents' edits and commits that add it are refused.
- **Case-variant paths get the gates.** On a case-insensitive disk, an edit of `backbone/3-tasks.md` (or another
  spelling of a gated backbone file) skipped its checks. Paths are now matched to the gated names first.

## 0.22.0 (2026-11-01)

- **`harness.py report` measures what the harness buys.** Accepted work: the first-pass judge rate, griller fails
  that led to a spec change, the median time from start to finish, cost and escalations per finished task. What the
  gates and rules catch: refusals per gate, fires per guardrail rule, and the project rules that never fired
  (`report --rules` lists them all). Slow hook calls.
- **Harness candidates.** The report lists failures that keep coming back across tasks: the same refusal in 3 or
  more tasks, the same judge failure in 2 or more, the same escalation kind in 2 or more. Each points at a missing
  instruction, rule or skill; the user decides the fix.
- **The scribe proposes rules.** A lesson a regex can catch comes back as a `guardrails.conf` line for the user to
  add.
- New events: `rule` (a guardrail rule matched), `gate` (a gate refused), and `task-start` / `task-finish` when a
  task line is edited through the gates.

## 0.21.0 (2026-11-01)

- **Trace a task.** `harness.py trace <id> [--json]` prints what happened during a task, in order: the project
  knowledge and skills its agents loaded, the files they edited, the calls the hooks refused, the harness's test
  runs, verdicts, escalations and runner attempts. Every event now carries the task in progress and, inside a hook,
  the session and agent. Paths only: no file contents are logged.
- New events: `context`, `skill`, `edit`, `tests-run`, and `hook-slow` for a hook call that took
  `HARNESS_HOOK_SLOW` seconds or more (new setting, default 5).
- `log_event` never raises: an error there could turn a refusal into a non-blocking hook error.

## 0.20.0 (2026-11-01)

- **A retry changes something, or the task is escalated.** `harness.py run` used to send a failed task the same
  prompt again. Now the next session is told why the last one stopped (timed out, exited with an error, finished
  without committing, or ended unfinished), the task's next step with the judge's findings and the debugger's brief,
  and the calls the hooks refused during it, and it continues from that step. A retry that ended cleanly but changed nothing (same next step, same
  files, specs and verdicts included, same commit) escalates the task at once instead of using up the attempts. A
  session that failed with an agent error or timed out keeps its attempts.
- **The Orca coordinator stops restarting a worker that changed nothing.** `harness.py next --json` reports
  `progress`, a fingerprint of the checkout. When a role step comes back with the same progress after its worker
  reported success, the task is escalated rather than the worker started again.
- Each `run-attempt` event records its cause and the step the task stopped at.

## 0.19.0 (2026-11-01)

- **Change receipt.** `harness.py receipt <id>` states what the harness can prove about a judged task, built from the
  spec, the verdicts and the diff rather than from the agents' report: what changed since the task's base, each
  acceptance criterion with the tests and evidence that prove it, the harness's own test run, what is **not**
  verified (NFRs no criterion covers, criteria not met, findings left open), the ADRs followed and added, the
  assumptions with their sources, the risks and rounds, and what still needs the user (Proposed ADRs, open
  escalations). It refuses a task with no judge pass on the current code. `--json` gives the same for machines.
- The report step of the workflow (step 13) is the receipt, instead of a summary the orchestrator writes.
- `harness.py run` saves each finished task's receipt next to its logs, and `--pr` puts it in the pull request. The
  Orca coordinator puts it in its pull requests too, keeps it in `.git/harness/receipts/`, and lists it in the digest.

## 0.18.2 (2026-10-25)

- **The analyst goes with its own recommendation too.** An open question the analyst has a recommendation for,
  and that isn't a blocker, is recorded under Assumptions (`source: the analyst's recommendation; the user may
  change it`) instead of being left open and escalated. Found in a trial: the analyst escalated whether empty
  cells count as 0, although its draft already said so.

## 0.18.1 (2026-10-25)

- **`harness.py orca --help` no longer starts a run.** It prints the usage. An unknown argument, such as a
  misspelled `--merg`, is refused with exit code 2 instead of being ignored by a run that then starts.

## 0.18.0 (2026-10-25)

- **Only blockers are asked; the griller's recommendations are applied.** A griller question can now carry a
  `recommendation`, the exact fix it would accept. The recorder marks a non-blocker with a recommendation `apply`.
  The analyst or architect makes that change as a real edit to the spec or ADR, without asking the user or
  escalating, and records it under Assumptions (`source: the griller's recommendation, grill round N`). A blocker
  is still asked, or escalated in autonomous mode; its recommendation is only a proposal. `harness.py questions`
  shows which questions are to apply, and `next` reports `needs_user`. The hook never writes into the spec, and
  the spec is grilled again after the changes, so the griller checks the recommended text before the spec passes.

## 0.17.0 (2026-10-18)

From the end of the ledger run (10 of 10 tasks merged; 785 tests and 10 ADRs for a small CLI):
- **The judge checks proportion.** Over-engineering got past every gate: the judge asked only whether the spec was met. It now also asks whether the change is the simplest one that meets it. Code the task doesn't need is a major finding, so the judge fails the task. That covers a hand-written replacement for the standard library, an option or layer nobody asked for, defences against inputs the threat model rules out, and duplicated tests.
- **Fewer, non-duplicated tests.** The tester writes a criterion's own examples, not a matrix of variations. When the tester has covered a criterion, the implementer doesn't write a second copy, and adds unit tests only for logic of its own.
- **Decisions stay decided.** Task 1.9 re-raised a file-size limit the user had already decided, because older notes in `3-TASKS.md` and `6-MEMORY.md` still called it open. A recorded user decision now wins over such notes, and the scribe marks memory questions a task settled.
- **The scribe proposes ADRs.** It was told to write emergent ADRs as `Accepted`, which the harness refuses (only the user accepts an ADR). It now writes them `Proposed`.
- **Missing sources are caught at spec-check.** Task 1.9's spec passed spec-check and the griller, then `approve` refused it because one assumption had no `(source: ...)`. The analyst had been told to write "the analyst's choice" without a source. Spec-check now reports a missing source, and the analyst writes `(source: the analyst's choice; ...)`.
- **The sync before approval runs on work in progress.** It skipped every task with uncommitted changes, so in practice it never ran. It now merges the base in around the task's own work, and logs why when git refuses. It leaves a merge already in progress in the worktree alone, and a refused sync commit is undone and reported, not logged as a sync.
- **Updates no longer conflict in `harness.conf`.** The comment the update adds over new settings named the harness version, so tasks updated at different versions conflicted on that line (tasks 1.7, 1.8 and 1.10).
- **Dependencies written without a colon count.** `3-TASKS.md` notes like `(after 6.1a)` were ignored; only `(after: 6.1a)` was read. coefficiency writes them that way, so the coordinator would have run tasks in parallel that must run one after another. Both forms are read now, and only tokens that look like task ids count.
- **`harness.py report` counts Orca runs.** It showed "0 tasks finished" after the backlog because only the old runner recorded events. The coordinator now records each worker's outcome (answer workers and workers that failed at startup included), each integration and each merge, and the report shows them.

## 0.16.3 (2026-10-18)

From the ledger run:
- **Task branches are brought up to date before approval.** Decisions taken on the base after a task's worktree was made, such as ADRs the user accepted or other tasks' code, didn't reach the task. Task 1.10 was escalated over ADRs already accepted on `main`. The coordinator now merges the base into a task's branch before approving or starting it, resolving the conflicts it understands. With a code conflict it leaves the branch as it is, and the integrate step deals with it at merge time.
- **Citing a skill isn't touching a sensitive path.** The risk check flagged task 1.10 because its spec cited `.claude/skills/security/SKILL.md` as a source. Harness files a spec cites (skills, backbone docs, harness scripts) no longer count as paths the change touches.

## 0.16.2 (2026-10-18)

- **Assumptions with nested lists.** `approve` read each sub-bullet of an assumption as its own assumption "without a source", so task 1.7's spec, with one assumption listing its parts and citing its source once, could never be approved. The source check now joins nested lines and sub-bullets to the item above them.
- **The coordinator explains a refused approval.** It retried `approve` until its "no progress" guard escalated, without showing why. Now it logs `approve`'s own message and escalates with it right away.

## 0.16.1 (2026-10-18)

- **A person's answer gives a task fresh rounds.** In the ledger run, task 1.8 was escalated over the duplicate rule. After the answer, the griller rightly asked for the spec to be rewritten to it, but the round limit still counted the round from before the answer, so the task was escalated again mid-rewrite. The griller's and judge's round limits now count only failures since the task's latest escalation.

## 0.16.0 (2026-10-18)

ADRs in parallel work, from the ledger backlog run:
- **ADR numbers no longer collide.** Each parallel task took "the next ADR number" in its own worktree, so `ADR-006` and `ADR-007` meant different decisions on different branches. Now:
  - `harness.py adr-number` hands out numbers from a counter all of a repository's worktrees share, under a lock; the architect and the scribe use it.
  - Before merging a task, the coordinator renumbers any new ADR whose number the base already uses for another ADR, and updates the references in the files the task changed.
- **Proposed ADRs are visible.** ADRs written during builds reached the base still Proposed, decisions nobody had accepted. The coordinator's digest now lists them. The architect writes an ADR only for decisions that are hard to reverse and matter beyond the task.

## 0.15.3 (2026-10-18)

**Specs that converge.** The dominant failure in the ledger backlog was spec bloat. Task 1.10 ("export and import as JSON") grew to 49 requirements and acceptance criteria and 7 ADRs, and the griller found new detail in every round until its limit escalated the task. Task 1.2 shipped a hand-written CSV reader. Instructions alone (0.13.2) didn't stop it, so:
- **`HARNESS_SPEC_MAX_ITEMS`** (user-only, default 30): spec-check refuses a spec with more requirements plus acceptance criteria than that, so it goes back to the analyst to be cut or split.
- **The griller's later rounds narrow:** only what changed and its own open questions, at most 5 questions, and a spec good enough to build correctly passes.

## 0.15.2 (2026-10-18)

From the ledger backlog run:
- **The architect designs against the product's threat model.** For `import_json` (task 1.10), the architect proposed a hand-written JSON parser to accept any nesting depth, for a file the tool writes itself, and the choice had to be escalated. The architect now builds no defences against inputs the PRD's formats rule out, and uses the standard library's behaviour instead.
- **Minor questions get a default, not an escalation.** The analyst escalated a minor question (who else reads the export format). It now records a sensible default as its own choice, and escalates only blocker and major questions the sources can't settle.

## 0.15.1 (2026-10-17)

- **Integrate again when the base moves.** In the ledger run, task 1.6 was integrated with `main`, then 1.1 merged first and `main` moved on, so 1.6's merge conflicted again (`ledger/money.py`, which both tasks had built). The coordinator now integrates again whenever the base has moved since the last integration, up to 3 times, before escalating.

## 0.15.0 (2026-10-17)

- **Integrating parallel tasks.** In the ledger backlog, three tasks running in parallel each wrote their own `ledger/errors.py`, the project's shared error module, and the coordinator could only refuse the merge. A code conflict now starts an **integrate** step:
  - The coordinator merges the base into the task's branch in its worktree and resolves what it understands: harness-owned files take the base's version, the task list and logs as before.
  - An implementer worker resolves only the conflicted code files, with its normal (gated) file tools.
  - The coordinator commits the merge and runs the tests (`harness.py test-run`) before merging into the base. If markers remain or the tests fail, the task is escalated.
- New commands: `harness.py test-run` (runs `HARNESS_TEST_CMD`), and `harness.py snapshot` (refreshes the out-of-band snapshot after the coordinator's own git work; refused to agents).

## 0.14.1 (2026-10-17)

- **Orca coordinator merges finish what they started.** In the ledger backlog run, two parallel tasks both changed `backbone/escalations.md`, and the merge was refused, leaving the tasks after them waiting.
  - `escalations.md` is now merged by entry: both sides' entries are kept, and one resolved on either side stays resolved.
  - A resumed `harness.py orca --merge` merges tasks that finished on their branch in an earlier run but never reached the base.

## 0.14.0 (2026-10-17)

**Project Enrollment and Shell Gating.** The harness now provides opt-in project enrollment and enforces shell gates for agents:
- `enroll.sh`: installs or updates the harness, runs doctor, and registers the project in Orca with `--orca` (including automation schedule, one automation per checkout).
- **Automation precheck**: executes `harness.py orca-nightly`, which opens an Orca terminal running `harness.py orca --merge --trust`; the automation agent reports only `harness.py orca-digest` (the last finished run's summary, kept in its own file).
- **Coordinator Lock**: ensures one coordinator per repository via an OS file lock; agents may not start `harness.py orca` or `orca-nightly`, but may run `orca --dry-run` and `orca-digest`.
- **CI Protect**: uses the default branch, preserves existing checks (including app bindings), reviews, and rules, and changes nothing if it cannot read current protection.
- **Machine guard**: in block mode, allows only the harness's own enroll.sh (the path machine.sh install records), and checks the paths and cd targets a shell command names; it fails open when its own lookup fails; it checks the repository of each written file and, for shell, the working directory.
- **Orca skill**: tells coordinators to plan with `--dry-run` and to ask the user to start runs.
- **Reviews**: Three Codex review rounds: 19 findings, then 9, then 3; all fixed with behaviour tests, except two documented limits: the machine guard can't see a shell command's paths built at run time, and it fails open when its own lookup fails.

## 0.13.3 (2026-10-17)

More from the ledger backlog run: **false escalations from over-adversarial grilling.**
- `format_money` was escalated over `Decimal('1E+100000000')`, and `parse_amount` over `str` subclasses and a CLI file-size limit (task 1.9's business). The griller's instruction to cover "abuse cases" applied hostile-input thinking to a local tool reading its own user's bank file.
- Now the griller judges abuse cases by the product's threat model (who supplies the input, across which trust boundary). It doesn't ask about inputs outside the PRD's domain or about another task's scope (at most a minor suggesting "out of scope").
- The analyst settles such questions under Out of scope with their source, instead of escalating them.

## 0.13.2 (2026-10-17)

Findings from the 10-task ledger backlog run:
- **Specs that never converge.** For `parse_amount`, the analyst and architect wrote 31 acceptance criteria, an exact regex and an error-message length cap. The griller kept finding blocker-level contradictions inside that detail, and the task was escalated after 3 rounds. Now:
  - the analyst specifies behaviour, not internals;
  - the architect keeps implementation out of the spec;
  - the griller asks for detail nobody asked for to be removed (major), not perfected, and reserves "blocker" for behaviour that would be wrong for users.
- **Codex in a worktree:** the worktree's git metadata lives in the main repository's `.git`, outside Codex's workspace-write sandbox, so `harness.py next` (and any git write) asked for approval. The coordinator now starts Codex with that `.git` as a writable root.
- **Coordinator log:** it now says when and why a task settles (blocked, done), and it watches the terminals it opened itself for approval prompts (the handle was missing).

## 0.13.1 (2026-10-17)

- **`harness.py orca --trust` also trusts the repository itself.** Claude Code decides trust for a git worktree by its main repository, so trusting only the task worktrees still blocked every Claude Code worker (`Agent startup blocked: agent-trust-workspace`). Found on the first run of the 10-task ledger backlog.

## 0.13.0 (2026-10-17)

- **`harness.py orca` runs a backlog, not just a batch.**
  - All ready tasks are queued; up to `--parallel` run at once, and the next starts when a slot frees.
  - Dependencies come from the task line: `(after: 1.2, 1.3)`. A task waits until they are `[x]` on the base branch, and `--dry-run` shows what it waits for.
  - `--merge` brings each finished task into the base branch, so the tasks after it build on it.
  - Conflicts only in `3-TASKS.md` (neighbouring task lines) and the memory and decision logs are resolved: the base's task list with the task marked `[x]`, and both sides of each log. Any other conflict aborts the merge and is reported.

## 0.12.1 (2026-10-17)

- **Codex workers report to Orca without permission prompts.** `.codex/rules/harness.rules` (harness-owned and lock-checked) allows exactly `orca orchestration check`, `send` and `ask` outside Codex's sandbox; everything else keeps Codex's own approvals (checked with `codex execpolicy check`). Codex loads it once the project's `.codex/` layer is trusted, which `harness.py orca --trust` does for task worktrees. This removes the manual approvals of the 0.12.0 live run.

## 0.12.0 (2026-10-17)

- **Orca coordinator: `harness.py orca`.** It drives ready tasks in parallel with Orca supervised workers, one Orca worktree per task and one worker per step. It asks `harness.py next` what each task needs, and runs approve, start, finish and the commit itself, through the gates.
  - **Questions between agents:** a worker asks the coordinator. An analyst or architect worker answers from the sources into the spec, with its source, and the reply says where. What nobody can answer is escalated.
  - **Griller questions** spanning both roles are answered by each role before the next grill, the blocker's owner first. A spec with only placeholder tech requirements goes to the architect.
  - **The agent per role** is set by `HARNESS_ORCA_AGENTS` (for example `judge=codex`). Launch commands come from `HARNESS_ORCA_LAUNCH`: Codex starts with the hook-trust bypass and without its update prompt.
  - **`--trust`** marks the task worktrees trusted for Claude Code and Codex.
  - **Lifecycle:** every delivery is acknowledged, and a worker is released only after it settles. A worker that Orca reports failed without a report (for example a blocked startup) escalates its task. A worker waiting at a permission prompt is logged and never answered. A step that comes back 3 times without progress is escalated.
- **Live run with Orca:** two tasks in parallel, Claude Code for the roles and Codex as the judge.
  - Both finished: analyst, architect, griller (with answer rounds), policy approval, tester, implementer, Codex judge (verdicts recorded through Codex's `SubagentStop` hook), scribe, commit.
  - One question the sources didn't settle was escalated and answered.
  - The run found and fixed these bugs:
    - the out-of-band snapshot was shared between worktrees, so parallel tasks saw each other's files as tampering;
    - the tester's acceptance files, and harness files, made `next` skip the implementer;
    - "permission" and "role" in ordinary prose made a spec risky (the defaults now name access-control phrases: RBAC, access control, user or admin roles, permission model);
    - Codex's directory-trust and update prompts blocked unattended starts.
  - **Still manual:** Codex asks before each `orca orchestration` command until you allow them once (see `backbone/HOOKS.md`).
- `next` sends a `[WIP]` task back to the griller when its spec changed during the build.

## 0.11.0 (2026-10-17)

- **Tester** (`HARNESS_TESTER`, user-only, default `off`): independent acceptance tests.
  - The new `tester` agent writes at least one acceptance test per AC from the spec, before the code exists, in files matching `HARNESS_ACCEPTANCE_PATHS` (default: paths containing `acceptance`). They should fail at that point.
  - The tester may write only there, and the implementer may not write there.
  - On the tester's Stop, the harness records which files cover which criteria, and a fingerprint of them (`backbone/.verdicts/<id>.tests.json`). It refuses to record while a criterion has no acceptance test.
  - The judge gate refuses to finish a task without recorded tests, with a criterion uncovered, or with the tests changed since, including through the shell. The judge's evidence no longer comes from the code's own author.
- **Debugger** (`HARNESS_DEBUGGER`, default `on`): after a judge fail, `next` sends the task to the new `debugger` agent before the implementer.
  - It changes nothing. It reproduces the failure and records a fix brief, with a root cause, a fix and an owner per problem (`backbone/.verdicts/<id>.debug.json`).
  - `next` hands the brief to the implementer, and flags causes owned by the tester, analyst or user under `needs`.
- `next` gains the steps `test` (tester) and `diagnose` (debugger). The Codex and OpenCode adapters record both roles, and their agents are generated.
- Existing projects get the new settings commented out in `harness.conf` on update.

## 0.10.0 (2026-10-17)

- **Codex and OpenCode reach the same gates as Claude Code.** Every CLI's hooks call `harness.py hook <event> --from <cli>`, which normalises the input before any gate runs.
  - Codex: `.codex/hooks.json`. Its `apply_patch` edits are parsed and checked file by file; verdicts come from `SubagentStop`; a skill counts as loaded when its SKILL.md is printed; the Stop hook always answers with JSON, as Codex requires.
  - OpenCode 2 (and 1): `.opencode/plugins/harness.js` translates `shell`, `edit`, `write` and `patch` calls and refuses blocked ones by throwing (fail closed on crashes and timeouts). Verdicts come from the `subagent` tool's result. Its primary agents (`build`, `plan`) count as the main session.
  - The role agents for both are generated from `.claude/agents/` by `tools/gen_agents.py`. Codex has no per-agent tool list, so the harness now holds the griller and judge to "no edits" itself, by role.
  - Live checks: in both Codex 0.162 and OpenCode 2.0.26, a `git commit -n` and a forged verdict file were refused by the harness hooks.
- **Role sessions:** `HARNESS_ROLE=<role>` makes a whole session one role (a coordinator's worker). It is held to that role's write scope, records the griller's or judge's verdict when it stops, and leaves the Definition of Done to the coordinator.
- **Coordinator API:** `harness.py state`, `next <id>`, `questions <id>`, `start <id>` and `finish <id>`. A coordinator learns the next step and its role from the artifacts the gates check, and moves task lines through the same gates as an edit. Griller questions are routed: design to the architect, the rest to the analyst.
- **Orca:** with `HARNESS_ORCA_RUN` set, `escalate` also posts an `escalation` message to the Orca Run.
- **Runner:** reads Codex's `exec --json` (turns) and OpenCode's `run --format json` (cost per step) logs, and stops when either can't start. The Claude Code trust check applies only to `claude` commands. A Codex command without `--dangerously-bypass-hook-trust` is refused, because Codex would skip untrusted project hooks.

## 0.9.1 (2026-10-13)

- **`update.sh` brings new settings into `harness.conf`.** The file is project-owned, so update never rewrote it, and every new setting meant copying lines from the template by hand. Update now appends any setting the template has and the project's file lacks, **commented out** and with the template's explanation, and reports it as `migrate`. Nothing changes until you uncomment a line; a key you commented out yourself counts as present and isn't added again. User-only settings still need a commit as the user once you uncomment them.

## 0.9.0 (2026-10-13)

- **Knowledge source for grilling (autonomous mode).** When `backbone/` doesn't answer a griller question, the analyst and architect search a read-only notes vault behind an MCP server registered as `knowledge` (for example the second-brain vault). A clear answer becomes an assumption citing `vault:<path>`; a question that is silent, vague, contradicted, or already in the vault's open-questions register is escalated as before. A blocker may be settled from the vault only by an accepted decision record. Nothing is written to the vault.
  - New user-only settings: `HARNESS_KNOWLEDGE_ROOT` (the vault folder; empty = off), `HARNESS_KNOWLEDGE_PATHS` (folders agents may read and cite) and `HARNESS_KNOWLEDGE_TOOLS` (the read-only tool names).
    `backbone/harness.conf` is project-owned, so `update.sh` doesn't add them: existing projects copy the block from the template, and commit it as the user (`HARNESS_VERIFY=off`).
  - The hooks refuse the server's write tools, any knowledge tool while the source is off, and reads outside the allowed folders.
  - `approve` refuses an assumption without a `(source: ...)`, and a `vault:` citation that isn't an existing note in the allowed folders.
  - The griller re-reads every cited source and raises the question again when the note doesn't back the assumption.
  - `.claude/settings.json` gains a `PreToolUse` hook for `mcp__knowledge__.*` and allows `mcp__knowledge` for unattended sessions (the hook keeps it read-only). Doctor warns when the source is on but no `knowledge` server is registered; `report` counts lookups.
- **Stricter `approve`:** every assumption needs a source, with or without a knowledge source.
- **Live runs against the second-brain vault** (2 tasks, with read access limited to the engineering folders):
  - First run: one lookup only. The analyst picked "fixed delay, no jitter" as its own choice, while the vault's reliability note says exponential backoff with jitter. So the analyst and architect now check the vault before any default or design choice of their own, and the griller searches it against such choices.
  - Second run: 12 lookups, including the open-questions register. Exponential backoff was settled from `vault:25-Reliability/rel-Reliability-Failover.md`. The numbers the vault doesn't give (base wait, factor, cap) were escalated with proposed values, and the griller flagged dropping the jitter the note asks for.
  - The hook points agents at Read when they ask the knowledge server for a project file, and at the plain path when they pass a `vault:` citation as a path.

## 0.8.3 (2026-10-13)

- **Fewer false escalations in autonomous mode:** the policy approval no longer reads the spec's Skills section. In the first sandbox run, the architect explained why `security` wasn't needed ("no auth, secret or personal data is handled"), and the keyword check escalated a slug-length task as touching auth, secrets and personal data. Requirements, acceptance criteria, architecture and the diff's sensitive paths are still checked.
  - The analyst and architect are told not to name risks to rule them out, since a negated mention still matches elsewhere in the spec.
- **Sandbox: first real task.** After the fix, the runner took a task from spec to a judged commit inside the sandbox in under 2 minutes with a `CLAUDE_CODE_OAUTH_TOKEN`. The agent passed git and the harness hooks through the firewall, and `verify --range` passes on its commit.
  - Git inside the container needs a user name and email. VS Code copies your `~/.gitconfig` into a dev container; with other tools, set them in the workspace.

## 0.8.2 (2026-10-13)

- **Sandbox built and checked for the first time** (OrbStack, Docker 29). The outbound allowlist works: the Anthropic API and GitHub are reachable, everything else is dropped. The hooks block inside the container, and the self-test passes there.
  - **Bug fixed:** the `~/.claude` volume was created owned by root, so Claude Code couldn't write its sessions or settings. The image now creates the folder for the `agent` user before the volume mounts on it.
  - No agent task has run inside the sandbox yet.
- **Subscription credentials:** the sandbox and the `harness-judge.yml` template accept `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) as well as `ANTHROPIC_API_KEY`, so unattended runs and the CI judge can use a Claude subscription instead of per-token billing.
  - `harness-judge.yml` is project-owned: existing projects add the `CLAUDE_CODE_OAUTH_TOKEN` and `HAS_AUTH` lines themselves.
- **Runner:** an agent session that fails at no cost with an error (not logged in, bad API key) stops the run. Before, each task was retried and then escalated with a misleading "no resolution" note. With `--worktree`, the task's branch is removed so the next run retries it.
- **Self-test in CI** on Ubuntu and macOS. The test API stubs no longer resolve their host name on start, which hung on macOS.

## 0.8.1 (2026-10-11)

- **CI workflow templates use current action versions:** `actions/checkout@v7` and `actions/setup-node@v7`, instead of v4, which GitHub runs on a deprecated Node 20 and warns about.
  - `harness-verify.yml` is harness-owned, so `update.sh` replaces it.
  - `harness-judge.yml` is a project-owned template, so existing projects change its two `@v4` lines themselves.

## 0.8.0 (2026-10-09)

Hardening from the first live unattended run, and the last trust gaps in autonomous mode.

- **Found in the live run (1 task, about 85 minutes, ended BLOCKED with no code):** in a folder Claude Code hasn't trusted, `claude -p` ignores the project's hooks, agent hooks and permissions, so the griller's verdict recorder never ran. The agent correctly escalated rather than forge a verdict.
  - `harness.py run` and `ci-judge` now refuse an untrusted workspace, and doctor warns in autonomous mode.
  - The sandbox and the CI judge trust their own workspace.
- **Bug fixed:** `escalate` (and every task-line parser) could match the example task line inside the HTML comment in `3-TASKS.md`. With the usual first task id `1.1`, the BLOCKED note landed on the comment and the real task stayed runnable.
- **Independent CI judge:** `harness.py ci-judge --range` re-judges tasks a pull request finishes with a fresh session (`HARNESS_CI_JUDGE_CMD`), re-runs the tests, and applies the re-derivation rules. There's a project-owned workflow template, `harness-judge.yml`.
- **`harness.py ci-protect`:** requires the `verify` check (and optionally `judge`) on a branch, and creates the `harness-change-approved` label.
- **Assumptions:** the spec template has an Assumptions section. In autonomous mode `approve` refuses a spec whose griller asked questions while Assumptions is empty. The analyst records settled answers with their source and keeps specs proportionate.
- **Out-of-band changes** (autonomous): a snapshot of the protected files is compared after each shell command. Changes made outside the file tools (for example by a script) are logged and the `[WIP]` task is escalated. Restores to the committed version are fine.
- **Runner:**
  - `--worktree [--pr]` runs each task on its own branch, optionally opening a pull request, and `--only <id>` runs one task.
  - `HARNESS_RUN_MAX_COST` sets a per-run budget, using cost and turns from `--output-format json` (now the default `HARNESS_AGENT_CMD`).
- **Sandbox template** `.devcontainer/harness-agent/`: outbound allowlist, trusted workspace, unattended agent command. Untested on this release.
- **Doctor** flags skills not verified within `HARNESS_SKILL_MAX_AGE` days (default 180), or with no `last-verified` date.
- **`harness.py report --json`**, plus agent cost and out-of-band change counts in the report.
- **No `__pycache__`** written into projects.
- **Reading `core.hooksPath` is allowed;** only setting or unsetting it is refused. This false positive was found by a live probe, which also confirmed that in a trusted folder both the project hooks and the agent (frontmatter) hooks load under `claude -p`.
- **Hooks fail closed on time.** A hook Claude Code kills for running too long lets the tool call through. Gate hooks now have their own 25-second budget (settings and agent hook timeouts are raised to 30 seconds), `git` calls time out inside hooks, and a gate that runs out of time refuses the call.
- **Second live run, in a trusted folder: success end to end.** One task went spec → griller (2 passes, 8 minor questions settled as Assumptions) → policy approval → implementer → judge (pass on round 1; tests re-run by the harness) → scribe → `[x]` and committed. That took 21 turns and $6.39. Wall time was 4.8 hours for about 20 minutes of work, because the idle Mac slept; HOOKS.md now recommends `caffeinate -i`.
- **Self-test:** 490 checks.

## 0.7.0 (2026-10-09)

Unattended runs, with CI as the authority.

- **`harness.py run`** (autonomous mode, user or scheduler only): for each ready task (a `[WIP]` one first, BLOCKED ones skipped), it starts a fresh session with `HARNESS_AGENT_CMD` (prompt on stdin).
  - Budgets: `HARNESS_RUN_TASK_TIMEOUT` per session and `HARNESS_RUN_ATTEMPTS` per task.
  - The outcome is read from `3-TASKS.md`: done when `[x]` and committed, otherwise retried and then escalated as `runner`.
  - It honours the kill switch between sessions and keeps a log per session. Agents can't start it.
- **CI workflow** `.github/workflows/harness-verify.yml` (harness-owned): runs `verify --range` on every pull request with the base branch's `scripts/harness/lib` (new `HARNESS_ROOT`), so a pull request can't change its own verifier. In a range, harness changes and user-only setting changes need the `harness-change-approved` label.
- **The lock is protected:** agents can no longer edit `backbone/.harness-lock.json`. Before, the main session could rewrite it to match a modified harness file.
- **Event log** `.git/harness/events.jsonl` (blocks, verify refusals, verdicts, approvals, escalations, run attempts), summarised by `harness.py report`.
- **Self-test:** 441 checks.

## 0.6.0 (2026-10-09)

Autonomous mode: the harness runs without a human in the loop, and the human-only decisions become policy or escalations.

- **`HARNESS_AUTONOMY`** (`supervised` default, or `autonomous`; user-only). AGENTS.md section 7 replaces every "ask the user", and session start announces the mode.
- **Policy approval:** `harness.py approve <id>` writes `Approved-by: policy:low-risk (...; base <commit>; ...)` for a valid, grilled spec only when it is low-risk.
  - **Risk** is deterministic: `HARNESS_RISK_TERMS` in the spec, `HARNESS_RISK_PATHS` it names, or a referenced ADR that isn't Accepted.
  - When the task finishes, the judge gate re-assesses the diff since the base commit: sensitive paths, or more than `HARNESS_RISK_MAX_FILES` files.
  - `harness.py risk <id>` shows the assessment. `HARNESS_AUTO_APPROVE` (`low`/`off`).
- **Escalation:** `harness.py escalate <id> --reason ...` parks a task (`BLOCKED:` note, out of `[WIP]`) and appends to `backbone/escalations.md`, optionally opening a GitHub issue (`HARNESS_ESCALATE_GH`).
  - BLOCKED tasks can't start, and agents can't clear the note or edit the file.
  - The griller's and judge's recorders escalate automatically after `HARNESS_GRILL_MAX_ROUNDS` / `HARNESS_JUDGE_MAX_ROUNDS` fails.
  - `harness.py escalations` lists open entries.
- **Kill switch:** `.git/harness/STOP` refuses every tool call and lets the session end.
- **Stop hook** acts as `block` in autonomous mode.
- **Doctor:** errors on autonomous mode without `HARNESS_TEST_CMD`, or with verify or a gate off.
- **Self-test:** 419 checks.

## 0.5.0 (2026-10-09)

The gates hold no matter how a change is made. A probe of 0.4.2 found that every file-level gate could be bypassed through the shell (`sed -i` on `3-TASKS.md`, `echo Approved-by: >> spec`, a Python one-liner writing a verdict), that `git commit -n` and `core.hooksPath` switched off the git hooks, and that a task marked `[x]` with no spec, grill or judge verdict could be committed.

- **`harness.py verify`:** re-checks the gates on the resulting state, not on the edit.
  - It runs in pre-commit on the staged change, and in CI with `verify --range <base>..HEAD`.
  - It checks that new `[WIP]`/`[x]` tasks passed the start gate, and that finished tasks have a judge pass matching the committed code.
  - It also checks that verdict history is append-only, user-only settings are unchanged, harness enforcement files match the lock, and settings still run the hooks.
  - `HARNESS_VERIFY` (`block`/`off`, user-only) controls it; the user commits a deliberate exception with `HARNESS_VERIFY=off`.
  - `HOOKS.md` has a GitHub Actions example.
- **Shell checks:** commands are split into segments and tokenized instead of matched as raw text.
  - Shell writes to `backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`, `.git/hooks`, `.git/harness` and `.git/config` are refused. This covers redirections, `rm`/`mv`/`cp`/`tee`, `sed -i`, `git rm`, and interpreter one-liners and heredocs; `cd`, `bash -c` and `eval` are followed.
  - Also refused: `git commit -n`, `core.hooksPath` changes, `HARNESS_*=`/`SKIP_BUILD=` from the shell, `+<ref>`/`--mirror`/delete pushes, `find / -delete`, `DELETE` without `WHERE`, and `curl | sh`.
  - `@bash` rules no longer match commit messages or data heredocs, so `git commit -m "docs: why we never drop table"` is allowed.
- **The judge's tests are run by the harness:** on a claimed pass the recorder runs `HARNESS_TEST_CMD` (`HARNESS_TEST_TIMEOUT`, default 900 s) and records `test_run` (exit code, duration, output hash and tail) in the verdict. A failure or timeout turns the pass into a fail, and test evidence in the judge's JSON is ignored. The judge's hook timeout is 1200 s.
- **Recorded passes are re-derived** from their stored evidence by the gates, so a hand-written `{"verdict": "pass"}` does not count.
- **ADR acceptance is the user's:** agents can't set an ADR to `Accepted`, and an accepted ADR is frozen except for being superseded.
- **Orchestrator scope** (`HARNESS_ORCHESTRATOR_SCOPE`, user-only, default `on`): the main session (no `agent_id`) may edit only `backbone/` docs and configuration, `.claude/skills/` and `CLAUDE.md`. Specs, ADRs and code go through the role agents.
- **`SKIP_BUILD=1` is user-only**, like the other escape hatches.
- **Self-test:** 389 checks, up from 314.

## 0.4.2 (2026-10-05)

- **java pack:** test paths now include `src/intTest` (Gradle's common name for an integration-test source set), for the JUnit-assertion rules, the `java-test` route and the `gradle` option's `HARNESS_TEST_PATHS`. The gap was found by the griller in the first live trial.

## 0.4.1 (2026-10-05)

- **Decision layer: `ollama` provider** for a local Jev-style decision endpoint (Ollama's `/v1/systemone`, default model `nimble`).
  - Data stays on the machine and calls are free.
  - `HARNESS_DECISION_URL` overrides the endpoint, and is user-only like the other decision settings.
- **Decision thresholds:** a choice's `warn_if` can use `min_probability`, the probability of the chosen option, besides `min_confidence`. Local Jev-style models report a low confidence even for likely answers.
- **The `claude` provider uses plain HTTPS** (standard library), so there's no SDK to install.

## 0.4.0 (2026-10-05)

The stack is decided in design, not at install; the reviewed skill library from agentic-backbone.

- **Stack-neutral install:** nothing language- or tool-specific is installed or assumed.
  - First-run setup records the stack in an ADR.
  - A **catalog** of stack packs ships inert in `scripts/harness/catalog/`.
  - `harness.py catalog` lists the packs. `harness.py adopt <pack> --adr ADR-NNN --with ... --without ...` adopts them only from an **Accepted** ADR that names them, and only with every pack option decided.
  - Adopted rules and routes are written into the project's `guardrails.conf` and `routing.conf` as blocks citing the ADR, and options set `harness.conf` values.
  - `adopt --remove` undoes an adoption. Updates refresh adopted packs' files. Doctor warns when a pack's ADR is no longer Accepted.
- **Catalog packs** were rewritten against the review findings (Java 25 API fixes, no Spring/Lombok/JPA in examples), with every tool choice conditional on an option:

  | Pack | Skills | Options |
  |---|---|---|
  | `java` | `java`, `java-review`, plus `java-test` via the `junit5-assertj` option | `gradle`/`maven`, `no-lombok` |
  | `quarkus` | `quarkus`, `quarkus-cdi`, `native-test.sh` | `no-spring`, `hexagonal-layers`, `named-use-cases` |
  | `jdbi` | `jdbi` | `no-orm`, `hexagonal-layers`, `flyway` |
  | `container` | `containers`, `container-security` | `podman`/`docker` |

  The rules ported from agentic-backbone's `validate-quarkus.sh` are now pack options.
- **New core skills:**
  - `code-quality`, routed to all source files;
  - `module-testing`, routed to tests, with acceptance-criterion traceability;
  - `security`, covering the OWASP Top 10:2025 and NIST SP 800-63B rev. 4;
  - `changelog`, used on demand.
- **Merged into existing core skills:** `architecture` gains `review.md` (with the driving/driven port labels fixed) and `api-design` gains `compatibility.md` (Deprecation/Sunset headers). Every skill now has a **Linked skills** section.
- **`harness.py scan`:** checks the full content of existing files against the rules (drift). It is reported at session start and by `doctor.sh`.
- **Warning rules for shell commands,** reported after the command runs.
- **commit-msg** warns when the scope matches no staged path.
- **Stop hook** nudges to commit when no task is `[WIP]` and many files have changed.
- **`8-WORKFLOW`** gains commit scope and BREAKING CHANGE rules. The judge loads `code-quality`, `module-testing`, `security` and adopted `*-review` skills.
- **Self-test** enforces the skill format contract: frontmatter first, SKILL.md at most 220 lines, linked skills that exist, and no secret-like literals.

## 0.3.0 (2026-10-04)

The define, build, judge and record pipeline.

- **Specs:** one per task in `backbone/specs/<id>.md` (template `backbone/templates/spec.md`).
  - Numbered requirements `REQ-<id>-<n>` and Given/When/Then acceptance criteria `AC-<id>-<n>`, each linked to its requirements.
  - NFRs, an Architecture section with the governing ADRs (at least one required), Skills, Out of scope, Open questions, and Approval.
  - `harness.py spec-check <id>` reports readiness.
- **ADRs** are files in `backbone/adr/` (template `backbone/templates/adr.md`), and `5-DECISIONS.md` is now their index. The seed includes `ADR-001`.
- **Agents:** `analyst` (spec), `architect` (ADRs, tech requirements, skills), `griller` (adversarial spec review), `implementer` (code and tests), `judge`, `scribe`. Analyst, architect, implementer and scribe each have a hook-enforced write scope. `planner` is removed.
- **Start gate:** a task becomes `[WIP]` only with a valid spec, a griller pass on the current spec and ADRs (spec and ADR fingerprint), and the user's `Approved-by:` line. Agents can't write approval lines, and approved specs are frozen.
- **Skill gate:** before editing a file, an agent must have loaded (read or invoked) every skill routed to its path in `scripts/harness/routing.core.conf` and `backbone/routing.conf`. For code during a task, it also needs the skills the spec lists. This is tracked per session in `.git/harness/sessions/`.
- **Judge gate** now judges against the spec. Every AC must be evaluated as met, list its tests, and be mentioned in a test file (`HARNESS_TEST_PATHS`). Tests must be reported `passed`.
- **Harness skills** in `.claude/skills/`: `requirements-writing`, `adr-writing`, `architecture`, `api-design`, `openapi`.
- **New user-only settings:** `HARNESS_SPEC_GATE`, `HARNESS_SKILL_GATE`; plus `HARNESS_TEST_PATHS`.
- The task format is now one line per task, `- [ ] **Task <id>: <title>** (spec: ...)`. The steps and "Done when" lists move into the spec.
- **Upgrade notes from 0.2.0:**
  - Verdict files are now named `<id>.judge.json` and `<id>.grill.json`. Old `<id>.json` files are ignored.
  - A task already `[WIP]` keeps going, but finishing it needs a spec with acceptance criteria and a judge pass. Otherwise the user finishes it or switches `HARNESS_JUDGE_GATE` off.
  - Add `HARNESS_SPEC_GATE` and `HARNESS_SKILL_GATE` to `harness.conf` to make them explicit; both default to on.
  - `routing.conf` and `adr/ADR-001` are created by the update.

## 0.2.0 (2026-10-04)

Agent roles and the judge gate.

- New harness-owned agents in `.claude/agents/`:
  - `planner`: read-only; drafts tasks with "Done when" criteria.
  - `judge`: independent review that returns a structured verdict.
  - `scribe`: writes decisions and memory; a scoped hook limits it to `5-DECISIONS.md` and `6-MEMORY.md`.
- Judge gate: finishing a `[WIP]` task requires a current pass verdict.
  - The judge's scoped Stop/SubagentStop hook records each verdict in `backbone/.verdicts/<task>.json`, with a fingerprint of the code (git tree hash excluding `backbone/`).
  - A claimed pass is recorded as a fail if the judge's own evidence shows an unmet criterion, a blocker or major finding, or failed tests.
  - Rewording or deleting a task line counts as finishing it; reverting to `- [ ]` abandons it.
  - After `HARNESS_JUDGE_MAX_ROUNDS` fails, the agent is told to escalate to the user.
  - Agents can't write verdicts or change `HARNESS_JUDGE_*`.
- New task format: tasks are list lines (`- [ ] **Task <id>: ...**`) with nested "Done when" and steps. `[WIP]` goes on task lines only.
- `doctor.sh` checks the judge configuration.
- **Upgrade note:** the gate is on by default for updated projects too. Existing tasks need "Done when" criteria before the judge can pass them. To finish old tasks without review, set `HARNESS_JUDGE_GATE="off"` in `backbone/harness.conf` yourself.

## 0.1.0 (2026-10-04)

First release. Extracted from `agentic-backbone` as a stack-agnostic core.

- `bootstrap.sh` / `update.sh`: install into any repo root, with hash-tracked updates, conflict files, `--dry-run`, `--force`, and `status`.
- Settings merge: only harness hook entries are replaced; custom hooks, permissions and other settings are kept.
- Git hooks via `core.hooksPath`, so they work in worktrees and nothing is copied into `.git/hooks`.
- A single Python runtime for all hooks, using the output formats Claude Code reads:
  - Blocks go through exit 2 with the reason on stderr.
  - Feedback goes through `additionalContext`.
  - The Stop hook uses `systemMessage`, or `decision: block` guarded by `stop_hook_active`.
- Guardrail rules in a data file (`guardrails.conf`), with core rules for destructive commands and secrets.
- The WIP check matches task lines only. A second `[WIP]` task is refused at edit time.
- Session start reports unfinished setup (FILL placeholders), the open WIP task and harness errors in a few lines.
- `doctor.sh` health check.
