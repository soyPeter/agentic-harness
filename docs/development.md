# Developing the harness

- Run `tests/run-tests.sh` after every change. It installs into temporary repos and runs the whole pipeline (define,
  grill, approve, build, judge) plus every hook, rule and update path. Install the test-only tools first
  (`python3 -m pip install -r tests/requirements.txt`, in a virtual environment). The `tests/test-*.py` files run in
  parallel, `HARNESS_TEST_JOBS` at a time (default: one per CPU). `HARNESS_STRESS=1` adds a stress check of the
  harness-verify step that takes the base branch's engine: it keeps every CPU busy for a few minutes, as on a loaded
  macOS runner. The macOS pull request jobs run the suite in two parts per Python at once (`HARNESS_TEST_PART=1|2`
  runs one part locally), and the hook-time Budget checks of `tests/test-eval-replay.py` measure the hook's CPU time,
  so a loaded runner doesn't fail them.
- The property checks run every example by default (`HYPOTHESIS_PROFILE=thorough`). The required pull request jobs use
  `HYPOTHESIS_PROFILE=ci`, which runs a quarter of the examples for checks that start a process per example; the
  `nightly` workflow runs the full profile on Ubuntu and macOS every night.
- Bump `VERSION` and add a `CHANGELOG.md` entry for each release. Projects see the version at session start and in `update.sh status`.
- Keep `payload/owned` stack-neutral. Stack knowledge goes into catalog packs, and every tool or policy choice inside a pack is an option the ADR decides.
- Never write a literal FILL placeholder (two braces, FILL, colon) into a harness-owned backbone doc, or projects will count it as unfinished setup.

## Repository layout

```
bootstrap.sh, update.sh         entry points (thin wrappers)
tools/installer.py              install, update and status logic
tools/thin.py                   thin mode: init --thin and pin
tools/convert.py                update.sh --to-thin and --to-full
plugin/                         the plugin's launcher, hooks, pre-commit shim, OpenCode adapter and init skill
.claude-plugin/, .codex-plugin/ plugin manifests for Claude Code and Codex, and the marketplace
tools/gen_agents.py             generates the Codex and OpenCode agents from .claude/agents/
tools/enroll.py, enroll.sh      enroll a project (install or update, Orca, automation, CI protection)
tools/machine.py, machine.sh    the machine guard (user level, or managed files to install)
machine/guard.py                the guard's check: its own hook, or run by the plugin's launcher
orca/skills/agentic-harness/    the Orca skill for coordinators
payload/owned/                  harness-owned files, replaced on update
payload/seed/                   project-owned templates, created once
payload/settings.fragment.json  hooks and permissions merged into .claude/settings.json
catalog/<pack>/                 stack packs (layout: docs/catalog.md)
tests/run-tests.sh              end-to-end self-test in throwaway repos
backbone/                       this repository's own harness state: thin mode at a pinned release (see CLAUDE.md)
docs/                           the SDLC diagrams, guides, ADRs and research
.github/workflows/              self-test.yml and nightly.yml (product CI), harness-verify.yml (the pin's check)
VERSION, CHANGELOG.md
```
