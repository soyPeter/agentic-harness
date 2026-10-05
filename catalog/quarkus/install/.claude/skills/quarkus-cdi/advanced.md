# Quarkus CDI - advanced features

Read this when you write events, interceptors, programmatic lookup, decorators, alternatives or startup code.
With option `hexagonal-layers`, everything here belongs in `infra/` (or a shared infrastructure library); `app/` and `domain/`
never import it.

## Events and observers

- Event payloads are immutable records. A domain event that crosses modules is a domain record. The CDI
  `Event<T>` that fires it is an infra concern.
- In hexagonal code, a use case calls a domain port (`DomainEventPublisher`). The infra adapter implements
  the port and may fire a CDI event for in-process listeners. Do not make reliable cross-service delivery depend on CDI
  events; use what the ADR chose (for example a transactional outbox written in the same transaction).

```java
@ApplicationScoped
class CdiDomainEventPublisher implements DomainEventPublisher {        // infra
    private final Event<CustomerCreated> created;
    CdiDomainEventPublisher(Event<CustomerCreated> created) { this.created = created; }
    @Override public void publish(CustomerCreated e) { created.fire(e); }
}

@ApplicationScoped
class AuditListener {
    void onCreated(@Observes CustomerCreated e) { Log.infof("customer %s created", e.id()); }
}
```

- `@Observes` is synchronous: it runs in the caller's thread and transaction, and an exception propagates to the caller.
- `@ObservesAsync` with `fireAsync()` runs on a worker pool. It has no caller transaction and no request context.
  Exceptions are delivered to the returned `CompletionStage`, so handle them.
- Order synchronous observers with `@Observes @jakarta.annotation.Priority(n)` on the parameter (lower runs first).
- `jakarta.enterprise.event.TransactionPhase.AFTER_SUCCESS` (`@Observes(during = AFTER_SUCCESS)`) only applies under a
  JTA transaction. With transactions managed by a non-JTA library (e.g. JDBI) it does not fire as you expect; use an
  explicit mechanism such as an outbox instead.
- Qualified events: define a custom qualifier and use it on both the `Event<T>` injection point and the observer.
  Never name it `Priority`, because it clashes with `jakarta.annotation.Priority`.

```java
@Qualifier @Retention(RUNTIME) @Target({FIELD, PARAMETER, METHOD, TYPE})
public @interface Severity { Level value(); enum Level { HIGH, LOW } }

AlertService(@Severity(Level.HIGH) Event<Alert> high) { this.high = high; }
void escalate(@Observes @Severity(Level.HIGH) Alert a) { ... }
```

## Interceptors

Use interceptors for cross-cutting infrastructure concerns such as idempotency, API logging and metrics. Do not put business rules in them.

```java
@InterceptorBinding @Retention(RUNTIME) @Target({TYPE, METHOD})
public @interface Idempotent {}

@Idempotent @Interceptor @jakarta.annotation.Priority(Interceptor.Priority.APPLICATION + 10)
class IdempotencyInterceptor {
    private final IdempotencyStore store;
    IdempotencyInterceptor(IdempotencyStore store) { this.store = store; }

    @AroundInvoke
    Object around(InvocationContext ctx) throws Exception {
        // look up key, short-circuit or proceed
        return ctx.proceed();
    }
}
```

- Every interceptor declares `@jakarta.annotation.Priority`. Without it the interceptor is not enabled.
  Lower values run first. `PLATFORM_BEFORE` (0) < `LIBRARY_BEFORE` (1000) < `APPLICATION` (2000) < `LIBRARY_AFTER`
  (3000) < `PLATFORM_AFTER` (4000).
- Interceptor bindings need no `@RegisterForReflection`. ArC generates the interception code at build time.
  Binding members marked `@Nonbinding` are read from the annotation at build time as well.
- Bindings only apply to the methods of beans that the container creates. They do not apply to `private` or `static` methods,
  to instances created with `new`, or to producer-returned objects (bind on the producer's class instead).
- ArC supports self-invocation interception (calling an intercepted method from the same bean triggers the
  interceptor). Standard CDI does not, so do not port that assumption to other containers.
- `@ServerExceptionMapper` methods do not run class-level interceptors unless they are annotated themselves.
- With `hexagonal-layers`: if a use case (`app/`) needs an interceptor, bind it on the infra producer or wrap the use case
  in an infra decorator or adapter. Never annotate `app/` classes with infra bindings.

## Programmatic lookup: `Instance<T>`

- Use it for optional beans (`isResolvable()`), for iterating all implementations (or use `@io.quarkus.arc.All List<T>`),
  for selecting by qualifier at runtime (`instance.select(new SeverityLiteral(HIGH))`), and for lazy resolution.
- Destroy `@Dependent` instances that you obtain from `Instance.get()` with `instance.destroy(obj)`, or use
  `Instance.Handle` in try-with-resources. Otherwise they leak.
- Beans reachable only through `Instance<T>` are kept by unused-bean removal. Beans reached through
  `Arc.container().instance(...)` are not, so annotate them with `@Unremovable`.
- Prefer `Instance<T>` to `jakarta.inject.Provider<T>`, because only `Instance` offers the CDI-aware API.

## Decorators

Use a decorator to add behaviour to one interface type, for example caching or metrics around a port:

```java
@Decorator @jakarta.annotation.Priority(10)
abstract class TimedCustomerRepository implements CustomerRepository {
    @Inject @Delegate CustomerRepository delegate;   // the one accepted field injection (ArC docs form)
    @Override public Optional<Customer> findById(CustomerId id) { /* time */ return delegate.findById(id); }
}
```

ArC supports decorators. Keep them with the adapters (`infra/` under `hexagonal-layers`). Prefer an explicit wrapper adapter when the decoration is not truly generic.

## Alternatives and overrides

- `@Alternative @jakarta.annotation.Priority(1)` enables an alternative globally. You can also list it in
  `quarkus.arc.selected-alternatives`.
- Build-profile beans: `@IfBuildProfile("test")` / `@UnlessBuildProfile("prod")`. These are resolved at build time, so
  runtime profile switches have no effect.
- `@DefaultBean` for library defaults that the application may replace.
- In tests: `@InjectMock` (normal-scoped beans), `@io.quarkus.test.Mock` stereotype beans in `src/test`, or
  a `QuarkusTestProfile` that enables alternatives. A profile restarts the application, so keep profiles few.

## Startup and shutdown

- Beans are lazy. For eager work, use `@io.quarkus.runtime.Startup` on the bean, or
  `void init(@Observes StartupEvent ev)`, or `@Startup` on a method. For cleanup, use
  `@Observes ShutdownEvent` or `@io.quarkus.runtime.Shutdown`.
- Keep startup work fast and idempotent. Do not do network calls that block readiness. Expose the dependency's state
  through a readiness health check instead.
- Migration tools may run at startup (Flyway: `quarkus.flyway.migrate-at-start=true`). Do not duplicate migration logic.
- Scheduled jobs (`@io.quarkus.scheduler.Scheduled`) register even without a bean-defining annotation.
  Annotate the class `@ApplicationScoped` anyway for clarity, and use `concurrentExecution = SKIP` for pollers
  (e.g. an outbox poller).

## Error reference

| Build/runtime error | Cause | Fix |
|---|---|---|
| Unsatisfied dependency / `UnsatisfiedResolutionException` | No bean: class has only `@Named`, no bean-defining annotation, or was removed as unused | Add a producer or scope, check removal rules, use `@Unremovable` |
| Ambiguous dependency | Two enabled beans for one type and qualifier set (often `@Named` plus `@Default`) | Custom qualifier, `@Alternative @Priority`, or `@DefaultBean` |
| `IllegalProductException` | Producer returned `null` | Null Object |
| `ContextNotActiveException` | Request-scoped bean used outside a request (scheduler, async observer, worker thread) | Pass data explicitly or use `@ActivateRequestContext` |
| Interceptor not invoked | No `@Priority`, private method, or object built with `new` | Fix as in the interceptor rules above |
