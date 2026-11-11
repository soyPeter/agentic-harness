# Harness Hooks and Gates

Harness-owned. All hook logic lives in `scripts/harness/lib/harness.py`, which needs `python3` and `git`.

## Claude Code hooks (`.claude/settings.json`)

| Event | Tools | What it does | Effect |
|---|---|---|---|
| SessionStart | all | Shows the reading list, SETUP INCOMPLETE if FILL placeholders remain, the `[WIP]` task, and harness errors | Added to context |
| PreToolUse | Bash | **Shell checks** (below) and `@bash` block rules: destructive git, recursive root/home delete, DROP/TRUNCATE, `--no-verify` | Command refused |
| PreToolUse | Write, Edit, MultiEdit | Block rules for the path, the **orchestrator scope**, the **skill gate**, plus per file (see below) | Edit refused |
| PreToolUse | every other tool except Read, Grep, Glob, LS and TodoWrite | Its **tool contract** (below): the file gates for the paths a write tool names, `confirm` and unknown tools refused in autonomous mode | Call refused, or a warning |
| PostToolUse | Read, Skill | Records which skills the session has loaded (for the skill gate) | Silent |
| PostToolUse | Write, Edit, MultiEdit | Warn rules; harness-owned file edited; spec readiness after a spec edit | Added to context |
| PostToolUse | other tools with a non-read contract | Logs a `tool` event with the tool's class and paths | Silent |
| PostToolUse | Bash | `@bash` warn rules (discarding changes, force branch delete, amend, ...); after a fresh `git commit`: task log touched, ADR format, TODO stubs, WIP left | Added to context |
| Stop | n/a | If a task is still `[WIP]`: `remind` shows a one-line note; `block` makes the agent address the DoD once. With no `[WIP]`, a commit nudge once `HARNESS_COMMIT_NUDGE` tracked files are changed | Per `HARNESS_STOP_MODE` |

Session start and `doctor.sh` also run a **scan**: every file rule against the full content of tracked and untracked files. Rules otherwise only see added text, so the scan finds violations that already existed (drift). Session start names files with blocking violations so agents don't copy those patterns; `python3 scripts/harness/lib/harness.py scan` lists them all.

Per-file checks in PreToolUse:

| File | Checks |
|---|---|
| `backbone/3-TASKS.md` | One `[WIP]` at a time; **start gate** for a new `[WIP]`; **judge gate** for finishing one |
| `backbone/specs/*.md` | `Approved-by:` lines are user-only; an approved spec is frozen |
| `backbone/adr/*.md` | Only the user sets an ADR to `Accepted`; an accepted ADR is frozen except for being superseded |
| `backbone/harness.conf` | The gate switches, `HARNESS_JUDGE_MAX_ROUNDS`, `HARNESS_VERIFY`, `HARNESS_ORCHESTRATOR_SCOPE` and the decision-layer keys are user-only |
| `backbone/.verdicts/*` | Never writable by agents |
| `backbone/.harness-lock.json` | Written only by the installer and `harness.py adopt` |
| `backbone/escalations.md` | Written by `harness.py escalate`; resolved by the user |
| `backbone/tools.conf` | The tool contracts are user-only; verify also refuses commits that change them |

**Orchestrator scope** (`HARNESS_ORCHESTRATOR_SCOPE`, user-only, default `on`): the main session (a tool call without an `agent_id`) may edit only `backbone/` docs and configuration (not specs, ADRs or verdicts), `.claude/skills/` and `CLAUDE.md`. Specs, ADRs and code are written by the role agents.

**Shell checks.** A command is split into its segments (`;`, `&&`, `|`, newlines) and tokenized, so the checks see the program that runs and its arguments, not text that only mentions a command. `@bash` rules don't see commit or tag messages or the bodies of data heredocs (`cat > notes.md <<EOF`). Refused:
- Shell writes, moves and deletes in `backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`, `.git/hooks`, `.git/harness` and `.git/config`: redirections, `rm`/`mv`/`cp`/`tee`/`touch`/`chmod`, `sed -i`/`perl -i`, `git rm|mv`, and `python -c`/`node -e` or interpreter heredocs that write there. Every gate is enforced on the file tools, so these changes go through Write or Edit. `cd` and `bash -c`/`eval` are followed.
- Bypasses: `git commit -n`, `git -c core.hooksPath=...`, `git config core.hooksPath`, and setting `HARNESS_*` or `SKIP_BUILD` from the shell (those are the user's, in their own terminal).
- `git push` with a `+<ref>`, `--mirror` or a branch delete; `find / ... -delete`; `DELETE` without `WHERE` sent to a SQL client; `curl ... | sh`.

**Tool contracts** (`backbone/tools.conf`, user-only). Every tool that can change something goes through the gate, not only Bash and the file tools. A contract line is `<tool or pattern>... <class> [path=<input field>] [confirm]`, with class `read`, `write`, `exec`, `network` or `agent`; patterns are shell-style (`mcp__github__*`).
- A `write` tool's paths (the `path=` fields of its input) get the same gates as Write and Edit: harness files (`backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, ...) are refused outright, and other paths go through the agent's write scope, the orchestrator scope, the skill gate and the block rules. A write tool whose contract names no path field is refused in autonomous mode, since the gates can't see what it writes.
- A `confirm` tool is refused in autonomous mode; in supervised mode Claude Code's own permission prompt asks the user.
- A tool with **no contract** runs with a warning in supervised mode and is refused in autonomous mode. Each use is logged as `tool-unknown`, and `harness.py report` lists the tools still without a contract.
- The agents' own tools (Write, Edit, NotebookEdit, Bash, WebFetch, Task, ... and the Codex and OpenCode names) have built-in contracts that `tools.conf` can't change, so `NotebookEdit read` doesn't open `backbone/` to notebook edits.

Claude Code skips the hook for Read, Grep, Glob, LS and TodoWrite, so the reads that make up most calls cost nothing. Codex sends Bash, `apply_patch` and MCP tools; OpenCode's plugin sends every call.

### Hooks scoped to agents (`.claude/agents/*.md` frontmatter)

| Agent | Event | What it does |
|---|---|---|
| `analyst`, `architect`, `implementer`, `scribe` | PreToolUse | Write scope: analyst may edit specs and the PRD; architect ADRs, the ADR index, `2-PLANNING.md` and specs; scribe `6-MEMORY.md`, ADRs and the index; implementer anything except `backbone/`, `.claude/` and harness files |
| `griller` | Stop (as SubagentStop) | Records the grill verdict with the spec fingerprint in `.verdicts/<id>.grill.json`. It marks each non-blocker that carries a recommendation `apply`, so that question is applied without being asked |
| `judge` | Stop (as SubagentStop) | Records the judge verdict with the code fingerprint in `.verdicts/<id>.judge.json` |

Both recorders take the verdict JSON from the agent's final message, falling back to the transcript. If there is no valid JSON, they send the agent back once. A claimed pass is **re-derived** from the agent's own evidence and the files before it is recorded, as described below. Project subagents and their hooks only load once Claude Code trusts the project folder.

## The gates

### Start gate (`HARNESS_SPEC_GATE`)

A task line may become `[WIP]` only when all of these hold. Check them with `python3 scripts/harness/lib/harness.py spec-check <id>`.

1. **Spec valid:**
   - It has at least one requirement `REQ-<id>-<n>`.
   - Every acceptance criterion `AC-<id>-<n>` is Given/When/Then and references existing requirements, and every requirement has an acceptance criterion.
   - The Architecture section references at least one existing ADR, with status Accepted or Proposed and all its sections filled.
   - The Skills section lists existing skills.
   - `Change-Class:`, when present, is exactly one of `docs`, `refactor`, `feature`, `schema` (any case), and only one value is declared. Without it the spec counts as `feature`. The line is read only outside the Approval section, the part the grill fingerprint covers and approval freezes, so it is part of what the griller and the user passed. A line in a comment or a fenced code block is a note or an example, not the declaration.
   - `## Approval` is a heading at column 0, on a line of its own, outside HTML comments and fenced code blocks. Its section runs to the next heading of level 1 or 2 (`#` or `##`), and so does every section the gates read (Skills, Open questions, Assumptions and the rest), cut the same way. Code blocks are read as Markdown reads them: a fence opens at column 0 with ``` or ~~~ and closes with a run of the same character at least as long, at 0-3 spaces with nothing after it. A comment that starts at column 0 runs to its `-->`, as an HTML block does, across lines; `<!-->` and `<!--->` are whole, empty comments, as in CommonMark 0.31; neither a comment nor a fence starts inside the other. A heading or fence that is indented, follows a list or quote marker, or sits in an HTML block is refused, since a reader may take it for text or code: keep it at column 0 outside HTML blocks. HTML blocks start and end as CommonMark says: a `<?`, `<!X` or `<![CDATA[` block runs to its `?>`, `>` or `]]>`, blank lines included; `<pre>`, `<script>`, `<style>` and `<textarea>` run to their closing tag and interrupt a paragraph; a block-level tag runs to a blank line; a block in a list item or quote ends with the item or quote, so a `<pre>`, `<script>`, `<style>`, `<textarea>`, `<?`, `<!X` or `<![CDATA[` block there is refused; a complete tag alone on its line runs to a blank line but can't interrupt a paragraph, so an autolink or a tag followed by text is plain text. A `***` or `___` thematic break ends the paragraph above it, so a tag alone on the next line starts a block. A tag alone on the line right after a list or quote paragraph, or after a paragraph that starts with `[` (a reader may take it for a link reference definition), is refused, since a reader may take it for a block. Line endings are read as LF, in the file and in the text a hook proposes, so a lone CR can't start a section. A blank line holds only spaces and tabs, as CommonMark has it: a line of a non-breaking space or another Unicode space is text, so it keeps an HTML block open and a line before a setext underline is text. A vertical tab, form feed, NEL, or Unicode line or paragraph separator anywhere makes the spec invalid, since a reader may take it for a line end. An unusual space or control character (a control character, or a Unicode space or invisible character such as a non-breaking space) on a line with a `<` or `#`, or that starts with a fence marker of 3 backticks or tildes, makes the spec invalid too, since a reader may take it for a space that starts a tag, heading or fence; elsewhere it is text, inline code included. A setext heading (text over a line of `=` or `-`, in a list or quote too) is refused; write `## Title`. A heading inside a comment or a code block, or one that only reads as a heading once a comment on its line is removed, makes the spec invalid. So does a fence marker indented 4 or more columns, or with a tab, and a comment that doesn't start at column 0 and doesn't close on its line (a comment in a list item ends with the item). Indent an example's heading inside its code block to show it. An `Approved-by:` line in a code block is an example, not an approval. Approval lines are read with comments blanked out, the same way for the approval check and the write guard, so an agent can't write one behind a comment or move one into the Approval section.
   - Open questions is `- none`, and there are no FILL, TODO or TBD markers.
2. **Grill pass on the current spec.** The fingerprint covers the spec text outside the Approval section (all of it, when the spec is refused for how a reader reads it) and every referenced ADR, so changing either makes the pass stale. A pass is recorded as a fail if any blocker or major question is open, or if the spec is invalid.
3. **User approval:** an `Approved-by:` line under `## Approval`. Only the user can write it. Once it is there, agents can't change the spec outside its Approval section, whichever section follows it.

**Light lane** (`HARNESS_LIGHT_LANE`, user-only, default `off`). A task the user marks `(light)` on its line in `3-TASKS.md` skips the architect and step 2 when its spec has at most `HARNESS_LIGHT_MAX_ITEMS` requirements plus criteria (default 3) and is low-risk (`harness.py risk`), not counting the `feature` class: the user's mark is enough for feature work, which the user approves anyway. A `Change-Class: schema` task never takes the lane. The spec must still be valid (step 1) and approved (step 3; `approve` in autonomous mode), and the judge gate and verify apply as usual. Starting a light task records the commit it started from (`backbone/.verdicts/<id>.light.json`). Finishing counts every file changed since then, committed or not (a moved file at both its old and its new path), and refuses a light task that changed more than `HARNESS_LIGHT_MAX_FILES` files (default 3) or touched a sensitive path: the user removes the mark and the task is grilled. A task marked `(light)` after it started has no recorded start and can't finish as light. A `(light)` task that doesn't qualify goes through the griller, and the start gate says why. Only the user adds the mark: agents' edits that add it are refused, and so are commits that add it (verify).

### Skill gate (`HARNESS_SKILL_GATE`)

Before an agent edits a file, it must have loaded, in the same session, every skill routed to that path (`routing.core.conf` and `backbone/routing.conf`). For code while a task is `[WIP]`, it also needs the skills listed in the spec. "Loaded" means it read `.claude/skills/<name>/SKILL.md` or invoked the skill. The refusal message lists the missing skills. Paths under `backbone/`, `.claude/` and `scripts/harness/` only need their routes.

### Judge gate (`HARNESS_JUDGE_GATE`)

Taking a task out of `[WIP]`, other than reverting it to `- [ ]` with the same text, requires a latest judge verdict of **pass** whose code fingerprint equals the current code. The fingerprint is the git tree hash of the working tree, excluding `backbone/`.

A judge pass is recorded as a fail unless all of these hold:
- Every AC in the spec was evaluated as met, with tests listed.
- Every AC id appears in at least one test file (matching `HARNESS_TEST_PATHS`, outside `backbone/`).
- There are no blocker or major findings.
- Tests were reported `passed`.
- **The harness ran the tests itself.** When the judge claims a pass, its recorder runs `HARNESS_TEST_CMD` (timeout `HARNESS_TEST_TIMEOUT`, default 900 seconds) and records the exit code, duration, output hash and tail in the verdict as `test_run`. A non-zero exit or a timeout turns the pass into a fail. Test evidence in the judge's own JSON is ignored.

Gates re-derive a recorded pass from its stored evidence before trusting it, so a hand-written `{"verdict": "pass"}` does not count.

After `HARNESS_JUDGE_MAX_ROUNDS` consecutive fails, the agent is told to escalate to the user.

The user can always act directly. Hooks only see agent edits, so the user can edit `3-TASKS.md` or a spec themselves, or switch a gate off in `harness.conf`. To commit such a deliberate exception, they use `HARNESS_VERIFY=off git commit ...` (see verify below).

## Verify (`HARNESS_VERIFY`)

The hooks guard edits made through the tools. `harness.py verify` checks the **resulting state**, so it also catches changes made any other way. It runs in the pre-commit hook on the staged change, in the pre-push hook on the commits being pushed, and in CI on a range of commits:

- Every task that became `[WIP]` or `[x]` passes the start gate: valid spec, current grill pass, user approval.
- Every task that became `[x]` has a judge pass whose fingerprint equals the committed code (in CI, the code of the commit that marked it done), and the pass holds up when re-derived.
- With `HARNESS_REVIEW` on, every task that became `[x]` also has a pass from each review lens (correctness, structure, lean) on that same code.
- At most one `[WIP]` task (unless `HARNESS_ALLOW_PARALLEL_WIP="1"`).
- Verdict history is append-only.
- User-only settings in `harness.conf` are unchanged.
- Harness enforcement files (`scripts/harness/`, `.claude/agents/`) match `backbone/.harness-lock.json`, and `.claude/settings.json` still runs the harness hooks.
- In a range, `harness-attest.pub` (the public key the attest job trusts, ADR-005) is unchanged: it counts as an enforcement file. Agents may not write it either: the implementer's scope and the shell and code checks of the hooks refuse it.
- A moved file counts at both its old and its new path, so moving one of these files away is a change to it.

`HARNESS_VERIFY` is `block` (default) or `off`, and user-only. The user commits or pushes a deliberate exception with `HARNESS_VERIFY=off git commit ...` (or `git push`); agents can't set it.

**CI** is the authoritative copy of this check, because nothing in an agent's session can switch it off. The harness installs `.github/workflows/harness-verify.yml`, which on every pull request:
- takes `scripts/harness/lib` from the **base branch** and runs it against the pull request's checkout (`HARNESS_ROOT`), so a pull request can't change the verifier that checks it;
- runs `verify --range origin/<base>..HEAD`;
- when that passes, writes the traceability matrix (`trace export --format html`) with the same base-branch engine and uploads it as the `harness-traceability` artifact, so a pull request can't change the exporter that describes it. An engine from before `trace export` writes none, with a warning; the check doesn't depend on it.

In a range, any change to the harness itself (enforcement files, the lock) or to user-only settings fails. The only way through is the `harness-change-approved` label, which the workflow turns into `--allow-user-changes`. Make the check required in branch protection, and restrict who may label pull requests.

**Signed verdict attestation** (optional, the harness's ADR-005). `harness.py attest --range <base>..<tip> [--allow-user-changes]` prints an unsigned in-toto Statement (predicate type `https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1`) about the tip commit and its code tree without `backbone/`. It names the engine that made it and the release the base commit's lock pins, the range, the flag and every harness setting it resolved (its value, and whether the environment set it), and, for each task finished in the range, the commit that finished it, the spec's fingerprint and approval lines, the Change-Class, the latest grill, judge and review verdicts, the receipt's risks, suggested labels and verified / not-verified lists. It runs the checks of `verify --range` and prints nothing (exit 1, verify's problems on stderr) when they fail, and it refuses a checkout that isn't the tip with a clean working tree. The same commits, settings and engine give the same bytes.

The `attest` job of `harness-verify.yml` runs on a push to the default branch, not on pull requests. With the secrets `HARNESS_ATTEST_KEY` (a cosign private key, `cosign generate-key-pair`) and `HARNESS_ATTEST_PASSWORD`, it writes the statement for the pushed range with the engine the push starts from (the default branch's previous tip; a first or forced push, or a previous tip with neither a harness nor a thin pin, gets no statement, and the job never takes the engine from the tip), signs it with cosign 3.1.4 (downloaded and checked against its SHA-256), sending nothing to a transparency log, and uploads the statement and its Sigstore bundle as the `harness-attestation` artifact. It then writes the traceability export as a `.reqifz` with the same engine, signs it with the same key (`cosign sign-blob`) and uploads both as the `harness-traceability-signed` artifact; an engine without the `.reqifz` export signs nothing, with a warning, and the verdict attestation stays. Set up first:
1. Commit the public key as `harness-attest.pub` on the default branch. The job checks the key it receives against that file on the previous tip, so a key from another place refuses. The file is an enforcement file: publish it as a harness change, through a pull request with the `harness-change-approved` label or with your own `HARNESS_VERIFY=off git push`.
2. `harness.py ci-protect --attest` (needs `gh` and admin rights on the repository) creates the environment `harness-attest` with the default branch as its only deployment branch, refuses while repository-level secrets or variables named like the two secrets exist (`--delete-repo-copies` deletes them), records the branch in the repository variable `HARNESS_ATTEST_BRANCH`, and states the mode in force.
3. Add the two secrets in that environment, not at repository level. If you want each signing to wait for a person, add required reviewers to the environment.
4. Optionally, add `HARNESS_ATTEST_POLICY_TOKEN` to the environment: a fine-grained token with read access to the repository's Actions, Secrets and Variables and nothing else. The job reads the environment's rule with it, in its own step, and lists the repository's secrets and variables (names only): it refuses to sign while a repository-level `HARNESS_ATTEST_KEY` or `HARNESS_ATTEST_PASSWORD` exists, since a repository secret signs when the environment has none and every workflow can read it. Without the token, or when a list can't be read, the job refuses to sign, unless you opt in with `harness.py ci-protect --attest --recorded-fallback`, which accepts the branch recorded in `HARNESS_ATTEST_BRANCH` without re-reading the rule (`HARNESS_ATTEST_RECORDED_FALLBACK` is set to `true`) and leaves repository copies unchecked. The job logs which (`attest mode: ...`, `repository copies: ...`).

Without a readable rule, a pull request that edits the workflow could read the key. A failure in the job's steps fails the job; without the key the job does nothing. To rotate the key, publish the new public key as a harness change (that push gets no statement), then replace the two secrets. Publish the public key and check an attestation with:

```sh
cosign verify-blob-attestation --key harness-attest.pub --bundle harness-verdicts.sigstore.json \
  --type https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1 \
  --digest "$(git rev-parse <commit>)" --digestAlg gitCommit --insecure-ignore-tlog
```

A signature shows that a holder of the key signed the statement; it doesn't name the run that made it. Anyone who can read the key can sign anything until it is rotated, so check the content as well: running the same engine's `attest` on the same commits must give the same bytes. The statement is about the commit on the default branch, so for a squash or rebase merge it isn't the pull request's head. Artifacts expire with the repository's retention setting. Set the secrets once the base branch runs a release with `attest`: an older engine fails the step.

## Autonomous mode (`HARNESS_AUTONOMY`)

`supervised` (default) or `autonomous`, user-only. In autonomous mode no human is in the loop, and AGENTS.md section 7 replaces every "ask the user":

| Mechanism | What it does |
|---|---|
| `harness.py approve <id>` | Policy approval. For a valid spec with a current griller pass, it writes `Approved-by: policy:low-risk (<date>; base <commit>; grill <fingerprint>)`, but only if `risk_reasons` finds nothing, so only for `Change-Class: docs` or `refactor`. Otherwise it escalates. Only `HARNESS_AUTO_APPROVE="low"` enables it; `off` escalates every spec. |
| Risk | A `Change-Class` of `feature` or `schema` (or none, which counts as `feature`): the user approves those (the harness's ADR-002). Spec text (outside the Skills section) matching `HARNESS_RISK_TERMS`, spec paths matching `HARNESS_RISK_PATHS`, or a referenced ADR that isn't Accepted, whatever the class. When finishing a policy-approved task, the judge gate also assesses the diff since the base commit: sensitive paths, more than `HARNESS_RISK_MAX_FILES` files, or, for `docs`, a file that isn't documentation (`HARNESS_DOC_PATHS`). A moved file counts at both its old and its new path. `harness.py risk <id>` shows the assessment, the class and what it allows. |
| `harness.py escalate <id> --reason ...` | Parks the task. Its line leaves `[WIP]` with a `BLOCKED: <kind>` note, and an entry goes into `backbone/escalations.md` (a GitHub issue too with `HARNESS_ESCALATE_GH="on"` and `gh`). A BLOCKED task cannot start. Agents can't clear the note or edit `escalations.md`. `harness.py escalations` lists open entries. |
| Automatic escalation | The griller's recorder after `HARNESS_GRILL_MAX_ROUNDS` consecutive fails, the judge's after `HARNESS_JUDGE_MAX_ROUNDS`. |
| Stop hook | Behaves as `block` (once per stop) whenever a task is `[WIP]`. |
| Kill switch | While `.git/harness/STOP` exists, every Bash and file tool call is refused, and the Stop hook lets the session end. Agents can't remove it through the shell. |
| Plugin mismatch (thin mode) | While the plugin's version differs from the pinned engine's, every call except reads is refused, and `run` and `orca` don't start. Supervised sessions are only told at start. |

`doctor.sh` reports an error if autonomous mode runs without `HARNESS_TEST_CMD`, or with verify, the start gate or the judge gate off.

### Failure classes and the flywheel

Every escalation records a **class** and the **playbook** that recovers from it. The harness picks the class from the escalation's kind and reason; `escalate --class <c>` sets it. After repeated judge fails, the last debugger brief decides: a spec or test it blames (owner `analyst`, `tester` or `user`) is `contradictory_req`, anything else `failed_test`.

| Class | Playbook | Typical source |
|---|---|---|
| `tool_timeout` | retry with backoff | A worker or tool died or timed out. The Orca coordinator retries a dead step worker once (after `HARNESS_ORCA_RETRY_WAIT` seconds, default 30), then escalates. |
| `invalid_args` | repair the call | A tool or command called wrongly |
| `missing_context` | retrieve the source | An unanswered question (the default) |
| `failed_test` | repair from the debugger's brief | The judge failed the code; delivery or CI failed |
| `permission_denied` | request approval | A gate, guardrail, contract or approval refused it |
| `contradictory_req` | escalate to the user | The spec, ADRs or PRD disagree; the griller kept failing |
| `unchanged_repeat` | stop | A step came back without progress |

`harness.py escalations` counts escalations by class. Once a class has been escalated twice, the harness opens `backbone/proposals/<class>.md` with every occurrence and the kind of change that would stop it. The scribe may draft the concrete change there: a guardrail, a regression test or a skill rule. The harness applies nothing. A proposal stays `Status: draft` until the user acts on it through a task they approve.

## Runner (`harness.py run`)

The user (or a scheduled job) runs `python3 scripts/harness/lib/harness.py run [--max-tasks N] [--dry-run]` in autonomous mode. The runner only sequences work; the hooks, gates and verify still do all the enforcing. For each ready task (a `[WIP]` one first, then pending lines in order; BLOCKED tasks are skipped), it:

- starts a fresh agent session with `HARNESS_AGENT_CMD`, passing the task prompt on stdin;
- stops the session after `HARNESS_RUN_TASK_TIMEOUT` seconds;
- reads the outcome from `3-TASKS.md`:
  - `[x]` with a clean working tree means done;
  - a `BLOCKED` note means the agent escalated;
  - anything else is retried, up to `HARNESS_RUN_ATTEMPTS` sessions, and then escalated as `runner`;
- gives a retry what went wrong instead of the same prompt: why the last session stopped (timed out, exited with an error, left the task `[x]` but uncommitted, or ended unfinished), the task's next step from `harness.py next` with the judge's findings and the debugger's brief, and the calls the hooks refused during it;
- escalates at once when a retry that ended cleanly changed nothing: the same next step, the same files (specs and verdicts included) and the same commit as after the attempt before. Another identical session would only repeat it. A session that failed with an agent error or timed out keeps its attempts, since an API overload or a long test run can pass;
- checks the kill switch between sessions.

Logs go to `.git/harness/runs/<timestamp>/<task>-<attempt>.log`. Agents can't start the runner.

**The runner brings the sandbox up** (`HARNESS_SANDBOX_START=on`, user-only, default `off`; the harness's ADR-003). Run on the host, `run` doesn't need you to start it inside the sandbox: before each session it brings `.devcontainer/harness-agent/` up with the devcontainer CLI (`devcontainer up`, which builds the image the first time), checks from the host that a process in it is isolated (`isolation_class` `container`, worked out by the host's own code), has the harness inside check it (`doctor`, which also checks a thin project's plugin) and refuses to run any session when any of these fails. `devcontainer up` runs parts of the sandbox's definition on the host (an `initializeCommand`, the Compose file's mounts and privileges), and an agent in the sandbox can write the workspace, so before every `up` the runner copies the whole folder to a folder of that run's own under `~/.agentic-harness/sandbox-runs/` (only you can open it, no sandbox mounts it, and it is removed after the session), checks the copy against a definition this machine trusts, and brings up the copy (with a generated Compose file that mounts the workspace by its absolute path, and a Compose project the harness names), so a change made after the check never reaches `devcontainer up`. It refuses a definition with a symlink, a bind mount from a path relative to the sandbox's folder other than the workspace's own (it would resolve from the private copy), and a bind mount that holds or lies in `~/.agentic-harness`. A trusted definition is the running engine's own copy, when the engine lives outside the project (thin mode), or one you approved with `python3 scripts/harness/lib/harness.py sandbox-approve`, which records the folder's digest in `~/.agentic-harness/sandbox-approvals.json`, outside every project and every sandbox. Anything else (a changed, added or removed file) stops the run before `devcontainer up`, and `doctor` reports it. Agents can't change the definition (Write, Edit, shell and code writes to `.devcontainer/harness-agent/` are refused), write the approvals or run `sandbox-approve`. A full install's definition needs one approval before the first such run, and every change to it, an update's included, another. It then runs the session in the agent's container with the agent command the sandbox defines (`HARNESS_AGENT_CMD` in `docker-compose.yml`), the prompt naming the harness command there, and the harness settings your environment sets (apart from the agent command). The session's timeout is enforced inside the container, because stopping `devcontainer exec` on the host would leave it running there. After each session the runner removes the sandbox's containers, so whatever the session left running or changed in them (a shell startup file, a program on its PATH) doesn't reach the next session; the isolation check also runs with an absolute interpreter and no environment but the two variables it reads. Named volumes stay: the Claude Code login (`harness-agent-claude-config`, shared by every project's sandbox) keeps what an agent writes under `~/.claude` from one session to the next. It refuses to start while the project's sandbox, or any container that mounts the project, is already up (opened in an editor, say), so that no process an agent left there can change the definition while it is checked and copied. `doctor` reports an error, so `run` refuses, when the devcontainer CLI or `docker` isn't on the PATH or the sandbox files are missing. `--worktree` can't run this way, since a worktree's git metadata lives outside the folder the sandbox mounts. Inside the sandbox the setting changes nothing. The devcontainer CLI names the Compose project after the sandbox's folder, so one project's sandbox runs on a machine at a time. In a full install, though, `run` on the host executes the workspace's own `scripts/harness/`, which an agent in the sandbox can also write, so the approval protects thin installs fully and full installs only as far as the harness's own files are left alone: use thin mode, where the engine lives outside the project, with `HARNESS_SANDBOX_START=on`.

- **Workspace trust.** In a folder Claude Code hasn't trusted, `claude -p` ignores the project's hooks, agent hooks and permissions, so the harness would not run at all. The runner refuses to start there; accept the trust dialog once interactively. The sandbox and the CI judge trust their own workspace. `HARNESS_SKIP_TRUST_CHECK=1` is for agent commands other than Claude Code.
- **Budgets.**
  - `HARNESS_RUN_TASK_TIMEOUT` per session and `HARNESS_RUN_ATTEMPTS` per task.
  - `HARNESS_RUN_MAX_COST`: dollars per run. The run stops before the next task once spent. Cost and turns are read from `--output-format json` output (the default command uses it).
  - Per session, add `--max-budget-usd <n>` to `HARNESS_AGENT_CMD`.
- **`--worktree [--pr]`:** each task runs in its own worktree, on branch `harness/task-<id>` from the current HEAD. The base branch is left untouched.
  - A done task's branch is delivered by its own session (the deliver step, when `HARNESS_DELIVER` is on). With `--pr`, a blocked or escalated task's branch is pushed and a pull request opened too, for a person to look at.
  - A task that already has a branch is skipped; delete the branch to retry.
  - Tasks run independently of each other, so `3-TASKS.md` may need a rebase between their pull requests.
- **`--only <id>`** runs one task.
- **An agent that cannot start** (not logged in, bad API key: it fails at no cost) stops the run. Retrying or moving to the next task can't help, so no task is escalated for it, and the task stays ready.
- **Keep the machine awake.** A sleeping laptop suspends the run, so wall time grows while nothing happens. On macOS, start the runner with `caffeinate -i python3 scripts/harness/lib/harness.py run`.

**Sandbox.** `.devcontainer/harness-agent/` is a sandbox for unattended runs: two containers from one image (`docker-compose.yml`), started by the devcontainer tooling. `tests/test-sandbox-egress.py` brings it up for real (`HARNESS_E2E=1`) and checks the allowlist, the agent's capabilities and the evidence; the earlier one-container version also ran a real task end to end with a subscription token. Review it before use, and add your toolchain. It provides:
- outbound traffic limited to the Anthropic API, GitHub and `HARNESS_FIREWALL_ALLOW` (set on the `egress` service in `docker-compose.yml`). The `egress` container applies the rules (`init-firewall.sh`) in the network namespace the agent's container joins; the agent's container drops NET_ADMIN and NET_RAW, runs with `no-new-privileges` and has no sudo, so nothing the agent runs changes the rules. Outbound IPv6 is dropped;
- DNS for allowlisted names only: every DNS query the agent's processes make, to any resolver, is redirected to `egress.py` in the `egress` container, which resolves a name only when it is on the published allowlist (exactly, in any case) and answers NXDOMAIN otherwise, logging the name; a name with a label no host name has (a dot inside it, a space, a control byte) gets FORMERR and is logged as `(malformed)`. For a listed name it sends upstream a query rebuilt from the name alone (lower case, a fresh id, no other section), so an EDNS option, extra records, the id or the flags the agent chose stay inside. Port 53 to anywhere else is dropped, and so is Docker's own resolver for everyone but the `egress` container's root, so nothing leaves in DNS queries but the listed names. Still possible: DNS over HTTPS to an allowlisted host that offers it, and domain fronting through an allowlisted CDN, since TLS isn't inspected. Names still resolve to addresses once, when the `egress` container starts;
- a log of what the `egress` container denied: every packet its rules drop is logged first (an NFLOG rule, up to 50 a second), and `egress.py` appends one line per packet to `/run/harness-egress/denials.jsonl` (target address, port and protocol, and the uid that sent it; the first line says when the log started), and one per refused DNS name, on the volume the agent mounts read-only. The log restarts with the `egress` container and stops at 20,000 lines;
- an image built from a base pinned by digest;
- no host credentials apart from `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, counted against your Claude subscription) or `ANTHROPIC_API_KEY` (billed per token). The host's keychain login isn't visible in the container;
- a trusted workspace;
- `HARNESS_AGENT_CMD` set to `--dangerously-skip-permissions`, because the container, not the prompt, is the boundary;
- in a thin project (ADR-001), the harness plugin: `init --thin` and `pin` install the sandbox too, and when the container starts, `thin-engine.py` fetches the release the project pins into `~/.agentic-harness/engines/<version>/`, refuses it unless it is the pinned commit with no local changes, and links it into `~/.agentic-harness/plugins/`, which `CLAUDE_CODE_PLUGIN_DIRS` names, so every Claude Code session in the container loads the pinned plugin and its hooks. Run the harness there with `python3 ~/.agentic-harness/plugins/agentic-harness/plugin/launcher.py <command>`. `HARNESS_ENGINE_SOURCE` on the host names another repository to fetch from; it must be reachable from the container. Inside the image, `doctor` reports an error, so `run` and `orca` refuse to start, when a thin project's sessions wouldn't load exactly the pinned plugin. `pin` updates the sandbox files nobody edited and keeps an edited one, writing the release's copy to `<file>.harness-new` (exit code 1), as `update.sh` does.

Add your toolchain in a Dockerfile that builds `FROM` it.

**Sandbox backend and evidence** (the harness's ADR-003). The runner starts each session through a sandbox backend, `HARNESS_SANDBOX_BACKEND` (user-only). The only one is `devcontainer`, the default: it runs the session where the runner runs, inside the container when you started `run` there, else on the host. Any other value is a doctor error, so `run` and `orca` refuse to start. `verify` and `harness-verify` never use a backend. Inside the harness-agent image (`HARNESS_SANDBOX_IMAGE` set), an egress allowlist that isn't published at `/run/harness-egress/allowlist` is a doctor error, so `run` and `orca` refuse to start; `doctor` also warns about a `devcontainer.json` that names no `dockerComposeFile` or can't be parsed. Each judge verdict records the sandbox it was recorded in, and `receipt` shows it (SANDBOX; `sandbox` in `--json`): `backend`, `isolation_class` (`container` only in a Linux container whose process has NoNewPrivs set, no NET_ADMIN, NET_RAW or SYS_ADMIN in its effective or bounding set, and the egress allowlist published at `/run/harness-egress/allowlist`; `none` otherwise, with `isolation_reason` saying why), `base_image_digest` (the pinned base, not the packages installed on top), `allowlist_hash` (sha256 of the allowlisted host names, lower-case, sorted, one per line, as the `egress` container publishes them; not the resolved addresses), `region`, `control_plane` and `credential_mode` (`env` when `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` is set in the container, `login` otherwise, `host` outside it), and in a container `egress_denials`: a summary of the denial log at the judge pass (since when it logs, how many packets were denied, the ten targets denied most, and the log's sha256), which the receipt cites (a target shows only the characters of a host name, address and port, `?` for any other, at most 255 of them, since the agent chooses the names it asks for), or "not logged" for an `egress` container from before the log. A receipt flags a container with no allowlist. An image built before this release reports `none` until it is rebuilt.

**Sandbox gate.** `HARNESS_SANDBOX_REQUIRE` (user-only) names the isolation class each Change-Class needs, as space-separated `<class>=<isolation class>` pairs. The default, `auto`, is `schema=container` in autonomous mode and nothing in supervised mode, where a person approves each step; pairs you set apply in both. The isolation classes rank `none` < `container` < `userspace-kernel` < `microVM` < `dedicated-VM`. A pair holds for its class and every class above it on the ladder (`docs` < `refactor` < `feature` < `schema`), so `feature=container` covers schema work too. Such a task starts (`start`, or an edit of `3-TASKS.md`) only in a session whose own sandbox has that class; while it is `[WIP]`, a session without that sandbox may read but not write or run anything (write and exec tool calls, and tools with no contract, are refused; its task line stays the start and finish gates' to judge); and it finishes (`finish`, an edit, and `verify`, so the pre-commit hook and CI too) only when its latest judge pass recorded one; CI's verify reads the recorded evidence, never the sandbox CI runs in. A judge pass with no recorded sandbox, an isolation class the harness doesn't know and a backend it doesn't know count as no isolation. A value the harness can't read is a doctor error and stops every start and finish until the user fixes it. `run` skips such a task before starting any session for it (`run: skipped task <id>`, exit 1), unless it brings the sandbox up itself (`HARNESS_SANDBOX_START=on`), and `receipt` says what the class requires and whether the judge pass met it. The Orca coordinator's workers run on the host, so they can't do work that needs a container. Lower the requirement, or set it empty, to work without the sandbox.

`HARNESS_AGENT_CMD` defaults to `claude -p --permission-mode acceptEdits --output-format json`. The prompt arrives on stdin. That matters because `--allowedTools` takes any number of values and would swallow a prompt passed as an argument; quote each pattern, as in `--allowedTools 'Bash(git:*)' 'Bash(python3:*)'`. An unattended agent needs its tools pre-approved: allow the build and test commands in `.claude/settings.json`, or run it in a container or VM with `--dangerously-skip-permissions`. The harness hooks apply either way. Work on a branch and let the CI check gate the merge.

## Agent CLIs: Claude Code, Codex, OpenCode

The gates don't depend on the agent CLI. Each CLI's hooks call the same `harness.py hook <event> --from <cli>`, which turns its input into one shape before any gate runs. The git hooks, `verify` and the CI checks apply to every commit whichever agent made it.

| | Claude Code | Codex | OpenCode |
|---|---|---|---|
| Hook wiring | `.claude/settings.json`, agent frontmatter | `.codex/hooks.json` | `.opencode/plugins/harness.js` |
| Role agents | `.claude/agents/*.md` (the source) | `.codex/agents/*.toml` (generated) | `.opencode/agents/*.md` (generated) |
| File edits seen as | Write / Edit / MultiEdit | `apply_patch` (the patch is parsed and checked file by file) | edit / write / patch |
| Who may edit what | the agent's tool list and the harness's role scopes | the harness's role scopes only (Codex has no per-agent tool list) | the agent's `permissions` and the harness's role scopes |
| Verdicts recorded from | the griller's and judge's Stop hook | `SubagentStop` | the result of the `subagent` tool (no stop hook) |
| Skills | the Skill tool, or Read of the SKILL.md | printing `.claude/skills/<name>/SKILL.md` (cat, sed, head) | the Skill tool |
| Unattended | `claude -p --output-format json` (cost per session) | `codex exec --json -s workspace-write --dangerously-bypass-hook-trust` (prompt on stdin; turns, no price) | `opencode run --format json --auto "$(cat)"` (cost per step) |
| Gaps | | Project hooks run only once trusted: `harness.py run` refuses Codex without `--dangerously-bypass-hook-trust` (sandbox it), unless you trusted them with `/hooks` and set `HARNESS_SKIP_TRUST_CHECK=1` | No Stop hook: the "still [WIP]" reminder doesn't fire. Knowledge-server tools are mapped by name (`knowledge_*`), unverified |

A session can also play a single role from start to finish (a coordinator starting one worker per role): set `HARNESS_ROLE=<role>` in its environment. The hooks then hold it to that role's write scope, record the griller's or judge's verdict when it stops, and leave the Definition of Done to the coordinator. The agent can't change the variable: the hooks read it from the session's own environment.

**Thin mode** (the plugin runs the pinned engine; the project has no `AGENTS.md` or `scripts/harness/`). Session start and a `SubagentStart` hook tell each session and subagent which engine paths stand in for those files. Codex and OpenCode plugins can't ship agents, so on session start the harness installs the pinned engine's role agents in `$CODEX_HOME/agents` or OpenCode's user `agents` folder; restart the CLI to load them. A file there that the harness didn't write is kept and reported, and agents can't edit the installed ones. OpenCode has no session-start hook, so its plugin adds that context to each model request. `run --worktree` and `orca` run the pinned engine on each task's worktree. In Claude Code and Codex the plugin also runs the machine guard's check, once the machine has its settings (`machine.sh install --plugin`): an edit or shell command that reaches a repository under the machine's roots that isn't enrolled gets a reminder, or is refused in block mode. Where `machine.sh install` also put the guard hook in a CLI's user settings and the CLI runs it (Codex: once it is trusted in `/hooks`, as it is now, and switched on), the plugin leaves the check to that hook.

Regenerate the Codex and OpenCode agents after changing a Claude Code agent: `tools/gen_agents.py` (the self-test fails while they are out of date).

## Tester and debugger

**Tester** (`HARNESS_TESTER`, user-only, default `off`). Without it, the implementer writes both the code and the tests that prove it. With it:
- The tester writes the acceptance tests from the spec first, at least one per AC, in files matching `HARNESS_ACCEPTANCE_PATHS` (default: any path containing `acceptance`).
- The tester may write only there; the implementer may not write there at all.
- On the tester's Stop, the harness records which files cover which criteria, and a fingerprint of them, in `backbone/.verdicts/<id>.tests.json`. It refuses to record while a criterion has no acceptance test.
- The judge gate refuses to finish the task when no tests were recorded, a criterion lacks one, or the files changed since they were recorded, including through the shell.

**Debugger** (`HARNESS_DEBUGGER`, default `on`). After a judge fail, `next` sends the task to the debugger before the implementer. It changes nothing and records a fix brief with the root causes, each with an owner, in `backbone/.verdicts/<id>.debug.json`. `next` hands that brief to the implementer, and lists any other owner (the tester, analyst or user) under `needs`.

## Reviewer (`HARNESS_REVIEW`)

`HARNESS_REVIEW` (user-only, default `on`). After the judge passes a task, `next` returns the `review` step with the `lenses` still due: `correctness` (bugs, security, blast radius, missing tests), `structure` and `lean`. Start one `reviewer` per lens, all at once; they work independently, so they run in parallel, and the lenses can run on different models (`--agents reviewer=codex`). Each follows the `change-review` skill and changes nothing.

Its Stop hook (`review-stop`; Codex and OpenCode through `subagent-stop`) records the lens's verdict in `backbone/.verdicts/<id>.review.json`, with the code fingerprint. A `must-fix` finding records a fail whatever verdict the reviewer claimed. A fail sends the task to the implementer with the findings (`fix`); the changed code goes back to the judge, then to the lenses again. A lens that passed on the current code is not run again.

The judge gate, and so `finish`, pre-commit, pre-push and CI `verify`, refuses a finished task without a pass from every lens on its committed code. After `HARNESS_JUDGE_MAX_ROUNDS` consecutive fails of a lens, it says to stop and take the findings to the user.

## Deliverer (`HARNESS_DELIVER`)

`HARNESS_DELIVER` (user-only, default `on`). A finished task is `done` only once the branch tip that holds it is delivered. After the task is `[x]` and committed, `next` returns `deliver` (the `deliverer`). With uncommitted changes or no `origin` remote, it returns `deliver` with no role and says what is `needed`. The deliverer pushes the branch, opens or updates its PR with each task's receipt and the reviews' should-fix findings as follow-ups, and watches `gh pr checks`. It labels the PR with the receipts' suggested labels: the highest `risk:*` among them and each `class:*`, creating the ones the repository lacks. On an existing PR the risk label only goes up. It writes nothing in the checkout and never merges.

Its shell commands are held to the role (the main session can still merge):
- It runs only the gh commands delivery needs: `gh pr create`, `edit`, `view`, `checks` and `list`, `gh run view`, `list` and `watch`, `gh label list` and `create`, `gh repo view`, and `gh api` reads. Every other gh command is refused as the user's call, among them `gh repo edit` (auto-merge, the default branch), `gh workflow`, `gh secret`, `gh variable`, `gh issue`, `gh release`, `gh ruleset`, `gh run rerun`, and gh aliases and extensions. `gh pr merge`, `close`, `review` and `ready` are refused (merging, closing and approving are the user's), and so is a push to the default branch or from it. `--web` is refused (it opens a browser), and so is `git push --all` and `--mirror`, and a refspec whose destination is the default branch or a wildcard. A merge, close, review or auto-merge that a command only names (in `echo`, a log search or any other text outside a PR's title and body) is refused too.
- `gh api` only reads: a `GET` or `HEAD` request, never GraphQL. GraphQL and REST writes can merge, enable auto-merge or set labels, with a query or body the harness may not see (`-F query=@-`, `--input -`).
- Labels: it may add and create only `risk:low|elevated|high` and `class:docs|refactor|feature|schema`, and remove only a `risk:*` label lower than the one it adds in the same call. `gh label create --force` is refused: it rewrites a label someone else defined. A PR keeps one `risk:*` label, which only goes up: before the deliverer adds one to an existing PR, the harness reads the PR's labels (`gh pr view --json labels`) and refuses a second one. Every gh call is checked against the labels as they are before the command runs, so a command whose gh calls add different `risk:*` labels is refused too. If gh can't read the labels, the call is refused. A label such as `harness-change-approved`, which lets a PR change the harness, stays the user's.
- The harness reads gh and git calls as the shell would run them: written directly, behind runners such as `timeout`, `env` or `nice` and the shell's `builtin`, `noglob` and `nocorrect`, in `sh -c` and `eval`, in `$(...)` and backticks, and in heredocs and here-strings a shell reads. It refuses what it can't read: gh behind `xargs`, `parallel` or `find -exec`; a shell reading its commands from a pipe or a file, `source` and `.` included; a command, subcommand or flag that comes from an expansion (`$GH`, `"$FLAGS"`); an unquoted glob or brace in a gh or git call or in a command's name, which the shell expands into words the harness doesn't read (`ls tests/*.py`, `git rev-parse @{u}` and a `gh api` placeholder such as `{owner}` are fine); `--recover`; a variable that runs a command or changes what gh and git run or read, set as a prefix or exported (`GH_BROWSER=`, `BROWSER=`, `GIT_SSH_COMMAND=`, `PATH=`, any `GH_` or `GIT_` setting); shell alias definitions (`alias`, `BASH_ALIASES[...]=`, zsh's `aliases[...]=`): in a shell that expands aliases, as Claude Code's often does, a name defined on one line can run gh on the next; a program that runs code or commands from its arguments or stdin, which the harness doesn't read: `python3 -c` (even `print(1)`: run a script file), `python3 -` or a heredoc fed to it, a script read from `/dev/stdin` or a `/dev/fd` path (`node /dev/stdin <<<`, `bun`, `tsx` and `deno` too), `perl -e` and `perl -M` with code in the argument, `node -e`, `node --eval=`, `node --import data:...`, `ruby -e`, `bun -e`, `deno eval`, `tsx -e`, `ts-node -e`, `java --source`, `java -`, `jshell`, `go run` from stdin, `/dev/` or a `module@version`, or with `-exec`, `awk`, `sed`, `osascript`, `fish`, `csh`, `tcsh`, `Rscript`, `julia`, `swift`, `ed` and the editors and pagers; a runtime's option that takes a value is read as taking it, and a URL or data: URL is refused; every Python module run (`python3 -m`) and `pytest` are refused, since the deliverer runs no tests: `pty`, `timeit` and `pdb` run what they are given, `unittest` imports the module it names (`code.interact` reads Python from stdin) and `pytest -p` loads any module as a plugin; `--version` and `--help` run nothing alone, and with anything else on the command they are refused; a package runner (`npx`, `bunx`, `pnpx`, `uvx`, `uv`, `pipx`, `poetry`, `npm exec`, `pnpm dlx`, `yarn dlx`, `bun x`, `deno eval`, `npm create`) runs code from the registry; `coproc` and `trap`, which run a command later; `hash`, and `ln`, `cp`, `mv` and `install`, which copy or link a program under another name; a program run by a path outside the system directories (`./deliver`, `/tmp/g`); and a gh or git binary reached under another name, which its symlink or the PATH resolves to.
- gh acts on this repository only: `-R`, a PR or issue URL and `gh repo view <repo>` must name the origin remote, and `gh api` takes no `--hostname` and no URL, which would send the request and the token to another host.
- A git ref command (`checkout`, `switch`, `merge`, `rebase`, `reset`, `branch`, `fetch`, `pull`, `update-ref`, `symbolic-ref`, `restore`, `cherry-pick`, `revert`, `am`, `worktree`, `push`) that names the default branch in any spelling (`main`, `origin/main`, `heads/main`, `refs/heads/main`), or that uses `-`, `@{-1}` or a `$` or backtick, is refused, since the default branch changes through the PR. So is a push refspec with a wildcard. `git fetch`, `git pull` and `git rebase` read the default branch and are allowed (`git fetch origin main`, `git rebase origin/main`); a pull or rebase on the default branch, and a fetch or pull whose refspec destination is the default branch or a wildcard, are refused. A rebase given the branch to rebase (`git rebase origin/main main`, `git rebase --onto x origin/main main`, `git rebase --root main`) is refused: git checks that branch out first, so a push after it would push a branch the harness didn't check. An interactive rebase is refused, since it waits for an editor the deliverer can't drive: `-i` alone or in a cluster of short flags (`-ki`), `--interactive` and its prefixes, `--edit-todo`, and `git pull --rebase=interactive` (`--rebase=i`, `-ri`). For the same reason a push is refused in a command that also runs `git checkout`, `switch`, `symbolic-ref`, `bisect` or `worktree`, wherever they come in it: push in a command of its own. `make`, `just`, `task` and `ninja` read no file from `-`, `/dev/stdin`, a `/dev/fd` path or an expansion. A commit message (`-m`, `-F`) and the body of a heredoc a PR takes as `--body-file -` are text; `$'...'` escapes are read as the characters they name, so a tab or newline before `gh` ends a word.

This check is best-effort. It doesn't see gh run from a script the repository holds, nor from a program a person installs in a system directory that calls gh itself (a `make` target, a git hook), nor requests sent with another HTTP client. Git subcommands that run a command (`git rebase -x`, `git bisect run`) aren't read. Its git configuration is refused rather than read: `git -c`, `--config-env`, `--exec-path`, `--git-dir` and `--work-tree` are refused, and so are `git config` writes (an alias that starts with `!` or an ssh command would run a command the harness doesn't read; reading config is fine), and `--exec`, `--upload-pack` and `--receive-pack`. GitHub permissions remain the boundary, so restrict who may label and merge pull requests, and protect the default branch. The gate doesn't close writing a script and running it: a command that writes a file and then runs it (`printf ... > s.py; python3 s.py`, `printf ... > Makefile; make`, a written `package.json` run by `npm run`) is refused. Written files are a redirection's target, `tee`'s files, the last operand of `cp`, `mv`, `install` and `ln`, `dd of=` and `curl -o` or `wget -O`, compared by file name whatever directory a run spells (`$PWD/s.py`, `sub/../s.py`), and a runtime operand with an expansion or a glob is refused after any write. A later command can still run what an earlier one wrote, a file written by another program (`tar`, `unzip`, or a script the command runs) isn't seen as written, and a file the repo already holds runs as the repo's code, as `make` targets do. Unlisted runtime options that take a value are read as the script name, and an interpreter reached through an unlisted name is read by its name only.

Its Stop hook (`deliver-stop`; Codex and OpenCode through `subagent-stop`) checks the report against git:
- `delivered` is refused unless the tree is clean, `HEAD` equals its upstream branch, and `checks` is `passed` or `none`;
- `hold` and `ci-failed` are refused without findings, each with an owner;
- every report is logged as a `deliver` event with the PR, the head, the findings and the owners. `next` reads it: `delivered` on the current `HEAD` makes the task `done`; `hold` or `ci-failed` makes it `delivery-failed`, with the findings. A fix goes through the pipeline as a new task, and the next delivery covers the new `HEAD`.

The **pre-push hook** runs `verify` on the commits being pushed, so no push, by the deliverer or anyone else, carries a finished task without its judge and review passes. In `harness.py orca --merge`, tasks are merged into the base locally; the base branch is delivered from its own checkout.

## Coordinator API

A coordinator asks the harness what a task needs instead of knowing the workflow. The answers come from the artifacts the gates check.

| Command | Answer |
|---|---|
| `harness.py state [--json]` | Every task: state, `change_class`, spec problems, grill and judge verdicts (and whether they are current), approval, open escalations |
| `harness.py next <id> [--json]` | `progress` is a fingerprint of the whole checkout, specs and verdicts included: the same step with the same `progress` means the last worker changed nothing. `change_class` is the spec's class (`feature` when it declares none). The next step and who does it: `define` (analyst or architect), `grill` (griller), `answer` (the griller's questions, routed; `needs_user` says whether any must go to the user), `approve`, `start`, `test` (tester), `implement`, `judge`, `diagnose` (debugger), `fix` (implementer, with the debugger's brief or the reviews' must-fix findings), `review` (one reviewer per lens in `lenses`, in parallel), `finish` (scribe, then `finish`), `deliver` (deliverer, after the commit), `delivery-failed`, `blocked`, `done` |
| `harness.py questions <id> [--json]` | The griller's open questions, each routed: design questions to the architect, the rest to the analyst. A question marked `apply` (a non-blocker with the griller's recommendation) is applied by that role without asking |
| `harness.py start <id>` / `finish <id>` | Mark the task `[WIP]` / `[x]` through the same gates as an edit of `3-TASKS.md` (start: spec, grill, approval, one `[WIP]`; finish: a current judge pass) |

Under an Orca coordinator (`HARNESS_ORCA_RUN` set), `escalate` also sends an `escalation` message to the Run's mailbox.

## Orca coordinator (`harness.py orca`)

`python3 scripts/harness/lib/harness.py orca [--tasks 1.3,1.4] [--parallel 2] [--agents default=claude,judge=codex] [--trust] [--merge] [--dry-run]` drives ready tasks with [Orca](https://github.com/stablyai/orca) supervised workers. It needs autonomous mode and a running Orca.

- **A queue.** All ready tasks are queued; up to `--parallel` run at once, and the next one starts as soon as a slot frees. A task waits for the tasks named on its line, `- [ ] **Task 1.4: ...** (spec: ...) (after: 1.2, 1.3)`, until they are `[x]` on the base branch. `--dry-run` shows what each task waits for.
- **`--merge`** merges each finished task's branch into the base branch, so the tasks after it build on it. Parallel tasks both edit `3-TASKS.md` and append to `6-MEMORY.md` and `5-DECISIONS.md`. When those are the only conflicts, the coordinator resolves them: the base's task list with this task marked `[x]`, and both sides of each log. Harness-owned files take the base's version, and `escalations.md` is merged by entry. A **code** conflict (parallel tasks built the same module) starts an **integrate** step: the coordinator merges the base into the task's branch in its worktree, an implementer worker resolves only the conflicted code files, and the coordinator commits that and runs `HARNESS_TEST_CMD` (`harness.py test-run`) before merging. If conflict markers remain or the tests fail, the task is escalated. A resumed run merges tasks that finished on their branch earlier. Without `--merge`, each task's branch is delivered by the deliver step: one pull request per task.
- **One Orca worktree per task** (`harness-task-<id>`, from the current branch), so tasks run in parallel without sharing `3-TASKS.md`. The repository is registered with Orca if it isn't yet.
- **One worker per step.** The coordinator asks `harness.py next <id>` what the task needs. For a role step it starts a worker with a self-contained spec: target, change, ownership, constraints and the acceptance check. The worker delegates the step to the role agent, and the hooks hold that agent to its role. Approve, start, finish and the commit the coordinator runs itself, through the same gates.
- **Questions between agents.** A worker that needs an answer asks the coordinator (`orca orchestration ask`). The coordinator starts an analyst worker, or an architect worker for design questions, to answer from `backbone/` and the knowledge source. The answer goes into the spec under Assumptions, with its source, and the reply tells the asker where it is. A question nobody can answer from the sources is escalated. A spec that changed during the build is grilled again before the task goes on.
- **Agents per role** (`--agents` or `HARNESS_ORCA_AGENTS`, user-only): for example `default=claude,judge=codex` runs the judge on a different model from the implementer. Agents that need launch flags get their own terminal (`HARNESS_ORCA_LAUNCH`, default `codex=codex --dangerously-bypass-hook-trust -c check_for_update_on_startup=false`: an update prompt would block an unattended start). Codex otherwise skips the hooks of every new worktree until someone trusts them, and the harness's hooks are lock-checked.
- **Permission prompts.** A worker must run Orca's own commands to report back. For Codex, the harness ships `.codex/rules/harness.rules`, which allows exactly `orca orchestration check`, `send` and `ask` without asking; every other command still follows Codex's own approvals. Codex loads it once the project's `.codex/` layer is trusted, which `--trust` does for task worktrees. A worker still waiting at a prompt (another agent, another command) is logged by the coordinator and never answered.
- **`--trust`** marks the repository and each task worktree trusted for Claude Code (`~/.claude.json`) and Codex (`~/.codex/config.toml`). Claude Code decides trust for a worktree by its main repository. Without it, a worker in a new worktree waits at its trust dialog, which Orca reports as `Agent startup blocked: agent-trust-workspace`.
- **Safety.** The coordinator follows Orca's lifecycle rules: it acknowledges every delivery after processing it, and releases a worker only after it settles. It never stops, abandons or retries a worker by itself. A role step that comes back with the same `progress` as when its worker started, after the worker reported success (it changed nothing), is escalated instead of started again, and so is a step that comes back more than 3 times. `.git/harness/STOP` halts it.
- **The end.** It commits each finished task on its branch and runs its deliver step (a `delivery-failed` is escalated), then reports every task's outcome, PR and the open escalations. Answer those, then run it again: it picks up where the tasks stand.

## Knowledge source (`HARNESS_KNOWLEDGE_ROOT`)

In autonomous mode the griller's questions are answered from `backbone/`. A knowledge source adds a second place to look: a folder of notes (an Obsidian vault, a wiki export) served by an MCP server. Unanswered questions still escalate; the knowledge source only means fewer of them do.

**Setup (user-only):**
1. Register the server for this project under the name `knowledge`: `claude mcp add -s local knowledge -- <the server's command>`. For the second-brain vault that is its `start.sh`. The name is fixed because the agent definitions grant `mcp__knowledge`.
2. Set `HARNESS_KNOWLEDGE_ROOT` in `backbone/harness.conf` to the folder the server reads (used to check citations). Doctor warns if no `knowledge` server is registered.
3. Optionally set `HARNESS_KNOWLEDGE_PATHS` to the vault folders agents may read and cite, and `HARNESS_KNOWLEDGE_TOOLS` to the server's read-only tool names.

**How a question is settled.** The analyst (or the architect, for design questions) first checks `backbone/`, then the knowledge source:
- A question already in the vault's open-questions register (`pending_questions`) is known to be open: it stays open.
- A note that answers it clearly becomes an assumption citing it: `- A2: Endpoints are versioned in the path (source: vault:20-Architecture/adr-api-versioning.md)`.
- Silence, vagueness or contradicting notes leave it open. A **blocker** may be settled from the vault only by an accepted decision record.
- The griller's next pass re-reads every cited source and raises the question again if the note doesn't say what the assumption claims.
- Questions left open are escalated to `backbone/escalations.md` as before. Nothing is written to the vault.

**What the harness enforces:**
| Check | Where |
|---|---|
| Knowledge tools are refused while `HARNESS_KNOWLEDGE_ROOT` is empty | `pre-tool-use` (matcher `mcp__knowledge__.*`) |
| Only tools matching `HARNESS_KNOWLEDGE_TOOLS` run: write tools such as `create_note`, `update_note` or `move_note` are refused | `pre-tool-use` |
| With `HARNESS_KNOWLEDGE_PATHS`, read tools must name notes by their vault path inside those folders (no bare aliases, no `..`) | `pre-tool-use` |
| Every assumption has a `(source: ...)`; every `vault:<path>` is an existing note inside the vault and the allowed folders | `approve` |
| Each lookup is logged; `report` counts them | event log |

**Limits.** Search results aren't filtered: a search can list notes outside `HARNESS_KNOWLEDGE_PATHS`, though reading or citing them is refused. Whatever the agents read is sent to the model, so keep notes that must never leave your machine out of the folder the server serves (or run a second server over a subset). In the sandbox, mount the vault read-only, set `HARNESS_KNOWLEDGE_ROOT` to the mount point in the agent service's `environment` in `docker-compose.yml`, install the server's dependencies in your Dockerfile, and register the server in `postStartCommand` (see the comments in `devcontainer.json`).

## Out-of-band changes

The shell checks can't see what a script file does. The harness keeps a snapshot of the protected files (`backbone/`, `scripts/harness/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`). The snapshot is refreshed after every file-tool edit and every write of the harness's own. It caches each file's hash by size, modification time and change time (which a script can't set back), so a refresh costs a directory walk, not a read of every file. Claude Code's worktrees under `.claude/worktrees/` are not part of it.

- **Autonomous mode**: after each shell command, any protected file that changed outside those, and isn't simply back to its committed version, is reported. It is logged as `tamper`, and the `[WIP]` task is escalated for review.
- **Supervised mode**: the user edits these files too, so the snapshot is also taken as each shell command starts, and only what changed while that command ran is reported, whether it succeeded or failed (`PostToolUseFailure`). Edits made between commands are not. While commands overlap, the snapshot from the first one's start stays until the last has finished, and the note names every command that was running. A command whose end never comes (interrupted) stops counting after its timeout plus 30 seconds. A background command (`run_in_background`) is checked when it is launched, not when it ends. The agent gets a note naming the command and the files, and the change is logged as `tamper` (it shows in `trace` and `report`); nothing is escalated, since the user is there. A file the user saves while an agent's command runs is reported too; the note names the command so they can tell.

Restore a file with `git checkout -- <file>`.

## Event log, trace and report

Blocks, verify refusals, verdicts, approvals, escalations and run attempts are appended to `.git/harness/events.jsonl`, and so is what a task's agents did:
- `context`: a read of project knowledge or instructions (`backbone/`, `.claude/skills/`, `AGENTS.md`, `CLAUDE.md`), not every code file;
- `skill`: a skill loaded;
- `edit`: a file written with the file tools (the path and tool, never the content);
- `tests-run`: every run of `HARNESS_TEST_CMD` by the harness, with its exit code and time;
- `hook-slow`: a hook call that took `HARNESS_HOOK_SLOW` seconds or more (default 5; 0 = off).

Each event carries the task in progress and, inside a hook, the session and agent. `harness.py trace <id> [--json]` prints a task's events in order, so a failed run can be followed step by step.

`harness.py report [--days N]` summarises the log (`--json` for machines):
- tasks finished;
- judge verdicts, and claimed passes the harness overturned;
- escalations and policy approvals;
- blocked tool calls and refused commits, by reason;
- **accepted work**: the first-pass judge rate, how many griller fails led to a spec change (a fail that changed nothing cost a round for nothing), the median time from start to finish, cost and escalations per finished task;
- **what the gates and rules catch**: refusals per gate, and how often each guardrail rule fired. A project rule that never fires may no longer apply; `report --rules` lists every rule with its count (core rules guard against rare accidents and are expected to stay quiet);
- **slow hook calls** (`HARNESS_HOOK_SLOW`);
- **harness candidates**: a failure seen across several tasks, where an instruction, rule or skill is missing: the same refusal in 3 or more tasks, the same judge failure (with the AC and REQ ids taken out) in 2 or more, the same escalation kind in 2 or more. Fix the cause in `4-KNOWLEDGE.md`, a skill or `guardrails.conf`; the report only points at it.

## Change receipt

`harness.py receipt <id> [--base <rev>] [--json]` states what the harness can prove about a judged task, built only from the spec, the verdicts and the diff:
- **Changed:** files since the base: `--base`, else the light lane's recorded start, else the policy approval's base, else the parent of the commit that added the spec, else HEAD (only the uncommitted work).
- **Verified:** the harness's own test run, and each AC with its tests, evidence and the test files that mention it.
- **Not verified:** ACs not met, NFRs no AC covers, and findings the judge left open.
- **Sandbox:** where the judge pass was recorded (`sandbox` in the JSON; see Sandbox backend and evidence). A judge pass recorded before sandbox evidence existed says "not recorded" (`null`).
- **Decisions:** the ADRs the spec follows, the ADRs the task added or changed (with their status), and the assumptions with their sources.
- **Risks**, headed by the spec's Change-Class (`change_class` in the JSON), and the number of grill, judge and debugger rounds.
- **Approval needed:** ADRs that aren't Accepted and open escalations.
- **Suggested labels** for whoever triages the pull request (`suggested_labels` with `--json`): one risk label from the spec's `Change-Class` (ADR-002) and the risks above, and `class:<class>` when the spec has a `Change-Class:` line. The class is the one `approve` and `risk` use: a spec with two different values, or a value that isn't one of the four, is labelled `class:feature`, and the receipt says why (`change_class_problem`). A spec without the line is rated as `feature` and gets no class label. The risk the class itself brings (the user approves `feature` and `schema` work) is already its step; only other risks raise the label. The labels are advisory: none approves or merges anything.

| Change-Class | No other risks | Other risks |
|---|---|---|
| `docs`, `refactor` | `risk:low` | `risk:elevated` |
| `feature`, an invalid one, or none | `risk:elevated` | `risk:high` |
| `schema` | `risk:high` | `risk:high` |

It refuses a task without a judge pass on the current code. `harness.py run` saves it next to the run logs and `--pr` puts it in the pull request; the Orca coordinator does the same and keeps it in `.git/harness/receipts/`.

**Traceability export** (ADR-004 in the agentic-harness repository). `harness.py trace export --format reqif|reqifz|needs|html [--out DIR] [--task ID]` writes every task with a spec (or `--task`) as the chain requirement → acceptance criterion → test file → judge verdict → commit. It is derived and one-way: `backbone/` and git stay the record, it makes no network call, and no gate reads it.
- **Formats:** `reqif` (ReqIF 1.2: one `SPECIFICATION` per task, requirements, criteria and test files as `SPEC-OBJECT`s, `Verifies` and `Tests` relations, `ReqIF.ForeignID`/`ReqIF.Text`/`ReqIF.Name`, the enumerations `Harness.Result` (met, not met, not evaluated, not judged) and `Harness.Verdict` (pass on the current code, pass on earlier code, fail, not judged), and `Harness.*` string attributes for the rest), `reqifz` (a ZIP archive holding that document as `traceability.reqif` and `receipts/<task>.txt`, the `harness.py receipt` of each task with a judge pass on the current code, which the task's XHTML attribute `Harness.Receipt` names), `needs` (Sphinx-Needs `needs.json`, format 1: need types `task`, `req`, `ac`, `test`, link fields `verifies` and `tests`, fields `harness_*`; ids contain dots and dashes, so a Sphinx project sets `needs_id_regex` to allow them) and `html` (one self-contained page, no script or external resource).
- **Ids:** the spec's own `REQ-`, `NFR-` and `AC-<task>-<n>`, `TASK-<task>`, and `TEST-<task>-<first 12 hex digits of the SHA-256 of the path>`. An NFR without an id is listed as a gap.
- **Verdict:** the latest judge verdict: *pass on the current code*, *pass on earlier code*, *fail* or *not judged*, with its time, code fingerprint and test run, and each criterion's result. Its commits are every commit reachable from `HEAD` whose code (the tree without `backbone/`) is the verdict's fingerprint; CI needs the full history for them. Test files are those that mention the criterion in the judged code.
- **EARS** (`HARNESS_REQ_STYLE=ears`): each requirement's pattern (ubiquitous, event-driven, state-driven, unwanted behaviour, optional feature, complex, or not an EARS pattern).
- **Output:** stdout, or `DIR/traceability.reqif`, `DIR/traceability.reqifz`, `DIR/needs.json` or `DIR/traceability.html` with `--out`. An `--out` inside the repository is refused unless git ignores it, since an untracked file counts as code and would make the judge's passes stale. The same repository state gives the same bytes.
- **Link:** `harness.py trace link <matrix-url> [--task ID]` prints the Markdown comment that links a matrix (the `harness-traceability` artifact's page, say) and names the commit it describes. It accepts only an https link with none of the characters that would end a Markdown link early or open a tag. The deliverer adds it to the pull request's body once CI passes; `linear receipt <task> --matrix <url>` adds it to the receipt comment on the ticket.

**Linear** (`harness.py linear`, user-only; agents may run only `--dry-run`). `linear import <ISSUE> --task <id> [--light] [--from <issue.json>]` writes a draft spec from the template, with a `Linear: <ISSUE> (<url>)` line and the ticket quoted in Context as source material. It also adds the pending task line, `(light)` when asked. `linear receipt <task> [--status <state>] [--matrix <url>]` posts the receipt as a comment on the ticket, with the `trace link` comment for the matrix at `<url>` when given. It refuses without a judge pass on the current code, and refuses a state that completes or cancels the ticket. Both need `LINEAR_API_KEY`; `HARNESS_LINEAR_URL` points them at another endpoint.

## Profiles (`HARNESS_PROFILE`)

`triple`: only a human merges. `harness.py orca` refuses `--merge` and `--trust`, `orca-nightly` refuses to start, and `enroll` refuses `--automation` and `--protect`. The shell gate refuses `gh pr merge` and GitHub's merge API, and the tool gate refuses any MCP tool whose name contains `merge`. `HARNESS_PROFILE=triple` or `TRIPLE_MODE=1` in the environment adds the profile; clearing the variable doesn't lift a profile set in `harness.conf`.

## CI judge and branch protection

`harness.py ci-judge --range <base>..<tip>` re-judges every task the range marks `[x]`:
- It runs a fresh judge session with `HARNESS_CI_JUDGE_CMD` (default `claude -p --agent judge ...`).
- It re-runs `HARNESS_TEST_CMD`, and applies the same re-derivation rules as the judge recorder.
- It fails unless the independent verdict is a pass.

The verdicts committed with a task were produced inside the agent's session; this one isn't. The project-owned template `.github/workflows/harness-judge.yml` runs it on pull requests when the `ANTHROPIC_API_KEY` secret is set; add your toolchain steps to it.

`harness.py ci-protect [--branch main] [--with-judge] [--dry-run]` (needs `gh`) does two things:
- requires the `verify` check (and optionally `judge`) on the branch;
- creates the `harness-change-approved` label.

`harness.py ci-protect --attest [--dry-run] [--recorded-fallback] [--delete-repo-copies]` sets up the `harness-attest` environment for the attest job, as described under the signed verdict attestation above. It states the attest mode in force (live with `HARNESS_ATTEST_POLICY_TOKEN`, the recorded-branch opt-in, or none) and whether `harness-attest.pub` is on the default branch. `--recorded-fallback` sets the opt-in variable; without it, the variable is removed. It names repository-level secrets and variables called `HARNESS_ATTEST_KEY` or `HARNESS_ATTEST_PASSWORD` and changes nothing while they exist; `--delete-repo-copies` deletes them first (put the key in the environment before, if it is only there). `harness.py doctor` states the attest mode too, when `gh` sees the repository, and warns of such copies.

Agents can't run `ci-judge` or `ci-protect`.

## Git hooks (`core.hooksPath = scripts/harness/git-hooks`)

| Hook | What it does | Blocks? |
|---|---|---|
| pre-commit | Checks added lines of staged files against block and warn rules, runs **verify** on the staged change, then runs `HARNESS_BUILD_CMD` if it is set | Yes, on a block rule, a verify problem or a failed build |
| commit-msg | Conventional Commits, types from `HARNESS_COMMIT_TYPES`, subject within `HARNESS_SUBJECT_MAX`. Merge, Revert, `fixup!`, `squash!` and `amend!` are exempt. Warns (does not block) when the scope matches no staged path, unless it is a cross-cutting scope (`HARNESS_CROSS_SCOPES`) | Yes, on format |

A fresh clone needs `git config core.hooksPath scripts/harness/git-hooks` once. `doctor.sh` and the session-start note report when it is missing.

**Another hook manager** (Husky, lefthook) may keep `core.hooksPath`. Then each of its `pre-commit`, `commit-msg` and `pre-push` hooks must call the harness's: `scripts/harness/git-hooks/pre-commit`, `scripts/harness/git-hooks/commit-msg "$1"` and `scripts/harness/git-hooks/pre-push "$@"`. With Husky (`core.hooksPath = .husky/_`), put the calls in `.husky/<hook>`. Doctor treats the hooks as active only when all three hand on, and names the ones that don't.

## Hook time budget

Claude Code treats a hook it kills for running too long as a non-blocking error, and lets the tool call through. So the harness keeps its own budget of 25 seconds, under the 30-second timeout in `.claude/settings.json`, and its `git` calls time out before that:
- `pre-tool-use` and the agents' write-scope checks **fail closed** when the budget runs out: the call is refused with "retry".
- Other hooks exit quietly.
- The griller's and judge's verdict recorders are exempt: they run the tests under `HARNESS_TEST_TIMEOUT`.

## Rule and route files

```
guardrails:  <block|warn> | <path regex, or @bash> | <content regex> | <message>
routes:      <path regex> | <skill>[, <skill>...] | <why>
```

Fields are separated by a space, a pipe and a space. Regexes use Python syntax. Guardrails match per line, and only the text being added (an edit's new text, or a staged diff's added lines).

Two files of each kind apply: the core file in `scripts/harness/`, then the project's file in `backbone/`. Stack packs adopted from an accepted ADR add their rules and routes to the project files, as blocks marked `# >>> adopted pack: <name> (ADR-NNN, ...)`. Re-adopting replaces the block, and `adopt --remove` deletes it. A block's rules belong to that ADR's decision. To change one, change the decision: write a superseding ADR, then re-adopt.

## Configuration (`backbone/harness.conf`)

`KEY="value"` lines. The file is parsed, never executed. An environment variable with the same name overrides the file.

| Key | Default | Meaning |
|---|---|---|
| `HARNESS_PROJECT_NAME` | folder name | Shown at session start |
| `HARNESS_BUILD_CMD` | empty | Run by pre-commit; empty skips it |
| `HARNESS_TEST_CMD` | empty | The test command the implementer and judge run |
| `HARNESS_TEST_PATHS` | common test layouts | Regex for test files, used for AC traceability |
| `HARNESS_COMMIT_TYPES` | `feat\|fix\|refactor\|perf\|test\|docs\|build\|ci\|chore\|style\|revert` | Allowed commit types |
| `HARNESS_SUBJECT_MAX` | `72` | Maximum length of a commit subject |
| `HARNESS_STOP_MODE` | `remind` | `remind`, `block` or `off` |
| `HARNESS_ALLOW_PARALLEL_WIP` | `0` | `1` allows several `[WIP]` tasks |
| `HARNESS_SPEC_GATE` | `on` | Start gate. User-only |
| `HARNESS_SKILL_GATE` | `on` | Skill gate. User-only |
| `HARNESS_JUDGE_GATE` | `on` | Judge gate. User-only |
| `HARNESS_JUDGE_MAX_ROUNDS` | `2` | Judge fails before escalating. User-only |
| `HARNESS_VERIFY` | `block` | `block` or `off`: verify in pre-commit. User-only |
| `HARNESS_ORCHESTRATOR_SCOPE` | `on` | Main session may not edit specs, ADRs or code. User-only |
| `HARNESS_TEST_TIMEOUT` | `900` | Seconds the judge recorder lets `HARNESS_TEST_CMD` run |
| `HARNESS_AUTONOMY` | `supervised` | `supervised` or `autonomous` (see above). User-only |
| `HARNESS_AUTO_APPROVE` | `low` | `low`: `approve` approves low-risk specs in autonomous mode; `off`: every spec is escalated. User-only |
| `HARNESS_RISK_TERMS`, `HARNESS_RISK_PATHS` | security, data, API and build terms and paths | Regexes for what is not low-risk. User-only |
| `HARNESS_RISK_MAX_FILES` | `20` | A policy-approved change touching more files is escalated. User-only |
| `HARNESS_DOC_PATHS` | Files with a documentation extension (`md`, `mdx`, `markdown`, `rst`, `adoc`, `asciidoc`, `txt`), and README, CHANGELOG, LICENSE and the like without one; not `CMakeLists.txt` or pip's requirements and constraints files | Regex for documentation. A `Change-Class: docs` change that touches anything else is a risk. A folder doesn't make a file documentation: doc-tool code (`docs/conf.py`, which Sphinx runs, MkDocs hooks), images and stylesheets count as code. MDX can import and run JSX components, and files your application reads at runtime (templates, prompts) may have these extensions: narrow the regex if your project has them. While the regex is invalid (doctor reports it), nothing counts as documentation. User-only |
| `HARNESS_GRILL_MAX_ROUNDS` | `3` | Griller fails before an autonomous escalation. User-only |
| `HARNESS_ESCALATE_GH` | `off` | `on`: escalations also open a GitHub issue (`gh`). User-only |
| `HARNESS_AGENT_CMD` | `claude -p --permission-mode acceptEdits --output-format json` | The runner's agent command (prompt on stdin). User-only |
| `HARNESS_RUN_TASK_TIMEOUT` | `3600` | Seconds per agent session in a run. User-only |
| `HARNESS_RUN_ATTEMPTS` | `2` | Sessions per task before the runner escalates it. User-only |
| `HARNESS_RUN_MAX_COST` | empty (no limit) | Dollars per run; the runner stops before the next task once spent. User-only |
| `HARNESS_SANDBOX_BACKEND` | `devcontainer` | Where the runner starts its sessions (ADR-003); `devcontainer` is the only backend. User-only |
| `HARNESS_SANDBOX_REQUIRE` | `auto` | The sandbox each Change-Class needs to start and finish; `auto` is `schema=container` in autonomous mode only (see Sandbox gate). User-only |
| `HARNESS_SANDBOX_START` | `off` | `on`: `run` on the host brings the sandbox up with the devcontainer CLI and runs each session in it (see Runner). User-only |
| `HARNESS_CI_JUDGE_CMD` | `claude -p --agent judge --dangerously-skip-permissions --output-format json` | The CI judge session. User-only |
| `HARNESS_SKILL_MAX_AGE` | `180` | Days after which doctor flags a skill's `last-verified` date; `0` turns it off |
| `HARNESS_SCOPE_CHECK` | `on` | Commit-scope warning |
| `HARNESS_CROSS_SCOPES` | `deps\|build\|ci\|docs\|backbone\|harness\|release\|config\|tests?` | Scopes exempt from the scope check (regex) |
| `HARNESS_CONTAINER_ENGINE` | empty | Container engine chosen in the stack ADR (set when a container pack is adopted) |
| `HARNESS_DECISION_PROVIDER`, `_MODE`, `_ADR`, `_CMD`, `_MODEL`, `_URL`, `_TIMEOUT` | `none`, `off`, empty, empty, empty, empty, `20` | Decision layer (see above). User-only, except the timeout |
| `HARNESS_COMMIT_NUDGE` | `8` | With no `[WIP]` task, nudge to commit at this many changed tracked files; `0` turns it off |
| `HARNESS_PROFILE` | empty | Organisation profile: empty or `triple` (see Profiles). User-only; the environment can add it, never lift it |
| `HARNESS_REQ_STYLE` | `plain` | `plain` or `ears`: with `ears`, `spec-check` requires an EARS pattern for every requirement. User-only |

## Decision layer (advisory)

Some checks need judgement that code cannot compute. The decision layer asks a model for **typed answers**, not prose: a choice among declared options, a score on a declared scale, or a yes/no probability, each with a confidence. Deterministic checks never move here, and decisions never block anything.

- **Providers:**
  - `none` (default);
  - `command`: any executable, given JSON on stdin and printing JSON on stdout, so local models fit behind it;
  - `ollama`: a local Jev-style decision endpoint (Ollama's `/v1/systemone`, default model `nimble`). Data stays on the machine, and there's no per-call cost. `HARNESS_DECISION_URL` overrides the endpoint;
  - `claude`: the Claude Messages API over plain HTTPS, with structured outputs, effort `low`, and refusal fallback. It needs no install, only `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) in the environment of whoever commits;
  - `jev`: TypeSafe Jev via `typesafe-sdk`. This adapter is written from published examples and is unverified.
- **Authorisation:** a provider receives project data (diffs and messages), so it runs only when `HARNESS_DECISION_ADR` names an **Accepted** ADR that mentions it. Choosing a provider is a design decision like any other stack choice. All `HARNESS_DECISION_*` keys are user-only.
- **Modes:** `shadow` only logs. `advise` also prints the answers that cross their thresholds. Start in shadow mode, compare the log with your own judgement, then tune thresholds before switching to advise.
- **Questions and thresholds** live in `scripts/harness/decisions.json`, versioned. The model never sees question ids, so the meaning has to be in `instructions` and the option texts. `warn_if` thresholds sit next to each question and are reviewed like code. A choice warns when its confidence reaches `min_confidence`, or when the probability of the chosen option reaches `min_probability`. Providers calibrate confidence differently: local Jev-style models report low confidence even for likely answers.
- **Log:** every call is appended to `.git/harness/decisions.jsonl`, with its state, questions, answers, latency and errors, so any change can be replayed. Summarise it with `python3 scripts/harness/lib/harness.py decisions [--last N]`.
- **Failures never block:** a timeout, error, refusal or off-schema answer is logged and ignored.

| Decision | Where | Questions |
|---|---|---|
| `commit-message` | commit-msg hook, after the format checks pass | `fit` (accurate / partial / mismatch); `unmentioned` (significant change not in the message); `leftovers` (debug prints, commented-out code, skipped tests) |

## Escape hatches

- `SKIP_BUILD=1 git commit ...` skips the build check once, and `HARNESS_VERIFY=off git commit ...` the verify check. Both are for the user in their own terminal; agents can't set them.
- Blocked destructive commands are run by the user, never rephrased by agents.
- A wrong rule or route is fixed in its file, not bypassed.

## Troubleshooting

- Run `scripts/harness/doctor.sh`. It reports inactive git hooks, missing settings hooks or agents, invalid rules or routes, routes to missing skills, locally edited harness files and empty commands.
- Run a hook by hand. For example: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 scripts/harness/lib/harness.py hook pre-tool-use`.
- Session skill state lives in `.git/harness/sessions/`, outside the repository content.
