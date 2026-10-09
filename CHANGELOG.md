# Changelog

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
- **Catalog packs** were rewritten against the review findings (Java 25 API fixes, no Spring/Lombok/JPA in examples), with every tool choice made conditional on an option:

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
