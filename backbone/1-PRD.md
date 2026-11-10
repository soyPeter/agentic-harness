# 1. Product Requirements: agentic-harness

## What we are building
Agentic Harness is a stack-agnostic process for AI coding agents. It installs into a git repository and takes each task through a spec, a grill, an implementation, a judge, three reviews and a pull request. This repository is the harness itself. It is enrolled in thin mode, pinned at release v0.30.0, so the gates that judge a change come from that release and not from the files a worker edits.

## Who it is for
Pedro, the maintainer, and the agents he runs (Claude Code, Codex, OpenCode, and the Orca coordinator). The need is a gated path from a task line to a pull request, with a human still merging.

## What good looks like
- `python3 ~/.agentic-harness/engines/0.30.0/plugin/launcher.py doctor` reports no errors on a fresh clone after `git config core.hooksPath .githooks`.
- `tests/run-tests.sh` passes on the self-test.
- Orca, started by Pedro, opens one pull request per task and never merges.
- A task that changes a gate does not change the gate that judges it. The new gate applies only after Pedro cuts a release and moves the pin.

## Out of scope
- Generating an application on top of the harness. This repository is the harness.
- Merging pull requests. Pedro merges each one.
- Moving the pin, scheduling `orca-nightly`, or running `enroll.sh --automation`.
- Changing the status of a product ADR in `docs/adr/`. That stays Pedro's decision.
- Adopting the catalog pack named `triple`. `HARNESS_PROFILE="triple"` is only the no-merge profile.
