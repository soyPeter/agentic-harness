---
name: requirements-writing
description: Write or review a task spec (backbone/specs/<id>.md) with clear requirements and testable Given/When/Then acceptance criteria. Use when defining a task, grilling a spec, or judging against one.
applies-to: any
last-verified: 2026-11-06
---

# Requirements and acceptance criteria

Specs use the format in `backbone/templates/spec.md`. Run `python3 scripts/harness/lib/harness.py spec-check <id>` to see what the start gate will reject.

## Change-Class and parent links

- Set `Change-Class:` to exactly one of `docs` | `refactor` | `feature` | `schema`, on its own line under `PRD:`. If unsure, use `feature`. Any other value, or two different ones, fails `spec-check`; without the line the spec counts as `feature`. A `Change-Class:` line in a comment or a code block is a note or an example, not the declaration.
  - `docs`: documentation files only: Markdown, reST, AsciiDoc and text files, README, LICENSE and the like (`HARNESS_DOC_PATHS`). Doc-tool code such as Sphinx's `docs/conf.py` or MkDocs hooks, and comments in code files, are not `docs`.
  - `refactor`: structural change with no intended behaviour change.
  - `feature`: new or changed behaviour (new REQ/AC).
  - `schema`: migrations, auth, secrets, payments, deploy/infra (aligns with `HARNESS_RISK_*`).
- `feature` and `schema` always need a human `Approved-by:` line: `harness.py approve` escalates them. `schema` never takes the light lane; `feature` takes it only when the user marks the task `(light)`.
- `docs` / low-risk `refactor` may use autonomous `harness.py approve` only when `HARNESS_AUTO_APPROVE=low` and `risk_reasons` is empty (the harness's ADR-002, not the project's). A `docs` change that touches anything but documentation (`HARNESS_DOC_PATHS`) is a risk again when the task finishes, and so is a `refactor` that touches sensitive paths; a moved file counts at both its old and its new path. `harness.py risk <id>` shows the class and what it allows.
- Optional `Parent-CHNG:`, `Parent-RFC:`, `Parent-ADR:`: if a vault change record, RFC or ADR already exists, **copy its stable id/link** into these fields. The vault (or `backbone/adr/`) remains the system of record — do not create a CHNG folder inside the harness install.
- Write the class as a bare word (`Change-Class: docs`, without backticks or a note after it); anything else fails `spec-check`. The receipt turns the class into the PR's suggested triage labels (`class:<class>` and a `risk:*` level), which the deliverer applies.

## Requirements (`REQ-<task>-<n>`)

- One behaviour per requirement: "The system shall <verb> <object> <condition>".
- Describe **what** the system does, never how: no class names, libraries or SQL. Those belong in the Architecture section or the ADRs.
- Make them unambiguous. Replace "fast", "user-friendly", "secure", "handle errors" and "etc." with something measurable or enumerable ("responds within 300 ms at p95", "rejects names longer than 100 characters with 400").
- Each one is necessary and traceable to the PRD, a Parent-* link, or a stated need. Delete requirements nobody asked for.
- Cover the unhappy paths: invalid input, not found, conflicts, permissions, empty results, limits, concurrency and idempotency where relevant.

When `HARNESS_REQ_STYLE` is `ears`, write every requirement in an EARS pattern and read `ears.md`: `spec-check` enforces it. When it is `plain` (default), EARS phrasing is still allowed and useful; it is not required.

### EARS ↔ REQ/AC (short map)

| EARS pattern | REQ shape | Main AC When |
|---|---|---|
| Ubiquitous | The `<system>` shall `<response>`. | the action under test |
| Event-driven | When `<trigger>`, the `<system>` shall `<response>`. | same trigger |
| State-driven | While `<state>`, the `<system>` shall `<response>`. | action while in that state |
| Unwanted | If `<condition>`, then the `<system>` shall `<response>`. | the unwanted condition |
| Optional feature | Where `<feature>`, the `<system>` shall `<response>`. | using that feature |

Keep ids as `REQ-<task>-<n>` either way. Acceptance criteria stay Given/When/Then and cite those ids.

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
- Missing or wrong `Change-Class:` (especially marking `schema` work as `docs`/`refactor` to chase policy approve).

## Linked skills

- `module-testing`: how each AC is turned into a test that names its id and asserts its Then.
- `adr-writing`: decisions that surface while writing requirements go into ADRs, not the spec.
- `architecture`: the spec's Architecture section and where each requirement is implemented.
- `api-design`: phrasing API requirements and ACs with concrete status codes and payloads.
- `security`: turning "secure" into concrete, testable security requirements and NFRs.
