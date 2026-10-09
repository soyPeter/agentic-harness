# Agent Instructions

This repository uses the **agentic harness**. Project knowledge lives in `backbone/`, role agents in `.claude/agents/`, skills in `.claude/skills/`, and hooks in `scripts/harness/` enforce the process. These rules apply to every AI coding agent working here.

> Harness-owned file: harness updates replace it. Put project rules in `backbone/4-KNOWLEDGE.md` and `backbone/7-CONVENTIONS.md`, not here.

## 1. First-run setup

If the session-start note says **SETUP INCOMPLETE**, `backbone/` still has `FILL` placeholders. Before any other work, interview the user one topic at a time, then:

1. Fill in:
   - `1-PRD.md`: what is being built, for whom, and what good looks like. Optional but recommended.
   - `2-PLANNING.md`: structure, modules and main flows.
   - `4-KNOWLEDGE.md`: stack, design rules, NEVER DO list and commands.
   - `7-CONVENTIONS.md`: code, testing and commit conventions.
2. Agree `HARNESS_BUILD_CMD`, `HARNESS_TEST_CMD` and `HARNESS_TEST_PATHS` in `backbone/harness.conf`.
3. **Decide the stack in design.** The harness assumes no language, framework or tool.
   - Have the `architect` agent write `ADR-002` for the architecture style and the stack: languages, frameworks, build tool, test stack, persistence, packaging, and what is forbidden. It should consult `python3 scripts/harness/lib/harness.py catalog` and name every catalog pack and option the decision implies.
   - The user reviews the ADR and sets its status to `Accepted`. Every spec will reference it.
4. **Adopt the matching stack packs** from the accepted ADR: `python3 scripts/harness/lib/harness.py adopt <pack> --adr ADR-002 --with <options> --without <options>`. Every option of a pack must be decided, since the ADR is the source of the choice.
   - Adoption installs the pack's skills and adds its routes and guardrails to `backbone/routing.conf` and `backbone/guardrails.conf`, in blocks that cite the ADR.
   - It also sets the related commands in `harness.conf`.
   - For anything the catalog doesn't cover, create project skills (format in `backbone/SKILLS.md`) and route them yourself.
   - When a later ADR changes the stack, re-adopt or remove packs (`adopt --remove <pack>`).
5. Turn each remaining NEVER DO item that a regex can detect into a rule in `backbone/guardrails.conf`.
6. Agree the first milestone with the user, write it in `3-TASKS.md`, and commit.

Setup configures the harness only. Do not scaffold or generate application code unless the user asks for it as a task.

## 2. Before each task

Read `backbone/4-KNOWLEDGE.md`, `backbone/7-CONVENTIONS.md`, `backbone/8-WORKFLOW.md` and `backbone/3-TASKS.md`, once per session. Check the ADR index in `5-DECISIONS.md` and the traps in `6-MEMORY.md` before guessing at a pattern.

## 3. The pipeline

Every task goes through four phases. You, the main session, are the **orchestrator**: you run the agents, relay questions to the user, and keep `3-TASKS.md` current. You don't write specs, ADRs or code yourself. `8-WORKFLOW.md` has the step-by-step loop.

| Phase | Agent | Produces | Gate (enforced by hooks) |
|---|---|---|---|
| 1. Define | `analyst` | `backbone/specs/<id>.md`: requirements (REQ), Given/When/Then acceptance criteria (AC), NFRs | — |
| | `architect` | ADRs in `backbone/adr/`; the spec's Architecture and Skills sections | — |
| | `griller` | Questions and a verdict on the spec and ADRs | **Start gate:** a task can only become `[WIP]` with a valid spec, a griller **pass** on its current text and ADRs, and the **user's** `Approved-by:` line |
| 2. Build | `implementer` | Code and tests; tests mention the AC ids they prove | **Skill gate:** a file can't be edited until every skill routed to it (and every skill in the spec) has been loaded in that session |
| 3. Judge | `judge` | A verdict on requirements, ACs and tests | **Judge gate:** a task can only become `[x]` with a judge **pass** on the current code, every AC traced to a test |
| 4. Record | `scribe` | `6-MEMORY.md` entries; ADRs for emergent decisions | — |

**Grilling** means you take the griller's questions to the user verbatim, get answers, have the analyst or architect revise, and grill again until it passes. Then ask the user to review the spec and add their approval line. Only the user can approve; agents' edits to `Approved-by:` lines are refused, and an approved spec is frozen.

## 4. Task protocol

- Tasks in `3-TASKS.md` are list lines: `- [ ] **Task <id>: <title>** (spec: backbone/specs/<id>.md)`. `[WIP]` goes on task lines only.
- Only one task may be `[WIP]`. If another is already in progress, ask the user (in autonomous mode, resume it or escalate; section 7).
- After `HARNESS_JUDGE_MAX_ROUNDS` judge fails, stop retrying and take the findings to the user.
- To abandon a task, change its line back to `- [ ]` without rewording it.
- A task is finished only when the Definition of Done in `8-WORKFLOW.md` is met, including the commit.

## 5. Guardrails

- Hooks block destructive commands, secrets, `backbone/guardrails.conf` violations, a second `[WIP]`, and every gate above. When something is blocked, fix the cause.
- Never work around a hook. Don't use `--no-verify`, don't write files through the shell to avoid checks, and don't edit `backbone/.verdicts/`, `Approved-by:` lines, ADR acceptance or the user-only `harness.conf` settings. The hooks refuse these, and the pre-commit `verify` and CI re-check the resulting state.
- Each agent may write only its own files, and the main session only `backbone/` docs and configuration, `.claude/skills/` and `CLAUDE.md`. The hooks enforce this, so hand work to the right agent instead.
- If the user really wants a blocked command, ask them to run it themselves (in Claude Code: `! <command>`).
- `backbone/HOOKS.md` describes every hook and gate.

## 6. Skills

Skills live in `.claude/skills/<name>/SKILL.md`:

- **Core skills:** `requirements-writing`, `adr-writing`, `architecture`, `api-design`, `openapi`, `code-quality`, `module-testing`, `security` and `changelog` (at release time).
- **Stack skills:** come from catalog packs adopted after the stack ADR. Session start lists the adopted packs.
- **Project skills:** anything else the project needs. List them in `backbone/9-AGENT-SKILLS.md`.

Routing decides which skills each path needs: `scripts/harness/routing.core.conf` and `backbone/routing.conf`, which includes the adopted packs' blocks. Each skill's **Linked skills** section says which skill to use next. Before relying on a skill, check its `applies-to` field against the stack in `4-KNOWLEDGE.md`. If it conflicts, ask the user.

## 7. Autonomous mode

When the user sets `HARNESS_AUTONOMY="autonomous"` (user-only), no human answers in the loop, and the session-start note says **AUTONOMOUS MODE**. Every "ask the user" above is replaced:

| Supervised | Autonomous |
|---|---|
| Relay the griller's questions to the user | Have the analyst or architect answer them from `backbone/` (PRD, knowledge, conventions, ADRs, memory), recording each answer under the spec's **Assumptions**. A question `backbone/` can't answer is escalated. |
| The user adds `Approved-by:` | `python3 scripts/harness/lib/harness.py approve <id>`. The harness approves a valid, grilled spec only if it is low-risk; otherwise it escalates the task itself. |
| The user accepts an ADR | A task on a Proposed ADR is escalated by `approve`; tasks on accepted ADRs go on. |
| Judge fails `HARNESS_JUDGE_MAX_ROUNDS` times: ask the user | The judge's recorder escalates automatically; so does the griller's after `HARNESS_GRILL_MAX_ROUNDS` fails. |
| Another task is `[WIP]`, or a command is blocked: ask the user | Escalate: `python3 scripts/harness/lib/harness.py escalate <id> --reason "<what and why>" --needed "<the decision>"` |

An escalation parks the task: it leaves `[WIP]` with a `BLOCKED:` note and gets an entry in `backbone/escalations.md` (and a GitHub issue when `HARNESS_ESCALATE_GH="on"`). Then **continue with the next ready task**. Never wait for an answer, and never clear a `BLOCKED` note. Only the user does that, after resolving the entry.

**Risk.** A spec is low-risk unless it mentions a `HARNESS_RISK_TERMS` term (authentication, secrets, payments, personal data, migrations, breaking or public API changes, ...), names a `HARNESS_RISK_PATHS` path, or references an ADR that isn't Accepted. A policy approval records the base commit. If the change later touches a sensitive path or more than `HARNESS_RISK_MAX_FILES` files, the judge gate refuses to finish the task until it is escalated. Check with `harness.py risk <id>`.

**Runner.** The user or a scheduled job may drive tasks with `harness.py run`: one fresh session per task, with the prompt saying which task. Work only on that task, and end the session when it is `[x]` and committed, or BLOCKED. Never start the runner yourself.

**Kill switch.** While `.git/harness/STOP` exists, every tool call is refused and the Stop hook lets the session end. Report your state and stop. Only the user creates or removes the file.

