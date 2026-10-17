# Agentic Harness

A stack-agnostic harness for AI coding agents such as Claude Code. Install it into any git repository and every task goes through a **defined, gated pipeline**:

```
 DEFINE                                   BUILD                 JUDGE                  RECORD
 analyst ─> architect ─> griller ⇄ user   implementer           judge                  scribe
 spec:      ADRs +       questions,       code + tests          requirements, ACs,     memory +
 REQ, AC    tech reqs,   verdict          (skills loaded        tests -> verdict       emergent ADRs
 (G/W/T)    skills                        per path)
        └──── start gate ────┘      └─ skill gate ─┘   └── judge gate ──┘
   valid spec + griller pass on      routed + spec      pass on current code,
   current spec/ADRs + USER          skills loaded      every AC traced to a
   approval  ->  [WIP]               before any edit    passing test  ->  [x]
```

- **Definition first**: one spec per task (`backbone/specs/<id>.md`) holds numbered requirements, Given/When/Then acceptance criteria, NFRs, the ADRs it follows and the skills it needs. A PRD is optional; ADRs are mandatory.
- **Grilling**: an adversarial `griller` agent questions the spec and its ADRs. Its questions go to the user, the spec is revised, and grilling repeats until it passes. Then the **user** approves the spec. Only the user can write the approval line, and an approved spec is frozen.
- **Skill routing**: `routing.conf` maps paths to skills. ADRs need `adr-writing`, `architecture` and the language skill; controllers need `api-design` and `openapi`; and so on. The spec adds what the task needs. An agent can't edit a file until it has loaded every required skill in its session.
- **Judging**: an independent `judge` checks every requirement and acceptance criterion against the code and tests. The verdict is recorded by a hook, which re-derives it from the evidence: an AC without a test that mentions its id, unmet criteria or failing tests all turn a claimed pass into a fail. The recorder runs the test command itself rather than trusting the judge's report. Verdicts are tied to a fingerprint of the code, so any later change makes them stale.
- **Guardrails** throughout: destructive commands, secrets and project rules are blocked. Each agent can only write its own files, and the main session only orchestrates. Shell commands can't write harness state or switch off checks. One task is `[WIP]` at a time. Commits follow Conventional Commits. The gates are on by default and only the user can switch them off.
- **Autonomous mode** (opt-in, user-only): no human in the loop. The harness approves low-risk specs by policy, from the spec and later the diff. Everything else, including repeated griller or judge failures, is escalated: the task is parked as BLOCKED, an entry goes into `backbone/escalations.md` (optionally a GitHub issue), and work continues. A kill switch halts everything.
- **Agent CLIs**: the same gates for Claude Code, Codex and OpenCode. Each CLI's hooks (`.claude/settings.json`, `.codex/hooks.json`, `.opencode/plugins/harness.js`) call one normalising entry point, and the Codex and OpenCode role agents are generated from the Claude Code ones.
- **Orca coordinator** (`harness.py orca`): drives tasks in parallel with Orca supervised workers, one per step and one worktree per task. Questions between agents are answered from the sources into the spec, and the agent can differ per role.
- **Coordinator API**: `state`, `next`, `questions`, `start` and `finish` let a coordinator (Orca, a script) drive tasks without knowing the workflow.
- **Knowledge source** (opt-in, user-only): in autonomous mode, griller questions `backbone/` can't answer are looked up in a read-only notes vault behind an MCP server (`knowledge`). Clear answers are recorded with a `vault:<path>` citation the harness checks; the rest are escalated.
- **Runner and CI**: `harness.py run` drives ready tasks unattended (optionally one worktree, branch and PR per task, with a cost budget), one fresh agent session per task, with time and attempt budgets, escalating stalls. The installed `harness-verify` workflow re-checks every pull request with the **base branch's** verifier, so a pull request can't weaken the check that gates it. `harness.py report` summarises the event log.
- **Verify**: the pre-commit hook re-checks the gates on the staged state, and CI runs the same check on a pull request's commits (`harness.py verify --range`), so a change made any other way is still caught.
- **Safe updates**: harness files are tracked by hash. Local edits are detected and never overwritten silently.

The harness never generates application code. On the first session, the agent interviews you to fill in the project's knowledge, stack ADR, language skill and routes.

Requirements: `git` and `python3` (3.8 or later, standard library only).

## Stack-neutral by design

The harness assumes no language, framework or tool. The stack is decided in the **design phase**: the architect records it in an ADR, and you accept it. Only then does the project adopt matching packs from the catalog, which ships with every install but stays inert:

```sh
python3 scripts/harness/lib/harness.py catalog          # packs, when each applies, options the ADR must decide
python3 scripts/harness/lib/harness.py adopt java,quarkus --adr ADR-002 \
        --with gradle,junit5-assertj,no-lombok,no-spring,hexagonal-layers,named-use-cases
python3 scripts/harness/lib/harness.py adopt --remove quarkus     # when a later ADR changes the stack
```

Adoption refuses unless:
- the ADR is Accepted and names the pack;
- every option of the pack is decided.

It then installs the pack's skills, writes its routes and guardrails into the project's `routing.conf` and `guardrails.conf` as blocks citing the ADR, and sets related `harness.conf` values such as the build and test commands.

| Pack | Applies when the ADR chooses | Options to decide |
|---|---|---|
| `java` | Java | build tool `gradle` / `maven`; `junit5-assertj`; `no-lombok` |
| `quarkus` (requires java) | Quarkus | `no-spring`; `hexagonal-layers`; `named-use-cases` |
| `jdbi` (requires java) | JDBI for data access | `no-orm`; `hexagonal-layers`; `flyway` |
| `container` | Container images | engine `podman` / `docker` |

Stacks without a pack get project skills written during design, routed in `backbone/routing.conf`.

## Install into a project

```sh
./bootstrap.sh /path/to/repo [--name my-service] [--git-init] [--dry-run]
cd /path/to/repo && git add -A && git commit -m "chore: adopt agentic harness"
```

Then start an agent session in that repo. It reports **SETUP INCOMPLETE** and runs first-run setup with you (`AGENTS.md` section 1).

After a fresh clone, each developer runs this once to activate the git hooks:

```sh
git config core.hooksPath scripts/harness/git-hooks
```

## Update a project

```sh
./update.sh status /path/to/repo           # what is outdated or edited locally
./update.sh /path/to/repo [--dry-run]      # apply
./update.sh /path/to/repo --force          # also replace locally edited harness files (keeps *.harness-bak)
```

| Situation | Result |
|---|---|
| Harness file unchanged locally | Replaced with the new version |
| Edited locally, no upstream change | Kept |
| Edited locally and changed upstream | Kept; new version written to `<file>.harness-new` (exit code 1) |
| Removed from the harness | Deleted if unedited, otherwise left in place |
| Project file (`seed`) | Never rewritten; missing ones are created. New `harness.conf` settings are appended commented out, with their explanation, so nothing changes until you uncomment one |
| `.claude/settings.json` | Harness hook entries replaced; everything else kept |

## Enforce it everywhere

The harness enforces itself inside each project (agent hooks, git hooks, CI). Three tools make sure every project
has it and every agent loads it:

- **`./enroll.sh <project> [--orca] [--automation daily] [--agents "default=claude judge=codex"] [--protect]`**:
  - installs or updates the harness and runs the doctor;
  - registers the project in Orca;
  - with `--automation <schedule>`, creates one Orca automation per checkout: its precheck, which Orca runs itself, starts `harness.py orca --merge --trust` in its own Orca terminal (`harness.py orca-nightly`), and its agent reports the previous run's digest (`harness.py orca-digest`);
  - sets the agent per role;
  - with `--protect`, requires the CI checks on the GitHub default branch, keeping its existing checks and rules.

  `--dry-run` shows what it would do. Enrolling again is safe.
- **`./machine.sh install [--roots ~/Work/repos] [--mode warn|block]`**: a user-level guard hook for Claude Code and
  Codex on this machine. In a git repository under the roots that has no harness, it reminds you (warn) or refuses
  file edits (block) until the repository is enrolled; enrolled repositories are left to their own hooks. Codex asks
  you to trust the new hook once (`/hooks`). `machine.sh status` and `machine.sh remove` show and undo it.
  - `machine.sh managed --out DIR` writes the same guard as Claude Code `managed-settings.json` and Codex
    `requirements.toml`, which nobody on the machine can switch off. Review them and install with sudo (see the
    generated INSTALL.md); the tool never writes system files.
- **`orca/skills/agentic-harness/SKILL.md`**: the Orca skill for coordinators you run by hand. It says to check for
  the harness, prefer `harness.py orca`, and otherwise follow the gates (`harness.py next` before every step, command
  steps through the harness, answers recorded in the spec with their source, prompts left to the user). Share it with
  `orca skills share`.

The hard floor stays CI: an agent without hooks, or a human with `--no-verify`, still can't merge past
`harness-verify` once the branch is protected.

The guard's limits: it needs `python3` and `git` on the PATH, and when its own lookup fails (no git, a broken
config) it lets the call through rather than stop every agent on the machine. It checks the repository of each file
a tool writes and, for shell commands, the working directory plus every path and `cd` target the command names. A
shell command that builds a path at run time (a variable, a computed string) can still reach another repository unseen.
In block mode the only shell command it lets run in an unenrolled repository is the harness's own `enroll.sh`.

## What gets installed

| Path | Owner | Notes |
|---|---|---|
| `AGENTS.md` | harness | Agent instructions: setup, pipeline, protocol, guardrails |
| `CLAUDE.md` | project | `@AGENTS.md` import plus Claude-specific notes |
| `.claude/agents/` | harness | `analyst`, `architect`, `griller`, `tester`, `implementer`, `judge`, `debugger`, `scribe`, with scoped hooks |
| `.codex/hooks.json`, `.codex/agents/` | harness | Codex: the harness hooks and the role agents (generated) |
| `.opencode/plugins/harness.js`, `.opencode/agents/` | harness | OpenCode: the adapter plugin and the role agents (generated) |
| `.claude/skills/` | harness + project | Core: `requirements-writing`, `adr-writing`, `architecture`, `api-design`, `openapi`, `code-quality`, `module-testing`, `security`, `changelog`. Adopted pack skills. Yours: anything else |
| `scripts/harness/catalog/` | harness | Stack packs, inert until adopted from an accepted ADR |
| `backbone/0-START-HERE.md`, `8-WORKFLOW.md`, `HOOKS.md`, `SKILLS.md`, `templates/` | harness | Map, pipeline and DoD, hooks and gates, skill format, spec and ADR templates |
| `backbone/1-PRD.md` … `7-CONVENTIONS.md`, `9-AGENT-SKILLS.md`, `adr/ADR-001` | project | Created with `{{FILL: …}}` placeholders |
| `backbone/specs/`, `backbone/adr/` | project | One spec per task; one ADR per decision |
| `backbone/harness.conf`, `guardrails.conf`, `routing.conf` | project | Commands and gate switches; project rules; skill routes |
| `backbone/.verdicts/` | hooks | Griller and judge verdicts per task, with fingerprints (audit trail) |
| `backbone/.harness-lock.json` | harness | Installed version and file hashes |
| `scripts/harness/` | harness | Runtime (`lib/harness.py`), git hooks, core rules and routes, `doctor.sh` |
| `.github/workflows/harness-verify.yml` | harness | CI: `verify --range` with the base branch's verifier on every pull request |
| `.github/workflows/harness-judge.yml` | project | CI: an independent judge session re-judges tasks a pull request finishes (needs `ANTHROPIC_API_KEY`; add your toolchain) |
| `.devcontainer/harness-agent/` | harness | Sandbox for unattended runs: outbound allowlist, trusted workspace, no prompts (checked; has run a real task end to end) |
| `.claude/settings.json` | shared | Merged: harness hook entries plus a few read-only permissions |

Check the state of a task's definition with `python3 scripts/harness/lib/harness.py spec-check <id>`, and the harness with `scripts/harness/doctor.sh`.

## Repository layout

```
bootstrap.sh, update.sh         entry points (thin wrappers)
tools/installer.py              install, update and status logic
tools/gen_agents.py             generates the Codex and OpenCode agents from .claude/agents/
tools/enroll.py, enroll.sh      enroll a project (install or update, Orca, automation, CI protection)
tools/machine.py, machine.sh    the machine guard (user level, or managed files to install)
machine/guard.py                the guard hook itself
orca/skills/agentic-harness/    the Orca skill for coordinators
payload/owned/                  harness-owned files, replaced on update
payload/seed/                   project-owned templates, created once
payload/settings.fragment.json  hooks and permissions merged into .claude/settings.json
catalog/<pack>/pack.json        pack metadata: when it applies, requirements, option groups and options
catalog/<pack>/install/         files adopted into the project (skills, scripts)
catalog/<pack>/{guardrails,routing}.conf  base rules; catalog/<pack>/options/<id>/ option-specific files
tests/run-tests.sh              end-to-end self-test in throwaway repos
VERSION, CHANGELOG.md
```

## Developing the harness

- Run `tests/run-tests.sh` after every change. It installs into temporary repos and runs the whole pipeline (define, grill, approve, build, judge) plus every hook, rule and update path.
- Bump `VERSION` and add a `CHANGELOG.md` entry for each release. Projects see the version at session start and in `update.sh status`.
- Keep `payload/owned` stack-neutral. Stack knowledge goes into catalog packs, and every tool or policy choice inside a pack is an option the ADR decides.
- Never write a literal FILL placeholder (two braces, FILL, colon) into a harness-owned backbone doc, or projects will count it as unfinished setup.
