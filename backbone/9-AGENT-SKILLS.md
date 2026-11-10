# 9. Agent Skills: agentic-harness

Skills in `.claude/skills/`. Format and routing: `backbone/SKILLS.md`. Routes: `backbone/routing.conf`.

## Harness core skills

| Skill | Use for |
|---|---|
| `requirements-writing` | Specs: requirements and Given/When/Then acceptance criteria |
| `adr-writing` | Architecture Decision Records |
| `architecture` | Layers, boundaries, dependency direction, design reviews (`review.md`) |
| `api-design` | HTTP APIs: resources, status codes, errors, versioning, compatibility |
| `openapi` | OpenAPI contracts kept in sync with the code |
| `code-quality` | Readable, maintainable code; routed to all source files; judge checklist |
| `module-testing` | Test method, AC traceability, determinism; routed to tests; judge checklist |
| `security` | Input, injection, authN/authZ, secrets, data exposure; judge checklist |
| `changelog` | Release notes from Conventional Commits (on demand) |
| `change-review` | The reviewers' three lenses after the judge: correctness (with blast radius), structure, lean |

Stack skills come from catalog packs adopted after the stack ADR (`harness.py catalog`, `harness.py adopt`). List them below with the ADR that chose them.

## Stack and project skills

None. ADR-002 accepts Python 3.8 and the standard library and adopts no catalog pack. Core skills come from the pinned release. `HARNESS_PROFILE="triple"` does not install the `triple` pack.
