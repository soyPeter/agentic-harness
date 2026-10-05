---
name: java
description: Java coding rules (Java 21+, examples target 25) - core rules and stack-dependent rules decided by ADR, final vs preview language features, enums and sealed types with exhaustive switch, immutability, exceptions, null/Optional, concurrency, performance smells and logging. Read before every .java edit and when writing Java-related ADRs.
applies-to: java>=21 (examples target Java 25)
last-verified: 2026-10-05
sources: adapted from cuioss/plan-marshall pm-dev-java java-core (standards/java-17/21/25-features, java-concurrency, java-performance-patterns; enum+switch section from current upstream) and decebals/claude-code-java concurrency-review, performance-smell-detection, logging-patterns (0d98fe9); Spring/Lombok/JPA content removed, tool and policy choices made conditional on the stack ADR and java pack options, and Java 25 facts corrected against JEPs 491, 502, 505, 506, 507, 511-513, 519
---

# Java

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

## Core rules

1. Language level: the Java release the stack ADR chose (this skill assumes 21+; examples use 25 LTS). Do not raise or lower it without an ADR.
2. Build and test with the commands in `backbone/harness.conf`: `HARNESS_BUILD_CMD`, `HARNESS_TEST_CMD` (Gradle option: `./gradlew compileJava compileTestJava -q` / `./gradlew test`; Maven option: `./mvnw -q -DskipTests test-compile` / `./mvnw -q test`). Use only the build tool the ADR chose; never add a second build next to it.
3. Prefer records for DTOs, value objects, commands, events and entities that do not need identity mutation. Validate in the compact constructor.
4. Use record accessors (`customer.name()`); never add `getName()` to a record.
5. Prefer constructor injection with dependencies in `private final` fields over field or setter injection (testable, immutable, explicit).
6. One top-level public type per file; package names lower case, by feature (`customer`, `order`), not by layer suffix soup.
7. No preview or incubator features (`--enable-preview`, `jdk.incubator.*`) without an accepted ADR.
8. No `System.out`/`printStackTrace()` in production code; use the logger.
9. Public methods of public types validate arguments; private methods trust their callers.
10. Methods: one level of abstraction, ≤ 50 lines, ≤ 4 parameters (else a parameter record), cyclomatic complexity ≤ 15.

```java
public record Customer(CustomerId id, String name, List<Email> emails) {
    public Customer {
        Objects.requireNonNull(id, "id");
        if (name == null || name.isBlank()) throw new IllegalArgumentException("name must not be blank");
        emails = List.copyOf(emails);               // defensive, unmodifiable, rejects null elements
    }
    public Customer withName(String newName) { return new Customer(id, newName, emails); }
}
```

## Stack-dependent rules (apply only when the ADR or pack option says so)

- **Lombok:** if the stack ADR rules out Lombok (java option `no-lombok`), do not import `lombok.*`: records replace `@Data`/`@Value`; static factories or record `with`-style methods replace `@Builder`; `private static final Logger` replaces `@Slf4j`. Otherwise follow the ADR on where Lombok is allowed.
- **Frameworks:** use only the frameworks and libraries the ADRs accept; framework specifics live in their own skill if that pack is adopted (`quarkus`, `quarkus-cdi`, `jdbi`). If the quarkus option `no-spring` is adopted, no `org.springframework.*` imports or annotations.
- **Layering:** if the architecture ADR uses hexagonal layering (option `hexagonal-layers`), domain packages import no framework, persistence or transport types (see `architecture`).

## Language level (Java 25 shown)

Final by Java 25 (a number in parentheses is the release that finalised it; use it only if the ADR's release has it): records, sealed types, `switch` expressions, pattern matching for `instanceof` and `switch`, record patterns, text blocks, `var` for locals with obvious types, sequenced collections (`getFirst()`, `getLast()`, `reversed()`), virtual threads, unnamed variables/patterns `_` (22), stream gatherers `Stream.gather(...)` (24), Markdown doc comments `///` (23).

Final in Java 25:
- **Scoped values** (JEP 506): `ScopedValue.where(KEY, value).run(() -> ...)` or `.call(() -> ...)`; read with `KEY.get()`, test with `KEY.isBound()`. There is no `runWhere`/`callWhere` (removed in JDK 24). Prefer over `ThreadLocal` for request context.
- **Flexible constructor bodies** (JEP 513): validate or compute arguments before `super(...)`/`this(...)`; no `this` access before the call.
- **Module import declarations** (JEP 511): `import module java.base;` acceptable in scripts/tests; in production code prefer explicit imports (clearer diffs, no ambiguity).
- **Compact source files and instance `main`** (JEP 512): for scripts and tooling only, not application entry points.
- **Key derivation API** (JEP 510): `javax.crypto.KDF` (HKDF) instead of third-party HKDF code.
- **Compact object headers** (JEP 519): product feature, opt-in with `-XX:+UseCompactObjectHeaders`; a JVM flag decision, record it in an ADR or the container config.

Preview in Java 25 - **not without an ADR**: structured concurrency (JEP 505, `StructuredTaskScope.open(...)` with `Joiner`s; the old `ShutdownOnFailure`/`ShutdownOnSuccess` classes do not exist in 25), stable values (JEP 502), primitive types in patterns (JEP 507), PEM encodings (JEP 470). Vector API is incubator. String templates were withdrawn; do not use `STR."..."`.

Read `java25-features.md` when using a feature introduced after Java 17 or deciding whether something is final.

## Closed sets: enum + exhaustive switch, sealed + patterns

An `if`/`else if` chain testing one value against constants and ending in `throw` is a switch in disguise. Model the set as an enum and switch exhaustively: no `default`, and a new constant becomes a compile error, not a runtime exception.

```java
enum TokenKind { JWT, OAUTH2, LEGACY }
String label(TokenKind kind) {
    return switch (kind) { case JWT -> "JSON Web Token"; case OAUTH2 -> "OAuth 2.0"; case LEGACY -> "Legacy"; };
}
sealed interface PaymentResult permits Approved, Declined {}
record Approved(String authCode) implements PaymentResult {}
record Declined(String reason) implements PaymentResult {}
String describe(PaymentResult r) {
    return switch (r) { case Approved(var code) -> "ok " + code; case Declined(var why) -> "declined: " + why; };
}
```

If the input must stay a `String` (wire format), parse it to the enum at the boundary; a string `switch` keeps `default -> throw`. Never add `default` to a switch over a sealed type or enum you own: it hides missing cases.

## Immutability and collections

- Fields `private final` by default; a class with no setters and final fields of immutable types is immutable.
- Records holding collections: `List.copyOf`/`Set.copyOf`/`Map.copyOf` in the compact constructor. Never expose a mutable internal collection.
- Return `List.of()`/`Map.of()` for empty results, never `null`.
- `stream.toList()` (unmodifiable) instead of `collect(Collectors.toList())` unless the caller must mutate. Note `List.copyOf` and `List.of` reject `null` elements; `Stream.toList()` accepts them.
- Do not mutate a collection passed in as a parameter; return a new one.
- Use `Map.getOrDefault`, `computeIfAbsent`, `merge` instead of get-check-put.
- `equals`/`hashCode` come for free on records; on a hand-written class, override both or neither, over the same fields.
- Prefer `java.time` (`Instant`, `LocalDate`, `Duration`) and inject a `Clock` for testability; never `Date`/`Calendar`.
- Money: `BigDecimal` with explicit scale and `RoundingMode`, or a `Money` record; never `double`.
- Use interfaces in signatures (`List`, `Map`), concrete types only at construction.

## Exceptions

- Throw the most specific type: `IllegalArgumentException` (bad argument), `IllegalStateException` (wrong state), a domain exception (`CustomerNotFoundException extends RuntimeException`) for business rules. Never `throw new RuntimeException("...")` or `Exception`.
- Prefer unchecked domain exceptions; use checked exceptions only when the caller can realistically recover.
- Always chain: `throw new StorageException("save failed for " + id, e);` - never drop the cause.
- No catch-all: no `catch (Exception e)` / `catch (Throwable t)` except at a top-level boundary (request handler, scheduled job, main), and there log and translate.
- Never swallow: an empty `catch` needs a comment explaining why ignoring is correct.
- Translate at layer boundaries: infrastructure exceptions (SQL, HTTP client) become domain/application exceptions in the adapter; the API layer maps them to responses (see `api-design`).
- Log **once**, where handled. Do not log-and-rethrow.
- Do not use exceptions for normal control flow (e.g. `Optional` or a result type for "not found" in queries).
- `try-with-resources` for every `AutoCloseable` (streams, connections, `ExecutorService`).
- `InterruptedException`: restore the flag (`Thread.currentThread().interrupt()`) then rethrow or exit.

## Null and Optional

- `Optional<T>` is for **return values** that may be absent (`Optional<Customer> findById(CustomerId id)`). Never for fields, parameters, record components or collections.
- Never return `null` from a method that returns a collection, array or `Optional`.
- Do not call `optional.get()`; use `orElseThrow(() -> new CustomerNotFoundException(id))`, `map`, `orElse`, `ifPresentOrElse`.
- `Objects.requireNonNull(x, "x")` at public boundaries and in compact constructors; it documents the contract and fails fast.
- Compare with possibly-null values via `Objects.equals(a, b)` or constant-first `"x".equals(s)`.
- Unboxing a `null` `Integer`/`Long` throws NPE; prefer primitives where absence is impossible.

## Concurrency essentials

- Avoid shared mutable state first: immutable records, confinement, message passing.
- I/O-bound concurrency: virtual threads, `try (var exec = Executors.newVirtualThreadPerTaskExecutor()) { ... }`. Do not pool virtual threads; limit access to scarce resources with a `Semaphore`.
- CPU-bound work: a bounded platform pool sized to cores. Name threads; shut executors down (try-with-resources).
- `synchronized` is fine on Java 24+ (JEP 491 removed virtual-thread pinning for monitors in JDK 24). Use `ReentrantLock` only when you need tryLock, timeouts or conditions; unlock in `finally`.
- Check-then-act on shared state must be atomic: `ConcurrentHashMap.computeIfAbsent`/`merge`, `AtomicInteger`, or a lock.
- Lazy init: holder idiom or `computeIfAbsent`. Volatile double-checked locking is correct (Java 5+) but rarely needed.
- `AtomicReference.updateAndGet` may call its function more than once: keep it side-effect free and cheap.
- `ScopedValue` instead of `ThreadLocal` for per-request context (final from Java 25; preview before).
- Document thread-safety of every shared class (`// Thread-safe: immutable` or which lock guards what).

Read `concurrency.md` when writing or reviewing code that shares state between threads, uses executors, locks, atomics, `CompletableFuture` or virtual threads.

## Performance smells (measure first)

- Precompile regex: `private static final Pattern EMAIL = Pattern.compile(...)`; no `String.matches`/`split(regex)`/`replaceAll` in loops.
- No `+=` string concatenation in loops; use `StringBuilder` or `Collectors.joining`.
- Membership tests in loops: `Set`/`Map`, not `List.contains` (O(n) per call).
- Avoid boxing in hot paths (`long` not `Long` accumulators; `IntStream`/`mapToLong`).
- Unbounded reads are a defect: paginate queries (keyset or `LIMIT`) and bound queues/caches.
- Optimise only with evidence (profiler, JFR, benchmark). Readability wins elsewhere.

Read `performance.md` when touching a hot path, batch job, large collection or query, or reviewing for performance.

## Logging

- One `private static final` logger per class (SLF4J `LoggerFactory.getLogger(X.class)`, or JBoss/Quarkus `Log`, as the project uses).
- Parameterised messages only: `log.info("order placed id={} items={}", id, n)` (SLF4J) / `Log.infof("order placed id=%s", id)` (JBoss). Never string concatenation.
- SLF4J `debug(String, Object)` takes no supplier lambda; guard expensive arguments with `if (log.isDebugEnabled())`.
- Pass the exception as the last argument (`log.error("payment failed id={}", id, e)`) so the stack trace is kept.
- Levels: ERROR needs action, WARN degraded but handled, INFO business events, DEBUG diagnostics. No INFO inside loops.
- Log once at the boundary that handles the error; include identifiers (ids, correlation id), not whole objects.
- **Never log** secrets, tokens, passwords, keys, full card numbers or PII (emails, names, addresses); mask or omit. Beware `toString()` of records holding such fields: override it to redact.

## Naming and structure

- Types are nouns (`CustomerSearch`, `PlaceOrder`), methods verbs (`findByEmail`, `place`), booleans read as questions (`isActive`, `hasLines`). No `Manager`/`Helper`/`Util` grab-bags; no Hungarian prefixes; no abbreviations beyond the ubiquitous (`id`, `url`).
- Constants `UPPER_SNAKE_CASE`, `private static final`; no magic numbers or strings in logic.
- Utility holders are `final` classes with a private constructor; prefer methods on the record/domain type they concern.
- Prefer composition over inheritance; classes `final` unless designed for extension.
- No boolean flag parameters in public APIs; use an enum or two methods.
- Javadoc on public API types and non-obvious methods: contract, units, nullability, thrown exceptions. Comments explain why, not what. No commented-out code; `TODO` only with a task reference.

## Before finishing an edit

- [ ] Compiles with no new warnings: `HARNESS_BUILD_CMD` (Gradle `./gradlew compileJava compileTestJava` · Maven `./mvnw -DskipTests test-compile`).
- [ ] No preview usage without an ADR; Lombok, Spring and domain-layer imports only as the ADRs and adopted options allow.
- [ ] New records validate in the compact constructor and copy collections.
- [ ] Every switch over an owned enum/sealed type is exhaustive without `default`.
- [ ] No `null` returned for collections/Optional; no `Optional.get()`.
- [ ] Exceptions specific, chained, logged once; resources in try-with-resources.
- [ ] Logs parameterised and free of secrets/PII.
- [ ] Tests updated (per `java-test` if adopted), naming the AC ids they prove.

## Linked skills

- `java-test` (if adopted, option `junit5-assertj`): writing or changing tests.
- `java-review`: reviewing Java code or judging a task.
- `code-quality`: general complexity, naming and refactoring rules.
- `architecture`: package/layer boundaries, ports and adapters.
- `security`: input validation, secrets, crypto, injection.
- `api-design`: mapping exceptions to HTTP responses.
- `quarkus`, `quarkus-cdi` (if adopted): CDI scopes, config, Quarkus specifics.
- `jdbi` (if adopted): SQL persistence and pagination queries.
- `adr-writing`: to adopt a preview feature, JVM flag or new dependency.
