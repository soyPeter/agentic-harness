# Java 17 to 25 feature reference

Status is for JDK 25. "Final" means usable without flags. Anything marked preview or incubator needs `--enable-preview` / `--add-modules` and is **forbidden without an accepted ADR** (the API changes between releases).

## Status table

| Feature | JEP | Final in | Notes |
|---|---|---|---|
| Switch expressions | 361 | 14 | `->` arms, `yield` in blocks |
| Text blocks | 378 | 15 | `"""` multi-line strings |
| Records | 395 | 16 | compact constructor validation |
| Pattern matching for `instanceof` | 394 | 16 | `if (o instanceof Foo f)` |
| `Stream.toList()` | - | 16 | unmodifiable, allows nulls |
| Sealed classes | 409 | 17 | `sealed ... permits` |
| Pattern matching for `switch` | 441 | 21 | type patterns, guards `when`, `case null` |
| Record patterns | 440 | 21 | deconstruction, nesting |
| Sequenced collections | 431 | 21 | `getFirst`, `getLast`, `reversed`, `addFirst` |
| Virtual threads | 444 | 21 | `Thread.ofVirtual()`, per-task executor |
| Unnamed variables and patterns `_` | 456 | 22 | unused lambda params, catch vars, patterns |
| Foreign function and memory API | 454 | 22 | replaces JNI for native calls |
| Markdown documentation comments | 467 | 23 | `///` comments |
| Stream gatherers | 485 | 24 | `stream.gather(Gatherers.windowFixed(n))` |
| Class-File API | 484 | 24 | for bytecode tools |
| Virtual threads synchronize without pinning | 491 | 24 | `synchronized` is fine with virtual threads |
| Key derivation function API | 510 | 25 | `javax.crypto.KDF` |
| Module import declarations | 511 | 25 | `import module java.base;` |
| Compact source files, instance `main` | 512 | 25 | `void main()`, `java.lang.IO` |
| Flexible constructor bodies | 513 | 25 | statements before `super(...)` |
| Scoped values | 506 | 25 | replaces `ThreadLocal` for context |
| Compact object headers | 519 | 25 (product) | opt-in `-XX:+UseCompactObjectHeaders` |
| AOT command-line ergonomics / method profiling | 514, 515 | 25 | `-XX:AOTCacheOutput=app.aot`, then `-XX:AOTCache=app.aot` |

Preview / incubator in JDK 25 (do not use without ADR):

| Feature | JEP | Status in 25 |
|---|---|---|
| Structured concurrency | 505 | 5th preview; `StructuredTaskScope.open(...)` + `Joiner` |
| Stable values | 502 | preview |
| Primitive types in patterns, `instanceof`, `switch` | 507 | 3rd preview |
| PEM encodings of cryptographic objects | 470 | preview |
| Vector API | 508 | incubator |

Withdrawn: string templates (`STR."..."`) were removed in JDK 23. Removed: Security Manager is permanently disabled (JDK 24).

## Pattern matching for switch and record patterns

```java
sealed interface Shape permits Circle, Rect {}
record Circle(double r) implements Shape {}
record Rect(double w, double h) implements Shape {}

double area(Shape s) {
    return switch (s) {
        case Circle(var r) -> Math.PI * r * r;
        case Rect(var w, var h) when w == h -> w * w;   // guard
        case Rect(var w, var h) -> w * h;
    };                                                   // exhaustive: no default
}

String classify(Object o) {
    return switch (o) {
        case null -> "null";                             // explicit, otherwise NPE
        case Integer i when i > 0 -> "positive int";
        case Integer _ -> "int";                         // unnamed pattern (22)
        case String s -> "string of " + s.length();
        default -> "other";                              // needed: Object is open
    };
}
```

Rules: order more specific cases first (the compiler rejects dominated cases); no `default` on sealed/enum switches you own; `case null` only when null is a legal input.

## Sequenced collections

```java
List<Order> orders = repository.recent();
Order newest = orders.getLast();          // not orders.get(orders.size() - 1)
List<Order> newestFirst = orders.reversed(); // view, not a copy
LinkedHashMap<String, Integer> m = new LinkedHashMap<>();
m.putFirst("a", 1);
var first = m.firstEntry();
```

`getFirst()` on an empty list throws `NoSuchElementException`.

## Unnamed variables

```java
try { Integer.parseInt(s); return true; } catch (NumberFormatException _) { return false; }
map.forEach((_, value) -> total.add(value));
```

## Stream gatherers (24)

```java
List<List<Reading>> batches = readings.stream().gather(Gatherers.windowFixed(100)).toList();
List<Integer> runningSum = numbers.stream().gather(Gatherers.scan(() -> 0, Integer::sum)).toList();
```

Built-ins: `windowFixed`, `windowSliding`, `fold`, `scan`, `mapConcurrent` (runs the mapper on virtual threads with a concurrency limit).

## Scoped values (25)

```java
private static final ScopedValue<RequestContext> CONTEXT = ScopedValue.newInstance();

void handle(Request req) {
    ScopedValue.where(CONTEXT, RequestContext.from(req)).run(() -> service.process(req));
}
Result handleWithResult(Request req) throws Exception {
    return ScopedValue.where(CONTEXT, RequestContext.from(req)).call(() -> service.compute(req));
}
// deeper in the call stack
RequestContext ctx = CONTEXT.get();          // NoSuchElementException if unbound
boolean bound = CONTEXT.isBound();
```

- Declare `static final`. Bindings are immutable and end with the `run`/`call` scope: no `set`, no `remove`, no leaks.
- Multiple bindings: `ScopedValue.where(A, a).where(B, b).run(...)`.
- `ScopedValue.runWhere`/`callWhere`/`getWhere` no longer exist (removed in JDK 24).
- Bindings are inherited by subtasks of structured concurrency (preview), not by arbitrary executor threads.

## Flexible constructor bodies (25)

```java
public final class PositiveAmount extends Amount {
    public PositiveAmount(BigDecimal value) {
        if (value.signum() <= 0) throw new IllegalArgumentException("must be positive");
        super(value);                       // validation runs before the superclass constructor
    }
}
```

Statements before `super(...)` may not read instance fields or use `this`. Records still validate in the compact constructor.

## Module imports and compact source files (25)

```java
import module java.base;      // all packages exported by java.base
import java.util.List;        // single-type import wins over module import on ambiguity
```

Prefer explicit imports in production sources; module imports suit scripts, tests, prototypes.

```java
// Tool.java - run with: java Tool.java
void main() {
    IO.println("rows: " + countRows());
}
```

Compact source files implicitly import `java.base`. Not for application entry points.

## Key derivation (25)

```java
KDF hkdf = KDF.getInstance("HKDF-SHA256");
AlgorithmParameterSpec params = HKDFParameterSpec.ofExtract()
        .addIKM(inputKeyMaterial).addSalt(salt).thenExpand(info, 32);
SecretKey key = hkdf.deriveKey("AES", params);
```

## Virtual threads (21, pinning fix 24)

```java
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    List<Future<Price>> futures = skus.stream().map(sku -> executor.submit(() -> client.price(sku))).toList();
    for (var f : futures) prices.add(f.get());
}   // close() waits for all tasks
```

- One virtual thread per task; never pool them.
- Since JDK 24 (JEP 491) blocking inside `synchronized` no longer pins the carrier. Pinning can still occur in native frames (JNI/FFM upcalls); diagnose with JFR event `jdk.VirtualThreadPinned`.
- Bound access to limited resources (DB connections, rate-limited APIs) with a `Semaphore` or the resource's own pool.
- Do not cache expensive objects in `ThreadLocal`: with millions of threads that is millions of copies.
- No gain for CPU-bound work; use a bounded platform pool or parallel streams for that.

## Structured concurrency (preview in 25; ADR required)

Shown only so you recognise it; the API changed in every preview.

```java
// JDK 25 preview API (--enable-preview). Not ShutdownOnFailure: that class no longer exists.
try (var scope = StructuredTaskScope.open()) {           // default joiner: fail on first failure
    Subtask<User> user = scope.fork(() -> users.find(id));
    Subtask<List<Order>> orders = scope.fork(() -> orderClient.forUser(id));
    scope.join();
    return new Profile(user.get(), orders.get());
}
```

Final alternative without an ADR: a virtual-thread executor with `Future`s as above, cancelling outstanding futures on failure.
