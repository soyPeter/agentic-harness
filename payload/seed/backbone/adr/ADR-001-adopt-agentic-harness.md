# ADR-001: Adopt the agentic harness

## Status
Accepted

## Date
{{DATE}}

## Context
AI agents and people work in this repository. They need shared project knowledge, a defined path from request to verified code, and checks that hold even when an agent forgets an instruction.

## Decision
Use agentic harness {{HARNESS_VERSION}}:
- Project knowledge lives in `backbone/`.
- Every task goes through a spec (requirements, acceptance criteria, ADRs) that is grilled and approved by the user, an implementer that loads the skills routed to the files it touches, and a judge that checks the result against the acceptance criteria and tests.
- Hooks in `scripts/harness/` enforce each gate.

## Alternatives considered
- Prompt-only conventions (an instructions file without hooks): cheaper, but agents skip steps under pressure and nothing records that a review happened.
- An external workflow tool: more features, but it would separate the process from the repository, and agents could not see or follow it.

## Consequences
- Every task needs a spec and an approval before code is written, which adds a definition step even for small changes.
- Reviews leave an audit trail in `backbone/.verdicts/`.
- Harness files are updated from the harness repository. Local edits to them surface as conflicts on update.
