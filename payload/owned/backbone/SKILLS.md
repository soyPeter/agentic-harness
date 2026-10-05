# Skills

Harness-owned guide. Skills live in `.claude/skills/<name>/SKILL.md`, which Claude Code discovers natively; other agents read the same files.

- **Harness core skills** (replaced on update): `requirements-writing`, `adr-writing`, `architecture`, `api-design`, `openapi`, `code-quality`, `module-testing`, `security`, `changelog`.
- **Stack skills** (from the catalog, replaced on update once adopted): the harness assumes no language, framework or tool. The stack is decided in the design phase in an ADR. Packs in `scripts/harness/catalog/` stay inert until that ADR is accepted and they are adopted:

  ```
  python3 scripts/harness/lib/harness.py catalog                 # packs, what each applies to, options to decide
  python3 scripts/harness/lib/harness.py adopt <pack> --adr ADR-NNN --with <options> --without <options>
  python3 scripts/harness/lib/harness.py adopt --remove <pack>   # when a later ADR changes the stack
  ```

  Adopting checks that the ADR is Accepted and names the pack, and that every option of the pack is decided. It then:
  - installs the pack's skills (and the skills of chosen options) into `.claude/skills/`;
  - writes the pack's routes and guardrails into `backbone/routing.conf` and `backbone/guardrails.conf`, as blocks marked with the ADR;
  - sets related `harness.conf` values, such as the build and test commands for the chosen build tool.
- **Project skills** (yours): anything the catalog doesn't cover, such as a domain skill or a stack without a pack. List them in `backbone/9-AGENT-SKILLS.md`, and don't reuse a harness skill's name.

## Format

```markdown
---
name: <skill-name, same as the folder>
description: <one line: what it covers and when to use it; agents choose skills by this>
applies-to: <what it is valid for: "any", or the language/framework and version range>
last-verified: <YYYY-MM-DD>
sources: <optional provenance: where it was adapted from, with a version, so upstream changes can be tracked>
---

# <Title>

<Rules, procedure, checklists and short examples. Make them concrete and checkable; a reviewer
must be able to tell whether code follows the skill.>

## Linked skills
- `<skill>`: <when to use it together with this one>
```

- The frontmatter must be the first thing in the file; nothing may come before the opening `---`.
- `SKILL.md` stays at or under 200 lines, because routed skills are read in full before every routed edit. Put long references in files next to `SKILL.md` and say when to read them.
- **Linked skills** connects skills into a graph, so an agent knows which one to load next. Name only skills that exist.

## Routing (skill gate)

`scripts/harness/routing.core.conf` and `backbone/routing.conf` (including adopted packs' blocks) map paths to the skills an agent must load before editing them. All matching routes apply.

```
<path regex> | <skill>[, <skill>...] | <why>
```

The required skills for a file are its routes plus, for code while a task is `[WIP]`, the skills listed in that task's spec. A skill counts as loaded once the agent has read its `SKILL.md` or invoked it in the current session (each subagent has its own session). Routes to skills that don't exist yet are ignored by the gate and reported by `doctor.sh`.

Typical project routes:

| Path | Skills |
|---|---|
| `backbone/adr/` | language skill (core routes add `adr-writing` and `architecture`) |
| all code (`\.java$`, `\.py$`, ...) | language and framework skills |
| outer API layer (controllers, resources, handlers) | `api-design`, `openapi` |
| domain layer | `architecture` |
| migrations | database or migration skill |

## Maintenance

Re-verify a skill when the stack version it applies to changes, and update `last-verified`. Treat a skill that is wrong as a bug: fix it, and record the trap in `6-MEMORY.md`.
