# 2. Planning: agentic-harness

## Architecture style
One Python engine, standard library only, with a thin install in this same repository. The committed project state is `backbone/` and the pin. The gates run from the pinned release under `~/.agentic-harness/engines/0.30.0/`. Role agents and core skills come from the plugin at that same release. Orca drives ready tasks one worker per step, one worktree per task, and opens a pull request. It does not merge.

## Structure
```text
backbone/          project state: tasks, specs, ADRs, pin, harness.conf
plugin/            thin-mode launcher and hook shims (the product)
payload/owned/     engine files a full install copies into a project
payload/seed/      project files a fresh install writes once
catalog/           stack packs; none are adopted here
tools/             installer, enroll, thin-mode switch
tests/             self-test (tests/run-tests.sh)
docs/adr/          product ADRs (thin mode, change class, sandbox, trace, attest)
docs/research/     plans the wave 1 audits read
.github/workflows/ self-test.yml (product CI) and harness-verify.yml (the pin's check)
```

## Main flows
- A task line in `backbone/3-TASKS.md` becomes a spec, then a grill, then policy approval when the change class is docs or refactor and the risk is low. Feature and schema specs wait for Pedro's `Approved-by:` line.
- The implementer edits code, the judge runs `tests/run-tests.sh`, three reviewers pass, and the deliverer opens a pull request.
- `harness-verify` on a pull request runs `verify --range` with the engine the base branch pins.
- Pedro starts Orca by hand from the pinned launcher. A dependent task starts only after he merges the pull request it waits for.

## External dependencies
Git and Python 3.8 or later. The GitHub CLI (`gh`) for pull requests. Claude Code and Codex on the machine that runs Orca, with the agentic-harness plugin at v0.30.0. The Orca app, already running. No database and no extra Python packages for the engine. The self-test may install the tools listed in `tests/requirements.txt`.
