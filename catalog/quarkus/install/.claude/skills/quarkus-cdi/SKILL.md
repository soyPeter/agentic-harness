---
name: quarkus-cdi
description: Dependency injection with Quarkus ArC (CDI Lite) - verified ArC bean-discovery facts (@Named is not bean-defining), scopes, constructor injection, producers, qualifiers, and layer placement when the ADR adopts hexagonal layers or named use cases. Use before writing or changing use cases, adapters, producers or any injected bean.
applies-to: quarkus 3.x, java>=21
last-verified: 2026-10-05
sources: agentic-backbone skills/quarkus/java-cdi (corrected); plan-marshall pm-dev-java java-cdi templates; Quarkus CDI reference guide (quarkus.io/guides/cdi-reference) and ArC/Quarkus REST source, checked 2026-10-05; layer and use-case rules made conditional on the quarkus pack options
---

# Quarkus CDI (ArC)

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill. ArC resolves beans at
build time: wiring errors (unsatisfied, ambiguous) fail the build, not the request. Read the build error.

## Layer placement (if the architecture ADR uses option `hexagonal-layers`)

Without that option, place annotations as the architecture ADR says; the ArC facts below still hold. With it:

| Layer | Allowed | Forbidden |
|---|---|---|
| `domain/` | Plain Java, records, interfaces (ports). No DI at all. | Any `jakarta.inject`, `jakarta.enterprise`, `io.quarkus`, `org.jboss`, `io.smallrye`, data-access library (e.g. `org.jdbi`) import; `lombok` too under `no-lombok` |
| `app/` (use cases) | constructor injection of domain ports; with option `named-use-cases`: `jakarta.inject.Named`, `jakarta.inject.Inject` | imports of `infra`; keep out `io.quarkus.*`, JAX-RS and the data-access library (they belong in adapters); with `named-use-cases` also scope annotations (`@ApplicationScoped`, `@RequestScoped`, `@Singleton`...) and `@Produces` |
| `infra/` adapters | `@ApplicationScoped` (default), `@Singleton`, `@Produces` producer classes, qualifiers, interceptors | Business rules; returning infrastructure types (row records, connections/handles) through ports |
| REST resources (`infra/.../rest`) | `@Path` class, constructor injection of use cases | Field injection of beans, business logic, direct data access |

REST resources: `@Path` is a bean-defining annotation in Quarkus REST with default scope `@Singleton`
(one instance for all requests). A resource that uses field injection of REST parameters
(`@RestQuery`/`@QueryParam` on fields) is made `@RequestScoped` automatically; any other explicit scope then fails the build.
Keep resources stateless: no mutable fields.

## `@Named` beans: verified ArC behaviour

These facts hold in any Quarkus project; the use-case rules after them apply with option `named-use-cases`.

- `@Named` is a qualifier, NOT a bean-defining annotation in ArC. A class annotated only with `@Named`
  (no scope) is not discovered. Injecting it fails the build with an unsatisfied dependency.
  Only the `quarkus-spring-di` extension treats `@Named` alone as a bean, as an implicit `@Singleton`.
  Do not add that extension to get this behaviour.
- A bean whose only qualifier is `@Named` also gets `@Default`, so `@Named` does not disambiguate.
  Use a custom qualifier or `@io.smallrye.common.annotation.Identifier` (in infra under `hexagonal-layers`).
- With option `named-use-cases`, a `@Named` use case must still become a bean in some other way. Use whatever the ADR chose:
  1. Default: a producer in infrastructure creates the use case, so `app/` keeps JSR-330 annotations only:
     ```java
     @ApplicationScoped
     public class CustomerUseCaseConfig {                     // infra/config
         @Produces @ApplicationScoped
         CreateCustomerUseCase createCustomer(CustomerRepository repo, DomainEventPublisher events) {
             return new CreateCustomerUseCase(repo, events);
         }
     }
     ```
  2. `@Named @jakarta.inject.Singleton` on the use case. Both annotations are JSR-330, and ArC treats `@Singleton` as
     bean-defining in its default (non-strict) mode. Use this only if the ADR allows it, because
     the `named-use-cases` guardrail warns on scope annotations, `@Singleton` included, in the application layer.
- Without `named-use-cases`, a use case can simply carry a bean-defining scope (e.g. `@ApplicationScoped`) if the ADR allows
  framework annotations there.
- To check: the build (Gradle `./gradlew quarkusBuild` or `test`; Maven `./mvnw package` or `test`) fails with
  `UnsatisfiedResolutionException` / "Unsatisfied dependency" if a use case is not a bean.

## Injection rules

- Prefer constructor injection, and keep the injected fields `private final`. ArC does not need `@Inject` when there is exactly one
  constructor. Put `@Inject` on the injection constructor when there are several.
- Avoid field or setter injection in `main` code. Tests use `@Inject` fields in `@QuarkusTest` classes.
- Avoid `private` injection points, observers and producers. ArC then needs reflection. Use package-private if
  a field is unavoidable.
- Inject interfaces (ports), not adapter classes. Each port has exactly one enabled bean, otherwise the build fails
  with an ambiguity error.
- Do not use `@Inject` in records or domain types.

## Scopes (ArC semantics)

| Scope | Proxy | Created | Use for |
|---|---|---|---|
| `@ApplicationScoped` | client proxy | lazily, on first method call | Default for infra adapters and producers. Mockable with `@InjectMock` |
| `@Singleton` | none (direct ref) | lazily, when first injected | Slightly cheaper. Not mockable with `@InjectMock` unless `@MockitoConfig(convertScopes = true)` |
| `@RequestScoped` | client proxy | per request, on first call | Request-bound state (tenant, correlation data) |
| `@Dependent` | none | per injection point, shares the owner's lifecycle | Small helpers. Default for producer-declaring classes without a scope |

- Both `@ApplicationScoped` and `@Singleton` are LAZY. For eager initialization, use `@io.quarkus.runtime.Startup`
  on the bean or an `void onStart(@Observes StartupEvent ev)` method.
- `@SessionScoped` is not supported with Quarkus REST. Do not use it.
- Normal-scoped classes must be proxyable: non-final, with no non-private final methods. ArC
  transforms them by default (`quarkus.arc.transform-unproxyable-classes=true`), but do not rely on it.

### Scope mixing (corrected rule)

- Injecting a normal-scoped bean (`@RequestScoped`, `@ApplicationScoped`) into a longer-lived bean is SAFE.
  The holder gets a client proxy that resolves the current contextual instance on each call.
  `JsonWebToken` and `SecurityIdentity` are injected this way.
- The real hazard is capturing state without a proxy:
  - injecting a `@Dependent` or `@Singleton` bean that holds per-request data into an `@ApplicationScoped` bean;
  - copying a value out of a request-scoped proxy into a field (`this.tenant = ctx.tenant()`) in a constructor;
  - mutable fields in `@Singleton`/`@ApplicationScoped` beans. They are shared across threads, so make them immutable, or use
    concurrent types, or `@io.quarkus.arc.Lock`.
- Use `Instance<T>` only for optional, multiple or lazily resolved dependencies. Do not use it to "fix" scope mixing.

## Producers

- `@Produces` methods live in config classes (`@ApplicationScoped` or no-scope; in `infra/` under `hexagonal-layers`). They
  give the produced bean an explicit scope.
- Never return `null` (that fails with `IllegalProductException` for normal scopes). Return a Null Object instead.
- Pair a producer with `@Disposes` when the product holds resources (pools, clients) that are not closed elsewhere.
- Third-party types (the data-access library's entry point such as `Jdbi`, `ObjectMapper` customizers, clients) come from
  producers, never from `new` in adapters.
- Several beans of one type need a custom `@Qualifier`. Example (JDBI, if the architecture ADR separates command and query
  datasources):
  ```java
  @Qualifier @Retention(RUNTIME) @Target({METHOD, FIELD, PARAMETER, TYPE})
  public @interface QueryDb {}
  // producer:  @Produces @ApplicationScoped @QueryDb Jdbi queryJdbi(@DataSource("query") AgroalDataSource ds)
  // consumer:  public CustomerQueryAdapter(@QueryDb Jdbi jdbi)
  ```
- Never name a qualifier after `jakarta.annotation.Priority`, `Named`, `Default` or `Any`. A clash silently changes meaning.

## Quarkus-specific switches

- Unused beans are removed at build time. Beans reached only through `Instance<T>`/`Arc.container()` lookup, or that are named with
  `@Named`, survive. Otherwise use `@io.quarkus.arc.Unremovable`.
- Defaults and overrides: `@io.quarkus.arc.DefaultBean` (overridable default), `@IfBuildProfile("dev")`
  (build-time only), `@LookupIfProperty` (runtime config), `@io.quarkus.arc.All List<T>` (all beans of a type).
- Prefer `@ConfigMapping` interfaces injected by constructor over `@ConfigProperty` fields (quarkus skill).

## Checklist before finishing

- [ ] `hexagonal-layers`: no DI annotation in `domain/`, no `io.quarkus` in `app/`. `named-use-cases`: no CDI scope in `app/`.
- [ ] Every injected class is a bean through a mechanism the ADR allows (producer, scope, `@Singleton`), and the build passes.
- [ ] Constructor injection, final fields, no `private` injection points.
- [ ] No mutable shared state in `@ApplicationScoped`/`@Singleton`/resource classes.
- [ ] Beans you mock with `@InjectMock` are normal-scoped.
- [ ] Ambiguity is resolved with custom qualifiers, not `@Named`.

Read `advanced.md` when you write events/observers, interceptors, programmatic lookup (`Instance<T>`),
decorators, alternatives or startup logic.

## Linked skills

- quarkus: config, REST resources, security, testing (`@QuarkusTest`, `@InjectMock`).
- jdbi (if adopted): `Jdbi` producers and persistence adapters.
- java: language rules. java-test (if adopted): unit tests of use cases without CDI.
- architecture: layer rules and dependency direction.
- code-quality, module-testing, security.
