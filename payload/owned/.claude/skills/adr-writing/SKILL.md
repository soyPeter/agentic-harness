---
name: adr-writing
description: Write or review Architecture Decision Records in backbone/adr/. Use when a task needs a decision about structure, technology, patterns, data or interfaces, or when checking that a spec references the right ADRs.
applies-to: any
last-verified: 2026-10-04
---

# Architecture Decision Records

Format: `backbone/templates/adr.md`. File: `backbone/adr/ADR-<NNN>-<kebab-title>.md`, numbered sequentially and never reused. Add every ADR to the index in `backbone/5-DECISIONS.md`.

## When an ADR is needed

Write one when a choice is **hard to reverse, affects more than one module, or a future developer would ask "why?"**. For example:
- Choosing or replacing a framework, library, database, queue or external service.
- Defining structure: layering, module boundaries, package conventions.
- Defining data: schemas, ownership, consistency, migrations, retention.
- Defining interfaces: API style, versioning, error format, events.
- Adopting a cross-cutting approach: auth, logging, configuration, error handling, testing strategy.

A task without a new decision still references the ADRs that govern it (at minimum the architecture and stack ADRs).

## Writing a good ADR

- **Title** states the decision ("Use PostgreSQL for order storage"), not the topic ("Persistence").
- **Context** gives the forces: requirements (with REQ ids), constraints and quality attributes. It is neutral, so a reader can see why the decision was hard.
- **Decision** is one or two sentences, then the essential rules that implementers must follow.
- **Alternatives considered**: at least two real options, each with the concrete reason it lost.
- **Consequences**: both positive and negative, including follow-up work, new risks and what is now forbidden.
- **Status**: `Proposed` while under discussion, `Accepted` once the user agrees. To change a decision, write a new ADR and set the old one to `Superseded by ADR-<NNN>`; never rewrite accepted history.

## Review checklist

- Is the decision actually decided? Avoid "we could"/"maybe" wording.
- Does it conflict with an existing accepted ADR or the NEVER DO list in `4-KNOWLEDGE.md`?
- Are the consequences honest about costs?
- Can an implementer follow it without asking? If not, add the missing rule.

## Linked skills

- `architecture`: the principles that structural ADRs apply.
- `requirements-writing`: the REQ ids and NFRs an ADR's context cites.
- `api-design`: API style, versioning and error-format decisions.
- `security`: security-relevant decisions (auth, secrets, data protection).
- The project's language skill: stack-specific constraints for technology ADRs.
