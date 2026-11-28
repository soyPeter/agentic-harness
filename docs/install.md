# Install and update

Two ways to put the harness into a git repository: a full install copies the engine into the project, and thin mode
runs it from an agent plugin at the release the project pins. Either way the project keeps its state in `backbone/`.
Requirements: `git` and `python3` (3.8 or later, standard library only).

## Full install

```sh
./bootstrap.sh /path/to/repo [--name my-service] [--git-init] [--dry-run]
cd /path/to/repo && git add -A && git commit -m "chore: adopt agentic harness"
```

Then start an agent session in that repo. It reports **SETUP INCOMPLETE** and runs first-run setup with you (`AGENTS.md` section 1).

To keep the engine out of the project instead, install it in [thin mode](#thin-mode).

After a fresh clone, each developer runs this once to activate the git hooks:

```sh
git config core.hooksPath scripts/harness/git-hooks
```

## Update a full install

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

To switch a project between this full install and thin mode, see [Thin mode](#thin-mode).

## Thin mode

In thin mode the engine isn't copied into the project: an agent plugin, installed once per machine, runs the release
the project pins ([ADR-001](adr/ADR-001-thin-mode-plugin.md)). The project keeps `backbone/` (its state, with the
pin in `backbone/.harness-lock.json`: `"mode": "thin"`, `"version"`, `"commit"`), `CLAUDE.md`, its own and adopted
skills, `.github/workflows/harness-verify.yml`, a pre-commit shim in `.githooks/` and the plugin entries in
`.claude/settings.json`. `scripts/harness/`, `AGENTS.md`, the core agents and skills, `.codex/` and `.opencode/` come
from the plugin and the pinned release. Thin mode needs a release that has it (0.30.0 or later).

**Install the plugin** for each agent CLI you use, at the release your projects pin:

- Claude Code: `/plugin marketplace add soyPeter/agentic-harness#v<version>`, then
  `/plugin install agentic-harness@agentic-harness`. A thin project names both in `.claude/settings.json`, so Claude
  Code offers them to teammates.
- Codex: `codex plugin marketplace add soyPeter/agentic-harness --ref v<version>`, then
  `codex plugin add agentic-harness@agentic-harness`. Codex runs the plugin's hooks once you trust them (`/hooks`).
- OpenCode: a global plugin file, `~/.config/opencode/plugins/agentic-harness.js`, containing
  `export { default } from "/path/to/agentic-harness/plugin/opencode.js";`, where the path is a checkout of the
  release.

Codex and OpenCode plugins can't ship agents, so session start installs the pinned release's role agents in the
user's agents folder.

**Start a project** from its repository root, then commit what it writes:

```sh
python3 /path/to/agentic-harness/plugin/launcher.py init --thin [--version <version>] [--name my-service]
```

In Claude Code, `/agentic-harness:init` does the same. It fetches and checks the release, then writes the project seed
(`backbone/`, `CLAUDE.md`), the pin, `harness-verify.yml`, the shim with `core.hooksPath=.githooks`, the sandbox
(`.devcontainer/harness-agent/`) and the plugin entries. After a fresh clone, each developer runs `git config core.hooksPath .githooks` once.

**Upgrade** by moving the pin and the plugin together: see [Upgrade a thin project](#upgrade-a-thin-project).

Agents run the pinned engine from the plugin or the engine cache, with the commands the engine lists for agents.
`pin`, `init --thin` and the user-only commands are yours to run in a terminal
([HOOKS.md](../payload/owned/backbone/HOOKS.md#the-agent-clis-own-configuration)).

**Switch an installed project**:

```sh
./update.sh --to-thin /path/to/repo [--version <version>] [--dry-run]   # full install -> thin mode
./update.sh --to-full /path/to/repo [--force] [--dry-run]               # thin mode -> full install
```

- Both need a clean working tree and check everything before they write. If a write fails part way (permissions, a
  full disk), they undo their changes. On a project that is already switched, they change nothing.
- `--to-thin` pins the installed release, or `--version`. It deletes each harness file you haven't edited and keeps
  an edited one as `<file>.harness-bak`. `backbone/`, `CLAUDE.md` and adopted packs' files stay as they are, and so
  does the sandbox, brought to the pinned release as `update.sh` would (an edited file whose release copy changed gets
  a `<file>.harness-new`, and the switch exits 1). The pin
  keeps the hashes the full install recorded for the harness's files among them (`"kept"`) and the install date.
  `harness.py adopt` and `adopt --remove` work from these hashes as they do from a full install's, so a pack can be
  adopted again after the pin moved, and removing one deletes the files you haven't edited. Adopting again never
  overwrites an edited pack file: it keeps the edit, and when the release changed that file too, writes the release's
  copy to `<file>.harness-new` and exits 1, as `update.sh` does; an existing `<file>.harness-new` is never written over,
  and `adopt` refuses until you merge it or delete it. Adopting again while such a `<file>.harness-new` is still there
  reports it as pending and exits 1 until it is gone. An edited file that a dropped option leaves behind is kept, and
  adding the option back treats it as an edited pack file. The switch adds the shim,
  `core.hooksPath=.githooks` and the plugin entries, and takes the harness's hooks and the installed release's
  permission rules out of `.claude/settings.json` (a rule of yours that the harness also adds goes with them, and comes
  back with `--to-full`). With `--version`, it fetches the installed release to read those rules, and refuses if it
  can't. If another hook manager owns `core.hooksPath`, it refuses unless `--force-hooks-path`.
- `--to-full` installs the pinned release's files as `update.sh` would, with the kept hashes telling your edits apart,
  including after the pin moved: a file you haven't edited becomes the release's copy; an edited one is kept, and if
  the release changed it too, its copy goes to `<file>.harness-new` (exit code 1), or `--force` replaces it (keeping
  `<file>.harness-bak`). New `harness.conf` settings are appended, commented out. It takes the shim and the plugin
  entries out again. It uses the installer of the checkout you run it from, with the pinned release's files: run it
  from a checkout of that release or a later one.
- Commit the switch. Its pull request needs the `harness-change-approved` label, like any harness change. After
  `--to-full`, the pre-push hook refuses it, so push with `HARNESS_VERIFY=off git push`.

**CI**: `harness-verify` reads the pin from the base branch, fetches that commit of `soyPeter/agentic-harness` and
runs `verify --range` with it. A pull request that moves the pin, or switches modes, is checked by the base branch's
harness, so it can't weaken its own gate. The first thin install, with nothing on the base branch, uses the pull
request's pin.

**Plugin and pin**: the plugin supplies the agents, skills and agent rules, and the pinned release supplies the
gates. When the plugin isn't the pinned release, session start says so. In autonomous mode, `run` and `orca` refuse
to start and every call except reads is refused until they match. `doctor` reports it as an error in autonomous mode
and a warning in supervised mode. Install the plugin at the pinned release, or move the pin
([Upgrade a thin project](#upgrade-a-thin-project)).

**Limits**:

- The first session after a pin change needs the network to fetch the release; until then the hooks refuse
  everything except reads.
- In supervised mode, the plugin's agents and skills can drift from the pinned engine: this is reported, not
  prevented.
- Codex and OpenCode agents are per user, so two projects pinned to different releases share one set.
- Codex asks you to trust the plugin's hooks once.
- Teammates without the plugin get no gates in their agent; `harness-verify` still stops the merge once the branch
  is protected.
- The pre-commit shim is the only git hook: Conventional Commits (`commit-msg`) and the pre-push check run in full
  installs only, while CI's `verify --range` applies to both.
- The `.devcontainer/harness-agent/` sandbox comes with thin mode too (`init --thin`, `pin` and `--to-thin` install
  it). When the container starts, it fetches the pinned release and Claude Code loads it as the plugin; run the
  harness there with `python3 ~/.agentic-harness/plugins/agentic-harness/plugin/launcher.py <command>`. `pin` keeps a
  sandbox file you edited (the allowlist in `docker-compose.yml`, say) and writes the release's copy beside it as
  `<file>.harness-new`.

### Upgrade a thin project

The pin decides which release's gates run; the plugin supplies the agents, skills and agent rules, and forwards each
hook to the pinned engine. Move both to the same release at the same time: while they differ, session start says so,
and in autonomous mode every call except reads is refused (see **Plugin and pin** above). Read the **Upgrading**
notes of each release you skip in the [CHANGELOG](../CHANGELOG.md) first.

1. **Move the pin**: `python3 /path/to/agentic-harness/plugin/launcher.py pin <version>`. It checks the release,
   updates `backbone/.harness-lock.json` and the marketplace ref in the project's `.claude/settings.json`, and brings
   the shim, `harness-verify.yml` and the sandbox files you haven't edited to that release. Commit it as one change.
   Its pull request changes the lock, so it needs the `harness-change-approved` label.
2. **Update the plugin** in each agent CLI on your machine, to the same release:
   - Claude Code: `marketplace update` only fetches the ref the marketplace was added at, and adding a marketplace
     records its ref under `extraKnownMarketplaces` in your user settings (`~/.claude/settings.json`). Set the `ref`
     of the `agentic-harness` entry there to `v<version>`, then run
     `claude plugin marketplace update agentic-harness` and `claude plugin update agentic-harness@agentic-harness`,
     and start a new session (or run `/reload-plugins`). While that entry still names the old ref, adding the
     marketplace at the new ref fails ("its source doesn't match its extraKnownMarketplaces entry"), and a marketplace
     you removed is "not found" by `marketplace update` until it is added again: fix the ref first.
   - Codex and OpenCode: install the plugin at the new release as under **Install the plugin** above.
3. **Accept the changed configuration**: `extraKnownMarketplaces` is a setting the harness watches, so session start
   and `doctor` report the change until you run
   `python3 /path/to/agentic-harness/plugin/launcher.py accept-agent-config` in your own terminal. In autonomous mode
   `run` and `orca` don't start until you do.
4. Run `doctor` and follow the release's Upgrading notes (for 0.32.0: fix the `(after: ...)` dependency notes it
   warns about).

Other projects on the machine that still pin the older release report the plugin mismatch until their pins move too.

## What gets installed

This table is for a full install; [Thin mode](#thin-mode) says what a thin project keeps.

| Path | Owner | Notes |
|---|---|---|
| `AGENTS.md` | harness | Agent instructions: setup, pipeline, protocol, guardrails |
| `CLAUDE.md` | project | `@AGENTS.md` import plus Claude-specific notes |
| `.claude/agents/` | harness | `analyst`, `architect`, `griller`, `tester`, `implementer`, `judge`, `debugger`, `reviewer`, `scribe`, `deliverer`, with scoped hooks |
| `.codex/hooks.json`, `.codex/agents/` | harness | Codex: the harness hooks and the role agents (generated) |
| `.opencode/plugins/harness.js`, `.opencode/agents/` | harness | OpenCode: the adapter plugin and the role agents (generated) |
| `.claude/skills/` | harness + project | Core skills (listed in `backbone/SKILLS.md`), adopted pack skills, and yours |
| `scripts/harness/catalog/` | harness | Stack packs, inert until adopted from an accepted ADR |
| `backbone/0-START-HERE.md`, `8-WORKFLOW.md`, `HOOKS.md`, `SKILLS.md`, `templates/` | harness | Map, pipeline and DoD, hooks and gates, skill format, spec and ADR templates |
| `backbone/1-PRD.md` … `7-CONVENTIONS.md`, `9-AGENT-SKILLS.md`, `adr/ADR-001` | project | Created with placeholders that first-run setup fills in |
| `backbone/specs/`, `backbone/adr/` | project | One spec per task; one ADR per decision |
| `backbone/harness.conf`, `guardrails.conf`, `routing.conf` | project | Commands and gate switches; project rules; skill routes |
| `backbone/.verdicts/` | hooks | Griller and judge verdicts per task, with fingerprints (audit trail) |
| `backbone/.harness-lock.json` | harness | Installed version and file hashes |
| `scripts/harness/` | harness | Runtime (`lib/harness.py`), git hooks, core rules and routes, `doctor.sh` |
| `.github/workflows/harness-verify.yml` | harness | CI: `verify --range` with the base branch's verifier on every pull request, and the traceability matrix when it passes; on a push to the default branch, once signing is set up (the `HARNESS_ATTEST_KEY` secret, or a KMS or keyless mode in `HARNESS_ATTEST_SIGNING`), the signed verdict attestation and a signed `.reqifz` export |
| `.github/workflows/harness-judge.yml` | project | CI: an independent judge session re-judges tasks a pull request finishes (needs `ANTHROPIC_API_KEY`; add your toolchain) |
| `.devcontainer/harness-agent/` | harness | Sandbox for unattended runs: an outbound allowlist enforced from a second container (the agent's has no NET_ADMIN or NET_RAW), DNS for allowlisted names only, a log of what it denied, a base image pinned by digest, a trusted workspace, no prompts. Checked in a real container by `tests/test-sandbox-egress.py` (`HARNESS_E2E=1`); the earlier one-container version ran a real task end to end |
| `.claude/settings.json` | shared | Merged: harness hook entries plus a few read-only permissions |

Check the state of a task's definition with `python3 scripts/harness/lib/harness.py spec-check <id>`, and the harness with `scripts/harness/doctor.sh`.
