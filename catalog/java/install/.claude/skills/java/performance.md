# Java performance smells

Measure before optimising: a profiler (async-profiler, JFR via `-XX:StartFlightRecording`), a JMH benchmark, or production metrics. "Looks slow" is not a measurement. Fix high-severity smells on sight; medium ones only on a hot path with evidence; low ones when touching the code anyway.

## Severity table

| Smell | Severity | Fix |
|---|---|---|
| Unbounded query / collection / queue / cache | High | paginate (keyset or `LIMIT`), bound queue capacity, size-limited cache with eviction |
| `Pattern.compile` / `String.matches` / `replaceAll` / `split(regex)` in a loop | High | `static final Pattern` |
| N+1 remote or database calls in a loop | High | batch query (`WHERE id IN (...)`), bulk API, join |
| String `+=` in a loop | High | `StringBuilder`, `Collectors.joining`, `String.join` |
| Parallel stream with shared mutable state | High | collect with a collector; no side effects |
| Exceptions for normal control flow in hot paths | Medium | `Optional`, result type, pre-check |
| `List.contains`/`indexOf` inside a loop | Medium | build a `HashSet`/`HashMap` once |
| Boxing in hot paths (`Long` accumulator, `List<Integer>` math) | Medium | primitives, `IntStream`/`LongStream`, `mapToLong` |
| Stream pipeline inside a tight inner loop (>100k iterations) | Medium | measure; a plain loop may win |
| Platform threads for many blocking I/O tasks | Medium | virtual threads |
| Logging with eager expensive arguments | Medium | parameterised message + level guard |
| Missing initial capacity for large known-size collections | Low | `new ArrayList<>(n)`, `HashMap.newHashMap(n)` (19+) |
| `toArray(new T[size])` | Low | `toArray(T[]::new)` or `toArray(new T[0])` |

## Strings

```java
// Bad: O(n^2) copying
String csv = "";
for (var row : rows) csv += row.id() + ",";
// Good
String csv = rows.stream().map(r -> r.id().toString()).collect(Collectors.joining(","));
```

A single `a + b + c` expression outside a loop is fine (compiled to `invokedynamic` concatenation).

## Regular expressions

```java
private static final Pattern SKU = Pattern.compile("[A-Z]{3}-\\d{4}");
boolean valid(String s) { return SKU.matcher(s).matches(); }
```

`String.split` with a single literal non-regex-meta character has a fast path; anything else compiles a pattern per call.

## Lookups

```java
// Bad: O(n*m)
orders.stream().filter(o -> blockedIds.contains(o.customerId())).toList();   // blockedIds is a List
// Good: O(n+m)
Set<CustomerId> blocked = Set.copyOf(blockedIds);
orders.stream().filter(o -> blocked.contains(o.customerId())).toList();
```

Group once instead of filtering repeatedly: `Map<CustomerId, List<Order>> byCustomer = orders.stream().collect(Collectors.groupingBy(Order::customerId));`

## Boxing

```java
// Bad: allocates a Long per iteration
Long total = 0L;
for (var line : lines) total += line.amountCents();
// Good
long total = lines.stream().mapToLong(Line::amountCents).sum();
```

Watch `Map<String, Integer>` counters in hot loops: `merge(key, 1, Integer::sum)` still boxes; use a `LongAdder` value or a primitive collection if measured to matter.

## Pagination and bounded reads

Never load an unbounded table or remote collection into memory. Keyset pagination scales; `OFFSET` degrades with depth.

```sql
-- first page
SELECT id, name, created_at FROM customer ORDER BY created_at, id LIMIT :pageSize;
-- next page: continue after the last row seen (keyset / seek method)
SELECT id, name, created_at FROM customer
WHERE (created_at, id) > (:lastCreatedAt, :lastId)
ORDER BY created_at, id LIMIT :pageSize;
```

```java
public record Page<T>(List<T> items, Optional<String> nextCursor) {
    public Page { items = List.copyOf(items); Objects.requireNonNull(nextCursor, "nextCursor"); }
}
```

API endpoints that list resources take a page size with an enforced maximum (see `api-design`). Batch jobs stream or page; they never `SELECT *` the whole table.

## Exceptions

- Exceptions are expensive (stack trace capture) and obscure intent; do not use them for expected outcomes in loops (e.g. parse-or-skip thousands of values: pre-validate or return `Optional`).
- Never swallow an exception to "keep going" silently: at least count and log once per batch.

## Collections sizing

```java
var byId = HashMap.<CustomerId, Customer>newHashMap(customers.size());   // sized for n entries without rehash
var result = new ArrayList<Line>(lines.size());
```

Only matters for large collections on hot paths.

## Streams and parallelism

- Streams are fine for clarity; in a measured tight loop a plain `for` may be faster.
- `parallel()` only for large CPU-bound workloads with no shared state and no blocking I/O, after measuring. It uses the common pool.
- Never mutate external collections from `forEach` in a parallel stream; collect instead.

## Logging cost

```java
log.debug("order {} lines={}", order.id(), order.lines().size());       // cheap args: fine
if (log.isDebugEnabled()) log.debug("payload {}", toJson(order));       // expensive arg: guard
```

## When not to optimise

- Not on a hot path (startup, config, admin endpoints, one-off scripts).
- No measured problem.
- The change hurts readability for a gain nobody needs.
- Small collections (hundreds of items are processed in microseconds).

## Review checklist

- [ ] No unbounded query, queue, cache or in-memory list of remote data.
- [ ] No regex compilation or string `+=` in loops.
- [ ] No database or remote call per item in a loop.
- [ ] Membership tests use `Set`/`Map`.
- [ ] No parallel stream with side effects.
- [ ] Hot-path boxing, stream-in-loop and capacity changes are backed by a measurement.
- [ ] Blocking I/O fan-out uses virtual threads, bounded by a `Semaphore` where the target is limited.

## Finding candidates

```bash
grep -rn "\.matches(\|\.replaceAll(\|\.split(" --include=*.java src/main
grep -rn "+= *\"" --include=*.java src/main
grep -rn "\.parallel()\|parallelStream()" --include=*.java src/main
grep -rni "select \*\|findAll()" --include=*.java src/main
```
