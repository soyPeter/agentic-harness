# Java concurrency (Java 25)

Guiding rule: the best concurrent code shares nothing mutable. Prefer immutable records, thread confinement and passing values between tasks; reach for locks only when shared mutable state is unavoidable.

## Choosing the mechanism

| Need | Use | Notes |
|---|---|---|
| Many blocking I/O tasks | `Executors.newVirtualThreadPerTaskExecutor()` | never pool virtual threads |
| CPU-bound parallel work | bounded platform pool (`newFixedThreadPool(cores)`) or parallel stream | virtual threads give no gain |
| Simple mutual exclusion | `synchronized` | fine with virtual threads since JDK 24 (JEP 491) |
| tryLock, timeout, interruptible lock, several conditions | `ReentrantLock` (+ `Condition`) | `unlock()` in `finally` |
| Read-mostly, rare writes | `ReadWriteLock`, or `StampedLock` optimistic read | `StampedLock` is not reentrant |
| Single counter/flag/reference | `AtomicInteger`, `AtomicLong`, `AtomicReference` | lock-free |
| Hot counter under contention | `LongAdder` | read with `sum()` |
| Per-request context | `ScopedValue` (final in 25) | instead of `ThreadLocal` |
| Limit concurrent access to a resource | `Semaphore` | e.g. 20 concurrent calls to a rate-limited API |
| Async pipeline with callbacks | `CompletableFuture` with explicit executor | see below |

## Visibility and atomicity

```java
// Bad: check-then-act race, two threads both see "absent"
if (!cache.containsKey(key)) cache.put(key, load(key));
// Good: atomic
cache.computeIfAbsent(key, this::load);

// Bad: may exceed MAX under contention
if (counter.get() < MAX) counter.incrementAndGet();
// Good: CAS loop; the function may run more than once, keep it pure and cheap
counter.getAndUpdate(c -> c < MAX ? c + 1 : c);
```

- A field written by one thread and read by another needs `volatile`, a lock, an atomic, or safe publication (final field set in the constructor).
- A `while (!stopped)` loop on a non-volatile field may never terminate.
- `long`/`double` writes are not guaranteed atomic without `volatile`.
- `count++` on a shared field is never atomic, even when `volatile`.

## Lazy initialisation

```java
// Preferred: holder idiom, lazy and thread-safe through class initialisation
private static final class Holder { static final ExpensiveParser INSTANCE = new ExpensiveParser(); }
static ExpensiveParser parser() { return Holder.INSTANCE; }

// Keyed lazy values
private final ConcurrentHashMap<Locale, Formatter> formatters = new ConcurrentHashMap<>();
Formatter formatter(Locale l) { return formatters.computeIfAbsent(l, Formatter::create); }
```

Double-checked locking with a `volatile` field is correct since Java 5 but verbose; use it only for per-instance lazy fields where the above do not fit. Without `volatile` it is broken. Do not lazily create expensive objects inside `AtomicReference.updateAndGet`/`accumulateAndGet`: the function can be retried. `StableValue` (JEP 502) is preview in 25: ADR required.

## Locks

```java
private final ReentrantLock lock = new ReentrantLock();
void update() {
    lock.lock();
    try { /* critical section */ } finally { lock.unlock(); }
}
```

- Never call unknown or external code (callbacks, listeners, remote calls) while holding a lock: deadlock and latency risk.
- Acquire several locks in a consistent global order (e.g. by id) to avoid deadlock:

```java
void transfer(Account from, Account to, BigDecimal amount) {
    Account first = from.id().compareTo(to.id()) < 0 ? from : to;
    Account second = first == from ? to : from;
    synchronized (first) { synchronized (second) { /* move money */ } }
}
```

- Prefer `tryLock(timeout, unit)` where a stuck lock must not hang a request.
- Synchronize on a private final lock object, not on `this` or a public/interned object (strings, boxed values).

## Executors and virtual threads

```java
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    var futures = ids.stream().map(id -> executor.submit(() -> client.fetch(id))).toList();
    for (var f : futures) results.add(f.get(5, TimeUnit.SECONDS));
}   // close() waits for submitted tasks
```

- Every `ExecutorService` is closed (try-with-resources, or `shutdown()` + `awaitTermination` in a lifecycle hook). Leaked executors keep the JVM alive.
- Platform pools: bounded queue, named threads (`Thread.ofPlatform().name("import-", 0).factory()`), explicit rejection policy.
- Virtual threads: one per task; bound scarce resources with a `Semaphore`; avoid `ThreadLocal` caches of heavy objects (one copy per thread); diagnose remaining pinning (native frames) with JFR `jdk.VirtualThreadPinned`.
- Structured concurrency (JEP 505) is preview in 25 - ADR required; the old `ShutdownOnFailure`/`ShutdownOnSuccess` API is gone.

## Interruption

```java
try { queue.put(item); }
catch (InterruptedException e) {
    Thread.currentThread().interrupt();          // restore the flag
    throw new IllegalStateException("interrupted while enqueuing " + item.id(), e);
}
```

Never swallow `InterruptedException`; never loop on `Thread.sleep` to wait for a condition (use a latch, future or queue).

## CompletableFuture

```java
CompletableFuture
    .supplyAsync(() -> inventory.reserve(order), ioExecutor)        // explicit executor for blocking I/O
    .orTimeout(5, TimeUnit.SECONDS)                                  // or completeOnTimeout(fallback, ...)
    .thenCombine(pricingFuture, Quote::new)
    .exceptionally(ex -> Quote.unavailable(order.id()));            // handle or propagate, never drop
```

- Default async methods run on `ForkJoinPool.commonPool()`: fine for short CPU work, wrong for blocking I/O. Pass an executor (virtual-thread executor for I/O).
- A future nobody joins and that has no `exceptionally`/`handle`/`whenComplete` loses its exception silently.
- `join()` wraps in `CompletionException`, `get()` in `ExecutionException`; unwrap the cause before translating.
- `allOf(...)` returns `CompletableFuture<Void>`; read results from the individual futures afterwards.
- Do not block (`join()`) inside a `thenApply` stage running on the common pool.

## Concurrent collections

| Need | Use | Avoid |
|---|---|---|
| Shared map | `ConcurrentHashMap` | `HashMap`, `Collections.synchronizedMap` |
| Shared set | `ConcurrentHashMap.newKeySet()` | `synchronizedSet` |
| Read-heavy list, rare writes | `CopyOnWriteArrayList` | `synchronizedList` |
| Producer/consumer | bounded `ArrayBlockingQueue`/`LinkedBlockingQueue(capacity)` | `wait`/`notify`, unbounded queues |
| Sorted concurrent map | `ConcurrentSkipListMap` | synchronized `TreeMap` |

`ConcurrentHashMap` pitfalls: compound get-then-put is not atomic (use `compute*`/`merge`); the function passed to `compute`/`computeIfAbsent` must be short and must not modify the same map (can deadlock or throw `IllegalStateException`); it does not accept `null` keys or values.

## Review checklist

High (likely bugs):
- Check-then-act or read-modify-write on shared state without atomicity.
- Shared mutable field without `volatile`/lock/atomic; busy-wait on a non-volatile flag.
- Lock held while calling external code; inconsistent lock ordering.
- `compute*` function touching the same map; expensive or side-effecting function in `updateAndGet`.
- Swallowed `InterruptedException`; `CompletableFuture` exceptions never handled.
- Mutable internal collection exposed from a shared object.

Medium (potential issues):
- Executor not closed; unnamed threads; unbounded queue or pool.
- Blocking I/O on the common pool; pooled virtual threads; `ThreadLocal` heavy caches with virtual threads.
- `unlock()` not in `finally`; synchronizing on `this` or a public object.
- No timeout on remote calls in futures.
- Preview concurrency APIs (structured concurrency, stable values) without an ADR.

Documentation:
- Every shared class states its thread-safety; every `volatile` and lock says what it guards; nested lock order is documented.

## Finding candidates

```bash
grep -rn "synchronized\|volatile\|ReentrantLock" --include=*.java src/main
grep -rn "ThreadLocal\|newFixedThreadPool\|newCachedThreadPool\|new Thread(" --include=*.java src/main
grep -rn "supplyAsync\|runAsync" --include=*.java src/main      # check executor + error handling
```
