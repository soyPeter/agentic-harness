# Architecture review

Part of the `architecture` skill. Use it for an architecture review of a change, a module or the whole codebase. The project's own rules (architecture ADR, `2-PLANNING.md`, NEVER DO in `4-KNOWLEDGE.md`, `backbone/guardrails.conf`) define what is a violation; this file gives the method.

## Method

1. Read the architecture and stack ADRs to learn the intended style (layered, hexagonal, modular monolith, services) and the package or directory conventions.
2. Map the structure: `find <src> -type d | head -50`; identify modules and layers.
3. Run the import-leak checks below for every inner layer.
4. Sample two or three features end to end (entry point to persistence); don't read every file.
5. Compare against the smells and anti-patterns; write findings in the report format.
6. Limit findings to what the review was asked to cover. In a task review, issues outside the task's code are recorded in `backbone/6-MEMORY.md` or proposed as tasks, not fixed.

## Hexagonal vocabulary (check that code uses it correctly)

| Term | Meaning | Typical names |
|---|---|---|
| Inbound port (driving) | Interface through which the outside drives the application: use cases | `CreateOrderUseCase`, `PlaceOrder` |
| Inbound adapter (driving) | Calls an inbound port: REST resource, message listener, CLI, scheduler | `OrderResource`, `OrderEventListener` |
| Outbound port (driven) | Interface the application needs from the outside world, defined by the application or domain | `OrderRepository`, `PaymentGateway`, `Clock` |
| Outbound adapter (driven) | Implements an outbound port with a technology | `JdbcOrderRepository`, `StripePaymentGateway` |

- Dependencies point inward: adapters -> application -> domain. Inner code never imports adapters.
- A port with a single adapter is normal and not a smell.
- Port signatures use domain types, never transport or persistence types (no HTTP request objects, ORM entities, result sets).

## Smells

| Smell | Symptom | Impact | Typical fix |
|---|---|---|---|
| Framework in the domain | Domain imports framework, ORM, DI, serialisation or validation packages | Core logic tied to infrastructure; hard to test | Pure domain types; mapping in adapters |
| Wrong dependency direction | Domain or application imports an adapter package | Cycles; changes ripple inward | Introduce or use an outbound port |
| Circular dependencies | Package A -> B -> A | Untestable, cannot extract modules | Extract the shared concept, or invert with a port or event |
| Leaky abstraction | Controller builds SQL; repository returns HTTP responses; port exposes ORM entities | Layers can't change independently | Move logic to its layer; map at the boundary |
| Logic in adapters | Business rules in controllers, listeners or repositories | Duplicated rules; tests need infrastructure | Move to domain or application layer |
| Cross-module reach-in | Module reads another module's tables or internal classes | Hidden coupling; broken ownership | Use the other module's public API or events |
| God package | One package with dozens of unrelated classes | Hard to navigate; unclear ownership | Split by feature within the layer |
| Inconsistent structure | Same concept organised differently across modules | Slow onboarding; misplaced code | Align with the architecture ADR |
| Unjustified dependency | New library without an ADR where the rules require one | Uncontrolled stack growth | ADR or removal |

## Anti-patterns

### Big ball of mud

No visible structure: hundreds of files in one package, everything imports everything. Fix incrementally: agree the target structure in an ADR, then move one feature at a time behind tests. Never as a side effect of an unrelated task.

### Util dumping ground

`util/`, `common/`, `helpers/` growing with domain logic (`OrderCalculator`, `UserHelper`). Keep only genuinely generic, dependency-free helpers there; move domain logic to the module that owns the concept.

### Anemic versus rich domain (judge in context)

An anemic model (data-only entities, all rules in services) is a smell **when the domain has real invariants**: rules about an entity are scattered across services and can be bypassed. Move each invariant into the entity or a value type so it cannot be violated.

It is **not** a smell when:
- the module is CRUD or data transfer with no business rules;
- the architecture ADR deliberately chooses transaction scripts or a functional core with plain data plus pure functions.

### Framework coupling in the domain

Domain types carrying persistence, serialisation, validation or DI annotations, or generated-code annotations the NEVER DO list forbids. Separate the domain model from persistence and API models and map between them in adapters.

## Import-leak checks

Parameterise by stack: `<inner dirs>` are the domain (and usually application) source directories from the architecture ADR; `<framework packages>` come from the stack and the NEVER DO list.

```bash
# Framework or infrastructure imports in an inner layer (must print nothing)
grep -rnE '^import (static )?(<framework packages>)' <domain dir>

# Inner layer importing adapters (must print nothing)
grep -rnE '^import .*\.(adapter|infrastructure)\.' <domain dir> <application dir>

# Largest packages (god-package candidates)
find <src> -name '*.<ext>' | xargs -n1 dirname | sort | uniq -c | sort -rn | head -10
```

Example for a Java codebase (derive the package list from the stack ADR and the NEVER DO list; for Python use `^(from|import) (<packages>)`, for TypeScript `from ['\"](<packages>)`):

```bash
grep -rnE '^import (static )?(io\.quarkus|jakarta\.(inject|enterprise|ws|persistence|transaction)|javax\.(inject|persistence)|org\.springframework|org\.jdbi|lombok|com\.fasterxml\.jackson)\.' src/main/java/<base>/domain
```

Other stacks: TypeScript `grep -rnE "from '(express|@nestjs|typeorm|prisma|axios)" src/domain`; Python `grep -rnE '^(from|import) (django|flask|fastapi|sqlalchemy|requests)' src/<pkg>/domain`; Go `grep -rn '"net/http"\|"database/sql"' internal/domain`.

Circular dependencies: if the stack has a tool (ArchUnit, dependency-cruiser, import-linter, `go vet` cycle errors, jdeps), use it. Otherwise, for each pair of packages A and B, check whether A imports B and B imports A.

Prefer turning each recurring check into a rule in `backbone/guardrails.conf` (regex) or an architecture test, so it is enforced rather than reviewed.

## Review checklist

- [ ] Structure matches the architecture ADR; naming is consistent across modules.
- [ ] Inner layers have no framework or adapter imports (checks above print nothing).
- [ ] Inbound ports are use cases called by driving adapters; outbound ports are defined inward and implemented by driven adapters.
- [ ] No circular dependencies between packages or modules.
- [ ] Controllers, listeners and repositories contain no business rules.
- [ ] DTOs at the boundaries; domain types inside; mapping in adapters.
- [ ] Modules expose a small public API; internals are not visible to other modules.
- [ ] Each module owns its data; no cross-module table access.
- [ ] Transactions are bounded as the ADRs say; cross-module effects are explicit (events, outbox).
- [ ] New dependencies and structural changes have ADRs.

## Findings report format

```markdown
## Architecture review: <scope>

### Structure
- Style: <layered | hexagonal | modular monolith | ...> per ADR-<NNN>
- Conformance: <conforms | minor deviations | significant deviations>

### Findings
| Severity | Finding | Location | Rule violated | Recommendation |
|---|---|---|---|---|
| High | Domain imports ORM annotations | `domain/Order.<ext>:3` | ADR-002, NEVER DO #4 | Separate persistence entity in the adapter |
| Medium | Business rule in controller | `adapter/in/web/OrderResource.<ext>:57` | architecture skill | Move to `PlaceOrder` use case |
| Low | `util/` holds `PriceCalculator` | `util/PriceCalculator.<ext>` | - | Move to the pricing module |

### Dependency analysis
<direction of dependencies, cycles found, leak-check output>

### Recommendations
1. <highest priority, with the ADR or task it needs>
2. ...
```

Severity: **High** violates an accepted ADR or NEVER DO rule, or blocks testing; **Medium** erodes boundaries and will spread; **Low** is consistency or naming.
