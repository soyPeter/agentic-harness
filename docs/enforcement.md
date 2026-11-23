# Enforce it everywhere

The harness enforces itself inside each project (agent hooks, git hooks, CI). Three tools make sure every project
has it and every agent loads it:

- **`./enroll.sh <project> [--orca] [--automation daily] [--agents "default=claude judge=codex"] [--protect]`**:
  - installs or updates the harness and runs the doctor;
  - registers the project in Orca;
  - with `--automation <schedule>`, creates one Orca automation per checkout: its precheck, which Orca runs itself, starts `harness.py orca --merge --trust` in its own Orca terminal (`harness.py orca-nightly`), and its agent reports the previous run's digest (`harness.py orca-digest`);
  - sets the agent per role;
  - with `--protect`, requires the CI checks on the GitHub default branch, keeping its existing checks and rules.

  `--dry-run` shows what it would do. Enrolling again is safe.
- **`./machine.sh install [--roots ~/Work/repos] [--mode warn|block] [--plugin]`**: a user-level guard hook for
  Claude Code and Codex on this machine, in their user settings (`~/.claude` and `~/.codex`, or `$CLAUDE_CONFIG_DIR`
  and `$CODEX_HOME` when set). In a git repository under the roots that isn't enrolled (it has neither a full install
  nor a thin pin), it reminds you (warn) or refuses file edits (block) until the repository is enrolled; enrolled
  repositories are left to their own hooks, or the plugin's. Codex runs the new hook only once you trust it in
  `/hooks`, and once more after it changes. `machine.sh status` shows it, and says whether Codex runs it; `machine.sh
  remove` undoes it. Settings that aren't usable count as none: `roots` or `exempt` that aren't lists of absolute folder
  paths, or an `enroll` that isn't one. `status` says which. The
  CLIs load hooks when a session starts, so restart the sessions that are open after `install`, `install --plugin` or
  `remove`: until then they keep the hooks they started with.
  - The agentic-harness plugin gives the same reminder or refusal from its own hooks, with the same settings
    (`~/.agentic-harness/machine.json`). On a machine with the plugin, `--plugin` writes only the settings and takes
    out a guard hook installed earlier, leaving the guard copy for the sessions still open. In a CLI that runs both,
    the guard hook answers and the plugin stays quiet, so nothing is said twice. Codex runs the guard hook only while
    it is trusted as it is now and switched on (Codex's `config.toml`); until then the plugin answers in its place.
    Where the plugin can't tell (it can't read that file, or Codex runs with `--dangerously-bypass-hook-trust`), it
    answers as well: a refusal can come twice, a reminder still comes once per session and repository. An installed
    guard is a copy: run `install` again after updating the harness. Until you do, the plugin doesn't leave the check
    to that copy, and `status` says it is outdated. Where `status` runs from the checkout that installed the copy, it
    names the copy's release and says the plugin checks too wherever its own `guard.py` differs.
  - `machine.sh managed --out DIR` writes the same guard as Claude Code `managed-settings.json` and Codex
    `requirements.toml`, which nobody on the machine can switch off. Review them and install with sudo (see the
    generated INSTALL.md); the tool never writes system files. The plugin reads only the user's settings, so with a
    managed guard don't run `install --plugin` as well, or a call gets both answers.
- **`orca/skills/agentic-harness/SKILL.md`**: the Orca skill for coordinators you run by hand. It says to check for
  the harness, prefer `harness.py orca`, and otherwise follow the gates (`harness.py next` before every step, command
  steps through the harness, answers recorded in the spec with their source, prompts left to the user). Share it with
  `orca skills share`.

The hard floor stays CI: an agent without hooks, or a human with `--no-verify`, still can't merge past
`harness-verify` once the branch is protected.

**The agent CLIs' own configuration.** A user-level setting can switch the hooks off in every project. What the
hooks do about it, their limits, and the managed settings for unattended runs are in
[HOOKS.md](../payload/owned/backbone/HOOKS.md#the-agent-clis-own-configuration).

The guard's limits, which the plugin's check shares: it needs `python3` and `git` on the PATH, and when its own lookup
fails (no git, a broken config) it lets the call through rather than stop every agent on the machine. It checks the
repository of each file a tool writes and, for shell commands, the working directory plus every path and `cd` target
the command names. A shell command that builds a path at run time (a variable, a computed string) can still reach
another repository unseen. In block mode the only shell command it lets run in an unenrolled repository is the
harness's own `enroll.sh`; a thin install (`launcher.py init --thin`) is yours to run in a terminal.

## Profiles

A profile is an organisation policy on top of the gates. Set it in `backbone/harness.conf` (user-only) or when you enroll:

```sh
./enroll.sh /path/to/repo --profile triple      # writes HARNESS_PROFILE="triple"
./enroll.sh /path/to/repo --profile no-merge    # writes HARNESS_PROFILE="no-merge"
```

What each profile refuses, and how the environment can add a profile but never lift one, is in
[HOOKS.md](../payload/owned/backbone/HOOKS.md#profiles-harness_profile). The `triple` catalog pack is separate from
the profile: it adds the Linear, EARS and Disputes/PCI layers (see
[catalog/triple/README.md](../catalog/triple/README.md)).
