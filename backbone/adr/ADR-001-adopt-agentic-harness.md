# ADR-001: Adopt the agentic harness

## Status
Accepted

## Date
2026-11-10

## Context
AI agents and people work in this repository. They need shared project knowledge, a defined path from request to verified code, and checks that hold even when an agent forgets an instruction.

## Decision
Use agentic harness 0.30.0:
- Project knowledge lives in `backbone/`.
- Every task goes through a spec (requirements, acceptance criteria, ADRs) that is grilled and approved by the user, an implementer that loads the skills routed to the files it touches, and a judge that checks the result against the acceptance criteria and tests.
- This repository is enrolled in thin mode, pinned at v0.30.0. The gates run from that release (`~/.agentic-harness/engines/0.30.0/`), not from a copy of `scripts/harness/` in the working tree.

## Alternatives considered
- Prompt-only conventions (an instructions file without hooks): cheaper, but agents skip steps under pressure and nothing records that a review happened.
- An external workflow tool: more features, but it would separate the process from the repository, and agents could not see or follow it.

## Consequences
- Every task needs a spec and an approval before code is written, which adds a definition step even for small changes.
- Reviews leave an audit trail in `backbone/.verdicts/`.
- The pin moves only when Pedro runs `pin` after a wave is merged. Until then, edits in this working tree do not change the gates.
