# 4. Knowledge: agentic-harness

The rules of the road. Agents read this file before every task.

## Summary
This repository is the agentic harness, enrolled in thin mode at v0.30.0. Workers may edit the product source. The gates that check their work stay on the pinned release until Pedro cuts a new release and moves the pin.

## Tech stack
- Language: Python 3.8 or later. The engine uses the standard library only.
- Framework: none.
- Build tool: none. `python3 -m compileall` can check syntax. The real check is the self-test.
- Persistence: git. Project state is `backbone/` and the pin in `backbone/.harness-lock.json`.
- Messaging: none.
- Testing: `tests/run-tests.sh` (unittest, plus the tools in `tests/requirements.txt`).
- Coordinator: Orca, started only by Pedro. Agents may run `doctor`, `orca --dry-run`, `state`, `report` and `escalations`.

## Design rules
1. Thin mode. Commands go through the pinned launcher, `~/.agentic-harness/engines/0.30.0/plugin/launcher.py`, once work has started. The copy at `plugin/launcher.py` in this clone is product source and workers will edit it.
2. `HARNESS_PROFILE="triple"` refuses `--merge`, `--trust` and `orca-nightly`. Delivery is `--pr` only. Pedro merges.
3. `HARNESS_ORCA_AGENTS` is `default=claude judge=codex`. The judge runs on a different model.
4. Parallel workers: 2.
5. A spec whose Change-Class is `docs` or `refactor` can be approved by policy when it is low risk. `feature` and `schema` wait for Pedro's `Approved-by:` line.
6. A spec's `ADRs:` line must name an ADR file in `backbone/adr/`. Product ADRs live in `docs/adr/` and are indexed in `5-DECISIONS.md`. Cite an Accepted backbone ADR on the `ADRs:` line (ADR-002 for the stack). Mention a Proposed product ADR in the narrative, not on that line, or policy will not approve the spec.
7. Wave 1 tasks are audits and docs. They read the plan path on their task line. If that file is not on the base branch, the plan does not exist for the worker yet.
8. Do not adopt the catalog pack `triple`. The profile and the pack are different things.
9. Do not change a product ADR's status. Pedro does that.

## NEVER DO
- Do not run `orca` without `--dry-run` from an agent. Pedro starts the real run.
- Do not pass `--merge` or `--trust`, and do not schedule `orca-nightly` or `enroll.sh --automation`.
- Do not move the pin (`launcher.py pin`). Pedro does that after a wave is merged.
- Do not add a third-party import to `payload/owned/scripts/harness/lib/`.
- Do not write secrets, private keys or tokens into the repository.
- Do not mark a product ADR Accepted.
- Do not treat `payload/`, `plugin/` or `catalog/` as the installed engine. The installed gates are the pinned release.

## Commands
| Purpose | Command |
|---|---|
| Doctor | `python3 ~/.agentic-harness/engines/0.30.0/plugin/launcher.py doctor` |
| Test | `tests/run-tests.sh` |
| Dry run | `python3 ~/.agentic-harness/engines/0.30.0/plugin/launcher.py orca --dry-run --parallel 2 --pr --tasks 1.1,1.2,1.3,1.4,1.5,1.6,1.7` |
| Stop Orca | create `.git/harness/STOP` in the clone |
