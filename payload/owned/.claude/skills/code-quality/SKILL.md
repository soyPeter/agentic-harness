---
name: code-quality
description: Write or review readable, maintainable code - responsibilities, naming, function design, complexity limits, duplication, value types, immutability, error handling and comments. Use for any production code change and for code review.
applies-to: any
last-verified: 2026-10-05
sources: adapted from cuioss/plan-marshall dev-general-code-quality and dev-general-code-documentation (tree ce2cc13) and decebals/claude-code-java clean-code (0d98fe9); thresholds unified, layer and single-implementation rules corrected for hexagonal architecture
---

# Code quality

Project rules come first: `backbone/4-KNOWLEDGE.md` (NEVER DO), `backbone/7-CONVENTIONS.md` and the accepted ADRs. Where they say nothing, use these defaults. The project's language skill gives the idioms for each rule.

## Scope: improve what the task touches, nothing more

- The approved spec is frozen. Never widen a task to clean up code it does not need to change.
- Inside the code the task changes (the functions and types you edit, and their tests), leave it cleaner: fix naming, dead code, missing error handling or a violated limit below.
- Problems you notice elsewhere: do not fix them. Record each one in `backbone/6-MEMORY.md` (via the scribe) or propose it as a new task in `3-TASKS.md`, with file and line.
- If a required change cannot be made cleanly without touching unrelated code, stop and report it instead of refactoring silently.

## Limits (one set; review triggers, not targets)

| Measure | Limit | When exceeded |
|---|---|---|
| Function body | 50 lines | Extract steps; a focused function slightly over is acceptable, a short one doing two things is not |
| Cyclomatic complexity | 15 per function | Guard clauses, extract, polymorphism or a lookup table |
| Nesting depth | 3 levels | Early returns, extract the inner block |
| Parameters | 4 | Group cohesive ones into a value type; languages with named arguments may go higher if call sites stay readable |
| Class or module | 500 lines or 20 public members | Split by responsibility |
| Boolean expression | 3 operators | Name it: `isActiveAdmin(user)` |

These numbers are the only thresholds in this skill and its linked files. A project value in `7-CONVENTIONS.md` overrides them.

## Responsibilities and structure

- **Single responsibility**: a function, class or module has one reason to change. If its purpose needs "and" to describe, split it.
- **Command-query separation**: a function either changes state or returns information, not both. Established exceptions: `pop`, `dequeue`, compare-and-set, idempotent "create or get" required by the spec.
- **Composition over inheritance**: delegate for reuse; keep hierarchies at most 2-3 levels; use interfaces for polymorphism.
- **Smallest visibility**: private by default, module-internal for collaborators, public only for real API.
- **Structure follows the architecture ADR.** Layered and hexagonal layouts (`domain/`, `application/`, `adapter/`) are legitimate; within each layer, group by feature. Do not restructure packages as part of a task.
- **Ports are not over-abstraction.** A port interface with exactly one adapter is expected in hexagonal architecture; it keeps the domain free of infrastructure and enables test doubles. Remove an interface only when it is neither a port nor a real extension point and the architecture ADR allows it.
- **YAGNI**: no options, parameters, hooks or generic layers "for later". Build what the acceptance criteria need.

## Functions

- **Single level of abstraction**: a function either orchestrates named steps or does low-level work, not both.

  ```
  // mixed                                  // one level
  process(order):                           process(order):
    validate(order)                           validate(order)
    total = 0                                 total = totalOf(order)
    for line in order.lines:                  sendConfirmation(order, total)
      total += line.price * line.qty
    sendConfirmation(order, total)
  ```
- **No flag arguments**: a boolean that switches behaviour means two functions. `send(msg, urgent=true)` becomes `sendNow(msg)` and `enqueue(msg)`.
- **Guard clauses**: check preconditions first and return or fail early; the main path stays unindented.
- **No hidden side effects**: a function named `isValid` or `get...` does not mutate, log at warn/error, or do I/O.
- **Pure where possible**: push I/O to the edges (adapters), keep decisions in pure domain functions that are easy to test.

## Names

- Say what it is or does in domain language from the spec: `overdueInvoices`, not `list2`; `calculateShippingCost`, not `process`.
- Functions: verb + object. Booleans: `is`, `has`, `can`, `should`. Types: specific nouns.
- Avoid `data`, `info`, `item`, `manager`, `helper`, `util`, `handler` as whole names; they hide responsibility.
- No abbreviations except universal ones (`id`, `url`, `http`). Single letters only for short loop indices and lambdas.
- Replace magic numbers and strings with named constants or configuration: `FREE_SHIPPING_THRESHOLD`, not `100`.

## Types and data

- **Value types over primitives** (primitive obsession): an email, money amount, id or date range gets its own small type that validates itself on construction. Mixed-up arguments then fail to compile.

  ```
  // primitives: createUser("12345", "ana@x.org", "555-1234") compiles with the wrong order
  // value types: createUser(Email, PhoneNumber, ZipCode)
  type Email(value): require value matches EMAIL_FORMAT
  ```
- **Immutable by default**: records, data classes or frozen structs with all fields set at construction. No setters on domain values. Prefer records over hand-written getters, and a constructor or static factory over a builder unless there are many optional fields.
- Return unmodifiable collections or copies; never expose internal mutable state.
- Money is never a binary float. Time carries an offset or zone; inject a clock instead of reading the system time in domain code.
- Represent absence explicitly (option/optional type, nullable type with checks, or an empty collection), never as a magic value.

## Duplication (DRY, with judgement)

- One piece of **knowledge** (a rule, a format, a calculation) has one home. When a business rule is copied, extract it.
- **Rule of three**: tolerate a second copy; extract on the third, when the shared shape is clear.
- **Coincidental duplication is not duplication**: code that looks alike but serves different rules (shipping cost vs insurance cost) stays separate, because the rules will change independently.
- Do not merge two similar functions with a flag argument; extract the shared part instead.

## Errors

- Throw or return the most specific error type; never catch a generic error just to continue.
- Messages say what failed, why, and with which identifiers: `"Invoice INV-42 not found for customer C-7"`, not `"Error"`.
- When wrapping, keep the cause. Either handle an error or propagate it; do not log and rethrow (it is logged twice).
- Never swallow an error silently, and never return `null` to signal failure.
- Expected outcomes (not found, validation failed) are values or domain errors, not exceptions used as control flow, unless the project convention says otherwise.
- Validate fully at system boundaries (API, messages, files); inside the domain, check invariants once in constructors and trust them afterwards.
- Translate errors at layer boundaries: infrastructure errors become domain or application errors; the API layer maps them to responses (api-design skill).
- Retries with backoff, fallbacks and circuit breakers only where an NFR or ADR asks for them, and only for transient failures.

## Comments and documentation (summary)

- Code says what; comments say **why**: a constraint, a non-obvious decision, a workaround with its reason.
- Document every public API's contract: purpose, parameters and constraints, return value, errors and when they occur.
- No commented-out code, no comments that repeat the name, no stale docs; update docs in the same change as the behaviour.
- `TODO` only with a task id or issue reference.

Read `documentation.md` when writing or reviewing API documentation, module docs or comments.

## Review checklist

- [ ] Change stays within the task's scope; unrelated findings recorded, not fixed.
- [ ] No limit in the table exceeded in changed code (or the reason is stated).
- [ ] Names use the spec's domain vocabulary; no flag arguments; one abstraction level per function.
- [ ] Domain values are immutable value types; no primitive obsession in new signatures.
- [ ] No duplicated business rule; no premature abstraction.
- [ ] Errors are specific, carry context and causes, and are neither swallowed nor double-logged.
- [ ] No dead code, commented-out code or unused parameters introduced.
- [ ] Public APIs documented; comments explain why.

Read `refactoring.md` when deciding whether and how to refactor code in scope, or when prioritising findings in a review.

## Linked skills

- `architecture`: where code belongs (layer, module, port or adapter) before judging its structure.
- `module-testing`: every quality change in scope is covered by tests that still prove the acceptance criteria.
- `security`: error messages, logging and input validation rules overlap; apply both.
- `api-design`: error translation and DTO rules for the outer API layer.
- The project's language skill: idioms for value types, immutability, null handling and error types.
