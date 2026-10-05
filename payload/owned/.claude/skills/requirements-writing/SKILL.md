---
name: requirements-writing
description: Write or review a task spec (backbone/specs/<id>.md) with clear requirements and testable Given/When/Then acceptance criteria. Use when defining a task, grilling a spec, or judging against one.
applies-to: any
last-verified: 2026-10-04
---

# Requirements and acceptance criteria

Specs use the format in `backbone/templates/spec.md`. Run `python3 scripts/harness/lib/harness.py spec-check <id>` to see what the start gate will reject.

## Requirements (`REQ-<task>-<n>`)

- One behaviour per requirement: "The system shall <verb> <object> <condition>".
- Describe **what** the system does, never how: no class names, libraries or SQL. Those belong in the Architecture section or the ADRs.
- Make them unambiguous. Replace "fast", "user-friendly", "secure", "handle errors" and "etc." with something measurable or enumerable ("responds within 300 ms at p95", "rejects names longer than 100 characters with 400").
- Each one is necessary and traceable to the PRD or a stated need. Delete requirements nobody asked for.
- Cover the unhappy paths: invalid input, not found, conflicts, permissions, empty results, limits, concurrency and idempotency where relevant.

## Acceptance criteria (`AC-<task>-<n> (REQ-<task>-<n>)`)

- Form: `Given <state>, when <action>, then <observable result>`. One scenario per criterion.
- **Observable**: the "then" describes something a test can assert, such as a status code, a returned value, a persisted row, an emitted event or a log entry. "Works correctly" is not observable.
- **Specific data**: use concrete examples ("given customers 'Ana' and 'ana'"), not "some customers".
- Every requirement has at least one criterion. Every criterion names the requirement(s) it proves.
- Include at least one negative criterion for each requirement that can fail.
- Tests that prove a criterion mention its id (in the test name, a tag or a comment), so the judge can trace it.

## Non-functional requirements

Name the quality constraints with a number or a standard: latency, throughput, data volume, security controls, accessibility level, backward compatibility. If there are none, write "none" deliberately.

## Common defects to catch

- Criteria that restate the requirement ("then the search works").
- Hidden decisions, such as pagination size, sorting or time zones. Make each one a requirement or an open question.
- Scope creep, where the task does more than its PRD section. Move the extra to "Out of scope".
- Open questions left unresolved. The griller fails the spec until they are answered by the user.

## Linked skills

- `module-testing`: how each AC is turned into a test that names its id and asserts its Then.
- `adr-writing`: decisions that surface while writing requirements go into ADRs, not the spec.
- `architecture`: the spec's Architecture section and where each requirement is implemented.
- `api-design`: phrasing API requirements and ACs with concrete status codes and payloads.
- `security`: turning "secure" into concrete, testable security requirements and NFRs.
