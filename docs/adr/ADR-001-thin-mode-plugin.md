# ADR-001: Thin mode: the engine ships as an agent plugin, the project keeps its state and a version pin

## Status
Accepted

## Date
2026-11-03

## Context
Today `bootstrap.sh` vendors the whole harness into every project: the runtime (`scripts/harness/`), `AGENTS.md`, the
role agents and core skills, and the hook wiring for Claude Code, Codex and OpenCode. Each project then needs
`update.sh` for every release. With many projects, this means hundreds of copied files per repository and a version
spread that nobody chose.

All three agent CLIs can now load extensions once per machine:

- **Claude Code** plugins carry hooks (`hooks/hooks.json`, with `${CLAUDE_PLUGIN_ROOT}`), agents, skills and MCP
  servers. A project's `.claude/settings.json` can name the marketplace (`extraKnownMarketplaces`) and the plugin
  (`enabledPlugins`), so teammates are offered it.
- **Codex** plugins carry hooks, skills and MCP servers, but **not agents**. Codex looks for `.codex-plugin/plugin.json`
  before `.claude-plugin/plugin.json`, gives hook commands `PLUGIN_ROOT` (and `CLAUDE_PLUGIN_ROOT`), and asks the user
  to trust a plugin's hooks before they run.
- **OpenCode** loads global plugins from `~/.config/opencode/plugins/` or npm, and agents from
  `~/.config/opencode/agents/`.

Some things can't move out of the project, though:

- The project state (`backbone/`) is the audit trail.
- `verify` reads specs and verdicts from git (`show(rev, name)`).
- CI's `harness-verify` checks every pull request with the **base branch's** verifier, so a pull request can't weaken
  the check that gates it.

The engine can leave the project; the state and the enforcement floor stay.

## Decision
Add a **thin install mode** alongside the full (vendored) mode. In thin mode, the engine comes from an agent plugin
installed once per machine, and **the version that runs is chosen by a pin in the repository**, not by the plugin.

### What stays in the repository
| Path | Why |
|---|---|
| `backbone/` (specs, ADRs, verdicts, `harness.conf`, `routing.conf`, `guardrails.conf`, `tools.conf`) | project state and audit trail |
| `backbone/.harness-lock.json` with `"mode": "thin"`, `"version"` and `"commit"` | the pin |
| `.github/workflows/harness-verify.yml` | the CI floor |
| `.githooks/pre-commit` (a shim, a few lines) | `verify` on the staged change after a fresh clone |
| `CLAUDE.md`, adopted pack skills in `.claude/skills/<pack>/`, project skills | project-specific, tied to ADRs |
| `.claude/settings.json` entries `extraKnownMarketplaces` and `enabledPlugins` | offers the plugin to teammates |

These leave the repository: `scripts/harness/`, `AGENTS.md`, the core agents and skills, `.codex/` and `.opencode/`.

### Packaging
This repository is the plugin and its own marketplace. Nothing in `payload/` moves.

- `.claude-plugin/plugin.json` and `marketplace.json`: the manifest points `agents`, `skills` and `hooks` at the
  existing `payload/owned/...` paths.
- `.codex-plugin/plugin.json`: the Codex hooks (`--from codex`) and the skills.
- An npm package for OpenCode wrapping `payload/owned/.opencode/plugins/harness.js`.

Every hook calls one **launcher**, `launcher.py hook <event> --from <cli>`. It is small and its interface stays stable
across releases.

### The launcher picks the engine
1. It finds the project root: `git rev-parse --show-toplevel` from the hook's working directory.
2. **Opt-in**: no thin lock means the repository isn't enrolled, so it exits 0 at once. The not-enrolled warning that
   `machine/guard.py` gives today moves here, governed by the same `~/.agentic-harness/machine.json`.
3. **Full installs win**: a repository with a vendored `scripts/harness/lib/harness.py` keeps its own hooks; the
   launcher exits 0, so nothing is gated twice.
4. It runs the pinned engine from `~/.agentic-harness/engines/<version>/`, a checkout of the tag, fetched once.
   - It checks that the checkout's commit equals the pinned `commit`, so a moved tag is refused.
   - The cache is shared by Claude Code, Codex, OpenCode and the pre-commit shim, so it is not in a CLI's plugin data
     folder.
5. It runs `harness.py` with `HARNESS_ROOT` set to the project root.

**It fails closed.** If the pinned engine can't be fetched or checked, the hook refuses everything except reads and
says why, the same as a gate that can't be evaluated. Turning gates off stays user-only (`harness.conf`).

### CI keeps the base branch's verifier
- `harness-verify` reads the pin from the **base** branch and checks out `soyPeter/agentic-harness` at that commit.
- It runs `verify --range` with that engine.
- A pull request that bumps the pin is checked by the old engine, so a pull request still can't weaken its own gate.
- The repository is public, so no token is needed.

### Plugin version and pinned engine
Agents and skills come from the plugin, but the hook logic comes from the pinned engine.

- A plugin release and an engine release are the same tag of this repository.
- `session-start` reports when the plugin's version differs from the pin.
- In autonomous mode, a mismatch blocks the run until it is fixed.
- Where a CLI can pin the plugin version in project settings, `init` writes that pin too.

### Engine changes
- **Project root**: `ROOT` falls back to the git toplevel of the working directory when `HARNESS_ROOT` is unset and
  the engine isn't inside a project (`harness.py:53`).
- **Skills and agents**: they resolve from the plugin first, then the project.
  - This affects the skill gate (`load_skills` and its checks near `:621` and `:731`), the doctor's agent check
    (`:2245`) and context tracking (`:2892`).
  - The orchestrator allowlist keeps allowing project skills only.
- **Namespaced agent names**: Claude Code prefixes plugin agents (`agentic-harness:judge`).
  - `:1272` must strip the prefix, as `:4689` and `:4766` already do.
  - The Claude Code agent-name matchers must accept both forms.
- **Codex role agents**: Codex plugins can't ship agents, so the launcher installs the generated ones into
  `~/.codex/agents/` on `session-start`. OpenCode's go into `~/.config/opencode/agents/`.
- **Protection**: the pin (`backbone/.harness-lock.json`), the engine cache and the plugin root become enforcement
  files.
  - An agent can't write them, not even by absolute path or through a shell command.
  - An agent that could lower the pin locally could pick a weaker engine.
- **AGENTS.md**: its text is injected as context by `session-start` instead of living in the repository. The thin
  `CLAUDE.md` seed drops the `@AGENTS.md` import.

### Commands
- `harness.py init --thin` (also `/agentic-harness:init`) writes:
  - the `backbone/` seed;
  - the lock with the pin;
  - `harness-verify.yml`;
  - the pre-commit shim, setting `core.hooksPath=.githooks`;
  - the plugin entries in `.claude/settings.json`.
- `harness.py pin <version>` (user-only) moves the pin and refreshes the commit.
- `update.sh --to-thin <repo>` converts a full install. It deletes harness-owned files that are unedited, keeps edited
  ones as `*.harness-bak`, and writes the pin.
- `update.sh --to-full <repo>` goes back.

## Alternatives considered
- **Plugin version decides the engine (no pin)**: the simplest option. But two developers, or a developer and CI,
  would run different gates on the same commit, and an upgrade would land in every project at once, unreviewed.
- **Private mode (harness state git-ignored, nothing in the repository)**: considered for repositories where others
  don't use the harness. It loses the CI floor, the team's shared specs and the git-based verify, so it is not this
  decision.
- **Stripping harness files at push time (filters, rewriting commits)**: fragile, and it breaks `verify`, which reads
  the committed state.
- **Keep the full install only**: no work, but the copying and the version spread stay.

## Consequences
- **Easier**:
  - Setting up a project means committing its state, a pin, one workflow and one shim.
  - Upgrading a project is a reviewed change to one line.
  - One install per machine serves every enrolled project in all three CLIs.
- **Harder**:
  - The first session after a pin change needs the network, or the hooks refuse.
  - The plugin's agents and skills can drift from the pinned engine; this is reported, not prevented, in supervised
    mode.
  - Codex and OpenCode agents are user-level, so two projects pinned to different versions share one set.
  - Codex asks the user to trust the plugin's hooks once.
- **Unchanged**:
  - Teammates without the plugin get no gates in their agent, as today without hooks; `harness-verify` still stops
    the merge once the branch is protected.
  - Full mode keeps working, and the launcher defers to it.
- **Follow-up work**, each as its own change with tests in `tests/run-tests.sh`:
  1. Project-root fallback and the skill/agent lookup in the engine.
  2. The launcher with the engine cache, commit check and fail-closed refusal.
  3. The plugin manifests and marketplace.
  4. `init --thin`, `pin`, and the pre-commit shim.
  5. `harness-verify.yml` fetching the base branch's pinned engine.
  6. Protection for the pin, engine cache and plugin root.
  7. Installing the Codex and OpenCode agents at user level.
  8. `update.sh --to-thin` / `--to-full`.
  9. Folding `machine/guard.py` into the launcher.
  10. README and CHANGELOG.
