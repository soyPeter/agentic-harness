# 5. Decisions: agentic-harness

The index of Architecture Decision Records. Project ADRs live in `backbone/adr/` and are the ones a spec's `ADRs:` line can name. Product ADRs live in `docs/adr/`, and their index, linked below, lists each one with its status. Do not copy them into `backbone/adr/`, and do not change their status. Pedro does that.

## Project ADRs

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](adr/ADR-001-adopt-agentic-harness.md) | Adopt the agentic harness | Accepted | 2026-11-10 |
| [ADR-002](adr/ADR-002-python-stdlib.md) | Python 3.8 and the standard library | Accepted | 2026-11-10 |

## Product ADRs

These are the harness's own decisions. [docs/adr/README.md](../docs/adr/README.md) lists every one with its status, date and plan; it is the only table of them. A spec that needs one of them on its `ADRs:` line cannot see it: `spec-check` only looks in `backbone/adr/`. Cite ADR-002 there, and name the product ADR in the narrative. A Proposed product ADR on the `ADRs:` line would also block policy approval, once a copy existed.
