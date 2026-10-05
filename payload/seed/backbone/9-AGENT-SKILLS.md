# 9. Agent Skills: {{PROJECT_NAME}}

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

Stack skills come from catalog packs adopted after the stack ADR (`harness.py catalog`, `harness.py adopt`). List them below with the ADR that chose them.

## Stack and project skills

| Skill | From (pack + ADR, or project) | Use for | Routed to |
|---|---|---|---|
| {{FILL: stack skills adopted after the stack ADR, and project skills}} | | | |
