---
name: architecture
description: Design or review the structure of a change - layers, boundaries, dependency direction, module responsibilities, data ownership and cross-cutting concerns. Use for ADRs, the Architecture section of specs, domain-layer code and architecture reviews.
applies-to: any
last-verified: 2026-10-04
---

# Architecture

Start from the project's own rules: the architecture style in `backbone/2-PLANNING.md`, the design rules and NEVER DO list in `backbone/4-KNOWLEDGE.md`, and the accepted ADRs in `backbone/adr/`. This skill gives the general principles behind them.

## Principles

- **Dependency direction**: dependencies point inward, toward the domain. Domain code knows no framework, database, transport or UI. Application code orchestrates use cases through ports (interfaces). Infrastructure implements the ports.
- **Boundaries**: each module owns its data and exposes behaviour through explicit interfaces. No reaching into another module's tables or internals.
- **Single responsibility per layer**:
  - The outer layer (API, UI, messaging) translates and validates input.
  - The application layer coordinates.
  - The domain layer decides.
  - Infrastructure persists and integrates.
- **Explicit contracts**: DTOs and messages at the boundaries are separate from domain models. Map between them instead of leaking persistence or transport annotations inward.
- **Consistency**: decide where transactions start and end. Prefer one aggregate per transaction, and make cross-module effects explicit (events, outbox, sagas) instead of distributed transactions.
- **Simplicity**: choose the simplest structure that meets the requirements and NFRs. Every abstraction must pay for itself. YAGNI applies to layers too.

## When designing a change

1. Locate the change: which module and layer owns each requirement?
2. Identify the contracts that change (API, events, schema). Contract changes need versioning or compatibility notes.
3. Check the NFRs: does the design meet the stated performance, security and availability targets? Say how.
4. Record each hard-to-reverse choice as an ADR (adr-writing skill), and reference it in the spec.

## Review checklist

- Do imports respect the dependency direction? Is there no framework code in the domain?
- Is the business logic in the domain or application layer, not in controllers or repositories?
- Are errors translated at boundaries rather than leaked (no SQL exceptions in API responses)?
- Are new dependencies justified by an ADR?
- Do the tests exercise the layer where the logic lives?

For a review, read `review.md`.

## Linked skills

- `adr-writing`: record every hard-to-reverse structural choice as an ADR.
- `api-design`: design of the outer API layer and its contracts.
- `code-quality`: structure inside a module once the layer and boundary are right.
- `module-testing`: choose the test category that matches the layer where the logic lives.
- `security`: where authorization and validation belong in the layers.
