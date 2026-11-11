# ADR-004: Traceability export from the receipt's evidence: ReqIF, needs.json and an HTML matrix, derived and one-way

## Status
Accepted

## Date
2026-11-07

## Context
The harness already records a full trace for every task, spread over several files:

- The spec (`backbone/specs/<task>.md`) numbers the requirements (`REQ-<task>-<n>`) and acceptance criteria
  (`AC-<task>-<n>`), and each criterion names the requirements it proves. With `HARNESS_REQ_STYLE=ears`, requirements
  follow an EARS pattern, and an NFR that a criterion proves gets an id (`NFR-<task>-<n>`).
- The judge gate accepts a pass only when every criterion is met and a test file mentions its id, and only after the
  harness has run the test command itself.
- Verdicts in `backbone/.verdicts/` carry fingerprints. The grill's is a hash of the spec and its ADRs. The judge's and
  the reviewers' is the git tree hash of the code without `backbone/`.
- Git holds the commits, and `verify --range` already ties a commit to a code fingerprint (`tree_fingerprint`).

`harness.py receipt <id>` turns that evidence into text, for one judged task, in its pull request. Regulated teams
need the same chain across tasks, in a form their tools read: requirement → acceptance criterion → test → verdict →
commit.

The research note [Agent-SDLC landscape](../research/2026-11-agent-sdlc-landscape.md) (Spaces 1 and 2, next steps 3
and 4) compared the options:

- The QMS and ALM products (Ketryx, Jama, Polarion, codebeamer, Greenlight Guru, Matrix) model process state, not
  verdicts fingerprinted to code. None publishes a PCI DSS attestation. Syncing to one would create a second system
  of record and a new data flow.
- Two open formats cover the need without a vendor: OMG ReqIF 1.2, which Jama, Polarion, codebeamer and DOORS import,
  and the `needs.json` file of Sphinx-Needs, a docs-as-code tool with no SaaS.

The constraints:

- The engine is Python 3.8 or later, standard library only.
- `backbone/` and git are the audit trail.
- The `triple` pilot (Disputes, under a PCI DSS framing) sends nothing to a SaaS.
- The code fingerprint counts every file outside `backbone/` that git doesn't ignore, untracked ones included.

## Decision
`harness.py trace export` writes a **derived, one-way, non-authoritative** view of the trace chain.

- `backbone/` and git stay the system of record. The export reads them, and nothing reads the export back.
- It makes no network call, needs no account and adds no dependency to the engine or to any gate.

### Command (v1)

```
harness.py trace export --format reqif|needs|html [--out DIR] [--task ID]
```

- It exports every task that has a spec in `backbone/specs/`, or only `--task ID`. A task without a spec is refused.
- Without `--out`, the document goes to stdout. With `--out DIR`, it goes to `DIR/traceability.reqif`,
  `DIR/needs.json` or `DIR/traceability.html`.
- An `--out` inside the repository is refused unless git ignores the file, and so is stdout redirected to such a file
  (`> trace.html`). An untracked file there counts as code, so writing it would make every judge pass stale. The
  refusal goes to stderr, so it can't land in the file. CI writes to the runner's temporary folder and keeps the file
  as a build artifact.
- The output depends only on the repository's state and its committed `backbone/harness.conf`: no clock and no
  randomness. The settings it reads are `HARNESS_REQ_STYLE`, `HARNESS_TEST_PATHS` and `HARNESS_PROJECT_NAME`, from that
  file, never from environment overrides; an unnamed project is called `unnamed project`, not after its folder. The
  same commit and working tree give the same bytes on any machine, so anyone can regenerate an export and compare.
- Timestamps come from the data. The document's time is the committer date of `HEAD`; verdict times are the
  recorded ones.

### What is exported
| Harness item | Id, the same in all three formats | ReqIF | needs.json |
|---|---|---|---|
| a task's spec | `TASK-<task>` | a `SPECIFICATION`; its hierarchy holds the task's objects | need of type `task` |
| requirement `REQ-<task>-<n>` | unchanged | `SPEC-OBJECT` of type Requirement | need of type `req` |
| NFR with an id, `NFR-<task>-<n>` | unchanged | `SPEC-OBJECT` of type Requirement (`Harness.Kind` NFR) | need of type `req` (`harness_kind` NFR) |
| acceptance criterion `AC-<task>-<n>` | unchanged | `SPEC-OBJECT` of type Acceptance criterion | need of type `ac` |
| a test file that mentions an AC id | `TEST-<task>-<first 12 hex digits of the SHA-256 of its path>` | `SPEC-OBJECT` of type Test | need of type `test` |
| a criterion proves a requirement (the spec's `(REQ-…)` list) | | `SPEC-RELATION` Verifies, from the AC to the requirement | link field `verifies` |
| a test file mentions a criterion | | `SPEC-RELATION` Tests, from the test to the AC | link field `tests` |
| verdicts, fingerprints, commits | | string attributes `Harness.*` | fields `harness_*` |

- **Ids.** Requirement, NFR and criterion ids are the spec's own, unchanged in every format (`ReqIF.ForeignID`, the
  need's `id`, the HTML row). An auditor can search for them in the spec, the tests, the verdicts and the receipt.
  - Task ids use only `A-Z a-z 0-9 . _ -`, so every id is a valid XML ID.
  - A test's id comes from its path, so it stays the same across exports while the file keeps its name.
  - The other ReqIF identifiers (types, attribute definitions, relations, hierarchy nodes) are derived the same way,
    never random, so importing a newer export can update the objects an earlier one created.
- **Text.** Requirement and criterion text is exported as the spec writes it on the item's line, without the
  criterion's leading `(REQ-…)` list and without control characters that XML can't carry. An NFR without an id is
  exported as text on its task, marked untraced: nothing can prove it.
- **Judge verdict.** The task's latest judge verdict is one of:
  - *pass on the current code*: its fingerprint equals the working tree's;
  - *pass on earlier code*;
  - *fail*;
  - *not judged*.

  It comes with its time, its code fingerprint and the harness's own test run: the command, exit code, seconds and
  SHA-256 of the output. Each criterion is *met*, *not met* or *not evaluated*, with the judge's evidence and test
  names.
- **Commits.** A verdict links to every commit reachable from `HEAD` whose tree, without `backbone/`, hashes to the
  verdict's fingerprint. This is the definition `verify --range` uses (`tree_fingerprint`). With the full history, no
  commit means the judged code was never committed exactly as judged, but only when git can read the whole history.
  A shallow clone (`actions/checkout` fetches depth 1 by default) holds only part of it. So do a git call that times
  out or fails, and trees git can't read (their objects are missing, as in a partial clone whose remote is gone). When
  the judged commit isn't found and the history may hold it, the gap reads `history incomplete` and says how to restore
  the history (`git fetch --unshallow`, or `fetch-depth: 0` in CI, as `harness-verify` already does; the objects of a
  partial clone from its remote), and the export doesn't claim the code was never committed. A commit found in a
  shallow clone is no gap.
- **Test files.** These are the files that match `HARNESS_TEST_PATHS` and mention the criterion's id, in the code the
  latest judge verdict judged: the working tree when that is the current code, otherwise a commit that carries it.
  They are unknown when no commit does. A task without a judge verdict shows the working tree's.
- **Spec fingerprint.** The export gives the current one (`spec_fingerprint`: the spec without its Approval section,
  plus its ADRs) and whether the latest grill verdict was recorded on it.
- **Also per task**:
  - its status in `3-TASKS.md`, its title and its Change-Class;
  - the `Approved-by:` lines;
  - the latest review per lens, and whether it reviewed the judged code;
  - the gaps: requirements without a criterion, criteria not met or without a test file, references to requirements
    the spec doesn't define, untraced NFRs, findings the judge left open, and a pass that isn't on the current code.

### Formats
- **ReqIF 1.2** (OMG `formal/16-07-01`):
  - It is written with `xml.etree`, in the namespace `http://www.omg.org/spec/ReqIF/20110401/reqif.xsd` that ReqIF
    1.0.1 to 1.2 share, with `REQ-IF-VERSION` `1.0`, the value the schema fixes.
  - It uses one string datatype, the attribute names of the ReqIF Implementation Guide where they fit
    (`ReqIF.ForeignID`, `ReqIF.Name`, `ReqIF.Text`) and `Harness.*` for the rest.
  - ReqIF has no notion of a test result, a verdict or a code fingerprint. They are plain strings whose meaning this
    ADR defines.
  - The tests check the output against the schema's required elements and attributes, element order, references and
    id rules, with a minimal check vendored from `reqif.xsd`. They download nothing.
- **Sphinx-Needs `needs.json`, format 1**:
  - This is the released layout: `project`, `current_version`, and `versions.<version>.needs` keyed by id, with
    `needs_amount` and `creator`. It isn't the experimental `2a1` layout.
  - It has no `created` stamp, as with `needs_reproducible_json`. The version is the `HEAD` commit.
  - To import it with `needimport`, a Sphinx project declares the need types `task`, `req`, `ac` and `test`, the link
    options `verifies` and `tests` and the `harness_*` fields, and sets a `needs_id_regex` that accepts dots and
    dashes.
  - Sphinx-Needs (Python 3.11 or later) stays outside the engine: the harness only writes JSON.
- **HTML matrix**:
  - One self-contained file: inline CSS, no script, no external resource. Every string from the spec or the verdicts
    is escaped.
  - A section per task gives its verdict, commits, test run, grill, approval and reviews. A row per requirement and
    criterion gives the requirement, the criterion, the test files, the judge's result and the commits that carry the
    judged code. The gaps follow.
  - CI can attach it to a pull request as an artifact.

### EARS specs (`HARNESS_REQ_STYLE=ears`)
- A requirement's text is its EARS sentence, and its pattern is exported with it (`Harness.EARSPattern`,
  `harness_ears_pattern`, a column in the HTML matrix). The patterns are ubiquitous, event-driven, state-driven,
  unwanted behaviour, optional feature and complex, read from the leading When, While, If … then and Where clauses.
  A requirement without the shape spec-check requires (`… the <system> shall …` after those clauses) is exported as
  *not an EARS pattern*. Spec-check's other EARS rules, such as untestable words, don't change the pattern.
- NFRs with ids are requirement objects, and the criteria that prove them link to them. Plain style does the same
  when a spec gives NFR ids; EARS is where they are expected.
- The Given/When/Then criteria stay the evidence layer, as `requirements-writing/ears.md` says. In plain style no
  pattern is exported.

### What regulated users can and cannot claim (the `triple` Disputes/PCI pilot)
For the commit an export was made at, they can show:

- which criteria prove each requirement, which test files mention each criterion, and what the judge recorded for
  each criterion, when, and on which code;
- that the harness ran the test command itself (exit code, output hash), whether the spec was grilled on its current
  text, and the `Approved-by:` lines;
- which commits carry exactly the judged code, so a reviewer can check out that commit and regenerate the same export;
- every gap the harness can see, listed rather than left out.

They cannot claim:

- **A record.** The export is a copy. It isn't signed, and anyone can edit the file. Where it disagrees with
  `backbone/` and git, those win: regenerate it from the commit instead of trusting a file.
- **That the requirement text is the ticket's.** The requirements and criteria are the spec's, in `backbone/specs/`.
  The `triple` pilot names Linear as its system of record (`catalog/triple/`), and its Analyst writes the spec from the
  ticket, but the export traces the spec's text. A change to the ticket changes nothing here until the spec changes.
- **That an earlier pass covers the current code.** A pass on earlier code says nothing about the code since.
- **Independent or qualified verification.** The judge is an agent. The harness checks its claims mechanically (a
  test file names the AC, and the tests pass), but that doesn't show that the test exercises the behaviour.
- **Electronic records or signatures** (21 CFR Part 11, EU GMP Annex 11). `Approved-by:` is a line in git, not a
  signature. Signing verdicts is a separate decision.
- **A validated system** (GxP computerised-system validation, IEC 62304 tool qualification). Neither the harness nor
  the export is validated, and a team that imports the export into a validated eQMS owns validating that import.
- **PCI DSS evidence.** The pilot keeps PCI surfaces parked (`disputes-pci`), and the `harness-agent` devcontainer is
  not an attestation. The export covers the non-PCI work the pilot does and is not a PCI DSS control. It stays
  local: where it is uploaded is the user's choice, and that destination is a data flow to review.
- **A round trip.** What an ALM tool changes after an import doesn't come back.

## Alternatives considered
- **Integrate a QMS or ALM product** (Ketryx `POST /builds`, Jama REST, Polarion): a second system of record,
  credentials in CI and a new subprocessor. None of them publishes a PCI attestation or models fingerprinted
  verdicts. A one-way adapter stays possible later, for med-device profiles only (research next step 9).
- **OSLC**: linked-data REST with RDF containers and tracked resources. It is too heavy for a standard-library CLI
  and needs a server.
- **Python libraries** (`reqif`, Sphinx-Needs, StrictDoc): a runtime dependency, and two of them need Python 3.10 or
  3.11. The formats are small enough to write directly.
- **Committing the export into the project**, as the research suggested: outside `backbone/` it changes the code
  fingerprint and so makes every judge pass stale; inside `backbone/` it puts a derived, non-authoritative file into
  the record. It can be regenerated at any commit, so it isn't committed.
- **Exporting from the receipt** (`receipt <id> --format …`): the receipt exists only for a judge pass on the current
  code, so a project-wide export would leave out every task finished before. The export shares the receipt's evidence
  and helpers instead, and says for each task whether its pass is current.
- **ReqIF enumerations for results** instead of strings: better filters in some tools, but more importer edge cases.
  Strings come first.

## Consequences
- **Easier**:
  - A regulated reviewer gets requirement-to-commit traceability in a standard file their tools import, without a
    vendor, an account or an upload.
  - A pull request can carry a readable matrix, and an auditor can regenerate it from any commit.
- **Harder**:
  - The `Harness.*` attributes and `harness_*` fields are a format of their own. Changing them is a change to this
    ADR, and tools that imported older exports see new attributes.
  - Importers differ: a ReqIF file that meets the schema can still need a mapping in a given tool.
- **Unchanged**:
  - The gates, verdicts, receipt and `verify` don't read the export. Deleting it changes nothing.
  - `harness.py trace <id>` still prints a task's events.
- **v1 (this change)**: `trace export` with the three formats as described, and tests through the command in
  throwaway repositories: the ReqIF output against the vendored minimal schema check, the `needs.json` shape, the
  HTML matrix, EARS specs, determinism (folder name and environment overrides), the `--out` and stdout guards, the
  shallow-clone gap, and one fingerprint per `state` or `next` command.
- **Follow-up work**, each as its own change:
  1. A `harness-verify` step that writes the HTML matrix with the base branch's engine, so a pull request can't change
     the exporter that describes it, and uploads it as an artifact.
  2. Posting a link to the matrix in the pull request and on its Linear ticket.
  3. `.reqifz` with the receipt attached, and ReqIF enumerations for results.
  4. Signed exports, once verdicts are signed.
