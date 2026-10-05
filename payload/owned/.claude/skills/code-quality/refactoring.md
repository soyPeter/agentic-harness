# Refactoring triggers

Part of the `code-quality` skill. Thresholds are the ones in the `SKILL.md` limits table; they are not repeated here. Apply this catalogue only to code inside the task's scope. Findings outside it go to `backbone/6-MEMORY.md` or a new task.

## Before refactoring

- Tests that prove the affected acceptance criteria exist and pass. If they don't, write them first.
- Refactor in small, behaviour-preserving steps; build and run the tests after each.
- Keep refactoring and behaviour changes distinguishable (separate commits, or clearly separated in the commit body).
- Do not change public contracts (API, events, schema, port signatures used by other modules) as a "refactoring". That is a design change and needs the architect and possibly an ADR.

## Catalogue

| Trigger | How to detect | Refactoring |
|---|---|---|
| Long function | Over the length limit, or needs "and" to describe | Extract function per step; name steps in domain terms |
| High complexity | Over the complexity limit; many `if`/`case`/`&&`/`\|\|` | Guard clauses; extract; replace conditional with polymorphism or a lookup table |
| Deep nesting | Over the nesting limit | Early returns; extract the inner loop body |
| Complex condition | Over the boolean-operator limit, or mixed `!`, `&&`, `\|\|` | Extract a named predicate |
| Long parameter list | Over the parameter limit; same group of parameters in several signatures | Introduce a value type for the group |
| Flag argument | Boolean parameter switching behaviour | Split into two functions |
| Mixed abstraction levels | Orchestration interleaved with low-level loops or formatting | Extract the low-level part |
| God class | Over the class limit; unrelated groups of fields and methods | Extract class per responsibility |
| Feature envy | A function uses another type's data more than its own | Move the function to that type |
| Anemic domain logic | Rules about an entity live in a service that only reads its fields | Move the rule into the entity or value type, if the architecture ADR puts logic in the domain |
| Primitive obsession | Strings or numbers carrying meaning (email, money, ids) | Introduce a self-validating value type |
| Magic values | Unexplained literals | Named constant or configuration |
| Duplicated knowledge | Same rule in three places (rule of three) | Extract to one home; leave coincidental look-alikes |
| Shotgun surgery | One change needs edits in many places | Consolidate the knowledge in one module |
| CQS violation | A query mutates, or a command returns data it also changes | Split into command and query |
| Redundant logic | `if x return true else return false`; double negation; `else` after `return` | Simplify: `return x` |
| Temporary variable chains | Variables only hold intermediate values for one use | Inline, or replace temp with a query function |
| Poor names | Generic, abbreviated or misleading names | Rename to domain vocabulary |
| Dead code | Unreachable code, unused private members, unused parameters | Delete (see exceptions) |
| Swallowed or generic errors | Empty catch; catch-all; `return null` on failure | Specific error with context and cause |
| Wrapper without value | A class that only forwards calls and is not a port, adapter or anti-corruption layer | Inline it |

## Not triggers

- A port interface with one adapter (hexagonal architecture). It is a boundary, not over-abstraction.
- A layered or hexagonal directory layout that matches the architecture ADR.
- Two similar-looking functions that implement different business rules.
- A function a few lines over the limit that does one thing clearly.
- Framework-required members that look unused (called by reflection, dependency injection, serialisation or lifecycle callbacks).

## Dead code exceptions

Do not delete, and ask or record instead, when the code:
- is public or published API that external clients may use;
- is reached by reflection, configuration, dependency injection or serialisation;
- belongs to another task's planned work (check `3-TASKS.md`).

## Prioritising findings (reviews)

| Priority | Findings |
|---|---|
| High | Security problems; broken public contracts; error-handling gaps on critical paths; domain logic leaking into adapters or framework code in the domain |
| Medium | Limit violations; duplicated business rules; primitive obsession in new signatures; dead code |
| Low | Naming nits; style already covered by a formatter; speculative performance changes without a measurement |

High findings in the task's code block the judge's pass if they violate a NEVER DO rule, an ADR or an acceptance criterion; otherwise they are reported. Low findings are batched, never a reason to expand the task.

## Reporting a finding

```
[Priority] <trigger> - <file>:<line>
Why it matters: <one sentence>
Suggested refactoring: <one sentence>
In scope: yes (fixed) | no (recorded in 6-MEMORY.md / proposed task <id>)
```
