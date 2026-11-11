# 5. Decisions: agentic-harness

The index of Architecture Decision Records. Project ADRs live in `backbone/adr/` and are the ones a spec's `ADRs:` line can name. Product ADRs live in `docs/adr/`. They are linked here so a spec can follow them. Do not copy them into `backbone/adr/`, and do not change their status. Pedro does that.

## Project ADRs

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](adr/ADR-001-adopt-agentic-harness.md) | Adopt the agentic harness | Accepted | 2026-11-10 |
| [ADR-002](adr/ADR-002-python-stdlib.md) | Python 3.8 and the standard library | Accepted | 2026-11-10 |

## Product ADRs

These are the harness's own decisions. A spec that needs one of them on its `ADRs:` line cannot see it: `spec-check` only looks in `backbone/adr/`. Cite ADR-002 there, and name the product ADR in the narrative. A Proposed product ADR on the `ADRs:` line would also block policy approval, once a copy existed.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](../docs/adr/ADR-001-thin-mode-plugin.md) | Thin mode plugin | Accepted | 2026-11-03 |
| [ADR-002](../docs/adr/ADR-002-change-class-ladder.md) | Change-class ladder | Accepted | 2026-11-06 |
| [ADR-003](../docs/adr/ADR-003-sandbox-backends.md) | Sandbox backends | Proposed | 2026-11-07 |
| [ADR-004](../docs/adr/ADR-004-traceability-export.md) | Traceability export | Proposed | 2026-11-07 |
| [ADR-005](../docs/adr/ADR-005-verdict-attestations.md) | Verdict attestations | Proposed | 2026-11-07, revised 2026-11-08 |
| [ADR-006](../docs/adr/ADR-006-external-agent-resource-admission.md) | External agent resource admission | Proposed | 2026-11-08 |
| [ADR-007](../docs/adr/ADR-007-evidence-closed-loop.md) | Evidence closed loop | Proposed | 2026-11-07, revised 2026-11-10 |
