# Stack packs

The harness assumes no language, framework or tool. The stack is decided in the **design phase**: the architect
records it in an ADR, and you accept it. Only then does the project adopt matching packs from the catalog, which
ships with every install but stays inert. How to list, adopt and remove packs, and what adoption checks and writes,
is in [SKILLS.md](../payload/owned/backbone/SKILLS.md) (installed as `backbone/SKILLS.md`).

| Pack | Applies when the ADR chooses | Options to decide |
|---|---|---|
| `java` | Java | build tool `gradle` / `maven`; `junit5-assertj`; `no-lombok` |
| `quarkus` (requires java) | Quarkus | `no-spring`; `hexagonal-layers`; `named-use-cases` |
| `jdbi` (requires java) | JDBI for data access | `no-orm`; `hexagonal-layers`; `flyway` |
| `container` | Container images | engine `podman` / `docker` |
| `typescript` | TypeScript on Node.js | package manager `npm` / `pnpm`; test runner `vitest` / `jest`; `strict` |
| `react` (requires typescript) | React for the UI | `nextjs` (App Router); `testing-library` |
| `triple` | Triple's delivery policy (with `HARNESS_PROFILE=triple`) | `disputes-pci`; `ears` |

Stacks without a pack get project skills written during design, routed in `backbone/routing.conf`.

## Layout

Each pack is a folder under `catalog/`. A full install copies the whole catalog, inert, to `scripts/harness/catalog/`.

```
catalog/<pack>/pack.json        pack metadata: when it applies, requirements, option groups and options
catalog/<pack>/install/         files adopted into the project (skills, scripts)
catalog/<pack>/{guardrails,routing}.conf  base rules; catalog/<pack>/options/<id>/ option-specific files
```
