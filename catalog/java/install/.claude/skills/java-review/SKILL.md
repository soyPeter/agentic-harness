---
name: java-review
description: Java review checklist for the judge and reviewers - severity rules aligned with the harness judge (blocker/major/minor), Java correctness checks (null, exceptions, collections, concurrency, resources, equality, API misuse), stack checks conditional on the ADRs and adopted options (Lombok, Spring, layering), records, constructor injection and size/complexity thresholds. Use when judging a task or reviewing Java changes.
applies-to: java>=21 (examples target Java 25)
last-verified: 2026-10-05
sources: adapted from decebals/claude-code-java java-code-review and solid-principles (0d98fe9) and cuioss/plan-marshall java-maintenance (refactoring-triggers, compliance-checklist); Spring/Lombok/JPA checks replaced by checks conditional on the stack ADR and pack options; thresholds aligned with the harness code-quality skill
---

# Java review

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

Review the diff against the task spec first, then the code. Rules come from `backbone/4-KNOWLEDGE.md` (NEVER DO), accepted ADRs, `java`, `java-test` (if adopted), `code-quality`, `module-testing` and `security`. Report every finding as `file:line - issue - fix`.

## Severity

| Severity | Use when | Examples |
|---|---|---|
| **blocker** | a requirement or AC is unmet; an ADR or NEVER-DO rule is violated; behaviour is broken | AC without a test that names it; import of a library or framework the ADRs rule out (e.g. Lombok under `no-lombok`, Spring under `no-spring`); preview feature without ADR; domain imports infrastructure under `hexagonal-layers`; compile error; failing test; swallowed exception hiding a failure; secret in code or logs; SQL built by string concatenation with input |
| **major** | a real defect, or a test that does not prove its criterion | NPE path; race condition; resource leak; mutable collection escaping a record; `equals` without `hashCode`; catch-all that changes behaviour; test with no assertion or asserting only `isNotNull()`; test that passes with the feature removed; `Thread.sleep` in a test; mocking the class under test; unbounded query |
| **minor** | style or clarity, no behaviour impact | naming; magic number; method slightly over threshold; redundant comment; getter-style name on a record; missing `@DisplayName` on a non-AC test |

Do not inflate: a style preference is minor even if it is repeated. Do not deflate: a missing AC test is a blocker even if the code looks right.

## 1. Spec and tests (do first)

- [ ] Every AC id of the task appears in a test (`@DisplayName("AC-x.y-z: ...")` or the parameterised name) and that test exercises the behaviour the AC states, including its negative/edge path.
- [ ] Assertions are specific: exact values, exact collection contents, exception type **and** message. If option `junit5-assertj` is adopted: AssertJ only, no JUnit `assertEquals`/`assertTrue`/`assertThrows`.
- [ ] Would the test fail if the production change were reverted? If not: major.
- [ ] No sleeps, real clock, network, order dependence or shared static state.
- [ ] Mocks only at ports; outcomes asserted rather than mere interactions.
- [ ] Tests ran and passed (`HARNESS_TEST_CMD`: Gradle `./gradlew test` · Maven `./mvnw test`); a bug fix has a reproducing test.

## 2. Stack rules (blocker when an adopted rule is violated)

Check the accepted stack and architecture ADRs for which pack options were adopted; apply only the matching lines.

- [ ] Option `no-lombok`: no `lombok.*` imports or annotations.
- [ ] Option `no-spring` (quarkus pack): no `org.springframework.*` imports or annotations.
- [ ] Option `hexagonal-layers`: domain packages (`..domain..`) import no framework, persistence, HTTP or JSON types (e.g. `jakarta.*`, `io.quarkus.*`, `org.jdbi.*`, `com.fasterxml.*`, `java.sql.*`); the application layer does not import infrastructure.
- [ ] Always: no `--enable-preview` / preview API (on Java 25: `StructuredTaskScope`, `StableValue`, primitive patterns) without an accepted ADR.
- [ ] Always: new dependencies are covered by an ADR or the task spec.
- [ ] Idiom (major only if it causes a defect, else minor): DTOs, commands, events and value objects are records with compact-constructor validation; accessors `x()`, not `getX()`; constructor injection with `private final` fields rather than field or setter injection.

```bash
grep -rn "import lombok" --include=*.java src                     # if no-lombok
grep -rn "org\.springframework" --include=*.java src             # if no-spring
grep -rn "^import" --include=*.java src/main/java | grep "/domain/" \
  | grep -E "jakarta\.|io\.quarkus|org\.jdbi|com\.fasterxml|java\.sql"   # if hexagonal-layers
```

## 3. Null safety and Optional

- [ ] Public constructors/methods reject `null` (`Objects.requireNonNull`) where null is not legal.
- [ ] No method returning a collection, array or `Optional` returns `null`.
- [ ] No `Optional.get()` without proof of presence; no `Optional` fields, parameters or record components.
- [ ] Chained calls on values that can be absent (`a.b().c()` where `b()` may be null).
- [ ] Unboxing of possibly-null wrappers (`int x = map.get(k)`).
- [ ] `equals` called on a possibly-null receiver; use `Objects.equals` or constant-first.

## 4. Exceptions

- [ ] Specific exception types; no `throw new RuntimeException/Exception`.
- [ ] Cause always chained; no `catch (Exception e) { throw new X(e.getMessage()); }` (cause lost).
- [ ] No empty catch without a justifying comment; no `catch (Throwable)` / `catch (Exception)` below the top-level boundary.
- [ ] Infrastructure exceptions translated in the adapter; HTTP mapping only in the API layer.
- [ ] Logged once, where handled; no log-and-rethrow.
- [ ] `InterruptedException` restores the interrupt flag.
- [ ] No exceptions used for expected control flow.

## 5. Collections and immutability

- [ ] Records copy collection components (`List.copyOf`); getters/accessors never expose mutable internals.
- [ ] No modification of a collection while iterating it (use `removeIf` or an iterator).
- [ ] `Stream.toList()` unless mutation is needed; streams have no side effects in `map`/`filter`.
- [ ] Membership tests in loops use a `Set`/`Map`.
- [ ] `equals`/`hashCode` overridden together on non-record classes used in sets/maps, over the same immutable fields; mutable fields in a `hashCode` are a defect.
- [ ] `compareTo` consistent with `equals` for sorted collections.
- [ ] Switches over enums/sealed types are exhaustive without `default`.

## 6. Concurrency

- [ ] Shared mutable state is guarded (lock, atomic, concurrent collection) or eliminated.
- [ ] No check-then-act races (`containsKey` + `put`; `get() < MAX` + increment).
- [ ] No lock held while calling external code; consistent lock order.
- [ ] Executors closed; virtual threads not pooled; blocking I/O not on the common pool.
- [ ] `CompletableFuture` failures handled; remote calls have timeouts.
- [ ] `ScopedValue` API correct for Java 25: `ScopedValue.where(K, v).run/call`; no `runWhere`.

Read `.claude/skills/java/concurrency.md` for the full concurrency checklist.

## 7. Resources and I/O

- [ ] Every `AutoCloseable` (streams, readers, connections, `ExecutorService`, `HttpClient` response bodies) in try-with-resources.
- [ ] Explicit charset (`StandardCharsets.UTF_8`) on byte/char conversions.
- [ ] Timeouts on every network call.
- [ ] Queries paginated or bounded; no per-item query in a loop.

## 8. API misuse and common bugs

- [ ] `==` on strings or boxed numbers; `BigDecimal.equals` where `compareTo` was meant; `new BigDecimal(double)`.
- [ ] `double`/`float` for money.
- [ ] `Date`/`Calendar`/`SimpleDateFormat` instead of `java.time`; `Instant.now()`/`LocalDate.now()` without an injected `Clock` in testable logic.
- [ ] Integer overflow in arithmetic on sizes, money in cents or time (`Math.addExact`, `long`).
- [ ] `String.format`/concatenation in log calls; secrets or PII in logs or exception messages.
- [ ] Regex compiled per call in hot paths; `String +=` in loops.
- [ ] `Random` for security-relevant values (use `SecureRandom`); hard-coded credentials.
- [ ] `switch` fall-through or missing cases on open input without `default -> throw`.

## Thresholds

Same numbers as `code-quality`; exceeding one is minor, exceeding it by 2x or hiding a defect is major.

| Metric | Limit |
|---|---|
| Method length | ≤ 50 lines |
| Cyclomatic complexity per method | ≤ 15 |
| Parameters | ≤ 4 (else a parameter record) |
| Nesting depth | ≤ 3 |
| Class length | ≤ 500 lines |
| Boolean parameters | none in public APIs (use an enum or two methods) |
| `if`/`else if` chain over constants | ≥ 3 branches: enum + exhaustive switch |
| Duplicated block | ≥ 3 copies of ≥ 5 lines: extract |
| Magic numbers/strings | named constant unless 0, 1, -1 or obvious in context |
| Unused code | no unused imports, private methods, parameters or fields |
| Commented-out code | none |
| `TODO` | only with a task/issue reference |
| Field/setter injection | none unless the ADR or framework requires it |
| Mutable public static fields | none |
| Hand-written data classes | replace with a record (fields + equals/hashCode/toString only) |

## Output

For the harness judge, findings go into the verdict JSON (`severity`, `file`, `line`, `issue`, `fix`). For a human review, group by severity, blockers first, and end with what is good about the change only if it informs the decision.

Read `solid.md` when a finding concerns class responsibilities, extension points, inheritance, interface size or dependency direction.

## Linked skills

- `java`: the rules the code must follow.
- `java-test` (if adopted): what a sufficient test looks like.
- `code-quality`: general quality rules and refactoring triggers.
- `module-testing`: test method and coverage expectations.
- `security`: security checklist for inputs, secrets and crypto.
- `architecture`: layer and dependency rules.
- `quarkus`, `quarkus-cdi`, `jdbi` (if adopted): framework-specific review points.
